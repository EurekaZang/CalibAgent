#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${REPOSITORY_ROOT}"

REMOTE_CHECK=true
if [[ "${1:-}" == "--local-only" ]]; then
  REMOTE_CHECK=false
elif [[ -n "${1:-}" ]]; then
  echo "usage: $0 [--local-only]" >&2
  exit 2
fi

required_paths=(
  "README.md"
  "README_zh-CN.md"
  "src/calibagent/interfaces/types.py"
  "src/calibagent/interfaces/protocols.py"
  "src/calibagent/backends/go2_ros.py"
  "src/calibagent/core/models/bayesian.py"
  "src/calibagent/core/planning/ivr.py"
  "src/calibagent/core/safety/filter.py"
  "src/calibagent/core/shift/detector.py"
  "src/calibagent/core/compensation/inverse.py"
  "sim/isaaclab/calibagent_sim/p6_runner.py"
  "sim/isaaclab/calibagent_sim/p7_runner.py"
  "data/calibration_extracted/calibration/go2_plan_capture_runner.py"
  "docs/p8_go2_real_deployment_data_handoff_zh.md"
  "docs/p8_go2_implementation_guide_zh.md"
  "docs/assets/readme/p5_isaac_sim_closeup.png"
  "docs/assets/readme/p5_isaac_sim_overview.png"
  "docs/assets/readme/p5_isaac_sim_capture.json"
  "docs/assets/readme/p7_isaac_sim_overview.png"
  "docs/assets/readme/p7_isaac_sim_robot_view.png"
  "docs/assets/readme/p7_isaac_sim_capture.json"
  "docs/assets/readme/p7_slalom_seed_8006.png"
  "sim/isaaclab/scripts/capture_readme_scene.py"
  "scripts/build_readme_figures.py"
)

for path in "${required_paths[@]}"; do
  if ! git ls-files --error-unmatch "${path}" >/dev/null 2>&1; then
    echo "FAIL: required source is not tracked: ${path}" >&2
    exit 1
  fi
done

status="$(git status --porcelain --untracked-files=all)"
if [[ -n "${status}" ]]; then
  echo "FAIL: worktree is not clean:" >&2
  printf '%s\n' "${status}" >&2
  exit 1
fi

local_head="$(git rev-parse HEAD)"
echo "tracked source gate: PASS"
echo "local HEAD: ${local_head}"

if [[ "${REMOTE_CHECK}" == false ]]; then
  echo "remote synchronization gate: SKIPPED (--local-only)"
  exit 0
fi

origin_url="$(git remote get-url origin)"
if [[ "${origin_url}" != "https://github.com/EurekaZang/CalibAgent.git" ]]; then
  echo "FAIL: unexpected origin URL: ${origin_url}" >&2
  exit 1
fi

remote_head="$(
  git ls-remote --exit-code origin refs/heads/main |
    awk 'NR == 1 {print $1}'
)"
if [[ -z "${remote_head}" ]]; then
  echo "FAIL: origin/main does not exist" >&2
  exit 1
fi
if [[ "${local_head}" != "${remote_head}" ]]; then
  echo "FAIL: local HEAD ${local_head} != origin/main ${remote_head}" >&2
  exit 1
fi

echo "origin: ${origin_url}"
echo "remote synchronization gate: PASS"
