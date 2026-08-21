#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
exec bash "${ROOT}/dclp_deploy/robots/unitree_go2/start_dclp_nav.sh" --status
