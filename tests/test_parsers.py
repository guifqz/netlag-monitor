import pytest

from netlag.parsers import (
    SUB_MS_RTT,
    parse_linux_gateway,
    parse_macos_gateway,
    parse_rtts,
    parse_windows_gateway,
)

WINDOWS_PT = """
Disparando 1.1.1.1 com 32 bytes de dados:
Resposta de 1.1.1.1: bytes=32 tempo=12ms TTL=57
Resposta de 1.1.1.1: bytes=32 tempo<1ms TTL=57

Estatísticas do Ping para 1.1.1.1:
    Pacotes: Enviados = 2, Recebidos = 2, Perdidos = 0 (0% de perda),
Aproximar um número de vezes em milissegundos:
    Mínimo = 0ms, Máximo = 12ms, Média = 6ms
"""

WINDOWS_PT_TIMEOUT = """
Disparando 10.255.255.1 com 32 bytes de dados:
Esgotado o tempo limite do pedido.

Estatísticas do Ping para 10.255.255.1:
    Pacotes: Enviados = 1, Recebidos = 0, Perdidos = 1 (100% de perda),
"""

WINDOWS_EN = """
Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=18ms TTL=116

Ping statistics for 8.8.8.8:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 18ms, Maximum = 18ms, Average = 18ms
"""

WINDOWS_EN_TIMEOUT = """
Pinging 10.255.255.1 with 32 bytes of data:
Request timed out.

Ping statistics for 10.255.255.1:
    Packets: Sent = 1, Received = 0, Lost = 1 (100% loss),
"""

WINDOWS_EN_UNREACHABLE = """
Pinging 192.168.0.99 with 32 bytes of data:
Reply from 192.168.0.4: Destination host unreachable.

Ping statistics for 192.168.0.99:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
"""

WINDOWS_ES = "Respuesta desde 8.8.8.8: bytes=32 tiempo=21ms TTL=116"
WINDOWS_DE = "Antwort von 8.8.8.8: Bytes=32 Zeit=19ms TTL=116"

LINUX = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=11.8 ms

--- 1.1.1.1 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 11.812/11.812/11.812/0.000 ms
"""

LINUX_PT = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes de 1.1.1.1: icmp_seq=1 ttl=57 tempo=11,8 ms

--- estatísticas de ping 1.1.1.1 ---
1 pacotes transmitidos, 1 recebidos, 0% packet loss, tempo 0ms
"""

LINUX_TIMEOUT = """PING 10.255.255.1 (10.255.255.1) 56(84) bytes of data.

--- 10.255.255.1 ping statistics ---
1 packets transmitted, 0 received, 100% packet loss, time 0ms
"""

MACOS = """PING 1.1.1.1 (1.1.1.1): 56 data bytes
64 bytes from 1.1.1.1: icmp_seq=0 ttl=57 time=14.623 ms

--- 1.1.1.1 ping statistics ---
1 packets transmitted, 1 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 14.623/14.623/14.623/nan ms
"""

MACOS_TIMEOUT = """PING 10.255.255.1 (10.255.255.1): 56 data bytes
Request timeout for icmp_seq 0

--- 10.255.255.1 ping statistics ---
1 packets transmitted, 0 packets received, 100.0% packet loss
"""


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (WINDOWS_PT, [12.0, SUB_MS_RTT]),
        (WINDOWS_EN, [18.0]),
        (WINDOWS_ES, [21.0]),
        (WINDOWS_DE, [19.0]),
        (LINUX, [11.8]),
        (LINUX_PT, [11.8]),
        (MACOS, [14.623]),
    ],
)
def test_parse_rtts_replies(output: str, expected: list[float]) -> None:
    assert parse_rtts(output) == pytest.approx(expected)


@pytest.mark.parametrize(
    "output",
    [
        WINDOWS_PT_TIMEOUT,
        WINDOWS_EN_TIMEOUT,
        WINDOWS_EN_UNREACHABLE,
        LINUX_TIMEOUT,
        MACOS_TIMEOUT,
        "",
        "ping: unknown host exemplo.invalido",
    ],
)
def test_parse_rtts_without_reply(output: str) -> None:
    assert parse_rtts(output) == []


WINDOWS_ROUTE = """
IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0     192.168.15.1     192.168.15.4     25
          0.0.0.0          0.0.0.0      10.0.0.1         10.0.0.50       600
===========================================================================
"""

MACOS_ROUTE = """   route to: default
destination: default
       mask: default
    gateway: 192.168.1.1
  interface: en0
"""


def test_windows_gateway_picks_lowest_metric() -> None:
    assert parse_windows_gateway(WINDOWS_ROUTE) == "192.168.15.1"


def test_windows_gateway_missing() -> None:
    assert parse_windows_gateway("Network Destination  Netmask  Gateway") is None


def test_linux_gateway() -> None:
    output = "default via 192.168.0.1 dev eth0 proto dhcp src 192.168.0.20 metric 100\n"
    assert parse_linux_gateway(output) == "192.168.0.1"
    assert parse_linux_gateway("") is None


def test_macos_gateway() -> None:
    assert parse_macos_gateway(MACOS_ROUTE) == "192.168.1.1"
    assert parse_macos_gateway("route: writing to routing socket: not in table") is None
