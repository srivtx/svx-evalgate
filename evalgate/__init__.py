"""SVX EvalGate - deterministic statistics gate for AI evals in CI.

Part of SVX Research (gap #1 of the SVX Industry Gap Analysis 2025-2026:
the evals-in-CI adapter). EvalGate wraps whatever eval suite you already
run and turns its non-deterministic output into one ordinary, trustworthy
green-or-red check on the pull request:

  - pass@k (unbiased combinatorial estimator) per eval case,
  - Wilson intervals for pass rates, bootstrap intervals for scores,
  - regression bands against a committed baseline,
  - fully deterministic: same seed in, same verdict out.

EvalGate does not compete with eval platforms - it connects them to the
workflow engineers already trust.

v2 adds: latency and cost statistics (p50/p95, totals, bootstrap CIs),
upper-bound thresholds for them, a self-contained HTML report with
inline SVG charts, run history with `evalgate trend`, and direction-aware
regression bands (lower-is-better metrics).

v2.1 adds: JUnit XML output for CI test-report integrations (GitLab,
Jenkins, Azure), pytest-JUnit ingestion (`evalgate ingest` - gate an
existing test suite with zero emitter code), `evalgate diff` for
snapshot comparisons, and per-case pass@k floors.
"""

__version__ = "2.1.0"
__all__ = [
    "adapters",
    "baseline",
    "cli",
    "config",
    "diff",
    "gate",
    "github",
    "history",
    "htmlreport",
    "init",
    "junitxml",
    "report",
    "runner",
    "stats",
]
