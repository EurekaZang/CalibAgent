#!/bin/bash
# 量当前定位输出(/Odometry)的 roll/pitch/yaw, 判断实时点云是否相对水平地图倾斜。
# 用法: 在已启动 run_reloc_only.sh / run_localization.sh 的情况下, 另开终端执行:
#   cd /home/unitree/ws_localization && ./check_live_tilt.sh
#
# 读数含义(map 系, 重力对齐后):
#   roll/pitch 应接近 0(±2° 内正常, 狗站平地时)。
#   若 roll 或 pitch 持续 >5°, 说明实时定位姿态相对水平地图倾斜 -> 需进一步排查。
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/setup_env.sh" >/dev/null 2>&1

echo "采集 /Odometry (最多等 15s)..."
QUAT="$(timeout 15 ros2 topic echo /Odometry --field pose.pose.orientation --once 2>/dev/null)"

if [ -z "$QUAT" ]; then
    echo "未收到 /Odometry。检查: 1) reloc/loc 是否在跑  2) ros2 topic hz /livox/lidar 有无数据"
    exit 1
fi

echo "$QUAT" | python3 -c "
import sys, math, re
t = sys.stdin.read()
def g(k):
    m = re.search(k + r':\s*([-\d.eE+]+)', t)
    return float(m.group(1)) if m else 0.0
x, y, z, w = g('x'), g('y'), g('z'), g('w')
# quaternion -> RPY (ZYX)
roll  = math.degrees(math.atan2(2*(w*x + y*z), 1 - 2*(x*x + y*y)))
sinp  = 2*(w*y - z*x)
pitch = math.degrees(math.asin(max(-1, min(1, sinp))))
yaw   = math.degrees(math.atan2(2*(w*z + x*y), 1 - 2*(y*y + z*z)))
print(f'  四元数: x={x:.4f} y={y:.4f} z={z:.4f} w={w:.4f}')
print(f'  roll  = {roll:+.2f} deg')
print(f'  pitch = {pitch:+.2f} deg')
print(f'  yaw   = {yaw:+.2f} deg')
tilt = math.degrees(math.acos(max(-1, min(1, math.cos(math.radians(roll))*math.cos(math.radians(pitch))))))
print(f'  >>> 相对水平的总倾角 = {tilt:.2f} deg')
if tilt > 5:
    print('  [警告] 实时定位姿态明显倾斜, 与水平地图不一致, 需排查。')
else:
    print('  [正常] 实时姿态基本水平, 截图里的斜大概率是 RViz 视角/真实斜面。')
"
