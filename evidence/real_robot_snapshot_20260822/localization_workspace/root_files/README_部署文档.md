# Go2 建图 / 定位 / 重定位 独立工作区（ws_localization）

本工作区是从原 `ws_fastlio` 中**抽取的纯定位栈**，只包含 **建图、定位、全局重定位、坐标转换、地图工具**，
**不含 Nav2 导航**。用于在另一只 Unitree Go2 机器狗上独立部署。

---

## 1. 包含什么

```
ws_localization/
├── setup_env.sh              # 统一环境(DDS 网口自动选择 + source 各 workspace), 所有脚本先 source 它
├── run_mapping.sh           # ① 建图: Livox + FAST-LIO, Ctrl-C 自动存 scans.pcd
├── build_reloc_db.sh        # ② 建重定位库: 从 scans.pcd + keyframes 生成 reloc_db
├── run_reloc_only.sh        # ③ 单独测重定位(+RViz): Livox + global_reloc + FAST-LIO
├── run_localization.sh      # ④ 定位栈(给上层用): 上面 + nav_tf_manager + loc_health_monitor
├── build_nav_map.sh         # 工具: 3D 点云 → 2D 栅格地图(pgm/yaml)
├── third_party/
│   └── 3d_bbs-main/         # 重定位依赖的 BBS3D 分支定界库(含预编译 libcpu_bbs3d.so)
└── src/
    ├── FAST_LIO/            # FAST-LIO LIO 里程计(建图 + 纯定位两种模式)
    ├── global_reloc/        # 全局重定位(Scan Context + BBS3D + GICP)
    ├── go2_nav_frames/      # nav_tf_manager: map→odom→base_link TF 拆分(坐标转换)
    ├── go2_map_tools/       # 3D→2D 投影 + 虚拟障碍编辑(纯 Python 工具)
    └── go2_loc_bringup/     # 启动包: 建图/定位/重定位 launch + loc_health_monitor + maps/
```

### 各 ROS 包职责

| 包 | 语言 | 职责 | 关键可执行 |
|----|------|------|-----------|
| `fast_lio` | C++ | LIO 紧耦合里程计；建图模式写 `scans.pcd` + 关键帧；定位模式接收 `/initialpose` 跟踪 | `fastlio_mapping` |
| `global_reloc` | C++/CUDA | 开机自动全局重定位，发布一次 `/initialpose` | `global_reloc_node`、`build_reloc_db` |
| `go2_nav_frames` | C++ | 把 FAST-LIO 的 `/Odometry(map→base)` 拆成 `/odom` + TF `map→odom→base_link` | `nav_tf_manager` |
| `go2_map_tools` | Python | 点云转 2D 栅格、玻璃墙/禁区/鬼影擦除等地图编辑 | `pcd_to_occupancy_grid` 等 4 个 |
| `go2_loc_bringup` | (ament_cmake) | launch 编排 + 定位健康监控 | `loc_health_monitor` |

---

## 2. 技术栈总结

### 2.1 建图（FAST-LIO mapping）
- **算法**：FAST-LIO2，IMU 紧耦合的迭代误差状态卡尔曼滤波（IKFoM）+ ikd-Tree 增量地图。
- **输入**：`/livox/lidar`（Livox CustomMsg, ~10Hz）、`/livox/imu`（~200Hz）。
- **输出**：
  - `src/FAST_LIO/PCD/scans.pcd`（合并后的 3D 先验点云地图）
  - `src/FAST_LIO/PCD/reloc_db/poses.txt` + `keyframes/*.pcd`（关键帧，供重定位检索）
- **配置**：`src/FAST_LIO/config/mid360.yaml`（`localization_mode: false`）。

### 2.2 定位（FAST-LIO localization）
- **模式**：加载先验 `scans.pcd`，`localization_mode: true`，`update_map: true`（在先验图上增量更新，防走廊退化漂移）。
- **初值来源**：`global_reloc` 自动发布的 `/initialpose`（无需手点 RViz）。
- **护栏**：速度/跳变/竖直漂移/有效点比例超限即回退上一可信状态（见 `mid360_localization.yaml`）。
- **配置**：`src/FAST_LIO/config/mid360_localization.yaml`。

### 2.3 全局重定位（global_reloc）
开机用当前一帧雷达在先验地图里找回 `(x, y, yaw)`，**级联**策略：
1. **Scan Context 召回**：当前扫描算描述子，从 `reloc_db` 取 top-k 候选关键帧。
2. **SC + GICP**：每个候选做全 yaw 网格搜索 + 多级 GICP 精修；带正反歧义检测与相对关键帧漂移拒绝。
3. **BBS3D 全局兜底**：官方 [KOKIAOKI/3d_bbs](https://github.com/KOKIAOKI/3d_bbs) 分支定界全局搜索（x,y,yaw），地面约束 + 从中心外扩。
4. **多重门槛校验**：GICP fitness、SC 距离门、yaw 门、发布门槛 `min_publish_fitness=0.95`、对称性自检。
5. 通过后发 `/initialpose`，成功后用 `/cloud_registered` 持续自检（绑架检测）。
- **依赖**：`third_party/3d_bbs-main/build/libcpu_bbs3d.so`（CPU 版；Jetson Orin 上 GPU 版评分异常故用 CPU）。
- **配置**：`src/global_reloc/config/global_reloc.yaml`。

### 2.4 坐标转换（go2_nav_frames / nav_tf_manager）
- FAST-LIO 直接输出 `map→base_link` 的 `/Odometry`；上层（如 Nav2）需要标准的 `odom→base_link`。
- `nav_tf_manager` 把 `/Odometry` 拆成 `/odom`（`odom→base_link`）并广播 TF `map→odom→base_link`。
- 定位模式下 FAST-LIO 设 `localization.publish_tf: false`，由本节点统一发 TF，避免冲突。

### 2.5 地图工具（go2_map_tools）
- `pcd_to_occupancy_grid`：3D `scans.pcd` → 2D 栅格 `scans.base.pgm` + `scans.yaml`（按格内高差 ΔH 判障）。
- `manage_obstacles` / `pick_map_line` / `paint_virtual_obstacles`：以世界坐标记录虚拟墙/禁区/擦除（`scans.obstacles.json`），非破坏式合成到 `scans.pgm`。
- 一键入口：`build_nav_map.sh`。注：2D 图主要供后续 Nav2 用，**不影响 3D 重定位**。

---

## 3. 数据流

```
建图(离线)                            在线定位
─────────                            ────────
run_mapping.sh                       run_reloc_only.sh / run_localization.sh
   │                                    │
   ├─► scans.pcd ─────────┐            Livox /livox/lidar,/livox/imu
   └─► reloc_db/poses.txt │              │        │
       + keyframes/*.pcd  │              ▼        ▼
              │           └──► global_reloc   FAST-LIO(localization)
              ▼                   │ /initialpose  │
       build_reloc_db.sh ──► reloc_db/map_*.pcd   │
                                  └──────────────►│ 跟踪
                                                  ▼
                                          /Odometry(map→base)
                                                  │
                                          nav_tf_manager
                                                  ▼
                                          /odom + TF map→odom→base_link
                                                  ▼
                                          loc_health_monitor → /loc_health
```

核心话题：

| Topic | 类型 | 发布者 | frame |
|-------|------|--------|-------|
| `/livox/lidar` `/livox/imu` | CustomMsg / Imu | livox 驱动 | livox_frame |
| `/initialpose` | PoseWithCovarianceStamped | global_reloc | map |
| `/Odometry` | Odometry | FAST-LIO | map→base_link |
| `/cloud_registered` | PointCloud2 | FAST-LIO | map |
| `/odom` + TF | Odometry / tf2 | nav_tf_manager | odom→base_link |
| `/loc_health` | String(`READY\|...`) | loc_health_monitor | — |

---

## 4. 在新机器狗上部署

### 4.1 前置依赖（系统已具备，狗出厂一般都有）
| 依赖 | 路径/来源 | 说明 |
|------|-----------|------|
| ROS 2 Foxy | `/opt/ros/foxy` | 基础环境 |
| `unitree_ros2` | `/home/unitree/unitree_ros2` | 宇树 DDS/消息（CycloneDDS）。无则降级用 foxy，cmd_vel 真走需它（本栈不发 cmd_vel，可不强求） |
| Livox 驱动 `ws_livox` | `/home/unitree/ws_livox` | 提供 `livox_ros_driver2`（含 MID360_config.json） |
| PCL / Eigen3 / OpenMP | apt | FAST-LIO、global_reloc 编译依赖 |
| `3d_bbs-main` | 本仓 `third_party/3d_bbs-main` | 已随包携带预编译 `.so`，无需再装 |

> **网络**：MID360 雷达与狗 DDS 都在 `192.168.123.x`。`setup_env.sh` 会自动选持有该网段且 UP 的网口；
> 也可手动 `export GO2_DDS_IFACE=eth1`。

### 4.2 拷贝到新狗
把整个 `ws_localization/` 目录拷到新狗的 `/home/unitree/`：
```bash
# 在新狗上(或用 scp/U 盘)
rsync -a ws_localization/ unitree@<新狗IP>:/home/unitree/ws_localization/
```
> 路径默认硬编码为 `/home/unitree/ws_localization`。若放到别处，需相应改 `setup_env.sh`、
> 各 `config/*.yaml` 与 launch 默认值（或编译时 `export BBS3D_DIR=...` 覆盖 BBS3D 路径）。

### 4.3 编译
```bash
cd /home/unitree/ws_localization
source /opt/ros/foxy/setup.bash
source /home/unitree/ws_livox/install/setup.bash   # 需要 livox_ros_driver2
colcon build --symlink-install
```
> BBS3D 库路径解析顺序：环境变量 `BBS3D_DIR` → 本仓 `third_party/3d_bbs-main` → `/home/unitree/3d_bbs-main`。
> 默认会自动用随包携带的 `third_party/3d_bbs-main`，无需配置。
>
> 若 `third_party/3d_bbs-main/build/libcpu_bbs3d.so` 与新狗架构不匹配（少见，同为 Jetson Orin 一般可用），
> 需在新狗上重新编译 3d_bbs：见其自带说明，编出 `build/libcpu_bbs3d.so` 后再 `colcon build`。

### 4.4 使用流程（按顺序）
```bash
cd /home/unitree/ws_localization

# ① 建图：遥控狗走完整条路线，结束按一次 Ctrl-C(自动存 scans.pcd + 带时间戳存档)
./run_mapping.sh                 # 无显示器用 ./run_mapping.sh norviz

# ② 建重定位库：每次重新建图后必须重跑(会清旧缓存, 从当前 scans.pcd 重建)
./build_reloc_db.sh

# ③ 验收重定位(单独, 带 RViz)：白色底图与彩色实时点云应重合
./run_reloc_only.sh              # 无显示器用 norviz

# ④ 作为定位栈对外服务(给上层/Nav2)：另开终端 ros2 topic echo /loc_health 等 READY
./run_localization.sh

# (可选) 生成 2D 栅格地图，供后续导航
./build_nav_map.sh src/FAST_LIO/PCD/scans.pcd scans
```

### 4.5 验收标准
- `run_reloc_only.sh` 日志出现 `Published /initialpose` 与 `Global relocalization SUCCESS (fitness≈1.0)`。
- RViz 中先验地图（白）与实时点云（彩）重合，不倾斜。
- `ros2 topic echo /loc_health` 输出 `READY|...`（用于上层启动门控）。

---

## 5. 重要注意事项（来自踩坑经验）

1. **每次重新建图后必须 `./build_reloc_db.sh`**。否则 `map_gicp.pcd`/`map_voxel.pcd` 旧缓存会让重定位
   对齐到旧坐标系，出现「fitness=1.0 但实际偏 ~40°」的假成功。`build_reloc_db.sh` 已会自动清旧缓存。
2. **走廊/对称环境**重定位易出正反歧义；`global_reloc` 已内置 yaw 歧义检测 + BBS3D 全 yaw 兜底，
   但发布门槛严（0.95），失败时会反复重试而非乱发。
3. **纯定位漂移**：`update_map: true` 解决了长走廊几何退化导致的静止漂走（匹配率 62%→95%）。
4. 不要在建图会话里同时起 `global_reloc`；三个脚本对应三种独立会话。
5. 本工作区**不含 Nav2**。`build_nav_map.sh` 产出的 2D 图是给后续导航准备的，定位/重定位本身不依赖它。

---

## 6. 与原 ws_fastlio 的差异
- 路径从 `/home/unitree/ws_fastlio` 全量改为 `/home/unitree/ws_localization`。
- 启动包从 `go2_nav_bringup`（混了 Nav2）精简为新包 `go2_loc_bringup`（只保留建图/定位/重定位 launch + 健康监控）。
- BBS3D 依赖从硬编码 `/home/unitree/3d_bbs-main` 改为：优先随包 `third_party/`，可用 `BBS3D_DIR` 覆盖。
- 删除了 Nav2 相关包（`go2_cmd_vel`、`go2_nav_bringup` 的 nav2 部分、profiles/behavior_trees 等）。
