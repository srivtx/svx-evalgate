"""End-to-end tests: the full pipeline against a mock eval suite.

These are the tests that matter most - they prove the product's two
headline claims:

  1. Determinism: same seed -> same verdict, byte-identical metrics.
  2. The gate actually catches a regression and turns red.
"""
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

MOCK_EVALS = textwrap.dedent(
    """
    import json, os, random

    CASES = [
        ("sql-gen-basic", 0.98),
        ("sql-gen-join", 0.93),
        ("summarize-faithful", 0.91),
        ("extract-entities", 0.96),
        ("classify-tone", 0.97),
        ("route-support", 0.94),
        ("translate-idiom", 0.90),
    ]

    regression = os.environ.get("DEMO_MODE") == "regression"
    seed = int(os.environ.get("SVX_SEED", "0"))
    rng = random.Random(seed)

    for name, quality in CASES:
        q = quality - 0.15 if regression else quality
        passed = rng.random() < q
        score = min(1.0, max(0.0, rng.gauss(q, 0.05)))
        print(json.dumps({
            "case": name, "passed": passed, "score": round(score, 4),
        }))
    """
)


@pytest.fixture()
def project(tmp_path):
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals" / "run_evals.py").write_text(MOCK_EVALS, encoding="utf-8")
    (tmp_path / "svx.evalgate.yaml").write_text(textwrap.dedent(
        """
        evals:
          command: "python evals/run_evals.py"
          repetitions: 24
          base_seed: 777001
          bootstrap_iterations: 2000

        gate:
          k: 1
          min_pass_at_k: 0.80
          min_mean_score: 0.60
          regression:
            mode: absolute
            tolerance: 0.04
        """
    ), encoding="utf-8")
    return tmp_path


def _evalgate(project, *args, env_extra=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(project),
           "PYTHONPATH": str(REPO_ROOT),
           "DEMO_MODE": "", **(env_extra or {})}
    return subprocess.run(
        [sys.executable, "-m", "evalgate", *args],
        cwd=project, env=env, capture_output=True, text=True, timeout=300,
    )


class TestFullPipeline:
    def test_first_run_green_and_writes_report(self, project):
        proc = _evalgate(project, "run", "--report-stdout")
        assert proc.returncode == 0, proc.stderr
        assert "evalgate: verdict: GREEN" in proc.stderr
        report = (project / ".svx" / "report.md").read_text(encoding="utf-8")
        assert report.startswith("## EvalGate - GREEN")
        assert "Pass@1 by case" in report
        assert "`translate-idiom`" in report
        # threshold-only mode: no baseline yet
        assert "no baseline on record" in proc.stderr

    def test_baseline_update(self, project):
        proc = _evalgate(project, "run", "--update-baseline")
        assert proc.returncode == 0, proc.stderr
        baseline_file = project / ".svx" / "baseline.json"
        assert baseline_file.exists()
        doc = json.loads(baseline_file.read_text(encoding="utf-8"))
        assert doc["tool"] == "svx-evalgate"
        assert doc["schema_version"] == 1
        assert doc["base_seed"] == 777001
        pak = doc["metrics"]["pass_at_k_mean"]
        assert 0.5 < pak["value"] <= 1.0
        assert pak["low"] <= pak["value"] <= pak["high"]
        assert doc["metrics"]["mean_score"]["value"] > 0.6

    def test_same_seed_same_verdict_and_metrics(self, project):
        # establish baseline
        _evalgate(project, "run", "--update-baseline")
        # two gated runs with identical seed
        r1 = _evalgate(project, "run", "--report-stdout")
        r2 = _evalgate(project, "run", "--report-stdout")
        assert r1.returncode == r2.returncode == 0
        # identical markdown reports (deterministic bootstrap included)
        assert r1.stdout == r2.stdout
        # identical baselines when recomputed
        b1 = json.loads((project / ".svx" / "baseline.json").read_text(encoding="utf-8"))
        _evalgate(project, "run", "--update-baseline")
        b2 = json.loads((project / ".svx" / "baseline.json").read_text(encoding="utf-8"))
        assert b1["metrics"] == b2["metrics"]

    def test_noise_with_different_seed_stays_green(self, project):
        # THE anti-flake guarantee: a different seed (different sampling
        # noise) against an unchanged system must not fail the gate.
        _evalgate(project, "run", "--update-baseline")
        # change the seed -> different samples, same underlying quality
        cfg = project / "svx.evalgate.yaml"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace("777001", "999333"),
                       encoding="utf-8")
        proc = _evalgate(project, "run")
        assert proc.returncode == 0, proc.stderr
        assert "verdict: GREEN" in proc.stderr

    def test_regression_turns_red(self, project):
        _evalgate(project, "run", "--update-baseline")
        proc = _evalgate(project, "run", "--report-stdout",
                         env_extra={"DEMO_MODE": "regression"})
        assert proc.returncode == 1, proc.stderr
        assert "evalgate: verdict: RED" in proc.stderr
        assert "REGRESSION" in proc.stdout
        report = (project / ".svx" / "report.md").read_text(encoding="utf-8")
        assert report.startswith("## EvalGate - RED")

    def test_baseline_subcommand(self, project):
        proc = _evalgate(project, "baseline")
        assert proc.returncode == 2  # no baseline yet -> error exit
        _evalgate(project, "run", "--update-baseline")
        proc = _evalgate(project, "baseline")
        assert proc.returncode == 0
        doc = json.loads(proc.stdout)
        assert doc["tool"] == "svx-evalgate"

    def test_exit_code_2_on_runner_error(self, project):
        (project / "svx.evalgate.yaml").write_text(
            'evals:\n  command: "python evals/does_not_exist.py"\n',
            encoding="utf-8")
        proc = _evalgate(project, "run")
        assert proc.returncode == 2

    def test_missing_config_is_clean_error(self, tmp_path):
        proc = _evalgate(tmp_path, "run")
        assert proc.returncode != 0
        assert "config not found" in proc.stdout + proc.stderr

    def test_version(self, project):
        proc = _evalgate(project, "version")
        assert proc.returncode == 0
        assert "svx-evalgate" in proc.stdout
