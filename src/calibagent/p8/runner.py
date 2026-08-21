"""Complete P8-NAV and P8-SHIFT experiment state machines."""

import contextlib
import csv
import hashlib
import json
import shutil
import time
from pathlib import Path

import numpy as np

from calibagent.p8.backend import FakeBackend, Go2RosBackend
from calibagent.p8.config import (
    MAP_IDS,
    NAV_METHOD_COUNTS,
    NAV_METHODS,
    SHIFT_IDS,
    SHIFT_METHODS,
    read_csv,
    read_yaml,
    validate_config,
)
from calibagent.p8.model import VelocityModel
from calibagent.p8.planning import (
    ActiveSelector,
    CalibrationTransform,
    CommandTable,
    ResidualDetector,
)
from calibagent.p8.recording import (
    BagSession,
    RunRecorder,
    git_commit,
    next_bag_path,
    write_manifest,
)


def _utc():  # type: () -> str
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _hash_runtime_path(path):  # type: (Path) -> Dict[str, Any]
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError("runtime artifact not found: {}".format(path))
    digest = hashlib.sha256()
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    total_size = 0
    for item in files:
        relative = item.name if path.is_file() else item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8") + b"\0")
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                total_size += len(chunk)
    return {
        "path": str(path),
        "sha256": digest.hexdigest(),
        "file_count": len(files),
        "size_bytes": total_size,
    }


def _runtime_artifact_hashes(payload):  # type: (Dict[str, Any]) -> Dict[str, Dict[str, Any]]
    return {
        str(name): _hash_runtime_path(Path(value))
        for name, value in payload.get("runtime_artifacts", {}).items()
    }


def _run_has_completed_units(run_dir):  # type: (Path) -> bool
    statuses = {
        "trials.csv": {"SUCCESS"},
        "navigation_episodes.csv": {"SUCCESS", "RESULT"},
        "shift_sequences.csv": {"SUCCESS"},
    }
    for name, completed in statuses.items():
        path = run_dir / name
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8", newline="") as stream:
            if any(row.get("status") in completed for row in csv.DictReader(stream)):
                return True
    return False


class P8Runtime:
    def __init__(
        self,
        config,
        run_id,
        output_root,
        backend_name="fake",
        arm=False,
        resume=False,
        overwrite=False,
        auto_continue=False,
        max_units=None,
    ):
        # type: (ResolvedConfig, str, Path, str, bool, bool, bool, bool, Optional[int]) -> None
        self.config = config
        self.run_id = run_id
        self.output_root = output_root.expanduser().resolve()
        self.backend_name = backend_name
        if not run_id or Path(run_id).name != run_id or run_id in (".", ".."):
            raise ValueError("run ID must be one non-empty directory name")
        self.run_dir = (self.output_root / run_id).resolve()
        try:
            self.run_dir.relative_to(self.output_root)
        except ValueError as exc:
            raise ValueError("run directory must be directly inside output root") from exc
        if resume and overwrite:
            raise ValueError("--resume and --overwrite are mutually exclusive")
        self.code_commit = git_commit(Path(__file__).resolve().parents[3])
        self.code_migration = None
        self.config_migration = None
        if self.run_dir.exists():
            if overwrite:
                if not self.run_dir.is_dir() or self.run_dir.is_symlink():
                    raise RuntimeError(
                        "refusing to overwrite a non-directory or symbolic-link run path: "
                        f"{self.run_dir}"
                    )
                shutil.rmtree(self.run_dir)
            elif not resume:
                raise FileExistsError(
                    f"run directory exists; use --resume or --overwrite: {self.run_dir}"
                )
        self.previous_manifest = {}
        manifest_path = self.run_dir / "manifest.json"
        if manifest_path.is_file():
            self.previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            previous_config_hash = self.previous_manifest.get("config_hash")
            if previous_config_hash != self.config.config_hash:
                if _run_has_completed_units(self.run_dir):
                    raise RuntimeError(
                        "resume config hash differs after completed experimental units; use the "
                        "original configuration"
                    )
                self.config_migration = {
                    "from_hash": previous_config_hash,
                    "to_hash": self.config.config_hash,
                    "reason": "technical fix before the first valid experimental unit",
                    "timestamp": _utc(),
                }
            previous_commit = self.previous_manifest.get("git_commit")
            if previous_commit and previous_commit != self.code_commit:
                if _run_has_completed_units(self.run_dir):
                    raise RuntimeError(
                        "resume code commit differs after completed experimental units; use the "
                        "original commit"
                    )
                self.code_migration = {
                    "from_commit": previous_commit,
                    "to_commit": self.code_commit,
                    "reason": "technical fix before the first valid experimental unit",
                    "timestamp": _utc(),
                }
        self.runtime_artifacts = (
            _runtime_artifact_hashes(self.config.payload) if backend_name == "ros" else {}
        )
        previous_runtime = self.previous_manifest.get("runtime_artifacts")
        if previous_runtime is not None and previous_runtime != self.runtime_artifacts:
            raise RuntimeError("resume runtime map/relocation artifacts differ from run manifest")
        self.recorder = RunRecorder(self.run_dir, run_id)
        self.resume = bool(resume)
        self.auto_continue = bool(auto_continue)
        self.max_units = max_units
        self.units = 0
        payload = dict(config.payload)
        topic_payload = read_yaml(config.files["topic_map"])
        payload["topics"] = topic_payload["topics"]
        payload["quality"] = dict(payload.get("quality", {}))
        self.backend = (
            FakeBackend(payload, self.recorder.trace)
            if backend_name == "fake"
            else Go2RosBackend(payload, self.recorder.trace, arm=arm)
        )
        self.arm = bool(arm)
        self.tables = {
            key: CommandTable(path)
            for key, path in config.files.items()
            if key
            in (
                "candidate_pool",
                "dense_design",
                "lhs_design",
                "sobol_design",
                "random_design",
                "active_seed",
                "validation_commands",
                "task_distribution",
                "pre_calibration",
                "monitor_commands",
                "passive_recovery",
                "recovery_validation",
                "restore_checks",
            )
        }
        self.pool = self.tables["candidate_pool"]
        self.task = self.tables["task_distribution"]
        inverse = payload.get("calibration_transform", {})
        self.transform = CalibrationTransform(
            self.pool, inverse.get("regularization", 0.02), inverse.get("risk_weight", 0.05)
        )
        self.selector = ActiveSelector(self.pool, self.task)
        self.profile = dict(payload["trial_profile"])
        self.profile["command_rate_hz"] = float(payload.get("command_rate_hz", 50.0))
        self._initialize_artifacts()

    def _initialize_artifacts(self):  # type: () -> None
        self.config.save(self.run_dir / "configs")
        shutil.copy2(str(self.config.path), str(self.run_dir / "configs" / "source_config.yaml"))
        for key, path in self.config.files.items():
            shutil.copy2(str(path), str(self.run_dir / "configs" / (key + path.suffix)))
        schedule_key = "nav_schedule" if self.config.payload["protocol"] == "nav" else "shift_schedule"
        shutil.copy2(str(self.config.files[schedule_key]), str(self.run_dir / "schedule.csv"))
        manifest_path = self.run_dir / "manifest.json"
        previous = self.previous_manifest
        code_history = list(previous.get("code_history", []))
        if self.code_migration is not None:
            code_history.append(self.code_migration)
        config_history = list(previous.get("config_history", []))
        if self.config_migration is not None:
            config_history.append(self.config_migration)
        manifest = dict(previous)
        manifest.update(
            {
                "schema": "calibagent.p8.real.v1",
                "run_id": self.run_id,
                "protocol": self.config.payload["protocol"],
                "created_at": previous.get("created_at", _utc()),
                "last_opened_at": _utc(),
                "git_commit": self.code_commit,
                "code_history": code_history,
                "config_history": config_history,
                "config_hash": self.config.config_hash,
                "input_hashes": self.config.hashes,
                "backend": self.backend_name,
                "armed": self.arm,
                "robot": self.config.payload.get("robot", {}),
                "runtime_artifacts": self.runtime_artifacts,
                "command_chain": "DCLP planner -> optional CalibAgent calibration transform -> direct Unitree Sport Move",
                "locomotion_interventions": [],
            }
        )
        write_manifest(manifest_path, manifest)

    def _new_model(self, feature_set):  # type: (str) -> VelocityModel
        model_cfg = self.config.payload.get("model", {})
        return VelocityModel(
            feature_set,
            self.pool.commands,
            prior_scale=float(model_cfg.get("prior_scale", 1.0)),
            noise_variance=model_cfg.get("noise_variance", [0.0025, 0.0025, 0.005]),
        )

    def _limit_reached(self):  # type: () -> bool
        return self.max_units is not None and self.units >= self.max_units

    def _pause(self, message):  # type: (str) -> None
        if self.backend_name == "ros" and not self.auto_continue:
            input(message + " Press Enter to continue: ")

    def _previous_trial_rows(self, prefix):  # type: (str) -> List[Dict[str, str]]
        return [
            row
            for row in self.recorder.trials.rows()
            if row.get("planned_unit_id", "").startswith(prefix)
        ]

    def _successful_trial_row(self, planned_unit_id):  # type: (str) -> Optional[Dict[str, str]]
        rows = [
            row
            for row in self.recorder.trials.rows()
            if row.get("planned_unit_id") == planned_unit_id and row.get("status") == "SUCCESS"
        ]
        return rows[-1] if rows else None

    def _completed_episode_row(self, planned_unit_id, route):
        # type: (str, Dict[str, Any]) -> Optional[Dict[str, str]]
        expected_goal_count = len(route.get("waypoints", [])) + 1
        expected_waypoints = len(route.get("waypoints", []))
        goal_radius = float(
            route.get(
                "goal_radius_m",
                self.config.payload.get("navigation", {}).get("goal_radius_m", 0.25),
            )
        )
        rows = [
            row
            for row in self.recorder.episodes.rows()
            if row.get("planned_unit_id") == planned_unit_id
        ]
        for row in reversed(rows):
            if row.get("status") == "RESULT":
                return row
            if row.get("status") != "SUCCESS":
                continue
            try:
                consistent = bool(
                    row.get("success", "").lower() in ("1", "true")
                    and row.get("data_quality_valid", "").lower() in ("1", "true")
                    and row.get("collision", "").lower() not in ("1", "true")
                    and row.get("terminal_reason") == "reached"
                    and int(row.get("route_goal_count", "")) == expected_goal_count
                    and int(row.get("waypoints_reached", "")) == expected_waypoints
                    and float(row.get("final_goal_distance_m", "inf")) <= goal_radius
                )
            except (TypeError, ValueError):
                consistent = False
            if consistent:
                return row
        return None

    def _restore_model(self, model, prefix):  # type: (VelocityModel, str) -> Tuple[VelocityModel, List[np.ndarray]]
        rows = [
            row
            for row in self._previous_trial_rows(prefix)
            if row.get("stage") in ("calibration", "pre_calibration", "recovery")
            and row.get("status") == "SUCCESS"
            and row.get("update_applied", "").lower() == "true"
        ]
        history = []  # type: List[np.ndarray]
        latest = None
        for row in rows:
            with contextlib.suppress(ValueError, TypeError, json.JSONDecodeError):
                history.append(np.asarray(json.loads(row["planned_command"]), dtype=np.float64))
            if row.get("posterior_path"):
                candidate = Path(row["posterior_path"])
                if candidate.is_file():
                    latest = candidate
        return (VelocityModel.load(latest) if latest else model), history

    def _restore_detector(self, detector, prefix):  # type: (ResidualDetector, str) -> None
        for row in self._previous_trial_rows(prefix):
            if row.get("status") != "SUCCESS" or row.get("stage") not in (
                "pre_monitor",
                "post_monitor",
            ):
                continue
            with contextlib.suppress(ValueError, TypeError):
                statistic = float(row.get("detector_statistic", ""))
                detector.run = detector.run + 1 if statistic >= detector.threshold else 0
                alarm = str(row.get("detector_alarm", "")).lower() == "true"
                if alarm and not detector.alarm:
                    detector.alarm = True
                    detector.first_alarm_index = int(row.get("trial_index", 0))

    def _trial(
        self,
        base,
        stage,
        trial_index,
        command_id,
        command,
        model,
        update_enabled,
        adapter_matrix=None,
        detector=None,
        recovery_index=None,
    ):
        # type: (Dict[str, Any], str, int, str, Sequence[float], VelocityModel, bool, Optional[Sequence[Sequence[float]]], Optional[ResidualDetector], Optional[int]) -> Dict[str, Any]
        planned_unit_id = f"{base['planned_unit_id']}_{stage.upper()}_{trial_index:02d}"
        completed = self.recorder.completed("trial")
        if planned_unit_id in completed:
            rows = [
                row
                for row in self.recorder.trials.rows()
                if row.get("planned_unit_id") == planned_unit_id
            ]
            return {"skipped": True, "row": rows[-1] if rows else {}}
        attempt_id = self.recorder.attempt_id(planned_unit_id, "trial")
        identity = dict(
            base,
            planned_unit_id=planned_unit_id,
            attempt_id=attempt_id,
            stage=stage,
            trial_index=trial_index,
            command_id=command_id,
        )
        before = model.posterior_version
        prediction, _ = model.predict(command)
        result = self.backend.execute_trial(
            identity, command, self.profile, adapter_matrix=adapter_matrix
        )
        update_applied = bool(update_enabled and result["valid"])
        if update_applied:
            model.update(
                command,
                result["measured_velocity"],
                np.asarray(result["covariance"], dtype=np.float64),
            )
        posterior_path = (
            self.run_dir / "posterior" / (planned_unit_id + f"_v{model.posterior_version:04d}.npz")
        )
        model.save(posterior_path)
        detector_statistic = ""
        detector_alarm = ""
        if detector is not None and result["valid"]:
            detector_statistic, detector_alarm = detector.observe(
                command,
                result["measured_velocity"],
                np.asarray(result["covariance"]),
                model,
                trial_index,
            )
        validation_rmse = ""
        if stage in ("validation", "recovery_validation", "restore_check") and result["valid"]:
            residual = np.asarray(result["measured_velocity"]) - prediction
            validation_rmse = float(np.sqrt(np.mean(residual**2)))
        row = dict(
            identity,
            planned_command=result["planned_command"],
            sent_command=result["sent_command"],
            measured_velocity=result["measured_velocity"],
            covariance=result["covariance"],
            valid=result["valid"],
            reason=result["reason"],
            update_enabled=update_enabled,
            update_applied=update_applied,
            posterior_before=before,
            posterior_after=model.posterior_version,
            posterior_path=str(posterior_path),
            measure_start=result["measure_start"],
            measure_end=result["measure_end"],
            sample_count=result["sample_count"],
            reference_max_age_ms=result["reference_max_age_ms"],
            reference_max_gap_ms=result["reference_max_gap_ms"],
            scan_max_age_ms=result["scan_max_age_ms"],
            scan_max_gap_ms=result["scan_max_gap_ms"],
            detector_statistic=detector_statistic,
            detector_alarm=detector_alarm,
            recovery_index=recovery_index or "",
            validation_rmse=validation_rmse,
            bag_path=base.get("bag_path", ""),
            status="SUCCESS" if result["valid"] else "INVALID",
            terminal_reason=result["terminal_reason"],
            created_at=_utc(),
        )
        self.recorder.trace.write(
            dict(
                identity,
                event="trial_quality",
                reference_max_age_ms=result["reference_max_age_ms"],
                reference_max_gap_ms=result["reference_max_gap_ms"],
                scan_max_age_ms=result["scan_max_age_ms"],
                scan_max_gap_ms=result["scan_max_gap_ms"],
                timestamp=time.time(),
            )
        )
        self.recorder.trials.append(row)
        self.units += 1
        if not result["valid"]:
            raise RuntimeError(
                "trial {} produced an invalid observation ({}); fix the data chain and resume "
                "the same run-id".format(planned_unit_id, result["reason"])
            )
        return {"skipped": False, "row": row, "result": result}

    def _fixed_selection(self, method, index):  # type: (str, int) -> Tuple[str, np.ndarray, str, List[Dict[str, object]]]
        if method == "B1_dense":
            table, kind = self.tables["dense_design"], "dense_fixed"
        elif method == "B2_lhs":
            table, kind = self.tables["lhs_design"], "lhs_fixed"
        elif method == "B3_sobol":
            table, kind = self.tables["sobol_design"], "sobol_fixed"
        elif method == "B6_random":
            table, kind = self.tables["random_design"], "random_fixed"
        else:
            table, kind = self.tables["active_seed"], "active_seed"
        return table.ids[index], table.commands[index], kind, []

    def _nav_selection(self, method, index, model, history):
        # type: (str, int, VelocityModel, List[np.ndarray]) -> Tuple[str, np.ndarray, str, List[Dict[str, object]]]
        if method in ("B1_dense", "B2_lhs", "B3_sobol", "B6_random") or (
            index < 6 and method in ("B5_active_no_task", "B8_full")
        ):
            return self._fixed_selection(method, index)
        kind = (
            "d_opt"
            if method == "B4_d_opt"
            else "uniform_ivr"
            if method == "B5_active_no_task"
            else "task_ivr"
        )
        pool_index, diagnostics = self.selector.select(model, history, kind)
        return self.pool.ids[pool_index], self.pool.commands[pool_index], kind, diagnostics

    def run_nav(self, blocks=None, methods=None, routes=None):
        # type: (Optional[Sequence[str]], Optional[Sequence[str]], Optional[Sequence[str]]) -> Dict[str, Any]
        if self.config.payload["protocol"] != "nav":
            raise ValueError("NAV runner requires nav config")
        validate_config(self.config)
        schedule = read_csv(self.config.files["nav_schedule"])
        selected_blocks = set(blocks or [])
        selected_methods = set(methods or NAV_METHODS)
        selected_routes = {str(value).upper() for value in (routes or ("A", "B"))}
        invalid_routes = selected_routes.difference(("A", "B"))
        if invalid_routes:
            raise ValueError("unknown NAV route letters: {}".format(sorted(invalid_routes)))
        schedule = [
            row
            for row in schedule
            if (not selected_blocks or row["block_id"] in selected_blocks)
            and row["method_id"] in selected_methods
        ]
        routes = {map_id: read_yaml(self.config.files[map_id]) for map_id in MAP_IDS}
        map_by_letter = {"A": "real_offset_slalom", "B": "real_weighted_arc"}
        bags = list(self.config.payload.get("recording", {}).get("bag_topics", []))
        for schedule_row in schedule:
            if self._limit_reached():
                break
            block_id, method = schedule_row["block_id"], schedule_row["method_id"]
            base_id = f"{block_id}_{method}"
            bag_output = next_bag_path(self.run_dir / "bags", base_id)
            with BagSession(
                bag_output,
                bags,
                self.backend_name == "ros"
                and bool(self.config.payload.get("recording", {}).get("rosbag", True)),
            ) as bag:
                base = {
                    "run_id": self.run_id,
                    "planned_unit_id": base_id,
                    "block_id": block_id,
                    "method_id": method,
                    "map_id": "",
                    "shift_id": "",
                    "bag_path": bag.path,
                }
                model, history = self._restore_model(self._new_model("m1_affine"), base_id)
                for index in range(NAV_METHOD_COUNTS[method]):
                    if self._limit_reached():
                        break
                    planned_unit_id = "{}_CALIBRATION_{:02d}".format(base_id, index + 1)
                    if self._successful_trial_row(planned_unit_id) is not None:
                        continue
                    command_id, command, kind, diagnostics = self._nav_selection(
                        method, index, model, history
                    )
                    for diagnostic in diagnostics:
                        self.recorder.decisions.write(
                            dict(
                                base,
                                event="calibration_selection",
                                trial_index=index + 1,
                                planning_kind=kind,
                                **diagnostic,
                            )
                        )
                    self._trial(base, "calibration", index + 1, command_id, command, model, True)
                    history.append(np.asarray(command).copy())
                final_posterior = self.run_dir / "posterior" / (base_id + "_final.npz")
                model.save(final_posterior)
                for index, command in enumerate(self.tables["validation_commands"].commands):
                    if self._limit_reached():
                        break
                    self._trial(
                        base,
                        "validation",
                        index + 1,
                        self.tables["validation_commands"].ids[index],
                        command,
                        model,
                        False,
                    )
                if self._limit_reached():
                    continue
                execution_route_order = "".join(
                    letter for letter in schedule_row["route_order"] if letter in selected_routes
                )
                self.recorder.trace.write(
                    dict(
                        base,
                        event="route_phase_selection",
                        scheduled_route_order=schedule_row["route_order"],
                        execution_route_order=execution_route_order,
                        timestamp=time.time(),
                    )
                )
                for letter in execution_route_order:
                    if self._limit_reached():
                        break
                    map_id = map_by_letter[letter]
                    planned_unit_id = f"{base_id}_NAV_{map_id}"
                    if self._completed_episode_row(planned_unit_id, routes[map_id]) is not None:
                        continue
                    attempt_id = self.recorder.attempt_id(planned_unit_id, "episode")
                    identity = dict(
                        base, planned_unit_id=planned_unit_id, attempt_id=attempt_id, map_id=map_id
                    )
                    self._pause(
                        f"Place the robot at the marked start for {block_id}/{map_id}. "
                        "First confirmation triggers localization only."
                    )
                    start_localization = self.backend.converge_route_start(
                        identity, routes[map_id]
                    )
                    self._pause(
                        "Route-start localization converged: position error "
                        "{:.3f} m, yaw error {:.2f} deg. Second confirmation starts DCLP.".format(
                            float(start_localization["position_error_m"]),
                            float(start_localization["yaw_error_deg"]),
                        )
                    )
                    summary = self.backend.run_navigation(
                        identity,
                        routes[map_id],
                        model,
                        self.transform,
                        raw_method=method == "B0_raw",
                        timeout_s=float(self.config.payload["navigation"]["timeout_s"]),
                    )
                    row = dict(
                        identity,
                        route_order=execution_route_order,
                        posterior_path=str(final_posterior),
                        bag_path=bag.path,
                        created_at=_utc(),
                        start_pose_error_m=start_localization["position_error_m"],
                        start_yaw_error_deg=start_localization["yaw_error_deg"],
                        start_reference_age_ms=start_localization["reference_age_ms"],
                        start_scan_age_ms=start_localization["scan_age_ms"],
                        start_stable_samples=start_localization["stable_samples"],
                        **summary,
                    )
                    self.recorder.episodes.append(row)
                    self.units += 1
                    if not summary.get("data_quality_valid", False):
                        raise RuntimeError(
                            "episode {} failed data quality ({}); "
                            "fix the data chain and resume the same run-id".format(
                                planned_unit_id,
                                summary.get("data_quality_reason", "unknown reason"),
                            )
                        )
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "units_executed": self.units,
            "completed_trials": len(self.recorder.completed("trial")),
            "completed_episodes": len(self.recorder.completed("episode")),
        }

    def _shift_matrix(self, shift_id):  # type: (str) -> Optional[Sequence[Sequence[float]]]
        definitions = read_yaml(self.config.files["shift_definitions"])["shifts"]
        return (
            definitions[shift_id].get("command_matrix")
            if shift_id == "R1_command_gain_coupling"
            else None
        )

    def run_shift(self, shifts=None, blocks=None, methods=None):
        # type: (Optional[Sequence[str]], Optional[Sequence[str]], Optional[Sequence[str]]) -> Dict[str, Any]
        if self.config.payload["protocol"] != "shift":
            raise ValueError("SHIFT runner requires shift config")
        validate_config(self.config)
        selected_shifts = set(shifts or SHIFT_IDS)
        selected_blocks = set(blocks or [])
        selected_methods = set(methods or SHIFT_METHODS)
        schedule = [
            row
            for row in read_csv(self.config.files["shift_schedule"])
            if row["shift_id"] in selected_shifts
            and row["method_id"] in selected_methods
            and (not selected_blocks or row["block_id"] in selected_blocks)
        ]
        bags = list(self.config.payload.get("recording", {}).get("bag_topics", []))
        detector_cfg = self.config.payload.get("detector", {})
        for schedule_row in schedule:
            if self._limit_reached():
                break
            shift_id, block_id, method = (
                schedule_row["shift_id"],
                schedule_row["block_id"],
                schedule_row["method_id"],
            )
            sequence_id = f"{shift_id}_{block_id}_{method}"
            if sequence_id in self.recorder.completed("sequence"):
                continue
            bag_output = next_bag_path(self.run_dir / "bags", sequence_id)
            with BagSession(
                bag_output,
                bags,
                self.backend_name == "ros"
                and bool(self.config.payload.get("recording", {}).get("rosbag", True)),
            ) as bag:
                base = {
                    "run_id": self.run_id,
                    "planned_unit_id": sequence_id,
                    "block_id": block_id,
                    "method_id": method,
                    "map_id": "",
                    "shift_id": shift_id,
                    "bag_path": bag.path,
                }
                model, history = self._restore_model(
                    self._new_model("m2_affine_cross_hinge"), sequence_id
                )
                detector = ResidualDetector(
                    float(detector_cfg.get("threshold", 3.5)),
                    int(detector_cfg.get("consecutive", 2)),
                )
                self._restore_detector(detector, sequence_id)
                for index, command in enumerate(self.tables["pre_calibration"].commands):
                    if self._limit_reached():
                        break
                    planned_unit_id = "{}_PRE_CALIBRATION_{:02d}".format(
                        sequence_id, index + 1
                    )
                    if self._successful_trial_row(planned_unit_id) is not None:
                        continue
                    outcome = self._trial(
                        base,
                        "pre_calibration",
                        index + 1,
                        self.tables["pre_calibration"].ids[index],
                        command,
                        model,
                        True,
                    )
                    if not outcome["skipped"]:
                        history.append(command.copy())
                for index in range(4):
                    if self._limit_reached():
                        break
                    self._trial(
                        base,
                        "pre_monitor",
                        index + 1,
                        self.tables["monitor_commands"].ids[index],
                        self.tables["monitor_commands"].commands[index],
                        model,
                        False,
                        detector=detector,
                    )
                if self._limit_reached():
                    continue
                shift_matrix = self._shift_matrix(shift_id)
                shifted_ids = [
                    "{}_POST_MONITOR_{:02d}".format(sequence_id, index + 1)
                    for index in range(5)
                ] + [
                    "{}_{}_{:02d}".format(sequence_id, stage, index + 1)
                    for index in range(12)
                    for stage in ("RECOVERY", "RECOVERY_VALIDATION")
                ]
                need_shift_trials = any(
                    self._successful_trial_row(planned_id) is None
                    for planned_id in shifted_ids
                )
                if need_shift_trials and shift_id != "R1_command_gain_coupling":
                    self._pause(f"Apply and record physical shift {shift_id} for {sequence_id}.")
                if need_shift_trials:
                    self.recorder.trace.write(
                        dict(
                            base,
                            event="shift_applied",
                            shift_id=shift_id,
                            command_matrix=shift_matrix,
                            timestamp=time.time(),
                        )
                    )
                inflated = bool(
                    method == "full"
                    and detector.alarm
                    and any(
                        row.get("status") == "SUCCESS" and row.get("stage") == "recovery"
                        for row in self._previous_trial_rows(sequence_id)
                    )
                )
                partial = False
                for offset in range(5):
                    if self._limit_reached():
                        partial = True
                        break
                    index = offset + 4
                    self._trial(
                        base,
                        "post_monitor",
                        offset + 1,
                        self.tables["monitor_commands"].ids[index],
                        self.tables["monitor_commands"].commands[index],
                        model,
                        False,
                        adapter_matrix=shift_matrix,
                        detector=detector,
                    )
                    if method == "full" and detector.alarm and not inflated:
                        model.inflate(
                            float(
                                self.config.payload.get("adaptation", {}).get(
                                    "covariance_inflation", 4.0
                                )
                            )
                        )
                        inflated = True
                if partial:
                    continue
                for index in range(12):
                    if self._limit_reached():
                        partial = True
                        break
                    recovery_id = "{}_RECOVERY_{:02d}".format(sequence_id, index + 1)
                    existing_recovery = self._successful_trial_row(recovery_id)
                    if existing_recovery is not None:
                        command_id = existing_recovery["command_id"]
                        command = np.asarray(
                            json.loads(existing_recovery["planned_command"]), dtype=np.float64
                        )
                    elif method == "full":
                        pool_index, diagnostics = self.selector.select(model, history, "task_ivr")
                        command_id, command = (
                            self.pool.ids[pool_index],
                            self.pool.commands[pool_index],
                        )
                        for diagnostic in diagnostics:
                            self.recorder.decisions.write(
                                dict(
                                    base,
                                    event="recovery_selection",
                                    recovery_index=index + 1,
                                    **diagnostic,
                                )
                            )
                    else:
                        command_id = self.tables["passive_recovery"].ids[index]
                        command = self.tables["passive_recovery"].commands[index]
                    outcome = self._trial(
                        base,
                        "recovery",
                        index + 1,
                        command_id,
                        command,
                        model,
                        update_enabled=method in ("passive", "full"),
                        adapter_matrix=shift_matrix,
                        recovery_index=index + 1,
                    )
                    if not outcome["skipped"]:
                        history.append(command.copy())
                    if self._limit_reached():
                        partial = True
                        break
                    validation_command = self.tables["recovery_validation"].commands[index]
                    self._trial(
                        base,
                        "recovery_validation",
                        index + 1,
                        self.tables["recovery_validation"].ids[index],
                        validation_command,
                        model,
                        False,
                        adapter_matrix=shift_matrix,
                        recovery_index=index + 1,
                    )
                if partial or self._limit_reached():
                    continue
                if shift_id != "R1_command_gain_coupling":
                    self._pause(f"Restore nominal physical context after {sequence_id}.")
                self.recorder.trace.write(dict(base, event="shift_restored", timestamp=time.time()))
                for index, command in enumerate(self.tables["restore_checks"].commands):
                    if self._limit_reached():
                        partial = True
                        break
                    self._trial(
                        base,
                        "restore_check",
                        index + 1,
                        self.tables["restore_checks"].ids[index],
                        command,
                        model,
                        False,
                    )
                if partial or self._limit_reached():
                    continue
                final_posterior = self.run_dir / "posterior" / (sequence_id + "_final.npz")
                model.save(final_posterior)
                attempt_id = self.recorder.attempt_id(sequence_id, "sequence")
                self.recorder.sequences.append(
                    dict(
                        base,
                        attempt_id=attempt_id,
                        status="SUCCESS",
                        alarm=detector.alarm,
                        detection_index=detector.first_alarm_index or "",
                        posterior_path=str(final_posterior),
                        bag_path=bag.path,
                        created_at=_utc(),
                    )
                )
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "units_executed": self.units,
            "completed_trials": len(self.recorder.completed("trial")),
            "completed_sequences": len(self.recorder.completed("sequence")),
        }

    def io_check(self, duration_s):  # type: (float) -> Dict[str, Any]
        return self.backend.io_check(duration_s)

    def close(self):  # type: () -> None
        try:
            self.backend.close()
        finally:
            self.recorder.close()
