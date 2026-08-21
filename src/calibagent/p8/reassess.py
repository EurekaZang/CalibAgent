"""Auditable NAV freshness reassessment from immutable trace and rosbag data."""

import csv
import hashlib
import json
import math
import os
import shutil
import sqlite3
import time
from pathlib import Path

from calibagent.p8.backend import (
    NAVIGATION_FRESHNESS_RULE_VERSION,
    navigation_quality_reasons,
)
from calibagent.p8.recording import EPISODE_FIELDS


RULE_VERSION = NAVIGATION_FRESHNESS_RULE_VERSION


def _sha256(path):  # type: (Path) -> str
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _max_gap_ms(values):
    if len(values) < 2:
        return float("inf")
    return max((b - a) * 1000.0 for a, b in zip(values, values[1:]))


def _trace_evidence(path, planned_unit_id):
    ticks = []
    send_times = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("planned_unit_id") != planned_unit_id:
                continue
            if row.get("event") == "navigation_tick":
                ticks.append(row)
            elif row.get("event") == "sent_action" and row.get("source") in (
                "navigation",
                "navigation_end",
            ):
                value = row.get("sent_ros_time")
                if value is not None:
                    send_times.append(float(value))
    if not ticks or len(send_times) < 2:
        raise RuntimeError("navigation trace has no complete action window")
    active_ages = [
        float(row["planned_action_age_ms"])
        for row in ticks
        if max(abs(float(value)) for value in row.get("sent_action", (0.0, 0.0, 0.0)))
        > 1e-9
    ]
    return {
        "start_ros_time": min(send_times),
        "end_ros_time": max(send_times),
        "trace_ticks": len(ticks),
        "max_scan_age_ms": max(float(row["scan_age_ms"]) for row in ticks),
        "max_reference_action_age_ms": max(
            float(row["reference_age_ms"]) for row in ticks
        ),
        "max_sent_action_age_ms": max(
            float(row["planned_action_age_ms"]) for row in ticks
        ),
        "max_active_action_receive_age_ms": max(active_ages) if active_ages else 0.0,
    }


def _header_age_ms(receive_ns, message):
    stamp = message.header.stamp
    source_ns = int(stamp.sec) * 1000000000 + int(stamp.nanosec)
    return (int(receive_ns) - source_ns) * 1e-6


def _bag_evidence(bag_path, start_ros_time, end_ros_time):
    try:
        from nav_msgs.msg import Odometry
        from rclpy.serialization import deserialize_message
        from sensor_msgs.msg import LaserScan
        from geometry_msgs.msg import Twist
    except ImportError as exc:
        raise RuntimeError(
            "ROS 2 Python message support is required; source /opt/ros/foxy/setup.bash"
        ) from exc

    bag_path = Path(bag_path).expanduser().resolve()
    databases = sorted(bag_path.glob("*.db3")) if bag_path.is_dir() else [bag_path]
    if len(databases) != 1 or not databases[0].is_file():
        raise RuntimeError("expected exactly one rosbag sqlite database: {}".format(bag_path))
    connection = sqlite3.connect(str(databases[0]))
    try:
        topics = {name: topic_id for topic_id, name in connection.execute("select id,name from topics")}
        lower = int(float(start_ros_time) * 1e9)
        upper = int(float(end_ros_time) * 1e9)
        duration = max(float(end_ros_time) - float(start_ros_time), 1e-9)
        evidence = {}
        for label, topic, message_type in (
            ("reference", "/Odometry", Odometry),
            ("scan", "/scan", LaserScan),
        ):
            if topic not in topics:
                raise RuntimeError("rosbag is missing required topic {}".format(topic))
            records = list(
                connection.execute(
                    "select timestamp,data from messages where topic_id=? and timestamp between ? and ? order by timestamp",
                    (topics[topic], lower, upper),
                )
            )
            receives = [int(row[0]) * 1e-9 for row in records]
            source_ages = [
                _header_age_ms(row[0], deserialize_message(row[1], message_type))
                for row in records
            ]
            evidence[label] = {
                "frames": len(records),
                "rate_hz": len(records) / duration,
                "max_receive_gap_ms": _max_gap_ms(receives),
                "max_source_age_ms": max(source_ages) if source_ages else float("inf"),
            }
        topic = "/p8/planned_cmd_vel"
        if topic not in topics:
            raise RuntimeError("rosbag is missing required topic {}".format(topic))
        planned_records = list(
            connection.execute(
                "select timestamp,data from messages where topic_id=? and timestamp between ? and ? order by timestamp",
                (topics[topic], lower, upper),
            )
        )
        receives = [int(row[0]) * 1e-9 for row in planned_records]
        active = []
        for _, data in planned_records:
            message = deserialize_message(data, Twist)
            active.append(
                max(
                    abs(float(message.linear.x)),
                    abs(float(message.linear.y)),
                    abs(float(message.angular.z)),
                )
                > 1e-9
            )
        evidence["planned_action"] = {
            "frames": len(receives),
            "rate_hz": len(receives) / duration,
            "max_receive_gap_ms": _max_gap_ms(receives),
            "max_active_hold_gap_ms": max(
                [
                    (right - left) * 1000.0
                    for left, right, is_active in zip(
                        receives, receives[1:], active[:-1]
                    )
                    if is_active
                ]
                or [0.0]
            ),
        }
        evidence["database"] = str(databases[0])
        evidence["window_s"] = duration
        return evidence
    finally:
        connection.close()


def _write_csv_atomic(path, rows, fields):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def reassess_navigation_run(run_dir, quality, apply=False):
    run_dir = Path(run_dir).expanduser().resolve()
    episodes_path = run_dir / "navigation_episodes.csv"
    trace_path = run_dir / "navigation_trace.jsonl"
    if not episodes_path.is_file() or not trace_path.is_file():
        raise FileNotFoundError("run has no complete NAV records: {}".format(run_dir))
    effective_quality = dict(quality)
    effective_quality.setdefault("max_reference_gap_ms", 120.0)
    effective_quality.setdefault("max_scan_gap_ms", 120.0)
    effective_quality.setdefault("max_planned_action_gap_ms", 120.0)
    original_hash = _sha256(episodes_path)
    with episodes_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        original_fields = list(reader.fieldnames or ())
        rows = [dict(row) for row in reader]

    audit_rows = []
    updated_rows = []
    for row in rows:
        trace = _trace_evidence(trace_path, row["planned_unit_id"])
        bag = _bag_evidence(row["bag_path"], trace["start_ros_time"], trace["end_ros_time"])
        metrics = {
            "max_scan_age_ms": trace["max_scan_age_ms"],
            "max_reference_source_age_ms": bag["reference"]["max_source_age_ms"],
            "max_reference_receive_gap_ms": bag["reference"]["max_receive_gap_ms"],
            "max_scan_receive_gap_ms": bag["scan"]["max_receive_gap_ms"],
            "max_active_action_receive_age_ms": trace[
                "max_active_action_receive_age_ms"
            ],
            "max_planned_action_receive_gap_ms": bag["planned_action"][
                "max_receive_gap_ms"
            ],
            "max_active_action_receive_gap_ms": bag["planned_action"][
                "max_active_hold_gap_ms"
            ],
            "planned_action_rate_hz": bag["planned_action"]["rate_hz"],
            "reference_rate_hz": bag["reference"]["rate_hz"],
            "scan_rate_hz": bag["scan"]["rate_hz"],
        }
        reasons = navigation_quality_reasons(metrics, effective_quality)
        route_reached = str(row.get("route_reached", "")).lower() == "true"
        collision = str(row.get("collision", "")).lower() == "true"
        valid = route_reached and not collision and not reasons
        updated = dict(row)
        updated.update({key: str(value) for key, value in metrics.items()})
        updated["max_reference_age_ms"] = str(trace["max_reference_action_age_ms"])
        updated["max_sent_action_age_ms"] = str(trace["max_sent_action_age_ms"])
        updated["data_quality_valid"] = str(bool(not reasons))
        updated["data_quality_reason"] = "; ".join(reasons)
        updated["freshness_rule_version"] = RULE_VERSION
        if valid:
            updated.update(status="SUCCESS", terminal_reason="reached", success="True")
        elif route_reached:
            updated.update(status="INVALID", terminal_reason="data_quality_invalid", success="False")
        updated_rows.append(updated)
        audit_rows.append(
            {
                "planned_unit_id": row["planned_unit_id"],
                "old_status": row.get("status"),
                "new_status": updated.get("status"),
                "route_reached": route_reached,
                "collision": collision,
                "quality_reasons": reasons,
                "metrics": metrics,
                "diagnostics": {
                    "max_reference_action_age_ms": trace["max_reference_action_age_ms"],
                    "max_all_action_receive_age_ms": trace["max_sent_action_age_ms"],
                },
                "bag": bag,
            }
        )

    fields = list(EPISODE_FIELDS)
    fields.extend(field for field in original_fields if field not in fields)
    audit = {
        "rule_version": RULE_VERSION,
        "run_dir": str(run_dir),
        "source_csv": str(episodes_path),
        "source_csv_sha256": original_hash,
        "applied": bool(apply),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "quality_thresholds": effective_quality,
        "episodes": audit_rows,
    }
    audit_path = run_dir / "freshness_reassessment_v2.json"
    if apply:
        backup = run_dir / "navigation_episodes.before_freshness_v2.csv"
        if not backup.exists():
            shutil.copy2(str(episodes_path), str(backup))
        _write_csv_atomic(episodes_path, updated_rows, fields)
        audit["backup_csv"] = str(backup)
        audit["updated_csv_sha256"] = _sha256(episodes_path)
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "run_dir": str(run_dir),
        "rule_version": RULE_VERSION,
        "applied": bool(apply),
        "episodes": len(audit_rows),
        "valid_episodes": sum(not row["quality_reasons"] for row in audit_rows),
        "audit": str(audit_path),
    }
