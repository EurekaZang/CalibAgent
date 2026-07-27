# CalibAgent P8：Go2 实机软件实现与仿真代码导读

> 面向对象：没有参与 P0–P7 仿真的 ROS 2、Unitree SDK、定位、控制和数据工程同事。
> 目标：说明已有算法、仿真验证、代码入口、P8 缺口和实机联调顺序。
> 安全边界：本文是实现指南，不授权机器人运动。正式运动必须同时满足
> `docs/p8_go2_real_deployment_data_handoff_zh.md` 的安全与冻结门槛。

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan
- Origin Date: 2026-07-27
- Verification Status: REVIEWED AGAINST TRACKED SOURCE TREE
- Version Label: `p8_go2_implementation_guide_v1`

---

## 1. 从 GitHub 获取唯一代码版本

项目 GitHub：

```text
https://github.com/EurekaZang/CalibAgent
```

克隆后不要直接追随以后变化的 `main` 做确认性实验。软件负责人会提供
`P8_FROZEN_COMMIT`：

```bash
git clone https://github.com/EurekaZang/CalibAgent.git
cd CalibAgent
git fetch --tags origin
git checkout --detach P8_FROZEN_COMMIT
git status --short
git rev-parse HEAD
```

要求：

- `git status --short` 为空；
- `git rev-parse HEAD` 与 release 中 `source_commit.txt` 完全一致；
- 不在 robot 上临时修改代码；
- 必须修复时创建新分支、新 commit、新容器 digest，重新走 DEV/HIL gate；
- 正式数据的 manifest 必须写入完整 40 位 commit。

当前仓库的 `main` 是 P0–P7 和 P8 协议代码源，不代表 P8 backend 已完成。
`env/unitree_sdk_commit.txt` 当前仍是 `UNSET-P8-NOT-INTEGRATED`；软件负责人
必须在确认性采集前写入实际 Unitree SDK/ROS bridge commit。

---

## 2. 先理解系统边界

CalibAgent 不替代 Go2 底层 locomotion controller。软件链为：

```text
固定任务/waypoint planner
        │ desired body velocity
        ▼
inverse compensator + bounded feedback
        │ proposed Go2 command
        ▼
hard safety filter ───────────────┐
        │ accepted command         │ reject/fault
        ▼                          ▼
Go2RosBackend / Unitree bridge   zero command + latched abort
        │
        ├── actual transmitted/ACK command
        ├── onboard state / IMU / BMS / fault
        └── independent reference pose
                    │
                    ▼
          MeasurementPipeline
                    │ TrialObservation
                    ▼
   Bayesian model / shift detector / planner
```

需要严格区分：

- `desired velocity`：导航希望机器人达到的机身速度；
- `candidate command`：标定 planner 提出的候选；
- `safe command`：通过 hard safety filter 的命令；
- `transmitted command`：真正送到 Unitree bridge 的 setpoint；
- `ACK/effective command`：SDK 能返回时记录控制器接受的命令；
- `measured velocity`：从独立参考 pose 重算，不是 onboard odometry。

任何分析都不能用 `desired` 或 `candidate` 冒充 `transmitted`。

---

## 3. P0–P7 仿真和软件验证导读

### P0：与机器人无关的接口

关键文件：

- `src/calibagent/interfaces/types.py`
- `src/calibagent/interfaces/protocols.py`
- `docs/architecture.md`
- `docs/adr/ADR-001-public-contracts.md`

`RobotBackend` 只有四个方法：

```python
reset(context) -> None
get_state() -> RobotState
execute_trial(command, policy) -> RawTrialData
emergency_stop(reason) -> None
```

实机团队的首要任务是实现这个 port，而不是改模型和 planner。

### P1：真实 Go2 离线数据管线

关键文件：

- `src/calibagent/measurement/pipeline.py`
- `src/calibagent/eval/real_delivery.py`
- `src/calibagent/eval/real_replay.py`
- `data/calibration_extracted/calibration/go2_plan_capture_runner.py`
- `evidence/p1_capture/plan.csv`

P1 runner 是已执行过的 ROS 2 采集参考，包含：

- `/cmd_vel` ramp/settle/measure/ramp-out；
- `/Odometry`、localization health、实际命令订阅；
- plan hash 校验、场地半径、回原点；
- attempt ledger 和逐样本导出。

它只能作为 P8 的 trial/记录实现线索，不能直接作为 P8 完成代码：

- 它是被动执行冻结 P1 plan，不会在线调用 active planner；
- 现场曾以约 20 Hz 参考采样运行，低于 P8 目标；
- 没有 P8 完整 rosbag/video/posterior/candidate/safety schema；
- 不包含 P8-NAV navigation runner 或 P8-SHIFT orchestration；
- 不能替代独立物理急停和 watchdog。

### P2/P3：模型和主动实验设计

关键文件：

- `src/calibagent/core/models/features.py`
- `src/calibagent/core/models/bayesian.py`
- `src/calibagent/core/planning/candidates.py`
- `src/calibagent/core/planning/samplers.py`
- `src/calibagent/core/planning/d_optimal.py`
- `src/calibagent/core/planning/ivr.py`
- `src/calibagent/core/planning/task.py`
- `src/calibagent/eval/benchmark.py`

可直接复用的核心算法：

- `BayesianBasisModel`：posterior update、predict、save/load；
- `IntegratedVariancePlanner`：task-weighted active IVR；
- `DOptimalPlanner`：matched-budget baseline；
- LHS、Sobol、random 和 dense 设计；
- 冻结 candidate pool 和 task distribution。

实机 adapter 必须把每个有效 `TrialObservation` 交给这些 API。不得为了接 ROS
而复制一套“简化版”模型；否则仿真和实机不再是同一算法。

### P4：安全、状态机和停止

关键文件：

- `src/calibagent/core/safety/filter.py`
- `src/calibagent/core/runtime/state_machine.py`
- `src/calibagent/core/stopping/rules.py`
- `src/calibagent/eval/p4_benchmark.py`
- `configs/experiments/p4_safety_stop_main.yaml`

已经验证的逻辑：

- 非有限、过期、定位无效、姿态/高度/电池异常 fail closed；
- command axis、线速度范数、线角耦合、slew 和 projected workspace；
- 没有安全候选时返回 `NO_SAFE_CANDIDATE`，而不是执行次优危险命令；
- 非法状态转换拒绝；
- safety/error 可从任意非终态直接进入 ABORT；
- stopping 必须经过 held-out validation 和 patience。

真机必须重新冻结 envelope 数值，但不能删除这些检查类别。

### P5：Isaac Lab 闭环

关键文件：

- `src/calibagent/backends/isaaclab.py`
- `sim/isaaclab/calibagent_sim/runner.py`
- `sim/isaaclab/calibagent_sim/policy.py`
- `configs/experiments/p5_isaaclab_main.yaml`

P5 将模型和 planner 接到 Isaac Lab/PhysX Go2 与冻结 locomotion policy。
`IsaacLabBackend` 展示了正确的 adapter 思路：外部 driver 实现 robot-specific
细节，核心包只看 `RobotBackend`。

不可复制到真机的部分包括 PhysX state、仿真 reset、仿真 friction/mass event、
仿真 base-height 阈值和 Isaac policy checkpoint。

### P6：shift 检测和恢复

关键文件：

- `src/calibagent/core/shift/detector.py`
- `sim/isaaclab/calibagent_sim/p6_runner.py`
- `src/calibagent/eval/p6_isaaclab.py`
- `configs/experiments/p6_domain_shift_strong_confirmatory.yaml`

阅读 `p6_runner.py` 时重点看：

1. frozen/passive/full 三种方法如何隔离；
2. monitor residual 如何进入 `DomainShiftDetector`；
3. alarm 后如何做 posterior inflation；
4. passive 如何使用固定恢复设计；
5. full 如何调用 IVR planner；
6. held-out validation 如何形成 rolling RMSE；
7. 达到 recovery gate 后如何停止更新但继续记录。

真机 shift 必须由外部 marker 留给 evaluator，不能把 shift label/time 传给
detector。

### P7：标定后的固定规划导航

关键文件：

- `src/calibagent/core/compensation/inverse.py`
- `sim/isaaclab/calibagent_sim/p7_runner.py`
- `src/calibagent/eval/p7_isaaclab.py`
- `configs/experiments/p7_navigation_strong_confirmatory_v2.yaml`

阅读 `p7_runner.py` 时重点看：

1. 每种方法如何独立初始化 posterior；
2. B0/B1/B2/B3/B4/B5/B8 的数据隔离；
3. `ConstrainedInverseCompensator` 如何从期望速度反解安全命令；
4. velocity feedback、height guard、stall recovery 的调用次序；
5. 相同 planner/map/policy 如何跨方法保持不变；
6. timeout、collision、abort 如何保留为失败；
7. posterior、calibration、navigation trace 如何写 manifest。

P7 runner 是编排参考，不可直接 import 到 ROS 节点：它依赖 Isaac Lab scene、
simulation tensors 和并行 environments。

---

## 4. 代码成熟度清单

| 模块 | 当前状态 | 实机使用方式 |
|---|---|---|
| public types/protocols | 已实现、已测试 | 直接 import |
| measurement pipeline | 已实现、P1 真实数据验证 | 直接复用，输入必须来自独立参考 |
| Bayesian model/features | 已实现、已测试 | 直接复用 |
| candidate/samplers/IVR/D-opt | 已实现、已测试 | 直接复用 |
| task distribution | 已实现、已测试 | 直接复用 |
| hard safety logic类别 | 已实现、已故障注入 | 复用代码，真机重新冻结阈值 |
| state machine/stopping | 已实现、已测试 | 直接复用并记录 transition |
| shift detector | 已实现、已测试 | 直接复用 |
| inverse compensator | 已实现、已测试 | 直接复用 |
| Isaac Lab runners | 已实现、仿真证据完成 | 只作 P8 orchestration 参考 |
| P1 ROS 2 capture runner | 已有历史实机版本 | 只作 topic/trial/ledger 参考 |
| `Go2RosBackend` | **占位，全部方法 fail closed** | P8 必须实现 |
| P8 NAV/SHIFT runner | **尚未实现** | P8 必须实现 |
| Unitree SDK/bridge pin | **尚未冻结** | P8 必须选择、记录 commit |
| 独立 E-stop/watchdog | **仓库内尚无实机实现** | 必须独立实现和故障注入 |
| P8 exporter/validator | **协议已有 schema，工具尚未实现** | 必须在 CONFIRM 前实现 |

这张表是当前真实状态。不得把“算法代码已完成”汇报成“P8 已可采数据”。

---

## 5. `Go2RosBackend` 必须怎样实现

目标文件：

```text
src/calibagent/backends/go2_ros.py
```

建议把 Unitree/ROS 细节放在独立 driver，backend 只适配 contract：

```text
Go2RosBackend
├── Go2CommandDriver
├── Go2StateReader
├── IndependentReferenceReader
├── TrialRecorder
├── SafetyWatchdog
└── ClockDiagnostics
```

### 5.1 `reset(context)`

必须：

- 发送并确认零命令；
- 验证 control mode/gait 与冻结配置一致；
- 清空 trial-local buffer，不删除已有原始文件；
- 检查 reference health、timestamp age、frame tree；
- 检查 BMS/motor/temperature/network；
- 记录新的 session/trial marker；
- 不能隐式重置全局 attempt ledger 或覆盖已有 output。

### 5.2 `get_state()`

返回 `RobotState`，但同时在 raw bag 保留完整原始消息。最低字段：

- 单调时间戳；
- world/map 中的 base x/y/yaw；
- roll、pitch、base height；
- body velocity；
- battery ratio；
- localization validity。

如果任一安全关键字段缺失、非有限或超龄，`localization_valid=false`，并让
watchdog 进入零命令；不能用最后一个旧值伪装当前状态。

### 5.3 `execute_trial(command, policy)`

必须严格执行：

```text
PRECHECK → RAMP_IN → EXCITE/SETTLE → MEASURE → RAMP_OUT
         → VALIDATE → UPDATE/ABORT
```

每个 control tick：

1. 读取新 state；
2. 运行 execution-time safety monitor；
3. 检查 heartbeat/reference/SDK ACK；
4. 发布当时 phase 对应的命令；
5. 记录 planned、safe、transmitted、ACK、state 和 timestamps；
6. fault 时先零命令，再 latched abort，再写事件。

返回的 `RawTrialData.pose_se2` 必须来自独立参考，`command` 必须是实际发送
setpoint。rosbag 路径放入 `raw_ref`。

### 5.4 `emergency_stop(reason)`

最低语义：

- 可重入：调用多次仍安全；
- 不等待模型、planner、磁盘 flush 或 reference；
- 立即发布零命令，并调用批准的 Unitree stop/damping API；
- latch 后普通命令不能自动恢复；
- 记录 decision time、publish time、ACK time 和物理停止 time；
- Python 进程崩溃时仍有独立 watchdog/bridge 停止机器人。

物理 E-stop 不能只调用此 Python 方法；它必须有独立链路。

---

## 6. ROS 2 / Unitree topic contract

现场 topic 名可以不同，但必须在 `topic_map.yaml` 映射：

| 逻辑通道 | 示例 topic | 方向 | 硬要求 |
|---|---|---|---|
| desired command | `/calibagent/desired_cmd` | internal→log | 每个 planner tick |
| safe command | `/calibagent/safe_cmd` | filter→driver | 每个 control tick |
| actual transmitted command | `/go2_capture/actual_cmd_vel` | bridge→log | ≥50 Hz |
| SDK ACK/effective command | site-specific | Go2→log | 有则必须记录 |
| independent base pose | `/mocap/base` 或 `/Odometry` | reference→backend | ≥40 Hz，目标 ≥50 Hz |
| reference health | `/loc_health` | reference→watchdog | 状态变化和 heartbeat |
| onboard state | site-specific | Go2→backend | ≥50 Hz |
| IMU/base height | site-specific | Go2→watchdog | 目标 ≥100 Hz |
| BMS/motor fault | site-specific | Go2→watchdog | ≥10 Hz/事件 |
| phase marker | `/calibagent/trial_marker` | runner→bag | 每个边界 |
| safety event | `/calibagent/safety_event` | watchdog→bag | 事件触发 |
| posterior version | `/calibagent/model_marker` | model→bag | 每次 update |
| shift marker | evaluator-only channel | operator→bag | 不可给 detector |

QoS 必须在 DEV 中做丢包/延迟测试。安全状态优先可靠、有限队列和 deadline；
高率原始传感器可使用合适 sensor QoS，但 recorder 必须报告实际丢包。

---

## 7. 必须新增的 P8 软件

建议目录/API，不强制文件名：

```text
src/calibagent/backends/go2_ros.py
src/calibagent/hardware/go2/
├── driver.py
├── state_reader.py
├── reference.py
├── recorder.py
├── watchdog.py
├── topic_contract.py
├── nav_runner.py
├── shift_runner.py
├── export.py
└── validate_delivery.py
tests/unit/hardware/go2/
tests/integration/hardware/go2/
```

必须实现的功能：

1. Go2 command/state adapter；
2. 独立 reference adapter 和外参变换；
3. actual-command/ACK logging；
4. trial executor；
5. P8-NAV 方法、地图和 posterior 隔离；
6. P8-SHIFT 三方法和 evaluator-only marker；
7. independent watchdog 和 fault latch；
8. rosbag/video/index/manifest 管理；
9. 第 12 节全部 exported schema；
10. raw→export 和 trace→metric 重算；
11. frozen schedule 执行和 write-once output；
12. backend hardware gate 报告。

---

## 8. 实现顺序和每一步通过条件

### Gate A：纯软件

- fake driver 下四个 backend 方法通过；
- 100 次 reset/zero-command；
- state stale/nonfinite/invalid 全部 fail closed；
- 每类 illegal transition 都进入异常或 ABORT；
- raw→observation 与 P1 replay 一致；
- posterior save/load 后预测一致；
- 不需要连接机器人。

### Gate B：ROS graph，无运动

- `--arm` 默认关闭；
- 所有 required topics、QoS、频率、age 和 frame 检查通过；
- rosbag、marker、posterior、candidate 和 manifest 能完整写出；
- output root 非空时拒绝覆盖；
- 拔掉 reference/network/进程后 watchdog 发零命令；
- 机器人保持物理架起或不使能运动。

### Gate C：HIL/低速

- 100 次零命令/reset；
- 30 次低速 ramp trial；
- 网络、reference、state、进程、非法命令各至少 10 次故障注入；
- 最大 `safety decision→zero-command publish` ≤40 ms；
- 物理停止时间单独报告；
- 0 serious event。

### Gate D：DEV pilot

- 每种 NAV 方法至少跑一个完整小 block；
- 每个 shift 至少跑一个 frozen/passive/full triplet；
- raw bag、video、reference、posterior 和 export 可重放；
- 只检查流程和 power，不据此挑选有利方法或门槛；
- 完成真实 envelope、地图、shift 和 sample size 冻结。

### Gate E：CONFIRM

只有 A–D、冻结 release、checksums 和签字全部通过才允许开始。之后不改方法、
地图、门槛、n 或排除规则。

---

## 9. 外部依赖与“不在本仓库”的边界

GitHub 仓库存储 CalibAgent 自有源码、配置、测试、紧凑证据和协议。以下依赖
不能被误认为已随仓库提供：

| 外部项 | 当前状态 | P8 要求 |
|---|---|---|
| Unitree SDK/ROS bridge | 未 vendored，pin 未设置 | 由实机团队选择合法版本，记录 repo/commit/license |
| Go2 固件 | 不可能随仓库存储 | 记录版本和升级策略 |
| FAST-LIO/mocap stack | 现场已有或另行安装 | 记录 repo/commit/config 和外参 |
| 物理 E-stop/安全 PLC | 硬件系统 | 提供接线、测试和维护记录 |
| Isaac Lab/Isaac Sim | 仅复现实验 P5–P7 需要 | P8 robot host 不需要安装 |
| Unitree/Isaac policy checkpoint | 外部下载并 hash | 真机底层 controller 不得由仿真 checkpoint 替换 |
| `data/`、`outputs/` | 本地大体量 raw/regenerable 数据，gitignored | 不通过 GitHub 交正式 P8 raw；使用受控数据存储 |

任何 P8 自编的 Python/C++/launch/config/schema/test 都属于 CalibAgent 交付代码，
必须在 CONFIRM 前提交到 GitHub；不得只留在某台机器人 `/home/...` 工作区。
第三方代码不应复制进本仓库规避许可证，而应记录上游 URL、commit、patch 和
构建说明。

---

## 10. 实机团队开始工作时应向软件负责人索取

- GitHub URL 和 `P8_FROZEN_COMMIT`；
- 与 commit 对应的 container digest；
- Unitree SDK/bridge URL、commit 和本地 patch；
- `p8_real_safety.yaml`；
- NAV/SHIFT frozen configs；
- schedule、candidate pool、validation commands 和 map files；
- `topic_map.yaml` 和 frame tree；
- backend hardware gate report；
- exporter、validator 和 analysis 命令；
- checksums 和已通过的 DEV dry-run；
- 数据上传位置及访问权限。

如果其中任何一项不存在，应记录为 P8 blocker，不允许由现场人员根据猜测补齐。

---

## 11. 最小阅读顺序

1. `README.md`
2. `docs/p8_go2_real_deployment_data_handoff_zh.md`
3. 本文
4. `docs/architecture.md`
5. `src/calibagent/interfaces/types.py`
6. `src/calibagent/interfaces/protocols.py`
7. `src/calibagent/backends/go2_ros.py`
8. `data/calibration_extracted/calibration/go2_plan_capture_runner.py`
9. `sim/isaaclab/calibagent_sim/p6_runner.py`
10. `sim/isaaclab/calibagent_sim/p7_runner.py`
11. safety、shift、inverse 三个 core 模块

先理解 contract 和 safety，再实现 ROS/Unitree glue；不要从复制整个仿真 runner
开始。
