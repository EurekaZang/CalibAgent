#!/usr/bin/env bash
# 将 Livox MID360 PointCloud2 转成 /scan。

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${HOME}/cyclonedds_ws/cyclonedds.xml}"

if [[ -f "${CYCLONEDDS_CONFIG}" ]]; then
  export CYCLONEDDS_URI="${CYCLONEDDS_CONFIG}"
fi

CLOUD_TOPIC="${CLOUD_TOPIC:-/livox/lidar}"
SCAN_TOPIC="${SCAN_TOPIC:-/scan}"
TARGET_FRAME="${TARGET_FRAME:-base_link}"
TRANSFORM_TOLERANCE="${TRANSFORM_TOLERANCE:-0.2}"
MIN_HEIGHT="${MIN_HEIGHT:-0.20}"
MAX_HEIGHT="${MAX_HEIGHT:-1.00}"
ANGLE_MIN="${ANGLE_MIN:--3.14159265359}"
ANGLE_MAX="${ANGLE_MAX:-3.14159265359}"
ANGLE_INCREMENT="${ANGLE_INCREMENT:-0.005817764}"
QUEUE_SIZE="${QUEUE_SIZE:-10}"
SCAN_TIME="${SCAN_TIME:-0.1}"
RANGE_MIN="${RANGE_MIN:-0.26}"
RANGE_MAX="${RANGE_MAX:-20.0}"
PC2SCAN_ACCUMULATION_FRAMES="${PC2SCAN_ACCUMULATION_FRAMES:-5}"
PC2SCAN_ACCUMULATION_MAX_AGE="${PC2SCAN_ACCUMULATION_MAX_AGE:-0.12}"
PC2SCAN_MOTION_COMPENSATION="${PC2SCAN_MOTION_COMPENSATION:-true}"
PC2SCAN_ODOM_MAX_STAMP_DELTA="${PC2SCAN_ODOM_MAX_STAMP_DELTA:-0.08}"
PC2SCAN_ODOM_HISTORY_SEC="${PC2SCAN_ODOM_HISTORY_SEC:-2.0}"
PC2SCAN_MIN_RAW_FINITE_POINTS="${PC2SCAN_MIN_RAW_FINITE_POINTS:-1000}"
PC2SCAN_MIN_VALID_BEAMS="${PC2SCAN_MIN_VALID_BEAMS:-64}"
PC2SCAN_DROP_LOW_QUALITY_SCAN="${PC2SCAN_DROP_LOW_QUALITY_SCAN:-true}"
case "${PC2SCAN_MOTION_COMPENSATION,,}" in
  1|true|yes|on) PC2SCAN_MOTION_COMPENSATION=true ;;
  0|false|no|off) PC2SCAN_MOTION_COMPENSATION=false ;;
  *) echo "[go2:pc2scan] PC2SCAN_MOTION_COMPENSATION 必须是布尔值" >&2; exit 1 ;;
esac
case "${PC2SCAN_DROP_LOW_QUALITY_SCAN,,}" in
  1|true|yes|on) PC2SCAN_DROP_LOW_QUALITY_SCAN=true ;;
  0|false|no|off) PC2SCAN_DROP_LOW_QUALITY_SCAN=false ;;
  *) echo "[go2:pc2scan] PC2SCAN_DROP_LOW_QUALITY_SCAN 必须是布尔值" >&2; exit 1 ;;
esac
USE_INF="${USE_INF:-true}"
PC2SCAN_IMPL="${PC2SCAN_IMPL:-custom}"
case "${USE_INF,,}" in
  1|true|yes|on) USE_INF_ROS=true ;;
  0|false|no|off) USE_INF_ROS=false ;;
  *)
    echo "[go2:pc2scan] USE_INF 必须是 true/false/1/0，当前: ${USE_INF}" >&2
    exit 1
    ;;
esac

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
  echo "[go2:pc2scan] ROS2 setup 不存在: ${ROS2_SETUP}" >&2
  exit 1
fi
source_setup "${ROS2_SETUP}"
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros2_go2_logs}"
mkdir -p "${ROS_LOG_DIR}"

echo "[go2:pc2scan] ${CLOUD_TOPIC} -> ${SCAN_TOPIC}, target_frame=${TARGET_FRAME}"
if [[ "${PC2SCAN_IMPL}" == "custom" ]]; then
  exec python3 "${ROBOT_DIR}/go2_livox_pc2scan_ros2.py" \
    --ros-args \
    -p "cloud_topic:=${CLOUD_TOPIC}" \
    -p "scan_topic:=${SCAN_TOPIC}" \
    -p "odom_topic:=${ODOM_TOPIC:-/odom}" \
    -p "target_frame:=${TARGET_FRAME}" \
    -p "min_height:=${MIN_HEIGHT}" \
    -p "max_height:=${MAX_HEIGHT}" \
    -p "angle_min:=${ANGLE_MIN}" \
    -p "angle_max:=${ANGLE_MAX}" \
    -p "angle_increment:=${ANGLE_INCREMENT}" \
    -p "queue_size:=${QUEUE_SIZE}" \
    -p "scan_time:=${SCAN_TIME}" \
    -p "range_min:=${RANGE_MIN}" \
    -p "range_max:=${RANGE_MAX}" \
    -p "accumulation_frames:=${PC2SCAN_ACCUMULATION_FRAMES}" \
    -p "accumulation_max_age:=${PC2SCAN_ACCUMULATION_MAX_AGE}" \
    -p "motion_compensation:=${PC2SCAN_MOTION_COMPENSATION}" \
    -p "odom_max_stamp_delta:=${PC2SCAN_ODOM_MAX_STAMP_DELTA}" \
    -p "odom_history_sec:=${PC2SCAN_ODOM_HISTORY_SEC}" \
    -p "min_raw_finite_points:=${PC2SCAN_MIN_RAW_FINITE_POINTS}" \
    -p "min_valid_beams:=${PC2SCAN_MIN_VALID_BEAMS}" \
    -p "drop_low_quality_scan:=${PC2SCAN_DROP_LOW_QUALITY_SCAN}" \
    -p "use_inf:=${USE_INF_ROS}" \
    -p "tf_x:=${TF_X}" \
    -p "tf_y:=${TF_Y}" \
    -p "tf_z:=${TF_Z}" \
    -p "tf_qx:=${TF_QX}" \
    -p "tf_qy:=${TF_QY}" \
    -p "tf_qz:=${TF_QZ}" \
    -p "tf_qw:=${TF_QW}"
fi

exec ros2 run pointcloud_to_laserscan pointcloud_to_laserscan_node \
  --ros-args \
  -r "cloud_in:=${CLOUD_TOPIC}" \
  -r "scan:=${SCAN_TOPIC}" \
  -p "target_frame:=${TARGET_FRAME}" \
  -p "transform_tolerance:=${TRANSFORM_TOLERANCE}" \
  -p "min_height:=${MIN_HEIGHT}" \
  -p "max_height:=${MAX_HEIGHT}" \
  -p "angle_min:=${ANGLE_MIN}" \
  -p "angle_max:=${ANGLE_MAX}" \
  -p "angle_increment:=${ANGLE_INCREMENT}" \
  -p "queue_size:=${QUEUE_SIZE}" \
  -p "scan_time:=${SCAN_TIME}" \
  -p "range_min:=${RANGE_MIN}" \
  -p "range_max:=${RANGE_MAX}" \
  -p "use_inf:=${USE_INF_ROS}"
