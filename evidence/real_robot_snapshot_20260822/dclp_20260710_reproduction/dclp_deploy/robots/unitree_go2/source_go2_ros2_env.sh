#!/usr/bin/env bash
# Source this before running raw ros2 CLI checks for the Go2 deploy stack.

_GO2_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_GO2_ENV_DIR}/load_params_env.sh"

ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
UNITREE_ROS2_MSG_SETUP="${UNITREE_ROS2_MSG_SETUP:-${HOME}/unitree_ros2/cyclonedds_ws/install/setup.bash}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${_GO2_ENV_DIR}/cyclonedds_go2_eth0.xml}"

if [[ -f "${ROS_DISTRO_SETUP}" ]]; then
  source "${ROS_DISTRO_SETUP}"
fi
if [[ -f "${ROS2_SETUP}" ]]; then
  source "${ROS2_SETUP}"
fi
if [[ -f "${UNITREE_ROS2_MSG_SETUP}" ]]; then
  source "${UNITREE_ROS2_MSG_SETUP}"
fi
if [[ -f "${CYCLONEDDS_CONFIG}" ]]; then
  export CYCLONEDDS_URI="${CYCLONEDDS_CONFIG}"
fi
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros2_go2_logs}"
mkdir -p "${ROS_LOG_DIR}"

if [[ "${CYCLONEDDS_URI:-}" == *"eth0"* ]] && command -v ip >/dev/null 2>&1; then
  if _go2_eth0_addr="$(ip -4 addr show dev eth0 2>/dev/null)" && ! grep -q 'inet ' <<<"${_go2_eth0_addr}"; then
    echo "[go2:env] WARN: eth0 has no IPv4 address; MID360 expects 192.168.123.222/24 on eth0" >&2
  fi
fi

echo "[go2:env] CYCLONEDDS_URI=${CYCLONEDDS_URI:-<unset>}"
echo "[go2:env] RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<unset>}"
