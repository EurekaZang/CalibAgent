"""Run one vectorized P5 scenario inside Isaac Lab."""

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

from calibagent_sim.runner import ScenarioConfig, run_scenario  # noqa: E402


def main() -> None:
    payload = json.loads(args.scenario_config.read_text(encoding="utf-8"))
    config = ScenarioConfig(
        scenario_id=str(payload["scenario_id"]),
        tier=str(payload["tier"]),
        task=str(payload["task"]),
        distortion=str(payload["distortion"]),
        terrain=str(payload["terrain"]),
        static_friction=float(payload["static_friction"]),
        dynamic_friction=float(payload["dynamic_friction"]),
        payload_add_kg=float(payload["payload_add_kg"]),
        com_offset_x_m=float(payload["com_offset_x_m"]),
        seeds=tuple(int(item) for item in payload["seeds"]),
        calibration_trials=int(payload["calibration_trials"]),
        warmup_s=float(payload["warmup_s"]),
        ramp_in_s=float(payload["ramp_in_s"]),
        settle_s=float(payload["settle_s"]),
        measure_s=float(payload["measure_s"]),
        ramp_out_s=float(payload["ramp_out_s"]),
        sample_rate_hz=float(payload["sample_rate_hz"]),
        simulator_seed=int(payload["simulator_seed"]),
        safety_min_base_height_m=float(payload["safety_min_base_height_m"]),
        safety_max_base_height_m=float(payload["safety_max_base_height_m"]),
        model_prior_scale=float(payload["model_prior_scale"]),
    )
    summary = run_scenario(config, args.checkpoint.resolve(), args.output.resolve(), args.device)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except BaseException:  # Isaac Sim may suppress an exception during shutdown.
        traceback.print_exc()
        exit_code = 1
    finally:
        simulation_app.close()
    raise SystemExit(exit_code)
