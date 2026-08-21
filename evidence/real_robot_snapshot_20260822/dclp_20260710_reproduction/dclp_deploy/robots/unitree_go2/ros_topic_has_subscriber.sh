#!/usr/bin/env bash
# Exit 0 when a ROS2 topic has at least one discovered subscriber.

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"

TOPIC="${1:-}"

if [[ -z "${TOPIC}" ]]; then
  echo "usage: $0 /topic" >&2
  exit 2
fi

set +u
source "${ROBOT_DIR}/source_go2_ros2_env.sh" >/dev/null
set -u
export ROS2CLI_ENABLE_DAEMON="${ROS2CLI_ENABLE_DAEMON:-0}"

info="$(ros2 topic info "${TOPIC}" 2>/dev/null || true)"
count="$(printf '%s\n' "${info}" | awk -F': ' '/Subscription count:/ {print $2; exit}')"
[[ "${count:-0}" =~ ^[0-9]+$ ]] && (( count > 0 ))
