"""``evalgate diff``: compare two metric snapshots at the command line.

A snapshot is either a baseline document (``{"metrics": {...}}`` with
value/confidence-interval entries) or a flat point-metrics document
(a history entry, or anything shaped like one). The comparison reuses
the gate's interval-vs-interval logic with the configured regression
band, so a diff only calls a metric WORSE when it is *confidently*
worse - the same anti-flapping guarantee the gate itself gives.

Exit codes: 0 when nothing is confidently worse, 1 when at least one
metric is, 2 on errors (the CLI layer decides).
"""
from __future__ import annotations

import json
from pathlib import Path

from .baseline import TRACKED_METRICS
from .gate import LOWER_IS_BETTER

WORSE = "WORSE"
BETTER = "BETTER"
UNCHANGED = "unchanged"
NA = "n/a"


def _entry_to_metric(entry) -> dict | None:
    """Normalize one metric entry to {value, low, high}."""
    if isinstance(entry, dict):
        value = entry.get("value")
        if value is None:
            return None
        low = entry.get("low")
        high = entry.get("high")
        return {
            "value": float(value),
            "low": float(value if low is None else low),
            "high": float(value if high is None else high),
        }
    if isinstance(entry, (int, float)):
        value = float(entry)
        return {"value": value, "low": value, "high": value}
    return None


def load_snapshot(path: Path) -> dict[str, dict]:
    """Load a baseline document or flat point-metrics JSON as a snapshot."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: expected a JSON object")
    if isinstance(doc.get("metrics"), dict):
        snapshot = {}
        for metric, entry in doc["metrics"].items():
            normalized = _entry_to_metric(entry)
            if normalized is not None:
                snapshot[str(metric)] = normalized
        if not snapshot:
            raise ValueError(f"{path}: baseline document has no usable metrics")
        return snapshot
    # Flat (history-entry) shape: known metric keys at the top level.
    snapshot = {}
    for metric in TRACKED_METRICS:
        normalized = _entry_to_metric(doc.get(metric))
        if normalized is not None:
            snapshot[metric] = normalized
    if not snapshot:
        raise ValueError(f"{path}: no recognized metrics in this document")
    return snapshot


def from_history_entry(entry: dict) -> dict[str, dict]:
    """Convert a history entry (flat point metrics) into a snapshot."""
    snapshot = {}
    for metric in TRACKED_METRICS:
        normalized = _entry_to_metric(entry.get(metric))
        if normalized is not None:
            snapshot[metric] = normalized
    return snapshot


def compare(a: dict[str, dict], b: dict[str, dict], regression) -> list[dict]:
    """Direction-aware comparison of two snapshots, oldest first.

    ``a`` is the reference (typically the baseline); ``b`` is compared
    against it. Band logic mirrors the gate: relative mode scales the
    band by |a.value|, absolute mode uses the tolerance directly.
    """
    rows: list[dict] = []
    for metric in TRACKED_METRICS:
        a_entry, b_entry = a.get(metric), b.get(metric)
        if a_entry is None or b_entry is None:
            rows.append({"metric": metric, "a": a_entry, "b": b_entry,
                         "delta": None, "rel": None, "band": None,
                         "status": NA})
            continue
        if regression.mode == "relative":
            band = abs(a_entry["value"]) * regression.tolerance
        else:
            band = regression.tolerance
        if metric in LOWER_IS_BETTER:
            worse = b_entry["low"] > a_entry["high"] + band
            better = b_entry["high"] < a_entry["low"] - band
        else:
            worse = b_entry["high"] < a_entry["low"] - band
            better = b_entry["low"] > a_entry["high"] + band
        if worse:
            status = WORSE
        elif better:
            status = BETTER
        else:
            status = UNCHANGED
        delta = b_entry["value"] - a_entry["value"]
        rel = (delta / a_entry["value"]) if a_entry["value"] else None
        rows.append({"metric": metric, "a": a_entry, "b": b_entry,
                     "delta": delta, "rel": rel, "band": band,
                     "status": status})
    return rows


def _fmt_entry(entry: dict | None) -> str:
    if entry is None:
        return "-"
    if entry["low"] == entry["high"]:
        return f"{entry['value']:.4f}"
    return f"{entry['value']:.4f} [{entry['low']:.4f}, {entry['high']:.4f}]"


def render(rows: list[dict], a_label: str, b_label: str) -> str:
    """Render the diff as an aligned terminal table (same style as trend)."""
    lines: list[str] = []
    lines.append(f"evalgate: diff - A: {a_label}")
    lines.append(f"                    B: {b_label}")
    header = (f"{'metric':16}  {'A':24}  {'B':24}  "
              f"{'delta':>10}  {'rel':>7}  verdict")
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        delta = (f"{row['delta']:+.4f}" if row["delta"] is not None else "-")
        rel = (f"{row['rel']:+.1%}" if row["rel"] is not None else "-")
        lines.append(
            f"{row['metric']:16}  {_fmt_entry(row['a']):24}  "
            f"{_fmt_entry(row['b']):24}  {delta:>10}  {rel:>7}  {row['status']}"
        )
    worse = [r for r in rows if r["status"] == WORSE]
    lines.append("")
    if worse:
        lines.append(f"confidently worse: {', '.join(r['metric'] for r in worse)}")
    else:
        lines.append("no metric is confidently worse than the reference")
    return "\n".join(lines)
