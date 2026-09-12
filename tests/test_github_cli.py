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
