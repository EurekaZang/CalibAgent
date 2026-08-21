#!/usr/bin/env bash

profile_common() {
  export PROFILE_DESCRIPTION=""
  export PROFILE_RISK="medium"
  export POLICY_RATE_HZ="20.0"
  export POLICY_CONTROL_PERIOD_SEC="0.02"
  export POLICY_OBS_MAX_LINEAR_ACC="3.0"
  export POLICY_OBS_MAX_ANGULAR_ACC="3.0"
  export POLICY_SCAN_TIMEOUT="0.3"
  export POLICY_ODOM_TIMEOUT="0.3"
  export POLICY_TF_TIMEOUT="0.01"
  export POLICY_SCAN_MIN_VALUE="0.2"
  export POLICY_SCAN_INVALID_FILL="2.0"
  export COMPENSATE="0"
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
}

speed_v6() {
  export POLICY_MAX_LINEAR="1.05"
  export POLICY_MAX_ANGULAR="1.09956"
}

speed_v7_double() {
  export POLICY_MAX_LINEAR="2.10"
  export POLICY_MAX_ANGULAR="2.19912"
}

speed_v8() {
  export POLICY_MAX_LINEAR="1.00"
  export POLICY_MAX_ANGULAR="1.0472"
}

speed_v9_angular() {
  speed_v8
  export POLICY_MAX_ANGULAR="0.83776"
}

speed_v10_final() {
  speed_v9_angular
  export POLICY_MAX_LINEAR="0.90"
}

speed_linear_only() {
  speed_v8
  export POLICY_MAX_LINEAR="0.90"
}

compensation_off() {
  export COMPENSATE="0"
}

compensation_raw() {
  export COMPENSATE="1"
}

compensation_guarded() {
  export COMPENSATE="1"
}
