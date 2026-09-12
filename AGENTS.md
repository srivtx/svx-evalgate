# AGENTS.md — SVX EvalGate

Guidance for AI coding agents (and humans in a hurry) working in this
repository. **Read this file before changing anything.** It encodes the
project's intent, its non-negotiable invariants, and the decisions that
look unusual but are deliberate.

## What this project is

EvalGate is a deterministic statistics gate for AI evals in CI. It wraps
the eval suite a user already runs (one JSON object per stdout line),
repeats it with fixed seeds, computes pass@k plus Wilson/bootstrap
confidence intervals, and reduces the result to **one green-or-red check
on the pull request**. It is the productization of **gap #1** — the
evals-in-CI adapter, "the sharpest unmet need found in the entire
research" — from the [SVX Industry Gap Analysis 2025-2026]
(https://github.com/srivtx/svx-research).

The strategic thesis: eval platforms monetize dashboards and judge-token
spend, so none of them is structurally motivated to make the CI gate
itself excellent. The merge gate is the only control point every
engineer already obeys. EvalGate is deliberately narrow — deterministic
statistics over an existing suite, one check — because that narrowness
is the moat.

## Current state (verify before trusting this section)

- **v2.1.0** on `main`, tagged. Minor releases add capabilities; patches
  fix them; a 3.0 must be *earned in production*, not ambition.
- 264 tests passing, 92% coverage (CI gate at 85%), ruff + mypy clean.
- Zero runtime dependencies — Python 3.10+ standard library only.
- CI: three workflows, all green on GitHub runners — `ci.yml`
  (lint + tests + coverage + self-checks), `evalgate.yml` (dogfooding
  the gate on this repo's own example), `release.yml` (build + opt-in
  PyPI publish on tag).
- Not yet on PyPI (workflow ready; waiting on trusted-publisher setup —
  a user-side GitHub/PyPI action, not a code task).

## Non-negotiable invariants

Breaking any of these is a correctness bug, not a style choice:

1. **Determinism is the product.** Nothing in the pipeline may use
   wall-clock time, `hash()`, or unseeded randomness. Sub-seeds derive
   from SHA-256 of `(base_seed, metric name)`. Same seed in → same
   verdict out, byte-identical reports, bootstrap included. Enforced by
   `test_same_seed_same_verdict_and_metrics`.
2. **Interval-vs-interval comparison — never point-vs-interval.** A PR
   is REGRESSION only when the current run's *entire* confidence
   interval sits outside the baseline's interval beyond the tolerance
   band (below for higher-is-better metrics, above for latency/cost).
   Overlapping intervals are PASS — that is what makes the gate
   flake-proof. Comparing a point estimate against an interval
   false-fires on unchanged systems; that was a real bug in v1.0 and it
   must not come back.
3. **Direction-aware gating.** Higher-is-better: `pass_at_k_mean`,
   `pass_rate`, `mean_score`. Lower-is-better: all latency metrics and
   cost. Threshold and regression logic invert accordingly in `gate.py`
   and `diff.py`.
4. **Zero dependencies.** Stdlib only. The YAML subset parser is
   hand-rolled *on purpose* — supply-chain-free install is a stated,
   badge-displayed feature. Adding a runtime dependency requires an
   overwhelming reason and a changelog entry explaining it.
5. **Exit codes mean what they say.** 0 = green, 1 = red (threshold
   miss or statistically confident regression), 2 = config/command
   error. PR-comment failures degrade to warnings and never fail a
   user's build.
6. **Versioning discipline (explicit owner instruction).** Do NOT bump
   versions quickly. The tool earns version numbers; it does not chase
   them. Docs-only changes get no bump; a new capability is a minor; a
   contract break is the only reason for a major, and 3.0 specifically
   requires 2.x proving itself in real pipelines first.

## Commands

```bash
# install for development (use a venv)
pip install -e .[dev]

# test / lint / typecheck — all three must be clean before any commit
python3 -m pytest -q
python3 -m pytest -q --cov=evalgate --cov-report=term   # keep >= 85%
python3 -m ruff check .
python3 -m mypy evalgate

# 30-second end-to-end demo (the whole product story)
cd examples/llm-app
evalgate run --update-baseline      # GREEN: baseline recorded
DEMO_MODE=regression evalgate run   # RED:   regression caught, exit 1
evalgate run                        # GREEN: back within band
evalgate diff                       # baseline vs last run, exit 1 evidence
evalgate trend                      # recent runs + sparkline

# dogfood: gate this repo's own 264-test pytest suite
pytest --junitxml=/tmp/report.xml
evalgate ingest --format pytest-junit /tmp/report.xml
```

Artifacts land in `.svx/` (baseline.json, report.md, report.html,
report.xml, history.jsonl). Baseline is committed; history is not.

## Module map

| File | Responsibility |
|---|---|
| `evalgate/config.py` | YAML-subset + JSON config parsing, validation, `config_hash` (floors and thresholds participate — refresh baselines after touching gate config) |
| `evalgate/runner.py` | Executes the eval command `repetitions` times with `SVX_SEED = base_seed + i`; validates JSONL rows (`passed` required; `score`/`latency_ms`/`cost_usd` optional, finite, >= 0) |
| `evalgate/stats.py` | pass@k unbiased estimator, Wilson intervals, nearest-rank percentiles, seeded bootstrap CIs; `AggregateStats` carries values + CIs + raw lists |
| `evalgate/baseline.py` | Baseline store (value + low + high per metric); backward-compatible with v1 point-only baselines |
| `evalgate/gate.py` | Threshold + regression verdicts; per-case floors; direction map; loud notes for absent cases |
| `evalgate/report.py` | Markdown report |
| `evalgate/htmlreport.py` | Self-contained HTML report — inline SVG only, XSS-escaped, zero external resources |
| `evalgate/junitxml.py` | JUnit XML projection of gate verdicts |
| `evalgate/adapters.py` | `ingest --format pytest-junit`: JUnit XML → rows; DTD/entity rejection at parser door |
| `evalgate/diff.py` | Snapshot comparison reusing the gate's band logic |
| `evalgate/history.py` | Bounded JSONL run log, trim, sparkline |
| `evalgate/github.py` | PR comment + step summary (failure-degrades-to-warning) |
| `evalgate/init.py` | `evalgate init` scaffolding — never overwrites existing files |
| `evalgate/cli.py` | Command surface; `run`/`ingest` share `_gate_pipeline` for identical reports/history/exit codes |

## Testing conventions and known gotchas

- **Interpreter-proof tests.** Python 3.12 and 3.13 have different
  `random` streams; a test that depends on exact pass counts can flake
  across interpreters. Where exactness matters, assert on invariants
  (monotonicity, containment, verdicts) rather than raw counts — see
  the per-case floor e2e test for the pattern.
- **JUnit identity.** Threshold and regression checks on the *same*
  metric must carry different classnames (`evalgate.gate` vs
  `evalgate.regression`) or testcase identities collide.
- **Old baselines.** Baselines recorded before v2 lack latency/cost
  intervals; the gate must skip those metrics cleanly, not crash.
- Every fix worth remembering is reflected in the test suite — if you
  fix a bug, add the test that would have caught it (the project's
  history of real bug fixes — point-vs-interval false-fires, Wilson
  clamping, workflow path double-prefixes — is all regression-tested).

## Deliberate design decisions (do not "fix" these)

- Hand-rolled YAML subset parser → zero dependencies; exotic configs
  are directed to native JSON support.
- Nearest-rank percentiles → deterministic across platforms; no
  interpolation ambiguity.
- Bootstrap capped at 2,000 iterations for percentile CIs → gated runs
  stay fast; determinism preserved by seed derivation.
- Skipped tests dropped on ingestion → a skip is the absence of a data
  point, not a failure.
- JUnit XML is a *projection* of the gate, not a separate computation —
  verdicts are computed once in `gate.py` and rendered everywhere.

## Release process

1. All checks green: 264+ tests, ruff, mypy, coverage >= 85%.
2. Update `CHANGELOG.md` (Keep-a-Changelog), `README.md` version badge
   and roadmap checkboxes, `docs/methodology.md` if statistics changed.
3. Version bump **per the discipline above** — default is: don't, unless
   a user-visible capability shipped.
4. Commit, tag `vX.Y.Z`, push `main` + tag. `release.yml` builds and
   (only if the trusted-publisher variable is set) publishes.

## Roadmap (open items)

- PyPI publication — blocked on user-side trusted-publisher setup only.
- More ingestion formats: Go test JSON, Jest, vitest (same row pipeline
  as pytest-junit; adapters are ~150 lines each).
- `evalgate why` — plain-language explanation of a RED verdict.

## Where the full context lives

- `README.md` — product surface, quickstart, config reference.
- `docs/methodology.md` — the statistics, precisely.
- `CONTRIBUTING.md` — ground rules (determinism is the product).
- `CHANGELOG.md` — every user-visible change, per release.
- The parent research: [svx-research](https://github.com/srivtx/svx-research)
  — evidence base for why this product should exist at all.
