"""Tests for the run-history module (v2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalgate import history


class _FakeConfig:
    def __init__(self, path: str, source: Path):
        self.history = type("H", (), {"path": path, "max_entries": 500})()
        self.source_path = source
        import dataclasses
        self._gate = dataclasses.asdict  # unused

    def config_hash(self) -> str:
        return "deadbeef00000000"


def _entry(ts: str, pak: float, verdict: str = "GREEN") -> dict:
    return {"ts": ts, "verdict": verdict, "pass_at_k_mean": pak}


class TestAppendLoad:
    def test_append_creates_and_loads(self, tmp_path):
        p = tmp_path / ".svx" / "history.jsonl"
        history.append_run(p, _entry("2026-09-12T01:00:00+00:00", 0.9), 500)
        entries = history.load_history(p)
        assert len(entries) == 1
        assert entries[0]["pass_at_k_mean"] == 0.9

    def test_append_many_in_order(self, tmp_path):
        p = tmp_path / "history.jsonl"
        for i in range(5):
            history.append_run(p, _entry(f"2026-09-12T0{i}:00:00+00:00", 0.5 + i / 10), 500)
        entries = history.load_history(p)
        assert [e["pass_at_k_mean"] for e in entries] == [0.5, 0.6, 0.7, 0.8, 0.9]

    def test_trim_oldest_beyond_max(self, tmp_path):
        p = tmp_path / "history.jsonl"
        for i in range(10):
            history.append_run(p, _entry(f"run-{i}", i / 10), 4)
        entries = history.load_history(p)
        assert len(entries) == 4
        # the four newest survive
        assert entries[0]["ts"] == "run-6"
        assert entries[-1]["ts"] == "run-9"

    def test_corrupt_lines_skipped(self, tmp_path):
        p = tmp_path / "history.jsonl"
        p.write_text('{"ts": "a", "verdict": "GREEN", "pass_at_k_mean": 0.8}\n'
                     "not json at all\n"
                     "\n"
                     '{"ts": "b", "verdict": "RED", "pass_at_k_mean": 0.4}\n',
                     encoding="utf-8")
        entries = history.load_history(p)
        assert len(entries) == 2

    def test_load_missing_file_empty(self, tmp_path):
        assert history.load_history(tmp_path / "nope.jsonl") == []

    def test_load_limit_takes_latest(self, tmp_path):
        p = tmp_path / "history.jsonl"
        for i in range(8):
            history.append_run(p, _entry(f"r{i}", i / 8), 500)
        entries = history.load_history(p, limit=3)
        assert [e["ts"] for e in entries] == ["r5", "r6", "r7"]


class TestSparkline:
    def test_empty_flat(self):
        line = history.sparkline([])
        assert set(line) == {"▁"}

    def test_none_values_low(self):
        line = history.sparkline([None, None])
        assert set(line) == {"▁"}

    def test_monotonic_ends(self):
        line = history.sparkline([0.0, 0.5, 1.0], width=3)
        assert line[0] == "▁"
        assert line[-1] == "█"

    def test_flat_series_middle_block(self):
        line = history.sparkline([0.5, 0.5, 0.5], width=3)
        # zero span -> every block maps to the lowest index
        assert set(line) == {"▁"}

    def test_width_respected(self):
        assert len(history.sparkline([0.1] * 100, width=10)) == 10


class TestRunSummary:
    def test_summary_from_aggregate(self):
        from evalgate.stats import aggregate
        rows = [
            {"case": "a", "passed": True, "score": 0.9,
             "latency_ms": 100.0, "cost_usd": 0.001},
            {"case": "a", "passed": False, "score": 0.4,
             "latency_ms": 200.0, "cost_usd": 0.002},
            {"case": "b", "passed": True, "score": 0.8,
             "latency_ms": 150.0, "cost_usd": 0.001},
        ]
        agg = aggregate(rows, k=1, base_seed=1, bootstrap_iterations=50)

        from evalgate.gate import GateResult
        result = GateResult(green=True)

        class Cfg:
            def config_hash(self):
                return "abc123"

        entry = history.run_summary(agg, Cfg(), result, "2.0.0")
        assert entry["verdict"] == "GREEN"
        assert entry["total_runs"] == 3
        assert entry["total_passes"] == 2
        assert entry["cases"] == 2
        assert entry["failing"] == 1
        assert entry["pass_rate"] == pytest.approx(2 / 3, abs=1e-6)
        assert entry["p95_latency_ms"] == pytest.approx(200.0)
        assert entry["total_cost_usd"] == pytest.approx(0.004, abs=1e-9)
        assert entry["config_hash"] == "abc123"
        assert "ts" in entry and "git_sha" in entry
        # round-trips through JSON
        json.dumps(entry)
