"""Tests for config loading (YAML subset + JSON) and the runner."""
import json

import pytest

from evalgate import config as config_mod
from evalgate import runner as runner_mod

YAML_DOC = """
# SVX EvalGate example config
evals:
  command: "python evals/run_evals.py"
  repetitions: 12
  base_seed: 424242
  bootstrap_iterations: 500

gate:
  k: 2
  min_pass_at_k: 0.9
  min_mean_score: 0.75
  regression:
    mode: relative
    tolerance: 0.04

baseline:
  path: .svx/baseline.json
  auto_write_on_missing: false

report:
  path: .svx/report.md
"""


class TestYamlSubset:
    def test_parse_full_doc(self):
        data = config_mod.parse_yaml_subset(YAML_DOC)
        assert data["evals"]["repetitions"] == 12
        assert data["evals"]["command"] == "python evals/run_evals.py"
        assert data["gate"]["k"] == 2
        assert data["gate"]["regression"]["mode"] == "relative"
        assert data["gate"]["regression"]["tolerance"] == 0.04
        assert data["baseline"]["auto_write_on_missing"] is False

    def test_scalars(self):
        data = config_mod.parse_yaml_subset(
            "a: 1\nb: 1.5\nc: true\nd: 'text # not comment'\ne: hi\n")
        assert data == {"a": 1, "b": 1.5, "c": True, "d": "text # not comment", "e": "hi"}

    def test_bad_indentation_rejected(self):
        with pytest.raises(ValueError):
            config_mod.parse_yaml_subset("evals:\n   command: x\n")

    def test_missing_colon_rejected(self):
        with pytest.raises(ValueError):
            config_mod.parse_yaml_subset("just text\n")


class TestLoadConfig:
    def test_load_yaml(self, tmp_path):
        path = tmp_path / "svx.evalgate.yaml"
        path.write_text(YAML_DOC, encoding="utf-8")
        cfg, warnings = config_mod.load_config(path)
        assert cfg.evals.repetitions == 12
        assert cfg.evals.base_seed == 424242
        assert cfg.gate.k == 2
        assert cfg.gate.min_pass_at_k == 0.9
        assert cfg.gate.regression.mode == "relative"
        assert cfg.gate.regression.tolerance == pytest.approx(0.04)
        assert cfg.source_path == path
        assert warnings == []

    def test_load_json(self, tmp_path):
        path = tmp_path / "svx.evalgate.json"
        path.write_text(json.dumps({
            "evals": {"repetitions": 5, "command": "echo"},
            "gate": {"min_pass_at_k": 0.5},
        }), encoding="utf-8")
        cfg, _ = config_mod.load_config(path)
        assert cfg.evals.repetitions == 5
        assert cfg.gate.min_pass_at_k == 0.5

    def test_defaults(self, tmp_path):
        path = tmp_path / "svx.evalgate.yaml"
        path.write_text("evals:\n  command: x\n", encoding="utf-8")
        cfg, _ = config_mod.load_config(path)
        assert cfg.evals.repetitions == 20
        assert cfg.gate.k == 1
        assert cfg.gate.regression.tolerance == 0.05
        assert cfg.baseline.path == ".svx/baseline.json"

    def test_unknown_key_warns(self, tmp_path):
        path = tmp_path / "svx.evalgate.yaml"
        path.write_text("evals:\n  command: x\n  bananas: 3\n", encoding="utf-8")
        cfg, warnings = config_mod.load_config(path)
        assert cfg.evals.command == "x"
        assert any("bananas" in w for w in warnings)

    def test_validation(self, tmp_path):
        path = tmp_path / "svx.evalgate.yaml"
        path.write_text("evals:\n  repetitions: 0\n", encoding="utf-8")
        with pytest.raises(ValueError):
            config_mod.load_config(path)
        path.write_text("gate:\n  regression:\n    mode: sideways\n", encoding="utf-8")
        with pytest.raises(ValueError):
            config_mod.load_config(path)

    def test_config_hash_stable(self, tmp_path):
        path = tmp_path / "svx.evalgate.yaml"
        path.write_text(YAML_DOC, encoding="utf-8")
        cfg, _ = config_mod.load_config(path)
        h1 = cfg.config_hash()
        assert h1 == cfg.config_hash()
        cfg.gate.min_pass_at_k = 0.4
        assert cfg.config_hash() != h1

    def test_find_config(self, tmp_path):
        assert config_mod.find_config(None, tmp_path) is None
        assert config_mod.find_config("nope.yaml", tmp_path) is None
        p = tmp_path / "svx.evalgate.yml"
        p.write_text("evals:\n  command: x\n", encoding="utf-8")
        assert config_mod.find_config(None, tmp_path) == p
        assert config_mod.find_config("svx.evalgate.yml", tmp_path) == p


EVAL_SCRIPT = """import json, os
seed = int(os.environ.get("SVX_SEED", "0"))
passed = seed % 2 == 0
print(json.dumps({"case": "odd-even", "passed": passed, "score": 0.9 if passed else 0.4}))
"""


class TestRunner:
    def _write_script(self, tmp_path):
        script = tmp_path / "evals" / "run_evals.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(EVAL_SCRIPT, encoding="utf-8")
        return f"python {script}"

    def test_seed_env_flows_to_child(self, tmp_path):
        command = self._write_script(tmp_path)
        outcome = runner_mod.run_evals(command, repetitions=4, base_seed=10, cwd=tmp_path)
        assert len(outcome.rows) == 4
        # seeds 10,11,12,13 -> passed pattern T,F,T,F
        passed = [r["passed"] for r in outcome.rows]
        assert passed == [True, False, True, False]
        assert all(r["_seed"] == 10 + i for i, r in enumerate(outcome.rows))

    def test_malformed_json_rejected(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text('print("this is not json")\n', encoding="utf-8")
        with pytest.raises(runner_mod.RunnerError, match="not valid JSON"):
            runner_mod.run_evals(f"python {bad}", repetitions=1, base_seed=0, cwd=tmp_path)

    def test_missing_fields_rejected(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text('import json; print(json.dumps({"case": "x"}))\n', encoding="utf-8")
        with pytest.raises(runner_mod.RunnerError, match="missing 'passed'"):
            runner_mod.run_evals(f"python {bad}", repetitions=1, base_seed=0, cwd=tmp_path)

    def test_nonzero_exit_rejected(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("import sys; sys.exit(3)\n", encoding="utf-8")
        with pytest.raises(runner_mod.RunnerError, match="exit 3"):
            runner_mod.run_evals(f"python {bad}", repetitions=1, base_seed=0, cwd=tmp_path)

    def test_no_output_rejected(self, tmp_path):
        quiet = tmp_path / "quiet.py"
        quiet.write_text("pass\n", encoding="utf-8")
        with pytest.raises(runner_mod.RunnerError, match="no JSON rows"):
            runner_mod.run_evals(f"python {quiet}", repetitions=1, base_seed=0, cwd=tmp_path)

    def test_score_optional(self, tmp_path):
        script = tmp_path / "noscore.py"
        script.write_text(
            'import json; print(json.dumps({"case": "x", "passed": True}))\n',
            encoding="utf-8")
        outcome = runner_mod.run_evals(f"python {script}", repetitions=2, base_seed=0, cwd=tmp_path)
        assert all(r.get("score") is None for r in outcome.rows)


class TestV2Config:
    def _load(self, tmp_path, doc):
        p = tmp_path / "svx.evalgate.yaml"
        p.write_text(doc, encoding="utf-8")
        return config_mod.load_config(p)

    def test_v2_defaults(self, tmp_path):
        cfg, warnings = self._load(tmp_path, "evals:\n  repetitions: 2\n")
        assert cfg.gate.max_p95_latency_ms is None
        assert cfg.gate.max_total_cost_usd is None
        assert cfg.report.html_path == ".svx/report.html"
        assert cfg.history.enabled is True
        assert cfg.history.path == ".svx/history.jsonl"
        assert cfg.history.max_entries == 500
        assert warnings == []

    def test_v2_full_load(self, tmp_path):
        doc = """
evals:
  repetitions: 2
  command: "python evals/run_evals.py"
gate:
  min_pass_at_k: 0.8
  max_p95_latency_ms: 1500
  max_total_cost_usd: 1.25
report:
  path: .svx/report.md
  html_path: .svx/gate.html
history:
  enabled: false
  path: .svx/hist.jsonl
  max_entries: 42
"""
        cfg, warnings = self._load(tmp_path, doc)
        assert warnings == []
        assert cfg.gate.max_p95_latency_ms == 1500
        assert cfg.gate.max_total_cost_usd == 1.25
        assert cfg.report.html_path == ".svx/gate.html"
        assert cfg.history.enabled is False
        assert cfg.history.path == ".svx/hist.jsonl"
        assert cfg.history.max_entries == 42

    def test_html_disable_with_null(self, tmp_path):
        doc = """
evals:
  repetitions: 2
report:
  html_path: ~
"""
        cfg, _warnings = self._load(tmp_path, doc)
        assert cfg.report.html_path is None

    def test_zero_latency_threshold_rejected(self, tmp_path):
        doc = """
evals:
  repetitions: 2
gate:
  max_p95_latency_ms: 0
"""
        with pytest.raises(ValueError):
            self._load(tmp_path, doc)

    def test_bad_history_max_entries(self, tmp_path):
        doc = """
evals:
  repetitions: 2
history:
  max_entries: 0
"""
        with pytest.raises(ValueError):
            self._load(tmp_path, doc)

    def test_config_hash_covers_v2_thresholds(self, tmp_path):
        base = "evals:\n  repetitions: 2\n"
        c1, _ = self._load(tmp_path, base + "gate:\n  max_p95_latency_ms: 1200\n")
        c2, _ = self._load(tmp_path, base + "gate:\n  max_p95_latency_ms: 9999\n")
        assert c1.config_hash() != c2.config_hash()


class TestRunnerV2Fields:
    def test_latency_and_cost_parsed(self):
        stdout = ('{"case": "a", "passed": true, "latency_ms": "123.4", '
                  '"cost_usd": 0.0012}\n'
                  '{"case": "b", "passed": false, "latency_ms": 200}\n')
        rows = runner_mod._parse_jsonl(stdout, "test")
        assert rows[0]["latency_ms"] == 123.4
        assert rows[0]["cost_usd"] == 0.0012
        assert rows[1]["latency_ms"] == 200.0
        assert rows[1].get("cost_usd") is None

    def test_negative_latency_rejected(self):
        stdout = '{"case": "a", "passed": true, "latency_ms": -5}\n'
        with pytest.raises(runner_mod.RunnerError, match="latency_ms"):
            runner_mod._parse_jsonl(stdout, "test")

    def test_negative_cost_rejected(self):
        stdout = '{"case": "a", "passed": true, "cost_usd": -0.01}\n'
        with pytest.raises(runner_mod.RunnerError, match="cost_usd"):
            runner_mod._parse_jsonl(stdout, "test")

    def test_nonfinite_latency_rejected(self):
        stdout = '{"case": "a", "passed": true, "latency_ms": 1e999}\n'
        with pytest.raises(runner_mod.RunnerError):
            runner_mod._parse_jsonl(stdout, "test")

    def test_non_numeric_latency_rejected(self):
        stdout = '{"case": "a", "passed": true, "latency_ms": "fast"}\n'
        with pytest.raises(runner_mod.RunnerError, match="latency_ms"):
            runner_mod._parse_jsonl(stdout, "test")

    def test_null_fields_pass_through(self):
        stdout = '{"case": "a", "passed": true, "latency_ms": null, "cost_usd": null}\n'
        rows = runner_mod._parse_jsonl(stdout, "test")
        assert rows[0]["latency_ms"] is None
        assert rows[0]["cost_usd"] is None
