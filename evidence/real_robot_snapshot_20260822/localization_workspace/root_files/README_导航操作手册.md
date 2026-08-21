# Go2 定位 + 导航 操作手册

> 适用工作区: `/home/unitree/ws_localization`
> 两套栈**分进程、分 RViz、仅通过话题解耦通信**: 定位栈负责"我在哪", 导航栈负责"去哪/起终点管理"。

---

## 目录
1. [系统架构 / 数据流](#1-系统架构--数据流)
2. [话题对应表](#2-话题对应表)
3. [TF 坐标系](#3-tf-坐标系)
4. [完整操作流程(命令行)](#4-完整操作流程命令行)
5. [机器狗位姿获取](#5-机器狗位姿获取)
6. [起点 / 终点拾取](#6-起点--终点拾取)
7. [导航目标设定](#7-导航目标设定)
8. [常用查询 / 调试命令](#8-常用查询--调试命令)
9. [停止 / 清理](#9-停止--清理)
10. [常见问题](#10-常见问题)

---

## 1. 系统架构 / 数据流

```
┌──────────────────────── 定位栈 (run_localization.sh) ────────────────────────┐
│                                                                              │
│  Livox MID360 ──/livox/lidar──┐                                              │
│  (20Hz)        ──/livox/imu───┤                                              │
│                               ▼                                              │
│                        ┌─────────────┐   /initialpose(一次性初值)            │
│   global_reloc ────────┤  FAST-LIO   │◄─────────── global_reloc             │
│   (Scan Context+        │ (定位模式)  │   (重定位成功后给一次, 之后只在丢失重发) │
│    BBS3D+GICP)          └──────┬──────┘                                      │
│                                │ /Odometry  (map->base_link, ~20Hz 持续)      │
│                                ├──────────────► (供导航/RViz 直接用)           │
│                                ▼                                              │
│                        ┌──────────────┐  TF: map->odom + odom->base_link     │
│                        │ nav_tf_manager│──────────────► (供规划/控制查 TF)     │
│                        └──────────────┘                                      │
│                                                                              │
│   loc_health_monitor ──/loc_health (READY / NOT_READY)──► (供导航判断就绪)    │
│                                                                              │
│   RViz: rviz2_localization (3D点云+里程计, 看重定位对齐)                       │
└──────────────────────────────────────────────────────────────────────────────┘
                    │ /Odometry   │ /loc_health   │ TF
                    ▼             ▼               ▼
┌──────────────────────── 导航栈 (run_navigation.sh) ──────────────────────────┐
│                                                                              │
│                        ┌──────────────────┐                                  │
│   /clicked_point ──────┤ nav_goal_manager │──/map (2D栅格, latched)──►        │
│   /goal_pose     ──────┤                  │──/start_point  (起点, latched)──► │
│   /Odometry      ──────┤  · 加载2D地图     │──/end_point    (终点, latched)──► │
│   /loc_health    ──────┤  · 起终点拾取     │──/nav_goal     (目标, latched)──► │
│   /route_reset   ──────┤  · 目标管理       │──/nav_status   (状态)──►          │
│                        │  · 当前位姿       │──/route_markers(RViz可视化)──►    │
│                        └──────────────────┘──/nav_goal_marker(RViz)──►        │
│                                                                              │
│   RViz: rviz2_navigation (2D地图 + 起终点 + 目标 + 机器人位姿)                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

**核心思想: 位姿是"持续数据流", 不是一次性传递。**
重定位只在开始(或定位丢失)给 FAST-LIO 一个初值; 之后 FAST-LIO 每帧持续跟踪,
`/Odometry` 以 ~20Hz 持续发布。任何时刻订阅 `/Odometry` 或查 TF, 拿到的都是最新位姿。

---

## 2. 话题对应表

### 定位相关
| 话题 | 类型 | 方向 | 说明 |
|------|------|------|------|
| `/livox/lidar` | `livox_ros_driver2/CustomMsg` | 雷达→FAST-LIO | 原始点云 (20Hz) |
| `/livox/imu` | `sensor_msgs/Imu` | 雷达→FAST-LIO | IMU |
| `/initialpose` | `geometry_msgs/PoseWithCovarianceStamped` | global_reloc→FAST-LIO | 重定位初值(一次性) |
| **`/Odometry`** | `nav_msgs/Odometry` | FAST-LIO→导航/RViz | **机器狗实时位姿 map→base_link (~20Hz)** |
| `/cloud_registered` | `sensor_msgs/PointCloud2` | FAST-LIO→RViz | 配准后点云 |
| `/Laser_map` | `sensor_msgs/PointCloud2` | FAST-LIO→RViz | 先验地图点云(latched) |
| **`/loc_health`** | `std_msgs/String` | 监控→导航 | 定位健康: `READY` / `NOT_READY` |

### 导航相关
| 话题 | 类型 | 方向 | 说明 |
|------|------|------|------|
| `/map` | `nav_msgs/OccupancyGrid` | nav→RViz/规划 | 2D 栅格地图 (latched) |
| `/clicked_point` | `geometry_msgs/PointStamped` | RViz→nav | "Publish Point" 点选(起/终点拾取) |
| `/goal_pose` | `geometry_msgs/PoseStamped` | RViz→nav | "2D Goal Pose" 设目标 |
| **`/start_point`** | `geometry_msgs/PointStamped` | nav→规划 | **起点坐标 (latched)** |
| **`/end_point`** | `geometry_msgs/PointStamped` | nav→规划 | **终点坐标 (latched)** |
| `/route_reset` | `std_msgs/Empty` | →nav | 重置起/终点 |
| `/route_markers` | `visualization_msgs/MarkerArray` | nav→RViz | 起终点+连线可视化 (latched) |
| `/nav_goal` | `geometry_msgs/PoseStamped` | nav→规划 | 当前导航目标 (latched) |
| `/nav_goal_marker` | `visualization_msgs/Marker` | nav→RViz | 目标点箭头 (latched) |
| `/nav_status` | `std_msgs/String` | nav→外部 | `NO_GOAL`/`LOC_NOT_READY`/`NO_ODOM`/`ACTIVE\|dist=..`/`REACHED` |

---

## 3. TF 坐标系

```
map ──(nav_tf_manager)──> odom ──(nav_tf_manager)──> base_link
```
- `map → base_link`: 机器狗在地图中的全局位姿(等价于 `/Odometry`)。
- `nav_tf_manager` 把 FAST-LIO 的 `map→base_link` 拆成标准 `map→odom` + `odom→base_link`, 供 Nav2/规划器使用。
- 重定位大跳变会写入 `map→odom`, `odom→base_link` 保持连续(`max_initialpose_jump=0` 已禁用拒绝护栏)。

---

## 4. 完整操作流程(命令行)

> **每个新终端先进入工作区并加载环境:**
> ```bash
> cd /home/unitree/ws_localization
> source setup_env.sh
> ```

### 步骤 0(仅首次/重新建图时): 建图 → 重定位数据库 → 2D 地图
```bash
# 1) 建图(扫描环境, 生成 scans.pcd)
./run_mapping.sh

# 2) 用点云建重定位数据库
./build_reloc_db.sh

# 3) 3D 点云 → 2D 导航栅格地图(生成 scans.pgm/scans.yaml)
./build_nav_map.sh src/FAST_LIO/PCD/scans.pcd scans
```

### 步骤 1 — 终端 A: 启动定位栈
```bash
cd /home/unitree/ws_localization
./run_localization.sh            # 默认开定位 RViz(rviz2_localization)
# ./run_localization.sh norviz   # 无显示器时
```
预期: 日志出现 `Global relocalization SUCCESS` + `[loc-debug] match=99.x%`。

### 步骤 2 — 终端 B: 启动导航栈(等定位成功后)
```bash
cd /home/unitree/ws_localization
./run_navigation.sh              # 默认开导航 RViz(rviz2_navigation)
# ./run_navigation.sh norviz     # 无显示器时
# ./run_navigation.sh 路径/xxx.yaml   # 指定其他 2D 地图
```
预期: 日志 `已加载并发布 /map`, RViz 显示 2D 地图与机器人位姿。

---

## 5. 机器狗位姿获取

**方式 1: 订阅 `/Odometry`(推荐, ~20Hz 实时)**
```bash
ros2 topic echo /Odometry                              # 完整位姿
ros2 topic echo /Odometry --field pose.pose.position   # 只看位置
```
代码:
```python
self.create_subscription(Odometry, '/Odometry', cb, 20)
# cb 中: msg.pose.pose.position / msg.pose.pose.orientation
```

**方式 2: 查 TF `map → base_link`(适合规划/控制)**
```bash
ros2 run tf2_ros tf2_echo map base_link
```
```python
t = tf_buffer.lookup_transform('map', 'base_link', rclpy.time.Time())
```

---

## 6. 起点 / 终点拾取

### 方式 1: RViz 鼠标点选(主用法)
导航 RViz 工具栏选 **Publish Point**, 然后点地图:
- 第 1 次点 = **起点 START**(绿球 + START 文字)
- 第 2 次点 = **终点 END**(红球 + END 文字 + 青色连线)
- 第 3 次点 = 重新设起点(循环)

### 方式 2: 命令行设两点
```bash
# set_route SX SY EX EY [frame]   坐标为 map 系, 单位米
ros2 run go2_navigation set_route 0.0 0.0 3.5 1.2
```

### 重置起/终点
```bash
ros2 topic pub --once /route_reset std_msgs/msg/Empty {}
```

### 查看起/终点
```bash
ros2 topic echo /start_point
ros2 topic echo /end_point
```

---

## 7. 导航目标设定

```bash
# RViz: 工具栏 "2D Goal Pose" 拖动设目标
# 或命令行(X Y [YAW度]):
ros2 run go2_navigation send_goal 2.0 1.0 0

# 查看当前目标 / 状态
ros2 topic echo /nav_goal
ros2 topic echo /nav_status
```

---

## 8. 常用查询 / 调试命令

```bash
# 定位是否就绪
ros2 topic echo /loc_health

# 位姿实时频率(rclpy 法, 比 ros2 topic hz 在本机可靠)
python3 -c "
import rclpy, time
from rclpy.node import Node
from nav_msgs.msg import Odometry
rclpy.init(); n=Node('hz'); c={'n':0}
n.create_subscription(Odometry,'/Odometry',lambda m: c.update(n=c['n']+1),50)
t0=time.time()
while time.time()-t0<5.0: rclpy.spin_once(n,timeout_sec=0.05)
print(f'/Odometry: {c[\"n\"]/5:.1f} Hz'); rclpy.shutdown()
"

# 话题/节点/TF 概览
ros2 topic list
ros2 node list
ros2 run tf2_tools view_frames        # 生成 frames.pdf

# 看节点存活
pgrep -af "fastlio_mapping|global_reloc_node|nav_tf_manager|nav_goal_manager|livox_ros_driver2_node"
```

> 注: 本机 `ros2 topic echo`/`hz` 对 latched 话题偶发收不到(CycloneDDS 发现问题),
> 用 RViz 显示或上面的 rclpy 脚本更可靠; 节点终端日志也会直接打印起终点/目标设定结果。

---

## 9. 停止 / 清理

```bash
# 正常停止: 各自终端 Ctrl+C

# 或在 source setup_env.sh 后, 分栈清理(互不影响另一栈/RViz):
go2_kill_loc_stack     # 只清定位栈(FAST-LIO/重定位/雷达/rviz2_localization)
go2_kill_nav_stack     # 只清导航栈(nav_goal_manager/rviz2_navigation)

# 全部清理
go2_kill_stack
```

---

## 10. 常见问题

| 现象 | 处理 |
|------|------|
| 重定位失败 / `NOT_READY` | 确认狗在已建图区域内; 查 `/loc_health`; 重启 `./run_localization.sh` |
| 导航 RViz 无机器人位姿 | 先确认定位栈 `READY` 且 `/Odometry` 有数据 |
| 2D 地图不存在 | `./build_nav_map.sh src/FAST_LIO/PCD/scans.pcd scans` |
| 重定位后导航位姿错误 | 已修复(nav_tf_manager 跳变护栏 `max_initialpose_jump=0`); 确认未跑旧版本 |
| 脚本 Permission denied | `chmod +x *.sh` |
| 雷达不可达 | 确认狗内网 192.168.123.x 在哪个网口; 必要时 `GO2_DDS_IFACE=ethX ./run_localization.sh` |
| `ros2 topic echo` 收不到 latched | 用 RViz 看 / 用 rclpy 脚本; 这是本机 CLI 发现问题, 不影响实际通信 |

---

## 附: 关键文件
| 文件 | 作用 |
|------|------|
| `setup_env.sh` | 统一环境(ROS/DDS网口/清理函数), 所有脚本先 source |
| `run_mapping.sh` | 建图 |
| `build_reloc_db.sh` | 建重定位数据库 |
| `build_nav_map.sh` | 3D→2D 栅格地图 |
| `run_localization.sh` | 启动定位栈 + 定位 RViz |
| `run_navigation.sh` | 启动导航栈 + 导航 RViz |
| `src/go2_loc_bringup/launch/localization.launch.py` | 定位栈 launch(雷达20Hz, nav_tf 护栏关) |
| `src/go2_navigation/go2_navigation/nav_goal_manager.py` | 导航节点(地图/起终点/目标/位姿) |
| `src/go2_navigation/go2_navigation/set_route.py` | 命令行设起终点 |
| `src/go2_navigation/go2_navigation/send_goal.py` | 命令行设导航目标 |
| `src/go2_navigation/rviz/navigation.rviz` | 导航 RViz 配置 |
