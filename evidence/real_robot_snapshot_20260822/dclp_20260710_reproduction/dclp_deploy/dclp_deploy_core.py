"""Pure helpers for DCLP real-robot deployment.

DCLP deploy intentionally follows the DCLP simulation/eval contract:
90 full-circle scan groups times [cos, sin, distance, length1, length2, width],
followed by the 8-D goal/speed/dynamics tail. The policy action is normalized
and converted directly to physical cmd_vel using the policy speed scales.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Sequence, Tuple

import numpy as np

from dclp_deploy.dclp_schema import (
    BEAM_NUM,
    CONTROL_PERIOD_SEC,
    DEFAULT_MAX_ANGULAR_ACC,
    DEFAULT_MAX_ANGULAR_SPEED,
    DEFAULT_MAX_LINEAR_ACC,
    DEFAULT_MAX_LINEAR_SPEED,
    OBS_DIM,
    SCAN_GROUPS,
    SCAN_GROUP_SIZE,
)


DEFAULT_RANGE_FILL = 2.0
EPS = 1e-8


@dataclass(frozen=True)
class DclpRobotContext:
    length1: float = 0.21
    length2: float = 0.21
    width: float = 0.165
    max_linear_speed: float = DEFAULT_MAX_LINEAR_SPEED
    max_angular_speed: float = DEFAULT_MAX_ANGULAR_SPEED
    max_linear_acc: float = DEFAULT_MAX_LINEAR_ACC
    max_angular_acc: float = DEFAULT_MAX_ANGULAR_ACC


def wrap_to_pi(angles: Sequence[float]) -> np.ndarray:
    arr = np.asarray(angles, dtype=np.float32)
    return ((arr + np.pi) % (2.0 * np.pi) - np.pi).astype(np.float32, copy=False)


def _validate_same_shape(ranges: Sequence[float], angles: Sequence[float]) -> Tuple[np.ndarray, np.ndarray]:
    ranges_arr = np.asarray(ranges, dtype=np.float32).reshape(-1)
    angles_arr = np.asarray(angles, dtype=np.float32).reshape(-1)
    if ranges_arr.shape != angles_arr.shape:
        raise ValueError("ranges and angles must have the same shape, got %s vs %s" % (ranges_arr.shape, angles_arr.shape))
    return ranges_arr, angles_arr


def clean_scan_ranges(
    ranges: Sequence[float],
    *,
    scan_range_min: float = 0.0,
    scan_range_max: float = DEFAULT_RANGE_FILL,
    fill_range: float = DEFAULT_RANGE_FILL,
) -> np.ndarray:
    raw = np.asarray(ranges, dtype=np.float32).reshape(-1)
    fill = float(fill_range)
    if not np.isfinite(fill) or fill <= 0.0:
        raise ValueError("fill_range must be positive and finite, got %r" % fill_range)
    rmin = float(scan_range_min)
    if not np.isfinite(rmin) or rmin < 0.0:
        rmin = 0.0
    rmax = float(scan_range_max)
    if not np.isfinite(rmax) or rmax <= 0.0:
        rmax = fill
    valid = np.isfinite(raw) & (raw >= np.float32(rmin)) & (raw <= np.float32(rmax))
    clean = np.full(raw.shape, np.float32(fill), dtype=np.float32)
    clean[valid] = raw[valid]
    return clean


def transform_scan_points_to_base(
    *,
    ranges: Sequence[float],
    sensor_angles: Sequence[float],
    transform_2d: Tuple[float, float, float],
) -> Tuple[np.ndarray, np.ndarray]:
    ranges_arr, angles_arr = _validate_same_shape(ranges, sensor_angles)
    tx, ty, yaw = (float(transform_2d[0]), float(transform_2d[1]), float(transform_2d[2]))
    sx = ranges_arr * np.cos(angles_arr)
    sy = ranges_arr * np.sin(angles_arr)
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    bx = tx + cos_yaw * sx - sin_yaw * sy
    by = ty + sin_yaw * sx + cos_yaw * sy
    base_ranges = np.sqrt(bx * bx + by * by).astype(np.float32)
    base_angles = np.arctan2(by, bx).astype(np.float32)
    return base_ranges, base_angles


def dclp_group_centers() -> np.ndarray:
    return (
        np.arange(SCAN_GROUPS, dtype=np.float32) * np.float32(2.0 * np.pi / SCAN_GROUPS)
        - np.float32(np.pi / 2.0)
        + np.float32(np.pi / SCAN_GROUPS)
    ).astype(np.float32, copy=False)


def pool_scan_to_dclp_groups(
    *,
    ranges: Sequence[float],
    angles: Sequence[float],
    range_fill: float = DEFAULT_RANGE_FILL,
    eps: float = EPS,
) -> Tuple[np.ndarray, Dict[str, object]]:
    ranges_arr, angles_arr = _validate_same_shape(ranges, angles)
    fill = float(range_fill)
    if not np.isfinite(fill) or fill <= 0.0:
        raise ValueError("range_fill must be positive and finite, got %r" % range_fill)
    bin_width = (2.0 * np.pi) / float(SCAN_GROUPS)
    pooled = np.full(SCAN_GROUPS, np.float32(fill), dtype=np.float32)
    coverage = np.zeros(SCAN_GROUPS, dtype=np.bool_)

    finite = np.isfinite(ranges_arr) & np.isfinite(angles_arr)
    if np.any(finite):
        clean_ranges = np.clip(ranges_arr[finite], np.float32(eps), np.float32(fill))
        wrapped_angles = wrap_to_pi(angles_arr[finite])
        # Match dclp_group_centers(): bin 0 is centered near -pi/2, not -pi.
        # The policy-facing sector distribution is rotated clockwise by 270 degrees
        # total: the previous 180-degree rotation plus another 90 degrees.
        shifted = (
            wrapped_angles
            + np.float32(np.pi / 2.0)
            - np.float32(np.pi)
            - np.float32(np.pi / 2.0)
        ) % np.float32(2.0 * np.pi)
        for rng, angle_shifted in zip(clean_ranges, shifted):
            idx = int(math.floor(float(angle_shifted) / bin_width))
            idx = max(0, min(SCAN_GROUPS - 1, idx))
            if float(rng) < float(pooled[idx]):
                pooled[idx] = np.float32(rng)
            coverage[idx] = True

    ros_centers = (
        np.arange(SCAN_GROUPS, dtype=np.float32) * np.float32(bin_width)
        - np.float32(np.pi)
        + np.float32(0.5 * bin_width)
    ).astype(np.float32, copy=False)
    coverage_count = int(np.count_nonzero(coverage))
    finite_pooled = pooled[np.isfinite(pooled)]
    diag = {
        "pooled_ranges": pooled.copy(),
        "coverage_mask": coverage.copy(),
        "coverage_count": coverage_count,
        "empty_group_count": int(SCAN_GROUPS - coverage_count),
        "empty_bin_count": int(SCAN_GROUPS - coverage_count),
        "min_pooled_range": float(np.min(finite_pooled)) if finite_pooled.size else float("inf"),
        "fov_min": float(-np.pi),
        "fov_max": float(np.pi),
        "ros_group_centers": ros_centers.copy(),
    }
    return pooled, diag


def pool_front_scan_to_dclp_groups(
    *,
    ranges: Sequence[float],
    angles: Sequence[float],
    range_fill: float = DEFAULT_RANGE_FILL,
    eps: float = EPS,
) -> Tuple[np.ndarray, Dict[str, object]]:
    return pool_scan_to_dclp_groups(
        ranges=ranges,
        angles=angles,
        range_fill=range_fill,
        eps=eps,
    )


def build_dclp_laser_features_from_points(
    *,
    ranges: Sequence[float],
    angles: Sequence[float],
    robot: DclpRobotContext,
    range_fill: float = DEFAULT_RANGE_FILL,
) -> Tuple[np.ndarray, Dict[str, object]]:
    pooled, diag = pool_scan_to_dclp_groups(
        ranges=ranges,
        angles=angles,
        range_fill=range_fill,
    )
    centers = dclp_group_centers()
    diag["group_centers"] = centers.copy()
    pool_state = np.zeros((SCAN_GROUPS, SCAN_GROUP_SIZE), dtype=np.float32)
    pool_state[:, 0] = np.cos(centers)
    pool_state[:, 1] = np.sin(centers)
    pool_state[:, 2] = pooled
    pool_state[:, 3] = np.float32(robot.length1)
    pool_state[:, 4] = np.float32(robot.length2)
    pool_state[:, 5] = np.float32(robot.width)
    laser = pool_state.reshape(-1).astype(np.float32, copy=False)
    if laser.shape[0] != BEAM_NUM:
        raise ValueError("DCLP laser feature shape mismatch: %r" % (laser.shape,))
    return laser, diag


def build_target_tail(
    *,
    goal_in_base: Sequence[float],
    current_vw: Sequence[float],
    robot: DclpRobotContext,
    eps: float = EPS,
) -> np.ndarray:
    goal = np.asarray(goal_in_base, dtype=np.float32).reshape(-1)
    speed = np.asarray(current_vw, dtype=np.float32).reshape(-1)
    if goal.shape[0] < 2:
        raise ValueError("goal_in_base must contain x and y")
    if speed.shape[0] < 2:
        raise ValueError("current_vw must contain linear and angular speed")
    dist = max(float(np.hypot(goal[0], goal[1])), float(eps))
    angle = float(math.atan2(float(goal[1]), float(goal[0])))
    return np.asarray(
        [
            dist,
            angle,
            float(speed[0]),
            float(speed[1]),
            float(robot.max_linear_speed),
            float(robot.max_angular_speed),
            float(robot.max_linear_acc),
            float(robot.max_angular_acc),
        ],
        dtype=np.float32,
    )


def build_dclp_observation(laser_features: Sequence[float], tail: Sequence[float]) -> np.ndarray:
    laser = np.asarray(laser_features, dtype=np.float32).reshape(-1)
    tail_arr = np.asarray(tail, dtype=np.float32).reshape(-1)
    if laser.shape[0] != BEAM_NUM:
        raise ValueError("DCLP laser_features must have %d values, got %d" % (BEAM_NUM, laser.shape[0]))
    if tail_arr.shape[0] != 8:
        raise ValueError("DCLP tail must have 8 values, got %d" % tail_arr.shape[0])
    obs = np.concatenate([laser, tail_arr], axis=0).astype(np.float32, copy=False)
    if obs.shape[0] != OBS_DIM:
        raise ValueError("DCLP observation must have %d values, got %d" % (OBS_DIM, obs.shape[0]))
    return obs


def normalized_action_to_cmd_vel(
    *,
    normalized_action: Sequence[float],
    current_vw: Sequence[float],
    robot: DclpRobotContext,
    control_period_sec: float = CONTROL_PERIOD_SEC,
) -> np.ndarray:
    action = np.asarray(normalized_action, dtype=np.float32).reshape(-1)
    if action.shape[0] < 2:
        raise ValueError("DCLP normalized action must contain at least 2 values, got %d" % action.shape[0])
    return np.asarray(
        [
            float(action[0]) * float(robot.max_linear_speed),
            float(action[1]) * float(robot.max_angular_speed),
        ],
        dtype=np.float32,
    )
