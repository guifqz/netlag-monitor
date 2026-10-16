import csv
from datetime import UTC, datetime
from pathlib import Path

from netlag.bufferbloat import evaluate
from netlag.diagnosis import Diagnosis, diagnose
from netlag.report import render_chart, render_html, write_csv
from netlag.targets import Target, TargetResult

NOW = datetime(2026, 10, 16, 20, 0, tzinfo=UTC)


def sample_results() -> list[TargetResult]:
    gateway = TargetResult(Target("gateway", "192.168.0.1", kind="gateway"), "ping")
    cloud = TargetResult(Target("cloudflare", "1.1.1.1", kind="dns"), "ping")
    for i in range(12):
        gateway.add(1_000.0 + i, None if i == 5 else 2.0 + i % 3)
        cloud.add(1_000.0 + i, 12.0 + i % 4)
    return [gateway, cloud]


def test_html_is_self_contained() -> None:
    results = sample_results()
    page = render_html(results, diagnose(results), generated_at=NOW)
    assert page.startswith("<!DOCTYPE html>")
    assert "<svg" in page
    assert "<polyline" in page
    assert "http://" not in page.replace("http://www.w3.org", "")
    assert "<script" not in page
    assert "cdn" not in page.lower()
    assert "gateway" in page
    assert "192.168.0.1" in page
    assert "2026-10-16 20:00:00 UTC" in page


def test_html_escapes_user_input() -> None:
    result = TargetResult(Target("<b>x</b>", 'evil.test"><script>'), "ping")
    result.add(0.0, 10.0)
    page = render_html([result], [Diagnosis("warn", "<img src=x>")], generated_at=NOW)
    assert "<b>x</b>" not in page
    assert "<script>" not in page
    assert "&lt;img src=x&gt;" in page


def test_html_includes_bufferbloat_section() -> None:
    results = sample_results()
    bloat = evaluate([10, 11, 12], [90, 100, 110], 50_000_000, 10)
    page = render_html(results, diagnose(results, bloat), bloat, generated_at=NOW)
    assert "Bufferbloat" in page
    assert f'aria-label="Nota {bloat.grade}"' in page


def test_chart_marks_losses_and_breaks_line() -> None:
    gateway = sample_results()[0]
    svg = render_chart([gateway])
    assert svg.count('stroke="#d6453b"') == 1
    assert svg.count("<polyline") == 2


def test_chart_handles_empty_and_all_lost() -> None:
    assert "<svg" in render_chart([])
    lost = TargetResult(Target("x", "x.test"), "ping")
    lost.add(0.0, None)
    assert "<polyline" not in render_chart([lost])


def test_csv_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "out.csv"
    write_csv(path, sample_results())
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 24
    assert list(rows[0]) == ["timestamp", "target", "host", "method", "seq", "rtt_ms"]
    lost = [r for r in rows if r["target"] == "gateway" and r["seq"] == "5"]
    assert lost[0]["rtt_ms"] == ""
    assert rows[1]["rtt_ms"] == "3.000"
    assert rows[0]["timestamp"].endswith("+00:00")
