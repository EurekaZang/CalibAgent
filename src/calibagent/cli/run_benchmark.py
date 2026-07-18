"""Run paired sample-efficiency suites from a frozen YAML config."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from calibagent.eval.benchmark import BenchmarkConfig, run_suite


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    arguments = parser.parse_args()
    with arguments.config.open(encoding="utf-8") as stream:
        config = BenchmarkConfig.from_dict(yaml.safe_load(stream))
    print(json.dumps(run_suite(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
