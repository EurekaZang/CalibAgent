#!/bin/bash
# 导航线程: 加载 2D 地图 + 导航目标管理(nav_goal_manager) + 可选 RViz。
# 与定位栈分离运行, 仅通过话题通信(订阅 /Odometry /loc_health; 发布 /map /nav_goal /nav_status)。
#
# 用法:
#   ./run_navigation.sh                      # 开 RViz, 用默认地图 scans.yaml
#   ./run_navigation.sh norviz               # 无显示器时
#   ./run_navigation.sh [地图.yaml]          # 指定 2D 栅格地图
#
# 前置: 另一个终端已运行 ./run_localization.sh (自动重定位, /loc_health READY 后再导航)
#
# 设定目标(任选其一):
#   - RViz 工具栏 "2D Goal Pose" 直接点地图
#   - RViz 工具栏 "Publish Point" 点地图 -> 终端打印坐标, 再用下面命令导航过去
#   - ros2 run go2_navigation send_goal X Y [YAW度]
#
# 查看: ros2 topic echo /nav_status ; ros2 topic echo /nav_goal

set -e

DEFAULT_MAP=/home/unitree/ws_localization/src/go2_loc_bringup/maps/scans.yaml
MAP_YAML="$DEFAULT_MAP"
RVIZ=true

for arg in "$@"; do
    if [ "$arg" = "norviz" ]; then
        RVIZ=false
    elif [ -f "$arg" ]; then
        MAP_YAML="$arg"
    elif [ -n "$arg" ]; then
        echo "错误: 找不到地图文件: $arg"
        exit 1
    fi
done

if [ ! -f "$MAP_YAML" ]; then
    echo "错误: 2D 地图不存在: $MAP_YAML"
    echo "请先生成: ./build_nav_map.sh src/FAST_LIO/PCD/scans.pcd scans"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/setup_env.sh"
go2_kill_nav_stack
sleep 1

echo "============================================"
echo " Go2 导航线程 (nav_goal_manager)"
echo " 地图: $MAP_YAML"
echo " RViz: $RVIZ -> 独立窗口 rviz2_navigation (2D地图/设目标)"
echo ""
echo " 前置: 另开终端先跑 ./run_localization.sh (自动重定位, 等 /loc_health=READY)"
echo ""
echo " 【导航】RViz「2D Goal Pose」或 ros2 run go2_navigation send_goal X Y [YAW度]"
echo " 取坐标: RViz 'Publish Point' 点地图, 看本终端打印"
echo "============================================"

ros2 launch go2_navigation navigation.launch.py \
    map_yaml:="$MAP_YAML" rviz:=$RVIZ
