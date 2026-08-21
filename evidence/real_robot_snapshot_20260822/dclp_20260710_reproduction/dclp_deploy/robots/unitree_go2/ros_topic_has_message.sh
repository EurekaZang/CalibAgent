#!/usr/bin/env bash
# Exit 0 when a ROS2 topic yields at least one message within a short timeout.

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"

TOPIC="${1:-}"
TYPE="${2:-}"
QOS_RELIABILITY="${QOS_RELIABILITY:-best_effort}"
QOS_DURABILITY="${QOS_DURABILITY:-volatile}"
WAIT_SECONDS="${WAIT_SECONDS:-8}"

if [[ -z "${TOPIC}" || -z "${TYPE}" ]]; then
  echo "usage: $0 /topic pkg/msg/Type" >&2
  exit 2
fi

set +u
source "${ROBOT_DIR}/source_go2_ros2_env.sh" >/dev/null
set -u
export ROS2CLI_ENABLE_DAEMON="${ROS2CLI_ENABLE_DAEMON:-0}"

tmp_file="$(mktemp)"
cleanup() {
  rm -f "${tmp_file}"
  if [[ -n "${echo_pid:-}" ]]; then
    kill "${echo_pid}" 2>/dev/null || true
    wait "${echo_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

PYTHONUNBUFFERED=1 ros2 topic echo \
  --qos-reliability "${QOS_RELIABILITY}" \
  --qos-durability "${QOS_DURABILITY}" \
  "${TOPIC}" "${TYPE}" >"${tmp_file}" 2>/dev/null &
echo_pid="$!"
deadline=$((SECONDS + WAIT_SECONDS))
while (( SECONDS < deadline )); do
  if [[ -s "${tmp_file}" ]]; then
    exit 0
  fi
  if ! kill -0 "${echo_pid}" 2>/dev/null; then
    break
  fi
  sleep 0.2
done

exit 1
