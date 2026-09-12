"""Ingestion adapters: existing test reports become eval rows, zero wrappers.

``evalgate ingest --format pytest-junit report.xml`` gates an ordinary
pytest suite with no emitter code at all: run pytest with its built-in
``--junitxml=report.xml`` flag, point EvalGate at the file, and every
test becomes a case, failures/errors become failed rows, and durations
become latency observations. The full pipeline runs exactly as it does
for ``evalgate run``: aggregate statistics, thresholds, regression bands
against the baseline, markdown/HTML/JUnit reports, history.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

FORMATS = ("pytest-junit",)


def parse_pytest_junit(path: Path) -> list[dict]:
    """Parse a pytest JUnit XML report into EvalGate eval rows.

    Handles both root shapes pytest emits (``<testsuites>`` for the
    default xunit2 family, a bare ``<testsuite>`` for xunit1). A
    testcase carrying ``<failure>`` or ``<error>`` becomes a failed row;
    ``<skipped>`` testcases are dropped entirely (a skip is the absence
    of a data point, not a failure); the ``time`` attribute (seconds)
    becomes ``latency_ms`` when present and parsable.
    """
    raw = path.read_text(encoding="utf-8")
    # Hardening: ElementTree never resolves external entities, but a
    # crafted report with internal entity expansion (billion laughs)
    # can still burn memory on old interpreters. Reject DTDs at the
    # door; pytest never emits them.
    if "<!DOCTYPE" in raw or "<!ENTITY" in raw:
        raise ValueError(f"{path}: DTD/entity declarations are not accepted")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"{path}: not valid XML: {exc}") from exc

    rows: list[dict] = []
    for testcase in root.iter("testcase"):
        if testcase.find("skipped") is not None:
            continue
        name = testcase.get("name") or "unnamed"
        classname = testcase.get("classname")
        case = f"{classname}.{name}" if classname else name
        passed = (testcase.find("failure") is None
                  and testcase.find("error") is None)
        row: dict = {"case": case, "passed": passed}
        time_attr = testcase.get("time")
        if time_attr is not None:
            try:
                row["latency_ms"] = round(float(time_attr) * 1000.0, 3)
            except ValueError:
                pass  # a malformed time attr is data we can live without
        rows.append(row)

    if not rows:
        raise ValueError(
            f"{path}: no usable testcases found (empty report or all skipped)"
        )
    return rows
