#!/bin/bash
# 从建图导出的关键帧 + 合并地图, 生成全局重定位数据库
# 用法: ./build_reloc_db.sh [地图.pcd] [db目录]
set -e

MAP="${1:-/home/unitree/ws_localization/src/FAST_LIO/PCD/scans.pcd}"
DB="${2:-/home/unitree/ws_localization/src/FAST_LIO/PCD/reloc_db}"

if [ ! -f "$MAP" ]; then
    echo "错误: 地图不存在: $MAP"
    exit 1
fi
if [ ! -f "$DB/poses.txt" ]; then
    echo "错误: 未找到 $DB/poses.txt"
    echo "请先运行 ./run_mapping.sh 重新建图(已开启 keyframe_save), 走完一圈后 Ctrl-C"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/setup_env.sh"

echo "============================================"
echo " 构建全局重定位数据库"
echo " 地图: $MAP"
echo " DB:   $DB"
echo "============================================"

# 清掉上一次的派生缓存, 强制从当前 scans.pcd 重建。
# 关键: map_gicp.pcd/map_voxel.pcd 是缓存, 若残留旧图会让 GICP 把初值算到旧坐标系
# (实测 06-10 旧缓存 + 06-11 新图 => 重定位初值偏 ~40°, RViz 点云倾斜)。
rm -f "$DB/map_gicp.pcd" "$DB/map_voxel.pcd" 2>/dev/null && \
    echo ">>> 已清除旧派生缓存(map_gicp.pcd/map_voxel.pcd), 将从当前地图重建"

ros2 run global_reloc build_reloc_db --ros-args \
    -p db_dir:="$DB" \
    -p map_pcd:="$MAP" \
    -p voxel_leaf:=0.3

echo ""
echo ">>> 完成。启动自动重定位:"
echo "    cd ~/ws_localization && ./run_reloc_only.sh"
