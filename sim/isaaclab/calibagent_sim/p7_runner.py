"""Vectorized P7 fixed-planner navigation benchmark executed in Isaac Lab."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import gymnasium as gym
import isaaclab.sim as sim_utils
import numpy as np
import torch
from isaaclab.assets import AssetBaseCfg

from calibagent.core.compensation import ConstrainedInverseCompensator
from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.models.features import BasisTransformer
from calibagent.core.planning.candidates import CandidatePool, CommandSpace
from calibagent.core.planning.ivr import IntegratedVariancePlanner
from calibagent.core.planning.task import TaskDistribution
from calibagent.core.safety import HardSafetyFilter, SafetyEnvelope
from calibagent.interfaces.types import PriorState, RobotState, VelocityCommand
from calibagent.sim import CommandDistortion, make_distortion_parameters
from calibagent_sim.policy import load_actor
from calibagent_sim.runner import (
    ScenarioConfig,
    _configure_environment,
    _execute_batch_trial,
    _robot_state,
    _state_arrays,
    _write_csv,
)

_METHODS = {"B0_raw", "B1_dense", "B8_full"}


def _write_csv_gzip(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty P7 trace: {path}")
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _physical_config(payload: dict[str, Any]) -> ScenarioConfig:
    calibration = dict(payload["calibration"])
    safety = dict(payload["safety"])
    physics = dict(payload["physics"])
    return ScenarioConfig(
        scenario_id=str(payload["id"]),
        tier="P7",
        task=str(payload["task"]),
        distortion=str(payload["distortion"]),
        terrain="navigation_map",
        static_friction=float(physics["static_friction"]),
        dynamic_friction=float(physics["dynamic_friction"]),
        payload_add_kg=float(physics["payload_add_kg"]),
        com_offset_x_m=float(physics["com_offset_x_m"]),
        seeds=tuple(int(item) for item in payload["seeds"]),
        calibration_trials=(
            int(calibration["dense_trials"])
            if payload["method"] == "B1_dense"
            else int(calibration["active_trials"])
            if payload["method"] == "B8_full"
            else 0
        ),
        warmup_s=float(calibration["warmup_s"]),
        ramp_in_s=float(calibration["ramp_in_s"]),
        settle_s=float(calibration["settle_s"]),
        measure_s=float(calibration["measure_s"]),
        ramp_out_s=float(calibration["ramp_out_s"]),
        sample_rate_hz=float(payload["navigation"]["sample_rate_hz"]),
        simulator_seed=int(payload["simulator_seed"]),
        safety_min_base_height_m=float(safety["min_base_height_m"]),
        safety_max_base_height_m=float(safety["max_base_height_m"]),
        safety_max_coupled_load=float(safety["max_coupled_load"]),
        model_prior_scale=float(calibration["model_prior_scale"]),
    )


def _map_environment(payload: dict[str, Any], device: str) -> tuple[Any, ScenarioConfig]:
    config = _physical_config(payload)
    env_cfg = _configure_environment(config, device)
    env_cfg.sim.physx.enable_enhanced_determinism = bool(payload["enhanced_determinism"])
    env_cfg.scene.env_spacing = float(payload["navigation"]["environment_spacing_m"])
    for index, obstacle in enumerate(payload["obstacles"]):
        size = tuple(float(item) for item in obstacle["size"])
        center = tuple(float(item) for item in obstacle["center"])
        asset = AssetBaseCfg(
            prim_path=f"{{ENV_REGEX_NS}}/P7Obstacle{index}",
            spawn=sim_utils.CuboidCfg(
                size=size,
                collision_props=sim_utils.CollisionPropertiesCfg(),
                rigid_props=sim_utils.RigidBodyPropertiesCfg(kinematic_enabled=True),
                physics_material=sim_utils.RigidBodyMaterialCfg(
                    static_friction=0.9,
                    dynamic_friction=0.8,
                ),
                visual_material=sim_utils.PreviewSurfaceCfg(
                    diffuse_color=(0.75, 0.18, 0.12),
                ),
                activate_contact_sensors=True,
            ),
            init_state=AssetBaseCfg.InitialStateCfg(
                pos=(center[0], center[1], size[2] / 2.0),
            ),
        )
        setattr(env_cfg.scene, f"p7_obstacle_{index}", asset)
    return env_cfg, config


def _model_components(
    config: ScenarioConfig,
    payload: dict[str, Any],
) -> tuple[
    list[BayesianBasisModel],
    list[IntegratedVariancePlanner],
    CandidatePool,
    HardSafetyFilter,
    TaskDistribution,
]:
    calibration = dict(payload["calibration"])
    command_space = CommandSpace(
        np.asarray(calibration["command_bounds"], dtype=np.float64),
        max_linear_norm=float(calibration["maximum_linear_norm"]),
    )
    reference = CandidatePool.generate(command_space, count=512, seed=77131)
    transformer = BasisTransformer(str(payload["calibration"]["feature_set"])).fit(
        reference.commands
    )
    basis = transformer.transform(reference.commands)
    prior_targets = float(calibration["model_prior_gain"]) * reference.commands
    command_prior = np.linalg.lstsq(basis, prior_targets, rcond=None)[0].T
    models = [
        BayesianBasisModel(
            transformer,
            prior_scale=config.model_prior_scale,
            noise_variance=[0.0025, 0.0025, 0.0050],
        )
        for _ in config.seeds
    ]
    for model in models:
        model.initialize(PriorState(mean=command_prior))
    envelope = SafetyEnvelope(
        min_base_height=config.safety_min_base_height_m,
        max_base_height=config.safety_max_base_height_m,
        max_coupled_load=config.safety_max_coupled_load,
    )
    linear_load = np.linalg.norm(reference.commands[:, :2], axis=1) / envelope.max_linear_norm
    angular_scale = max(abs(bound) for bound in envelope.command_bounds[2])
    coupled = linear_load + np.abs(reference.commands[:, 2]) / angular_scale
    safe_pool = CandidatePool(
        reference.commands[coupled <= envelope.max_coupled_load],
        command_space,
    )
    task_commands = np.asarray(payload["navigation"]["task_commands"], dtype=np.float64)
    active_pool = CandidatePool(task_commands, command_space)
    planners = [
        IntegratedVariancePlanner(active_pool, duplicate_distance=0.02) for _ in config.seeds
    ]
    return (
        models,
        planners,
        safe_pool,
        HardSafetyFilter(envelope),
        TaskDistribution.uniform(task_commands),
    )


def _run_calibration(
    env: Any,
    actor: torch.nn.Module,
    payload: dict[str, Any],
    config: ScenarioConfig,
    models: list[BayesianBasisModel],
    planners: list[IntegratedVariancePlanner],
    pool: CandidatePool,
    safety_filter: HardSafetyFilter,
    task: TaskDistribution,
) -> tuple[list[dict[str, Any]], int, int, list[bool]]:
    method = str(payload["method"])
    if method == "B0_raw":
        return (
            [
                {
                    "map": payload["id"],
                    "seed": seed,
                    "method": method,
                    "trial": 0,
                    "source": "skipped_raw_control",
                    "cmd_vx": 0.0,
                    "cmd_vy": 0.0,
                    "cmd_wz": 0.0,
                    "measured_vx": 0.0,
                    "measured_vy": 0.0,
                    "measured_wz": 0.0,
                    "valid": True,
                    "safety_events": "",
                }
                for seed in config.seeds
            ],
            0,
            0,
            [],
        )
    calibration = dict(payload["calibration"])
    dense_pool = CandidatePool.generate(
        pool.command_space,
        count=int(calibration["dense_trials"]),
        seed=int(calibration["dense_design_seed"]),
    )
    distortion = CommandDistortion(
        make_distortion_parameters(str(payload["distortion"]), config.seeds),
        seed=config.simulator_seed + 91,
    )
    histories: list[list[np.ndarray]] = [[] for _ in config.seeds]
    rows: list[dict[str, Any]] = []
    safety_events = 0
    serious_events = 0
    valid_flags: list[bool] = []
    neutral = RobotState(
        0.0,
        (0.0, 0.0),
        0.0,
        0.0,
        0.0,
        0.40,
        (0.0, 0.0, 0.0),
    )
    zero_history = [VelocityCommand(0.0, 0.0, 0.0, 0.1)]
    bounds = pool.command_space.bounds
    calibration_seed = np.asarray(
        [
            [bounds[0, 0], 0.0, 0.0],
            [bounds[0, 1], 0.0, 0.0],
            [0.0, bounds[1, 0], 0.0],
            [0.0, bounds[1, 1], 0.0],
            [0.0, 0.0, bounds[2, 0]],
            [0.0, 0.0, bounds[2, 1]],
        ],
        dtype=np.float64,
    )
    for trial in range(config.calibration_trials):
        desired = np.zeros((len(config.seeds), 3), dtype=np.float64)
        sources: list[str] = []
        for env_index in range(len(config.seeds)):
            if method == "B1_dense":
                desired[env_index] = dense_pool.commands[trial]
                sources.append("dense_grid")
            elif trial < len(calibration_seed):
                desired[env_index] = calibration_seed[trial]
                sources.append("seed_design")
            else:
                candidates = planners[env_index].propose(
                    models[env_index],
                    task,
                    histories[env_index],
                    k=min(12, len(pool.commands)),
                )
                decision = safety_filter.select_first_safe(
                    candidates,
                    neutral,
                    zero_history,
                )
                if not decision.accepted or decision.command is None:
                    raise RuntimeError(
                        f"no safe P7 calibration candidate for seed {config.seeds[env_index]}"
                    )
                desired[env_index] = decision.command.as_array()
                sources.append("active_ivr")
        observations, _ = _execute_batch_trial(
            env,
            actor,
            desired,
            distortion,
            config,
            trial + 1,
            "p7_calibration",
            [],
        )
        for env_index, observation in enumerate(observations):
            valid_flags.append(observation.valid)
            if observation.valid:
                models[env_index].update(observation)
            histories[env_index].append(desired[env_index].copy())
            safety_events += int(bool(observation.safety_events))
            serious_events += int("SIM_TERMINATION" in "|".join(observation.safety_events))
            rows.append(
                {
                    "map": payload["id"],
                    "seed": config.seeds[env_index],
                    "method": method,
                    "trial": trial + 1,
                    "source": sources[env_index],
                    "cmd_vx": desired[env_index, 0],
                    "cmd_vy": desired[env_index, 1],
                    "cmd_wz": desired[env_index, 2],
                    "measured_vx": observation.mean_velocity[0],
                    "measured_vy": observation.mean_velocity[1],
                    "measured_wz": observation.mean_velocity[2],
                    "valid": observation.valid,
                    "safety_events": "|".join(observation.safety_events),
                }
            )
    return rows, safety_events, serious_events, valid_flags


def _planner_command(
    position: np.ndarray,
    yaw: float,
    target: np.ndarray,
    navigation: dict[str, Any],
) -> np.ndarray:
    delta = target - position
    cosine, sine = np.cos(yaw), np.sin(yaw)
    body = np.asarray(
        [
            cosine * delta[0] + sine * delta[1],
            -sine * delta[0] + cosine * delta[1],
        ],
        dtype=np.float64,
    )
    distance = float(np.linalg.norm(body))
    if distance <= 1e-12:
        return np.zeros(3, dtype=np.float64)
    speed = min(
        float(navigation["cruise_speed_mps"]),
        float(navigation["position_gain"]) * distance,
    )
    direction = body / distance
    heading_error = float(np.arctan2(body[1], body[0]))
    return np.asarray(
        [
            speed * direction[0],
            float(
                np.clip(
                    speed * direction[1],
                    -float(navigation["maximum_lateral_speed_mps"]),
                    float(navigation["maximum_lateral_speed_mps"]),
                )
            ),
            float(
                np.clip(
                    float(navigation["heading_gain"]) * heading_error,
                    -float(navigation["maximum_yaw_rate_rps"]),
                    float(navigation["maximum_yaw_rate_rps"]),
                )
            ),
        ],
        dtype=np.float64,
    )


def _slew_limit(
    proposed: np.ndarray,
    previous: np.ndarray,
    navigation: dict[str, Any],
    control_dt: float,
) -> np.ndarray:
    output = proposed.copy()
    delta = output[:2] - previous[:2]
    limit = float(navigation["maximum_linear_accel_mps2"]) * control_dt
    norm = float(np.linalg.norm(delta))
    if norm > limit:
        output[:2] = previous[:2] + delta * (limit / norm)
    angular_limit = float(navigation["maximum_angular_accel_rps2"]) * control_dt
    output[2] = previous[2] + float(np.clip(output[2] - previous[2], -angular_limit, angular_limit))
    return output


def _near_obstacle(
    position: np.ndarray,
    obstacles: list[dict[str, Any]],
    footprint_radius: float,
) -> bool:
    for obstacle in obstacles:
        center = np.asarray(obstacle["center"], dtype=np.float64)
        size = np.asarray(obstacle["size"], dtype=np.float64)
        if (
            abs(float(position[0] - center[0])) <= size[0] / 2.0 + footprint_radius
            and abs(float(position[1] - center[1])) <= size[1] / 2.0 + footprint_radius
        ):
            return True
    return False


def _planner_hash(payload: dict[str, Any]) -> str:
    frozen = {
        "navigation": payload["navigation"],
        "waypoints": payload["waypoints"],
        "obstacles": payload["obstacles"],
    }
    encoded = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _run_navigation(
    env: Any,
    actor: torch.nn.Module,
    payload: dict[str, Any],
    config: ScenarioConfig,
    models: list[BayesianBasisModel],
    pool: CandidatePool,
    safety_filter: HardSafetyFilter,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, list[bool]]:
    method = str(payload["method"])
    navigation = dict(payload["navigation"])
    waypoints = np.asarray(payload["waypoints"], dtype=np.float64)
    obstacles = list(payload["obstacles"])
    sample_rate = int(navigation["sample_rate_hz"])
    planner_rate = int(navigation["planner_rate_hz"])
    decimation = sample_rate // planner_rate
    timeout = float(navigation["timeout_s"])
    max_steps = round(timeout * sample_rate)
    warmup_steps = round(float(navigation["initial_stabilization_s"]) * sample_rate)
    dt = 1.0 / sample_rate
    control_dt = 1.0 / planner_rate
    footprint = float(navigation["collision_footprint_radius_m"])
    waypoint_radius = float(navigation["waypoint_radius_m"])
    goal_radius = float(navigation["goal_radius_m"])
    recovery = dict(navigation["stall_recovery"])
    recovery_detection_ticks = max(1, round(float(recovery["detection_s"]) * planner_rate))
    recovery_zero_ticks = max(1, round(float(recovery["zero_command_s"]) * planner_rate))
    emergency_recovery_zero_ticks = max(
        1, round(float(recovery["emergency_zero_command_s"]) * planner_rate)
    )
    maximum_recovery_attempts = int(recovery["maximum_attempts"])
    maximum_emergency_recovery_attempts = int(recovery["maximum_emergency_attempts"])
    unwrapped = env.unwrapped
    env.reset()
    command_term = unwrapped.command_manager.get_term("base_velocity")
    robot = unwrapped.scene["robot"]
    origins = unwrapped.scene.env_origins
    device = str(unwrapped.device)
    distortion = CommandDistortion(
        make_distortion_parameters(str(payload["distortion"]), config.seeds),
        seed=config.simulator_seed + 191,
    )
    distortion.reset()
    compensators = [
        ConstrainedInverseCompensator(
            pool,
            safety_filter,
            regularization=float(navigation["inverse_regularization"]),
            risk_weight=float(navigation["inverse_risk_weight"]),
            undertracking_confidence_weights=np.asarray(
                navigation["inverse_undertracking_confidence_weights"],
                dtype=np.float64,
            ),
            duration_s=control_dt,
            enforce_axis_signs=True,
        )
        for _ in config.seeds
    ]
    count = len(config.seeds)
    waypoint_index = np.zeros(count, dtype=np.int64)
    success = np.zeros(count, dtype=bool)
    collision = np.zeros(count, dtype=bool)
    finished = np.zeros(count, dtype=bool)
    serious = np.zeros(count, dtype=bool)
    arrival_time = np.full(count, timeout, dtype=np.float64)
    arrival_position = np.full((count, 2), np.nan, dtype=np.float64)
    path_length = np.zeros(count, dtype=np.float64)
    desired = np.zeros((count, 3), dtype=np.float64)
    compensated = np.zeros((count, 3), dtype=np.float64)
    effective = np.zeros((count, 3), dtype=np.float64)
    inverse_objective = np.full(count, np.nan, dtype=np.float64)
    stall_ticks = np.zeros(count, dtype=np.int64)
    recovery_ticks = np.zeros(count, dtype=np.int64)
    recovery_attempts = np.zeros(count, dtype=np.int64)
    regular_recovery_attempts = np.zeros(count, dtype=np.int64)
    emergency_recovery_attempts = np.zeros(count, dtype=np.int64)
    recovery_active = np.zeros(count, dtype=bool)
    emergency_recovery_active = np.zeros(count, dtype=bool)
    trace_rows: list[dict[str, Any]] = []
    valid_flags: list[bool] = []
    arrays = _state_arrays(robot, origins)
    previous_position = arrays[0][:, :2].copy()
    safety_event_count = 0

    with torch.no_grad():
        for _warmup in range(warmup_steps):
            command_term.vel_command_b[:] = 0.0
            observation = unwrapped.observation_manager.compute()["policy"]
            actions = actor(torch.clamp(observation, -100.0, 100.0))
            env.step(torch.clamp(actions, -100.0, 100.0))
        arrays = _state_arrays(robot, origins)
        previous_position = arrays[0][:, :2].copy()
        for step in range(max_steps):
            if step % decimation == 0:
                position, control_velocity, _, _, _, yaw = arrays
                for env_index in range(count):
                    if finished[env_index]:
                        desired[env_index] = 0.0
                        compensated[env_index] = 0.0
                        continue
                    while waypoint_index[env_index] < len(waypoints) - 1:
                        distance = np.linalg.norm(
                            waypoints[waypoint_index[env_index]] - position[env_index, :2]
                        )
                        if distance > waypoint_radius:
                            break
                        waypoint_index[env_index] += 1
                    goal_distance = np.linalg.norm(waypoints[-1] - position[env_index, :2])
                    if (
                        waypoint_index[env_index] == len(waypoints) - 1
                        and goal_distance <= goal_radius
                    ):
                        success[env_index] = True
                        finished[env_index] = True
                        arrival_time[env_index] = step * dt
                        arrival_position[env_index] = position[env_index, :2]
                        desired[env_index] = 0.0
                        compensated[env_index] = 0.0
                        continue
                    target = waypoints[waypoint_index[env_index]]
                    desired[env_index] = _planner_command(
                        position[env_index, :2],
                        float(yaw[env_index]),
                        target,
                        navigation,
                    )
                    actual_speed = float(np.linalg.norm(control_velocity[env_index, :2]))
                    stalled = bool(
                        np.linalg.norm(desired[env_index, :2])
                        >= float(recovery["minimum_desired_speed_mps"])
                        and actual_speed <= float(recovery["maximum_actual_speed_mps"])
                        and position[env_index, 2] <= float(recovery["maximum_base_height_m"])
                    )
                    stall_ticks[env_index] = stall_ticks[env_index] + 1 if stalled else 0
                    emergency_trigger = bool(
                        position[env_index, 2] <= float(recovery["emergency_base_height_m"])
                    )
                    regular_trigger = stall_ticks[env_index] >= recovery_detection_ticks
                    use_emergency_recovery = bool(
                        emergency_trigger
                        and emergency_recovery_attempts[env_index]
                        < maximum_emergency_recovery_attempts
                    )
                    use_regular_recovery = bool(
                        not use_emergency_recovery
                        and regular_trigger
                        and regular_recovery_attempts[env_index] < maximum_recovery_attempts
                    )
                    if recovery_ticks[env_index] == 0 and (
                        use_emergency_recovery or use_regular_recovery
                    ):
                        recovery_ticks[env_index] = (
                            emergency_recovery_zero_ticks
                            if use_emergency_recovery
                            else recovery_zero_ticks
                        )
                        recovery_attempts[env_index] += 1
                        regular_recovery_attempts[env_index] += int(use_regular_recovery)
                        emergency_recovery_active[env_index] = use_emergency_recovery
                        emergency_recovery_attempts[env_index] += int(use_emergency_recovery)
                        stall_ticks[env_index] = 0
                    recovery_active[env_index] = recovery_ticks[env_index] > 0
                    if recovery_active[env_index]:
                        proposed = np.zeros(3, dtype=np.float64)
                        inverse_objective[env_index] = np.nan
                        recovery_ticks[env_index] -= 1
                        if recovery_ticks[env_index] == 0:
                            emergency_recovery_active[env_index] = False
                    elif method == "B0_raw":
                        proposed = desired[env_index]
                        inverse_objective[env_index] = np.nan
                    else:
                        solution = compensators[env_index].solve(
                            desired[env_index],
                            models[env_index],
                            _robot_state(env_index, step * dt, arrays),
                            compensated[env_index],
                        )
                        proposed = solution.command
                        inverse_objective[env_index] = solution.objective
                    compensated[env_index] = (
                        np.zeros(3, dtype=np.float64)
                        if recovery_active[env_index]
                        else _slew_limit(
                            proposed,
                            compensated[env_index],
                            navigation,
                            control_dt,
                        )
                    )
            effective = distortion.step(compensated, dt)
            effective[finished] = 0.0
            command_term.vel_command_b[:] = torch.as_tensor(
                effective,
                dtype=torch.float32,
                device=device,
            )
            observation = unwrapped.observation_manager.compute()["policy"]
            actions = actor(torch.clamp(observation, -100.0, 100.0))
            _, _, terminated, truncated, _ = env.step(torch.clamp(actions, -100.0, 100.0))
            arrays = _state_arrays(robot, origins)
            position, velocity, angular, roll, pitch, yaw = arrays
            done = (terminated | truncated).detach().cpu().numpy()
            path_length += np.linalg.norm(position[:, :2] - previous_position, axis=1) * (~finished)
            previous_position = position[:, :2].copy()
            for env_index in range(count):
                was_active = not finished[env_index]
                if was_active:
                    state = _robot_state(env_index, step * dt, arrays)
                    safety_decision = safety_filter.monitor(state)
                    valid_flags.append(safety_decision.accepted)
                    hit = _near_obstacle(
                        position[env_index, :2],
                        obstacles,
                        footprint,
                    )
                    if hit:
                        collision[env_index] = True
                        finished[env_index] = True
                    elif bool(done[env_index]):
                        serious[env_index] = True
                        finished[env_index] = True
                        safety_event_count += 1
                    elif not safety_decision.accepted:
                        # Match the P4/P6 severity contract: a hard-envelope
                        # trigger that zeros the next command is a timely abort,
                        # while simulator termination/fall is a serious event.
                        finished[env_index] = True
                        safety_event_count += 1
                trace_rows.append(
                    {
                        "map": payload["id"],
                        "seed": config.seeds[env_index],
                        "method": method,
                        "sample": step,
                        "timestamp_s": step * dt,
                        "waypoint_index": int(waypoint_index[env_index]),
                        "target_x": waypoints[waypoint_index[env_index], 0],
                        "target_y": waypoints[waypoint_index[env_index], 1],
                        "desired_vx": desired[env_index, 0],
                        "desired_vy": desired[env_index, 1],
                        "desired_wz": desired[env_index, 2],
                        "compensated_vx": compensated[env_index, 0],
                        "compensated_vy": compensated[env_index, 1],
                        "compensated_wz": compensated[env_index, 2],
                        "effective_vx": effective[env_index, 0],
                        "effective_vy": effective[env_index, 1],
                        "effective_wz": effective[env_index, 2],
                        "inverse_objective": inverse_objective[env_index],
                        "stall_recovery_active": bool(recovery_active[env_index]),
                        "stall_recovery_attempts": int(recovery_attempts[env_index]),
                        "regular_recovery_attempts": int(regular_recovery_attempts[env_index]),
                        "emergency_recovery_active": bool(emergency_recovery_active[env_index]),
                        "emergency_recovery_attempts": int(emergency_recovery_attempts[env_index]),
                        "pose_x": position[env_index, 0],
                        "pose_y": position[env_index, 1],
                        "pose_yaw": yaw[env_index],
                        "base_height": position[env_index, 2],
                        "roll": roll[env_index],
                        "pitch": pitch[env_index],
                        "velocity_vx": velocity[env_index, 0],
                        "velocity_vy": velocity[env_index, 1],
                        "velocity_wz": angular[env_index, 2],
                        "success": bool(success[env_index]),
                        "collision": bool(collision[env_index]),
                        "serious_safety_event": bool(serious[env_index]),
                        "finished": bool(finished[env_index]),
                    }
                )
            if bool(np.all(finished)):
                break
    episode_rows = [
        {
            "map": payload["id"],
            "seed": seed,
            "method": method,
            "success": bool(success[index]),
            "collision": bool(collision[index]),
            "arrival_time_s": (float(arrival_time[index]) if success[index] else float("nan")),
            "completion_time_s": float(arrival_time[index]),
            "path_length_m": float(path_length[index]),
            "arrival_x": float(arrival_position[index, 0]),
            "arrival_y": float(arrival_position[index, 1]),
            "goal_distance_at_arrival_m": float(
                np.linalg.norm(waypoints[-1] - arrival_position[index])
            ),
            "final_x": float(arrays[0][index, 0]),
            "final_y": float(arrays[0][index, 1]),
            "goal_distance_m": float(np.linalg.norm(waypoints[-1] - arrays[0][index, :2])),
            "stall_recovery_attempts": int(recovery_attempts[index]),
            "regular_recovery_attempts": int(regular_recovery_attempts[index]),
            "emergency_recovery_attempts": int(emergency_recovery_attempts[index]),
            "serious_safety_event": bool(serious[index]),
        }
        for index, seed in enumerate(config.seeds)
    ]
    return episode_rows, trace_rows, safety_event_count, valid_flags


def run_p7_navigation(
    payload: dict[str, Any],
    checkpoint: Path,
    output: Path,
    device: str,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    method = str(payload["method"])
    if method not in _METHODS:
        raise ValueError(f"unsupported P7 method: {method}")
    env_cfg, config = _map_environment(payload, device)
    env = gym.make(config.task, cfg=env_cfg)
    actor = load_actor(checkpoint, str(env.unwrapped.device))
    models, planners, pool, safety_filter, task = _model_components(config, payload)
    try:
        (
            calibration_rows,
            calibration_safety_events,
            calibration_serious_events,
            calibration_valid,
        ) = _run_calibration(
            env,
            actor,
            payload,
            config,
            models,
            planners,
            pool,
            safety_filter,
            task,
        )
        episode_rows, trace_rows, nav_safety_events, nav_valid = _run_navigation(
            env,
            actor,
            payload,
            config,
            models,
            pool,
            safety_filter,
        )
    finally:
        env.close()
    serious_events = calibration_serious_events + sum(
        int(row["serious_safety_event"]) for row in episode_rows
    )
    safety_events = calibration_safety_events + nav_safety_events
    valid = calibration_valid + nav_valid
    success = np.asarray([bool(row["success"]) for row in episode_rows])
    collision = np.asarray([bool(row["collision"]) for row in episode_rows])
    completion = np.asarray(
        [float(row["completion_time_s"]) for row in episode_rows],
        dtype=np.float64,
    )
    planner_hash = _planner_hash(payload)
    summary = {
        "schema_version": "1.0",
        "map": payload["id"],
        "method": method,
        "num_seeds": len(config.seeds),
        "calibration_trials": config.calibration_trials,
        "planner_config_sha256": planner_hash,
        "success_rate": float(np.mean(success)),
        "collision_rate": float(np.mean(collision)),
        "mean_completion_time_s": float(np.mean(completion)),
        "median_completion_time_s": float(np.median(completion)),
        "stall_recovery_attempts": int(
            sum(int(row["stall_recovery_attempts"]) for row in episode_rows)
        ),
        "regular_recovery_attempts": int(
            sum(int(row["regular_recovery_attempts"]) for row in episode_rows)
        ),
        "emergency_recovery_attempts": int(
            sum(int(row["emergency_recovery_attempts"]) for row in episode_rows)
        ),
        "valid_observation_ratio": float(np.mean(valid)) if valid else 1.0,
        "safety_events": int(safety_events),
        "maximum_abort_latency_s": (
            1.0 / float(payload["navigation"]["sample_rate_hz"]) if safety_events else 0.0
        ),
        "serious_safety_events": int(serious_events),
        "finite": bool(np.all(np.isfinite(completion))),
    }
    _write_csv(output / "calibration_metrics.csv", calibration_rows)
    _write_csv(output / "episode_metrics.csv", episode_rows)
    _write_csv_gzip(output / "nav_trace.csv.gz", trace_rows)
    (output / "map_geometry.json").write_text(
        json.dumps(
            {
                "map": payload["id"],
                "waypoints": payload["waypoints"],
                "obstacles": payload["obstacles"],
                "collision_footprint_radius_m": payload["navigation"][
                    "collision_footprint_radius_m"
                ],
                "planner_config_sha256": planner_hash,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (output / "scenario_config.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary
