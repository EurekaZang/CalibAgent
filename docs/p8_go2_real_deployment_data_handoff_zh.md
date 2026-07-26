# CalibAgent P8：Unitree Go2 在线实机实验、数据采集与交付规范

> 文档用途：直接交给实机部署、参考定位、场地、安全、数据记录和导出人员执行。
> 文档日期：2026-07-26。
> 当前状态：**正式采集前冻结草案**。软件团队完成第 3 节全部前置物并提交冻结 commit/hash 后，才可将本草案标记为 `FROZEN`。
> 目标：补齐在线实机主动标定、实机域偏移恢复和实机下游导航证据；不是只录几段演示视频。
> 适用机器人：Unitree Go2；具体型号、序列号、固件和 SDK 版本必须在正式采集前写入元数据。

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan
- Origin Date: 2026-07-26
- Verification Status: REVIEWED AGAINST CURRENT P1/P6/P7 CONTRACTS
- Version Label: `p8_go2_real_handoff_v1`
- Local evidence basis:
  - `docs/p1_go2_real_data_collection_handoff_zh.md`
  - `docs/p6_p7_strong_confirmatory_protocol.md`
  - `configs/experiments/p6_domain_shift_strong_confirmatory.yaml`
  - `configs/experiments/p7_navigation_strong_confirmatory_v2.yaml`
  - `src/calibagent/interfaces/types.py`
  - `src/calibagent/core/safety/filter.py`

---

## 1. 先回答：现在是否只缺实机

从论文证据看，P0–P7 的软件、P1 离线真实 Go2 数据、强 P6/P7 仿真和独立审计已经闭合。若论文要增加以下主张，主要剩余工作就是 P8：

1. 主动标定策略在真实 Go2 上在线执行；
2. 12-trial 主动标定在真实下游导航中优于 raw，并与 30-trial dense 和 matched-budget controls 非劣；
3. 真实 Go2 在受控域偏移后能够检测并恢复；
4. 实机安全、时延、失败和可重复性有完整原始证据。

但 P8 不只是“采数据”。当前 `src/calibagent/backends/go2_ros.py` 仍是 fail-closed 占位接口。正式采集前还必须完成并冻结：

- Go2 在线 backend；
- 独立急停和通信 watchdog；
- 参考定位、坐标外参和时间同步；
- 实机安全 envelope；
- 方法/地图/shift 随机化计划；
- 写一次、全量 hash 的数据记录链。

**在第 3 节全部通过以前，实机同事只能做 `DEV` 调试，不能开始 `CONFIRMATORY` 采集。**

P1 的 183 个离线真实 trial 已经存在，不需要重复采集。P8 必须新采，因为 P1 不能证明主动策略已在真机在线闭环运行。

---

## 2. 最终必须交付的两个确认性数据包

| 数据包 | 回答的问题 | 独立实验单位 | 计划规模 | 是否必须 |
|---|---|---|---:|---|
| `P8-NAV` | 在线标定是否改善真实下游导航，且保持预算/安全优势 | `paired_block_id` | 30 个完整 paired blocks | 必须 |
| `P8-SHIFT` | 受控实机域偏移后，full 是否优于 passive 的早期恢复 | 每个 shift 内的 `paired_block_id` | 4 shifts × 20 paired blocks | 若要把 P6 提升为实机 claim，则必须 |

两个数据包不能互相替代：

- 只有 `P8-NAV`：可写真实在线标定和下游导航，P6 域偏移仍只能写仿真；
- 只有 `P8-SHIFT`：可写真实恢复，但不能证明下游导航；
- 两者都完成：可闭合当前 P6/P7 对应的实机证据。

所有开发、联调、pilot 和失败确认必须保留，但不得与正式确认性数据合并。

### 2.1 工作量和排期底线

仅按机器人运动时间计算：

- P8-NAV calibration 至少 `3,060 × 4 s = 3.4 h`；
- P8-NAV validation 至少 `1,920 × 4 s = 2.1 h`；
- P8-NAV navigation 为 1,440 个 episode，最坏 timeout 总时长 24 h；
- P8-SHIFT 为 `10,800 × 4 s = 12 h`。

这些数字不包含 reset、回到起点、地图检查、换电、载荷安装、参考重定位、
QC、备份和技术故障。现场排期应为：

- backend/HIL/安全 commissioning：至少 3–5 个工作日；
- P8-NAV 正式采集：至少 10 个运行日；
- P8-SHIFT 正式采集：通常再需 10–20 个运行日；
- 数据导出、视频复核、raw 重放和补齐技术无效 run：至少 3–5 个工作日。

不得通过复用不同方法的 calibration、缩短 trial、减少地图、跳过失败 run 或
把同一 block 拆成伪独立重复来压缩工作量。

---

## 3. 正式采集前软件团队必须交给实机团队的冻结物

### 3.1 必需文件

实机同事在收到下列全部文件前不得执行正式数据：

```text
p8_frozen_release/
├── RELEASE_README.md
├── source_commit.txt
├── container_image_digest.txt
├── backend_hardware_gate_report.json
├── protocol/
│   ├── p8_go2_real_deployment_data_handoff_zh.md
│   ├── analysis_plan.yaml
│   └── exported_table_schemas/
├── configs/
│   ├── p8_real_safety.yaml
│   ├── p8_real_nav_confirmatory.yaml
│   └── p8_real_shift_confirmatory.yaml
├── schedules/
│   ├── nav_block_schedule.csv
│   ├── shift_block_schedule.csv
│   └── method_blinding_key.enc-or-controlled.csv
├── maps/
│   ├── map_01_geometry.yaml
│   ├── ...
│   └── map_06_geometry.yaml
├── commands/
│   ├── validation_commands.csv
│   ├── dense_design.csv
│   └── frozen_candidate_pool.csv
├── tools/
│   ├── export_p8_delivery
│   ├── validate_p8_delivery
│   └── analyze_p8_confirmatory
├── environment/
│   └── analysis_requirements.lock.txt
└── checksums.sha256
```

所有文件必须由 `checksums.sha256` 覆盖；校验文件本身不列入自身，避免不可能的 self-hash。
三个工具必须有 `--help`、非零失败退出码和一个已通过的 DEV dry-run 示例。
实机团队不应现场手写汇总指标或猜测 schema。

### 3.2 backend 硬门槛

`backend_hardware_gate_report.json` 必须证明：

- `Go2RosBackend.reset/get_state/execute_trial/emergency_stop` 均已实现，不再抛出 `NotImplementedError`；
- 命令发送、状态读取、trial phase marker 和原始记录端到端可用；
- 网络断开、进程退出、状态过期、定位失效、非有限状态和低电量均 fail closed；
- 失去上位机 heartbeat 后自动发送零命令；
- planner 输出不能绕过 hard safety filter；
- 急停不依赖学习模型、posterior、planner 或 Python 主进程；
- 每次后验更新均保存版本号和状态；
- output root 非空时拒绝覆盖；
- backend、记录器和安全 monitor 使用同一冻结 source commit。

### 3.3 硬件门控测试

正式 release 至少通过：

1. 100 次静止零命令与 reset 测试；
2. 30 次低速 ramp-in/measure/ramp-out 测试；
3. 每类至少 10 次故障注入：网络断开、参考定位失效、状态超时、进程崩溃、非法命令；
4. 所有故障均进入零命令或阻尼/安全模式；
5. `safety decision → zero-command publish` 最大时延不超过 40 ms；
6. 物理减速时间单独记录，不与软件发布时延混为一个指标；
7. 0 次未受控工作区越界、跌倒、人员接触或设备损伤。

这些是软件/硬件 gate，不计入论文主实验。

---

## 4. 机器人、场地和人员配置

### 4.1 机器人

必须记录：

- `robot_id`、Go2 具体型号和序列号；
- 固件、运动控制器、SDK、ROS/ROS 2、驱动和上位机版本；
- 电池型号和唯一 ID；
- 足端型号及磨损状态；
- LiDAR、计算单元、marker 架、线缆和固定支架的质量；
- 空载和实验配置下的总附加载荷；
- gait/control mode；
- 厂商校准和本地维护日期。

使用一台 Go2 时，论文只能主张“在该 Go2 平台实例上验证”。如果有多台：

- 每个 `robot_id` 都要独立记录；
- 方法不能与 robot 混杂；
- 目标是每台至少 15 个 P8-NAV blocks；
- 只有一两台机器人时仍不得声称跨个体泛化。

Unitree 官方产品页对不同 Go2 型号给出的载荷约为 7–8 kg、最大约 10–12 kg，但这些是产品规格，不是本实验可直接使用的安全上限。P8 的附加载荷必须取“厂商/本地批准值、支架批准值和本文实验值”三者中的最小值。正式实验不得靠近厂商最大载荷。

### 4.2 场地

最低要求：

- 封闭、无无关人员和动物的实验区域；
- 建议有效区域至少 `10 m × 8 m`，外围另留至少 1 m 缓冲；
- 固定软质障碍物，不使用锐边、玻璃、硬金属或易翻倒重物；
- 地面水平、照明稳定、无散落线缆；
- 参考定位覆盖整个区域；
- 一台固定广角相机覆盖全场；
- 机器人和人员逃生路径不重叠；
- 地图原点、障碍物和 waypoint 有可复测的场地坐标。

如果实际场地更小，必须在 `p8_real_safety.yaml` 中缩小 workspace 和命令上限；不得通过关闭 projected-workspace 检查来适配小场地。

### 4.3 人员

正式运行至少三人：

| 角色 | 职责 |
|---|---|
| 运行负责人 | 加载 frozen schedule，启动/结束 run，不修改结果 |
| 独立安全员 | 始终手持物理急停，只负责安全判断 |
| 数据/参考定位负责人 | 监控 rosbag、时间同步、mocap/LiDAR health 和备份 |

同一人不能同时持续盯控制终端和承担唯一急停职责。

---

## 5. 独立参考定位和时间同步

### 5.1 接受的 ground truth

首选：

- 外部 motion capture；
- 独立 LiDAR odometry/SLAM，且不把被测 Go2 onboard state 当真值。

`pose_x/y/yaw` 必须表示固定 world/map 坐标系下的 Go2 `base`，不是 LiDAR 或 marker 本体：

```text
T_world_base(t) = T_world_reference(t) × T_reference_base
```

必须交付：

- 原始参考输出；
- `T_reference_base` 外参；
- 外参标定方法和重复测量结果；
- frame tree；
- 实际导出所用的外参文件；
- 静止、直行、左移、逆时针旋转四项方向检查。

参考系统 commissioning 还必须完成：

1. 静止 60 s：报告 x/y/yaw 的 median、p95 抖动和最大跳变；
2. 沿测量过的直线移动至少 3 m：位置尺度误差目标 ≤1%，硬拒收 >2%；
3. 原地旋转约 360°：yaw 闭环误差目标 ≤0.02 rad，硬拒收 >0.05 rad；
4. 在六张地图的 start/goal/极端位置各静止 10 s，确认无遮挡失锁；
5. 重复安装外参至少 3 次，报告平移和 yaw 重复性；
6. 如果使用 LiDAR odometry，另报告 5 min 静止漂移和闭环漂移；如果使用
   mocap，报告 marker 遮挡率和系统标定残差。

所有 commissioning 原始记录和报告进入 `reference/`。超过硬拒收线时不得
用后处理平滑把系统“修到通过”。

### 5.2 频率和同步

| 通道 | 目标频率 | 最低可接受 | 说明 |
|---|---:|---:|---|
| 安全 monitor / 实际发送命令 | ≥100 Hz | 50 Hz | 必须可计算 abort latency |
| onboard state / IMU | ≥100 Hz | 50 Hz | 用于实时控制和安全 |
| 独立参考 base pose | ≥50 Hz | 40 Hz | 禁止复制样本伪造频率 |
| planner/model diagnostics | planner 每次决策 | 不得缺决策 | 通常 10 Hz |
| 固定相机视频 | ≥30 fps | 25 fps | 用于碰撞/跌倒复核 |

时间要求：

- 每条消息保留 source timestamp 和 recorder receive timestamp；
- 同时记录 `monotonic_ns` 与 UTC/TAI 映射；
- 时钟 offset 目标 ≤5 ms，硬拒收线 10 ms；
- 同一流内 timestamp 严格递增；
- 不得混用未说明的 ROS time、system time 和 sensor time；
- 每个 session 开始和结束都保存同步诊断；
- 视频必须有可对齐的灯光/蜂鸣/软件 marker。

P1 的真实数据只有约 20 Hz 参考采样，且缺少完整 rosbag 和外部视频。P8 不能沿用这些缺口。

`measured_vx/vy/wz` 只是可复核的派生量。最终交付必须保留原始
`T_world_reference(t)`、冻结外参和时间戳，使分析端能够重新计算
`T_world_base(t)`、做 SE(2) 相对运动和重新估计速度。不得：

- 用 onboard odometry 替换独立参考；
- 只交现场软件导出的 velocity；
- 复制/插值样本来伪造 40–50 Hz；
- 在没有记录参数的情况下人工平滑或修剪轨迹；
- 用未来信息修改在线 planner 当时看到的状态。

---

## 6. 实机安全协议

### 6.1 总原则

- 所有命令先经过不可学习、不可绕过的 hard safety filter；
- safety filter 拒绝时不能由 planner 降级为“仍然执行最优候选”；
- 未知/缺失/过期/非有限状态一律拒绝；
- 任何人员进入安全区时立即零命令；
- 物理急停优先级高于软件；
- 机器人倒地、失控、越界或发生硬碰撞后必须结束当前 session 并检查；
- 禁止在正式数据中临时放宽 envelope。

### 6.2 建议初始命令上限

以下数值是正式 commissioning 的**上限建议**，不是要求机器人必须达到：

| 项目 | 建议初始上限 |
|---|---:|
| `vx` | `[-0.30, 0.30] m/s` |
| `vy` | `[-0.20, 0.20] m/s` |
| `wz` | `[-0.50, 0.50] rad/s` |
| 平移范数 | `≤0.35 m/s` |
| 导航 cruise speed | `0.18 m/s` |
| 导航侧向速度 | `≤0.14 m/s` |
| 导航 yaw rate | `≤0.25 rad/s` |

正式上限必须：

1. 不超过上述建议；
2. 不超过本机型/固件/场地批准值；
3. 通过 DEV commissioning；
4. 在主实验前写入冻结 config 并 hash。

仿真中的 `min_base_height=0.15 m`、`0.158/0.160 m` interlock 阈值不得直接复制到实机。实机阈值必须根据该机器人、gait、支架和载荷的 DEV 站立/运动高度分布，由安全负责人批准后冻结。

### 6.3 必须监控的硬状态

- roll、pitch、base height、yaw rate；
- world workspace 和 projected workspace；
- battery、电压和 BMS fault；
- motor/driver fault 和温度；
- localization validity 和消息 age；
- control heartbeat、network age；
- mode/gait 是否意外切换；
- command bounds、线速度范数、线角耦合和 slew；
- physical E-stop 状态。

### 6.4 安全事件定义

`serious_safety_event=true` 包括：

- 人员或动物被机器人接触；
- 跌倒或翻滚；
- 未受控离开工作区；
- 物理急停未生效；
- 机器人、场地或传感器受损；
- 电池、关节、电机或通信故障导致不可控运动。

软障碍物轻触可以记为 `collision=true` 而不一定是 serious event，但必须保留视频、事件时间和判定依据。

正式证据要求 serious safety events 为 0。发生一次即暂停确认性实验并启动安全复审；不能删除该 run 后继续假装没有发生。

---

## 7. 全局实验设计、配对和随机化

### 7.1 独立统计单位

- 原始采样点不是独立样本；
- 一个 calibration trial 也不是论文的独立重复；
- P8-NAV 的独立单位是包含全部方法的 `paired_block_id`；
- P8-SHIFT 的独立单位是某个 shift 下包含 frozen/passive/full 的 `paired_block_id`。

所有 bootstrap、Wilcoxon 和置信区间均按 block 重采样，不能按 50 Hz 行数扩充 n。

### 7.2 正式 block 的独立性

P8-NAV 的 30 个 blocks：

- 分布在至少 5 个独立日期/时间块；
- 每天建议不超过 3 个 blocks；如果单个 block 的实际运行时间超过 2 h，
  则按人员疲劳和电池周转进一步减少；
- 每个 block 重新初始化定位和 posterior；
- 每个方法从同一 prior 开始；
- 方法顺序使用冻结 balanced Latin square；
- 六个地图顺序也使用冻结 balanced order；
- 电池、地面、地图和 robot 状态记录；
- 方法不能固定绑定某一天、电池或地图顺序。

P8-SHIFT 每个 shift 的 20 个 blocks：

- 至少分布在 4 个独立日期/时间块；
- 每个 block 内 frozen/passive/full 顺序随机；
- 三个方法使用相同初始设计、monitor commands、validation commands 和 shift 定义；
- 任何 complete 失败都保留。

### 7.3 开发和确认分离

ID 必须带角色：

- `DEV-*`：commissioning、调参、地图修改、阈值选择；
- `CONFIRM-*`：冻结后确认性数据；
- `RERUN-TECH-*`：仅允许预定义技术故障重采。

看过 `CONFIRM` 结果后：

- 不改门槛；
- 不改地图；
- 不改方法；
- 不改样本量；
- 不把 failed confirmation 改名为 pilot；
- 若必须修复，保留失败结果，使用新 commit、新 block IDs 和新确认协议。

---

## 8. P8-NAV：在线标定与真实导航实验

### 8.1 方法

| ID | 方法 | 标定 trial 数 | 作用 |
|---|---|---:|---|
| `B0_raw` | 无标定 / identity | 0 | raw 基线 |
| `B1_dense` | 冻结 dense safe design | 30 | 高预算参考 |
| `B2_lhs` | safe-snapped LHS | 12 | matched budget |
| `B3_sobol` | safe-snapped Sobol | 12 | matched budget |
| `B4_d_opt` | Bayesian D-optimal | 12 | matched budget |
| `B5_active_no_task` | active IVR、无 task weighting | 12 | task ablation |
| `B6_random` | 冻结安全候选池随机采样 | 12 | 经典随机基线 |
| `B8_full` | task-weighted active IVR | 12 | 主方法 |

每个方法必须使用：

- 相同 `M1 affine` feature set；
- 相同 prior；
- 相同安全候选池；
- 相同 8 个 held-out validation commands；
- 相同 planner、inverse compensator、velocity feedback、gait 和 safety；
- posterior reset；
- 不得让 validation commands 进入模型更新。

### 8.2 每个 P8-NAV block 的数据量

每个 block 包含：

- calibration：`30 + 6×12 = 102` 个 trial；
- validation：`8 methods × 8 commands = 64` 个 trial；
- navigation：`8 methods × 6 maps = 48` 个 episode。

30 个完整 blocks 的目标总量：

| 数据 | 数量 |
|---|---:|
| calibration trials | 3,060 |
| held-out validation trials | 1,920 |
| navigation episodes | 1,440 |
| method-level posterior states | 至少 240 份 |

这些数字是正式计划，不是最少录几条即可的参考值。

### 8.3 calibration trial 时序

实机使用 P1 已验证的 4.0 s profile：

| phase | 时长 | 是否进入 calibration measurement |
|---|---:|---|
| precheck/warm-up | ≥0.5 s | 否 |
| ramp-in | 0.6 s | 否 |
| settle | 0.8 s | 否 |
| measure | 2.0 s | 是 |
| ramp-out | 0.6 s | 否 |

measure 内命令必须恒定；实际发送命令而非计划值进入记录。每个 trial 必须保留完整 ramp 和安全 trace。

### 8.4 held-out validation commands

默认沿用强 P7 的 8 个低速命令：

```text
[+0.13, +0.04, +0.08]
[+0.13, -0.04, -0.08]
[+0.10, +0.08, +0.16]
[+0.10, -0.08, -0.16]
[+0.16, +0.06, +0.14]
[+0.16, -0.06, -0.14]
[+0.09, +0.10, +0.21]
[+0.09, -0.10, -0.21]
```

单位为 m/s、m/s、rad/s。它们必须在 real safety envelope 内，并在正式 config 中 hash。若 commissioning 证明某命令不安全，只能在查看确认性结果前统一修改并重新冻结。

### 8.5 六个真实地图

地图 ID 固定为：

1. `real_s_bend`
2. `real_offset_slalom`
3. `real_narrow_lane`
4. `real_double_chicane`
5. `real_weighted_arc`
6. `real_extended_lane`

每个 `map_*_geometry.yaml` 必须包含：

- world frame；
- start pose 和容差；
- waypoint 坐标和顺序；
- goal 坐标、`goal_radius=0.25 m`；
- 软障碍物中心、尺寸、高度和安全材料；
- 机器人 footprint 定义；
- collision 判据；
- timeout，默认 60 s；
- 现场实测坐标和测量工具；
- 一张带标尺的俯视图/照片；
- geometry SHA-256。

所有方法使用同一地图、同一 waypoint planner 和同一成功/碰撞判据。

### 8.6 每个 navigation episode

1. 将机器人放到 start pose，位置误差 ≤5 cm、yaw 误差 ≤0.05 rad；
2. 确认 map、method、block、posterior version 和 reference health；
3. 开始 rosbag、视频和 episode marker；
4. 0.5 s 稳定；
5. 启动固定 planner；
6. 直到到达、碰撞、safety abort 或 60 s timeout；
7. 发送零命令并确认停止；
8. 保存 posterior、trace、episode metrics、视频时间范围和事件台账；
9. 机器人回到 start 后才进入下一 episode。

成功定义：在 timeout 前进入 0.25 m goal radius，且没有 collision 或 serious safety event。

timeout 和算法性 abort 是失败结果，不能当技术故障排除。

---

## 9. P8-SHIFT：实机域偏移检测与恢复

### 9.1 方法

| ID | 说明 |
|---|---|
| `frozen` | 检测后也不更新 posterior |
| `passive` | 检测后按冻结安全设计更新 |
| `full` | 检测、posterior inflation、task-aware active recovery |

三种方法必须共享相同初始 calibration、pre/post monitor commands、validation commands 和 shift 定义。

### 9.2 四类受控 shift

| Shift ID | 具体实现 | 必须记录 |
|---|---|---|
| `R1_command_gain_coupling` | 在命令接口加入冻结、可逆的 gain/coupling matrix | 矩阵、启用时刻、代码/config hash |
| `R2_payload_com` | 快拆支架增加额外载荷；建议目标 2.0 kg，前向 COM 偏置不超过 20 mm | 所有既有+新增载荷、称重、安装坐标、照片 |
| `R3_surface_friction` | 从 nominal 地面进入预先测量的中等低摩擦安全材料 | 材料、批次、表面状态、摩擦代理测量、照片 |
| `R4_mixed_context` | 批准的小载荷 + 中等 friction shift + 冻结 context/task 变化 | 每个组成量及统一启用时刻 |

安全约束：

- `R2/R4` 的总附加载荷不得超过厂商/本地/支架批准值中的最小值；
- 推荐 2.0 kg 是实验目标上限，不是厂商额定值；
- 载荷必须刚性固定，有二次防脱落；
- 低摩擦表面不得造成不可控滑倒；
- 正式 shift 参数只可由 DEV commissioning 决定一次；
- shift 必须可重复测量，不能使用“地面大概更滑”等描述。

### 9.3 每个 shift sequence

每个 method/shift/block 需要 45 个 motion trials：

| 阶段 | trial 数 | 目的 |
|---|---:|---|
| pre-shift calibration | 12 | 建立相同初始 posterior |
| pre-shift monitor | 4 | 估计 false alarm |
| post-shift monitor | 5 | 检测和 delay |
| recovery step | 固定 12 | passive/full 最多更新 12 次；frozen 执行对应命令但不更新 |
| interleaved recovery validation | 12 | 形成 rolling validation RMSE |

四 shifts × 20 paired blocks × 3 methods：

- 240 个完整 shift sequences；
- 10,800 个 motion trials；
- 每个 shift 至少 20 个完整 frozen/passive/full triplets。

三种方法和所有 blocks 都必须执行完整 12 个 recovery step。若算法提前达到
recovery gate，只停止 posterior update，剩余 step 继续执行冻结的安全命令并
标记为 `post_recovery_monitor`。因此样本量不随算法是否早恢复而变化。
`10,800` 是进入主分析的计划 trial 数，不包含 DEV、故障注入、上下文恢复
sentinel 或技术无效 attempt；这些额外数据仍全部保留。

### 9.4 shift 执行规则

- algorithm 不接收 shift label 或 shift time；
- evaluator 和原始日志必须知道真实 shift marker；
- R1 可在零命令边界原子启用；
- R2/R4 必须先硬件禁止运动、人员进入并安装快拆载荷、人员离场、重新确认 E-stop 后再继续；
- R3 使用冻结的地面过渡区或可复现实验模块；
- 安装/切换期间的数据不进入 monitor endpoint，但完整保留；
- 每个 method sequence 后恢复 nominal context，并执行 2 个不进入 endpoint
  的冻结 sentinel；只有两次均通过 nominal 恢复门槛，才可开始下一个方法；
- R2/R4 每次拆装后复核载荷质量、安装坐标、二次防脱和照片，不能假定首次
  安装测量对全天都有效；
- 不得因检测失败而重新触发 shift；
- complete 的 false alarm、missed detection、slow recovery 和高 RMSE 都是有效结果。

### 9.5 P8-SHIFT 主要 endpoint

- pre-shift false alarm；
- detection success 和 detection delay；
- recovery success 和 recovery trials；
- recovery trials 4–9 的早期 rolling RMSE；
- `passive early RMSE - full early RMSE`；
- full terminal RMSE；
- valid observation ratio；
- safety abort、zero-command latency 和 serious event。

缺失 rolling window 使用冻结 penalty `0.25`，不得删除该 block 或插值。

---

## 10. 必须记录的原始逻辑通道

具体 ROS topic 名可由现场决定，但 `topic_map.yaml` 必须把每个 topic 映射到以下逻辑通道。

| 逻辑通道 | 最低要求 | 用途 |
|---|---|---|
| planner desired command | 每次 planner tick | 任务要求 |
| candidate commands + scores | 每次 propose | 复算 active/D-opt/安全选择 |
| safety decision | 每个候选和每个 monitor tick | accepted、reason codes |
| inverse compensated command | 每次控制 tick | 复查 compensator |
| actual transmitted command | ≥50 Hz | 真正执行的 setpoint |
| robot command ACK/effective command | 若 SDK 提供则必须 | 区分发送与接受；无 ACK 时写 `ack_available=false` |
| independent reference pose | ≥40 Hz，目标 ≥50 Hz | ground truth |
| onboard odometry/state | ≥50 Hz | 控制和诊断，不作独立真值 |
| IMU, roll, pitch, yaw rate | ≥100 Hz，最低 50 Hz | safety |
| base height | ≥100 Hz，最低 50 Hz | safety/interlock |
| joint/motor state | SDK 可提供的最高稳定频率 | fault、温度、扭矩诊断 |
| foot contact | 若可用则必须 | 滑移/跌倒诊断 |
| battery/BMS | ≥10 Hz | 比较性和安全 |
| localization health/covariance | 每条 reference 或状态变化 | 技术故障判定 |
| model prediction | 每个 trial/validation | mean、covariance、posterior version |
| posterior snapshot | 初始化和每次 update 后 | 完整复算 |
| shift detector | 每次 monitor trial | NIS、CUSUM、evidence、alarm |
| trial/phase marker | 每次边界 | block/method/trial/attempt/phase |
| navigation marker | episode start、waypoint、goal、timeout | endpoint |
| collision/safety event | 事件发生时 | 原因、来源、operator confirmation |
| state-machine transition | 每次 transition | 检查合法流程 |
| network/clock diagnostics | ≥1 Hz 和事件触发 | latency/同步 |
| fixed overview video | 全程 ≥25 fps | 独立碰撞和安全复核 |

禁止只保存汇总 CSV 后删除 rosbag。

---

## 11. 最终交付目录

```text
p8_go2_real_delivery/
├── README.md
├── frozen_release/
│   └── [第3节完整冻结物的原样副本]
├── raw/
│   ├── P8-NAV/
│   │   └── robot_id/date_id/block_id/method_id/
│   │       ├── calibration_attempts/
│   │       ├── validation_attempts/
│   │       ├── navigation_episodes/
│   │       └── video/
│   └── P8-SHIFT/
│       └── robot_id/date_id/shift_id/block_id/method_id/
│           ├── sequence_bag/
│           ├── native_reference/
│           └── video/
├── exported/
│   ├── session_metadata.csv
│   ├── block_schedule_executed.csv
│   ├── attempt_ledger.csv
│   ├── calibration_samples.csv.gz
│   ├── calibration_trials.csv
│   ├── validation_trials.csv
│   ├── planner_candidates.csv.gz
│   ├── navigation_trace.csv.gz
│   ├── episode_metrics.csv
│   ├── shift_monitor_metrics.csv
│   ├── shift_recovery_metrics.csv
│   ├── safety_events.csv
│   ├── state_machine_trace.csv
│   ├── time_sync_diagnostics.csv
│   └── posterior_index.csv
├── posterior/
│   └── [run_id]/posterior_v0000.npz ...
├── reference/
│   ├── reference_to_base_extrinsic.yaml
│   ├── frame_tree.pdf-or.svg
│   ├── calibration_report.md
│   └── native_logs/
├── maps/
│   ├── geometry/
│   ├── survey/
│   └── photos/
├── metadata/
│   ├── robot_inventory.csv
│   ├── battery_inventory.csv
│   ├── payload_measurements.csv
│   ├── surface_measurements.csv
│   ├── topic_map.yaml
│   ├── operator_log.md
│   └── deviations.md
├── manifests/
│   ├── run_manifests/
│   ├── bag_metadata/
│   └── delivery_manifest.json
└── checksums.sha256
```

目录必须只读备份至少两份。交付前随机抽取至少 5% rosbag 做 reopen/playback 检查。

存储容量不能在正式采集当天临时估计。DEV dry run 先测量“一小时完整 bag +
视频”的真实字节数，再按下式预留：

```text
primary_capacity >= measured_bytes_per_hour × planned_recording_hours × 1.5
total_capacity   >= primary_capacity × 3
```

其中三份为采集盘、一份现场备份、一份异地/服务器备份。对本协议的 bag、参考
和视频规模，建议起步准备每份至少 2 TB；如果 dry run 推算更高，以推算值为准。
任何一份存储剩余空间低于单日预计数据量的 2 倍时，不开始新 block。

---

## 12. 必需表结构

### 12.1 `session_metadata.csv`

```text
session_id,date_id,start_utc,end_utc,robot_id,robot_model,robot_serial,
firmware_version,sdk_version,source_commit,container_digest,config_sha256,
reference_sensor,reference_serial,reference_config_sha256,extrinsic_sha256,
time_sync_method,time_offset_ms,time_jitter_ms,terrain_id,surface_id,
payload_total_kg,payload_added_kg,payload_com_x_m,payload_com_y_m,
gait_id,battery_id,battery_start_ratio,battery_end_ratio,
operator_id,safety_operator_id,location,weather_or_indoor,
floor_temperature_c,notes
```

正式数据中这些字段不得填 `unknown`、空字符串或猜测值。

### 12.2 `block_schedule_executed.csv`

```text
dataset_role,block_id,robot_id,date_id,shift_id,planned_method_order,
executed_method_order,planned_map_order,executed_map_order,schedule_seed,
schedule_sha256,start_utc,end_utc,deviation,approved_deviation_reason
```

### 12.3 `attempt_ledger.csv`

```text
dataset_role,run_id,session_id,block_id,shift_id,map_id,method_id,
trial_or_episode_id,attempt_id,execution_order,bag_path,video_path,
start_timestamp_ns,end_timestamp_ns,status,technical_failure_code,
algorithm_outcome,selected_for_export,reference_valid,command_log_valid,
safety_abort,collision,serious_safety_event,operator_notes
```

允许的 `status`：

- `complete`
- `pre_measure_abort`
- `technical_abort`
- `safety_abort`
- `timeout`

`timeout`、算法性 safety abort、碰撞和未到达均是有效 outcome，不是技术排除理由。

### 12.4 `calibration_samples.csv.gz`

每行是一条真实采样，不是 trial 均值：

```text
dataset_role,run_id,session_id,block_id,shift_id,map_id,method_id,
trial_id,attempt_id,phase,sample_index,source_timestamp_ns,
receive_timestamp_ns,monotonic_ns,posterior_version,
planned_vx,planned_vy,planned_wz,candidate_vx,candidate_vy,candidate_wz,
safe_vx,safe_vy,safe_wz,transmitted_vx,transmitted_vy,transmitted_wz,
ack_vx,ack_vy,ack_wz,ack_available,
ref_pose_x,ref_pose_y,ref_pose_yaw,
ref_cov_xx,ref_cov_xy,ref_cov_xyaw,ref_cov_yy,ref_cov_yyaw,ref_cov_yawyaw,
reference_tracking_state,reference_frame_id,
onboard_pose_x,onboard_pose_y,onboard_pose_yaw,
velocity_vx,velocity_vy,velocity_wz,base_height,roll,pitch,
battery_ratio,localization_valid,safety_accepted,safety_reason_codes,
aborted,abort_reason
```

### 12.5 `calibration_trials.csv` / `validation_trials.csv`

```text
dataset_role,run_id,block_id,shift_id,map_id,method_id,trial_id,
source,posterior_version,cmd_vx,cmd_vy,cmd_wz,
measured_vx,measured_vy,measured_wz,
predicted_vx,predicted_vy,predicted_wz,
residual_vx,residual_vy,residual_wz,
cov_xx,cov_xy,cov_xw,cov_yy,cov_yw,cov_ww,
sample_count,duration_s,median_rate_hz,max_gap_s,clock_offset_ms,
steady_ratio,command_deviation,valid,invalid_reason,safety_events,
raw_bag_ref,raw_time_start_ns,raw_time_end_ns
```

validation 行必须标明 `source=held_out_validation`，并证明未用于 update。

### 12.6 `planner_candidates.csv.gz`

```text
dataset_role,run_id,block_id,method_id,planner_step,posterior_version,
candidate_rank,cmd_vx,cmd_vy,cmd_wz,score,information_gain,cost,
task_weighted,safety_accepted,safety_reason_codes,selected,
candidate_pool_sha256,planner_config_sha256
```

### 12.7 `navigation_trace.csv.gz`

```text
run_id,block_id,map_id,method_id,episode_id,sample_index,
source_timestamp_ns,receive_timestamp_ns,monotonic_ns,posterior_version,
waypoint_index,target_x,target_y,
desired_vx,desired_vy,desired_wz,
inverse_target_vx,inverse_target_vy,inverse_target_wz,
compensated_vx,compensated_vy,compensated_wz,
transmitted_vx,transmitted_vy,transmitted_wz,
ack_vx,ack_vy,ack_wz,ack_available,
velocity_feedback_active,height_guard_active,high_rate_interlock_active,
stall_recovery_active,stall_recovery_attempts,
ref_pose_x,ref_pose_y,ref_pose_yaw,
ref_cov_xx,ref_cov_xy,ref_cov_xyaw,ref_cov_yy,ref_cov_yyaw,ref_cov_yawyaw,
reference_tracking_state,reference_frame_id,
onboard_pose_x,onboard_pose_y,onboard_pose_yaw,
base_height,roll,pitch,velocity_vx,velocity_vy,velocity_wz,
localization_valid,collision,success,finished,
safety_accepted,safety_reason_codes,serious_safety_event
```

### 12.8 `episode_metrics.csv`

```text
run_id,block_id,map_id,method_id,episode_id,success,collision,
timeout,safety_abort,arrival_time_s,completion_time_s,path_length_m,
arrival_x,arrival_y,goal_distance_at_arrival_m,
final_x,final_y,goal_distance_m,
stall_recovery_attempts,height_guard_updates,high_rate_interlock_updates,
minimum_base_height_m,maximum_abs_roll_rad,maximum_abs_pitch_rad,
maximum_zero_command_latency_ms,reference_valid_ratio,
serious_safety_event,raw_bag_ref,video_ref
```

失败 episode 的 `completion_time_s` 统一写 frozen timeout，不得缺失或只对成功 episode 计算。

### 12.9 P8-SHIFT 表

`shift_monitor_metrics.csv`：

```text
run_id,shift_id,block_id,method_id,context_stage,monitor_trial,
cmd_vx,cmd_vy,cmd_wz,measured_vx,measured_vy,measured_wz,
predicted_vx,predicted_vy,predicted_wz,normalized_nis,cusum,
positive_evidence_count,alarm,detected,detection_delay_trials,
valid,safety_events,shift_marker_timestamp_ns
```

`shift_recovery_metrics.csv`：

```text
run_id,shift_id,block_id,method_id,recovery_trial,source,
cmd_vx,cmd_vy,cmd_wz,measured_vx,measured_vy,measured_wz,
predicted_vx,predicted_vy,predicted_wz,rolling_rmse,target_rmse,
recovered,posterior_version,valid,invalid_reason,safety_events
```

### 12.10 `safety_events.csv`

```text
event_id,run_id,block_id,method_id,shift_id,map_id,
event_timestamp_ns,event_source,event_type,reason_codes,
decision_timestamp_ns,zero_command_timestamp_ns,
zero_command_latency_ms,measured_stop_timestamp_ns,
physical_stop_latency_ms,manual_estop,collision,
serious_safety_event,operator_confirmation,bag_ref,video_ref,notes
```

### 12.11 其余必需索引表

`posterior_index.csv`：

```text
run_id,block_id,shift_id,map_id,method_id,posterior_version,
created_timestamp_ns,update_source_trial_id,feature_set,prior_scale,
mean_shape,covariance_shape,noise_variance_json,snapshot_path,
snapshot_sha256,planner_config_sha256,validation_leakage_check
```

`state_machine_trace.csv`：

```text
run_id,block_id,method_id,timestamp_ns,previous_state,event,next_state,
transition_legal,reason_code,posterior_version,trial_or_episode_id,
safety_latched,operator_action
```

`time_sync_diagnostics.csv`：

```text
session_id,timestamp_ns,clock_source,peer_or_sensor_id,offset_ms,
jitter_ms,round_trip_ms,sync_locked,source_timestamp_valid,
diagnostic_source,valid,invalid_reason
```

`delivery_manifest.json` 至少包含：

- dataset title、protocol version、`DEV/CONFIRM` role；
- source commit、container digest、全部 config/schedule/map/command hashes；
- robot/session/block/method/map/shift 的期望和实际计数；
- raw、exported、posterior、video、reference 文件计数和总字节数；
- 技术无效、算法失败、安全 abort、collision、serious event 计数；
- 生成时间、生成工具版本和生成者；
- checksums 文件名；不得把 manifest 中自报的 `GO` 当验收结论。

---

## 13. 现场数据质量硬门槛

### 13.1 calibration / validation

| 检查 | 目标 | 硬拒收线 |
|---|---:|---:|
| measure duration | 2.0 s | 1.90–2.10 s |
| reference samples | 约 101 | ≥80 个真实样本 |
| median reference rate | 50 Hz | 40–60 Hz |
| timestamp | 严格递增 | 任何重复/倒退均拒收 |
| maximum reference gap | 约 0.02 s | ≤0.10 s |
| clock offset | ≤5 ms | ≤10 ms |
| command deviation | 接近 0 | 三轴范数最大偏差 `<1e-3` |
| steady ratio | ≥0.80 | ≥0.65 |
| finite values | 100% | 不允许 NaN/inf |

低质量 complete trial 不能由现场根据误差大小删除。先保留，再由冻结质量规则标记 `valid=false`。

### 13.2 navigation

- reference valid ratio ≥0.95；
- control/command trace coverage ≥0.99；
- reference gap ≤0.10 s；
- episode 起终点和 map frame 一致；
- 每个 sample key `(run_id, sample_index)` 唯一；
- completion、collision、timeout、abort 均有唯一终止原因；
- metrics 可从 trace 重算；
- collision 必须有传感器、几何或视频证据；
- 任何 serious event 均保留。

### 13.3 posterior 和 planner

- 初始化状态和每次 update 后均有 NPZ/JSON snapshot；
- posterior version 单调递增；
- means、covariances、noise variance 全部有限；
- candidate pool、task distribution 和 planner config 有 hash；
- 所选 candidate 必须出现在 candidate table；
- safety 拒绝原因完整；
- B0 不得更新，B1/B2/B3/B4/B5/B6/B8 trial 数必须精确。

---

## 14. 中止、失败、重采和排除

### 14.1 可以技术性重采

仅限在看到 outcome 前可客观判断的故障：

- rosbag 未启动或文件损坏；
- 独立参考完全失效/跳 frame；
- frozen schedule 或 config 加载错误；
- 非算法原因的网络/电源/场地中断；
- 人员误入安全区；
- trial/episode marker 缺失，无法恢复边界。

原 attempt 仍必须保留，并在 ledger 中写明。
`technical_failure_code` 只能从冻结词表选择：

```text
RECORDER_NOT_STARTED
BAG_CORRUPT
REFERENCE_DROPOUT
REFERENCE_FRAME_JUMP
TIME_SYNC_UNLOCKED
CONFIG_OR_SCHEDULE_MISMATCH
EXTERNAL_NETWORK_OR_POWER
UNPLANNED_HUMAN_ENTRY
MARKER_UNRECOVERABLE
FACILITY_INTERRUPTION
```

新增 failure code 必须由数据负责人和独立审计者共同批准并写入
`deviations.md`；不得创建 `POOR_RESULT`、`HIGH_RMSE` 或同义技术代码。

### 14.2 不可因结果重采

以下都是有效结果：

- RMSE 高；
- active 选到表现不佳但安全的命令；
- 未检测到 shift；
- 恢复慢或未恢复；
- 导航 timeout；
- 算法 safety abort；
- 碰撞；
- 路径长；
- B8 输给 baseline。

每个 run 的第一个 protocol-complete attempt 进入分析。不得挑选最好 attempt。

### 14.3 样本量规则

- P8-NAV 预先计划 30 个完整 paired blocks；
- P8-SHIFT 每个 shift 预先计划 20 个完整 paired blocks；
- 仅技术无效 block 可按 schedule 规则补采；
- 不根据 p-value、效果大小或“看起来已经够好”提前停止；
- 若不慎多采，所有 protocol-complete blocks 全部纳入；
- confirmatory 数据开始后不得降低 n。

---

## 15. 预注册统计分析和发表门槛

### 15.1 通用

- 主要重采样单位：paired block；
- paired bootstrap：10,000 次，固定 analysis seed；
- rate 使用两侧 95% Clopper–Pearson interval；
- 配对连续 endpoint 同时报 mean difference、median、95% CI 和 win rate；
- 主要比较预先固定；secondary comparisons 使用 Holm correction；
- 另做 mixed-effects sensitivity analysis：method 为 fixed effect，day/robot/block 为 grouping factors；
- 不能将 trial/sample/time-step 当独立 n。

DEV pilot 只能用于确认 30/20 blocks 对最小有意义效应具有至少 80% power。若不足，必须在任何 CONFIRM 数据前提高并冻结 n。

### 15.2 P8-NAV primary gates

除明确写为全局检查的 budget、validity 和 safety 项外，下表的 rate、时间、
win-rate 和 noninferiority gate 必须在 **6 个地图上分别通过**。不允许将
简单地图和困难地图池化后掩盖单图失败。matched comparison 必须对
`B2_lhs`、`B3_sobol`、`B4_d_opt`、`B5_active_no_task` 和 `B6_random`
分别计算；不能先挑出最有利的 baseline。

| Gate | 门槛 |
|---|---:|
| map coverage | 6/6 |
| paired blocks | ≥30 |
| B8 success point estimate | ≥0.90 |
| B8 success exact lower bound | ≥0.80 |
| B8 collision point estimate | ≤0.05 |
| B8 collision exact upper bound | ≤0.15 |
| B8 vs B0 completion-time improvement CI lower | >0 s |
| B8 vs B0 win rate | ≥0.80 |
| B8 vs B1/matched success NI | lower CI ≥−0.10 |
| baseline minus B8 collision NI | lower CI ≥−0.10 |
| B8/B1 completion-time ratio CI upper | ≤1.25 |
| B8/matched completion-time ratio CI upper | ≤1.25 |
| B8/B1 calibration budget | ≤0.40 |
| minimum valid calibration ratio | ≥0.90 |
| maximum serious safety events | 0 |
| maximum software zero-command latency | ≤40 ms |

30 blocks 无法支持仿真中 72/72 对应的 `exact lower ≥0.90 / upper ≤0.05` 强 rate bound。若论文坚持把这些更严格 exact gates 原样用于实机，每个 map 必须采至少 72 个 paired blocks；不得用 30 个 block 声称通过 72-block 精度门槛。

### 15.3 P8-SHIFT primary gates

下表除全局 safety 项外，必须在 **4 个 shift 上分别通过**。不得用一个容易
检测的 shift 补偿另一个 shift 的 missed detection 或恢复失败。

| Gate | 门槛 |
|---|---:|
| shift coverage | 4/4 |
| paired blocks per shift | ≥20 |
| pre-shift false alarm point estimate | ≤0.05 |
| detection rate | ≥0.90 |
| recovery rate | ≥0.90 |
| median/p95 detection delay | ≤5 / ≤5 trials |
| median/p95 recovery trials | ≤10 / ≤12 trials |
| `passive - full` early RMSE CI lower | >0 |
| one-sided paired Wilcoxon | p≤0.05 |
| full terminal RMSE bootstrap upper | ≤0.14 m/s |
| minimum valid observation ratio | ≥0.85 |
| maximum serious safety events | 0 |
| maximum software zero-command latency | ≤40 ms |

exact rate intervals必须报告。20 blocks 的 interval 精度低于 72-seed 仿真，论文必须明确区分，不得把实机和仿真 n 混写。

### 15.4 科研偏差检查

分析报告必须逐项回答：

- 是否把 50 Hz 行数当独立样本；
- 是否按结果排除/重采；
- 是否看过结果后改 n 或门槛；
- 是否存在 method×day、method×battery、method×map-order 混杂；
- validation commands 是否泄漏进模型；
- reference 是否独立于被测估计器；
- collision 是否只对 B8 更严格判定；
- complete failure 是否被误标为 technical failure；
- 是否只报告成功地图/shift；
- 多重比较是否按预注册处理；
- failed confirmation 是否被保留。

---

## 16. 每日标准操作流程

### 开始前

- [ ] 确认 frozen release 全部 SHA-256。
- [ ] `git status`/container digest 与 release 一致。
- [ ] 机器人、足端、支架、LiDAR/marker 无松动或损伤。
- [ ] 电池起始比例 ≥0.60；低于 0.25 停止新 block。
- [ ] 参考定位静止 30 s，无 frame jump。
- [ ] +x、+y、+yaw 方向检查通过。
- [ ] 时间 offset ≤5 ms，且小于 10 ms 硬线。
- [ ] 物理急停、软件急停、heartbeat timeout 均实测。
- [ ] 场地清空，软障碍物和地图坐标复测。
- [ ] 固定相机录制和同步 marker 正常。
- [ ] 新建空、write-once session root。

### 每个 block

- [ ] 按 frozen schedule 执行，不手动选方法。
- [ ] 每个方法 posterior reset 并记录 v0000。
- [ ] calibration/validation trial 数精确。
- [ ] held-out validation 不 update。
- [ ] 地图顺序与 schedule 一致。
- [ ] 每个 episode 前 start pose 在容差内。
- [ ] raw bag、reference、video、marker 同时存在。
- [ ] complete failure 保留。
- [ ] 技术重采有 ledger 和原因。
- [ ] block 结束立即运行结构/数量/时间同步 QC。

### 每日结束

- [ ] schedule 计划数与实际数一致。
- [ ] 所有 bag 可打开。
- [ ] 生成当日 checksums。
- [ ] 复制到第二存储介质并抽样校验。
- [ ] `unknown`/空元数据数量为 0。
- [ ] 安全事件与视频时间戳对齐。
- [ ] 记录任何偏离，不补写虚构信息。
- [ ] 在拆地图/外参前完成快速复算。

---

## 17. 交付前自动和人工验收

### 17.1 自动检查

- 所有 frozen release hash 一致；
- 所有原始/导出文件 hash 一致；
- 每个 manifest 的 source commit/config/container/robot 信息完整；
- block/method/map/shift Cartesian product 完整；
- trial/episode ID 唯一；
- sample timestamp 严格递增；
- 所有必需数值有限；
- raw→export 可重放；
- exported metrics 可从 trace 独立重算；
- posterior、candidate、safety decision 可追溯；
- attempt ledger 覆盖 raw 目录中的每个 attempt；
- checksums 不含 self-entry；
- 没有静默覆盖。

### 17.2 人工检查

- 随机抽查每个方法、每个 map、每个 shift 至少 2 个视频；
- 人工复核全部 collision、timeout、abort 和 serious-event 候选；
- 核对载荷照片、称重和坐标；
- 核对 friction surface 批次和状态；
- 核对 start/goal/obstacle survey；
- 核对所有排除理由与原始 bag；
- 确认未出现结果导向排除。

---

## 18. 最终交付签字表

### 软件冻结

- [ ] `Go2RosBackend` 非占位实现。
- [ ] backend hardware gate 全部通过。
- [ ] NAV/SHIFT/safety config 已提交并 hash。
- [ ] schedule、candidate pool、validation commands、maps 已冻结。
- [ ] 任何 DEV 数据均与 CONFIRM IDs 分离。

### 实机与安全

- [ ] 机器人型号/序列号/固件/SDK 完整。
- [ ] 实机 envelope 经 commissioning 和安全负责人批准。
- [ ] 仿真 base-height 阈值未直接照搬。
- [ ] E-stop 和 watchdog 可独立工作。
- [ ] serious safety events 为 0。
- [ ] 所有 abort latency 有原始时间戳。

### 参考与同步

- [ ] ground truth 为独立 mocap/LiDAR odometry。
- [ ] 已转换到 Go2 base frame。
- [ ] 外参、frame tree 和 native logs 齐全。
- [ ] 参考实际采样 ≥40 Hz，目标 ≥50 Hz。
- [ ] 时钟 offset ≤10 ms，目标 ≤5 ms。
- [ ] 视频可与 bag 对齐。

### P8-NAV

- [ ] 30 个完整 paired blocks。
- [ ] 至少 5 个独立日期/时间块。
- [ ] 8 个方法全部存在。
- [ ] calibration 3,060 trials。
- [ ] validation 1,920 trials。
- [ ] navigation 1,440 episodes。
- [ ] 6 个 map 的几何、照片和 survey 齐全。
- [ ] complete failures 未排除。

### P8-SHIFT

- [ ] 4 个 shift 定义全部冻结且可测量。
- [ ] 每个 shift ≥20 个完整 paired triplets。
- [ ] 240 个 sequences、10,800 motion trials 目标完整。
- [ ] frozen/passive/full 使用相同初始条件。
- [ ] shift marker 只给 evaluator，不泄漏给 detector。
- [ ] 缺失 recovery window 使用 0.25 penalty。

### 数据与科研完整性

- [ ] 原始 rosbag、native reference、视频均保留。
- [ ] attempt ledger 覆盖成功和失败 attempt。
- [ ] 没有按 RMSE/成功率选择重采。
- [ ] 没有 optional stopping。
- [ ] 没有把 sample rows 当独立 n。
- [ ] 所有文件有 SHA-256 和第二份备份。
- [ ] 能从 raw 重建全部 exported tables。
- [ ] failed confirmation 若存在，已单独保留和报告。

签字：

```text
运行负责人：________________  日期：________________
独立安全员：________________  日期：________________
数据负责人：________________  日期：________________
软件冻结负责人：____________  日期：________________
PI/论文负责人：______________  日期：________________
```

---

## 19. 该数据能够支持和不能支持的论文表述

全部 gate 通过后，可以支持：

> CalibAgent 在冻结的真实 Go2 在线实验中，以 12 个主动标定 trial
> 改善了 raw 下游导航，并在预注册门槛内与 30-trial dense 和多个
> matched-budget controls 非劣。

若 P8-SHIFT 也通过，可以支持：

> 在四类受控真实 Go2 域偏移下，full 方法相对 passive 更新改善了
> 早期恢复误差，并满足检测、恢复、终端精度和安全门槛。

不能自动支持：

- 所有 Go2 个体或所有四足机器人上的泛化；
- 户外、楼梯、高速、拥挤人群或未知地形安全；
- 未测试 payload/friction/firmware 的泛化；
- 无监督长期自主部署；
- 比所有 calibration 方法普遍优越；
- 零风险或形式化安全保证。

一台机器人、一个实验室和冻结低速 envelope 得到的是可信的真实硬件验证，不是无限外推。

---

## 20. 厂商与本项目参考

- Unitree Go2 官方产品页（型号、速度和载荷参数会因版本变化）：
  <https://www.unitree.com/go2/>
- Unitree Go2 官方手册入口：
  <https://www.unitree.com/app/go2/>
- Unitree 官方开发文档：
  <https://support.unitree.com/home/en/developer/>
- 本项目 P1 实机交付规范：
  `docs/p1_go2_real_data_collection_handoff_zh.md`
- 本项目强 P6/P7 冻结协议：
  `docs/p6_p7_strong_confirmatory_protocol.md`

正式实验必须以现场实际型号的最新厂商手册和本地安全制度为准；产品页中的最大性能不能作为实验命令目标。
