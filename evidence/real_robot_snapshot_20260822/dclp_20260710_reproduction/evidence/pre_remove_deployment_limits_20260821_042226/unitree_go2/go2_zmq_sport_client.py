#!/usr/bin/env python3
"""ZMQ velocity client for Unitree Go2 SportClient.

The input protocol matches the existing demo_cmd.py script:
JSON [linear, angular]. Dict payloads with v/w or linear/angular are accepted
too so local policy scripts can be a little more explicit.
"""

import argparse
import ipaddress
import json
import os
import signal
import sys
import time
from typing import Any, Tuple

import zmq


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def parse_cmd(payload: Any) -> Tuple[float, float]:
    if isinstance(payload, dict):
        if "linear" in payload:
            linear = payload["linear"]
        elif "v" in payload:
            linear = payload["v"]
        else:
            raise ValueError("missing linear/v")

        if "angular" in payload:
            angular = payload["angular"]
        elif "w" in payload:
            angular = payload["w"]
        elif "yaw" in payload:
            angular = payload["yaw"]
        else:
            raise ValueError("missing angular/w/yaw")
        return float(linear), float(angular)

    if isinstance(payload, (list, tuple)) and len(payload) >= 2:
        return float(payload[0]), float(payload[1])

    raise ValueError("expected JSON list [linear, angular] or dict")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def interface_ipv4_addresses(name: str):
    try:
        output = os.popen(f"ip -4 -o addr show dev {name}").read()
    except OSError:
        return []

    addresses = []
    for line in output.splitlines():
        parts = line.split()
        if "inet" not in parts:
            continue
        value = parts[parts.index("inet") + 1]
        addresses.append(value.split("/", 1)[0])
    return addresses


def available_interfaces():
    base = "/sys/class/net"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    return [name for name in names if name != "lo"]


def interface_exists(name: str) -> bool:
    return os.path.exists(os.path.join("/sys/class/net", name))


def choose_auto_interface() -> str:
    unitree_net = ipaddress.ip_network("192.168.123.0/24")
    candidates = available_interfaces()

    for name in candidates:
        for addr in interface_ipv4_addresses(name):
            if ipaddress.ip_address(addr) in unitree_net:
                return name

    for name in ("eth1", "eth0"):
        if name in candidates:
            return name
    if candidates:
        return candidates[0]

    raise RuntimeError("no non-loopback network interface found")


def resolve_interface(requested: str) -> str:
    if requested == "auto":
        selected = choose_auto_interface()
        print(f"[go2:sport] auto-selected interface: {selected}", flush=True)
        return selected

    if interface_exists(requested) and interface_ipv4_addresses(requested):
        return requested

    selected = choose_auto_interface()
    if interface_exists(requested):
        reason = "exists but has no IPv4 address"
    else:
        reason = "does not exist"
    available = ", ".join(available_interfaces()) or "none"
    raise RuntimeError(
        f"interface '{requested}' {reason}. Available interfaces: {available}. "
        f"Try '{selected}' or use 'auto'."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unitree Go2 ZMQ velocity client")
    parser.add_argument("iface", nargs="?", default=os.environ.get("GO2_IFACE", "auto"))
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("GO2_ZMQ_ENDPOINT", "tcp://192.168.123.222:5596"),
        help="ZMQ PUB endpoint to subscribe to",
    )
    parser.add_argument(
        "--recv-timeout-ms",
        type=int,
        default=int(env_float("GO2_RECV_TIMEOUT_MS", 100)),
    )
    parser.add_argument(
        "--max-action-age-ms",
        type=float,
        default=env_float("GO2_MAX_ACTION_AGE_MS", 80.0),
        help="Reject non-zero commands older than this from scan stamp to ZMQ receive; <=0 disables.",
    )
    parser.add_argument(
        "--max-policy-lag-ms",
        type=float,
        default=env_float("GO2_MAX_POLICY_LAG_MS", 20.0),
        help="Reject non-zero commands whose policy-to-ZMQ transport lag exceeds this; <=0 disables.",
    )
    parser.add_argument(
        "--max-odom-age-ms",
        type=float,
        default=env_float("GO2_MAX_ODOM_AGE_MS", 50.0),
        help="Reject non-zero commands based on odometry older than this; <=0 disables.",
    )
    parser.add_argument(
        "--max-linear",
        type=float,
        default=env_float("GO2_MAX_LINEAR", 0.66),
    )
    parser.add_argument(
        "--max-angular",
        type=float,
        default=env_float("GO2_MAX_ANGULAR", 0.56),
    )
    parser.add_argument(
        "--allow-reverse",
        action="store_true",
        default=env_bool("GO2_ALLOW_REVERSE", False),
    )
    parser.add_argument(
        "--keep-obstacle-avoid",
        action="store_true",
        default=not env_bool("GO2_DISABLE_OBSTACLE_AVOID", True),
        help="Keep Unitree built-in obstacle avoidance enabled",
    )
    parser.add_argument(
        "--gait",
        choices=[
            "economic",
            "classic",
            "classic-off",
            "normal",
            "static",
            "trot",
            "balance",
            "recovery",
            "none",
        ],
        default=os.environ.get("GO2_GAIT", "economic"),
        help="Switch sport gait after SportClient.Init; use none to skip",
    )
    parser.add_argument(
        "--allow-gait-failure",
        action="store_true",
        default=env_bool("GO2_ALLOW_GAIT_FAILURE", False),
        help="Continue even if the requested gait switch fails",
    )
    parser.add_argument(
        "--disable-joystick",
        action="store_true",
        default=env_bool("GO2_DISABLE_JOYSTICK", True),
        help="Disable wireless controller joystick commands while this DCLP client is running",
    )
    parser.add_argument(
        "--keep-joystick-disabled-on-exit",
        action="store_true",
        default=env_bool("GO2_KEEP_JOYSTICK_DISABLED_ON_EXIT", False),
        help="Do not restore joystick commands when this client exits",
    )
    parser.add_argument(
        "--allow-joystick-switch-failure",
        action="store_true",
        default=env_bool("GO2_ALLOW_JOYSTICK_SWITCH_FAILURE", False),
        help="Continue even if disabling/restoring joystick commands fails",
    )
    parser.add_argument(
        "--force-api-remote-command",
        action="store_true",
        default=env_bool("GO2_FORCE_API_REMOTE_COMMAND", True),
        help="Force remote-command source to API while this DCLP client is running",
    )
    parser.add_argument(
        "--keep-api-remote-command-on-exit",
        action="store_true",
        default=env_bool("GO2_KEEP_API_REMOTE_COMMAND_ON_EXIT", False),
        help="Do not restore remote-command source when this client exits",
    )
    parser.add_argument(
        "--sport-timeout",
        type=float,
        default=env_float("GO2_SPORT_TIMEOUT", 5.0),
        help="SportClient service timeout in seconds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=env_bool("GO2_DRY_RUN", False),
        help="Subscribe to policy ZMQ commands and log them, but do not initialize or command SportClient.",
    )
    parser.add_argument(
        "--zero-motion",
        action="store_true",
        default=env_bool("GO2_ZERO_MOTION", False),
        help="Initialize SportClient and receive policy commands, but replace every command with Move(0,0,0).",
    )
    return parser


def load_unitree_sdk():
    try:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        from unitree_sdk2py.go2.obstacles_avoid.obstacles_avoid_client import (
            ObstaclesAvoidClient,
        )
        from unitree_sdk2py.go2.sport.sport_api import SPORT_API_ID_ECONOMICGAIT
        from unitree_sdk2py.go2.sport.sport_client import SportClient
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("unitree_sdk2py"):
            print(
                "[go2:sport] cannot import unitree_sdk2py; "
                "run start_go2_zmq_sport_client.sh or activate the go2 conda env",
                file=sys.stderr,
                flush=True,
            )
            raise SystemExit(1)
        raise

    return ChannelFactoryInitialize, SportClient, ObstaclesAvoidClient, SPORT_API_ID_ECONOMICGAIT


def call_no_arg_api(client, api_id: int) -> int:
    code, _ = client._Call(api_id, json.dumps({}))
    return code


def switch_joystick(client, enabled: bool) -> int:
    if not hasattr(client, "SwitchJoystick"):
        raise RuntimeError("SportClient has no SwitchJoystick API")
    return client.SwitchJoystick(bool(enabled))


def switch_gait(client, gait: str, economic_api_id: int) -> int:
    if gait == "none":
        return 0
    if gait == "classic":
        return client.ClassicWalk(True)
    if gait in ("classic-off", "normal"):
        return client.ClassicWalk(False)
    if gait == "economic":
        return call_no_arg_api(client, economic_api_id)
    if gait == "static":
        return client.StaticWalk()
    if gait == "trot":
        return client.TrotRun()
    if gait == "balance":
        return client.BalanceStand()
    if gait == "recovery":
        return client.RecoveryStand()
    raise ValueError(f"unsupported gait: {gait}")


class Go2ZmqSportClient:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
        self.socket.setsockopt(zmq.RCVTIMEO, int(args.recv_timeout_ms))
        self.socket.setsockopt(zmq.CONFLATE, 1)

        if args.dry_run:
            self.channel_factory_initialize = None
            self.sport_client_cls = None
            self.obstacle_client_cls = None
            self.economic_gait_api_id = None
        else:
            (
                self.channel_factory_initialize,
                self.sport_client_cls,
                self.obstacle_client_cls,
                self.economic_gait_api_id,
            ) = load_unitree_sdk()
        self.sport_client = None
        self.obstacle_client = None
        self.running = True
        self.stopped = False
        self.cmd_count = 0
        self.stale_count = 0
        self.last_cmd_time = None
        self.joystick_disabled = False
        self.api_remote_command_forced = False

    def start(self) -> None:
        print(f"[go2:sport] connecting zmq: {self.args.endpoint}", flush=True)
        self.socket.connect(self.args.endpoint)
        if self.args.dry_run:
            print("[go2:sport] DRY RUN: SportClient is not initialized; commands will only be logged", flush=True)
            return

        iface = resolve_interface(self.args.iface)
        print(f"[go2:sport] ChannelFactoryInitialize iface={iface}", flush=True)
        self.channel_factory_initialize(0, iface)

        self.sport_client = self.sport_client_cls()
        self.obstacle_client = self.obstacle_client_cls()
        self.sport_client.SetTimeout(self.args.sport_timeout)
        self.sport_client.Init()
        print("[go2:sport] SportClient ready", flush=True)

        if self.args.disable_joystick:
            code = switch_joystick(self.sport_client, False)
            if code != 0:
                message = f"[go2:sport] disable joystick failed: {code}"
                if not self.args.allow_joystick_switch_failure:
                    raise RuntimeError(message)
                print(message, flush=True)
            else:
                self.joystick_disabled = True
                print("[go2:sport] joystick commands disabled for DCLP", flush=True)

        code = switch_gait(self.sport_client, self.args.gait, self.economic_gait_api_id)
        if code != 0:
            message = f"[go2:sport] gait switch '{self.args.gait}' failed: {code}"
            if not self.args.allow_gait_failure:
                raise RuntimeError(message)
            print(message, flush=True)
        elif self.args.gait != "none":
            print(f"[go2:sport] gait switch '{self.args.gait}' success", flush=True)

        self.obstacle_client.Init()
        if not self.args.keep_obstacle_avoid:
            code = self.obstacle_client.SwitchSet(False)
            if code != 0:
                print(f"[go2:sport] obstacle avoid switch error: {code}", flush=True)
            else:
                print("[go2:sport] obstacle avoid disabled", flush=True)
        else:
            print("[go2:sport] obstacle avoid kept enabled", flush=True)

        if self.args.force_api_remote_command:
            try:
                code = self.obstacle_client.UseRemoteCommandFromApi(True)
                if code != 0:
                    print(f"[go2:sport] force API remote-command source failed: {code}", flush=True)
                else:
                    self.api_remote_command_forced = True
                    print("[go2:sport] remote-command source forced to API", flush=True)
            except Exception as exc:
                print(f"[go2:sport] force API remote-command source failed: {exc!r}", flush=True)

    def stop_robot(self, use_stop_move: bool = False) -> None:
        if self.sport_client is None:
            self.stopped = True
            return
        try:
            if use_stop_move and hasattr(self.sport_client, "StopMove"):
                self.sport_client.StopMove()
            else:
                self.sport_client.Move(0.0, 0.0, 0.0)
        except Exception as exc:
            print(f"[go2:sport] stop failed: {exc!r}", flush=True)
        self.stopped = True

    def handle_message(self, message: str) -> None:
        payload = json.loads(message)
        linear, angular = parse_cmd(payload)

        min_linear = -self.args.max_linear if self.args.allow_reverse else 0.0
        linear = clamp(linear, min_linear, self.args.max_linear)
        angular = clamp(angular, -self.args.max_angular, self.args.max_angular)
        now = time.monotonic()
        dt_ms = 0.0 if self.last_cmd_time is None else (now - self.last_cmd_time) * 1000.0
        self.last_cmd_time = now
        self.cmd_count += 1

        policy_lag_ms = None
        scan_age_ms = None
        odom_age_ms = None
        action_age_ms = None
        seq = None
        if isinstance(payload, dict):
            seq = payload.get("seq")
            send_mono = payload.get("send_monotonic")
            if send_mono is not None:
                try:
                    policy_lag_ms = (now - float(send_mono)) * 1000.0
                except (TypeError, ValueError):
                    policy_lag_ms = None
            try:
                scan_age_ms = float(payload["scan_age_ms"])
            except (KeyError, TypeError, ValueError):
                scan_age_ms = None
            try:
                odom_age_ms = float(payload["odom_age_ms"])
            except (KeyError, TypeError, ValueError):
                odom_age_ms = None
        if scan_age_ms is not None and policy_lag_ms is not None:
            action_age_ms = scan_age_ms + max(policy_lag_ms, 0.0)
        lag_text = ""
        if policy_lag_ms is not None:
            lag_text += " policy_zmq_lag=%.1fms" % policy_lag_ms
        if action_age_ms is not None:
            lag_text += " action_age=%.1fms" % action_age_ms
        if isinstance(payload, dict):
            for key, label in (
                ("scan_age_ms", "scan_age"),
                ("scan_rx_age_ms", "scan_rx_age"),
                ("odom_age_ms", "odom_age"),
                ("odom_rx_age_ms", "odom_rx_age"),
                ("sensor_stamp_skew_ms", "sensor_skew"),
                ("loop_to_send_ms", "loop_to_send"),
            ):
                value = payload.get(key)
                if value is not None:
                    try:
                        lag_text += " %s=%.1fms" % (label, float(value))
                    except (TypeError, ValueError):
                        pass
        seq_text = "" if seq is None else " seq=%s" % seq

        is_stop_command = abs(linear) <= 1e-9 and abs(angular) <= 1e-9
        stale_reasons = []
        if not is_stop_command:
            if self.args.max_action_age_ms > 0.0:
                if action_age_ms is None:
                    stale_reasons.append("missing_action_age")
                elif action_age_ms > self.args.max_action_age_ms:
                    stale_reasons.append(
                        "action_age=%.1fms>%.1fms"
                        % (action_age_ms, self.args.max_action_age_ms)
                    )
            if self.args.max_policy_lag_ms > 0.0:
                if policy_lag_ms is None:
                    stale_reasons.append("missing_policy_lag")
                elif policy_lag_ms > self.args.max_policy_lag_ms:
                    stale_reasons.append(
                        "policy_lag=%.1fms>%.1fms"
                        % (policy_lag_ms, self.args.max_policy_lag_ms)
                    )
            if self.args.max_odom_age_ms > 0.0:
                if odom_age_ms is None:
                    stale_reasons.append("missing_odom_age")
                elif odom_age_ms + max(policy_lag_ms or 0.0, 0.0) > self.args.max_odom_age_ms:
                    stale_reasons.append(
                        "odom_age=%.1fms>%.1fms"
                        % (
                            odom_age_ms + max(policy_lag_ms or 0.0, 0.0),
                            self.args.max_odom_age_ms,
                        )
                    )
        if stale_reasons:
            self.stale_count += 1
            print(
                "[go2:sport] STALE_DROP cmd#%d%s reasons=%s%s"
                % (self.cmd_count, seq_text, ",".join(stale_reasons), lag_text),
                flush=True,
            )
            self.stop_robot(use_stop_move=True)
            return

        if self.args.dry_run:
            self.stopped = False
            print(
                f"[go2:sport] DRY cmd#{self.cmd_count}{seq_text} v={linear:.3f} w={angular:.3f} dt={dt_ms:.1f}ms{lag_text}",
                flush=True,
            )
            return
        move_v = 0.0 if self.args.zero_motion else linear
        move_w = 0.0 if self.args.zero_motion else angular
        t0 = time.perf_counter()
        ret = self.sport_client.Move(move_v, 0.0, move_w)
        move_ms = (time.perf_counter() - t0) * 1000.0
        self.stopped = False
        mode = " ZERO" if self.args.zero_motion else ""
        print(
            f"[go2:sport]{mode} cmd#{self.cmd_count}{seq_text} policy_v={linear:.3f} policy_w={angular:.3f} sent_v={move_v:.3f} sent_w={move_w:.3f} ret={ret} dt={dt_ms:.1f}ms move_ms={move_ms:.1f}{lag_text}",
            flush=True,
        )

    def spin(self) -> None:
        while self.running:
            try:
                message = self.socket.recv_string()
            except zmq.Again:
                continue

            try:
                self.handle_message(message)
            except Exception as exc:
                print(f"[go2:sport] bad command {message!r}: {exc}", flush=True)
                self.stop_robot(use_stop_move=True)

    def restore_api_remote_command(self) -> None:
        if not self.api_remote_command_forced or self.obstacle_client is None:
            return
        if self.args.keep_api_remote_command_on_exit:
            print("[go2:sport] remote-command source remains API on exit", flush=True)
            return
        try:
            code = self.obstacle_client.UseRemoteCommandFromApi(False)
            if code != 0:
                print(f"[go2:sport] restore remote-command source failed: {code}", flush=True)
            else:
                print("[go2:sport] remote-command source restored", flush=True)
        except Exception as exc:
            print(f"[go2:sport] restore remote-command source failed: {exc!r}", flush=True)
        finally:
            self.api_remote_command_forced = False

    def restore_joystick(self) -> None:
        if not self.joystick_disabled or self.sport_client is None:
            return
        if self.args.keep_joystick_disabled_on_exit:
            print("[go2:sport] joystick remains disabled on exit", flush=True)
            return
        try:
            code = switch_joystick(self.sport_client, True)
            if code != 0:
                message = f"[go2:sport] restore joystick failed: {code}"
                if not self.args.allow_joystick_switch_failure:
                    print(message, flush=True)
                else:
                    print(message, flush=True)
            else:
                print("[go2:sport] joystick commands restored", flush=True)
        except Exception as exc:
            print(f"[go2:sport] restore joystick failed: {exc!r}", flush=True)
        finally:
            self.joystick_disabled = False

    def shutdown(self) -> None:
        self.running = False
        if not self.args.dry_run:
            self.stop_robot(use_stop_move=True)
            self.restore_api_remote_command()
            self.restore_joystick()
        try:
            self.socket.close(0)
            self.context.term()
        except Exception:
            pass


def main() -> int:
    args = build_parser().parse_args()
    client = Go2ZmqSportClient(args)

    def _handle_signal(_signum, _frame):
        client.running = False

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        client.start()
        client.spin()
    finally:
        client.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
