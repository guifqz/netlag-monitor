import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from netlag.bufferbloat import LoadGenerator
from netlag.cli import resolve_targets
from netlag.monitor import run_monitor
from netlag.probes import TcpProbe, ping_command, resolve_method
from netlag.targets import PRESETS, Target, TargetResult, parse_target


def test_ping_command_per_platform() -> None:
    assert ping_command("1.1.1.1", 1.0, "win32") == ["ping", "-n", "1", "-w", "1000", "1.1.1.1"]
    assert ping_command("1.1.1.1", 1.0, "linux") == ["ping", "-c", "1", "-W", "1", "1.1.1.1"]
    assert ping_command("1.1.1.1", 0.2, "linux")[5] == "1.1.1.1"
    assert ping_command("1.1.1.1", 0.2, "linux")[4] == "1"
    assert ping_command("1.1.1.1", 2.0, "darwin") == ["ping", "-c", "1", "-W", "2000", "1.1.1.1"]


def test_parse_target() -> None:
    assert parse_target("example.com") == Target("example.com", "example.com")
    tcp = parse_target("game.example.com:27015")
    assert (tcp.host, tcp.port, tcp.method) == ("game.example.com", 27015, "tcp")
    with pytest.raises(ValueError):
        parse_target("  ")
    with pytest.raises(ValueError):
        parse_target("host:70000")


def test_aws_presets_use_tcp_443() -> None:
    target = PRESETS["aws-sa-east-1"]
    assert target.host == "dynamodb.sa-east-1.amazonaws.com"
    assert (target.method, target.port) == ("tcp", 443)


def test_resolve_targets_defaults_and_gateway() -> None:
    targets = resolve_targets(None, "192.168.0.1")
    assert [t.name for t in targets] == ["gateway", "cloudflare", "google", "aws-sa-east-1"]
    assert targets[0].host == "192.168.0.1"
    assert targets[0].kind == "gateway"
    with pytest.raises(ValueError):
        resolve_targets(["gateway"], None)


def test_resolve_method() -> None:
    assert resolve_method(PRESETS["aws-sa-east-1"], "auto") == "tcp"
    assert resolve_method(PRESETS["cloudflare"], "tcp") == "tcp"
    assert resolve_method(PRESETS["aws-sa-east-1"], "ping") == "ping"


@pytest.fixture
def listener() -> Iterator[int]:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    yield server.getsockname()[1]
    server.close()


def test_tcp_probe_measures_open_port(listener: int) -> None:
    rtt = TcpProbe("127.0.0.1", listener, timeout=1.0).measure()
    assert rtt is not None
    assert 0 <= rtt < 1000


def test_tcp_probe_counts_refused_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    class Refusing:
        def __init__(self, *args: object) -> None:
            pass

        def __enter__(self) -> "Refusing":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def settimeout(self, value: float) -> None:
            pass

        def connect(self, address: object) -> None:
            raise ConnectionRefusedError

    monkeypatch.setattr("netlag.probes.socket.socket", Refusing)
    assert TcpProbe("127.0.0.1", 9, timeout=1.0).measure() is not None


def test_tcp_probe_unresolvable_host_is_loss() -> None:
    assert TcpProbe("nao-existe.invalid", 443, timeout=0.5).measure() is None


class ScriptedProbe:
    def __init__(self, values: list[float | None]) -> None:
        self._values = iter(values)

    def measure(self) -> float | None:
        return next(self._values)


def test_run_monitor_collects_rounds_in_order() -> None:
    results = [TargetResult(Target("a", "a")), TargetResult(Target("b", "b"))]
    probes = [ScriptedProbe([1.0, None, 3.0]), ScriptedProbe([5.0, 6.0, 7.0])]
    rounds: list[int] = []
    sleeps: list[float] = []
    run_monitor(results, probes, 3, 1.0, on_round=lambda: rounds.append(1), sleep=sleeps.append)
    assert results[0].samples == [1.0, None, 3.0]
    assert results[1].samples == [5.0, 6.0, 7.0]
    assert len(rounds) == 3
    assert len(sleeps) == 2


class _Body(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "262144")
        self.end_headers()
        self.wfile.write(b"x" * 262144)

    def log_message(self, *args: object) -> None:
        pass


def test_load_generator_downloads_in_background() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Body)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        with LoadGenerator(url, threads=2, timeout=2.0) as load:
            deadline = threading.Event()
            while load.bytes_downloaded < 1_000_000 and not deadline.wait(0.05):
                pass
            assert load.bytes_downloaded >= 1_000_000
    finally:
        server.shutdown()
        server.server_close()


def test_load_generator_survives_unreachable_url() -> None:
    with LoadGenerator("http://127.0.0.1:1/", threads=1, timeout=0.5) as load:
        threading.Event().wait(0.3)
    assert load.bytes_downloaded == 0
