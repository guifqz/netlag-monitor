"""Sondas de latência (ICMP via `ping` do sistema e conexão TCP) e detecção do gateway."""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from typing import Protocol

from netlag.parsers import (
    parse_linux_gateway,
    parse_macos_gateway,
    parse_rtts,
    parse_windows_gateway,
)
from netlag.targets import Method, Target


class Probe(Protocol):
    def measure(self) -> float | None:
        """RTT em ms, ou None se não houve resposta dentro do timeout."""


def ping_command(host: str, timeout: float, platform: str = sys.platform) -> list[str]:
    """Linha de comando de um único ping, com o flag de timeout de cada sistema."""
    if platform.startswith("win"):
        return ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
    if platform == "darwin":
        return ["ping", "-c", "1", "-W", str(int(timeout * 1000)), host]
    return ["ping", "-c", "1", "-W", str(max(1, round(timeout))), host]


class PingProbe:
    def __init__(self, host: str, timeout: float = 1.0) -> None:
        self.host = host
        self.timeout = timeout

    def measure(self) -> float | None:
        try:
            proc = subprocess.run(
                ping_command(self.host, self.timeout),
                capture_output=True,
                timeout=self.timeout + 3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        rtts = parse_rtts(proc.stdout.decode("latin-1"))
        return rtts[0] if rtts else None


class TcpProbe:
    """Tempo de handshake TCP. Recusa de conexão (RST) também conta: o pacote foi e voltou."""

    def __init__(self, host: str, port: int, timeout: float = 1.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._address: tuple[int, tuple] | None = None

    def _resolve(self) -> tuple[int, tuple]:
        if self._address is None:
            family, _, _, _, sockaddr = socket.getaddrinfo(
                self.host, self.port, type=socket.SOCK_STREAM
            )[0]
            self._address = (family, sockaddr)
        return self._address

    def measure(self) -> float | None:
        try:
            family, sockaddr = self._resolve()
        except OSError:
            return None
        start = time.perf_counter()
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(sockaddr)
        except ConnectionRefusedError:
            pass
        except OSError:
            return None
        return (time.perf_counter() - start) * 1000


def ping_available() -> bool:
    return shutil.which("ping") is not None


def resolve_method(target: Target, requested: str) -> Method:
    """Método efetivo: `auto` respeita o preferido do alvo e cai em TCP sem `ping`."""
    if requested in ("ping", "tcp"):
        return requested  # type: ignore[return-value]
    if target.method == "ping" and not ping_available():
        return "tcp"
    return target.method


def make_probe(target: Target, method: Method, timeout: float) -> Probe:
    if method == "tcp":
        return TcpProbe(target.host, target.port, timeout)
    return PingProbe(target.host, timeout)


def _run(command: list[str]) -> str:
    try:
        proc = subprocess.run(command, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.decode("latin-1")


def detect_gateway(platform: str = sys.platform) -> str | None:
    """IP do gateway padrão, ou None se não for possível descobrir."""
    if platform.startswith("win"):
        return parse_windows_gateway(_run(["route", "print", "-4", "0.0.0.0"]))
    if platform == "darwin":
        return parse_macos_gateway(_run(["route", "-n", "get", "default"]))
    return parse_linux_gateway(_run(["ip", "route", "show", "default"]))
