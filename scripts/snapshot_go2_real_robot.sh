#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAPSHOT_ROOT="${REPO_ROOT}/evidence/real_robot_snapshot_20260822"
P8_ROOT="/home/unitree/lly/p8_real"
DCLP_ROOT="/home/unitree/qyw/dclp_20260710_reproduction"
LOCALIZATION_ROOT="/home/unitree/ws_localization"
ROS2_ROOT="/home/unitree/project/ros2_ws"

for source_path in "${P8_ROOT}" "${DCLP_ROOT}" "${LOCALIZATION_ROOT}" "${ROS2_ROOT}"; do
  if [[ ! -d "${source_path}" ]]; then
    echo "required real-robot source is missing: ${source_path}" >&2
    exit 1
  fi
done
if [[ -e "${SNAPSHOT_ROOT}" ]]; then
  echo "refusing to overwrite existing snapshot: ${SNAPSHOT_ROOT}" >&2
  exit 1
fi
command -v rsync >/dev/null

mkdir -p "${SNAPSHOT_ROOT}"

# All P8 runner outputs, including official runs, health checks, smoke runs,
# bags, traces, posteriors, frozen configs, manifests, and stack logs.
rsync -a "${P8_ROOT}/" "${SNAPSHOT_ROOT}/p8_real/"

# The complete DCLP reproduction/deployment tree contains the earlier real Go2
# runs, MID360 evidence, deployment source, model, and raw bags.
rsync -a \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache/' \
  "${DCLP_ROOT}/" "${SNAPSHOT_ROOT}/dclp_20260710_reproduction/"

# Preserve localization source and operator scripts, but not derived build,
# install, or compiler logs. Historical map backups are intentionally omitted;
# the exact active P8 map and relocation database are copied below.
mkdir -p "${SNAPSHOT_ROOT}/localization_workspace/root_files"
find "${LOCALIZATION_ROOT}" -maxdepth 1 -type f -exec \
  cp -a -t "${SNAPSHOT_ROOT}/localization_workspace/root_files" -- {} +
rsync -a \
  --exclude='FAST_LIO/PCD/' \
  --exclude='FAST_LIO/Log/' \
  --exclude='.git' \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  "${LOCALIZATION_ROOT}/src/" "${SNAPSHOT_ROOT}/localization_workspace/src/"
rsync -a \
  --exclude='.git' \
  --exclude='.git/' \
  --exclude='build/' \
  "${LOCALIZATION_ROOT}/third_party/" \
  "${SNAPSHOT_ROOT}/localization_workspace/third_party/"
mkdir -p "${SNAPSHOT_ROOT}/localization_workspace/src/FAST_LIO/PCD"
cp -a "${LOCALIZATION_ROOT}/src/FAST_LIO/PCD/scans.pcd" \
  "${SNAPSHOT_ROOT}/localization_workspace/src/FAST_LIO/PCD/scans.pcd"
rsync -a "${LOCALIZATION_ROOT}/src/FAST_LIO/PCD/reloc_db/" \
  "${SNAPSHOT_ROOT}/localization_workspace/src/FAST_LIO/PCD/reloc_db/"

# Source snapshots for the Livox driver and pointcloud conversion packages.
mkdir -p "${SNAPSHOT_ROOT}/ros2_workspace/src"
rsync -a \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  "${ROS2_ROOT}/src/" "${SNAPSHOT_ROOT}/ros2_workspace/src/"

cp "${REPO_ROOT}/docs/real_robot_snapshot_20260822.md" \
  "${SNAPSHOT_ROOT}/README.md"

python3 - "${SNAPSHOT_ROOT}" "${REPO_ROOT}" <<'PY'
import json
import subprocess
import sys
import time
from pathlib import Path

snapshot = Path(sys.argv[1])
repo = Path(sys.argv[2])
files = [path for path in snapshot.rglob("*") if path.is_file()]
metadata = {
    "schema": "calibagent.real_robot_snapshot.v1",
    "snapshot_created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "calibagent_commit": subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip(),
    "source_roots": {
        "p8_real": "/home/unitree/lly/p8_real",
        "dclp": "/home/unitree/qyw/dclp_20260710_reproduction",
        "localization": "/home/unitree/ws_localization",
        "ros2": "/home/unitree/project/ros2_ws/src",
    },
    "file_count_before_integrity_manifest": len(files),
    "bytes_before_integrity_manifest": sum(path.stat().st_size for path in files),
    "livox_ros_driver2_commit": "6b9356cadf77084619ba406e6a0eb41163b08039",
    "pointcloud_to_laserscan_commit": "58d5b0659dc1f7db1b8745d1363b6163397797b8",
    "active_map": "localization_workspace/src/FAST_LIO/PCD/scans.pcd",
    "active_relocation_database": (
        "localization_workspace/src/FAST_LIO/PCD/reloc_db"
    ),
}
(snapshot / "SNAPSHOT_METADATA.json").write_text(
    json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

(
  cd "${SNAPSHOT_ROOT}"
  find . -type f ! -name SNAPSHOT_MANIFEST.sha256 -print0 \
    | sort -z \
    | xargs -0 sha256sum > SNAPSHOT_MANIFEST.sha256
)

echo "snapshot=${SNAPSHOT_ROOT}"
du -sh "${SNAPSHOT_ROOT}"
find "${SNAPSHOT_ROOT}" -type f | wc -l
