"""Heurísticas que transformam as metricas em dicas legíveis (pt-BR)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from netlag.bufferbloat import BufferbloatResult
from netlag.targets import TargetResult

Level = Literal["ok", "info", "warn", "crit"]

MIN_SAMPLES = 10
LOSS_WARN = 1.0
LOSS_CRIT = 5.0
GATEWAY_JITTER_WARN = 8.0
INTERNET_JITTER_WARN = 20.0
ROUTING_RATIO = 2.5
ROUTING_MIN_MS = 120.0


@dataclass(frozen=True, slots=True)
class Diagnosis:
    level: Level
    message: str


def _loss_level(loss: float) -> Level:
    return "crit" if loss >= LOSS_CRIT else "warn"


def _reliable(result: TargetResult) -> bool:
    return result.stats.sent >= MIN_SAMPLES and result.stats.received > 0


def diagnose(
    results: Sequence[TargetResult], bufferbloat: BufferbloatResult | None = None
) -> list[Diagnosis]:
    findings: list[Diagnosis] = []

    for result in results:
        stats = result.stats
        if stats.sent >= 3 and stats.received == 0:
            findings.append(
                Diagnosis(
                    "crit",
                    f"Sem resposta de {result.target.name} (100% de perda). O alvo pode "
                    "bloquear ICMP ou estar inacessível; tente --method tcp.",
                )
            )

    if results and all(r.stats.sent < MIN_SAMPLES for r in results):
        findings.append(
            Diagnosis(
                "info",
                f"Poucas amostras (menos de {MIN_SAMPLES} por alvo): aumente --count "
                "para um diagnóstico confiável.",
            )
        )

    gateway = next((r for r in results if r.target.kind == "gateway" and _reliable(r)), None)
    internet = [r for r in results if r.target.kind != "gateway" and _reliable(r)]
    findings += _loss_rules(gateway, internet)
    findings += _jitter_rules(gateway, internet)
    findings += _routing_rules(internet)
    if bufferbloat is not None:
        findings += _bufferbloat_rules(bufferbloat)

    healthy = not any(f.level in ("warn", "crit") for f in findings)
    if healthy and any(_reliable(r) for r in results):
        findings.append(
            Diagnosis("ok", "Nenhum problema evidente: latência, jitter e perda dentro do normal.")
        )
    return findings


def _loss_rules(gateway: TargetResult | None, internet: list[TargetResult]) -> list[Diagnosis]:
    worst_internet = max(internet, key=lambda r: r.stats.loss_pct, default=None)
    internet_loss = worst_internet.stats.loss_pct if worst_internet else 0.0
    gateway_loss = gateway.stats.loss_pct if gateway else 0.0

    if gateway and gateway_loss >= LOSS_WARN:
        if internet_loss < LOSS_WARN:
            return [
                Diagnosis(
                    _loss_level(gateway_loss),
                    f"Perda de {gateway_loss:.1f}% só no gateway, sem perda na internet: "
                    "problema na rede local. Verifique sinal e interferência do Wi-Fi, "
                    "troque o cabo Ethernet ou teste outra porta do roteador.",
                )
            ]
        return [
            Diagnosis(
                _loss_level(max(gateway_loss, internet_loss)),
                f"Perda já no gateway ({gateway_loss:.1f}%) e também na internet "
                f"({internet_loss:.1f}%): resolva primeiro a rede local (Wi-Fi, cabo, "
                "roteador); a perda no caminho pode ser consequencia dela.",
            )
        ]
    if worst_internet and internet_loss >= LOSS_WARN:
        return [
            Diagnosis(
                _loss_level(internet_loss),
                f"Perda de {internet_loss:.1f}% para {worst_internet.target.name} com o "
                "gateway limpo: o problema está depois do roteador (provedor ou rota). "
                "Rode um MTR/traceroute e abra chamado com o provedor.",
            )
        ]
    return []


def _jitter_rules(gateway: TargetResult | None, internet: list[TargetResult]) -> list[Diagnosis]:
    if gateway and gateway.stats.jitter >= GATEWAY_JITTER_WARN:
        return [
            Diagnosis(
                "warn",
                f"Jitter alto até o gateway ({gateway.stats.jitter:.1f} ms): rede local "
                "instavel. Prefira cabo, mude o canal do Wi-Fi ou use a faixa de 5 GHz.",
            )
        ]
    noisy = [r for r in internet if r.stats.jitter >= INTERNET_JITTER_WARN]
    if noisy and (gateway is None or gateway.stats.jitter < GATEWAY_JITTER_WARN):
        worst = max(noisy, key=lambda r: r.stats.jitter)
        return [
            Diagnosis(
                "warn",
                f"Jitter alto para {worst.target.name} ({worst.stats.jitter:.1f} ms) com a "
                "rede local estavel: oscilação no provedor ou na rota. Se só ocorre em "
                "horário de pico, é congestionamento do provedor.",
            )
        ]
    return []


def _routing_rules(internet: list[TargetResult]) -> list[Diagnosis]:
    if len(internet) < 2:
        return []
    p50 = {r.target.name: r.stats.p50 or 0.0 for r in internet}
    best = min(p50.values())
    far = [
        name
        for name, value in p50.items()
        if value >= ROUTING_MIN_MS and value >= best * ROUTING_RATIO
    ]
    if not far:
        return []
    return [
        Diagnosis(
            "info",
            f"Latência alta só para {', '.join(far)} (mediana até "
            f"{max(p50[n] for n in far):.0f} ms "
            f"contra {best:.0f} ms no melhor alvo): provável distância ou roteamento ruim. "
            "Se for a região do seu jogo, escolha outra região ou teste uma VPN/rota alternativa.",
        )
    ]


def _bufferbloat_rules(result: BufferbloatResult) -> list[Diagnosis]:
    detail = (
        f"latência média subiu {result.delta_ms:.0f} ms sob carga "
        f"({result.idle.avg:.0f} -> {result.loaded.avg:.0f} ms; "
        f"jitter {result.idle.jitter:.1f} -> {result.loaded.jitter:.1f} ms)"
    )
    if result.grade in ("D", "E", "F"):
        return [
            Diagnosis(
                "crit" if result.grade == "F" else "warn",
                f"Bufferbloat nota {result.grade}: {detail}. Downloads e streams vão causar "
                "lag no jogo. Ative SQM (fq_codel/CAKE) no roteador ou limite a banda em "
                "~90% da velocidade contratada via QoS.",
            )
        ]
    if result.grade == "C":
        return [
            Diagnosis(
                "info",
                f"Bufferbloat moderado (nota C): {detail}. Vale ativar SQM/QoS se houver "
                "lag quando alguem usa a rede.",
            )
        ]
    return []
