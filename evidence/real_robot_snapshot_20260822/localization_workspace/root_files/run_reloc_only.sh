#!/bin/bash
# 单独测重定位 + RViz 可视化（与 run_global_localization 相同视图）
# 不含 Nav2 / nav_tf_manager / loc_health_monitor
#
# 用法:
#   ./run_reloc_only.sh              # 开 RViz（默认）
#   ./run_reloc_only.sh norviz       # 无显示时用
#   ./run_reloc_only.sh [地图.pcd]   # 指定先验地图
#
# RViz 中看: CloudRegistered(/cloud_registered), Odometry(/Odometry), TF

set -e

DEFAULT_MAP=/home/unitree/ws_localization/src/FAST_LIO/PCD/scans.pcd
DEFAULT_DB=/home/unitree/ws_localization/src/FAST_LIO/PCD/reloc_db
PRIOR_MAP="$DEFAULT_MAP"
DB_DIR="$DEFAULT_DB"
RVIZ=true

for arg in "$@"; do
    if [ "$arg" = "norviz" ]; then
        RVIZ=false
    elif [ -f "$arg" ]; then
        PRIOR_MAP="$arg"
    elif [ -n "$arg" ]; then
        echo "错误: 找不到文件: $arg"
        exit 1
    fi
done

if [ ! -f "$PRIOR_MAP" ]; then
    echo "错误: 先验地图不存在: $PRIOR_MAP"
    exit 1
fi
if [ ! -f "$DB_DIR/poses.txt" ]; then
    echo "错误: 重定位数据库不存在: $DB_DIR/poses.txt"
    echo "请先: ./run_mapping.sh -> ./build_reloc_db.sh"
    exit 1
fi
if [ ! -f "$DB_DIR/map_voxel.pcd" ]; then
    echo "提示: map_voxel.pcd 不存在, 正在构建..."
    ./build_reloc_db.sh "$PRIOR_MAP" "$DB_DIR"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/setup_env.sh"
go2_pre_reloc_cleanup

LOG="/tmp/go2_reloc_only.log"
echo "============================================"
echo " 单独重定位 + FAST-LIO + RViz"
echo " 地图: $PRIOR_MAP"
echo " DB:   $DB_DIR"
echo " RViz: $RVIZ"
echo " 日志: $LOG"
echo ""
echo " 测试前已清场(杀残留 fastlio/global_reloc/nav_tf/rviz)"
echo " (无 Nav2 / nav_tf / loc_health)"
echo ""
echo " RViz: CloudRegistered, Odometry, TF"
echo " 启动后等 5~10s IMU 初始化"
echo "============================================"

ros2 launch go2_loc_bringup reloc_only.launch.py \
    prior_map:="$PRIOR_MAP" db_dir:="$DB_DIR" rviz:=$RVIZ 2>&1 | tee "$LOG"
