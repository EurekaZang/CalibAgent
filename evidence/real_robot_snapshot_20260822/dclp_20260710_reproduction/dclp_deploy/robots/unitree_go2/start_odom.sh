#!/usr/bin/env bash
# 从 /sportmodestate 发布 /odom 和 odom->base_link TF。

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
UNITREE_ROS2_SETUP="${UNITREE_ROS2_SETUP:-/home/unitree/unitree_ros2/setup.sh}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${HOME}/cyclonedds_ws/cyclonedds.xml}"
SPORT_TOPIC="${SPORT_TOPIC:-/sportmodestate}"
ODOM_TOPIC="${ODOM_TOPIC:-/odom}"
ODOM_FRAME="${ODOM_FRAME:-odom}"
BASE_FRAME="${BASE_FRAME:-base_link}"

apply_cyclonedds_config() {
  if [[ -f "${CYCLONEDDS_CONFIG}" ]]; then
    export CYCLONEDDS_URI="${CYCLONEDDS_CONFIG}"
  fi
}

apply_cyclonedds_config

source_setup() {
  local setup_file="$1"
  if [[ -f "${setup_file}" ]]; then
    set +u
    source "${setup_file}"
    set -u
  fi
}

source_setup "${ROS_DISTRO_SETUP}"
source_setup "${ROS2_SETUP}"
source_setup "${UNITREE_ROS2_SETUP}"
apply_cyclonedds_config
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros2_go2_logs}"
mkdir -p "${ROS_LOG_DIR}"

echo "[go2:odom] ${SPORT_TOPIC} -> ${ODOM_TOPIC}, TF ${ODOM_FRAME}->${BASE_FRAME}"
exec python3 "${ROBOT_DIR}/go2_sport_odom_node.py" \
  --ros-args \
  -p "sport_topic:=${SPORT_TOPIC}" \
  -p "odom_topic:=${ODOM_TOPIC}" \
  -p "odom_frame:=${ODOM_FRAME}" \
  -p "base_frame:=${BASE_FRAME}"
