"""Run the frozen P4 safety and stopping benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from calibagent.eval.p4_benchmark import run_p4_suite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiments/p4_safety_stop_main.yaml"),
    )
    parser.add_argument("--workspace", type=Path, default=Path("."))
    args = parser.parse_args()
    summary = run_p4_suite(args.config.resolve(), args.workspace.resolve())
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["verdict"] != "GO":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
