"""Interface de linha de comando."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console
from rich.live import Live

from netlag import __version__
from netlag.bufferbloat import (
    DEFAULT_LOAD_URL,
    BufferbloatError,
    BufferbloatResult,
    run_bufferbloat,
)
from netlag.diagnosis import diagnose
from netlag.display import build_bufferbloat_table, build_table, format_diagnosis
from netlag.monitor import run_monitor
from netlag.probes import detect_gateway, make_probe, resolve_method
from netlag.report import write_csv, write_html
from netlag.targets import (
    DEFAULT_PRESETS,
    GATEWAY_NAME,
    PRESETS,
    Target,
    TargetResult,
    parse_target,
)

COMMANDS = ("run", "targets")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netlag",
        description="Diagnóstico de latência, jitter, perda de pacotes e bufferbloat.",
    )
    parser.add_argument("--version", action="version", version=f"netlag {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="{run,targets}")

    run = sub.add_parser("run", help="mede os alvos e gera o diagnóstico (padrão)")
    run.add_argument(
        "-t",
        "--targets",
        nargs="+",
        metavar="ALVO",
        help=f"presets, host ou host:porta (padrão: {' '.join(DEFAULT_PRESETS)})",
    )
    run.add_argument(
        "-c", "--count", type=int, default=30, help="rodadas de medição (0 = até Ctrl+C)"
    )
    run.add_argument("-i", "--interval", type=float, default=1.0, help="segundos entre rodadas")
    run.add_argument("--timeout", type=float, default=1.0, help="timeout por sonda, em segundos")
    run.add_argument(
        "-m",
        "--method",
        choices=("auto", "ping", "tcp"),
        default="auto",
        help="auto: ICMP onde fizer sentido, TCP nos endpoints AWS",
    )
    run.add_argument("--csv", type=Path, metavar="ARQUIVO", help="exporta as amostras em CSV")
    run.add_argument("--html", type=Path, metavar="ARQUIVO", help="gera o relatório HTML")
    run.add_argument("--no-live", action="store_true", help="não atualiza a tabela ao vivo")
    bloat = run.add_argument_group("bufferbloat")
    bloat.add_argument("--bufferbloat", action="store_true", help="roda o teste de bufferbloat")
    bloat.add_argument("--load-url", default=DEFAULT_LOAD_URL, help="URL baixada para gerar carga")
    bloat.add_argument("--load-threads", type=int, default=4, help="downloads simultaneos")
    bloat.add_argument("--idle-seconds", type=float, default=8.0, help="duração da fase em repouso")
    bloat.add_argument("--load-seconds", type=float, default=12.0, help="duração da fase sob carga")
    bloat.add_argument(
        "--bufferbloat-target",
        default="cloudflare",
        metavar="ALVO",
        help="alvo medido durante o teste (padrão: cloudflare)",
    )

    sub.add_parser("targets", help="lista os alvos pré-definidos")
    return parser


def resolve_targets(specs: Sequence[str] | None, gateway: str | None) -> list[Target]:
    """Converte nomes/hosts em alvos; `gateway` e resolvido pelo IP detectado."""
    targets: list[Target] = []
    for spec in specs or DEFAULT_PRESETS:
        if spec == GATEWAY_NAME:
            if gateway is None:
                raise ValueError("não foi possível detectar o gateway; passe o IP com --targets")
            targets.append(Target(GATEWAY_NAME, gateway, kind="gateway"))
        elif spec in PRESETS:
            targets.append(PRESETS[spec])
        else:
            targets.append(parse_target(spec))
    return targets


def _list_targets(console: Console) -> int:
    gateway = detect_gateway()
    console.print(f"{GATEWAY_NAME:<15} {gateway or 'não detectado'}  (gateway padrão, ICMP)")
    for name, target in PRESETS.items():
        console.print(f"{name:<15} {target.host}  ({target.description})")
    console.print("\nOutros hosts: --targets exemplo.com ou --targets exemplo.com:27015 (TCP)")
    return 0


def _run_bufferbloat(
    console: Console, args: argparse.Namespace, probe_spec: Target
) -> BufferbloatResult | None:
    method = resolve_method(probe_spec, args.method)
    probe = make_probe(probe_spec, method, args.timeout)
    phases = {
        "idle": f"Bufferbloat: medindo em repouso ({args.idle_seconds:.0f}s)...",
        "load": f"Bufferbloat: medindo sob carga ({args.load_seconds:.0f}s)...",
    }
    try:
        result = run_bufferbloat(
            probe,
            url=args.load_url,
            idle_seconds=args.idle_seconds,
            load_seconds=args.load_seconds,
            threads=args.load_threads,
            on_phase=lambda phase: console.print(f"[dim]{phases[phase]}[/dim]"),
        )
    except BufferbloatError as error:
        console.print(f"[yellow]Bufferbloat inconclusivo:[/yellow] {error}")
        return None
    console.print(build_bufferbloat_table(result))
    return result


def command_run(args: argparse.Namespace, console: Console) -> int:
    if args.count < 0 or args.interval <= 0 or args.timeout <= 0:
        console.print("[red]--count, --interval e --timeout precisam ser positivos[/red]")
        return 2
    needs_gateway = args.targets is None or GATEWAY_NAME in args.targets
    try:
        targets = resolve_targets(args.targets, detect_gateway() if needs_gateway else None)
        bloat_target = resolve_targets([args.bufferbloat_target], None)[0]
    except ValueError as error:
        console.print(f"[red]{error}[/red]")
        return 2

    methods = [resolve_method(t, args.method) for t in targets]
    results = [TargetResult(t, m) for t, m in zip(targets, methods, strict=True)]
    probes = [make_probe(t, m, args.timeout) for t, m in zip(targets, methods, strict=True)]

    interactive = console.is_terminal and not args.no_live
    try:
        if interactive:
            with Live(build_table(results), console=console, refresh_per_second=4) as live:
                run_monitor(
                    results,
                    probes,
                    args.count,
                    args.interval,
                    on_round=lambda: live.update(build_table(results)),
                )
        else:
            run_monitor(results, probes, args.count, args.interval)
            console.print(build_table(results))
    except KeyboardInterrupt:
        console.print("\n[dim]Interrompido; usando as amostras coletadas.[/dim]")
    if not any(r.samples for r in results):
        return 1

    bloat: BufferbloatResult | None = None
    if args.bufferbloat:
        try:
            bloat = _run_bufferbloat(console, args, bloat_target)
        except KeyboardInterrupt:
            console.print("\n[dim]Teste de bufferbloat interrompido.[/dim]")

    diagnoses = diagnose(results, bloat)
    console.print("\n[bold]Diagnóstico[/bold]")
    for item in diagnoses:
        console.print(format_diagnosis(item))

    if args.csv:
        write_csv(args.csv, results)
        console.print(f"CSV salvo em {args.csv}")
    if args.html:
        write_html(args.html, results, diagnoses, bloat)
        console.print(f"Relatório HTML salvo em {args.html}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if not args_list or (args_list[0] not in (*COMMANDS, "-h", "--help", "--version")):
        args_list.insert(0, "run")
    args = build_parser().parse_args(args_list)

    console = Console(highlight=False)
    if args.command == "targets":
        return _list_targets(console)
    return command_run(args, console)


if __name__ == "__main__":
    sys.exit(main())
