#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIVE_CHECK=0
[[ "${1:-}" == "--live" ]] && LIVE_CHECK=1

failures=0
warnings=0
ok() { printf '[OK]   %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; warnings=$((warnings + 1)); }
fail() { printf '[FAIL] %s\n' "$*"; failures=$((failures + 1)); }

check_file() {
  local path="$1" label="$2"
  [[ -f "${path}" ]] && ok "${label}: ${path}" || fail "${label} missing: ${path}"
}

MODEL="${ROOT}/models/dclp/V1_41lambda1_101.pth"
POLICY="${ROOT}/dclp_deploy/robots/unitree_go2/dclp_go2_policy_ros2.py"
LAUNCHER="${ROOT}/dclp_deploy/robots/unitree_go2/start_dclp_nav.sh"
EXPECTED_MODEL_SHA="dacaf9fc45da536ae6b45cdbedc949370b7828fac4cadcf40ebedabc4080c452"

check_file "${MODEL}" "DCLP model101"
check_file "${POLICY}" "instrumented policy"
check_file "${LAUNCHER}" "experiment launcher"
check_file "/opt/ros/foxy/setup.bash" "ROS2 Foxy"
check_file "/home/unitree/project/ros2_ws/install/setup.bash" "local ROS2 workspace"
check_file "/home/unitree/unitree_ros2/setup.sh" "Unitree ROS2 messages"
check_file "/home/unitree/project/ros2_ws/install/livox_ros_driver2/share/livox_ros_driver2/config/MID360_config.json" "MID360 config"
check_file "${ROOT}/dclp_deploy/robots/unitree_go2/cyclonedds_go2_eth0.xml" "CycloneDDS config"

if [[ -f "${MODEL}" ]]; then
  actual_model_sha="$(sha256sum "${MODEL}" | awk '{print $1}')"
  [[ "${actual_model_sha}" == "${EXPECTED_MODEL_SHA}" ]] \
    && ok "model SHA256=${actual_model_sha}" \
    || fail "model SHA mismatch: ${actual_model_sha}"
fi

declare -A provenance_hashes=(
  ["provenance/historical_snapshots/launcher/start_dclp_nav_final_041531.sh"]="17c934f00f16cd7f4f4090cc263064ea2b9c67c41a7347db055b6304d24a5075"
  ["provenance/historical_snapshots/policy/dclp_go2_policy_ros2_v3.py"]="215175cd7f7a7c960d637802aff528a38407b0ab0a7875a256e6c8239d5b7b7d"
  ["provenance/historical_snapshots/policy/dclp_go2_policy_ros2_v4.py"]="f6768172ee30d71192f8cd1392967d993e6b065216c2866ef04ff12c93a750bb"
  ["provenance/historical_snapshots/core/dclp_deploy_core_v3.py"]="df6c78b263454c8bf8fb616de9dff7d268f6f48fe40127c299dd56455464e7de"
)
for relative in "${!provenance_hashes[@]}"; do
  path="${ROOT}/${relative}"
  if [[ ! -f "${path}" ]]; then
    fail "provenance missing: ${relative}"
    continue
  fi
  actual="$(sha256sum "${path}" | awk '{print $1}')"
  [[ "${actual}" == "${provenance_hashes[${relative}]}" ]] \
    && ok "provenance verified: ${relative}" \
    || fail "provenance changed: ${relative}"
done

if ! bash -n "${LAUNCHER}"; then
  fail "launcher shell syntax"
else
  ok "launcher shell syntax"
fi
python_syntax_ok=1
for source_file in \
  "${POLICY}" \
  "${ROOT}/dclp_deploy/dclp_deploy_core.py" \
  "${ROOT}/dclp_deploy/dclp_policy_backend.py"; do
  python3 -c 'import pathlib,sys; compile(pathlib.Path(sys.argv[1]).read_text(), sys.argv[1], "exec")' "${source_file}" \
    || python_syntax_ok=0
done
[[ "${python_syntax_ok}" == "1" ]] && ok "Python syntax" || fail "Python syntax"

POLICY_PYTHON="/home/unitree/miniconda3/envs/go2/bin/python"
if [[ ! -x "${POLICY_PYTHON}" ]]; then
  fail "policy Python missing: ${POLICY_PYTHON}"
else
  set +u
  source /opt/ros/foxy/setup.bash
  source /home/unitree/project/ros2_ws/install/setup.bash
  set -u
  if PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 "${POLICY_PYTHON}" -c 'import numpy, rclpy, tf2_ros, torch, zmq; print("imports OK")'; then
    ok "policy Python imports"
  else
    fail "policy Python imports"
  fi
  if PYTHONDONTWRITEBYTECODE=1 "${POLICY_PYTHON}" -c 'import unitree_sdk2py; print(unitree_sdk2py.__file__)'; then
    sdk_path="$(PYTHONDONTWRITEBYTECODE=1 "${POLICY_PYTHON}" -c 'import unitree_sdk2py; print(unitree_sdk2py.__file__)')"
    ok "unitree_sdk2py import: ${sdk_path}"
    [[ "${sdk_path}" == /home/unitree/workspace/unitree_sdk2_python2/* ]] \
      && warn "unitree_sdk2py is an editable external dependency; keep that source tree unchanged" \
      || true
  else
    fail "unitree_sdk2py import"
  fi
fi

command -v ros2 >/dev/null 2>&1 && ok "ros2 CLI available" || fail "ros2 CLI unavailable"
if command -v ros2 >/dev/null 2>&1 && ros2 bag --help >/dev/null 2>&1; then
  ok "rosbag2 CLI available"
else
  fail "rosbag2 CLI unavailable"
fi

if pgrep -af 'dclp_go2_policy_ros2.py|go2_zmq_sport_client.py|start_dclp_nav.sh' >/tmp/dclp_repro_preflight_processes.txt 2>/dev/null; then
  if [[ "${LIVE_CHECK}" == "1" ]]; then
    fail "a DCLP/Go2 control process is already running; inspect /tmp/dclp_repro_preflight_processes.txt and stop it before a live trial"
  else
    warn "a DCLP/Go2 control process is already running; inspect /tmp/dclp_repro_preflight_processes.txt and stop it before a trial"
  fi
else
  ok "no existing DCLP/Go2 controller detected"
fi

if [[ "${LIVE_CHECK}" == "1" ]]; then
  # Avoid a false negative under `set -o pipefail`: `grep -q` may exit after
  # the first match, causing `ip` to receive SIGPIPE and the pipeline to fail.
  eth0_ipv4="$(ip -4 addr show dev eth0 2>/dev/null || true)"
  if grep -q 'inet 192\.168\.123\.222/24' <<<"${eth0_ipv4}"; then
    ok "eth0 is 192.168.123.222/24"
  else
    fail "eth0 must be 192.168.123.222/24 for this captured deployment"
  fi
  listening_tcp="$(ss -ltn 2>/dev/null || true)"
  if grep -q ':5596[[:space:]]' <<<"${listening_tcp}"; then
    fail "TCP 5596 is already in use"
  else
    ok "TCP 5596 is free"
  fi
fi

printf '\nPreflight summary: failures=%d warnings=%d mode=%s\n' \
  "${failures}" "${warnings}" "$(if [[ "${LIVE_CHECK}" == "1" ]]; then echo live; else echo static; fi)"
[[ "${failures}" -eq 0 ]]
