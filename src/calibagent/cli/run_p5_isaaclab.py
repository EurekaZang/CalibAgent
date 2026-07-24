"""Run the frozen P5 Isaac Lab Go2 benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from calibagent.eval.p5_isaaclab import run_p5_suite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiments/p5_isaaclab_main.yaml"),
    )
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--isaaclab-root", type=Path, required=True)
    parser.add_argument(
        "--checkpoint-cache",
        type=Path,
        default=Path("outputs/p5_cache"),
    )
    args = parser.parse_args()
    summary = run_p5_suite(
        args.config.resolve(),
        args.workspace.resolve(),
        args.isaaclab_root.resolve(),
        args.checkpoint_cache.resolve(),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["verdict"] != "GO":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

