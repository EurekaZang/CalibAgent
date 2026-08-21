"""P8 Go2 real-robot experiment CLI."""

import argparse
import json
import time
from pathlib import Path

from calibagent.p8.analysis import analyze
from calibagent.p8.config import load_config, validate_config
from calibagent.p8.recording import export_jsonl
from calibagent.p8.reassess import reassess_navigation_run
from calibagent.p8.runner import P8Runtime


def _split(value):  # type: (Optional[str]) -> Optional[Sequence[str]]
    if not value or value.lower() == "all":
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _runtime(args):  # type: (argparse.Namespace) -> P8Runtime
    config = load_config(Path(args.config))
    validate_config(config)
    return P8Runtime(
        config,
        args.run_id,
        Path(args.output_root).expanduser().resolve(),
        backend_name=args.backend,
        arm=args.arm,
        resume=args.resume,
        overwrite=args.overwrite,
        auto_continue=args.auto_continue,
        max_units=args.max_units,
    )


def _add_run_arguments(parser):  # type: (argparse.ArgumentParser) -> None
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", default="p8_real")
    parser.add_argument("--backend", choices=("ros", "fake"), default="ros")
    parser.add_argument(
        "--arm", action="store_true", help="Publish nonzero direct Unitree Sport Move requests"
    )
    existing_run = parser.add_mutually_exclusive_group()
    existing_run.add_argument("--resume", action="store_true")
    existing_run.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete an existing run directory with this exact run ID and start from zero",
    )
    parser.add_argument("--auto-continue", action="store_true")
    parser.add_argument("--max-units", type=int, default=None)
    parser.add_argument("--blocks", default="all")
    parser.add_argument("--methods", default="all")


def build_parser():  # type: () -> argparse.ArgumentParser
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="Validate counts, IDs, and all frozen input hashes")
    validate.add_argument("--config", required=True)
    nav = sub.add_parser("nav", help="Run or resume P8-NAV")
    _add_run_arguments(nav)
    nav.add_argument(
        "--routes",
        default="all",
        help="Run only route letters A and/or B; e.g. --routes A for route-phase execution",
    )
    shift = sub.add_parser("shift", help="Run or resume P8-SHIFT")
    _add_run_arguments(shift)
    shift.add_argument("--shifts", default="all")
    check = sub.add_parser("io-check", help="Read-only scan/reference/planner freshness check")
    check.add_argument("--config", required=True)
    check.add_argument("--duration", type=float, default=60.0)
    check.add_argument("--backend", choices=("ros", "fake"), default="ros")
    check.add_argument("--output-root", default="p8_real")
    export = sub.add_parser("export", help="Export JSONL traces to CSV and Parquet when available")
    export.add_argument("--run-dir", required=True)
    analysis = sub.add_parser("analyze", help="Generate paired-block NAV/SHIFT analysis")
    analysis.add_argument("--run-dir", required=True)
    reassess = sub.add_parser(
        "reassess-nav", help="Recompute NAV freshness from trace and rosbag evidence"
    )
    reassess.add_argument("--config", required=True)
    reassess.add_argument("--run-dir", required=True)
    reassess.add_argument("--apply", action="store_true")
    return parser


def main(argv=None):  # type: (Optional[Sequence[str]]) -> int
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        result = validate_config(load_config(Path(args.config)))
    elif args.command == "export":
        result = export_jsonl(Path(args.run_dir).expanduser().resolve())
    elif args.command == "analyze":
        result = analyze(Path(args.run_dir).expanduser().resolve())
    elif args.command == "reassess-nav":
        config = load_config(Path(args.config))
        validate_config(config)
        result = reassess_navigation_run(
            Path(args.run_dir), config.payload.get("quality", {}), apply=args.apply
        )
    elif args.command == "io-check":
        config = load_config(Path(args.config))
        validate_config(config)
        run_id = "io_check_{}".format(time.strftime("%Y%m%dT%H%M%S"))
        runtime = P8Runtime(
            config,
            run_id,
            Path(args.output_root).expanduser().resolve(),
            backend_name=args.backend,
            arm=False,
            auto_continue=True,
        )
        try:
            result = runtime.io_check(args.duration)
            output = runtime.run_dir / "io_check.json"
            output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result["output"] = str(output)
        finally:
            runtime.close()
    else:
        runtime = _runtime(args)
        try:
            if args.command == "nav":
                result = runtime.run_nav(
                    blocks=_split(args.blocks),
                    methods=_split(args.methods),
                    routes=_split(args.routes),
                )
            else:
                result = runtime.run_shift(
                    shifts=_split(args.shifts),
                    blocks=_split(args.blocks),
                    methods=_split(args.methods),
                )
        finally:
            runtime.close()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
