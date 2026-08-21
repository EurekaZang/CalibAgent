#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${P8_PYTHON:-/usr/bin/python3}"
source /home/unitree/ws_localization/setup_env.sh
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export P8_OUTPUT_ROOT="${P8_OUTPUT_ROOT:-/home/unitree/lly/p8_real}"

usage() {
  echo "Usage: $0 {validate-nav|validate-shift|io-check|nav|shift|resume-nav|resume-shift|export|analyze|collision|clear-collision|fake-smoke} ..."
}

ensure_p8_stack() {
  local stack_session="calibagent_p8_stack"
  local loc_session="calibagent_p8_localization"
  if tmux has-session -t "${stack_session}" 2>/dev/null \
      && ! tmux list-panes -s -t "${stack_session}" -F '#{pane_dead}' | grep -qx '1'; then
    if "${ROOT}/scripts/p8_stack.sh" verify; then
      return 0
    fi
    echo "P8 stack exists but failed freshness checks; restarting the complete input stack." >&2
  else
    echo "P8 input stack is not running; starting it automatically." >&2
  fi

  # No experiment runner exists yet: this preflight runs before the Python
  # process is exec'd, so replacing stale input services cannot interrupt a trial.
  tmux kill-session -t "${stack_session}" 2>/dev/null || true
  tmux kill-session -t "${loc_session}" 2>/dev/null || true
  "${ROOT}/scripts/p8_stack.sh" start
}

cmd="${1:-}"; shift || true
case "${cmd}" in
  validate-nav) exec "${PYTHON_BIN}" -m calibagent.cli.p8_real validate --config "${ROOT}/configs/p8/nav.yaml" "$@" ;;
  validate-shift) exec "${PYTHON_BIN}" -m calibagent.cli.p8_real validate --config "${ROOT}/configs/p8/shift.yaml" "$@" ;;
  io-check) ensure_p8_stack; exec "${PYTHON_BIN}" -m calibagent.cli.p8_real io-check --config "${ROOT}/configs/p8/nav.yaml" --output-root "${P8_OUTPUT_ROOT}" "$@" ;;
  nav) run_id="${1:?run-id required}"; shift; ensure_p8_stack; exec "${PYTHON_BIN}" -m calibagent.cli.p8_real nav --config "${ROOT}/configs/p8/nav.yaml" --run-id "${run_id}" --output-root "${P8_OUTPUT_ROOT}" --backend ros --arm "$@" ;;
  shift) run_id="${1:?run-id required}"; shift; ensure_p8_stack; exec "${PYTHON_BIN}" -m calibagent.cli.p8_real shift --config "${ROOT}/configs/p8/shift.yaml" --run-id "${run_id}" --output-root "${P8_OUTPUT_ROOT}" --backend ros --arm "$@" ;;
  resume-nav) run_id="${1:?run-id required}"; shift; ensure_p8_stack; exec "${PYTHON_BIN}" -m calibagent.cli.p8_real nav --config "${ROOT}/configs/p8/nav.yaml" --run-id "${run_id}" --output-root "${P8_OUTPUT_ROOT}" --backend ros --arm --resume "$@" ;;
  resume-shift) run_id="${1:?run-id required}"; shift; ensure_p8_stack; exec "${PYTHON_BIN}" -m calibagent.cli.p8_real shift --config "${ROOT}/configs/p8/shift.yaml" --run-id "${run_id}" --output-root "${P8_OUTPUT_ROOT}" --backend ros --arm --resume "$@" ;;
  export) exec "${PYTHON_BIN}" -m calibagent.cli.p8_real export --run-dir "${1:?run-dir required}" ;;
  analyze) exec "${PYTHON_BIN}" -m calibagent.cli.p8_real analyze --run-dir "${1:?run-dir required}" ;;
  collision) exec ros2 topic pub --once /p8/collision std_msgs/msg/Bool '{data: true}' ;;
  clear-collision) exec ros2 topic pub --once /p8/collision std_msgs/msg/Bool '{data: false}' ;;
  fake-smoke) exec "${PYTHON_BIN}" -m calibagent.cli.p8_real nav --config "${ROOT}/configs/p8/nav.yaml" --run-id "fake_smoke_$(date +%Y%m%dT%H%M%S)" --output-root /tmp/calibagent_p8_smoke --backend fake --max-units 4 --blocks NAV_BLOCK_01 --methods B8_full ;;
  *) usage; exit 2 ;;
esac
