"""Estatísticas de latência: percentis, jitter e perda."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

Sample = float | None
"""Uma medição em milissegundos; None representa um pacote perdido."""


@dataclass(frozen=True, slots=True)
class Stats:
    sent: int
    received: int
    loss_pct: float
    min: float | None
    avg: float | None
    max: float | None
    p50: float | None
    p95: float | None
    p99: float | None
    jitter: float


def percentile(values: Sequence[float], q: float) -> float:
    """Percentil `q` (0-100) com interpolação linear entre vizinhos."""
    if not values:
        raise ValueError("percentil de uma sequencia vazia")
    if not 0 <= q <= 100:
        raise ValueError("q deve estar entre 0 e 100")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def jitter(values: Sequence[float]) -> float:
    """Média da diferença absoluta entre amostras consecutivas (ms)."""
    if len(values) < 2:
        return 0.0
    diffs = [abs(b - a) for a, b in pairwise(values)]
    return sum(diffs) / len(diffs)


def summarize(samples: Sequence[Sample]) -> Stats:
    """Resume uma série de amostras; as perdas entram só no cálculo de perda."""
    received = [s for s in samples if s is not None]
    sent = len(samples)
    loss = 100 * (sent - len(received)) / sent if sent else 0.0
    if not received:
        return Stats(sent, 0, loss, None, None, None, None, None, None, 0.0)
    return Stats(
        sent=sent,
        received=len(received),
        loss_pct=loss,
        min=min(received),
        avg=sum(received) / len(received),
        max=max(received),
        p50=percentile(received, 50),
        p95=percentile(received, 95),
        p99=percentile(received, 99),
        jitter=jitter(received),
    )
