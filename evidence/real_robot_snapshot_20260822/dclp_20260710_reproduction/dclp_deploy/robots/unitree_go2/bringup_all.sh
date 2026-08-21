#!/usr/bin/env bash
# Unitree Go2 + Livox MID360 一键多终端启动链。

set -euo pipefail

ROBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROBOT_DIR}/load_params_env.sh"
AMCL_MAP="${AMCL_MAP:-}"
if [[ -z "${SLAM_MODE:-}" && -n "${AMCL_MAP}" ]]; then
  SLAM_MODE="amcl"
else
  SLAM_MODE="${SLAM_MODE:-slam}"            # slam | amcl
fi
NO_RVIZ="${NO_RVIZ:-0}"
MID360_RVIZ="${MID360_RVIZ:-0}"
AUTOLAUNCH_POLICY="${AUTOLAUNCH_POLICY:-0}"
AUTOLAUNCH_UWB_GOAL="${AUTOLAUNCH_UWB_GOAL:-0}"
if [[ -z "${AUTOLAUNCH_GO2_ZMQ:-}" ]]; then
  if [[ "${AUTOLAUNCH_POLICY}" == "1" ]]; then
    AUTOLAUNCH_GO2_ZMQ=1
  else
    AUTOLAUNCH_GO2_ZMQ=0
  fi
fi
CLEAN_EXISTING="${CLEAN_EXISTING:-1}"

case "${SLAM_MODE}" in
  slam) ;;
  amcl)
    if [[ -z "${AMCL_MAP}" || ! -f "${AMCL_MAP}" ]]; then
      echo "[bringup:unitree_go2] SLAM_MODE=amcl 但 AMCL_MAP 不存在: ${AMCL_MAP}" >&2
      echo "  先 SLAM_MODE=slam 建图，再运行 ${ROBOT_DIR}/save_map.sh" >&2
      exit 1
    fi
    ;;
  *)
    echo "[bringup:unitree_go2] 未知 SLAM_MODE=${SLAM_MODE}（可选: slam / amcl）" >&2
    exit 1
    ;;
esac

echo "[bringup:unitree_go2] PARAM_FILE=${PARAM_FILE}"
echo "[bringup:unitree_go2] mode=${SLAM_MODE}, AMCL_MAP=${AMCL_MAP:-<empty>}"
if [[ "${SLAM_MODE}" == "slam" && -n "${AMCL_MAP}" ]]; then
  echo "[bringup:unitree_go2] 注意：SLAM_MODE=slam 会建新图，AMCL_MAP 会被忽略。导入地图请用 SLAM_MODE=amcl。"
fi

if [[ -n "${GOAL_LIST:-}" && ! -f "${GOAL_LIST}" ]]; then
  echo "[bringup:unitree_go2] GOAL_LIST 不存在: ${GOAL_LIST}" >&2
  exit 1
fi
GOAL_LIST="${GOAL_LIST:-}"

if [[ "${CLEAN_EXISTING}" == "1" ]]; then
  bash "${ROBOT_DIR}/stop_stack.sh"
elif [[ "${CLEAN_EXISTING}" != "0" ]]; then
  echo "[bringup:unitree_go2] 未知 CLEAN_EXISTING=${CLEAN_EXISTING}（可选: 1 / 0）" >&2
  exit 1
fi

if ! command -v gnome-terminal >/dev/null; then
  echo "[bringup:unitree_go2] 需要 gnome-terminal；也可以按 README 分组件手动启动"
  exit 1
fi

run_terminal() {
  local title="$1"
  local body="$2"
  local terminal_cmd
  terminal_cmd="${body}
status=\$?
echo
echo \"[bringup:unitree_go2] ${title} exited with status \${status}\"
exec bash"
  if ! gnome-terminal --tab --title="${title}" -- env DVST2_TERMINAL_CMD="${terminal_cmd}" \
    bash -lc 'exec bash -ic "$DVST2_TERMINAL_CMD"'; then
    echo "[bringup:unitree_go2] gnome-terminal 启动失败: ${title}" >&2
    return 1
  fi
}

if [[ "${MID360_RVIZ}" == "1" ]]; then
  run_terminal "Go2 MID360" "NO_RVIZ=0 bash ${ROBOT_DIR}/start_mid360.sh"
else
  run_terminal "Go2 MID360" "NO_RVIZ=1 bash ${ROBOT_DIR}/start_mid360.sh"
fi
sleep 2

run_terminal "Go2 Odom" "bash ${ROBOT_DIR}/start_odom.sh"
sleep 1

TF_PARENT_FRAME="${TF_PARENT_FRAME:-base_link}"
TF_CHILD_FRAME="${TF_CHILD_FRAME:-livox_frame}"
TF_X="${TF_X:-0.1870}"
TF_Y="${TF_Y:-0}"
TF_Z="${TF_Z:-0.3603}"
TF_QX="${TF_QX:-0}"
TF_QY="${TF_QY:-0.113203}"
TF_QZ="${TF_QZ:-0}"
TF_QW="${TF_QW:-0.993572}"
ROS2_WS="${ROS2_WS:-/home/unitree/project/ros2_ws}"
ROS2_SETUP="${ROS2_SETUP:-${ROS2_WS}/install/setup.bash}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/foxy/setup.bash}"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-${HOME}/cyclonedds_ws/cyclonedds.xml}"
run_terminal "Go2 TF" "if [[ -f ${CYCLONEDDS_CONFIG} ]]; then export CYCLONEDDS_URI=${CYCLONEDDS_CONFIG}; fi
if [[ -f ${ROS_DISTRO_SETUP} ]]; then source ${ROS_DISTRO_SETUP}; fi
if [[ -f ${ROS2_SETUP} ]]; then source ${ROS2_SETUP}; fi
export ROS_LOG_DIR=\${ROS_LOG_DIR:-/tmp/ros2_go2_logs}
mkdir -p \"\${ROS_LOG_DIR}\"
echo \"[go2:tf] ${TF_PARENT_FRAME} -> ${TF_CHILD_FRAME}\"
exec ros2 run tf2_ros static_transform_publisher ${TF_X} ${TF_Y} ${TF_Z} ${TF_QX} ${TF_QY} ${TF_QZ} ${TF_QW} ${TF_PARENT_FRAME} ${TF_CHILD_FRAME}"
sleep 1

run_terminal "Go2 PC2Scan" "bash ${ROBOT_DIR}/start_pc2scan.sh"
sleep 1

case "${SLAM_MODE}" in
  slam)
    run_terminal "Go2 SLAM" "bash ${ROBOT_DIR}/start_slam.sh"
    ;;
  amcl)
    run_terminal "Go2 AMCL" "AMCL_MAP=${AMCL_MAP} bash ${ROBOT_DIR}/start_amcl.sh"
    echo "[bringup:unitree_go2] AMCL 已加载地图，但还需要初始位姿才会发布 map -> odom"
    echo "  请在 RViz2 里用 2D Pose Estimate 手动设置初始位姿"
    ;;
esac
sleep 2

if [[ "${AUTOLAUNCH_UWB_GOAL}" == "1" ]]; then
  run_terminal "Go2 UWB Goal" "bash ${ROBOT_DIR}/start_uwb_goal_bridge.sh"
  sleep 1
else
  echo "[bringup:unitree_go2] AUTOLAUNCH_UWB_GOAL=0，UWB goal bridge 未自动启动"
fi

if [[ "${NO_RVIZ}" != "1" ]]; then
  RVIZ_CONFIG="${RVIZ_CONFIG:-${ROBOT_DIR}/go2_slam.rviz}"
  run_terminal "Go2 RViz" "if [[ -f ${CYCLONEDDS_CONFIG} ]]; then export CYCLONEDDS_URI=${CYCLONEDDS_CONFIG}; fi
if [[ -f ${ROS_DISTRO_SETUP} ]]; then source ${ROS_DISTRO_SETUP}; fi
if [[ -f ${ROS2_SETUP} ]]; then source ${ROS2_SETUP}; fi
export ROS_LOG_DIR=\${ROS_LOG_DIR:-/tmp/ros2_go2_logs}
mkdir -p \"\${ROS_LOG_DIR}\"
echo \"[go2:rviz] ${RVIZ_CONFIG}\"
exec rviz2 -d ${RVIZ_CONFIG}"
  sleep 1
fi

if [[ "${AUTOLAUNCH_POLICY}" == "1" ]]; then
  run_terminal "Go2 Policy" "bash ${ROBOT_DIR}/start_policy.sh"
  sleep 1
else
  echo "[bringup:unitree_go2] AUTOLAUNCH_POLICY=0，策略节点未自动启动"
  echo "  定位收敛后再手动启动导航任务，避免定位阶段就接管底盘"
fi

if [[ "${AUTOLAUNCH_GO2_ZMQ}" == "1" ]]; then
  run_terminal "Go2 ZMQ" "bash ${ROBOT_DIR}/start_go2_zmq_sport_client.sh"
else
  echo "[bringup:unitree_go2] AUTOLAUNCH_GO2_ZMQ=0，Unitree SDK ZMQ 控制客户端未自动启动"
fi

if [[ -n "${GOAL_LIST}" ]]; then
  echo
  echo "[bringup:unitree_go2] GOAL_LIST=${GOAL_LIST} 已记录。定位收敛后运行："
  echo "    GOAL_LIST=${GOAL_LIST} bash ${ROBOT_DIR}/start_goals_policy.sh"
else
  echo "  多目标导航任务：GOAL_LIST=/abs/goals.yaml bash ${ROBOT_DIR}/start_goals_policy.sh"
fi

echo
echo "[bringup:unitree_go2] 已启动 Go2 deploy 链路。"
echo "SLAM_MODE=${SLAM_MODE}, AUTOLAUNCH_POLICY=${AUTOLAUNCH_POLICY}, AUTOLAUNCH_UWB_GOAL=${AUTOLAUNCH_UWB_GOAL}, AUTOLAUNCH_GO2_ZMQ=${AUTOLAUNCH_GO2_ZMQ}"
echo "关闭组件：在对应终端里 Ctrl-C。"
echo "停止整套链路：bash ${ROBOT_DIR}/stop_stack.sh"
