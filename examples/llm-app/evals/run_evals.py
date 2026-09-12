# Demo eval suite for SVX EvalGate.
#
# This stands in for YOUR eval suite: pytest with LLM assertions, a
# promptfoo/promptscripts run, a custom harness - anything that can print
# one JSON object per line per repetition. Ten lines of wrapping is the
# entire integration cost.
#
# Determinism contract: the same SVX_SEED must always produce the same
# output. This mock derives everything from random.Random(SVX_SEED), so
# EvalGate's statistics are exactly reproducible.
#
# DEMO_MODE=regression simulates a model/config downgrade for the
# "catch a regression" walkthrough in the README.
import json
import os
import random

# name -> per-run success probability (stand-in for eval quality)
CASES = [
    ("sql-gen-basic", 0.98),
    ("sql-gen-join", 0.93),
    ("sql-gen-window", 0.86),
    ("summarize-faithful", 0.91),
    ("summarize-concise", 0.88),
    ("extract-entities", 0.96),
    ("classify-tone", 0.97),
    ("route-support", 0.94),
    ("translate-idiom", 0.90),
    ("code-review-suggestion", 0.87),
]


def main() -> None:
    seed = int(os.environ.get("SVX_SEED", "0"))
    regression = os.environ.get("DEMO_MODE") == "regression"
    rng = random.Random(seed)

    for name, quality in CASES:
        q = quality - 0.15 if regression else quality
        passed = rng.random() < q
        score = min(1.0, max(0.0, rng.gauss(q, 0.05)))
        print(json.dumps({
            "case": name,
            "passed": passed,
            "score": round(score, 4),
            "meta": {"seed": seed, "mode": "regression" if regression else "normal"},
        }))


if __name__ == "__main__":
    main()
