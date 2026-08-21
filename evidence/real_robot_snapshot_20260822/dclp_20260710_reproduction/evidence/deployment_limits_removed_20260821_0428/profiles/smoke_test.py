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
from dclp_deploy.robots.unitree_go2.go2_zmq_sport_client import Go2ZmqSportClient
from dclp_deploy.robots.unitree_go2.velocity_compensation import compensate_velocity


def close(actual, expected, tolerance=1e-5):
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tolerance):
        raise AssertionError("%r != %r" % (actual, expected))


def test_direct_calibration_switch():
    node = object.__new__(DclpGo2PolicyRos2)
    desired = np.asarray([1.05, -1.09956], dtype=np.float32)
    expected = compensate_velocity(*map(float, desired))

    node.use_compensation = True
    output, raw, accepted, reasons = node._apply_compensation(desired)
    close(output[0], expected[0])
    close(output[1], expected[1])
    assert accepted == (True, True)
    assert reasons == ("calibration_direct", "calibration_direct")

    node.use_compensation = False
    output, raw, accepted, reasons = node._apply_compensation(desired)
    assert np.allclose(output, desired)
    assert np.isnan(raw).all()
    assert reasons == ("off", "off")


def test_policy_direct_scale_has_no_floor_or_clip():
    node = object.__new__(DclpGo2PolicyRos2)
    node.robot = SimpleNamespace(max_linear_speed=0.9, max_angular_speed=0.83776)
    target = node._scale_action_to_cmd([0.01, -0.5])
    close(target[0], 0.009)
    close(target[1], -0.41888)
    outside = node._scale_action_to_cmd([1.2, -1.3])
    close(outside[0], 1.08)
    close(outside[1], -1.089088)


def test_zmq_transport_does_not_change_command():
    class FakeSport:
        def __init__(self):
            self.calls = []

        def Move(self, v, lateral, w):
            self.calls.append((v, lateral, w))
            return 0

    client = object.__new__(Go2ZmqSportClient)
    client.args = SimpleNamespace(dry_run=False, zero_motion=False)
    client.last_cmd_time = None
    client.cmd_count = 0
    client.stopped = False
    client.sport_client = FakeSport()
    client.handle_message("[2.5, -3.0]")
    assert client.sport_client.calls == [(2.5, 0.0, -3.0)]


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
    test_direct_calibration_switch()
    test_policy_direct_scale_has_no_floor_or_clip()
    test_zmq_transport_does_not_change_command()
    test_model101_load_and_action()
    print("smoke tests passed")


if __name__ == "__main__":
    main()
