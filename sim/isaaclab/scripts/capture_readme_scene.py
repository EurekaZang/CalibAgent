"""Capture publication-facing RGB frames from a frozen CalibAgent scene.

This utility replays the declared Isaac Lab scene with one selected simulator
seed.  The resulting images are qualitative scene documentation; the frozen
multi-seed evidence remains the source of quantitative claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--scenario-config", type=Path, required=True)
parser.add_argument("--checkpoint", type=Path, required=True)
parser.add_argument("--runtime-manifest", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--phase", choices=("p5", "p7"), required=True)
parser.add_argument("--seed", type=int, required=True)
parser.add_argument("--stabilization-steps", type=int, default=0)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

import gymnasium as gym  # noqa: E402
import torch  # noqa: E402
from calibagent_sim.p7_runner import _map_environment  # noqa: E402
from calibagent_sim.policy import load_actor  # noqa: E402
from calibagent_sim.runner import (  # noqa: E402
    ScenarioConfig,
    _configure_environment,
)
from isaaclab import sim as sim_utils  # noqa: E402
from isaaclab.sensors.camera import CameraCfg  # noqa: E402
from isaaclab.sensors.camera.utils import save_images_to_file  # noqa: E402

_VIEWS = {
    "p5": {
        "overview": {
            "eye": (2.6, 2.2, 1.45),
            "target": (0.0, 0.0, 0.28),
            "description": "Oblique view of the Go2 in the P5 closed-loop calibration scene.",
        },
        "closeup": {
            "eye": (1.25, 1.15, 0.72),
            "target": (0.0, 0.0, 0.27),
            "description": "Front-oblique view of the Go2 under the registered policy.",
        },
    },
    "p7": {
        "overview": {
            "eye": (4.4, 3.8, 3.0),
            "target": (1.45, 0.0, 0.25),
            "description": ("Elevated view of the Go2, three slalom obstacles, and ground plane."),
        },
        "robot_view": {
            "eye": (-1.8, 2.3, 1.25),
            "target": (0.75, 0.0, 0.30),
            "description": "Low oblique view from behind the Go2 toward the slalom course.",
        },
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _single_seed_payload(path: Path, seed: int) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    declared_seeds = [int(item) for item in payload["seeds"]]
    if seed not in declared_seeds:
        raise ValueError(f"seed {seed} is not declared in {path}; choose one of {declared_seeds}")
    payload["seeds"] = [seed]
    return payload


def _p5_config(payload: dict[str, Any]) -> ScenarioConfig:
    return ScenarioConfig(
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
        safety_max_coupled_load=float(payload["safety_max_coupled_load"]),
        model_prior_scale=float(payload["model_prior_scale"]),
    )


def _capture() -> None:
    scenario_config = args.scenario_config.resolve()
    checkpoint = args.checkpoint.resolve()
    runtime_manifest = args.runtime_manifest.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = _single_seed_payload(scenario_config, args.seed)
    if args.phase == "p7":
        env_cfg, config = _map_environment(payload, args.device)
        scenario_id = str(payload["id"])
        method = str(payload["method"])
    else:
        config = _p5_config(payload)
        env_cfg = _configure_environment(config, args.device)
        scenario_id = config.scenario_id
        method = "active"
    env_cfg.scene.readme_camera = CameraCfg(
        prim_path="{ENV_REGEX_NS}/ReadmeCamera",
        update_period=0.0,
        height=720,
        width=1280,
        data_types=["rgb"],
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=28.0,
            focus_distance=400.0,
            horizontal_aperture=24.0,
            clipping_range=(0.1, 1.0e5),
        ),
    )

    env = gym.make(config.task, cfg=env_cfg)
    actor = load_actor(checkpoint, str(env.unwrapped.device))
    captured: list[dict[str, Any]] = []
    try:
        env.reset()
        unwrapped = env.unwrapped
        command_term = unwrapped.command_manager.get_term("base_velocity")
        camera = unwrapped.scene["readme_camera"]

        with torch.no_grad():
            for _ in range(args.stabilization_steps):
                command_term.vel_command_b[:] = 0.0
                observation = unwrapped.observation_manager.compute()["policy"]
                actions = actor(torch.clamp(observation, -100.0, 100.0))
                env.step(torch.clamp(actions, -100.0, 100.0))

            for name, view in _VIEWS[args.phase].items():
                eyes = torch.tensor(
                    [view["eye"]],
                    dtype=torch.float32,
                    device=unwrapped.device,
                )
                targets = torch.tensor(
                    [view["target"]],
                    dtype=torch.float32,
                    device=unwrapped.device,
                )
                camera.set_world_poses_from_view(eyes, targets)
                for _ in range(4):
                    command_term.vel_command_b[:] = 0.0
                    observation = unwrapped.observation_manager.compute()["policy"]
                    actions = actor(torch.clamp(observation, -100.0, 100.0))
                    env.step(torch.clamp(actions, -100.0, 100.0))

                rgb = camera.data.output["rgb"].clone()
                if not torch.is_floating_point(rgb):
                    rgb = rgb.to(dtype=torch.float32) / 255.0
                image_path = output_dir / f"{args.phase}_isaac_sim_{name}.png"
                save_images_to_file(rgb, str(image_path))
                captured.append(
                    {
                        "path": image_path.name,
                        "sha256": _sha256(image_path),
                        "resolution": [1280, 720],
                        "eye_xyz_m": list(view["eye"]),
                        "target_xyz_m": list(view["target"]),
                        "description": view["description"],
                    }
                )
    finally:
        env.close()

    manifest = json.loads(runtime_manifest.read_text(encoding="utf-8"))
    provenance = {
        "schema_version": "1.0",
        "artifact_type": "qualitative_isaac_sim_scene_capture",
        "quantitative_evidence": False,
        "source_phase": args.phase.upper(),
        "scenario_id": scenario_id,
        "method": method,
        "selected_seed": args.seed,
        "declared_seed_membership_verified": True,
        "task": payload["task"],
        "scenario_config": str(args.scenario_config),
        "scenario_config_sha256": _sha256(scenario_config),
        "runtime_manifest": str(args.runtime_manifest),
        "runtime": manifest["runtime"],
        "checkpoint": {
            "path": str(args.checkpoint),
            "sha256": _sha256(checkpoint),
            "registered_sha256": manifest["checkpoints"]["flat"]["sha256"],
        },
        "stabilization": {
            "steps": args.stabilization_steps,
            "command": [0.0, 0.0, 0.0],
            "policy": "registered official Go2 flat checkpoint",
        },
        "frames": captured,
        "interpretation": (
            "These RGB frames document the frozen scene and simulator assets. "
            "They do not replace or augment the registered multi-seed statistics."
        ),
    }
    if provenance["checkpoint"]["sha256"] != provenance["checkpoint"]["registered_sha256"]:
        raise RuntimeError("checkpoint SHA-256 does not match the frozen P7 manifest")
    (output_dir / f"{args.phase}_isaac_sim_capture.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    exit_code = 0
    try:
        _capture()
    except BaseException:
        traceback.print_exc()
        exit_code = 1
    finally:
        simulation_app.close()
    raise SystemExit(exit_code)
