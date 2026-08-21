#!/bin/bash
# One-key workflow for mapping an unfamiliar environment.
#
# Usage:
#   ./run_mapping_onekey.sh          # mapping with RViz, then build reloc DB and 2D map
#   ./run_mapping_onekey.sh norviz   # no RViz
#   ./run_mapping_onekey.sh --map-name lobby
#
# During mapping, drive the robot through the environment. Press Ctrl-C once in
# this terminal when finished; the script will let run_mapping.sh save scans.pcd,
# then it continues with reloc DB and 2D map generation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PCD_DIR="$SCRIPT_DIR/src/FAST_LIO/PCD"
PCD_FILE="$PCD_DIR/scans.pcd"
DB_DIR="$PCD_DIR/reloc_db"
MAP_NAME="scans"
RVIZ_ARG=""
SKIP_RELOC=false
SKIP_NAV_MAP=false

usage() {
    sed -n '2,12p' "$0"
}

for arg in "$@"; do
    case "$arg" in
        norviz|--norviz)
            RVIZ_ARG="norviz"
            ;;
        --skip-reloc-db)
            SKIP_RELOC=true
            ;;
        --skip-nav-map)
            SKIP_NAV_MAP=true
            ;;
        --map-name=*)
            MAP_NAME="${arg#--map-name=}"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "未知参数: $arg"
            usage
            exit 2
            ;;
    esac
done

if [ -z "$MAP_NAME" ]; then
    echo "错误: --map-name 不能为空"
    exit 2
fi

mkdir -p "$PCD_DIR"

START_TS="$(date +%s)"
BEFORE_MTIME=0
if [ -f "$PCD_FILE" ]; then
    BEFORE_MTIME="$(stat -c %Y "$PCD_FILE" 2>/dev/null || echo 0)"
fi

echo "============================================"
echo " 一键陌生环境建图"
echo " 工作区: $SCRIPT_DIR"
echo " RViz:   $([ -n "$RVIZ_ARG" ] && echo false || echo true)"
echo ""
echo " 流程:"
echo "   1) 启动 MID360 + FAST-LIO 建图"
echo "   2) 你遥控机器狗走完整个环境"
echo "   3) 在本终端按一次 Ctrl-C 保存地图"
echo "   4) 自动生成全局重定位数据库"
echo "   5) 自动生成 2D 栅格地图"
echo ""
echo " 输出:"
echo "   3D地图:      $PCD_FILE"
echo "   重定位数据库: $DB_DIR"
echo "   2D地图名:     $MAP_NAME"
echo "============================================"

INT_SEEN=0
on_mapping_int() {
    INT_SEEN=1
    echo ""
    echo ">>> 收到 Ctrl-C，等待 run_mapping.sh 保存 scans.pcd，然后继续后处理..."
}
trap on_mapping_int INT

set +e
if [ -n "$RVIZ_ARG" ]; then
    "$SCRIPT_DIR/run_mapping.sh" "$RVIZ_ARG"
else
    "$SCRIPT_DIR/run_mapping.sh"
fi
MAP_RC=$?
set -e
trap - INT

AFTER_MTIME=0
MAP_SIZE=0
if [ -f "$PCD_FILE" ]; then
    AFTER_MTIME="$(stat -c %Y "$PCD_FILE" 2>/dev/null || echo 0)"
    MAP_SIZE="$(stat -c %s "$PCD_FILE" 2>/dev/null || echo 0)"
fi

echo ""
echo "============================================"
echo " 建图进程已退出: rc=$MAP_RC, ctrl_c=$INT_SEEN"
echo " scans.pcd mtime: before=$BEFORE_MTIME after=$AFTER_MTIME size=$MAP_SIZE"
echo "============================================"

if [ ! -f "$PCD_FILE" ]; then
    echo "错误: 未生成地图文件: $PCD_FILE"
    exit 1
fi

if [ "$AFTER_MTIME" -lt "$START_TS" ]; then
    echo "错误: scans.pcd 看起来不是本次建图生成的，停止后处理，避免误用旧地图。"
    echo "提示: 请确认雷达有数据，并在 FAST-LIO 完成保存后再退出。"
    exit 1
fi

if [ "$MAP_SIZE" -lt 1024 ]; then
    echo "错误: scans.pcd 文件过小，可能没有有效点云，停止后处理。"
    exit 1
fi

if [ "$MAP_RC" -ne 0 ] && [ "$MAP_RC" -ne 130 ]; then
    echo "警告: run_mapping.sh 返回非正常退出码 $MAP_RC，但检测到新 scans.pcd，继续后处理。"
fi

if [ "$SKIP_RELOC" = false ]; then
    echo ""
    echo ">>> 构建全局重定位数据库..."
    "$SCRIPT_DIR/build_reloc_db.sh" "$PCD_FILE" "$DB_DIR"
else
    echo ""
    echo ">>> 跳过全局重定位数据库构建。"
fi

if [ "$SKIP_NAV_MAP" = false ]; then
    echo ""
    echo ">>> 生成 2D 栅格地图..."
    "$SCRIPT_DIR/build_nav_map.sh" "$PCD_FILE" "$MAP_NAME"
else
    echo ""
    echo ">>> 跳过 2D 栅格地图生成。"
fi

echo ""
echo "============================================"
echo " 一键建图完成"
echo ""
echo " 下一步可验证:"
echo "   cd $SCRIPT_DIR"
echo "   ./run_reloc_only.sh"
echo "   ./run_localization.sh"
echo "   ./run_navigation.sh"
echo "============================================"
