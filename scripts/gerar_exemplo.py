"""Gera docs/exemplo-relatorio.html a partir de dados sintéticos (semente fixa)."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path

from netlag.bufferbloat import evaluate
from netlag.diagnosis import diagnose
from netlag.report import render_html
from netlag.stats import Sample
from netlag.targets import PRESETS, Target, TargetResult

SAMPLES = 120
START = datetime(2026, 10, 16, 20, 0, tzinfo=UTC)
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "exemplo-relatorio.html"


def synthetic(
    rng: random.Random, base: float, noise: float, loss: float, spikes: float = 0.0
) -> list[Sample]:
    samples: list[Sample] = []
    for _ in range(SAMPLES):
        if rng.random() < loss:
            samples.append(None)
            continue
        value = base + abs(rng.gauss(0, noise))
        if rng.random() < spikes:
            value += rng.uniform(20, 90)
        samples.append(round(value, 2))
    return samples


def build_results() -> list[TargetResult]:
    rng = random.Random(2026)
    gateway = Target("gateway", "192.168.0.1", kind="gateway")
    series = [
        (gateway, "ping", synthetic(rng, 2.0, 1.5, 0.04, spikes=0.08)),
        (PRESETS["cloudflare"], "ping", synthetic(rng, 12.0, 1.2, 0.0)),
        (PRESETS["google"], "ping", synthetic(rng, 14.0, 1.5, 0.0)),
        (PRESETS["aws-sa-east-1"], "tcp", synthetic(rng, 22.0, 2.0, 0.0)),
        (PRESETS["aws-us-east-1"], "tcp", synthetic(rng, 118.0, 4.0, 0.0)),
    ]
    results = []
    for target, method, samples in series:
        result = TargetResult(target, method)  # type: ignore[arg-type]
        for index, sample in enumerate(samples):
            result.add(START.timestamp() + index, sample)
        results.append(result)
    return results


def main() -> None:
    rng = random.Random(7)
    results = build_results()
    idle = synthetic(rng, 12.0, 1.0, 0.0)[:30]
    loaded = synthetic(rng, 150.0, 25.0, 0.02)[:48]
    bufferbloat = evaluate(idle, loaded, bytes_downloaded=135_000_000, load_seconds=12)
    page = render_html(
        results,
        diagnose(results, bufferbloat),
        bufferbloat,
        generated_at=START,
        title="Exemplo de relatório netlag (dados fictícios)",
    )
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"Gravado em {OUTPUT} ({len(page) // 1024} KiB)")


if __name__ == "__main__":
    main()
