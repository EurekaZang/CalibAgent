"""Run the frozen task-distribution mismatch sensitivity analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from calibagent.eval.task_mismatch import run_task_mismatch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiments/task_distribution_mismatch.yaml"),
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    summary = run_task_mismatch(arguments.config, arguments.workspace)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
