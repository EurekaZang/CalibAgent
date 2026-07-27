#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
ROBOT_WORKSPACE="${CALIBAGENT_ROBOT_WORKSPACE:-/home/unitree/ws_fastlio}"
source "${ROBOT_WORKSPACE}/setup_nav_env.sh"

SESSION="${1:-go2-session-01}"
MODE="${2:-append}"   # fresh 或 append
OUT="${CALIBAGENT_P1_OUTPUT:-${REPOSITORY_ROOT}/outputs/p1_go2_real_delivery}"

if [ "$MODE" = "fresh" ]; then
  WRITE_FLAG="--overwrite"
elif [ "$MODE" = "append" ]; then
  WRITE_FLAG="--append"
else
  echo "用法: bash run_p1_20hz_session.sh go2-session-01 fresh|append"
  exit 1
fi

echo "准备采集 ${SESSION}，输出: ${OUT}"
echo "注意: 这是 20Hz 全流程采集，不是严格 50Hz P1 audit 合规数据。"
read -r -p "确认 localization READY、cmd_vel_bridge 运行、场地安全。输入 y 开始: " ans
ans="$(printf '%s' "$ans" | tr -d '[:space:]')"
case "$ans" in
  y|Y|yes|YES) ;;
  *) echo "取消。"; exit 1 ;;
esac

python3 "${SCRIPT_DIR}/go2_plan_capture_runner.py" \
  --preflight-only \
  --min-odom-hz 18 \
  --max-odom-hz 25 \
  --min-samples 35

python3 "${SCRIPT_DIR}/go2_plan_capture_runner.py" \
  --arm \
  --session-id "$SESSION" \
  --output-dir "$OUT" \
  $WRITE_FLAG \
  --terrain-id lab_flat \
  --payload-kg 0.0 \
  --battery-ratio 0.90 \
  --gait-id trot \
  --return-home every-trial \
  --max-radius-m 3.0 \
  --hard-radius-m 3.5 \
  --home-xy-tolerance-m 0.45 \
  --home-yaw-tolerance-rad 0.80 \
  --return-timeout-s 8 \
  --home-settle-s 0.2 \
  --min-odom-hz 18 \
  --max-odom-hz 25 \
  --min-samples 35
