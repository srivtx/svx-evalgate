"""Baseline store: the committed record of what "good" looks like.

The baseline is a small JSON file (`.svx/baseline.json` by default) that
lives in your repository. Pushes to the main branch refresh it; pull
requests are gated against it. That is the entire lifecycle.
"""
from __future__ import annotations

import datetime as _dt
import json
import subprocess
from pathlib import Path

SCHEMA_VERSION = 1

# Metrics persisted in the baseline and compared by the regression gate.
# v2 adds the lower-is-better pair; baselines recorded by older versions
# simply lack those entries and the gate skips them (no breakage).
TRACKED_METRICS = (
    "pass_at_k_mean", "pass_rate", "mean_score",
    "p95_latency_ms", "total_cost_usd",
)


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def baseline_path(config) -> Path:
    assert config.source_path is not None
    base = config.source_path.parent
    path = Path(config.baseline.path)
    return path if path.is_absolute() else base / path


def build_baseline(agg, config) -> dict:
    """Serialize aggregate stats into the baseline document.

    Metrics are stored with their confidence intervals so the regression
    gate can compare interval against interval (a like-for-like
    comparison that does not fire on statistical noise).
    """
    metrics = {}
    for name in TRACKED_METRICS:
        value = agg.metric_value(name)
        if value is None:
            continue
        entry = {"value": round(float(value), 6)}
        ci = agg.metric_ci(name)
        if ci is not None:
            entry["low"] = round(float(ci[0]), 6)
            entry["high"] = round(float(ci[1]), 6)
        metrics[name] = entry
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "svx-evalgate",
        "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "repetitions": agg.total_runs and config.evals.repetitions,
        "cases": len(agg.cases),
        "base_seed": config.evals.base_seed,
        "config_hash": config.config_hash(),
        "metrics": metrics,
    }


def save_baseline(doc: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"baseline file {path} is not valid JSON: {exc}") from exc
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"baseline file {path} has schema_version {doc.get('schema_version')!r}; "
            f"expected {SCHEMA_VERSION} (delete the file to regenerate)"
        )
    return doc
