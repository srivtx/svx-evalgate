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
"""

__version__ = "1.0.0"
__all__ = [
    "config", "stats", "runner", "baseline", "gate", "report", "github",
    "cli",
]
