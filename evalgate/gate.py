"""The gate: thresholds + regression bands -> one green-or-red verdict."""
from __future__ import annotations

from dataclasses import dataclass, field

from .baseline import TRACKED_METRICS

PASS = "pass"
REGRESSION = "regression"
IMPROVED = "improved"
FAIL = "fail"
NA = "n/a"

# Metrics where smaller is better: regression means the current interval
# sits entirely ABOVE the baseline interval plus the band. For everything
# else (rates, scores) regression means entirely BELOW.
LOWER_IS_BETTER = frozenset({"p95_latency_ms", "total_cost_usd"})


@dataclass
class MetricVerdict:
    metric: str
    kind: str          # "threshold" | "regression"
    current: float | None
    ci_low: float | None = None
    ci_high: float | None = None
    threshold: float | None = None     # for kind=threshold
    baseline: float | None = None      # for kind=regression
    baseline_low: float | None = None
    baseline_high: float | None = None
    band: float | None = None          # for kind=regression
    status: str = NA
    detail: str = ""


@dataclass
class GateResult:
    green: bool = True
    verdicts: list[MetricVerdict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def reasons(self) -> list[str]:
        return [v.detail for v in self.verdicts if v.status in (FAIL, REGRESSION)]


def _bounds(agg, metric: str) -> tuple[float | None, float | None]:
    """(low, high) confidence bounds for a metric; degenerate (v, v)
    when no interval is available."""
    ci = agg.metric_ci(metric) if hasattr(agg, "metric_ci") else None
    if ci is not None:
        return ci[0], ci[1]
    value = agg.metric_value(metric)
    return value, value


def evaluate(agg, config, baseline: dict | None) -> GateResult:
    """Evaluate thresholds and (if a baseline exists) regression bands.

    Threshold checks use point estimates. Regression checks compare
    confidence intervals: a run is REGRESSION only when its entire
    interval sits below the baseline's interval minus the tolerance
    band - i.e. the current run is *confidently* worse than the
    baseline by more than the band. Overlapping intervals are PASS,
    which is what keeps non-deterministic suites from flapping the
    check; an interval fully above the baseline plus band is IMPROVED.
    """
    result = GateResult()
    gate = config.gate
    reg = gate.regression

    # --- threshold checks (always active) ---
    if gate.min_pass_at_k is not None:
        value = agg.pass_at_k_mean
        if value is None:
            result.notes.append("pass@k not computable (no cases)")
        else:
            ok = value >= gate.min_pass_at_k
            v = MetricVerdict(
                metric="pass_at_k_mean", kind="threshold", current=value,
                threshold=gate.min_pass_at_k,
                status=PASS if ok else FAIL,
                detail=(f"pass@{gate.k} mean {value:.3f} "
                        f"{'>=' if ok else '<'} threshold {gate.min_pass_at_k:.3f}"),
            )
            result.verdicts.append(v)
            if not ok:
                result.green = False

    if gate.min_mean_score is not None:
        value = agg.mean_score
        if value is None:
            result.notes.append("mean_score not computable (evals emitted no scores)")
        else:
            ok = value >= gate.min_mean_score
            v = MetricVerdict(
                metric="mean_score", kind="threshold", current=value,
                threshold=gate.min_mean_score,
                status=PASS if ok else FAIL,
                detail=(f"mean score {value:.3f} "
                        f"{'>=' if ok else '<'} threshold {gate.min_mean_score:.3f}"),
            )
            result.verdicts.append(v)
            if not ok:
                result.green = False

    # --- v2 thresholds: upper bounds (latency / cost) ---
    if gate.max_p95_latency_ms is not None:
        value = agg.p95_latency_ms
        if value is None:
            result.notes.append(
                "p95 latency not computable (evals emitted no latency_ms)")
        else:
            ok = value <= gate.max_p95_latency_ms
            v = MetricVerdict(
                metric="p95_latency_ms", kind="threshold", current=value,
                threshold=gate.max_p95_latency_ms,
                status=PASS if ok else FAIL,
                detail=(f"p95 latency {value:.1f} ms "
                        f"{'<=' if ok else '>'} max {gate.max_p95_latency_ms:.1f} ms"),
            )
            result.verdicts.append(v)
            if not ok:
                result.green = False

    if gate.max_total_cost_usd is not None:
        value = agg.total_cost_usd
        if value is None:
            result.notes.append(
                "total cost not computable (evals emitted no cost_usd)")
        else:
            ok = value <= gate.max_total_cost_usd
            v = MetricVerdict(
                metric="total_cost_usd", kind="threshold", current=value,
                threshold=gate.max_total_cost_usd,
                status=PASS if ok else FAIL,
                detail=(f"total cost ${value:.4f} "
                        f"{'<=' if ok else '>'} max ${gate.max_total_cost_usd:.4f}"),
            )
            result.verdicts.append(v)
            if not ok:
                result.green = False

    # --- regression checks (only when a baseline exists) ---
    if baseline is None:
        result.notes.append(
            "no baseline present - threshold checks only "
            "(run with --update-baseline to establish one)"
        )
        return result

    if baseline.get("config_hash") and config.config_hash() != baseline["config_hash"]:
        result.notes.append(
            "gate configuration changed since the baseline was recorded "
            "(config_hash mismatch); consider refreshing the baseline"
        )

    base_metrics = baseline.get("metrics", {})
    for metric in TRACKED_METRICS:
        base_entry = base_metrics.get(metric)
        cur_value = agg.metric_value(metric) if hasattr(agg, "metric_value") else None
        if base_entry is None or cur_value is None:
            continue
        # Baseline entries carry {value, low, high}; plain floats (older
        # baselines) degrade to a degenerate interval.
        if isinstance(base_entry, dict):
            base_value = base_entry.get("value")
            base_low = base_entry.get("low", base_value)
            base_high = base_entry.get("high", base_value)
        else:
            base_value = float(base_entry)
            base_low = base_high = base_value
        if base_value is None:
            continue
        cur_low, cur_high = _bounds(agg, metric)
        if cur_low is None or cur_high is None:
            cur_low = cur_high = cur_value
        if reg.mode == "relative":
            band = abs(base_value) * reg.tolerance
        else:
            band = reg.tolerance
        if metric in LOWER_IS_BETTER:
            # Worse = slower / costlier: current interval entirely ABOVE.
            if cur_low > base_high + band:
                status = REGRESSION
            elif cur_high < base_low - band:
                status = IMPROVED
            else:
                status = PASS
        else:
            # Worse = lower quality: current interval entirely BELOW.
            if cur_high < base_low - band:
                status = REGRESSION
            elif cur_low > base_high + band:
                status = IMPROVED
            else:
                status = PASS
        v = MetricVerdict(
            metric=metric, kind="regression", current=cur_value,
            ci_low=cur_low, ci_high=cur_high,
            baseline=base_value, baseline_low=base_low, baseline_high=base_high,
            band=band, status=status,
            detail=(f"{metric}: current [{cur_low:.3f}, {cur_high:.3f}] vs "
                    f"baseline [{base_low:.3f}, {base_high:.3f}] "
                    f"(band +/-{band:.3f}) -> {status}"),
        )
        result.verdicts.append(v)
        if status == REGRESSION:
            result.green = False

    return result
