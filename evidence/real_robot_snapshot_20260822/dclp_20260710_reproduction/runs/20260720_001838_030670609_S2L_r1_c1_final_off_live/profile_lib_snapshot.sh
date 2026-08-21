#!/usr/bin/env bash

profile_common() {
  export PROFILE_DESCRIPTION=""
  export PROFILE_RISK="medium"
  export POLICY_RATE_HZ="20.0"
  export POLICY_CONTROL_PERIOD_SEC="0.02"
  export POLICY_MAX_LINEAR_ACC="3.0"
  export POLICY_MAX_ANGULAR_ACC="3.0"
  export POLICY_SCAN_TIMEOUT="0.3"
  export POLICY_ODOM_TIMEOUT="0.3"
  export POLICY_TF_TIMEOUT="0.01"
  export POLICY_SCAN_MIN_VALUE="0.2"
  export POLICY_SCAN_INVALID_FILL="2.0"
  export POLICY_STRAIGHTEN_FRONT_GOAL_ANGLE="0.0"
  export POLICY_STRAIGHTEN_FRONT_CLEAR_ANGLE="0.35"
  export POLICY_STRAIGHTEN_FRONT_CLEAR_RANGE="1.2"
  export POLICY_STRAIGHTEN_FRONT_GOAL_W_LIMIT="0.0"
  export POLICY_ACTION_MAPPING="range"
  export POLICY_ACCEL_LIMITER_MODE="last_cmd_dt"
  export COMPENSATE="0"
  export POLICY_COMPENSATION_MODE="off"
  export RECORD_ROSBAG="1"
  export GOAL_TIMEOUT_SEC="60"
  export MIN_HEIGHT="0.20"
  export MAX_HEIGHT="1.00"
  export RANGE_MIN="0.26"
  export RANGE_MAX="20.0"
}

geometry_old() {
  export DCLP_LENGTH1="0.42"
  export DCLP_LENGTH2="0.42"
  export DCLP_WIDTH="0.372"
}

geometry_final() {
  export DCLP_LENGTH1="0.504"
  export DCLP_LENGTH2="0.504"
  export DCLP_WIDTH="0.4464"
}

speed_v5() {
  export POLICY_MAX_LINEAR="1.5"
  export POLICY_MAX_ANGULAR="1.5708"
  export POLICY_CMD_VEL_V_MIN="0.5"
  export POLICY_CMD_VEL_W_MIN="0.5236"
  export POLICY_CMD_VEL_V_FLOOR="0.0"
  export POLICY_CMD_VEL_W_FLOOR="0.0"
  export POLICY_CMD_VEL_V_CAP="1.5"
  export POLICY_CMD_VEL_W_CAP="1.5708"
  export GO2_MAX_LINEAR="1.5"
  export GO2_MAX_ANGULAR="1.5708"
}

speed_v6() {
  export POLICY_MAX_LINEAR="1.05"
  export POLICY_MAX_ANGULAR="1.09956"
  export POLICY_CMD_VEL_V_MIN="0.35"
  export POLICY_CMD_VEL_W_MIN="0.36652"
  export POLICY_CMD_VEL_V_FLOOR="0.0"
  export POLICY_CMD_VEL_W_FLOOR="0.0"
  export POLICY_CMD_VEL_V_CAP="1.05"
  export POLICY_CMD_VEL_W_CAP="1.09956"
  export GO2_MAX_LINEAR="1.05"
  export GO2_MAX_ANGULAR="1.09956"
}

speed_v7_double() {
  export POLICY_MAX_LINEAR="2.10"
  export POLICY_MAX_ANGULAR="2.19912"
  export POLICY_CMD_VEL_V_MIN="0.70"
  export POLICY_CMD_VEL_W_MIN="0.73304"
  export POLICY_CMD_VEL_V_FLOOR="0.0"
  export POLICY_CMD_VEL_W_FLOOR="0.0"
  export POLICY_CMD_VEL_V_CAP="2.10"
  export POLICY_CMD_VEL_W_CAP="2.19912"
  export GO2_MAX_LINEAR="2.10"
  export GO2_MAX_ANGULAR="2.19912"
}

speed_v8() {
  export POLICY_MAX_LINEAR="1.00"
  export POLICY_MAX_ANGULAR="1.0472"
  export POLICY_CMD_VEL_V_MIN="0.3333"
  export POLICY_CMD_VEL_W_MIN="0.3491"
  export POLICY_CMD_VEL_V_FLOOR="0.0"
  export POLICY_CMD_VEL_W_FLOOR="0.0"
  export POLICY_CMD_VEL_V_CAP="1.50"
  export POLICY_CMD_VEL_W_CAP="1.5708"
  export GO2_MAX_LINEAR="1.50"
  export GO2_MAX_ANGULAR="1.5708"
}

speed_v9_angular() {
  speed_v8
  export POLICY_MAX_ANGULAR="0.83776"
  export POLICY_CMD_VEL_W_MIN="0.27928"
}

speed_v10_final() {
  speed_v9_angular
  export POLICY_MAX_LINEAR="0.90"
  export POLICY_CMD_VEL_V_MIN="0.29997"
}

speed_linear_only() {
  speed_v8
  export POLICY_MAX_LINEAR="0.90"
  export POLICY_CMD_VEL_V_MIN="0.29997"
}

compensation_off() {
  export COMPENSATE="0"
  export POLICY_COMPENSATION_MODE="off"
}

compensation_raw() {
  export COMPENSATE="1"
  export POLICY_COMPENSATION_MODE="raw"
}

compensation_guarded() {
  export COMPENSATE="1"
  export POLICY_COMPENSATION_MODE="guarded"
}
