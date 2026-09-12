"""Unit tests for GitHub integration + CLI parser (fast, no network)."""
from __future__ import annotations

import pytest

from evalgate import cli, github


class TestPrNumber:
    def test_merge_ref(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REF", "refs/pull/42/merge")
        assert github._pr_number() == 42

    def test_branch_ref(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
        assert github._pr_number() is None

    def test_missing(self, monkeypatch):
        monkeypatch.delenv("GITHUB_REF", raising=False)
        assert github._pr_number() is None

    def test_malformed(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REF", "refs/pull/not-a-number/merge")
        assert github._pr_number() is None


class TestStepSummary:
    def test_writes_when_env_set(self, tmp_path, monkeypatch):
        target = tmp_path / "summary.md"
        target.write_text("# existing\n", encoding="utf-8")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
        assert github.write_step_summary("appended line") is True
        assert "appended line" in target.read_text(encoding="utf-8")
        assert "# existing" in target.read_text(encoding="utf-8")

    def test_noop_without_env(self, monkeypatch):
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        assert github.write_step_summary("x") is False


class TestPrComment:
    def test_noop_without_context(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
        assert github.post_pr_comment("x") is False

    def test_noop_on_plain_branch(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
        monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
        assert github.post_pr_comment("x") is False


class TestParser:
    def test_run_flags(self):
        parser = cli.build_parser()
        args = parser.parse_args(
            ["run", "--config", "c.yaml", "--update-baseline",
             "--report-stdout", "--json"])
        assert args.func is cli.cmd_run
        assert args.config == "c.yaml"
        assert args.update_baseline is True
        assert args.report_stdout is True
        assert args.json is True

    def test_baseline_actions(self):
        parser = cli.build_parser()
        assert parser.parse_args(["baseline"]).action == "show"
        assert parser.parse_args(["baseline", "reset"]).action == "reset"

    def test_baseline_bad_action_rejected(self):
        parser = cli.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["baseline", "explode"])

    def test_trend_defaults(self):
        parser = cli.build_parser()
        args = parser.parse_args(["trend"])
        assert args.func is cli.cmd_trend
        assert args.limit == 15

    def test_trend_limit(self):
        parser = cli.build_parser()
        assert parser.parse_args(["trend", "--limit", "5"]).limit == 5

    def test_init_directory_default(self):
        parser = cli.build_parser()
        assert parser.parse_args(["init"]).directory == "."

    def test_version_flag(self, capsys):
        parser = cli.build_parser()
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--version"])
        assert exc.value.code == 0
        assert "svx-evalgate" in capsys.readouterr().out

    def test_no_command_prints_help(self, capsys):
        assert cli.main([]) == cli.EXIT_ERROR
        out = capsys.readouterr().out
        assert "run" in out and "trend" in out


PYTEST_XML = """<?xml version="1.0"?>
<testsuites>
  <testsuite name="t" tests="2">
    <testcase classname="t" name="a" time="0.1"/>
    <testcase classname="t" name="b" time="0.2"/>
  </testsuite>
</testsuites>
"""


def _write_config(tmp_path, extra=""):
    (tmp_path / "svx.evalgate.yaml").write_text(
        "evals:\n"
        "  command: \"python emit.py\"\n"
        "  repetitions: 2\n"
        "  base_seed: 11\n"
        "  bootstrap_iterations: 100\n"
        "gate:\n"
        "  k: 1\n"
        "  min_pass_at_k: 0.5\n"
        "report:\n"
        "  html_path: ~\n"
        "  junit_path: .svx/report.xml\n"
        + extra,
        encoding="utf-8")
    (tmp_path / "emit.py").write_text(
        "import json\n"
        "for i in range(2):\n"
        "    print(json.dumps({'case': 'c%d' % i, 'passed': True}))\n",
        encoding="utf-8")


class TestCliDirect:
    """In-process CLI coverage: main() with argv, no subprocess wrapping."""

    def test_run_pipeline_direct(self, tmp_path, monkeypatch, capsys):
        _write_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert cli.main(["run", "--update-baseline", "--json"]) == 0
        out = capsys.readouterr()
        doc = __import__("json").loads(out.out)
        assert doc["green"] is True
        assert (tmp_path / ".svx" / "baseline.json").exists()
        assert (tmp_path / ".svx" / "report.md").exists()
        assert (tmp_path / ".svx" / "report.xml").exists()
        assert not (tmp_path / ".svx" / "report.html").exists()  # disabled

    def test_run_missing_config_exits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            cli.main(["run"])

    def test_ingest_direct_green(self, tmp_path, monkeypatch, capsys):
        _write_config(tmp_path)
        (tmp_path / "r.xml").write_text(PYTEST_XML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert cli.main(["ingest", "r.xml", "--update-baseline",
                         "--report-stdout"]) == 0
        out = capsys.readouterr()
        assert "ingested 2 row(s)" in out.err
        assert "ingested from pytest-junit" in out.out  # markdown on stdout

    def test_ingest_missing_source_error(self, tmp_path, monkeypatch):
        _write_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert cli.main(["ingest", "ghost.xml"]) == cli.EXIT_ERROR

    def test_ingest_no_source_arg_error(self, tmp_path, monkeypatch):
        _write_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):  # argparse: source is required
            cli.main(["ingest"])

    def test_ingest_bad_xml_error(self, tmp_path, monkeypatch):
        _write_config(tmp_path)
        (tmp_path / "bad.xml").write_text("<oops", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert cli.main(["ingest", "bad.xml"]) == cli.EXIT_ERROR

    def test_diff_default_after_runs(self, tmp_path, monkeypatch, capsys):
        _write_config(tmp_path)
        (tmp_path / "r.xml").write_text(PYTEST_XML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        cli.main(["ingest", "r.xml", "--update-baseline"])
        cli.main(["ingest", "r.xml"])
        assert cli.main(["diff"]) == 0
        out = capsys.readouterr()
        assert "no metric is confidently worse" in out.out

    def test_diff_explicit_files(self, tmp_path, monkeypatch, capsys):
        _write_config(tmp_path)
        (tmp_path / "r.xml").write_text(PYTEST_XML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        cli.main(["ingest", "r.xml", "--update-baseline"])
        import shutil
        shutil.copy(tmp_path / ".svx" / "baseline.json", tmp_path / "a.json")
        shutil.copy(tmp_path / ".svx" / "baseline.json", tmp_path / "b.json")
        assert cli.main(["diff", "a.json", "b.json"]) == 0

    def test_diff_no_baseline_error(self, tmp_path, monkeypatch):
        _write_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert cli.main(["diff"]) == cli.EXIT_ERROR

    def test_diff_missing_file_error(self, tmp_path, monkeypatch):
        _write_config(tmp_path)
        (tmp_path / "r.xml").write_text(PYTEST_XML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        cli.main(["ingest", "r.xml", "--update-baseline"])
        assert cli.main(["diff", "ghost.json"]) == cli.EXIT_ERROR

    def test_diff_bad_snapshot_error(self, tmp_path, monkeypatch):
        _write_config(tmp_path)
        (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert cli.main(["diff", "bad.json", "bad.json"]) == cli.EXIT_ERROR

    def test_baseline_show_and_reset_direct(self, tmp_path, monkeypatch, capsys):
        _write_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        cli.main(["run", "--update-baseline"])
        assert cli.main(["baseline"]) == 0
        assert '"metrics"' in capsys.readouterr().out
        assert cli.main(["baseline", "reset"]) == 0
        assert cli.main(["baseline"]) == cli.EXIT_ERROR  # gone now

    def test_trend_direct(self, tmp_path, monkeypatch, capsys):
        _write_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert cli.main(["trend"]) == cli.EXIT_ERROR  # no history yet
        cli.main(["run"])
        assert cli.main(["trend", "--limit", "1"]) == 0
        assert "last 1 of 1 run(s)" in capsys.readouterr().out

    def test_runner_error_maps_to_exit_2(self, tmp_path, monkeypatch):
        _write_config(tmp_path)
        (tmp_path / "emit.py").write_text("import sys; sys.exit(3)\n",
                                         encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert cli.main(["run"]) == cli.EXIT_ERROR
