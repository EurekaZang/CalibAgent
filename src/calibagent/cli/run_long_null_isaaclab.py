"""Run the frozen long-horizon no-shift Isaac Lab exposure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from calibagent.eval.long_null_isaaclab import run_long_null_suite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiments/long_null_monitor.yaml"),
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--isaaclab-root", type=Path, required=True)
    parser.add_argument(
        "--checkpoint-cache", type=Path, default=Path("outputs/p5_cache")
    )
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
    summary = run_long_null_suite(
        arguments.config,
        arguments.workspace,
        arguments.isaaclab_root,
        arguments.checkpoint_cache,
        resume=arguments.resume,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["verdict"] != "GO":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
