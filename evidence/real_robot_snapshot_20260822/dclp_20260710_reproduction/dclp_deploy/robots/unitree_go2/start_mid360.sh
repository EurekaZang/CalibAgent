#!/usr/bin/env bash
# 启动 Livox MID360 ROS2 driver。默认带 RViz，可用 NO_RVIZ=1 关闭。

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
NO_RVIZ="${NO_RVIZ:-0}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${HOME}/cyclonedds_ws/cyclonedds.xml}"
LIVOX_CONFIG_PATH="${LIVOX_CONFIG_PATH:-${ROS2_WS}/install/livox_ros_driver2/share/livox_ros_driver2/config/MID360_config.json}"
LIVOX_FRAME_ID="${LIVOX_FRAME_ID:-livox_frame}"
LIVOX_PUBLISH_FREQ="${LIVOX_PUBLISH_FREQ:-20.0}"
LIVOX_LVX_FILE_PATH="${LIVOX_LVX_FILE_PATH:-/home/livox/livox_test.lvx}"
LIVOX_CMDLINE_BD_CODE="${LIVOX_CMDLINE_BD_CODE:-livox0000000001}"

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
  echo "[go2:mid360] ROS2 setup 不存在: ${ROS2_SETUP}" >&2
  exit 1
fi
source_setup "${ROS2_SETUP}"
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros2_go2_logs}"
mkdir -p "${ROS_LOG_DIR}"

if [[ "${NO_RVIZ}" == "1" && -z "${LIVOX_LAUNCH:-}" ]]; then
  if [[ ! -f "${LIVOX_CONFIG_PATH}" ]]; then
    echo "[go2:mid360] Livox config 不存在: ${LIVOX_CONFIG_PATH}" >&2
    exit 1
  fi

  echo "[go2:mid360] ros2 run livox_ros_driver2 livox_ros_driver2_node (PointCloud2, no RViz)"
  exec ros2 run livox_ros_driver2 livox_ros_driver2_node \
    --ros-args \
    -r "__node:=livox_lidar_publisher" \
    -p "xfer_format:=0" \
    -p "multi_topic:=0" \
    -p "data_src:=0" \
    -p "publish_freq:=${LIVOX_PUBLISH_FREQ}" \
    -p "output_data_type:=0" \
    -p "frame_id:=${LIVOX_FRAME_ID}" \
    -p "lvx_file_path:=${LIVOX_LVX_FILE_PATH}" \
    -p "user_config_path:=${LIVOX_CONFIG_PATH}" \
    -p "cmdline_input_bd_code:=${LIVOX_CMDLINE_BD_CODE}"
fi

LIVOX_LAUNCH="${LIVOX_LAUNCH:-rviz_MID360_launch.py}"
echo "[go2:mid360] ros2 launch livox_ros_driver2 ${LIVOX_LAUNCH}"
exec ros2 launch livox_ros_driver2 "${LIVOX_LAUNCH}"
