"""Vectorized P6 domain-shift benchmark executed inside Isaac Lab."""

from __future__ import annotations

import csv
import gzip
import json
from collections import deque
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
import torch

from calibagent.core.models.bayesian import BayesianBasisModel
from calibagent.core.models.features import BasisTransformer
from calibagent.core.planning.candidates import CandidatePool, CommandSpace
from calibagent.core.planning.d_optimal import DOptimalPlanner
from calibagent.core.planning.ivr import IntegratedVariancePlanner
from calibagent.core.planning.samplers import latin_hypercube, random_uniform
from calibagent.core.planning.task import TaskDistribution
from calibagent.core.safety import (
    HardSafetyFilter,
    SafetyEnvelope,
    filter_candidates_by_forward_cap,
)
from calibagent.core.shift import (
    DomainShiftConfig,
    DomainShiftDetector,
    PairedSignatureConfig,
    PairedSignatureDetector,
)
from calibagent.interfaces.types import Candidate, PriorState, RobotState, VelocityCommand
from calibagent.sim import CommandDistortion, make_distortion_parameters
from calibagent_sim.policy import load_actor
from calibagent_sim.runner import (
    _CALIBRATION_SEED,
    _VALIDATION_COMMANDS,
    ScenarioConfig,
    _configure_environment,
    _execute_batch_trial,
    _write_csv,
)

_BOUNDS = np.asarray(
    [[-0.40, 0.40], [-0.25, 0.25], [-0.70, 0.70]],
    dtype=np.float64,
)
_PASSIVE_RECOVERY = np.asarray(
    [
        [-0.35, -0.12, -0.35],
        [0.35, 0.12, 0.35],
        [-0.20, 0.20, 0.45],
        [0.20, -0.20, -0.45],
        [-0.38, 0.05, 0.25],
        [0.38, -0.05, -0.25],
        [0.05, 0.22, -0.55],
        [-0.05, -0.22, 0.55],
        [0.28, 0.14, -0.30],
        [-0.28, -0.14, 0.30],
        [0.15, -0.18, 0.60],
        [-0.15, 0.18, -0.60],
    ],
    dtype=np.float64,
)


def _write_csv_gzip(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write high-rate trace evidence without discarding any samples."""

    if not rows:
        raise ValueError(f"refusing to write empty trace: {path}")
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _physical_config(
    payload: dict[str, Any],
    physics: dict[str, Any],
    slot_seeds: tuple[int, ...],
) -> ScenarioConfig:
    trial = dict(payload["trial"])
    safety = dict(payload["safety"])
    adaptation = dict(payload["adaptation"])
    return ScenarioConfig(
        scenario_id=str(payload["id"]),
        tier="P6",
        task=str(payload["task"]),
        distortion="domain_shift",
        terrain="flat",
        static_friction=float(physics["static_friction"]),
        dynamic_friction=float(physics["dynamic_friction"]),
        payload_add_kg=float(physics["payload_add_kg"]),
        com_offset_x_m=float(physics["com_offset_x_m"]),
        seeds=slot_seeds,
        calibration_trials=int(trial["pre_calibration_trials"]),
        warmup_s=float(trial["warmup_s"]),
        ramp_in_s=float(trial["ramp_in_s"]),
        settle_s=float(trial["settle_s"]),
        measure_s=float(trial["measure_s"]),
        ramp_out_s=float(trial["ramp_out_s"]),
        sample_rate_hz=float(trial["sample_rate_hz"]),
        simulator_seed=int(payload["simulator_seed"]),
        safety_min_base_height_m=float(safety["min_base_height_m"]),
        safety_max_base_height_m=float(safety["max_base_height_m"]),
        safety_max_coupled_load=float(safety["max_coupled_load"]),
        model_prior_scale=float(adaptation["model_prior_scale"]),
    )


def _safe_pool(
    config: ScenarioConfig,
) -> tuple[CandidatePool, CandidatePool, BasisTransformer]:
    command_space = CommandSpace(_BOUNDS, max_linear_norm=0.45)
    reference = CandidatePool.generate(command_space, count=128, seed=66131)
    envelope = SafetyEnvelope(
        min_base_height=config.safety_min_base_height_m,
        max_base_height=config.safety_max_base_height_m,
        max_coupled_load=config.safety_max_coupled_load,
    )
    linear_load = np.linalg.norm(reference.commands[:, :2], axis=1) / envelope.max_linear_norm
    angular_scale = max(abs(bound) for bound in envelope.command_bounds[2])
    coupled = linear_load + np.abs(reference.commands[:, 2]) / angular_scale
    pool = CandidatePool(
        reference.commands[coupled <= envelope.max_coupled_load],
        command_space,
    )
    transformer = BasisTransformer("m2_affine_cross_hinge").fit(reference.commands)
    return reference, pool, transformer


def _annotate_trace(
    rows: list[dict[str, Any]],
    start: int,
    slots: list[tuple[str, int]],
    context_stage: str,
) -> None:
    count = len(slots)
    for offset, row in enumerate(rows[start:]):
        method, seed = slots[offset % count]
        row["method"] = method
        row["seed"] = seed
        row["context_stage"] = context_stage


def _execute(
    env: Any,
    actor: Any,
    desired: np.ndarray,
    distortion: CommandDistortion,
    config: ScenarioConfig,
    trial: int,
    phase: str,
    trace_rows: list[dict[str, Any]],
    slots: list[tuple[str, int]],
    context_stage: str,
) -> list[Any]:
    start = len(trace_rows)
    observations, _ = _execute_batch_trial(
        env,
        actor,
        desired,
        distortion,
        config,
        trial,
        phase,
        trace_rows,
    )
    _annotate_trace(trace_rows, start, slots, context_stage)
    return observations


def _model_components(
    config: ScenarioConfig,
    slots: list[tuple[str, int]],
) -> tuple[
    dict[tuple[str, int], BayesianBasisModel],
    dict[tuple[str, int], IntegratedVariancePlanner],
    CandidatePool,
    TaskDistribution,
]:
    reference, pool, transformer = _safe_pool(config)
    basis = transformer.transform(pool.commands)
    identity = np.linalg.lstsq(basis, pool.commands, rcond=None)[0].T
    models: dict[tuple[str, int], BayesianBasisModel] = {}
    planners: dict[tuple[str, int], IntegratedVariancePlanner] = {}
    for key in slots:
        model = BayesianBasisModel(
            transformer,
            prior_scale=config.model_prior_scale,
            noise_variance=[0.0025, 0.0025, 0.0050],
        )
        model.initialize(PriorState(mean=identity))
        models[key] = model
        planners[key] = IntegratedVariancePlanner(
            pool,
            duplicate_distance=0.02,
        )
    return models, planners, reference, TaskDistribution.uniform(_VALIDATION_COMMANDS)


def _recovery_sequence(
    method: str,
    seed: int,
    pool: CandidatePool,
    count: int,
) -> np.ndarray:
    """Return a safe, deterministic matched-budget recovery sequence."""

    if method == "recovery_random":
        targets = random_uniform(count * 4, _BOUNDS, seed + 91301)
    elif method == "recovery_lhs":
        targets = latin_hypercube(count * 4, _BOUNDS, seed + 91303)
    else:
        raise ValueError(f"unsupported passive recovery selector: {method}")
    normalized_pool = pool.command_space.normalized(pool.commands)
    selected: list[int] = []
    for target in targets:
        if len(selected) == count:
            break
        remaining = np.asarray(
            [index for index in range(len(pool.commands)) if index not in selected],
            dtype=np.int64,
        )
        if not len(remaining):
            break
        normalized_target = pool.command_space.normalized(target[None, :])[0]
        distance = np.linalg.norm(
            normalized_pool[remaining] - normalized_target,
            axis=1,
        )
        selected.append(int(remaining[int(np.argmin(distance))]))
    if len(selected) != count:
        raise RuntimeError(f"could not construct {method} recovery sequence")
    return pool.commands[np.asarray(selected, dtype=np.int64)]


def _distortion(
    family: str,
    slots: list[tuple[str, int]],
    seed_offset: int,
    simulator_seed: int,
) -> CommandDistortion:
    paired_seeds = [seed + seed_offset for _, seed in slots]
    return CommandDistortion(
        make_distortion_parameters(family, paired_seeds),
        seed=simulator_seed,
    )


def _apply_physics_shift(
    env: Any,
    pre_physics: dict[str, Any],
    post_physics: dict[str, Any],
) -> dict[str, Any]:
    """Apply the declared material, base-mass and COM event in-place."""

    robot = env.unwrapped.scene["robot"]
    env_count = int(env.unwrapped.num_envs)
    indices = torch.arange(env_count, dtype=torch.int32, device="cpu")
    materials = robot.root_physx_view.get_material_properties()
    materials[:, :, 0] = float(post_physics["static_friction"])
    materials[:, :, 1] = float(post_physics["dynamic_friction"])
    robot.root_physx_view.set_material_properties(materials, indices)

    base_ids, _ = robot.find_bodies("base")
    if len(base_ids) != 1:
        raise RuntimeError(f"expected one Go2 base body, found {base_ids}")
    base_id = int(base_ids[0])
    payload_delta = float(post_physics["payload_add_kg"]) - float(pre_physics["payload_add_kg"])
    masses = robot.root_physx_view.get_masses()
    old_mass = masses[:, base_id].clone()
    masses[:, base_id] += payload_delta
    if torch.any(masses[:, base_id] <= 0.0):
        raise RuntimeError("P6 shift produced a non-positive base mass")
    robot.root_physx_view.set_masses(masses, indices)
    inertias = robot.root_physx_view.get_inertias()
    inertias[:, base_id] *= (masses[:, base_id] / torch.clamp(old_mass, min=1e-9))[:, None]
    robot.root_physx_view.set_inertias(inertias, indices)

    com_delta = float(post_physics["com_offset_x_m"]) - float(pre_physics["com_offset_x_m"])
    coms = robot.root_physx_view.get_coms()
    coms[:, base_id, 0] += com_delta
    robot.root_physx_view.set_coms(coms, indices)
    return {
        "event": "in_place_material_mass_com_shift",
        "num_envs": env_count,
        "base_body_id": base_id,
        "payload_delta_kg": payload_delta,
        "com_delta_x_m": com_delta,
        "static_friction": float(post_physics["static_friction"]),
        "dynamic_friction": float(post_physics["dynamic_friction"]),
    }


def _predict_rows(
    models: dict[tuple[str, int], BayesianBasisModel],
    slots: list[tuple[str, int]],
    desired: np.ndarray,
) -> list[tuple[np.ndarray, np.ndarray]]:
    result = []
    for index, key in enumerate(slots):
        predictive = models[key].predict(desired[index])
        result.append(
            (
                predictive.mean,
                predictive.covariance,
            )
        )
    return result


def _rmse(residuals: list[np.ndarray]) -> float:
    values = np.asarray(residuals, dtype=np.float64)
    return float(np.sqrt(np.mean(values**2)))


def _safe_candidate_or_stop(
    candidates: list[Candidate],
    safe_filter: HardSafetyFilter,
    neutral_state: RobotState,
    zero_history: list[VelocityCommand],
) -> tuple[np.ndarray, bool]:
    """Return the first authorized candidate or a shared zero-command fallback."""

    decision = safe_filter.select_first_safe(
        candidates,
        neutral_state,
        zero_history,
    )
    if decision.accepted and decision.command is not None:
        return decision.command.as_array(), False
    return np.zeros(3, dtype=np.float64), True


def run_p6_scenario(
    payload: dict[str, Any],
    checkpoint: Path,
    output: Path,
    device: str,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    seeds = tuple(int(item) for item in payload["seeds"])
    methods = tuple(str(item) for item in payload["methods"])
    if len(methods) != 1:
        raise ValueError("one P6 simulator process must execute exactly one method")
    slots = [(method, seed) for method in methods for seed in seeds]
    slot_seeds = tuple(seed for _, seed in slots)
    pre_config = _physical_config(payload, dict(payload["pre_physics"]), slot_seeds)
    post_config = _physical_config(payload, dict(payload["post_physics"]), slot_seeds)
    actor = load_actor(checkpoint, device)
    models, planners, pool, task = _model_components(pre_config, slots)
    no_task = TaskDistribution.uniform(pool.commands)
    d_optimal = {key: DOptimalPlanner(pool, duplicate_distance=0.02) for key in slots}
    recovery_sequences = {
        key: _recovery_sequence(
            key[0],
            key[1],
            pool,
            int(payload["trial"]["recovery_budget_trials"]),
        )
        for key in slots
        if key[0] in {"recovery_random", "recovery_lhs"}
    }
    histories: dict[tuple[str, int], list[np.ndarray]] = {key: [] for key in slots}
    detector_payload = dict(payload["detector"])
    detector_mode = str(detector_payload.get("mode", "cusum_nis"))
    if detector_mode not in {"cusum_nis", "paired_signature"}:
        raise ValueError(f"unsupported P6 detector mode: {detector_mode}")
    cusum_payload = dict(detector_payload)
    if detector_mode == "paired_signature":
        cusum_payload.update(
            {
                "minimum_positive_evidence": int(
                    detector_payload.get("legacy_minimum_positive_evidence", 3)
                ),
                "evidence_window_trials": int(
                    detector_payload.get("legacy_evidence_window_trials", 5)
                ),
                "minimum_dwell_trials": int(detector_payload.get("legacy_minimum_dwell_trials", 3)),
            }
        )
    detector_settings = DomainShiftConfig(
        **{
            key: value
            for key, value in cusum_payload.items()
            if key
            in {
                "reference_nis",
                "allowance",
                "alarm_threshold",
                "minimum_positive_evidence",
                "evidence_window_trials",
                "minimum_dwell_trials",
            }
        }
    )
    legacy_detectors = {key: DomainShiftDetector(detector_settings) for key in slots}
    signature_detectors: dict[tuple[str, int], PairedSignatureDetector] = {}
    if detector_mode == "paired_signature":
        signature_settings = PairedSignatureConfig(
            component_scales=tuple(float(item) for item in detector_payload["component_scales"]),
            distance_threshold=float(detector_payload["distance_threshold"]),
            minimum_positive_evidence=int(detector_payload["minimum_positive_evidence"]),
            evidence_window_trials=int(detector_payload["evidence_window_trials"]),
            minimum_dwell_trials=int(detector_payload["minimum_dwell_trials"]),
        )
        signature_detectors = {key: PairedSignatureDetector(signature_settings) for key in slots}
    monitor_commands = np.asarray(
        detector_payload.get("monitor_commands", _VALIDATION_COMMANDS),
        dtype=np.float64,
    )
    if monitor_commands.ndim != 2 or monitor_commands.shape[1] != 3:
        raise ValueError("P6 monitor commands must have shape (n, 3)")
    if not np.all(np.isfinite(monitor_commands)):
        raise ValueError("P6 monitor commands must be finite")
    baseline_trials = int(detector_payload.get("signature_baseline_trials", len(monitor_commands)))
    if detector_mode == "paired_signature" and baseline_trials != len(monitor_commands):
        raise ValueError("paired-signature baseline must cover every monitor command once")

    def detector_latched(key: tuple[str, int]) -> bool:
        if detector_mode == "paired_signature":
            return signature_detectors[key].latched
        return legacy_detectors[key].latched

    contextual_forward_cap = float(
        payload["safety"].get("forward_cap_after_base_height_abort", np.inf)
    )
    forward_caps = {key: float("inf") for key in slots}

    def context_filtered(key: tuple[str, int], candidates: list[Candidate]) -> list[Candidate]:
        if np.isfinite(forward_caps[key]):
            return filter_candidates_by_forward_cap(candidates, forward_caps[key])
        return candidates

    inflation = float(payload["adaptation"]["posterior_inflation_factor"])
    trial_cfg = dict(payload["trial"])
    monitor_rows: list[dict[str, Any]] = []
    recovery_rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    all_valid: list[bool] = []
    serious_events = 0
    safety_aborts = 0
    safe_filter = HardSafetyFilter(
        SafetyEnvelope(
            min_base_height=pre_config.safety_min_base_height_m,
            max_base_height=pre_config.safety_max_base_height_m,
            max_coupled_load=pre_config.safety_max_coupled_load,
        )
    )
    neutral_state = RobotState(
        0.0,
        (0.0, 0.0),
        0.0,
        0.0,
        0.0,
        0.40,
        (0.0, 0.0, 0.0),
    )
    zero_history = [VelocityCommand(0.0, 0.0, 0.0, 0.1)]
    pre_distortion = _distortion(
        str(payload["pre_distortion"]),
        slots,
        0,
        int(payload["simulator_seed"]) + 17,
    )
    pre_residuals: dict[tuple[str, int], list[np.ndarray]] = {key: [] for key in slots}
    false_alarms: dict[tuple[str, int], bool] = {key: False for key in slots}
    env = gym.make(
        pre_config.task,
        cfg=_configure_environment(pre_config, device),
    )
    try:
        for trial in range(int(trial_cfg["pre_calibration_trials"])):
            desired = np.zeros((len(slots), 3), dtype=np.float64)
            for index, key in enumerate(slots):
                if trial < len(_CALIBRATION_SEED):
                    desired[index] = _CALIBRATION_SEED[trial]
                else:
                    candidates = planners[key].propose(
                        models[key],
                        task,
                        histories[key],
                        k=min(12, len(planners[key].candidate_pool.commands)),
                    )
                    decision = safe_filter.select_first_safe(
                        candidates,
                        neutral_state,
                        zero_history,
                    )
                    if not decision.accepted or decision.command is None:
                        raise RuntimeError(f"no safe P6 calibration candidate: {key}")
                    desired[index] = decision.command.as_array()
            observations = _execute(
                env,
                actor,
                desired,
                pre_distortion,
                pre_config,
                trial + 1,
                "pre_calibration",
                trace_rows,
                slots,
                "pre_shift",
            )
            for index, (key, observation) in enumerate(zip(slots, observations, strict=True)):
                all_valid.append(observation.valid)
                histories[key].append(desired[index].copy())
                if observation.valid:
                    models[key].update(observation)
                if observation.safety_events:
                    safety_aborts += 1
                    serious_events += int("SIM_TERMINATION" in "|".join(observation.safety_events))
        for trial in range(1, int(trial_cfg["pre_monitor_trials"]) + 1):
            signature_id = (trial - 1) % len(monitor_commands)
            command = monitor_commands[signature_id]
            desired = np.tile(command, (len(slots), 1))
            predictions = _predict_rows(models, slots, desired)
            observations = _execute(
                env,
                actor,
                desired,
                pre_distortion,
                pre_config,
                trial,
                "pre_monitor",
                trace_rows,
                slots,
                "pre_shift",
            )
            for index, (key, observation) in enumerate(zip(slots, observations, strict=True)):
                prediction, covariance = predictions[index]
                residual = observation.mean_velocity - prediction
                all_valid.append(observation.valid)
                legacy_detection = legacy_detectors[key].update(
                    residual,
                    covariance + observation.covariance,
                    trial=trial,
                )
                signature_distance = float("nan")
                selected_alarm = legacy_detection.alarm
                if detector_mode == "paired_signature":
                    selected_alarm = False
                    if trial <= baseline_trials:
                        if not observation.valid:
                            raise RuntimeError(
                                f"invalid paired-signature commissioning observation: {key}"
                            )
                        signature_detectors[key].prime(signature_id, residual)
                    elif observation.valid:
                        signature_detection = signature_detectors[key].update(
                            signature_id,
                            residual,
                            trial=trial - baseline_trials,
                        )
                        signature_distance = signature_detection.distance
                        selected_alarm = signature_detection.alarm
                false_alarms[key] |= selected_alarm
                if observation.valid:
                    pre_residuals[key].append(residual)
                monitor_rows.append(
                    {
                        "scenario": payload["id"],
                        "seed": key[1],
                        "method": key[0],
                        "context_stage": "pre_shift",
                        "monitor_trial": trial,
                        "cmd_vx": command[0],
                        "cmd_vy": command[1],
                        "cmd_wz": command[2],
                        "measured_vx": observation.mean_velocity[0],
                        "measured_vy": observation.mean_velocity[1],
                        "measured_wz": observation.mean_velocity[2],
                        "predicted_vx": prediction[0],
                        "predicted_vy": prediction[1],
                        "predicted_wz": prediction[2],
                        "normalized_nis": legacy_detection.normalized_nis,
                        "cusum": legacy_detection.statistic,
                        "legacy_alarm": legacy_detection.alarm,
                        "signature_distance": signature_distance,
                        "alarm": selected_alarm,
                        "valid": observation.valid,
                        "safety_events": "|".join(observation.safety_events),
                    }
                )
    except BaseException:
        env.close()
        raise

    pre_rmse = {key: _rmse(values) for key, values in pre_residuals.items()}
    target_rmse = {
        key: float(
            np.clip(
                value * float(payload["adaptation"]["target_rmse_multiplier"]),
                float(payload["adaptation"]["target_rmse_floor"]),
                float(payload["adaptation"]["target_rmse_ceiling"]),
            )
        )
        for key, value in pre_rmse.items()
    }
    post_distortion = _distortion(
        str(payload["post_distortion"]),
        slots,
        int(payload["post_seed_offset"]),
        int(payload["simulator_seed"]) + 117,
    )
    detection_delay: dict[tuple[str, int], int | None] = {key: None for key in slots}
    shifted_residuals: dict[tuple[str, int], list[np.ndarray]] = {key: [] for key in slots}
    applied_shift = _apply_physics_shift(
        env,
        dict(payload["pre_physics"]),
        dict(payload["post_physics"]),
    )
    try:
        pre_monitor_count = int(trial_cfg["pre_monitor_trials"])
        for shift_trial in range(
            1,
            int(trial_cfg["shift_monitor_trials"]) + 1,
        ):
            signature_id = (shift_trial - 1) % len(monitor_commands)
            command = monitor_commands[signature_id]
            desired = np.tile(command, (len(slots), 1))
            predictions = _predict_rows(models, slots, desired)
            observations = _execute(
                env,
                actor,
                desired,
                post_distortion,
                post_config,
                shift_trial,
                "shift_monitor",
                trace_rows,
                slots,
                "post_shift",
            )
            for index, (key, observation) in enumerate(zip(slots, observations, strict=True)):
                prediction, covariance = predictions[index]
                residual = observation.mean_velocity - prediction
                all_valid.append(observation.valid)
                legacy_detection = legacy_detectors[key].update(
                    residual,
                    covariance + observation.covariance,
                    trial=pre_monitor_count + shift_trial,
                )
                signature_distance = float("nan")
                selected_alarm = legacy_detection.alarm
                if detector_mode == "paired_signature":
                    selected_alarm = False
                    if observation.valid:
                        signature_detection = signature_detectors[key].update(
                            signature_id,
                            residual,
                            trial=max(0, pre_monitor_count - baseline_trials) + shift_trial,
                        )
                        signature_distance = signature_detection.distance
                        selected_alarm = signature_detection.alarm
                if observation.valid:
                    shifted_residuals[key].append(residual)
                if selected_alarm:
                    detection_delay[key] = shift_trial
                    if key[0] != "frozen":
                        models[key].inflate_posterior(inflation)
                monitor_rows.append(
                    {
                        "scenario": payload["id"],
                        "seed": key[1],
                        "method": key[0],
                        "context_stage": "post_shift",
                        "monitor_trial": shift_trial,
                        "cmd_vx": command[0],
                        "cmd_vy": command[1],
                        "cmd_wz": command[2],
                        "measured_vx": observation.mean_velocity[0],
                        "measured_vy": observation.mean_velocity[1],
                        "measured_wz": observation.mean_velocity[2],
                        "predicted_vx": prediction[0],
                        "predicted_vy": prediction[1],
                        "predicted_wz": prediction[2],
                        "normalized_nis": legacy_detection.normalized_nis,
                        "cusum": legacy_detection.statistic,
                        "legacy_alarm": legacy_detection.alarm,
                        "signature_distance": signature_distance,
                        "alarm": selected_alarm,
                        "valid": observation.valid,
                        "safety_events": "|".join(observation.safety_events),
                    }
                )
                if observation.safety_events:
                    safety_aborts += 1
                    serious_events += int("SIM_TERMINATION" in "|".join(observation.safety_events))

        windows: dict[tuple[str, int], deque[np.ndarray]] = {
            key: deque(maxlen=int(trial_cfg["validation_window"])) for key in slots
        }
        recovered_at: dict[tuple[str, int], int | None] = {key: None for key in slots}
        final_rmse: dict[tuple[str, int], float] = {key: float("inf") for key in slots}
        for recovery_trial in range(
            1,
            int(trial_cfg["recovery_budget_trials"]) + 1,
        ):
            desired = np.zeros((len(slots), 3), dtype=np.float64)
            sources: list[str] = []
            for index, key in enumerate(slots):
                adaptive_methods = {
                    "passive",
                    "full",
                    "recovery_no_task",
                    "recovery_d_opt",
                    "recovery_lhs",
                    "recovery_random",
                }
                stopped = bool(
                    payload["adaptation"].get("stop_updates_after_recovery", False)
                    and key[0] in adaptive_methods
                    and recovered_at[key] is not None
                )
                if stopped:
                    desired[index] = 0.0
                    sources.append("stopped_after_recovery")
                elif key[0] == "full" and detector_latched(key):
                    candidates = planners[key].propose(
                        models[key],
                        task,
                        histories[key],
                        k=min(12, len(planners[key].candidate_pool.commands)),
                    )
                    candidates = context_filtered(key, candidates)
                    desired[index], used_fallback = _safe_candidate_or_stop(
                        candidates,
                        safe_filter,
                        neutral_state,
                        zero_history,
                    )
                    sources.append("active_safe_stop" if used_fallback else "active")
                elif key[0] == "recovery_no_task" and detector_latched(key):
                    candidates = planners[key].propose(
                        models[key],
                        no_task,
                        histories[key],
                        k=min(12, len(planners[key].candidate_pool.commands)),
                    )
                    candidates = context_filtered(key, candidates)
                    desired[index], used_fallback = _safe_candidate_or_stop(
                        candidates,
                        safe_filter,
                        neutral_state,
                        zero_history,
                    )
                    sources.append(
                        "active_no_task_safe_stop" if used_fallback else "active_no_task"
                    )
                elif key[0] == "recovery_d_opt" and detector_latched(key):
                    candidates = d_optimal[key].propose(
                        models[key],
                        histories[key],
                        k=min(12, len(pool.commands)),
                    )
                    candidates = context_filtered(key, candidates)
                    desired[index], used_fallback = _safe_candidate_or_stop(
                        candidates,
                        safe_filter,
                        neutral_state,
                        zero_history,
                    )
                    sources.append("d_optimal_safe_stop" if used_fallback else "d_optimal")
                elif key[0] in {"recovery_random", "recovery_lhs"} and detector_latched(key):
                    desired[index] = recovery_sequences[key][recovery_trial - 1]
                    sources.append(key[0].removeprefix("recovery_"))
                else:
                    desired[index] = _PASSIVE_RECOVERY[
                        (recovery_trial - 1) % len(_PASSIVE_RECOVERY)
                    ]
                    sources.append("fixed")
            observations = _execute(
                env,
                actor,
                desired,
                post_distortion,
                post_config,
                recovery_trial,
                "adaptation",
                trace_rows,
                slots,
                "post_shift",
            )
            for index, (key, observation) in enumerate(zip(slots, observations, strict=True)):
                all_valid.append(observation.valid)
                histories[key].append(desired[index].copy())
                update_enabled = not bool(
                    payload["adaptation"].get("stop_updates_after_recovery", False)
                    and recovered_at[key] is not None
                )
                if (
                    key[0] in adaptive_methods
                    and detector_latched(key)
                    and observation.valid
                    and update_enabled
                ):
                    models[key].update(observation)
                recovery_rows.append(
                    {
                        "scenario": payload["id"],
                        "seed": key[1],
                        "method": key[0],
                        "phase": "adaptation",
                        "recovery_trial": recovery_trial,
                        "source": sources[index],
                        "cmd_vx": desired[index, 0],
                        "cmd_vy": desired[index, 1],
                        "cmd_wz": desired[index, 2],
                        "measured_vx": observation.mean_velocity[0],
                        "measured_vy": observation.mean_velocity[1],
                        "measured_wz": observation.mean_velocity[2],
                        "predicted_vx": np.nan,
                        "predicted_vy": np.nan,
                        "predicted_wz": np.nan,
                        "rolling_rmse": np.nan,
                        "target_rmse": target_rmse[key],
                        "recovered": False,
                        "valid": observation.valid,
                        "safety_events": "|".join(observation.safety_events),
                    }
                )
                if observation.safety_events:
                    safety_aborts += 1
                    serious_events += int("SIM_TERMINATION" in "|".join(observation.safety_events))
                    if "BASE_HEIGHT_LIMIT" in observation.safety_events and np.isfinite(
                        contextual_forward_cap
                    ):
                        forward_caps[key] = min(forward_caps[key], contextual_forward_cap)
            validation_command = _VALIDATION_COMMANDS[
                (recovery_trial - 1) % len(_VALIDATION_COMMANDS)
            ]
            validation_desired = np.tile(
                validation_command,
                (len(slots), 1),
            )
            predictions = _predict_rows(models, slots, validation_desired)
            validation_observations = _execute(
                env,
                actor,
                validation_desired,
                post_distortion,
                post_config,
                recovery_trial,
                "recovery_validation",
                trace_rows,
                slots,
                "post_shift",
            )
            for index, (key, observation) in enumerate(
                zip(slots, validation_observations, strict=True)
            ):
                prediction, _ = predictions[index]
                residual = observation.mean_velocity - prediction
                all_valid.append(observation.valid)
                if observation.valid:
                    windows[key].append(residual)
                rolling = (
                    _rmse(list(windows[key]))
                    if len(windows[key]) == int(trial_cfg["validation_window"])
                    else float("nan")
                )
                if np.isfinite(rolling):
                    final_rmse[key] = rolling
                    if recovered_at[key] is None and rolling <= target_rmse[key]:
                        recovered_at[key] = recovery_trial
                recovery_rows.append(
                    {
                        "scenario": payload["id"],
                        "seed": key[1],
                        "method": key[0],
                        "phase": "validation",
                        "recovery_trial": recovery_trial,
                        "source": "rolling_fixed_holdout",
                        "cmd_vx": validation_command[0],
                        "cmd_vy": validation_command[1],
                        "cmd_wz": validation_command[2],
                        "measured_vx": observation.mean_velocity[0],
                        "measured_vy": observation.mean_velocity[1],
                        "measured_wz": observation.mean_velocity[2],
                        "predicted_vx": prediction[0],
                        "predicted_vy": prediction[1],
                        "predicted_wz": prediction[2],
                        "rolling_rmse": rolling,
                        "target_rmse": target_rmse[key],
                        "recovered": recovered_at[key] is not None,
                        "valid": observation.valid,
                        "safety_events": "|".join(observation.safety_events),
                    }
                )
                if observation.safety_events:
                    safety_aborts += 1
                    serious_events += int("SIM_TERMINATION" in "|".join(observation.safety_events))
    finally:
        env.close()

    shifted_rmse = {key: _rmse(values) for key, values in shifted_residuals.items()}
    per_seed_rows: list[dict[str, Any]] = []
    for method in methods:
        for seed in seeds:
            key = (method, seed)
            per_seed_rows.append(
                {
                    "scenario": payload["id"],
                    "seed": seed,
                    "method": method,
                    "false_alarm": false_alarms[key],
                    "detected": detection_delay[key] is not None,
                    "detection_delay_trials": (
                        detection_delay[key]
                        if detection_delay[key] is not None
                        else int(trial_cfg["shift_monitor_trials"]) + 1
                    ),
                    "pre_shift_rmse": pre_rmse[key],
                    "initial_shifted_rmse": shifted_rmse[key],
                    "target_rmse": target_rmse[key],
                    "recovered": recovered_at[key] is not None,
                    "recovery_trials": (
                        recovered_at[key]
                        if recovered_at[key] is not None
                        else int(trial_cfg["recovery_budget_trials"]) + 1
                    ),
                    "final_rmse": final_rmse[key],
                }
            )
    method = methods[0]
    detected_delays = np.asarray(
        [float(row["detection_delay_trials"]) for row in per_seed_rows if bool(row["detected"])],
        dtype=np.float64,
    )
    recovered_trials = np.asarray(
        [float(row["recovery_trials"]) for row in per_seed_rows if bool(row["recovered"])],
        dtype=np.float64,
    )
    summary = {
        "schema_version": "1.0",
        "scenario": payload["id"],
        "method": method,
        "detector_mode": detector_mode,
        "num_seeds": len(seeds),
        "no_shift_false_alarm_rate": float(
            np.mean([bool(row["false_alarm"]) for row in per_seed_rows])
        ),
        "detection_rate": float(np.mean([bool(row["detected"]) for row in per_seed_rows])),
        "median_detection_delay_trials": (
            float(np.median(detected_delays)) if len(detected_delays) else float("inf")
        ),
        "p95_detection_delay_trials": (
            float(np.quantile(detected_delays, 0.95)) if len(detected_delays) else float("inf")
        ),
        "recovery_rate": float(np.mean([bool(row["recovered"]) for row in per_seed_rows])),
        "median_recovery_trials": (
            float(np.median(recovered_trials)) if len(recovered_trials) else float("inf")
        ),
        "p95_recovery_trials": (
            float(np.quantile(recovered_trials, 0.95)) if len(recovered_trials) else float("inf")
        ),
        "recovery_to_dense_budget_ratio": (
            int(trial_cfg["recovery_budget_trials"]) / int(trial_cfg["dense_budget_trials"])
        ),
        "primary_recovery_horizon_trials": int(
            trial_cfg.get(
                "primary_recovery_horizon_trials",
                trial_cfg["recovery_budget_trials"],
            )
        ),
        "validation_window_trials": int(trial_cfg["validation_window"]),
        "invalid_window_rmse_penalty": float(
            payload["adaptation"].get("invalid_window_rmse_penalty", 1.0)
        ),
        "valid_observation_ratio": float(np.mean(all_valid)),
        "safety_aborts": int(safety_aborts),
        "maximum_abort_latency_s": (1.0 / post_config.sample_rate_hz if safety_aborts else 0.0),
        "serious_safety_events": int(serious_events),
        "finite": bool(np.all(np.isfinite([float(row["final_rmse"]) for row in per_seed_rows]))),
    }
    curve_rows = [
        {
            "scenario": row["scenario"],
            "seed": row["seed"],
            "method": row["method"],
            "recovery_trial": row["recovery_trial"],
            "rolling_rmse": row["rolling_rmse"],
            "target_rmse": row["target_rmse"],
        }
        for row in recovery_rows
        if row["phase"] == "validation" and np.isfinite(row["rolling_rmse"])
    ]
    _write_csv(output / "monitor_metrics.csv", monitor_rows)
    _write_csv(output / "recovery_metrics.csv", recovery_rows)
    _write_csv(output / "per_seed_metrics.csv", per_seed_rows)
    _write_csv(output / "recovery_curve.csv", curve_rows)
    _write_csv_gzip(output / "pose_trace.csv.gz", trace_rows)
    (output / "shift_events.json").write_text(
        json.dumps(
            {
                "event_after_pre_monitor_trial": int(trial_cfg["pre_monitor_trials"]),
                "pre_distortion": payload["pre_distortion"],
                "post_distortion": payload["post_distortion"],
                "post_seed_offset": payload["post_seed_offset"],
                "pre_physics": payload["pre_physics"],
                "post_physics": payload["post_physics"],
                "applied_event": applied_shift,
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
