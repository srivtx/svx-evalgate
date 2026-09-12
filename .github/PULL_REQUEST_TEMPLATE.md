## What

<!-- One paragraph: what this PR changes and why. -->

## Type

<!-- Keep the one that applies. -->

- [ ] Statistics (estimator / interval / gate logic)
- [ ] Report output (markdown / HTML)
- [ ] CLI or config schema
- [ ] CI / packaging / docs
- [ ] Other

## Determinism checklist

Every number EvalGate prints must be reproducible from (seed, rows). If this
PR adds a number to any output, confirm:

- [ ] New outputs derive only from row data + `SVX_SEED` (no wall clock in metrics, no `hash()`, no set iteration order)
- [ ] Tests cover the new behavior, including the noise-vs-regression distinction where applicable
- [ ] `pytest` passes locally with the same seed twice producing byte-identical output

## Docs

- [ ] README / docs updated if config keys, CLI flags, or report fields changed
- [ ] CHANGELOG.md has an entry
