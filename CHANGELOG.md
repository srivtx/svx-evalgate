# Changelog

All notable changes to SVX EvalGate are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-09-12

### Added

- **Latency and cost statistics.** Eval rows may carry `latency_ms` and
  `cost_usd` (validated: finite, >= 0, optional). EvalGate computes mean /
  p50 / p95 / max latency with bootstrap confidence intervals (percentile
  CIs capped at 2,000 resamples for speed), plus total and mean cost with
  an interval derived from the bootstrap of the per-row mean.
- **Upper-bound thresholds.** `gate.max_p95_latency_ms` and
  `gate.max_total_cost_usd` fail the gate when the run exceeds them —
  the missing "how slow is too slow / how expensive is too expensive"
  checks for AI features.
- **Direction-aware regression bands.** `p95_latency_ms` and
  `total_cost_usd` are tracked in the baseline and compared
  interval-vs-interval with inverted direction: REGRESSION fires when the
  current interval sits entirely *above* the baseline interval plus the
  band. Rates and scores keep the original below-is-worse logic. Older
  baselines without the new metrics are honored and simply skip them.
- **Self-contained HTML report** (`.svx/report.html` by default,
  `report.html_path: ~` disables). One file, inline SVG, no external
  resources: metric cards with confidence intervals, per-case pass@k bar
  chart with threshold marker and pass-rate ghost bars, pass@k trend line
  across history runs with verdict-colored dots, score and latency
  histograms, per-case and verdict tables, and a RED-reasons block. All
  case names HTML-escaped (tested against script-tag and
  attribute-injection payloads). Screenshots ship in `docs/assets/`.
- **Run history.** Every run appends a compact summary to
  `.svx/history.jsonl` (bounded by `history.max_entries`, oldest trimmed;
  corrupt lines skipped). Feeds the trend chart and the new CLI.
- **`evalgate trend [--limit N]`** — recent runs as a table plus a unicode
  sparkline of pass@k.
- **`evalgate baseline reset`** — delete the baseline (graceful no-op when
  absent); `evalgate baseline` alone still prints it.
- **Score distribution statistics.** p50 / p95 / min / max of all row
  scores, in `--json` and both reports.
- **CI hardening.** New lint job (ruff + mypy, both clean), coverage
  measurement with an 85% gate (`pytest-cov`), and a v2 self-check step
  verifying the HTML report, history file, and `evalgate trend` on every
  push. Release workflow uploads distribution artifacts and includes an
  opt-in PyPI publish job (gated on the repository variable
  `PUBLISH_TO_PYPI=true` with trusted publishing).
- **Community scaffolding.** Bug-report and feature-request issue forms
  (with a statistics-ground section), discussions contact link, and a PR
  template with a determinism checklist.
- 85 new tests (108 → 193): percentile exactness and determinism,
  percentile-CI containment and seed sensitivity, latency/cost aggregation
  and accessor coverage, direction-aware gate logic (regression / noise /
  improved / relative-band), v2 config loading and validation, runner
  validation of the new fields, history append/trim/corruption/sparkline,
  HTML report structure, XSS escaping, external-resource-free output,
  SVG well-formedness, baseline reset, trend reporting, and full-pipeline
  e2e (markdown + html + history + json artifacts, latency threshold
  tripping red).

### Changed

- `--json` output now includes `p95_latency_ms`, `p95_latency_ci`, and
  `total_cost_usd` in `metrics`, and the markdown report gains P95 latency
  and total-cost lines when rows carry the fields. Both remain
  byte-identical across same-seed reruns.
- `config_hash` covers the new threshold keys, so baselines recorded with
  different v2 thresholds are flagged for refresh (informational note, as
  before).
- The demo suite in `examples/llm-app` now emits latency and cost, and the
  config sets `max_p95_latency_ms: 1200` so the regression walkthrough
  trips both a quality and a latency threshold. `evalgate init` scaffolds
  the new optional keys (commented) and its demo emitter includes
  `latency_ms` / `cost_usd`.
- Version pin in `action.yml` documentation examples updated to `@v2`.

### Compatibility

- Existing configs, baselines, and runner scripts work unchanged: all v2
  row fields are optional, all v2 config keys default sensibly, and old
  baselines skip the new metrics. The only behavior change on upgrade is
  the additional HTML report file and history file written under `.svx/`
  (both gitignored; disable via `report.html_path: ~` and
  `history.enabled: false`).

## [1.1.0] - 2026-09-12

### Added

- `evalgate init [DIR]` — scaffolds `svx.evalgate.yaml` and a runnable
  `evals/run_evals.py` demo emitter. Never overwrites existing files, so it
  is safe to run inside a live repository.
- `evalgate run --json` — machine-readable result document on stdout
  (verdict, reasons, all metrics with confidence intervals, failing cases,
  baseline state). Enables dashboards, bots, and non-GitHub CI systems to
  consume the gate result directly.
- `--version` flag on the top-level CLI.
- PEP 561 type-checking marker (`py.typed`); the package ships its type
  hints.
- 48 new tests (59 → 107), including property tests for the statistics
  core: `pass@k` bounds, monotonicity in `k` and `c`, exactness against
  the combinatorial definition; Wilson containment, width shrinkage, and
  unit-interval confinement; bootstrap determinism, seed sensitivity, and
  mean containment; aggregate invariants and end-to-end determinism.
- End-to-end test that a freshly `init`-scaffolded project gates green on
  its second run.
- This changelog, `CONTRIBUTING.md`, `SECURITY.md`, and
  `docs/methodology.md`.
- Release workflow: tagged builds produce sdist + wheel artifacts and a
  GitHub Release.

### Fixed

- `wilson_interval` now clamps to `[0, 1]` to remove floating-point
  overshoot (e.g. `1.0000000000000002` at `p = 1.0`).

### Changed

- Package metadata URLs point to the canonical `srivtx/svx-evalgate`
  repository.

## [1.0.0] - 2026-09-12

### Added

- Initial release: deterministic statistics gate for AI evals in CI.
- Unbiased `pass@k` estimator (Chen et al., 2021 closed form), Wilson
  score intervals for pass rates, seeded percentile bootstrap for scores.
- Interval-vs-interval regression comparison: a regression fires only when
  the current confidence interval sits entirely below the baseline
  interval minus the configured band — point-estimate comparisons are
  deliberately rejected as statistically unsound (they false-fire on
  unchanged systems).
- JSONL runner contract with `SVX_SEED` exported per repetition.
- Baseline store (`value` + CI bounds), markdown report, GitHub step
  summary + pull-request comment, composite GitHub Action, and a live
  dogfooding pipeline (the repo gates its own demo suite).
- 59 tests, including the live-demo paths: baseline write, unchanged
  rerun stays green, noise with a different seed stays green, and forced
  regression exits 1 with interval evidence.
