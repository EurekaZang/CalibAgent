#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSION="go2_mapping"
LOG_FILE="$SCRIPT_DIR/mapping_control.log"

usage() {
    echo "Usage: $0 {start [MAP_NAME]|status|save|stop|log|attach}"
}

is_running() {
    tmux has-session -t "$SESSION" 2>/dev/null \
        && [ "$(tmux display-message -p -t "$SESSION" '#{pane_dead}')" = "0" ]
}

case "${1:-}" in
    start)
        MAP_NAME="${2:-scans}"
        if [[ ! "$MAP_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
            echo "非法地图名: $MAP_NAME" >&2
            exit 2
        fi
        if is_running; then
            echo "建图会话已在运行: $SESSION" >&2
            exit 1
        fi
        tmux kill-session -t "$SESSION" 2>/dev/null || true
        : > "$LOG_FILE"
        tmux new-session -d -s "$SESSION" \
            "cd '$SCRIPT_DIR' && exec ./run_mapping_onekey.sh norviz --map-name='$MAP_NAME'"
        tmux set-option -t "$SESSION" remain-on-exit on
        tmux pipe-pane -t "$SESSION" -o "cat >> '$LOG_FILE'"
        sleep 2
        if ! is_running; then
            echo "建图启动失败；最近输出：" >&2
            tail -n 80 "$LOG_FILE" >&2 || true
            tmux capture-pane -pt "$SESSION" -S -80 2>/dev/null >&2 || true
            exit 1
        fi
        echo "建图已启动: session=$SESSION map=$MAP_NAME"
        echo "查看实时输出: $0 attach"
        ;;
    status)
        if is_running; then
            echo "RUNNING session=$SESSION"
            tmux list-panes -t "$SESSION" -F 'pid=#{pane_pid} dead=#{pane_dead} command=#{pane_current_command}'
        elif tmux has-session -t "$SESSION" 2>/dev/null; then
            echo "STOPPED session=$SESSION"
            tmux list-panes -t "$SESSION" -F 'pid=#{pane_pid} dead=#{pane_dead} exit=#{pane_dead_status}'
        else
            echo "STOPPED session=$SESSION"
        fi
        pgrep -af 'fastlio_mapping|livox_ros_driver2_node' || true
        stat -c 'map=%n size=%s mtime=%y' "$SCRIPT_DIR/src/FAST_LIO/PCD/scans.pcd" 2>/dev/null || true
        ;;
    save|stop)
        if ! is_running; then
            echo "建图会话没有运行" >&2
            exit 1
        fi
        tmux send-keys -t "$SESSION" C-c
        echo "已发送 Ctrl-C；FAST-LIO2 正在保存 PCD，随后一键脚本会生成重定位库和 2D 地图。"
        echo "用 '$0 log' 查看进度，用 '$0 status' 确认结束。"
        ;;
    log)
        if [ -f "$LOG_FILE" ]; then
            tail -n 160 "$LOG_FILE"
        elif tmux has-session -t "$SESSION" 2>/dev/null; then
            tmux capture-pane -pt "$SESSION" -S -120
        else
            echo "没有建图日志。"
        fi
        ;;
    attach)
        exec tmux attach-session -t "$SESSION"
        ;;
    *)
        usage
        exit 2
        ;;
esac
