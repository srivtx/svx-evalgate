"""EvalGate command-line interface.

    evalgate run [--config PATH] [--update-baseline] [--report-stdout] [--json]
    evalgate ingest --format pytest-junit PATH [--config PATH]
                    [--update-baseline] [--report-stdout] [--json]
    evalgate diff [A] [B] [--config PATH]
    evalgate baseline [show|reset] [--config PATH]
    evalgate trend [--config PATH] [--limit N]
    evalgate init [DIR]                        # scaffold a gated eval suite
    evalgate version

`run` executes the configured eval command; `ingest` reads an existing
test report (pytest's built-in JUnit XML) instead - zero emitter code.
Both share the same pipeline: aggregate statistics, thresholds,
regression bands, baseline management, and the markdown/HTML/JUnit
reports.

`diff` compares two metric snapshots (baseline documents or history
entries): `evalgate diff` is baseline-vs-last-run, `evalgate diff A`
is baseline-vs-A, `evalgate diff A B` compares two snapshot files.
Exit codes: 0 = green, 1 = red (threshold, regression, or confidently
worse in a diff), 2 = error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from . import adapters as adapters_mod
from . import baseline as baseline_mod
from . import config as config_mod
from . import diff as diff_mod
from . import gate as gate_mod
from . import github as github_mod
from . import history as history_mod
from . import htmlreport as htmlreport_mod
from . import init as init_mod
from . import junitxml as junitxml_mod
from . import report as report_mod
from . import runner as runner_mod
from . import stats as stats_mod

EXIT_GREEN, EXIT_RED, EXIT_ERROR = 0, 1, 2


def _log(msg: str) -> None:
    print(f"evalgate: {msg}", file=sys.stderr)


def _resolve_config(args) -> tuple[config_mod.Config, list[str], Path]:
    cwd = Path.cwd()
    path = config_mod.find_config(getattr(args, "config", None), cwd)
    if path is None:
        hint = getattr(args, "config", None) or " or ".join(config_mod.DEFAULT_CONFIG_NAMES)
        raise SystemExit(
            f"evalgate: config not found ({hint}); create one in the working "
            "directory or pass --config"
        )
    cfg, warnings = config_mod.load_config(path)
    assert cfg is not None and cfg.source_path is not None
    for warning in warnings:
        _log(warning)
    return cfg, warnings, path


def _gate_pipeline(cfg, rows: list[dict], args, source_note: str | None = None) -> int:
    """Shared run/ingest tail: stats -> gate -> reports -> exit code."""
    assert cfg.source_path is not None
    base_dir = cfg.source_path.parent

    agg = stats_mod.aggregate(
        rows, k=cfg.gate.k, base_seed=cfg.evals.base_seed,
        bootstrap_iterations=cfg.evals.bootstrap_iterations,
    )

    bpath = baseline_mod.baseline_path(cfg)
    baseline = baseline_mod.load_baseline(bpath)
    if baseline is not None:
        _log(f"baseline loaded from {bpath} "
             f"(created {baseline.get('created', '?')})")

    gate_result = gate_mod.evaluate(agg, cfg, baseline)
    if source_note:
        gate_result.notes.insert(0, source_note)

    # history first: the HTML trend chart includes the current run
    hpath = history_mod.history_path(cfg)
    history_entries: list[dict] = []
    if cfg.history.enabled:
        entry = history_mod.run_summary(agg, cfg, gate_result, __version__)
        history_mod.append_run(hpath, entry, cfg.history.max_entries)
        history_entries = history_mod.load_history(
            hpath, limit=max(cfg.history.max_entries, 30))

    markdown = report_mod.render(agg, cfg, baseline, gate_result)
    report_path = (base_dir / cfg.report.path
                   if not Path(cfg.report.path).is_absolute() else Path(cfg.report.path))
    report_mod.write_report(markdown, report_path)
    github_mod.write_step_summary(markdown)
    github_mod.post_pr_comment(markdown)

    if cfg.report.html_path:
        html_path = (base_dir / cfg.report.html_path
                     if not Path(cfg.report.html_path).is_absolute()
                     else Path(cfg.report.html_path))
        htmlreport_mod.write_report(
            htmlreport_mod.render(agg, cfg, baseline, gate_result, history_entries),
            html_path)
        _log(f"html report: {html_path}")

    if cfg.report.junit_path:
        junit_path = (base_dir / cfg.report.junit_path
                      if not Path(cfg.report.junit_path).is_absolute()
                      else Path(cfg.report.junit_path))
        junitxml_mod.write_report(
            junitxml_mod.render(gate_result, cfg), junit_path)
        _log(f"junit report: {junit_path}")

    update = args.update_baseline or os.environ.get("EVALGATE_UPDATE_BASELINE") == "1"
    if baseline is None and cfg.baseline.auto_write_on_missing:
        update = True
    if update:
        doc = baseline_mod.build_baseline(agg, cfg)
        baseline_mod.save_baseline(doc, bpath)
        _log(f"baseline written to {bpath}")
    elif baseline is None:
        _log("no baseline on record; threshold checks only")

    if args.report_stdout:
        print(markdown)

    if args.json:
        machine = {
            "version": __version__,
            "green": gate_result.green,
            "verdict": "GREEN" if gate_result.green else "RED",
            "reasons": gate_result.reasons(),
            "metrics": {
                "pass_at_k_mean": agg.pass_at_k_mean,
                "pass_at_k_ci": (list(agg.pass_at_k_ci)
                                  if agg.pass_at_k_ci else None),
                "pass_rate": agg.pass_rate,
                "pass_rate_ci": (list(agg.pass_rate_ci)
                                 if agg.pass_rate_ci else None),
                "mean_score": agg.mean_score,
                "mean_score_ci": (list(agg.mean_score_ci)
                                  if agg.mean_score_ci else None),
                "p95_latency_ms": agg.p95_latency_ms,
                "p95_latency_ci": (list(agg.p95_latency_ci)
                                   if agg.p95_latency_ci else None),
                "total_cost_usd": agg.total_cost_usd,
            },
            "total_runs": agg.total_runs,
            "total_passes": agg.total_passes,
            "failing_cases": agg.failing_cases,
            "baseline_used": baseline is not None,
            "baseline_updated": bool(update),
            "report_path": str(report_path),
        }
        print(json.dumps(machine, indent=2, sort_keys=True))

    verdict = "GREEN" if gate_result.green else "RED"
    _log(f"verdict: {verdict}")
    for reason in gate_result.reasons():
        _log(f"  - {reason}")
    _log(f"report: {report_path}")
    return EXIT_GREEN if gate_result.green else EXIT_RED


def cmd_run(args) -> int:
    cfg, _warnings, _cfg_path = _resolve_config(args)

    assert cfg.source_path is not None
    base_dir = cfg.source_path.parent
    workdir = base_dir
    if cfg.evals.working_dir:
        candidate = Path(cfg.evals.working_dir)
        workdir = candidate if candidate.is_absolute() else (base_dir / candidate)

    # Pass a curated environment to the eval command: PR context variables
    # do not leak into child processes (keeps eval output reproducible).
    passthrough = {}
    for var in ("DEMO_MODE",):
        if var in os.environ:
            passthrough[var] = os.environ[var]

    _log(f"running '{cfg.evals.command}' x{cfg.evals.repetitions} "
         f"(base seed {cfg.evals.base_seed}, cwd {workdir})")
    outcome = runner_mod.run_evals(
        cfg.evals.command, cfg.evals.repetitions, cfg.evals.base_seed,
        workdir, extra_env=passthrough,
    )

    return _gate_pipeline(cfg, outcome.rows, args)


def cmd_ingest(args) -> int:
    cfg, _warnings, _cfg_path = _resolve_config(args)
    source_arg = getattr(args, "source", None)
    if not source_arg:
        _log("ingest requires a source path (e.g. pytest's --junitxml output)")
        return EXIT_ERROR
    source = Path(source_arg)
    if not source.is_absolute():
        source = Path.cwd() / source
    if not source.exists():
        _log(f"ingest source not found: {source}")
        return EXIT_ERROR
    fmt = getattr(args, "format", "pytest-junit") or "pytest-junit"
    if fmt not in adapters_mod.FORMATS:
        _log(f"unsupported ingest format: {fmt} "
             f"(supported: {', '.join(adapters_mod.FORMATS)})")
        return EXIT_ERROR
    try:
        rows = adapters_mod.parse_pytest_junit(source)
    except ValueError as exc:
        _log(f"ingest error: {exc}")
        return EXIT_ERROR
    _log(f"ingested {len(rows)} row(s) from {source} (format {fmt})")
    return _gate_pipeline(
        cfg, rows, args,
        source_note=(f"rows ingested from {fmt} report: {source} "
                     "(evals.command was not executed; repetitions do not "
                     "apply to ingested rows)"),
    )


def cmd_diff(args) -> int:
    cfg, _warnings, _cfg_path = _resolve_config(args)
    bpath = baseline_mod.baseline_path(cfg)

    a_arg = getattr(args, "a", None)
    b_arg = getattr(args, "b", None)

    if a_arg:
        a_path = Path(a_arg)
        if not a_path.is_absolute():
            a_path = Path.cwd() / a_path
        if not a_path.exists():
            _log(f"diff source A not found: {a_path}")
            return EXIT_ERROR
        try:
            a = diff_mod.load_snapshot(a_path)
        except ValueError as exc:
            _log(f"diff error: {exc}")
            return EXIT_ERROR
        a_label = str(a_path)
    else:
        if not bpath.exists():
            _log(f"no baseline at {bpath}; pass snapshot paths or run "
                 "evalgate first")
            return EXIT_ERROR
        try:
            a = diff_mod.load_snapshot(bpath)
        except ValueError as exc:
            _log(f"diff error: {exc}")
            return EXIT_ERROR
        a_label = f"baseline ({bpath})"

    if b_arg:
        b_path = Path(b_arg)
        if not b_path.is_absolute():
            b_path = Path.cwd() / b_path
        if not b_path.exists():
            _log(f"diff source B not found: {b_path}")
            return EXIT_ERROR
        try:
            b = diff_mod.load_snapshot(b_path)
        except ValueError as exc:
            _log(f"diff error: {exc}")
            return EXIT_ERROR
        b_label = str(b_path)
    else:
        entries = history_mod.load_history(history_mod.history_path(cfg))
        if not entries:
            _log("no history yet; pass a second snapshot path (evalgate diff "
                 "A B) or run evalgate first")
            return EXIT_ERROR
        b = diff_mod.from_history_entry(entries[-1])
        if not b:
            _log("last history entry carries no metrics; cannot diff")
            return EXIT_ERROR
        b_label = f"last run {entries[-1].get('ts', '?')}"

    rows = diff_mod.compare(a, b, cfg.gate.regression)
    print(diff_mod.render(rows, a_label, b_label))
    if any(r["status"] == diff_mod.WORSE for r in rows):
        return EXIT_RED
    return EXIT_GREEN


def cmd_baseline(args) -> int:
    cfg, _warnings, _path = _resolve_config(args)
    bpath = baseline_mod.baseline_path(cfg)
    action = getattr(args, "action", "show") or "show"
    if action == "reset":
        if bpath.exists():
            bpath.unlink()
            _log(f"baseline removed: {bpath}")
            _log("next `evalgate run --update-baseline` records a fresh one")
        else:
            _log(f"no baseline at {bpath} (nothing to reset)")
        return EXIT_GREEN
    doc = baseline_mod.load_baseline(bpath)
    if doc is None:
        _log(f"no baseline at {bpath}")
        return EXIT_ERROR
    print(json.dumps(doc, indent=2, sort_keys=True))
    return EXIT_GREEN


def cmd_trend(args) -> int:
    cfg, _warnings, _path = _resolve_config(args)
    hpath = history_mod.history_path(cfg)
    limit = max(1, getattr(args, "limit", 15) or 15)
    entries = history_mod.load_history(hpath, limit=limit)
    if not entries:
        _log(f"no history at {hpath} yet")
        _log("history grows by one entry every `evalgate run`")
        return EXIT_ERROR
    total = len(history_mod.load_history(hpath))
    shown = entries[-limit:]

    def cell(value, spec: str, prefix: str = "") -> str:
        if value is None:
            return ""
        return prefix + format(value, spec)

    print(f"evalgate: trend - last {len(shown)} of {total} run(s)")
    header = (f"{'run':>4}  {'timestamp':19}  {'verdict':7}  "
              f"{'pass@k':>7}  {'rate':>6}  {'score':>6}  "
              f"{'p95 ms':>8}  {'cost':>9}")
    print(header)
    print("-" * len(header))
    for i, e in enumerate(shown, start=1):
        ts = str(e.get("ts", ""))[:19].replace("T", " ")
        verdict = str(e.get("verdict", "?"))
        pak = cell(e.get("pass_at_k_mean"), ".3f")
        rate = cell(e.get("pass_rate"), ".3f")
        score = cell(e.get("mean_score"), ".3f")
        p95 = cell(e.get("p95_latency_ms"), ",.0f")
        cost = cell(e.get("total_cost_usd"), ".4f", prefix="$")
        print(f"{i:>4}  {ts:19}  {verdict:7}  "
              f"{pak:>7}  {rate:>6}  {score:>6}  "
              f"{p95:>8}  {cost:>9}")
    values = [e.get("pass_at_k_mean") for e in shown]
    if any(v is not None for v in values):
        print()
        print(f"pass@k sparkline: {history_mod.sparkline(values)}")
    return EXIT_GREEN


def cmd_version(_args) -> int:
    print(f"svx-evalgate {__version__}")
    return EXIT_GREEN


def cmd_init(args) -> int:
    target = Path(getattr(args, "directory", None) or ".").resolve()
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
    created = init_mod.init_project(target)
    if not created:
        _log("nothing to do: svx.evalgate.yaml and evals/run_evals.py already exist")
        return EXIT_GREEN
    for path in created:
        print(f"created: {path}")
    print("\nnext steps:")
    print("  1. edit svx.evalgate.yaml (command, thresholds, k)")
    print("  2. python evals/run_evals.py   # sanity-check your emitter")
    print("  3. evalgate run               # first run writes the baseline")
    print("  4. evalgate run               # second run gates against it")
    return EXIT_GREEN


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evalgate",
        description="SVX EvalGate - deterministic statistics gate for AI evals in CI",
    )
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="run evals, gate, report (the whole pipeline)")
    p_run.add_argument("--config", help="path to svx.evalgate.yaml / .json")
    p_run.add_argument("--update-baseline", action="store_true",
                       help="write a new baseline after the run (use on pushes to main)")
    p_run.add_argument("--report-stdout", action="store_true",
                       help="print the markdown report to stdout")
    p_run.add_argument("--json", action="store_true",
                       help="print a machine-readable result document to stdout")
    p_run.set_defaults(func=cmd_run)

    p_ing = sub.add_parser(
        "ingest", help="gate an existing test report instead of running a command")
    p_ing.add_argument("--format", default="pytest-junit",
                       choices=list(adapters_mod.FORMATS),
                       help="report format to ingest (default: pytest-junit)")
    p_ing.add_argument("source",
                       help="path to the report file (e.g. pytest's --junitxml output)")
    p_ing.add_argument("--config", help="path to svx.evalgate.yaml / .json")
    p_ing.add_argument("--update-baseline", action="store_true",
                       help="write a new baseline after the ingest")
    p_ing.add_argument("--report-stdout", action="store_true",
                       help="print the markdown report to stdout")
    p_ing.add_argument("--json", action="store_true",
                       help="print a machine-readable result document to stdout")
    p_ing.set_defaults(func=cmd_ingest)

    p_diff = sub.add_parser(
        "diff", help="compare two metric snapshots (default: baseline vs last run)")
    p_diff.add_argument("a", nargs="?", default=None,
                        help="snapshot A (default: the project baseline)")
    p_diff.add_argument("b", nargs="?", default=None,
                        help="snapshot B (default: the last history entry)")
    p_diff.add_argument("--config", help="path to svx.evalgate.yaml / .json")
    p_diff.set_defaults(func=cmd_diff)

    p_base = sub.add_parser("baseline", help="show or reset the baseline document")
    p_base.add_argument("action", nargs="?", default="show",
                        choices=["show", "reset"],
                        help="show: print the baseline (default); "
                             "reset: delete it so the next run re-records")
    p_base.add_argument("--config", help="path to svx.evalgate.yaml / .json")
    p_base.set_defaults(func=cmd_baseline)

    p_trend = sub.add_parser("trend", help="recent run history + sparkline")
    p_trend.add_argument("--config", help="path to svx.evalgate.yaml / .json")
    p_trend.add_argument("--limit", type=int, default=15,
                         help="number of recent runs to show (default 15)")
    p_trend.set_defaults(func=cmd_trend)

    p_init = sub.add_parser("init", help="scaffold svx.evalgate.yaml + evals/run_evals.py")
    p_init.add_argument("directory", nargs="?", default=".",
                        help="target directory (default: current)")
    p_init.set_defaults(func=cmd_init)

    p_ver = sub.add_parser("version", help="print the version")
    p_ver.set_defaults(func=cmd_version)
    parser.add_argument("--version", action="version",
                        version=f"svx-evalgate {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_ERROR
    try:
        return args.func(args)
    except runner_mod.RunnerError as exc:
        _log(f"eval command error: {exc}")
        return EXIT_ERROR
    except (ValueError, OSError) as exc:
        _log(f"error: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
