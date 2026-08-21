#!/usr/bin/env bash
# Start the upward-facing MID360 and FAST-LIO2 mapping stack.
# Ctrl-C performs a clean FAST-LIO2 shutdown and writes scans.pcd.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PCD_DIR="$SCRIPT_DIR/src/FAST_LIO/PCD"
PCD_FILE="$PCD_DIR/scans.pcd"
RELOC_DIR="$PCD_DIR/reloc_db"
START_TS="$(date +%s)"
PREVIOUS_MAP=""
PREVIOUS_RELOC=""

mkdir -p "$PCD_DIR"
if [ -f "$PCD_FILE" ]; then
    PREVIOUS_MAP="$PCD_DIR/map_backup_before_$(date +%Y%m%d_%H%M%S).pcd"
    mv "$PCD_FILE" "$PREVIOUS_MAP"
    echo ">>> 旧 scans.pcd 已保全为: $PREVIOUS_MAP"
fi
if [ -d "$RELOC_DIR" ]; then
    PREVIOUS_RELOC="$PCD_DIR/reloc_db_backup_before_$(date +%Y%m%d_%H%M%S)"
    mv "$RELOC_DIR" "$PREVIOUS_RELOC"
    echo ">>> 旧 reloc_db 已保全为: $PREVIOUS_RELOC"
fi

archive_map() {
    if [ -f "$PCD_FILE" ]; then
        local mt ts out ply
        mt="$(stat -c %Y "$PCD_FILE" 2>/dev/null || echo 0)"
        if [ "$mt" -ge "$START_TS" ]; then
            ts="$(date +%Y%m%d_%H%M%S)"
            out="$PCD_DIR/map_$ts.pcd"
            cp "$PCD_FILE" "$out"
            echo ">>> 本次地图已存档为: $out"
            ply="${out%.pcd}.ply"
            if command -v pcl_pcd2ply >/dev/null 2>&1; then
                pcl_pcd2ply -format 1 -use_camera 0 "$out" "$ply" >/dev/null 2>&1 \
                    && echo ">>> 已生成 PLY: $ply"
            fi
            return
        fi
    fi

    echo ">>> 本次没有生成有效的新 scans.pcd。"
    if [ -n "$PREVIOUS_MAP" ] && [ -f "$PREVIOUS_MAP" ] && [ ! -e "$PCD_FILE" ]; then
        mv "$PREVIOUS_MAP" "$PCD_FILE"
        echo ">>> 已恢复启动前的 scans.pcd。"
    fi
    if [ -n "$PREVIOUS_RELOC" ] && [ -d "$PREVIOUS_RELOC" ]; then
        if [ -d "$RELOC_DIR" ]; then
            mv "$RELOC_DIR" "$PCD_DIR/reloc_db_failed_$(date +%Y%m%d_%H%M%S)"
        fi
        mv "$PREVIOUS_RELOC" "$RELOC_DIR"
        echo ">>> 已恢复启动前的 reloc_db。"
    fi
}
trap archive_map EXIT

# shellcheck disable=SC1091
source "$SCRIPT_DIR/setup_env.sh"
go2_kill_stack
sleep 1

export LIVOX_CONFIG_PATH
LIVOX_CONFIG_PATH="$("$SCRIPT_DIR/prepare_mid360_config.sh")"

RVIZ=true
if [ "${1:-}" = "norviz" ] || [ "${1:-}" = "--norviz" ]; then
    RVIZ=false
fi

echo "启动头顶 MID360(192.168.123.20) + FAST-LIO2，rviz=$RVIZ"
echo "Livox runtime config: $LIVOX_CONFIG_PATH"
echo "结束时按一次 Ctrl-C；FAST-LIO2 将保存 $PCD_FILE"

ros2 launch go2_loc_bringup mapping.launch.py \
    rviz:="$RVIZ" \
    livox_config:="$LIVOX_CONFIG_PATH"
