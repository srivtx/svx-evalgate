# GitLab CI (and other JUnit-native CI systems)

SVX EvalGate runs anywhere Python runs, and its JUnit XML output
(`.svx/report.xml` by default) plugs directly into the test-report UIs
CI teams already watch. This page shows the GitLab recipe; Jenkins,
Azure Pipelines, and GitHub test-annotation actions follow the same
shape.

## The pipeline

Save as `.gitlab-ci.yml` in your repository:

```yaml
stages:
  - evals

evalgate:
  stage: evals
  image: python:3.12
  rules:
    # Merge requests: gate against the committed baseline.
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    # Default branch: refresh the baseline for the next MRs.
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  script:
    - pip install svx-evalgate
    - |
      if [ "$CI_COMMIT_BRANCH" = "$CI_DEFAULT_BRANCH" ]; then
        evalgate run --update-baseline
        git config user.name "evalgate-bot"
        git config user.email "evalgate@${CI_SERVER_HOST}"
        git remote set-url origin "https://oauth2:${GITLAB_BOT_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git"
        git add .svx/baseline.json
        git commit -m "evalgate: refresh baseline" || echo "baseline unchanged"
        git push origin "$CI_DEFAULT_BRANCH"
      else
        evalgate run
      fi
  artifacts:
    when: always
    reports:
      junit: .svx/report.xml
    paths:
      - .svx/report.html
      - .svx/report.md
    expire_in: 30 days
```

What each piece buys you:

- **`artifacts:reports:junit`** renders the gate verdicts in GitLab's
  native test tab: every threshold and regression-band check appears as
  a test case, and RED verdicts carry their statistical evidence
  (current interval vs baseline interval, band) inline in the failure
  message.
- **`artifacts:paths`** preserves the self-contained HTML report (trend
  chart, histograms, per-case bars) and the markdown report for each
  pipeline, downloadable for 30 days.
- **The refresh rule** keeps the baseline honest: merge trains gate
  against what main actually looks like, not a stale snapshot. If you
  prefer manual baseline updates, drop the git-push block and commit
  the baseline yourself.

`GITLAB_BOT_TOKEN` is a project access token with `write_repository`
scope, defined under Settings > CI/CD > Variables. If you would rather
not have CI push commits, remove the push block and treat the baseline
like any other reviewed file.

## Gating an existing pytest suite (zero emitter code)

Have a plain pytest suite and want statistical gating on it? Point
EvalGate at pytest's own JUnit output - no wrapper, no emitter:

```yaml
evalgate-pytest:
  stage: evals
  image: python:3.12
  script:
    - pip install svx-evalgate pytest
    - pytest --junitxml=.svx/pytest.xml
    - evalgate ingest --format pytest-junit .svx/pytest.xml
  artifacts:
    when: always
    reports:
      junit: .svx/report.xml
```

Every test becomes a case, failures/errors become failed rows, and
test durations become latency observations - so the same
`max_p95_latency_ms` threshold and latency regression bands that gate
LLM evals also catch a test suite that quietly got 40% slower.

## Exit codes everywhere

`evalgate run` and `evalgate ingest` exit 0 on green, 1 on red, 2 on
error - the contract every CI system already understands. `evalgate
diff` (baseline vs last run) uses the same codes, which makes it a
cheap post-deploy smoke check: run it after a rollout and let the exit
code tell you whether the metrics moved.
