#!/usr/bin/env bash
# Start DCLP policy control using Unitree /uwbstate as the goal source.

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"

START_POLICY="${START_POLICY:-1}"
START_GO2_ZMQ="${START_GO2_ZMQ:-1}"
START_UWB_GOAL="${START_UWB_GOAL:-1}"
WAIT_SCAN_TIMEOUT="${WAIT_SCAN_TIMEOUT:-12}"
WAIT_ODOM_TIMEOUT="${WAIT_ODOM_TIMEOUT:-12}"
WAIT_UWB_TIMEOUT="${WAIT_UWB_TIMEOUT:-60}"
WAIT_POLICY_READY_TIMEOUT="${WAIT_POLICY_READY_TIMEOUT:-45}"
POLICY_SCRIPT="${POLICY_SCRIPT:-${ROBOT_DIR}/dclp_go2_policy_ros2.py}"
GO2_CMD_SCRIPT="${GO2_CMD_SCRIPT:-${ROBOT_DIR}/go2_zmq_sport_client.py}"
UWB_GOAL_BRIDGE_SCRIPT="${UWB_GOAL_BRIDGE_SCRIPT:-${ROBOT_DIR}/go2_uwb_ros_goal_bridge.py}"

UWB_GOAL_FRAME="${UWB_GOAL_FRAME:-odom}"
UWB_POLICY_GOAL_TOLERANCE="${UWB_POLICY_GOAL_TOLERANCE:-0.20}"
if [[ "${UWB_GOAL_FRAME}" == "odom" ]]; then
  if [[ "${UNITREE_GO2_PARAM_SET_VARS:-:}" == *":POLICY_GLOBAL_FRAME:"* ]]; then
    export POLICY_GLOBAL_FRAME="odom"
  fi
  if [[ "${UNITREE_GO2_PARAM_SET_VARS:-:}" == *":GOAL_FRAME:"* ]]; then
    export GOAL_FRAME="odom"
  fi
fi
if [[ "${UNITREE_GO2_PARAM_SET_VARS:-:}" == *":POLICY_GOAL_TOLERANCE:"* ]]; then
  export POLICY_GOAL_TOLERANCE="${UWB_POLICY_GOAL_TOLERANCE}"
fi

if [[ "${START_POLICY}${START_GO2_ZMQ}${START_UWB_GOAL}" == *"1"* ]] && ! command -v gnome-terminal >/dev/null; then
  echo "[go2:uwb_policy] need gnome-terminal; start start_policy.sh, start_uwb_goal_bridge.sh, and start_go2_zmq_sport_client.sh manually" >&2
  exit 1
fi

run_terminal() {
  local title="$1"
  local body="$2"
  local terminal_cmd
  terminal_cmd="${body}
status=\$?
echo
echo \"[go2:uwb_policy] ${title} exited with status \${status}\"
exec bash"

  gnome-terminal --tab --title="${title}" -- env DVST2_TERMINAL_CMD="${terminal_cmd}" \
    bash -lc 'exec bash -ic "$DVST2_TERMINAL_CMD"'
}

already_running() {
  local pattern="$1"
  pgrep -af "${pattern}" >/dev/null 2>&1
}

wait_topic_message() {
  local label="$1"
  local topic="$2"
  local type="$3"
  local timeout="$4"
  if WAIT_SECONDS="${timeout}" bash "${ROBOT_DIR}/ros_topic_has_message.sh" "${topic}" "${type}"; then
    echo "[go2:uwb_policy] ${label} ready: ${topic}"
  else
    echo "[go2:uwb_policy] ${label} has no message within ${timeout}s: ${topic}" >&2
  fi
}

wait_policy_ready() {
  local deadline
  deadline=$((SECONDS + WAIT_POLICY_READY_TIMEOUT))
  while (( SECONDS < deadline )); do
    if bash "${ROBOT_DIR}/ros_topic_has_subscriber.sh" "${UWB_GOAL_TOPIC:-${GOAL_TOPIC:-/move_base_simple/goal}}" >/dev/null 2>&1; then
      echo "[go2:uwb_policy] policy goal subscriber ready"
      return 0
    fi
    sleep 1
  done
  echo "[go2:uwb_policy] policy goal subscriber not discovered after ${WAIT_POLICY_READY_TIMEOUT}s; continuing anyway" >&2
  return 1
}

wait_topic_message "scan" "${SCAN_TOPIC:-/scan}" sensor_msgs/msg/LaserScan "${WAIT_SCAN_TIMEOUT}"
wait_topic_message "odom" "${ODOM_TOPIC:-/odom}" nav_msgs/msg/Odometry "${WAIT_ODOM_TIMEOUT}"
QOS_RELIABILITY="${UWB_RELIABILITY:-reliable}" \
  wait_topic_message "uwb" "${UWB_ROS_TOPIC:-/uwbstate}" unitree_go/msg/UwbState "${WAIT_UWB_TIMEOUT}"

if [[ "${START_POLICY}" == "1" ]]; then
  if already_running "${POLICY_SCRIPT}"; then
    echo "[go2:uwb_policy] policy already running: ${POLICY_SCRIPT}"
else
    run_terminal "Go2 Policy" "POLICY_GLOBAL_FRAME=${POLICY_GLOBAL_FRAME:-} POLICY_GOAL_TOLERANCE=${POLICY_GOAL_TOLERANCE:-} POLICY_SCRIPT=${POLICY_SCRIPT} bash ${ROBOT_DIR}/start_policy.sh"
  fi
  wait_policy_ready || true
fi

if [[ "${START_UWB_GOAL}" == "1" ]]; then
  if already_running "${UWB_GOAL_BRIDGE_SCRIPT}"; then
    echo "[go2:uwb_policy] UWB goal bridge already running: ${UWB_GOAL_BRIDGE_SCRIPT}"
  else
    run_terminal "Go2 UWB Goal" "UWB_ROS_GOAL_BRIDGE_SCRIPT=${UWB_GOAL_BRIDGE_SCRIPT} bash ${ROBOT_DIR}/start_uwb_goal_bridge.sh"
    sleep 1
  fi
fi

if [[ "${START_GO2_ZMQ}" == "1" ]]; then
  if already_running "${GO2_CMD_SCRIPT}"; then
    echo "[go2:uwb_policy] Go2 ZMQ already running: ${GO2_CMD_SCRIPT}"
  else
    run_terminal "Go2 ZMQ" "GO2_CMD_SCRIPT=${GO2_CMD_SCRIPT} bash ${ROBOT_DIR}/start_go2_zmq_sport_client.sh"
    sleep 2
  fi
fi

echo "[go2:uwb_policy] started UWB policy task"
echo "[go2:uwb_policy] START_POLICY=${START_POLICY}, START_UWB_GOAL=${START_UWB_GOAL}, START_GO2_ZMQ=${START_GO2_ZMQ}"
echo "[go2:uwb_policy] POLICY_GLOBAL_FRAME=${POLICY_GLOBAL_FRAME:-<unset>}, POLICY_GOAL_TOLERANCE=${POLICY_GOAL_TOLERANCE:-<unset>}"
