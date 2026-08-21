#!/usr/bin/env bash
# Stop only Go2 policy navigation task processes; keep localization running.

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRACE_SECONDS="${GRACE_SECONDS:-2}"

PATTERNS=(
  "${ROBOT_DIR}/go2_zmq_sport_client.py"
  "${ROBOT_DIR}/dclp_go2_policy_ros2.py"
  "${ROBOT_DIR}/go2_uwb_ros_goal_bridge.py"
  "${ROBOT_DIR}/goal_sequencer_ros2.py"
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
  echo "[go2:stop_nav] no existing Go2 navigation task processes"
  exit 0
fi

echo "[go2:stop_nav] stopping navigation task processes: ${pids[*]}"
stop_pids INT "${pids[@]}"
sleep "${GRACE_SECONDS}"

mapfile -t pids < <(collect_pids)
if [[ "${#pids[@]}" -gt 0 ]]; then
  stop_pids TERM "${pids[@]}"
  sleep 1
fi

mapfile -t pids < <(collect_pids)
if [[ "${#pids[@]}" -gt 0 ]]; then
  echo "[go2:stop_nav] force killing: ${pids[*]}"
  stop_pids KILL "${pids[@]}"
fi

echo "[go2:stop_nav] done"
