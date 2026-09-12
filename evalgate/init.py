"""Scaffolding for new EvalGate projects.

``evalgate init`` writes a starter ``svx.evalgate.yaml`` and a runnable
``evals/run_evals.py`` demo into the working directory (or a target
directory), so a repository goes from zero to a gated eval suite in one
command. Existing files are never overwritten.
"""
from __future__ import annotations

from pathlib import Path

CONFIG_TEMPLATE = """# SVX EvalGate configuration
# Docs: https://github.com/srivtx/svx-evalgate

evals:
  # The command EvalGate wraps. It must print JSONL rows to stdout:
  #   {"case": "<id>", "passed": true|false, "score": 0.0-1.0|null,
  #    "latency_ms": 123.4|null, "cost_usd": 0.0012|null}
  # SVX_SEED is exported on every repetition so your suite can stay
  # deterministic where it wants to be.
  command: "python evals/run_evals.py"
  repetitions: 20          # per-case runs; pass@k and CIs need >= 2
  base_seed: 20260912      # any integer; change it to reroll the noise
  bootstrap_iterations: 10000

baseline:
  path: .svx/baseline.json
  auto_write_on_missing: true   # first run records, later runs gate

report:
  path: .svx/report.md
  html_path: .svx/report.html   # self-contained SVG report (set ~ to skip)

history:                     # v2: run log behind `evalgate trend`
  enabled: true
  path: .svx/history.jsonl
  max_entries: 500

gate:
  k: 5                      # pass@k: chance at least one of k runs passes
  min_pass_at_k: 0.80       # threshold on the mean of per-case pass@k
  min_mean_score: 0.60      # optional threshold on mean score (delete to skip)
  # max_p95_latency_ms: 1500   # v2: RED when p95 latency exceeds this
  # max_total_cost_usd: 1.00   # v2: RED when total run cost exceeds this
  regression:
    mode: absolute          # "absolute" or "relative" (fraction of baseline)
    tolerance: 0.04         # band before a run is confidently RED
"""

RUNNER_TEMPLATE = '''"""Demo eval emitter for SVX EvalGate.

Prints JSONL rows. Replace the case list and the pass/score logic with
your real eval suite; keep the SVX_SEED contract.
"""
import json
import os
import random

SEED = int(os.environ.get("SVX_SEED", "0"))
rng = random.Random(SEED)

# Demo cases: replace with your own.
CASES = [
    ("capital-of-france", 0.95),
    ("sort-a-list", 0.90),
    ("sql-join", 0.80),
    ("refactor-hint", 0.70),
]

for name, quality in CASES:
    passed = rng.random() < quality
    score = round(rng.uniform(max(0.0, quality - 0.1), min(1.0, quality + 0.1)), 3)
    latency_ms = round(rng.uniform(120.0, 480.0), 1)
    cost_usd = round(rng.uniform(0.0004, 0.0021), 6)
    print(json.dumps({
        "case": name,
        "passed": passed,
        "score": score,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "seed": SEED,
    }))
'''

README_ADDENDUM = """evals/README.md is a placeholder; delete it once you document your suite.
"""


def init_project(target_dir: Path) -> list[str]:
    """Create starter files in ``target_dir``.

    Returns the list of files written. Existing files are left untouched,
    so ``init`` is always safe to run on a live repository.
    """
    created: list[str] = []

    cfg_path = target_dir / "svx.evalgate.yaml"
    if not cfg_path.exists():
        cfg_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        created.append(str(cfg_path))

    evals_dir = target_dir / "evals"
    runner_path = evals_dir / "run_evals.py"
    if not runner_path.exists():
        evals_dir.mkdir(parents=True, exist_ok=True)
        runner_path.write_text(RUNNER_TEMPLATE, encoding="utf-8")
        created.append(str(runner_path))

    return created
