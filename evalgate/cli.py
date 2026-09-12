"""EvalGate command-line interface.

    evalgate run [--config PATH] [--update-baseline] [--report-stdout]
    evalgate baseline [--config PATH]          # print the current baseline
    evalgate version

Exit codes: 0 = green, 1 = red (threshold or regression), 2 = error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from . import baseline as baseline_mod
from . import config as config_mod
from . import gate as gate_mod
from . import github as github_mod
from . import report as report_mod
from . import runner as runner_mod
from . import stats as stats_mod

EXIT_GREEN, EXIT_RED, EXIT_ERROR = 0, 1, 2


def _log(msg: str) -> None:
    print(f"evalgate: {msg}", file=sys.stderr)


def _resolve_config(args) -> tuple[config_mod.Config | None, list[str], Path]:
    cwd = Path.cwd()
    path = config_mod.find_config(getattr(args, "config", None), cwd)
    if path is None:
        hint = getattr(args, "config", None) or " or ".join(config_mod.DEFAULT_CONFIG_NAMES)
        raise SystemExit(
            f"evalgate: config not found ({hint}); create one in the working "
            "directory or pass --config"
        )
    cfg, warnings = config_mod.load_config(path)
    for warning in warnings:
        _log(warning)
    return cfg, warnings, path


def cmd_run(args) -> int:
    cfg, _warnings, cfg_path = _resolve_config(args)

    workdir = cfg.source_path.parent
    if cfg.evals.working_dir:
        candidate = Path(cfg.evals.working_dir)
        workdir = candidate if candidate.is_absolute() else (cfg.source_path.parent / candidate)

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

    agg = stats_mod.aggregate(
        outcome.rows, k=cfg.gate.k, base_seed=cfg.evals.base_seed,
        bootstrap_iterations=cfg.evals.bootstrap_iterations,
    )

    bpath = baseline_mod.baseline_path(cfg)
    baseline = baseline_mod.load_baseline(bpath)
    if baseline is not None:
        _log(f"baseline loaded from {bpath} "
             f"(created {baseline.get('created', '?')})")

    gate_result = gate_mod.evaluate(agg, cfg, baseline)

    markdown = report_mod.render(agg, cfg, baseline, gate_result)
    report_path = (cfg.source_path.parent / cfg.report.path
                   if not Path(cfg.report.path).is_absolute() else Path(cfg.report.path))
    report_mod.write_report(markdown, report_path)
    github_mod.write_step_summary(markdown)
    github_mod.post_pr_comment(markdown)

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

    verdict = "GREEN" if gate_result.green else "RED"
    _log(f"verdict: {verdict}")
    for reason in gate_result.reasons():
        _log(f"  - {reason}")
    _log(f"report: {report_path}")
    return EXIT_GREEN if gate_result.green else EXIT_RED


def cmd_baseline(args) -> int:
    cfg, _warnings, _path = _resolve_config(args)
    bpath = baseline_mod.baseline_path(cfg)
    doc = baseline_mod.load_baseline(bpath)
    if doc is None:
        _log(f"no baseline at {bpath}")
        return EXIT_ERROR
    print(json.dumps(doc, indent=2, sort_keys=True))
    return EXIT_GREEN


def cmd_version(_args) -> int:
    print(f"svx-evalgate {__version__}")
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
    p_run.set_defaults(func=cmd_run)

    p_base = sub.add_parser("baseline", help="print the current baseline document")
    p_base.add_argument("--config", help="path to svx.evalgate.yaml / .json")
    p_base.set_defaults(func=cmd_baseline)

    p_ver = sub.add_parser("version", help="print the version")
    p_ver.set_defaults(func=cmd_version)
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
