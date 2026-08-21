#!/usr/bin/env python3
import math
import pathlib
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dclp_deploy" / "robots" / "unitree_go2"))

from dclp_deploy.dclp_policy_backend import DclpPolicyBackend
from dclp_deploy.robots.unitree_go2.dclp_go2_policy_ros2 import DclpGo2PolicyRos2
from dclp_deploy.robots.unitree_go2.velocity_compensation import compensate_velocity


def close(actual, expected, tolerance=1e-5):
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tolerance):
        raise AssertionError("%r != %r" % (actual, expected))


def test_compensation_modes():
    node = object.__new__(DclpGo2PolicyRos2)
    node.cmd_vel_v_min = 0.35
    node.cmd_vel_w_min = 0.36652
    node.robot = SimpleNamespace(max_linear_speed=1.05, max_angular_speed=1.09956)
    desired = np.asarray([1.05, -1.09956], dtype=np.float32)
    expected = compensate_velocity(*map(float, desired))

    node.compensation_mode = "raw"
    output, raw, accepted, reasons = node._apply_compensation(desired)
    close(output[0], expected[0])
    close(output[1], expected[1])
    assert accepted == (True, True) and reasons == ("raw", "raw")

    node.compensation_mode = "guarded"
    output, raw, accepted, reasons = node._apply_compensation(desired)
    close(output[0], desired[0])
    close(output[1], desired[1])
    assert accepted == (False, False)
    assert reasons == ("above_max", "above_max")

    node.compensation_mode = "off"
    output, raw, accepted, reasons = node._apply_compensation(desired)
    assert np.allclose(output, desired)
    assert np.isnan(raw).all()
    assert reasons == ("off", "off")


def test_legacy_anchor():
    node = object.__new__(DclpGo2PolicyRos2)
    node.robot = SimpleNamespace(
        max_linear_speed=3.0,
        max_angular_speed=3.1416,
        max_linear_acc=3.0,
        max_angular_acc=3.0,
    )
    node.control_period_sec = 0.02
    node.cmd_vel_v_floor = 1.0
    node.cmd_vel_w_floor = 1.0472
    node.cmd_vel_v_cap = 3.0
    node.cmd_vel_w_cap = 3.1416
    target = node._legacy_action_target([0.5, -0.5])
    limited = node._limit_cmd_accel_fixed(target, [0.0, 0.0])
    close(limited[0], 0.06)
    close(limited[1], -0.06)
    floored = node._apply_legacy_floors(limited)
    close(floored[0], 1.0)
    close(floored[1], -1.0472)


def test_model101_load_and_action():
    model = ROOT / "models" / "dclp" / "V1_41lambda1_101.pth"
    backend = DclpPolicyBackend(
        model_path=str(model),
        backend_type="pth",
        device="cpu",
        deterministic=True,
    )
    obs = np.zeros(548, dtype=np.float32)
    scan = obs[:540].reshape(90, 6)
    angles = np.arange(90, dtype=np.float32) * (2.0 * np.pi / 90.0) - np.pi / 2.0 + np.pi / 90.0
    scan[:, 0] = np.cos(angles)
    scan[:, 1] = np.sin(angles)
    scan[:, 2] = 2.0
    scan[:, 3] = 0.504
    scan[:, 4] = 0.504
    scan[:, 5] = 0.4464
    obs[-8:] = [4.0, 0.0, 0.0, 0.0, 0.90, 0.83776, 3.0, 3.0]
    action = np.asarray(backend.act(obs)).reshape(-1)
    assert action.shape[0] >= 2
    assert np.isfinite(action[:2]).all()
    assert np.all(np.abs(action[:2]) <= 1.000001)
    print("model101 action:", action[:2].tolist())


def main():
    test_compensation_modes()
    test_legacy_anchor()
    test_model101_load_and_action()
    print("smoke tests passed")


if __name__ == "__main__":
    main()
