"""Config loading for EvalGate.

Supports `svx.evalgate.yaml` (a flat two-level subset of YAML, parsed with
a tiny in-tree parser so EvalGate has zero runtime dependencies) and
`svx.evalgate.json` (plain stdlib JSON). CLI flags override file values.

The subset accepted: nested mappings (2-space indentation), scalar values
(strings, ints, floats, true/false), `#` comments, blank lines. That is
all the shipped schema needs; anything richer should use the JSON form.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_NAMES = ("svx.evalgate.yaml", "svx.evalgate.yml", "svx.evalgate.json")


# ---------------------------------------------------------------------------
# YAML subset parser (mappings + scalars only)
# ---------------------------------------------------------------------------
def _parse_scalar(raw: str):
    text = raw.strip()
    if not text:
        return None
    if (text[0] == text[-1] == '"') or (text[0] == text[-1] == "'"):
        return text[1:-1]
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _strip_comment(line: str) -> str:
    """Strip `#` comments, but only outside quoted values."""
    out: list[str] = []
    quote: str | None = None
    for ch in line:
        if quote is not None:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            out.append(ch)
        elif ch == '#':
            break
        else:
            out.append(ch)
    return ''.join(out).rstrip()


def parse_yaml_subset(text: str) -> dict:
    """Parse the YAML subset: nested dicts by 2-space indent, scalar leaves."""
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = _strip_comment(line)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        if indent % 2 != 0:
            raise ValueError(f"config line {lineno}: indentation must be 2-space steps")
        if ":" not in stripped:
            raise ValueError(f"config line {lineno}: expected 'key: value'")
        key, _, rest = stripped.strip().partition(":")
        key = key.strip().strip('"').strip("'")
        rest = rest.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError(f"config line {lineno}: bad indentation structure")
        parent = stack[-1][1]
        if rest == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(rest)
    return root


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
@dataclass
class EvalsConfig:
    command: str = "python evals/run_evals.py"
    repetitions: int = 20
    base_seed: int = 20260912
    working_dir: str | None = None  # None -> config file's directory
    bootstrap_iterations: int = 10000


@dataclass
class RegressionConfig:
    mode: str = "absolute"           # "absolute" | "relative"
    tolerance: float = 0.05


@dataclass
class GateConfig:
    k: int = 1
    min_pass_at_k: float = 0.85
    min_mean_score: float | None = None
    # v2 thresholds: RED when the current run EXCEEDS these (None = skip).
    max_p95_latency_ms: float | None = None
    max_total_cost_usd: float | None = None
    regression: RegressionConfig = field(default_factory=RegressionConfig)


@dataclass
class BaselineConfig:
    path: str = ".svx/baseline.json"
    auto_write_on_missing: bool = False


@dataclass
class ReportConfig:
    path: str = ".svx/report.md"
    # Self-contained HTML report with inline SVG charts (v2).
    # Set to null (~) to disable; written next to the markdown report
    # by default and attached to the run artifact.
    html_path: str | None = ".svx/report.html"


@dataclass
class HistoryConfig:
    """Run history (v2): one JSON line per `evalgate run`, feeding the
    trend command and the trend chart in the HTML report."""

    enabled: bool = True
    path: str = ".svx/history.jsonl"
    max_entries: int = 500


@dataclass
class Config:
    evals: EvalsConfig = field(default_factory=EvalsConfig)
    gate: GateConfig = field(default_factory=GateConfig)
    baseline: BaselineConfig = field(default_factory=BaselineConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    source_path: Path | None = None

    def config_hash(self) -> str:
        """Stable digest of the gate-relevant settings."""
        payload = {
            "repetitions": self.evals.repetitions,
            "base_seed": self.evals.base_seed,
            "k": self.gate.k,
            "min_pass_at_k": self.gate.min_pass_at_k,
            "min_mean_score": self.gate.min_mean_score,
            "max_p95_latency_ms": self.gate.max_p95_latency_ms,
            "max_total_cost_usd": self.gate.max_total_cost_usd,
            "regression": dataclasses.asdict(self.gate.regression),
        }
        blob = json.dumps(payload, sort_keys=True).encode("utf-8")
        import hashlib
        return hashlib.sha256(blob).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Loading + merging
# ---------------------------------------------------------------------------
def _apply(obj: dict, target, path: str = "") -> list[str]:
    """Overlay dict values onto a dataclass instance. Returns warnings."""
    warnings: list[str] = []
    valid = {f.name for f in dataclasses.fields(target)}
    for key, value in obj.items():
        attr = str(key)
        if attr not in valid:
            warnings.append(f"unknown config key ignored: {path}{attr}")
            continue
        current = getattr(target, attr)
        if dataclasses.is_dataclass(current) and isinstance(value, dict):
            warnings.extend(_apply(value, current, f"{path}{attr}."))
        elif isinstance(current, bool):
            setattr(target, attr, bool(value))
        elif isinstance(current, int) and not isinstance(current, bool):
            setattr(target, attr, int(value))
        elif isinstance(current, float) and value is not None:
            setattr(target, attr, float(value))
        else:
            setattr(target, attr, value)
    return warnings


def find_config(path: str | None, cwd: Path) -> Path | None:
    if path:
        candidate = (cwd / path) if not Path(path).is_absolute() else Path(path)
        return candidate if candidate.exists() else None
    for name in DEFAULT_CONFIG_NAMES:
        candidate = cwd / name
        if candidate.exists():
            return candidate
    return None


def load_config(path: Path) -> tuple[Config, list[str]]:
    """Load a config file (.yaml/.yml subset or .json) into a Config."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
    else:
        data = parse_yaml_subset(text)
    cfg = Config()
    warnings = _apply(data if isinstance(data, dict) else {}, cfg)
    cfg.source_path = path
    if cfg.evals.repetitions < 1:
        raise ValueError("evals.repetitions must be >= 1")
    if cfg.gate.k < 1:
        raise ValueError("gate.k must be >= 1")
    if cfg.gate.regression.mode not in ("absolute", "relative"):
        raise ValueError("gate.regression.mode must be 'absolute' or 'relative'")
    if cfg.gate.regression.tolerance < 0:
        raise ValueError("gate.regression.tolerance must be >= 0")
    if cfg.gate.max_p95_latency_ms is not None and cfg.gate.max_p95_latency_ms <= 0:
        raise ValueError("gate.max_p95_latency_ms must be > 0")
    if cfg.gate.max_total_cost_usd is not None and cfg.gate.max_total_cost_usd <= 0:
        raise ValueError("gate.max_total_cost_usd must be > 0")
    if cfg.history.max_entries < 1:
        raise ValueError("history.max_entries must be >= 1")
    return cfg, warnings
