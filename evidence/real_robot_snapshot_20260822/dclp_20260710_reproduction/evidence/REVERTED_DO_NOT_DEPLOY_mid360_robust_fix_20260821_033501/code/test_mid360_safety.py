#!/usr/bin/env python3
"""Pure logic regression tests for MID360 accumulation and policy safety."""

import math
from collections import deque
from types import SimpleNamespace

import numpy as np

from dclp_go2_policy_ros2 import DclpGo2PolicyRos2
from go2_livox_pc2scan_ros2 import Go2LivoxPc2Scan


def make_pc2scan_stub():
    node = object.__new__(Go2LivoxPc2Scan)
    node.ranges_size = 1081
    node.use_inf = True
    node.range_min = 0.26
    node.range_max = 20.0
    node.angle_min = -math.pi
    node.angle_max = math.pi
    node.angle_increment = 0.005817764
    node.motion_compensation = True
    node.frames = deque()
    return node


def test_motion_compensated_projection():
    node = make_pc2scan_stub()
    node.frames.append(
        {
            "stamp": 1.0,
            "x": np.asarray([1.0], dtype=np.float32),
            "y": np.asarray([0.0], dtype=np.float32),
            "pose": (0.0, 0.0, 0.0),
        }
    )
    ranges, used, compensated = node._project_history((0.1, 0.0, 0.0))
    finite = ranges[np.isfinite(ranges)]
    assert used == 1
    assert compensated == 1
    assert finite.size == 1
    assert abs(float(finite[0]) - 0.9) < 1e-5


def make_policy_stub():
    node = object.__new__(DclpGo2PolicyRos2)
    node.front_safety_enabled = True
    node.front_safety_angle = 0.55
    node.front_safety_base_distance = 0.55
    node.front_safety_reaction_time = 0.12
    node.front_safety_decel = 3.0
    node.front_safety_release_margin = 0.15
    node.front_safety_hold_sec = 0.25
    node.front_safety_min_cluster_beams = 2
    node.front_safety_reverse_w_limit = 0.35
    node.front_safety_latched_until = 0.0
    node.front_safety_last_distance = float("inf")
    node.front_safety_active = False
    node.last_cmd = np.asarray([0.9, 0.0], dtype=np.float32)
    return node


def test_front_safety_brakes_before_accel_limiter_finishes():
    node = make_policy_stub()
    ranges = np.asarray([0.70, 0.68], dtype=np.float32)
    angles = np.asarray([-0.01, 0.0], dtype=np.float32)
    state = node._front_safety_state(ranges, angles, np.asarray([0.9, 0.0]), 10.0)
    assert state["active"]
    assert abs(state["threshold"] - 0.793) < 1e-6

    # This matches the collision: policy target is reverse, but the normal
    # acceleration limiter still has a positive command. Safety must send zero.
    cmd, hard_brake = node._apply_front_safety_to_cmd(
        np.asarray([0.636, 0.5]), np.asarray([-0.583, 0.4]), state
    )
    assert hard_brake
    assert np.allclose(cmd, [0.0, 0.0])

    # Once the limiter starts producing reverse, allow backing away but bound yaw.
    cmd, hard_brake = node._apply_front_safety_to_cmd(
        np.asarray([-0.12, 0.7]), np.asarray([-0.583, 0.7]), state
    )
    assert not hard_brake
    assert np.allclose(cmd, [-0.12, 0.35])

    # A stopped robot must not start accelerating into an obstacle just because
    # the current-speed braking distance is short; planned forward speed counts.
    node = make_policy_stub()
    node.last_cmd[:] = 0.0
    state = node._front_safety_state(
        ranges,
        angles,
        np.asarray([0.0, 0.0]),
        20.0,
        planned_v=0.9,
    )
    assert state["active"]


def test_front_cluster_and_hysteresis():
    node = make_policy_stub()
    assert math.isinf(
        node._clustered_front_distance(
            np.asarray([0.4]), np.asarray([0.0]), max_distance=1.0
        )
    )
    assert abs(
        node._clustered_front_distance(
            np.asarray([0.4, 0.42]), np.asarray([0.0, 0.01]), max_distance=1.0
        )
        - 0.4
    ) < 1e-6

    node._front_safety_state(
        np.asarray([0.4, 0.42]), np.asarray([0.0, 0.01]), np.asarray([0.0, 0.0]), 1.0
    )
    held = node._front_safety_state(
        np.asarray([2.0, 2.0]), np.asarray([0.0, 0.01]), np.asarray([0.0, 0.0]), 1.1
    )
    assert held["active"]
    released = node._front_safety_state(
        np.asarray([2.0, 2.0]), np.asarray([0.0, 0.01]), np.asarray([0.0, 0.0]), 1.3
    )
    assert not released["active"]


def test_scan_quality_count():
    scan = SimpleNamespace(
        ranges=[float("inf"), 0.25, 0.26, 1.0, 20.0, 21.0],
        range_min=0.26,
        range_max=20.0,
    )
    assert DclpGo2PolicyRos2._valid_scan_beam_count(scan) == 3


def main():
    test_motion_compensated_projection()
    test_front_safety_brakes_before_accel_limiter_finishes()
    test_front_cluster_and_hysteresis()
    test_scan_quality_count()
    print("mid360 safety regression tests passed")


if __name__ == "__main__":
    main()
