"""Tests for the gate: thresholds and regression bands."""
import pytest

from evalgate import gate as gate_mod
from evalgate import stats


def _agg_from_metrics(pass_at_k_mean, mean_score, pak_ci=None, ms_ci=None):
    class FakeAgg:
        pass
    agg = FakeAgg()
    agg.pass_at_k_mean = pass_at_k_mean
    agg.mean_score = mean_score
    agg.pass_at_k_mean_ci = pak_ci
    agg.pass_at_k_ci = pak_ci or (
        (pass_at_k_mean, pass_at_k_mean) if pass_at_k_mean is not None else None)
    agg.mean_score_ci = ms_ci or ((mean_score, mean_score) if mean_score is not None else None)
    agg.pass_rate = pass_at_k_mean
    agg.pass_rate_ci = agg.pass_at_k_ci

    def metric_value(name):
        return {"pass_at_k_mean": agg.pass_at_k_mean,
                "mean_score": agg.mean_score,
                "pass_rate": agg.pass_rate}.get(name)

    def metric_ci(name):
        return {"pass_at_k_mean": agg.pass_at_k_ci,
                "mean_score": agg.mean_score_ci,
                "pass_rate": agg.pass_rate_ci}.get(name)

    agg.metric_value = metric_value
    agg.metric_ci = metric_ci
    return agg


def _cfg(min_pass_at_k=0.85, min_mean_score=None, tol=0.05, mode="absolute"):
    from evalgate import config as config_mod
    return config_mod.Config(
        gate=config_mod.GateConfig(
            k=1, min_pass_at_k=min_pass_at_k, min_mean_score=min_mean_score,
            regression=config_mod.RegressionConfig(mode=mode, tolerance=tol),
        ),
    )


class TestThresholds:
    def test_pass_above_threshold(self):
        agg = _agg_from_metrics(0.92, 0.8)
        result = gate_mod.evaluate(agg, _cfg(), baseline=None)
        assert result.green
        assert result.verdicts[0].status == gate_mod.PASS

    def test_fail_below_threshold(self):
        agg = _agg_from_metrics(0.70, 0.8)
        result = gate_mod.evaluate(agg, _cfg(), baseline=None)
        assert not result.green
        assert result.verdicts[0].status == gate_mod.FAIL

    def test_no_baseline_note(self):
        agg = _agg_from_metrics(0.92, 0.8)
        result = gate_mod.evaluate(agg, _cfg(), baseline=None)
        assert any("no baseline" in n for n in result.notes)

    def test_mean_score_threshold(self):
        agg = _agg_from_metrics(0.9, 0.60)
        result = gate_mod.evaluate(agg, _cfg(min_mean_score=0.7), baseline=None)
        assert not result.green

    def test_missing_metrics_degrade_to_notes(self):
        agg = _agg_from_metrics(None, None)
        result = gate_mod.evaluate(agg, _cfg(min_mean_score=0.7), baseline=None)
        assert result.green  # nothing computable -> nothing failing
        assert result.notes


class TestRegression:
    """Interval-vs-interval semantics: REGRESSION requires the current
    run's entire CI to sit below the baseline CI minus the band."""

    def _baseline(self, pass_at_k=0.90, mean=0.88, with_ci=True):
        def entry(value):
            if value is None:
                return None
            if not with_ci:
                return value
            return {"value": value, "low": value - 0.02, "high": value + 0.02}
        return {"schema_version": 1, "config_hash": None, "metrics": {
            "pass_at_k_mean": entry(pass_at_k),
            "mean_score": entry(mean),
            "pass_rate": entry(pass_at_k),
        }}

    def test_unchanged_system_stays_green(self):
        # identical distributions: CIs overlap exactly -> PASS
        agg = _agg_from_metrics(0.90, 0.88,
                                pak_ci=(0.88, 0.92), ms_ci=(0.86, 0.90))
        result = gate_mod.evaluate(agg, _cfg(), baseline=self._baseline())
        assert result.green
        regressions = [v for v in result.verdicts if v.kind == "regression"]
        assert regressions and all(v.status == gate_mod.PASS for v in regressions)

    def test_noise_inside_band_stays_green(self):
        # slight wobble, intervals overlap -> PASS
        agg = _agg_from_metrics(0.88, 0.86,
                                pak_ci=(0.85, 0.91), ms_ci=(0.83, 0.89))
        result = gate_mod.evaluate(agg, _cfg(), baseline=self._baseline())
        assert result.green

    def test_confident_regression_goes_red(self):
        # current CI entirely below baseline CI low minus band
        agg = _agg_from_metrics(0.75, 0.70,
                                pak_ci=(0.72, 0.78), ms_ci=(0.67, 0.73))
        result = gate_mod.evaluate(agg, _cfg(), baseline=self._baseline())
        assert not result.green
        assert any(v.status == gate_mod.REGRESSION for v in result.verdicts)
        # reasons mention intervals
        assert any("[" in r for r in result.reasons())

    def test_partial_regression_single_metric(self):
        # pass@k confidently worse, score fine
        agg = _agg_from_metrics(0.70, 0.88,
                                pak_ci=(0.67, 0.73), ms_ci=(0.86, 0.90))
        result = gate_mod.evaluate(agg, _cfg(), baseline=self._baseline())
        assert not result.green
        regressed = {v.metric for v in result.verdicts if v.status == gate_mod.REGRESSION}
        assert "pass_at_k_mean" in regressed and "mean_score" not in regressed

    def test_improvement_detected_is_green(self):
        agg = _agg_from_metrics(0.99, 0.99,
                                pak_ci=(0.96, 1.0), ms_ci=(0.95, 1.0))
        result = gate_mod.evaluate(agg, _cfg(),
                                   baseline=self._baseline(pass_at_k=0.80, mean=0.70))
        assert result.green
        assert any(v.status == gate_mod.IMPROVED for v in result.verdicts)

    def test_relative_band(self):
        # relative 10% of baseline 0.90 -> band 0.09; current CI (0.83, 0.87)
        # vs baseline CI (0.88, 0.92): cur_high 0.87 < 0.88 - 0.09? no -> PASS
        agg = _agg_from_metrics(0.85, None, pak_ci=(0.83, 0.87))
        result = gate_mod.evaluate(
            agg, _cfg(mode="relative", tol=0.10), baseline=self._baseline(mean=None))
        pak = next(v for v in result.verdicts
                   if v.kind == "regression" and v.metric == "pass_at_k_mean")
        assert pak.band == pytest.approx(0.09)
        assert pak.status == gate_mod.PASS

    def test_relative_band_catches_regression(self):
        # band 0.09 -> baseline low 0.88 - 0.09 = 0.79; cur_high 0.77 < 0.79
        agg = _agg_from_metrics(0.74, None, pak_ci=(0.71, 0.77))
        result = gate_mod.evaluate(
            agg, _cfg(mode="relative", tol=0.10), baseline=self._baseline(mean=None))
        pak = next(v for v in result.verdicts
                   if v.kind == "regression" and v.metric == "pass_at_k_mean")
        assert pak.status == gate_mod.REGRESSION
        assert not result.green

    def test_plain_float_baseline_degrades_gracefully(self):
        # old-format baseline (plain floats, degenerate CI)
        agg = _agg_from_metrics(0.75, 0.70, pak_ci=(0.72, 0.78))
        result = gate_mod.evaluate(agg, _cfg(), baseline=self._baseline(with_ci=False))
        assert not result.green

    def test_threshold_fail_plus_regression_is_red(self):
        agg = _agg_from_metrics(0.60, 0.5, pak_ci=(0.57, 0.63), ms_ci=(0.47, 0.53))
        result = gate_mod.evaluate(agg, _cfg(min_mean_score=0.7), baseline=self._baseline())
        assert not result.green
        assert len(result.reasons()) >= 2

    def test_config_hash_mismatch_noted(self):
        from evalgate import config as config_mod
        cfg = config_mod.Config()
        baseline = self._baseline()
        baseline["config_hash"] = "deadbeef00000000"
        agg = _agg_from_metrics(0.9, 0.88, pak_ci=(0.88, 0.92), ms_ci=(0.86, 0.90))
        result = gate_mod.evaluate(agg, cfg, baseline)
        assert any("configuration changed" in n for n in result.notes)


class TestBounds:
    def test_real_aggregate_bounds(self):
        rng_vals = [0.4, 0.9, 0.6, 0.7, 0.3, 0.8, 0.55, 0.65, 0.5, 0.75]
        rows = [{"case": "a", "passed": i < 7, "score": rng_vals[i]}
                for i in range(10)]
        agg = stats.aggregate(rows, k=1, base_seed=3, bootstrap_iterations=300)
        lo, hi = agg.pass_rate_ci
        assert lo < 0.7 < hi
        # intervals bracket their point estimates
        for metric in ("pass_rate", "mean_score", "pass_at_k_mean"):
            ci = agg.metric_ci(metric)
            value = agg.metric_value(metric)
            assert ci[0] <= value <= ci[1]
            got = gate_mod._bounds(agg, metric)
            assert got == ci
        # degenerate fallback when CI missing
        class Bare:
            def metric_value(self, name):
                return 0.5
            def metric_ci(self, name):
                return None
        assert gate_mod._bounds(Bare(), "x") == (0.5, 0.5)


def _agg_with_latency(p95, p95_ci=None, cost=None, cost_ci=None,
                       pak_mean=0.9, pak_ci=(0.85, 0.95)):
    class FakeAgg:
        pass
    agg = FakeAgg()
    agg.pass_at_k_mean = pak_mean
    agg.pass_at_k_ci = pak_ci
    agg.pass_rate = pak_mean
    agg.pass_rate_ci = pak_ci
    agg.mean_score = None
    agg.mean_score_ci = None
    agg.p95_latency_ms = p95
    agg.p95_latency_ci = p95_ci or ((p95, p95) if p95 is not None else None)
    agg.total_cost_usd = cost
    agg.total_cost_ci = cost_ci or ((cost, cost) if cost is not None else None)

    def metric_value(name):
        return {"pass_at_k_mean": agg.pass_at_k_mean,
                "pass_rate": agg.pass_rate,
                "mean_score": agg.mean_score,
                "p95_latency_ms": agg.p95_latency_ms,
                "total_cost_usd": agg.total_cost_usd}.get(name)

    def metric_ci(name):
        return {"pass_at_k_mean": agg.pass_at_k_ci,
                "pass_rate": agg.pass_rate_ci,
                "mean_score": agg.mean_score_ci,
                "p95_latency_ms": agg.p95_latency_ci,
                "total_cost_usd": agg.total_cost_ci}.get(name)

    agg.metric_value = metric_value
    agg.metric_ci = metric_ci
    return agg


def _cfg_v2(max_lat=None, max_cost=None, tol=50.0, mode="absolute"):
    from evalgate import config as config_mod
    return config_mod.Config(
        gate=config_mod.GateConfig(
            k=1, min_pass_at_k=0.85,
            max_p95_latency_ms=max_lat, max_total_cost_usd=max_cost,
            regression=config_mod.RegressionConfig(mode=mode, tolerance=tol),
        ),
    )


class TestLatencyThresholds:
    def test_under_limit_passes(self):
        agg = _agg_with_latency(p95=800.0)
        result = gate_mod.evaluate(agg, _cfg_v2(max_lat=1200.0), baseline=None)
        assert result.green
        lat = [v for v in result.verdicts if v.metric == "p95_latency_ms"]
        assert lat and lat[0].status == gate_mod.PASS
        assert "800.0 ms" in lat[0].detail

    def test_over_limit_fails(self):
        agg = _agg_with_latency(p95=1400.0)
        result = gate_mod.evaluate(agg, _cfg_v2(max_lat=1200.0), baseline=None)
        assert not result.green
        lat = next((v for v in result.verdicts if v.metric == "p95_latency_ms"), None)
        assert lat is not None and lat.status == gate_mod.FAIL

    def test_missing_latency_notes(self):
        agg = _agg_with_latency(p95=None)
        result = gate_mod.evaluate(agg, _cfg_v2(max_lat=1200.0), baseline=None)
        assert result.green  # notes only, not a failure
        assert any("latency" in n for n in result.notes)


class TestCostThresholds:
    def test_under_limit_passes(self):
        agg = _agg_with_latency(p95=None, cost=0.4)
        result = gate_mod.evaluate(agg, _cfg_v2(max_cost=1.0), baseline=None)
        assert result.green

    def test_over_limit_fails(self):
        agg = _agg_with_latency(p95=None, cost=1.4)
        result = gate_mod.evaluate(agg, _cfg_v2(max_cost=1.0), baseline=None)
        assert not result.green
        cost = next((v for v in result.verdicts if v.metric == "total_cost_usd"), None)
        assert cost is not None and cost.status == gate_mod.FAIL


class TestDirectionAwareRegression:
    def test_latency_regression_above_band(self):
        # current interval entirely ABOVE baseline + band -> RED
        agg = _agg_with_latency(p95=1200.0, p95_ci=(1150.0, 1250.0))
        baseline = {"config_hash": None, "metrics": {
            "p95_latency_ms": {"value": 800.0, "low": 780.0, "high": 820.0}}}
        result = gate_mod.evaluate(agg, _cfg_v2(tol=50.0), baseline=baseline)
        lat = next((v for v in result.verdicts if v.metric == "p95_latency_ms"), None)
        assert lat is not None and lat.status == gate_mod.REGRESSION
        assert not result.green

    def test_latency_noise_stays_green(self):
        # overlapping intervals -> PASS (the anti-flake guarantee)
        agg = _agg_with_latency(p95=860.0, p95_ci=(780.0, 940.0))
        baseline = {"config_hash": None, "metrics": {
            "p95_latency_ms": {"value": 800.0, "low": 760.0, "high": 840.0}}}
        result = gate_mod.evaluate(agg, _cfg_v2(tol=50.0), baseline=baseline)
        lat = next((v for v in result.verdicts if v.metric == "p95_latency_ms"), None)
        assert lat is not None and lat.status == gate_mod.PASS
        assert result.green

    def test_latency_improved_below_band(self):
        agg = _agg_with_latency(p95=500.0, p95_ci=(480.0, 520.0))
        baseline = {"config_hash": None, "metrics": {
            "p95_latency_ms": {"value": 800.0, "low": 780.0, "high": 820.0}}}
        result = gate_mod.evaluate(agg, _cfg_v2(tol=50.0), baseline=baseline)
        lat = next((v for v in result.verdicts if v.metric == "p95_latency_ms"), None)
        assert lat is not None and lat.status == gate_mod.IMPROVED

    def test_cost_regression_relative_band(self):
        # relative mode: band = 10% of baseline 0.5 -> 0.05
        agg = _agg_with_latency(p95=None, cost=0.62, cost_ci=(0.61, 0.63))
        baseline = {"config_hash": None, "metrics": {
            "total_cost_usd": {"value": 0.5, "low": 0.49, "high": 0.51}}}
        result = gate_mod.evaluate(
            agg, _cfg_v2(tol=0.10, mode="relative"), baseline=baseline)
        cost = next((v for v in result.verdicts if v.metric == "total_cost_usd"), None)
        assert cost is not None and cost.status == gate_mod.REGRESSION

    def test_old_baseline_without_latency_is_skipped(self):
        agg = _agg_with_latency(p95=1200.0)
        baseline = {"config_hash": None, "metrics": {
            "pass_at_k_mean": {"value": 0.9, "low": 0.88, "high": 0.92}}}
        result = gate_mod.evaluate(agg, _cfg_v2(), baseline=baseline)
        assert not any(v.metric == "p95_latency_ms" for v in result.verdicts)


class TestCaseThresholds:
    """v2.1: per-case pass@k floors."""

    def _agg(self, qualities, reps=10):
        from evalgate import stats as stats_mod
        rows = []
        for name, quality in qualities:
            for i in range(reps):
                rows.append({"case": name, "passed": (i / reps) < quality})
        return stats_mod.aggregate(rows, k=1, base_seed=7)

    def _cfg(self, floors):
        from evalgate import config as config_mod
        return config_mod.Config(
            gate=config_mod.GateConfig(
                k=1, min_pass_at_k=0.0, case_min_pass_at_k=floors),
        )

    def test_case_above_floor_passes(self):
        agg = self._agg([("a", 1.0), ("b", 0.5)])
        result = gate_mod.evaluate(agg, self._cfg({"a": 0.9, "b": 0.4}), None)
        assert result.green
        case_verdicts = [v for v in result.verdicts if v.case_name]
        assert {v.case_name for v in case_verdicts} == {"a", "b"}
        assert all(v.status == gate_mod.PASS for v in case_verdicts)

    def test_case_below_floor_fails(self):
        agg = self._agg([("a", 0.5)])
        result = gate_mod.evaluate(agg, self._cfg({"a": 0.9}), None)
        assert not result.green
        v = next(x for x in result.verdicts if x.case_name)
        assert v.case_name == "a"
        assert v.status == gate_mod.FAIL
        assert "required 0.900" in v.detail
        assert v.metric == "case:a"

    def test_missing_case_produces_note_not_failure(self):
        agg = self._agg([("a", 1.0)])
        result = gate_mod.evaluate(agg, self._cfg({"ghost-case": 0.9}), None)
        assert result.green  # note, never a silent fail
        assert any("ghost-case" in n and "not present" in n
                   for n in result.notes)
        assert not any(v.case_name == "ghost-case" for v in result.verdicts)

    def test_aggregate_still_applies_on_top(self):
        # every case meets its floor but the aggregate mean does not
        agg = self._agg([("a", 0.6), ("b", 0.6)])
        cfg = self._cfg({"a": 0.5, "b": 0.5})
        cfg.gate.min_pass_at_k = 0.8
        result = gate_mod.evaluate(agg, cfg, None)
        assert not result.green

    def test_verdict_order_is_deterministic(self):
        agg = self._agg([("b", 1.0), ("a", 1.0), ("c", 1.0)])
        result = gate_mod.evaluate(agg, self._cfg({"c": 0.5, "a": 0.5, "b": 0.5}), None)
        names = [v.case_name for v in result.verdicts if v.case_name]
        assert names == ["a", "b", "c"]  # sorted, not insertion-ordered
