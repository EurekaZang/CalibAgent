#!/usr/bin/env bash
set -euo pipefail

BASE_CONFIG="${LIVOX_BASE_CONFIG:-/home/unitree/project/ros2_ws/install/livox_ros_driver2/share/livox_ros_driver2/config/MID360_config.json}"
IFACE="${GO2_DDS_IFACE:-}"

if [ -z "$IFACE" ]; then
    IFACE="$(ip -4 -o addr show | awk '$4 ~ /^192\.168\.123\./ {print $2; exit}')"
fi
if [ -z "$IFACE" ]; then
    echo "找不到 192.168.123.x 的 MID360 网口" >&2
    exit 1
fi

HOST_IP="$(ip -4 -o addr show dev "$IFACE" | awk '$4 ~ /^192\.168\.123\./ {sub(/\/.*/, "", $4); print $4; exit}')"
if [ -z "$HOST_IP" ]; then
    echo "网口 $IFACE 没有 192.168.123.x 地址" >&2
    exit 1
fi
if [ ! -f "$BASE_CONFIG" ]; then
    echo "MID360 基础配置不存在: $BASE_CONFIG" >&2
    exit 1
fi

OUT="${LIVOX_RUNTIME_CONFIG:-/tmp/go2_mid360_${HOST_IP//./_}.json}"
python3 - "$BASE_CONFIG" "$OUT" "$HOST_IP" <<'PY'
import json
import os
import sys
import tempfile

source, output, host_ip = sys.argv[1:]
with open(source, "r", encoding="utf-8") as handle:
    config = json.load(handle)

host = config["MID360"]["host_net_info"]
for key in ("cmd_data_ip", "push_msg_ip", "point_data_ip", "imu_data_ip", "log_data_ip"):
    host[key] = host_ip

lidars = config.get("lidar_configs", [])
if len(lidars) != 1 or lidars[0].get("ip") != "192.168.123.20":
    raise SystemExit("配置不是唯一的头顶 MID360 192.168.123.20")

directory = os.path.dirname(output) or "."
os.makedirs(directory, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=".mid360-", suffix=".json", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY

echo "MID360 runtime config: lidar=192.168.123.20 host=$HOST_IP iface=$IFACE" >&2
echo "$OUT"
