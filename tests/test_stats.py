"""Tests for evalgate.stats: pass@k, Wilson, bootstrap, aggregation."""
import math
from itertools import pairwise

import pytest

from evalgate import stats


class TestPassAtK:
    def test_perfect_case(self):
        assert stats.pass_at_k(20, 20, 1) == 1.0

    def test_zero_passes(self):
        assert stats.pass_at_k(20, 0, 1) == 0.0
        assert stats.pass_at_k(20, 0, 5) == 0.0

    def test_closed_form_small(self):
        # n=4, c=2, k=1: 1 - C(2,1)/C(4,1) = 1 - 2/4 = 0.5
        assert stats.pass_at_k(4, 2, 1) == pytest.approx(0.5)
        # n=4, c=2, k=2: 1 - C(2,2)/C(4,2) = 1 - 1/6
        assert stats.pass_at_k(4, 2, 2) == pytest.approx(1 - 1 / 6)

    def test_matches_simulation(self):
        # Cross-check against a large exact enumeration via binomial logic:
        # p(pass in one run) = c/n; P(at least one pass in k) = 1-(1-c/n)^k
        # is the *biased* estimator; pass@k is unbiased w.r.t. the sample.
        # For an independent check, use the identity when k = n: pass@n = 1
        # iff c > 0.
        assert stats.pass_at_k(10, 1, 10) == pytest.approx(1.0)
        assert stats.pass_at_k(10, 0, 10) == pytest.approx(0.0)

    def test_monotone_in_c(self):
        values = [stats.pass_at_k(30, c, 3) for c in range(31)]
        assert all(b >= a for a, b in pairwise(values))

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            stats.pass_at_k(0, 0, 1)
        with pytest.raises(ValueError):
            stats.pass_at_k(10, 11, 1)
        with pytest.raises(ValueError):
            stats.pass_at_k(10, 5, 0)
        with pytest.raises(ValueError):
            stats.pass_at_k(10, 5, 11)


class TestWilson:
    def test_bounds_contain_point_estimate(self):
        lo, hi = stats.wilson_interval(70, 100)
        assert lo <= 0.70 <= hi
        assert 0.0 < lo < hi < 1.0

    def test_extremes(self):
        assert stats.wilson_interval(0, 0) == (0.0, 1.0)
        lo, hi = stats.wilson_interval(100, 100)
        assert lo > 0.9 and hi == pytest.approx(1.0)

    def test_width_shrinks_with_n(self):
        w50 = stats.wilson_interval(35, 50)
        w500 = stats.wilson_interval(350, 500)
        assert (w500[1] - w500[0]) < (w50[1] - w50[0])


class TestBootstrap:
    def test_deterministic(self):
        vals = [0.1, 0.4, 0.9, 0.55, 0.62, 0.3]
        a = stats.bootstrap_ci(vals, iterations=2000, seed=42)
        b = stats.bootstrap_ci(vals, iterations=2000, seed=42)
        assert a == b

    def test_contains_mean(self):
        vals = [0.2, 0.5, 0.5, 0.8]
        lo, hi = stats.bootstrap_ci(vals, iterations=5000, seed=7)
        mean = sum(vals) / len(vals)
        assert lo <= mean <= hi

    def test_empty(self):
        assert stats.bootstrap_ci([]) == (0.0, 1.0)

    def test_stable_seed_is_stable_and_label_sensitive(self):
        assert stats.stable_seed(100, "mean_score") == stats.stable_seed(100, "mean_score")
        assert stats.stable_seed(100, "mean_score") != stats.stable_seed(100, "pass_rate")
        assert stats.stable_seed(100, "mean_score") != stats.stable_seed(101, "mean_score")


def _row(case, passed, score=None):
    return {"case": case, "passed": passed, "score": score}


class TestAggregate:
    def test_basic_aggregation(self):
        rows = [
            _row("a", True, 0.9), _row("a", True, 0.8), _row("a", False, 0.3),
            _row("b", True, 0.7), _row("b", True, 0.75),
        ]
        agg = stats.aggregate(rows, k=1, base_seed=1, bootstrap_iterations=500)
        assert agg.total_runs == 5
        assert agg.total_passes == 4
        case_a = next(c for c in agg.cases if c.name == "a")
        assert case_a.runs == 3 and case_a.passes == 2
        assert case_a.pass_at_k == pytest.approx(2 / 3)
        assert case_a.mean_score == pytest.approx((0.9 + 0.8 + 0.3) / 3)
        assert agg.pass_at_k_mean == pytest.approx((2 / 3 + 1.0) / 2)
        assert agg.pass_rate == pytest.approx(4 / 5)
        assert agg.mean_score == pytest.approx(sum(r["score"] for r in rows) / 5)
        assert "a" in agg.failing_cases and "b" not in agg.failing_cases
        assert agg.mean_score_ci is not None and agg.mean_score_ci[0] < agg.mean_score_ci[1]

    def test_rows_without_scores(self):
        rows = [_row("a", True), _row("a", False)]
        agg = stats.aggregate(rows, k=1, base_seed=1)
        assert agg.mean_score is None
        assert agg.mean_score_ci is None

    def test_pass_at_k_k2(self):
        # 10 runs, 6 passes, k=2: 1 - C(4,2)/C(10,2) = 1 - 6/45
        rows = [_row("x", i < 6) for i in range(10)]
        agg = stats.aggregate(rows, k=2, base_seed=1)
        assert agg.cases[0].pass_at_k == pytest.approx(1 - math.comb(4, 2) / math.comb(10, 2))

    def test_aggregate_is_order_insensitive(self):
        rows = [_row("a", True, 0.5), _row("b", False, 0.2), _row("a", False, 0.4)]
        reversed_rows = list(reversed(rows))
        a1 = stats.aggregate(rows, k=1, base_seed=9, bootstrap_iterations=300)
        a2 = stats.aggregate(reversed_rows, k=1, base_seed=9, bootstrap_iterations=300)
        assert a1.pass_at_k_mean == pytest.approx(a2.pass_at_k_mean)
        assert a1.mean_score == pytest.approx(a2.mean_score)
        assert a1.mean_score_ci == a2.mean_score_ci


class TestPercentile:
    def test_known_values(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert stats.percentile(values, 0) == 1.0
        assert stats.percentile(values, 50) == 5.0
        assert stats.percentile(values, 90) == 9.0
        assert stats.percentile(values, 100) == 10.0

    def test_single_value(self):
        assert stats.percentile([7.5], 95) == 7.5

    def test_unsorted_input(self):
        # nearest-rank on even n picks the lower-middle element (no interpolation)
        assert stats.percentile([5.0, 1.0, 9.0, 3.0], 50) == 3.0

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            stats.percentile([], 50)

    def test_bad_q_raises(self):
        with pytest.raises(ValueError):
            stats.percentile([1.0], 101)
        with pytest.raises(ValueError):
            stats.percentile([1.0], -1)

    def test_deterministic(self):
        vals = [float(i % 13) for i in range(97)]
        assert stats.percentile(vals, 95) == stats.percentile(vals, 95)


class TestBootstrapPercentileCI:
    def test_contains_point_estimate(self):
        rng_vals = [0.1 * (i % 21) for i in range(120)]
        p95 = stats.percentile(rng_vals, 95)
        lo, hi = stats.bootstrap_percentile_ci(rng_vals, 95, iterations=400, seed=3)
        assert lo <= p95 <= hi
        assert lo < hi

    def test_deterministic_given_seed(self):
        vals = [float(i % 17) for i in range(60)]
        a = stats.bootstrap_percentile_ci(vals, 95, iterations=200, seed=5)
        b = stats.bootstrap_percentile_ci(vals, 95, iterations=200, seed=5)
        assert a == b

    def test_different_seed_different_interval(self):
        vals = [float(i % 17) for i in range(60)]
        a = stats.bootstrap_percentile_ci(vals, 95, iterations=200, seed=5)
        b = stats.bootstrap_percentile_ci(vals, 95, iterations=200, seed=6)
        assert a != b

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            stats.bootstrap_percentile_ci([], 95)


class TestLatencyCostAggregation:
    ROWS = (
        {"case": "a", "passed": True, "score": 0.9,
         "latency_ms": 100.0, "cost_usd": 0.001},
        {"case": "a", "passed": True, "score": 0.8,
         "latency_ms": 300.0, "cost_usd": 0.002},
        {"case": "b", "passed": False, "score": 0.3,
         "latency_ms": 200.0, "cost_usd": 0.001},
        {"case": "b", "passed": True, "score": 0.7,
         "latency_ms": 400.0, "cost_usd": 0.003},
        {"case": "c", "passed": True},   # no latency/cost at all
    )

    def test_latency_stats(self):
        agg = stats.aggregate(self.ROWS, k=1, base_seed=1, bootstrap_iterations=300)
        assert agg.latency_rows == 4
        assert agg.mean_latency_ms == pytest.approx(250.0)
        # nearest-rank p50 of [100, 200, 300, 400] = 200 (lower middle)
        assert agg.p50_latency_ms == pytest.approx(200.0)
        assert agg.p95_latency_ms == pytest.approx(400.0)
        assert agg.max_latency_ms == pytest.approx(400.0)
        assert agg.mean_latency_ci[0] < agg.mean_latency_ci[1]
        assert agg.p95_latency_ci[0] <= agg.p95_latency_ms <= agg.p95_latency_ci[1]
        assert len(agg.latency_values) == 4

    def test_cost_stats(self):
        agg = stats.aggregate(self.ROWS, k=1, base_seed=1, bootstrap_iterations=300)
        assert agg.cost_rows == 4
        assert agg.total_cost_usd == pytest.approx(0.007, abs=1e-12)
        assert agg.mean_cost_usd == pytest.approx(0.00175, abs=1e-12)
        assert agg.total_cost_ci[0] < agg.total_cost_usd < agg.total_cost_ci[1]

    def test_score_distribution(self):
        agg = stats.aggregate(self.ROWS, k=1, base_seed=1, bootstrap_iterations=300)
        # nearest-rank p50 of [0.3, 0.7, 0.8, 0.9] = 0.7 (lower middle)
        assert agg.score_p50 == pytest.approx(0.7)
        assert agg.score_p95 == pytest.approx(0.9)
        assert agg.score_min == pytest.approx(0.3)
        assert agg.score_max == pytest.approx(0.9)
        assert len(agg.score_values) == 4

    def test_metric_accessors(self):
        agg = stats.aggregate(self.ROWS, k=1, base_seed=1, bootstrap_iterations=300)
        assert agg.metric_value("p95_latency_ms") == pytest.approx(400.0)
        assert agg.metric_value("total_cost_usd") == pytest.approx(0.007, abs=1e-12)
        assert agg.metric_ci("p95_latency_ms") == agg.p95_latency_ci
        assert agg.metric_ci("total_cost_usd") == agg.total_cost_ci
        with pytest.raises(KeyError):
            agg.metric_value("nope")
        with pytest.raises(KeyError):
            agg.metric_ci("nope")

    def test_absent_latency_and_cost(self):
        rows = [{"case": "a", "passed": True}, {"case": "a", "passed": False}]
        agg = stats.aggregate(rows, k=1, base_seed=1, bootstrap_iterations=100)
        assert agg.latency_rows == 0
        assert agg.p95_latency_ms is None
        assert agg.p95_latency_ci is None
        assert agg.total_cost_usd is None
        assert agg.total_cost_ci is None
        assert agg.metric_value("p95_latency_ms") is None

    def test_latency_deterministic(self):
        a = stats.aggregate(self.ROWS, k=1, base_seed=11, bootstrap_iterations=300)
        b = stats.aggregate(self.ROWS, k=1, base_seed=11, bootstrap_iterations=300)
        assert a.p95_latency_ci == b.p95_latency_ci
        assert a.total_cost_ci == b.total_cost_ci
