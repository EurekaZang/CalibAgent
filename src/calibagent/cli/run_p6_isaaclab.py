"""Run the frozen P6 Isaac Lab domain-shift benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from calibagent.eval.p6_isaaclab import run_p6_suite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiments/p6_domain_shift_main.yaml"),
    )
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--isaaclab-root", type=Path, required=True)
    parser.add_argument(
        "--checkpoint-cache",
        type=Path,
        default=Path("outputs/p5_cache"),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse method directories only when every required artifact is complete",
    )
    args = parser.parse_args()
    summary = run_p6_suite(
        args.config.resolve(),
        args.workspace.resolve(),
        args.isaaclab_root.resolve(),
        args.checkpoint_cache.resolve(),
        resume=args.resume,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["verdict"] != "GO":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
