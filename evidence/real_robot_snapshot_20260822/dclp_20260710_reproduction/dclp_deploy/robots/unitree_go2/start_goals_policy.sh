#!/usr/bin/env bash
# 定位收敛后手动启动神经网络导航任务：policy + Go2 ZMQ + 多目标序列。

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"
GOAL_LIST="${GOAL_LIST:-}"
AUTO_START="${AUTO_START:-1}"
GOAL_TIMEOUT="${GOAL_TIMEOUT:-120}"
POLICY_STATUS_TOPIC="${POLICY_STATUS_TOPIC:-/nav_status}"
STOP_ON_FAILURE="${STOP_ON_FAILURE:-1}"
START_POLICY="${START_POLICY:-1}"
START_GO2_ZMQ="${START_GO2_ZMQ:-1}"
WAIT_POLICY_READY_TIMEOUT="${WAIT_POLICY_READY_TIMEOUT:-45}"
WAIT_SCAN_TIMEOUT="${WAIT_SCAN_TIMEOUT:-12}"
POLICY_SCRIPT="${POLICY_SCRIPT:-${ROBOT_DIR}/dclp_go2_policy_ros2.py}"
GO2_CMD_SCRIPT="${GO2_CMD_SCRIPT:-${ROBOT_DIR}/go2_zmq_sport_client.py}"

if [[ -z "${GOAL_LIST}" || ! -f "${GOAL_LIST}" ]]; then
  echo "[go2:policy_goals] GOAL_LIST 未设置或不存在: ${GOAL_LIST}" >&2
  exit 1
fi

if ! command -v gnome-terminal >/dev/null; then
  echo "[go2:policy_goals] 需要 gnome-terminal；也可分终端手动运行 start_policy.sh、start_go2_zmq_sport_client.sh、start_goal_sequencer.sh" >&2
  exit 1
fi

run_terminal() {
  local title="$1"
  local body="$2"
  local terminal_cmd
  terminal_cmd="${body}
status=\$?
echo
echo \"[go2:policy_goals] exited with status \${status}\"
exec bash"

  gnome-terminal --tab --title="${title}" -- env DVST2_TERMINAL_CMD="${terminal_cmd}" \
    bash -lc 'exec bash -ic "$DVST2_TERMINAL_CMD"'
}

already_running() {
  local pattern="$1"
  pgrep -af "${pattern}" >/dev/null 2>&1
}

wait_policy_ready() {
  local deadline
  deadline=$((SECONDS + WAIT_POLICY_READY_TIMEOUT))
  while (( SECONDS < deadline )); do
    if bash "${ROBOT_DIR}/ros_topic_has_subscriber.sh" "${GOAL_TOPIC:-/move_base_simple/goal}" >/dev/null 2>&1; then
      echo "[go2:policy_goals] policy goal subscriber ready"
      return 0
    fi
    sleep 1
  done
  echo "[go2:policy_goals] policy goal subscriber not discovered after ${WAIT_POLICY_READY_TIMEOUT}s; continuing anyway" >&2
  return 1
}

if [[ "${START_POLICY}" == "1" ]]; then
  if WAIT_SECONDS="${WAIT_SCAN_TIMEOUT}" bash "${ROBOT_DIR}/ros_topic_has_message.sh" "${SCAN_TOPIC:-/scan}" sensor_msgs/msg/LaserScan; then
    echo "[go2:policy_goals] scan messages ready"
  else
    echo "[go2:policy_goals] /scan 没有在 ${WAIT_SCAN_TIMEOUT}s 内收到消息；请检查 Livox/pc2scan/TF" >&2
  fi

  if already_running "${POLICY_SCRIPT}"; then
    echo "[go2:policy_goals] policy 已在运行，跳过重复启动: ${POLICY_SCRIPT}"
  else
    run_terminal "Go2 Policy" "POLICY_SCRIPT=${POLICY_SCRIPT} bash ${ROBOT_DIR}/start_policy.sh"
  fi
  wait_policy_ready || true
fi

if [[ "${START_GO2_ZMQ}" == "1" ]]; then
  if already_running "${GO2_CMD_SCRIPT}"; then
    echo "[go2:policy_goals] Go2 ZMQ 已在运行，跳过重复启动: ${GO2_CMD_SCRIPT}"
  else
    run_terminal "Go2 ZMQ" "GO2_CMD_SCRIPT=${GO2_CMD_SCRIPT} bash ${ROBOT_DIR}/start_go2_zmq_sport_client.sh"
    sleep 2
  fi
fi

run_terminal "Go2 Policy Goals" \
  "GOAL_LIST=${GOAL_LIST} AUTO_START=${AUTO_START} GOAL_TIMEOUT=${GOAL_TIMEOUT} POLICY_STATUS_TOPIC=${POLICY_STATUS_TOPIC} STOP_ON_FAILURE=${STOP_ON_FAILURE} bash ${ROBOT_DIR}/start_goal_sequencer.sh"

echo "[go2:policy_goals] 已启动 policy 导航任务: ${GOAL_LIST}"
echo "[go2:policy_goals] START_POLICY=${START_POLICY}, START_GO2_ZMQ=${START_GO2_ZMQ}, AUTO_START=${AUTO_START}"
