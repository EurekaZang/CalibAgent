"""Build traceable P1 evidence from raw robot trial time series."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from calibagent.eval.real_replay import build_real_replay_evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("outputs/p1_real"))
    parser.add_argument("--source-kind", choices=("real_robot", "synthetic_fixture"), required=True)
    parser.add_argument("--robot-model", default="unitree_go2")
    parser.add_argument("--reference-sensor", required=True)
    parser.add_argument("--capture-plan", type=Path)
    parser.add_argument("--delivery-root", type=Path)
    parser.add_argument("--source-archive", type=Path)
    parser.add_argument("--budget", type=int, default=30)
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=1701)
    arguments = parser.parse_args()
    evidence = build_real_replay_evidence(
        arguments.source,
        arguments.output,
        source_kind=arguments.source_kind,
        robot_model=arguments.robot_model,
        reference_sensor=arguments.reference_sensor,
        capture_plan=arguments.capture_plan,
        delivery_root=arguments.delivery_root,
        source_archive=arguments.source_archive,
        budget=arguments.budget,
        validation_fraction=arguments.validation_fraction,
        seed=arguments.seed,
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
