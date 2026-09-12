"""Tests for `evalgate init` scaffolding and CLI surface."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evalgate import __version__, init as init_mod
from evalgate import cli as cli_mod


def test_init_creates_config_and_runner(tmp_path: Path) -> None:
    created = init_mod.init_project(tmp_path)
    assert str(tmp_path / "svx.evalgate.yaml") in created
    assert str(tmp_path / "evals" / "run_evals.py") in created
    cfg = (tmp_path / "svx.evalgate.yaml").read_text(encoding="utf-8")
    assert "evals:" in cfg
    assert "min_pass_at_k" in cfg
    runner = (tmp_path / "evals" / "run_evals.py").read_text(encoding="utf-8")
    assert "SVX_SEED" in runner


def test_init_never_overwrites(tmp_path: Path) -> None:
    init_mod.init_project(tmp_path)
    cfg_path = tmp_path / "svx.evalgate.yaml"
    cfg_path.write_text("# custom config, must survive\n", encoding="utf-8")
    created = init_mod.init_project(tmp_path)
    assert str(cfg_path) not in created
    assert cfg_path.read_text(encoding="utf-8").startswith("# custom config")


def test_cmd_init_reports_created_files(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = cli_mod.main(["init", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "created:" in out
    assert "next steps" in out


def test_cmd_init_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cli_mod.main(["init", str(tmp_path)])
    capsys.readouterr()
    rc = cli_mod.main(["init", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "created:" not in out


def test_version_command(capsys: pytest.CaptureFixture) -> None:
    rc = cli_mod.main(["version"])
    assert rc == 0
    assert __version__ in capsys.readouterr().out


def test_dash_dash_version_flag() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "evalgate", "--version"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert __version__ in proc.stdout


def test_scaffolded_config_loads_without_warnings(tmp_path: Path) -> None:
    """The scaffolded yaml must match the real parser schema exactly:
    every key recognized, zero warnings, thresholds actually applied."""
    from evalgate import config as config_mod
    init_mod.init_project(tmp_path)
    cfg, warnings = config_mod.load_config(tmp_path / "svx.evalgate.yaml")
    assert warnings == []
    assert cfg.gate.k == 5
    assert cfg.gate.min_pass_at_k == 0.80
    assert cfg.gate.min_mean_score == 0.60
    assert cfg.gate.regression.tolerance == 0.04
    assert cfg.evals.repetitions == 20
    assert cfg.baseline.auto_write_on_missing is True


def test_scaffolded_project_gates_end_to_end(tmp_path: Path) -> None:
    """init -> first run (baseline) -> second run stays green."""
    cli_mod.main(["init", str(tmp_path)])
    rc1 = cli_mod.main(["run", "--config", str(tmp_path / "svx.evalgate.yaml")])
    assert rc1 == 0  # first run: auto-writes baseline, threshold-only
    assert (tmp_path / ".svx" / "baseline.json").exists()
    rc2 = cli_mod.main(["run", "--config", str(tmp_path / "svx.evalgate.yaml")])
    assert rc2 == 0  # unchanged rerun against baseline: green


def test_run_json_emits_machine_document(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cli_mod.main(["init", str(tmp_path)])
    capsys.readouterr()
    rc = cli_mod.main([
        "run", "--config", str(tmp_path / "svx.evalgate.yaml"), "--json",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    doc = json.loads(out)
    assert doc["green"] is True
    assert doc["verdict"] == "GREEN"
    assert doc["version"] == __version__
    assert isinstance(doc["metrics"]["pass_at_k_mean"], float)
    assert doc["metrics"]["pass_at_k_ci"][0] <= doc["metrics"]["pass_at_k_mean"]
    assert doc["metrics"]["pass_at_k_ci"][1] >= doc["metrics"]["pass_at_k_mean"]
    assert doc["total_runs"] > 0
