#!/usr/bin/env bash
# 启动 ROS2 DCLP 策略 controller。默认使用地图目标版本，不依赖 /uwbstate。

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
UNITREE_ROS2_SETUP="${UNITREE_ROS2_SETUP:-/home/unitree/unitree_ros2/setup.sh}"
POLICY_SOURCE_UNITREE_ROS2="${POLICY_SOURCE_UNITREE_ROS2:-0}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${HOME}/cyclonedds_ws/cyclonedds.xml}"
DEFAULT_POLICY_SCRIPT="${ROBOT_DIR}/dclp_go2_policy_ros2.py"
POLICY_SCRIPT="${POLICY_SCRIPT:-${DEFAULT_POLICY_SCRIPT}}"
DEFAULT_POLICY_PYTHON="${HOME}/miniconda3/envs/go2/bin/python"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "${DEFAULT_POLICY_PYTHON}" ]]; then
    PYTHON_BIN="${DEFAULT_POLICY_PYTHON}"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi
# 禁掉 user-site，避免 import 到 ~/.local 中残留的包版本。
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
DEFAULT_REPO_ROOT="$(cd "${ROBOT_DIR}/../../.." && pwd)"
DEFAULT_POLICY_MODEL_PATH="${DEFAULT_REPO_ROOT}/models/dclp/V1_41lambda1_101.pth"
if [[ -z "${POLICY_WORKDIR:-}" ]]; then
  if [[ "${POLICY_SCRIPT}" == "${DEFAULT_POLICY_SCRIPT}" ]]; then
    POLICY_WORKDIR="${DEFAULT_REPO_ROOT}"
  else
    POLICY_WORKDIR="$(dirname "${POLICY_SCRIPT}")"
  fi
fi
if [[ -z "${PYTHONPATH:-}" ]]; then
  export PYTHONPATH="${DEFAULT_REPO_ROOT}"
else
  export PYTHONPATH="${DEFAULT_REPO_ROOT}:${PYTHONPATH}"
fi
if [[ -n "${MODEL_PATH:-}" && "${UNITREE_GO2_PARAM_SET_VARS:-:}" == *":POLICY_MODEL_PATH:"* ]]; then
  export POLICY_MODEL_PATH="${MODEL_PATH}"
elif [[ -n "${POLICY_MODEL_PATH:-}" && "${UNITREE_GO2_PARAM_SET_VARS:-:}" == *":MODEL_PATH:"* ]]; then
  export MODEL_PATH="${POLICY_MODEL_PATH}"
elif [[ -z "${POLICY_MODEL_PATH:-}" && -n "${MODEL_PATH:-}" ]]; then
  export POLICY_MODEL_PATH="${MODEL_PATH}"
elif [[ -z "${MODEL_PATH:-}" && -n "${POLICY_MODEL_PATH:-}" ]]; then
  export MODEL_PATH="${POLICY_MODEL_PATH}"
fi
if [[ "${MODEL_PATH:-}" == *$'\n'* || "${POLICY_MODEL_PATH:-}" == *$'\n'* ]]; then
  echo "[go2:policy] MODEL_PATH/POLICY_MODEL_PATH 含换行，使用脚本内置默认 DCLP 模型路径" >&2
  export MODEL_PATH="${DEFAULT_POLICY_MODEL_PATH}"
  export POLICY_MODEL_PATH="${DEFAULT_POLICY_MODEL_PATH}"
fi
if [[ -z "${MODEL_PATH:-}" && -z "${POLICY_MODEL_PATH:-}" && -f "${DEFAULT_POLICY_MODEL_PATH}" ]]; then
  export MODEL_PATH="${DEFAULT_POLICY_MODEL_PATH}"
  export POLICY_MODEL_PATH="${DEFAULT_POLICY_MODEL_PATH}"
fi
MODEL_PATH_EFFECTIVE="${POLICY_MODEL_PATH:-${MODEL_PATH:-}}"
if [[ -z "${MODEL_PATH_EFFECTIVE}" ]]; then
  echo "[go2:policy] 必须设置 MODEL_PATH 或 POLICY_MODEL_PATH 指向 DCLP policy checkpoint" >&2
  exit 1
fi

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

source_setup "${ROS_DISTRO_SETUP}"
if [[ ! -f "${ROS2_SETUP}" ]]; then
  echo "[go2:policy] ROS2 setup 不存在: ${ROS2_SETUP}" >&2
  exit 1
fi
source_setup "${ROS2_SETUP}"
if [[ "${POLICY_SOURCE_UNITREE_ROS2}" == "1" ]]; then
  source_setup "${UNITREE_ROS2_SETUP}"
  apply_cyclonedds_config
fi
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros2_go2_logs}"
mkdir -p "${ROS_LOG_DIR}"
if [[ ! -f "${POLICY_SCRIPT}" ]]; then
  echo "[go2:policy] 策略脚本不存在: ${POLICY_SCRIPT}" >&2
  exit 1
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[go2:policy] 找不到 PYTHON_BIN=${PYTHON_BIN}" >&2
  exit 1
fi

check_python_imports() {
  "${PYTHON_BIN}" - <<'PY'
import os
missing = []
backend = os.environ.get("POLICY_BACKEND", "pth").strip().lower()
names = ["rclpy", "tf2_ros", "numpy", "zmq"]
if backend in ("", "pth", "torch", "pytorch"):
    names.append("torch")
elif backend in ("legacy_tf", "tf", "tensorflow"):
    names.append("tensorflow")
for name in names:
    try:
        __import__(name)
    except Exception as exc:
        missing.append(f"{name}: {type(exc).__name__}: {exc}")
if missing:
    raise SystemExit("\n".join(missing))
PY
}

if ! IMPORT_CHECK="$(check_python_imports 2>&1)"; then
  echo "[go2:policy] PYTHON_BIN=${PYTHON_BIN} 缺少部署所需模块:" >&2
  echo "${IMPORT_CHECK}" >&2
  echo "[go2:policy] 可尝试设置 PYTHON_BIN=/abs/python，pth 后端要求能 import rclpy/tf2_ros/torch/numpy/zmq" >&2
  exit 1
fi

cd "${POLICY_WORKDIR}"
echo "[go2:policy] python=${PYTHON_BIN}"
echo "[go2:policy] script=${POLICY_SCRIPT}"
echo "[go2:policy] model_path=${MODEL_PATH_EFFECTIVE}"
echo "[go2:policy] backend=${POLICY_BACKEND:-pth}"
echo "[go2:policy] rate=${POLICY_RATE_HZ:-<default>}Hz, scan=${POLICY_SCAN_TOPIC:-${SCAN_TOPIC:-/scan}}, odom=${POLICY_ODOM_TOPIC:-${ODOM_TOPIC:-/odom}}"
exec "${PYTHON_BIN}" "${POLICY_SCRIPT}"
