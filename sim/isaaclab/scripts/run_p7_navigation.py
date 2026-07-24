"""Run one vectorized P7 navigation method/map inside Isaac Lab."""

from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--scenario-config", type=Path, required=True)
parser.add_argument("--checkpoint", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

from calibagent_sim.p7_runner import run_p7_navigation  # noqa: E402


def main() -> None:
    payload = json.loads(args.scenario_config.read_text(encoding="utf-8"))
    summary = run_p7_navigation(
        payload,
        args.checkpoint.resolve(),
        args.output.resolve(),
        args.device,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except BaseException:
        traceback.print_exc()
        exit_code = 1
    finally:
        simulation_app.close()
    raise SystemExit(exit_code)
