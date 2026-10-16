"""Teste de bufferbloat: latência em repouso vs. latência com a linha saturada por downloads."""

from __future__ import annotations

import threading
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import TracebackType

from netlag.probes import Probe
from netlag.stats import Sample, Stats, summarize

DEFAULT_LOAD_URL = "https://proof.ovh.net/files/100Mb.dat"
USER_AGENT = "netlag-monitor"

# Aumento da latência média sob carga (ms) -> nota. Acima do ultimo limite: F.
GRADE_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (15, "A"),
    (30, "B"),
    (60, "C"),
    (120, "D"),
    (200, "E"),
)


class BufferbloatError(RuntimeError):
    """O teste não produziu dados suficientes para uma nota confiável."""


def grade_bufferbloat(delta_ms: float) -> str:
    for limit, letter in GRADE_THRESHOLDS:
        if delta_ms < limit:
            return letter
    return "F"


@dataclass(frozen=True, slots=True)
class BufferbloatResult:
    idle: Stats
    loaded: Stats
    delta_ms: float
    grade: str
    mbps: float


def evaluate(
    idle_samples: Sequence[Sample],
    loaded_samples: Sequence[Sample],
    bytes_downloaded: int,
    load_seconds: float,
) -> BufferbloatResult:
    idle = summarize(idle_samples)
    loaded = summarize(loaded_samples)
    if idle.avg is None:
        raise BufferbloatError("sem resposta do alvo durante a medição em repouso")
    if bytes_downloaded == 0:
        raise BufferbloatError("nenhum dado foi baixado; verifique a URL de carga e a conexão")
    if loaded.avg is None:
        raise BufferbloatError("sem resposta do alvo sob carga (linha totalmente saturada)")
    delta = loaded.avg - idle.avg
    mbps = bytes_downloaded * 8 / load_seconds / 1_000_000 if load_seconds > 0 else 0.0
    return BufferbloatResult(idle, loaded, delta, grade_bufferbloat(delta), mbps)


class LoadGenerator:
    """Baixa `url` em loop, em varias threads, até sair do contexto."""

    def __init__(self, url: str, threads: int = 4, timeout: float = 10.0) -> None:
        self.url = url
        self.timeout = timeout
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._bytes = 0
        self._threads = [
            threading.Thread(target=self._worker, name=f"netlag-load-{i}", daemon=True)
            for i in range(threads)
        ]

    @property
    def bytes_downloaded(self) -> int:
        with self._lock:
            return self._bytes

    def __enter__(self) -> LoadGenerator:
        for thread in self._threads:
            thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=self.timeout + 1)

    def _worker(self) -> None:
        request = urllib.request.Request(self.url, headers={"User-Agent": USER_AGENT})
        while not self._stop.is_set():
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    while not self._stop.is_set():
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        with self._lock:
                            self._bytes += len(chunk)
            except (OSError, ValueError):
                self._stop.wait(0.5)


def _collect(probe: Probe, seconds: float, interval: float) -> list[Sample]:
    samples: list[Sample] = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        started = time.monotonic()
        samples.append(probe.measure())
        time.sleep(max(0.0, interval - (time.monotonic() - started)))
    return samples


def run_bufferbloat(
    probe: Probe,
    url: str = DEFAULT_LOAD_URL,
    idle_seconds: float = 8.0,
    load_seconds: float = 12.0,
    interval: float = 0.25,
    threads: int = 4,
    ramp_seconds: float = 2.0,
    on_phase: Callable[[str], None] | None = None,
) -> BufferbloatResult:
    """Mede em repouso, depois sob carga (descartando o inicio, enquanto a carga sobe)."""

    def announce(phase: str) -> None:
        if on_phase is not None:
            on_phase(phase)

    announce("idle")
    idle = _collect(probe, idle_seconds, interval)
    announce("load")
    with LoadGenerator(url, threads=threads) as load:
        time.sleep(ramp_seconds)
        start_bytes = load.bytes_downloaded
        started = time.monotonic()
        loaded = _collect(probe, load_seconds, interval)
        elapsed = time.monotonic() - started
        transferred = load.bytes_downloaded - start_bytes
    return evaluate(idle, loaded, transferred, elapsed)
