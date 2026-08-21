#!/usr/bin/env python3
"""Pure scan-pipeline regression tests for rolling MID360 projection."""

import math
from collections import deque

import numpy as np

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


def main():
    test_motion_compensated_projection()
    print("mid360 scan regression tests passed")


if __name__ == "__main__":
    main()
