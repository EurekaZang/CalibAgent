#!/usr/bin/env bash
# 启动 ROS2 slam_toolbox 在线建图。

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
SLAM_PARAMS="${SLAM_PARAMS:-${ROBOT_DIR}/slam_toolbox_params.yaml}"
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
mkdir -p "${ROS_LOG_DIR}"

if [[ ! -f "${SLAM_PARAMS}" ]]; then
  echo "[go2:slam] SLAM_PARAMS 不存在: ${SLAM_PARAMS}" >&2
  exit 1
fi

echo "[go2:slam] slam_toolbox online_async, params=${SLAM_PARAMS}"
exec ros2 launch slam_toolbox online_async_launch.py \
  params_file:="${SLAM_PARAMS}" \
  use_sim_time:=false
