"""Run history: one JSON line per `evalgate run`.

The history file (`.svx/history.jsonl` by default) is a local, append-only
log of run outcomes. It feeds two things:

  - `evalgate trend` (a compact table + unicode sparkline in the terminal),
  - the trend chart in the HTML report.

It is per-machine state, like the report: never gate on it, never commit
it (the committed artifact is the baseline, which is the *reference*).
Entries are trimmed to `history.max_entries` (oldest first) so the file
stays bounded on long-lived CI runners.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

SCHEMA_VERSION = 1

# Compact per-run record (v2). Keep it small: history is read on every
# report render and every `evalgate trend`.
_SUMMARY_FIELDS = (
    "ts", "git_sha", "verdict", "pass_at_k_mean", "pass_rate",
    "mean_score", "p95_latency_ms", "total_cost_usd",
    "total_runs", "total_passes", "cases", "failing", "config_hash",
)


def history_path(config) -> Path:
    assert config.source_path is not None
    base = config.source_path.parent
    path = Path(config.history.path)
    return path if path.is_absolute() else base / path


def _git_sha() -> str | None:
    import subprocess
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def run_summary(agg, config, gate_result, version: str) -> dict:
    """Serialize one run into a history entry (compact, sortable)."""
    entry: dict = {
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "verdict": "GREEN" if gate_result.green else "RED",
        "version": version,
        "pass_at_k_mean": (round(agg.pass_at_k_mean, 6)
                           if agg.pass_at_k_mean is not None else None),
        "pass_rate": (round(agg.pass_rate, 6)
                      if agg.pass_rate is not None else None),
        "mean_score": (round(agg.mean_score, 6)
                       if agg.mean_score is not None else None),
        "p95_latency_ms": (round(agg.p95_latency_ms, 3)
                           if agg.p95_latency_ms is not None else None),
        "total_cost_usd": (round(agg.total_cost_usd, 6)
                           if agg.total_cost_usd is not None else None),
        "total_runs": agg.total_runs,
        "total_passes": agg.total_passes,
        "cases": len(agg.cases),
        "failing": len(agg.failing_cases),
        "config_hash": config.config_hash(),
    }
    return entry


def append_run(path: Path, entry: dict, max_entries: int) -> None:
    """Append one entry; trim the oldest when the log exceeds max_entries.

    Corrupt trailing lines (a killed run mid-write) are dropped during the
    rewrite so a bad line never poisons the history forever.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, sort_keys=True) + "\n"
    if not path.exists():
        path.write_text(line, encoding="utf-8")
        return

    existing = _read_lines(path)
    existing.append(line)
    overflow = len(existing) - max_entries
    if overflow > 0:
        existing = existing[overflow:]
    path.write_text("".join(existing), encoding="utf-8")


def _read_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped:
            lines.append(stripped + "\n")
    return lines


def load_history(path: Path, limit: int | None = None) -> list[dict]:
    """Parse history entries, oldest first. Skips unparsable lines."""
    if not path.exists():
        return []
    entries: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            doc = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict):
            entries.append(doc)
    if limit is not None and limit > 0:
        entries = entries[-limit:]
    return entries


def sparkline(values: list[float | None], width: int = 24) -> str:
    """Unicode block-character sparkline for the terminal (v2).

    Missing values (None) render as low blocks; an empty list renders as
    a flat line. Purely cosmetic - the numbers in the table are the truth.
    """
    blocks = "▁▂▃▄▅▆▇█"
    if not values:
        return "▁" * width
    vals = [0.0 if v is None else float(v) for v in values]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    step = max(1, (len(vals) + width - 1) // width)
    sampled = vals[::step][-width:]
    return "".join(blocks[int((v - lo) / span * (len(blocks) - 1))]
                   for v in sampled)
