# Changelog

All notable changes to SVX EvalGate are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/).

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
