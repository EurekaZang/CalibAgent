"""Minimal single synthetic calibration run for the P0-P3 vertical slice."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from calibagent.eval.benchmark import BenchmarkConfig, run_suite


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path, default=Path("configs/experiments/offline_active_m2.yaml")
    )
    parser.add_argument("--seed", type=int, default=None)
    arguments = parser.parse_args()
    with arguments.config.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if arguments.seed is not None:
        payload["seeds"] = [arguments.seed]
    payload["methods"] = ["active"]
    run_suite(BenchmarkConfig.from_dict(payload))


if __name__ == "__main__":
    main()
