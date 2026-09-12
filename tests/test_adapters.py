"""Tests for the pytest-JUnit ingestion adapter."""
import textwrap

import pytest

from evalgate import adapters

PYTEST_REPORT = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="utf-8"?>
    <testsuites name="pytest" tests="4" failures="1" errors="1" skipped="1">
      <testsuite name="tests.test_llm" tests="4" failures="1" errors="1" skipped="1" time="0.42">
        <testcase classname="tests.test_llm" name="test_sql_gen" time="0.12"/>
        <testcase classname="tests.test_llm" name="test_sql_join" time="0.25">
          <failure message="assert False">AssertionError: wrong join order</failure>
        </testcase>
        <testcase classname="tests.test_llm" name="test_extract" time="0.01">
          <error message="connection reset">ConnectionError: db gone</error>
        </testcase>
        <testcase classname="tests.test_llm" name="test_flaky" time="0.04">
          <skipped type="pytest.skip" message="not ready"/>
        </testcase>
      </testsuite>
    </testsuites>
    """
)

XUNIT1_REPORT = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="utf-8"?>
    <testsuite name="tests" tests="2" failures="0">
      <testcase classname="tests" name="test_alpha" time="0.5"/>
      <testcase name="test_beta"/>
    </testsuite>
    """
)


class TestParsePytestJunit:
    def test_pass_fail_error_skip_semantics(self, tmp_path):
        path = tmp_path / "report.xml"
        path.write_text(PYTEST_REPORT, encoding="utf-8")
        rows = adapters.parse_pytest_junit(path)
        by_case = {r["case"]: r for r in rows}
        assert set(by_case) == {
            "tests.test_llm.test_sql_gen",
            "tests.test_llm.test_sql_join",
            "tests.test_llm.test_extract",
        }  # skipped dropped
        assert by_case["tests.test_llm.test_sql_gen"]["passed"] is True
        assert by_case["tests.test_llm.test_sql_join"]["passed"] is False
        assert by_case["tests.test_llm.test_extract"]["passed"] is False

    def test_durations_become_latency_ms(self, tmp_path):
        path = tmp_path / "report.xml"
        path.write_text(PYTEST_REPORT, encoding="utf-8")
        rows = adapters.parse_pytest_junit(path)
        by_case = {r["case"]: r for r in rows}
        assert by_case["tests.test_llm.test_sql_gen"]["latency_ms"] == 120.0
        assert by_case["tests.test_llm.test_sql_join"]["latency_ms"] == 250.0

    def test_xunit1_root_shape(self, tmp_path):
        path = tmp_path / "report.xml"
        path.write_text(XUNIT1_REPORT, encoding="utf-8")
        rows = adapters.parse_pytest_junit(path)
        by_case = {r["case"]: r for r in rows}
        # classname-less testcase keeps its bare name
        assert "tests.test_alpha" in by_case
        assert "test_beta" in by_case
        assert by_case["test_beta"]["passed"] is True
        assert "latency_ms" not in by_case["test_beta"]

    def test_dtd_is_rejected(self, tmp_path):
        path = tmp_path / "evil.xml"
        path.write_text(
            '<?xml version="1.0"?><!DOCTYPElol [<!ENTITY x "y">]>'
            "<testsuites/>".replace("DOCTYPElol", "DOCTYPE lol"),
            encoding="utf-8")
        with pytest.raises(ValueError, match="DTD"):
            adapters.parse_pytest_junit(path)

    def test_invalid_xml_is_rejected(self, tmp_path):
        path = tmp_path / "broken.xml"
        path.write_text("this is not <xml", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid XML"):
            adapters.parse_pytest_junit(path)

    def test_empty_report_is_rejected(self, tmp_path):
        path = tmp_path / "empty.xml"
        path.write_text("<testsuites/>", encoding="utf-8")
        with pytest.raises(ValueError, match="no usable testcases"):
            adapters.parse_pytest_junit(path)

    def test_all_skipped_report_is_rejected(self, tmp_path):
        path = tmp_path / "skipped.xml"
        path.write_text(textwrap.dedent(
            """\
            <testsuites>
              <testsuite name="t">
                <testcase classname="t" name="x"><skipped/></testcase>
              </testsuite>
            </testsuites>
            """
        ), encoding="utf-8")
        with pytest.raises(ValueError, match="no usable testcases"):
            adapters.parse_pytest_junit(path)

    def test_malformed_time_is_tolerated(self, tmp_path):
        path = tmp_path / "weird.xml"
        path.write_text(textwrap.dedent(
            """\
            <testsuite name="t">
              <testcase classname="t" name="x" time="fast"/>
            </testsuite>
            """
        ), encoding="utf-8")
        rows = adapters.parse_pytest_junit(path)
        assert rows[0]["passed"] is True
        assert "latency_ms" not in rows[0]

    def test_rows_feed_the_stats_pipeline(self, tmp_path):
        """The whole point: ingested rows are ordinary eval rows."""
        from evalgate import stats
        path = tmp_path / "report.xml"
        path.write_text(PYTEST_REPORT, encoding="utf-8")
        rows = adapters.parse_pytest_junit(path)
        agg = stats.aggregate(rows, k=1, base_seed=42)
        assert agg.total_runs == 3
        assert agg.total_passes == 1
        assert agg.p95_latency_ms is not None
        assert agg.p95_latency_ms > 0
        assert agg.failing_cases == [
            "tests.test_llm.test_extract", "tests.test_llm.test_sql_join"]
