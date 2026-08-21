#!/usr/bin/env python3
import argparse
import os
import pathlib
import subprocess
import sys


REQUIRED = (
    "PROFILE_ID",
    "PROFILE_DESCRIPTION",
    "PROFILE_RISK",
    "COMPENSATE",
    "POLICY_COMPENSATION_MODE",
    "POLICY_ACTION_MAPPING",
    "POLICY_ACCEL_LIMITER_MODE",
    "POLICY_MAX_LINEAR",
    "POLICY_MAX_ANGULAR",
    "POLICY_CMD_VEL_V_MIN",
    "POLICY_CMD_VEL_W_MIN",
    "POLICY_CMD_VEL_V_CAP",
    "POLICY_CMD_VEL_W_CAP",
    "DCLP_LENGTH1",
    "DCLP_LENGTH2",
    "DCLP_WIDTH",
)


def resolve_profile(path):
    command = [
        "bash",
        "-c",
        'set -euo pipefail; source "$1"; env -0',
        "profile-resolver",
        str(path),
    ]
    raw = subprocess.check_output(command)
    result = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            result[key.decode()] = value.decode()
    return result


def validate(path, values):
    errors = []
    expected_id = path.stem
    if values.get("PROFILE_ID") != expected_id:
        errors.append("PROFILE_ID does not match filename")
    for key in REQUIRED:
        if key not in values or values[key] == "":
            errors.append("missing %s" % key)
    if errors:
        return errors
    mode = values["POLICY_COMPENSATION_MODE"]
    flag = values["COMPENSATE"]
    if (mode == "off") != (flag == "0"):
        errors.append("COMPENSATE and POLICY_COMPENSATION_MODE disagree")
    if mode not in ("off", "raw", "guarded"):
        errors.append("invalid compensation mode")
    if values["POLICY_ACTION_MAPPING"] not in ("range", "legacy_floor"):
        errors.append("invalid action mapping")
    if values["POLICY_ACCEL_LIMITER_MODE"] not in (
        "last_cmd_dt",
        "last_cmd_fixed",
        "odom_fixed",
    ):
        errors.append("invalid limiter mode")
    if values["PROFILE_RISK"] not in ("medium", "high", "extreme"):
        errors.append("invalid risk")
    numeric = {key: float(values[key]) for key in REQUIRED if key.startswith(("POLICY_MAX_", "POLICY_CMD_", "DCLP_"))}
    if numeric["POLICY_CMD_VEL_V_MIN"] > numeric["POLICY_MAX_LINEAR"]:
        errors.append("linear min > target max")
    if numeric["POLICY_CMD_VEL_W_MIN"] > numeric["POLICY_MAX_ANGULAR"]:
        errors.append("angular min > target max")
    if numeric["POLICY_MAX_LINEAR"] > numeric["POLICY_CMD_VEL_V_CAP"]:
        errors.append("linear target max > hard cap")
    if numeric["POLICY_MAX_ANGULAR"] > numeric["POLICY_CMD_VEL_W_CAP"]:
        errors.append("angular target max > hard cap")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "profile_dir",
        nargs="?",
        default=str(pathlib.Path(__file__).resolve().parents[1] / "profiles"),
    )
    args = parser.parse_args()
    profile_dir = pathlib.Path(args.profile_dir)
    failures = 0
    print("profile\trisk\tcompensation\tmapping\tlimiter\tv_range\tw_range\tgeometry")
    for path in sorted(profile_dir.glob("*.env")):
        try:
            values = resolve_profile(path)
            errors = validate(path, values)
        except Exception as exc:
            failures += 1
            print("%s\tERROR: %s" % (path.stem, exc), file=sys.stderr)
            continue
        if errors:
            failures += 1
            print("%s\tERROR: %s" % (path.stem, "; ".join(errors)), file=sys.stderr)
            continue
        print(
            "%s\t%s\t%s\t%s\t%s\t%s..%s\t%s..%s\t%s/%s/%s"
            % (
                values["PROFILE_ID"],
                values["PROFILE_RISK"],
                values["POLICY_COMPENSATION_MODE"],
                values["POLICY_ACTION_MAPPING"],
                values["POLICY_ACCEL_LIMITER_MODE"],
                values["POLICY_CMD_VEL_V_MIN"],
                values["POLICY_MAX_LINEAR"],
                values["POLICY_CMD_VEL_W_MIN"],
                values["POLICY_MAX_ANGULAR"],
                values["DCLP_LENGTH1"],
                values["DCLP_LENGTH2"],
                values["DCLP_WIDTH"],
            )
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
