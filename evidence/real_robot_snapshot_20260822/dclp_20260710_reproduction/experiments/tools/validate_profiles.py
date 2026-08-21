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
    "POLICY_MAX_LINEAR",
    "POLICY_MAX_ANGULAR",
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
    flag = values["COMPENSATE"]
    if flag not in ("0", "1"):
        errors.append("COMPENSATE must be 0 or 1")
    if values["PROFILE_RISK"] not in ("medium", "high", "extreme"):
        errors.append("invalid risk")
    for key in ("POLICY_MAX_LINEAR", "POLICY_MAX_ANGULAR"):
        if float(values[key]) <= 0.0:
            errors.append("%s must be positive" % key)
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
    print("profile\trisk\tcompensation\tcommand_path\tv_scale\tw_scale\tgeometry")
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
            "%s\t%s\t%s\t%s\t%s\t%s\t%s/%s/%s"
            % (
                values["PROFILE_ID"],
                values["PROFILE_RISK"],
                "calibration_direct" if values["COMPENSATE"] == "1" else "off",
                "policy_direct_scale",
                values["POLICY_MAX_LINEAR"],
                values["POLICY_MAX_ANGULAR"],
                values["DCLP_LENGTH1"],
                values["DCLP_LENGTH2"],
                values["DCLP_WIDTH"],
            )
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
