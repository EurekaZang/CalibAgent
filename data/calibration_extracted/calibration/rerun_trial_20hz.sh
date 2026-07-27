#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
ROBOT_WORKSPACE="${CALIBAGENT_ROBOT_WORKSPACE:-/home/unitree/ws_fastlio}"
source "${ROBOT_WORKSPACE}/setup_nav_env.sh"

SESSION="${1:?用法: bash rerun_trial_20hz.sh go2-session-03 25}"
TRIAL="${2:?用法: bash rerun_trial_20hz.sh go2-session-03 25}"
OUT="${CALIBAGENT_P1_OUTPUT:-${REPOSITORY_ROOT}/outputs/p1_go2_real_delivery}"

echo "补跑 ${SESSION} trial ${TRIAL}，结果 append 到总数据集: ${OUT}"
read -r -p "确认 localization READY、cmd_vel_bridge 运行、场地安全。输入 y 开始: " ans
ans="$(printf '%s' "$ans" | tr -d '[:space:]')"
case "$ans" in y|Y|yes|YES) ;; *) echo "取消。"; exit 1 ;; esac

python3 "${SCRIPT_DIR}/go2_plan_capture_runner.py" \
  --arm \
  --session-id "$SESSION" \
  --trials "$TRIAL" \
  --attempt-id 2 \
  --output-dir "$OUT" \
  --append \
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
  --min-odom-hz 18 \
  --max-odom-hz 25 \
  --min-samples 35
