"""Fake and ROS 2 backends for P8.

The ROS backend publishes Unitree Sport Move requests directly.  It never
clips, floors, slews, guards, or otherwise rewrites an action.  The optional
adapter matrix is only the declared R1 experimental context change.
"""

import contextlib
import json
import math
import threading
import time

import numpy as np


def _stamp_sec(stamp):  # type: (Any) -> float
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def _yaw(quaternion):  # type: (Any) -> float
    return math.atan2(
        2.0 * (quaternion.w * quaternion.z + quaternion.x * quaternion.y),
        1.0 - 2.0 * (quaternion.y * quaternion.y + quaternion.z * quaternion.z),
    )


def _unwrap(values):  # type: (Sequence[float]) -> np.ndarray
    return np.unwrap(np.asarray(values, dtype=np.float64))


def estimate_velocity(samples):  # type: (List[Dict[str, float]]) -> Tuple[np.ndarray, np.ndarray]
    if len(samples) < 3:
        raise ValueError("reference measure window has fewer than 3 samples")
    stamps = np.asarray([row["stamp"] for row in samples], dtype=np.float64)
    stamps -= stamps[0]
    if np.any(np.diff(stamps) <= 0.0):
        raise ValueError("reference timestamps are not strictly increasing")
    values = np.column_stack(
        (
            [row["x"] for row in samples],
            [row["y"] for row in samples],
            _unwrap([row["yaw"] for row in samples]),
        )
    )
    design = np.column_stack((stamps, np.ones(len(stamps))))
    coefficients = np.linalg.lstsq(design, values, rcond=None)[0]
    slopes = coefficients[0]
    fitted = design.dot(coefficients)
    residual = values - fitted
    max(float(stamps[-1] - stamps[0]), 1e-6)
    residual_variance = np.var(residual, axis=0, ddof=min(1, len(samples) - 1))
    slope_variance = residual_variance / max(float(np.sum((stamps - stamps.mean()) ** 2)), 1e-9)
    mean_yaw = float(np.mean(values[:, 2]))
    cosine, sine = math.cos(mean_yaw), math.sin(mean_yaw)
    body = np.asarray(
        (cosine * slopes[0] + sine * slopes[1], -sine * slopes[0] + cosine * slopes[1], slopes[2])
    )
    rotation = np.asarray(((cosine, sine, 0.0), (-sine, cosine, 0.0), (0.0, 0.0, 1.0)))
    covariance = rotation.dot(np.diag(slope_variance)).dot(rotation.T)
    return body, covariance


class FakeBackend:
    """Deterministic immediate backend used for full workflow tests."""

    def __init__(self, config, trace):  # type: (Dict[str, Any], Any) -> None
        self.config = config
        self.trace = trace
        fake = config.get("fake", {})
        self.matrix = np.asarray(
            fake.get(
                "dynamics_matrix", [[0.82, 0.03, 0.02], [0.01, 0.78, -0.02], [0.02, 0.01, 0.86]]
            ),
            dtype=np.float64,
        )
        self.bias = np.asarray(fake.get("dynamics_bias", [0.01, -0.005, 0.008]), dtype=np.float64)
        self.tick = 0

    def execute_trial(self, identity, command, profile, adapter_matrix=None):
        # type: (Dict[str, Any], Sequence[float], Dict[str, Any], Optional[Sequence[Sequence[float]]]) -> Dict[str, Any]
        planned = np.asarray(command, dtype=np.float64)
        sent = planned.copy()
        if adapter_matrix is not None:
            sent = np.asarray(adapter_matrix, dtype=np.float64).dot(sent)
        measured = self.matrix.dot(sent) + self.bias
        phase_start = float(self.tick)
        self.tick += 1
        covariance = np.diag([0.0004, 0.0004, 0.0009])
        result = {
            "planned_command": planned.tolist(),
            "sent_command": sent.tolist(),
            "measured_velocity": measured.tolist(),
            "covariance": covariance.tolist(),
            "valid": True,
            "reason": "",
            "sample_count": 101,
            "measure_start": phase_start + float(profile["ramp_in_s"]) + float(profile["settle_s"]),
            "measure_end": phase_start
            + float(profile["ramp_in_s"])
            + float(profile["settle_s"])
            + float(profile["measure_s"]),
            "reference_max_age_ms": 0.0,
            "scan_max_age_ms": 0.0,
            "terminal_reason": "completed",
        }
        self.trace.write(dict(identity, event="fake_trial", **result))
        return result

    def run_navigation(self, identity, route, model, transform, raw_method, timeout_s):
        # type: (Dict[str, Any], Dict[str, Any], Any, Any, bool, float) -> Dict[str, Any]
        desired_commands = route.get(
            "fake_desired_commands", [[0.25, 0.0, 0.10], [0.28, 0.0, -0.08], [0.20, 0.0, 0.0]]
        )
        path = 0.0
        for index, desired_value in enumerate(desired_commands):
            desired = np.asarray(desired_value, dtype=np.float64)
            if raw_method:
                sent, diagnostics = desired, {"candidate_id": "raw", "inverse_objective": 0.0}
            else:
                sent, diagnostics = transform.apply(desired, model)
            measured = self.matrix.dot(sent) + self.bias
            path += float(np.linalg.norm(measured[:2])) * 0.04
            self.trace.write(
                dict(
                    identity,
                    event="navigation_tick",
                    tick=index,
                    desired_action=desired.tolist(),
                    sent_action=sent.tolist(),
                    scan_age_ms=0.0,
                    reference_age_ms=0.0,
                    planned_action_age_ms=0.0,
                    sent_action_age_ms=0.0,
                    diagnostics=diagnostics,
                )
            )
        return {
            "status": "SUCCESS",
            "terminal_reason": "reached",
            "success": True,
            "collision": False,
            "duration_s": min(1.0, timeout_s),
            "path_length_m": path,
            "final_goal_distance_m": 0.0,
            "route_goal_count": len(route.get("waypoints", [])) + 1,
            "waypoints_reached": len(route.get("waypoints", [])),
            "trace_ticks": len(desired_commands),
            "max_scan_age_ms": 0.0,
            "max_reference_age_ms": 0.0,
            "max_sent_action_age_ms": 0.0,
        }

    def io_check(self, duration_s):  # type: (float) -> Dict[str, Any]
        return {
            "backend": "fake",
            "duration_s": duration_s,
            "valid": True,
            "topics": {
                "scan": {"rate_hz": 50.0, "max_age_ms": 0.0, "empty_frames": 0},
                "reference": {"rate_hz": 50.0, "max_age_ms": 0.0},
                "planned_action": {"rate_hz": 25.0, "max_age_ms": 0.0},
            },
        }

    def close(self):  # type: () -> None
        return None


class Go2RosBackend:
    """Direct ROS 2 Sport request adapter and synchronized reference recorder."""

    MOVE_API_ID = 1008

    def __init__(self, config, trace, arm=False):  # type: (Dict[str, Any], Any, bool) -> None
        try:
            import rclpy
            from geometry_msgs.msg import Point, PoseStamped, Twist
            from nav_msgs.msg import Odometry
            from rclpy.node import Node
            from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
            from sensor_msgs.msg import LaserScan
            from std_msgs.msg import Bool, String
            from unitree_api.msg import Request
        except ImportError as exc:
            raise RuntimeError(
                "ROS 2/Unitree Python messages are unavailable; source the P8 environment"
            ) from exc

        self._rclpy = rclpy
        self._Request = Request
        self._PoseStamped = PoseStamped
        self._Point = Point
        self.config = config
        self.trace = trace
        self.arm = bool(arm)
        self.lock = threading.Lock()
        self.latest_ref = None  # type: Optional[Dict[str, Any]]
        self.latest_scan = None  # type: Optional[Dict[str, Any]]
        self.latest_planned = None  # type: Optional[Dict[str, Any]]
        self.latest_status = ""
        self.collision = False
        self.counts = {"reference": 0, "scan": 0, "planned_action": 0}
        self.times = {"reference": [], "scan": [], "planned_action": []}  # type: Dict[str, List[float]]
        self.ages = {"reference": [], "scan": []}  # type: Dict[str, List[float]]
        self.scan_valid_beams = []  # type: List[int]
        self.request_id = 0
        if not rclpy.ok():
            rclpy.init()
        topics = config["topics"]
        outer = self

        class P8Node(Node):
            def __init__(self):
                Node.__init__(self, "calibagent_p8_real")
                sensor_qos = QoSProfile(
                    reliability=ReliabilityPolicy.BEST_EFFORT,
                    history=HistoryPolicy.KEEP_LAST,
                    depth=1,
                )
                self.create_subscription(Odometry, topics["reference"], self._reference, sensor_qos)
                self.create_subscription(LaserScan, topics["scan"], self._scan, sensor_qos)
                self.create_subscription(Twist, topics["planned_action"], self._planned, 1)
                self.create_subscription(String, topics["navigation_status"], self._status, 10)
                self.create_subscription(Bool, topics["collision"], self._collision, 10)
                self.command_pub = self.create_publisher(Request, topics["sport_request"], 10)
                self.goal_pub = self.create_publisher(PoseStamped, topics["goal"], 10)
                self.relative_goal_pub = self.create_publisher(Point, topics["relative_goal"], 10)

            def _reference(self, message):
                receive = time.time()
                pose = message.pose.pose
                stamp = _stamp_sec(message.header.stamp)
                row = {
                    "stamp": stamp,
                    "receive": receive,
                    "age_ms": (receive - stamp) * 1000.0,
                    "x": float(pose.position.x),
                    "y": float(pose.position.y),
                    "z": float(pose.position.z),
                    "yaw": _yaw(pose.orientation),
                    "frame": str(message.header.frame_id),
                    "child_frame": str(message.child_frame_id),
                }
                with outer.lock:
                    outer.latest_ref = row
                    outer.counts["reference"] += 1
                    outer.times["reference"].append(receive)
                    outer.ages["reference"].append(row["age_ms"])

            def _scan(self, message):
                receive = time.time()
                ranges = np.asarray(message.ranges, dtype=np.float64)
                valid = (
                    np.isfinite(ranges)
                    & (ranges >= float(message.range_min))
                    & (ranges <= float(message.range_max))
                )
                stamp = _stamp_sec(message.header.stamp)
                valid_beams = int(np.count_nonzero(valid))
                row = {
                    "stamp": stamp,
                    "receive": receive,
                    "age_ms": (receive - stamp) * 1000.0,
                    "frame": str(message.header.frame_id),
                    "range_min": float(message.range_min),
                    "range_max": float(message.range_max),
                    "beams": len(ranges),
                    "valid_beams": valid_beams,
                }
                with outer.lock:
                    row["sequence"] = outer.counts["scan"] + 1
                    outer.counts["scan"] += 1
                    outer.times["scan"].append(receive)
                    outer.ages["scan"].append(row["age_ms"])
                    outer.scan_valid_beams.append(valid_beams)
                    outer.latest_scan = row

            def _planned(self, message):
                receive = time.time()
                row = {
                    "receive": receive,
                    "command": [
                        float(message.linear.x),
                        float(message.linear.y),
                        float(message.angular.z),
                    ],
                    "sequence": outer.counts["planned_action"] + 1,
                }
                with outer.lock:
                    outer.latest_planned = row
                    outer.counts["planned_action"] += 1
                    outer.times["planned_action"].append(receive)

            def _status(self, message):
                with outer.lock:
                    outer.latest_status = str(message.data)

            def _collision(self, message):
                with outer.lock:
                    outer.collision = bool(message.data)

        self.node = P8Node()
        self.thread = threading.Thread(target=rclpy.spin, args=(self.node,), daemon=True)
        self.thread.start()

    def now(self):  # type: () -> float
        return float(self.node.get_clock().now().nanoseconds) * 1e-9

    def snapshot(self):  # type: () -> Dict[str, Any]
        with self.lock:
            return {
                "reference": dict(self.latest_ref) if self.latest_ref else None,
                "scan": dict(self.latest_scan) if self.latest_scan else None,
                "planned": dict(self.latest_planned) if self.latest_planned else None,
                "status": self.latest_status,
                "collision": self.collision,
            }

    def send(self, command, identity, source):  # type: (Sequence[float], Dict[str, Any], str) -> float
        values = [float(value) for value in command]
        stamp = self.now()
        if self.arm:
            request = self._Request()
            self.request_id += 1
            request.header.identity.id = self.request_id
            request.header.identity.api_id = self.MOVE_API_ID
            request.parameter = json.dumps(
                {"x": values[0], "y": values[1], "z": values[2]}, separators=(",", ":")
            )
            self.node.command_pub.publish(request)
        self.trace.write(
            dict(
                identity,
                event="sent_action",
                sent_ros_time=stamp,
                sent_action=values,
                source=source,
                armed=self.arm,
            )
        )
        return stamp

    def wait_inputs(self, timeout_s, require_planned=False):  # type: (float, bool) -> None
        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            value = self.snapshot()
            if value["reference"] and value["scan"] and (value["planned"] or not require_planned):
                return
            time.sleep(0.02)
        raise RuntimeError("timed out waiting for P8 ROS inputs")

    def execute_trial(self, identity, command, profile, adapter_matrix=None):
        # type: (Dict[str, Any], Sequence[float], Dict[str, Any], Optional[Sequence[Sequence[float]]]) -> Dict[str, Any]
        self.wait_inputs(float(self.config.get("input_wait_s", 10.0)))
        planned = np.asarray(command, dtype=np.float64)
        target = (
            planned
            if adapter_matrix is None
            else np.asarray(adapter_matrix, dtype=np.float64).dot(planned)
        )
        rate = float(profile.get("command_rate_hz", 50.0))
        period = 1.0 / rate
        ramp_in = float(profile["ramp_in_s"])
        settle = float(profile["settle_s"])
        measure = float(profile["measure_s"])
        ramp_out = float(profile["ramp_out_s"])
        total = ramp_in + settle + measure + ramp_out
        start = time.monotonic()
        measure_samples = []  # type: List[Dict[str, float]]
        ref_ages = []  # type: List[float]
        scan_ages = []  # type: List[float]
        sent_values = []  # type: List[List[float]]
        next_tick = start
        try:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= total:
                    break
                if elapsed < ramp_in:
                    scale = elapsed / max(ramp_in, 1e-9)
                    phase = "ramp_in"
                elif elapsed < ramp_in + settle:
                    scale, phase = 1.0, "settle"
                elif elapsed < ramp_in + settle + measure:
                    scale, phase = 1.0, "measure"
                else:
                    scale = 1.0 - (elapsed - ramp_in - settle - measure) / max(ramp_out, 1e-9)
                    phase = "ramp_out"
                sent = target * scale
                sent_stamp = self.send(sent, identity, phase)
                sent_values.append(sent.tolist())
                snapshot = self.snapshot()
                reference = snapshot["reference"]
                scan = snapshot["scan"]
                if reference:
                    ref_ages.append((sent_stamp - float(reference["stamp"])) * 1000.0)
                    if phase == "measure" and (
                        not measure_samples or reference["stamp"] > measure_samples[-1]["stamp"]
                    ):
                        measure_samples.append(reference)
                if scan:
                    scan_ages.append((sent_stamp - float(scan["stamp"])) * 1000.0)
                next_tick += period
                time.sleep(max(0.0, next_tick - time.monotonic()))
        finally:
            self.send((0.0, 0.0, 0.0), identity, "trial_end")
        valid, reason = True, ""
        try:
            measured, covariance = estimate_velocity(measure_samples)
        except ValueError as exc:
            measured, covariance = np.full(3, np.nan), np.full((3, 3), np.nan)
            valid, reason = False, str(exc)
        quality = self.config.get("quality", {})
        max_reference_age = max(ref_ages) if ref_ages else float("inf")
        max_scan_age = max(scan_ages) if scan_ages else float("inf")
        if max_reference_age > float(quality.get("max_reference_age_ms", 80.0)):
            valid, reason = False, "reference age exceeded data-quality threshold"
        return {
            "planned_command": planned.tolist(),
            "sent_command": target.tolist(),
            "measured_velocity": measured.tolist(),
            "covariance": covariance.tolist(),
            "valid": valid,
            "reason": reason,
            "sample_count": len(measure_samples),
            "measure_start": self.now() - ramp_out - measure,
            "measure_end": self.now() - ramp_out,
            "reference_max_age_ms": max_reference_age,
            "scan_max_age_ms": max_scan_age,
            "terminal_reason": "completed" if valid else "invalid_observation",
        }

    def publish_goal(self, goal, frame):  # type: (Dict[str, Any], str) -> None
        message = self._PoseStamped()
        message.header.frame_id = str(frame)
        message.header.stamp = self.node.get_clock().now().to_msg()
        message.pose.position.x = float(goal["x"])
        message.pose.position.y = float(goal["y"])
        half = 0.5 * float(goal.get("yaw", 0.0))
        message.pose.orientation.z = math.sin(half)
        message.pose.orientation.w = math.cos(half)
        self.node.goal_pub.publish(message)

    def run_navigation(self, identity, route, model, transform, raw_method, timeout_s):
        # type: (Dict[str, Any], Dict[str, Any], Any, Any, bool, float) -> Dict[str, Any]
        self.wait_inputs(float(self.config.get("input_wait_s", 10.0)), require_planned=False)
        with self.lock:
            self.latest_status = ""
            self.collision = False
        route_goals = list(route.get("waypoints", [])) + [route["goal_pose"]]
        route_frame = str(route.get("frame", "map"))
        goal_index = 0
        awaiting_goal_acceptance = True
        self.publish_goal(route_goals[goal_index], route_frame)
        self.trace.write(
            dict(
                identity,
                event="route_goal_published",
                route_goal_index=goal_index,
                route_goal=route_goals[goal_index],
                timestamp=time.time(),
            )
        )
        start = time.monotonic()
        self.snapshot()["reference"]
        previous_position = None  # type: Optional[np.ndarray]
        path_length = 0.0
        last_sequence = -1
        ticks = 0
        scan_ages = []  # type: List[float]
        reference_ages = []  # type: List[float]
        action_ages = []  # type: List[float]
        terminal = "timeout"
        success = False
        collision = False
        try:
            while time.monotonic() - start < float(timeout_s):
                snapshot = self.snapshot()
                reference = snapshot["reference"]
                if reference:
                    position = np.asarray((reference["x"], reference["y"]), dtype=np.float64)
                    if previous_position is not None:
                        path_length += float(np.linalg.norm(position - previous_position))
                    previous_position = position
                planned = snapshot["planned"]
                if planned and int(planned["sequence"]) != last_sequence:
                    last_sequence = int(planned["sequence"])
                    desired = np.asarray(planned["command"], dtype=np.float64)
                    if raw_method:
                        sent, diagnostics = (
                            desired,
                            {"candidate_id": "raw", "inverse_objective": 0.0},
                        )
                    else:
                        sent, diagnostics = transform.apply(desired, model)
                    sent_stamp = self.send(sent, identity, "navigation")
                    scan_age = (
                        (sent_stamp - float(snapshot["scan"]["stamp"])) * 1000.0
                        if snapshot["scan"]
                        else float("nan")
                    )
                    reference_age = (
                        (sent_stamp - float(reference["stamp"])) * 1000.0
                        if reference
                        else float("nan")
                    )
                    action_age = (time.time() - float(planned["receive"])) * 1000.0
                    scan_ages.append(scan_age)
                    reference_ages.append(reference_age)
                    action_ages.append(action_age)
                    self.trace.write(
                        dict(
                            identity,
                            event="navigation_tick",
                            tick=ticks,
                            desired_action=desired.tolist(),
                            sent_action=sent.tolist(),
                            scan_age_ms=scan_age,
                            reference_age_ms=reference_age,
                            planned_action_age_ms=action_age,
                            sent_action_age_ms=action_age,
                            diagnostics=diagnostics,
                        )
                    )
                    ticks += 1
                if snapshot["collision"]:
                    collision, terminal = True, "collision"
                    break
                status = str(snapshot["status"])
                reached = status.startswith("REACHED")
                if status.startswith("NAVIGATING"):
                    awaiting_goal_acceptance = False
                elif not awaiting_goal_acceptance:
                    if goal_index + 1 < len(route_goals):
                        goal_index += 1
                        awaiting_goal_acceptance = True
                        with self.lock:
                            self.latest_status = ""
                        self.publish_goal(route_goals[goal_index], route_frame)
                        self.trace.write(
                            dict(
                                identity,
                                event="route_goal_published",
                                route_goal_index=goal_index,
                                route_goal=route_goals[goal_index],
                                timestamp=time.time(),
                            )
                        )
                    else:
                        success, terminal = True, "reached"
                        break
                time.sleep(0.005)
        finally:
            self.send((0.0, 0.0, 0.0), identity, "navigation_end")
        final_ref = self.snapshot()["reference"]
        final_distance = float("nan")
        if final_ref:
            goal = route["goal_pose"]
            final_distance = math.hypot(
                float(goal["x"]) - float(final_ref["x"]), float(goal["y"]) - float(final_ref["y"])
            )
        return {
            "status": "SUCCESS" if success else "RESULT",
            "terminal_reason": terminal,
            "success": success and not collision,
            "collision": collision,
            "duration_s": time.monotonic() - start,
            "path_length_m": path_length,
            "final_goal_distance_m": final_distance,
            "route_goal_count": len(route_goals),
            "waypoints_reached": goal_index if success else min(goal_index, len(route_goals) - 1),
            "trace_ticks": ticks,
            "max_scan_age_ms": max(scan_ages) if scan_ages else float("nan"),
            "max_reference_age_ms": max(reference_ages) if reference_ages else float("nan"),
            "max_sent_action_age_ms": max(action_ages) if action_ages else float("nan"),
        }

    def io_check(self, duration_s):  # type: (float) -> Dict[str, Any]
        with self.lock:
            baseline = dict(self.counts)
        start = time.time()
        while time.time() - start < duration_s:
            time.sleep(0.02)
        elapsed = max(time.time() - start, 1e-6)
        with self.lock:
            final_counts = dict(self.counts)
            new_times = {
                key: list(self.times[key][baseline[key] : final_counts[key]]) for key in baseline
            }
            scan_ages = list(self.ages["scan"][baseline["scan"] : final_counts["scan"]])
            reference_ages = list(
                self.ages["reference"][baseline["reference"] : final_counts["reference"]]
            )
            beam_counts = list(
                self.scan_valid_beams[baseline["scan"] : final_counts["scan"]]
            )
            snapshot = {
                "scan": dict(self.latest_scan) if self.latest_scan else None,
                "reference": dict(self.latest_ref) if self.latest_ref else None,
                "planned": dict(self.latest_planned) if self.latest_planned else None,
            }
        rates = {key: (final_counts[key] - baseline[key]) / elapsed for key in baseline}
        max_gaps = {}
        for key, values in new_times.items():
            max_gaps[key] = (
                max((right - left) * 1000.0 for left, right in zip(values, values[1:]))
                if len(values) >= 2
                else float("inf")
            )
        quality = self.config.get("quality", {})
        max_scan_age = max(scan_ages) if scan_ages else float("inf")
        max_reference_age = max(reference_ages) if reference_ages else float("inf")
        planned_receive_age = (
            (time.time() - float(snapshot["planned"]["receive"])) * 1000.0
            if snapshot["planned"]
            else float("inf")
        )
        max_planned_receive_age = max(max_gaps["planned_action"], planned_receive_age)
        zero_valid_beam_frames = sum(value == 0 for value in beam_counts)
        valid = bool(
            rates["scan"] >= float(quality.get("min_scan_rate_hz", 15.0))
            and rates["reference"] >= float(quality.get("min_reference_rate_hz", 10.0))
            and rates["planned_action"] >= float(quality.get("min_planned_action_rate_hz", 20.0))
            and max_scan_age <= float(quality.get("max_scan_age_ms", 80.0))
            and max_reference_age <= float(quality.get("max_reference_age_ms", 80.0))
            and max_planned_receive_age
            <= float(quality.get("max_planned_action_receive_age_ms", 80.0))
            and zero_valid_beam_frames == 0
        )
        return {
            "backend": "ros",
            "duration_s": elapsed,
            "valid": valid,
            "topics": {
                "scan": {
                    "frames": len(beam_counts),
                    "rate_hz": rates["scan"],
                    "max_age_ms": max_scan_age,
                    "max_gap_ms": max_gaps["scan"],
                    "zero_valid_beam_frames": zero_valid_beam_frames,
                    "minimum_valid_beams": min(beam_counts) if beam_counts else None,
                    "range_min": snapshot["scan"]["range_min"] if snapshot["scan"] else None,
                    "range_max": snapshot["scan"]["range_max"] if snapshot["scan"] else None,
                    "valid_beams": snapshot["scan"]["valid_beams"] if snapshot["scan"] else None,
                },
                "reference": {
                    "frames": len(reference_ages),
                    "rate_hz": rates["reference"],
                    "max_age_ms": max_reference_age,
                    "max_gap_ms": max_gaps["reference"],
                },
                "planned_action": {
                    "frames": len(new_times["planned_action"]),
                    "rate_hz": rates["planned_action"],
                    "max_gap_ms": max_gaps["planned_action"],
                    "max_receive_age_ms": max_planned_receive_age,
                    "receive_age_ms_at_end": planned_receive_age,
                },
            },
        }

    def close(self):  # type: () -> None
        if self.arm:
            with contextlib.suppress(Exception):
                self.send((0.0, 0.0, 0.0), {"run_id": "shutdown"}, "shutdown")
        self.node.destroy_node()
        if self._rclpy.ok():
            self._rclpy.shutdown()
        self.thread.join(timeout=2.0)
