#!/usr/bin/env bash
# 启动 Unitree Go2 ZMQ -> SportClient.Move 控制客户端。

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
UNITREE_ROS2_SETUP="${UNITREE_ROS2_SETUP:-/home/unitree/unitree_ros2/setup.sh}"
GO2_CONDA_ENV="${GO2_CONDA_ENV:-go2}"
GO2_IFACE="${GO2_IFACE:-auto}"
GO2_GAIT="${GO2_GAIT:-economic}"
GO2_CMD_SCRIPT="${GO2_CMD_SCRIPT:-${ROBOT_DIR}/go2_zmq_sport_client.py}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${HOME}/cyclonedds_ws/cyclonedds.xml}"

apply_cyclonedds_config() {
  if [[ -f "${CYCLONEDDS_CONFIG}" ]]; then
    export CYCLONEDDS_URI="${CYCLONEDDS_CONFIG}"
  fi
}

apply_cyclonedds_config

source_setup() {
  local setup_file="$1"
  if [[ -f "${setup_file}" ]]; then
    set +u
    source "${setup_file}"
    set -u
  fi
}

if [[ -n "${GO2_CONDA_ENV}" ]]; then
  set +u
  if command -v conda >/dev/null 2>&1; then
    eval "$(conda shell.bash hook)"
    conda activate "${GO2_CONDA_ENV}"
  elif [[ -f "${HOME}/miniconda3/etc/profile.d/conda.sh" ]]; then
    source "${HOME}/miniconda3/etc/profile.d/conda.sh"
    conda activate "${GO2_CONDA_ENV}"
  else
    echo "[go2:sport] 找不到 conda，无法激活 ${GO2_CONDA_ENV}" >&2
    exit 1
  fi
  set -u
fi

source_setup "${ROS2_SETUP}"
source_setup "${UNITREE_ROS2_SETUP}"
apply_cyclonedds_config
if [[ ! -f "${GO2_CMD_SCRIPT}" ]]; then
  echo "[go2:sport] 控制脚本不存在: ${GO2_CMD_SCRIPT}" >&2
  exit 1
fi

args=("${GO2_IFACE}" --gait "${GO2_GAIT}")
case "${GO2_ALLOW_GAIT_FAILURE:-0}" in
  1|true|TRUE|yes|YES|on|ON) args+=(--allow-gait-failure) ;;
esac

echo "[go2:sport] python3 ${GO2_CMD_SCRIPT} ${args[*]}"
exec python3 "${GO2_CMD_SCRIPT}" "${args[@]}"
