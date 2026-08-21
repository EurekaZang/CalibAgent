#!/usr/bin/env bash
# ============================================================================
# DCLP 一键导航启动脚本
# 足部里程计 + MID360 + DCLP 策略部署 + 续航步态
#
# 用法:
#   ./start_dclp_nav.sh <向右距离> <向前距离>
#   ./start_dclp_nav.sh 0.0 2.0     # 向前 2 米
#   ./start_dclp_nav.sh 0.5 1.5     # 向前 1.5 米, 向右 0.5 米
#
#   ./start_dclp_nav.sh --stop      # 停止全部组件
#   ./start_dclp_nav.sh --status    # 查看运行状态
#   ./start_dclp_nav.sh --log       # 实时查看日志
# ============================================================================

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${DCLP_COMPONENT_LOG_DIR:-${ROBOT_DIR}/../logs}"
PID_DIR="${DCLP_PID_DIR:-${ROBOT_DIR}/../.pids}"
mkdir -p "${LOG_DIR}" "${PID_DIR}"

# ---- 配置 (可通过环境变量覆盖) ----
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
UNITREE_ROS2_SETUP="${UNITREE_ROS2_SETUP:-/home/unitree/unitree_ros2/setup.sh}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${ROBOT_DIR}/cyclonedds_go2_eth0.xml}"
RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
GO2_CONDA_ENV="${GO2_CONDA_ENV:-go2}"
GO2_IFACE="${GO2_IFACE:-auto}"
GO2_GAIT="${GO2_GAIT:-economic}"
GO2_ZMQ_ENDPOINT="${GO2_ZMQ_ENDPOINT:-tcp://127.0.0.1:5596}"
GO2_MAX_ACTION_AGE_MS="${GO2_MAX_ACTION_AGE_MS:-80.0}"
GO2_MAX_POLICY_LAG_MS="${GO2_MAX_POLICY_LAG_MS:-20.0}"
GO2_MAX_ODOM_AGE_MS="${GO2_MAX_ODOM_AGE_MS:-50.0}"
DRY_RUN="${DRY_RUN:-0}"
ZERO_MOTION="${ZERO_MOTION:-0}"
DRY_RUN_DURATION="${DRY_RUN_DURATION:-30}"
GOAL_TIMEOUT_SEC="${GOAL_TIMEOUT_SEC:-120}"
RECORD_ROSBAG="${RECORD_ROSBAG:-1}"
ROSBAG_OUTPUT_DIR="${ROSBAG_OUTPUT_DIR:-${ROBOT_DIR}/../bags/bag_$(date +%Y%m%d_%H%M%S)}"
ROSBAG_TOPICS="${ROSBAG_TOPICS:-/scan /odom /sportmodestate /go2_policy/cmd_vel /nav_status /dclp_relative_goal}"

LIVOX_FRAME_ID="${LIVOX_FRAME_ID:-livox_frame}"
LIVOX_PUBLISH_FREQ="${LIVOX_PUBLISH_FREQ:-50.0}"
LIVOX_CONFIG_PATH="${LIVOX_CONFIG_PATH:-${ROBOT_DIR}/MID360_config_eth0_192_168_123_18.json}"
LIVOX_CMDLINE_BD_CODE="${LIVOX_CMDLINE_BD_CODE:-livox0000000001}"

TF_X="${TF_X:-0.1870}"; TF_Y="${TF_Y:-0}"; TF_Z="${TF_Z:-0.3603}"
TF_QX="${TF_QX:-0}"; TF_QY="${TF_QY:-0.113203}"; TF_QZ="${TF_QZ:-0}"; TF_QW="${TF_QW:-0.993572}"

CLOUD_TOPIC="${CLOUD_TOPIC:-/livox/lidar}"
SCAN_TOPIC="${SCAN_TOPIC:-/scan}"
# Training-aligned height/range filters: ignore floor/self returns that otherwise
# appear as false close obstacles and make the policy steer around empty space.
MIN_HEIGHT="${MIN_HEIGHT:-0.20}"
MAX_HEIGHT="${MAX_HEIGHT:-1.00}"
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
  *) echo "PC2SCAN_MOTION_COMPENSATION 必须是布尔值" >&2; exit 1 ;;
esac
case "${PC2SCAN_DROP_LOW_QUALITY_SCAN,,}" in
  1|true|yes|on) PC2SCAN_DROP_LOW_QUALITY_SCAN=true ;;
  0|false|no|off) PC2SCAN_DROP_LOW_QUALITY_SCAN=false ;;
  *) echo "PC2SCAN_DROP_LOW_QUALITY_SCAN 必须是布尔值" >&2; exit 1 ;;
esac

MODEL_PATH="${MODEL_PATH:-${ROBOT_DIR}/../../../models/dclp/V1_41lambda1_101.pth}"
POLICY_RATE_HZ="${POLICY_RATE_HZ:-25.0}"
POLICY_SCAN_STAMP_TIMEOUT="${POLICY_SCAN_STAMP_TIMEOUT:-0.08}"
POLICY_ODOM_STAMP_TIMEOUT="${POLICY_ODOM_STAMP_TIMEOUT:-0.05}"
POLICY_BACKEND="${POLICY_BACKEND:-pth}"
POLICY_DEVICE="${POLICY_DEVICE:-cpu}"
GOAL_REACH_DIST="${GOAL_REACH_DIST:-0.4}"

HEALTH_CHECK_SCRIPT="${ROBOT_DIR}/dclp_topic_health.py"
STATUS_WAITER_SCRIPT="${ROBOT_DIR}/wait_nav_status_ros2.py"
MIN_LIVOX_RATE_HZ="${MIN_LIVOX_RATE_HZ:-40.0}"
MIN_SCAN_RATE_HZ="${MIN_SCAN_RATE_HZ:-40.0}"
MIN_ODOM_RATE_HZ="${MIN_ODOM_RATE_HZ:-100.0}"
LIVOX_MAX_AGE_MS="${LIVOX_MAX_AGE_MS:-80.0}"
SCAN_MAX_AGE_MS="${SCAN_MAX_AGE_MS:-80.0}"
ODOM_MAX_AGE_MS="${ODOM_MAX_AGE_MS:-50.0}"
SCAN_WATCHDOG_PERIOD_SEC="${SCAN_WATCHDOG_PERIOD_SEC:-5}"
SCAN_WATCHDOG_DURATION_SEC="${SCAN_WATCHDOG_DURATION_SEC:-1.5}"

RELATIVE_GOAL_TOPIC="/dclp_relative_goal"
STATUS_TOPIC="/nav_status"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[dclp_nav]${NC} $*"; }
warn()  { echo -e "${YELLOW}[dclp_nav]${NC} $*"; }
err()   { echo -e "${RED}[dclp_nav]${NC} $*" >&2; }
title() { echo ""; echo -e "${CYAN}══════════════════════════════════════════${NC}"; echo -e "${CYAN}  $*${NC}"; echo -e "${CYAN}══════════════════════════════════════════${NC}"; }

apply_cyclonedds() { [[ -f "${CYCLONEDDS_CONFIG}" ]] && export CYCLONEDDS_URI="${CYCLONEDDS_CONFIG}"; }
source_setup() { local f="$1"; [[ -f "${f}" ]] && { set +u; source "${f}"; set -u; }; }

pid_file()  { echo "${PID_DIR}/$1.pid"; }
log_file()  { echo "${LOG_DIR}/$1.log"; }

save_pid()   { echo "$!" > "$(pid_file "$1")"; }
read_pid()   { local f; f="$(pid_file "$1")"; [[ -f "${f}" ]] && cat "${f}" || echo ""; }
del_pid()    { rm -f "$(pid_file "$1")"; }
is_running() { local p; p="$(read_pid "$1")"; [[ -n "${p}" ]] && kill -0 "${p}" 2>/dev/null; }

STOP_INT_TIMEOUT="${STOP_INT_TIMEOUT:-2}"
STOP_TERM_TIMEOUT="${STOP_TERM_TIMEOUT:-1}"
STOP_KILL_TIMEOUT="${STOP_KILL_TIMEOUT:-1}"
PORT_WAIT_TIMEOUT="${PORT_WAIT_TIMEOUT:-3}"

# 按安全顺序清理残留：先让 ZMQ 运动客户端优雅停机，再停 policy 和传感器链路。
RESIDUAL_LABELS=(
  "Scan Watchdog"
  "ZMQ SportClient"
  "Navigation status waiter"
  "DCLP Policy"
  "Foot Odom"
  "pc2scan"
  "Static TF"
  "MID360"
  "Relative goal publisher"
)
RESIDUAL_PATTERNS=(
  "launch_watchdog"
  "go2_zmq_sport_client.py"
  "wait_nav_status_ros2.py"
  "dclp_go2_policy_ros2.py"
  "go2_sport_odom_node.py"
  "go2_livox_pc2scan_ros2.py"
  "static_transform_publisher.*livox"
  "livox_ros_driver2_node"
  "ros2.*topic.*pub.*dclp_relative"
)

is_protected_pid() {
  local pid="$1"
  [[ "${pid}" == "$$" || "${pid}" == "${BASHPID}" || "${pid}" == "${PPID}" ]]
}

collect_matching_pids() {
  local pattern pid
  for pattern in "$@"; do
    [[ -n "${pattern}" ]] || continue
    while read -r pid; do
      [[ -n "${pid}" ]] || continue
      is_protected_pid "${pid}" && continue
      echo "${pid}"
    done < <(pgrep -f "${pattern}" 2>/dev/null || true)
  done | sort -n -u
}

filter_live_pids() {
  local pid
  for pid in "$@"; do
    [[ -n "${pid}" ]] || continue
    [[ "${pid}" =~ ^[0-9]+$ ]] || continue
    kill -0 "${pid}" 2>/dev/null && echo "${pid}"
  done | sort -n -u
}

wait_pids_gone() {
  local timeout="$1"
  shift || true
  local start=${SECONDS}
  local live=()
  while true; do
    mapfile -t live < <(filter_live_pids "$@")
    [[ "${#live[@]}" -eq 0 ]] && return 0
    (( SECONDS - start >= timeout )) && return 1
    sleep 0.2
  done
}

stop_pids_staged() {
  local label="$1"
  shift || true
  local pids=() signal_targets=() live=()
  mapfile -t pids < <(filter_live_pids "$@")
  [[ "${#pids[@]}" -eq 0 ]] && return 0
  for pid in "${pids[@]}"; do
    # Components are launched with setsid. Signal the whole process group so
    # shells spawned by ros2 launch/run do not leave child processes behind.
    signal_targets+=("-${pid}")
  done

  warn "${label}: 停止旧进程 (pid: ${pids[*]})，先发送 SIGINT..."
  kill -INT "${signal_targets[@]}" 2>/dev/null || kill -INT "${pids[@]}" 2>/dev/null || true
  wait_pids_gone "${STOP_INT_TIMEOUT}" "${pids[@]}" || true

  mapfile -t live < <(filter_live_pids "${pids[@]}")
  if [[ "${#live[@]}" -gt 0 ]]; then
    signal_targets=()
    for pid in "${live[@]}"; do signal_targets+=("-${pid}"); done
    warn "${label}: 仍未退出 (pid: ${live[*]})，发送 SIGTERM..."
    kill -TERM "${signal_targets[@]}" 2>/dev/null || kill -TERM "${live[@]}" 2>/dev/null || true
    wait_pids_gone "${STOP_TERM_TIMEOUT}" "${live[@]}" || true
  fi

  mapfile -t live < <(filter_live_pids "${pids[@]}")
  if [[ "${#live[@]}" -gt 0 ]]; then
    signal_targets=()
    for pid in "${live[@]}"; do signal_targets+=("-${pid}"); done
    warn "${label}: 仍未退出 (pid: ${live[*]})，最后发送 SIGKILL..."
    kill -KILL "${signal_targets[@]}" 2>/dev/null || kill -KILL "${live[@]}" 2>/dev/null || true
    wait_pids_gone "${STOP_KILL_TIMEOUT}" "${live[@]}" || true
  fi

  mapfile -t live < <(filter_live_pids "${pids[@]}")
  if [[ "${#live[@]}" -gt 0 ]]; then
    err "${label}: 以下进程无法清理: ${live[*]}"
    return 1
  fi
  info "${label}: 旧进程已清理"
}

assert_no_matching_pids() {
  local label="$1"
  shift || true
  local pids=()
  mapfile -t pids < <(collect_matching_pids "$@")
  if [[ "${#pids[@]}" -gt 0 ]]; then
    err "${label}: 仍有残留进程 (pid: ${pids[*]})"
    return 1
  fi
}

port_5596_in_use() {
  ss -ltnp 2>/dev/null | grep -Eq '(^|[[:space:]])[^[:space:]]*:5596[[:space:]]'
}

show_port_5596_owner() {
  ss -ltnp 2>/dev/null | grep -E '(^|[[:space:]])[^[:space:]]*:5596[[:space:]]' || true
}

wait_port_5596_free() {
  local timeout="${1:-${PORT_WAIT_TIMEOUT}}"
  local start=${SECONDS}
  while true; do
    if ! port_5596_in_use; then
      return 0
    fi
    if (( SECONDS - start >= timeout )); then
      err "ZMQ 端口 5596 仍被占用，拒绝启动新的 policy："
      show_port_5596_owner >&2
      return 1
    fi
    sleep 0.2
  done
}

# ---- 导出全部配置变量 (供子进程 bash -c 使用) ----
export_all_vars() {
  export ROBOT_DIR LOG_DIR PID_DIR
  export RED GREEN YELLOW CYAN NC
  export ROS2_WS ROS2_SETUP ROS_DISTRO_SETUP UNITREE_ROS2_SETUP CYCLONEDDS_CONFIG RMW_IMPLEMENTATION
  export GO2_CONDA_ENV GO2_IFACE GO2_GAIT GO2_ZMQ_ENDPOINT
  export GO2_MAX_ACTION_AGE_MS GO2_MAX_POLICY_LAG_MS GO2_MAX_ODOM_AGE_MS
  export DRY_RUN ZERO_MOTION DRY_RUN_DURATION
  export GOAL_TIMEOUT_SEC RECORD_ROSBAG ROSBAG_OUTPUT_DIR ROSBAG_TOPICS
  export LIVOX_FRAME_ID LIVOX_PUBLISH_FREQ LIVOX_CONFIG_PATH LIVOX_CMDLINE_BD_CODE
  export TF_X TF_Y TF_Z TF_QX TF_QY TF_QZ TF_QW
  export CLOUD_TOPIC SCAN_TOPIC MIN_HEIGHT MAX_HEIGHT RANGE_MIN RANGE_MAX
  export PC2SCAN_ACCUMULATION_FRAMES PC2SCAN_ACCUMULATION_MAX_AGE
  export PC2SCAN_MOTION_COMPENSATION PC2SCAN_ODOM_MAX_STAMP_DELTA PC2SCAN_ODOM_HISTORY_SEC
  export PC2SCAN_MIN_RAW_FINITE_POINTS PC2SCAN_MIN_VALID_BEAMS PC2SCAN_DROP_LOW_QUALITY_SCAN
  export MODEL_PATH POLICY_RATE_HZ POLICY_SCAN_STAMP_TIMEOUT POLICY_ODOM_STAMP_TIMEOUT
  export POLICY_BACKEND POLICY_DEVICE GOAL_REACH_DIST
  export HEALTH_CHECK_SCRIPT MIN_LIVOX_RATE_HZ MIN_SCAN_RATE_HZ MIN_ODOM_RATE_HZ
  export LIVOX_MAX_AGE_MS SCAN_MAX_AGE_MS ODOM_MAX_AGE_MS
  export SCAN_WATCHDOG_PERIOD_SEC SCAN_WATCHDOG_DURATION_SEC
  export STOP_INT_TIMEOUT STOP_TERM_TIMEOUT STOP_KILL_TIMEOUT PORT_WAIT_TIMEOUT
  export COMPENSATE RELATIVE_GOAL_TOPIC
}

# ---- 初始化 ROS2 环境 ----
init_env() {
  apply_cyclonedds
  source_setup "${ROS_DISTRO_SETUP}"
  source_setup "${ROS2_SETUP}"
  export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros2_go2_logs}"
  mkdir -p "${ROS_LOG_DIR}"
}

# ---- 启动/停止各组件 ----
start_component() {
  local name="$1"; local cmd="$2"; local match="$3"
  local old_pids=() pidfile_pid

  pidfile_pid="$(read_pid "${name}")"
  if [[ -n "${pidfile_pid}" ]] && kill -0 "${pidfile_pid}" 2>/dev/null; then
    old_pids+=("${pidfile_pid}")
  fi
  if [[ -n "${match}" ]]; then
    while read -r pid; do
      [[ -n "${pid}" ]] && old_pids+=("${pid}")
    done < <(collect_matching_pids "${match}")
  fi

  if [[ "${#old_pids[@]}" -gt 0 ]]; then
    mapfile -t old_pids < <(filter_live_pids "${old_pids[@]}")
    if [[ "${#old_pids[@]}" -gt 0 ]]; then
      stop_pids_staged "${name}" "${old_pids[@]}"
    fi
  fi
  if [[ -n "${match}" ]]; then
    assert_no_matching_pids "${name}" "${match}"
  fi
  del_pid "${name}"

  if [[ "${name}" == "policy" ]]; then
    wait_port_5596_free "${PORT_WAIT_TIMEOUT}"
  fi

  info "启动 ${name}..."
  # Use a new session/process group so Ctrl-C or terminal exit of this wrapper
  # does not SIGINT long-running sensor/control components mid-navigation.
  setsid bash -c "${cmd}" > "$(log_file "${name}")" 2>&1 &
  save_pid "${name}"
  sleep 0.2
  if ! is_running "${name}"; then
    err "${name} 启动后立即退出，请查看日志: $(log_file "${name}")"
    return 1
  fi
  info "  ${name} started (pid=$(read_pid "${name}"), log=$(log_file "${name}"))"
}

restart_component() {
  local name="$1" cmd="$2" match="$3"
  warn "重启 ${name}..."
  stop_component "${name}" || true
  start_component "${name}" "${cmd}" "${match}"
}

ensure_topic_health_or_restart() {
  local label="$1" topic="$2" type="$3" min_rate="$4" max_age_ms="$5" duration="$6"
  local component="$7" cmd="$8" match="$9" log_name="${10}"
  if check_topic_health "${label}" "${topic}" "${type}" "${min_rate}" "${max_age_ms}" "${duration}"; then
    return 0
  fi
  warn "${label} 不健康，尝试重启 ${component} 后复查"
  restart_component "${component}" "${cmd}" "${match}"
  sleep 2
  if check_topic_health "${label}" "${topic}" "${type}" "${min_rate}" "${max_age_ms}" "${duration}"; then
    return 0
  fi
  err "${label} 重启后仍不健康，日志: ${LOG_DIR}/${log_name}.log"
  tail -12 "${LOG_DIR}/${log_name}.log" 2>/dev/null | while read -r l; do echo "  ${l}"; done
  return 1
}

stop_component() {
  local name="$1"
  local rc=0
  local pid; pid="$(read_pid "${name}")"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    stop_pids_staged "${name}" "${pid}" || rc=1
  fi
  del_pid "${name}"
  return "${rc}"
}

# ---- 各组件启动命令 ----
launch_mid360() {
  init_env
  exec ros2 run livox_ros_driver2 livox_ros_driver2_node --ros-args \
    -r "__node:=livox_lidar_publisher" \
    -p "xfer_format:=0" -p "multi_topic:=0" -p "data_src:=0" \
    -p "publish_freq:=${LIVOX_PUBLISH_FREQ}" -p "output_data_type:=0" \
    -p "frame_id:=${LIVOX_FRAME_ID}" -p "user_config_path:=${LIVOX_CONFIG_PATH}" \
    -p "cmdline_input_bd_code:=${LIVOX_CMDLINE_BD_CODE}"
}

launch_tf() {
  init_env
  exec ros2 run tf2_ros static_transform_publisher \
    "${TF_X}" "${TF_Y}" "${TF_Z}" "${TF_QX}" "${TF_QY}" "${TF_QZ}" "${TF_QW}" \
    base_link "${LIVOX_FRAME_ID}"
}

launch_pc2scan() {
  init_env
  exec python3 "${ROBOT_DIR}/go2_livox_pc2scan_ros2.py" --ros-args \
    -p "cloud_topic:=${CLOUD_TOPIC}" -p "scan_topic:=${SCAN_TOPIC}" \
    -p "odom_topic:=/odom" \
    -p "target_frame:=base_link" -p "queue_size:=1" -p "scan_time:=0.02" \
    -p "min_height:=${MIN_HEIGHT}" -p "max_height:=${MAX_HEIGHT}" \
    -p "range_min:=${RANGE_MIN}" -p "range_max:=${RANGE_MAX}" \
    -p "accumulation_frames:=${PC2SCAN_ACCUMULATION_FRAMES}" \
    -p "accumulation_max_age:=${PC2SCAN_ACCUMULATION_MAX_AGE}" \
    -p "motion_compensation:=${PC2SCAN_MOTION_COMPENSATION}" \
    -p "odom_max_stamp_delta:=${PC2SCAN_ODOM_MAX_STAMP_DELTA}" \
    -p "odom_history_sec:=${PC2SCAN_ODOM_HISTORY_SEC}" \
    -p "min_raw_finite_points:=${PC2SCAN_MIN_RAW_FINITE_POINTS}" \
    -p "min_valid_beams:=${PC2SCAN_MIN_VALID_BEAMS}" \
    -p "drop_low_quality_scan:=${PC2SCAN_DROP_LOW_QUALITY_SCAN}" \
    -p "tf_x:=${TF_X}" -p "tf_y:=${TF_Y}" -p "tf_z:=${TF_Z}" \
    -p "tf_qx:=${TF_QX}" -p "tf_qy:=${TF_QY}" -p "tf_qz:=${TF_QZ}" -p "tf_qw:=${TF_QW}"
}

launch_odom() {
  init_env
  source_setup "${UNITREE_ROS2_SETUP}"
  apply_cyclonedds
  exec python3 "${ROBOT_DIR}/go2_sport_odom_node.py" --ros-args \
    -p "sport_topic:=/sportmodestate" -p "odom_topic:=/odom" \
    -p "odom_frame:=odom" -p "base_frame:=base_link"
}

launch_policy() {
  init_env
  export POLICY_MODEL_PATH="${MODEL_PATH}"
  export POLICY_BACKEND="${POLICY_BACKEND}"
  export POLICY_DEVICE="${POLICY_DEVICE}"
  export POLICY_RATE_HZ="${POLICY_RATE_HZ}"
  export POLICY_SCAN_STAMP_TIMEOUT="${POLICY_SCAN_STAMP_TIMEOUT}"
  export POLICY_SCAN_TOPIC="${SCAN_TOPIC}"
  export POLICY_GLOBAL_FRAME="odom"
  export POLICY_ZMQ_BIND="tcp://*:5596"
  export POLICY_ZMQ_INCLUDE_META="true"
  export POLICY_ENABLED_ON_START="true"
  export POLICY_STOP_WHEN_REACHED="true"
  export POLICY_GOAL_TOLERANCE="${GOAL_REACH_DIST}"
  export POLICY_CONTROL_PERIOD_SEC="0.02"
  # Policy target speed range. Caps stay higher to leave room for compensation
  # without clipping compensated commands into constant boundary values.
  export POLICY_MAX_LINEAR="${POLICY_MAX_LINEAR:-0.90}"
  export POLICY_MAX_ANGULAR="${POLICY_MAX_ANGULAR:-0.83776}"
  export POLICY_CMD_VEL_V_CAP="${POLICY_CMD_VEL_V_CAP:-1.50}"
  export POLICY_CMD_VEL_W_CAP="${POLICY_CMD_VEL_W_CAP:-1.5708}"
  # Scale policy action magnitude [0, 1] into [min, max] speed ranges.
  export POLICY_CMD_VEL_V_MIN="${POLICY_CMD_VEL_V_MIN:-0.29997}"
  export POLICY_CMD_VEL_W_MIN="${POLICY_CMD_VEL_W_MIN:-0.27928}"
  export POLICY_MAX_LINEAR_ACC="${POLICY_MAX_LINEAR_ACC:-3.0}"
  export POLICY_MAX_ANGULAR_ACC="${POLICY_MAX_ANGULAR_ACC:-3.0}"
  export POLICY_SCAN_TIMEOUT="${POLICY_SCAN_TIMEOUT:-0.10}"
  export POLICY_ODOM_TIMEOUT="${POLICY_ODOM_TIMEOUT:-0.10}"
  export POLICY_ODOM_STAMP_TIMEOUT="${POLICY_ODOM_STAMP_TIMEOUT}"
  export POLICY_TF_TIMEOUT="${POLICY_TF_TIMEOUT:-0.01}"
  export POLICY_SCAN_MIN_VALUE="${POLICY_SCAN_MIN_VALUE:-0.2}"
  # Disable the front-goal straightening override so angular velocity stays policy-driven.
  export POLICY_STRAIGHTEN_FRONT_GOAL_ANGLE="${POLICY_STRAIGHTEN_FRONT_GOAL_ANGLE:-0.0}"
  export POLICY_STRAIGHTEN_FRONT_CLEAR_ANGLE="${POLICY_STRAIGHTEN_FRONT_CLEAR_ANGLE:-0.35}"
  export POLICY_STRAIGHTEN_FRONT_CLEAR_RANGE="${POLICY_STRAIGHTEN_FRONT_CLEAR_RANGE:-1.2}"
  export POLICY_STRAIGHTEN_FRONT_GOAL_W_LIMIT="${POLICY_STRAIGHTEN_FRONT_GOAL_W_LIMIT:-0.0}"
  export POLICY_TIMING_WARN_MS="${POLICY_TIMING_WARN_MS:-25.0}"
  export POLICY_SCAN_INVALID_FILL="${POLICY_SCAN_INVALID_FILL:-2.0}"
  export DCLP_LENGTH1="${DCLP_LENGTH1:-0.6048}"
  export DCLP_LENGTH2="${DCLP_LENGTH2:-0.6048}"
  export DCLP_WIDTH="${DCLP_WIDTH:-0.53568}"
  export POLICY_TRAJECTORY_LOG_ENABLED="${POLICY_TRAJECTORY_LOG_ENABLED:-true}"
  export POLICY_TRAJECTORY_LOG_DIR="${POLICY_TRAJECTORY_LOG_DIR:-${ROBOT_DIR}/../trajectory_logs}"
  export POLICY_TRAJECTORY_LOG_BASENAME="${POLICY_TRAJECTORY_LOG_BASENAME:-}"
  export POLICY_RELATIVE_GOAL_TOPIC="${RELATIVE_GOAL_TOPIC}"
  export POLICY_COMPENSATE="${COMPENSATE:-0}"
  if [[ -z "${POLICY_COMPENSATION_MODE:-}" ]]; then
    if [[ "${POLICY_COMPENSATE}" == "1" ]]; then
      export POLICY_COMPENSATION_MODE="guarded"
    else
      export POLICY_COMPENSATION_MODE="off"
    fi
  fi
  export PYTHONNOUSERSITE="1"
  REPO_ROOT="$(cd "${ROBOT_DIR}/../../.." && pwd)"
  export PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  cd "${REPO_ROOT}"
  PYTHON_BIN="${PYTHON_BIN:-${HOME}/miniconda3/envs/go2/bin/python}"
  [[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3)"
  exec "${PYTHON_BIN}" "${ROBOT_DIR}/dclp_go2_policy_ros2.py"
}

launch_zmq() {
  init_env
  source_setup "${UNITREE_ROS2_SETUP}"
  apply_cyclonedds
  set +u
  if command -v conda >/dev/null 2>&1; then
    eval "$(conda shell.bash hook)"; conda activate "${GO2_CONDA_ENV}"
  elif [[ -f "${HOME}/miniconda3/etc/profile.d/conda.sh" ]]; then
    source "${HOME}/miniconda3/etc/profile.d/conda.sh"; conda activate "${GO2_CONDA_ENV}"
  fi
  set -u
  local dry_args=()
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    dry_args+=(--dry-run --gait none --keep-obstacle-avoid)
  elif [[ "${ZERO_MOTION:-0}" == "1" ]]; then
    dry_args+=(--zero-motion --gait "${GO2_GAIT}" --allow-gait-failure --disable-joystick --force-api-remote-command)
  else
    dry_args+=(--gait "${GO2_GAIT}" --allow-gait-failure --disable-joystick --force-api-remote-command)
  fi
  exec python3 "${ROBOT_DIR}/go2_zmq_sport_client.py" \
    "${GO2_IFACE}" "${dry_args[@]}" \
    --endpoint "${GO2_ZMQ_ENDPOINT}" \
    --max-linear "${GO2_MAX_LINEAR:-${POLICY_CMD_VEL_V_CAP:-1.50}}" \
    --max-angular "${GO2_MAX_ANGULAR:-${POLICY_CMD_VEL_W_CAP:-1.5708}}" \
    --max-action-age-ms "${GO2_MAX_ACTION_AGE_MS}" \
    --max-policy-lag-ms "${GO2_MAX_POLICY_LAG_MS}" \
    --max-odom-age-ms "${GO2_MAX_ODOM_AGE_MS}" \
    --allow-reverse --sport-timeout "${GO2_SPORT_TIMEOUT:-5.0}"
}

launch_rosbag() {
  init_env
  local topics=()
  read -r -a topics <<<"${ROSBAG_TOPICS}"
  mkdir -p "$(dirname "${ROSBAG_OUTPUT_DIR}")"
  exec ros2 bag record -o "${ROSBAG_OUTPUT_DIR}" "${topics[@]}"
}

launch_watchdog() {
  init_env
  local mid360_cmd pc2scan_cmd
  mid360_cmd="$(declare -f init_env launch_mid360 apply_cyclonedds source_setup); launch_mid360"
  pc2scan_cmd="$(declare -f init_env launch_pc2scan apply_cyclonedds source_setup); launch_pc2scan"
  while true; do
    if ! check_topic_health "MID360 ${CLOUD_TOPIC}" "${CLOUD_TOPIC}" "sensor_msgs/msg/PointCloud2" \
      "${MIN_LIVOX_RATE_HZ}" "${LIVOX_MAX_AGE_MS}" "${SCAN_WATCHDOG_DURATION_SEC}"; then
      warn "watchdog: MID360 点云断流，先重启 mid360，再重启 pc2scan"
      restart_component "mid360" "${mid360_cmd}" "livox_ros_driver2_node" || true
      sleep 2
      restart_component "pc2scan" "${pc2scan_cmd}" "go2_livox_pc2scan_ros2" || true
      sleep 2
    elif ! check_topic_health "LaserScan ${SCAN_TOPIC}" "${SCAN_TOPIC}" "sensor_msgs/msg/LaserScan" \
      "${MIN_SCAN_RATE_HZ}" "${SCAN_MAX_AGE_MS}" "${SCAN_WATCHDOG_DURATION_SEC}" \
      "${PC2SCAN_MIN_VALID_BEAMS}"; then
      warn "watchdog: ${SCAN_TOPIC} 断流，重启 pc2scan"
      restart_component "pc2scan" "${pc2scan_cmd}" "go2_livox_pc2scan_ros2" || true
      sleep 2
    fi
    sleep "${SCAN_WATCHDOG_PERIOD_SEC}"
  done
}

# ---- 停止 ----
do_stop() {
  title "停止 DCLP 导航链路"
  local failed=0
  local wrapper_pids=() pids=()

  # 先停旧的 start_dclp_nav 包装脚本，避免旧脚本继续拉起子进程。
  mapfile -t wrapper_pids < <(collect_matching_pids "bash.*start_dclp_nav")
  if [[ "${#wrapper_pids[@]}" -gt 0 ]]; then
    stop_pids_staged "旧 start_dclp_nav 脚本" "${wrapper_pids[@]}" || failed=1
  fi

  for name in watchdog zmq status_waiter policy rosbag odom pc2scan tf mid360; do
    stop_component "${name}" || failed=1
  done

  # 兜底清理未被 pidfile 跟踪的残留进程，仍然使用分阶段停止。
  for i in "${!RESIDUAL_PATTERNS[@]}"; do
    mapfile -t pids < <(collect_matching_pids "${RESIDUAL_PATTERNS[$i]}")
    if [[ "${#pids[@]}" -gt 0 ]]; then
      stop_pids_staged "${RESIDUAL_LABELS[$i]}" "${pids[@]}" || failed=1
    fi
    assert_no_matching_pids "${RESIDUAL_LABELS[$i]}" "${RESIDUAL_PATTERNS[$i]}" || failed=1
  done

  wait_port_5596_free "${PORT_WAIT_TIMEOUT}" || failed=1

  if [[ "${failed}" -ne 0 ]]; then
    err "停止未完全成功，请检查残留进程后再启动"
    return 1
  fi
  info "停止完成"
}

# ---- 状态 ----
do_status() {
  title "DCLP 导航链路状态"
  local all_ok=true
  local labels=( "MID360" "Static TF" "pc2scan" "Foot Odom" "DCLP Policy" "ZMQ SportClient" "Scan Watchdog" "rosbag2" )
  local names=(  "mid360"  "tf"         "pc2scan" "odom"      "policy"       "zmq"             "watchdog"      "rosbag" )
  for i in "${!names[@]}"; do
    local pid; pid="$(read_pid "${names[$i]}")"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      echo -e "  ${GREEN}[OK]${NC}  ${labels[$i]} (pid=${pid})"
    else
      echo -e "  ${RED}[--]${NC} ${labels[$i]}"
      all_ok=false
    fi
  done
  echo ""
  echo "日志目录: ${LOG_DIR}"
}

# ---- 查看日志 ----
do_log() {
  local log="${LOG_DIR}/$1.log"
  if [[ ! -f "${log}" ]]; then
    err "日志文件不存在: ${log}"
    return 1
  fi
  tail -f "${log}"
}

# ---- 等待 topic ----
wait_for_topic() {
  local topic="$1"; local timeout="${2:-60}"; local start; start=$(date +%s)
  while true; do
    if ros2 topic list 2>/dev/null | grep -qF "${topic}"; then
      return 0
    fi
    if (( $(date +%s) - start >= timeout )); then
      return 1
    fi
    sleep 0.5
  done
}

check_topic_health() {
  local label="$1" topic="$2" type="$3" min_rate="$4" max_age_ms="$5" duration="${6:-2.0}"
  local min_valid_beams="${7:-0}"
  if [[ ! -f "${HEALTH_CHECK_SCRIPT}" ]]; then
    err "健康检查脚本不存在: ${HEALTH_CHECK_SCRIPT}"
    return 1
  fi
  local output rc
  set +e
  output=$(python3 "${HEALTH_CHECK_SCRIPT}" \
    --topic "${topic}" \
    --type "${type}" \
    --duration "${duration}" \
    --min-rate "${min_rate}" \
    --min-count 2 \
    --max-age-ms "${max_age_ms}" \
    --min-valid-beams "${min_valid_beams}" \
    --reliability best_effort 2>&1)
  rc=$?
  set -e
  if [[ "${rc}" -ne 0 ]]; then
    err "${label} 不健康: ${output}"
    return 1
  fi
  info "  ${label} ${output}"
}

# ---- 发送目标并等待完成 ----
send_goal_and_wait() {
  local goal_x="$1"; local goal_y="$2"

  info "等待组件就绪 (最长 60s)..."

  wait_for_topic "${CLOUD_TOPIC}" 60 || {
    err "${CLOUD_TOPIC} 未出现 —— 请检查 MID360 是否连接，日志: ${LOG_DIR}/mid360.log"
    err "最后 8 行日志:"
    tail -8 "${LOG_DIR}/mid360.log" 2>/dev/null | while read -r l; do echo "  ${l}"; done
    return 1
  }
  check_topic_health "MID360 ${CLOUD_TOPIC}" "${CLOUD_TOPIC}" "sensor_msgs/msg/PointCloud2" \
    "${MIN_LIVOX_RATE_HZ}" "${LIVOX_MAX_AGE_MS}" 3.0 || {
    err "MID360 点云没有持续新帧，拒绝继续导航"
    tail -8 "${LOG_DIR}/mid360.log" 2>/dev/null | while read -r l; do echo "  ${l}"; done
    return 1
  }

  wait_for_topic "${SCAN_TOPIC}" 60 || {
    err "${SCAN_TOPIC} 未出现 —— 请检查 pc2scan，日志: ${LOG_DIR}/pc2scan.log"
    err "最后 8 行日志:"
    tail -8 "${LOG_DIR}/pc2scan.log" 2>/dev/null | while read -r l; do echo "  ${l}"; done
    return 1
  }
  check_topic_health "LaserScan ${SCAN_TOPIC}" "${SCAN_TOPIC}" "sensor_msgs/msg/LaserScan" \
    "${MIN_SCAN_RATE_HZ}" "${SCAN_MAX_AGE_MS}" 3.0 "${PC2SCAN_MIN_VALID_BEAMS}" || {
    err "${SCAN_TOPIC} 没有持续健康发布，拒绝继续导航"
    tail -8 "${LOG_DIR}/pc2scan.log" 2>/dev/null | while read -r l; do echo "  ${l}"; done
    return 1
  }

  wait_for_topic "/odom" 30 || {
    err "/odom 未就绪 —— 请确认机器狗已上电，日志: ${LOG_DIR}/odom.log"
    tail -8 "${LOG_DIR}/odom.log" 2>/dev/null | while read -r l; do echo "  ${l}"; done
    return 1
  }
  check_topic_health "足部里程计 /odom" "/odom" "nav_msgs/msg/Odometry" \
    "${MIN_ODOM_RATE_HZ}" "${ODOM_MAX_AGE_MS}" 2.0 || {
    err "/odom 没有持续健康发布，拒绝继续导航"
    tail -8 "${LOG_DIR}/odom.log" 2>/dev/null | while read -r l; do echo "  ${l}"; done
    return 1
  }

  wait_for_topic "${STATUS_TOPIC}" 20 || {
    err "${STATUS_TOPIC} 未就绪 —— 策略进程可能启动失败，日志: ${LOG_DIR}/policy.log"
    tail -5 "${LOG_DIR}/policy.log" 2>/dev/null | while read l; do echo "  ${l}"; done
    return 1
  }
  info "  ${STATUS_TOPIC} OK"
  info "全部组件就绪。"
  echo ""

  title "导航目标: 向右 ${goal_x} m, 向前 ${goal_y} m"

  local max_wait="${GOAL_TIMEOUT_SEC}"
  local status="" status_rc=0 status_waiter_pid=""
  local status_ready_file="${PID_DIR}/nav_status_waiter.ready"
  local status_result_file="${LOG_DIR}/nav_status_result.txt"

  if [[ "${DRY_RUN:-0}" != "1" && "${ZERO_MOTION:-0}" != "1" ]]; then
    [[ -f "${STATUS_WAITER_SCRIPT}" ]] || {
      err "导航状态监视脚本不存在: ${STATUS_WAITER_SCRIPT}"
      return 1
    }
    rm -f "${status_ready_file}"
    python3 "${STATUS_WAITER_SCRIPT}" \
      --topic "${STATUS_TOPIC}" \
      --timeout "${max_wait}" \
      --ready-timeout 10 \
      --ready-file "${status_ready_file}" \
      >"${status_result_file}" &
    status_waiter_pid=$!
    echo "${status_waiter_pid}" >"$(pid_file status_waiter)"

    local ready_deadline=$((SECONDS + 10))
    while [[ ! -s "${status_ready_file}" ]]; do
      if ! kill -0 "${status_waiter_pid}" 2>/dev/null; then
        if wait "${status_waiter_pid}"; then status_rc=0; else status_rc=$?; fi
        del_pid status_waiter
        err "导航状态监视器在 ready 前退出 (exit=${status_rc})"
        return 1
      fi
      if (( SECONDS >= ready_deadline )); then
        stop_component status_waiter || true
        rm -f "${status_ready_file}"
        err "导航状态监视器 ready 超时"
        return 1
      fi
      sleep 0.1
    done
    if ! kill -0 "${status_waiter_pid}" 2>/dev/null; then
      if wait "${status_waiter_pid}"; then status_rc=0; else status_rc=$?; fi
      del_pid status_waiter
      rm -f "${status_ready_file}"
      err "导航状态监视器在 ready 后意外退出 (exit=${status_rc})"
      return 1
    fi
    info "  ${STATUS_TOPIC} terminal monitor ready"
  fi

  if ! ros2 topic pub --once "${RELATIVE_GOAL_TOPIC}" geometry_msgs/msg/Point \
    "{x: ${goal_x}, y: ${goal_y}, z: 0.0}" 2>/dev/null; then
    if [[ -n "${status_waiter_pid}" ]]; then
      stop_component status_waiter || true
    fi
    rm -f "${status_ready_file}"
    err "目标发送失败"
    return 1
  fi
  info "目标已发送，等待到达..."

  if [[ "${DRY_RUN:-0}" == "1" || "${ZERO_MOTION:-0}" == "1" ]]; then
    info "安全观测模式：底盘不会执行非零 Move，记录 ${DRY_RUN_DURATION}s 后结束。"
    local observe_start; observe_start=$(date +%s)
    while (( $(date +%s) - observe_start < DRY_RUN_DURATION )); do
      sleep 0.5
    done
    local stale_count fresh_count
    stale_count=$(grep -c "STALE_DROP" "${LOG_DIR}/zmq.log" 2>/dev/null || true)
    fresh_count=$(grep -c " action_age=" "${LOG_DIR}/zmq.log" 2>/dev/null || true)
    if (( stale_count > 0 )); then
      err "freshness gate 失败：ZMQ 丢弃了 ${stale_count} 条过期动作"
      tail -10 "${LOG_DIR}/zmq.log" | while read -r l; do echo "  ${l}"; done
      return 1
    fi
    if (( fresh_count == 0 )); then
      err "freshness gate 失败：未收到带 action_age 的策略动作"
      return 1
    fi
    info "freshness gate 通过：${fresh_count} 条动作均满足 action<${GO2_MAX_ACTION_AGE_MS}ms、policy_lag<${GO2_MAX_POLICY_LAG_MS}ms、odom<${GO2_MAX_ODOM_AGE_MS}ms。"
    info "安全观测完成；该结果不计作 REACHED。"
    return 0
  fi

  if wait "${status_waiter_pid}"; then status_rc=0; else status_rc=$?; fi
  del_pid status_waiter
  rm -f "${status_ready_file}"
  status="$(tail -n 1 "${status_result_file}" 2>/dev/null || true)"

  case "${status_rc}" in
    0)
      if [[ "${status}" != "REACHED" ]]; then
        err "导航状态监视返回了意外结果: ${status:-empty}"
        return 1
      fi
      echo ""
      info "============================================="
      info "  目标已到达! (向前 ${goal_y}m, 向右 ${goal_x}m)"
      info "============================================="
      return 0
      ;;
    10)
      echo ""
      warn "安全停车 (距障碍物过近)"
      return 1
      ;;
    124)
      err "导航超时 (${max_wait}s, last_status=${status:-unknown})"
      return 1
      ;;
    130)
      warn "导航状态监视被中止"
      return 130
      ;;
    *)
      err "导航状态监视失败 (exit=${status_rc}, last_status=${status:-unknown})"
      return 1
      ;;
  esac
}

# ---- 启动全部组件 ----
launch_all() {
  title "DCLP 一键导航 — 续航步态 (${GO2_GAIT})"
  echo ""
  info "传感器:  MID360 -> /livox/lidar -> pc2scan -> /scan"
  info "里程计:  /sportmodestate -> 足部里程计 -> /odom + odom->base_link TF"
  info "策略:    /scan + /odom -> DCLP -> ZMQ -> Go2 SportClient"
  info "调试:    dry-run=$(if [[ "${DRY_RUN:-0}" == "1" ]]; then echo ON-不调用SportClient.Move; else echo OFF; fi), zero-motion=$(if [[ "${ZERO_MOTION:-0}" == "1" ]]; then echo ON-只发送零速度; else echo OFF; fi)"
  info "补偿:    速度前馈补偿=$(if [[ "${COMPENSATE:-0}" == "1" ]]; then echo ON; else echo OFF; fi)"
  info "模型:    ${MODEL_PATH}"
  info "日志:    ${LOG_DIR}"
  echo ""

  # 导出全部变量使子进程 bash -c 能访问
  export_all_vars

  start_component "mid360"  "$(declare -f init_env launch_mid360 apply_cyclonedds source_setup); launch_mid360" \
    "livox_ros_driver2_node"
  sleep 1
  init_env
  wait_for_topic "${CLOUD_TOPIC}" 20 || {
    err "MID360 已启动但 ${CLOUD_TOPIC} 未出现，日志: ${LOG_DIR}/mid360.log"
    tail -8 "${LOG_DIR}/mid360.log" 2>/dev/null | while read -r l; do echo "  ${l}"; done
    return 1
  }
  check_topic_health "MID360 ${CLOUD_TOPIC}" "${CLOUD_TOPIC}" "sensor_msgs/msg/PointCloud2" \
    "${MIN_LIVOX_RATE_HZ}" "${LIVOX_MAX_AGE_MS}" 3.0 || return 1

  start_component "tf"      "$(declare -f init_env launch_tf apply_cyclonedds source_setup); launch_tf" \
    "static_transform_publisher.*livox"
  sleep 0.5
  start_component "pc2scan" "$(declare -f init_env launch_pc2scan apply_cyclonedds source_setup); launch_pc2scan" \
    "go2_livox_pc2scan_ros2"
  sleep 0.5
  wait_for_topic "${SCAN_TOPIC}" 20 || {
    err "pc2scan 已启动但 ${SCAN_TOPIC} 未出现，日志: ${LOG_DIR}/pc2scan.log"
    tail -8 "${LOG_DIR}/pc2scan.log" 2>/dev/null | while read -r l; do echo "  ${l}"; done
    return 1
  }
  check_topic_health "LaserScan ${SCAN_TOPIC}" "${SCAN_TOPIC}" "sensor_msgs/msg/LaserScan" \
    "${MIN_SCAN_RATE_HZ}" "${SCAN_MAX_AGE_MS}" 3.0 "${PC2SCAN_MIN_VALID_BEAMS}" || return 1

  start_component "odom"    "$(declare -f init_env launch_odom apply_cyclonedds source_setup); launch_odom" \
    "go2_sport_odom_node"
  sleep 3
  wait_for_topic "/odom" 20 || {
    err "足部里程计已启动但 /odom 未出现，日志: ${LOG_DIR}/odom.log"
    tail -8 "${LOG_DIR}/odom.log" 2>/dev/null | while read -r l; do echo "  ${l}"; done
    return 1
  }
  check_topic_health "足部里程计 /odom" "/odom" "nav_msgs/msg/Odometry" \
    "${MIN_ODOM_RATE_HZ}" "${ODOM_MAX_AGE_MS}" 2.0 || return 1
  # 确保 ZMQ 端口不被旧进程占用；只验证端口状态，避免杀错进程。
  wait_port_5596_free "${PORT_WAIT_TIMEOUT}"
  start_component "policy"  "$(declare -f init_env launch_policy apply_cyclonedds source_setup); launch_policy" \
    "dclp_go2_policy_ros2"
  sleep 2
  start_component "zmq"     "$(declare -f init_env launch_zmq apply_cyclonedds source_setup); launch_zmq" \
    "go2_zmq_sport_client"
  start_component "watchdog" "$(declare -f init_env launch_mid360 launch_pc2scan launch_watchdog apply_cyclonedds source_setup check_topic_health restart_component start_component stop_component stop_pids_staged wait_pids_gone filter_live_pids collect_matching_pids is_protected_pid assert_no_matching_pids pid_file log_file save_pid read_pid del_pid is_running port_5596_in_use show_port_5596_owner wait_port_5596_free info warn err); launch_watchdog" \
    "launch_watchdog"

  if [[ "${RECORD_ROSBAG}" == "1" ]]; then
    start_component "rosbag" "$(declare -f init_env launch_rosbag apply_cyclonedds source_setup); launch_rosbag" ""
  elif [[ "${RECORD_ROSBAG}" != "0" ]]; then
    err "RECORD_ROSBAG 必须是 0 或 1，收到: ${RECORD_ROSBAG}"
    return 1
  fi

  info "核心组件已启动，rosbag=$(if [[ "${RECORD_ROSBAG}" == "1" ]]; then echo ON; else echo OFF; fi)"
}

# ---- 主入口 ----
case "${1:-}" in
  --stop)   do_stop; exit 0 ;;
  --status) do_status; exit 0 ;;
  --log)
    do_log "${2:-mid360}"
    exit 0 ;;
  --help|-h)
    echo "用法:"
    echo "  $0 [--bg] [--dry-run|--zero-motion] <向右距离> <向前距离>"
    echo "  $0 --stop              停止全部组件"
    echo "  $0 --status            查看运行状态"
    echo "  $0 --log [name]        查看组件日志 (mid360/tf/pc2scan/odom/policy/zmq)"
    echo ""
    echo "示例:"
    echo "  $0 0.0 2.0             # 向前 2 米"
    echo "  $0 --bg 0.5 1.5        # 后台, 向前1.5米, 向右0.5米"
    echo "  $0 --dry-run 0.0 5.0   # 全流程调试，但不调用 SportClient.Move"
    echo "  $0 --zero-motion 0.0 5.0 # 初始化 SportClient，但所有 Move 都发 0 速度"
    echo "  $0 --log policy         # 实时查看策略日志"
    echo ""
    echo "环境变量:"
    echo "  GO2_GAIT=economic       步态 (economic/classic/trot/...)"
    echo "  DRY_RUN=1               全流程调试但不移动机器狗、不初始化SDK"
    echo "  ZERO_MOTION=1           初始化SDK但只发送零速度"
    echo "  DRY_RUN_DURATION=30     --dry-run/--zero-motion 自动观测秒数"
    echo "  GOAL_TIMEOUT_SEC=120    真机任务超时"
    echo "  RECORD_ROSBAG=1         记录 scan/odom/sport/cmd/status/goal"
    echo "  POLICY_RATE_HZ=25.0     策略控制频率；在 50Hz scan 下减少等待且保留 CPU 裕量"
    echo "  POLICY_SCAN_STAMP_TIMEOUT=0.08  policy 拒绝超过 80ms 的 scan"
    echo "  POLICY_ODOM_STAMP_TIMEOUT=0.05  policy 拒绝超过 50ms 的 odom"
    echo "  GO2_MAX_ACTION_AGE_MS=80  SportClient 端拒绝 scan→action 超过 80ms 的非零动作"
    echo "  MODEL_PATH=...          策略模型路径"
    echo "  GOAL_REACH_DIST=0.4     目标到达判定距离"
    exit 0
    ;;
esac

# 解析参数
BG_MODE=0; GOAL_X=""; GOAL_Y=""; COMPENSATE="${COMPENSATE:-0}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bg) BG_MODE=1; shift ;;
    --dry-run) DRY_RUN=1; ZERO_MOTION=0; shift ;;
    --zero-motion) ZERO_MOTION=1; DRY_RUN=0; shift ;;
    --compensate)
      COMPENSATE="$2"; shift 2
      [[ "${COMPENSATE}" =~ ^[01]$ ]] || { err "--compensate 必须是 0 或 1"; exit 1; }
      ;;

    --*)  err "未知选项: $1"; exit 1 ;;
    *)
      if [[ -z "${GOAL_X}" ]]; then GOAL_X="$1"
      elif [[ -z "${GOAL_Y}" ]]; then GOAL_Y="$1"
      else err "多余参数: $1"; exit 1; fi
      shift ;;
  esac
done

# 验证目标参数
if [[ -z "${GOAL_X}" || -z "${GOAL_Y}" ]]; then
  err "缺少目标坐标。用法: $0 [--bg] <向右距离(米)> <向前距离(米)>"
  err "示例: $0 0.0 2.0"
  exit 1
fi
if ! [[ "${GOAL_X}" =~ ^-?[0-9]+\.?[0-9]*$ && "${GOAL_Y}" =~ ^-?[0-9]+\.?[0-9]*$ ]]; then
  err "目标坐标必须是数字，收到: ${GOAL_X} ${GOAL_Y}"
  exit 1
fi

handle_interrupt() {
  trap - INT TERM
  warn "收到中止信号：立即停止 ZMQ、policy 与传感器链路。"
  do_stop || true
  exit 130
}
trap handle_interrupt INT TERM

# ---- 执行 ----
# 启动前自动清理旧实例；若清理不干净，拒绝叠加启动新导航链路。
if ! do_stop; then
  err "旧 DCLP 导航链路未能完全清理，拒绝启动新任务"
  exit 1
fi
rm -f "${PID_DIR}"/*.pid 2>/dev/null || true

launch_all
init_env

set +e
send_goal_and_wait "${GOAL_X}" "${GOAL_Y}"
RET=$?
set -e

if [[ "${RECORD_ROSBAG}" == "1" ]]; then
  stop_component "rosbag" || true
fi

if [[ ${RET} -eq 0 && ( "${DRY_RUN:-0}" == "1" || "${ZERO_MOTION:-0}" == "1" ) ]]; then
  title "安全观测完成（不计作 REACHED）"
elif [[ ${RET} -eq 0 ]]; then
  title "导航完成 ✓"
else
  title "导航异常 (exit=${RET})"
  echo ""
  echo "查看日志诊断问题:"
  echo "  $0 --log mid360"
  echo "  $0 --log policy"
  echo "  $0 --log zmq"
fi

echo ""
echo "组件仍在后台运行。停止: $0 --stop"

[[ "${BG_MODE}" == "1" ]] && exit ${RET}
exit ${RET}
