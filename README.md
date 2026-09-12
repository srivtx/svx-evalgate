# SVX EvalGate

**Deterministic statistics for non-deterministic software.** EvalGate wraps the eval suite you already run and turns its flaky output into one ordinary, trustworthy **green-or-red check on your pull request**.

![SVX](https://img.shields.io/badge/SVX-EvalGate-1d9459?style=flat-square)
![version](https://img.shields.io/badge/version-1.1.0-40c884?style=flat-square)
![tests](https://img.shields.io/badge/tests-108%20passing-2f5140?style=flat-square)
![deps](https://img.shields.io/badge/dependencies-zero%20(stdlib%20only)-747d78?style=flat-square)
![typed](https://img.shields.io/badge/typed-PEP%20561-388860?style=flat-square)
![license](https://img.shields.io/badge/license-MIT-1d9459?style=flat-square)

[![CI](https://github.com/srivtx/svx-evalgate/actions/workflows/ci.yml/badge.svg)](https://github.com/srivtx/svx-evalgate/actions/workflows/ci.yml)

---

## The problem

Your LLM feature shipped with evals. Your team wrote them, ran them in a notebook, saw **87% pass**, and felt good. Then the evals moved into CI - and everything broke:

- The suite passes on one run, fails on the next. Someone adds `--retries 3`. Now it always passes, including when the model got worse.
- Somebody rewrites a prompt in a PR. The evals run once, come back green, and merge - because one sample of a non-deterministic system says nothing.
- Someone asks "is the model *better* than last month?" There is no answer, because nothing was ever recorded.

This is the gap SVX Research ranked **#1 of twelve** validated opportunities in the [SVX Industry Gap Analysis 2025-2026](https://github.com/srivtx/svx-research): eval platforms monetize dashboards and judge-token spend, so none of them is structurally motivated to make the CI gate itself excellent. The field is empty at exactly the moment every team is shipping AI features - **362 documented AI incidents in 2025, up from 233 the year before, while enterprise LLM spend doubled in six months.**

## What EvalGate does

```
              your eval suite               EvalGate                  your PR
        ┌────────────────────────┐   ┌────────────────────────┐   ┌──────────┐
        │  python evals/run.py   │──▶│  24 seeded repetitions │──▶│  GREEN   │
        │  prints JSON lines     │   │  pass@k  per case      │   │  or      │
        │  (any runner)          │   │  Wilson + bootstrap CI │   │  RED     │
        └────────────────────────┘   │  regression bands      │   └──────────┘
                                     └────────────────────────┘
```

| Capability | What it actually means |
|---|---|
| **pass@k** | The unbiased combinatorial estimator from the Codex/HumanEval paper, computed per eval case: the probability the case passes at least once in k runs. Not "did my single sample pass". |
| **Fixed seeds** | Every repetition runs your command with `SVX_SEED = base_seed + i`. Same seed in, same verdict out - flaky gates are a design failure, not a fact of life. |
| **Regression bands** | A committed baseline (`.svx/baseline.json`) records what "good" means - value *and* confidence interval. A PR goes red only when the current run's entire interval sits below the baseline's interval minus your tolerance: noise cannot separate two intervals from the same distribution. |
| **Bootstrap CI** | Seeded percentile bootstrap for score means - deterministic, because the seed derives from a stable digest of (base_seed, metric). |
| **Zero dependencies** | Pure Python standard library. Installs in seconds, runs anywhere, has no supply chain. |
| **Plays well with others** | EvalGate does not host your evals, judge them, or store them. It is not another platform. It connects whatever you already run to the workflow engineers already trust. |

## Quickstart

**Zero-to-gated in four commands** - scaffold a config and a runnable demo suite, then let the statistics do the talking:

```bash
pip install svx-evalgate
evalgate init                  # writes svx.evalgate.yaml + evals/run_evals.py
evalgate run --update-baseline # first run: record what good looks like
evalgate run                   # every run after: gate against it
```

Or wire an existing suite by hand:

**1. Wrap your eval suite.** Make your runner print one JSON object per line per invocation:

```json
{"case": "sql-gen-basic", "passed": true, "score": 0.93}
```

`passed` is required; `score` is optional. A ten-line wrapper around pytest, a notebook, or an existing harness is the entire integration.

**2. Add the config** (`svx.evalgate.yaml` in the repo root):

```yaml
evals:
  command: "python evals/run_evals.py"
  repetitions: 24
  base_seed: 777001

gate:
  k: 1
  min_pass_at_k: 0.80
  min_mean_score: 0.60
  regression:
    mode: absolute        # or "relative"
    tolerance: 0.04
```

**3. Install and run locally** (same verdict as CI, because seeds):

```bash
pip install svx-evalgate      # or: pip install git+https://github.com/srivtx/svx-evalgate
evalgate run --update-baseline   # first run: record what good looks like
evalgate run                     # every run after: gate against it
evalgate run --json              # machine-readable verdict for bots and dashboards
```

Exit codes: `0` green · `1` red (threshold or regression) · `2` error. Add `--json` for a machine-readable document (verdict, reasons, every metric with its confidence interval, failing cases, baseline state) — for non-GitHub CI systems, dashboards, or chat bots that post the gate result.

**4. Gate your pull requests** - `.github/workflows/evalgate.yml`:

```yaml
name: evalgate
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: write
  pull-requests: write
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: srivtx/svx-evalgate@v1     # the action installs and runs the gate
        with:
          update-baseline: ${{ github.ref == 'refs/heads/main' }}
```

Pushes to `main` refresh the baseline; PRs are gated against it. The check posts a full report to the PR - metric table, per-case pass@k, confidence intervals, baseline provenance - and to the job's step summary.

## The report you get on every PR

```markdown
## EvalGate - GREEN

Deterministic statistics for `24` repetitions (base seed `777001`) across **10 case(s) / 240 runs**.

### Thresholds

| Metric | Current | 95% CI | Required | Verdict |
|---|---:|---:|---:|---|
| `pass_at_k_mean` | 0.921 | [0.867, 0.971] | min 0.800 | PASS |
| `mean_score` | 0.919 | [0.911, 0.927] | min 0.600 | PASS |

### Regression vs baseline

| Metric | Current [CI] | Baseline [CI] | Band | Verdict |
|---|---|---|---:|---|
| `pass_at_k_mean` | 0.921 [0.867, 0.971] | 0.921 [0.867, 0.971] | +/-0.040 | PASS |
| `pass_rate` | 0.921 [0.880, 0.949] | 0.921 [0.880, 0.949] | +/-0.040 | PASS |
| `mean_score` | 0.919 [0.911, 0.927] | 0.919 [0.911, 0.927] | +/-0.040 | PASS |

### Pass@1 by case

| Case | Runs | Passes | Pass rate | pass@1 |
|---|---:|---:|---:|---:|
| `sql-gen-basic` | 24 | 24 | 1.00 | 1.000 |
| `sql-gen-join` | 24 | 24 | 1.00 | 1.000 |
| `translate-idiom` | 24 | 20 | 0.83 | 0.833 |
...
```

Full example: [`examples/llm-app/`](examples/llm-app/) - a complete demo project with a seeded mock eval suite. Reproduce the whole story in ~30 seconds:

```bash
cd examples/llm-app
evalgate run --update-baseline      # GREEN: baseline recorded
DEMO_MODE=regression evalgate run   # RED:   regression caught, exit 1
evalgate run                        # GREEN: back within band
```

## How the statistics work

**pass@k.** For a case run `n` times with `c` passes, the unbiased estimator of "passes at least once in k future runs" is `1 − C(n−c, k) / C(n, k)` (Chen et al., 2021). It is exact, closed-form, and never flaps. EvalGate reports it per case and aggregates the mean.

**Regression bands.** The baseline stores each metric's confidence interval alongside its value (Wilson intervals for rates, seeded bootstrap for means and pass@k). A PR is called REGRESSION only when the current run's *entire* interval sits below the baseline's interval minus your tolerance - i.e. the run is confidently worse than the baseline by more than the band. Overlapping intervals are PASS, which is what makes the gate flake-proof: sampling noise moves point estimates around, but it cannot separate two intervals drawn from the same distribution. The band width is yours to choose, absolute or relative.

**Determinism.** Nothing in the pipeline uses wall-clock time, `hash()`, or unseeded randomness. Sub-seeds derive from SHA-256 of `(base_seed, metric name)`. The test suite proves it: two full runs with the same seed produce byte-identical reports, including the bootstrap.

## Why a gate and not a dashboard

The research finding worth repeating: eval platforms live in dashboards *outside* the workflow, where a regression is an email nobody reads at 6 p.m. on Friday. The merge gate is the only control point every engineer already obeys. EvalGate is deliberately narrow - it wraps existing suites in deterministic statistics and posts one check - because that narrowness is the moat. The big platforms cannot monetize "make the CI adapter excellent"; a small team can make it perfect.

## Configuration reference

| Key | Default | Meaning |
|---|---|---|
| `evals.command` | `python evals/run_evals.py` | Shell command; runs `repetitions` times |
| `evals.repetitions` | `20` | Repetitions per gate evaluation |
| `evals.base_seed` | `20260912` | `SVX_SEED = base_seed + i` per repetition |
| `evals.working_dir` | config dir | cwd for the eval command |
| `evals.bootstrap_iterations` | `10000` | Bootstrap resample count (seeded) |
| `gate.k` | `1` | k for per-case pass@k |
| `gate.min_pass_at_k` | `0.85` | Aggregate threshold on mean pass@k |
| `gate.min_mean_score` | *(off)* | Optional threshold on mean score |
| `gate.regression.mode` | `absolute` | `absolute` or `relative` (fraction of baseline) |
| `gate.regression.tolerance` | `0.05` | Band width before REGRESSION |
| `baseline.path` | `.svx/baseline.json` | Baseline location (commit it) |
| `baseline.auto_write_on_missing` | `false` | Write a baseline on first run |
| `report.path` | `.svx/report.md` | Markdown report location |

JSON configs (`svx.evalgate.json`) are supported natively. The YAML subset parser handles the schema above with zero dependencies; anything exotic, use JSON.

## Design guarantees

- **The gate never flakes.** Same seed, same verdict - enforced by `test_same_seed_same_verdict_and_metrics` - and a different seed on an unchanged system stays green too (`test_noise_with_different_seed_stays_green`).
- **CI failures mean what they say.** Exit 1 only on a threshold miss or a statistically confident regression; exit 2 for config/command errors; PR-comment failures degrade to warnings and never fail your build.
- **Your evals stay yours.** JSONL on stdout is the entire contract. No vendor format, no lock-in, no upload.
- **No dependencies.** Stdlib only - `pip install` has nothing to resolve.

## Repository layout

```
evalgate/            the package (config, runner, stats, baseline, gate, report, github, init, cli)
tests/               108 tests: statistics property tests, gate logic, config/runner, full e2e
examples/llm-app/    complete demo: seeded mock suite + config + regression walkthrough
action.yml           GitHub Action (composite, installs and runs the gate)
docs/methodology.md  the statistics, precisely: pass@k, Wilson, seeded bootstrap, interval-vs-interval
.github/workflows/   ci.yml (tests + self-checks), evalgate.yml (dogfooding), release.yml
CHANGELOG.md         every user-visible change, per release
CONTRIBUTING.md      ground rules (determinism is the product)
SECURITY.md          reporting and scope
```

## Origin

EvalGate builds **gap #1** of the [SVX Industry Gap Analysis 2025-2026](https://github.com/srivtx/svx-research): the evals-in-CI adapter - "the sharpest unmet need found in the entire research," ranked first of twelve opportunities by evidence strength, openness of the field, and realism of a small-team distribution model. The research repo contains the full evidence base: 362 documented AI incidents in 2025, the collapse of manual verification under AI code volume, and the structural reasons the incumbent platforms will not build this themselves.

## Roadmap

- [x] `evalgate init` scaffolding (v1.1.0)
- [x] `--json` machine-readable output (v1.1.0)
- [ ] JUnit-XML and pytest report adapters (zero-wrapper ingestion)
- [ ] `evalgate diff` - compare two baselines at the command line
- [ ] Cost dimensions: token spend per case alongside pass@k
- [ ] GitLab CI and generic webhook exits
- [ ] Per-case regression bands (not just aggregate metrics)

## License

MIT - see [LICENSE](LICENSE). Part of SVX Research.
