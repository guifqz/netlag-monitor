"""Laço de medição: uma rodada por intervalo, todos os alvos em paralelo."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

from netlag.probes import Probe
from netlag.stats import Sample
from netlag.targets import TargetResult


def run_monitor(
    results: Sequence[TargetResult],
    probes: Sequence[Probe],
    count: int,
    interval: float,
    on_round: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Mede `count` rodadas (0 = até interromper), acumulando em `results`."""
    if len(results) != len(probes):
        raise ValueError("results e probes precisam ter o mesmo tamanho")
    if not results:
        return
    rounds = 0
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        while count == 0 or rounds < count:
            started = time.monotonic()
            samples: list[Sample] = list(pool.map(lambda p: p.measure(), probes))
            now = time.time()
            for result, sample in zip(results, samples, strict=True):
                result.add(now, sample)
            rounds += 1
            if on_round is not None:
                on_round()
            if count == 0 or rounds < count:
                sleep(max(0.0, interval - (time.monotonic() - started)))
