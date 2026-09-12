"""Self-contained HTML report with inline SVG charts (v2).

One file, zero dependencies, no external fonts or scripts: the report
renders identically in a browser, in `file://` previews, and in CI
artifacts. Everything - the metric cards, the per-case bar chart, the
trend line, the histograms - is inline SVG generated deterministically
from the run's statistics.

Design: SVX green family on near-white surfaces, near-black ink, thin
borders, tabular numbers. Charts encode confidence intervals, not just
points, because that is the entire point of the tool.
"""
from __future__ import annotations

import datetime as _dt
import html
from pathlib import Path

from . import __version__

# --- palette (SVX green family, mirrors the report PDF) -------------------
_ACCENT = "#1d9459"      # emerald
_DARK = "#14573a"        # deep green
_INK = "#0d2b1d"         # near-black green ink
_MUTE = "#5a7568"        # secondary text
_SAGE = "#e9f6ef"        # light green surface
_FAINT = "#f5faf7"       # faint surface
_BORDER = "#d8e8de"      # hairline borders
_RED = "#c62828"
_RED_SAGE = "#fdecea"

_SANS = ("ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', "
         "Roboto, 'Helvetica Neue', Arial, sans-serif")


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def _fmt_ci(ci) -> str:
    if ci is None:
        return ""
    return f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def _fmt_pct(value) -> str:
    return f"{value * 100:.1f}%"


def _fmt_ms(value) -> str:
    return f"{value:,.0f} ms"


def _fmt_usd(value) -> str:
    if value is None:
        return "n/a"
    if value >= 10:
        return f"${value:,.2f}"
    if value >= 0.01:
        return f"${value:.3f}"
    return f"${value:.4f}"


# ---------------------------------------------------------------------------
# SVG chart builders (deterministic, no dependencies)
# ---------------------------------------------------------------------------
def _svg_case_bars(cases, k: int, threshold: float | None,
                   width: int = 760) -> str:
    """Horizontal bars: pass@k (solid) with pass-rate ghost (light)."""
    row_h = 26
    top, bottom = 8, 26
    label_w, value_w = 200, 64
    plot_w = width - label_w - value_w - 10
    height = top + bottom + row_h * len(cases)
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'role="img" aria-label="pass@{k} by case">']

    if threshold is not None:
        x = label_w + threshold * plot_w
        out.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" '
                   f'y2="{height - bottom}" stroke="{_RED}" '
                   f'stroke-width="1" stroke-dasharray="5 4" opacity="0.55"/>')
        out.append(f'<text x="{x + 4:.1f}" y="{top + 10}" font-size="10" '
                   f'fill="{_RED}" opacity="0.8">threshold {threshold:.2f}</text>')

    for i, c in enumerate(cases):
        y = top + i * row_h
        cy = y + row_h / 2
        name = esc(c.name if len(c.name) <= 28 else c.name[:25] + "...")
        out.append(f'<text x="{label_w - 10}" y="{cy + 3.5:.1f}" '
                   f'font-size="11.5" fill="{_INK}" text-anchor="end" '
                   f'font-family="{_SANS}">{name}</text>')
        # ghost: raw pass rate
        gw = c.pass_rate * plot_w
        out.append(f'<rect x="{label_w}" y="{cy - 5:.1f}" width="{gw:.1f}" '
                   f'height="10" rx="2" fill="{_ACCENT}" opacity="0.18"/>')
        # solid: pass@k
        bw = c.pass_at_k * plot_w
        out.append(f'<rect x="{label_w}" y="{cy - 5:.1f}" width="{bw:.1f}" '
                   f'height="10" rx="2" fill="{_ACCENT}"/>')
        below = (c.passes < c.runs)
        color = _RED if below and c.pass_rate < 0.5 else _INK
        out.append(f'<text x="{label_w + plot_w + 8}" y="{cy + 3.5:.1f}" '
                   f'font-size="11.5" fill="{color}" text-anchor="start" '
                   f'font-family="{_SANS}">{c.pass_at_k:.3f}</text>')
    out.append("</svg>")
    return "".join(out)


def _svg_trend(entries, threshold: float | None,
               width: int = 760, height: int = 210) -> str:
    """pass@k mean across runs: line, dots colored by verdict, threshold."""
    left, right, top, bottom = 44, 16, 14, 30
    plot_w = width - left - right
    plot_h = height - top - bottom
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
           'role="img" aria-label="pass@k trend">']

    def y_of(v: float) -> float:
        return top + (1.0 - max(0.0, min(1.0, v))) * plot_h

    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        gy = y_of(frac)
        out.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{width - right}" '
                   f'y2="{gy:.1f}" stroke="{_BORDER}" stroke-width="1"/>')
        out.append(f'<text x="{left - 8}" y="{gy + 3.5:.1f}" font-size="10" '
                   f'fill="{_MUTE}" text-anchor="end" '
                   f'font-family="{_SANS}">{frac:.2f}</text>')

    if threshold is not None:
        ty = y_of(threshold)
        out.append(f'<line x1="{left}" y1="{ty:.1f}" x2="{width - right}" '
                   f'y2="{ty:.1f}" stroke="{_RED}" stroke-width="1" '
                   f'stroke-dasharray="5 4" opacity="0.55"/>')

    pts = []
    for i, e in enumerate(entries):
        v = e.get("pass_at_k_mean")
        if v is None:
            continue
        x = left + (i / max(1, len(entries) - 1)) * plot_w
        pts.append((x, y_of(float(v)), e.get("verdict") == "GREEN"))

    if len(pts) > 1:
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts)
        out.append(f'<polyline points="{poly}" fill="none" stroke="{_ACCENT}" '
                   f'stroke-width="2" stroke-linejoin="round" '
                   f'stroke-linecap="round"/>')
    for j, (x, y, green) in enumerate(pts):
        last = j == len(pts) - 1
        r = 4.5 if last else 3.0
        fill = _ACCENT if green else _RED
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}"'
                   + (f' stroke="{_DARK}" stroke-width="1.5"' if last else "")
                   + "/>")

    if entries:
        first_ts = str(entries[0].get("ts", ""))[:10]
        last_ts = str(entries[-1].get("ts", ""))[:10]
        out.append(f'<text x="{left}" y="{height - 8}" font-size="10" '
                   f'fill="{_MUTE}" font-family="{_SANS}">{esc(first_ts)}</text>')
        out.append(f'<text x="{width - right}" y="{height - 8}" font-size="10" '
                   f'fill="{_MUTE}" text-anchor="end" '
                   f'font-family="{_SANS}">{esc(last_ts)}</text>')
    out.append("</svg>")
    return "".join(out)


def _svg_histogram(values: list[float], bins: int, unit: str,
                   width: int = 368, height: int = 180,
                   color: str = _ACCENT) -> str:
    """Vertical-bar histogram of raw per-row values."""
    left, right, top, bottom = 40, 10, 12, 26
    plot_w = width - left - right
    plot_h = height - top - bottom
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, int((v - lo) / span * bins))
        counts[idx] += 1
    peak = max(counts) or 1
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'role="img" aria-label="distribution">']
    for frac in (0.0, 0.5, 1.0):
        gy = top + (1.0 - frac) * plot_h
        out.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{width - right}" '
                   f'y2="{gy:.1f}" stroke="{_BORDER}" stroke-width="1"/>')
        out.append(f'<text x="{left - 6}" y="{gy + 3.5:.1f}" font-size="9.5" '
                   f'fill="{_MUTE}" text-anchor="end" '
                   f'font-family="{_SANS}">{int(frac * peak)}</text>')
    bw = plot_w / bins
    for i, count in enumerate(counts):
        if count == 0:
            continue
        h = (count / peak) * plot_h
        x = left + i * bw
        y = top + plot_h - h
        out.append(f'<rect x="{x + 0.75:.2f}" y="{y:.1f}" '
                   f'width="{bw - 1.5:.2f}" height="{h:.1f}" rx="1.5" '
                   f'fill="{color}" opacity="0.75"/>')
    for frac, label_frac in ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0)):
        x = left + frac * plot_w
        v = lo + label_frac * span
        text = f"{v:,.0f}" if unit == "ms" else f"{v:.2f}"
        out.append(f'<text x="{x:.1f}" y="{height - 8}" font-size="9.5" '
                   f'fill="{_MUTE}" text-anchor="middle" '
                   f'font-family="{_SANS}">{text}</text>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------
_STATUS_BADGE = {
    "pass": ("PASS", _ACCENT),
    "improved": ("IMPROVED ↑", _DARK),
    "regression": ("REGRESSION ↓", _RED),
    "fail": ("FAIL ✕", _RED),
    "n/a": ("N/A", _MUTE),
}


def _card(label: str, value: str, sub: str = "") -> str:
    sub_html = f'<div class="card-sub">{sub}</div>' if sub else ""
    return (f'<div class="card"><div class="card-label">{label}</div>'
            f'<div class="card-value">{value}</div>{sub_html}</div>')


def _chart_card(title: str, subtitle: str, svg: str) -> str:
    return (f'<div class="chart-card"><div class="chart-title">{title}</div>'
            f'<div class="chart-sub">{subtitle}</div>{svg}</div>')


def _status_badge(status: str) -> str:
    word, color = _STATUS_BADGE.get(status, (status.upper(), _MUTE))
    return f'<span class="badge" style="color:{color}">{word}</span>'


def render(agg, config, baseline, gate_result, history_entries) -> str:
    """Render the full self-contained HTML report for a run."""
    green = gate_result.green
    verdict = "GREEN" if green else "RED"
    tone = _ACCENT if green else _RED
    tone_bg = _SAGE if green else _RED_SAGE
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    parts: list[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EvalGate Report - {verdict}</title>
<style>
  :root {{
    --ink: {_INK}; --mute: {_MUTE}; --accent: {_ACCENT}; --dark: {_DARK};
    --sage: {_SAGE}; --faint: {_FAINT}; --border: {_BORDER}; --red: {_RED};
    --red-sage: {_RED_SAGE};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: #fbfdfc; color: var(--ink);
    font-family: {_SANS};
    -webkit-font-smoothing: antialiased; line-height: 1.45;
  }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 28px 20px 60px; }}
  .banner {{
    border: 1px solid var(--border); border-left: 5px solid {tone};
    background: {tone_bg}; border-radius: 12px; padding: 18px 22px;
    display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
  }}
  .brand {{ display: flex; align-items: center; gap: 10px; }}
  .brand-mark {{
    width: 34px; height: 34px; border-radius: 8px; background: var(--accent);
    color: #fff; font-weight: 800; font-size: 13px; letter-spacing: 0.02em;
    display: flex; align-items: center; justify-content: center;
  }}
  .brand-name {{
    font-size: 13px; font-weight: 700; letter-spacing: 0.14em;
    color: var(--mute); text-transform: uppercase;
  }}
  .brand-name b {{ color: var(--ink); }}
  .verdict {{
    margin-left: auto; font-size: 30px; font-weight: 800; color: {tone};
    letter-spacing: 0.04em; display: flex; align-items: center; gap: 10px;
  }}
  .verdict-dot {{
    width: 12px; height: 12px; border-radius: 50%; background: {tone};
  }}
  .meta {{
    width: 100%; font-size: 12.5px; color: var(--mute); margin-top: 2px;
  }}
  .cards {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px; margin-top: 22px;
  }}
  .card {{
    background: #fff; border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 16px;
  }}
  .card-label {{
    font-size: 10.5px; font-weight: 700; letter-spacing: 0.09em;
    text-transform: uppercase; color: var(--mute); margin-bottom: 6px;
  }}
  .card-value {{
    font-size: 25px; font-weight: 650; font-variant-numeric: tabular-nums;
  }}
  .card-sub {{
    font-size: 11.5px; color: var(--mute); margin-top: 4px;
    font-variant-numeric: tabular-nums;
  }}
  .charts {{ display: grid; gap: 12px; margin-top: 22px; }}
  .chart-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  @media (max-width: 760px) {{ .chart-grid {{ grid-template-columns: 1fr; }} }}
  .chart-card {{
    background: #fff; border: 1px solid var(--border); border-radius: 10px;
    padding: 16px 18px 10px;
  }}
  .chart-title {{ font-size: 13px; font-weight: 700; }}
  .chart-sub {{
    font-size: 11.5px; color: var(--mute); margin: 2px 0 10px;
  }}
  table {{
    width: 100%; border-collapse: collapse; font-size: 12.5px;
    font-variant-numeric: tabular-nums; background: #fff;
  }}
  .table-card {{
    background: #fff; border: 1px solid var(--border); border-radius: 10px;
    padding: 16px 18px; margin-top: 22px; overflow-x: auto;
  }}
  th {{
    text-align: right; font-size: 10.5px; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--mute); font-weight: 700;
    padding: 6px 10px; border-bottom: 1px solid var(--border);
  }}
  th:first-child, td:first-child {{ text-align: left; }}
  td {{
    padding: 6px 10px; border-bottom: 1px solid var(--faint);
    text-align: right; font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 12px;
  }}
  td:first-child {{ font-family: inherit; font-size: 12.5px; }}
  tr:last-child td {{ border-bottom: none; }}
  .badge {{
    font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em;
    font-family: inherit;
  }}
  .reasons {{
    background: var(--red-sage); border: 1px solid #f2c4be;
    border-left: 4px solid var(--red); border-radius: 10px;
    padding: 14px 18px; margin-top: 22px;
  }}
  .reasons h3 {{ margin: 0 0 8px; font-size: 13px; color: var(--red); }}
  .reasons li {{ font-size: 13px; margin: 4px 0; }}
  .notes {{
    background: var(--faint); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 18px; margin-top: 22px;
    font-size: 12.5px; color: var(--mute);
  }}
  .notes ul {{ margin: 6px 0 0; padding-left: 18px; }}
  footer {{
    margin-top: 30px; padding-top: 14px; border-top: 1px solid var(--border);
    font-size: 11.5px; color: var(--mute);
  }}
</style>
</head>
<body>
<div class="wrap">""")

    # --- banner -----------------------------------------------------------
    base_line = ""
    if baseline is not None:
        created = esc(baseline.get("created", "unknown"))
        sha = baseline.get("git_sha") or "unknown"
        sha = esc(sha[:10] if isinstance(sha, str) else sha)
        base_line = f" · baseline {created} @ {sha}"
    parts.append(f"""
<div class="banner">
  <div class="brand">
    <div class="brand-mark">SVX</div>
    <div class="brand-name"><b>EVALGATE</b> · SVX</div>
  </div>
  <div class="verdict">{verdict}<div class="verdict-dot"></div></div>
  <div class="meta">
    {esc(config.evals.repetitions)} repetitions · seed {esc(config.evals.base_seed)} ·
    {len(agg.cases)} cases / {agg.total_runs} runs ·
    {agg.total_passes} passing runs ({_fmt_pct(agg.total_passes / agg.total_runs)})
    {base_line}
  </div>
</div>""")

    # --- metric cards -----------------------------------------------------
    cards: list[str] = []
    if agg.pass_at_k_mean is not None:
        cards.append(_card(
            f"pass@{agg.k} mean", f"{agg.pass_at_k_mean:.3f}",
            f"95% CI {_fmt_ci(agg.pass_at_k_ci)}"))
    if agg.pass_rate is not None:
        cards.append(_card(
            "pass rate", _fmt_pct(agg.pass_rate),
            f"Wilson 95% CI {_fmt_ci(agg.pass_rate_ci)}"))
    if agg.mean_score is not None:
        cards.append(_card(
            "mean score", f"{agg.mean_score:.3f}",
            f"95% CI {_fmt_ci(agg.mean_score_ci)} · p50 {agg.score_p50:.3f} "
            f"· p95 {agg.score_p95:.3f}"))
    if agg.p95_latency_ms is not None:
        cards.append(_card(
            "p95 latency", _fmt_ms(agg.p95_latency_ms),
            f"95% CI [{agg.p95_latency_ci[0]:,.0f}, "
            f"{agg.p95_latency_ci[1]:,.0f}] ms · max {_fmt_ms(agg.max_latency_ms)}"))
    if agg.total_cost_usd is not None:
        cards.append(_card(
            "total cost", _fmt_usd(agg.total_cost_usd),
            f"{agg.cost_rows} rows · mean {_fmt_usd(agg.mean_cost_usd)}"))
    if cards:
        parts.append('<div class="cards">' + "".join(cards) + "</div>")

    # --- charts -----------------------------------------------------------
    charts: list[str] = []
    charts.append(_chart_card(
        f"pass@{agg.k} by case",
        "solid bar: pass@" + str(agg.k) + " (estimator) · ghost bar: raw pass rate"
        + (" · dashed line: threshold" if config.gate.min_pass_at_k else ""),
        _svg_case_bars(agg.cases, agg.k, config.gate.min_pass_at_k)))

    trend_note = (f"{len(history_entries)} run(s) on record"
                  if history_entries else "first run on record")
    charts.append(_chart_card(
        "pass@k trend", f"{trend_note} · dot color: run verdict",
        _svg_trend(history_entries, config.gate.min_pass_at_k)))

    hist_parts: list[str] = []
    if agg.score_values:
        hist_parts.append(_chart_card(
            "score distribution",
            f"min {agg.score_min:.2f} · max {agg.score_max:.2f} · per-run scores",
            _svg_histogram(agg.score_values, 24, "score")))
    if agg.latency_values:
        hist_parts.append(_chart_card(
            "latency distribution",
            f"{agg.latency_rows} rows · p50 {_fmt_ms(agg.p50_latency_ms)}",
            _svg_histogram(agg.latency_values, 24, "ms")))
    if hist_parts:
        charts.append('<div class="chart-grid">' + "".join(hist_parts) + "</div>")
    parts.append('<div class="charts">' + "".join(charts) + "</div>")

    # --- per-case table ---------------------------------------------------
    rows_html: list[str] = []
    for c in agg.cases:
        flag = "" if c.passes == c.runs else " ⚠"
        score_cell = f"{c.mean_score:.3f}" if c.mean_score is not None else "-"
        rows_html.append(
            f"<tr><td>{esc(c.name)}{flag}</td><td>{c.runs}</td><td>{c.passes}</td>"
            f"<td>{c.pass_rate:.2f}</td><td>{c.pass_at_k:.3f}</td>"
            f"<td>{score_cell}</td></tr>")
    if rows_html:
        parts.append(f"""
<div class="table-card">
  <div class="chart-title">Cases</div>
  <div class="chart-sub">⚠ marks cases that did not pass every run</div>
  <table>
    <thead><tr><th>case</th><th>runs</th><th>passes</th><th>rate</th>
    <th>pass@{agg.k}</th><th>mean score</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
</div>""")

    # --- threshold / regression verdict table ------------------------------
    verdict_rows: list[str] = []
    for v in gate_result.verdicts:
        if v.kind == "threshold":
            cur = f"{v.current:.3f}" if v.current is not None else "n/a"
            verdict_rows.append(
                f"<tr><td>{esc(v.metric)}</td><td>{cur}</td>"
                f"<td>{esc(v.threshold)}</td><td>{_status_badge(v.status)}</td></tr>")
        else:
            cur = (f"{v.current:.3f} [{v.ci_low:.3f}, {v.ci_high:.3f}]"
                   if v.current is not None and v.ci_low is not None else "n/a")
            base = (f"{v.baseline:.3f} [{v.baseline_low:.3f}, {v.baseline_high:.3f}]"
                    if v.baseline is not None and v.baseline_low is not None
                    else (f"{v.baseline:.3f}" if v.baseline is not None else "-"))
            verdict_rows.append(
                f"<tr><td>{esc(v.metric)}</td><td>{cur}</td>"
                f"<td>{base}</td><td>{_status_badge(v.status)}</td></tr>")
    if verdict_rows:
        parts.append(f"""
<div class="table-card">
  <div class="chart-title">Gate verdicts</div>
  <div class="chart-sub">current [95% CI] vs threshold or baseline [95% CI]</div>
  <table>
    <thead><tr><th>metric</th><th>current</th><th>reference</th>
    <th>verdict</th></tr></thead>
    <tbody>{''.join(verdict_rows)}</tbody>
  </table>
</div>""")

    # --- reasons / notes ---------------------------------------------------
    reasons = gate_result.reasons()
    if reasons:
        items = "".join(f"<li>{esc(r)}</li>" for r in reasons)
        parts.append(f'<div class="reasons"><h3>Why this run is RED</h3>'
                     f"<ul>{items}</ul></div>")
    if gate_result.notes:
        items = "".join(f"<li>{esc(n)}</li>" for n in gate_result.notes)
        parts.append(f'<div class="notes"><b>Notes</b><ul>{items}</ul></div>')

    # --- footer ------------------------------------------------------------
    parts.append(f"""
<footer>
  generated {now} by svx-evalgate {esc(__version__)} ·
  report {esc(config.report.path)} · html {esc(config.report.html_path or "disabled")} ·
  SVX green family {_ACCENT} {_DARK} · deterministic given seed {esc(config.evals.base_seed)}
</footer>
</div>
</body>
</html>""")
    return "".join(parts)


def write_report(html_text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
