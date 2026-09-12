"""JUnit XML output: the gate verdict as a CI-native test report.

Written to ``report.junit_path`` (``.svx/report.xml`` by default; set the
key to ``~`` to disable). CI systems that speak JUnit XML - GitLab
(``artifacts:reports:junit``), Jenkins, Azure Pipelines, and the various
GitHub test-report annotations actions - render it as ordinary test
results, so EvalGate lands in the test UI engineers already watch
instead of a log wall.

Semantics: every MetricVerdict is one assertion. Threshold checks
become testcases under ``evalgate.gate``; regression checks
(interval-vs-baseline) under ``evalgate.regression``, so one metric
appears at most once per classname; per-case threshold checks under
``evalgate.cases`` with the case name as the testcase name. FAIL and
REGRESSION verdicts carry their statistical evidence inside a
``<failure>`` element. Case-level flakiness without a configured
threshold is statistical data, not an assertion, and stays in the
markdown and HTML reports.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from . import __version__
from .gate import FAIL, REGRESSION, GateResult

_FAILURE_STATUSES = (FAIL, REGRESSION)


def _message(verdict) -> str:
    """One-line failure summary for the CI test list (detail goes in the body)."""
    current = f"{verdict.current:.3f}" if verdict.current is not None else "n/a"
    if verdict.kind == "threshold" and verdict.threshold is not None:
        return (f"{verdict.metric} = {current} violates threshold "
                f"{verdict.threshold:.3f}")
    if verdict.baseline is not None:
        band = f"+/-{verdict.band:.3f}" if verdict.band is not None else "?"
        return (f"{verdict.metric} = {current} regressed vs baseline "
                f"{verdict.baseline:.3f} (band {band})")
    return f"{verdict.metric} = {current} failed"


def render(gate_result: GateResult, config) -> str:
    """Render the gate as a single-testsuites JUnit XML document."""
    suites = ET.Element("testsuites", {"name": "svx-evalgate"})
    suite = ET.SubElement(suites, "testsuite", {
        "name": "evalgate",
        "package": "svx.evalgate",
    })
    props = ET.SubElement(suite, "properties")
    for name, value in (
        ("tool", "svx-evalgate"),
        ("version", __version__),
        ("k", str(config.gate.k)),
        ("repetitions", str(config.evals.repetitions)),
        ("base_seed", str(config.evals.base_seed)),
    ):
        ET.SubElement(props, "property", {"name": name, "value": value})

    failures = 0
    for verdict in gate_result.verdicts:
        if verdict.case_name:
            classname, name = "evalgate.cases", verdict.case_name
        elif verdict.kind == "regression":
            classname, name = "evalgate.regression", verdict.metric
        else:
            classname, name = "evalgate.gate", verdict.metric
        testcase = ET.SubElement(suite, "testcase", {
            "classname": classname,
            "name": name,
            "time": "0",
        })
        if verdict.status in _FAILURE_STATUSES:
            failures += 1
            failure = ET.SubElement(testcase, "failure", {
                "type": "assert",
                "message": _message(verdict),
            })
            failure.text = verdict.detail

    suite.set("tests", str(len(gate_result.verdicts)))
    suite.set("failures", str(failures))
    suite.set("errors", "0")
    suite.set("skipped", "0")
    body = ET.tostring(suites, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def write_report(xml_text: str, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml_text, encoding="utf-8")
