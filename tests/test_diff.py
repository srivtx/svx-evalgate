"""Tests for evalgate diff: snapshot loading, comparison, rendering."""
import json

import pytest

from evalgate import config as config_mod
from evalgate import diff as diff_mod


def _baseline_doc(metrics, created="2026-01-01T00:00:00+00:00"):
    return {
        "schema_version": 1,
        "tool": "svx-evalgate",
        "created": created,
        "metrics": {
            name: {"value": v, "low": lo, "high": hi}
            for name, (v, lo, hi) in metrics.items()
        },
    }


def _reg(mode="absolute", tolerance=0.05):
    return config_mod.RegressionConfig(mode=mode, tolerance=tolerance)


class TestLoadSnapshot:
    def test_baseline_document_shape(self, tmp_path):
        path = tmp_path / "a.json"
        path.write_text(json.dumps(_baseline_doc({
            "pass_at_k_mean": (0.9, 0.85, 0.95),
        })), encoding="utf-8")
        snap = diff_mod.load_snapshot(path)
        assert snap["pass_at_k_mean"] == {"value": 0.9, "low": 0.85, "high": 0.95}

    def test_flat_history_shape(self, tmp_path):
        path = tmp_path / "entry.json"
        path.write_text(json.dumps({
            "ts": "2026-01-02", "verdict": "GREEN",
            "pass_at_k_mean": 0.91, "p95_latency_ms": 800.0,
        }), encoding="utf-8")
        snap = diff_mod.load_snapshot(path)
        assert snap["pass_at_k_mean"]["value"] == 0.91
        assert snap["pass_at_k_mean"]["low"] == 0.91  # degenerate interval
        assert snap["p95_latency_ms"]["value"] == 800.0

    def test_from_history_entry(self):
        entry = {"pass_at_k_mean": 0.5, "unknown_metric": 1.0}
        snap = diff_mod.from_history_entry(entry)
        assert list(snap) == ["pass_at_k_mean"]

    def test_point_only_baseline_entries_degenerate(self, tmp_path):
        path = tmp_path / "old.json"
        path.write_text(json.dumps({
            "metrics": {"pass_at_k_mean": 0.8},
        }), encoding="utf-8")
        snap = diff_mod.load_snapshot(path)
        assert snap["pass_at_k_mean"] == {"value": 0.8, "low": 0.8, "high": 0.8}

    def test_invalid_json_rejected(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{nope", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            diff_mod.load_snapshot(path)

    def test_no_metrics_rejected(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"metrics": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match="no usable metrics"):
            diff_mod.load_snapshot(path)


class TestCompare:
    def _row(self, rows, metric):
        return {r["metric"]: r for r in rows}[metric]

    def test_confident_regression_is_worse(self):
        a = {"pass_at_k_mean": {"value": 0.9, "low": 0.88, "high": 0.92}}
        b = {"pass_at_k_mean": {"value": 0.6, "low": 0.55, "high": 0.65}}
        rows = diff_mod.compare(a, b, _reg(tolerance=0.05))
        row = self._row(rows, "pass_at_k_mean")
        assert row["status"] == diff_mod.WORSE
        assert row["delta"] == pytest.approx(-0.3)
        assert row["rel"] == pytest.approx(-0.3 / 0.9)

    def test_overlapping_intervals_are_unchanged(self):
        a = {"pass_at_k_mean": {"value": 0.9, "low": 0.85, "high": 0.95}}
        b = {"pass_at_k_mean": {"value": 0.88, "low": 0.83, "high": 0.93}}
        rows = diff_mod.compare(a, b, _reg(tolerance=0.05))
        assert rows[0]["status"] == diff_mod.UNCHANGED

    def test_confident_improvement_is_better(self):
        a = {"pass_at_k_mean": {"value": 0.6, "low": 0.55, "high": 0.65}}
        b = {"pass_at_k_mean": {"value": 0.9, "low": 0.88, "high": 0.92}}
        rows = diff_mod.compare(a, b, _reg(tolerance=0.05))
        assert rows[0]["status"] == diff_mod.BETTER

    def test_lower_is_better_direction_inverted(self):
        # latency: b entirely ABOVE a + band -> WORSE
        a = {"p95_latency_ms": {"value": 100.0, "low": 90.0, "high": 110.0}}
        b = {"p95_latency_ms": {"value": 200.0, "low": 180.0, "high": 220.0}}
        rows = diff_mod.compare(a, b, _reg(tolerance=5.0))
        assert self._row(rows, "p95_latency_ms")["status"] == diff_mod.WORSE
        # and a faster b is BETTER
        rows = diff_mod.compare(b, a, _reg(tolerance=5.0))
        assert self._row(rows, "p95_latency_ms")["status"] == diff_mod.BETTER

    def test_relative_mode_scales_band(self):
        a = {"pass_at_k_mean": {"value": 0.8, "low": 0.78, "high": 0.82}}
        b = {"pass_at_k_mean": {"value": 0.7, "low": 0.68, "high": 0.72}}
        # band = 0.8 * 0.10 = 0.08; b high (0.72) >= a low (0.78) - 0.08
        rows = diff_mod.compare(a, b, _reg(mode="relative", tolerance=0.10))
        assert self._row(rows, "pass_at_k_mean")["status"] == diff_mod.UNCHANGED
        # with a small band (0.8 * 0.01 = 0.008) it IS confidently worse
        rows = diff_mod.compare(a, b, _reg(mode="relative", tolerance=0.01))
        assert self._row(rows, "pass_at_k_mean")["status"] == diff_mod.WORSE

    def test_missing_metric_on_either_side_is_na(self):
        a = {"pass_at_k_mean": {"value": 0.9, "low": 0.9, "high": 0.9}}
        b = {"p95_latency_ms": {"value": 100.0, "low": 100.0, "high": 100.0}}
        rows = diff_mod.compare(a, b, _reg())
        by_metric = {r["metric"]: r for r in rows}
        assert by_metric["pass_at_k_mean"]["status"] == diff_mod.NA
        assert by_metric["p95_latency_ms"]["status"] == diff_mod.NA

    def test_relative_delta_impossible_is_none(self):
        a = {"total_cost_usd": {"value": 0.0, "low": 0.0, "high": 0.0}}
        b = {"total_cost_usd": {"value": 1.0, "low": 1.0, "high": 1.0}}
        rows = diff_mod.compare(a, b, _reg())
        row = self._row(rows, "total_cost_usd")
        assert row["rel"] is None
        assert row["delta"] == pytest.approx(1.0)


class TestRender:
    def test_table_renders_labels_and_verdicts(self):
        a = {"pass_at_k_mean": {"value": 0.9, "low": 0.88, "high": 0.92}}
        b = {"pass_at_k_mean": {"value": 0.6, "low": 0.55, "high": 0.65}}
        rows = diff_mod.compare(a, b, _reg())
        text = diff_mod.render(rows, "baseline.json", "last run")
        assert "A: baseline.json" in text
        assert "B: last run" in text
        assert "WORSE" in text
        assert "confidently worse: pass_at_k_mean" in text

    def test_clean_diff_reports_no_regressions(self):
        a = {"pass_at_k_mean": {"value": 0.9, "low": 0.88, "high": 0.92}}
        rows = diff_mod.compare(a, a, _reg())
        text = diff_mod.render(rows, "a", "a")
        assert "no metric is confidently worse" in text
