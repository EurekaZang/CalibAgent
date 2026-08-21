"""Configuration loading, hashing, and protocol validation for P8."""

import csv
import hashlib
import json
from pathlib import Path

import yaml

NAV_METHOD_COUNTS = {
    "B0_raw": 0,
    "B1_dense": 30,
    "B2_lhs": 12,
    "B3_sobol": 12,
    "B4_d_opt": 12,
    "B5_active_no_task": 12,
    "B6_random": 12,
    "B8_full": 12,
}
NAV_METHODS = tuple(NAV_METHOD_COUNTS)
SHIFT_METHODS = ("frozen", "passive", "full")
SHIFT_IDS = (
    "R1_command_gain_coupling",
    "R2_payload_com",
    "R3_surface_friction",
    "R4_mixed_context",
)
MAP_IDS = ("real_offset_slalom", "real_weighted_arc")


def sha256_file(path):  # type: (Path) -> str
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value):  # type: (Any) -> str
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_yaml(path):  # type: (Path) -> Dict[str, Any]
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream) or {}
    if not isinstance(value, dict):
        raise ValueError(f"configuration root must be a mapping: {path}")
    return value


def read_csv(path):  # type: (Path) -> List[Dict[str, str]]
    with path.open("r", encoding="utf-8", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _resolve(root, value):  # type: (Path, str) -> Path
    path = Path(value).expanduser()
    return path if path.is_absolute() else (root / path).resolve()


def _require_keys(payload, keys, label):  # type: (Mapping[str, Any], Iterable[str], str) -> None
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValueError("{} missing keys: {}".format(label, ", ".join(missing)))


def _unique(rows, field, label):  # type: (List[Dict[str, str]], str, str) -> None
    values = [row.get(field, "") for row in rows]
    if any(not value for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{label} has empty or duplicate {field}")


class ResolvedConfig:
    """Resolved immutable-enough configuration plus source hashes."""

    def __init__(self, path, payload, files, hashes):
        # type: (Path, Dict[str, Any], Dict[str, Path], Dict[str, str]) -> None
        self.path = path
        self.root = path.parent
        self.payload = payload
        self.files = files
        self.hashes = hashes
        self.config_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def save(self, directory):  # type: (Path) -> None
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "resolved_config.yaml").open("w", encoding="utf-8") as stream:
            yaml.safe_dump(self.payload, stream, allow_unicode=True, sort_keys=False)
        with (directory / "input_hashes.json").open("w", encoding="utf-8") as stream:
            json.dump(self.hashes, stream, indent=2, sort_keys=True)
            stream.write("\n")


def load_config(path):  # type: (Path) -> ResolvedConfig
    path = path.expanduser().resolve()
    payload = read_yaml(path)
    _require_keys(payload, ("schema", "protocol", "files", "trial_profile"), str(path))
    if payload["schema"] != "calibagent.p8.real.v1":
        raise ValueError("unsupported P8 schema: {}".format(payload["schema"]))
    root = path.parent
    file_map = payload.get("files", {})
    if not isinstance(file_map, dict):
        raise ValueError("files must be a mapping")
    files = {}  # type: Dict[str, Path]
    hashes = {"config": sha256_file(path)}
    for key, value in file_map.items():
        if isinstance(value, str):
            resolved = _resolve(root, value)
            if not resolved.is_file():
                raise FileNotFoundError(f"P8 input {key} not found: {resolved}")
            files[str(key)] = resolved
            hashes[str(key)] = sha256_file(resolved)
    return ResolvedConfig(path, payload, files, hashes)


def _check_command_table(path, expected, label):  # type: (Path, Optional[int], str) -> List[Dict[str, str]]
    rows = read_csv(path)
    if expected is not None and len(rows) != expected:
        raise ValueError(f"{label} expected {expected:d} rows, got {len(rows):d}")
    _unique(rows, "command_id", label)
    seen = set()
    for row in rows:
        command = tuple(round(float(row[key]), 9) for key in ("cmd_vx", "cmd_vy", "cmd_wz"))
        if command in seen:
            raise ValueError(f"{label} has duplicate command vector {command}")
        seen.add(command)
    return rows


def validate_config(config):  # type: (ResolvedConfig) -> Dict[str, Any]
    protocol = str(config.payload["protocol"])
    profile = config.payload["trial_profile"]
    expected_profile = {"ramp_in_s": 0.6, "settle_s": 0.8, "measure_s": 2.0, "ramp_out_s": 0.6}
    for key, expected in expected_profile.items():
        if abs(float(profile.get(key, -1.0)) - expected) > 1e-9:
            raise ValueError(f"trial_profile.{key} must be {expected:.1f}")

    if protocol == "nav":
        required = (
            "runtime_stack",
            "topic_map",
            "reference_extrinsic",
            "candidate_pool",
            "dense_design",
            "lhs_design",
            "sobol_design",
            "random_design",
            "active_seed",
            "validation_commands",
            "task_distribution",
            "nav_schedule",
            "real_offset_slalom",
            "real_weighted_arc",
        )
        _require_keys(config.files, required, "NAV files")
        _check_command_table(config.files["candidate_pool"], None, "candidate_pool")
        _check_command_table(config.files["dense_design"], 30, "dense_design")
        _check_command_table(config.files["lhs_design"], 12, "lhs_design")
        _check_command_table(config.files["sobol_design"], 12, "sobol_design")
        _check_command_table(config.files["random_design"], 12, "random_design")
        _check_command_table(config.files["active_seed"], 6, "active_seed")
        _check_command_table(config.files["validation_commands"], 8, "validation_commands")
        schedule = read_csv(config.files["nav_schedule"])
        blocks = int(config.payload["design"]["blocks"])
        if len(schedule) != blocks * len(NAV_METHODS):
            raise ValueError(f"NAV schedule expected {blocks * 8:d} rows, got {len(schedule):d}")
        _unique(schedule, "planned_unit_id", "NAV schedule")
        by_method = {method: {"AB": 0, "BA": 0} for method in NAV_METHODS}
        for row in schedule:
            if row["method_id"] not in NAV_METHODS or row["route_order"] not in ("AB", "BA"):
                raise ValueError(f"invalid NAV schedule row: {row}")
            by_method[row["method_id"]][row["route_order"]] += 1
        if blocks == 30 and any(counts != {"AB": 15, "BA": 15} for counts in by_method.values()):
            raise ValueError("each NAV method must have 15 AB and 15 BA blocks")
        expected = {
            "schedule_rows": len(schedule),
            "calibration_trials": blocks * sum(NAV_METHOD_COUNTS.values()),
            "validation_trials": blocks * len(NAV_METHODS) * 8,
            "navigation_episodes": blocks * len(NAV_METHODS) * 2,
        }
    elif protocol == "shift":
        required = (
            "runtime_stack",
            "topic_map",
            "reference_extrinsic",
            "candidate_pool",
            "pre_calibration",
            "monitor_commands",
            "passive_recovery",
            "recovery_validation",
            "restore_checks",
            "task_distribution",
            "shift_schedule",
            "shift_definitions",
        )
        _require_keys(config.files, required, "SHIFT files")
        _check_command_table(config.files["candidate_pool"], None, "candidate_pool")
        _check_command_table(config.files["pre_calibration"], 12, "pre_calibration")
        _check_command_table(config.files["monitor_commands"], 9, "monitor_commands")
        _check_command_table(config.files["passive_recovery"], 12, "passive_recovery")
        _check_command_table(config.files["recovery_validation"], 12, "recovery_validation")
        _check_command_table(config.files["restore_checks"], 2, "restore_checks")
        schedule = read_csv(config.files["shift_schedule"])
        blocks = int(config.payload["design"]["blocks_per_shift"])
        expected_rows = len(SHIFT_IDS) * blocks * len(SHIFT_METHODS)
        if len(schedule) != expected_rows:
            raise ValueError(
                f"SHIFT schedule expected {expected_rows:d} rows, got {len(schedule):d}"
            )
        _unique(schedule, "planned_unit_id", "SHIFT schedule")
        for row in schedule:
            if row["method_id"] not in SHIFT_METHODS or row["shift_id"] not in SHIFT_IDS:
                raise ValueError(f"invalid SHIFT schedule row: {row}")
        expected = {
            "schedule_rows": len(schedule),
            "sequences": expected_rows,
            "motion_trials": expected_rows * 45,
            "restore_checks": expected_rows * 2,
        }
    else:
        raise ValueError("protocol must be nav or shift")
    return {
        "protocol": protocol,
        "config": str(config.path),
        "config_hash": config.config_hash,
        "input_hashes": config.hashes,
        "expected": expected,
        "valid": True,
    }
