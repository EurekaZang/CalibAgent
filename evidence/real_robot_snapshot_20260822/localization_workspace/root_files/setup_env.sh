#!/bin/bash
# 导航统一环境 - 所有脚本必须先 source 此文件
export PATH="/usr/bin:/bin:/usr/local/bin:$PATH"

if [ -n "${CONDA_DEFAULT_ENV:-}" ]; then
  echo "提示: 检测到 conda ($CONDA_DEFAULT_ENV), 正在退出..."
  if command -v conda &>/dev/null; then
    conda deactivate 2>/dev/null || true
    conda deactivate 2>/dev/null || true
  fi
fi

# ROS setup.bash 在 set -u 下会因 AMENT_TRACE_SETUP_FILES 未定义而报错
set +u
if [ -f /home/unitree/unitree_ros2/setup.sh ]; then
  # shellcheck disable=SC1091
  source /home/unitree/unitree_ros2/setup.sh
else
  echo "警告: 未找到 unitree_ros2 (重定位/Nav2 仍可测; cmd_vel 真走需安装)"
  # shellcheck disable=SC1091
  source /opt/ros/foxy/setup.bash
fi
# shellcheck disable=SC1091
source /home/unitree/project/ros2_ws/install/setup.bash
# shellcheck disable=SC1091
source /home/unitree/ws_localization/install/setup.bash

_LIVOX_SDK_OPT="/home/unitree/Livox-SDK2/build/sdk_core"
if [ -f "$_LIVOX_SDK_OPT/liblivox_lidar_sdk_shared.so" ]; then
  export LD_LIBRARY_PATH="$_LIVOX_SDK_OPT:${LD_LIBRARY_PATH:-}"
fi

# 防止后续 workspace 覆盖 DDS 配置
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# 机载算力(狗上 Jetson)网口说明:
#   狗内部网 = 192.168.123.x (MID360 雷达 .20 + 狗 DDS 都在这个网段)
#   关键: 这个网段可能落在 eth0 或 eth1 上(实测会随插拔/重启互换!),
#   所以必须"按 IP 段选网口", 而不是按网口名硬选 eth1。
#   历史教训: 旧逻辑硬选 eth1, 结果跑导航时 eth1 掉线、123.x 跑到了 eth0,
#   DDS 绑死在已 DOWN 的 eth1 上 -> 节点全部失联 -> controller 报 odom 不存在。
# 手动覆盖: GO2_DDS_IFACE=eth1 ./run_navigation.sh
_iface_has_dog_net() {
  ip -4 addr show "$1" 2>/dev/null | grep -q 'inet 192\.168\.123\.'
}
_iface_lower_up() {
  ip link show "$1" 2>/dev/null | grep -q 'LOWER_UP'
}
_pick_dds_iface() {
  if [ -n "${GO2_DDS_IFACE:-}" ]; then
    echo "$GO2_DDS_IFACE"
    return
  fi
  # 1) 优先: 谁真正持有狗内网 192.168.123.x 且链路 UP, 就用谁(不管叫 eth0 还是 eth1)
  local i
  for i in eth1 eth0 $(ls /sys/class/net 2>/dev/null); do
    if _iface_lower_up "$i" && _iface_has_dog_net "$i"; then
      echo "$i"
      return
    fi
  done
  # 2) 退而求其次: 任一 UP 的物理网口
  if _iface_lower_up eth1; then echo eth1; return; fi
  if _iface_lower_up eth0; then echo eth0; return; fi
  echo lo
}
GO2_DDS_IFACE="$(_pick_dds_iface)"
export GO2_DDS_IFACE
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"${GO2_DDS_IFACE}\" priority=\"default\" multicast=\"default\" /></Interfaces></General></Domain></CycloneDDS>"

if [ "$GO2_DDS_IFACE" = "lo" ]; then
  echo "警告: 未找到 UP 的物理网口, DDS 使用 lo (仅本机自检, 收不到雷达/狗)"
elif _iface_has_dog_net "$GO2_DDS_IFACE"; then
  _dog_ip="$(ip -4 addr show "$GO2_DDS_IFACE" 2>/dev/null | grep -o 'inet 192\.168\.123\.[0-9]*' | head -1)"
  echo "DDS 使用 $GO2_DDS_IFACE (持有狗内网 ${_dog_ip#inet }, 雷达/狗 DDS 可达)"
else
  echo "警告: DDS 使用 $GO2_DDS_IFACE, 但该网口没有 192.168.123.x 地址!"
  echo "      雷达(192.168.123.20)/狗 DDS 可能不可达。检查 'ip addr' 确认狗内网在哪个口。"
fi

# 统一清理本套导航/定位的所有节点(含上次残留的 setsid RViz、nav2 全家、TF 发布者)。
# 关键: 残留的 nav_tf_manager 会和新实例抢发 map->odom TF, 残留 fastlio 会双发 /Odometry,
# 都会让"再次启动"时定位/显示发飘。每次启动前必须从干净状态开始。
go2_kill_stack() {
  # 先杀 launch 主进程, 否则它会把被杀的子节点重新拉起。
  pkill -9 -f "ros2 launch go2_loc_bringup" 2>/dev/null || true
  pkill -9 -f "ros2 launch global_reloc" 2>/dev/null || true
  pkill -9 -f "ros2 launch fast_lio" 2>/dev/null || true
  pkill -9 -f "ros2 launch livox" 2>/dev/null || true
  local procs=(
    "rviz2 -d"
    nav_tf_manager
    controller_server
    planner_server
    bt_navigator
    recoveries_server
    lifecycle_manager
    goal_pose_relay
    "lib/go2_cmd_vel/cmd_vel_bridge"
    cmd_vel_bridge
    loc_health_monitor
    pointcloud_to_laserscan
    map_server
    global_reloc_node
    fastlio_mapping
    livox_ros_driver2_node
  )
  local p
  for p in "${procs[@]}"; do
    pkill -9 -f "$p" 2>/dev/null || true
  done
  # 等 fastlio 真正退出(它收到 SIGINT 后退出慢, 不等会和新实例双发 /Odometry)
  local i
  for i in $(seq 1 20); do
    if ! pgrep -f fastlio_mapping >/dev/null 2>&1; then
      break
    fi
    sleep 0.2
  done
}

# 重定位/定位测试专用清场: 比 go2_kill_stack 更彻底, 并打印残留进程。
# 残留 fastlio / nav_tf_manager / 双 launch 会导致 /Odometry 双发、TF 抢发, RViz 看起来"在飘"。
go2_pre_reloc_cleanup() {
  echo "=== 清场: 停止上次定位/导航/雷达/RViz ==="
  go2_kill_stack

  # 额外: 任意 rviz2、静态 TF。
  # 注意: 绝不能 pkill 本套 run_*.sh 脚本名(会匹配到当前正在运行的自己 -> 自杀"已杀死")。
  # 真正有害的 ros2 launch / 各节点已由 go2_kill_stack 处理。
  pkill -9 -f rviz2 2>/dev/null || true
  pkill -9 -f static_transform_publisher 2>/dev/null || true

  local wait_procs=(
    global_reloc_node
    fastlio_mapping
    livox_ros_driver2_node
    nav_tf_manager
    rviz2
  )
  local w i
  for w in "${wait_procs[@]}"; do
    for i in $(seq 1 25); do
      if ! pgrep -f "$w" >/dev/null 2>&1; then
        break
      fi
      sleep 0.2
    done
  done

  local leftover=0
  for w in "${wait_procs[@]}"; do
    local hits
    hits="$(pgrep -af "$w" 2>/dev/null | grep -v pgrep || true)"
    if [ -n "$hits" ]; then
      leftover=1
      echo "警告: 仍有残留 '$w':"
      echo "$hits" | sed 's/^/  /'
    fi
  done

  if [ "$leftover" -eq 0 ]; then
    echo "清场完成: 无残留定位/雷达/RViz 节点"
  else
    echo "清场未完全成功, 建议: ps aux | grep -E 'fastlio|global_reloc|livox|nav_tf'"
  fi
  sleep 1
}

# 仅清定位栈(不影响导航线程 / rviz2_navigation)
go2_kill_loc_stack() {
  pkill -9 -f "ros2 launch go2_loc_bringup localization.launch" 2>/dev/null || true
  pkill -9 -f "ros2 launch go2_loc_bringup reloc_only.launch" 2>/dev/null || true
  pkill -9 -f "ros2 launch go2_loc_bringup mapping.launch" 2>/dev/null || true
  pkill -9 -f "ros2 launch global_reloc" 2>/dev/null || true
  pkill -9 -f "ros2 launch fast_lio" 2>/dev/null || true
  pkill -9 -f "ros2 launch livox" 2>/dev/null || true
  local procs=(
    "rviz2 -d.*fastlio"
    nav_tf_manager
    loc_health_monitor
    global_reloc_node
    fastlio_mapping
    livox_ros_driver2_node
  )
  local p
  for p in "${procs[@]}"; do
    pkill -9 -f "$p" 2>/dev/null || true
  done
}

# 仅清导航栈(不影响定位栈 / rviz2_localization)
go2_kill_nav_stack() {
  pkill -9 -f "ros2 launch go2_navigation" 2>/dev/null || true
  pkill -9 -f nav_goal_manager 2>/dev/null || true
  pkill -9 -f "rviz2 -d.*navigation.rviz" 2>/dev/null || true
}
