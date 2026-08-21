#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import json
import math
import pathlib
from collections import Counter


def number(row, key, default=float("nan")):
    try:
        return float(row.get(key, ""))
    except (TypeError, ValueError):
        return default


def read_env(path):
    result = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value.strip().strip("'\"")
    return result


def sign_flips(values, epsilon=1e-4):
    signs = [1 if value > epsilon else -1 for value in values if abs(value) > epsilon]
    return sum(a != b for a, b in zip(signs, signs[1:]))


def iso_time(value):
    try:
        return dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def analyze(run_dir):
    trajectory = run_dir / "trajectory" / "trajectory.csv"
    if not trajectory.exists():
        raise FileNotFoundError("trajectory not found: %s" % trajectory)
    with trajectory.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    nav = []
    reached_row = None
    for row in rows:
        if row.get("status") == "NAVIGATING":
            nav.append(row)
        elif row.get("status") == "REACHED" and reached_row is None:
            reached_row = row
            break
    used = nav + ([reached_row] if reached_row else [])
    if not used:
        raise RuntimeError("trajectory has no NAVIGATING/REACHED samples")

    points = [(number(row, "robot_x"), number(row, "robot_y")) for row in used]
    path_length = sum(
        math.hypot(x1 - x0, y1 - y0)
        for (x0, y0), (x1, y1) in zip(points, points[1:])
    )
    start_x, start_y = points[0]
    goal_x, goal_y = number(used[0], "goal_x"), number(used[0], "goal_y")
    gx, gy = goal_x - start_x, goal_y - start_y
    direct = math.hypot(gx, gy)
    lateral = []
    if direct > 1e-9:
        lateral = [((x - start_x) * gy - (y - start_y) * gx) / direct for x, y in points]

    commands_v = [number(row, "cmd_published_linear") for row in nav]
    commands_w = [number(row, "cmd_published_angular") for row in nav]
    ranges = [number(row, "min_pooled_range") for row in nav]
    ranges = [value for value in ranges if math.isfinite(value)]
    config_path = run_dir / "policy_effective_config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    cap_v = abs(float(config.get("cap_linear", float("nan"))))
    cap_w = abs(float(config.get("cap_angular", float("nan"))))
    cap_v_count = sum(abs(value) >= cap_v - 1e-4 for value in commands_v) if math.isfinite(cap_v) else 0
    cap_w_count = sum(abs(value) >= cap_w - 1e-4 for value in commands_w) if math.isfinite(cap_w) else 0

    guarded_rows = [row for row in nav if row.get("compensation_mode") == "guarded"]
    v_accept = sum(row.get("compensation_linear_accepted") == "1" for row in guarded_rows)
    w_accept = sum(row.get("compensation_angular_accepted") == "1" for row in guarded_rows)
    both_accept = sum(
        row.get("compensation_linear_accepted") == "1"
        and row.get("compensation_angular_accepted") == "1"
        for row in guarded_rows
    )
    reason_v = Counter(row.get("compensation_linear_reason", "") for row in guarded_rows)
    reason_w = Counter(row.get("compensation_angular_reason", "") for row in guarded_rows)

    start_time = iso_time(used[0].get("wall_time"))
    end_time = iso_time(used[-1].get("wall_time"))
    duration = (end_time - start_time).total_seconds() if start_time and end_time else None
    outcome = read_env(run_dir / "operator_outcome.env")
    no_contact = outcome.get("contact_obstacle") == "no"
    no_manual = outcome.get("manual_stop") == "no"
    no_external = outcome.get("external_safety_stop") == "no"
    held = outcome.get("held_goal_for_1s") == "yes"

    result = {
        "run_dir": str(run_dir),
        "experiment_id": used[0].get("experiment_id", ""),
        "profile": used[0].get("experiment_profile", ""),
        "compensation_mode": used[0].get("compensation_mode", ""),
        "samples_navigating": len(nav),
        "reached": reached_row is not None,
        "no_collision_success": bool(reached_row and no_contact and no_manual and no_external and held),
        "duration_sec": duration,
        "path_length_m": path_length,
        "direct_goal_distance_m": direct,
        "path_efficiency": direct / path_length if path_length > 1e-9 else None,
        "max_abs_lateral_deviation_m": max(map(abs, lateral)) if lateral else None,
        "negative_linear_command_count": sum(value < -1e-4 for value in commands_v),
        "angular_sign_flips": sign_flips(commands_w),
        "angular_rms": math.sqrt(sum(value * value for value in commands_w) / len(commands_w)) if commands_w else None,
        "angular_peak_abs": max(map(abs, commands_w)) if commands_w else None,
        "min_pooled_range_m": min(ranges) if ranges else None,
        "hard_cap_linear_fraction": cap_v_count / len(commands_v) if commands_v else None,
        "hard_cap_angular_fraction": cap_w_count / len(commands_w) if commands_w else None,
        "guard": {
            "evaluated_rows": len(guarded_rows),
            "linear_accept_fraction": v_accept / len(guarded_rows) if guarded_rows else None,
            "angular_accept_fraction": w_accept / len(guarded_rows) if guarded_rows else None,
            "both_accept_fraction": both_accept / len(guarded_rows) if guarded_rows else None,
            "linear_reasons": dict(reason_v),
            "angular_reasons": dict(reason_w),
        },
        "operator_outcome": outcome,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Summarize one DCLP reproduction run")
    parser.add_argument("run_dir", type=pathlib.Path)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    result = analyze(args.run_dir.resolve())
    rendered = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)
    print(rendered)
    if not args.no_write:
        (args.run_dir / "analysis.json").write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
