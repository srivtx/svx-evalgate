# Methodology: the statistics behind EvalGate

This document explains, precisely, why EvalGate computes what it computes —
and just as importantly, what it deliberately refuses to compute. The gate
exists because "the evals moved a little" is the most expensive sentence in
an AI codebase: it blocks merges that were fine and passes merges that were
broken, in roughly equal measure. Every design decision below optimizes for
one property: **the same eval results must always produce the same verdict,
and verdicts must mean what they claim to mean.**

## The problem: non-determinism breaks `pytest` semantics

Traditional tests are deterministic assertions: same input, same output,
same verdict. LLM evals are not — the same prompt can pass on one run and
fail on the next. When a CI system treats each run as a binary fact, every
flake becomes a build failure, and teams respond by disabling the evals
entirely (the exact failure mode documented across 2025-2026 CI tooling:
flaky evals "wreck your CI signal"). The fix is not retry-until-green;
the fix is to stop treating a single run as a fact and start estimating a
quantity that is actually stable: the probability structure of the suite.

## pass@k: the unbiased estimator

For each eval case we estimate **pass@k** — the probability that at least
one of `k` independent runs passes. We use the unbiased closed-form
estimator from Chen et al. (2021, the HumanEval/Codex paper):

```
pass@k(n, c, k) = 1 - C(n-c, k) / C(n, k)
```

where `n` is the number of runs executed and `c` the number that passed.
Two properties make it the right choice for CI:

1. **It is exact, not simulated.** For fixed `n`, `c`, and `k` the value is
   a combinatorial identity — there is no sampling noise in the estimator
   itself. (EvalGate's test suite verifies this against the product-form
   definition.)
2. **It is monotone in both `c` and `k`**, matching intuition: more passes
   can never lower the estimate, and drawing more runs can never lower the
   chance of at least one pass.

The suite-level metric is the mean of per-case pass@k, which is the
quantity the threshold gate protects.

## Confidence intervals: Wilson and bootstrap

A point estimate without an interval is a coin with no thickness. Two
interval types cover the two kinds of metrics EvalGate aggregates:

- **Wilson score interval** for pass rates (binomial proportions). Wilson
  is used instead of the naive normal-approximation interval because it
  behaves correctly at the extremes — a 100% pass rate over few runs gets
  a wide interval, not a zero-width one, and the bounds never leave
  `[0, 1]`.
- **Seeded percentile bootstrap** for means of continuous scores. The
  bootstrap is seeded from a stable SHA-256 digest of
  `(base_seed, metric name)` — never from Python's `hash()`, which is
  salted per process. Same inputs, same interval, every time, on every
  machine.

Determinism is a hard constraint, not a nicety: a gate that flips verdicts
between identical runs is worse than no gate.

## Regression logic: interval vs interval

The subtlest decision in the gate. The naive approach — compare the current
point estimate against the baseline point estimate — is statistically
unsound and operationally catastrophic: the current run's *point* estimate
sits above the baseline *point* on luck alone about half the time, and a
fixed tolerance band does not survive contact with different sample sizes.
(EvalGate v1.0 caught exactly this bug in its own live demo: comparing a
Wilson lower bound against a baseline point estimate false-fired on an
unchanged system at n=240.)

EvalGate instead compares **interval against interval**:

> A regression is declared only when the current confidence interval lies
> entirely below the baseline interval, with the configured band applied
> on top.

This means noise that stays inside the combined uncertainty never fails
the gate, while genuine degradation — the whole interval moving down past
the band — always does. The gate trades a small, quantified false-negative
rate (real-but-tiny regressions inside the band) for a near-zero
false-positive rate, which is the correct trade for CI: engineers stop
reading gates that cry wolf.

## The runner contract

EvalGate wraps your existing suite rather than replacing it. The contract
is one line: the command must print JSONL rows to stdout —
`{"case": ..., "passed": ..., "score": ...}` — and may consume the
`SVX_SEED` environment variable, which EvalGate re-exports on every
repetition (base seed plus repetition index). Everything else — the eval
framework, the model, the judging — stays yours.

## What EvalGate does not do

- It does not host dashboards or judge LLMs; it connects the statistics to
  the merge gate, which the eval platforms deliberately leave open.
- It does not guarantee a green gate means "no regression anywhere" — it
  guarantees the verdict is reproducible and that stated regressions are
  outside combined statistical uncertainty.
- It does not require a fixed eval count: statistics degrade gracefully
  (wider intervals) with fewer runs, and the gate's conservatism scales
  with the honesty of the data.

## Latency and cost statistics (v2)

**Percentiles.** Latency percentiles use the nearest-rank definition: for
`n` observations and target `q`, report the `ceil(q/100 * n)`-th smallest
value. This is deliberately not an interpolating percentile: a sort and an
index produce bit-identical results on every platform, which matters
because the gate's promise is determinism. On even `n`, the median is the
lower middle element - a documented choice, not an accident.

**Percentile confidence intervals.** The bootstrap CI for p95 resamples
rows with replacement, recomputes the percentile, and takes the 2.5th and
97.5th percentiles of the resampled statistics. Each resample costs a
sort, so iterations are capped at `min(bootstrap_iterations, 2000)` - the
seed still derives from SHA-256 of `(base_seed, "p95_latency_ms")`, so
the interval is exactly reproducible.

**Cost.** Total cost is the plain row sum. Its interval bootstraps the
per-row mean (the natural estimand) and scales the resulting bounds by the
row count. Mean-of-rows and sum-times-n carry the same information; the
sum is what the threshold gates on and what a budget owner reads.

**Direction-aware regression.** For rates and scores, worse means lower,
and REGRESSION fires when the current interval lies entirely below the
baseline interval minus the band. For `p95_latency_ms` and
`total_cost_usd`, worse means *higher*, so the comparison inverts:
REGRESSION when the current interval lies entirely above the baseline
interval plus the band. Overlap remains PASS in both directions - the
anti-flake guarantee is symmetric: noise cannot separate two intervals
from the same distribution, in either direction.

**History.** Each run appends one JSON line (timestamp, git SHA, verdict,
core metrics). The file is bounded (`history.max_entries`, oldest
trimmed) and never gates anything - it exists to answer "is the system
drifting?" over weeks, which a single baseline cannot. The HTML report
plots it; the CLI prints it. It is per-machine state like the report:
never commit it, never trust it as evidence - the baseline is the
reference.

## The HTML report

The report is a single HTML file with inline SVG and no external
resources (no fonts, scripts, stylesheets, or images), so it renders
identically in a browser tab, from `file://`, and inside CI artifact
zips. Every chart is generated deterministically from the run's
statistics; case names are HTML-escaped (the test suite feeds it
script-tag and attribute-injection payloads); numbers use tabular
figures. The only non-deterministic string anywhere in the file is the
generation timestamp in the footer.
