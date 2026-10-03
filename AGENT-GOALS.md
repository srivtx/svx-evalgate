# AGENT-GOALS.md — Future Goals as Work Orders

**Self-contained work orders for SVX EvalGate's open goals.** Any agent
(human or AI) should be able to pick one goal from this file and
execute it without any other context than this document plus
[`AGENTS.md`](AGENTS.md). Product context and history live in
[`AGENTS.md`](AGENTS.md) and the [research repo]
(https://github.com/srivtx/svx-research); the *whole story* of how
EvalGate fits the SVX research-to-product system is in that repo's
`AGENT-MISSION.md`.

**Claiming a goal:** read it fully, check the current repo state hasn't
already shipped it, do the work, add a `CHANGELOG.md` entry under
`[Unreleased]`, and note the completion here by moving the goal to the
"Shipped" section at the bottom.

## Standing constraints (apply to every goal)

1. **Versioning discipline — owner's explicit rule.** Do NOT bump
   versions quickly; the tool matures first. Docs-only: no bump.
   New capability: one minor bump (e.g. 2.1.0 → 2.2.0), and a *batch*
   of related capabilities is one bump, not several. A major (3.0)
   must be earned by 2.x proving itself in real pipelines.
2. **The six invariants** in [`AGENTS.md`](AGENTS.md) — determinism,
   interval-vs-interval comparison, direction-aware gating, zero
   runtime dependencies, exit-code contract, meaningful CI failures.
3. **Definition of done:** tests added and green (264+ and growing),
   ruff + mypy clean, coverage ≥ 85%, docs updated, CI verified green
   on GitHub runners, worklog/CHANGELOG updated.

---

## Goal 1 — Publish to PyPI

**Why this goal exists.** EvalGate is release-ready but installable
only from git (`pip install git+https://github.com/srivtx/svx-evalgate`).
PyPI presence is the default install path every Python user expects,
and the README quickstart already says `pip install svx-evalgate` —
that command must actually work.

**Current state (verified):** packaging is complete — `pyproject.toml`
is fully configured (name `svx-evalgate`, version 2.1.0, readme,
classifiers, `evalgate` console script, PEP 561 `py.typed`);
`.github/workflows/release.yml` builds on any `v*` tag, runs the full
test suite first, builds sdist + wheel, **smoke-installs the wheel and
runs the gate**, attaches artifacts to the GitHub Release, and has an
opt-in publish job (`if: vars.PUBLISH_TO_PYPI == 'true'`, environment
`pypi`, OIDC `id-token: write`, using `pypa/gh-action-pypi-publish`).

**The blocker (and it is NOT code):** PyPI trusted publishing must be
registered on pypi.org by the **account owner** — an agent cannot do
this step, because it requires logging into PyPI as a human. Everything
else is below.

**Work order:**

- **Part A — agent-side verification (do first).**
  1. Clone fresh; `pip install -e .[dev]`; `python -m pytest -q` —
     all green before anything else.
  2. `pip install build && python -m build` — must produce both sdist
     and wheel without warnings that matter (read them; metadata
     warnings are worth fixing, vendoring noise is not).
  3. `pip install dist/*.whl` into a clean venv; run the README
     quickstart verbatim (`evalgate init`, `evalgate run
     --update-baseline`, `evalgate run`, `evalgate version`) in a temp
     dir. If this works, the package is provably installable.
  4. Check `twine check dist/*` (pip install twine) — zero errors.
- **Part B — hand the owner exact instructions.** Write them in the
  chat/PR, not just in a file (the owner must act outside GitHub
  Actions):
  1. PyPI → account → **Add a new pending publisher**: PyPI project
     name `svx-evalgate`, owner `srivtx`, repository `svx-evalgate`,
     workflow filename `release.yml`, environment name `pypi`.
  2. GitHub → repo `svx-evalgate` → Settings → Environments → create
     environment named `pypi` (can be empty; no secrets needed —
     trusted publishing uses OIDC, no tokens).
  3. GitHub → Settings → Secrets and variables → Actions → Variables
     → create repository variable `PUBLISH_TO_PYPI` = `true`.
- **Part C — after the owner confirms setup.**
  1. Verify no code changed since the last tag (docs-only commits
     since v2.1.0 are fine to publish as-is under 2.1.0 — **no bump**;
     if code did change, stop and re-evaluate: patch bump at most).
  2. `git tag v2.1.0-pypi`? **No — do not invent tag shapes.** If
     v2.1.0 was already tagged, the cleanest path is a patch-only
     release: fix nothing, bump nothing, instead re-run the existing
     tag's workflow via `workflow_dispatch` if needed, or tag the
     current docs-only HEAD as `v2.1.1` *only if* a re-tag is not
     possible. Prefer: ask the owner to delete nothing, tag current
     HEAD `v2.1.1` (patch = re-publication of the same capability
     set, changelog notes "PyPI publication"), push the tag, watch
     the run.
  3. Watch `release.yml` on the tag: build job → publish job → green.
  4. Verify: `pip install svx-evalgate` in a clean venv on a machine
     that never cloned the repo; `evalgate version` prints the
     version; `pip index versions svx-evalgate` shows it.
  5. Update README (remove `pip install git+...` alternative or demote
     it), add a PyPI shield badge, CHANGELOG entry, mark this goal
     shipped below.

**Acceptance criteria:** `pip install svx-evalgate` works from a clean
environment; version on PyPI matches `evalgate version`; README badge
green; release run green; no version bump beyond a patch.

---

## Goal 2 — Ingestion adapters: Go test JSON, Jest, vitest

**Why:** `evalgate ingest --format pytest-junit` (v2.1.0) proved the
pattern — gate an *existing* suite with zero wrapper code. Every new
format multiplies the addressable audience by a language/ecosystem.
All three formats are small deltas on the same row pipeline.

**Context:** `evalgate/adapters.py` is the template (~150 lines per
format). The contract: parse the foreign format → emit standard rows
(case, passed, optional latency_ms / cost_usd) → feed `_gate_pipeline`
(identical thresholds, bands, all three reports, history, exit codes).
Gotchas encoded in the pytest adapter that generalize: skipped tests
are *dropped* (a skip is the absence of a data point, not a failure);
durations map to `latency_ms`; malformed input must be rejected loudly
at the parser door (the pytest adapter rejects DTD/entity declarations
— apply the equivalent paranoia per format).

**Format specifics:**

- **Go test JSON** — `go test -json` emits NDJSON events
  (`{"Action":"pass|fail|skip","Package":"...","Test":"...","Elapsed":0.123}`).
  A case = a `Test` within a `Package` (combine as
  `Package::Test`); `pass`/`fail` map directly; `Elapsed` seconds →
  `latency_ms` (× 1000); `skip` rows dropped; package-level events
  without a `Test` field are ignored.
- **Jest** — `jest --json --useStderr` emits a single JSON document:
  `testResults[]` → `assertionResults[]` with `status` of
  `passed`/`failed`/`skipped`/`pending` and `duration` ms per
  assertion. `fullName` is the case name; `duration` → `latency_ms`;
  skipped/pending dropped.
- **vitest** — `vitest run --reporter=json` emits a Jest-shaped
  document (`testResults[]`/`assertionResults[]`); same mapping as
  Jest. One adapter can likely serve both with a tolerant parser, but
  validate against real fixtures from each before claiming it.

**Work order:** one adapter at a time, tests first (valid fixture →
correct rows; malformed fixture → clean error; determinism), real
fixtures checked in under `tests/fixtures/`. CLI gains
`--format go-test-json`, `--format jest-json`, `--format vitest-json`.
README table + `docs/` updated per adapter. **One minor bump for the
whole batch (2.2.0), not three.**

**Acceptance criteria:** each adapter runs green against a real-world
fixture; ingestion output identical in shape to pytest-junit; tests
≥ 264 + new; CI green; version 2.2.0 exactly once.

---

## Goal 3 — `evalgate why`

**Why:** a RED verdict currently shows *evidence* (intervals, bands,
pass counts) but the interpretation is left as an exercise. `why`
explains a verdict in plain language: which check fired (threshold /
regression / per-case floor), what the numbers mean, and the likely
next steps (re-run with more repetitions? widen the band deliberately?
the case actually got worse?).

**Constraints:** deterministic (it may read `.svx/` artifacts —
`report.md`, `history.jsonl`, baseline — or accept the `--json`
output of a run; never wall-clock, never unseeded randomness); zero
deps; text output to stdout with an exit code that does not interfere
with gate usage (it explains, it does not gate — recommend exit 0 with
`--strict` option to mirror the explained run's exit code).

**Scope guard:** natural-language *templating* over the existing
statistical objects — no new statistics, no LLM calls, no network.
The phrasing rules already exist in `docs/methodology.md`; `why`
reads like that document explaining your specific run.

**Acceptance criteria:** `evalgate run && evalgate why` narrates the
run correctly for GREEN, threshold-RED, regression-RED, and floor-RED
(four fixture cases in tests); docs updated; part of the 2.2.0 batch
or its own minor — owner's call, default: same batch.

---

## Goal 4 — Maturation criteria (what earns 2.2, what earns 3.0)

Not a coding goal — a **documented contract** this repo already states
and future agents must honor and enforce in review:

- **2.2.0** = the adapter batch + `why` (Goals 2-3). No more.
- **2.3+** = whatever real users ask for, one capability per minor,
  each proven by tests before the bump.
- **3.0** = contract break *and* evidence of 2.x running in real
  external pipelines (stars/uses/issues from strangers, a dependency
  appearing in someone else's CI). Absent that evidence, there is no
  3.0, no matter how much code changed. "The tool is young — it earns
  a 3.0 by proving 2.x in real pipelines, not by ambition."

When in doubt: **do not bump.** Ship docs, ship fixes as patches,
leave the version alone.

---

## Goal 5 — Smaller improvements (pick up anytime, no bump needed)

- CI recipes for Azure Pipelines and Jenkins (JUnit output already
  works there; `docs/gitlab-ci.md` is the pattern — recipe docs only).
- A `docs/` page walking the HTML report fields (screenshots exist in
  `docs/assets/`).
- Example directory for the pytest-ingestion path (currently the demo
  assumes an emitter; show the zero-wrapper path end to end).

---

## Goal 6 — Provider-axis portability: `evalgate portability`

**Why this goal exists.** SVX research track R11 (2026-09-30,
[report](https://github.com/srivtx/svx-research/blob/main/research/track-reports/R11-model-portability.md))
verified that LLM request-format portability is a closed, crowded
category — gateways (LiteLLM, OpenRouter, Portkey, Cloudflare), MCP,
and promptfoo killed it — but **behavior portability is not solved and
has no owner**: "OpenAI-compatible ≠ interchangeable — test the actual
failure modes per provider" (aiwisdom.dev, Jul 2026). Agent performance
is scaffold-shaped, not model-shaped (searcharxiv, Aug 2026), so public
leaderboards cannot answer "does *my* agent survive a model swap?"
Eval platforms have started monetizing exactly this gate ($1.50/1000
scores, beri.net Aug 2026) — the same structural opening that produced
EvalGate, along a provider axis. **This is EvalGate's home ground** —
deterministic per-case interval statistics, baselines, and
`evalgate diff` — extended from the time axis to the provider axis.

**Context.** v2.1.0 already has every primitive needed: named baselines
(`.svx/baseline.json`), direction-aware interval-vs-interval comparison,
`evalgate diff` with an all-worse/all-better table and exit codes. The
extension is conceptually: run the *same* eval suite against N providers
(or N models), store one baseline per provider, then diff across the
provider axis instead of the time axis.

**Work order:**

1. **Input contract.** The user's existing eval harness produces
   per-provider result files (JUnit XML / pytest JSON / Go / Jest rows
   — Goal 2 adapters). EvalGate never makes network calls: it only
   reads artifacts, so provider identity arrives as a label
   (`--provider claude-sonnet`, `--provider gpt-5`), not an API call.
   Determinism invariant unchanged.
2. **`evalgate portability --baseline-provider A --candidate-provider B`**
   (name is a proposal — pick the clearest): per-case
   interval-vs-interval comparison of B's run against A's baseline,
   the existing direction-aware verdicts, and a portability diff table
   (which cases degrade when swapping A→B, which hold, which improve —
   the `evalgate diff` table with provider columns).
3. **Exit-code contract** (invariant #5): 0 = no case degrades beyond
   tolerance, 1 = at least one case degrades. CI usage: the swap check
   — "if we move provider, does the gate go red?" — as a PR artifact.
4. **Baselines:** one baseline file per provider label under `.svx/`
   (`.svx/baseline.claude-sonnet.json` — shape is a naming convention
   over the existing baseline object, not a new format).
5. Tests first, per house rules: fixture with two providers' rows →
   correct per-case portability table; identical rows → all-hold;
   degraded rows → exit 1 with the right rows named; determinism
   (same input → byte-identical output).
6. Docs: a `docs/portability.md` walking the swap-check workflow;
   README gains the provider-axis story in one paragraph.
7. **Versioning:** this is a new capability → part of the 2.2.0 batch
   or its own 2.x minor (owner's call; default: after the Goal 2-3
   batch, so 2.3.0).

**Acceptance criteria:** swap-check demo runs green on GitHub CI using
fixtures from two "providers"; portability diff table present in text
and HTML reports; tests ≥ 264 + new; ruff + mypy clean; zero runtime
deps still true; R11's evidence trail linked in the docs; one minor
bump maximum for the capability.

**Evidence addendum (research track V4, 2026-10-04):** deprecation
visibility is being absorbed *per-platform* — Fiddler's LLM Gateway
surfaces deprecation cues in model pickers (docs.fiddler.ai), Tencent
exposes pending-deprecation status (Sep 16 2026), Salesforce documents
model-deprecation/rerouting — but the **cross-vendor** slice (a
standalone tracker + version-pinned canary evals that tell you what
*your* agent loses when a model retires) remains unsurfaced. If the
portability capability lands (2.2/2.3), a natural follow-on is
`evalgate portability --frozen-baseline` — the "Renovate for models"
shape the research flagged — but that is a separate capability with
its own work order, not part of this goal.

---

## Shipped goals (append with commit SHA when a goal completes)

| Goal | Shipped in | Notes |
|------|-----------|-------|
| — | — | none yet — Goals 1-3, 6 are open |
