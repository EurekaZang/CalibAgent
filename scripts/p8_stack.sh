#!/usr/bin/env bash
set -euo pipefail

SESSION="calibagent_p8_stack"
LOC_SESSION="calibagent_p8_localization"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DCLP_ROOT="/home/unitree/qyw/dclp_20260710_reproduction"
ROBOT_DIR="${DCLP_ROOT}/dclp_deploy/robots/unitree_go2"
LOG_DIR="/home/unitree/lly/p8_real/stack_logs"
HEALTH="${ROBOT_DIR}/dclp_topic_health.py"
mkdir -p "${LOG_DIR}"

ros_env='source /home/unitree/ws_localization/setup_env.sh'

case "${1:-}" in
  start)
    if tmux has-session -t "${SESSION}" 2>/dev/null; then echo "P8 stack already running" >&2; exit 1; fi
    if pgrep -f 'go2_zmq_sport_client.py' >/dev/null; then
      echo "Another Go2 actuator client is running. Stop the existing DCLP run first." >&2; exit 1
    fi
    sha256sum --check "${ROOT}/configs/p8/runtime_stack.sha256"
    started_localization=0
    cleanup_failed_start() {
      tmux kill-session -t "${SESSION}" 2>/dev/null || true
      if [[ "${started_localization}" == "1" ]]; then
        tmux kill-session -t "${LOC_SESSION}" 2>/dev/null || true
      fi
    }
    trap cleanup_failed_start ERR
    if ! tmux has-session -t "${LOC_SESSION}" 2>/dev/null; then
      tmux new-session -d -s "${LOC_SESSION}" "cd /home/unitree/ws_localization && exec ./run_localization.sh norviz 2>&1 | tee '${LOG_DIR}/localization.log'"
      started_localization=1
      # Let Livox discovery and its startup backlog settle before the strict
      # timestamp check; the checker intentionally does not accept stale data.
      sleep 8
    fi
    bash -lc "${ros_env}; /usr/bin/python3 '${HEALTH}' --topic /livox/lidar_pc2 --type sensor_msgs/msg/PointCloud2 --duration 12 --min-rate 10 --min-count 30 --max-age-ms 120"
    bash -lc "${ros_env}; /usr/bin/python3 '${HEALTH}' --topic /Odometry --type nav_msgs/msg/Odometry --duration 5 --min-rate 10 --min-count 30 --max-age-ms 120"
    pc2scan="${ros_env}; exec /usr/bin/python3 '${ROBOT_DIR}/go2_livox_pc2scan_ros2.py' --ros-args -p cloud_topic:=/livox/lidar_pc2 -p scan_topic:=/scan -p odom_topic:=/Odometry -p target_frame:=base_link -p queue_size:=1 -p scan_time:=0.02 -p min_height:=0.20 -p max_height:=1.00 -p range_min:=0.26 -p range_max:=20.0 -p accumulation_frames:=5 -p accumulation_max_age:=0.12 -p motion_compensation:=true -p odom_max_stamp_delta:=0.08 -p odom_history_sec:=2.0 -p min_raw_finite_points:=1000 -p min_valid_beams:=64 -p drop_low_quality_scan:=true -p tf_x:=0.1870 -p tf_y:=0.0 -p tf_z:=0.3603 -p tf_qx:=0.0 -p tf_qy:=0.113203 -p tf_qz:=0.0 -p tf_qw:=0.993572"
    tmux new-session -d -s "${SESSION}" -n scan "${pc2scan} 2>&1 | tee '${LOG_DIR}/pc2scan.log'"
    bash -lc "${ros_env}; /usr/bin/python3 '${HEALTH}' --topic /scan --type sensor_msgs/msg/LaserScan --duration 8 --min-rate 15 --min-count 60 --max-age-ms 120 --min-valid-beams 64"
    policy="${ros_env}; export PYTHONNOUSERSITE=1 POLICY_MODEL_PATH='${DCLP_ROOT}/models/dclp/V1_41lambda1_101.pth' POLICY_BACKEND=pth POLICY_DEVICE=cpu POLICY_RATE_HZ=25.0 POLICY_SCAN_TOPIC=/scan POLICY_ODOM_TOPIC=/Odometry POLICY_GLOBAL_FRAME=map POLICY_GOAL_TOPIC=/move_base_simple/goal POLICY_RELATIVE_GOAL_TOPIC=/dclp_relative_goal POLICY_CMD_VEL_TOPIC=/p8/planned_cmd_vel POLICY_ZMQ_BIND=tcp://*:5598 POLICY_ZMQ_INCLUDE_META=true POLICY_COMPENSATE=0 POLICY_ENABLED_ON_START=true POLICY_STOP_WHEN_REACHED=true POLICY_GOAL_TOLERANCE=0.25 POLICY_MAX_LINEAR=0.60 POLICY_MAX_ANGULAR=0.80 POLICY_OBS_MAX_LINEAR_ACC=3.0 POLICY_OBS_MAX_ANGULAR_ACC=3.0 POLICY_SCAN_TIMEOUT=0.12 POLICY_SCAN_STAMP_TIMEOUT=0.12 POLICY_ODOM_TIMEOUT=0.12 POLICY_ODOM_STAMP_TIMEOUT=0.12 POLICY_TF_TIMEOUT=0.01 POLICY_SCAN_MIN_VALUE=0.20 POLICY_SCAN_INVALID_FILL=2.0 DCLP_LENGTH1=0.42 DCLP_LENGTH2=0.42 DCLP_WIDTH=0.372 POLICY_TRAJECTORY_LOG_ENABLED=true POLICY_TRAJECTORY_LOG_DIR='${LOG_DIR}'; exec '${ROBOT_DIR}/start_policy.sh'"
    tmux new-window -t "${SESSION}" -n policy "${policy} 2>&1 | tee '${LOG_DIR}/policy.log'"
    bash -lc "${ros_env}; /usr/bin/python3 '${HEALTH}' --topic /p8/planned_cmd_vel --type geometry_msgs/msg/Twist --duration 20 --min-rate 20 --min-count 100"
    trap - ERR
    "$0" status
    ;;
  status)
    tmux list-windows -t "${SESSION}" -F '#{window_name} pid=#{pane_pid} dead=#{pane_dead}' 2>/dev/null || true
    bash -lc "${ros_env}; ros2 topic list | grep -E '^/(Odometry|scan|p8/planned_cmd_vel|livox/lidar_pc2)$' || true"
    ;;
  stop)
    if pgrep -f 'calibagent.cli.p8_real (nav|shift)' >/dev/null; then
      echo "Stop the foreground P8 runner first so its defined trial/episode end sends zero." >&2; exit 1
    fi
    tmux kill-session -t "${SESSION}" 2>/dev/null || true
    if [[ "${2:-}" == "--with-localization" ]]; then tmux kill-session -t "${LOC_SESSION}" 2>/dev/null || true; fi
    echo "P8 planner/scan stack stopped"
    ;;
  log)
    tail -n 160 "${LOG_DIR}/${2:-policy}.log"
    ;;
  attach)
    exec tmux attach-session -t "${SESSION}"
    ;;
  *) echo "Usage: $0 {start|status|stop [--with-localization]|log [policy|pc2scan|localization]|attach}"; exit 2 ;;
esac
