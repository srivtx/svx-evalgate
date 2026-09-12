"""Property-style tests for the statistics core.

These pin the mathematical behavior an over-production gate must never
regress on: pass@k bounds and monotonicity, Wilson interval containment,
bootstrap determinism, and aggregate invariants.
"""
from __future__ import annotations

import random

import pytest

from evalgate.stats import (
    aggregate,
    bootstrap_ci,
    pass_at_k,
    stable_seed,
    wilson_interval,
)


# --- pass@k -----------------------------------------------------------------

@pytest.mark.parametrize("n,c,k", [
    (10, 0, 1), (10, 10, 3), (10, 5, 1), (20, 7, 5),
    (100, 99, 2), (50, 1, 1), (5, 2, 4), (30, 12, 9),
])
def test_pass_at_k_bounds(n: int, c: int, k: int) -> None:
    v = pass_at_k(n, c, k)
    assert 0.0 <= v <= 1.0


def test_pass_at_k_zero_passes_is_zero() -> None:
    assert pass_at_k(10, 0, 5) == 0.0


def test_pass_at_k_enough_passes_is_one() -> None:
    # c + k > n  =>  every k-subset must contain a pass
    assert pass_at_k(10, 9, 2) == 1.0
    assert pass_at_k(10, 10, 3) == 1.0


def test_pass_at_k_monotonic_in_c() -> None:
    n, k = 20, 5
    prev = pass_at_k(n, 0, k)
    for c in range(1, n + 1):
        cur = pass_at_k(n, c, k)
        assert cur >= prev
        prev = cur


def test_pass_at_k_monotonic_in_k() -> None:
    n, c = 20, 12
    prev = pass_at_k(n, c, 1)
    for k in range(2, n - c + 1):
        cur = pass_at_k(n, c, k)
        assert cur >= prev
        prev = cur


def test_pass_at_k_matches_bruteforce() -> None:
    """Unbiased estimator must equal the empirical probability over all
    k-subsets: 1 - C(n-c, k)/C(n, k) is exact, so compare with the
    combinatorial definition computed another way."""
    import math
    n, c, k = 12, 5, 4
    expected = 1.0 - math.prod((n - c - k + 1 + i) / (n - k + 1 + i)
                               for i in range(k))
    assert abs(pass_at_k(n, c, k) - expected) < 1e-12


@pytest.mark.parametrize("args", [((0, 0, 1)), ((5, -1, 1)), ((5, 6, 1)), ((5, 2, 0)), ((5, 2, 6))])
def test_pass_at_k_rejects_bad_inputs(args: tuple[int, int, int]) -> None:
    n, c, k = args
    with pytest.raises(ValueError):
        pass_at_k(n, c, k)


# --- Wilson ------------------------------------------------------------------

@pytest.mark.parametrize("passes,total", [
    (0, 10), (10, 10), (5, 10), (48, 240), (1, 1000), (999, 1000),
    (79, 100), (29, 100), (96, 100),
])
def test_wilson_contains_point_estimate(passes: int, total: int) -> None:
    lo, hi = wilson_interval(passes, total)
    p = passes / total
    assert lo <= p <= hi


def test_wilson_width_shrinks_with_n() -> None:
    w10 = wilson_interval(7, 10)
    w1000 = wilson_interval(700, 1000)
    assert (w1000[1] - w1000[0]) < (w10[1] - w10[0])


def test_wilson_stays_in_unit_interval() -> None:
    for passes in (0, 1, 2, 8, 9, 10):
        lo, hi = wilson_interval(passes, 10)
        assert 0.0 <= lo <= hi <= 1.0


def test_wilson_degenerate_total() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)


# --- Bootstrap ---------------------------------------------------------------

def test_bootstrap_deterministic() -> None:
    vals = [0.1, 0.4, 0.9, 0.2, 0.55, 0.75, 0.33, 0.61]
    a = bootstrap_ci(vals, iterations=2000, seed=42)
    b = bootstrap_ci(vals, iterations=2000, seed=42)
    assert a == b


def test_bootstrap_seed_changes_interval() -> None:
    vals = [0.1, 0.4, 0.9, 0.2, 0.55]
    a = bootstrap_ci(vals, iterations=2000, seed=1)
    b = bootstrap_ci(vals, iterations=2000, seed=2)
    assert a != b


def test_bootstrap_contains_mean() -> None:
    vals = [0.12, 0.48, 0.93, 0.27, 0.66, 0.51]
    lo, hi = bootstrap_ci(vals, iterations=4000, seed=7)
    mean = sum(vals) / len(vals)
    assert lo <= mean <= hi


def test_bootstrap_constant_input_collapses() -> None:
    lo, hi = bootstrap_ci([0.5] * 30, iterations=500, seed=3)
    assert abs(lo - 0.5) < 1e-9 and abs(hi - 0.5) < 1e-9


def test_stable_seed_is_stable_and_label_sensitive() -> None:
    assert stable_seed(10, "mean_score") == stable_seed(10, "mean_score")
    assert stable_seed(10, "mean_score") != stable_seed(10, "pass_at_k_mean")
    assert stable_seed(10, "m") != stable_seed(11, "m")


# --- Aggregate ---------------------------------------------------------------

def _rows(rng: random.Random, cases: int, runs: int, quality: float) -> list[dict]:
    rows = []
    for c in range(cases):
        for _ in range(runs):
            rows.append({
                "case": f"case-{c}",
                "passed": rng.random() < quality,
                "score": round(rng.uniform(0, 1), 3),
            })
    return rows


def test_aggregate_counts_and_ordering() -> None:
    rng = random.Random(0)
    rows = _rows(rng, cases=5, runs=8, quality=0.8)
    agg = aggregate(rows, k=3, base_seed=1, bootstrap_iterations=500)
    assert agg.total_runs == 40
    assert [c.name for c in agg.cases] == sorted(c.name for c in agg.cases)
    assert agg.total_passes == sum(c.passes for c in agg.cases)
    assert agg.pass_rate == agg.total_passes / agg.total_runs


def test_aggregate_ci_brackets_point_estimates() -> None:
    rng = random.Random(5)
    rows = _rows(rng, cases=12, runs=20, quality=0.7)
    agg = aggregate(rows, k=5, base_seed=9, bootstrap_iterations=2000)
    assert agg.pass_at_k_ci[0] <= agg.pass_at_k_mean <= agg.pass_at_k_ci[1]
    assert agg.pass_rate_ci[0] <= agg.pass_rate <= agg.pass_rate_ci[1]
    assert agg.mean_score_ci[0] <= agg.mean_score <= agg.mean_score_ci[1]


def test_aggregate_is_deterministic() -> None:
    rng1, rng2 = random.Random(3), random.Random(3)
    rows_a = _rows(rng1, cases=6, runs=10, quality=0.6)
    rows_b = _rows(rng2, cases=6, runs=10, quality=0.6)
    a = aggregate(rows_a, k=3, base_seed=77, bootstrap_iterations=1000)
    b = aggregate(rows_b, k=3, base_seed=77, bootstrap_iterations=1000)
    assert a.pass_at_k_ci == b.pass_at_k_ci
    assert a.mean_score_ci == b.mean_score_ci


def test_aggregate_failing_cases_flags_partial_passes() -> None:
    rows = [
        {"case": "always-pass", "passed": True},
        {"case": "always-pass", "passed": True},
        {"case": "sometimes", "passed": True},
        {"case": "sometimes", "passed": False},
        {"case": "never", "passed": False},
    ]
    agg = aggregate(rows, k=1, base_seed=0, bootstrap_iterations=100)
    assert agg.failing_cases == ["never", "sometimes"]


def test_aggregate_metric_lookup_rejects_unknown() -> None:
    rng = random.Random(1)
    agg = aggregate(_rows(rng, 2, 4, 0.5), k=1, base_seed=0,
                    bootstrap_iterations=100)
    with pytest.raises(KeyError):
        agg.metric_value("not_a_metric")
    with pytest.raises(KeyError):
        agg.metric_ci("not_a_metric")
