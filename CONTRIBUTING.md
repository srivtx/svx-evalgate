# Contributing to SVX EvalGate

Thanks for your interest — contributions are welcome.

## The one rule that matters most

**Determinism is the product.** Any change that makes identical inputs
produce different verdicts, or different machines produce different
verdicts, is a bug regardless of what else it improves. Before proposing a
change to the statistics, read
[docs/methodology.md](docs/methodology.md) and make sure you can argue why
the change preserves reproducibility.

## Development setup

```bash
git clone https://github.com/srivtx/svx-evalgate
cd svx-evalgate
pip install -e .[dev]
pytest
```

The full suite (107 tests) runs in about ten seconds. It includes the
live-demo paths: a real gated run that writes a baseline, an unchanged
rerun that must stay green, a different-seed run that must also stay
green (noise tolerance), and a forced regression that must exit 1 with
interval evidence. If any of those break, treat it as a release blocker.

## Ground rules

1. **Zero runtime dependencies** is a design constraint. The gate must run
   in a bare CI container; stdlib only. Proposals that add a required
   dependency will be declined unless the case is overwhelming.
2. **Python 3.10+** compatibility. Use `from __future__ import annotations`
   and modern typing, but no 3.12-only syntax.
3. **Tests are not optional.** New behavior ships with tests that would
   fail without it. Statistical behavior ships with property tests
   (bounds, monotonicity, determinism), not just example values.
4. **Every public function carries type hints and a docstring** that states
   the contract, including what happens on bad input.
5. **No silent fallbacks.** If a config field is malformed, raise with a
   message that names the field and the file. A gate that guesses is a
   gate that lies.

## Adding a metric

Metrics live in `evalgate/stats.py` (`AggregateStats.metric_value` /
`metric_ci`) and flow through `evalgate/gate.py`. A new metric must:

- define both a point estimate **and** a confidence interval,
- have a deterministic interval (seeded bootstrap or closed form),
- ship with property tests (containment of the point estimate,
  determinism across runs),
- update `docs/methodology.md` with the interval construction.

## Commit style and releases

- Commits: imperative subject line, body explains *why*. Multi-paragraph
  is fine.
- `CHANGELOG.md` gets an entry for every user-visible change.
- Releases: tag `vX.Y.Z`; the release workflow builds the sdist + wheel
  and publishes a GitHub Release. Version lives in
  `pyproject.toml` and `evalgate/__init__.py` — keep them in sync.

## Reporting a bug

Open an issue with: the version (`evalgate version`), the config file
(sanitized), the full stderr output, and — critically — whether the
verdict is reproducible on a rerun. For statistical surprises, include
the report markdown (`.svx/report.md`), which carries the intervals the
decision was made on.

## Security

See [SECURITY.md](SECURITY.md). Short version: report privately, do not
open an issue.
