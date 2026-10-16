"""Tabelas e painéis do terminal (rich)."""

from __future__ import annotations

from collections.abc import Sequence

from rich import box
from rich.table import Table
from rich.text import Text

from netlag.bufferbloat import BufferbloatResult
from netlag.diagnosis import Diagnosis, Level
from netlag.targets import TargetResult

_LEVEL_STYLE: dict[Level, tuple[str, str]] = {
    "ok": ("OK", "green"),
    "info": ("INFO", "cyan"),
    "warn": ("ATENÇÃO", "yellow"),
    "crit": ("CRÍTICO", "bold red"),
}


def _ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _loss_text(loss: float) -> Text:
    style = "red" if loss >= 5 else "yellow" if loss >= 1 else "green"
    return Text(f"{loss:.1f}%", style=style)


def build_table(results: Sequence[TargetResult], title: str = "netlag") -> Table:
    table = Table(title=title, title_justify="left", box=box.SIMPLE_HEAD, pad_edge=False)
    table.add_column("Alvo", no_wrap=True)
    table.add_column("Via")
    for name in ("Últ.", "Min", "Média", "p95", "Jitter"):
        table.add_column(name, justify="right", no_wrap=True)
    table.add_column("Perda", justify="right")
    table.add_column("N", justify="right")
    for result in results:
        stats = result.stats
        table.add_row(
            result.target.name,
            result.method,
            _ms(result.last),
            _ms(stats.min),
            _ms(stats.avg),
            _ms(stats.p95),
            f"{stats.jitter:.1f}",
            _loss_text(stats.loss_pct),
            str(stats.sent),
        )
    return table


def build_bufferbloat_table(result: BufferbloatResult) -> Table:
    table = Table(title="Bufferbloat", title_justify="left", box=box.SIMPLE_HEAD, pad_edge=False)
    for name in ("Fase", "Média (ms)", "p95 (ms)", "Jitter (ms)", "Perda"):
        table.add_column(name, justify="right" if name != "Fase" else "left")
    for label, stats in (("repouso", result.idle), ("sob carga", result.loaded)):
        table.add_row(
            label, _ms(stats.avg), _ms(stats.p95), f"{stats.jitter:.1f}", f"{stats.loss_pct:.1f}%"
        )
    table.caption = (
        f"Aumento de {result.delta_ms:.1f} ms com {result.mbps:.0f} Mbps de carga: "
        f"nota {result.grade}"
    )
    return table


def format_diagnosis(diagnosis: Diagnosis) -> Text:
    label, style = _LEVEL_STYLE[diagnosis.level]
    text = Text()
    text.append(f"[{label}] ", style=style)
    text.append(diagnosis.message)
    return text
