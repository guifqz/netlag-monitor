import re
from pathlib import Path

import pytest

from netlag import cli
from netlag.targets import Target, TargetResult


def test_targets_command_lists_presets(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["targets"]) == 0
    out = capsys.readouterr().out
    assert "cloudflare" in out
    assert "dynamodb.sa-east-1.amazonaws.com" in out


def test_run_with_tcp_target_writes_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "r.csv"
    html_path = tmp_path / "r.html"
    code = cli.main(
        [
            "-t",
            "127.0.0.1:1",
            "-c",
            "3",
            "-i",
            "0.05",
            "--timeout",
            "0.5",
            "--csv",
            str(csv_path),
            "--html",
            str(html_path),
        ]
    )
    assert code == 0
    assert len(csv_path.read_text(encoding="utf-8").splitlines()) == 4
    assert "<svg" in html_path.read_text(encoding="utf-8")
    assert re.search(r"127\.0\.0\.1:1", capsys.readouterr().out)


def test_invalid_arguments_return_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["-c", "-1"]) == 2
    assert cli.main(["-t", "host:99999"]) == 2


def test_table_renders_every_target() -> None:
    from rich.console import Console

    from netlag.display import build_table

    result = TargetResult(Target("cloudflare", "1.1.1.1"), "ping")
    for value in (10.0, None, 12.0):
        result.add(0.0, value)
    console = Console(record=True, width=120)
    console.print(build_table([result]))
    text = console.export_text()
    assert "cloudflare" in text
    assert "33.3%" in text
