#!/usr/bin/env bash
# Stop Go2 deploy processes started by this directory.

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRACE_SECONDS="${GRACE_SECONDS:-2}"

PATTERNS=(
  "${ROBOT_DIR}/go2_sport_odom_node.py"
  "${ROBOT_DIR}/go2_zmq_sport_client.py"
  "${ROBOT_DIR}/dclp_go2_policy_ros2.py"
  "${ROBOT_DIR}/go2_uwb_ros_goal_bridge.py"
  "${ROBOT_DIR}/goal_sequencer_ros2.py"
  "ros2 launch livox_ros_driver2"
  "livox_ros_driver2_node"
  "pointcloud_to_laserscan_node"
  "ros2 launch slam_toolbox online_async_launch.py"
  "async_slam_toolbox_node"
  "ros2 launch nav2_bringup localization_launch.py"
  "nav2_map_server/map_server"
  "nav2_amcl/amcl"
  "lifecycle_manager_localization"
  "static_transform_publisher .* base_link livox_frame"
  "rviz2 -d ${ROBOT_DIR}/go2_slam.rviz"
)

collect_pids() {
  local pattern pid
  for pattern in "${PATTERNS[@]}"; do
    while read -r pid; do
      [[ -n "${pid}" ]] || continue
      [[ "${pid}" != "$$" ]] || continue
      echo "${pid}"
    done < <(pgrep -f "${pattern}" || true)
  done | sort -n -u
}

stop_pids() {
  local signal="$1"
  shift
  local pids=("$@")
  if [[ "${#pids[@]}" -gt 0 ]]; then
    kill "-${signal}" "${pids[@]}" 2>/dev/null || true
  fi
}

mapfile -t pids < <(collect_pids)
if [[ "${#pids[@]}" -eq 0 ]]; then
  echo "[go2:stop] no existing Go2 deploy processes"
  exit 0
fi

echo "[go2:stop] stopping existing Go2 deploy processes: ${pids[*]}"
stop_pids INT "${pids[@]}"
sleep "${GRACE_SECONDS}"

mapfile -t pids < <(collect_pids)
if [[ "${#pids[@]}" -gt 0 ]]; then
  stop_pids TERM "${pids[@]}"
  sleep 1
fi

mapfile -t pids < <(collect_pids)
if [[ "${#pids[@]}" -gt 0 ]]; then
  echo "[go2:stop] force killing: ${pids[*]}"
  stop_pids KILL "${pids[@]}"
fi

echo "[go2:stop] done"
