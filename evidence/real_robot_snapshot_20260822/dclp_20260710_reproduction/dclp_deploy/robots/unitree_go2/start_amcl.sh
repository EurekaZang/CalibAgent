#!/usr/bin/env bash
# 启动 Nav2 map_server + AMCL 定位。

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
NAV2_PARAMS="${NAV2_PARAMS:-${ROBOT_DIR}/nav2_params.yaml}"
AMCL_MAP="${AMCL_MAP:-}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${HOME}/cyclonedds_ws/cyclonedds.xml}"

if [[ -z "${AMCL_MAP}" || ! -f "${AMCL_MAP}" ]]; then
  echo "[go2:amcl] AMCL_MAP 未设置或不存在: ${AMCL_MAP}" >&2
  echo "  先 SLAM_MODE=slam 建图，再运行 deploy/robots/unitree_go2/save_map.sh" >&2
  exit 1
fi
if [[ ! -f "${NAV2_PARAMS}" ]]; then
  echo "[go2:amcl] NAV2_PARAMS 不存在: ${NAV2_PARAMS}" >&2
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
  echo "[go2:amcl] ROS2 setup 不存在: ${ROS2_SETUP}" >&2
  exit 1
fi
source_setup "${ROS2_SETUP}"
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros2_go2_logs}"
mkdir -p "${ROS_LOG_DIR}"

echo "[go2:amcl] map=${AMCL_MAP}, params=${NAV2_PARAMS}"
exec ros2 launch nav2_bringup localization_launch.py \
  map:="${AMCL_MAP}" \
  params_file:="${NAV2_PARAMS}" \
  use_sim_time:=false \
  autostart:=true
