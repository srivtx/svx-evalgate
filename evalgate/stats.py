"""Statistics for non-deterministic evals.

Everything here is deterministic: pass@k is combinatorial (closed form),
Wilson intervals are closed form, and the bootstrap is seeded from a
stable digest of (base_seed, metric name) so the same inputs always
produce the same interval.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# pass@k - unbiased estimator (Chen et al., 2021, "Codex"/HumanEval)
# ---------------------------------------------------------------------------
def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that a case passes at least once in k random runs.

    n = total runs executed, c = runs that passed (0 <= c <= n), k <= n.
    Unbiased closed form: 1 - C(n-c, k) / C(n, k).
    """
    if n <= 0:
        raise ValueError("n must be positive")
    if c < 0 or c > n:
        raise ValueError("c out of range [0, n]")
    if k <= 0 or k > n:
        raise ValueError("k out of range (0, n]")
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


# ---------------------------------------------------------------------------
# Wilson score interval - closed-form CI for a pass rate
# ---------------------------------------------------------------------------
def wilson_interval(passes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% (z=1.96) Wilson score interval for a binomial proportion.

    The interval is mathematically confined to [0, 1]; the final clamp
    removes floating-point overshoot (e.g. 1.0000000000000002).
    """
    if total <= 0:
        return 0.0, 1.0
    p = passes / total
    denom = 1.0 + z * z / total
    centre = p + z * z / (2.0 * total)
    margin = z * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total))
    lo = max(0.0, (centre - margin) / denom)
    hi = min(1.0, (centre + margin) / denom)
    return lo, hi


# ---------------------------------------------------------------------------
# Seeded bootstrap CI for a mean
# ---------------------------------------------------------------------------
def stable_seed(base_seed: int, label: str) -> int:
    """Deterministic sub-seed from (base_seed, label); never uses hash()."""
    digest = hashlib.sha256(f"{int(base_seed)}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def bootstrap_ci(
    values: list[float],
    alpha: float = 0.05,
    iterations: int = 10000,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean of `values`.

    Deterministic given `seed`. Returns (low, high) covering 1-alpha.
    """
    if not values:
        return 0.0, 1.0
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    randrange = rng.randrange
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += values[randrange(n)]
        means.append(total / n)
    means.sort()
    lo_idx = max(0, min(math.ceil((alpha / 2.0) * iterations) - 1, iterations - 1))
    hi_idx = max(0, min(math.ceil((1.0 - alpha / 2.0) * iterations) - 1, iterations - 1))
    return means[lo_idx], means[hi_idx]


# ---------------------------------------------------------------------------
# Percentile (nearest-rank) and bootstrap CI for a percentile
# ---------------------------------------------------------------------------
def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile of `values`; q is in [0, 100].

    Deterministic, allocation-light, and identical across platforms
    (no floating-point interpolation, just a sort and an index).
    """
    if not values:
        raise ValueError("values must be non-empty")
    if q < 0.0 or q > 100.0:
        raise ValueError("q must be within [0, 100]")
    ordered = sorted(values)
    idx = max(0, min(math.ceil(q / 100.0 * len(ordered)) - 1, len(ordered) - 1))
    return ordered[idx]


def bootstrap_percentile_ci(
    values: list[float],
    q: float,
    alpha: float = 0.05,
    iterations: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the q-th percentile of `values`.

    Deterministic given `seed`. Iterations are capped by the caller for
    latency-style metrics because each resample costs a sort.
    """
    if not values:
        raise ValueError("values must be non-empty")
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    rng = random.Random(seed)
    n = len(values)
    randrange = rng.randrange
    stats: list[float] = []
    for _ in range(iterations):
        sample = sorted(values[randrange(n)] for _ in range(n))
        idx = max(0, min(math.ceil(q / 100.0 * n) - 1, n - 1))
        stats.append(sample[idx])
    stats.sort()
    lo_idx = max(0, min(math.ceil((alpha / 2.0) * iterations) - 1, iterations - 1))
    hi_idx = max(0, min(math.ceil((1.0 - alpha / 2.0) * iterations) - 1, iterations - 1))
    return stats[lo_idx], stats[hi_idx]


# ---------------------------------------------------------------------------
# Aggregate statistics over collected eval rows
# ---------------------------------------------------------------------------
@dataclass
class CaseStats:
    name: str
    runs: int
    passes: int
    pass_at_k: float
    mean_score: float | None = None

    @property
    def pass_rate(self) -> float:
        return self.passes / self.runs if self.runs else 0.0


@dataclass
class AggregateStats:
    """Everything the gate needs, computed once per run."""

    cases: list[CaseStats] = field(default_factory=list)
    k: int = 1
    pass_at_k_mean: float | None = None      # mean of per-case pass@k
    pass_at_k_ci: tuple[float, float] | None = None
    pass_rate: float | None = None           # passes / total runs
    pass_rate_ci: tuple[float, float] | None = None
    mean_score: float | None = None          # mean of all row scores
    mean_score_ci: tuple[float, float] | None = None
    # score distribution (v2)
    score_p50: float | None = None
    score_p95: float | None = None
    score_min: float | None = None
    score_max: float | None = None
    # latency, milliseconds (v2): per-row optional "latency_ms" field
    mean_latency_ms: float | None = None
    mean_latency_ci: tuple[float, float] | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    p95_latency_ci: tuple[float, float] | None = None
    max_latency_ms: float | None = None
    latency_rows: int = 0
    # cost, dollars (v2): per-row optional "cost_usd" field
    total_cost_usd: float | None = None
    mean_cost_usd: float | None = None
    total_cost_ci: tuple[float, float] | None = None
    cost_rows: int = 0
    # raw values retained for distribution charts (v2)
    score_values: list[float] = field(default_factory=list)
    latency_values: list[float] = field(default_factory=list)
    total_runs: int = 0
    total_passes: int = 0
    failing_cases: list[str] = field(default_factory=list)  # cases with c < n

    _METRIC_NAMES = (
        "pass_at_k_mean", "pass_rate", "mean_score",
        "p95_latency_ms", "total_cost_usd",
    )

    def metric_value(self, name: str) -> float | None:
        if name == "pass_at_k_mean":
            return self.pass_at_k_mean
        if name == "pass_rate":
            return self.pass_rate
        if name == "mean_score":
            return self.mean_score
        if name == "p95_latency_ms":
            return self.p95_latency_ms
        if name == "total_cost_usd":
            return self.total_cost_usd
        raise KeyError(f"unknown metric: {name}")

    def metric_ci(self, name: str) -> tuple[float, float] | None:
        if name == "pass_at_k_mean":
            return self.pass_at_k_ci
        if name == "pass_rate":
            return self.pass_rate_ci
        if name == "mean_score":
            return self.mean_score_ci
        if name == "p95_latency_ms":
            return self.p95_latency_ci
        if name == "total_cost_usd":
            return self.total_cost_ci
        raise KeyError(f"unknown metric: {name}")


def aggregate(rows: list[dict], k: int, base_seed: int,
              bootstrap_iterations: int = 10000) -> AggregateStats:
    """Compute aggregate statistics from eval rows.

    Each row: {"case": str, "passed": bool, "score": float|null,
                "latency_ms": float>=0|null, "cost_usd": float>=0|null, ...}
    Rows may arrive in any order; grouping is by "case".
    """
    by_case: dict[str, list[dict]] = {}
    for row in rows:
        name = str(row["case"])
        by_case.setdefault(name, []).append(row)

    cases: list[CaseStats] = []
    for name in sorted(by_case):
        case_rows = by_case[name]
        runs = len(case_rows)
        passes = sum(1 for r in case_rows if r["passed"])
        scores = [float(r["score"]) for r in case_rows if r.get("score") is not None]
        mean_score = (sum(scores) / len(scores)) if scores else None
        cases.append(CaseStats(
            name=name, runs=runs, passes=passes,
            pass_at_k=pass_at_k(runs, passes, min(k, runs)),
            mean_score=mean_score,
        ))

    agg = AggregateStats(cases=cases, k=k)
    agg.total_runs = sum(c.runs for c in cases)
    agg.total_passes = sum(c.passes for c in cases)
    agg.failing_cases = [c.name for c in cases if c.passes < c.runs]

    if cases:
        pk_values = [c.pass_at_k for c in cases]
        agg.pass_at_k_mean = sum(pk_values) / len(pk_values)
        agg.pass_at_k_ci = bootstrap_ci(
            pk_values, iterations=bootstrap_iterations,
            seed=stable_seed(base_seed, "pass_at_k_mean"),
        )
    if agg.total_runs:
        agg.pass_rate = agg.total_passes / agg.total_runs
        agg.pass_rate_ci = wilson_interval(agg.total_passes, agg.total_runs)

    all_scores = [float(r["score"]) for r in rows if r.get("score") is not None]
    if all_scores:
        agg.mean_score = sum(all_scores) / len(all_scores)
        agg.mean_score_ci = bootstrap_ci(
            all_scores, iterations=bootstrap_iterations,
            seed=stable_seed(base_seed, "mean_score"),
        )
        agg.score_p50 = percentile(all_scores, 50)
        agg.score_p95 = percentile(all_scores, 95)
        agg.score_min = min(all_scores)
        agg.score_max = max(all_scores)

    agg.score_values = all_scores

    latencies = [float(r["latency_ms"]) for r in rows if r.get("latency_ms") is not None]
    agg.latency_values = latencies
    if latencies:
        n_lat = len(latencies)
        agg.latency_rows = n_lat
        agg.mean_latency_ms = sum(latencies) / n_lat
        agg.p50_latency_ms = percentile(latencies, 50)
        agg.p95_latency_ms = percentile(latencies, 95)
        agg.max_latency_ms = max(latencies)
        agg.mean_latency_ci = bootstrap_ci(
            latencies, iterations=bootstrap_iterations,
            seed=stable_seed(base_seed, "mean_latency_ms"),
        )
        # percentile CIs cost a sort per resample; cap the budget so gated
        # runs stay fast (still deterministic given the seed).
        agg.p95_latency_ci = bootstrap_percentile_ci(
            latencies, 95,
            iterations=min(bootstrap_iterations, 2000),
            seed=stable_seed(base_seed, "p95_latency_ms"),
        )

    costs = [float(r["cost_usd"]) for r in rows if r.get("cost_usd") is not None]
    if costs:
        n_cost = len(costs)
        agg.cost_rows = n_cost
        agg.total_cost_usd = sum(costs)
        agg.mean_cost_usd = agg.total_cost_usd / n_cost
        mean_lo, mean_hi = bootstrap_ci(
            costs, iterations=bootstrap_iterations,
            seed=stable_seed(base_seed, "mean_cost_usd"),
        )
        agg.total_cost_ci = (mean_lo * n_cost, mean_hi * n_cost)
    return agg
