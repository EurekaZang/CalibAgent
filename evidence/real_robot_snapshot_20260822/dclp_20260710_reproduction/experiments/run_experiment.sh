#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROFILE_DIR="${SCRIPT_DIR}/profiles"
LAUNCHER="${ROOT}/dclp_deploy/robots/unitree_go2/start_dclp_nav.sh"

usage() {
  cat <<'EOF'
Usage:
  run_experiment.sh PROFILE RIGHT_M FORWARD_M --scene ID [options]

Safe default is dry-run. Options:
  --dry-run                 policy and logging only; no SportClient.Move
  --zero-motion             initialize SportClient but force every Move to zero
  --live --armed            enable real motion (both flags required)
  --allow-high-risk         additionally unlock a high-risk live profile
  --allow-extreme-historical additionally unlock an extreme historical profile
  --scene ID                fixed scene ID, e.g. S0, S1, S2L, S2R
  --scene-file PATH         measured scene YAML to snapshot with the run
  --repeat N                repeat number within the scene/profile block
  --operator NAME           operator identifier
EOF
}

[[ $# -ge 3 ]] || { usage; exit 2; }
PROFILE_NAME="$1"; RIGHT_M="$2"; FORWARD_M="$3"; shift 3
[[ "${PROFILE_NAME}" =~ ^[a-z0-9_]+$ ]] || { echo "invalid profile name" >&2; exit 2; }
[[ "${RIGHT_M}" =~ ^-?[0-9]+([.][0-9]+)?$ && "${FORWARD_M}" =~ ^-?[0-9]+([.][0-9]+)?$ ]] \
  || { echo "RIGHT_M and FORWARD_M must be numbers" >&2; exit 2; }

MODE="dry-run"
ARMED=0
ALLOW_HIGH=0
ALLOW_EXTREME=0
SCENE_ID=""
SCENE_FILE=""
REPEAT_ID="1"
OPERATOR_ID="${USER:-unknown}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) MODE="dry-run"; shift ;;
    --zero-motion) MODE="zero-motion"; shift ;;
    --live) MODE="live"; shift ;;
    --armed) ARMED=1; shift ;;
    --allow-high-risk) ALLOW_HIGH=1; shift ;;
    --allow-extreme-historical) ALLOW_EXTREME=1; shift ;;
    --scene) SCENE_ID="$2"; shift 2 ;;
    --scene-file) SCENE_FILE="$2"; shift 2 ;;
    --repeat) REPEAT_ID="$2"; shift 2 ;;
    --operator) OPERATOR_ID="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

[[ "${SCENE_ID}" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "--scene ID is required" >&2; exit 2; }
[[ "${REPEAT_ID}" =~ ^[0-9]+$ ]] || { echo "--repeat must be a positive integer" >&2; exit 2; }
if [[ -n "${SCENE_FILE}" ]]; then
  SCENE_FILE="$(realpath "${SCENE_FILE}")"
  [[ -f "${SCENE_FILE}" ]] || { echo "scene file not found: ${SCENE_FILE}" >&2; exit 2; }
elif [[ "${MODE}" == "live" ]]; then
  echo "WARNING: live run has no --scene-file; physical-layout reproducibility will be incomplete" >&2
fi

PROFILE_FILE="${PROFILE_DIR}/${PROFILE_NAME}.env"
[[ -f "${PROFILE_FILE}" ]] || { echo "profile not found: ${PROFILE_FILE}" >&2; exit 2; }
source "${PROFILE_FILE}"
[[ "${PROFILE_ID:-}" == "${PROFILE_NAME}" ]] \
  || { echo "profile ID mismatch: file=${PROFILE_NAME} content=${PROFILE_ID:-unset}" >&2; exit 2; }

if [[ "${MODE}" == "live" ]]; then
  [[ "${ARMED}" == "1" ]] || { echo "live motion requires --armed" >&2; exit 2; }
  case "${PROFILE_RISK}" in
    extreme)
      [[ "${ALLOW_EXTREME}" == "1" ]] \
        || { echo "extreme historical profile requires --allow-extreme-historical" >&2; exit 2; }
      ;;
    high)
      [[ "${ALLOW_HIGH}" == "1" ]] \
        || { echo "high-risk profile requires --allow-high-risk" >&2; exit 2; }
      ;;
  esac
fi

export MODEL_PATH="${ROOT}/models/dclp/V1_41lambda1_101.pth"
export CYCLONEDDS_CONFIG="${ROOT}/dclp_deploy/robots/unitree_go2/cyclonedds_go2_eth0.xml"
export POLICY_EXPERIMENT_PROFILE="${PROFILE_ID}"

STAMP="$(date +%Y%m%d_%H%M%S_%N)"
RUN_ID="${STAMP}_${SCENE_ID}_r${REPEAT_ID}_${PROFILE_ID}_${MODE}"
RUN_DIR="${ROOT}/runs/${RUN_ID}"
mkdir -p "${RUN_DIR}/component_logs" "${RUN_DIR}/trajectory" "${RUN_DIR}/ros_logs"
export POLICY_EXPERIMENT_ID="${RUN_ID}"
export POLICY_EFFECTIVE_CONFIG_PATH="${RUN_DIR}/policy_effective_config.json"
export POLICY_TRAJECTORY_LOG_DIR="${RUN_DIR}/trajectory"
export POLICY_TRAJECTORY_LOG_BASENAME="trajectory.csv"
export DCLP_COMPONENT_LOG_DIR="${RUN_DIR}/component_logs"
export ROS_LOG_DIR="${RUN_DIR}/ros_logs"
export ROSBAG_OUTPUT_DIR="${RUN_DIR}/rosbag"

cp "${PROFILE_FILE}" "${RUN_DIR}/profile_requested.env"
cp "${PROFILE_DIR}/_profile_lib.sh" "${RUN_DIR}/profile_lib_snapshot.sh"
if [[ -n "${SCENE_FILE}" ]]; then
  cp "${SCENE_FILE}" "${RUN_DIR}/scene_measurement.yaml"
fi

{
  printf 'run_id=%q\n' "${RUN_ID}"
  printf 'started_at=%q\n' "$(date --iso-8601=seconds)"
  printf 'profile=%q\n' "${PROFILE_ID}"
  printf 'description=%q\n' "${PROFILE_DESCRIPTION}"
  printf 'risk=%q\n' "${PROFILE_RISK}"
  printf 'mode=%q\n' "${MODE}"
  printf 'scene=%q\n' "${SCENE_ID}"
  printf 'scene_file=%q\n' "${SCENE_FILE:-unrecorded}"
  printf 'repeat=%q\n' "${REPEAT_ID}"
  printf 'operator=%q\n' "${OPERATOR_ID}"
  printf 'goal_right_m=%q\n' "${RIGHT_M}"
  printf 'goal_forward_m=%q\n' "${FORWARD_M}"
  printf 'host=%q\n' "$(hostname)"
  printf 'model_sha256=%q\n' "$(sha256sum "${MODEL_PATH}" | awk '{print $1}')"
  printf 'policy_sha256=%q\n' "$(sha256sum "${ROOT}/dclp_deploy/robots/unitree_go2/dclp_go2_policy_ros2.py" | awk '{print $1}')"
  printf 'deploy_core_sha256=%q\n' "$(sha256sum "${ROOT}/dclp_deploy/dclp_deploy_core.py" | awk '{print $1}')"
  printf 'velocity_compensation_sha256=%q\n' "$(sha256sum "${ROOT}/dclp_deploy/robots/unitree_go2/velocity_compensation.py" | awk '{print $1}')"
  printf 'launcher_sha256=%q\n' "$(sha256sum "${LAUNCHER}" | awk '{print $1}')"
  printf 'profile_sha256=%q\n' "$(sha256sum "${PROFILE_FILE}" | awk '{print $1}')"
  printf 'profile_lib_sha256=%q\n' "$(sha256sum "${PROFILE_DIR}/_profile_lib.sh" | awk '{print $1}')"
  if [[ -n "${SCENE_FILE}" ]]; then
    printf 'scene_file_sha256=%q\n' "$(sha256sum "${SCENE_FILE}" | awk '{print $1}')"
  fi
} >"${RUN_DIR}/run_manifest.env"

env | LC_ALL=C sort | grep -E '^(COMPENSATE|DCLP_|GO2_|MIN_HEIGHT|MAX_HEIGHT|RANGE_|MODEL_PATH|POLICY_|RECORD_ROSBAG|ROSBAG_|GOAL_TIMEOUT_SEC)=' \
  >"${RUN_DIR}/requested_effective_environment.txt"

cp "${SCRIPT_DIR}/operator_outcome_template.env" "${RUN_DIR}/operator_outcome.env"

STOPPED=0
stop_stack() {
  if [[ "${STOPPED}" == "0" ]]; then
    STOPPED=1
    DCLP_COMPONENT_LOG_DIR="${DCLP_COMPONENT_LOG_DIR}" bash "${LAUNCHER}" --stop || true
  fi
}
handle_runner_interrupt() {
  trap - INT TERM
  stop_stack
  {
    printf 'exit_code=130\n'
    printf 'finished_at=%q\n' "$(date --iso-8601=seconds)"
    printf 'mode=%q\n' "${MODE}"
    printf 'automatic_reached_claim=no\n'
    printf 'interrupted=yes\n'
  } >"${RUN_DIR}/run_result.env"
  exit 130
}
trap handle_runner_interrupt INT TERM

if [[ "${MODE}" == "live" ]]; then
  bash "${SCRIPT_DIR}/preflight.sh" --live
else
  bash "${SCRIPT_DIR}/preflight.sh"
fi

launch_mode=()
[[ "${MODE}" == "dry-run" ]] && launch_mode+=(--dry-run)
[[ "${MODE}" == "zero-motion" ]] && launch_mode+=(--zero-motion)

printf 'Run directory: %s\n' "${RUN_DIR}"
printf 'Profile: %s (%s), mode=%s, scene=%s, repeat=%s\n' \
  "${PROFILE_ID}" "${PROFILE_RISK}" "${MODE}" "${SCENE_ID}" "${REPEAT_ID}"

set +e
bash "${LAUNCHER}" "${launch_mode[@]}" "${RIGHT_M}" "${FORWARD_M}" \
  2>&1 | tee "${RUN_DIR}/orchestrator.log"
result=${PIPESTATUS[0]}
set -e

stop_stack
trap - INT TERM
{
  printf 'exit_code=%s\n' "${result}"
  printf 'finished_at=%q\n' "$(date --iso-8601=seconds)"
  printf 'mode=%q\n' "${MODE}"
  printf 'automatic_reached_claim=%q\n' "$(if [[ "${MODE}" == "live" && "${result}" == "0" ]]; then echo yes; else echo no; fi)"
} >"${RUN_DIR}/run_result.env"

printf '\nSaved: %s\n' "${RUN_DIR}"
printf 'Now edit operator_outcome.env: contact/manual_stop/timeout/video/notes.\n'
exit "${result}"
