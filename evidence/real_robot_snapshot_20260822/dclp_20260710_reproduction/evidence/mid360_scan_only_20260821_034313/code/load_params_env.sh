#!/usr/bin/env bash
# Load Unitree Go2 flat YAML defaults into environment variables.
#
# Existing environment variables win over PARAM_FILE values. The parser is
# intentionally small and supports flat "key: scalar" YAML entries, matching
# deploy/robots/*/default_params.yaml style.

_go2_params_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${PARAM_FILE:-}" && "${UNITREE_GO2_PARAM_FILE_AUTO:-0}" != "1" ]]; then
  _go2_param_file="${PARAM_FILE}"
else
  _go2_param_file="${_go2_params_dir}/default_params.yaml"
  export UNITREE_GO2_PARAM_FILE_AUTO=1
fi
PARAM_FILE="${_go2_param_file}"
export PARAM_FILE

if [[ -n "${UNITREE_GO2_PARAMS_ENV_LOADED:-}" && "${UNITREE_GO2_PARAMS_ENV_LOADED_FROM:-}" == "${PARAM_FILE}" ]]; then
  return 0
fi
export UNITREE_GO2_PARAMS_ENV_LOADED=1
export UNITREE_GO2_PARAMS_ENV_LOADED_FROM="${PARAM_FILE}"

if [[ ! -f "${PARAM_FILE}" ]]; then
  echo "[go2:params] PARAM_FILE 不存在: ${PARAM_FILE}" >&2
  return 1
fi

_go2_trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "${value}"
}

_go2_unquote() {
  local value="$1"
  if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "${value}"
}

_go2_normalize_scalar() {
  local value="$1"
  local lower="${value,,}"
  case "${lower}" in
    true|yes|on) value="1" ;;
    false|no|off) value="0" ;;
  esac
  if [[ "${value}" == "~/"* ]]; then
    value="${HOME}/${value#~/}"
  fi
  printf '%s' "${value}"
}

_go2_set_default() {
  local name="$1"
  local value="$2"
  if [[ -z "${!name+x}" || "${UNITREE_GO2_PARAM_SET_VARS:-:}" == *":${name}:"* ]]; then
    export "${name}=${value}"
    if [[ "${UNITREE_GO2_PARAM_SET_VARS:-:}" != *":${name}:"* ]]; then
      UNITREE_GO2_PARAM_SET_VARS="${UNITREE_GO2_PARAM_SET_VARS:-:}${name}:"
      export UNITREE_GO2_PARAM_SET_VARS
    fi
  fi
}

_go2_apply_param() {
  local key="$1"
  local value="$2"

  case "${key}" in
    ros2_ws) _go2_set_default ROS2_WS "${value}" ;;
    ros2_setup) _go2_set_default ROS2_SETUP "${value}" ;;
    ros_distro_setup) _go2_set_default ROS_DISTRO_SETUP "${value}" ;;
    unitree_ros2_setup) _go2_set_default UNITREE_ROS2_SETUP "${value}" ;;
    cyclonedds_config) _go2_set_default CYCLONEDDS_CONFIG "${value}" ;;
    cyclonedds_uri) _go2_set_default CYCLONEDDS_URI "${value}" ;;
    ros_log_dir) _go2_set_default ROS_LOG_DIR "${value}" ;;

    no_rviz) _go2_set_default NO_RVIZ "${value}" ;;
    mid360_rviz) _go2_set_default MID360_RVIZ "${value}" ;;
    clean_existing) _go2_set_default CLEAN_EXISTING "${value}" ;;
    autolaunch_policy) _go2_set_default AUTOLAUNCH_POLICY "${value}" ;;
    autolaunch_go2_zmq) _go2_set_default AUTOLAUNCH_GO2_ZMQ "${value}" ;;
    autolaunch_uwb_goal) _go2_set_default AUTOLAUNCH_UWB_GOAL "${value}" ;;
    livox_launch) _go2_set_default LIVOX_LAUNCH "${value}" ;;

    cloud_topic) _go2_set_default CLOUD_TOPIC "${value}" ;;
    model_path)
      _go2_set_default MODEL_PATH "${value}"
      _go2_set_default POLICY_MODEL_PATH "${value}"
      ;;
    gpu_mem_frac) _go2_set_default POLICY_GPU_MEM_FRAC "${value}" ;;
    policy_backend) _go2_set_default POLICY_BACKEND "${value}" ;;
    policy_device) _go2_set_default POLICY_DEVICE "${value}" ;;
    policy_deterministic) _go2_set_default POLICY_DETERMINISTIC "${value}" ;;
    control_period_sec) _go2_set_default POLICY_CONTROL_PERIOD_SEC "${value}" ;;
    dclp_length1) _go2_set_default DCLP_LENGTH1 "${value}" ;;
    dclp_length2) _go2_set_default DCLP_LENGTH2 "${value}" ;;
    dclp_width) _go2_set_default DCLP_WIDTH "${value}" ;;
    scan_invalid_fill) _go2_set_default POLICY_SCAN_INVALID_FILL "${value}" ;;
    cmd_vel_v_cap) _go2_set_default POLICY_CMD_VEL_V_CAP "${value}" ;;
    cmd_vel_w_cap) _go2_set_default POLICY_CMD_VEL_W_CAP "${value}" ;;
    cmd_vel_v_min|cmd_vel_v_floor|policy_cmd_vel_v_min|policy_cmd_vel_v_floor) _go2_set_default POLICY_CMD_VEL_V_MIN "${value}" ;;
    cmd_vel_w_min|cmd_vel_w_floor|policy_cmd_vel_w_min|policy_cmd_vel_w_floor) _go2_set_default POLICY_CMD_VEL_W_MIN "${value}" ;;
    scan_topic)
      _go2_set_default SCAN_TOPIC "${value}"
      _go2_set_default POLICY_SCAN_TOPIC "${value}"
      ;;
    sport_topic)
      _go2_set_default SPORT_TOPIC "${value}"
      _go2_set_default POLICY_SPORT_TOPIC "${value}"
      ;;
    odom_topic)
      _go2_set_default ODOM_TOPIC "${value}"
      _go2_set_default POLICY_ODOM_TOPIC "${value}"
      ;;
    cmd_vel_topic) _go2_set_default POLICY_CMD_VEL_TOPIC "${value}" ;;
    goal_topic)
      _go2_set_default GOAL_TOPIC "${value}"
      _go2_set_default POLICY_GOAL_TOPIC "${value}"
      ;;
    relative_goal_topic|policy_relative_goal_topic)
      _go2_set_default POLICY_RELATIVE_GOAL_TOPIC "${value}"
      ;;
    status_topic|policy_status_topic) _go2_set_default POLICY_STATUS_TOPIC "${value}" ;;
    goal_status_topic) _go2_set_default STATUS_TOPIC "${value}" ;;
    base_frame)
      _go2_set_default BASE_FRAME "${value}"
      _go2_set_default POLICY_BASE_FRAME "${value}"
      _go2_set_default TF_PARENT_FRAME "${value}"
      ;;
    target_frame) _go2_set_default TARGET_FRAME "${value}" ;;
    odom_frame) _go2_set_default ODOM_FRAME "${value}" ;;
    global_frame)
      _go2_set_default POLICY_GLOBAL_FRAME "${value}"
      _go2_set_default GOAL_FRAME "${value}"
      ;;
    livox_frame) _go2_set_default TF_CHILD_FRAME "${value}" ;;

    transform_tolerance) _go2_set_default TRANSFORM_TOLERANCE "${value}" ;;
    min_height) _go2_set_default MIN_HEIGHT "${value}" ;;
    max_height) _go2_set_default MAX_HEIGHT "${value}" ;;
    angle_min) _go2_set_default ANGLE_MIN "${value}" ;;
    angle_max) _go2_set_default ANGLE_MAX "${value}" ;;
    angle_increment) _go2_set_default ANGLE_INCREMENT "${value}" ;;
    queue_size) _go2_set_default QUEUE_SIZE "${value}" ;;
    scan_time) _go2_set_default SCAN_TIME "${value}" ;;
    range_min) _go2_set_default RANGE_MIN "${value}" ;;
    range_max) _go2_set_default RANGE_MAX "${value}" ;;
    use_inf) _go2_set_default USE_INF "${value}" ;;
    pc2scan_accumulation_frames) _go2_set_default PC2SCAN_ACCUMULATION_FRAMES "${value}" ;;
    pc2scan_accumulation_max_age) _go2_set_default PC2SCAN_ACCUMULATION_MAX_AGE "${value}" ;;
    pc2scan_motion_compensation) _go2_set_default PC2SCAN_MOTION_COMPENSATION "${value}" ;;
    pc2scan_odom_max_stamp_delta) _go2_set_default PC2SCAN_ODOM_MAX_STAMP_DELTA "${value}" ;;
    pc2scan_odom_history_sec) _go2_set_default PC2SCAN_ODOM_HISTORY_SEC "${value}" ;;
    pc2scan_min_raw_finite_points) _go2_set_default PC2SCAN_MIN_RAW_FINITE_POINTS "${value}" ;;
    pc2scan_min_valid_beams) _go2_set_default PC2SCAN_MIN_VALID_BEAMS "${value}" ;;
    pc2scan_drop_low_quality_scan) _go2_set_default PC2SCAN_DROP_LOW_QUALITY_SCAN "${value}" ;;

    tf_parent_frame) _go2_set_default TF_PARENT_FRAME "${value}" ;;
    tf_child_frame) _go2_set_default TF_CHILD_FRAME "${value}" ;;
    tf_x) _go2_set_default TF_X "${value}" ;;
    tf_y) _go2_set_default TF_Y "${value}" ;;
    tf_z) _go2_set_default TF_Z "${value}" ;;
    tf_qx) _go2_set_default TF_QX "${value}" ;;
    tf_qy) _go2_set_default TF_QY "${value}" ;;
    tf_qz) _go2_set_default TF_QZ "${value}" ;;
    tf_qw) _go2_set_default TF_QW "${value}" ;;

    slam_params) _go2_set_default SLAM_PARAMS "${value}" ;;
    nav2_params) _go2_set_default NAV2_PARAMS "${value}" ;;
    rviz_config) _go2_set_default RVIZ_CONFIG "${value}" ;;
    map_dir) _go2_set_default MAP_DIR "${value}" ;;
    map_name) _go2_set_default MAP_NAME "${value}" ;;
    map_prefix) _go2_set_default MAP_PREFIX "${value}" ;;

    policy_workdir) _go2_set_default POLICY_WORKDIR "${value}" ;;
    policy_script) _go2_set_default POLICY_SCRIPT "${value}" ;;
    policy_python_bin|python_bin) _go2_set_default PYTHON_BIN "${value}" ;;
    control_rate_hz|policy_rate_hz) _go2_set_default POLICY_RATE_HZ "${value}" ;;
    policy_timing_warn_ms) _go2_set_default POLICY_TIMING_WARN_MS "${value}" ;;
    scan_timeout) _go2_set_default POLICY_SCAN_TIMEOUT "${value}" ;;
    odom_timeout) _go2_set_default POLICY_ODOM_TIMEOUT "${value}" ;;
    enabled_on_start) _go2_set_default POLICY_ENABLED_ON_START "${value}" ;;
    min_obstacle_distance) _go2_set_default POLICY_MIN_OBSTACLE_DISTANCE "${value}" ;;
    speed_scale) _go2_set_default POLICY_SPEED_SCALE "${value}" ;;
    max_linear_speed)
      _go2_set_default POLICY_MAX_LINEAR "${value}"
      _go2_set_default GO2_MAX_LINEAR "${value}"
      ;;
    max_angular_speed)
      _go2_set_default POLICY_MAX_ANGULAR "${value}"
      _go2_set_default GO2_MAX_ANGULAR "${value}"
      ;;
    policy_max_linear) _go2_set_default POLICY_MAX_LINEAR "${value}" ;;
    policy_max_angular) _go2_set_default POLICY_MAX_ANGULAR "${value}" ;;
    max_linear_acc|max_linear_accel|policy_max_linear_acc) _go2_set_default POLICY_MAX_LINEAR_ACC "${value}" ;;
    max_angular_acc|max_angular_accel|policy_max_angular_acc) _go2_set_default POLICY_MAX_ANGULAR_ACC "${value}" ;;
    goal_reach_distance|policy_goal_tolerance) _go2_set_default POLICY_GOAL_TOLERANCE "${value}" ;;
    policy_stop_when_reached) _go2_set_default POLICY_STOP_WHEN_REACHED "${value}" ;;
    tf_timeout|policy_tf_timeout) _go2_set_default POLICY_TF_TIMEOUT "${value}" ;;
    scan_min_value) _go2_set_default POLICY_SCAN_MIN_VALUE "${value}" ;;
    straighten_front_goal_angle) _go2_set_default POLICY_STRAIGHTEN_FRONT_GOAL_ANGLE "${value}" ;;
    straighten_front_clear_angle) _go2_set_default POLICY_STRAIGHTEN_FRONT_CLEAR_ANGLE "${value}" ;;
    straighten_front_clear_range) _go2_set_default POLICY_STRAIGHTEN_FRONT_CLEAR_RANGE "${value}" ;;
    straighten_front_goal_w_limit) _go2_set_default POLICY_STRAIGHTEN_FRONT_GOAL_W_LIMIT "${value}" ;;
    policy_zmq_bind) _go2_set_default POLICY_ZMQ_BIND "${value}" ;;

    trajectory_log_enabled) _go2_set_default POLICY_TRAJECTORY_LOG_ENABLED "${value}" ;;
    trajectory_log_dir) _go2_set_default POLICY_TRAJECTORY_LOG_DIR "${value}" ;;
    trajectory_log_basename) _go2_set_default POLICY_TRAJECTORY_LOG_BASENAME "${value}" ;;
    trajectory_log_rate_hz) _go2_set_default POLICY_TRAJECTORY_LOG_RATE_HZ "${value}" ;;

    go2_conda_env) _go2_set_default GO2_CONDA_ENV "${value}" ;;
    go2_iface) _go2_set_default GO2_IFACE "${value}" ;;
    go2_cmd_script) _go2_set_default GO2_CMD_SCRIPT "${value}" ;;
    go2_zmq_endpoint) _go2_set_default GO2_ZMQ_ENDPOINT "${value}" ;;
    go2_recv_timeout_ms) _go2_set_default GO2_RECV_TIMEOUT_MS "${value}" ;;
    go2_max_linear) _go2_set_default GO2_MAX_LINEAR "${value}" ;;
    go2_max_angular) _go2_set_default GO2_MAX_ANGULAR "${value}" ;;
    go2_allow_reverse) _go2_set_default GO2_ALLOW_REVERSE "${value}" ;;
    go2_disable_obstacle_avoid) _go2_set_default GO2_DISABLE_OBSTACLE_AVOID "${value}" ;;
    go2_gait) _go2_set_default GO2_GAIT "${value}" ;;
    go2_allow_gait_failure) _go2_set_default GO2_ALLOW_GAIT_FAILURE "${value}" ;;
    go2_sport_timeout) _go2_set_default GO2_SPORT_TIMEOUT "${value}" ;;

    auto_start) _go2_set_default AUTO_START "${value}" ;;
    goal_timeout)
      _go2_set_default GOAL_TIMEOUT "${value}"
      _go2_set_default POLICY_GOAL_TIMEOUT "${value}"
      ;;
    stop_on_failure) _go2_set_default STOP_ON_FAILURE "${value}" ;;
    start_policy) _go2_set_default START_POLICY "${value}" ;;
    start_go2_zmq) _go2_set_default START_GO2_ZMQ "${value}" ;;
    uwb_ros_topic) _go2_set_default UWB_ROS_TOPIC "${value}" ;;
    uwb_odom_topic) _go2_set_default UWB_ODOM_TOPIC "${value}" ;;
    uwb_goal_topic) _go2_set_default UWB_GOAL_TOPIC "${value}" ;;
    uwb_goal_frame) _go2_set_default UWB_GOAL_FRAME "${value}" ;;
    uwb_goal_rate_hz) _go2_set_default UWB_GOAL_RATE_HZ "${value}" ;;
    uwb_stale_timeout) _go2_set_default UWB_STALE_TIMEOUT "${value}" ;;
    uwb_min_distance) _go2_set_default UWB_MIN_DISTANCE "${value}" ;;
    uwb_max_distance) _go2_set_default UWB_MAX_DISTANCE "${value}" ;;
    uwb_yaw_units) _go2_set_default UWB_YAW_UNITS "${value}" ;;
    uwb_yaw_sign) _go2_set_default UWB_YAW_SIGN "${value}" ;;
    uwb_reliability) _go2_set_default UWB_RELIABILITY "${value}" ;;
    uwb_goal_position_epsilon) _go2_set_default UWB_GOAL_POSITION_EPSILON "${value}" ;;
    uwb_goal_yaw_epsilon) _go2_set_default UWB_GOAL_YAW_EPSILON "${value}" ;;
    uwb_goal_republish_period) _go2_set_default UWB_GOAL_REPUBLISH_PERIOD "${value}" ;;
  esac
}

while IFS= read -r _go2_line || [[ -n "${_go2_line}" ]]; do
  _go2_line="${_go2_line%$'\r'}"
  _go2_line="$(_go2_trim "${_go2_line}")"
  [[ -z "${_go2_line}" || "${_go2_line}" == \#* ]] && continue
  [[ "${_go2_line}" == *:* ]] || continue

  _go2_key="$(_go2_trim "${_go2_line%%:*}")"
  _go2_value="$(_go2_trim "${_go2_line#*:}")"
  [[ -z "${_go2_key}" ]] && continue

  if [[ "${_go2_value}" == \"* || "${_go2_value}" == \'* ]]; then
    _go2_value="$(_go2_unquote "${_go2_value}")"
  else
    _go2_value="${_go2_value%%#*}"
    _go2_value="$(_go2_trim "${_go2_value}")"
  fi
  _go2_value="$(_go2_normalize_scalar "${_go2_value}")"
  _go2_apply_param "${_go2_key}" "${_go2_value}"
done < "${PARAM_FILE}"

unset -f _go2_trim _go2_unquote _go2_normalize_scalar _go2_set_default _go2_apply_param
unset _go2_params_dir _go2_line _go2_key _go2_value
