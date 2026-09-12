"""Markdown report rendering (GitHub step summary + PR comment + file)."""
from __future__ import annotations

from pathlib import Path

from .gate import IMPROVED, REGRESSION, GateResult

_GREEN = "#298959"
_LIGHT = "#4fbb85"
_DARK = "#1f5e40"


def _status_word(status: str) -> str:
    if status == IMPROVED:
        return "IMPROVED"
    if status == REGRESSION:
        return "REGRESSION"
    return status.upper()


def render(agg, config, baseline: dict | None, gate_result: GateResult) -> str:
    """Render the full markdown report for a run."""
    verdict = "GREEN" if gate_result.green else "RED"
    lines: list[str] = []
    lines.append(f"## EvalGate - {verdict}")
    lines.append("")
    lines.append(
        f"Deterministic statistics for `{config.evals.repetitions}` repetitions "
        f"(base seed `{config.evals.base_seed}`) across "
        f"**{len(agg.cases)} case(s) / {agg.total_runs} runs**."
    )
    lines.append("")

    # threshold table
    thresholds = [v for v in gate_result.verdicts if v.kind == "threshold"]
    if thresholds:
        lines.append("### Thresholds")
        lines.append("")
        lines.append("| Metric | Current | 95% CI | Required | Verdict |")
        lines.append("|---|---:|---:|---:|---|")
        for v in thresholds:
            cur = f"{v.current:.3f}" if v.current is not None else "n/a"
            if v.metric == "pass_at_k_mean" and agg.pass_at_k_ci is not None:
                ci = f"[{agg.pass_at_k_ci[0]:.3f}, {agg.pass_at_k_ci[1]:.3f}]"
            elif v.metric == "mean_score" and agg.mean_score_ci is not None:
                ci = f"[{agg.mean_score_ci[0]:.3f}, {agg.mean_score_ci[1]:.3f}]"
            else:
                ci = "-"
            lines.append(f"| `{v.metric}` | {cur} | {ci} | min {v.threshold:.3f} "
                         f"| {_status_word(v.status)} |")
        lines.append("")

    # regression table
    regressions = [v for v in gate_result.verdicts if v.kind == "regression"]
    if regressions:
        lines.append("### Regression vs baseline")
        lines.append("")
        lines.append("| Metric | Current [CI] | Baseline [CI] | Band | Verdict |")
        lines.append("|---|---|---|---:|---|")
        for v in regressions:
            cur = (f"{v.current:.3f} [{v.ci_low:.3f}, {v.ci_high:.3f}]"
                   if v.current is not None and v.ci_low is not None else "n/a")
            base = (f"{v.baseline:.3f} [{v.baseline_low:.3f}, {v.baseline_high:.3f}]"
                    if v.baseline is not None and v.baseline_low is not None
                    else (f"{v.baseline:.3f}" if v.baseline is not None else "-"))
            band = f"+/-{v.band:.3f}" if v.band is not None else "-"
            lines.append(f"| `{v.metric}` | {cur} | {base} | {band} "
                         f"| {_status_word(v.status)} |")
        lines.append("")

    # pass@k per case
    lines.append(f"### Pass@{agg.k} by case")
    lines.append("")
    lines.append("| Case | Runs | Passes | Pass rate | pass@" + str(agg.k) + " |")
    lines.append("|---|---:|---:|---:|---:|")
    for c in agg.cases:
        lines.append(
            f"| `{c.name}` | {c.runs} | {c.passes} | {c.pass_rate:.2f} "
            f"| {c.pass_at_k:.3f} |"
        )
    lines.append("")

    if agg.failing_cases:
        lines.append(
            f"Cases not passing every run ({len(agg.failing_cases)}): "
            + ", ".join(f"`{n}`" for n in agg.failing_cases)
        )
        lines.append("")

    if agg.mean_score_ci is not None:
        lines.append(
            f"Mean score {agg.mean_score:.3f}, bootstrap 95% CI "
            f"[{agg.mean_score_ci[0]:.3f}, {agg.mean_score_ci[1]:.3f}] "
            f"(seeded, deterministic)."
        )
        lines.append("")

    if agg.p95_latency_ms is not None:
        lines.append(
            f"P95 latency {agg.p95_latency_ms:.1f} ms "
            f"(p50 {agg.p50_latency_ms:.1f}, max {agg.max_latency_ms:.1f}), "
            f"bootstrap 95% CI [{agg.p95_latency_ci[0]:.1f}, "
            f"{agg.p95_latency_ci[1]:.1f}] ms across {agg.latency_rows} rows."
        )
        lines.append("")

    if agg.total_cost_usd is not None:
        lines.append(
            f"Total cost ${agg.total_cost_usd:.4f} across {agg.cost_rows} rows "
            f"(mean ${agg.mean_cost_usd:.5f})."
        )
        lines.append("")

    if gate_result.notes:
        lines.append("### Notes")
        lines.append("")
        for note in gate_result.notes:
            lines.append(f"- {note}")
        lines.append("")

    if baseline is not None:
        created = baseline.get("created", "unknown")
        sha = baseline.get("git_sha") or "unknown"
        lines.append(
            f"<sub>Baseline: {created} @ `{sha[:10] if isinstance(sha, str) else sha}` "
            f"- SVX EvalGate, green family {_GREEN} {_DARK} {_LIGHT}</sub>"
        )
    else:
        lines.append(
            "<sub>No baseline on record - SVX EvalGate, "
            f"green family {_GREEN} {_DARK} {_LIGHT}</sub>"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(markdown: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
