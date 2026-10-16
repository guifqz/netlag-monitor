"""Parsers da saída do `ping` e da tabela de rotas, tolerantes a idioma e sistema."""

from __future__ import annotations

import re

# "time=12.3 ms" (Linux/macOS/Windows en), "tempo=12ms" (pt), "tiempo=" (es),
# "Zeit=" (de), "temps=" (fr). Windows usa "<" quando o RTT fica abaixo de 1 ms.
_RTT = re.compile(
    r"(?:time|tempo|tiempo|zeit|temps)\s*(?P<op>[=<])\s*(?P<value>\d+(?:[.,]\d+)?)\s*ms",
    re.IGNORECASE,
)
SUB_MS_RTT = 0.5

_IPV4 = r"\d{1,3}(?:\.\d{1,3}){3}"
_WINDOWS_DEFAULT_ROUTE = re.compile(
    rf"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(?P<gateway>{_IPV4})\s+{_IPV4}\s+(?P<metric>\d+)\s*$",
    re.MULTILINE,
)
_LINUX_DEFAULT_ROUTE = re.compile(rf"^default\s+via\s+(?P<gateway>{_IPV4})", re.MULTILINE)
_MACOS_GATEWAY = re.compile(rf"^\s*gateway:\s*(?P<gateway>{_IPV4})\s*$", re.MULTILINE)


def parse_rtts(output: str) -> list[float]:
    """Extrai todos os RTTs (ms) das linhas de resposta do ping."""
    rtts: list[float] = []
    for match in _RTT.finditer(output):
        if match["op"] == "<":
            rtts.append(SUB_MS_RTT)
        else:
            rtts.append(float(match["value"].replace(",", ".")))
    return rtts


def parse_windows_gateway(route_print: str) -> str | None:
    """Gateway padrão de menor métrica na saída de `route print -4`."""
    routes = [
        (int(m["metric"]), m["gateway"]) for m in _WINDOWS_DEFAULT_ROUTE.finditer(route_print)
    ]
    return min(routes)[1] if routes else None


def parse_linux_gateway(ip_route: str) -> str | None:
    """Primeira rota default na saída de `ip route show default`."""
    match = _LINUX_DEFAULT_ROUTE.search(ip_route)
    return match["gateway"] if match else None


def parse_macos_gateway(route_get: str) -> str | None:
    """Gateway na saída de `route -n get default`."""
    match = _MACOS_GATEWAY.search(route_get)
    return match["gateway"] if match else None
