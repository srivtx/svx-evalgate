"""Tests for the JUnit XML output adapter."""
import xml.etree.ElementTree as ET

from evalgate import baseline as baseline_mod
from evalgate import config as config_mod
from evalgate import gate as gate_mod
from evalgate import junitxml, stats


def _rows(cases, seed=1, reps=8):
    rows = []
    for name, quality in cases:
        for i in range(reps):
            rows.append({"case": name, "passed": (i / reps) < quality,
                         "score": quality})
    return rows


def _gate_setup(cases, cfg=None, baseline=None, seed=1):
    agg = stats.aggregate(_rows(cases, seed=seed), k=1, base_seed=seed,
                          bootstrap_iterations=200)
    cfg = cfg or config_mod.Config(
        gate=config_mod.GateConfig(k=1, min_pass_at_k=0.85))
    result = gate_mod.evaluate(agg, cfg, baseline)
    return agg, cfg, result


class TestJunitXml:
    def test_green_run_is_valid_xml_with_zero_failures(self):
        _agg, cfg, result = _gate_setup([("a", 1.0), ("b", 1.0)])
        assert result.green
        doc = junitxml.render(result, cfg)
        root = ET.fromstring(doc)
        assert root.tag == "testsuites"
        suite = root.find("testsuite")
        assert suite is not None
        assert suite.get("name") == "evalgate"
        assert int(suite.get("failures")) == 0
        assert int(suite.get("errors")) == 0
        assert int(suite.get("tests")) == len(result.verdicts)

    def test_threshold_failure_becomes_failure_element(self):
        _agg, cfg, result = _gate_setup([("a", 0.5)])
        assert not result.green
        doc = junitxml.render(result, cfg)
        root = ET.fromstring(doc)
        failures = root.findall(".//failure")
        assert failures
        assert failures[0].get("type") == "assert"
        # the statistical evidence rides inside the failure body
        assert failures[0].text is not None
        assert "threshold" in failures[0].text

    def test_regression_verdict_is_a_failure(self):
        agg, cfg, _ = _gate_setup([("a", 0.95)])
        baseline_doc = baseline_mod.build_baseline(agg, cfg)
        _agg2, cfg2, result = _gate_setup([("a", 0.4)], cfg=cfg,
                                         baseline=baseline_doc)
        assert not result.green
        doc = junitxml.render(result, cfg2)
        root = ET.fromstring(doc)
        assert root.findall(".//failure")

    def test_regression_verdicts_get_own_classname(self):
        agg, cfg, _ = _gate_setup([("a", 0.95)])
        baseline_doc = baseline_mod.build_baseline(agg, cfg)
        _agg2, cfg2, result = _gate_setup([("a", 0.4)], cfg=cfg,
                                         baseline=baseline_doc)
        doc = junitxml.render(result, cfg2)
        root = ET.fromstring(doc)
        # threshold and regression checks for the same metric coexist
        # under distinct classnames (no duplicate testcase identity)
        ids = {(tc.get("classname"), tc.get("name"))
               for tc in root.findall(".//testcase")}
        assert ("evalgate.gate", "pass_at_k_mean") in ids
        assert ("evalgate.regression", "pass_at_k_mean") in ids

    def test_per_case_verdicts_use_case_classname(self):
        cfg = config_mod.Config(gate=config_mod.GateConfig(
            k=1, min_pass_at_k=0.0,
            case_min_pass_at_k={"a": 0.9}))
        _agg, cfg, result = _gate_setup([("a", 0.5), ("b", 1.0)], cfg=cfg)
        doc = junitxml.render(result, cfg)
        root = ET.fromstring(doc)
        case_tc = [tc for tc in root.findall(".//testcase")
                   if tc.get("classname") == "evalgate.cases"]
        assert [tc.get("name") for tc in case_tc] == ["a"]
        assert case_tc[0].find("failure") is not None

    def test_case_names_are_xml_escaped(self):
        cfg = config_mod.Config(gate=config_mod.GateConfig(
            k=1, min_pass_at_k=0.0,
            case_min_pass_at_k={"<script>alert(1)</script>": 0.9}))
        _agg, cfg, result = _gate_setup(
            [("<script>alert(1)</script>", 0.5)], cfg=cfg)
        doc = junitxml.render(result, cfg)
        assert "<script>alert(1)</script>" not in doc
        root = ET.fromstring(doc)  # still well-formed
        names = [tc.get("name") for tc in root.findall(".//testcase")]
        assert "<script>alert(1)</script>" in names

    def test_properties_carry_provenance(self):
        _agg, cfg, result = _gate_setup([("a", 1.0)])
        doc = junitxml.render(result, cfg)
        root = ET.fromstring(doc)
        props = {p.get("name"): p.get("value")
                 for p in root.findall(".//property")}
        assert props["tool"] == "svx-evalgate"
        assert props["k"] == "1"
        assert props["base_seed"] == str(cfg.evals.base_seed)

    def test_empty_gate_still_renders(self):
        cfg = config_mod.Config(gate=config_mod.GateConfig(k=1, min_pass_at_k=None))
        _agg, cfg, result = _gate_setup([("a", 1.0)], cfg=cfg)
        assert result.verdicts == []
        doc = junitxml.render(result, cfg)
        root = ET.fromstring(doc)
        assert int(root.find("testsuite").get("tests")) == 0

    def test_xml_declaration_present(self):
        _agg, cfg, result = _gate_setup([("a", 1.0)])
        assert junitxml.render(result, cfg).startswith("<?xml version=\"1.0\"")

    def test_write_report_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "nested" / "report.xml"
        _agg, cfg, result = _gate_setup([("a", 1.0)])
        junitxml.write_report(junitxml.render(result, cfg), target)
        assert target.exists()
        ET.parse(target)  # parses back cleanly
