"""Generate the frozen P1 Go2 acquisition command plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from calibagent.eval.capture_plan import CapturePlanConfig, write_capture_plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiments/p1_go2_capture.yaml"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/p1_capture/plan.csv"))
    arguments = parser.parse_args()
    config = CapturePlanConfig.from_yaml(arguments.config)
    print(json.dumps(write_capture_plan(config, arguments.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
