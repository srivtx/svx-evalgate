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
    agg.pass_at_k_ci = pak_ci or ((pass_at_k_mean, pass_at_k_mean) if pass_at_k_mean is not None else None)
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
        pak = [v for v in result.verdicts
               if v.kind == "regression" and v.metric == "pass_at_k_mean"][0]
        assert pak.band == pytest.approx(0.09)
        assert pak.status == gate_mod.PASS

    def test_relative_band_catches_regression(self):
        # band 0.09 -> baseline low 0.88 - 0.09 = 0.79; cur_high 0.77 < 0.79
        agg = _agg_from_metrics(0.74, None, pak_ci=(0.71, 0.77))
        result = gate_mod.evaluate(
            agg, _cfg(mode="relative", tol=0.10), baseline=self._baseline(mean=None))
        pak = [v for v in result.verdicts
               if v.kind == "regression" and v.metric == "pass_at_k_mean"][0]
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
