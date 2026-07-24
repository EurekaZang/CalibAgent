"""Vectorized Go2 calibration runner executed inside an Isaac Lab app."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import gymnasium as gym
import isaaclab_tasks  # noqa: F401
import numpy as np
import torch
from isaaclab.envs import mdp
from isaaclab.managers import EventTermCfg as EventTerm
from isaaclab.managers import SceneEntityCfg
from isaaclab.utils import math as math_utils
from isaaclab_tasks.utils import parse_env_cfg

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.models.features import BasisTransformer
from calibagent.core.planning.candidates import CandidatePool, CommandSpace
from calibagent.core.planning.ivr import IntegratedVariancePlanner
from calibagent.core.planning.task import TaskDistribution
from calibagent.core.safety import HardSafetyFilter, SafetyEnvelope
from calibagent.interfaces.types import (
    PriorState,
    RawTrialData,
    RobotContext,
    RobotState,
    VelocityCommand,
)
from calibagent.measurement.pipeline import MeasurementPipeline
from calibagent.sim import CommandDistortion, make_distortion_parameters
from calibagent_sim.policy import load_actor


@dataclass(frozen=True)
class ScenarioConfig:
    scenario_id: str
    tier: str
    task: str
    distortion: str
    terrain: str
    static_friction: float
    dynamic_friction: float
    payload_add_kg: float
    com_offset_x_m: float
    seeds: tuple[int, ...]
    calibration_trials: int
    warmup_s: float
    ramp_in_s: float
    settle_s: float
    measure_s: float
    ramp_out_s: float
    sample_rate_hz: float
    simulator_seed: int
    safety_min_base_height_m: float
    safety_max_base_height_m: float
    safety_max_coupled_load: float
    model_prior_scale: float


_CALIBRATION_SEED = np.asarray(
    [
        [-0.40, 0.00, 0.00],
        [0.40, 0.00, 0.00],
        [0.00, -0.25, 0.00],
        [0.00, 0.25, 0.00],
        [0.00, 0.00, -0.70],
        [0.00, 0.00, 0.70],
    ],
    dtype=np.float64,
)
_VALIDATION_COMMANDS = np.asarray(
    [
        [-0.30, 0.00, -0.35],
        [-0.30, 0.00, 0.35],
        [0.20, -0.18, -0.30],
        [0.20, -0.18, 0.30],
        [0.20, 0.18, -0.30],
        [0.20, 0.18, 0.30],
        [0.35, 0.00, -0.50],
        [0.35, 0.00, 0.50],
    ],
    dtype=np.float64,
)
_BOUNDS = np.asarray(
    [[-0.40, 0.40], [-0.25, 0.25], [-0.70, 0.70]],
    dtype=np.float64,
)


def _configure_environment(config: ScenarioConfig, device: str) -> Any:
    env_cfg = parse_env_cfg(
        config.task,
        device=device,
        num_envs=len(config.seeds),
    )
    env_cfg.seed = config.simulator_seed
    env_cfg.episode_length_s = 1000.0
    env_cfg.observations.policy.enable_corruption = False
    command = env_cfg.commands.base_velocity
    command.heading_command = False
    command.rel_heading_envs = 0.0
    command.rel_standing_envs = 0.0
    command.resampling_time_range = (1000.0, 1000.0)
    command.debug_vis = False
    if getattr(env_cfg.scene, "terrain", None) is not None:
        env_cfg.scene.terrain.debug_vis = False
    if getattr(env_cfg, "curriculum", None) is not None and hasattr(
        env_cfg.curriculum, "terrain_levels"
    ):
        env_cfg.curriculum.terrain_levels = None
    events = env_cfg.events
    events.physics_material.params["static_friction_range"] = (
        config.static_friction,
        config.static_friction,
    )
    events.physics_material.params["dynamic_friction_range"] = (
        config.dynamic_friction,
        config.dynamic_friction,
    )
    events.add_base_mass.params["mass_distribution_params"] = (
        config.payload_add_kg,
        config.payload_add_kg,
    )
    if config.com_offset_x_m != 0.0:
        # Go2 disables the parent locomotion COM event in its task config.
        # Restore a deterministic startup term so the declared Tier-B shift is
        # actually applied and appears in EventManager provenance.
        events.base_com = EventTerm(
            func=mdp.randomize_rigid_body_com,
            mode="startup",
            params={
                "asset_cfg": SceneEntityCfg("robot", body_names="base"),
                "com_range": {
                    "x": (config.com_offset_x_m, config.com_offset_x_m),
                    "y": (0.0, 0.0),
                    "z": (0.0, 0.0),
                },
            },
        )
    elif getattr(events, "base_com", None) is not None:
        events.base_com.params["com_range"] = {
            "x": (config.com_offset_x_m, config.com_offset_x_m),
            "y": (0.0, 0.0),
            "z": (0.0, 0.0),
        }
    events.base_external_force_torque = None
    events.push_robot = None
    events.reset_base.params["pose_range"] = {
        "x": (0.0, 0.0),
        "y": (0.0, 0.0),
        "yaw": (0.0, 0.0),
    }
    events.reset_base.params["velocity_range"] = {
        "x": (0.0, 0.0),
        "y": (0.0, 0.0),
        "z": (0.0, 0.0),
        "roll": (0.0, 0.0),
        "pitch": (0.0, 0.0),
        "yaw": (0.0, 0.0),
    }
    events.reset_robot_joints.params["position_range"] = (1.0, 1.0)
    return env_cfg


def _state_arrays(robot: Any, env_origins: torch.Tensor) -> tuple[np.ndarray, ...]:
    root_position = (robot.data.root_pos_w - env_origins).detach().cpu().numpy()
    root_velocity = robot.data.root_lin_vel_b.detach().cpu().numpy()
    root_angular = robot.data.root_ang_vel_b.detach().cpu().numpy()
    roll, pitch, yaw = math_utils.euler_xyz_from_quat(robot.data.root_quat_w)
    return (
        root_position,
        root_velocity,
        root_angular,
        roll.detach().cpu().numpy(),
        pitch.detach().cpu().numpy(),
        yaw.detach().cpu().numpy(),
    )


def _robot_state(
    index: int,
    timestamp: float,
    arrays: tuple[np.ndarray, ...],
) -> RobotState:
    position, velocity, angular, roll, pitch, yaw = arrays
    return RobotState(
        timestamp,
        (float(position[index, 0]), float(position[index, 1])),
        float(yaw[index]),
        float(roll[index]),
        float(pitch[index]),
        float(position[index, 2]),
        (
            float(velocity[index, 0]),
            float(velocity[index, 1]),
            float(angular[index, 2]),
        ),
    )


def _trial_profile(config: ScenarioConfig) -> tuple[np.ndarray, np.ndarray]:
    dt = 1.0 / config.sample_rate_hz
    counts = [
        max(1, round(config.warmup_s / dt)),
        max(1, round(config.ramp_in_s / dt)),
        max(1, round(config.settle_s / dt)),
        max(30, round(config.measure_s / dt)),
        max(1, round(config.ramp_out_s / dt)),
    ]
    warmup = np.zeros(counts[0])
    ramp_in = np.linspace(0.0, 1.0, counts[1], endpoint=True)
    settle = np.ones(counts[2])
    measure = np.ones(counts[3])
    ramp_out = np.linspace(1.0, 0.0, counts[4], endpoint=True)
    scales = np.concatenate([warmup, ramp_in, settle, measure, ramp_out])
    phases = np.concatenate(
        [
            np.full(counts[0], -1),
            np.full(counts[1], 0),
            np.full(counts[2], 1),
            np.full(counts[3], 2),
            np.full(counts[4], 3),
        ]
    )
    return scales, phases


def _execute_batch_trial(
    env: Any,
    actor: torch.nn.Module,
    desired: np.ndarray,
    distortion: CommandDistortion,
    config: ScenarioConfig,
    trial_index: int,
    phase_name: str,
    trace_rows: list[dict[str, Any]],
) -> tuple[list[Any], list[str]]:
    unwrapped = env.unwrapped
    observation, _ = env.reset()
    command_term = unwrapped.command_manager.get_term("base_velocity")
    robot = unwrapped.scene["robot"]
    origins = unwrapped.scene.env_origins
    device = str(unwrapped.device)
    dt = float(unwrapped.step_dt)
    scales, phases = _trial_profile(config)
    measurement_pipeline = MeasurementPipeline()
    safety = HardSafetyFilter(
        SafetyEnvelope(
            min_base_height=config.safety_min_base_height_m,
            max_base_height=config.safety_max_base_height_m,
            max_coupled_load=config.safety_max_coupled_load,
        )
    )
    distortion.reset()
    aborted = np.zeros(len(config.seeds), dtype=bool)
    abort_reason = ["" for _ in config.seeds]
    measurement_time: list[float] = []
    measurement_pose: list[np.ndarray] = []
    # Isaac Lab lazily caches mutable state tensors while observations are read.
    # ``inference_mode`` would mark those caches as inference tensors and make
    # the next environment reset fail on its required in-place update.
    with torch.no_grad():
        for step, (scale, phase) in enumerate(zip(scales, phases, strict=True)):
            commanded = desired * float(scale)
            effective = distortion.step(commanded, dt)
            effective[aborted] = 0.0
            command_term.vel_command_b[:] = torch.as_tensor(
                effective,
                dtype=torch.float32,
                device=device,
            )
            policy_observation = unwrapped.observation_manager.compute()["policy"]
            if policy_observation.shape[1] != actor[0].in_features:
                raise RuntimeError(
                    f"policy input mismatch: obs={policy_observation.shape[1]}, "
                    f"actor={actor[0].in_features}"
                )
            actions = actor(torch.clamp(policy_observation, -100.0, 100.0))
            observation, _, terminated, truncated, _ = env.step(
                torch.clamp(actions, -100.0, 100.0)
            )
            del observation
            arrays = _state_arrays(robot, origins)
            done = (terminated | truncated).detach().cpu().numpy()
            for env_index in range(len(config.seeds)):
                if aborted[env_index]:
                    continue
                decision = safety.monitor(
                    _robot_state(env_index, step * dt, arrays)
                )
                if done[env_index]:
                    aborted[env_index] = True
                    abort_reason[env_index] = "SIM_TERMINATION"
                elif not decision.accepted:
                    aborted[env_index] = True
                    abort_reason[env_index] = "|".join(decision.reason_codes)
            position, velocity, angular, roll, pitch, yaw = arrays
            for env_index, seed in enumerate(config.seeds):
                trace_rows.append(
                    {
                        "scenario": config.scenario_id,
                        "tier": config.tier,
                        "seed": seed,
                        "phase": phase_name,
                        "trial": trial_index,
                        "profile_phase": int(phase),
                        "sample": step,
                        "timestamp_s": step * dt,
                        "cmd_vx": desired[env_index, 0],
                        "cmd_vy": desired[env_index, 1],
                        "cmd_wz": desired[env_index, 2],
                        "effective_vx": effective[env_index, 0],
                        "effective_vy": effective[env_index, 1],
                        "effective_wz": effective[env_index, 2],
                        "pose_x": position[env_index, 0],
                        "pose_y": position[env_index, 1],
                        "pose_yaw": yaw[env_index],
                        "base_height": position[env_index, 2],
                        "roll": roll[env_index],
                        "pitch": pitch[env_index],
                        "velocity_vx": velocity[env_index, 0],
                        "velocity_vy": velocity[env_index, 1],
                        "velocity_wz": angular[env_index, 2],
                        "aborted": bool(aborted[env_index]),
                        "abort_reason": abort_reason[env_index],
                    }
                )
            if int(phase) == 2:
                measurement_time.append(len(measurement_time) * dt)
                measurement_pose.append(
                    np.column_stack([position[:, 0], position[:, 1], yaw])
                )
    pose = np.stack(measurement_pose, axis=0)
    timestamps = np.asarray(measurement_time, dtype=np.float64)
    observations: list[Any] = []
    for env_index, seed in enumerate(config.seeds):
        context = RobotContext(
            config.terrain,
            config.payload_add_kg,
            1.0,
            "official_go2_velocity_policy",
            f"{config.scenario_id}-seed-{seed}",
        )
        raw = RawTrialData(
            timestamps,
            np.tile(desired[env_index], (len(timestamps), 1)),
            pose[:, env_index, :],
            context,
            metadata={
                "backend": "isaaclab",
                "ground_truth": "root_pose",
                "tier": config.tier,
            },
            raw_ref=f"{config.scenario_id}/{phase_name}/{trial_index}/{seed}",
        )
        observation = measurement_pipeline.process(raw)
        if aborted[env_index]:
            observation.quality["valid"] = False
            observation.quality["reason_codes"] = abort_reason[env_index]
            observation.safety_events.append(abort_reason[env_index])
        observations.append(observation)
    return observations, abort_reason


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty artifact {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_scenario(
    config: ScenarioConfig,
    checkpoint: Path,
    output: Path,
    device: str,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    env_cfg = _configure_environment(config, device)
    env = gym.make(config.task, cfg=env_cfg)
    actor = load_actor(checkpoint, str(env.unwrapped.device))
    parameters = make_distortion_parameters(config.distortion, config.seeds)
    distortion = CommandDistortion(parameters, seed=config.simulator_seed + 91)

    command_space = CommandSpace(_BOUNDS, max_linear_norm=0.45)
    reference_pool = CandidatePool.generate(
        command_space,
        count=128,
        seed=55131,
    )
    planning_envelope = SafetyEnvelope(
        min_base_height=config.safety_min_base_height_m,
        max_base_height=config.safety_max_base_height_m,
        max_coupled_load=config.safety_max_coupled_load,
    )
    linear_load = (
        np.linalg.norm(reference_pool.commands[:, :2], axis=1)
        / planning_envelope.max_linear_norm
    )
    angular_scale = max(abs(bound) for bound in planning_envelope.command_bounds[2])
    coupled_load = (
        linear_load + np.abs(reference_pool.commands[:, 2]) / angular_scale
    )
    pool = CandidatePool(
        reference_pool.commands[
            coupled_load <= planning_envelope.max_coupled_load
        ],
        command_space,
    )
    transformer = BasisTransformer("m2_affine_cross_hinge").fit(
        reference_pool.commands
    )
    # A velocity controller is expected to be approximately identity before
    # calibration.  Project that structural prior into the frozen standardized
    # basis without using any simulator outcome; M2 then learns only deviations.
    basis_reference = transformer.transform(pool.commands)
    identity_prior = np.linalg.lstsq(
        basis_reference,
        pool.commands,
        rcond=None,
    )[0].T
    task = TaskDistribution.uniform(_VALIDATION_COMMANDS)
    models = [
        BayesianBasisModel(
            transformer,
            prior_scale=config.model_prior_scale,
            noise_variance=[0.0025, 0.0025, 0.0050],
        )
        for _ in config.seeds
    ]
    for model in models:
        model.initialize(PriorState(mean=identity_prior))
    planners = [
        IntegratedVariancePlanner(pool, duplicate_distance=0.02)
        for _ in config.seeds
    ]
    history: list[list[np.ndarray]] = [[] for _ in config.seeds]
    metric_rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    safe_filter = HardSafetyFilter(
        SafetyEnvelope(
            min_base_height=config.safety_min_base_height_m,
            max_base_height=config.safety_max_base_height_m,
            max_coupled_load=config.safety_max_coupled_load,
        )
    )
    zero_history = [VelocityCommand(0.0, 0.0, 0.0, 0.1)]
    try:
        for trial in range(config.calibration_trials):
            desired = np.zeros((len(config.seeds), 3), dtype=np.float64)
            candidate_sources: list[str] = []
            for env_index in range(len(config.seeds)):
                if trial < len(_CALIBRATION_SEED):
                    desired[env_index] = _CALIBRATION_SEED[trial]
                    candidate_sources.append("seed_design")
                else:
                    candidates = planners[env_index].propose(
                        models[env_index],
                        task,
                        history[env_index],
                        k=min(12, len(pool.commands)),
                    )
                    decision = safe_filter.select_first_safe(
                        candidates,
                        RobotState(
                            0.0,
                            (0.0, 0.0),
                            0.0,
                            0.0,
                            0.0,
                            0.40,
                            (0.0, 0.0, 0.0),
                        ),
                        zero_history,
                    )
                    if not decision.accepted or decision.command is None:
                        raise RuntimeError(
                            f"no safe candidate for env {env_index}: {decision.reason_codes}"
                        )
                    desired[env_index] = decision.command.as_array()
                    candidate_sources.append("active")
            observations, _ = _execute_batch_trial(
                env,
                actor,
                desired,
                distortion,
                config,
                trial + 1,
                "calibration",
                trace_rows,
            )
            for env_index, observation in enumerate(observations):
                valid = observation.valid
                if valid:
                    models[env_index].update(observation)
                # Attempted commands, including a runtime-rejected command, are
                # excluded from future active proposals so a hazard is not
                # knowingly repeated.
                history[env_index].append(desired[env_index].copy())
                metric_rows.append(
                    {
                        "scenario": config.scenario_id,
                        "tier": config.tier,
                        "seed": config.seeds[env_index],
                        "phase": "calibration",
                        "trial": trial + 1,
                        "source": candidate_sources[env_index],
                        "cmd_vx": desired[env_index, 0],
                        "cmd_vy": desired[env_index, 1],
                        "cmd_wz": desired[env_index, 2],
                        "measured_vx": observation.mean_velocity[0],
                        "measured_vy": observation.mean_velocity[1],
                        "measured_wz": observation.mean_velocity[2],
                        "predicted_vx": np.nan,
                        "predicted_vy": np.nan,
                        "predicted_wz": np.nan,
                        "predicted_std_vx": np.nan,
                        "predicted_std_vy": np.nan,
                        "predicted_std_wz": np.nan,
                        "valid": valid,
                        "reason_codes": observation.quality["reason_codes"],
                        "steady_ratio": observation.quality["steady_ratio"],
                        "safety_events": "|".join(observation.safety_events),
                    }
                )

        for trial, command in enumerate(_VALIDATION_COMMANDS, start=1):
            desired = np.tile(command, (len(config.seeds), 1))
            observations, _ = _execute_batch_trial(
                env,
                actor,
                desired,
                distortion,
                config,
                trial,
                "validation",
                trace_rows,
            )
            for env_index, observation in enumerate(observations):
                predictive = models[env_index].predict(command)
                prediction = predictive.mean
                predicted_std = np.sqrt(np.diag(predictive.covariance))
                metric_rows.append(
                    {
                        "scenario": config.scenario_id,
                        "tier": config.tier,
                        "seed": config.seeds[env_index],
                        "phase": "validation",
                        "trial": trial,
                        "source": "held_out_fixed",
                        "cmd_vx": command[0],
                        "cmd_vy": command[1],
                        "cmd_wz": command[2],
                        "measured_vx": observation.mean_velocity[0],
                        "measured_vy": observation.mean_velocity[1],
                        "measured_wz": observation.mean_velocity[2],
                        "predicted_vx": prediction[0],
                        "predicted_vy": prediction[1],
                        "predicted_wz": prediction[2],
                        "predicted_std_vx": predicted_std[0],
                        "predicted_std_vy": predicted_std[1],
                        "predicted_std_wz": predicted_std[2],
                        "valid": observation.valid,
                        "reason_codes": observation.quality["reason_codes"],
                        "steady_ratio": observation.quality["steady_ratio"],
                        "safety_events": "|".join(observation.safety_events),
                    }
                )
    finally:
        env.close()

    calibration = [row for row in metric_rows if row["phase"] == "calibration"]
    validation = [row for row in metric_rows if row["phase"] == "validation"]
    valid_validation = [row for row in validation if row["valid"]]
    command_values = np.asarray(
        [[row["cmd_vx"], row["cmd_vy"], row["cmd_wz"]] for row in valid_validation],
        dtype=np.float64,
    )
    measured_values = np.asarray(
        [
            [row["measured_vx"], row["measured_vy"], row["measured_wz"]]
            for row in valid_validation
        ],
        dtype=np.float64,
    )
    predicted_values = np.asarray(
        [
            [row["predicted_vx"], row["predicted_vy"], row["predicted_wz"]]
            for row in valid_validation
        ],
        dtype=np.float64,
    )
    predicted_std_values = np.asarray(
        [
            [
                row["predicted_std_vx"],
                row["predicted_std_vy"],
                row["predicted_std_wz"],
            ]
            for row in valid_validation
        ],
        dtype=np.float64,
    )
    if not len(valid_validation):
        raise RuntimeError("scenario produced no valid held-out validation rows")
    raw_rmse = float(np.sqrt(np.mean((command_values - measured_values) ** 2)))
    calibrated_rmse = float(
        np.sqrt(np.mean((predicted_values - measured_values) ** 2))
    )
    nonzero = np.linalg.norm(command_values, axis=1) > 0.05
    actual_motion = np.linalg.norm(measured_values, axis=1) > 0.03
    per_seed_rows: list[dict[str, Any]] = []
    for seed in config.seeds:
        seed_rows = [row for row in valid_validation if row["seed"] == seed]
        seed_command = np.asarray(
            [[row["cmd_vx"], row["cmd_vy"], row["cmd_wz"]] for row in seed_rows]
        )
        seed_measured = np.asarray(
            [
                [row["measured_vx"], row["measured_vy"], row["measured_wz"]]
                for row in seed_rows
            ]
        )
        seed_predicted = np.asarray(
            [
                [row["predicted_vx"], row["predicted_vy"], row["predicted_wz"]]
                for row in seed_rows
            ]
        )
        seed_raw_rmse = float(
            np.sqrt(np.mean((seed_command - seed_measured) ** 2))
        )
        seed_calibrated_rmse = float(
            np.sqrt(np.mean((seed_predicted - seed_measured) ** 2))
        )
        per_seed_rows.append(
            {
                "scenario": config.scenario_id,
                "tier": config.tier,
                "seed": seed,
                "validation_rows": len(seed_rows),
                "raw_rmse": seed_raw_rmse,
                "calibrated_rmse": seed_calibrated_rmse,
                "absolute_improvement": seed_raw_rmse - seed_calibrated_rmse,
                "relative_reduction": (
                    1.0 - seed_calibrated_rmse / seed_raw_rmse
                    if seed_raw_rmse > 0.0
                    else np.nan
                ),
            }
        )
    improvements = np.asarray(
        [row["absolute_improvement"] for row in per_seed_rows],
        dtype=np.float64,
    )
    bootstrap_rng = np.random.default_rng(config.simulator_seed + 191)
    bootstrap_means = np.mean(
        bootstrap_rng.choice(
            improvements,
            size=(2000, len(improvements)),
            replace=True,
        ),
        axis=1,
    )
    coverage_95 = float(
        np.mean(
            np.abs(measured_values - predicted_values)
            <= 1.96 * predicted_std_values
        )
    )
    safety_aborts = sum(bool(row["safety_events"]) for row in metric_rows)
    simulator_terminations = sum(
        "SIM_TERMINATION" in str(row["safety_events"]) for row in metric_rows
    )
    summary = {
        "schema_version": "1.0",
        "scenario": config.scenario_id,
        "tier": config.tier,
        "task": config.task,
        "terrain": config.terrain,
        "distortion": config.distortion,
        "num_envs": len(config.seeds),
        "calibration_rows": len(calibration),
        "validation_rows": len(validation),
        "valid_calibration_ratio": float(np.mean([row["valid"] for row in calibration])),
        "valid_validation_ratio": float(np.mean([row["valid"] for row in validation])),
        "actual_motion_ratio": float(np.mean(actual_motion[nonzero])),
        "raw_rmse": raw_rmse,
        "calibrated_rmse": calibrated_rmse,
        "calibrated_vs_raw_reduction": 1.0 - calibrated_rmse / raw_rmse,
        "paired_absolute_improvement_mean": float(np.mean(improvements)),
        "paired_absolute_improvement_ci95": [
            float(np.quantile(bootstrap_means, 0.025)),
            float(np.quantile(bootstrap_means, 0.975)),
        ],
        "calibrated_win_rate": float(np.mean(improvements > 0.0)),
        "predictive_coverage_95": coverage_95,
        "safety_aborts": int(safety_aborts),
        "maximum_abort_latency_s": float(
            (1.0 / config.sample_rate_hz) if safety_aborts else 0.0
        ),
        "simulator_terminations": int(simulator_terminations),
        # A hard-envelope crossing is a successful safety abort when the next
        # 50 Hz control update commands zero. Simulator termination is serious.
        "serious_safety_events": int(simulator_terminations),
        "finite": bool(
            np.all(np.isfinite(command_values))
            and np.all(np.isfinite(measured_values))
            and np.all(np.isfinite(predicted_values))
            and np.all(np.isfinite(predicted_std_values))
            and np.all(np.isfinite(improvements))
        ),
    }
    _write_csv(output / "trial_metrics.csv", metric_rows)
    _write_csv(output / "pose_trace.csv", trace_rows)
    _write_csv(output / "per_seed_metrics.csv", per_seed_rows)
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output / "distortion_parameters.json").write_text(
        json.dumps(parameters.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output / "scenario_config.json").write_text(
        json.dumps(asdict(config), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary
