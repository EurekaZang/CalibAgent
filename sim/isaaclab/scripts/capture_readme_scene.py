"""Capture publication-facing RGB frames from a frozen CalibAgent scene.

This utility replays the declared Isaac Lab scene with one selected simulator
seed.  The resulting images are qualitative scene documentation; the frozen
multi-seed evidence remains the source of quantitative claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import traceback
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--scenario-config", type=Path, required=True)
parser.add_argument("--checkpoint", type=Path, required=True)
parser.add_argument("--runtime-manifest", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--phase", choices=("p5", "p6", "p7"), required=True)
parser.add_argument("--seed", type=int, required=True)
parser.add_argument("--stabilization-steps", type=int, default=0)
parser.add_argument(
    "--artifact-prefix",
    help="Output basename; defaults to '<phase>_isaac_sim' for compatibility.",
)
parser.add_argument(
    "--visualize-route",
    action="store_true",
    help="Add non-colliding route and waypoint overlays from a P7 frozen config.",
)
parser.add_argument(
    "--auto-map-view",
    action="store_true",
    help="Fit P7 camera views to the frozen waypoint/obstacle extent.",
)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

import gymnasium as gym  # noqa: E402
import torch  # noqa: E402
from calibagent_sim.p6_runner import _physical_config as _p6_physical_config  # noqa: E402
from calibagent_sim.p7_runner import _map_environment  # noqa: E402
from calibagent_sim.policy import load_actor  # noqa: E402
from calibagent_sim.runner import (  # noqa: E402
    _VALIDATION_COMMANDS,
    ScenarioConfig,
    _configure_environment,
    _state_arrays,
    _trial_profile,
)
from isaaclab import sim as sim_utils  # noqa: E402
from isaaclab.assets import AssetBaseCfg  # noqa: E402
from isaaclab.sensors.camera import CameraCfg  # noqa: E402
from isaaclab.sensors.camera.utils import save_images_to_file  # noqa: E402

from calibagent.sim import CommandDistortion, make_distortion_parameters  # noqa: E402

_RESPONSE_PROBES = {
    "coupled_response": {
        "command": _VALIDATION_COMMANDS[2],
        "registered_command_index": 2,
        "color": (0.10, 0.72, 0.95),
        "description": (
            "Registered validation command [0.20, -0.18, -0.30] and its "
            "simulated body-response trajectory."
        ),
    },
    "forward_turn_response": {
        "command": _VALIDATION_COMMANDS[7],
        "registered_command_index": 7,
        "color": (0.92, 0.35, 0.16),
        "description": (
            "Registered validation command [0.35, 0.00, 0.50] and its "
            "simulated body-response trajectory."
        ),
    },
}

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
    "p6": {
        "overview": {
            "eye": (2.6, 2.2, 1.45),
            "target": (0.0, 0.0, 0.28),
            "description": "Oblique view of the Go2 in a P6 post-shift physical context.",
        },
        "closeup": {
            "eye": (1.25, 1.15, 0.72),
            "target": (0.0, 0.0, 0.27),
            "description": "Front-oblique view after applying the registered P6 shift.",
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


def _json_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


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


def _artifact_prefix(phase: str) -> str:
    prefix = args.artifact_prefix or f"{phase}_isaac_sim"
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", prefix) is None:
        raise ValueError("artifact prefix must contain only lowercase letters, digits, '_' or '-'")
    return prefix


def _p7_views(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not args.auto_map_view:
        return _VIEWS["p7"]
    points = [(0.0, 0.0)]
    points.extend((float(point[0]), float(point[1])) for point in payload["waypoints"])
    for obstacle in payload["obstacles"]:
        center = obstacle["center"]
        size = obstacle["size"]
        points.extend(
            [
                (
                    float(center[0]) - float(size[0]) / 2.0,
                    float(center[1]) - float(size[1]) / 2.0,
                ),
                (
                    float(center[0]) + float(size[0]) / 2.0,
                    float(center[1]) + float(size[1]) / 2.0,
                ),
            ]
        )
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    x_center = (x_min + x_max) / 2.0
    y_center = (y_min + y_max) / 2.0
    course_length = max(x_max - x_min, 2.5)
    half_width = max((y_max - y_min) / 2.0, 0.7)
    return {
        "overview": {
            "eye": (
                x_max + 1.35,
                y_center + 2.8 + half_width,
                2.7 + 0.15 * course_length,
            ),
            "target": (x_center, y_center, 0.16),
            "description": (f"Elevated view fitted to the frozen {payload['id']} navigation map."),
        },
        "robot_view": {
            "eye": (x_min - 1.65, y_center + 2.15 + half_width / 2.0, 1.25),
            "target": (x_center, y_center, 0.20),
            "description": (f"Low route-facing view of the Go2 and {payload['id']} map."),
        },
    }


def _add_p7_route_overlay(env_cfg: Any, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Add capture-only, non-colliding route geometry from frozen waypoints."""

    if not args.visualize_route:
        return []
    overlays: list[dict[str, Any]] = []
    points = [(0.0, 0.0)]
    points.extend((float(point[0]), float(point[1])) for point in payload["waypoints"])
    for index, point in enumerate(points):
        is_goal = index == len(points) - 1
        marker = AssetBaseCfg(
            prim_path=f"{{ENV_REGEX_NS}}/ReadmeRoutePoint{index}",
            spawn=sim_utils.SphereCfg(
                radius=0.065 if is_goal else 0.045,
                visual_material=sim_utils.PreviewSurfaceCfg(
                    diffuse_color=(0.15, 0.90, 0.35) if is_goal else (0.10, 0.62, 0.95),
                    emissive_color=(0.03, 0.16, 0.05) if is_goal else (0.02, 0.08, 0.16),
                ),
            ),
            init_state=AssetBaseCfg.InitialStateCfg(pos=(point[0], point[1], 0.055)),
        )
        setattr(env_cfg.scene, f"readme_route_point_{index}", marker)
        overlays.append(
            {
                "kind": "goal" if is_goal else "waypoint",
                "position_xy_m": [point[0], point[1]],
            }
        )
    for index, (start, end) in enumerate(pairwise(points)):
        delta_x = end[0] - start[0]
        delta_y = end[1] - start[1]
        length = math.hypot(delta_x, delta_y)
        yaw = math.atan2(delta_y, delta_x)
        segment = AssetBaseCfg(
            prim_path=f"{{ENV_REGEX_NS}}/ReadmeRouteSegment{index}",
            spawn=sim_utils.CuboidCfg(
                size=(length, 0.028, 0.012),
                visual_material=sim_utils.PreviewSurfaceCfg(
                    diffuse_color=(0.08, 0.54, 0.92),
                    emissive_color=(0.02, 0.08, 0.18),
                ),
            ),
            init_state=AssetBaseCfg.InitialStateCfg(
                pos=(
                    (start[0] + end[0]) / 2.0,
                    (start[1] + end[1]) / 2.0,
                    0.014,
                ),
                rot=(math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)),
            ),
        )
        setattr(env_cfg.scene, f"readme_route_segment_{index}", segment)
        overlays.append(
            {
                "kind": "route_segment",
                "start_xy_m": [start[0], start[1]],
                "end_xy_m": [end[0], end[1]],
            }
        )
    return overlays


def _checkpoint_key(payload: dict[str, Any], config: ScenarioConfig) -> str:
    declared = payload.get("checkpoint")
    if declared is not None:
        return str(declared)
    return "rough" if config.terrain == "rough" else "flat"


def _capture_distortion(
    phase: str,
    payload: dict[str, Any],
    config: ScenarioConfig,
) -> tuple[CommandDistortion, dict[str, Any]]:
    if phase == "p6":
        family = str(payload["post_distortion"])
        parameter_seed = int(args.seed) + int(payload["post_seed_offset"])
        stochastic_seed = int(payload["simulator_seed"]) + 117
        registration = "P6 post-shift distortion construction"
    else:
        family = config.distortion
        parameter_seed = int(args.seed)
        stochastic_seed = config.simulator_seed + 91
        registration = "P5 frozen distortion construction"
    parameters = make_distortion_parameters(family, (parameter_seed,))
    return (
        CommandDistortion(parameters, seed=stochastic_seed),
        {
            "family": family,
            "parameter_seed": parameter_seed,
            "stochastic_seed": stochastic_seed,
            "parameters": parameters.to_dict(),
            "registration": registration,
        },
    )


def _response_camera_view(
    probe_name: str,
) -> dict[str, Any]:
    if probe_name == "coupled_response":
        eye = (1.65, 2.15, 1.55)
        target = (0.18, -0.12, 0.15)
    else:
        eye = (-1.55, 2.10, 1.45)
        target = (0.35, 0.18, 0.14)
    return {
        "eye": eye,
        "target": target,
        "description": _RESPONSE_PROBES[probe_name]["description"],
    }


def _spawn_response_trajectory(
    trajectory: list[list[float]],
    environment_origin: torch.Tensor,
    color: tuple[float, float, float],
) -> dict[str, Any]:
    """Render an actual response trace as non-colliding Isaac Sim geometry."""

    overlay_root = "/World/envs/env_0/ReadmeResponse"
    if sim_utils.is_prim_path_valid(overlay_root):
        sim_utils.delete_prim(overlay_root)
    stride = max(1, len(trajectory) // 24)
    sampled = trajectory[::stride]
    if sampled[-1] != trajectory[-1]:
        sampled.append(trajectory[-1])
    origin = environment_origin.detach().cpu().tolist()
    world_points = [
        (
            point[0] + float(origin[0]),
            point[1] + float(origin[1]),
            0.055 + float(origin[2]),
        )
        for point in sampled
    ]

    start_cfg = sim_utils.SphereCfg(
        radius=0.075,
        visual_material=sim_utils.PreviewSurfaceCfg(
            diffuse_color=(0.98, 0.82, 0.12),
            emissive_color=(0.20, 0.13, 0.01),
        ),
    )
    start_cfg.func(f"{overlay_root}/Start", start_cfg, translation=world_points[0])
    end_cfg = sim_utils.SphereCfg(
        radius=0.075,
        visual_material=sim_utils.PreviewSurfaceCfg(
            diffuse_color=(0.18, 0.92, 0.32),
            emissive_color=(0.02, 0.18, 0.04),
        ),
    )
    end_cfg.func(f"{overlay_root}/ResponseEndpoint", end_cfg, translation=world_points[-1])

    segment_count = 0
    for index, (start, end) in enumerate(pairwise(world_points)):
        delta_x = end[0] - start[0]
        delta_y = end[1] - start[1]
        length = math.hypot(delta_x, delta_y)
        if length < 1.0e-4:
            continue
        yaw = math.atan2(delta_y, delta_x)
        segment_cfg = sim_utils.CuboidCfg(
            size=(length, 0.038, 0.018),
            visual_material=sim_utils.PreviewSurfaceCfg(
                diffuse_color=color,
                emissive_color=tuple(0.18 * channel for channel in color),
            ),
        )
        segment_cfg.func(
            f"{overlay_root}/Segment{index:03d}",
            segment_cfg,
            translation=(
                (start[0] + end[0]) / 2.0,
                (start[1] + end[1]) / 2.0,
                (start[2] + end[2]) / 2.0,
            ),
            orientation=(math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)),
        )
        segment_count += 1
    return {
        "kind": "measured_response_trajectory",
        "collision_enabled": False,
        "start_marker": "yellow",
        "endpoint_marker": "green",
        "segment_color_rgb": list(color),
        "source_samples": len(trajectory),
        "rendered_points": len(sampled),
        "rendered_segments": segment_count,
        "sampled_xy_m": [[point[0], point[1]] for point in sampled],
    }


def _run_response_probe(
    env: Any,
    actor: torch.nn.Module,
    distortion: CommandDistortion,
    config: ScenarioConfig,
    command: np.ndarray,
) -> dict[str, Any]:
    observation, _ = env.reset()
    del observation
    unwrapped = env.unwrapped
    command_term = unwrapped.command_manager.get_term("base_velocity")
    robot = unwrapped.scene["robot"]
    origins = unwrapped.scene.env_origins
    device = str(unwrapped.device)
    dt = float(unwrapped.step_dt)
    scales, phases = _trial_profile(config)
    desired = np.asarray(command, dtype=np.float64)[None, :]
    distortion.reset()
    trajectory: list[list[float]] = []
    effective_trace: list[list[float]] = []
    executed_phases: list[int] = []

    with torch.no_grad():
        for scale, phase in zip(scales, phases, strict=True):
            if int(phase) == 3:
                break
            commanded = desired * float(scale)
            effective = distortion.step(commanded, dt)
            command_term.vel_command_b[:] = torch.as_tensor(
                effective,
                dtype=torch.float32,
                device=device,
            )
            policy_observation = unwrapped.observation_manager.compute()["policy"]
            actions = actor(torch.clamp(policy_observation, -100.0, 100.0))
            env.step(torch.clamp(actions, -100.0, 100.0))
            position, _, _, roll, pitch, yaw = _state_arrays(robot, origins)
            trajectory.append(
                [
                    float(position[0, 0]),
                    float(position[0, 1]),
                    float(position[0, 2]),
                    float(roll[0]),
                    float(pitch[0]),
                    float(yaw[0]),
                ]
            )
            effective_trace.append([float(value) for value in effective[0]])
            executed_phases.append(int(phase))
    return {
        "desired_command": [float(value) for value in command],
        "sample_rate_hz": config.sample_rate_hz,
        "step_dt_s": dt,
        "capture_at": "registered_measurement_window_endpoint_before_ramp_out",
        "profile_samples": len(executed_phases),
        "profile_phase_counts": {
            str(phase): executed_phases.count(phase) for phase in sorted(set(executed_phases))
        },
        "trajectory": trajectory,
        "trajectory_sha256": _json_sha256(trajectory),
        "effective_command_trace_sha256": _json_sha256(effective_trace),
        "effective_command_min": np.min(effective_trace, axis=0).tolist(),
        "effective_command_max": np.max(effective_trace, axis=0).tolist(),
        "response_endpoint_pose": trajectory[-1],
    }


def _capture_response_frames(
    env: Any,
    actor: torch.nn.Module,
    phase: str,
    prefix: str,
    payload: dict[str, Any],
    config: ScenarioConfig,
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    unwrapped = env.unwrapped
    camera = unwrapped.scene["readme_camera"]
    environment_origin = unwrapped.scene.env_origins[0]
    captured: list[dict[str, Any]] = []
    overlays: list[dict[str, Any]] = []
    distortion, distortion_record = _capture_distortion(phase, payload, config)

    for probe_name, probe in _RESPONSE_PROBES.items():
        response = _run_response_probe(
            env,
            actor,
            distortion,
            config,
            np.asarray(probe["command"], dtype=np.float64),
        )
        trajectory = response.pop("trajectory")
        overlay = _spawn_response_trajectory(
            trajectory,
            environment_origin,
            probe["color"],
        )
        overlay["probe_name"] = probe_name
        overlays.append(overlay)
        view = _response_camera_view(probe_name)
        eyes = torch.tensor(
            [view["eye"]],
            dtype=torch.float32,
            device=unwrapped.device,
        ) + environment_origin
        targets = torch.tensor(
            [view["target"]],
            dtype=torch.float32,
            device=unwrapped.device,
        ) + environment_origin
        camera.set_world_poses_from_view(eyes, targets)

        command_term = unwrapped.command_manager.get_term("base_velocity")
        with torch.no_grad():
            for _ in range(4):
                command_term.vel_command_b[:] = 0.0
                observation = unwrapped.observation_manager.compute()["policy"]
                actions = actor(torch.clamp(observation, -100.0, 100.0))
                env.step(torch.clamp(actions, -100.0, 100.0))
        position, _, _, roll, pitch, yaw = _state_arrays(
            unwrapped.scene["robot"],
            unwrapped.scene.env_origins,
        )
        capture_pose = [
            float(position[0, 0]),
            float(position[0, 1]),
            float(position[0, 2]),
            float(roll[0]),
            float(pitch[0]),
            float(yaw[0]),
        ]
        rgb = camera.data.output["rgb"].clone()
        if not torch.is_floating_point(rgb):
            rgb = rgb.to(dtype=torch.float32) / 255.0
        image_path = output_dir / f"{prefix}_{probe_name}.png"
        save_images_to_file(rgb, str(image_path))
        captured.append(
            {
                "path": image_path.name,
                "sha256": _sha256(image_path),
                "resolution": [1280, 720],
                "camera_pose_frame": "environment_local",
                "eye_xyz_m": list(view["eye"]),
                "target_xyz_m": list(view["target"]),
                "description": view["description"],
                "response_probe": {
                    "name": probe_name,
                    "registered_command_source": (
                        "sim/isaaclab/calibagent_sim/runner.py::"
                        f"_VALIDATION_COMMANDS[{probe['registered_command_index']}]"
                    ),
                    "registered_command_index": probe["registered_command_index"],
                    **response,
                    "capture_pose_after_four_zero_command_render_steps": capture_pose,
                },
            }
        )
    return captured, overlays, distortion_record


def _capture() -> None:
    scenario_config = args.scenario_config.resolve()
    checkpoint = args.checkpoint.resolve()
    runtime_manifest = args.runtime_manifest.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = _single_seed_payload(scenario_config, args.seed)
    overlays: list[dict[str, Any]] = []
    distortion_record: dict[str, Any] | None = None
    if args.phase == "p7":
        env_cfg, config = _map_environment(payload, args.device)
        scenario_id = str(payload["id"])
        method = str(payload["method"])
        overlays = _add_p7_route_overlay(env_cfg, payload)
        views = _p7_views(payload)
        physical_context: dict[str, Any] = {
            "capture_stage": "declared_navigation_context",
            "physics": payload["physics"],
        }
    elif args.phase == "p6":
        config = _p6_physical_config(
            payload,
            dict(payload["post_physics"]),
            (int(args.seed),),
        )
        env_cfg = _configure_environment(config, args.device)
        scenario_id = str(payload["id"])
        method = "full"
        views = _VIEWS["p6"]
        physical_context = {
            "capture_stage": "registered_post_shift_dynamic_response",
            "pre_physics": payload["pre_physics"],
            "post_physics": payload["post_physics"],
            "pre_distortion": payload["pre_distortion"],
            "post_distortion": payload["post_distortion"],
        }
    else:
        config = _p5_config(payload)
        env_cfg = _configure_environment(config, args.device)
        scenario_id = config.scenario_id
        method = "active"
        views = _VIEWS["p5"]
        physical_context = {
            "capture_stage": "registered_closed_loop_dynamic_response",
            "terrain": config.terrain,
            "static_friction": config.static_friction,
            "dynamic_friction": config.dynamic_friction,
            "payload_add_kg": config.payload_add_kg,
            "com_offset_x_m": config.com_offset_x_m,
            "distortion": config.distortion,
        }
    prefix = _artifact_prefix(args.phase)
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
        if args.phase in {"p5", "p6"}:
            captured, overlays, distortion_record = _capture_response_frames(
                env,
                actor,
                args.phase,
                prefix,
                payload,
                config,
                output_dir,
            )
        else:
            unwrapped = env.unwrapped
            command_term = unwrapped.command_manager.get_term("base_velocity")
            camera = unwrapped.scene["readme_camera"]
            environment_origin = unwrapped.scene.env_origins[0]

            with torch.no_grad():
                for _ in range(args.stabilization_steps):
                    command_term.vel_command_b[:] = 0.0
                    observation = unwrapped.observation_manager.compute()["policy"]
                    actions = actor(torch.clamp(observation, -100.0, 100.0))
                    env.step(torch.clamp(actions, -100.0, 100.0))

                for name, view in views.items():
                    eyes = torch.tensor(
                        [view["eye"]],
                        dtype=torch.float32,
                        device=unwrapped.device,
                    ) + environment_origin
                    targets = torch.tensor(
                        [view["target"]],
                        dtype=torch.float32,
                        device=unwrapped.device,
                    ) + environment_origin
                    camera.set_world_poses_from_view(eyes, targets)
                    for _ in range(4):
                        command_term.vel_command_b[:] = 0.0
                        observation = unwrapped.observation_manager.compute()["policy"]
                        actions = actor(torch.clamp(observation, -100.0, 100.0))
                        env.step(torch.clamp(actions, -100.0, 100.0))

                    rgb = camera.data.output["rgb"].clone()
                    if not torch.is_floating_point(rgb):
                        rgb = rgb.to(dtype=torch.float32) / 255.0
                    image_path = output_dir / f"{prefix}_{name}.png"
                    save_images_to_file(rgb, str(image_path))
                    captured.append(
                        {
                            "path": image_path.name,
                            "sha256": _sha256(image_path),
                            "resolution": [1280, 720],
                            "camera_pose_frame": "environment_local",
                            "eye_xyz_m": list(view["eye"]),
                            "target_xyz_m": list(view["target"]),
                            "description": view["description"],
                        }
                    )
    finally:
        env.close()

    manifest = json.loads(runtime_manifest.read_text(encoding="utf-8"))
    checkpoint_key = _checkpoint_key(payload, config)
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
            "key": checkpoint_key,
            "path": str(args.checkpoint),
            "sha256": _sha256(checkpoint),
            "registered_sha256": manifest["checkpoints"][checkpoint_key]["sha256"],
        },
        "physical_context": physical_context,
        "dynamic_response_distortion": distortion_record,
        "capture_only_visualization_overlays": overlays,
        "stabilization": {
            "steps": args.stabilization_steps,
            "command": [0.0, 0.0, 0.0],
            "policy": f"registered official Go2 {checkpoint_key} checkpoint",
        },
        "frames": captured,
        "interpretation": (
            "These RGB frames document the frozen scene and simulator assets. "
            "They do not replace or augment the registered multi-seed statistics."
        ),
    }
    if provenance["checkpoint"]["sha256"] != provenance["checkpoint"]["registered_sha256"]:
        raise RuntimeError("checkpoint SHA-256 does not match the frozen manifest")
    (output_dir / f"{prefix}_capture.json").write_text(
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
