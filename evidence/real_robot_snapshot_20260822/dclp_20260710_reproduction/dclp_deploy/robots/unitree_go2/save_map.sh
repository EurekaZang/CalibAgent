#!/usr/bin/env bash
# 保存当前 /map 为 pgm/yaml。适用于 SLAM_MODE=slam。

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${ROBOT_DIR}/../.." && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
MAP_DIR="${MAP_DIR:-${DEPLOY_ROOT}/maps}"
MAP_NAME="${MAP_NAME:-go2_$(date +%Y%m%d_%H%M%S)}"
MAP_PREFIX="${MAP_PREFIX:-${MAP_DIR}/${MAP_NAME}}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${HOME}/cyclonedds_ws/cyclonedds.xml}"

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
source_setup "${ROS2_SETUP}"
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros2_go2_logs}"
mkdir -p "${ROS_LOG_DIR}" "${MAP_DIR}"

echo "[go2:save_map] saving ${MAP_PREFIX}.{pgm,yaml}"
exec ros2 run nav2_map_server map_saver_cli -f "${MAP_PREFIX}"
