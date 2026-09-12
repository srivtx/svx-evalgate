"""Tests for evalgate.stats: pass@k, Wilson, bootstrap, aggregation."""
import math

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
        values = [stats.pass_at_k(30, c, 3) for c in range(0, 31)]
        assert all(b >= a for a, b in zip(values, values[1:]))

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
