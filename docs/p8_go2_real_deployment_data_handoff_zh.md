# CalibAgent P8：Go2 实机实验计划

本文只规定 P8 的实验设计、执行顺序、记录内容和分析单位。

P8 runner、配置、CLI 和数据导出已实现；启动命令、单 block 调试和恢复命令见
`docs/p8_go2_implementation_guide_zh.md`。正式数据仍必须使用本文冻结的 schedule、
命令表、物理 shift 参数和统计单位。

## 1. 实验问题与范围

P8 包含两个互不替代的数据集：

1. `P8-NAV`：比较不同标定方法对真实 Go2 导航结果的影响；
2. `P8-SHIFT`：比较动力学变化后 `frozen`、`passive`、`full` 三种恢复方法。

`P8-NAV` 只使用两条路线：

- `real_offset_slalom`
- `real_weighted_arc`

`P8-SHIFT` 使用四种变化：

- `R1_command_gain_coupling`
- `R2_payload_com`
- `R3_surface_friction`
- `R4_mixed_context`

P7 的六地图仿真不属于 P8 实机数据。

## 2. 公共实验设置

### 2.1 统计单位

- `P8-NAV` 的独立样本是一个完整 `paired_block_id`；
- `P8-SHIFT` 的独立样本是某个 shift 下的一个完整 `paired_block_id`；
- trial、控制周期和传感器行只用于构造 block 指标，不能当作独立样本。

所有方法在同一 block 中使用相同初始条件、命令表、地图定义和参考定位。
每个方法都从相同 prior 独立开始，不能共享真实 observation 或 posterior。

### 2.2 单次速度 trial

| 阶段 | 时长 | 用途 |
|---|---:|---|
| ramp-in | 0.6 s | 从零命令过渡到目标命令 |
| settle | 0.8 s | 等待运动稳定 |
| measure | 2.0 s | 计算真实速度 observation |
| ramp-out | 0.6 s | 回到零命令 |

一次 trial 的 commanded-motion 共 4.0 s。模型只使用 `measure` 窗口；该窗口内
目标命令保持不变。每次 trial 记录期望命令、实际发送命令、参考位姿、状态时间戳、
observation、有效性和终止原因。

### 2.3 运行前固定的文件

正式数据开始前固定以下内容，正式数据期间不再更改：

- 机器人、固件、locomotion policy 和 CalibAgent commit；
- 两张路线的坐标、waypoint、障碍物、起点、终点和 60 s timeout；
- NAV/SHIFT candidate pool、固定设计、seed、validation commands；
- 四个 shift 的实际参数及其测量记录；
- method/block/map/shift 执行顺序；
- reference-to-base 外参和时钟换算；
- prior、feature set、模型参数及分析脚本版本。

这些内容分别写入 YAML/CSV，并由 run manifest 记录文件 SHA-256。

## 3. P8-NAV

### 3.1 方法

| ID | 标定策略 | 标定 trial 数 |
|---|---|---:|
| `B0_raw` | 不标定；identity/raw baseline | 0 |
| `B1_dense` | 固定 dense design | 30 |
| `B2_lhs` | 固定 LHS design | 12 |
| `B3_sobol` | 固定 Sobol design | 12 |
| `B4_d_opt` | Bayesian D-optimal | 12 |
| `B5_active_no_task` | 6 个固定 seed + 6 个 uniform IVR | 12 |
| `B6_random` | 从固定 candidate pool 随机选择 | 12 |
| `B8_full` | 6 个固定 seed + 6 个 task-weighted IVR | 12 |

八种方法使用 `m1_affine`。除 `B0_raw` 外，其余方法使用同一个 calibration-to-command
变换接口。`B0_raw` 直接使用 planner 的期望速度。命令链中不得再增加第三套速度
补偿、限幅、slew、反馈或 locomotion 干预逻辑。

validation commands 不用于模型更新。每个方法只标定一次，然后使用同一 posterior
依次跑两张路线；导航期间不更新模型。

### 3.2 每个 block

每个 NAV block 包含：

| 内容 | 计算 | 数量 |
|---|---:|---:|
| calibration trials | `30 + 6×12` | 102 |
| validation trials | `8 methods × 8 commands` | 64 |
| navigation episodes | `8 methods × 2 maps` | 16 |

正式实验执行 30 个完整 blocks，总计：

- 3,060 calibration trials；
- 1,920 validation trials；
- 480 navigation episodes；
- 240 个 method-final posterior snapshots。

### 3.3 block 执行顺序

对 schedule 中的每个 method：

1. 将该方法的模型重置为统一 prior；
2. 按方法定义完成 calibration；
3. 保存 posterior；
4. 运行 8 个 held-out validation commands；
5. 按该 block 指定的 `AB` 或 `BA` 顺序跑两张路线；
6. 保存 method 级结果后进入下一个 method。

8 个 method 的顺序在 30 个 blocks 中做位置平衡。两张路线在每个 method 内使用
15 次 `AB` 和 15 次 `BA`。不能让某个 method 固定绑定某一天、电池或路线顺序。

### 3.4 navigation episode

1. 将机器人和定位状态重置到地图起点；
2. 载入该 method 的 posterior 和地图；
3. 启动 rosbag、episode marker 和视频；
4. 运行统一 waypoint planner，直到到达、碰撞或 60 s timeout；
5. 记录轨迹、action、终止原因和 episode metrics；
6. 回到起点后进入下一 episode。

成功定义为在 60 s 内进入 `goal_radius=0.25 m` 且没有碰撞。碰撞和 timeout 都是
实验结果，不因表现不好而重跑。

### 3.5 NAV 指标

每张路线分别计算：

- success rate、collision rate；
- completion time；失败 episode 按 60 s 计；
- path length、横向/航向跟踪误差；
- held-out velocity RMSE；
- calibration budget 和有效 observation 比例。

主要比较是 `B8_full` 对 `B0_raw`、`B1_dense` 及五个 matched-budget baseline。
报告 paired block 差值、95% bootstrap CI 和原始 block 值，不把两张路线合并成
`n=60`。

## 4. P8-SHIFT

### 4.1 方法和模型

| ID | 变化后的行为 |
|---|---|
| `frozen` | posterior 保持不变 |
| `passive` | 使用固定 recovery commands 更新 posterior |
| `full` | 扩大 posterior covariance，并主动选择 recovery commands |

三种方法使用 `m2_affine_cross_hinge`，分别执行 pre-shift calibration 并维护独立
posterior。算法输入不包含 shift ID 或 shift 生效时刻。

### 4.2 四种 shift

| ID | 实施方式 | 记录内容 |
|---|---|---|
| `R1_command_gain_coupling` | 在 calibration command transform 中启用固定 gain/coupling matrix | matrix 与启用时间 |
| `R2_payload_com` | 安装固定质量和固定位置的载荷 | 质量、位置、照片 |
| `R3_surface_friction` | 切换到固定材料的地面区域 | 材料、表面状态、照片 |
| `R4_mixed_context` | 固定载荷、地面和 task profile 的组合变化 | 三个组成量与启用时间 |

shift 参数在正式数据前由配置文件固定。每个 sequence 只施加一次 shift；不能因为
检测失败而再次施加。

### 4.3 每个 sequence

每个 `shift × block × method` sequence 执行：

| 阶段 | trial 数 | 模型更新 |
|---|---:|---|
| pre-shift calibration | 12 | 是 |
| pre-shift monitor | 4 | 否 |
| 应用 shift | 1 次 | 不产生 observation |
| post-shift monitor | 5 | 否；只运行 detector |
| recovery | 12 | `passive/full` 更新，`frozen` 不更新 |
| interleaved validation | 12 | 否 |

一个 sequence 有 45 个进入主分析的 motion trials。每个 shift 执行 3 个完整 paired
blocks，每个 block 包含三个 method；三个 block 轮换 method 的执行位置，因此总计：

- 4 shifts × 3 blocks × 3 methods = 36 sequences；
- 36 × 45 = 1,620 motion trials；
- 36 × 2 = 72 个 context restore checks（不进入主 endpoint）。

这里的 block 是实机重复单位，主要分析保留 paired block 原始值和效应量。`n=3` 只支持
实机可行性和大效应比较，不把 sequence 内的 trial 伪装成独立重复。若后续需要对小效应
给出高精度置信区间，应另立扩展计划，不能在看到当前结果后选择性增加某个 method 的 block。

12 个 recovery step 全部执行。每个 recovery step 后立即执行对应 held-out validation，
用于得到随 recovery step 变化的 RMSE 曲线。

sequence 结束后恢复 nominal context，并用 2 个固定 check commands 验证残差已回到
该 sequence 的 nominal 范围；这两个 check 不进入主 endpoint。未恢复时继续恢复
context，不能把受 shift 影响的状态带入下一个 method。

### 4.4 SHIFT 指标

每个 shift 分别计算：

- pre-shift false-alarm rate；
- detection rate 和 detection delay；
- recovery step 1–4 的 early RMSE；
- recovery step 9–12 的 terminal RMSE；
- 达到预设 RMSE 阈值所需 recovery trials；
- 有效 observation 比例。

主要比较是 `full` 相对 `passive` 的 paired early/terminal RMSE，以及 `full` 的
detection/recovery 结果。每个 shift 的 `n=3`，不能把四个 shift 合并成 `n=12`，也不能
把同一 sequence 内的 trial 当作独立重复。

## 5. 数据记录与目录

每个 run 至少保存：

```text
p8_real/<run_id>/
├── manifest.json
├── schedule.csv
├── configs/
├── bags/
├── video/
├── trials.csv
├── navigation_episodes.csv
├── navigation_trace.parquet
├── shift_sequences.csv
├── planner_decisions.parquet
├── posterior/
└── analysis/
```

`manifest.json` 记录 commit、配置 hash、机器人、固件、日期、reference 配置和数据文件
hash。`trials.csv` 至少包含：

- run/block/method/map/shift/trial identity；
- planned command、实际发送 command；
- phase 起止时间和消息时间戳；
- observation、covariance、valid/reason；
- posterior version 和是否更新；
- rosbag/video 时间范围；
- terminal reason。

NAV 还记录每个 control tick 的 scan/reference age、policy 输入、policy action、实际发送
action 和机器人状态。SHIFT 还记录 detector statistic、alarm、shift marker、recovery
index 和 validation RMSE。

## 6. 无效数据与重跑

- 算法失败、碰撞、timeout、未检测到 shift、恢复慢或误差大：保留为有效结果；
- 只有数据文件损坏、参考定位缺失、进程崩溃或命令未发出等技术故障可以重跑；
- 重跑保留原记录，并用新的 `attempt_id` 指向原 attempt；
- 不能根据结果好坏删除 block、method、map 或 shift；
- 缺失值不填零，不使用相邻 trial 补值。

## 7. 完成条件

实验完成必须同时满足：

- NAV 有 30 个完整 paired blocks；
- 每个 shift 有 20 个完整 frozen/passive/full paired blocks；
- 每个 planned unit 都有结果或明确的技术故障记录；
- posterior、原始 bag、逐 trial/episode 表、schedule、config 和 manifest 可相互追溯；
- 分析以 paired block 为单位并覆盖全部方法、两张路线和四个 shift。
