#!/bin/bash
set -e
PCD="${1:-/home/unitree/ws_localization/src/FAST_LIO/PCD/scans.pcd}"
NAME="${2:-scans}"
OUT="/home/unitree/ws_localization/src/go2_loc_bringup/maps"
CONFIG="/home/unitree/ws_localization/src/go2_map_tools/config/map_projection.yaml"
export PATH="/usr/bin:/bin:/usr/local/bin:$PATH"
source /opt/ros/foxy/setup.bash
source /home/unitree/ws_localization/install/setup.bash
mkdir -p "$OUT"
ros2 run go2_map_tools pcd_to_occupancy_grid "$PCD" -o "$OUT/$NAME" --config "$CONFIG"

# 重新生成的是"干净底图"。保存为 base, 再把已有虚拟障碍(玻璃/禁区)重新合成回来,
# 这样重建地图不会丢失之前手动标的障碍(障碍以世界坐标存储, 与栅格原点无关)。
cp -f "$OUT/$NAME.pgm" "$OUT/$NAME.base.pgm"
if [ -f "$OUT/$NAME.obstacles.json" ]; then
    echo "检测到虚拟障碍记录, 重新合成..."
    ros2 run go2_map_tools manage_obstacles --map "$OUT/$NAME.yaml" rebuild
fi
