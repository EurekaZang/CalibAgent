#!/usr/bin/env bash
# 当前终端运行 ROS2 goal sequencer。

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
GOAL_LIST="${GOAL_LIST:-}"
AUTO_START="${AUTO_START:-1}"
GOAL_TIMEOUT="${GOAL_TIMEOUT:-120}"
GOAL_TOPIC="${GOAL_TOPIC:-/move_base_simple/goal}"
STATUS_TOPIC="${STATUS_TOPIC:-/goal_sequencer/status}"
POLICY_STATUS_TOPIC="${POLICY_STATUS_TOPIC:-/nav_status}"
STOP_ON_FAILURE="${STOP_ON_FAILURE:-1}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${HOME}/cyclonedds_ws/cyclonedds.xml}"

if [[ -z "${GOAL_LIST}" || ! -f "${GOAL_LIST}" ]]; then
  echo "[go2:goal_seq] GOAL_LIST 未设置或不存在: ${GOAL_LIST}" >&2
  exit 1
fi
if [[ -f "${CYCLONEDDS_CONFIG}" ]]; then
  export CYCLONEDDS_URI="${CYCLONEDDS_CONFIG}"
fi

source_setup() {
  local setup_file="$1"
  if [[ -f "${setup_file}" ]]; then
    set +u
    source "${setup_file}"
    set -u
  fi
}

source_setup "${ROS_DISTRO_SETUP}"
if [[ ! -f "${ROS2_SETUP}" ]]; then
  echo "[go2:goal_seq] ROS2 setup 不存在: ${ROS2_SETUP}" >&2
  exit 1
fi
source_setup "${ROS2_SETUP}"
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros2_go2_logs}"
mkdir -p "${ROS_LOG_DIR}"

AUTO_FLAG=()
if [[ "${AUTO_START}" == "1" ]]; then
  AUTO_FLAG+=(--auto-start)
fi
STOP_FLAG=()
if [[ "${STOP_ON_FAILURE}" == "1" ]]; then
  STOP_FLAG+=(--stop-on-failure)
fi

echo "[go2:goal_seq] ${GOAL_LIST}, mode=policy"
exec python3 "${ROBOT_DIR}/goal_sequencer_ros2.py" \
  --goal-list "${GOAL_LIST}" \
  --topic "${GOAL_TOPIC}" \
  --status-topic "${STATUS_TOPIC}" \
  --policy-status-topic "${POLICY_STATUS_TOPIC}" \
  --timeout "${GOAL_TIMEOUT}" \
  "${AUTO_FLAG[@]}" \
  "${STOP_FLAG[@]}"
