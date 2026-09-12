## EvalGate - GREEN

Deterministic statistics for `24` repetitions (base seed `777001`) across **10 case(s) / 240 runs**.

### Thresholds

| Metric | Current | 95% CI | Required | Verdict |
|---|---:|---:|---:|---|
| `pass_at_k_mean` | 0.921 | [0.867, 0.971] | min 0.800 | PASS |
| `mean_score` | 0.919 | [0.911, 0.927] | min 0.600 | PASS |

### Pass@1 by case

| Case | Runs | Passes | Pass rate | pass@1 |
|---|---:|---:|---:|---:|
| `classify-tone` | 24 | 24 | 1.00 | 1.000 |
| `code-review-suggestion` | 24 | 18 | 0.75 | 0.750 |
| `extract-entities` | 24 | 21 | 0.88 | 0.875 |
| `route-support` | 24 | 22 | 0.92 | 0.917 |
| `sql-gen-basic` | 24 | 24 | 1.00 | 1.000 |
| `sql-gen-join` | 24 | 24 | 1.00 | 1.000 |
| `sql-gen-window` | 24 | 24 | 1.00 | 1.000 |
| `summarize-concise` | 24 | 21 | 0.88 | 0.875 |
| `summarize-faithful` | 24 | 23 | 0.96 | 0.958 |
| `translate-idiom` | 24 | 20 | 0.83 | 0.833 |

Cases not passing every run (6): `code-review-suggestion`, `extract-entities`, `route-support`, `summarize-concise`, `summarize-faithful`, `translate-idiom`

Mean score 0.919, bootstrap 95% CI [0.911, 0.927] (seeded, deterministic).

### Notes

- no baseline present - threshold checks only (run with --update-baseline to establish one)

<sub>No baseline on record - SVX EvalGate, green family #298959 #1f5e40 #4fbb85</sub>
