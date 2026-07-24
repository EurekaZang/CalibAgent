"""P4 stopping and fault-injection benchmark with immutable evidence output."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import yaml

from calibagent.core.runtime import RuntimeEvent, TrialStateMachine
from calibagent.core.safety import HardSafetyFilter, SafetyEnvelope
from calibagent.core.stopping import StopCriteria, StopMetrics, StopReason, StopRule
from calibagent.eval.real_replay import file_sha256
from calibagent.interfaces.types import Candidate, RobotState, VelocityCommand


@dataclass(frozen=True)
class P4BenchmarkConfig:
    output_dir: str
    source_trace: str
    source_method: str
    expected_families: tuple[str, ...]
    expected_seeds: tuple[int, ...]
    stop: dict[str, Any]
    safety: dict[str, Any]
    fault_injection: dict[str, Any]
    publication_gates: dict[str, Any]
    experiment_role: str = "main"
    protocol_frozen_utc: str = ""

    @classmethod
    def from_yaml(cls, path: Path) -> P4BenchmarkConfig:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("P4 benchmark config must be a mapping")
        return cls(
            output_dir=str(payload["output_dir"]),
            source_trace=str(payload["source_trace"]),
            source_method=str(payload["source_method"]),
            expected_families=tuple(str(item) for item in payload["expected_families"]),
            expected_seeds=tuple(int(item) for item in payload["expected_seeds"]),
            stop=dict(payload["stop"]),
            safety=dict(payload["safety"]),
            fault_injection=dict(payload["fault_injection"]),
            publication_gates=dict(payload["publication_gates"]),
            experiment_role=str(payload.get("experiment_role", "main")),
            protocol_frozen_utc=str(payload.get("protocol_frozen_utc", "")),
        )


def _stop_criteria(config: P4BenchmarkConfig) -> StopCriteria:
    stop = config.stop
    return StopCriteria(
        min_trials=int(stop["min_trials"]),
        max_trials=int(stop["max_trials"]),
        max_time_s=float(stop["max_time_s"]),
        max_distance_m=float(stop["max_distance_m"]),
        min_battery_ratio=float(stop["min_battery_ratio"]),
        uncertainty_threshold=float(stop["uncertainty_threshold"]),
        validation_rmse_threshold=float(stop["validation_rmse_threshold"]),
        min_marginal_gain=float(stop["min_marginal_gain"]),
        target_confirmations=int(stop["target_confirmations"]),
        low_gain_patience=int(stop["low_gain_patience"]),
    )


def _safety_envelope(config: P4BenchmarkConfig) -> SafetyEnvelope:
    safety = config.safety
    command_bounds = tuple(
        (float(row[0]), float(row[1])) for row in safety["command_bounds"]
    )
    workspace_bounds = tuple(
        (float(row[0]), float(row[1])) for row in safety["workspace_bounds"]
    )
    return SafetyEnvelope(
        command_bounds=command_bounds,
        max_linear_norm=float(safety["max_linear_norm"]),
        max_coupled_load=float(safety["max_coupled_load"]),
        max_delta_linear=float(safety["max_delta_linear"]),
        max_delta_angular=float(safety["max_delta_angular"]),
        workspace_bounds=workspace_bounds,
        boundary_margin=float(safety["boundary_margin"]),
        max_roll=float(safety["max_roll"]),
        max_pitch=float(safety["max_pitch"]),
        min_base_height=float(safety["min_base_height"]),
        max_base_height=float(safety["max_base_height"]),
        max_abs_yaw_rate=float(safety["max_abs_yaw_rate"]),
        min_battery_ratio=float(safety["min_battery_ratio"]),
    )


def _stop_benchmark(
    trace: pd.DataFrame, config: P4BenchmarkConfig
) -> pd.DataFrame:
    required_columns = {
        "family",
        "method",
        "seed",
        "trial",
        "cmd_vx",
        "cmd_vy",
        "rmse",
        "integrated_uncertainty",
    }
    missing = required_columns - set(trace.columns)
    if missing:
        raise ValueError(f"P4 source trace is missing columns: {sorted(missing)}")
    selected = trace[trace["method"] == config.source_method].copy()
    expected_keys = {
        (family, seed)
        for family in config.expected_families
        for seed in config.expected_seeds
    }
    actual_keys = set(
        selected[["family", "seed"]].itertuples(index=False, name=None)
    )
    if actual_keys != expected_keys:
        raise ValueError("P4 source trace does not contain the frozen run keys")
    criteria = _stop_criteria(config)
    trial_time = float(config.stop["nominal_trial_time_s"])
    distance_scale = float(config.stop["nominal_distance_scale"])
    rows: list[dict[str, Any]] = []
    for (family, seed), group in selected.groupby(["family", "seed"], sort=True):
        ordered = group.sort_values("trial")
        eligible = ordered["trial"].to_numpy(dtype=int) >= criteria.min_trials
        target = (
            eligible
            & (ordered["rmse"].to_numpy(dtype=float) <= criteria.validation_rmse_threshold)
            & (
                ordered["integrated_uncertainty"].to_numpy(dtype=float)
                <= criteria.uncertainty_threshold
            )
        )
        if not np.any(target):
            raise ValueError(f"target is unreachable for {family}/{seed}")
        oracle_trial = int(cast(Any, ordered.loc[target, "trial"].iloc[0]))
        rule = StopRule(criteria)
        stop_trial = criteria.max_trials
        stop_reason = StopReason.TRIAL_BUDGET
        for record in ordered.itertuples(index=False):
            trial = int(cast(Any, record.trial))
            command_norm = float(
                np.hypot(cast(Any, record.cmd_vx), cast(Any, record.cmd_vy))
            )
            decision = rule.evaluate(
                StopMetrics(
                    trial_count=trial,
                    elapsed_s=trial * trial_time,
                    distance_m=distance_scale * command_norm,
                    battery_ratio=1.0,
                    integrated_uncertainty=float(
                        cast(Any, record.integrated_uncertainty)
                    ),
                    validation_rmse=float(cast(Any, record.rmse)),
                    coverage_complete=trial >= criteria.min_trials,
                )
            )
            if decision.stop:
                stop_trial = trial
                stop_reason = decision.reason
                break
        rows.append(
            {
                "family": family,
                "seed": int(cast(Any, seed)),
                "oracle_target_trial": oracle_trial,
                "stop_trial": stop_trial,
                "extra_trials": stop_trial - oracle_trial,
                "premature": stop_trial < oracle_trial,
                "stop_reason": stop_reason.value,
            }
        )
    return pd.DataFrame(rows)


def _state(**changes: object) -> RobotState:
    values: dict[str, object] = {
        "timestamp": 0.0,
        "position_xy": (0.0, 0.0),
        "yaw": 0.0,
        "roll": 0.0,
        "pitch": 0.0,
        "base_height": 0.32,
        "velocity": (0.0, 0.0, 0.0),
        "battery_ratio": 0.85,
        "localization_valid": True,
    }
    values.update(changes)
    return RobotState(**values)  # type: ignore[arg-type]


def _candidate(values: tuple[float, float, float], duration_s: float = 2.0) -> Candidate:
    return Candidate(VelocityCommand(*values, duration_s), 1.0, 1.0, 0.0)


def _fault_cases(
    rng: np.random.Generator,
    envelope: SafetyEnvelope,
) -> list[tuple[str, Candidate, RobotState, list[Candidate], str]]:
    jitter = float(rng.uniform(0.001, 0.01))
    safe = _candidate((0.20, 0.0, 0.20))
    same = [_candidate((0.20, 0.0, 0.20))]
    return [
        ("vx_high", _candidate((envelope.command_bounds[0][1] + jitter, 0.0, 0.0)), _state(), [], "COMMAND_AXIS_0"),
        ("vy_low", _candidate((0.0, envelope.command_bounds[1][0] - jitter, 0.0)), _state(), [], "COMMAND_AXIS_1"),
        ("wz_high", _candidate((0.0, 0.0, envelope.command_bounds[2][1] + jitter)), _state(), [], "COMMAND_AXIS_2"),
        ("linear_norm", _candidate((0.70, 0.45, 0.0)), _state(), [], "LINEAR_NORM"),
        ("coupled", _candidate((0.60, 0.0, 0.90)), _state(), [_candidate((0.60, 0.0, 0.90))], "LINEAR_ANGULAR_COUPLING"),
        ("linear_slew", _candidate((0.60, 0.0, 0.0)), _state(), [_candidate((0.10, 0.0, 0.0))], "LINEAR_SLEW"),
        ("angular_slew", _candidate((0.0, 0.0, 0.90)), _state(), [_candidate((0.0, 0.0, 0.0))], "ANGULAR_SLEW"),
        ("workspace", _candidate((0.20, 0.0, 0.0)), _state(position_xy=(4.5, 0.0)), [], "WORKSPACE_PROJECTED_AXIS_0"),
        ("roll", safe, _state(roll=envelope.max_roll + jitter), same, "ROLL_LIMIT"),
        ("pitch", safe, _state(pitch=-(envelope.max_pitch + jitter)), same, "PITCH_LIMIT"),
        ("height", safe, _state(base_height=envelope.min_base_height - jitter), same, "BASE_HEIGHT_LIMIT"),
        ("yaw_rate", safe, _state(velocity=(0.0, 0.0, envelope.max_abs_yaw_rate + jitter)), same, "YAW_RATE_LIMIT"),
        ("battery", safe, _state(battery_ratio=envelope.min_battery_ratio - jitter), same, "LOW_BATTERY"),
        ("localization", safe, _state(localization_valid=False), same, "LOCALIZATION_INVALID"),
        ("nonfinite", _candidate((float("nan"), 0.0, 0.0)), _state(), [], "COMMAND_NONFINITE"),
    ]


def _fault_benchmark(
    config: P4BenchmarkConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    envelope = _safety_envelope(config)
    filter_ = HardSafetyFilter(envelope)
    replicates = int(config.fault_injection["replicates"])
    rng = np.random.default_rng(int(config.fault_injection["seed"]))
    rows: list[dict[str, Any]] = []
    runtime_rows: list[dict[str, Any]] = []
    safe_candidate = _candidate((0.20, 0.0, 0.20))
    monitor_period = float(config.fault_injection["monitor_period_s"])
    for replicate in range(replicates):
        safe_decision = filter_.evaluate(
            safe_candidate,
            _state(),
            [_candidate((0.20, 0.0, 0.20))],
        )
        rows.append(
            {
                "replicate": replicate,
                "scenario": "safe_control",
                "hazard": False,
                "accepted": safe_decision.accepted,
                "expected_reason": "",
                "reason_codes": "|".join(safe_decision.reason_codes),
            }
        )
        for scenario, candidate, state, history, expected in _fault_cases(rng, envelope):
            decision = filter_.evaluate(candidate, state, history)
            rows.append(
                {
                    "replicate": replicate,
                    "scenario": scenario,
                    "hazard": True,
                    "accepted": decision.accepted,
                    "expected_reason": expected,
                    "reason_codes": "|".join(decision.reason_codes),
                }
            )
        runtime_states = {
            "roll": _state(roll=envelope.max_roll + 0.01),
            "pitch": _state(pitch=envelope.max_pitch + 0.01),
            "height_low": _state(base_height=envelope.min_base_height - 0.01),
            "height_high": _state(base_height=envelope.max_base_height + 0.01),
            "yaw_rate": _state(velocity=(0.0, 0.0, envelope.max_abs_yaw_rate + 0.01)),
            "workspace": _state(position_xy=(5.0, 0.0)),
            "localization": _state(localization_valid=False),
            "battery": _state(battery_ratio=envelope.min_battery_ratio - 0.01),
        }
        for scenario, state in runtime_states.items():
            decision = filter_.monitor(state)
            detection_step = 0 if not decision.accepted else -1
            latency = detection_step * monitor_period if detection_step >= 0 else np.inf
            runtime_rows.append(
                {
                    "replicate": replicate,
                    "scenario": scenario,
                    "detected": not decision.accepted,
                    "abort_latency_s": latency,
                    "reason_codes": "|".join(decision.reason_codes),
                    "serious_event": not decision.accepted
                    and latency > float(config.fault_injection["maximum_abort_latency_s"]),
                }
            )
    faults = pd.DataFrame(rows)
    expected_present = faults.apply(
        lambda row: (
            not bool(row["hazard"])
            or str(row["expected_reason"]) in str(row["reason_codes"]).split("|")
        ),
        axis=1,
    )
    faults["expected_reason_present"] = expected_present
    return faults, pd.DataFrame(runtime_rows)


def _state_machine_trace() -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    happy = TrialStateMachine()
    for event in (
        RuntimeEvent.PRECHECK_PASSED,
        RuntimeEvent.RAMP_REACHED,
        RuntimeEvent.SETTLED,
        RuntimeEvent.MEASUREMENT_COMPLETE,
        RuntimeEvent.RAMPED_OUT,
        RuntimeEvent.OBSERVATION_VALID,
        RuntimeEvent.MODEL_UPDATED,
        RuntimeEvent.STOP,
    ):
        happy.apply(event)
    fault = TrialStateMachine()
    fault.apply(RuntimeEvent.PRECHECK_PASSED)
    fault.apply(RuntimeEvent.RAMP_REACHED)
    fault.apply(RuntimeEvent.SAFETY_TRIGGER, "ROLL_LIMIT")
    for run_id, machine in (("happy", happy), ("fault", fault)):
        for transition in machine.transitions:
            records.append(
                {
                    "run_id": run_id,
                    "index": transition.index,
                    "source": transition.source.value,
                    "target": transition.target.value,
                    "event": transition.event.value,
                    "reason": transition.reason,
                }
            )
    return pd.DataFrame(records)


def _git_commit(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def run_p4_suite(config_path: Path, workspace: Path | None = None) -> dict[str, Any]:
    root = (workspace or Path.cwd()).resolve()
    config = P4BenchmarkConfig.from_yaml(config_path)
    source = root / config.source_trace
    trace = pd.read_csv(source)
    stop_results = _stop_benchmark(trace, config)
    faults, runtime_faults = _fault_benchmark(config)
    state_trace = _state_machine_trace()

    premature_rate = float(stop_results["premature"].mean())
    median_extra = float(stop_results["extra_trials"].median())
    p95_extra = float(stop_results["extra_trials"].quantile(0.95))
    hazards = faults[faults["hazard"]]
    safe = faults[~faults["hazard"]]
    hazard_rejection = float((~hazards["accepted"]).mean())
    safe_false_rejection = float((~safe["accepted"]).mean())
    expected_reason_rate = float(hazards["expected_reason_present"].mean())
    maximum_abort_latency = float(runtime_faults["abort_latency_s"].max())
    serious_events = int(runtime_faults["serious_event"].sum())
    gates = config.publication_gates
    gate_results = {
        "stop_all_runs_reached": len(stop_results)
        == len(config.expected_families) * len(config.expected_seeds),
        "premature_stop": premature_rate
        < float(gates["maximum_premature_stop_rate"]),
        "median_extra_trials": median_extra
        <= float(gates["maximum_median_extra_trials"]),
        "p95_extra_trials": p95_extra
        <= float(gates["maximum_p95_extra_trials"]),
        "hazard_rejection": hazard_rejection
        >= float(gates["minimum_hazard_rejection_rate"]),
        "expected_reason_coverage": expected_reason_rate == 1.0,
        "safe_false_rejection": safe_false_rejection
        <= float(gates["maximum_safe_false_rejection_rate"]),
        "abort_latency": maximum_abort_latency
        <= float(config.fault_injection["maximum_abort_latency_s"]),
        "serious_events": serious_events <= int(gates["maximum_serious_events"]),
    }
    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "verdict": "GO" if all(gate_results.values()) else "NO_GO",
        "stop_runs": len(stop_results),
        "premature_stop_rate": premature_rate,
        "median_extra_trials": median_extra,
        "p95_extra_trials": p95_extra,
        "fault_cases": len(hazards),
        "hazard_rejection_rate": hazard_rejection,
        "expected_reason_rate": expected_reason_rate,
        "safe_false_rejection_rate": safe_false_rejection,
        "runtime_fault_cases": len(runtime_faults),
        "maximum_abort_latency_s": maximum_abort_latency,
        "serious_events": serious_events,
        "gates": gate_results,
    }

    output = root / config.output_dir
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "stop_results": output / "stop_results.csv",
        "fault_injection": output / "fault_injection.csv",
        "runtime_faults": output / "runtime_faults.csv",
        "state_machine_trace": output / "state_machine_trace.csv",
        "summary": output / "summary.json",
        "resolved_config": output / "resolved_config.json",
    }
    stop_results.to_csv(paths["stop_results"], index=False)
    faults.to_csv(paths["fault_injection"], index=False)
    runtime_faults.to_csv(paths["runtime_faults"], index=False)
    state_trace.to_csv(paths["state_machine_trace"], index=False)
    paths["summary"].write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    paths["resolved_config"].write_text(
        json.dumps(asdict(config), indent=2, sort_keys=True), encoding="utf-8"
    )
    artifacts = {
        name: {
            "path": path.name,
            "sha256": file_sha256(path),
        }
        for name, path in paths.items()
    }
    resolved_config_path = config_path.resolve()
    config_reference = (
        str(resolved_config_path.relative_to(root))
        if resolved_config_path.is_relative_to(root)
        else str(resolved_config_path)
    )
    manifest = {
        "schema_version": "1.0",
        "phase": "P4",
        "backend": "frozen_p3_replay_and_fault_injection",
        "git_commit": _git_commit(root),
        "config_path": config_reference,
        "config_sha256": file_sha256(config_path),
        "source_trace": config.source_trace,
        "source_trace_sha256": file_sha256(source),
        "artifacts": artifacts,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary
