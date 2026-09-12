"""Eval command runner.

Contract (v2, JSON Lines on stdout): the eval command is executed
`repetitions` times. On each repetition i the child process sees

    SVX_SEED     = base_seed + i        (int)
    SVX_REPETITION = i                  (int, 0-based)
    EVALGATE=1                            (marker)

and must print one JSON object per non-empty line:

    {"case": "case-name", "passed": true, "score": 0.93,
     "latency_ms": 812.4, "cost_usd": 0.0013, "meta": {...}}

`score`, `latency_ms`, `cost_usd` and `meta` are optional (null when
absent); `latency_ms` and `cost_usd` must be finite numbers >= 0 when
present. Wrap your existing eval suite in ten lines of printing code and
EvalGate handles the statistics.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Optional numeric row fields validated on ingestion (v2).
_NUMERIC_FIELDS = ("latency_ms", "cost_usd")


class RunnerError(RuntimeError):
    """Raised for command failures or malformed output."""


@dataclass
class RunOutcome:
    rows: list[dict] = field(default_factory=list)
    raw_log: str = ""
    returncodes: list[int] = field(default_factory=list)
    repetitions: int = 0
    base_seed: int = 0


def _parse_jsonl(stdout: str, context: str) -> list[dict]:
    rows: list[dict] = []
    for lineno, raw in enumerate(stdout.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunnerError(
                f"{context}: stdout line {lineno} is not valid JSON: {exc}\n"
                f"  line was: {line[:200]}"
            ) from exc
        if not isinstance(obj, dict):
            raise RunnerError(f"{context}: stdout line {lineno} is not a JSON object")
        if "case" not in obj:
            raise RunnerError(f"{context}: stdout line {lineno} missing 'case' field")
        if "passed" not in obj:
            raise RunnerError(f"{context}: stdout line {lineno} missing 'passed' field")
        if not isinstance(obj["passed"], bool):
            raise RunnerError(f"{context}: stdout line {lineno}: 'passed' must be a boolean")
        score = obj.get("score")
        if score is not None:
            try:
                obj["score"] = float(score)
            except (TypeError, ValueError) as exc:
                raise RunnerError(
                    f"{context}: stdout line {lineno}: 'score' must be a number or null"
                ) from exc
        for field_name in _NUMERIC_FIELDS:
            raw_value = obj.get(field_name)
            if raw_value is None:
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise RunnerError(
                    f"{context}: stdout line {lineno}: '{field_name}' "
                    "must be a number or null"
                ) from exc
            if not math.isfinite(value) or value < 0:
                raise RunnerError(
                    f"{context}: stdout line {lineno}: '{field_name}' "
                    "must be a finite number >= 0"
                ) from None
            obj[field_name] = value
        rows.append(obj)
    return rows


def run_evals(command: str, repetitions: int, base_seed: int,
              cwd: Path, extra_env: dict | None = None) -> RunOutcome:
    """Execute the eval command `repetitions` times with derived seeds."""
    outcome = RunOutcome(repetitions=repetitions, base_seed=base_seed)
    env = dict(os.environ)
    env["EVALGATE"] = "1"
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})

    for i in range(repetitions):
        seed = base_seed + i
        rep_env = dict(env)
        rep_env["SVX_SEED"] = str(seed)
        rep_env["SVX_REPETITION"] = str(i)
        proc = subprocess.run(
            command, shell=True, cwd=str(cwd), env=rep_env,
            capture_output=True, text=True, timeout=3600,
        )
        outcome.returncodes.append(proc.returncode)
        if proc.returncode != 0:
            raise RunnerError(
                f"eval command failed at repetition {i} (seed {seed}, "
                f"exit {proc.returncode}).\nstderr tail:\n"
                + "\n".join(proc.stderr.strip().splitlines()[-12:])
            )
        context = f"repetition {i} (seed {seed})"
        rows = _parse_jsonl(proc.stdout, context)
        for row in rows:
            row["_rep"] = i
            row["_seed"] = seed
        outcome.rows.extend(rows)
        outcome.raw_log += proc.stdout

    if not outcome.rows:
        raise RunnerError(
            "eval command produced no JSON rows on stdout across "
            f"{repetitions} repetition(s); check the command in your config"
        )
    return outcome
