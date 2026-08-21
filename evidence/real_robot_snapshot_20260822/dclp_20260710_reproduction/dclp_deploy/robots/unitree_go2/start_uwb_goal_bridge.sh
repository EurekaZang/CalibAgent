#!/usr/bin/env bash
# Start local Unitree /uwbstate -> /move_base_simple/goal bridge.

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"

ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
UNITREE_ROS2_MSG_SETUP="${UNITREE_ROS2_MSG_SETUP:-${HOME}/unitree_ros2/cyclonedds_ws/install/setup.bash}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${ROBOT_DIR}/cyclonedds_go2_eth0.xml}"
UWB_ROS_GOAL_BRIDGE_SCRIPT="${UWB_ROS_GOAL_BRIDGE_SCRIPT:-${ROBOT_DIR}/go2_uwb_ros_goal_bridge.py}"
UWB_ROS_TOPIC="${UWB_ROS_TOPIC:-/uwbstate}"
UWB_ODOM_TOPIC="${UWB_ODOM_TOPIC:-${ODOM_TOPIC:-/odom}}"
UWB_GOAL_TOPIC="${UWB_GOAL_TOPIC:-${GOAL_TOPIC:-/move_base_simple/goal}}"
UWB_GOAL_FRAME="${UWB_GOAL_FRAME:-odom}"
UWB_GOAL_RATE_HZ="${UWB_GOAL_RATE_HZ:-10.0}"
UWB_STALE_TIMEOUT="${UWB_STALE_TIMEOUT:-1.5}"
UWB_MIN_DISTANCE="${UWB_MIN_DISTANCE:-0.25}"
UWB_MAX_DISTANCE="${UWB_MAX_DISTANCE:-20.0}"
UWB_YAW_UNITS="${UWB_YAW_UNITS:-auto}"
UWB_YAW_SIGN="${UWB_YAW_SIGN:-1.0}"
UWB_RELIABILITY="${UWB_RELIABILITY:-reliable}"
UWB_GOAL_POSITION_EPSILON="${UWB_GOAL_POSITION_EPSILON:-0.05}"
UWB_GOAL_YAW_EPSILON="${UWB_GOAL_YAW_EPSILON:-0.05}"
UWB_GOAL_REPUBLISH_PERIOD="${UWB_GOAL_REPUBLISH_PERIOD:-0.2}"

source_setup() {
  local setup_file="$1"
  if [[ -f "${setup_file}" ]]; then
    set +u
    source "${setup_file}"
    set -u
  fi
}

apply_cyclonedds_config() {
  if [[ -f "${CYCLONEDDS_CONFIG}" ]]; then
    export CYCLONEDDS_URI="${CYCLONEDDS_CONFIG}"
  fi
  export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
}

source_setup "${ROS_DISTRO_SETUP}"
if [[ ! -f "${ROS2_SETUP}" ]]; then
  echo "[go2:uwb_goal] ROS2 setup 不存在: ${ROS2_SETUP}" >&2
  exit 1
fi
source_setup "${ROS2_SETUP}"
source_setup "${UNITREE_ROS2_MSG_SETUP}"
apply_cyclonedds_config

export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros2_go2_logs}"
mkdir -p "${ROS_LOG_DIR}"

if [[ ! -f "${UWB_ROS_GOAL_BRIDGE_SCRIPT}" ]]; then
  echo "[go2:uwb_goal] bridge 脚本不存在: ${UWB_ROS_GOAL_BRIDGE_SCRIPT}" >&2
  exit 1
fi

echo "[go2:uwb_goal] CYCLONEDDS_URI=${CYCLONEDDS_URI:-<unset>}"
echo "[go2:uwb_goal] ${UWB_ROS_TOPIC} -> ${UWB_GOAL_TOPIC}, frame=${UWB_GOAL_FRAME}, odom=${UWB_ODOM_TOPIC}"
echo "[go2:uwb_goal] rate=${UWB_GOAL_RATE_HZ}, reliability=${UWB_RELIABILITY}, yaw=orientation_est"

exec python3 "${UWB_ROS_GOAL_BRIDGE_SCRIPT}" \
  --uwb-topic "${UWB_ROS_TOPIC}" \
  --odom-topic "${UWB_ODOM_TOPIC}" \
  --goal-topic "${UWB_GOAL_TOPIC}" \
  --goal-frame "${UWB_GOAL_FRAME}" \
  --rate-hz "${UWB_GOAL_RATE_HZ}" \
  --stale-timeout "${UWB_STALE_TIMEOUT}" \
  --min-distance "${UWB_MIN_DISTANCE}" \
  --max-distance "${UWB_MAX_DISTANCE}" \
  --yaw-units "${UWB_YAW_UNITS}" \
  --yaw-sign "${UWB_YAW_SIGN}" \
  --uwb-reliability "${UWB_RELIABILITY}" \
  --position-epsilon "${UWB_GOAL_POSITION_EPSILON}" \
  --yaw-epsilon "${UWB_GOAL_YAW_EPSILON}" \
  --republish-period "${UWB_GOAL_REPUBLISH_PERIOD}"
