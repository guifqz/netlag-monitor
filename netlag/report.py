"""Exportação dos resultados: CSV e relatório HTML autocontido (gráfico em SVG inline)."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from netlag import __version__
from netlag.bufferbloat import BufferbloatResult
from netlag.diagnosis import Diagnosis
from netlag.targets import TargetResult

CSV_FIELDS = ("timestamp", "target", "host", "method", "seq", "rtt_ms")
PALETTE = ("#2a78d6", "#e8743b", "#2e9d6a", "#a05cc2", "#c9a227", "#d6456b")

CHART_W, CHART_H = 900, 320
MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 56, 16, 14, 34

_CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1b1f24;--muted:#5b6571;--line:#d8dde3;
--card:#f6f8fa;--ok:#1a7f4b;--info:#2a78d6;--warn:#b7791f;--crit:#c0392b}
@média (prefers-color-scheme:dark){:root{--bg:#0f141a;--fg:#e6ebf0;--muted:#97a3b0;
--line:#2a333d;--card:#171e26;--ok:#4cc38a;--info:#6aa9f0;--warn:#e0b04b;--crit:#f07b6c}}
*{box-sizing:border-box}
body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:960px;margin:0 auto}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:28px 0 10px}
.meta{color:var(--muted);margin:0 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;text-align:right;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}th{color:var(--muted);font-weight:600}
.scroll{overflow-x:auto}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:8px 0 0;padding:0;list-style:none}
.swatch{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
.grade{font-size:2.4rem;font-weight:700;line-height:1}
.diag{list-style:none;margin:0;padding:0}
.diag li{padding:8px 12px;margin-bottom:8px;border-left:4px solid var(--info);
background:var(--card);border-radius:4px}
.diag .ok{border-color:var(--ok)}.diag .warn{border-color:var(--warn)}
.diag .crit{border-color:var(--crit)}
svg{width:100%;height:auto;display:block}
.axis{stroke:var(--line)}.tick{fill:var(--muted);font-size:11px}
footer{margin-top:32px;color:var(--muted);font-size:.85rem}
"""


def write_csv(path: Path, results: Sequence[TargetResult]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_FIELDS)
        for result in results:
            for seq, (ts, rtt) in enumerate(zip(result.timestamps, result.samples, strict=True)):
                stamp = datetime.fromtimestamp(ts, tz=UTC).isoformat(timespec="milliseconds")
                writer.writerow(
                    [
                        stamp,
                        result.target.name,
                        result.target.host,
                        result.method,
                        seq,
                        "" if rtt is None else f"{rtt:.3f}",
                    ]
                )


def _fmt(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _nice_ceiling(value: float) -> float:
    """Menor valor 'redondo' (1, 2, 5 x 10^n) que cobre `value`."""
    if value <= 0:
        return 1.0
    magnitude = 10 ** (len(str(int(value))) - 1) if value >= 1 else 1
    for factor in (1, 2, 5, 10):
        if value <= factor * magnitude:
            return float(factor * magnitude)
    return float(10 * magnitude)


def render_chart(results: Sequence[TargetResult]) -> str:
    """Grafico de linhas (RTT por amostra); perdas viram marcas vermelhas na base."""
    plot_w = CHART_W - MARGIN_L - MARGIN_R
    plot_h = CHART_H - MARGIN_T - MARGIN_B
    longest = max((len(r.samples) for r in results), default=0)
    peak = max((s for r in results for s in r.samples if s is not None), default=0.0)
    top = _nice_ceiling(peak * 1.05)

    def x_of(index: int) -> float:
        return MARGIN_L + (plot_w * index / (longest - 1) if longest > 1 else 0)

    def y_of(value: float) -> float:
        return MARGIN_T + plot_h * (1 - value / top)

    parts = [
        f'<svg viewBox="0 0 {CHART_W} {CHART_H}" role="img" '
        'aria-label="Latência por amostra, em milissegundos">'
    ]
    for step in range(5):
        value = top * step / 4
        y = y_of(value)
        parts.append(
            f'<line class="axis" x1="{MARGIN_L}" x2="{CHART_W - MARGIN_R}" '
            f'y1="{y:.1f}" y2="{y:.1f}"/>'
            f'<text class="tick" x="{MARGIN_L - 6}" y="{y + 4:.1f}" text-anchor="end">'
            f"{value:g}</text>"
        )
    parts.append(
        f'<text class="tick" x="{MARGIN_L}" y="{CHART_H - 8}">amostra 1</text>'
        f'<text class="tick" x="{CHART_W - MARGIN_R}" y="{CHART_H - 8}" text-anchor="end">'
        f"amostra {longest}</text>"
        f'<text class="tick" x="6" y="{MARGIN_T + 4}">ms</text>'
    )

    for number, result in enumerate(results):
        color = PALETTE[number % len(PALETTE)]
        segments: list[list[tuple[float, float]]] = []
        for index, sample in enumerate(result.samples):
            if sample is None:
                segments.append([])
                parts.append(
                    f'<line x1="{x_of(index):.1f}" x2="{x_of(index):.1f}" '
                    f'y1="{CHART_H - MARGIN_B - 8}" y2="{CHART_H - MARGIN_B}" '
                    'stroke="#d6453b" stroke-width="1.5"/>'
                )
                continue
            if not segments:
                segments.append([])
            segments[-1].append((x_of(index), y_of(sample)))
        for segment in segments:
            if len(segment) == 1:
                x, y = segment[0]
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2" fill="{color}"/>')
            elif segment:
                points = " ".join(f"{x:.1f},{y:.1f}" for x, y in segment)
                parts.append(
                    f'<polyline points="{points}" fill="none" stroke="{color}" '
                    'stroke-width="1.6" stroke-linejoin="round"/>'
                )
    parts.append("</svg>")
    return "".join(parts)


def _stats_table(results: Sequence[TargetResult]) -> str:
    head = (
        "<tr><th>Alvo</th><th>Método</th><th>Amostras</th><th>Perda %</th><th>Min</th>"
        "<th>Média</th><th>p50</th><th>p95</th><th>p99</th><th>Max</th><th>Jitter</th></tr>"
    )
    rows = []
    for result in results:
        s = result.stats
        rows.append(
            f"<tr><td>{escape(result.target.name)}<br>"
            f'<small class="meta">{escape(result.target.host)}</small></td>'
            f"<td>{escape(result.method)}</td><td>{s.sent}</td><td>{s.loss_pct:.1f}</td>"
            f"<td>{_fmt(s.min)}</td><td>{_fmt(s.avg)}</td><td>{_fmt(s.p50)}</td>"
            f"<td>{_fmt(s.p95)}</td><td>{_fmt(s.p99)}</td><td>{_fmt(s.max)}</td>"
            f"<td>{s.jitter:.1f}</td></tr>"
        )
    return f'<div class="scroll"><table>{head}{"".join(rows)}</table></div>'


def _bufferbloat_section(result: BufferbloatResult) -> str:
    return (
        "<h2>Bufferbloat</h2>"
        '<div class="card" style="display:flex;gap:24px;align-items:center;flex-wrap:wrap">'
        f'<div class="grade" aria-label="Nota {escape(result.grade)}">{escape(result.grade)}</div>'
        "<div>"
        f"Latência média em repouso: <b>{_fmt(result.idle.avg)} ms</b> "
        f"(jitter {result.idle.jitter:.1f} ms)<br>"
        f"Latência média sob carga: <b>{_fmt(result.loaded.avg)} ms</b> "
        f"(jitter {result.loaded.jitter:.1f} ms)<br>"
        f"Aumento: <b>{result.delta_ms:.1f} ms</b> com {result.mbps:.0f} Mbps de download"
        "</div></div>"
    )


def render_html(
    results: Sequence[TargetResult],
    diagnoses: Sequence[Diagnosis],
    bufferbloat: BufferbloatResult | None = None,
    generated_at: datetime | None = None,
    title: str = "Relatório de latência",
) -> str:
    generated_at = generated_at or datetime.now(tz=UTC)
    legend = "".join(
        f'<li><span class="swatch" style="background:{PALETTE[i % len(PALETTE)]}"></span>'
        f"{escape(r.target.name)}</li>"
        for i, r in enumerate(results)
    )
    diag_items = "".join(f'<li class="{d.level}">{escape(d.message)}</li>' for d in diagnoses)
    return (
        '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body><main>"
        f"<h1>{escape(title)}</h1>"
        f'<p class="meta">Gerado em {generated_at:%Y-%m-%d %H:%M:%S %Z} '
        f"por netlag {__version__}</p>"
        "<h2>Diagnóstico</h2>"
        f'<ul class="diag">{diag_items}</ul>'
        "<h2>Latência ao longo do tempo</h2>"
        f'<div class="card">{render_chart(results)}<ul class="legend">{legend}</ul></div>'
        "<h2>Métricas por alvo (ms)</h2>"
        f"{_stats_table(results)}"
        f"{_bufferbloat_section(bufferbloat) if bufferbloat else ''}"
        "<footer>Gerado por netlag-monitor. Marcas vermelhas na base do gráfico "
        "indicam pacotes perdidos.</footer>"
        "</main></body></html>"
    )


def write_html(
    path: Path,
    results: Sequence[TargetResult],
    diagnoses: Sequence[Diagnosis],
    bufferbloat: BufferbloatResult | None = None,
) -> None:
    path.write_text(render_html(results, diagnoses, bufferbloat), encoding="utf-8")
