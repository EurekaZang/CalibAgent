"""Run P1 passive baselines against a canonical Parquet dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

from calibagent.data.observations import load_observations
from calibagent.eval.replay import run_passive_replay_baseline


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, default=Path("outputs/p1_replay"))
    parser.add_argument("--budget", type=int, default=30)
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=1701)
    arguments = parser.parse_args()
    observations = load_observations(arguments.dataset)
    run_passive_replay_baseline(
        observations,
        arguments.output,
        budget=arguments.budget,
        validation_fraction=arguments.validation_fraction,
        seed=arguments.seed,
    )


if __name__ == "__main__":
    main()
