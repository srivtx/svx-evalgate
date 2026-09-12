"""Tests for the self-contained HTML report (v2)."""
from __future__ import annotations

import re

from evalgate.gate import GateResult, MetricVerdict
from evalgate.htmlreport import render, write_report
from evalgate.stats import aggregate


class _Gate:
    def __init__(self):
        self.k = 1
        self.min_pass_at_k = 0.8


class _Evals:
    def __init__(self):
        self.repetitions = 20
        self.base_seed = 424242


class _Report:
    def __init__(self):
        self.path = ".svx/report.md"
        self.html_path = ".svx/report.html"


class _Cfg:
    def __init__(self):
        self.evals = _Evals()
        self.gate = _Gate()
        self.report = _Report()


def _agg(rows):
    return aggregate(rows, k=1, base_seed=99, bootstrap_iterations=200)


ROWS_FULL = [
    {"case": f"case-{i}", "passed": i % 5 != 0, "score": 0.5 + (i % 7) / 20,
     "latency_ms": 100.0 + (i * 37) % 500, "cost_usd": 0.0005 + (i % 4) / 4000}
    for i in range(40)
]


class TestRender:
    def test_basic_structure(self):
        doc = render(_agg(ROWS_FULL), _Cfg(), None, GateResult(green=True), [])
        assert doc.startswith("<!DOCTYPE html>")
        assert doc.rstrip().endswith("</html>")
        assert "GREEN" in doc
        assert "SVX" in doc
        assert "pass@1 mean" in doc
        assert "p95 latency" in doc
        assert "total cost" in doc

    def test_contains_all_charts(self):
        doc = render(_agg(ROWS_FULL), _Cfg(), None, GateResult(green=True), [])
        # case bars, trend, score histogram, latency histogram
        assert doc.count("<svg") >= 4
        assert "pass@1 by case" in doc
        assert "pass@k trend" in doc
        assert "score distribution" in doc
        assert "latency distribution" in doc

    def test_trend_uses_history(self):
        history = [{"ts": "2026-09-11T00:00:00+00:00", "verdict": "GREEN",
                    "pass_at_k_mean": 0.8},
                   {"ts": "2026-09-12T00:00:00+00:00", "verdict": "RED",
                    "pass_at_k_mean": 0.6}]
        doc = render(_agg(ROWS_FULL), _Cfg(), None, GateResult(green=True), history)
        assert "2 run(s) on record" in doc
        assert "2026-09-11" in doc and "2026-09-12" in doc

    def test_red_verdict_and_reasons(self):
        result = GateResult(green=False)
        result.verdicts.append(MetricVerdict(
            metric="pass_at_k_mean", kind="threshold", current=0.5,
            threshold=0.8, status="fail", detail="pass@1 mean 0.500 < threshold 0.800"))
        doc = render(_agg(ROWS_FULL), _Cfg(), None, result, [])
        assert ">RED<" in doc
        assert "Why this run is RED" in doc
        assert "pass@1 mean 0.500" in doc

    def test_hostile_case_names_escaped(self):
        rows = [
            {"case": "<script>alert(1)</script>", "passed": True, "score": 0.9},
            {"case": 'x"onload="evil()', "passed": False, "score": 0.2},
        ]
        doc = render(_agg(rows), _Cfg(), None, GateResult(green=True), [])
        # angle brackets escaped: no executable script tag survives
        assert "<script>alert" not in doc
        assert "&lt;script&gt;" in doc
        # quotes escaped: no attribute-injection sequence with real quotes
        assert '"onload=' not in doc
        assert "onerror=" not in doc
        assert "javascript:" not in doc

    def test_no_external_resources(self):
        doc = render(_agg(ROWS_FULL), _Cfg(), None, GateResult(green=True), [])
        assert "http://" not in doc
        assert "https://" not in doc
        assert "<img" not in doc
        assert "<link" not in doc
        assert "url(" not in doc

    def test_minimal_rows_still_render(self):
        rows = [{"case": "only", "passed": True}]
        doc = render(_agg(rows), _Cfg(), None, GateResult(green=True), [])
        assert doc.startswith("<!DOCTYPE html>")
        # no latency / score sections, no crash
        assert "latency distribution" not in doc
        assert "score distribution" not in doc
        assert 'aria-label="pass@k trend"' in doc

    def test_svg_is_well_formed(self):
        doc = render(_agg(ROWS_FULL), _Cfg(), None, GateResult(green=True), [])
        blocks = re.findall(r"<svg[^>]*>.*?</svg>", doc, flags=re.DOTALL)
        assert len(blocks) >= 4
        for block in blocks:
            # every text element is closed; no dangling attribute quotes
            assert block.count("<text") == block.count("</text>")
            assert block.count("<svg") == block.count("</svg>")

    def test_baseline_line_rendered(self):
        baseline = {"created": "2026-09-01T00:00:00+00:00", "git_sha": "a" * 40}
        doc = render(_agg(ROWS_FULL), _Cfg(), baseline, GateResult(green=True), [])
        assert "baseline 2026-09-01" in doc
        assert "@" in doc

    def test_deterministic_body_except_timestamp(self):
        d1 = render(_agg(ROWS_FULL), _Cfg(), None, GateResult(green=True), [])
        d2 = render(_agg(ROWS_FULL), _Cfg(), None, GateResult(green=True), [])
        def strip(d):
            return re.sub(r"generated [^<]+", "generated X", d)
        assert strip(d1) == strip(d2)


class TestWriteReport:
    def test_creates_parents_and_file(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "report.html"
        write_report("<html></html>", target)
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "<html></html>"
