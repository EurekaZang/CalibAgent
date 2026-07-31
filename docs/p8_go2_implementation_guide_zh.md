# CalibAgent P8：Go2 实机软件完整实现规格（Coding Agent 执行版）

> 面向对象：第一次拿到本 GitHub 仓库、没有参与 P0–P7 的 Codex、Claude Code
> 或人工开发者。
>
> 本文目标：使 coding agent 能从当前仓库实现 P8 所有项目自有的实机代码、
> ROS 2 glue、运行脚本、数据导出、验收和分析工具，而不需要从聊天记录猜设计。
>
> 当前事实：本文是**实现规格，不是已实现声明**。截至 2026-07-31，
> `src/calibagent/backends/go2_ros.py` 仍是 fail-closed 占位，P8 runner、独立
> watchdog、P8 exporter/validator 和实机确认数据均未完成。

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan
- Origin Date: 2026-07-31
- Verification Status: REVIEWED AGAINST TRACKED P0–P7 SOURCE AND P8 HANDOFF V2
- Version Label: `p8_go2_implementation_spec_v2_two_map_nav`
- Scientific protocol: `docs/p8_go2_real_deployment_data_handoff_zh.md`
- Repository: `https://github.com/EurekaZang/CalibAgent`

---

## 0. 如何使用本文

### 0.1 文档权威顺序

若文件之间发生冲突，按下面顺序处理；coding agent 不得自行选择一个“看起来
合理”的版本：

1. `docs/p8_go2_real_deployment_data_handoff_zh.md`：科学问题、样本量、安全、
   排除规则和论文 claim 的权威来源；
2. 本文：源码布局、接口、状态机、命令语义、CLI、测试和 Definition of Done；
3. 冻结后的 P8 YAML/CSV/JSON Schema：具体数值和现场绑定；
4. P6/P7 runner：算法顺序和仿真实现参考；
5. P1 runner：ROS 2 topic health、phase、attempt ledger 和参考定位采集参考。

仍无法消解时必须 fail closed，记录 blocker，并修改协议/实现规格后再编码；不得
把现场猜测写成默认值。

### 0.2 本轮已经冻结的范围

P8-NAV 实机只做两张地图：

```text
real_offset_slalom
real_weighted_arc
```

P8-SHIFT 保留全部四类：

```text
R1_command_gain_coupling
R2_payload_com
R3_surface_friction
R4_mixed_context
```

P7 仿真仍是六张地图。不得修改 P7 config、P7 evidence、README 中的六图仿真
事实，也不得把 P8 两图写成 P7 只有两图。

### 0.3 三层完成语义

| 状态 | 含义 | 允许做什么 |
|---|---|---|
| `SOFTWARE_COMPLETE` | 纯 Python、generic Twist command adapter、fake/replay、schemas、CLI 和 CI 全通过 | 不允许宣称已接通真实 Go2 |
| `HARDWARE_INTEGRATED` | 已根据冻结的现场 topic/SDK/bridge 实现并通过无运动和 HIL gate | 只允许 DEV，不允许 CONFIRM |
| `CONFIRM_READY` | 两图、四 shift、命令表、阈值、schedule、release、硬件和签字全部冻结 | 才允许确认性采集 |

“代码已提交”不等于上述任何状态。每个状态必须由机器可读 gate report 支撑。

---

## 1. 不可改变的实验合同

### 1.1 P8-NAV 规模

方法集合及规范枚举顺序固定为；每个 block 的实际执行顺序由第 14 节冻结
schedule 决定：

```text
B0_raw
B1_dense
B2_lhs
B3_sobol
B4_d_opt
B5_active_no_task
B6_random
B8_full
```

每个 paired block：

| 单元 | 计算 | 数量 |
|---|---:|---:|
| calibration trials | `30 + 6×12` | 102 |
| held-out validation trials | `8×8` | 64 |
| navigation episodes | `8×2` | 16 |
| 调度运动单元 | `166 trials + 16 episodes` | 182 |

30 个 paired blocks：

```text
calibration = 3,060 trials
validation  = 1,920 trials
navigation  =   480 episodes
posterior   = 至少 240 个 method-final snapshots
```

每个 method 在一个 block 内只标定一次、validation 一次，然后用同一 posterior
跑两图。不得按地图重标定，navigation 期间不得 update。
论文主要统计的 `n=30 paired blocks`，不是 182 个运动单元。

Gate D 前的独立 `DEV` schedule 只含 5 个完整 paired blocks，但仍运行全部 8 methods
和两条路线：`510` calibration trials、`320` validation trials、`80` navigation
episodes。它与 30-block CONFIRM 使用不同 run/release/schedule/block-ID namespace，
只能估计 readiness，不能并入论文的 `n=30`。

### 1.2 P8-SHIFT 规模

每个 `shift × block × method` sequence：

```text
12 pre-shift calibration
 4 pre-shift monitor
 5 post-shift monitor
12 recovery trials
12 interleaved held-out validation trials
=45 primary motion trials
```

```text
4 shifts × 20 blocks × 3 methods = 240 sequences
240 × 45 = 10,800 primary motion trials
```

每个 sequence 恢复 nominal 后另做 2 个 sentinel；sentinel 不进入主要 endpoint，
但必须进入 raw bag、attempt ledger 和 checksum。因此完整计划还包含 480 个
planned sentinel units，即 11,280 个 planned motion units。若 sentinel 失败后
修复并复验，额外 attempt 保留但不增加 planned unit 数，所以实际 raw
attempts 可以大于 11,280。

三种方法只共享 prior、命令设计和 shift 定义；每种方法必须独立执行 12 个
pre-calibration trial，禁止共享真实 observation 或 posterior。

Gate D 前的独立 `DEV` schedule 对每个 R1–R4 只含 5 个完整 paired blocks：共
`4×5×3=60` sequences、`2,700` primary motion trials 和 `120` initial planned
sentinel units。它们不能并入每 shift `n=20` 的 CONFIRM 数据。

### 1.3 唯一实机 trial profile

```text
PRECHECK/WARM-UP  >=0.5 s  # commanded-motion 之外
RAMP_IN             0.6 s
SETTLE/EXCITE       0.8 s
MEASURE             2.0 s
RAMP_OUT            0.6 s
```

“4.0 s trial”只指四个 commanded-motion phase；包括 precheck 后总墙钟时间至少
4.5 s。恒定目标命令的等效位移预测时间为：

```text
0.5×0.6 + 0.8 + 2.0 + 0.5×0.6 = 3.4 s
```

calibration 的 projected-workspace precheck 必须使用 3.4 s，而不是只用 2.0 s
measure duration。P6/P7 仿真的短 profile 不是实机配置来源。

### 1.4 feature set

```text
P8-NAV   = m1_affine
P8-SHIFT = m2_affine_cross_hinge
```

runner 不得从数据自动选择 feature set。`BasisTransformer` 的 standardizer 只在
冻结 candidate/reference pool 上 fit，不在实机 observation 或 validation target
上 fit。

### 1.5 B0 的准确语义

`B0_raw` 是完整 raw-stack ablation：

```text
waypoint desired
    → 跳过 inverse compensator 和 outer velocity feedback
    → 与其他方法完全相同的 slew
    → height/interlock/stall safety
    → pre-transform safety → identity transform → wire safety → relay
```

它不运行 posterior inverse compensator，也不运行 outer velocity feedback。
除 `B0_raw` 外的七种方法才共享同一 inverse compensator 和 velocity feedback。所有方法仍共享
waypoint planner、gait、地图、启动条件、slew、hard safety 和终止判据。

---

## 2. 当前仓库：复用什么，缺什么

### 2.1 必须直接复用的实现

| 能力 | 权威文件 | 使用方式 |
|---|---|---|
| public contracts | `src/calibagent/interfaces/types.py`、`protocols.py` | 保持四方法 `RobotBackend` port |
| measurement | `src/calibagent/measurement/pipeline.py` | 只处理 measure-window 独立 reference pose |
| Bayesian model | `src/calibagent/core/models/` | 直接复用 update/predict/save/load/inflate |
| candidate/planners | `src/calibagent/core/planning/` | 直接复用 pool、IVR、D-opt、LHS、Sobol |
| safety | `src/calibagent/core/safety/filter.py` | planner 前过滤；实机另加 freshness/fault/watchdog |
| trial state machine | `src/calibagent/core/runtime/state_machine.py` | 增加明确的 no-update transition |
| shift detector | `src/calibagent/core/shift/detector.py` | detector API 不得增加 shift marker 输入 |
| inverse/feedback | `src/calibagent/core/compensation/inverse.py` | 除 B0 外的七种 NAV 方法共享 |
| P1 field pattern | `data/calibration_extracted/calibration/go2_plan_capture_runner.py` | 只参考 topic health、marker、ledger、fail closed |
| P6 sequence | `sim/isaaclab/calibagent_sim/p6_runner.py` | 参考 detector/inflation/recovery 顺序 |
| P7 navigation | `sim/isaaclab/calibagent_sim/p7_runner.py` | 提取纯 waypoint 数学并做 parity test |

不得复制一套 ROS 专用模型、planner、detector 或 measurement 算法。

### 2.2 当前缺口

当前仓库没有以下完成物：

- 实现后的 `Go2RosBackend`；
- Unitree bridge/SDK pin 和现场 message contract；
- 独立 command relay/watchdog；
- reference/onboard state adapters；
- P8 NAV/SHIFT runners；
- P8 config、两张实机 map、冻结 command tables 和 schedules；
- append-only journal、crash resume；
- P8 raw exporter、delivery validator、confirmatory analyzer；
- P8 ROS tests、HIL report 和 confirmatory data。

因此 coding agent 必须新增独立 P8 层，不能把 `P7BenchmarkConfig` 改名后使用。
P7 validator 硬编码至少三图、强方法不含 `B6_random`，语义也仍是 Isaac Lab。

---

## 3. 目标源码树：文件名是规范，不是建议

完成后仓库至少应存在：

```text
src/calibagent/core/navigation/
├── __init__.py
├── controller_state.py
└── waypoint.py

src/calibagent/hardware/go2/
├── __init__.py
├── contracts.py
├── config.py
├── clock.py
├── frames.py
├── state_reader.py
├── reference.py
├── command_path.py
├── operator_gate.py
├── reset_coordinator.py
├── recorder.py
├── journal.py
├── safety_review.py
├── watchdog.py
├── trial_executor.py
├── model_factory.py
├── methods.py
├── schedule.py
├── nav_runner.py
├── shift_actuators.py
├── shift_runner.py
├── export.py
├── validate_delivery.py
├── analysis.py
├── replay.py
├── release.py
└── fake.py

src/calibagent/backends/go2_ros.py
src/calibagent/eval/p8_real.py

src/calibagent/cli/
├── p8_config_validate.py
├── p8_generate_schedules.py
├── p8_preflight.py
├── run_p8_nav.py
├── run_p8_shift.py
├── p8_retry_unit.py
├── p8_review_safety.py
├── p8_reset_abort.py
├── p8_sign_approval.py
├── p8_replay.py
├── export_p8_delivery.py
├── validate_p8_delivery.py
├── analyze_p8_confirmatory.py
├── audit_p8_source.py
├── audit_p8_cli_help.py
└── freeze_p8_release.py

ros2/
├── calibagent_p8_msgs/
├── calibagent_go2/
└── calibagent_go2_watchdog/

configs/experiments/
├── p8_real_nav_dev_template.yaml
├── p8_real_nav_confirmatory_template.yaml
├── p8_real_shift_dev_template.yaml
├── p8_real_shift_confirmatory_template.yaml
├── p8_safety_review_criteria.yaml
└── p8_analysis_plan_template.yaml

configs/hardware/go2/
├── p8_real_safety.yaml
├── human_trust_registry.example.yaml
├── human_trust_registry.yaml       # 现场人员公钥批准后才出现
├── topic_map.example.yaml
├── topic_map.yaml                 # 现场冻结后才出现
├── reference_to_base_extrinsic.example.yaml
└── reference_to_base_extrinsic.yaml # 现场标定、批准后才出现

configs/maps/
├── real_offset_slalom.yaml
├── real_weighted_arc.yaml
└── evidence/
    ├── real_offset_slalom/
    │   ├── survey.csv
    │   └── overview_photo.jpg
    └── real_weighted_arc/
        ├── survey.csv
        └── overview_photo.jpg

configs/commands/
├── nav/
│   ├── candidate_pool.csv
│   ├── feature_reference_pool.csv
│   ├── dense_design.csv
│   ├── lhs_design.csv
│   ├── sobol_design.csv
│   ├── random_design.csv
│   ├── active_seed.csv
│   ├── validation_commands.csv
│   └── task_distribution.csv
└── shift/
    ├── candidate_pool.csv
    ├── feature_reference_pool.csv
    ├── pre_calibration_seed.csv
    ├── pre_monitor.csv
    ├── post_monitor.csv
    ├── validation_commands.csv
    ├── passive_recovery.csv
    ├── task_nominal.csv
    ├── r4_task_pre.csv
    ├── r4_task_post.csv
    ├── restore_sentinel.csv
    └── nominal_restore_thresholds.yaml

schemas/p8/
├── common.schema.json
├── topic_map.schema.json
├── safety_config.schema.json
├── reference_extrinsic.schema.json
├── nav_config_template.schema.json
├── shift_config_template.schema.json
├── nav_config.schema.json
├── shift_config.schema.json
├── schedule.schema.json
├── schedule_manifest.schema.json
├── map_geometry.schema.json
├── map_survey.schema.json
├── shift_evidence_content.schema.json
├── shift_evidence.schema.json
├── preflight_report.schema.json
├── static_preflight_report.schema.json
├── operation_report.schema.json
├── resolved_config.schema.json
├── event_journal.schema.json
├── protocol_checkpoint.schema.json
├── block_session_initialization.schema.json
├── runtime_initialization_result.schema.json
├── scientific_unit_result.schema.json
├── planner_decision.schema.json
├── runtime_state.schema.json
├── transition_trace.schema.json
├── prepared_attempt.schema.json
├── frozen_safety_state.schema.json
├── command_preauthorization.schema.json
├── physical_attempt_artifact.schema.json
├── unit_artifact.schema.json
├── nominal_restore_reference.schema.json
├── actuation_receipt.schema.json
├── shift_receipt.schema.json
├── transform_proof.schema.json
├── global_state_proof.schema.json
├── quota_record.schema.json
├── reset_authorization.schema.json
├── bag_segment_index.schema.json
├── bag_range_inventory.schema.json
├── watchdog_state.schema.json
├── human_trust_registry.schema.json
├── human_approval_request.schema.json
├── human_approval.schema.json
├── operator_gate_receipt.schema.json
├── scope_authorization_request.schema.json
├── scope_authorization.schema.json
├── arm_authorization.schema.json
├── safety_review.schema.json
├── safety_review_criteria.schema.json
├── safety_review_bundle.schema.json
├── safety_review_decision.schema.json
├── safety_review_receipt.schema.json
├── data_lock.schema.json
├── data_lock_commit.schema.json
├── gate_report.schema.json
├── backend_hardware_gate_report.schema.json
├── hil_event_log.schema.json
├── hil_case_result.schema.json
├── hil_trigger.schema.json
├── hil_result.schema.json
├── hil_zero_receipt.schema.json
├── gate_evidence_manifest.schema.json
├── source_audit_report.schema.json
├── cli_help_audit_report.schema.json
├── robot_dependency_manifest.schema.json
├── integration_stage_manifest.schema.json
├── dev_release_manifest.schema.json
├── candidate_manifest.schema.json
├── tools_manifest.schema.json
├── release_manifest.schema.json
├── analysis_plan_template.schema.json
├── analysis_plan.schema.json
├── confirmatory_analysis.schema.json
├── input_lock_manifest.schema.json
├── golden_expected.schema.json
├── delivery_manifest.schema.json
└── exported_tables/
    ├── session_metadata.schema.json
    ├── block_schedule_executed.schema.json
    ├── attempt_ledger.schema.json
    ├── calibration_samples.schema.json
    ├── calibration_trials.schema.json
    ├── validation_trials.schema.json
    ├── planner_candidates.schema.json
    ├── navigation_trace.schema.json
    ├── episode_metrics.schema.json
    ├── shift_monitor_metrics.schema.json
    ├── shift_recovery_metrics.schema.json
    ├── nominal_restore_sentinel_metrics.schema.json
    ├── changeover_evidence_index.schema.json
    ├── safety_events.schema.json
    ├── safety_review_index.schema.json
    ├── state_machine_trace.schema.json
    ├── time_sync_diagnostics.schema.json
    └── posterior_index.schema.json

tests/unit/hardware/go2/
tests/integration/p8/
tests/replay/p8/
tests/hil/p8/
tests/governance/test_p8_source_delivery.py
tests/governance/test_p8_protocol_scope.py
```

`ros2/` 是单独的 colcon workspace source tree；分析环境安装 `calibagent` 时不应
要求 `rclpy`。ROS package 可以 import 已安装的 `calibagent`，但 `core`、
`measurement`、`eval` 不得 import ROS 或 Unitree SDK。

freeze 的 protocol source mapping 只有一套：

```text
docs/p8_go2_real_deployment_data_handoff_zh.md -> protocol/p8_go2_real_deployment_data_handoff_zh.md
docs/p8_go2_implementation_guide_zh.md         -> protocol/p8_go2_implementation_guide_zh.md
configs/experiments/p8_safety_review_criteria.yaml -> protocol/p8_safety_review_criteria.yaml
configs/hardware/go2/{p8_real_safety,topic_map,reference_to_base_extrinsic,human_trust_registry}.yaml -> configs/<same-basename>
```

上述 docs/criteria/hardware source 必须 tracked、通过相应 schema/hash检查并逐字节
复制。四份 experiment config 不是可运行 config，而是无自引用的 tracked template：

```text
configs/experiments/p8_real_{nav,shift}_{dev,confirmatory}_template.yaml
  + source_commit + container digest + role-matched schedule manifest
  --(stage-integration)--> configs/p8_real_{nav,shift}_{dev,confirmatory}.yaml
```

template/final 的 strict schema 分别是 `nav|shift_config_template.schema.json` 和
`nav|shift_config.schema.json`；唯一 materialization 规则在第 6.1 节。analysis plan 使用
唯一无循环 mapping：

```text
configs/experiments/p8_analysis_plan_template.yaml
  + DEV manifests/input_lock_manifest.json raw SHA-256
  --(freeze-release prepare)--> protocol/analysis_plan.yaml
```

template 必须 tracked并通过 strict `p8.analysis-plan-template.v1`；其结构与 final plan
完全相同，但 `power_plan.pilot_input_lock_manifest_raw_sha256` 必须为 JSON/YAML null。
`prepare` 只能将该一个 null 替换为其 `--dev-delivery-root` 中通过 pre-lock
validation 的 input-lock manifest raw hash；其他任一 semantic value 或数组顺序变化都退出 6。
输出用冻结 PyYAML safe-dump profile（UTF-8、LF、`sort_keys=false`、两空格缩进、
Unicode 不转义、文件末尾一个 LF）并通过 strict `p8.analysis-plan.v1`。template/raw hash、
DEV input-lock semantic/raw hash、final plan raw hash 全部写 candidate manifest。不存在未跟踪的现场
plan 或可修改阈值的 CLI。`--analysis-plan` 在 analyzer 中只能解析到 frozen
release copy，不能指向 template 或任意临时文件。

---

## 4. 依赖与 import 边界

### 4.1 强制依赖方向

```text
interfaces ← core / measurement
interfaces + core + measurement ← hardware/go2
hardware/go2 ← backends/go2_ros
installed calibagent ← ros2/calibagent_go2
ROS messages ← ros2/calibagent_go2_watchdog
```

禁止：

- `core` import `rclpy`、ROS message 或 Unitree SDK；
- model/planner 直接 publish ROS topic；
- runner 绕过 `Go2RosBackend` 或独立 command relay 发布 vendor motion topic；
- recorder 的磁盘 I/O 阻塞 watchdog safety path；
- 在 import 时初始化 ROS、打开机器人或创建 output directory。

### 4.2 环境文件

必须补充并由 Git 跟踪的环境输入恰好是：

```text
env/analysis/requirements-p8.lock.txt
env/robot/Dockerfile
env/robot/requirements.lock.txt
env/robot/rosdep.lock-or-install-manifest.txt
env/robot/third_party_robot_dependencies.yaml
env/robot/dependency_evidence/
├── unitree_sdk.LICENSE.txt
├── command_bridge.LICENSE.txt
├── reference_stack.LICENSE.txt
└── patches/                              # 仅 PATCHED 项出现对应固定文件
    ├── unitree_sdk.patch
    ├── command_bridge.patch
    └── reference_stack.patch
```

robot image 必须 pin base image digest、ROS distro、Python dependencies、bridge
commit 和 reference stack commit。三项 robot dependency 的**唯一机器真源**是
`env/robot/third_party_robot_dependencies.yaml`；不得再保留
`unitree_sdk_commit.txt`、Dockerfile comment、README 表格或机器人主机文本作为第二份版本
authority。它通过 strict `p8.robot-dependencies.v1`，顶层 exact fields 为
`schema_version,dependencies,manifest_sha256`，且所有 object
`additionalProperties=false`。`dependencies` 长度恰为 3，按下列顺序、不得重排：

```text
UNITREE_SDK, COMMAND_BRIDGE, REFERENCE_STACK
```

每项 exact fields 为：

```text
dependency_id,repository_url,commit_sha40,license_spdx,
license_evidence_source_path,license_evidence_release_path,license_evidence_raw_sha256,
patch_status,patch_source_path,patch_release_path,patch_raw_sha256
```

`repository_url` 必须是 absolute `https://` 或 `ssh://` repository URL；
`commit_sha40` 必须是 lowercase 40-hex；`license_spdx` 是该 exact commit 的 SPDX
identifier/expression，license evidence source/release path 分别固定为
`env/robot/dependency_evidence/<id-lower>.LICENSE.txt` 和
`environment/dependency_evidence/<id-lower>.LICENSE.txt`，raw hash 必须等于 tracked
source bytes。`patch_status` 仅为 `CLEAN|PATCHED`：`CLEAN` 时三个 patch field 必须均为
JSON null；`PATCHED` 时 source/release path 分别固定为
`env/robot/dependency_evidence/patches/<id-lower>.patch` 与
`environment/dependency_evidence/patches/<id-lower>.patch`，且 raw hash 必须等于 tracked
patch bytes。`manifest_sha256=sha256(JCS(record 排除 manifest_sha256))`。

为了让仓库在现场值尚未知时仍可提交实现骨架，tracked validator 唯一额外允许的占位值是
字符串 `UNSET-P8-NOT-INTEGRATED`：它可暂用于 `repository_url,commit_sha40,license_spdx`
并要求该 dependency 的 `patch_status="UNSET-P8-NOT-INTEGRATED"`、三个 patch field 为 null；
license evidence file 此时也只能是单行同一 sentinel。这个宽限只属于
`config-validate tracked`。`build-gate-a` 可以据此产生 FAIL evidence，但
`stage-integration`、`seal-dev`、`prepare`、`seal` 和任何 PASS Gate 必须在读取到任一
`UNSET`、非 40-hex commit、license hash不符或未映射 patch 时 fail closed；coding agent
不得填猜测 URL/hash/license。

该 manifest、三份 license evidence 和仅在 `PATCHED` 时出现的固定 patch files 的唯一
source→release 映射、`tools_manifest.lock_files` logical name 与 release exact allowlist 见
§23.2。实现只能按 manifest 投影逐文件复制，不得 glob `dependency_evidence/`，也不得把现场
生成或机器人主机上的 dependency 文件临时加入 release。

---

## 5. 纯 Python 硬件合同

所有下面的数据类都放在 `src/calibagent/hardware/go2/contracts.py`。字段可以增加，
但不得删掉本节字段或改变单位。

### 5.1 时间和样本

所有原始样本同时保存：

```python
source_timestamp_ns: int   # 传感器/bridge 自己的时间
receive_timestamp_ns: int  # ROS 接收时间
monotonic_ns: int          # 本机 safety/order 时间
```

Safety age、lease 和 deadline 只用 `monotonic_ns`。source time 用于 reference
运动学和跨设备对齐；ROS time 跳变不能延长 command lease。

最低数据类（下面的 `VelocityCommand` 复用 public contract）：

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

@dataclass(frozen=True)
class ReferenceSample:
    source_timestamp_ns: int
    receive_timestamp_ns: int
    monotonic_ns: int
    frame_id: str
    child_frame_id: str
    pose_se2: tuple[float, float, float]
    covariance_se2: tuple[float, ...]  # row-major 3x3
    tracking_state: str

@dataclass(frozen=True)
class OnboardSample:
    source_timestamp_ns: int
    receive_timestamp_ns: int
    monotonic_ns: int
    roll: float
    pitch: float
    base_height_m: float
    body_velocity: tuple[float, float, float]
    battery_ratio: float
    control_mode: str
    gait_id: str
    onboard_pose_se2: tuple[float, float, float] | None
    motor_faults: tuple[str, ...]
    maximum_motor_temperature_c: float

@dataclass(frozen=True)
class RobotHealthSample:
    source_timestamp_ns: int
    receive_timestamp_ns: int
    monotonic_ns: int
    state_age_ms: float
    imu_age_ms: float
    bms_age_ms: float
    fault_age_ms: float
    network_age_ms: float
    imu_valid: bool
    bms_valid: bool
    network_ok: bool
    physical_estop_ready: bool
    collision_detected: bool
    recorder_ready: bool
    storage_ready: bool
    yaw_rate: float
    battery_voltage_v: float
    bms_faults: tuple[str, ...]
    reason_codes: tuple[str, ...]

@dataclass(frozen=True)
class CommandReceipt:
    boot_id: str
    sequence: int
    requested_monotonic_ns: int
    relay_receive_monotonic_ns: int
    published_monotonic_ns: int
    logical_command: tuple[float, float, float]
    post_transform_command: tuple[float, float, float]
    transmitted_command: tuple[float, float, float]
    ack_command: tuple[float, float, float] | None
    ack_monotonic_ns: int | None
    transform_id: str
    transform_sha256: str
    accepted: bool
    reason_codes: tuple[str, ...]

@dataclass(frozen=True)
class ZeroReceipt:
    action: str
    reason: str
    decision_monotonic_ns: int
    zero_publish_monotonic_ns: int
    bridge_ack_monotonic_ns: int | None
    measured_stop_monotonic_ns: int | None
    zero_confirmed: bool
    robot_stationary: bool
    watchdog_state: str
    reason_codes: tuple[str, ...]

@dataclass(frozen=True)
class DriverHealth:
    ready: bool
    publisher_count: int
    bridge_heartbeat_age_ms: float
    last_publish_echo_age_ms: float
    ack_available: bool
    ack_age_ms: float | None
    reason_codes: tuple[str, ...]

@dataclass(frozen=True)
class RichRobotState:
    cut_monotonic_ns: int
    reference: ReferenceSample
    onboard: OnboardSample
    health: RobotHealthSample
    causal_reference_body_twist: tuple[float, float, float]
    causal_velocity_valid: bool
    command_ack_age_ms: float | None
    runner_heartbeat_age_ms: float
    clock_offset_ms: float
    clock_sync_locked: bool
    reason_codes: tuple[str, ...]
```

`ReferenceSample` 必须来自独立 mocap/LiDAR reference，不得包装 onboard odometry
冒充 ground truth。

### 5.2 attempt identity

```python
@dataclass(frozen=True)
class AttemptIdentity:
    dataset_role: Literal["DEV", "CONFIRM", "TEST_FIXTURE"]
    attempt_role: Literal["PRIMARY", "RERUN_TECH"]
    run_id: str
    session_id: str
    block_id: str
    method_id: str
    scientific_unit_id: str
    unit_type: Literal["nav_calibration", "nav_validation", "nav_episode",
                       "shift_pre_calibration", "shift_pre_monitor",
                       "shift_post_monitor", "shift_recovery",
                       "shift_recovery_validation", "restore_sentinel",
                       "context_return"]
    attempt_uid: str
    attempt_index: int
    retry_of_attempt_uid: str | None
    shift_id: str
    map_id: str
```

`dataset_role` 在技术重采时保持原来的 `DEV` 或 `CONFIRM`；重采身份只由
`attempt_role=RERUN_TECH` 表示，禁止把重采变成第三种数据集后再跨角色拼表。
PRIMARY 必须 `attempt_index=1,retry_of_attempt_uid=None`；RERUN_TECH 必须
`attempt_index>=2` 且引用同一 scientific unit 的直接前一 attempt。`attempt_uid`
在 delivery 内全局唯一；`scientific_unit_id` 必须来自 schedule 的 planned 或
conditional registry，exporter
按 `unit_type` 将它确定性投影到 handoff 表的
`trial_id/episode_id/monitor_trial_id/trial_or_episode_id`。这些列必须在 handoff
指定的导出表中物理存在，但不加入 `AttemptIdentity` 并由多个 runner
独立维护；validator 必须从 `scientific_unit_id` 重算并逐行验证相等。

SHIFT 全部 unit 令 `map_id="NOT_APPLICABLE"`；NAV 的 `nav_calibration`/
`nav_validation` 也写 `NOT_APPLICABLE`，只有 `nav_episode` 写真实两图 ID。
`context_return` 若专门服务于某个 NAV episode 的 start return，写该真实
map ID；其余回位写 `NOT_APPLICABLE`。NAV 的 `shift_id` 固定写
`NOT_APPLICABLE`。`TEST_FIXTURE` 只允许 mini fixture CLI，任何
`--arm`、CONFIRM freeze 或生产 analyzer 遇到它必须拒绝。

#### 5.2.1 run/session 生命周期

session 是一个完整 paired block 的现场元数据边界：NAV 每个 `block_id` 恰一 session，SHIFT
每个 `shift_id × block_id` 恰一 session，block 内全部 8/3 methods 必须使用同一 ID且不能
跨到下一 session。`BLOCK_SESSION_INITIALIZED` 事务在该 block 的任何 method scope前按
canonical format 分配
`session_id="NAV/<run_id>/<block_id>"` 或
`"SHIFT/<run_id>/<shift_id>/<block_id>"`，并绑定 robot/date/battery/reference/config和
schedule row；不是由 wall clock/operator随机生成。source schedule不含 session ID，执行后
`block_schedule_executed` 和全部 identity从该事务投影同一值。

该事务不是内存赋值。runner 先写并 fsync content-addressed
`block_session_initialization_<sha256-prefix>.json`，其字段精确为
`schema_version,dataset_role,run_id,session_id,block_id,shift_id,date_slot,date_id,
robot_id,robot_inventory_sha256,battery_id,battery_inventory_sha256,
reference_config_path,reference_config_sha256,reference_extrinsic_path,
reference_extrinsic_sha256,nominal_context_sha256,source_commit,config_sha256,
schedule_sha256,schedule_row_sha256,created_monotonic_ns`；再 append+fsync
`BLOCK_SESSION_INITIALIZED{result_path,result_sha256,session_id,block_id,shift_id,
config_sha256,schedule_sha256,schedule_row_sha256}`，之后才允许创建该 block 的第一个
runtime INIT 或 scope。幂等 key 固定为 `(dataset_role,run_id,shift_id,block_id)`：同 key、
同 canonical bytes 复用原 commit；同 key、不同 bytes 立即判 `PERSISTENCE_CORRUPT`。
crash/resume 只从 hash-valid commit 恢复 session，不从目录名、wall clock 或 operator 输入
重建。`session_metadata.csv` 与 `block_schedule_executed.csv` 必须回链 result/commit hash，
并逐字段 join；未提交的 candidate 只能标 orphan。

因为 result 含首次分配的 monotonic time，幂等恢复顺序固定为：先按上述 key 查 journal；
已有 commit 就只读其 result ref；没有 commit 时扫描该 key 的 hash-valid candidate，0 个才
分配 time 并写一个，1 个必须逐字复用并补同一 commit，超过 1 个或发现不同 bytes 立即判
corruption。不得在 crash 后以新 time 重建“等价”candidate。fault injection 覆盖 result
file/fsync/rename、journal commit 和首个 INIT 前后，并断言 session result/commit 各恰一。

进程 crash、同 block `--resume-run-id`、context return、conditional sentinel与 RERUN_TECH
沿用原 session ID，只递增 resume epoch/boot；下一个 block才创建下一个 deterministic
session。一个 session内禁止换 robot、battery、reference config、普通 surface/payload或
未登记环境；SHIFT R1–R4 的计划 APPLY/RESTORE 是唯一 context例外，session metadata写
nominal baseline，变化由 changeover evidence逐项记录。启动 block 前必须证明 battery/storage
足够完成；若非计划换电/换场地不可避免，停止且该 block/package不满足完整性，不能用新
session拼接余下 methods。技术重采必须在该 block session正式关闭前闭合。

`session_metadata.csv` 因而 NAV DEV/CONFIRM 分别恰 5/30 行，SHIFT DEV/CONFIRM 分别恰
`4×5=20`/`4×20=80` 行；每行
battery/start/end/context都可真实填写。block可在 crash后恢复，但不得跨计划 date slot；
统计独立单位仍是 block，不把 resume epoch当重复。scope ID、lineage和目录键机械使用当前
BLOCK_SESSION_INITIALIZED ID。测试覆盖 block内 crash/retry保持 ID、下一 block新 ID、恶意
method中途 session切换、battery切换和 session metadata/cardinality join。

### 5.3 其余数据类和失败语义

`contracts.py` 还必须定义下列类，不得在 runner 中用临时 dict
代替：

```python
@dataclass(frozen=True)
class ExperimentEvent:
    identity: AttemptIdentity
    event_type: str
    phase: str
    source_timestamp_ns: int | None
    monotonic_ns: int
    payload: Mapping[str, JSONValue]

@dataclass(frozen=True)
class ChangeoverEvent:
    """Non-motion protocol event; never masquerades as an AttemptIdentity."""
    identity: "ChangeoverIdentity"
    event_type: str
    phase: str
    source_timestamp_ns: int | None
    monotonic_ns: int
    payload: Mapping[str, JSONValue]

@dataclass(frozen=True)
class RunLevelEvent:
    """Journal event with no attempt/changeover identity columns."""
    run_id: str
    event_type: str
    source_timestamp_ns: int | None
    monotonic_ns: int
    payload: Mapping[str, JSONValue]

@dataclass(frozen=True)
class CommandIntent:
    planned: VelocityCommand
    candidate: VelocityCommand
    safe: VelocityCommand
    model_input: VelocityCommand       # R1 matrix 之前
    phase: str
    motion_horizon_s: float
    metadata: Mapping[str, JSONValue]

@dataclass(frozen=True)
class CommandProposal:
    """Runner output before the backend-owned logical safety boundary."""
    planned: VelocityCommand
    candidate: VelocityCommand
    phase: str
    motion_horizon_s: float
    metadata: Mapping[str, JSONValue]

@dataclass(frozen=True)
class LogicalSafetyDecision:
    accepted: bool
    safe_command: VelocityCommand | None
    reason_codes: tuple[str, ...]

@dataclass(frozen=True)
class P8Sample:
    identity: AttemptIdentity
    phase: str
    sample_index: int
    snapshot: RichRobotState
    intent: CommandIntent
    receipt: CommandReceipt

@dataclass(frozen=True)
class AttemptResult:
    """Physical execution result; it is not the scientific/model decision."""
    identity: AttemptIdentity
    status: Literal["complete", "pre_measure_abort", "technical_abort",
                    "safety_abort", "timeout"]
    terminal_reason: str
    start_monotonic_ns: int
    end_monotonic_ns: int
    motion_completed: bool
    measurement_constructed: bool
    technical_failure_code: str | None
    serious_safety_event: bool

@dataclass(frozen=True)
class ScientificUnitResult:
    identity: AttemptIdentity
    physical_commit_event_sha256: str
    physical_status: Literal["complete", "pre_measure_abort", "technical_abort",
                             "safety_abort", "timeout"]
    physical_terminal_reason: str
    status: Literal["complete", "pre_measure_abort", "technical_abort",
                    "safety_abort", "timeout"]
    terminal_reason: str
    technical_failure_code: str | None
    observation_sha256: str | None
    observation_available: bool
    observation_valid: bool | None
    prediction_available: bool
    scientific_valid: bool
    primary_invalid_reason: str | None
    invalid_reason_codes: tuple[str, ...]
    planner_decision_path: str | None
    planner_decision_sha256: str | None
    method_state_before_path: str | None
    method_state_before_sha256: str | None
    method_state_after_path: str | None
    method_state_after_sha256: str | None
    shift_state_before_path: str | None
    shift_state_before_sha256: str | None
    shift_state_after_path: str | None
    shift_state_after_sha256: str | None
    nominal_restore_reference_before_path: str | None
    nominal_restore_reference_before_sha256: str | None
    nominal_restore_reference_after_path: str | None
    nominal_restore_reference_after_sha256: str | None
    transition_trace_path: str
    transition_trace_sha256: str
    update_enabled: bool
    model_update_applied: bool
    posterior_transition_kind: Literal["NONE", "MODEL_UPDATE", "ALARM_INFLATION"]
    posterior_transition_factor: float | None
    posterior_before_sha256: str
    posterior_after_sha256: str
    posterior_before_version: int
    posterior_after_version: int
    scientific_outcome: str
    protocol_complete: bool
    retry_permitted: bool
    selected_for_export: bool
    committed_monotonic_ns: int
```

`scientific_valid` 是 handoff 所有 CSV `valid` 列的唯一来源，但它只表示该 protocol outcome
本身结构/证据有效，不能当“有有效观测”。`observation_available` 只在
`unit_artifact_kind=TRIAL_OBSERVATION` 时为 true，此时 `observation_valid` 必须 non-null；
NAV metrics、context return、pre-observation safety/all-rejected outcome令 available=false、
observation_valid=null。trial 有 observation 时 scientific/numeric validity通常相同，除非
后续 integrity使 scientific result invalid。valid-ratio、monitor NIS/rolling penalty和模型
assimilation只读 `observation_available && observation_valid`，绝不读 `scientific_valid`
充数。`scientific_valid=true` 时 scientific invalid reason必须为空；false 时按 §9.5生成
非空 tuple/primary。
`prediction_available` 独立表示本 unit 的 frozen posterior-before prediction已成功持久；
它不能从 observation/scientific valid推断。NIS/residual要求 prediction和valid observation
同时存在；pre-measure abort可 prediction=true但 observation=false。

NAV 的 method-state 四列 required，SHIFT 的 shift-state 四列 required，另一组必须全
null；独立 `context_return` 仅暂停/恢复所属 cursor，使用适用的 NAV method-state 或 SHIFT
state pair。planner decision 两列要么同时 null，要么同时 non-null，只有 adaptive
selection（含 all-rejected）为 non-null。before/after path/hash conditional 和相应
`SCIENTIFIC_UNIT_COMMIT`/checkpoint 必须逐位相等。

`posterior_transition_kind` 的组合只允许：

- `NONE`：`model_update_applied=false` 且 posterior before/after hash 与 version 逐位相同；
  `posterior_transition_factor=null`；
- `MODEL_UPDATE`：`update_enabled=true,model_update_applied=true`，valid assimilation 令
  after hash不同且 `after_version=before_version+1`，factor=null；
- `ALARM_INFLATION`：只允许 SHIFT monitor 首次 alarm，
  `update_enabled=false,model_update_applied=false`，after hash不同且 version恰加 1，冻结
  `posterior_transition_factor=8.0`。

validation、NAV episode、context return、invalid observation 和 ordinary monitor 必须为
`NONE`。任何其他组合 schema/validator 失败；特别不得把 alarm inflation 报为 model update
或 validation leakage。

artifact 交叉 invariant：`unit_artifact_kind=TRIAL_OBSERVATION` 时
`observation_sha256 == unit_artifact_sha256 != null,observation_available=true` 且
`observation_valid` non-null；`NAV_EPISODE_METRICS|NONE` 时
`observation_sha256=null,observation_available=false,observation_valid=null`。planner
decision 是独立 top-level side artifact，不改变该规则。

```python

@dataclass(frozen=True)
class BagRangeRef:
    bag_group_id: str
    segment_id: str
    start_monotonic_ns: int
    end_monotonic_ns: int

@dataclass(frozen=True)
class ArtifactRefs:
    attempt_artifact_ref: ContentAddressedRef
    raw_uri: str
    bag_range: BagRangeRef
    video_uri: str | None
    immutable_sha256_by_uri: Mapping[str, str]

@dataclass(frozen=True)
class PhysicalAttemptCommit:
    result: AttemptResult
    artifacts: ArtifactRefs
    commit: "JournalCommitRef"

@dataclass(frozen=True)
class SealedBagSegmentRef:
    bag_group_id: str
    segment_id: str
    segment_ordinal: int
    uri: str
    start_monotonic_ns: int
    end_monotonic_ns: int
    segment_sha256: str
    metadata_sha256: str

@dataclass(frozen=True)
class BagRangeInventoryRef:
    path: str
    sha256: str
    inventory_sequence: int
    bag_group_id: str
    through_scientific_unit_id: str

@dataclass(frozen=True)
class ChangeoverMarkerAck:
    result_event_id: str
    result_event_sha256: str
    bag_group_id: str
    segment_id: str
    marker_sequence: int
    marker_sha256: str
    range_start_monotonic_ns: int
    range_end_monotonic_ns: int
    replayed: bool

@dataclass(frozen=True)
class ChangeoverMarkerRecord:
    """Canonical Python projection of ChangeoverMarker.msg."""
    identity: "ChangeoverIdentity"
    changeover_attempt_identity_sha256: str
    changeover_phase_identity_sha256: str
    result_event_id: str
    result_event_sha256: str
    evidence_bundle_sha256: str | None
    actuation_receipt_sha256: str | None
    shift_receipt_sha256: str
    monotonic_ns: int

@dataclass(frozen=True)
class NavigationMarkerRecord:
    """Canonical Python projection of NavigationMarker.msg."""
    identity: AttemptIdentity
    event_sequence: int
    event_type: str
    source_timestamp_ns: int
    monotonic_ns: int
    waypoint_index: int | None
    target_xy: tuple[float, float] | None
    terminal_reason: str | None
    navigation_elapsed_s: float
    posterior_sha256: str

@dataclass(frozen=True)
class JournalCommitRef:
    event_id: str
    event_sha256: str

@dataclass(frozen=True)
class ContentAddressedRef:
    relative_path: str
    semantic_sha256: str
    raw_sha256: str
    size_bytes: int
    schema_version: str

@dataclass(frozen=True)
class RecorderReadiness:
    ready: bool
    output_write_once: bool
    free_bytes: int
    reason_codes: tuple[str, ...]

@dataclass(frozen=True)
class WatchdogReadiness:
    boot_id: str
    status_monotonic_ns: int
    state_sequence: int
    state_sha256: str
    quota_state_sha256: str
    operator_gate_receipt_tail_sha256: str
    active_scope_authorization_sha256: str | None
    last_consumed_reset_authorization_sha256: str | None
    last_reset_target_state_sha256: str | None
    state: str
    ready_to_arm: bool
    zero_confirmed: bool
    robot_stationary: bool
    topic_ages_ms: Mapping[str, float]
    transform_id: str
    transform_sha256: str
    reason_codes: tuple[str, ...]

@dataclass(frozen=True)
class WatchdogPreflightReceipt:
    watchdog_request_sha256: str
    watchdog_receipt_sha256: str
    checked_monotonic_ns: int
    accepted: bool
    fault_class: Literal["none", "config", "technical", "safety"]
    primary_reason_code: str
    status: WatchdogReadiness

@dataclass(frozen=True)
class FrozenAttemptPlanning:
    planning_kind: Literal["FIXED_TRIAL", "ADAPTIVE_SAFE_SELECTION",
                           "ADAPTIVE_ALL_REJECTED", "NAV_EPISODE"]
    safety_state_path: str
    safety_state_sha256: str
    safety_boot_id: str
    safety_cut_monotonic_ns: int
    equivalent_motion_s: float
    proposal_sha256: str | None
    planner_history_before_sha256: str
    command_preauthorization_path: str | None
    command_preauthorization_sha256: str | None
    planner_decision_candidate_sha256: str | None

@dataclass(frozen=True)
class PreparedAttempt:
    identity: AttemptIdentity
    execution_mode: Literal["ROBOT_MOTION", "MANUAL_DISARMED"]
    start_pose_gate_result: StartPoseGateResult | None
    start_pose_gate_result_sha256: str | None
    planning: FrozenAttemptPlanning | None
    reservation_event_id: str
    reservation_event_sha256: str
    recorder_attempt_id: str
    raw_uri: str
    bag_group_id: str
    segment_id: str
    prepared_start_monotonic_ns: int
    precheck_start_monotonic_ns: int
    precheck_end_monotonic_ns: int
    precheck_snapshot_sha256: str

@dataclass(frozen=True)
class WatchdogPreflightRequest:
    identity: AttemptIdentity
    prepared_attempt_sha256: str
    source_commit: str
    release_manifest_sha256: str
    resolved_config_sha256: str
    schedule_sha256: str
    reference_extrinsic_path: str
    reference_extrinsic_sha256: str
    required_transform_id: str
    required_transform_sha256: str
    requested_monotonic_ns: int

@dataclass(frozen=True)
class PreflightRequest:
    identity: AttemptIdentity
    context: RobotContext
    prepared_attempt_sha256: str
    source_commit: str
    release_manifest_sha256: str
    resolved_config_sha256: str
    schedule_sha256: str
    reference_extrinsic_path: str
    reference_extrinsic_sha256: str
    required_transform_id: str
    required_transform_sha256: str
    requested_monotonic_ns: int

@dataclass(frozen=True)
class PreflightReport:
    request_sha256: str
    prepared_attempt_sha256: str
    watchdog_request_sha256: str
    watchdog_receipt_sha256: str
    checked_monotonic_ns: int
    ready: bool
    snapshot_cut_monotonic_ns: int
    reference_extrinsic_path: str
    reference_extrinsic_sha256: str
    driver: DriverHealth
    recorder: RecorderReadiness
    watchdog: WatchdogReadiness
    hashes_verified: bool
    schedule_unit_authorized: bool
    context_matches: bool
    reason_codes: tuple[str, ...]

@dataclass(frozen=True)
class StartPoseGateResult:
    identity: AttemptIdentity
    pose_role: Literal["calibration", "map", "context_return"]
    map_id: str
    reference_cut_monotonic_ns: int
    expected_pose_se2: tuple[float, float, float]
    measured_pose_se2: tuple[float, float, float]
    position_error_m: float
    yaw_error_rad: float
    maximum_position_error_m: float
    maximum_yaw_error_rad: float
    stationary_window_s: float
    maximum_stationary_speed_mps: float
    measured_maximum_speed_mps: float
    passed: bool
    reason_codes: tuple[str, ...]

@dataclass(frozen=True)
class ScopeAuthorizationRequest:
    scope_authorization_id: str
    authorization_purpose: Literal["PRIMARY_BATCH", "RERUN_TECH",
                                   "RESUME_RENEWAL", "CONDITIONAL_SENTINEL",
                                   "CONTEXT_RETURN"]
    cli_arm_requested: bool
    run_id: str
    session_id: str
    shift_id: str
    scope_id: str
    parent_scope_authorization_sha256: str | None
    lineage_root_scope_authorization_sha256: str | None
    retry_request_uuid: str | None
    activation_event_sha256: str | None
    eligibility_checkpoint_sha256: str
    eligibility_journal_tail_sha256: str
    allowed_scientific_unit_ids: tuple[str, ...]
    source_commit: str
    config_sha256: str
    schedule_sha256: str
    issued_monotonic_ns: int
    expires_monotonic_ns: int
    maximum_attempts: int

@dataclass(frozen=True)
class ScopeAuthorization:
    request: ScopeAuthorizationRequest
    scope_request_sha256: str
    operator_id: str
    safety_operator_id: str
    operator_gate_receipt_sha256: str

@dataclass(frozen=True)
class ArmAuthorization:
    """Single-attempt derivative of one persisted human scope authorization."""
    authorization_id: str
    scope_authorization_sha256: str
    identity: AttemptIdentity
    prepared_attempt_sha256: str
    preflight_report_sha256: str
    watchdog_receipt_sha256: str
    start_pose_gate_result_sha256: str
    attempt_gate_receipt_sha256: str
    issued_monotonic_ns: int
    expires_monotonic_ns: int

@dataclass(frozen=True)
class ArmLease:
    lease_id: str
    authorization_sha256: str
    run_id: str
    attempt_uid: str
    issued_monotonic_ns: int
    expires_monotonic_ns: int

@dataclass(frozen=True)
class ResetAuthorizationRequest:
    robot_id: str
    reason: str
    robot_stationary_confirmed: bool
    latch_reason: str
    watchdog_state_before_reset: Literal["TECH_ABORT_DISARMED",
                                         "SAFETY_ABORT_LATCHED"]
    watchdog_boot_id: str
    watchdog_state_sequence: int
    watchdog_state_sha256: str
    issued_monotonic_ns: int
    expires_monotonic_ns: int

@dataclass(frozen=True)
class ResetAuthorization:
    request: ResetAuthorizationRequest
    reset_request_sha256: str
    operator_id: str
    safety_operator_id: str
    operator_gate_receipt_sha256: str

@dataclass(frozen=True)
class ChangeoverIdentity:
    dataset_role: Literal["DEV", "CONFIRM", "TEST_FIXTURE"]
    run_id: str
    session_id: str
    block_id: str
    method_id: str
    shift_id: str
    changeover_unit_id: str
    changeover_kind: Literal["APPLY", "RESTORE", "RECOVER_NOMINAL"]
    changeover_attempt_index: int
    changeover_uid: str
    retry_of_changeover_uid: str | None
    parent_changeover_uid: str | None
    action: Literal["apply", "restore"]
    phase: Literal["precheck", "actuate", "postcheck"]

@dataclass(frozen=True)
class OperatorGateReceipt:
    receipt_id: str
    receipt_sequence: int
    action: str
    identity_kind: Literal["scope", "attempt", "changeover",
                           "context_return", "reset"]
    identity_id: str
    operator_id: str
    safety_operator_id: str
    operator_approval_path: str
    operator_approval_sha256: str
    safety_operator_approval_path: str
    safety_operator_approval_sha256: str
    accepted: bool
    referenced_report_sha256: str
    evidence_sha256: str | None
    payload_schema: Literal["p8.gate.scope.v1", "p8.gate.attempt.v1",
                            "p8.gate.changeover.v1",
                            "p8.gate.context-return.v1", "p8.gate.reset.v1"]
    payload: Mapping[str, JSONValue]
    payload_sha256: str
    created_utc: str
    created_monotonic_ns: int
    previous_receipt_sha256: str
    receipt_sha256: str

class SafetyFault(RuntimeError):
    def __init__(self, code: str, *, serious: bool, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.serious = serious

class TechnicalFault(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
```

`ChangeoverIdentity` 同时表达 attempt 与 phase，但两种 hash 禁止混叫：

```text
changeover_attempt_identity_sha256 = sha256(canonical JSON(asdict(identity) 排除 phase))
changeover_phase_identity_sha256   = sha256(canonical JSON(asdict(identity)))
```

同一 changeover UID 的三阶段 attempt hash 必须相同，phase hash 必须各不相同。
全文的 gate、R1 relay、ShiftReceipt、result commit 使用前者并必须写完整字段名；每个
EvidenceBundle/phase marker 另写自己的 phase hash。禁止再使用含义不明的
`changeover_identity_sha256`。

`Mapping` 字段在写盘前必须转成 canonical JSON；不允许任意 Python object。
canonical JSON 在全文唯一指 **RFC 8785 JSON Canonicalization Scheme (JCS)** bytes，不是
Python `json.dumps(sort_keys=True)`：UTF-8、ECMAScript number serialization、UTF-16 code-unit
property ordering、JCS escaping/no whitespace。所有输入 string先验证已是 Unicode NFC且无
lone surrogate/control character（JSON规定转义者除外），不替实现自动 normalize；所有
schema拒绝 NaN/Inf和 negative zero。跨语言实现必须使用 repository vendored/pinned的同一
JCS conformance layer；Python/C++禁止各选默认 serializer。fixture
`tests/fixtures/p8_jcs_edge_vectors.json` 至少覆盖 `1e-7/1e21/-0.0`拒绝边界、subnormal、
Unicode/non-ASCII/escaping、UTF-16排序和嵌套 arrays，并逐项给 RFC expected bytes/SHA-256；
两端启动/HIL先跑全部 vector。`scope_request_sha256`、`scope_authorization_sha256` 与
`authorization_sha256` 分别精确为
`sha256(canonical_json(asdict(ScopeAuthorizationRequest)))`、
`sha256(canonical_json(asdict(ScopeAuthorization)))` 和
`sha256(canonical_json(asdict(ArmAuthorization)))`；`PreflightRequest/Report` 采用
同一规则计算其 detached hash。不得把 hash 字段放进自己的 preimage。
`reset_request_sha256=sha256(canonical_json(asdict(ResetAuthorizationRequest)))`，
`reset_authorization_sha256=sha256(canonical_json(asdict(ResetAuthorization)))`；receipt
签前者，authorization 只在 receipt 持久化后构造，不能互相包含形成循环。

`OperatorGateReceipt.payload` 不是自由 dict。`payload_schema` 决定 required/nullable
字段，schema 拒绝 unknown key；`payload_sha256=sha256(canonical_json(payload))`，
`receipt_sha256=sha256(canonical_json(asdict(receipt) 排除 receipt_sha256))`。五种 payload
精确为：

```text
p8.gate.scope.v1:
  scope_request_sha256,scope_authorization_id,scope_id,run_id,session_id,shift_id,
  source_commit,config_sha256,schedule_sha256,maximum_attempts,
  expires_monotonic_ns,allowed_scientific_unit_ids
p8.gate.attempt.v1:
  scope_authorization_sha256,attempt_identity_sha256,prepared_attempt_sha256,
  preflight_report_sha256,watchdog_receipt_sha256,start_pose_gate_result_sha256,
  pose_role,map_id,
  reference_cut_monotonic_ns,expected_pose_se2,measured_pose_se2,
  position_error_m,yaw_error_rad,maximum_position_error_m,maximum_yaw_error_rad,
  stationary_window_s,maximum_stationary_speed_mps,measured_maximum_speed_mps,
  automatic_gate_passed
p8.gate.changeover.v1:
  changeover_attempt_identity_sha256,actuation_phase_identity_sha256,
  evidence_bundle_sha256,context_from,context_to,
  zero_confirmed,motion_inhibited
p8.gate.context-return.v1:
  attempt_identity_sha256,return_mode,trajectory_sha256,activation_event_sha256,
  watchdog_state,zero_confirmed
p8.gate.reset.v1:
  reset_request_sha256,robot_id,reason,robot_stationary_confirmed,latch_reason,
  watchdog_state_before_reset,watchdog_boot_id,watchdog_state_sequence,
  watchdog_state_sha256,expires_monotonic_ns
```

其中 scope/attempt payload 的 array 与 SE(2) vector 都是 canonical JSON array；null
只允许在 `trajectory_sha256`（manual return）以及 schema 明示的 measured pose
不可用拒绝行。`referenced_report_sha256` 是兼容索引：scope/attempt/changeover/
context-return/reset 分别必须等于 `scope_request_sha256/preflight_report_sha256/
evidence_bundle_sha256/activation_event_sha256/reset_request_sha256`；
`evidence_sha256` 仅 changeover 为同一 evidence hash，其余为 null。任何 typed payload、
兼容索引或外层 identity 不一致都拒绝，不能只验证 receipt 最外层 hash。

`WatchdogPreflightRequest` 是唯一 wire preflight request，且不含
`RobotContext` 或 Python-only driver/recorder object；它的 detached hash 为
`sha256(canonical_json(asdict(wire_request)))`。完整 `PreflightRequest` 另含
`RobotContext` 和相同 prepared hash，由 backend 自己 hash。watchdog 只重算/确认
wire request hash并返回 detached receipt hash；backend 才合并 context、driver、
recorder、snapshot 和 watchdog receipt 形成完整 `PreflightReport`。禁止要求 C++
watchdog 对一个它从未收到的完整 request hash 声称验证成功。

`ArtifactRefs` 只引用已封口的 attempt-local immutable artifact 和仍在打开 bag
中的时间范围，因此不含尚未产生的 journal event ID，也不声称打开中的 bag 已有
最终 hash。bag 封口后由 `SealedBagSegmentRef` 和 delivery index 将 range 解析到
最终 segment hash，不回写旧 attempt artifact。

recorder finalize 先写的 `PhysicalAttemptArtifact` preimage 精确为
`{schema_version,result,raw_uri,bag_range,video_uri,immutable_sha256_by_uri}`；其中 hash map
只列 raw/video/marker 等已封口对象，**不得**列本 artifact 自己。它由
`physical_attempt_artifact.schema.json` strict 验证，写入后 path/hash才回填
`ArtifactRefs.attempt_artifact_ref`；`immutable_sha256_by_uri` 仍只列其他 raw/video/marker
对象。随后 `ATTEMPT_PHYSICAL_COMMIT` journal payload逐字段引用该 ref 的
path/semantic/raw hash/size/schema；Python `PhysicalAttemptCommit.commit` 是 journal 返回 ref，永不
序列化进 artifact，因而不存在 self-hash。delivery 的
`physical_attempt_artifacts/[sha256].json` 保存前述 preimage，不保存包装 dataclass。

所有 protocol object统一经 `ContentAddressedStore.put/resolve(ContentAddressedRef)`：
`semantic_sha256` 按该 schema 的 detached/self-hash preimage计算，是 journal/commit中现有
`*_sha256` 字段的含义；`raw_sha256` 对最终落盘 bytes计算并用于文件名/checksum。含自身 hash
字段时两者通常不同。store 在每个 object class维护按
`(semantic_sha256,relative_path,raw_sha256,size_bytes,schema_version)` 排序的 class index；
resolve只能按 semantic hash查唯一 ref，再验证 raw hash/size/schema，不能把 semantic hash
拼成文件名。无 self/detached hash 的 plain object令两者相等。相同 semantic hash映射不同
raw bytes、重复 semantic entry或 path逃逸均为 corruption。exporter/validator复用同一
resolver，并按 handoff §11重算 class-index hash与logical/unique counts。

`TechnicalFault.code` 必须在 handoff §14.2 technical allowlist；
`require_report_ready_and_hash_bound` 逐 reason code 映射成 `TechnicalFault` 或
`SafetyFault`，多原因时按 handoff §14.3 优先级取最早触发者。它不得只抛无 code 的
`RuntimeError`，否则 prepared boundary 后无法唯一决定 retry/budget。

### 5.4 snapshot cut

禁止 runner 先读 reference、再读 onboard 后声称它们是同一 snapshot。
`state_reader.py` 必须在一把锁下以 `cut_monotonic_ns=clock.now_ns()` 对各
ring buffer 取最新且 `sample.monotonic_ns <= cut` 的样本，返回一个
`RichRobotState`。每个通道的 age 都相对同一 cut 计算；任一 required
通道不存在、越界或超龄都返回精确 reason code，不做时间外推。

### 5.5 ports

```python
class MonotonicClock(Protocol):
    def now_ns(self) -> int: ...

class Go2CommandDriver(Protocol):
    def publish(
        self, identity: AttemptIdentity, lease: ArmLease,
        intent: "CommandIntent", *, lease_deadline_ns: int
    ) -> CommandReceipt: ...
    def publish_zero(self, reason: str) -> CommandReceipt: ...
    def enter_safe_mode(self, reason: str) -> CommandReceipt: ...
    def health(self, now_ns: int) -> "DriverHealth": ...

class SensorSnapshotReader(Protocol):
    def latest_cut(self, cut_monotonic_ns: int) -> RichRobotState: ...

class IndependentReferenceReader(Protocol):
    def latest(self, now_ns: int) -> ReferenceSample: ...
    def window(self, start_monotonic_ns: int, end_monotonic_ns: int) -> tuple[ReferenceSample, ...]: ...

class P8Recorder(Protocol):
    def readiness(self) -> RecorderReadiness: ...
    def ensure_group_open(self, bag_group_id: str) -> None: ...
    def begin_attempt(
        self,
        identity: AttemptIdentity,
        *,
        precheck_start_monotonic_ns: int,
        precheck_end_monotonic_ns: int,
        precheck_snapshot_sha256: str,
    ) -> "AttemptRecorder": ...
    def snapshot_bag_range_inventory(
        self,
        *,
        through_identity: AttemptIdentity,
        physical_commit_event_sha256: str,
    ) -> BagRangeInventoryRef: ...
    def commit_changeover_marker(
        self,
        result_commit: JournalCommitRef,
        marker: ChangeoverMarkerRecord,
    ) -> ChangeoverMarkerAck: ...
    def seal_group(self, bag_group_id: str) -> tuple[SealedBagSegmentRef, ...]: ...

class AttemptRecorder(Protocol):
    def stable_attempt_id(self) -> str: ...
    def open_segment_id(self) -> str: ...
    def open_raw_uri(self) -> str: ...
    def mark(self, event: ExperimentEvent) -> None: ...
    def mark_navigation(self, marker: NavigationMarkerRecord) -> None: ...
    def append_sample(self, sample: P8Sample) -> None: ...
    def finalize(self, result: AttemptResult) -> ArtifactRefs: ...

class P8Journal(Protocol):
    def reserve_attempt_and_fsync(
        self, identity: AttemptIdentity
    ) -> JournalCommitRef: ...
    def append_and_fsync(
        self, event: ExperimentEvent | ChangeoverEvent | RunLevelEvent
    ) -> JournalCommitRef: ...

class P8SafetyPort(Protocol):
    """只负责 matrix 前的 logical safety；不得实现 R1 或 wire safety。"""
    def monitor_state(self, state: RichRobotState) -> LogicalSafetyDecision: ...
    def preauthorize_trial(
        self,
        command: VelocityCommand,
        state: RichRobotState,
        *,
        equivalent_motion_s: float,
        logical_history: tuple[VelocityCommand, ...],
    ) -> LogicalSafetyDecision: ...
    def evaluate_logical(
        self,
        proposal: CommandProposal,
        state: RichRobotState,
        *,
        dt_s: float,
        logical_history: tuple[VelocityCommand, ...],
    ) -> LogicalSafetyDecision: ...

class WatchdogClient(Protocol):
    def readiness(self, now_ns: int) -> WatchdogReadiness: ...
    def run_preflight(
        self, request: WatchdogPreflightRequest
    ) -> WatchdogPreflightReceipt: ...
    def register_scope_authorization(
        self, authorization: ScopeAuthorization
    ) -> str: ...  # 返回 persisted scope_authorization_sha256
    def register_operator_gate_receipt(
        self, receipt: OperatorGateReceipt
    ) -> str: ...  # 返回 persisted receipt_sha256
    def operator_gate_receipt_tail(self) -> tuple[int, str]: ...
    def arm(
        self, authorization: ArmAuthorization, identity: AttemptIdentity
    ) -> ArmLease: ...
    def disarm(self, reason: str) -> ZeroReceipt: ...
    def begin_execution(self, identity: AttemptIdentity, lease_id: str) -> None: ...
    def complete_execution(self, reason: str) -> ZeroReceipt: ...
    def heartbeat(
        self,
        heartbeat_sequence: int,
        *,
        command_sequence: int | None,
        lease_deadline_ns: int | None,
    ) -> None: ...
    def latch_abort(self, reason: str, *, serious: bool) -> ZeroReceipt: ...
    def technical_abort(self, reason: str) -> ZeroReceipt: ...
    def reset_latch(self, authorization: ResetAuthorization) -> WatchdogReadiness: ...
    def acknowledge_technical_abort(self, authorization: ResetAuthorization) -> WatchdogReadiness: ...

class OperatorGate(Protocol):
    """Persisted human authorization boundary; injected, never a module global."""
    def check_start_pose(
        self,
        identity: AttemptIdentity,
        *,
        pose_role: Literal["calibration", "map", "context_return"],
        map_id: str,
    ) -> StartPoseGateResult: ...
    def authorize_scope(
        self,
        request: ScopeAuthorizationRequest,
    ) -> ScopeAuthorization: ...
    def authorize_attempt(
        self,
        identity: AttemptIdentity,
        report: PreflightReport,
        *,
        scope_authorization: ScopeAuthorization,
        start_pose_gate: StartPoseGateResult,
    ) -> ArmAuthorization: ...
    def authorize_context_return(
        self,
        identity: AttemptIdentity,
        *,
        return_mode: Literal["manual_reposition_disarmed",
                             "approved_controlled_return"],
        trajectory_sha256: str | None,
    ) -> OperatorGateReceipt: ...
    def authorize_changeover(
        self,
        identity: ChangeoverIdentity,
        *,
        evidence_sha256: str,
    ) -> OperatorGateReceipt: ...
    def authorize_reset(
        self, request: ResetAuthorizationRequest
    ) -> ResetAuthorization: ...
    def load_receipt(self, receipt_sha256: str) -> OperatorGateReceipt: ...

class CommandSession(Protocol):
    """NAV 的连续命令会话；是唯一允许的高频运动边界。"""
    def snapshot(self) -> RichRobotState: ...
    def publish_tick(
        self,
        proposal: CommandProposal,
        *,
        controller_cut_monotonic_ns: int,
        scheduler_deadline_ns: int,
    ) -> CommandReceipt: ...
    def stabilize_zero(
        self, *, duration_s: float, first_deadline_ns: int
    ) -> tuple[int, int]: ...  # (STABILIZE_START, NAVIGATE_START) monotonic ns
    def assess_online_serious_event(self, reason: str) -> bool: ...
    def close(self, terminal_reason: str) -> PhysicalAttemptCommit: ...
    def abort(
        self,
        reason: str,
        *,
        kind: Literal["safety", "technical", "operator_cancel", "internal_fault"],
        serious: bool = False,
    ) -> PhysicalAttemptCommit: ...

class ContinuousCommandBackend(Protocol):
    def open_command_session(
        self,
        prepared: PreparedAttempt,
        context: RobotContext,
        lease: ArmLease,
    ) -> CommandSession: ...

class P8ExecutionBackend(RobotBackend, ContinuousCommandBackend, Protocol):
    def prepare_attempt(
        self, identity: AttemptIdentity, context: RobotContext,
        start_pose_gate: StartPoseGateResult,
        planning: FrozenAttemptPlanning,
    ) -> PreparedAttempt: ...
    def abandon_prepared_attempt(
        self,
        prepared: PreparedAttempt,
        *,
        reason: str,
        kind: Literal["technical", "safety", "operator_cancel", "internal_fault"],
        technical_failure_code: str | None,
    ) -> PhysicalAttemptCommit: ...
    def preflight(self, request: PreflightRequest) -> PreflightReport: ...
    def arm(
        self, authorization: ArmAuthorization, identity: AttemptIdentity
    ) -> ArmLease: ...
    def bind_prepared_attempt(
        self, prepared: PreparedAttempt, lease: ArmLease
    ) -> None: ...
```

`CommandSession.publish_tick()` 必须自己完成 execution-time state check、logical
safety、构造 accepted `CommandIntent`、发送、watchdog heartbeat 和 raw append。
NAV runner 只生成 `CommandProposal`，不得填 `safe/model_input`，也不得直接调
driver、ROS publisher 或 vendor adapter。独立 C++ relay 是 R1 transform、wire
amplitude/slew/workspace safety 和 vendor publish 的唯一 owner；Python backend 不得
再执行或伪造一次 R1/wire decision。
`Go2CommandDriver.publish` 的 identity/lease 是显式参数：driver 用它们逐字段构造
`CommandPacket`，并要求 lease attempt UID、authorization、deadline 与 watchdog active
record 相等。trial executor直接传本地 consumed binding；CommandSession 在构造时私有保存
同一 identity/lease并在每 tick传入。禁止 driver 读取 module-global“当前 attempt”、最近
lease或路径；旧 lease、跨 attempt identity、两个并发 session/driver publish 都 fail
closed并 zero。

`snapshot()` 返回的 cut 在同一 session 内只可供一个后续 tick 使用；
`publish_tick` 必须核对 `controller_cut_monotonic_ns` 与最后未消费 cut 相同，再在
`scheduler_deadline_ns` 到达时取得一个更晚或相同的 safety cut。controller cut 和
safety cut 都写 raw；`P8Sample.snapshot` 使用真正通过 safety 的 cut，controller cut
写入 metadata。这样既不把两个时刻冒充同一 snapshot，也不允许 stale controller
cut 绕过 execution check。

`open_command_session(prepared, context, lease)` 与 compatibility binding 相同，必须在
内部 `try/finally` 原子消费 prepared+lease；任何 validate/open/begin 异常都先调用
watchdog zero/disarm/abort，再 finalize physical failure。不得把“尚未返回 session”当作
无需停机的理由。

ownership 只有一次转移：caller 在调用 `open_command_session` **之前**置
`ownership_transferred=True`；从这一行起 caller 永不调用
`abandon_prepared_attempt`。该方法无论在 consume 前还是后失败，都必须自己将 prepared
置为 `ABANDONED` 或 `CONSUMED`、封唯一 `AttemptResult`、fsync
`ATTEMPT_PHYSICAL_COMMIT`，并令抛出的 exception 携带该
`PhysicalAttemptCommit`。成功返回后仅 `CommandSession.close/abort` 有权 finalize，二者
也直接返回 `PhysicalAttemptCommit`，不是只有 `ArtifactRefs`。同一 terminal 参数重入
返回同一 commit；不同 terminal/kind 重入判 integrity error。这样 open 抛错时不会由
caller 和 backend 各 finalize 一次。

`stabilize_zero` 在 `begin_execution` 之后运行，但只经 authorized command lane 发布
严格零命令；它使用 absolute monotonic deadlines、持续 heartbeat、reference/state/
stationary gate、raw sample 与 `NavigationMarker`，持续时间精确取冻结
`navigation.initial_stabilization_s`。返回值是已记录的 `STABILIZE_START` 与
`NAVIGATE_START` monotonic ns；任何 non-zero packet、reference gap、姿态/静止超限或
marker 持久化失败都先 abort。episode timeout 的时间原点只取
`NAVIGATE_START`，arm 前 PRECHECK 和这段 stabilize 不能互相替代。

`assess_online_serious_event` 只读本 session 已记录的 contact/roll/pitch/height/motor/
E-stop/person-contact flags，按 frozen safety criteria 做保守 OR；任一严重条件或 required
sensor 不确定可返回 true，绝不能硬编码 false。它的 online 值立即进入
AttemptResult/SafetyEvent，但最终论文 serious flag 还必须经过第 17.7 节 blind safety
review；offline review 只能把 false 提升为 true，不能把 online true 降为 false。

`scheduler_deadline_ns` 只用于绝对周期调度，绝不发送到 relay。session 在实际 publish
前计算 `lease_deadline_ns=min(arm_lease.expires_monotonic_ns,
clock.now_ns()+command_lease_ns)`，只把后者交给 driver/heartbeat/`CommandPacket`。
两种 deadline 不能复用一个变量或字段。

`Go2RosBackend` 同时实现冻结的 `RobotBackend` 和这个 P8 扩展。

`Go2RosBackend.__init__` 必须依赖注入这些 ports：

```python
Go2RosBackend(
    driver,
    snapshot_reader,
    reference_reader,
    recorder,
    journal,
    safety_filter: P8SafetyPort,
    watchdog,
    clock,
    config,
)
```

构造器不接受 `armed=True/False`；新 backend 的本地状态只能是 `UNBOUND/query-only`，
必须先查询外部 watchdog。外部 watchdog 从 fsync 的持久状态恢复，可能是
`DISARMED`、`TECH_ABORT_DISARMED` 或 `SAFETY_ABORT_LATCHED`；backend 构造、进程
重启和 `reset()` 都不得强制它回到 DISARMED。runner process 从启动起就在任意
watchdog state 发送 process
heartbeat；此时 `command_sequence=None,lease_deadline_ns=None`，只证明进程活着，
不授权任何非零命令。因而 preflight/arm 不依赖“先发一次运动命令”来建立 heartbeat。

每个运动 attempt 的唯一顺序为：在 fresh gate 后构造冻结 `FrozenAttemptPlanning`，再由
`backend.prepare_attempt(identity, context, start_pose_gate, planning)` 在
**未 arm 且持续 zero** 时完成 journal reservation、打开 attempt recorder、至少
0.5 s stationary precheck，并返回 immutable `PreparedAttempt` → 从该对象构造
`WatchdogPreflightRequest` 和完整 `PreflightRequest`，两者都绑定
`prepared_attempt_sha256` → `backend.preflight()` 聚合
driver/recorder/snapshot/hash/context，并调用 watchdog
`DISARMED→PREFLIGHT→READY` → 将 strict PreflightReport content-addressed写盘/fsync、以
semantic/raw双 hash注册并回读验证 → `OperatorGate` 核对当前 scope 的双人
`ScopeAuthorization`，再产生只绑定当前 identity/prepared/report/receipt 的
单-attempt `ArmAuthorization` → `watchdog.arm(authorization, identity)` 原子返回一条新
`ArmLease` 并进入 `ARMED_IDLE` → `bind_prepared_attempt` 或
`open_command_session(prepared,...)` 原子消费 prepared+lease →
`begin_execution`。任何 preflight/authorization/arm 失败都调用
`abandon_prepared_attempt(...)`，在 zero 状态将已经分配的 recorder 封为
`pre_measure_abort` 和
`ATTEMPT_PHYSICAL_COMMIT`；不得遗留一个没有结论的 prepared attempt，也不得直接从
DISARMED 调 `begin_execution`。

`abandon_prepared_attempt` 不得发明 reason code。真实 health/hash/storage 等失败
必须原样使用 handoff §14.2 中最早触发的 exact code。technical code 写
`pre_measure_abort` 并允许显式技术重采；prepared boundary 之后发生的 safety code
写 `safety_abort,protocol_complete=true` 并消耗该 unit。operator 拒绝或撤回
写 `terminal_reason="OPERATOR_CANCELLED"`、`technical_failure_code=None`，其
`ScientificUnitResult` 为 `protocol_complete=false,retry_permitted=false`，只能暂停并
由新的冻结 release/人工决定后续，绝不能自动获得 `RERUN_TECH` 资格。
未匹配 typed `TechnicalFault`/`SafetyFault`/`OperatorCancelled` 的代码异常使用
`kind="internal_fault",terminal_reason="UNCLASSIFIED_INTERNAL_FAULT",
technical_failure_code=None`：同样先走 technical zero/disarm，但 scientific cursor 进入
`PAUSED_INTERNAL_REVIEW`、不得重采。它不能被事后改写成 allowlist code；只能修复代码后
按批准的 protocol deviation 启动新 run，避免利用结果决定是否把任意 exception 变成
`SOFTWARE_PROCESS_CRASH`。

`PreparedAttempt` 的 detached hash 是其 canonical JSON 的 SHA-256。backend 内部只
保存 `prepared_attempt_sha256 → AttemptRecorder` 的 instance-local、single-use
handle；identity、reservation event、raw URI、bag group/segment 和 precheck cut 必须
逐项相等才能消费。一个 prepared object 只能处于
`PREPARED → CONSUMED` 或 `PREPARED → ABANDONED`，不能重新打开、换 lease、换 identity
或换 recorder。precheck 成功只证明准备态安全，不授权任何非零命令。
`PreparedAttempt` 内嵌完整 `StartPoseGateResult` 并另带其 semantic hash，validator可从
prepared bytes重算，不需要悬空 gate object；`PreflightReport` 不内嵌，必须解析到 delivery
`preflight_reports/`。ArmAuthorization/attempt receipt只允许引用刚持久化且
prepared/request/extrinsic/global-state heads逐项匹配的 report hash。
所有 calibration/validation/navigation/controlled-return 构造器必须显式写
`execution_mode="ROBOT_MOTION"`；只有第 15.1 节 manual return allocator 可写
`MANUAL_DISARMED`。preflight/arm/open session 遇到后者一律拒绝，manual executor 遇到
前者同样拒绝；该字段进入 prepared hash/golden vectors。
conditional schema 使用显式 `oneOf`，不能从 nullable 字段猜 branch：

- 所有 `ROBOT_MOTION` 的两个 start-pose gate fields required、hash 匹配且
  `passed=true`；`planning` required，safety state path/hash、boot/cut、horizon 和
  planner-history-before hash 在四个 planning kind 都 required，并与 fresh precheck/spec
  逐位相等；
- `FIXED_TRIAL`：`proposal_sha256` 与 CommandPreauthorization path/hash 全 required，
  planner-decision candidate 必须 null；
- `ADAPTIVE_SAFE_SELECTION`：proposal、CommandPreauthorization 和 planner-decision
  candidate hash 全 required；
- `ADAPTIVE_ALL_REJECTED`：proposal 与 CommandPreauthorization path/hash全 null，planner
  decision candidate hash required且其 selected command=null；它证明 pool全部评估过但没有
  命令被授权，不得生成虚假 zero-command proposal/preauthorization；
- `NAV_EPISODE`：proposal、CommandPreauthorization path/hash、planner-decision 全 null；
  NAV 的动态 control-tick proposal 只能在 armed episode 内经第 15.3 节 command lane 产生，
  不能伪造 60 s 单一 preauthorization；
- `MANUAL_DISARMED` 的 gate fields 与整个 `planning` 必须 null，因为它使用 AUX
  manual-entry/target verification 流程而不是 planned motion gate。

path/hash 必须成对出现或成对为 null。不得把失败 planned gate identity 塞进 AUX
PreparedAttempt。五个 execution/planning branch 的 canonical golden vectors、
wrong-branch/null-pair negative
vectors 都纳入 tests。

`abandon_prepared_attempt` 的第一条有副作用语句必须查询外部 watchdog，并在
`READY/ARMED_IDLE` 走 high-priority zero/disarm、在 `EXECUTING` 走对应 abort；确认不再
armed/executing 后才 finalize recorder/journal。这样 arm 成功但 binding/session open
失败也不会在写盘期间停留于 `ARMED_IDLE`。

CLI `--arm` 先由两个不同人员签出一个有界 `ScopeAuthorization`；它**不含**
prepared/preflight hash。logical `scope_id` 精确为
`run/session/shift_or_NOT_APPLICABLE/block/method`；NAV request 的 `shift_id` 与该路径段
都固定为 `NOT_APPLICABLE`，SHIFT request 必须写真实 `R1..R4`。因此四个 SHIFT
sequence 绝不共享 active/supersede/quota namespace。`scope_authorization_id` 是每份
授权实例的全局唯一 ID。五种 purpose 的规则冻结为：

- `PRIMARY_BATCH`：parent/root/retry UUID 均 null，注册后该 authorization 自身成为
  lineage root；`allowed_scientific_unit_ids` 精确等于该
  method scope 的冻结、尚未 complete 的 planned units，
  `maximum_attempts=len(allowed IDs)`；activation hash 为 null，只允许
  `attempt_role=PRIMARY,index=1`；
- `RERUN_TECH`：parent 指 previous failed attempt 实际消费的 issuing scope hash（可为
  PRIMARY/CONDITIONAL_SENTINEL/CONTEXT_RETURN/RERUN），lineage root 指其链上的 method
  PRIMARY root，`retry_request_uuid` required 且未使用，allowed
  IDs 恰含 fault matrix 允许重采的一个 unit、`maximum_attempts=1`；只允许该 unit 的
  next `RERUN_TECH` identity，activation hash 为 null；
- `RESUME_RENEWAL`：parent 指被续期的 active/expired scope，retry UUID 为 null，allowed
  IDs 必须恰为 parent 尚未消耗且未 protocol-complete 的集合，maximum 等于其长度；注册
  与 parent `ACTIVE→SUPERSEDED`、剩余 quota 转移是同一 durable transaction，activation
  hash 为 null；lineage root 与 parent record 相同；
- `CONDITIONAL_SENTINEL`：parent 指原 method scope，retry UUID 为 null，activation hash
  必须指第 14.4 节 hash-valid `CONDITIONAL_UNIT_ACTIVATED`，allowed IDs 恰为同一新
  verification set 的两条 sentinel，lineage root 指 method PRIMARY root，
  `maximum_attempts=2`，只允许 PRIMARY/index=1；
- `CONTEXT_RETURN`：parent 指触发 start-pose gate 的 method scope，retry UUID 为 null，
  activation hash 必须指领取该 AUX ID 的 `CONDITIONAL_UNIT_ACTIVATED`，allowed IDs 恰含
 这一条 context-return unit、lineage root 指 method PRIMARY root、`maximum_attempts=1`；
 只供 approved controlled return。

所有 purpose 的 `eligibility_checkpoint_sha256` 必须指构造 request 时最后一个 hash-valid
paired protocol checkpoint；每个全新 NAV method/SHIFT sequence 必须先产生第 13.1.1 节
`RUNTIME_STATE_INITIALIZED → CHECKPOINT_COMMIT`，首 scope指该 checkpoint，
`eligibility_journal_tail_sha256` 指同一 consistent read cut 的 journal tail；conditional
purpose 的 tail 必须已包含 activation event，RERUN tail 必须已包含 failed scientific
result/checkpoint和 `RETRY_REQUEST_ACCEPTED`。两值进入 request/gate hash，不能为空或由
CLI自填。

同一 logical scope 可有这些有 lineage 的不同实例，不能用相同
`scope_authorization_id` 覆盖。过期、超数、allowed-set 不等、parent/retry chain 不合法或
越 scope 一律不能生成 attempt authorization。

每次运动都必须在 fresh preflight 后生成新的 `ArmAuthorization`。它的 nested
`identity`、`prepared_attempt_sha256`、`preflight_report_sha256`、watchdog receipt 和
start-pose gate hash、attempt-gate receipt 必须与本次 attempt 逐字段相等；一个 authorization 只能换一条
lease。同一 authorization+identity 的重复 service request幂等返回原 lease，换任一
identity/prepared/report 字段都拒绝。这样 scope 人工批准可覆盖一个 method 的冻结批次，
但旧 preflight 永远不能给后续 attempt 授权。
`watchdog.arm(authorization, identity)` 的第二个参数只为兼容现有 port，必须与
`authorization.identity` canonical JSON 完全相等；不相等立即拒绝，不能选择其一。

scope quota 的权威 owner 是独立 watchdog。它以
`scope_authorization_id,scope_authorization_sha256,run_id,session_id,shift_id,scope_id,
purpose,parent_hash,lineage_root_hash,status,
allowed_scientific_unit_ids[],maximum_attempts,
consumed[{scientific_unit_id,attempt_uid,authorization_sha256,lease_id}]` 写
content-addressed state、`fsync+atomic rename+directory fsync`，重启后先恢复再允许 arm。
同一 scientific unit 的 eligibility 还要与 hash-valid journal scientific outcome/retry
chain 交叉验证；PRIMARY_BATCH、RERUN_TECH、RESUME_RENEWAL 不能通过不同 scope 重复授权
同一个不合法 role/index。每个新 attempt authorization 成功换 lease时原子消耗一次 quota。
lease ID 和 issued/expiry time 由 watchdog 生成，Python 不预造；
expiry 为 `min(scope authorization expiry, attempt authorization expiry,
now+arm_lease_ms)`。

quota 计数的是实际签发的 arm lease，不是 scientific unit 数。第 13.3.1 节
`ALL_CANDIDATES_REJECTED` 在 PREPARED 后 no-arm finalize：它完成并消耗 scientific unit，
但不创建 `ArmAuthorization/lease`，因此不增加 `consumed[]`。这不会留下可再次运动的资格：
watchdog 每次 register/arm 都在同一 protocol-store consistent cut 将 allowed IDs 与
hash-valid `SCIENTIFIC_UNIT_COMMIT.protocol_complete` 交叉，已 complete ID 即使 scope
`remaining_attempts>0` 也必须拒绝。scope close 可合法留下 unused lease quota，不得转给
其他 ID。`RESUME_RENEWAL.allowed IDs/maximum_attempts` 只取“未 protocol-complete 且 parent
未实际消耗 lease”的交集，all-rejected ID 永不转移。validator 分别报告
`planned_scientific_units,protocol_complete_units,arm_leases_consumed,
no_arm_protocol_complete_units,unused_lease_quota`，不能强制一一相等。测试覆盖 no-arm后用
旧 scope arm同 ID、scope close unused、resume transfer和普通 1 unit=1 lease路径。

watchdog 不信任 Python 传来的 allowed set。注册 scope 时，它在 safety config 的
`protocol_store` 下取得 consistent read lock，验证 journal 从 genesis 至 request 的
`eligibility_journal_tail_sha256` 完整 hash chain、paired checkpoint hash等于 request、
scientific results/attempt lineage与 schedule manifest一致，再机械重算 PRIMARY pending、
RERUN failed eligibility、RESUME remaining或 conditional activation set。重算结果与
allowed IDs/parent/purpose/quota任一不同即拒绝。每次 `ArmMotion` 又在新 consistent cut
重读最新 paired checkpoint，拒绝 rollback、已有 protocol-complete unit、错误 retry index
或 cursor不在本 unit；后续新 journal tail可以前进但不能与已验证前缀分叉。伪造 allowed
set、传旧 checkpoint/tail、替换 scientific result或 TOCTOU append 的跨进程测试必须
fail closed。这样 C++有明确 read-only evidence channel，无需相信 caller 摘要或自行猜
共享路径。

为了兼容冻结的 `RobotBackend.execute_trial(command, policy)`，backend 提供
instance-local、single-use 的 `bind_prepared_attempt(prepared, lease)`；下一次
`execute_trial` 在函数内 `try/finally` 保护下原子消费它，重复、缺失、hash 不匹配或
lease 不匹配即拒绝。NAV 不用该 compatibility binding，而在
`open_command_session(prepared, context, lease)` 显式消费同一对象。不得用 module
global、路径反推或隐式“最近一个 attempt”。

`OperatorGate` 必须通过 `NavRunner/ShiftRunner/P8RetryCoordinator` 构造器依赖注入；
禁止 runner 直接 `input()`、读取任意环境变量或使用 module-global 单例。文件实现把
receipt 写到 robot-global
`<robot_state_root>/operator_gate/<robot_id>/receipts/`
`gate_<sequence>_<receipt_sha256>.json`，并维护
`previous_receipt_sha256` hash 链；写临时文件、file fsync、同目录 atomic rename、
directory fsync 全部成功后才可返回授权。每个 scope、controlled return、changeover、
reset 必须由两个不同的 `operator_id/safety_operator_id` 批准。scope 内每个 arm 仍写
一条新的 attempt gate receipt，机械绑定 scope hash、fresh preflight、reference cut、
期望 pose、position/yaw tolerance、stationary window 与自动判定；它继承已签 scope 的
两个人员 ID，不要求每条 4 s trial 重新键盘确认。任何链损坏、ID 相同、scope 过期、
自动 gate 拒绝或持久化失败都 fail closed。
`check_start_pose` 只返回 immutable typed `StartPoseGateResult`，不写 operator receipt、
不推进 receipt sequence，也不使用隐藏 module cache；其 detached hash 按第 5.3 节
canonical规则计算。runner 必须把同一对象显式放入 spec，再传给
`authorize_attempt`。后者要求 identity逐字段相同且 `passed=true`，把 result hash和全部
pose/stationary fields写入唯一 `p8.gate.attempt.v1` receipt。这样每个 attempt只有一条需
注册的 gate receipt，C++ receipt chain 不会因丢弃 pose receipt出现 gap。
`ArmAuthorization.attempt_gate_receipt_sha256` 必须引用刚写成的 attempt receipt；
watchdog 同时核对它引用的 `scope_authorization_sha256` 已持久化且仍有效。回位和
changeover receipt 永不进入 calibration observation/model update。

gate receipt 写盘后，runner 必须立即用 `OperatorGate.load_receipt(hash)` 取回并调用
`WatchdogClient.register_operator_gate_receipt`；watchdog 只有在严格解析 typed payload、
重算 payload/receipt hash、验证 robot-scoped previous-receipt chain 并按第 10.1.1 节
持久化后才返回相同 hash。`RegisterScopeAuthorization` 与 `ArmMotion` 只接受已注册的
receipt hash，且重新交叉核对 typed payload；Python 侧“文件存在”不能替代 C++ 持久
验证。重复注册相同 bytes/hash 幂等，相同 `receipt_id` 或 sequence 不同 bytes 进入
`PERSISTENCE_CORRUPT`。

`receipt_sequence` 在同一 robot store 从 1 严格递增；sequence=1 的
`previous_receipt_sha256` 固定 64 个 `0`，其余必须指 sequence-1。文件名中的 sequence
就是 receipt 内十进制值（建议零填充 20 位）。gap、rollback、同 sequence 不同 hash、
跨 robot previous link 或链尾缺失均 fail closed；不得只靠文件名字典序推断顺序。

robot-global store 与 run output 的职责禁止混合：supervisor latch/boot链、robot-scoped
operator receipt tail和 quota records 跨 run 永久连续；run-scoped protocol store只含该
run journal/scientific/checkpoint。Python 每次签 receipt 前先用
`GetOperatorGateReceiptTail` 取得 global tail，在 shared global store/C++ 注册成功后，才把
相同 canonical receipt bytes复制到
`<output_root>/protocol_state/operator_receipt_refs/` 供 delivery；该副本不是 authority。
new run 的 receipt sequence/previous继续 global tail，不新建 genesis。new run attachment
还必须验证 global supervisor chain、robot ID、source release和无其他 run 的 active unexpired
scope；旧 scope正常结束时显式 close，crash只能 resume同 run，或等待/经双人批准使旧 scope
过期，不能用空 output重置。每个 run 的 `RUN_ATTACHED_TO_ROBOT_STATE` 事件绑定 global
supervisor/receipt/quota head hashes；delivery manifest复制全部实际引用的 receipt/quota/state
records及从 attachment head到运行末 head的 chain proof。测试连续运行两个空 output run，
在 run1留下 safety latch/receipt后证明 run2不能清除、sequence不归一且 provenance可验证。

attachment/end 不是文字日志。runner 在同一 atomic `WatchdogStatus` cut复制所需 global
records到 run protocol store，写 strict `GlobalStateProof`：
`schema_version,proof_kind=ATTACH|END,dataset_role,run_id,robot_id,source_commit,
release_manifest_sha256,boot_id,status_monotonic_ns,state_sequence,state_sha256,
quota_state_sha256,operator_gate_receipt_tail_sha256,active_scope_authorization_sha256,
last_consumed_reset_authorization_sha256,last_reset_target_state_sha256,
supervisor_record_refs[],quota_record_refs[],operator_receipt_refs[],
scope_authorization_refs[],arm_authorization_refs[],reset_authorization_refs[],
previous_global_state_proof_sha256,proof_sha256`。每个 ref 是第 5.3 节双-hash
`ContentAddressedRef`，必须指 run-local copy而非 robot root。

写/fync ATTACH proof 后 append+fsync
`RUN_ATTACHED_TO_ROBOT_STATE{proof_path,proof_semantic_sha256,proof_raw_sha256,
run_id,robot_id,boot_id,state_sequence,state_sha256,quota_state_sha256,
operator_gate_receipt_tail_sha256,active_scope_authorization_sha256,
release_manifest_sha256}`，此后才可创建 block session/INIT。run terminal 时先 close/expire
scope并取得新的 atomic cut，写 END proof并 append+fsync
`RUN_DETACHED_FROM_ROBOT_STATE` 同构 payload，且 previous proof指 ATTACH；若 safety latch仍在，
如实保留而不是强制 reset。delivery validator从两 event refs开始，仅靠复制 records重算
chain/head；没有 event引用的 proof是 orphan。crash在 proof copy/write/event fsync各点均按
run+proof_kind幂等恢复，同 kind不同 bytes判 corruption。

`GlobalStateProof.schema_version="p8.global-state-proof.v1"`；
`proof_sha256=sha256(JCS(record排除proof_sha256))`。ATTACH 的
`previous_global_state_proof_sha256=null`，END 必须等于同 run ATTACH semantic hash。
supervisor/quota/receipt 三个 refs array分别按
`state_sequence/quota_sequence/receipt_sequence` 严格连续排序，覆盖该 robot store 从
genesis（receipt可为空 sentinel）到本 cut；对应 head必须等于最后 ref semantic hash。
scope/arm/reset authorization没有 chain sequence：scope按
`scope_authorization_id`、arm按 `authorization_id`、reset按 semantic hash排序；三组只要求
恰好覆盖 supervisor/quota/receipt chain直接引用的这三类 authorization对象，不递归混入
prepared/preflight等其他 artifact，也不得塞入无关授权。
目录/schema dispatch固定为：
`supervisor_records→watchdog_state`、`quota_records→quota_record`、
`operator_receipt_refs→operator_gate_receipt`、`scope_authorizations→scope_authorization`、
`arm_authorizations→arm_authorization`、`reset_authorizations→reset_authorization`。
ref path/raw/semantic/size/schema任一不符都失败。

quota authority record精确为
`schema_version="p8.quota-record.v1",robot_id,quota_sequence,event_kind,
scope_authorization_sha256,arm_authorization_sha256,attempt_uid,maximum_attempts,
consumed_attempts,closed,recorded_monotonic_ns,previous_quota_state_sha256,
quota_state_sha256`；event kind只允许 `GENESIS|REGISTER_SCOPE|ISSUE_ARM|CLOSE|EXPIRE`，
strict oneOf为：GENESIS令scope/arm/attempt全null、max=consumed=0、closed=true；
REGISTER_SCOPE只令scope non-null、max取authorization positive quota、consumed=0、closed=false；
ISSUE_ARM要求同scope+arm+attempt全non-null、max不变、consumed=previous+1≤max、closed=false；
CLOSE/EXPIRE要求scope non-null、arm/attempt null、counters不变、closed=true。counters单调，
`quota_state_sha256=sha256(JCS(record排除quota_state_sha256))`。GENESIS sequence=0、previous
为64个`0`；以后 sequence+1且previous指前一 semantic hash。operator receipt store不造
假 receipt genesis：若从未有 receipt，atomic head精确为64个`0`且proof refs为空；一旦存在，
第一条 receipt sequence=1/previous=64个`0`，head等于最后 semantic hash。supervisor/quota
始终有真实 genesis object。global proof schema按以上 sentinel条件验证。
跨记录 guard 同样强制：robot_id恒定、recorded monotonic不倒退；REGISTER_SCOPE只允许
previous.closed=true且新 scope ID/hash从未出现；ISSUE_ARM只允许 previous为同一 open
scope，arm authorization必须解析到该 scope+attempt/preflight且其 hash/attempt从未消费；
CLOSE/EXPIRE只允许 previous为同一 open scope。任何 cross-scope、重复arm、counter rollback
或closed后消费都进入 corruption，不以单行 schema通过代替链验证。
ISSUE_ARM 先写/fsync quota candidate，但它只有被下一条 durable supervisor state的
`quota_state_sha256` 引用后才成为 live；该 supervisor record同时从 READY进入ARMED_IDLE并
写 active authorization/lease，是唯一 commit edge。crash在 supervisor fsync前令 quota
candidate为 orphan且不消费；fsync后从 supervisor恢复 quota+lease。禁止另造未定义的2PC
transaction对象；绝不能 state已armed而quota未消费，或先消费quota却没有可恢复 lease。

`OperatorGateReceipt.identity_id` 的机械映射为：`identity_kind=scope` 时取
`ScopeAuthorizationRequest.scope_authorization_id`，attempt/context-return 时取
`AttemptIdentity.attempt_uid`，changeover 时取 `ChangeoverIdentity.changeover_uid`，
reset 时取 `robot_id`；任何交叉类型或空 ID 都拒绝。

scope 签字的无环顺序固定为：先构造不含 receipt/operator 的 immutable
`ScopeAuthorizationRequest` 并计算 `scope_request_sha256`；两个人员 receipt 必须
`identity_kind=scope,identity_id=request.scope_authorization_id,
payload_schema=p8.gate.scope.v1,payload.scope_request_sha256=scope_request_sha256,
referenced_report_sha256=scope_request_sha256,evidence_sha256=null`。receipt 先经上述
register service 持久化，随后才构造
`ScopeAuthorization(request=<逐字段同一对象>,scope_request_sha256=<同值>,
operator_id/safety_operator_id=<receipt 两个不同 ID>,
operator_gate_receipt_sha256=<receipt hash>)`。receipt 不能签完整
`ScopeAuthorization`，ScopeAuthorization 也不写自己的 hash，因而无循环。watchdog 注册时
必须重算 request hash、receipt hash/链/两人 ID，再重算 scope authorization hash；任一步
不等即拒绝。这样 source/config/schedule/allowed IDs/quota/expiry 任一变化都会使旧 receipt
失效。

---

## 6. 配置与 schema 合同

### 6.1 通用规则

`config.py` 同时区分 tracked template、materialized release config 和 run-specific resolved
config。运行期绝不直接接受 template。必须做到：

- `yaml.safe_load`；顶层必须是 mapping；
- required key 缺失、unknown key、类型错误、NaN/inf 均失败；
- 所有冻结只读 input ref 都按下文 `FrozenRef` 规则解析；不得相对 config/map 文件所在
  目录解析；runtime output/global-state sentinel 按下述规则单独解析；
- 每个冻结文件的完整 64 hex SHA-256 保存在外部 release manifest/
  `checksums.sha256`，不写回被 hash 文件自身，也不用
  `canonical_config_hash()` 的 16 位短值；
- DEV template 只允许下文四个 derived slot 为 null；其他现场值不得用
  `REQUIRED_BEFORE_ARM`、`UNSET` 或任意 placeholder进入 stage/seal-dev；
- CONFIRM materialized config 不允许任何占位、dirty worktree、未跟踪 template 或 hash mismatch；
- resolved config 必须完整写入 output；除两个 runtime path sentinel 和上节明列的
  CONFIRM final-plan provenance 外，不得静默补默认值；
- config version 不兼容时失败，不做猜测迁移。

`FrozenRef` 的唯一 path 语义如下。任何 materialized config、map YAML、schedule manifest、
report 或其他冻结对象中的 `path`/`*_path`，只要它指向 release 内只读输入，就必须是
**validated release root-relative POSIX path**：非空、无前导 `/`、无 `.`/`..` component、
不用反斜杠、不含 NUL，且不得经过 symlink。运行时先由
`calibagent-p8-config-validate release --release-root ABS` 验证并锁定 release manifest、
checksums 和 exact allowlist，得到 `ValidatedReleaseRoot`；之后只能把 ref 解析为
`ValidatedReleaseRoot / PurePosixPath(ref.path)`，并再次验证 regular-file identity、raw hash
与 allowlist。config 自身位于哪个子目录不参与解析，config 中的 `release_root="."` 只是
被 materializer 冻结的 namespace marker，不授权使用进程 cwd 或 config parent。CLI 传入的
`--config/--schedule` 也必须分别等于该 validated root 下 config 已绑定的 canonical path；
absolute input ref、`../`、config-relative/map-relative fallback 或 hash 相同的 release 外文件
一律在连接机器人或写 output 前退出 2/6。

tracked template 同样只保存上述 **final release namespace**，不保存 repository path。
`config-validate tracked`、schedule generator 和 Gate A 只能通过下面唯一
`RepositorySourceMap` 把 canonical ref 映射到 tracked source；没有最长前缀猜测、cwd fallback
或 glob：

```text
protocol/p8_go2_real_deployment_data_handoff_zh.md -> docs/p8_go2_real_deployment_data_handoff_zh.md
protocol/p8_go2_implementation_guide_zh.md         -> docs/p8_go2_implementation_guide_zh.md
protocol/p8_safety_review_criteria.yaml            -> configs/experiments/p8_safety_review_criteria.yaml
protocol/analysis_plan_template.yaml               -> configs/experiments/p8_analysis_plan_template.yaml
configs/p8_real_safety.yaml                        -> configs/hardware/go2/p8_real_safety.yaml
configs/topic_map.yaml                             -> configs/hardware/go2/topic_map.yaml
configs/reference_to_base_extrinsic.yaml            -> configs/hardware/go2/reference_to_base_extrinsic.yaml
configs/human_trust_registry.yaml                  -> configs/hardware/go2/human_trust_registry.yaml
maps/<allowlisted-path>                            -> configs/maps/<same-allowlisted-path>
commands/nav/<allowlisted-basename>                -> configs/commands/nav/<same-basename>
commands/shift/<allowlisted-basename>              -> configs/commands/shift/<same-basename>
schemas/<allowlisted-path>                         -> schemas/p8/<same-allowlisted-path>
environment/<allowlisted-path>                     -> §4.2/§23.2 表中逐项 source_path
schedules/<allowlisted-basename>                   -> role-matched schedule generator NEW_DIR/<same-basename>
```

这里的 `<allowlisted-*>` 只能取 handoff §3.1 展开的 exact basename/path；它不是通配复制规则。
`protocol/analysis_plan.yaml` 只有 `prepare` 的单一派生源，四个 materialized experiment config
只有 `stage-integration` 的四个 template+role schedule 派生源，均不接受普通 source-map lookup。

integration stage 尚不是 release，故只允许 freeze/Gate B/C 内部构造的
`ValidatedStageRoleView(stage, role)` 解析同一 canonical namespace。其确定性映射为：

```text
configs/p8_real_nav_<role-suffix>.yaml   -> stage/views/<ROLE>/configs/<same-basename>
configs/p8_real_shift_<role-suffix>.yaml -> stage/views/<ROLE>/configs/<same-basename>
schedules/<allowlisted-basename>          -> stage/views/<ROLE>/schedules/<same-basename>
其他 canonical ref                        -> stage/common/<canonical-ref>
```

`ROLE=DEV` 时 `<role-suffix>=dev`，`ROLE=CONFIRM` 时为 `confirmatory`。resolver 必须先验证
stage manifest/checksums、role、两份 config 和四份 schedule 的 exact allowlist；两个分支若能
映射到同一 canonical path、目标缺失/额外、symlink 或 raw hash不符即退出 6。stage checksum
继续记录真实 `common/...`/`views/...` path；`ValidatedStageRoleView` 只是读取映射，不创建
symlink/overlay。seal 后把对应 view 确定性合并成 flat release，此后统一改用
`ValidatedReleaseRoot`。因此 map/command/survey/photo refs 的字面值在 template、stage
role-view、DEV release 和 CONFIRM release 中始终一致；template 的 `schedule` 是唯一允许的
null derived slot，物化后在 stage role-view、DEV release 和 CONFIRM release 中字面值始终为
`schedules/schedule_manifest.json`。NAV/SHIFT command 为 `commands/nav/...`、
`commands/shift/...`，map 为 `maps/<map_id>.yaml`，survey/photo 为
`maps/evidence/<map_id>/...`。

hash 对 freeze 工具复制后的原始 bytes 计算；不得重排 YAML、重写
float 或换行后沿用旧 hash。仓库用 `.gitattributes` 将 Markdown、Python、YAML、JSON、
CSV、TOML、XML、shell、C/C++、text/lock/patch 与 Dockerfile 明确冻结为 LF；唯一 binary
override 是已采集且需保持原始 bytes 的 `evidence/p1_real/raw_trials.csv`。新 P8 CSV 用
UTF-8、逗号、RFC 4180 quoting、LF 行末。
`checksums.sha256` 不包含自身。导出表的 `schedule_sha256` 是 schedule
源文件 bytes hash，由 resolved manifest 填入；schedule CSV 本身不带该列。

四份 tracked config template 必须分别通过
`p8.nav-config-template.v1|p8.shift-config-template.v1`，其顶层与对应 materialized
config 相同，但 exact derived slots 为：

```text
schema_version = "p8.nav-template.v1" | "p8.shift-template.v1"
release_root = null
source_commit = null
container_digest = null
schedule = null
```

`dataset_role,run_id,protocol_version`、全部实验参数、file refs 和
`analysis_plan_template` 均必须已经非空冻结。template 内 path 使用第 3 节 final
release-relative namespace，validator 以 fixed source→release mapping 在 repository 中定位并重算
raw hash，不把 path 相对 template 目录猜测。schedule generator 仅接受同 role 的
NAV/SHIFT template pair，从已冻结 seed/design 生成 role-matched schedule manifest。

`stage-integration` 是唯一 materializer。对每个 role/protocol，它先验证 template raw
hash 与 schedule generator provenance，再仅做以下替换：

```text
schema_version -> "p8.nav.v1" | "p8.shift.v1"
release_root -> "."
source_commit -> signed Gate A/source/remote 的同一 40-hex commit
container_digest -> stage 的同一 OCI sha256:<64hex>
schedule -> {path: "schedules/schedule_manifest.json",
             file_sha256: <role-matched manifest raw SHA-256>}
```

其余字段在 YAML load 后的 typed semantic tree 必须与 template 逐位相同；然后以与
analysis plan 相同的冻结 PyYAML profile 写出。stage manifest/candidate/final manifest 分别记录
`template_path,template_raw_sha256,materialized_path,materialized_raw_sha256,
schedule_manifest_raw_sha256`。将 commit/hash 回写 tracked template、在 materialization 后手改 config、
或用 config 生成了它所引用的 schedule 都是 integrity failure。

冻结 YAML 不保存现场绝对写路径：`recording.output_root` 必须逐字为
`RUNTIME_OUTPUT_ROOT`；safety YAML 的 run-scoped `protocol_store.root_path` 必须为
`RUNTIME_OUTPUT_ROOT/protocol_state`，robot-global supervisor/receipt/quota roots 必须位于
`ROBOT_GLOBAL_STATE_ROOT/{supervisor,operator_gate,quota}`。launcher 要求显式
`--output-root ABS_NEW_PATH --robot-state-root ABS_DURABLE_PATH`，只替换这两个 sentinel 后
生成 run-specific resolved config并计算完整 SHA-256；不改 frozen source config/hash。
CONFIRM output 必须在 release/repository 外、无 symlink、目标不存在或是该 run 的
write-once resume目录；robot-state root 同样在 release 外，但必须是已初始化、权限受控、
跨进程/重启/换 run 持久的同一 mounted directory，绝不能要求为空。

`--schedule`、`--dataset-role`、`--resume-run-id` 都只是显式确认而非 override：schedule
resolved path/raw hash 必须与 config entry相同，dataset role逐字相同；resume ID 必须等于
config.run_id和 existing run manifest，且 output root恰为该 manifest root。首次 run 禁止
`--resume-run-id`，resume禁止换 output/global-state root。任一不等在写文件/联系机器人前
失败。除两个路径 sentinel 外，CLI、环境变量和 launcher不得覆盖冻结 config。

### 6.2 NAV config 必须验证

```text
schema_version == "p8.nav.v1"
methods == [B0_raw, B1_dense, B2_lhs, B3_sobol,
            B4_d_opt, B5_active_no_task, B6_random, B8_full]
[item.map_id for item in maps] ==
    [real_offset_slalom, real_weighted_arc]       # maps 是对象数组；顺序由 schedule 决定
blocks == (dataset_role == DEV ? 5 : 30)
dense_trials == 30
matched_trials == 12
validation_commands == 8 unique rows
feature_set == m1_affine
planner_rate_hz == 10
control_rate_hz >= 50
reference_min_rate_hz == 40
timeout_s == 60
```

NAV YAML 的完整顶层 key 固定为：

```text
schema_version,dataset_role,run_id,protocol_version,release_root,source_commit,
container_digest,topic_map,safety_config,reference_extrinsic,human_trust_registry,
safety_review_criteria,
schedule,maps,methods,blocks,
trial_profile,calibration_start_gate,command_space,command_tables,model,
method_design,planner,inverse_compensator,velocity_feedback,navigation,
quality,recording,resume,analysis_plan_template
```

其中下列 nested key 全部 required；DEV 未知现场值可为
`REQUIRED_BEFORE_ARM`，CONFIRM 不可：

```yaml
trial_profile: {precheck_min_s, ramp_in_s, settle_s, measure_s, ramp_out_s,
                sample_rate_hz, equivalent_motion_s}
calibration_start_gate: {pose_xy_yaw, position_tolerance_m,
                         yaw_tolerance_rad, stationary_window_s,
                         maximum_speed_mps, maximum_start_pose_gate_age_ms, return_mode,
                         maximum_context_returns}
command_space: {lower_vx_vy_wz, upper_vx_vy_wz, maximum_linear_norm,
                maximum_coupled_load}
model: {feature_set, prior_gain, prior_scale, noise_variance_vx_vy_wz,
        hinge_thresholds_vx_vy_wz, maximum_feature_condition_number}
method_design: {dense_trials, matched_trials, active_seed_trials,
                active_online_trials, validation_trials, design_semantics}
planner: {risk_weight, distance_weight, duplicate_distance,
          candidate_duration_s, candidate_pool_sha256,
          feature_reference_pool_sha256, task_distribution_sha256}
inverse_compensator: {regularization, risk_weight,
                      undertracking_confidence_weights,
                      inactive_axis_command_limits, enforce_axis_signs,
                      sign_threshold, duration_s}
velocity_feedback: {gain, ema_alpha, maximum_correction,
                    activation_threshold, startup_delay_s,
                    recovery_reengagement_delay_s}
navigation: {planner_rate_hz, control_rate_hz, reference_min_rate_hz,
             timeout_s, initial_stabilization_s, cruise_speed_mps,
             maximum_lateral_speed_mps, maximum_yaw_rate_rps,
             position_gain, heading_gain, waypoint_radius_m, goal_radius_m,
             maximum_linear_accel_mps2, maximum_angular_accel_rps2,
             predictive_wire_horizon_s, height_rate_guard, stall_recovery,
             terminal_priority}
height_rate_guard: {activation_height_m, minimum_drop_per_planner_tick_m,
                    hold_s, maximum_linear_command_norm,
                    high_rate_interlock}
high_rate_interlock: {enabled, activation_height_m, release_height_m,
                      minimum_clearance_m, prediction_steps}
stall_recovery: {minimum_desired_speed_mps, maximum_actual_speed_mps,
                 maximum_base_height_m, detection_s,
                 emergency_base_height_m, zero_command_s,
                 emergency_zero_command_s, maximum_attempts,
                 maximum_emergency_attempts}
quality: {reference_max_age_ms, onboard_max_age_ms, imu_max_age_ms,
          bms_max_age_ms, command_echo_max_age_ms, maximum_clock_offset_ms,
          maximum_cross_stream_skew_ms, minimum_measure_samples,
          minimum_reference_rate_hz, maximum_reference_gap_s,
          minimum_steady_ratio, maximum_command_deviation}
recording: {output_root, rosbag_storage_id, bag_split_size_bytes,
            bag_split_duration_s, video_required, minimum_free_bytes}
resume: {allow_explicit_resume, checkpoint_every_unit,
         new_bag_segment_on_resume,maximum_rerun_tech_attempts_per_unit}
analysis_plan_template: {path, file_sha256}
```

本冻结 P8 的 CONFIRM config 强制
`calibration_start_gate.return_mode=manual_reposition_disarmed`。
`approved_controlled_return` 仅保留为 DEV-only future extension；v1 runner 遇到
CONFIRM+controlled 必须 schema失败，DEV 若没有另行批准的 trajectory schema/implementation
也必须 fail closed。正式 release 因而不需要也不允许实机同事发明自动回位控制器。

`maps` 每项为 `{map_id,path,file_sha256}`，且只能两项；不再接受字符串 shorthand。按
canonical map order，两项 path 必须分别逐字为
`maps/real_offset_slalom.yaml,maps/real_weighted_arc.yaml`。
`topic_map/safety_config/reference_extrinsic/human_trust_registry/
safety_review_criteria/schedule` 均为
`{path,file_sha256}`；其中
`reference_extrinsic.path` 必须逐字为 release-root-relative
`configs/reference_to_base_extrinsic.yaml`；其余四项 path 依次必须逐字为
`configs/topic_map.yaml,configs/p8_real_safety.yaml,configs/human_trust_registry.yaml,
protocol/p8_safety_review_criteria.yaml`。
`schedule.path` 必须逐字为 `schedules/schedule_manifest.json`，不能只写 basename、改成
config-relative path或指其中某一 CSV。`command_tables`
的每项同样是 path+hash，其 key 精确对应第 3 节 NAV 目录，且 path 只能是
`commands/nav/<与 key 相同的 basename>`；九个允许值按 target-tree 顺序为
`commands/nav/candidate_pool.csv,commands/nav/feature_reference_pool.csv,
commands/nav/dense_design.csv,commands/nav/lhs_design.csv,
commands/nav/sobol_design.csv,commands/nav/random_design.csv,
commands/nav/active_seed.csv,commands/nav/validation_commands.csv,
commands/nav/task_distribution.csv`。

NAV/SHIFT 四个 tracked source config 都只含
`analysis_plan_template:{path,file_sha256}`；path 必须逐字为 canonical
`protocol/analysis_plan_template.yaml`。tracked validator 仅通过第 6.1 节
`RepositorySourceMap` 定位 repository 的
`configs/experiments/p8_analysis_plan_template.yaml`，运行期仅从 validated release root读取。
source config 不含未知 final-plan hash，也不允许
`PENDING/UNSET/REQUIRED_BEFORE_ARM` 假冒 hash。冻结 release 时不修改 config bytes：

- DEV resolved config 仅记录 `analysis_plan_template` ref，`analysis_plan=null`；
- CONFIRM resolved config 同时记录 template ref 与
  `analysis_plan:{path="protocol/analysis_plan.yaml",file_sha256=<final raw hash>}`；该 final ref
  必须从 sealed `release_manifest.json` 的 derived-plan binding 获取，不受 CLI/config override。

`resolved_config.schema.json` 用 `dataset_role` conditional 实现上述 exact nullability，并绑定
`analysis_plan_template_sha256,pilot_input_lock_manifest_raw_sha256,
analysis_plan_sha256`的唯一派生关系。CONFIRM 的 final plan 只有第 3/§19.4.7 节 generator
能产生；替换 plan 或 template/config 任一 byte 都使 release/config 验证失败。
这些字段必须以 `schemas/p8/nav_config.schema.json` 固化，example YAML
和 dataclass 由同一 schema contract test 校验。
NAV template/materialized schema 还必须用 `dataset_role` conditional 将 DEV
`blocks=5` 与 CONFIRM `blocks=30` 写成两个 `const`；不得只检查正整数，也不得让 CLI
覆盖。两种 role 都保持上述 8 methods 和两路线。
NAV/SHIFT 两者的 `prior_gain` 都是长度 3 的有限正数数组，
`prior_scale` 是正 finite scalar，`noise_variance_vx_vy_wz` 是长度 3 的正
finite 数组。
`resume.maximum_rerun_tech_attempts_per_unit` 是 positive integer，精确计
`attempt_role=RERUN_TECH` 的 attempt rows，不含最初 PRIMARY，也不含 boundary 前只有
run-level event 的 preparation failure；NAV/SHIFT schema、resolved config、example、
fixture 和 release hash 都必须含同一字段。达到上限后 cursor 进入
`TECH_RETRY_EXHAUSTED`，当前 unit/delivery incomplete，普通 resume/retry 均退出 5；不得
现场提高数值。

同时验证每个速度 command table 的 `command_id,cmd_vx,cmd_vy,cmd_wz`：
有限、ID/速度行唯一、在 command space 内、
通过冻结安全 envelope、SHA-256 匹配。B2/B3/B6 在机器人上只加载 tracked CSV，
不调用 RNG。B4/B5/B8 可在线选，但 candidate pool 和 task distribution 必须冻结。

NAV 方法定义不得猜测：B1=30 行 dense；B2/B3/B6=各自 CSV 的
12 行；B4=12 次 online D-opt；B5/B8=前 6 行共享 `active_seed.csv`
axis seed + 后 6 次 online IVR，区别仅在 B5 使用 uniform/no-task
distribution，B8 使用冻结 task weights。B5 的 uniform support 精确等于
`candidate_pool.csv` 的全部 command rows，按文件行顺序、每行归一化 weight=`1/N`，绑定
candidate-pool raw hash；不得改用 `task_distribution.csv` rows、feature reference pool或
只对 planner top-k等权。B8 才读取/归一化 `task_distribution.csv.weight`。新增与现有 P7
`TaskDistribution.uniform(pool.commands)` 的 fixed-pool weight/order/IVR score parity test。
B0 无 calibration。

`task_distribution.csv` 和速度表不同，列为
`task_id,cmd_vx,cmd_vy,cmd_wz,weight`；weight 有限、非负，至少一个为正，
loader 必须归一化到和为 1 并导出归一化值。reference pool 变换后的
design matrix 必须满列秩，2-norm condition number 不超过 config 的
`maximum_feature_condition_number`。M1 仍显式写 hinge thresholds，但只作为
serialization parity 元数据、不生成 hinge features。
tracked NAV source 位于 `configs/commands/nav/`，但 template/materialized config 永远只
保存 canonical `commands/nav/` refs。tracked validator 使用 `RepositorySourceMap`；runtime
loader 使用显式 `ValidatedReleaseRoot` 或 `ValidatedStageRoleView`，不得读取 SHIFT 同名表。

### 6.3 SHIFT config 必须验证

```text
schema_version == "p8.shift.v1"
methods == [frozen, passive, full]
shifts == [R1_command_gain_coupling, R2_payload_com,
           R3_surface_friction, R4_mixed_context]
blocks_per_shift == (dataset_role == DEV ? 5 : 20)
feature_set == m2_affine_cross_hinge
pre_calibration_trials == 12
pre_calibration_seed_trials == 6
pre_calibration_active_trials == 6
pre_monitor_trials == 4
post_monitor_trials == 5
recovery_trials == 12
validation_trials == 12
validation_window == 4
posterior_inflation_factor == 8.0
target_rmse_multiplier == 1.30
target_rmse_floor == 0.075
target_rmse_ceiling == 0.140
invalid_window_rmse_penalty == 0.25
```

SHIFT YAML 与 NAV 共用 release/topic/safety/trial/start/quality/recording/resume
结构，不同的完整顶层 key 为：

```text
schema_version,dataset_role,run_id,protocol_version,release_root,source_commit,
container_digest,topic_map,safety_config,reference_extrinsic,human_trust_registry,
safety_review_criteria,
schedule,methods,shifts,
blocks_per_shift,trial_profile,calibration_start_gate,command_space,
command_tables,model,planner,detector,adaptation,shift_actuators,
nominal_restore,quality,recording,resume,analysis_plan_template
```

SHIFT-specific nested keys：

```yaml
model: {feature_set, prior_gain, prior_scale, noise_variance_vx_vy_wz,
        hinge_thresholds_vx_vy_wz, maximum_feature_condition_number}
planner: {risk_weight, distance_weight, duplicate_distance,
          candidate_duration_s, candidate_pool_sha256,
          feature_reference_pool_sha256, task_distribution_sha256}
detector: {reference_nis, allowance, alarm_threshold,
           minimum_positive_evidence, evidence_window_trials,
           minimum_dwell_trials, covariance_jitter}
adaptation: {pre_calibration_trials, pre_calibration_seed_trials,
             pre_calibration_active_trials, pre_monitor_trials,
             post_monitor_trials, recovery_trials, validation_trials,
             validation_window, posterior_inflation_factor,
             target_rmse_multiplier, target_rmse_floor,
             target_rmse_ceiling, invalid_window_rmse_penalty,
             stop_updates_after_recovery}
shift_actuators: {R1_command_gain_coupling, R2_payload_com,
                  R3_surface_friction, R4_mixed_context}
nominal_restore: {commands_path, commands_sha256, thresholds_path,
                  thresholds_sha256, reference_snapshot,
                  maximum_verification_sets, maximum_changeover_attempts}
```

SHIFT template/materialized schema 必须同样以 role conditional 冻结 DEV
`blocks_per_shift=5`、CONFIRM `blocks_per_shift=20`；两种 role 都保留全部 R1–R4 和
三种 methods。DEV 不是截取 CONFIRM schedule，而是由 DEV template/seed 独立生成。

`maximum_context_returns`、`maximum_verification_sets` 和
`maximum_changeover_attempts` 均为 CONFIRM 前冻结的正整数；前者同时适用于 NAV/SHIFT
共享的 `calibration_start_gate`。schedule generator 必须据此完整预展开 conditional
registry，runner 不得把这些值当现场可增大的 retry counter。

四个 `shift_actuators` value 也禁止自由扩展，完整 required key 为：

```yaml
R1_command_gain_coupling:
  {transform_id, matrix_row_major, matrix_sha256,
   nominal_transform_id, nominal_matrix_sha256,
   require_identity_before_apply, expected_identity_readback_sha256,
   required_evidence_types}
R2_payload_com:
  {payload_id, target_added_mass_kg, added_mass_tolerance_kg,
   maximum_total_payload_kg, bracket_frame,
   approved_installation_coordinates_xyz_m,
   maximum_abs_com_offset_xyz_m, required_evidence_types}
R3_surface_friction:
  {surface_id, material, batch_id, required_surface_state,
   friction_proxy_method, friction_proxy_unit,
   minimum_friction_proxy, maximum_friction_proxy,
   required_evidence_types}
R4_mixed_context:
  {payload_profile_ref, surface_profile_ref,
   pre_task_path, pre_task_sha256, post_task_path, post_task_sha256,
   changeover_mode, required_evidence_types}
```

所有 array 的长度、单位、finite 条件和 enum 均进 JSON Schema：matrix 恰 9 个
row-major finite 数；坐标/COM 恰 3 个 m 数；质量和 tolerance 为非负 finite；
friction proxy 下限不大于上限；`changeover_mode` 只能是
`single_zero_disarmed_barrier`；`required_evidence_types` 必须覆盖第 16.6 节对应
类型。DEV 可放 `REQUIRED_BEFORE_ARM`，但 schema 仍不允许未知 key；CONFIRM 全部
必须是现场冻结值。

`prior_gain` 是初始线性 identity gain，必须是三个有限正数；
`prior_scale>0`，三轴 `noise_variance>0`，M2 的三个 hinge threshold
有限且在各轴命令边界内。`model_factory` 使用这些值构造 prior，
不得读库默认值。`detector.covariance_jitter` 必须是 finite positive，且必须显式
传给 `DomainShiftConfig`，不得沿用库默认值。

canonical frozen ref `commands/shift/pre_calibration_seed.csv`（tracked source 由
`RepositorySourceMap` 映射到 `configs/commands/shift/pre_calibration_seed.csv`）必须恰有
6 个 axis seed；两个
monitor 表、`passive_recovery.csv` 和 SHIFT 自己的 `validation_commands.csv`
必须冻结逐行顺序及 hash。
其后 6 个 nominal calibration trial 在线使用冻结 task-aware IVR；三方法共享
planner/pool/task/config，不共享 observation/posterior，实际选择可不同。runner
不得自行使用 P6 模块常量，因为仿真常量不是交付文件。
SHIFT `command_tables` 的十二个 path 只能按第 3 节 basename 落在 canonical
`commands/shift/` namespace；`nominal_restore.commands_path/thresholds_path` 分别逐字为
`commands/shift/restore_sentinel.csv` 与
`commands/shift/nominal_restore_thresholds.yaml`，R4 actuator 的
`pre_task_path/post_task_path` 分别逐字为
`commands/shift/r4_task_pre.csv` 与 `commands/shift/r4_task_post.csv`。tracked source
统一由 `RepositorySourceMap` 映射到 `configs/commands/shift/`，runtime loader 只从
`ValidatedReleaseRoot` 或 `ValidatedStageRoleView` 的 `commands/shift/` 读取，不得读取 NAV
同名表。

`r4_task_pre.csv`/`r4_task_post.csv` 列为
`task_id,cmd_vx,cmd_vy,cmd_wz,weight`，各自归一化，两个 file hash 必须
不同。R4 在唯一 changeover marker 前只可读 pre table，之后只可读
post table；policy 只得到当前 commands+weights，不得到 table ID、hash 或
`context_stage`。

### 6.4 map geometry 必须验证

两张 YAML 均需：

```text
schema_version, map_id, world_frame
start_pose[x,y,yaw], start_position_tolerance_m, start_yaw_tolerance_rad
intermediate_waypoints[[x,y], ...], waypoint_radius_m
goal[x,y], goal_radius_m
obstacles[{id,center_xy,size_xy,height_m,material}]
robot_footprint{type:"circle",radius_m}
collision_rule{online_footprint_margin_m,contact_topic_required,
               contact_force_threshold_n,retrospective_video_adjudication}
timeout_s
survey_method, survey_timestamp_utc, survey_file, survey_file_sha256,
survey_maximum_disagreement_m, survey_maximum_disagreement_rad
overview_photo, overview_photo_sha256
```

文件内不存在 `geometry_sha256`；它的 file hash 在 NAV config 和 release
manifest 中。`route_targets = intermediate_waypoints + [goal]`，禁止把 goal 再写成
最后一个 intermediate waypoint。障碍是 world-frame 2D axis-aligned rectangle；
`center_xy/size_xy` 均为长度 2 的正有限 m 值，`height_m>0`。在线 collision
只由冻结 footprint/contact 规则触发并立即 zero；视频只用于事后盲态
裁定，不承担实时安全。

`survey_file` 与 `overview_photo` 不是 map-YAML-relative path；它们必须分别逐字为
validated-root-relative
`maps/evidence/<map_id>/survey.csv` 与
`maps/evidence/<map_id>/overview_photo.jpg`。tracked validator 只经第 6.1 节
`RepositorySourceMap` 定位到 `configs/maps/evidence/...`；loader/freeze 工具验证 raw-byte
hash、拒绝 symlink/逃逸/额外证据
文件。`survey.csv` 至少含 survey point ID、world-frame xyz、测量设备、单位和不确定度，
照片必须含可见标尺且与 YAML geometry 一致。`survey.csv` 的 UTF-8/LF header 精确为：

```text
map_id,feature_kind,feature_id,field_name,component,value,unit,
instrument_id,instrument_calibration_sha256,measured_utc,operator_id
```

row key `(map_id,feature_kind,feature_id,field_name,component)` 唯一；value finite；unit 只允许
`m|rad`；instrument/calibration hash/time/operator non-empty。loader 必须为 start pose、每个
waypoint、goal、每个 obstacle 的 center/size/height 和 footprint radius 找到逐 scalar row，
并分别在 YAML 的 maximum disagreement m/rad 内复算一致；缺 row、额外未知 geometry row、
超容差均 fail。`schemas/p8/map_survey.schema.json` 固化 header、枚举、主键和与
`map_geometry.schema.json` 的 cross-check；overview 必须是可解码 JPEG，EXIF 不能作为唯一
时间/身份来源。

坐标必须在 DEV 现场测量。coding agent 只实现 schema、loader 和 controller；不得
把 P7 Isaac 数值复制成真实坐标。

### 6.5 topic map 必须验证

每个逻辑通道声明：完全限定 topic 名、完整 ROS message type、字段路径、单位、
frame、QoS reliability/durability/history/depth、最低频率、最大 age、是否 required。
启动时用 ROS graph 验证实际 publisher type 和 publisher count。vendor motion topic
必须只有 command relay 一个 publisher；发现第二个 publisher 立即拒绝 arm。

`topic_map.yaml` 顶层只允许
`schema_version,robot_id,ros_domain_id,namespace,channels`。`logical_name` 的完整
机器枚举固定为：

```text
planner_desired_command,planner_candidates,safety_decision,
inverse_compensated_command,model_input_command,post_transform_command,
transmitted_command,command_ack,independent_reference_pose,
onboard_odometry_state,imu_attitude_yaw_rate,base_height,joint_motor_state,
foot_contact,battery_bms,localization_health,model_prediction,
posterior_snapshot,shift_detector,experiment_marker,navigation_marker,changeover_marker,
collision_safety_event,state_machine_transition,network_clock_diagnostics,
reference_state,robot_health,recorder_status,runner_heartbeat,
command_packet,command_telemetry,vendor_motion_command
```

每个 enum 恰出现一次，不得用近义词。现场确实不存在的 `command_ack` 或
`foot_contact` 仍保留 entry，令 `availability=not_available` 并给非空
`unavailable_reason`；此时 `topic/message_type/field_map/units/frame` 写 JSON null，
其余通道不得这样做。每个 channel 恰有：

```text
logical_name,topic,message_type,field_map,units,frame,
qos{reliability,durability,history,depth,deadline_ms,liveliness,
    liveliness_lease_ms},minimum_rate_hz,maximum_age_ms,required,
expected_publisher_count,ack_semantics,availability,unavailable_reason
```

`ack_semantics` 只允许 `controller_applied,bridge_accepted,relay_echo,not_available`；
derived `ack_available := ack_semantics in
{controller_applied,bridge_accepted}`，config、preflight、recorder 和 exporter 只能使用这个
推导值，`topic_map` 不另造 `ack_available` 字段。`availability` 只允许
`required,available_optional,not_available`；除上述两个条件通道外均必须为
`required`。不可用一个未定义“state”通道合并 BMS/IMU 的 age。

### 6.5.1 reference-to-base 外参必须验证

`reference_to_base_extrinsic.yaml` 是独立 reference frame 到机器人 base frame 的唯一冻结
刚体外参，不得藏在 launch 参数、TF static publisher 或代码常量中。顶层 key 精确为：

```text
schema_version,parent_frame,child_frame,translation_xyz_m,rotation_xyzw,
calibration_method,calibration_id,calibrated_utc,source_measurement_sha256,approved_by
```

`schema_version="p8.reference-extrinsic.v1"`；translation 是 3 个 finite m 值；quaternion
是 4 个 finite 值、顺序 xyzw、2-norm 在 `1±1e-6`，且 loader 归一化后结果必须仍在同一
hash-bound resolved value；parent/child 不同且分别与 topic map 的 independent reference
frame 和 safety/map 的 base/world frame contract 方向一致。`calibration_id`、source raw
measurement hash、UTC 和批准人均 non-empty；CONFIRM 禁止 identity/zero placeholder，除非
真实标定结果恰为 identity 且 calibration report 明确证明。schema 固定为
`schemas/p8/reference_extrinsic.schema.json`，raw file hash 写 config、preflight、resolved
config、release/delivery manifest 和每个 block-session initialization result。

### 6.5.2 双人 approval 与 trust registry

`human_trust_registry.yaml` 只含公钥，顶层精确为
`schema_version,registry_id,robot_id,valid_from_utc,valid_until_utc,people`；每个 person精确含
`person_id,key_id,ed25519_public_key_base64,roles,valid_from_utc,valid_until_utc,revoked`。
`roles` 只允许
`operator|safety_operator|safety_reviewer|pi|data_custodian|software_lead|
deployment_lead|hardware_lead|safety_lead|data_lead`；person/key全局
唯一。CONFIRM 需要至少两名不同 person，且 operator与safety_operator角色由不同 key验证。
registry raw hash进入 NAV/SHIFT config、resolved config、preflight、release manifest和
watchdog commissioning state；现场不能加名字或换 key。

签名前必须先持久化 strict `HumanApprovalRequest`，不允许 signer 从命令行自由
组合 purpose/subject/role。其顶层字段精确为：

```text
schema_version="p8.human-approval-request.v1",request_id,approval_purpose,
subject_kind,subject_id,subject_sha256,robot_id,run_id,dataset_role,
required_roles,minimum_distinct_people,minimum_distinct_keys,
issued_utc,expires_utc,trust_registry_sha256,request_sha256
```

`dataset_role` 只允许 `DEV|CONFIRM|TEST_FIXTURE`；`required_roles` 是无重复的非空
array，且必须按下表所列顺序逐字符相等，不能自由排序或缩减。
`minimum_distinct_people=minimum_distinct_keys=len(required_roles)`。UTC 字符串只允许
`YYYY-MM-DDTHH:MM:SSZ`；`expires_utc-issued_utc` 必须为正数且不超过下表 TTL。
`request_sha256=sha256(JCS(request 排除 request_sha256))`；
`HumanApproval.approval_request_sha256` 必须等于这个 semantic hash，不是包含
self-hash 后文件的 raw SHA-256。request 文件仍按第 5.3 节用 class index
同时记录 semantic/raw hash。

| purpose | `subject_kind` / `subject_id` | `subject_sha256` 的唯一 preimage | `required_roles` | maximum TTL |
|---|---|---|---|---:|
| `SCOPE` | `SCOPE_AUTHORIZATION_REQUEST` / `scope_authorization_id` | `scope_request_sha256` | `operator,safety_operator` | 43,200 s |
| `CHANGEOVER` | `EVIDENCE_BUNDLE_CONTENT` / `changeover_uid/phase` | 第 16.6 节 `content_preimage_sha256` | `operator,safety_operator` | 900 s |
| `CONTEXT_RETURN` | `CONTEXT_RETURN_GATE_PAYLOAD` / `attempt_uid` | strict `p8.gate.context-return.v1` payload 的 `payload_sha256` | `operator,safety_operator` | 900 s |
| `RESET` | `RESET_AUTHORIZATION_REQUEST` / `robot_id/watchdog_boot_id/watchdog_state_sequence` | `reset_request_sha256` | `operator,safety_operator` | 600 s |
| `SAFETY_REVIEW` | `BLIND_SAFETY_VERDICT` / `review_token` | 下文 strict `decision_sha256`（同时绑定 bundle、verdict、reasons） | `safety_operator,safety_reviewer` | 604,800 s |
| `GATE_REPORT` + Gate A | `GATE_REPORT_PREIMAGE` / `A` | `report_preimage_sha256` | `software_lead` | 604,800 s |
| `GATE_REPORT` + Gate B | `GATE_REPORT_PREIMAGE` / `B` | `report_preimage_sha256` | `deployment_lead,safety_operator` | 604,800 s |
| `GATE_REPORT` + Gate C | `GATE_REPORT_PREIMAGE` / `C` | `report_preimage_sha256` | `hardware_lead,safety_lead` | 604,800 s |
| `GATE_REPORT` + Gate D | `GATE_REPORT_PREIMAGE` / `D` | `report_preimage_sha256` | `data_lead,pi,safety_lead,software_lead` | 604,800 s |
| `DATA_LOCK` | `DATA_LOCK_INPUT_SET` / `lock_id` | 下文 `data_lock_approval_subject_sha256` | `data_custodian,pi` | 86,400 s |

`data_lock_approval_subject_sha256` 精确为下列 strict object 的 JCS SHA-256：
`{schema_version="p8.data-lock-approval-subject.v1",lock_id,dataset_role,run_id,
input_lock_manifest_path,input_lock_manifest_semantic_sha256,
input_lock_manifest_raw_sha256,analysis_plan_sha256,safety_review_criteria_sha256,
safety_review_chain_tail_sha256,required_review_count,completed_review_count}`。它排除尚未
存在的 approval refs、`locked_utc`与 `data_lock_sha256`，因而无自循环。
request 收集器必须对每个 required role 收到恰好一份 approval，且所有
person/key/nonce 两两不同。验证时要求
`request.issued_utc <= approval.issued_utc < approval.expires_utc <= request.expires_utc`，
并且 approval 在对应 receipt/review/gate/data-lock 的 immutable consume UTC 时仍
有效。日后离线 replay 核查该 consume UTC，不用当前 wall clock 使历史签名失效。

所有人工同意使用同一 strict `HumanApproval`：

```text
schema_version="p8.human-approval.v1",approval_id,approval_purpose,
subject_kind,subject_id,subject_sha256,robot_id,run_id,dataset_role,person_id,key_id,role,
issued_utc,expires_utc,nonce_hex,trust_registry_sha256,approval_request_sha256,payload_sha256,
signature_ed25519_base64,approval_sha256
```

purpose 枚举为 `SCOPE|CHANGEOVER|CONTEXT_RETURN|RESET|SAFETY_REVIEW|
GATE_REPORT|DATA_LOCK`。coordinator 先生成上述 strict approval-request；
signer先填 person/key/role/issued/expiry/128-bit random nonce；`payload_sha256` 精确等于该
完整 record排除 `payload_sha256,signature_ed25519_base64,approval_sha256` 后的 JCS bytes
SHA-256，因此 subject、trust registry、person/key/role、time与nonce全在签名域内。Ed25519
签名消息为 domain prefix `CalibAgent-P8-HumanApproval-v1\0` 的 ASCII bytes拼接
`payload_sha256` raw 32 bytes；`approval_sha256` 对加入 signature后的最终 record排除自身字段
的JCS bytes计算。schema验证 64-byte signature、NFC、UTC/expiry、nonce、subject 和
`dataset_role∈{DEV,CONFIRM,TEST_FIXTURE}`；approval 的 purpose/subject/robot/run/dataset/
trust-registry 必须与其 request 逐位相同。watchdog/OperatorGate还必须用冻结
registry验签、role、有效期/revocation。两份 approval的
`approval_request_sha256` 都等于共同 request 的 `request_sha256`，purpose/subject/
robot/run/dataset/trust-registry 逐位相同；由于
signer metadata不同，各自 signed `payload_sha256` 必须不同且分别验签。双人 gate还要求不同
`person_id`、不同 `key_id`、不同 nonce。
比较两个字符串 ID 绝不算授权。

`calibagent-p8-sign-approval` 是唯一 repository signer wrapper：

```text
calibagent-p8-sign-approval prepare-request
  --purpose SCOPE|CHANGEOVER|CONTEXT_RETURN|RESET|GATE_REPORT
  --subject PATH --trust-registry PATH --output NEW_FILE

calibagent-p8-sign-approval preview
  --request PATH --trust-registry PATH --person-id ID --role ROLE

calibagent-p8-sign-approval sign
  --request PATH --trust-registry PATH --person-id ID --role ROLE
  --ed25519-private-key-fd N --output NEW_FILE
```

`prepare-request` 只接受对应 strict subject artifact；robot/run/dataset/subject kind/ID/hash、
required roles 和最大 TTL全部从第 6.5.2 表机械推导，CLI不能覆盖。subject缺这些 context字段
或与 registry/config不符即失败。SAFETY_REVIEW/DATA_LOCK 因 blind/post-lock context分别只能由
§19.2 `prepare-review-request/prepare-lock-request` 生成，generic form必须拒绝这两个 purpose。
`preview` 不接受 key fd/output、只在 stdout给 canonical payload hash且不写文件；`sign`
必须同时给 fd和 NEW output。private key只从 inherited fd读取、永不进 argv/env/log/repo。
OperatorGateReceipt、BlindSafetyReviewReceipt、reset/data-lock record按上表保存要求的
approval path/semantic hash；run CLI用 `--approval-inbox ABS_PATH`，为每个
scope/changeover/context-return 写 request后只消费 request hash精确匹配的文件。
不存在 `approval_purpose=ATTEMPT`，每-attempt gate 绝不重新发起或要求人工双签：
`p8.gate.attempt.v1` receipt 的 operator/safety-operator approval path/hash 必须与它引用的
parent `p8.gate.scope.v1` receipt 逐位相同，并解析为同一
`purpose=SCOPE,subject_sha256=scope_request_sha256` 的两份 approval。attempt receipt 是
backend 基于 fresh prepared/preflight/watchdog/start-pose evidence 自动产生的 hash-chain record，
不是第三个人工批准对象。watchdog 同时验证 parent scope 未过期、quota 未用尽
且两份 SCOPE approval 在 attempt receipt consume UTC 时仍有效；
`--arm` 没有 inbox或
approval无效时保持 zero并退出 3。schema分别为
`human_trust_registry.schema.json`、`human_approval_request.schema.json` 与
`human_approval.schema.json`；Python/C++共享验签 golden
vectors，覆盖篡改、过期、revoked、wrong role、same person/key、nonce replay和cross-run replay。

### 6.6 safety YAML 必须验证

本节全部字段和条件由 `schemas/p8/safety_config.schema.json` 的 strict
`additionalProperties=false` 合同实现；不能只靠 dataclass 默认值。

`p8_real_safety.yaml` 顶层 key 精确为：

```text
schema_version,robot_id,firmware_version,control_mode,gait_id,
command_envelope,state_limits,freshness,time_sync,lease,
workspace,r1_transform,zero_confirmation,collision,storage,
watchdog_state_store,operator_gate_store,quota_store,protocol_store,
commissioning_evidence
```

```yaml
command_envelope: {lower_vx_vy_wz, upper_vx_vy_wz, maximum_linear_norm,
                   coupled_load_weights, maximum_coupled_load,
                   maximum_slew_vx_vy_wz_per_s,
                   trial_equivalent_motion_s, nav_predictive_horizon_s}
state_limits: {minimum_base_height_m, maximum_base_height_m,
               maximum_abs_roll_rad, maximum_abs_pitch_rad,
               minimum_battery_ratio, maximum_motor_temperature_c,
               allowed_control_modes, allowed_gait_ids}
freshness: {reference_max_age_ms, state_max_age_ms, imu_max_age_ms,
            bms_max_age_ms, fault_max_age_ms, network_max_age_ms,
            relay_echo_max_age_ms, ack_max_age_ms,
            runner_heartbeat_max_age_ms, recorder_status_max_age_ms}
time_sync: {target_offset_ms, maximum_offset_ms,
            maximum_cross_stream_skew_ms, clock_id, require_same_host_watchdog}
lease: {command_lease_ms, arm_lease_ms, authorization_ttl_ms, heartbeat_rate_hz,
        sequence_scope, start_disarmed, resume_disarmed}
workspace: {world_frame,allowed_polygon_xy,forbidden_polygons_xy,
            footprint_margin_m}
r1_transform: {maximum_condition_number,forbid_bias,forbid_clamp,
               require_full_trajectory_offline_check,
               require_runtime_wire_horizon_check}
zero_confirmation: {stationary_window_s,maximum_linear_speed_mps,
                    maximum_yaw_rate_rps,require_controller_ack_if_available,
                    require_relay_echo,require_bridge_heartbeat}
collision: {footprint_radius_m,online_margin_m,contact_required,
            contact_force_threshold_n,terminal_priority}
storage: {minimum_free_bytes,require_recorder_ready,write_once}
watchdog_state_store: {root_path,schema_version,require_hash_chain,
                       require_file_fsync,require_directory_fsync}
operator_gate_store: {root_path,schema_version,require_hash_chain,
                      require_file_fsync,require_directory_fsync}
quota_store: {root_path,schema_version,require_hash_chain,
              require_file_fsync,require_directory_fsync}
protocol_store: {root_path,event_journal_relative_path,checkpoint_relative_path,
                 scientific_result_relative_path,consistent_read_lock_relative_path,
                 require_watchdog_read_only,require_no_symlinks}
commissioning_evidence: {report_path,report_sha256,approved_by,approved_utc}
```

兼容字段 `start_disarmed/resume_disarmed` 在 v1 schema 中都必须为 true，但其精确
语义只是“ordinary nonzero command lane 初始 inhibited”；它们绝不授权 backend 把
持久 `SAFETY_ABORT_LATCHED/TECH_ABORT_DISARMED` 覆盖成 DISARMED。

所有限值在 DEV 可为 `REQUIRED_BEFORE_ARM`；CONFIRM 必须是带单位的有限值。
`terminal_priority` 必须精确为第 15.4 节的枚举顺序。
四个 root_path 必须使用第 6.1 节精确 sentinel：前三个是 robot-global durable
`ROBOT_GLOBAL_STATE_ROOT` 子目录，`protocol_store` 是当前 run 的
`RUNTIME_OUTPUT_ROOT/protocol_state`；
其余路径必须是无 `..` 的相对路径。Python journal writer 用 advisory exclusive lock完成
一行 append+fsync；C++ watchdog 用同一 lock做 consistent read cut，以
`openat/O_NOFOLLOW` 只读 journal/checkpoint/scientific artifacts，禁止跟随 symlink或逃出
root。CONFIRM 要求 `require_watchdog_read_only=true,require_no_symlinks=true`。

### 6.6.1 跨文件 invariant 与唯一 resolved config

loader 不采用“后读文件覆盖先读文件”。安全 YAML 是 physical safety 限值的唯一
权威，map 是几何的唯一权威，topic map 是 topic/QoS/capability 的唯一权威，NAV/
SHIFT config 只拥有算法与实验设计。为方便审阅而重复出现的字段必须满足：

```text
experiment.command_space == safety.command_envelope 的对应 bounds/norm/load
trial_profile.equivalent_motion_s == safety.command_envelope.trial_equivalent_motion_s == 3.4
navigation.predictive_wire_horizon_s == safety.command_envelope.nav_predictive_horizon_s
navigation.terminal_priority == safety.collision.terminal_priority
quality.*_max_age_ms == safety.freshness 的对应值
recording.minimum_free_bytes == safety.storage.minimum_free_bytes
navigation.reference_min_rate_hz == quality.minimum_reference_rate_hz
                               == topic independent_reference_pose.minimum_rate_hz == 40
navigation.timeout_s == 每个 map.timeout_s == 60
map.world_frame == safety.workspace.world_frame == reference frame contract world_frame
reference_extrinsic.parent_frame == topic independent_reference_pose.frame
reference_extrinsic.child_frame == frozen base frame
每个 map.robot_footprint.type == "circle"
每个 map.robot_footprint.radius_m == safety.collision.footprint_radius_m
每个 map.collision_rule.online_footprint_margin_m == safety.collision.online_margin_m
每个 map.collision_rule.contact_topic_required == safety.collision.contact_required
每个 map.collision_rule.contact_force_threshold_n == safety.collision.contact_force_threshold_n
每个 map.waypoint_radius_m == navigation.waypoint_radius_m
每个 map.goal_radius_m == navigation.goal_radius_m
config dataset_role/run_id == release manifest 与每份 block schedule 对应字段
config source_commit == release manifest/source_commit.txt/remote_commit
schedule manifest 的两份 template hash == release materialization provenance
map/safety contact_required=true => topic foot_contact availability=required，且
  message_type/field_map/units/minimum_rate_hz/maximum_age_ms 均有效
topic foot_contact availability=not_available => map/safety contact_required=false；
  在线碰撞只用冻结几何/其余可用 safety 通道，contact force不得伪造，视频仍只做盲审
```

任一不相等立即退出 2，禁止取 min/max 或静默选择一个。loader 验证全部外部 raw-byte
hash 后输出 canonical `resolved_config.json`；其 `resolved_config_sha256` 写 preflight、
authorization、journal 和 manifest。runner/watchdog adapter 只消费 typed resolved
config，不再分别重读若干 YAML 形成不同解释。`resolved_config.json` 是派生物，不替代
原文件及其各自 hash。

### 6.7 CSV 行数和 ID 合同

| 文件 | 列/行数 |
|---|---|
| NAV/SHIFT candidate/reference pool | `command_id,cmd_vx,cmd_vy,cmd_wz`；行数由 config 冻结 |
| NAV dense/LHS/Sobol/random | 同上；30/12/12/12 行 |
| NAV `active_seed.csv` | 同上；恰 6 个 signed-axis IDs |
| NAV/SHIFT validation | 同上；恰 8 行 |
| SHIFT pre-calibration seed | 同上；恰 6 个 signed-axis IDs |
| SHIFT pre/post monitor | 同上；4/5 行，pre IDs 为 `SHIFT_PRE_MON_01..04` |
| SHIFT passive recovery | 同上；恰 12 行，`SHIFT_RECOVERY_01..12` |
| task tables | `task_id,cmd_vx,cmd_vy,cmd_wz,weight`；weight 归一化 |
| restore sentinel | 第 16.7 节固定 4 列、2 行 |

所有 ID 为 ASCII，区分大小写，文件内唯一；速度单位固定 m/s,
m/s,rad/s。CSV 无注释行、无空行、无额外列。release generator 可在
DEV 生成 LHS/Sobol/random，但 CONFIRM runner 只读 bytes+hash，不 import RNG。

---

## 7. ROS 2 workspace 和消息

### 7.1 packages

`ros2/calibagent_p8_msgs` 使用 `ament_cmake` 生成消息；
`ros2/calibagent_go2` 使用 `ament_python` 实现 gateway/adapter/runner glue；
`ros2/calibagent_go2_watchdog` 使用 `ament_cmake` + C++ 实现 command relay 和
watchdog。watchdog 不得与模型 runner 在同一进程。

最低文件树：

```text
ros2/calibagent_p8_msgs/
├── CMakeLists.txt
├── package.xml
├── msg/
│   ├── CommandPacket.msg
│   ├── CommandTelemetry.msg
│   ├── ChangeoverMarker.msg
│   ├── ExperimentMarker.msg
│   ├── NavigationMarker.msg
│   ├── ReferenceState.msg
│   ├── RobotHealth.msg
│   ├── RecorderStatus.msg
│   ├── RunnerHeartbeat.msg
│   ├── SafetyEvent.msg
│   ├── WatchdogStatus.msg
│   └── ZeroReceipt.msg
└── srv/
    ├── RunPreflight.srv
    ├── RegisterOperatorGateReceipt.srv
    ├── GetOperatorGateReceiptTail.srv
    ├── RegisterScopeAuthorization.srv
    ├── ArmMotion.srv
    ├── DisarmMotion.srv
    ├── BeginExecution.srv
    ├── CompleteExecution.srv
    ├── LatchSafetyAbort.srv
    ├── ReportTechnicalAbort.srv
    ├── AcknowledgeTechnicalAbort.srv
    ├── SetCommandTransform.srv
    ├── ResetAbortLatch.srv
    └── GetReadiness.srv

ros2/calibagent_go2/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/calibagent_go2
├── calibagent_go2/
│   ├── __init__.py
│   ├── topic_contract.py
│   ├── qos.py
│   ├── command_driver.py
│   ├── state_gateway.py
│   ├── reference_gateway.py
│   ├── unitree_state_adapter.py
│   ├── recorder_control.py
│   ├── operator_shift_tool.py
│   └── runner_node.py
├── launch/p8_bringup.launch.py
└── test/

ros2/calibagent_go2_watchdog/
├── CMakeLists.txt
├── package.xml
├── include/calibagent_go2_watchdog/watchdog_node.hpp
├── include/calibagent_go2_watchdog/vendor_command_adapter.hpp
├── src/watchdog_node.cpp
├── src/vendor_command_relay.cpp
├── src/generic_twist_vendor_adapter.cpp
├── src/unitree_vendor_adapter.cpp       # S11 获得冻结 bridge contract 后实现
└── test/
```

command adapter 必须在 C++ relay/watchdog 进程内；Python 节点不得成为 vendor
motion publisher。`unitree_vendor_adapter.cpp` 在 bridge contract 未提供时必须
构建时禁用且 runtime fail closed，不能回退到 generic adapter。generic Twist
adapter 只用于 fake graph、已明确采用 `geometry_msgs/Twist` 的现场 bridge 或
HIL。若现场 bridge 使用 custom message，S11 在同一 C++ port 上实现并 pin。

Python `command_driver.py` 只发布内部 `CommandPacket`，并按 sequence 等待 C++
relay 发回 `CommandTelemetry`，在冻结的短 timeout 内构造 `CommandReceipt`；它
不发布 vendor topic。同步等待只要求 relay acceptance/publish echo；vendor ACK
若异步可用，由相同 sequence 后续补充记录，不阻塞每个 control tick。relay echo
超时立即视为 driver fault，由 watchdog 独立 zero。等待磁盘或 model 不得进入
此路径。

### 7.2 最低自定义消息

`CommandPacket.msg`：

```text
builtin_interfaces/Time source_stamp
uint64 monotonic_ns
string boot_id
uint64 sequence
string dataset_role
string attempt_role
string run_id
string session_id
string block_id
string shift_id
string map_id
string method_id
string scientific_unit_id
string unit_type
string attempt_uid
uint32 attempt_index
string retry_of_attempt_uid
string phase
float64 logical_vx
float64 logical_vy
float64 logical_wz
float64 motion_horizon_s
string lease_id
uint64 lease_deadline_ns
```

`sequence` 在每个 `boot_id` 内全局严格递增，不在 trial 边界归零。
Python 和 C++ relay 必须在同一 Linux host/boot 上使用
`CLOCK_MONOTONIC`；禁止将另一台主机的 monotonic number 直接比较。
PRIMARY 的 `retry_of_attempt_uid` 在线上编码为空字符串，export/dataclass 边界转换为
`None`；其余 identity 字段禁止空字符串。

`CommandTelemetry.msg`：

```text
builtin_interfaces/Time source_stamp
uint64 requested_monotonic_ns
uint64 relay_receive_monotonic_ns
uint64 published_monotonic_ns
uint64 ack_monotonic_ns             # ack_available=false 时必须为 0
string boot_id
uint64 sequence
float64 logical_vx
float64 logical_vy
float64 logical_wz
float64 post_transform_vx
float64 post_transform_vy
float64 post_transform_wz
float64 transmitted_vx
float64 transmitted_vy
float64 transmitted_wz
float64 ack_vx
float64 ack_vy
float64 ack_wz
bool ack_available
string transform_id
string transform_sha256
bool accepted
string[] reason_codes
```

四个 monotonic 字段与 `CommandReceipt` 的映射是机械的：
`requested_monotonic_ns` 必须逐位回显 `CommandPacket.monotonic_ns`；
`relay_receive_monotonic_ns` 是 C++ relay callback 在解析/验证 packet 前取得的
`CLOCK_MONOTONIC` 时刻；
`published_monotonic_ns` 是 relay 实际调用唯一 vendor publisher 的时刻；
`ack_monotonic_ns` 只在 `ack_available=true` 时非零。三个时刻必须来自与
`boot_id` 相同主机/boot 的 `CLOCK_MONOTONIC`，并满足
`requested <= relay_receive <= published <= ack`（没有 ACK 时只检查到 publish）。
Python 接收 telemetry 的本地时刻另写 raw diagnostics，不能冒充 publish/ACK 时刻。
driver 只能按这些 wire 字段构造 `CommandReceipt`，不得用 callback 到达时间补值。

`ReferenceState.msg`：

```text
builtin_interfaces/Time source_stamp
uint64 source_timestamp_ns
uint64 receive_timestamp_ns
uint64 receive_monotonic_ns
string boot_id
string frame_id
string child_frame_id
float64 x
float64 y
float64 yaw
float64[9] covariance_se2
string tracking_state
bool valid
string[] reason_codes
```

`RobotHealth.msg`（每个逻辑 stream 保留独立 age，BMS 不得被高频 IMU
“刷新”）：

```text
builtin_interfaces/Time source_stamp
uint64 source_timestamp_ns
uint64 receive_timestamp_ns
uint64 receive_monotonic_ns
string boot_id
float64 state_age_ms
float64 imu_age_ms
float64 bms_age_ms
float64 fault_age_ms
float64 network_age_ms
float64 roll
float64 pitch
float64 yaw_rate
float64 base_height_m
float64 body_velocity_vx
float64 body_velocity_vy
float64 body_velocity_wz
float64 onboard_pose_x
float64 onboard_pose_y
float64 onboard_pose_yaw
bool onboard_pose_available
float64 battery_ratio
float64 battery_voltage_v
float64 maximum_motor_temperature_c
string control_mode
string gait_id
bool state_finite
bool imu_valid
bool bms_valid
bool network_ok
bool physical_estop_ready
bool collision_detected
string[] motor_faults
string[] bms_faults
string[] reason_codes
```

`state_gateway.py` 用 `RobotHealth` 的 source/receive/body-velocity 字段构造
`OnboardSample`，再在同一 cut 合并 `RecorderStatus.ready/storage_ready` 形成
`RobotHealthSample.recorder_ready/storage_ready`。禁止把 recorder age 或 BMS age
伪装成 onboard state 的 source time；字段名映射固定为
`receive_timestamp_ns→*.receive_timestamp_ns`、
`receive_monotonic_ns→*.monotonic_ns`。

`RecorderStatus.msg`：

```text
builtin_interfaces/Time source_stamp
uint64 receive_monotonic_ns
string boot_id
string run_id
string bag_segment_id
bool ready
bool bag_active
bool output_write_once
bool storage_ready
uint64 free_bytes
string[] reason_codes
```

`RunnerHeartbeat.msg`：

```text
builtin_interfaces/Time source_stamp
uint64 monotonic_ns
string boot_id
uint64 heartbeat_sequence
string run_id
string attempt_uid
string lease_id
bool command_sequence_available
uint64 command_sequence
bool lease_deadline_available
uint64 lease_deadline_ns
```

process heartbeat 从 runner 启动即发送；DISARMED/preflight 时两个 available flag
均为 false，三个 identity/lease string 可以为空。执行期 available flag 必须为 true，
并与当前 accepted command/lease 一致。`heartbeat_sequence` 独立严格递增，不等同于
command sequence。

`ExperimentMarker.msg`：

```text
builtin_interfaces/Time source_stamp
uint64 monotonic_ns
uint64 event_sequence
string dataset_role
string attempt_role
string run_id
string session_id
string block_id
string shift_id
string map_id
string method_id
string scientific_unit_id
string unit_type
string attempt_uid
uint32 attempt_index
string retry_of_attempt_uid
string phase
string posterior_id
uint64 posterior_version
```

`NavigationMarker.msg`（`topic_map.navigation_marker` 的唯一 wire type，不能拿缺字段的
`ExperimentMarker` 代替）：

```text
builtin_interfaces/Time source_stamp
uint64 source_timestamp_ns
uint64 monotonic_ns
uint64 event_sequence
string event_type
string dataset_role
string attempt_role
string run_id
string session_id
string block_id
string shift_id
string map_id
string method_id
string scientific_unit_id
string unit_type
string attempt_uid
uint32 attempt_index
string retry_of_attempt_uid
bool waypoint_available
uint32 waypoint_index
float64 target_x_m
float64 target_y_m
string terminal_reason
float64 navigation_elapsed_s
string posterior_id
uint64 posterior_version
string posterior_sha256
```

`event_type` 只允许 `EPISODE_START|STABILIZE_START|STABILIZE_COMPLETE|
NAVIGATE_START|WAYPOINT_REACHED|GOAL_REACHED|TIMEOUT|COLLISION|SAFETY_ABORT|
TECH_ABORT|ZERO_CONFIRMED`。WAYPOINT_REACHED 必须
`waypoint_available=true` 且 index/target 与冻结 route 一致；其他事件 false、index=0、
target=NaN **禁止**，因此写 0.0 并由 flag 判 null semantics。terminal reason 仅终止事件
非空。`event_sequence` 在 attempt 内从 1 连续递增，所有 timestamp 来自同一 boot 的
source/host mapping；recorder marker、journal event 与 export trace 用
`attempt_uid+event_sequence` 一一 join。golden test 必须覆盖 episode start、stabilize、
两个 waypoint、success/timeout/collision 和 zero-confirm，且从 raw markers 重算
episode_metrics 完全一致。
backend/session 必须从 wire fields 构造 `NavigationMarkerRecord` 并只调用
`AttemptRecorder.mark_navigation`；generic `mark(ExperimentEvent)` 不接受 navigation
marker。recorder 在返回前写入当前 attempt range/marker index；event sequence或 identity
不连续即先 zero并报 `MARKER_UNRECOVERABLE`。

`ChangeoverMarker.msg`（recorder/evaluator-only；不是 `ExperimentMarker`）：

```text
builtin_interfaces/Time source_stamp
uint64 monotonic_ns
uint64 event_sequence
string dataset_role
string run_id
string session_id
string block_id
string method_id
string shift_id
string changeover_unit_id
string changeover_kind            # APPLY | RESTORE | RECOVER_NOMINAL
uint32 changeover_attempt_index
string changeover_uid
string retry_of_changeover_uid
string parent_changeover_uid
string action                    # apply | restore
string phase                     # precheck | actuate | postcheck
string changeover_attempt_identity_sha256
string changeover_phase_identity_sha256
string evidence_bundle_sha256
string actuation_receipt_sha256
string shift_receipt_sha256
string result_event_id
string result_event_sha256
```

该消息不得含 `attempt_uid/scientific_unit_id/unit_type`，不得发布到 detector 的可见
namespace，也不得为了复用 `ExperimentMarker` 而伪造 motion identity。其
`changeover_unit_id/kind/attempt_index/uid/retry/parent/action/phase` 与第 16.6 节
`ChangeoverIdentity` 逐字段相等；nullable retry/parent 在线上用空字符串，导出时转 null。
`result_event_id/result_event_sha256` 必须逐位等于已 fsync 的
`CHANGEOVER_RESULT_COMMIT` JournalCommitRef；recorder和rosbag replay以该 pair去重/回链，
不能只靠 changeover UID猜测 result bytes。

`SafetyEvent.msg`：

```text
builtin_interfaces/Time source_stamp
string event_id
string boot_id
string hil_case_nonce_hex
string event_source               # watchdog | command_relay | runner_safety_monitor | backend | operator_estop
string identity_kind              # attempt | run_level
string dataset_role
string attempt_role
string run_id
string session_id
string block_id
string shift_id
string map_id
string method_id
string scientific_unit_id
string unit_type
string attempt_uid
uint32 attempt_index
string retry_of_attempt_uid
string event_type
string[] reason_codes
uint64 decision_monotonic_ns
uint64 zero_publish_monotonic_ns
uint64 bridge_ack_monotonic_ns
uint64 measured_stop_monotonic_ns
bool decision_available
bool zero_publish_available
bool bridge_ack_available
bool measured_stop_available
bool manual_estop
bool collision
bool serious_safety_event
```

`identity_kind=attempt` 时上述 attempt identity 字段全部 required 且 index≥1；
`identity_kind=run_level` 只允许 PREPARED boundary 前的 E-stop/person-contact/全局 safety
事件，此时仍要求 dataset/run/event/reason/times，session/block/shift/map/method/scientific
unit/unit type/attempt role/attempt UID/retry 字符串在线上全为空、`attempt_index=0`，exporter
转成 nullable columns。run-level event 同时必须先 append journal，消息携带同 event ID；
recorder 以 event ID 去重并持久 ACK，不能靠空 attempt identity 丢弃它。

`hil_case_nonce_hex` 在非 HIL 运行必须为空字符串；Gate C 启动的每个 HIL
invocation 必须在触发任何 fault/命令前将本 case 的 32 位 lowercase-hex nonce
通过测试参数显式传入 event producer；该 case 产生的每个 `SafetyEvent`
必须逐字符携带同一非空 nonce。recorder/collector 只能复制该 wire 字段，
不得根据时间窗、event 顺序、reason code 或当前活动 case 反推。

`event_source` 只允许注释中的五个值；`boot_id` 是本次 command-path supervisor boot UUID，
五种 source 都必须从同一个 frozen readiness cut取得而不是各造进程 UUID。`event_type` 只允许
`SAFETY_STOP|TECHNICAL_STOP|COLLISION|ESTOP|PERSON_CONTACT|ZERO_PUBLISH_FAILURE|
PHYSICAL_STOP_TIMEOUT|INFORMATIONAL`。软件 timing-required 集合精确为前三个 source与
`{SAFETY_STOP,TECHNICAL_STOP,COLLISION,ESTOP,PERSON_CONTACT,ZERO_PUBLISH_FAILURE,
PHYSICAL_STOP_TIMEOUT}` 的笛卡尔交；`INFORMATIONAL` 永不进入。reason code（reference stale、
lease timeout、battery等）细分原因，但不能改变该集合。decision/zero/ACK/physical stop四个
monotonic timestamp必须与 `boot_id` 同 boot且按 available flags单调；跨 boot join立即
integrity failure。Python/C++/CSV analyzer共享这两个 frozen enum/set常量与 golden vectors。

`WatchdogStatus.msg`：

```text
builtin_interfaces/Time source_stamp
uint64 monotonic_ns
string boot_id
uint64 state_sequence
string state_sha256
string quota_state_sha256
string operator_gate_receipt_tail_sha256
string active_scope_authorization_sha256
string last_consumed_reset_authorization_sha256
string last_reset_target_state_sha256
string state
bool armed
bool executing
string lease_id
uint64 lease_deadline_ns
uint64 command_sequence
float64 reference_age_ms
float64 state_age_ms
float64 imu_age_ms
float64 bms_age_ms
float64 fault_age_ms
float64 network_age_ms
float64 heartbeat_age_ms
float64 recorder_age_ms
float64 ack_age_ms
bool ack_available
bool single_vendor_writer
bool physical_estop_ready
bool recorder_ready
bool storage_ready
bool zero_confirmed
bool robot_stationary
string transform_id
string transform_sha256
string latch_reason
string[] reason_codes
```

线上 nullable string 仍用空字符串表示；active scope与两个 last-reset hash可为空，
另外两个 head 在 genesis 也必须是定义好的 64-hex hash，不能空。watchdog 在同一个
persistent-state shared lock/cut 下生成 state/quota/receipt/active-scope 四个 head；Python
不得分别查询后拼接。`WatchdogReadiness` 将空 active scope 转成 `None`，其余逐字保留。
`RUN_ATTACHED_TO_ROBOT_STATE`、preflight request/report 和跨语言 golden vectors必须绑定
同一 atomic status cut 的全部 head，任一在 attach/arm 前变化都令 CAS/preflight 失效。

`ZeroReceipt.msg`：

```text
builtin_interfaces/Time source_stamp
string boot_id
string hil_case_nonce_hex
string action
string reason
uint64 decision_monotonic_ns
uint64 zero_publish_monotonic_ns
bool bridge_ack_available
uint64 bridge_ack_monotonic_ns
bool measured_stop_available
uint64 measured_stop_monotonic_ns
bool zero_confirmed
bool robot_stationary
string watchdog_state
string[] reason_codes
```

`ZeroReceipt.hil_case_nonce_hex` 与 `SafetyEvent` 使用同一规则：非 HIL 为空；
Gate C 内必须等于本 invocation 的 case nonce。watchdog 必须在执行零速/
readback 时从已验证的 HIL request 复制它，collector 不得补写。

`SafetyEvent/WatchdogStatus/ZeroReceipt` 的字段与
`schemas/p8/topic_map.schema.json` 必须有 golden
serialization test。

ACK 不可用时 `ack_available=false`，ROS 数值字段写 0，exported nullable ACK 字段
写空；任何 consumer 必须先检查 flag，禁止把 0 当真实 ACK。

`SetCommandTransform.srv`：

```text
string changeover_uid
string canonical_actuation_identity_json
string changeover_attempt_identity_sha256
string actuation_phase_identity_sha256
string changeover_kind
string action
string pre_evidence_bundle_sha256
string operator_gate_receipt_sha256
string context_from
string context_to
string transform_id
float64[9] row_major_matrix
string config_sha256
string schedule_sha256
bool enable
---
bool accepted
string reason
uint64 effective_monotonic_ns
string readback_sha256
string activation_record_sha256
```

该 service 是 R1 transform 的唯一写入口，不是普通参数 setter。
`canonical_actuation_identity_json` 必须是完整 `ChangeoverIdentity` canonical JSON，含
dataset/run/session/block/method/shift/unit/kind/index/UID/retry/parent/action/phase；relay 用
strict schema解析、要求 `phase=actuate`，重算 attempt/phase hashes，并用 schedule/registry
验证 planned/recovery/retry lineage。opaque hash 或 caller UID 不能替代这一步。C++ relay 必须先从
robot-scoped receipt store 载入已注册 `p8.gate.changeover.v1` receipt，逐字段核对
changeover UID/identity hash、pre-evidence、context from/to、双人 ID，并要求当前
`DISARMED + zero_confirmed + motion_inhibited`。`APPLY/action=apply` 只能
`enable=true,nominal→R1`；`RESTORE|RECOVER_NOMINAL/action=restore` 只能
`enable=false,R1→nominal`（linked nominal no-op 按 §16.6 明示）。matrix raw bytes/hash、
config/schedule 与 frozen release 必须相等。

relay 将 new matrix/enable、changeover UID、receipt/evidence hash、effective monotonic time
和 readback 写入同一个第 10.1.1 节 durable supervisor transition，成功 fsync 后才切换
command lane并返回；activation record 是该 transition 的 detached hash。完全相同 request
幂等返回原 effective/readback/record，不同 request 复用 changeover UID 或绕过 receipt
一律拒绝并保持原 transform。R1 `ActuationReceipt` 必须引用 response 的
effective/readback/activation record；Python 自己改 matrix 不能构成 evidence。

R1 的三个 hash namespace 不得混用。跨 Python/C++ preimage 精确冻结为：

```text
f64be(x) = IEEE-754 binary64 big-endian 8 bytes 的 16 位小写 hex

MatrixObject = {
  "schema_version":"p8.r1-matrix.v1",
  "transform_id": <string>,
  "row_major_f64be_hex": [f64be(a00),...,f64be(a22)]
}
matrix_sha256 = sha256(canonical_json(MatrixObject))

TransformReadback = {
  "schema_version":"p8.r1-readback.v1",
  "transform_id": <string>, "enabled": <bool>,
  "matrix_sha256": <MatrixObject hash>
}
readback_sha256 = sha256(canonical_json(TransformReadback))

ActiveTransformState = {
  "schema_version":"p8.r1-active-state.v1",
  "transform_id": <string>, "enabled": <bool>,
  "matrix_sha256": <hash>, "readback_sha256": <hash>,
  "config_sha256": <hash>, "schedule_sha256": <hash>,
  "changeover_attempt_identity_sha256": <hash-or-64-zero-genesis>,
  "changeover_uid": <string-or-NOT_APPLICABLE>,
  "operator_gate_receipt_sha256": <hash-or-64-zero-genesis>,
  "pre_evidence_bundle_sha256": <hash-or-64-zero-genesis>,
  "effective_monotonic_ns": <integer>,
  "previous_active_transform_state_sha256": <hash>
}
transform_sha256 = sha256(canonical_json(ActiveTransformState))
```

`nominal_transform_id` 字面值强制为 `IDENTITY`；nominal identity matrix也用 MatrixObject，
九个值精确为 `[1,0,0,0,1,0,0,0,1]` 的 binary64，其 hash 必须等于
`nominal_matrix_sha256`；
`expected_identity_readback_sha256` 只等于对应 `enabled=false` TransformReadback hash，避免把
config 自身 hash 纳入 preimage形成循环。`WatchdogStatus.transform_sha256` 是当前 durable
ActiveTransformState hash；service response 的 `readback_sha256` 是 readback object hash；
`activation_record_sha256` 是包含 supervisor sequence/boot/state refs及该 active-state hash 的
durable transition hash。config matrix、nominal identity、R1 apply/restore readback和 active
state各提供 tracked canonical bytes/full-SHA golden vector；relay逐个 binary64 bit pattern
核对，禁止十进制格式化后再 hash。
首个 commissioning identity ActiveTransformState 的
`previous_active_transform_state_sha256` 精确为 64 个 `0`；以后必须指前一 durable full hash，
空字符串/null/跳链均拒绝。

`RunPreflight.srv`：

```text
string watchdog_request_sha256
string prepared_attempt_sha256
string dataset_role
string attempt_role
string run_id
string session_id
string block_id
string shift_id
string map_id
string method_id
string scientific_unit_id
string unit_type
string attempt_uid
uint32 attempt_index
string retry_of_attempt_uid
string source_commit
string release_manifest_sha256
string resolved_config_sha256
string schedule_sha256
string required_transform_id
string required_transform_sha256
uint64 requested_monotonic_ns
---
bool accepted
calibagent_p8_msgs/WatchdogStatus status
uint64 checked_monotonic_ns
string fault_class
string primary_reason_code
string watchdog_receipt_sha256
string[] reason_codes
```

wire 字段（从 `prepared_attempt_sha256` 到
`requested_monotonic_ns`，不含 response）必须与第 5.3 节
`WatchdogPreflightRequest` 一一对应。该 service 自己执行
`DISARMED→PREFLIGHT→READY`；`watchdog_request_sha256` 不等于 C++ 对这些 wire 字段
canonical 重算值、
identity 不在 schedule、transform readback 不同或 health gate 失败时必须先按冻结
priority选唯一 `primary_reason_code` 并返回
`fault_class=none|config|technical|safety`：safety 立即 zero→
`SAFETY_ABORT_LATCHED`，technical→`TECH_ABORT_DISARMED`，config/hash→`DISARMED`；不得把
LOW_BATTERY/MOTOR/E-stop 等 safety 降级为普通 DISARMED。成功时 C++ 按冻结 receipt schema 计算并返回 detached
`watchdog_receipt_sha256`。Python backend 在此结果上再合并
RobotContext/driver/recorder/snapshot/hash，产生第 5 节完整 `PreflightReport`；C++
没有收到完整 `PreflightRequest`，因此既不重算也不声称验证
`PreflightRequest.request_sha256`。两边任一失败都不能 arm。

成功 response 的 wire 表示唯一固定为
`accepted=true,fault_class="none",primary_reason_code="NONE",reason_codes=[]`；不使用空串或
null。任一 rejection 必须 `accepted=false,fault_class∈{config,technical,safety}`，
`reason_codes` 是按冻结 priority 去重排序的非空数组，`primary_reason_code` 逐字等于其
第一项。Python projection 和跨语言 golden vectors 同时检查这些 conditional rules。

wire→Python projection 唯一为：`checked_monotonic_ns` 逐位复制 response；
`WatchdogReadiness.boot_id=status.boot_id`、
`WatchdogReadiness.status_monotonic_ns=status.monotonic_ns`，并要求后者逐位等于
`checked_monotonic_ns`；`state_sequence/state_sha256` 逐位复制同一 status snapshot；
`ready_to_arm = accepted and status.state=="READY"`；zero/stationary/transform/reason codes
逐字段复制。`topic_ages_ms` 的 key 固定为
`reference,state,imu,bms,fault,network,heartbeat,recorder`，再且只在
`ack_available=true` 时加 `ack`；value 逐项取 WatchdogStatus 对应 `*_age_ms`。C++ receipt
preimage 是 canonical JSON
`{watchdog_request_sha256,checked_monotonic_ns,accepted,fault_class,
primary_reason_code,status=<上述 WatchdogReadiness canonical object>}`，
`watchdog_receipt_sha256=sha256(preimage)`，hash 不进入自身。Python 重建完全相同对象并
重算 hash；同一次 preflight/receipt/report/arm 的 boot ID 必须一致、reason priority与 handoff
§14.3一致。提供 accepted、四类 rejection、ACK available/unavailable 的跨语言 golden
bytes/hash vectors。

`RegisterOperatorGateReceipt.srv`：

```text
string canonical_receipt_json
string receipt_sha256
---
bool accepted
string persisted_receipt_sha256
string[] reason_codes
```

request 的 JSON bytes 必须是第 5.3 节 `OperatorGateReceipt` 的 canonical UTF-8，不能
发送 YAML、路径或只发送 payload。watchdog 用严格
`operator_gate_receipt.schema.json` 解析，拒绝 unknown key，重算 typed payload hash 与
排除自身的 receipt hash，检查 `previous_receipt_sha256` 连续链、两个人员 ID 不同、
monotonic/UTC 合法，并将完整 bytes 写入 robot-scoped content-addressed receipt store。
response 只有在 file fsync、rename、directory fsync 及 supervisor receipt-tail 更新均
成功后才 accepted；相同 bytes/hash 重放幂等。后续两个 authorization service 只引用
这个 persisted hash，且依 purpose 再核对 typed payload，而不信任 Python 文件路径。

`GetOperatorGateReceiptTail.srv`：

```text
---
uint64 receipt_sequence
string receipt_sha256
```

runner 启动及每次创建新 receipt 前都执行 reconcile：验证 Python local chain 和 C++
chain 各自完整；C++ chain 必须是 local chain 的精确前缀。local 多出的 sequence 按顺序
读取 canonical bytes并幂等调用 register，直到两条 tail 相等，才允许签下一条。
C++领先、previous link分叉、同 sequence不同 bytes/hash 或任一链损坏都进入
`PERSISTENCE_CORRUPT`。crash 在 local fsync/register request/C++ fsync/response 任一点的
测试必须证明可按上述前缀规则恢复；不能因为 response丢失跳 sequence或永久死锁。

`RegisterScopeAuthorization.srv`：

```text
string scope_authorization_id
string authorization_purpose
bool cli_arm_requested
string run_id
string session_id
string shift_id
string scope_id
string parent_scope_authorization_sha256
string lineage_root_scope_authorization_sha256
string retry_request_uuid
string activation_event_sha256
string eligibility_checkpoint_sha256
string eligibility_journal_tail_sha256
string[] allowed_scientific_unit_ids
string source_commit
string config_sha256
string schedule_sha256
uint64 issued_monotonic_ns
uint64 expires_monotonic_ns
uint64 maximum_attempts
string scope_request_sha256
string operator_id
string safety_operator_id
string operator_gate_receipt_sha256
string scope_authorization_sha256
---
bool accepted
string persisted_scope_authorization_sha256
uint64 remaining_attempts
string[] reason_codes
```

nullable parent/root/retry/activation 在线上用空字符串，进入 dataclass 前转 `None`。watchdog 先从 request
字段重建并 hash `ScopeAuthorizationRequest`，要求等于 `scope_request_sha256`；再验证
receipt 确实引用这个 request hash，最后重建/hash `ScopeAuthorization`。随后按第 11 节
purpose/allowed IDs/parent/retry/quota 规则，以第 10.1.1 节事务顺序持久化或原子转移。
完全相同的重复注册幂等；相同 instance ID 不同内容、非法 supplement/renewal、越 scope、
过期或扩大 quota 一律拒绝。该 service 不进入 `READY/ARMED_IDLE`，也不开放非零 command lane。

`ArmMotion.srv`：

```text
string authorization_id
string scope_authorization_sha256
string dataset_role
string attempt_role
string run_id
string session_id
string block_id
string shift_id
string map_id
string method_id
string scientific_unit_id
string unit_type
string attempt_uid
uint32 attempt_index
string retry_of_attempt_uid
string authorization_sha256
string prepared_attempt_sha256
string preflight_report_sha256
string watchdog_receipt_sha256
string start_pose_gate_result_sha256
string attempt_gate_receipt_sha256
uint64 authorization_issued_monotonic_ns
uint64 authorization_expires_monotonic_ns
---
bool accepted
string state
string lease_id
string returned_authorization_sha256
uint64 lease_issued_monotonic_ns
uint64 lease_expires_monotonic_ns
string[] reason_codes
```

request 不携带 caller 生成的 lease。watchdog 重建第 5 节
`ArmAuthorization/AttemptIdentity`，重算 attempt authorization hash，并按
`scope_authorization_sha256` 载入已签、未过期且尚有 quota 的持久 scope record；再核对
最新 preflight 对应的 wire receipt、prepared hash 和 attempt-gate receipt，成功后才生成
response lease；client 由 response 构造 `ArmLease`。C++ 核对的是自身最近持久化的
wire receipt，不尝试重算 Python-only 的完整 report；完整 report 由其 hash 与 receipt
传递性绑定。一个 `authorization_sha256` 只允许同一个 `attempt_uid`，重复请求只在全部
字段相同且 durable lease 已存在时幂等。
watchdog 还从已注册 attempt receipt 读取 final start-pose cut、expected pose、tolerances
和 stationary limits，要求 cut age≤冻结 `maximum_start_pose_gate_age_ms`，并用 arm 时最新
independent reference再次验证 pose/stationary；不通过则保持 zero、不 arm，以 exact
`START_POSE_DRIFT_AFTER_PRECHECK` technical pre-measure abort封已存在 attempt。若证据表明
人员进入则优先 `UNPLANNED_HUMAN_ENTRY`。Python gate pass不能替代这次 C++ current check。

`DisarmMotion.srv`：

```text
string run_id
string attempt_uid
string reason
---
bool accepted
calibagent_p8_msgs/ZeroReceipt receipt
string[] reason_codes
```

`BeginExecution.srv`：

```text
string run_id
string attempt_uid
string lease_id
---
bool accepted
string state
string[] reason_codes
```

只允许 `ARMED_IDLE→EXECUTING`。`CompleteExecution.srv`：

```text
string run_id
string attempt_uid
string terminal_reason
---
bool accepted
calibagent_p8_msgs/ZeroReceipt receipt
string[] reason_codes
```

该 service 必须先 zero/stationary 再返回。

`LatchSafetyAbort.srv`：

```text
string run_id
string attempt_uid
string reason_code
bool serious
---
bool accepted
calibagent_p8_msgs/ZeroReceipt receipt
string[] reason_codes
```

`ReportTechnicalAbort.srv`：

```text
string run_id
string attempt_uid
string reason_code
---
bool accepted
calibagent_p8_msgs/ZeroReceipt receipt
string[] reason_codes
```

前者只能进 `SAFETY_ABORT_LATCHED`，后者只能进
`TECH_ABORT_DISARMED`。它们不依赖 recorder 完成 zero path。
`AcknowledgeTechnicalAbort.srv` 精确为：

```text
string robot_id
string operator_id
string safety_operator_id
string reason
bool robot_stationary_confirmed
string latch_reason
string watchdog_state_before_reset
string watchdog_boot_id
uint64 watchdog_state_sequence
string watchdog_state_sha256
uint64 issued_monotonic_ns
uint64 expires_monotonic_ns
string reset_request_sha256
string operator_gate_receipt_sha256
string reset_authorization_sha256
---
bool accepted
string state
string message
```

它只允许 `TECH_ABORT_DISARMED→DISARMED`，绝不能解除 safety latch。

`ResetAbortLatch.srv`：

```text
string robot_id
string operator_id
string safety_operator_id
string reason
bool robot_stationary_confirmed
string latch_reason
string watchdog_state_before_reset
string watchdog_boot_id
uint64 watchdog_state_sequence
string watchdog_state_sha256
uint64 issued_monotonic_ns
uint64 expires_monotonic_ns
string reset_request_sha256
string operator_gate_receipt_sha256
string reset_authorization_sha256
---
bool accepted
string state
string message
```

`ResetAbortLatch` 只允许 `SAFETY_ABORT_LATCHED→DISARMED`，必须由 watchdog 独立
验证 reference-measured stationary；request 中的 boolean 只是双人 attestation，
不能代替测量。普通 backend `reset(context)` 和
`AcknowledgeTechnicalAbort` 都不得调用或模拟该 transition。
两个 service 调用前，reset coordinator 必须 load/register
`p8.gate.reset.v1` receipt；watchdog 按 hash 载入已持久 receipt，核对 payload 中
robot/reason/stationary/latch reason/原状态与 request 和当前持久状态完全一致，并核对
`watchdog_boot_id/watchdog_state_sequence/watchdog_state_sha256` 与当前 persistent chain
head 逐位相同，再核对 request hash、expiry，重建 `ResetAuthorization` 与 authorization
hash；并核对
`ResetAuthorization.operator_gate_receipt_sha256`。无环构造顺序固定为 request→request
hash→双人 receipt/register→authorization。不得猜测“最新 receipt”或只信两个
operator string。

reset coordinator 构造 request 前必须调用一次 `GetReadiness`；其中
`WatchdogStatus.boot_id,state_sequence,state_sha256,state,latch_reason,monotonic_ns` 必须来自
同一把 persistent-state read lock 下的原子 snapshot，不得逐字段读取。coordinator 将这次
challenge 的 boot/sequence/hash 原样写进 request/typed receipt；receipt 注册或人工签字期间
state head 若改变，最终 CAS 正常失败并要求重新取 challenge。Python 不直接读取 C++ state
目录。跨语言 golden test覆盖 challenge→request→receipt→authorization全 preimage。

reset transition 必须是 watchdog 对该 chain head 的 compare-and-swap：新 DISARMED state
在同一 durable record 写
`last_consumed_reset_authorization_sha256` 与 `last_reset_target_state_sha256`，fsync 成功后
才回复 accepted。完全相同 authorization 重放只有在 chain 已显示它完成了同一个 target
transition 时才幂等返回该既有结果，不新增 sequence；任何后来的 latch—even reason 字符串
相同—都有不同 state sequence/hash，旧 request/receipt/authorization 必须拒绝。并发两个
reset 只允许一个 CAS 成功。测试必须覆盖同一 collision reason 的 latch→reset→再次 latch
后重放旧授权、跨 boot重放、并发 reset、response 丢失后的幂等重试和任一 hash伪造。

`GetReadiness.srv`：

```text
---
calibagent_p8_msgs/WatchdogStatus status
bool can_arm
string[] reason_codes
```

其中 status 提供 topic ages、single-writer 结果和 transform readback。不得
提供远程 service 直接绕过 schedule 发送任意非零速度。

QoS 不留给实现者自选：command/telemetry/heartbeat/status 均为
`RELIABLE + VOLATILE + KEEP_LAST(1)`；reference/robot-health 为
`BEST_EFFORT + VOLATILE + KEEP_LAST(5)`；safety event/experiment marker 为
`RELIABLE + TRANSIENT_LOCAL + KEEP_LAST(100)`；navigation/changeover marker 也固定为
`RELIABLE + TRANSIENT_LOCAL + KEEP_LAST(100)`；service 使用 reliable default。deadline/
liveliness lease 数值从冻结 topic map 读取，不在代码里暗藏默认。

SHIFT ground-truth marker 不发布到 detector 可订阅的普通算法 namespace。由
operator tool 直接写 recorder-only journal/受控 topic；detector node/process 的
subscriptions 白名单测试必须证明它看不到 matrix、shift ID、context stage 或
marker。
`changeover_marker` 的 message type 必须精确为
`calibagent_p8_msgs/msg/ChangeoverMarker`，publisher count 恰为 orchestrator/recorder
bridge 这一条；`navigation_marker` 精确为 `NavigationMarker`。两者的 transient replay
仍须由 recorder 以 event ID 去重并返回持久 ACK，不能把 DDS delivery 当 fsync 证明。

### 7.3 进程拓扑

```text
P8 orchestrator / Go2RosBackend
        │ safe logical command + lease + heartbeat
        ▼
independent command relay/watchdog
        │ R1 transform → post-transform safety → vendor adapter
        ▼
Unitree bridge → Go2

reference gateway ─┐
onboard/IMU/BMS ───┼─> state caches ─> backend + watchdog
E-stop/fault I/O ──┘

recorder <─ all raw channels + markers + evaluator-only shift event
```

runner 永远不直接 publish vendor motion topic。watchdog/relay 是唯一 writer，且
zero-command lane 优先于普通命令。bridge 自身还必须有 command timeout；只在
上位机运行 watchdog 不足以覆盖主机到 bridge 的链路断开。

---

## 8. 命令边界与 R1：必须按此实现

### 8.1 六种不同命令

```text
planned/desired
    → candidate
    → pre-R1 hard-safety accepted
    → model_input / safe logical command
    → hidden R1 matrix（nominal 时 identity）
    → post_transform command
    → final wire safety
    → transmitted command
    → ACK/effective command（bridge 能提供时）
```

科学模型标定的是 `model_input → measured body velocity`。因此：

- `RawTrialData.command` 和 `TrialObservation.command` 必须使用矩阵前的
  `model_input`；
- `post_transform`、`transmitted` 和 ACK 必须完整记录，但不得送给 model、
  planner 或 detector；
- nominal、NAV、R2、R3、R4 中 `model_input` 通常等于 transmitted；
- R1 中二者故意不同。

这与 P6 仿真一致：distortion 前 desired 是模型输入，effective 只进 trace。若
R1 用矩阵后的 transmitted command 更新模型，算法会直接获得干预信息，shift
会被显式消解，实验失去效度。

实现前新增 `docs/adr/ADR-003-p8-command-boundaries.md`，记录这一语义，并为
`RawTrialData.command` 增加 regression test；不是静默改写 ADR-001。

### 8.2 R1 command transform

R1 只允许冻结、有限、可逆的 `3×3` matrix：

```python
post_transform = A @ model_input
```

不允许隐式 bias、clipping 或根据结果改变 A。config validator 必须检查：shape、
finite、determinant 非零、`cond_2(A) <= r1.maximum_condition_number`。该上限
必须在 DEV safety config 中冻结，不得读代码默认。R1 的全命令宇宙包含
SHIFT candidate pool、pre-calibration seed、pre/post monitor、validation、
passive recovery、restore sentinel 及 R4 task table 可选命令。验证器要枚举
所有冻结命令的完整 ramp/hold/ramp-out 轨迹，不只查终点，并检查
幅值、linear norm、coupled load、相邻 wire slew/rate 和全时域 projected
workspace。

两个不同进程分别维护两条历史，且不得互相代替：

```text
Python backend / P8SafetyPort.logical_history := 连续 accepted model_input
C++ relay.wire_history                        := 连续 transmitted/post-transform command
```

禁止用 logical history 检查 A 后 slew，也禁止 Python backend 自报 wire accepted。
每个 trial 第一个非零 packet 的 `motion_horizon_s=3.4`；其后 packet 使用冻结 profile
从当前 tick 到最终 zero 的 **剩余等效运动时间**，由共享纯函数
`trial_remaining_equivalent_motion_s(phase, phase_elapsed_s)` 计算，并满足 ramp-in
起点 3.4、SETTLE 起点 3.1、MEASURE 起点 2.3、RAMP_OUT 起点 0.3、结束 0；测试对
分段线性 profile 数值积分做 `1e-12` parity。NAV 每个 packet 使用冻结
`predictive_wire_horizon_s`。relay 在发出第一个/当前非零命令前，用当前
reference pose 对 `A @ model_input` 做该 horizon 的 wire workspace preauthorization。
单 tick 幅值通过不能替代这个全 horizon gate。

`P8SafetyPort` 只产生 logical acceptance；relay 按 `CommandPacket` 原子执行
R1→wire amplitude/norm/coupled-load→wire slew→wire projected workspace→vendor publish，
并在 `CommandTelemetry` 返回最终 decision。任何 wire reject 都由 relay 自己优先
zero+latch，Python 收到 rejected telemetry 只记录/传播同一 fault，不再生成第二个
相互冲突的 safety verdict。

启用流程：

```text
zero command confirmed
→ runner motion-inhibited
→ operator tool loads exact matrix + config hash
→ relay atomically activates transform
→ recorder writes activation monotonic/source time + hash
→ second operator/readback verification
→ new arm lease
```

transform 后再次运行 wire safety。若不安全，必须 zero + latch
`WIRE_COMMAND_OUT_OF_ENVELOPE`；禁止 silent clamp 后继续 trial。
R1 restore 也必须在 zero/disarmed 状态原子将 transform 恢复 identity，记录
readback hash，不得仅在 Python 中忘掉 A。

---

## 9. Reference、frame、时钟和状态融合

### 9.1 frame 合同

唯一 measurement pose：

```text
T_world_base(t) = T_world_reference(t) × T_reference_base
```

`world_frame` 必须与 map geometry 一致；`base` 的 x 向前、y 向左、z 向上，
positive yaw 逆时针。`frames.py` 必须：

- 读取冻结外参并验证 rotation matrix/quaternion；
- 将 reference sensor pose 转成 base SE(2)；
- 做静止、前进、左移、逆时针旋转四个方向 golden tests；
- frame ID 不匹配时失败，不做名称猜测；
- yaw unwrap 只用于连续计算，raw yaw 原样保存。

### 9.2 causal velocity

NAV control 所用 body velocity 必须由独立 reference 的历史窗口因果估计。不得用
future sample、离线 smoother 或 onboard velocity 作为 ground truth feedback。

在 `reference.py` 实现：

```python
estimate_body_twist_causal(samples, window_s) -> (vx, vy, wz, quality)
```

算法使用从窗口起点到最新 pose 的 SE(2) log，与
`MeasurementPipeline._se2_twists_between` 数学一致。少于最小样本、时间倒退、
frame jump、窗口过旧时返回 invalid；不能重复 latest pose 伪造 50 Hz。

### 9.3 rich state 到 `RobotState`

`RobotState` 字段有限，因此 backend 内部先构造 `RichRobotState`：

```text
reference pose/covariance/tracking/age
causal reference body velocity
onboard roll/pitch/base height/yaw rate
battery/BMS/motor temperature/fault
control mode/gait
network/heartbeat/ACK ages
clock sync/frame health
```

然后投影到 public `RobotState`。任何 required stream 超龄、非有限、frame 错、
mode/gait 错或 fault active 时，`localization_valid=false`，同时把精确 reason
交给 watchdog。不得声称 `HardSafetyFilter` 自己检查了网络、电机、温度或 SDK
fault；它没有这些字段。

### 9.4 freshness 与同步

最大 age 全部来自冻结 safety YAML。至少覆盖：reference、onboard state、IMU/
height、BMS、command ACK、runner heartbeat。同步诊断每秒及状态变化时记录；
source clock offset 硬拒收 >10 ms，目标 ≤5 ms。Safety 不因 NTP/ROS clock 回拨
而延长 lease。

Python/relay/watchdog 在同一 host 使用同一 `CLOCK_MONOTONIC` clock ID 和
`boot_id`。reference sensor 可有自己 source clock，但经冻结 time-sync model
转到 host source timeline；不转换跨主机 monotonic 值。snapshot 的各 required
stream source time 经对齐后最大差值不超过
`quality.maximum_cross_stream_skew_ms`，否则 `CROSS_STREAM_SKEW`。

若 bridge 确认没有 controller ACK，topic map 明确 `ack_available=false`，watchdog
改为要求 relay publish echo/bridge heartbeat，不启用 `ACK_STALE`；不得虚构 ACK。
此时所有“zero confirmed”的精确定义为 `relay zero publish echo + fresh bridge
heartbeat + reference-measured stationary`；有 controller ACK 时再额外要求 zero ACK。
若 ACK 声明 available，则 stale 必须 fail closed。

### 9.5 P8 observation invalid reason 适配器

现有 `MeasurementPipeline` 的 `quality["reason_codes"]` 是内部词表，不能直接写入 P8
schema。新增唯一 `P8ObservationQualityAdapter`，在 immutable
`ScientificUnitResult` 构造前执行下列逐项 mapping；禁止 runner、SHIFT policy 或 exporter
各写一套别名：

| `MeasurementPipeline` 内部 code | P8 canonical invalid reason |
|---|---|
| `INSUFFICIENT_SAMPLES` | `REFERENCE_SAMPLE_COUNT_LOW` |
| `NON_MONOTONIC_TIMESTAMP` | `TIMESTAMP_NON_MONOTONIC` |
| `TIMESTAMP_GAP` | `REFERENCE_GAP_EXCEEDED` |
| `EXCESSIVE_DROP_RATE` | `REFERENCE_VALID_RATIO_LOW` |
| `INSUFFICIENT_STEADY_RATIO` | `STEADY_RATIO_LOW` |
| `NONFINITE_ESTIMATE` | `NONFINITE_VALUE` |
| `COMMAND_NOT_CONSTANT` | `COMMAND_DEVIATION_EXCEEDED` |

adapter 同时合并三个来源，来源顺序不决定 primary：

1. frame/reference/time-sync preprocessor 只可产生
   `FRAME_MISMATCH,REFERENCE_INVALID,REFERENCE_SAMPLE_COUNT_LOW,
   REFERENCE_RATE_OUT_OF_RANGE,REFERENCE_GAP_EXCEEDED,
   REFERENCE_VALID_RATIO_LOW,TIME_SYNC_OFFSET_EXCEEDED,CROSS_STREAM_SKEW,
   CONTROL_TRACE_COVERAGE_LOW,MEASUREMENT_WINDOW_UNAVAILABLE`；
2. `MeasurementPipeline` 内部 code 必须先经过上表，不允许保留原字符串；
3. prediction/metric reconstruction 层只可追加
   `PREDICTION_UNAVAILABLE,METRIC_RECONSTRUCTION_FAILED`，已有 physical outcome 而无法
   构造 observation 时可追加 `ATTEMPT_ABORTED_BEFORE_OBSERVATION`。

合并算法精确为：验证每个输入 code 属于其来源 allowlist → mapping → set 去重 → 按
handoff §12.3 的完整冻结 priority list 排序 → tuple 写
`invalid_reason_codes` → tuple 第一项写 `primary_invalid_reason`。空 tuple 时且仅当
`valid=true`；非空时且仅当 `valid=false`。同一 canonical code 被多个来源报告只保留一次。
pipeline 的 shape/API contract 违反或未知字符串不是科学 invalid observation，而是
`UNCLASSIFIED_INTERNAL_FAULT` 并进入 internal review；不得映射成可重采 code。exporter
只能逐字投影 scientific result 的 primary，不能再次解析 raw quality 字符串。

必须有 table-driven test 覆盖上述七个现有内部 code、跨来源重复、多个原因 priority、
空集合、未知 code 和 pipeline code 泄漏；另断言 handoff schema enum、guide priority 和
adapter 常量逐项相等。

---

## 10. 独立 watchdog、command lease 和 arm

### 10.1 supervisor 状态机

`watchdog.py` 的纯状态机与 ROS 独立进程使用同一枚举和测试向量：

```text
BOOT --self_test_pass + no prior state--> DISARMED
BOOT --self_test_pass + persisted state--> RESTORE_PERSISTED_STATE
RESTORE_PERSISTED_STATE --> DISARMED | TECH_ABORT_DISARMED | SAFETY_ABORT_LATCHED
BOOT/RESTORE_PERSISTED_STATE --missing/corrupt/rollback--> PERSISTENCE_CORRUPT
DISARMED --preflight_start--> PREFLIGHT --preflight_pass--> READY
READY --arm(valid one-attempt lease)--> ARMED_IDLE
ARMED_IDLE --begin_execution--> EXECUTING
EXECUTING --complete_execution--> ZERO_CONFIRM --stationary--> COMPLETE --finalize--> DISARMED

任意非终态 safety fault → ZERO_CONFIRM → SAFETY_ABORT_LATCHED
普通 runtime/technical fault → ZERO_CONFIRM → TECH_ABORT_DISARMED
TECH_ABORT_DISARMED --explicit acknowledge--> DISARMED
READY/ARMED_IDLE --disarm--> ZERO_CONFIRM → DISARMED
任意状态 --state persistence failure--> high-priority ZERO → PERSISTENCE_CORRUPT
```

只有首次 commissioning 且确实没有 prior state 才走 BOOT→DISARMED；corrupt/missing
state 但输出目录表明曾运行过时 fail closed，不得当成首次启动。`EXECUTING/READY/
ARMED_IDLE/ZERO_CONFIRM/COMPLETE` 在进程崩溃后恢复为
`TECH_ABORT_DISARMED`，但已有 `SAFETY_ABORT_LATCHED` 永远保持 latch。

`COMPLETE` 只是一个必须写 journal 的短过渡态，随后立即进入
`DISARMED`。每个 trial/episode 使用 fresh preflight、新的单-attempt
`ArmAuthorization` 和新 lease；只有其引用的 `ScopeAuthorization` 可在
scope/时间/quota 内复用。第二个乃至第 N 个 trial 绝不能复用前一 attempt
authorization 或 preflight hash。

`SAFETY_ABORT_LATCHED` 只能在机器人静止、ordinary command lane 被禁止、物理
安全员确认后通过显式 reset service 复位；断线重连、进程重启、下一 trial 和
resume 都不能自动复位。
只有冻结 safety fault 词表进入 latch；process crash、storage I/O 等不能
被泛化 `except Exception` 误标为 safety event，但两者都必须先 zero。

### 10.1.1 robot-scoped supervisor 持久状态

authorization quota 只是 supervisor 状态的一部分，不能作为唯一持久物。
`schemas/p8/watchdog_state.schema.json` 必须拒绝 unknown key，并冻结下面的完整 record：

```text
schema_version == "p8.watchdog-state.v1"
robot_id
state_sequence
previous_state_sha256                 # genesis 为 null
state_sha256                          # 不进入自己的 preimage
state                                  # 第 10.1 节枚举，另含 PERSISTENCE_CORRUPT
latch_reason                           # nullable
latch_serious                          # bool
active_scope_authorization_sha256      # nullable
active_authorization_sha256            # nullable，单-attempt authorization
active_preflight_receipt_sha256        # nullable
active_prepared_attempt_sha256         # nullable
active_lease_id                        # nullable
active_attempt_uid                     # nullable
lease_deadline_ns                      # nullable
boot_id
last_command_sequence                  # nullable
transform_id
transform_sha256
quota_state_sha256                     # 始终64hex；至少指 quota genesis
operator_gate_receipt_tail_sha256      # 始终64hex；空 receipt 链为64个0
last_consumed_reset_authorization_sha256 # nullable；最近一次 reset CAS
last_reset_target_state_sha256         # nullable；该 authorization 精确解除的旧 state
last_transition
transition_monotonic_ns
persisted_utc
```

每条 supervisor record都是 atomic cut：GlobalStateProof 顶层的 state/quota/receipt/
active-scope/last-reset heads必须逐位等于该 cut最后 supervisor record的同名字段；不得用之后
分别查询到的 heads拼接。active/reset字段按注释可 null，quota/receipt绝不为 null/空字符串。

权威路径精确为
`<watchdog_state_store.root_path>/<robot_id>/`
`supervisor_state_s<state_sequence:020d>_<state_sha256>.json`。`state_sha256` 为
canonical JSON 排除 `state_sha256` 自身后的 SHA-256；`previous_state_sha256` 必须
指向同 robot 的前一 sequence，sequence 必须逐一递增。可选
`supervisor_state_current.json` 只是 atomic pointer/cache，永远不能覆盖 hash 链选择。
目录或 record 的 `robot_id` 与 resolved safety config 不同即拒绝启动。

状态转换由 C++ watchdog/relay 独占写入。每次可能改变 durable state、latch、
authorization、quota、lease、attempt 或 transform 的操作必须按以下顺序：

```text
计算 next record（以及必要的 immutable quota record）
→ quota temp write + file fsync + rename（若有；尚未被引用时只是 orphan）
→ supervisor temp write + file fsync
→ same-directory atomic rename 到 content-addressed final path
→ directory fsync
→ atomic 更新 non-authoritative current pointer + file/directory fsync
→ 才返回 ROS service success、开放下一条非零 packet lane 或发布 READY/ARMED status
```

arm 的 `ARMED_IDLE` record 必须在同一 record 中绑定 scope hash、已经消费 quota、
单-attempt authorization、新 lease、attempt UID、prepared hash 和 receipt hash；重复 arm 只有在这些字段完全相同且链上已有
该 record 时才幂等返回原 lease。安全 fault 的 high-priority zero 不等待磁盘，但 zero
发出后必须先持久化 latch record才可回复 caller。普通命令 acceptance 绝不能先于
开启该 lease 的 `ARMED_IDLE/EXECUTING` durable commit。这里不要求 100 Hz 每个 packet
都 fsync；`last_command_sequence` 是每个 durable transition 时的快照，进程内 sequence
检查仍由 C++ relay 独占，重启生成新 `boot_id` 且必须重新 preflight/arm。

启动时从目录中重建并逐条验证最大完整连续链，而不是信任 pointer。hash 错、JSON/
schema 错、sequence gap/rollback、跨 robot link、两个同 sequence 不同 hash、链尾引用
缺失，或检测到 journal/目录表明该 robot 曾运行却找不到 state，均进入
`PERSISTENCE_CORRUPT`：立即走独立 zero lane、禁止所有 ordinary command 和 arm，且
不得自动“修复”为 DISARMED。任何 fsync/rename/pointer 失败同样 fail closed，并以
supervisor internal reason `PERSISTENCE_CORRUPT` 报告；该 reason 不是 scientific
technical-retry code。恢复必须由离线审计工具保存坏链、重建可验证链并经双人 reset，
Python runner 无权清除。

### 10.2 arm lease

非零命令同时要求：

- CLI 显式 `--arm`；
- release/config/schedule hash 匹配；
- watchdog state 为 `ARMED_IDLE/EXECUTING`；
- 物理 E-stop ready；
- runner heartbeat 未过期；
- command packet sequence 严格递增；
- command lease deadline 尚未过期；
- reference/state/fault/mode/storage recorder readiness 全通过。

任一条件失败，relay 只允许零命令。启动默认 zero；resume 后恢复持久 watchdog
state，并且只有原状态确为 DISARMED 才保持 DISARMED，绝不把 latch 当成默认值覆盖。

### 10.3 watchdog 必查故障

```text
RUNNER_HEARTBEAT_STALE
COMMAND_LEASE_EXPIRED
COMMAND_SEQUENCE_INVALID
REFERENCE_STALE
REFERENCE_INVALID
STATE_STALE
STATE_NONFINITE
IMU_OR_HEIGHT_STALE
BMS_STALE
LOW_BATTERY
MOTOR_FAULT
MOTOR_TEMPERATURE_LIMIT
CONTROL_MODE_MISMATCH
GAIT_MISMATCH
ACK_STALE
NETWORK_FAULT
PHYSICAL_ESTOP
ROLL_LIMIT
PITCH_LIMIT
BASE_HEIGHT_LIMIT
WORKSPACE_LIMIT
WIRE_COMMAND_OUT_OF_ENVELOPE
MULTIPLE_VENDOR_COMMAND_PUBLISHERS
RECORDER_NOT_READY
```

latency 记录四个事件：safety decision、zero publish、bridge ACK、reference 观察到
物理停止。`decision→zero publish` 必须 ≤40 ms；物理停止 latency 单独报告，
不能混成软件 latency。

### 10.3.1 停机响应、scientific status 与重采资格

三者必须分别计算，禁止从“watchdog 发了 zero”反推这个数据是否能重采：

| 事件类 | physical action | ledger/scientific status | budget/retry |
|---|---|---|---|
| `PREPARED_ATTEMPT` durable boundary 前的 readiness/technical/safety failure | zero；safety 仍 latch | 仅 run-level event，无 attempt/scientific row | 原 PRIMARY pending |
| 正常 success/complete | zero-confirm→DISARMED | `complete`, protocol-complete | 消耗 unit，不重采 |
| NAV timeout/未到达 | zero-confirm→DISARMED | `timeout / TIMEOUT`，protocol-complete | 消耗 unit，不重采 |
| NAV collision | immediate zero + safety latch | `safety_abort / COLLISION`，`collision=true`，protocol-complete | 消耗 unit，不重采，exit 4 |
| planner 无 safe candidate 或 logical envelope reject | immediate zero + safety latch | `safety_abort / ALGORITHM_SAFETY_ABORT`，protocol-complete | algorithmic outcome，消耗 unit |
| relay post-transform/wire envelope reject | immediate zero + safety latch | `safety_abort / WIRE_COMMAND_OUT_OF_ENVELOPE`，protocol-complete | runtime safety outcome，消耗 unit |
| durable boundary 后 handoff §14.2 的 runtime technical code（包括 reference/state/BMS/ACK/network/recorder/lease 对应 code） | immediate zero；运动中→TECH_ABORT_DISARMED，未运动保持 DISARMED | `technical_abort` 或 `pre_measure_abort`，`protocol_complete=false` | 不消耗；不自动；双人 acknowledge 后可显式 RERUN_TECH |
| durable boundary 后 handoff §14.2 的 runtime safety code（LOW_BATTERY/MOTOR/PHYSICAL_ESTOP/ROLL/PITCH/HEIGHT/WORKSPACE/WIRE） | immediate zero + safety latch | `safety_abort`；`serious` 依 handoff §6.4，`protocol_complete=true` | 消耗 unit，不重采，保留安全证据 |
| final zero/stationary 无法确认 | zero lane 重试 + safety latch | `safety_abort`, serious candidate | 不重采，先安全复审 |

`SafetyFault.code` 只能来自冻结 safety/algorithm vocabulary；technical code 只能来自
handoff §14.2，`POOR_RESULT/HIGH_RMSE/MISSED_DETECTION/TIMEOUT/COLLISION` 永远不是
technical code。`serious_safety_event` 按 handoff §6.4 的事实定义，不等于“凡 latch
都 serious”。技术重采保持原 `dataset_role/scientific_unit_id`，使用
`attempt_role=RERUN_TECH`、新 UID/递增 index/前一 UID；`retry_permitted` 只表示
allowlist 和 protocol completeness 的机械结论，仍需显式 retry CLI 与新 authorization。

### 10.4 独立性边界

Python runner 崩溃后 watchdog 仍必须工作。物理 E-stop 还必须有不依赖 ROS、
模型、磁盘或 Python 的独立链路。仓库代码只能验证/记录这一链路，不能用一个
Python `emergency_stop()` 冒充物理 E-stop。

---

## 11. `Go2RosBackend` 四方法的完整语义

### 11.1 构造与默认行为

没有完整依赖、没有当前有效 lease、topic 不健康、output 未就绪时，backend 必须只
允许 zero/preflight，并拒绝运动。完成 P8 后从 `pyproject.toml` coverage omit
中移除 `src/calibagent/backends/go2_ros.py`。
backend 初始化只建立 query-only client 并读取 watchdog status；它没有权限初始化、
覆盖或“同步”独立 watchdog 状态。本地 UNBOUND 不是一个 ROS supervisor state。

### 11.2 `reset(context)`

严格顺序：

1. `publish_zero("RESET")`；
2. 等待第 9.4 节定义的 zero-confirmation gate 和 reference-measured stationary；
3. 查询 watchdog；若为 `SAFETY_ABORT_LATCHED` 或 `TECH_ABORT_DISARMED`，立即拒绝并
   要求分别调用显式 `ResetAbortLatch` 或 `AcknowledgeTechnicalAbort`；否则确认它
   已在 DISARMED；
4. 验证 `RobotContext` 与冻结 terrain/payload/gait/session 一致；
5. 检查 reference、frame、clock、state、BMS、motor、mode、storage；
6. 清空 trial-local in-memory buffers；
7. 不删除任何 raw/journal/ledger/posterior；
8. 写 reset marker 和 readiness report；
9. 保持未 arm，等待显式 lease。

`reset` 不是“把机器人自动走回起点”。人工/受控回位由 NAV/SHIFT runner 的
operator gate 管理，且回位数据单独标记。
`reset(context)` 永远不能清除 safety latch、technical acknowledgement 或持久
authorization quota；即使机器人已经静止也不例外。

### 11.3 `get_state()`

一次调用必须从同一 snapshot cut 读取 reference/onboard/fault 状态，生成：

```python
RobotState(
    timestamp=clock.now_ns() * 1e-9,
    position_xy=reference_base_xy,
    yaw=reference_base_yaw,
    roll=onboard.roll,
    pitch=onboard.pitch,
    base_height=onboard.base_height_m,
    velocity=causal_reference_body_twist,
    battery_ratio=onboard.battery_ratio,
    localization_valid=all_required_health_valid,
)
```

缺失或 stale 时不得返回最后一次“看起来正常”的值。raw sample 仍保留完整原因。

### 11.3.1 `prepare_attempt(identity, context, start_pose_gate, planning)`

该方法解决 reservation/recorder/precheck 与 preflight/arm 的顺序：所有可能阻塞的磁盘
准备都在 arm 前完成，且整个阶段只允许 zero。伪代码必须等价于：

```python
def prepare_attempt(identity, context, start_pose_gate, planning):
    require_local_state("UNBOUND")
    require_watchdog_state("DISARMED")
    require_context_matches(identity, context)
    require_equal(start_pose_gate.identity, identity)
    require(start_pose_gate.passed)
    require_gate_age_at_most(
        start_pose_gate, config.calibration_start_gate.maximum_start_pose_gate_age_ms
    )
    require_frozen_planning_matches_identity_and_proposal(planning, identity)
    require_equal(planning.safety_boot_id, watchdog.current_boot_id())
    require_age_at_most(
        planning.safety_cut_monotonic_ns,
        config.calibration_start_gate.maximum_start_pose_gate_age_ms,
    )
    require_zero_confirmation_and_stationary(watchdog.disarm("PREPARE_ATTEMPT"))
    prepared_start_ns = clock.now_ns()
    attempt_recorder = None
    reservation = None
    event = None
    attempt_boundary_committed = False
    try:
        # group 可连续录系统 topic，但这里尚未创建 attempt。
        recorder.ensure_group_open(bag_group_id_for(identity))
        precheck_start_ns = clock.now_ns()
        precheck_samples = []
        for deadline_ns in absolute_deadlines(
            duration_s=max(0.5, config.trial_profile.precheck_min_s),
            rate_hz=config.trial_profile.sample_rate_hz,
        ):
            sleep_until_monotonic(deadline_ns)
            state = snapshot_reader.latest_cut(clock.now_ns())
            require_logical_monitor_safe(safety_filter.monitor_state(state))
            require_reference_measured_stationary(state)
            require_watchdog_state("DISARMED")
            watchdog.heartbeat(
                next_heartbeat_sequence(),
                command_sequence=None,
                lease_deadline_ns=None,
            )
            precheck_samples.append(state)
        precheck_end_ns = clock.now_ns()
        precheck_snapshot_sha256 = hash_precheck_window(precheck_samples)
        fresh_start_pose_gate = recheck_start_pose_from_precheck_end(
            identity=identity,
            prior_gate=start_pose_gate,
            samples=precheck_samples,
            cut_monotonic_ns=precheck_end_ns,
        )
        if not fresh_start_pose_gate.passed:
            raise StartPoseRefreshRequired(fresh_start_pose_gate)
        fresh_start_pose_gate_sha256 = detached_sha256(fresh_start_pose_gate)
        precheck_reauthorization = reauthorize_frozen_proposal_without_reselection(
            planning=planning,
            precheck_samples=precheck_samples,
            latest_state=precheck_samples[-1],
        )
        if planning.proposal_sha256 is not None and not precheck_reauthorization.accepted:
            raise SafetySnapshotRefreshRequired(precheck_reauthorization)
        precheck_snapshot_sha256 = hash_precheck_window_and_reauthorization(
            precheck_samples, precheck_reauthorization
        )

        # 只有完整 readiness/safety/stationary window 通过后才跨 attempt boundary。
        reservation = journal.reserve_attempt_and_fsync(identity)
        attempt_recorder = recorder.begin_attempt(
            identity,
            precheck_start_monotonic_ns=precheck_start_ns,
            precheck_end_monotonic_ns=precheck_end_ns,
            precheck_snapshot_sha256=precheck_snapshot_sha256,
        )
        prepared = PreparedAttempt(
            identity=identity,
            execution_mode="ROBOT_MOTION",
            start_pose_gate_result=fresh_start_pose_gate,
            start_pose_gate_result_sha256=fresh_start_pose_gate_sha256,
            planning=planning,
            reservation_event_id=reservation.event_id,
            reservation_event_sha256=reservation.event_sha256,
            recorder_attempt_id=attempt_recorder.stable_attempt_id(),
            raw_uri=attempt_recorder.open_raw_uri(),
            bag_group_id=bag_group_id_for(identity),
            segment_id=attempt_recorder.open_segment_id(),
            prepared_start_monotonic_ns=prepared_start_ns,
            precheck_start_monotonic_ns=precheck_start_ns,
            precheck_end_monotonic_ns=precheck_end_ns,
            precheck_snapshot_sha256=precheck_snapshot_sha256,
        )
        prepared_ref = content_store.put(
            object_class="prepared_attempts",
            value=prepared,
            schema="prepared_attempt.schema.json",
            idempotency_key=(reservation.event_sha256, identity.attempt_uid),
        )
        prepared_sha256 = prepared_ref.semantic_sha256
        event = prepared_attempt_event(
            identity=identity,
            reservation=reservation,
            prepared_ref=prepared_ref,
        )
        attempt_recorder.mark(event)
        journal.append_and_fsync(event)
        attempt_boundary_committed = True
        register_single_use_prepared_handle(
            prepared_sha256, prepared, attempt_recorder, context
        )
        return prepared
    except StartPoseRefreshRequired as error:
        immediate_zero_without_disk("START_POSE_REFRESH_REQUIRED")
        assert not resolve_hash_valid_prepared_boundary(journal, identity, event)
        journal.append_and_fsync(
            run_level_start_pose_refresh_event(
                planned_unit_id=identity.scientific_unit_id,
                gate_result_sha256=detached_sha256(error.gate_result),
            )
        )
        raise
    except SafetySnapshotRefreshRequired as error:
        immediate_zero_without_disk("SAFETY_SNAPSHOT_REFRESH_REQUIRED")
        assert not resolve_hash_valid_prepared_boundary(journal, identity, event)
        journal.append_and_fsync(
            run_level_safety_snapshot_refresh_event(
                planned_unit_id=identity.scientific_unit_id,
                original_preauthorization_sha256=
                    planning.command_preauthorization_sha256,
                refresh_result_sha256=detached_sha256(error.result),
            )
        )
        raise
    except SafetyFault as error:
        # 无论 boundary 在哪，第一动作都是 high-priority zero/latch。
        immediate_safety_latch_without_disk(error.code, serious=error.serious)
        attempt_boundary_committed = resolve_hash_valid_prepared_boundary(
            journal, identity, event
        )
        if attempt_boundary_committed:
            physical = finalize_pre_measure_safety_abort_and_physical_commit(
                attempt_recorder, identity, prepared_start_ns, error.code
            )
            raise_with_physical_commit(error, physical)
        append_run_level_preparation_gate_event_after_stop(
            identity, error.code, identity_fields="NOT_APPLICABLE"
        )
        raise
    except BaseException as error:
        # 第一动作是 zero；随后才允许碰 recorder/journal。
        immediate_zero_without_disk("PREPARATION_ABORT")
        fault = classify_execution_fault_nonthrowing(error)
        attempt_boundary_committed = resolve_hash_valid_prepared_boundary(
            journal, identity, event
        )
        if attempt_boundary_committed:
            physical = finalize_pre_measure_non_safety_abort_and_physical_commit(
                attempt_recorder,
                identity,
                prepared_start_ns,
                kind=fault.kind,
                terminal_reason=fault.terminal_reason,
                technical_failure_code=fault.technical_failure_code,
            )
            raise_with_physical_commit(error, physical)
        journal.append_and_fsync(
            run_level_preparation_failed_event(
                planned_unit_id=identity.scientific_unit_id,
                reason=fault.terminal_reason,
            )
        )
        raise
```

`AttemptRecorder.stable_attempt_id/open_segment_id` 是 recorder port 的只读属性；实现时
应把它们加进第 5.5 节 port，不得从路径拆字符串。group 在 precheck 前打开是为了保留
raw system topics，不等于创建 attempt；`begin_attempt` 必须把已验证的
`[precheck_start_ns,precheck_end_ns]` range 纳入 attempt artifact。只有
`PREPARED_ATTEMPT` journal event fsync 后，`attempt_boundary_committed=true`。
这个 bool 只是快取；exception/crash recovery 必须按 event identity/hash 查询 durable
journal 决定 boundary，不能因 `append_and_fsync` 在 fsync 后、return 前抛错而把已存在
attempt 降格成 run-level preparation failure。
`reserve_attempt_and_fsync` 只写 `identity_kind=run_level,event_type=ATTEMPT_RESERVATION`，
payload 保存 proposed identity/hash；它不创建 ledger/scientific attempt。reservation UID
仍进入全局 used-UID set，失败后不得复用；下一次可用新 UID 重新 reserve 同一
PRIMARY/index=1，因为此前没有 attempt row。只有 `PREPARED_ATTEMPT` 把 reservation
提升为 attempt boundary，validator 必须从两事件 hash link 验证。

`PREPARED_ATTEMPT` payload精确含
`identity,reservation_event_id,reservation_event_sha256,prepared_path,
prepared_semantic_sha256,prepared_raw_sha256,prepared_size_bytes,
prepared_schema_version`。crash在 prepared artifact fsync后/event前时，resume按
`(reservation_event_sha256,attempt_uid)`扫描：0个才写，1个 hash-valid candidate逐字复用并
补同一 event，多个不同 bytes立即 corruption。event已存在则只能 resolve其 ref；不能从
recorder目录重建新 timestamps。single-use handle在 event fsync后注册/恢复，event前 orphan
不构成 attempt boundary。fault injection覆盖 artifact file/dir fsync、event/marker fsync和
handle install，断言唯一 candidate/event与相同 prepared bytes。
此前任何 failure 只写 run-level preparation event，attempt-bound identity 字段为
`NOT_APPLICABLE`，原 PRIMARY 仍 pending；reservation/begin 留下的临时物是 orphan，不能
进入 attempt ledger。boundary 之后的 technical failure 写 `pre_measure_abort` 并允许
RERUN_TECH；safety failure 写 `safety_abort,protocol_complete=true`、消耗 unit。

prepared 已返回后的 preflight/authorization/arm failure 必须通过
`abandon_prepared_attempt` 幂等完成同一分类并 append+fsync
`ATTEMPT_PHYSICAL_COMMIT`。任何 helper 返回 physical commit 后都必须把它附在 exception，
让第 12 节 executor 写唯一 scientific commit；不能在 exception 中丢失已跨 boundary 的
attempt。

### 11.4 `execute_trial(command, policy)`

backend 只负责真实执行和物理 artifact，不更新 posterior。**从 arm 后的第一个本地
操作开始**，包括 consume binding 和 lease validation，全部在同一个 `try/finally`
内；伪代码必须等价于：

```python
def execute_trial(command, policy):
    prepared = identity = lease = attempt_recorder = None
    result = artifacts = physical_commit = None
    finalize_succeeded = False
    measure_start_ns = measure_end_ns = None
    measure_model_input = None
    physical_phase_trace = []
    logical_history = []
    try:
        prepared, lease, attempt_recorder = consume_single_use_prepared_binding()
        identity = prepared.identity
        require_prepared_hash_and_recorder_match(prepared, attempt_recorder)
        require_watchdog_state_and_lease("ARMED_IDLE", identity, lease)
        measure_model_input = command.as_array().copy()
        start_ns = prepared.prepared_start_monotonic_ns
        initial_state = snapshot_reader.latest_cut(clock.now_ns())
        require_logical_monitor_safe(
            safety_filter.preauthorize_trial(
                command,
                initial_state,
                equivalent_motion_s=3.4,
                logical_history=tuple(logical_history),
            )
        )
        precheck_event = physical_event(identity, "PRECHECK_PASSED", clock.now_ns())
        attempt_recorder.mark(precheck_event)
        journal.append_and_fsync(precheck_event)
        physical_phase_trace.append(precheck_event)
        watchdog.begin_execution(identity, lease.lease_id)

        for phase, absolute_deadlines_for_phase in frozen_profile(policy):
            phase_start = physical_event(identity, f"{phase}_START", clock.now_ns())
            attempt_recorder.mark(phase_start)
            journal.append_and_fsync(phase_start)
            for scheduler_deadline_ns in absolute_deadlines_for_phase:
                sleep_until_monotonic(scheduler_deadline_ns)
                rich_state = snapshot_reader.latest_cut(clock.now_ns())
                require_logical_monitor_safe(safety_filter.monitor_state(rich_state))
                proposal = CommandProposal(
                    planned=command,
                    candidate=phase_ramp(command, phase, scheduler_deadline_ns),
                    phase=phase,
                    motion_horizon_s=trial_remaining_equivalent_motion_s(
                        phase, phase_elapsed_s(scheduler_deadline_ns)
                    ),
                    metadata=trial_tick_metadata(),
                )
                decision = safety_filter.evaluate_logical(
                    proposal,
                    rich_state,
                    dt_s=1.0 / config.trial_profile.sample_rate_hz,
                    logical_history=tuple(logical_history),
                )
                model_input = require_accepted_logical_command(decision)
                if phase == MEASURE:
                    assert_exact_vector(model_input.as_array(), measure_model_input)
                intent = build_trial_intent(
                    proposal=proposal, safe=model_input, model_input=model_input
                )
                tick_lease_deadline_ns = min(
                    lease.expires_monotonic_ns,
                    clock.now_ns() + config.command_lease_ns,
                )
                receipt = driver.publish(
                    identity, lease, intent,
                    lease_deadline_ns=tick_lease_deadline_ns,
                )
                require_relay_accepted_or_propagate_latched_fault(receipt)
                watchdog.heartbeat(
                    next_heartbeat_sequence(),
                    command_sequence=receipt.sequence,
                    lease_deadline_ns=tick_lease_deadline_ns,
                )
                attempt_recorder.append_sample(
                    build_p8_sample(identity, rich_state, intent, receipt)
                )
                logical_history.append(model_input)
                if phase == MEASURE:
                    measure_start_ns = (
                        rich_state.reference.monotonic_ns
                        if measure_start_ns is None else measure_start_ns
                    )
                    measure_end_ns = rich_state.reference.monotonic_ns
            phase_complete = physical_event(
                identity, completion_event_for(phase), clock.now_ns()
            )
            attempt_recorder.mark(phase_complete)
            journal.append_and_fsync(phase_complete)
            physical_phase_trace.append(phase_complete)

        zero_receipt = watchdog.complete_execution("TRIAL_COMPLETE")
        require_zero_confirmation_and_stationary(zero_receipt)
        assert measure_start_ns is not None and measure_end_ns is not None
        reference_samples = reference_reader.window(measure_start_ns, measure_end_ns)
        raw = RawTrialData(
            timestamps=validated_source_seconds(reference_samples),
            command=repeat_vector_at_reference_times(
                measure_model_input, reference_samples
            ),
            pose_se2=world_base_pose(reference_samples),
            context=context_bound_to(prepared),
            metadata=command_boundary_and_physical_trace_metadata(
                physical_phase_trace
            ),
            raw_ref=attempt_recorder.open_raw_uri(),
        )
        validate_raw_trial_data_before_commit(raw)
        result = AttemptResult(
            identity=identity,
            status="complete",
            terminal_reason="TRIAL_COMPLETE",
            start_monotonic_ns=start_ns,
            end_monotonic_ns=clock.now_ns(),
            motion_completed=True,
            measurement_constructed=True,
            technical_failure_code=None,
            serious_safety_event=False,
        )
        artifacts = attempt_recorder.finalize(result)
        finalize_succeeded = True
        physical_commit = journal.append_and_fsync(
            attempt_physical_commit_event(result, artifacts)
        )
        raw.metadata["artifact_refs"] = artifact_refs_to_json(artifacts)
        raw.metadata["physical_commit_event_sha256"] = physical_commit.event_sha256
        return raw
    except SafetyFault as error:
        # 必须先 high-priority zero/latch；任何 finalize、日志或模型动作都在其后。
        immediate_stop_for_current_watchdog_state(
            kind="safety", reason=error.code, serious=error.serious
        )
        finalize_and_commit_failure_once(
            prepared, attempt_recorder, safety_attempt_result(prepared, error),
            finalize_succeeded,
        )
        raise
    except BaseException as error:
        # consume/lease validation 失败也可能发生在 ARMED_IDLE，不能逃出停机保护。
        fault = classify_execution_fault_nonthrowing(error)
        immediate_stop_for_current_watchdog_state(
            kind=fault.watchdog_kind, reason=fault.terminal_reason, serious=False
        )
        if finalize_succeeded:
            preserve_finalized_attempt_as_uncommitted_orphan(result, artifacts, error)
        else:
            finalize_and_commit_failure_once(
                prepared,
                attempt_recorder,
                non_safety_attempt_result(prepared, fault),
                False,
            )
        raise
    finally:
        release_consumed_binding_if_any(prepared)
        ensure_no_armed_or_executing_state_without_disk()
        best_effort_zero_without_waiting_for_model_or_disk()
```

上述 helper 不是留给 agent 发明语义：`physical_event/build_p8_sample` 只构造第 5 节
dataclass；`classify_execution_fault_nonthrowing` 不抛异常并严格三分 typed allowlist
technical、OperatorCancelled 和 internal fault；只有第一类携带 `technical_failure_code`；
`immediate_stop_for_current_watchdog_state` 在 `ARMED_IDLE/EXECUTING` 分别调用可达的
disarm/technical-abort 或 safety-latch service，并且它必须是 `except` 的第一条有副作用
语句。若 binding consume 在抛错前没有返回 identity，该 helper 从 watchdog 当前
持久 active attempt 取目标，不得因本地变量为 `None` 跳过停机。
`finalize_and_commit_failure_once` 最多调用一次 `AttemptRecorder.finalize`，成功后只写
`ATTEMPT_PHYSICAL_COMMIT`；finalize 对同一 result 幂等，对不同 result 拒绝。secondary
finalize/journal error 不能覆盖原始 fault。

`completion_event_for` 是冻结 mapping：
`RAMP_IN→RAMP_REACHED, EXCITE→SETTLED,
MEASURE→MEASUREMENT_COMPLETE, RAMP_OUT→RAMPED_OUT`，不允许其他 phase。
`frozen_profile(policy)` 只接受 policy 与 resolved trial profile 逐字段完全相等，按
`RAMP_IN(0.6),EXCITE(0.8),MEASURE(2.0),RAMP_OUT(0.6)` 顺序，每段使用 half-open tick
grid `[start,end)`，再单独记录 end marker。MEASURE window 包含第一至最后一条真实
accepted MEASURE sample 的 reference monotonic timestamp；
`IndependentReferenceReader.window` 两端 inclusive。PRECHECK 是 arm 前连续不少于
0.5 s 的 zero/stationary window，不属于四段 commanded-motion grid。

成功路径必须先构造并验证 `RawTrialData`，再单次 finalize attempt-local artifact，
最后 append `ATTEMPT_PHYSICAL_COMMIT`。该 commit 只说明不可变的物理结果可恢复，不
代表 observation、posterior 或论文 selection 已完成。finalize 后 journal 失败不允许
改写同一 artifact；它作为 orphan 保留，resume 按 artifact hash 幂等补同一个 physical
commit，只有 artifact 本身不可恢复时才按 handoff
`MARKER_UNRECOVERABLE/STORAGE_IO_FAILURE` 走显式技术重采。

事务失败表：

| 失败点 | 运动 | watchdog 终态 | physical journal | scientific unit |
|---|---:|---|---|---|
| durable boundary 前的 recorder readiness/precheck 失败 | 无 | DISARMED 或 safety latch | run-level event，无 attempt row | 原 PRIMARY 保持 pending |
| reservation/begin/boundary commit 失败 | 无 | DISARMED | orphan + `PREPARATION_FAILED`，无 attempt row | 原 PRIMARY 保持 pending |
| prepared 后 preflight/arm technical 失败 | 无 | DISARMED | `pre_measure_abort` + physical commit | exact allowlist 才可显式技术重采 |
| prepared 后 preflight/arm safety 失败 | 无 | SAFETY_ABORT_LATCHED | `safety_abort` + physical commit | protocol-complete，消耗预算 |
| prepared 后 operator cancel | 无 | DISARMED | `pre_measure_abort / OPERATOR_CANCELLED` | 暂停；不自动、不取得重采资格 |
| prepared 后 unknown internal exception | 无/可能已运动 | TECH_ABORT_DISARMED | `pre_measure_abort|technical_abort / UNCLASSIFIED_INTERNAL_FAULT` | PAUSED_INTERNAL_REVIEW；不得重采 |
| algorithm safety fault | 可能已运动 | SAFETY_ABORT_LATCHED | safety physical commit、raw 保留 | 消耗预算 |
| process/storage/reference technical fault | 可能已运动 | TECH_ABORT_DISARMED | technical physical commit、raw 保留 | 按冻结规则显式重采 |
| final zero/stop 无法确认 | 已运动 | SAFETY_ABORT_LATCHED | serious candidate | 保留 |
| raw 构造/finalize 失败 | 已完成 | DISARMED 或 TECH_ABORT_DISARMED | orphan 保留 | 仅按 handoff 显式判定 |
| finalize 后 physical commit 失败 | 已完成 | DISARMED | immutable orphan；resume 幂等补 commit | 补 commit 前禁止重采 |

另需保证 control loop ≥50 Hz（目标 100 Hz）、绝对 monotonic deadline、raw 只送真实
MEASURE samples 给 `MeasurementPipeline`、ramp/settle 仅保留于 bag/trace、恒定
pre-R1 `model_input`、final zero 失败升级 safety latch、不吞 exception、不在 backend
自动 retry。

### 11.5 `emergency_stop(reason)`

必须可重入、无模型依赖、无磁盘依赖：立即调用 watchdog high-priority zero 和
批准的 bridge damping/safe-mode API，锁存 abort。普通 command API 在 latch
解除前全部拒绝。方法返回前不要求视频、posterior 或 rosbag flush 完成。

---

## 12. Trial state machine 必须补的事件

`TrialExecutor` 是 scientific trial state machine 的唯一 owner；
`Go2RosBackend` 不 import、不构造它。backend 只把带真实 monotonic
timestamp 的 `physical_phase_trace` 放入 raw metadata。executor 验证其严格为
`PRECHECK_PASSED,RAMP_REACHED,SETTLED,MEASUREMENT_COMPLETE,RAMPED_OUT`，
按此回放到 `VALIDATE`，然后才运行 `MeasurementPipeline` 和 model
decision。这样 backend 安全事件与 scientific lifecycle 都有单一 owner。

```python
def execute_scientific_trial(spec, *, update_enabled):
    prepared = None
    prepared_consumed = False
    physical = None
    backend_boundary_error = None
    try:
        prepared = backend.prepare_attempt(
            spec.identity, spec.context, spec.start_pose_gate, spec.attempt_planning
        )
        full_request, wire_request = build_bound_preflight_requests(spec, prepared)
        report = backend.preflight(full_request)
        require_report_ready_and_hash_bound(
            report, full_request, wire_request, prepared
        )
        authorization = operator_gate.authorize_attempt(
            spec.identity,
            report,
            scope_authorization=spec.scope_authorization,
            start_pose_gate=prepared.start_pose_gate_result,
        )
        attempt_gate_receipt = operator_gate.load_receipt(
            authorization.attempt_gate_receipt_sha256
        )
        require_equal(
            backend.watchdog.register_operator_gate_receipt(attempt_gate_receipt),
            authorization.attempt_gate_receipt_sha256,
        )
        lease = backend.arm(authorization, spec.identity)
        backend.bind_prepared_attempt(prepared, lease)
        prepared_consumed = True
        raw_hint = backend.execute_trial(spec.command, spec.policy)
        # backend 的成功返回不是第二个事实来源；只用它的 hash 查找并核验
        # journal 中唯一的 durable physical commit。
        physical = require_unique_physical_commit_from_journal(
            spec.identity,
            expected_event_sha256=raw_hint.metadata[
                "physical_commit_event_sha256"
            ],
        )
    except BaseException as error:
        backend_boundary_error = error
        attached = physical_commit_attached_to_exception_or_none(error)
        if attached is not None:
            physical = attached
        elif prepared is None:
            # durable PREPARED_ATTEMPT 前没有 attempt/scientific row。
            physical = physical_commit_attached_or_journal_or_none(
                error, spec.identity
            )
            if physical is None:
                raise
        elif not prepared_consumed:
            # 只有尚未交给 backend 执行的 prepared attempt 可被 abandon。
            terminal = classify_trial_pre_execution_failure(error)
            physical = backend.abandon_prepared_attempt(
                prepared,
                reason=terminal.reason,
                kind=terminal.kind,
                technical_failure_code=terminal.technical_failure_code,
            )
        else:
            # bind 之后 backend 已拥有 terminalization；executor 不得再 finalize。
            physical = require_unique_physical_commit_from_exception_or_journal(
                error, spec.identity
            )

    assert physical is not None
    physical, backend_boundary_error = recover_physical_commit_and_classify_pending_error(
        identity=physical.result.identity,
        candidate_commit=physical,
        pending_error=backend_boundary_error,
    )
    posterior_before = require_bound_posterior_before_ref(spec, physical)
    method_state_before = require_bound_method_state_ref(spec, physical)
    detached_method_state_candidate = build_detached_method_state_candidate(
        before=method_state_before,
        unit_type=spec.identity.unit_type,
        frozen_proposed_logical_command=spec.command,
        proposal_sha256=spec.proposal_sha256,
        next_schedule_cursor=spec.next_schedule_cursor,
    )
    planner_decision_candidate = canonical_planner_decision_or_none(spec)

    def build_trial_material_from_committed_raw():
        """Pure/deterministic with respect to journal, live model, and cursor."""
        local_sm = TrialStateMachine()  # 每次调用都是全新实例
        raw = load_and_verify_raw_from_physical_commit(physical)
        replay_and_verify_physical_trace(
            local_sm, raw.metadata["physical_phase_trace"]
        )
        observation = measurement_pipeline.process(raw)
        candidate_model = model.detached_clone_from_ref(posterior_before)
        if not observation.valid:
            local_sm.apply(RuntimeEvent.OBSERVATION_INVALID)
        elif update_enabled:
            local_sm.apply(RuntimeEvent.OBSERVATION_VALID)
            candidate_model.update(observation)
            local_sm.apply(RuntimeEvent.MODEL_UPDATED)
        else:
            local_sm.apply(RuntimeEvent.OBSERVATION_RECORDED_NO_UPDATE)
        if not local_sm.is_terminal:
            local_sm.apply(RuntimeEvent.STOP)
        return TrialScientificMaterial(
            observation=observation,
            detached_posterior=candidate_model,
            detached_method_state_candidate=detached_method_state_candidate,
            planner_decision_candidate=planner_decision_candidate,
            transition_trace=freeze_transition_trace(local_sm),
        )

    def build_terminal_trace_from_physical():
        local_sm = TrialStateMachine()  # resume/re-entry 不继承上次回放状态
        event = (
            RuntimeEvent.SAFETY_TRIGGER
            if physical.result.status == "safety_abort"
            else RuntimeEvent.ERROR
        )
        apply_abort_if_nonterminal(local_sm, event)
        return freeze_transition_trace(local_sm)

    # trial 的所有 scientific 结局只允许经过这一处共享 helper。
    tx = commit_scientific_from_physical(
        spec=spec,
        physical=physical,
        unit_artifact_kind=(
            "TRIAL_OBSERVATION"
            if physical.result.status == "complete"
            else "NONE"
        ),
        unit_artifact_builder=(
            build_trial_material_from_committed_raw
            if physical.result.status == "complete"
            else None
        ),
        terminal_transition_trace=(
            None
            if physical.result.status == "complete"
            else build_terminal_trace_from_physical()
        ),
        posterior_before=posterior_before,
        posterior_after=(
            None  # TRIAL_OBSERVATION 从 TrialScientificMaterial 取 detached candidate
            if physical.result.status == "complete"
            else posterior_before
        ),
        method_state_before=method_state_before,
        detached_method_state_candidate=detached_method_state_candidate,
        planner_decision_candidate=planner_decision_candidate,
        update_enabled=update_enabled,
        next_schedule_cursor=spec.next_schedule_cursor,
    )
    if backend_boundary_error is not None:
        append_non_scientific_runner_diagnostic(
            identity=physical.result.identity,
            physical_commit_sha256=physical.commit.event_sha256,
            error=backend_boundary_error,
        )
    if backend_boundary_error is not None or tx.scientific_stage_error is not None:
        raise DeferredPostCommitFault(
            tx, cause=tx.scientific_stage_error or backend_boundary_error
        )
    return require_trial_observation(tx)
```

`backend.execute_trial` 内发生的 abort 已自己产生 physical commit。executor 捕获
异常后先取 exception 携带的 commit，否则按 identity 查 journal；只有
`prepared_consumed=false` 且不存在 commit 时才可单次
`abandon_prepared_attempt`。随后必须再以 event hash 查 journal，证明恰有一条
hash-valid `ATTEMPT_PHYSICAL_COMMIT`。返回的 `raw_hint` 不得直接驱动科学结果；
observation 只从该 physical commit 锁定的 raw URI/hash 重建。
`classify_trial_pre_execution_failure` 的冻结优先级为 `SafetyFault`→safety、
`OperatorCancelled`→operator cancel、精确 handoff allowlist→technical，其余→
internal/`UNCLASSIFIED_INTERNAL_FAULT`；禁止将 unknown 映射成可重采故障。

trial、NAV 和 SHIFT physical-only executor 必须共用
`recover_physical_commit_and_classify_pending_error(identity,candidate_commit,
pending_error)`。它先按 identity/event hash读取 journal：若存在完整 hash-valid
`ATTEMPT_PHYSICAL_COMMIT`，返回该 commit，并把任何 `pending_error` 降为仅供
`NON_SCIENTIFIC_RUNNER_DIAGNOSTIC` 使用的 diagnostic；绝不把它传进 scientific helper。
只有 journal 尚无 physical commit 时，才依据 prepared ownership 状态执行一次
terminalize/abandon，随后再次调用本函数。commit 自己的 status/terminal/reason 是 physical
分类唯一来源；deterministic scientific builder/helper 的新错误才可能改变 effective
scientific result。三种 executor 共享 golden fault test：在 finalize/physical fsync/return
envelope 前后注入同一 exception，比较 uninterrupted 与 crash-resume 的 scientific result、
posterior/runtime-state/cursor bytes 必须完全相同；允许前者多一条 non-scientific diagnostic。

scientific result 的时间也必须 crash-stable。shared helper 首次接管某个
`(physical_commit_event_sha256,scientific_unit_id,attempt_uid)` 时先 append+fsync唯一
`SCIENTIFIC_RESULT_RESERVED{reservation_key,reserved_monotonic_ns,
physical_commit_event_sha256,unit_id,attempt_uid}`；
`ScientificUnitResult.committed_monotonic_ns` 精确取该 reserved value，不再调用
`clock.now_ns()`。resume先查 journal：已有 reservation逐字复用；没有时才分配；同 key多个
不同 event/value是 corruption。result file fsync后、scientific commit前恢复时按
reservation key扫描：0 个 candidate才重建，1 个 hash-valid candidate逐字复用，多个不同
bytes失败。checkpoint/side artifacts中任何 created/committed time同样只能来自已提交 physical
event、此 reservation或其原始 evidence，不得在 replay生成新时间。fault tests覆盖
reservation/result/commit每个写点并要求 uninterrupted/crash bytes/hash逐位相等。

`TrialScientificMaterial` 是内存中的 deterministic build plan，只包含 observation、
detached candidate posterior、`detached_method_state_candidate` 和 transition trace；其
builder 每次调用必须在函数内新建 `TrialStateMachine`，不得闭包捕获或
复用外层 mutable state machine。builder 不得写 journal、安装 live
posterior/cursor 或自行写 immutable artifact。`commit_scientific_from_physical` 是唯一
允许写 observation/posterior artifact、bag-range inventory、scientific result、
`SCIENTIFIC_UNIT_COMMIT`、checkpoint 与 `CHECKPOINT_COMMIT` 的 owner。builder 或任一写入
阶段抛错也由该 helper 在同一调用中分类与闭合，executor 不得开启第二个
scientific transaction。

`detached_method_state_candidate` 的 canonical 字段至少为
`planner_history,candidate_cursor,attempted_logical_commands,next_schedule_cursor`，并绑定
`method_state_before_sha256,scientific_unit_id,proposal_sha256`。它是基于 paired checkpoint
的纯内存候选，不是 live state。共享 helper 在已决定
`ScientificUnitResult.protocol_complete` 后才选择 before 或 candidate，冻结规则是：

- `nav_calibration` 且 `protocol_complete=true`：恰好一次 append 已冻结 proposal 到
  `planner_history/attempted_logical_commands`并前移 candidate/schedule cursor；即使 observation
  invalid 或结果为 protocol-complete safety abort 也必须消耗该 proposal；
  唯一例外是第 13.3.1 节 typed `ALL_CANDIDATES_REJECTED`：它没有 selected
  command，只记 rejection decision 并前移 selection cursor，不向
  `attempted_logical_commands` 伪造一条 command；
- `protocol_complete=false`：方法状态与 schedule cursor 都保持 before，RERUN_TECH
  必须从同一 before hash 重建字节相同的 `proposal_sha256`，禁止跳过、重抽或
  重复 append；
- `nav_validation`：无论观测是否 valid，`planner_history/candidate_cursor/
  attempted_logical_commands` 始终逐位等于 before；只有 protocol-complete 时才由
  checkpoint 前移 schedule cursor。

helper 必须把 method-state before/after artifact hash 写入 `SCIENTIFIC_UNIT_COMMIT`，再把
after 完整写入同一 checkpoint；最后一次 atomic install 同时替换 posterior、
planner history、candidate cursor、attempted commands 和 schedule cursor。其中任一部分不得
在 paired `CHECKPOINT_COMMIT` fsync 前对下一 unit 可见。

adaptive safe selection 与 typed `ALL_CANDIDATES_REJECTED` 都必须产生 canonical
`PlannerDecisionArtifact`，至少包含
`outcome,scientific_unit_id,runtime_state_before_kind{NAV_METHOD|SHIFT_SEQUENCE},
runtime_state_before_sha256,proposal_sha256|null,safety_state_sha256,
safety_cut_monotonic_ns,equivalent_motion_s,
rows[{pool_index,rank,score,information_gain,cost,history_disallowed,
safety_accepted,safety_reason_codes,selected}]`。`planner_decision_candidate` 只是该
artifact 的内存 preimage；共享 helper 写出 immutable artifact 后产生
`planner_decision_ref{path,sha256}`，并将这两列同时写入
`ScientificUnitResult`、`SCIENTIFIC_UNIT_COMMIT` 和 checkpoint 顶层。NAV/SHIFT 分别绑定
适用的 before-state hash，另一类 state 为 null。只有 `protocol_complete=true` 时，helper
才把该 ref/decision摘要追加进适用 runtime-state after 的 planner history；
`protocol_complete=false` 时 runtime-state after逐位等于 before，但顶层 ref仍保留本 attempt
实际使用的 diagnostics，不能反向污染 history。
固定 CSV command 方法两列均为 null。`unit_artifact_kind=NONE` 不得令
planner decision ref 为 null：全候选拒绝时依然必须用该 ref 证明 diagnostics；
exporter 的 `planner_candidates` 只能从 commit 绑定的 ref 展开。

trial/context-return 的无 observation safety/technical/pre-measure/operator/internal 结果，
以及 NAV 无法确定性复算 metrics 的 technical/pre-measure/operator/internal 结果，使用
`unit_artifact_kind=NONE`、observation hash 为 null、posterior before/after相同、
`model_update_applied=false`。NAV 的 SUCCESS/TIMEOUT/COLLISION/其他 protocol-complete
algorithm safety 必须使用 `NAV_EPISODE_METRICS`，即使 outcome失败也不能降成 NONE。
因此每个已存在 `ATTEMPT_PHYSICAL_COMMIT` 的 attempt
最终必须有且只有一个匹配 scientific commit；没有 observation 也不得跳过
per-unit bag-range inventory 与 checkpoint 可恢复边界。

P8 不得定义或导入 `commit_scientific_outcome_without_observation`；无 observation
路径必须直接调用同一 `commit_scientific_from_physical`，使用
`unit_artifact_kind="NONE",unit_artifact_builder=None`，并传入与普通路径相同的
method/SHIFT detached-state candidate 和 checkpoint cursor。禁止为它保留第二个
scientific writer。

helper 先保留 immutable
`physical_status/physical_terminal_reason`，再决定 scientific effective
`status/terminal_reason/technical_failure_code`：physical 自身已经 abort/timeout 时沿用
其分类。`commit_scientific_from_physical` 不接受任意 caller exception 或
`initial_scientific_failure` 参数；一旦发现 hash-valid physical commit，backend
return/transport/exception-envelope 错误只写
`NON_SCIENTIFIC_RUNNER_DIAGNOSTIC{physical_commit_sha256,error_type,message_sha256}`，不得参与
effective result。physical 为 complete、但 helper 内部从 committed raw 确定性重建时在
measurement、observation/artifact/inventory 或
scientific pre-commit 阶段出现 typed §14.2 integrity/storage technical fault 时，effective
status 改为 `technical_abort/exact_code,protocol_complete=false,retry_permitted=true`；
OperatorCancelled 在 physical complete 后不能取消既成事实，executor继续 deterministic
commit，不接受该 cancel；未知 exception 写
`technical_abort/UNCLASSIFIED_INTERNAL_FAULT,technical_failure_code=null,
protocol_complete=false,retry_permitted=false` 并暂停 internal review。live posterior始终
未安装，before/after相同。attempt ledger 的 `status/terminal_reason` 来自 scientific
effective 字段，另导出 physical 两字段；绝不能篡改原 ATTEMPT_PHYSICAL_COMMIT。

如果错误发生在 `SCIENTIFIC_UNIT_COMMIT` fsync 成功但 return 前，resume 先按 event hash
查找；存在就只补 checkpoint，不能用随后抛出的 storage exception另造 technical result。
measurement.process、observation write、planner-decision write、posterior/method-state candidate write、inventory snapshot、
scientific artifact write 和 journal fsync 的 fault tests 必须分别覆盖 exact technical 与
unknown internal，并验证 selection/quota/cursor。
另加架构测试：将底层 scientific artifact/journal writer 设为抛错的禁用端口，
只给 `commit_scientific_from_physical` 注入真实 writer，并断言 trial、NAV 和 SHIFT
的每次未中断 executor invocation 只调用该 helper 一次、每类 commit 最终恰一条；
crash resume 允许以同一 idempotency key 重入 helper，但不得新建事务。禁止
executor/runner 直接引用 `write_immutable_scientific_result`、
`scientific_unit_commit_event` 或 `checkpoint_commit_event`。

trial 与 NAV 必须共用 `commit_scientific_from_physical`，不得各写一套错误语义。该 helper
以 `physical.commit.event_sha256` 为 idempotency key，按下列状态机实现：

```text
LOOKUP_EXISTING_SCIENTIFIC_COMMIT
  → BUILD_OR_VALIDATE_UNIT_ARTIFACT
  → WRITE_OR_VALIDATE_PLANNER_DECISION
  → WRITE_OR_VALIDATE_POSTERIOR_AND_RUNTIME_STATE
  → WRITE_BAG_RANGE_INVENTORY
  → WRITE_IMMUTABLE_SCIENTIFIC_RESULT
  → SCIENTIFIC_UNIT_COMMIT
  → WRITE_CHECKPOINT
  → CHECKPOINT_COMMIT
  → INSTALL_POSTERIOR_RUNTIME_STATE_AND_CURSOR
```

每步先查 hash-valid既有产物：同 key/同 bytes 幂等，不同 bytes integrity failure。
physical 的 technical/pre-measure/operator/internal 结果令 artifact kind=NONE；普通 trial
complete 构造 TRIAL_OBSERVATION，NAV success/timeout/collision/其他 protocol-complete safety
构造 NAV_EPISODE_METRICS。artifact builder/write/inventory/scientific commit 前的 typed
technical error生成第 12 节 effective technical ScientificUnitResult；unknown 生成 internal
pause；两者都令 posterior before=after。若 storage/journal 当前不可写，helper 抛
`ScientificCommitPending(physical_commit_sha256,classified_failure)`，普通 runner 立即停止；
resume 只重入本 helper，禁止机器人再次运动，并在 storage恢复后写同一 classified result。
调用参数中的 `unit_artifact_kind` 是无故障路径的 expected kind；若 physical 或
scientific failure 使 effective result 无 observation，helper 必须在内部将 effective kind
冻结为 `NONE`，不得以传入的 `TRIAL_OBSERVATION` 伪造 artifact。

若 `SCIENTIFIC_UNIT_COMMIT` 已经 fsync 但调用返回前抛错，LOOKUP 必须找到它并忽略随后
exception classification，只补 checkpoint。COLLISION/safety 永不能被 secondary
storage/unknown error改写成可重采技术故障。helper 返回
`ScientificTransaction{scientific,unit_artifact_ref|None,planner_decision_ref|None,inventory_ref,
posterior_before_ref,posterior_after_ref,method_state_before_ref,method_state_after_ref,
shift_state_before_ref,shift_state_after_ref,pre_checkpoint_event_refs,
scientific_commit,checkpoint_commit,scientific_stage_error}`；只有最后 install 后 caller才可
抛 `DeferredPostCommitFault` 或退出。
checkpoint cursor 的规则唯一：`protocol_complete=true` 才写
`next_schedule_cursor=spec.next_schedule_cursor`；technical/pre-measure incomplete 必须保持
`current_scientific_unit_id` 并进入 `AWAIT_EXPLICIT_RERUN_TECH`，operator cancellation
保持当前 unit 并进入 `PAUSED_OPERATOR_DECISION`。普通 runner 不得看到 checkpoint 后
自动跳到下一 unit；retry CLI 完成同 unit 的 protocol-complete attempt 后才前移。
`state_machine_trace.csv` 同样以 durable boundary 为准：共享 helper 只从已核验
`PhysicalAttemptCommit.result.identity` 导出 attempt-bound transition。prepare 在 boundary 前
失败时，其 RunLevelEvent 已由第 11.3.1 节保存，executor 不调用 scientific
helper、不创建 trace row、不得伪造 attempt UID。

两阶段的权威边界是：

```text
ATTEMPT_PHYSICAL_COMMIT
  → deterministic observation / detached posterior + NAV method-state or SHIFT state candidate
  → immutable SCIENTIFIC_UNIT_COMMIT
  → immutable checkpoint + CHECKPOINT_COMMIT
  → atomic install live posterior/runtime-state/cursor
```

任何模型更新都先发生在从 `posterior_before_sha256` 克隆出的 detached model；
planner history/candidate cursor/attempted commands 同样只从 `method_state_before_sha256`
构造 detached candidate；SHIFT detector/alarm/deque/reference/history/cursor 只从
`shift_state_before_sha256` 构造 detached candidate。live posterior 和适用的 runtime state
在 `SCIENTIFIC_UNIT_COMMIT` 与其配对 `CHECKPOINT_COMMIT` 都 fsync 前保持不变。crash 在
physical 与 scientific commit 之间时，resume 从 physical raw、冻结 config/source 和
`posterior_before_sha256 + method_state_before_sha256|shift_state_before_sha256 +
proposal_sha256` 确定性重跑
observation/update，禁止再次让机器人运动；crash 在
scientific 与 checkpoint commit 之间时只重建相同 checkpoint；crash 在 checkpoint 与
live swap 之间时从 checkpoint 同时安装已绑定的 posterior/runtime state/cursor。
所有 helper 以 physical/
scientific commit hash 为 idempotency key，同 key 不同内容立即判 corruption。
故障注入必须覆盖 method/SHIFT-state artifact write、scientific fsync、checkpoint fsync 以及
atomic install 前/后，并断言不会出现 posterior 已更新但 history/cursor 未更新的
torn state；未中断与每个 crash-resume 结果的所有上述 hash/序列必须逐位一致。

ledger/exporter 的 scientific outcome、protocol completeness、retry eligibility、model
version 和 primary-vs-rerun selection 只读 `SCIENTIFIC_UNIT_COMMIT`；
`ATTEMPT_PHYSICAL_COMMIT` 只证明运动与 raw 已固定，不能作为论文行或模型已更新的证据。

现有 `TrialStateMachine` 会把所有 valid observation 强制送入 `UPDATE`，无法如实
表示 validation、monitor、frozen 和 post-recovery no-update。修改
`src/calibagent/core/runtime/state_machine.py`：

```python
RuntimeEvent.OBSERVATION_RECORDED_NO_UPDATE

(TrialPhase.VALIDATE, OBSERVATION_RECORDED_NO_UPDATE) -> TrialPhase.DECIDE
```

使用规则：

- valid calibration 且 method 允许 update：`OBSERVATION_VALID → UPDATE`；
- held-out validation、monitor、frozen、post-recovery-monitor：
  `OBSERVATION_RECORDED_NO_UPDATE → DECIDE`；
- invalid observation：保留现有 fail-closed ABORT，不再发送 `STOP`；仍写
  protocol-complete invalid `SCIENTIFIC_UNIT_COMMIT`，posterior before/after 相同；
- 禁止为了走通状态机伪记 `MODEL_UPDATED`。

增加 enum/transition 不改变旧事件语义，并补单元测试。NAV episode 另建 P8 内部
状态机：

```text
PRECHECK → STABILIZE → NAVIGATE → ZERO_CONFIRM
         → SUCCESS | COLLISION | TIMEOUT | SAFETY_ABORT | TECH_ABORT
```

每个 episode 恰有一个终止原因。

---

## 13. Model/method factory

### 13.1 相同 prior 的构造

`model_factory.py` 应统一实现 NAV 和 SHIFT model 初始化：

1. 从 config 指定的 tracked NAV 或 SHIFT `feature_reference_pool.csv` 读取命令并
   验证 hash；两个协议不得隐式共用路径；
2. `BasisTransformer(feature_set, hinge_thresholds).fit(reference_commands)`；
3. `basis = transformer.transform(reference_commands)`；
4. 断言 basis 满列秩且 `cond_2(basis)` 不超过 config 上限；
5. identity prior：
   `prior_mean = lstsq(basis, reference_commands * prior_gain[None, :]).T`；
6. 用冻结 `prior_scale` 和 `noise_variance_vx_vy_wz` 创建新
   `BayesianBasisModel`；
7. model、prediction、snapshot 和 manifest 的 identity 都写
   `basis_blr/<feature_set>`，不得只在 manifest 改名而让
   `PredictiveDistribution/snapshot` 仍写 `M2_basis_blr`。S6 以向后兼容方式给
   `BayesianBasisModel.__init__` 增 optional `model_id`（默认仍为现有
   `M2_basis_blr`，保证 P0–P7 不变），并在 save/load 中持久化；P8 factory 显式传
   `basis_blr/m1_affine` 或 `basis_blr/m2_affine_cross_hinge`；
8. `initialize(PriorState(mean=prior_mean))`；
9. 保存 `posterior_v0000.npz` 和 hash。

每个 `block × method` 或 `shift × block × method` 都调用一次；禁止 shallow copy
共享 `_precision/_eta/history/detector/planner`。

### 13.1.1 每个 method/sequence 的初始化事务

fresh Python object 不能作为首个 unit 的 before ref。每个全新 NAV `block×method` 和 SHIFT
`shift×block×method` 在 scope authorization前必须执行唯一
`initialize_runtime_state_transaction(runtime_identity)`：

```text
write+fsync posterior_v0000 candidate
→ write+fsync applicable initial runtime-state artifact
→ write+fsync RUNTIME_STATE_INITIALIZATION result
→ append+fsync RUNTIME_STATE_INITIALIZED_COMMIT
→ write+fsync checkpoint(kind=RUNTIME_STATE_INITIALIZED)
→ append+fsync CHECKPOINT_COMMIT
→ atomic install posterior/runtime-state/current cursor
```

`runtime_identity={dataset_role,run_id,session_id,block_id,shift_id,method_id}`；NAV initial
method state含 empty planner history/attempted commands、frozen candidate cursor、该方法首
planned unit cursor和 transformer hash；SHIFT initial state含 empty history、fresh detector
CUSUM/latch/index、alarm=false、empty rolling slots、recovered_at=null、nominal reference=null、
nominal actuator state和 A_CALIBRATION row 1 cursor。两者均引用相同事务内的 v0000 path/hash/
version 0；不共享其他 method/sequence 的 artifact。

initialization result 至少含
`runtime_identity,posterior_after_path/hash/version=0,runtime_state_kind,
runtime_state_after_path/hash,next_scientific_unit_id,transformer_sha256,
source/config/schedule hashes`。result 先以 canonical JSON 写入 content-addressed path并
fsync；`RUNTIME_STATE_INITIALIZED_COMMIT` 必须含
`runtime_identity,initialization_result_path,initialization_result_sha256,
posterior_after_path,posterior_after_sha256,posterior_after_version=0,
runtime_state_after_path,runtime_state_after_sha256,next_scientific_unit_id,
source_commit,config_sha256,schedule_sha256`。commit 必须逐字段重算并绑定 result，不能只
引用其中 posterior。没有 physical/scientific unit：posterior/state before、
planner decision、observation、physical/scientific commit、bag inventory、changeover refs全 null；
`posterior_transition_kind=INITIAL,factor=null`。INIT checkpoint要求
`initialization_commit_sha256` non-null，scientific/changeover commit refs null，并把适用
method-state或shift-state after ref设为 required，另一组 null。

事务幂等 key 是完整 runtime identity。crash留下的 candidate文件只能按 canonical bytes复用
或标 orphan；已有 init commit只补同一 checkpoint，已有 checkpoint只 install，绝不能生成
第二个 v0000或重置当前已开始的 state。首个 `ScopeAuthorizationRequest` 的 eligibility
checkpoint/tail和首个 `PreparedAttempt/PhysicalAttemptCommit` 的 posterior/runtime-state
before ref都必须等于这份 INIT checkpoint 的 after refs。后续 method/sequence各自再执行新
INIT，不能拿 run-level `RUN_INITIALIZED` 或前一 method终态冒充。

checkpoint schema的 kind枚举因此精确为
`RUNTIME_STATE_INITIALIZED|SCIENTIFIC|CHANGEOVER`；三分支 required/null互斥。fault tests在
posterior、state、init result、init commit、checkpoint、checkpoint commit、live install
前后逐点 crash，验证 uninterrupted parity、global checkpoint sequence连续且任何 scope
都不存在 unbound before ref。

### 13.2 NAV 八方法

| Method | Calibration | 在线行为 |
|---|---:|---|
| `B0_raw` | 0 | posterior version 永远 0；NAV 不 inverse/feedback |
| `B1_dense` | 30 | 顺序执行 `commands/nav/dense_design.csv` |
| `B2_lhs` | 12 | 顺序执行 `commands/nav/lhs_design.csv` |
| `B3_sobol` | 12 | 顺序执行 `commands/nav/sobol_design.csv` |
| `B4_d_opt` | 12 | 每步从同一 pool 调 `DOptimalPlanner.propose` |
| `B5_active_no_task` | 12 | 前 6 个 `active_seed.csv`，后 6 个 IVR；对 `candidate_pool.csv` 全部行按文件顺序严格等权 `1/N` |
| `B6_random` | 12 | 顺序执行预生成 `commands/nav/random_design.csv`，runtime 不调用 RNG |
| `B8_full` | 12 | 前 6 个相同 `active_seed.csv`，后 6 个 task-weighted IVR，使用两图冻结 deployment task distribution |

B2/B3/B6 CSV 必须在 release 构建阶段生成、review、hash；现场不重新抽样。
B4/B5/B8 每次 propose 后使用共享 `rank_and_select_first_safe`
adapter。它从 planner diagnostics 取全 pool 的 score/information/cost，以
`(-score, pool_index)` stable sort，在同一 state/history 上对每行调 safety，
导出 `pool_index,rank,score,information_gain,cost,history_disallowed,
safety_accepted,safety_reason_codes,selected`，然后只执行第一个 accepted
row。当前 `last_diagnostics` 本身没有 safety 列，所以 S6 必须实现这个
adapter，不得把 `.propose(k=1)` 的 top-1 拒绝后直接失败。全部候选
均拒绝时才产生 algorithm safety abort。

### 13.3 invalid observation 与预算

每个 scientific trial ID 只消费一个 protocol-complete outcome：

- 预定义 technical failure 可用相同 trial ID、新 attempt ID 重采；
- algorithmic safety abort/invalid measurement 是有效结果，不更新 model，但消耗
  该 trial budget；
- history 仍记录已尝试的 logical command，避免 active planner 因无 update 重选；
- 不因 invalid 自动增加第 13 个 active trial。

### 13.3.1 全候选拒绝也必须跨可审计边界

`rank_and_select_first_safe` 不以 exception 表示“全候选拒绝”，而返回 typed
`PlanningDecision(outcome="ALL_CANDIDATES_REJECTED", diagnostics=<all rows>,
selected_command=None)`。在该 decision 产生时禁止修改 live history/cursor；NAV/SHIFT
runner 仍先完成对应 planned unit 的 start-pose/context-return gate，然后调用唯一专用事务：

该 outcome 只属于 `planning_kind=ADAPTIVE_ALL_REJECTED`。安全选出命令的普通 adaptive
attempt 使用 `ADAPTIVE_SAFE_SELECTION`。`FIXED_TRIAL` 的单一冻结命令若 fresh
CommandPreauthorization 拒绝，不伪装成“全 pool 拒绝”、不创建 planner decision，也不进入
本事务：在 PREPARED 前 append+fsync run-level
`FIXED_COMMAND_PREAUTHORIZATION_REJECTED{unit_id,proposal_sha256,safety_state_sha256,
reason_codes}`，保持 unit pending、zero/latch并退出 4；若原因证明冻结 command/config 永久
不合法则 release/config gate退出 2。修复瞬时状态并完成显式 safety reset 后才可重新
materialize同一 PRIMARY unit；由于没有 attempt/raw outcome，不形成选择偏差。

```python
def execute_algorithm_safety_rejection(
    spec: ShiftTrialSpec | NavTrialSpec,
    *,
    shift_hook: ShiftRejectionHook | None = None,
):
    require_equal(spec.planning.planning_kind, "ADAPTIVE_ALL_REJECTED")
    # physical-only executor 负责 prepare 的全部 crash/envelope 语义。
    physical = execute_trial_physical_only(
        spec,
        execution_directive=NoArmSafetyFinalize(
            reason="ALGORITHM_SAFETY_ABORT",
            candidate_diagnostics=spec.planning_decision.diagnostics,
        ),
    )
    # directive 在 PREPARED_ATTEMPT fsync 后立即调用且只调用一次
    # abandon_prepared_attempt(kind="safety")；从不 preflight/arm/publish nonzero。
    nav_method_state_before = (
        require_bound_method_state_ref(spec, physical)
        if shift_hook is None else None
    )
    shift_state_before = (
        require_bound_detached_shift_state(spec, physical)
        if shift_hook is not None else None
    )
    shift_state_candidate = (
        shift_hook(
            prior=shift_state_before,
            spec=spec,
            rejection_decision=spec.planning_decision,
        ) if shift_hook is not None else None
    )
    tx = commit_scientific_from_physical(
        spec=spec,
        physical=physical,
        unit_artifact_kind="NONE",
        unit_artifact_builder=None,
        posterior_before=spec.posterior_before_ref,
        posterior_after=spec.posterior_before_ref,
        update_enabled=False,
        planner_decision_candidate=spec.planning_decision,
        method_state_before=nav_method_state_before,
        shift_state_before=shift_state_before,
        detached_method_state_candidate=(
            method_state_after_protocol_complete_planning_rejection(
                spec, nav_method_state_before
            ) if shift_hook is None else None
        ),
        detached_shift_state_candidate=shift_state_candidate,
        next_schedule_cursor=spec.next_schedule_cursor,
    )
    return ProtocolCompleteSafetyOutcome.from_transaction(tx)
```

directive 若在 durable `PREPARED_ATTEMPT` 前失败，只写 run-level preparation event，planned
unit 保持 pending；一旦 boundary 已 fsync，就必须以同 attempt UID 产生且只产生一个
`ATTEMPT_PHYSICAL_COMMIT(status=safety_abort,terminal_reason=ALGORITHM_SAFETY_ABORT,
measurement_constructed=false)`，zero/latch，随后完成 protocol-complete scientific/
checkpoint并消耗该 unit。已有 attached/journal physical commit 时绝不再次 abandon。
candidate diagnostics 作为 scientific result 的 immutable side reference保存，即使
`unit_artifact_kind=NONE` 也不能丢；NAV detached method state 记录 rejection decision并
前移本 planned selection cursor，但 `attempted_logical_commands` 不追加不存在的 command。
SHIFT active recovery 同理记录 planner decision/history、保持 posterior不变并由
`recovery_rejection_hook` 前移当前 recovery row。完成 paired checkpoint 后 top-level 统一
exit 4；下一次 resume 必须先走双人 safety reset，且从下一 pending unit继续。

NAV B4/B5/B8 和 SHIFT active recovery 必须共享该函数。测试覆盖所有候选被拒、prepare
boundary 前后 crash、abandon physical fsync 前后 crash、scientific/checkpoint/install 前后
crash；断言 nonzero packet count=0、finalize=1、latch=true、unit 恰消耗一次、diagnostics
全保留、posterior不变、history/cursor按上述规则只安装一次。

### 13.4 held-out 隔离

每个 validation command：先保存 posterior version/hash，predict，执行，process，
写 residual，再断言 posterior version/hash 未变。validation command 不得进入
transformer fit、model update、candidate history、stopping threshold 调参或 task
weight 学习。

---

## 14. 冻结 schedule 与 resume identity

### 14.1 NAV method 顺序

`schedule.py` 实现 even-n Williams/near-balanced Latin 生成器。CONFIRM 使用 30 rows，
DEV 使用独立 seed 的 5 rows；DEV 不是 CONFIRM 前五行。两种 role 的 validator 均要求：

- CONFIRM 每种 method 在每个位置出现 3 或 4 次；DEV 为 0 或 1 次；
- 任意 method 的位置总失衡 ≤1；
- 56 种非对角 ordered predecessor pair 在该 role 全部 blocks 的相邻位置中出现
  次数之差 ≤1；
- row/label permutation 只由冻结 `schedule_seed` 决定；
- schedule CSV 在采集前生成，runner 不现场随机；
- block 与 day/battery/robot 的交叉分布写入 audit report。

### 14.2 两地图顺序

对每个 method，CONFIRM 30 blocks 中 `AB`、`BA` 精确各 15 次；DEV 5 blocks 中
两种顺序精确为 3/2 或 2/3，且 8 methods 间哪一种多出现的计数差≤1，其中：

```text
A = real_offset_slalom
B = real_weighted_arc
```

map order 写进 schedule CSV，不能由 operator 临时选择。两图是同一个 block 内
重复测量，paired bootstrap 以完整 block 重采样，不能将它们池化成 `n=60`。
validator 还要求 `map_order × method_position` 及
`method_position × date_slot` 的可行 cell 计数最大差 ≤1，并将完整
contingency table 写入 randomization audit，不只检查边际频数。

### 14.3 SHIFT method 顺序

每个 shift 独立生成 role-matched near-balanced 三方法 schedule：CONFIRM 20 rows、
DEV 5 rows。CONFIRM 每种方法在每个位置出现 6 或 7 次，DEV 出现 1 或 2 次；
最大失衡 1，6 种 ordered predecessor pair 的出现
次数差 ≤1。四个 shift 的 block ID namespace 独立。

另生成 `shift_date_order.csv`，使用 4-shift Williams order 分配冻结
`date_slot`；每个 shift 在各 date slot/日内 ordinal position 的可行计数差
≤1，shift ordered predecessor 计数差 ≤1。如实际可用 date slots 无法满足，
freeze 失败并要求先调整日程，不得现场自由选 shift。

### 14.4 schedule CSV 必需字段

`nav_block_schedule.csv` 与 `shift_block_schedule.csv` 每行对应一个
`block × method`，字段精确为：

```text
dataset_role,run_id,block_id,shift_id,robot_id,date_slot,method_position,
method_id,map_order,planned_unit_ids,conditional_sentinel_unit_ids,
conditional_context_return_unit_ids,planned_changeover_unit_ids,
conditional_changeover_recovery_unit_ids,schedule_seed
```

`planned_unit_ids` 必须展开到具体 trial/validation/episode/sequence 单元，使 runner
只能引用冻结 ID，不能接受任意速度或 waypoint。
NAV 行的 `conditional_sentinel_unit_ids=[]`。每个 SHIFT `block × method` 行的
`planned_unit_ids` 必须包含该 sequence 的全部 45 个 primary ID，再加初始
`verification_set_id=1` 的两个 sentinel ID，共 47 个；其中 planned sentinel 只包含
set 1，因此 480 的 planned sentinel 计数不变。`conditional_sentinel_unit_ids` 必须在 CONFIRM 前展开
`verification_set_id=2..maximum_verification_sets` 的每对稳定 ID。runner 只能在
紧邻前一整 set `set_passed=false`、context 修复并再次通过 preflight 后，
按顺序解锁下一对 conditional IDs；禁止运行时自创 ID或跳 set。

`conditional_context_return_unit_ids` 必须按每个 method scope 冻结的
`maximum_context_returns` 预展开为
`AUX/{run}/{block}/{method}/{shift_or_NOT_APPLICABLE}/CONTEXT_RETURN/{return_id:04d}`。
start-pose gate 超差时，runner
在 journal 事务内领取该 scope 最小未使用 ID；只有前一 return 已 terminal 且 pose
仍超差才能领取下一 ID，超过上限立即停止 session。技术重采保持该 AUX unit ID；
runtime 绝不能拼接新 ID。AUX 不进入 planned primary/sentinel 数量。
其中 NAV 固定写字面量 `NOT_APPLICABLE`，SHIFT 写该 row 的四类 shift ID；因此不同
block/shift/method 的 registry namespace 不重叠。
领取事务必须 append+fsync
`CONDITIONAL_UNIT_ACTIVATED{registry_sha256,triggering_scientific_unit_id,
registry_root_planned_unit_id,conditional_unit_id,ordinal,
previous_journal_event_sha256}` 后才可 prepare；相同 direct trigger+conditional ID+ordinal
重放幂等，不同 ID 直接判 corruption。resume 只由 hash-valid activation event 重建游标。

SHIFT 行的 `planned_changeover_unit_ids` 精确含 APPLY/RESTORE 两个 unit；NAV 写 `[]`。
`conditional_changeover_recovery_unit_ids` 按第 16.6 节及冻结
`maximum_changeover_attempts` 预展开；NAV 写 `[]`。NAV 的 sentinel/changeover 数组
写 `[]`，SHIFT/NAV 都必须有 context-return registry。

`shift_date_order.csv` 是独立 schema：

```text
dataset_role,run_id,date_slot,date_id,in_day_ordinal,shift_id,schedule_seed
```

schedule 旁的 `schedule_manifest.json` 顶层固定为：

```text
schema_version="p8.schedule-manifest.v1",
dataset_role,run_id,protocol_version,
nav_config_template_sha256,shift_config_template_sha256,
generator_source_sha256,
entries=[
  {schedule_id,schedule_path,schedule_sha256,generator_version,schedule_seed,
   expected_rows,planned_primary_units,planned_sentinel_units,
   maximum_conditional_sentinel_units,maximum_conditional_context_return_units,
   planned_changeover_units,maximum_conditional_changeover_recovery_units}
]
```

`dataset_role/run_id/protocol_version` 必须与两份 template 相同；
`nav_config_template_sha256/shift_config_template_sha256` 是两份 tracked template 的 raw
SHA-256，`generator_source_sha256` 是冻结 schedule generator source bytes hash。这三个
hash 不引用未来 materialized config，因而无循环。顶层和 entries item 均
`additionalProperties=false`，manifest 不含 self-hash；其 raw hash 由 stage/release config绑定。
`schedule_id` 恰为 `nav_block_schedule|shift_block_schedule|shift_date_order`，三者各一条、
path 各不相同、raw-byte hash 必须匹配；date-order 不适用的 unit count 全写 0。manifest
不在被 hash 的 CSV 内。所有 array 列都是无空格 canonical JSON array string，按 protocol
execution order 排序；不使用未定义分隔符。

manifest/schema 必须由 `dataset_role` 决定 exact cardinality，而不是只检查正整数。
DEV entries 固定为 NAV `expected_rows=5×8=40,planned_primary_units=910`（其中 830
trial + 80 episode），SHIFT block schedule
`expected_rows=4×5×3=60,planned_primary_units=2700,planned_sentinel_units=120,
planned_changeover_units=120`；CONFIRM 分别保持 NAV `240/5460` 和 SHIFT
`240/10800/480/480`。`shift_date_order` 的不适用 unit counts 始终为 0。

除 handoff `block_schedule_executed.schedule_sha256` 明确按 `schedule_id` 取某一 source
CSV hash 外，全文单数 `schedule_sha256`（config、preflight、scope authorization、journal）
一律指 `schedule_manifest.json` 的 raw-byte SHA-256。`schedule_manifest.sha256` 是该外层
值，不是 entries 中任一值，也不写回 manifest 自身。

---

## 15. P8-NAV runner

### 15.1 block 主流程

`nav_runner.py` 的执行语义：

```python
for method_id in durable_pending_methods(
    schedule.method_order(block_id), checkpoint_store.current()
):
    method_state = resume_manager.open_nav_method(block_id, method_id)
    if method_state.is_new:
        require_robot_nominal_and_at_calibration_start()
        model, method = method_factory.fresh(method_id)
        assert model.posterior_version == 0
        init_tx = initialize_runtime_state_transaction(
            nav_runtime_identity(run_id, session_id, block_id, method_id),
            posterior_candidate=model,
            runtime_state_candidate=method.initial_state_for_schedule(schedule),
        )
        method_state = resume_manager.open_nav_method_from_init_checkpoint(init_tx)
    else:
        model, method = method_factory.restore_exact(
            method_id=method_id,
            posterior_ref=method_state.posterior_ref,
            transformer_sha256=method_state.transformer_sha256,
            planner_history=method_state.planner_history,
            candidate_cursor=method_state.candidate_cursor,
            attempted_logical_commands=method_state.attempted_logical_commands,
        )
        require_hash_equal(model, method_state.posterior_ref.sha256)

    allowed_unit_ids = tuple(method_state.pending_planned_motion_unit_ids)
    scope_id = (
        f"{run_id}/{session_id}/NOT_APPLICABLE/{block_id}/{method_id}"
    )
    purpose, parent_hash = scope_purpose_for_method_open(method_state)
    scope_request = ScopeAuthorizationRequest(
        scope_authorization_id=next_persisted_scope_instance_id(scope_id),
        authorization_purpose=purpose,  # PRIMARY_BATCH 或 RESUME_RENEWAL
        cli_arm_requested=cli_arm_requested,
        run_id=run_id,
        session_id=session_id,
        shift_id="NOT_APPLICABLE",
        scope_id=scope_id,
        parent_scope_authorization_sha256=parent_hash,
        lineage_root_scope_authorization_sha256=method_state.lineage_root_scope_sha256,
        retry_request_uuid=None,
        activation_event_sha256=None,
        eligibility_checkpoint_sha256=method_state.checkpoint_sha256,
        eligibility_journal_tail_sha256=method_state.journal_tail_sha256,
        allowed_scientific_unit_ids=allowed_unit_ids,
        source_commit=release.source_commit,
        config_sha256=resolved_config.sha256,
        schedule_sha256=schedule_manifest.sha256,
        issued_monotonic_ns=clock.now_ns(),
        expires_monotonic_ns=scope_expiry_from_config(clock, resolved_config),
        maximum_attempts=len(allowed_unit_ids),
    )
    scope_authorization = operator_gate.authorize_scope(scope_request)
    scope_gate_receipt = operator_gate.load_receipt(
        scope_authorization.operator_gate_receipt_sha256
    )
    require_equal(
        watchdog.register_operator_gate_receipt(scope_gate_receipt),
        scope_authorization.operator_gate_receipt_sha256,
    )
    require_equal(
        watchdog.register_scope_authorization(scope_authorization),
        detached_sha256(scope_authorization),
    )

    while live_cursor.method_id == method_id and not live_cursor.method_complete:
        # 第一次只读 cursor/identity/pose role；此时禁止 propose 或 safety rank。
        unit_stub = materialize_current_nav_unit_identity_from_cursor(
            live_cursor, schedule
        )
        pose_role = (
            "map" if unit_stub.identity.unit_type == "nav_episode"
            else "calibration"
        )
        gate_map_id = (
            unit_stub.identity.map_id if pose_role == "map" else "NOT_APPLICABLE"
        )
        start_pose_gate = ensure_start_pose_or_context_return(
            unit_stub.identity, pose_role=pose_role, map_id=gate_map_id
        )
        # 回位结束后才取得同一 boot 的 fresh RichRobotState safety cut。
        safety_snapshot = capture_frozen_preauthorization_snapshot(
            start_pose_gate=start_pose_gate,
            maximum_age_ms=config.calibration_start_gate.maximum_start_pose_gate_age_ms,
        )
        spec = materialize_current_nav_unit_from_cursor(
            unit_stub=unit_stub,
            live_cursor=live_cursor,
            schedule=schedule,
            model=model,
            method=method,
            start_pose_gate=start_pose_gate,
            safety_snapshot=safety_snapshot,
        ).with_scope_authorization(scope_authorization)
        assert spec.identity.scientific_unit_id == live_cursor.current_unit_id
        if spec.planning_outcome == "ALL_CANDIDATES_REJECTED":
            assert spec.identity.unit_type in {"nav_calibration", "nav_validation"}
            outcome = execute_algorithm_safety_rejection(spec)
            # outcome 已完成 physical/scientific/checkpoint/install；unit 已消耗。
            raise PostCommitSafetyStop(outcome.scientific_commit_sha256)
        elif spec.identity.unit_type == "nav_calibration":
            execute_scientific_trial(spec, update_enabled=spec.update_enabled)
        elif spec.identity.unit_type == "nav_validation":
            frozen_hash = posterior_hash()
            execute_scientific_trial(spec, update_enabled=False)
            assert posterior_hash() == frozen_hash
        elif spec.identity.unit_type == "nav_episode":
            frozen_hash = posterior_hash()
            outcome = execute_navigation_scientific_episode(spec, model, method)
            assert posterior_hash() == frozen_hash
            if outcome.requires_cli_exit_4:
                raise PostCommitSafetyStop(outcome.scientific_commit_sha256)
        else:
            raise ProtocolCorruption("unexpected NAV cursor unit type")
```

`durable_pending_methods`/`materialize_current_nav_unit_from_cursor` 都由最后一个 hash-valid
paired checkpoint 驱动，不是从头循环再过滤。已完成 method 整体跳过；当前 method 从
checkpoint 精确恢复 posterior、transformer、planner history、candidate cursor 和 attempted
commands，不能 fresh；只有从未开始的 method 才建 v0000。每次只 materialize 当前一条，
且 adaptive calibration proposal 必须从恢复的 candidate/history 确定性重建；只有本条
`CHECKPOINT_COMMIT` 安装后才读取下一条。`scope_purpose_for_method_open` 对全新 method
返回 `PRIMARY_BATCH,parent=None`，对 resume 返回
`RESUME_RENEWAL,parent=<前 scope hash>`，allowed IDs/maximum 精确等于 parent 尚未消耗的
pending set；若 parent 仍 active 也必须先验证其 durable quota 与 cursor 一致，不能再建
第二个 PRIMARY scope。这样 crash 在 calibration、validation、两张 map 之间或 method
边界都不会重跑已完成 unit，也不会丢失 posterior lineage。

`materialize_current_nav_unit_identity_from_cursor` 是纯 cursor lookup，只返回 stable
identity、unit type、map/pose role。`materialize_current_nav_unit_from_cursor` 同样是纯函数，
但必须在 fresh start gate 与 frozen `RichRobotState` safety snapshot 已取得后调用；它可以返回
`planning_outcome=SAFE_SELECTION|ALL_CANDIDATES_REJECTED` 以及完整 frozen candidate
diagnostics，但不得 append history、移动 candidate cursor、写 planner CSV 或抛出
`ALGORITHM_SAFETY_ABORT`。这些 candidate diagnostics 与相应 detached method-state
candidate 一起交给第 12/13.3.1 节 scientific transaction；只有 paired checkpoint 安装后
才对下一条 proposal 可见。

`capture_frozen_preauthorization_snapshot` 把完整 `RichRobotState` canonical artifact 写成
content-addressed只读文件，返回 state path/hash、boot ID 和 cut monotonic time；它必须晚于
任何 context return 的终点验证，且与 start-pose result 在冻结 age 内。active method 对全
candidate pool 使用同一个 state hash/cut、同一个 equivalent-motion horizon 和同一个
history-before hash调用 `P8SafetyPort.preauthorize_trial`；不得每行刷新 state。fixed CSV
trial用相同接口检查唯一 command，但不因拒绝改选别的 CSV row。NAV episode 没有单个
proposal，planning 中 proposal/preauthorization null，仍绑定 episode-start safety state；
每 tick 继续按第 15.3 节 live safety。

materializer 把 safety artifact、canonical `CommandPreauthorizationArtifact`、proposal hash、
planner decision candidate hash 和 horizon 组装为 `FrozenAttemptPlanning`。后续
`prepare_attempt` 必须把它原样放入 durable `PreparedAttempt`；precheck/preflight/arm 可以
对 frozen proposal 在更晚 state 上再次拒绝，但绝不重新 select。若尚未跨 PREPARED boundary
就要求 refresh，原 unit pending并从 fresh gate/state重新 materialize；若 boundary 已存在，
resume 必须读取其 planning artifacts并重建逐字节相同 decision/proposal，禁止使用当前 state
重选。测试覆盖回位前候选 safe、回位后 unsafe/排序变化，以及 materialization、PREPARED、
physical/scientific/checkpoint 各边界 crash；一旦有 PREPARED，decision/state/cut hash 必须
与 uninterrupted run相同。

一个 method 未结束不得启动下一个 method；禁止“先统一采 102 个 calibration 再分配给
方法”。method 末 checkpoint 必须标 `method_complete=true,next_method_id`，并验证该方法
所有 planned IDs 恰有 effective scientific result，下一 method 才能 fresh。

每个 3.4 s equivalent-motion trial 前都必须通过同一个
`calibration_start_gate`，不是只在 method 开始检查一次。若上一 trial 后
超出 start tolerance，watchdog 先 DISARMED；CONFIRM 按冻结的
`return_mode=manual_reposition_disarmed` 回位。回位使用
`unit_type=context_return`、独立 attempt/marker/raw range，不进入模型、budget 或
endpoint。`approved_controlled_return` 只是 DEV-only future extension；当前 CONFIRM
runner 明确拒绝，agent 不实现或发明回位 controller。
每次回位前必须用第 14.4 节 journal allocator 领取最小未使用的
`conditional_context_return_unit_id`；没有合法 ID 时即使姿态超差也只能保持
DISARMED 并终止 session，不能现场拼接 `AUX/...`。

`ensure_start_pose_or_context_return` 的循环固定为：先调用纯
`operator_gate.check_start_pose`；passed 立即返回该 fresh result；failed 时在**任何 planned
unit prepare/reservation 之前**保持 zero/DISARMED，领取/commit 一个 AUX context-return
unit，随后重新取得新的 reference cut并 check。只有最后 `passed=true` 的对象可绑定 planned
spec。达到 registry上限或 return失败就停止，原 planned scientific unit 仍无 attempt row、
PRIMARY/index=1 pending。不得把 `START_POSE_OUT_OF_TOLERANCE` 伪成技术故障来消耗 planned
unit。SHIFT 的 45 primary和所有 sentinel逐条调用同一 helper；测试断言 off-pose只产生
AUX commits，planned UID/quota/attempt index不变。
三类 planned executor 调用都必须在 runner 的
`except StartPoseRefreshRequired: continue` 内；continue 回到同一 current cursor unit并
重新执行 `ensure_start_pose_or_context_return`，不能退出后由 operator手工绕过，也不能
把该 run-level event转成 RERUN_TECH。

`execute_context_return` 必须有两条显式实现，不能把人工移动伪装成机器人命令：

- `manual_reposition_disarmed`：确认 watchdog 持续 DISARMED/zero，领取 AUX ID，打开
  auxiliary recorder range，完成下述 disarmed-only prepared boundary，fsync
  `MANUAL_RETURN_STARTED`，双人 receipt 注册后由人员移动；
  人员离场后用 reference 验证 start pose/stationary，再 fsync physical/scientific/
  checkpoint commits。全程不得注册 arm/lease，也不得出现非零 `CommandPacket`；
- `approved_controlled_return`：当前只是 DEV extension stub，默认报
  `CONTROLLED_RETURN_NOT_COMMISSIONED` 且不跨 attempt boundary；未来 protocol version 必须
  另行增加 trajectory/controller/start-state schema与独立 HIL gate后才能启用，不能被本
  P8 CONFIRM release选择。

两条路径均写 `unit_type=context_return,selected_for_export=false`，raw/ledger 保留；
technical failure 只能在同 AUX ID 上 RERUN_TECH，完整 return 后仍超差才领取下一 AUX ID。
manual path 的人员进入是该批准流程本身，不标成 `UNPLANNED_HUMAN_ENTRY`；未持有效 receipt
的人进入仍按 safety/technical fault matrix。

manual return 不因“没有 arm”而绕开 attempt 生命周期。其唯一顺序为
`reserve_attempt_and_fsync → ensure_group_open → zero/stationary precheck →
begin_attempt → PREPARED_ATTEMPT fsync`；该 `PreparedAttempt` 标
`execution_mode=MANUAL_DISARMED`，watchdog 必须持续 `DISARMED`，永不调用 preflight/
arm/lease/begin_execution。boundary 后才写 `MANUAL_RETURN_STARTED` 和 typed
`p8.gate.context-return.v1` receipt，先向 watchdog 注册 receipt，再允许安全员示意人员
进入。结束时写 `MANUAL_RETURN_ENDED`，人员清场，reference 证明目标 pose 与 stationary，
然后唯一 finalize `AttemptResult(status=complete,terminal_reason=MANUAL_RETURN_COMPLETE)`、
`ATTEMPT_PHYSICAL_COMMIT → ScientificUnitResult(update=false,selected=false) →
SCIENTIFIC_UNIT_COMMIT → checkpoint/CHECKPOINT_COMMIT`。scientific cursor 只在 complete
时越过该 AUX unit，并恢复被它暂停的 primary unit。

boundary 前失败仍只有 run-level event、原 AUX PRIMARY pending；boundary 后 reference/
recorder/storage 的 exact technical fault 封 `pre_measure_abort|technical_abort` 并只允许同
AUX ID 的显式 RERUN_TECH，safety fault 封 protocol-complete safety abort/latch，operator
撤回封 `OPERATOR_CANCELLED` 并暂停。进程 crash/resume 若看到
`PREPARED_ATTEMPT`/`MANUAL_RETURN_STARTED` 无 physical commit，先保持 DISARMED、要求两人
确认人员已清场并从 raw/reference 重建终止；能够证明完整成功才幂等提交 success，否则
以 `SOFTWARE_PROCESS_CRASH` 封口，绝不续接人工移动或重用 UID。测试必须注入 boundary、
start marker、receipt register、end marker、physical/scientific/checkpoint 每一步崩溃，
并断言无任何非零 CommandPacket、每个 attempt 最多一个 finalize/commit。

`context_return` 没有 `TrialObservation`，其 validity 不能套用“是否构造 observation”：

- manual/controlled return 有 fresh reference cut，且 target-pose 与 stationary verification
  都通过时，写 `observation_valid=null,scientific_valid=true,invalid_reason_codes=[],
  primary_invalid_reason=null,scientific_outcome=CONTEXT_RETURN_COMPLETE`；
- 有完整、有效的终点 reference verification，但 pose/速度未达阈值时，同样
  `scientific_valid=true`，outcome=`CONTEXT_RETURN_TARGET_NOT_REACHED`。这是有效测得的失败，
  AUX unit protocol-complete；原 planned unit 仍暂停，重新 gate 后才可领取下一 return ID；
- protocol-complete safety abort 也是有效安全 outcome，`scientific_valid=true` 且不伪造
  observation invalid reason；
- technical/operator/internal 路径没有可验证终点时
  `scientific_valid=false,observation_valid=null`。若根因是 reference/frame/time-sync，使用
  §9.5 对应的 canonical code；否则统一使用 `MEASUREMENT_WINDOW_UNAVAILABLE`。其中 unknown
  仍保持 `retry_permitted=false`，invalid reason 不把它改成技术重采；
- `ATTEMPT_ABORTED_BEFORE_OBSERVATION` 只用于本来要求 trial observation 的 planned
  measurement unit，禁止用于任何成功或失败的 AUX context return。

handoff `attempt_ledger.valid` 逐字投影 `scientific_valid`。测试必须覆盖 manual/controlled
成功、valid endpoint但 target未到、reference无效、operator cancel、safety abort，并断言
成功 AUX 不会因 `observation_sha256=null` 被 exporter 标 invalid。

NAV 不使用 trial executor；唯一 scientific transaction owner 是
`execute_navigation_scientific_episode`。它必须通过第 5.5 节连续会话，不能调 4 s
`execute_trial`，也不能把 `PhysicalAttemptCommit` 丢给一个并不存在的后续 executor：

```python
def execute_navigation_scientific_episode(episode_spec, model, method):
    assert episode_spec.identity.unit_type == "nav_episode"
    assert episode_spec.identity.scientific_unit_id == live_cursor.current_unit_id
    assert posterior_hash() == episode_spec.frozen_posterior_sha256
    prepared = session = physical = None
    ownership_transferred = terminalization_started = False
    backend_boundary_error = None
    scientific_commit = checkpoint_commit = None

    try:
        prepared = backend.prepare_attempt(
            episode_spec.identity, episode_spec.context,
            episode_spec.start_pose_gate,
            episode_spec.attempt_planning,
        )
        request, wire_request = build_bound_preflight_requests(episode_spec, prepared)
        report = backend.preflight(request)
        require_report_ready_and_hash_bound(report, request, wire_request, prepared)
        authorization = operator_gate.authorize_attempt(
            episode_spec.identity,
            report,
            scope_authorization=episode_spec.scope_authorization,
            start_pose_gate=prepared.start_pose_gate_result,
        )
        gate_receipt = operator_gate.load_receipt(
            authorization.attempt_gate_receipt_sha256
        )
        require_equal(
            watchdog.register_operator_gate_receipt(gate_receipt),
            authorization.attempt_gate_receipt_sha256,
        )
        lease = backend.arm(authorization, episode_spec.identity)

        # 从此行开始 prepared 的终止权永久转给 backend/session；caller 不再 abandon。
        ownership_transferred = True
        session = backend.open_command_session(prepared, episode_spec.context, lease)
        _, navigate_start_ns = session.stabilize_zero(
            duration_s=config.navigation.initial_stabilization_s,
            first_deadline_ns=absolute_next_control_deadline(),
        )
        terminal = None
        while terminal is None:
            rich_state = session.snapshot()
            proposal, terminal = navigation_tick(
                rich_state,
                elapsed_s=(clock.now_ns() - navigate_start_ns) / 1e9,
            )
            if terminal is None:
                session.publish_tick(
                    proposal,
                    controller_cut_monotonic_ns=rich_state.cut_monotonic_ns,
                    scheduler_deadline_ns=absolute_next_control_deadline(),
                )

        terminalization_started = True
        if terminal is NavigationTerminal.COLLISION:
            physical = session.abort(
                "COLLISION", kind="safety",
                serious=session.assess_online_serious_event("COLLISION"),
            )
        else:
            assert terminal in {NavigationTerminal.SUCCESS, NavigationTerminal.TIMEOUT}
            physical = session.close(terminal.value)
    except BaseException as error:
        backend_boundary_error = error
        attached = physical_commit_attached_to_exception_or_none(error)
        if attached is not None:
            physical = attached
        elif session is not None and not terminalization_started:
            # snapshot/stabilize/planner/publish fault：第一动作就是一次 terminalize。
            physical = terminalize_session_fault_once(session, error)
        elif ownership_transferred:
            # open 失败，或 close/abort 已开始：禁止二次 terminalization。
            physical = require_unique_physical_commit_from_journal(
                episode_spec.identity
            )
        elif prepared is not None:
            if isinstance(error, SafetyFault):
                physical = backend.abandon_prepared_attempt(
                    prepared, reason=error.code, kind="safety",
                    technical_failure_code=None,
                )
            elif isinstance(error, OperatorCancelled):
                physical = backend.abandon_prepared_attempt(
                    prepared, reason="OPERATOR_CANCELLED", kind="operator_cancel",
                    technical_failure_code=None,
                )
            elif exact_technical_code_or_none(error) is not None:
                code = exact_technical_code_or_none(error)
                physical = backend.abandon_prepared_attempt(
                    prepared, reason=code, kind="technical",
                    technical_failure_code=code,
                )
            else:
                physical = backend.abandon_prepared_attempt(
                    prepared, reason="UNCLASSIFIED_INTERNAL_FAULT",
                    kind="internal_fault", technical_failure_code=None,
                )
        else:
            # durable PREPARED_ATTEMPT 前没有 attempt/scientific row；prepare 若已跨
            # boundary，必须由 exception 或 journal 提供 physical commit。
            physical = physical_commit_attached_or_journal_or_none(
                error, episode_spec.identity
            )
            if physical is None:
                raise

    # 一旦有 physical commit，禁止在科学事务完成前向外抛异常。
    assert physical is not None
    physical, backend_boundary_error = recover_physical_commit_and_classify_pending_error(
        identity=episode_spec.identity,
        candidate_commit=physical,
        pending_error=backend_boundary_error,
    )
    method_state_before = require_bound_method_state_ref(episode_spec, physical)
    detached_method_state_candidate = nav_episode_method_state_candidate(
        before=method_state_before,
        next_schedule_cursor=episode_spec.next_schedule_cursor,
        # NAV episode 永不改变 planner history/candidate/attempted commands。
    )
    tx = commit_scientific_from_physical(
        spec=episode_spec,
        physical=physical,
        unit_artifact_kind="NAV_EPISODE_METRICS",
        unit_artifact_builder=lambda: deterministically_build_navigation_episode_artifact(
            identity=episode_spec.identity,
            physical=physical,
            map_geometry_sha256=episode_spec.map_geometry_sha256,
            planner_sha256=episode_spec.planner_sha256,
            posterior_sha256=episode_spec.frozen_posterior_sha256,
        ),
        posterior_before=model.immutable_ref(),
        posterior_after=model.immutable_ref(),
        method_state_before=method_state_before,
        detached_method_state_candidate=detached_method_state_candidate,
        planner_decision_candidate=None,
        update_enabled=False,
        next_schedule_cursor=episode_spec.next_schedule_cursor,
    )
    outcome = NavigationEpisodeOutcome.from_transaction(tx)
    if backend_boundary_error is not None:
        append_non_scientific_runner_diagnostic(
            identity=physical.result.identity,
            physical_commit_sha256=physical.commit.event_sha256,
            error=backend_boundary_error,
        )
    if backend_boundary_error is not None or tx.scientific_stage_error is not None:
        raise DeferredPostCommitFault(
            outcome, cause=tx.scientific_stage_error or backend_boundary_error
        )
    return outcome
```

状态只允许
`PREPARED_UNCONSUMED → SESSION_OWNED → TERMINALIZING → PHYSICAL_COMMITTED →
SCIENTIFIC_COMMITTED → CHECKPOINT_COMMITTED`；exception envelope 必须携带
`physical_commit|None,ownership_transferred,terminalization_started`。已有 attached/journal
physical commit 时绝不再次 `close/abort/abandon`。`close` 只接受 SUCCESS/TIMEOUT，
`abort` 接受 COLLISION 或其他 safety/technical/operator/internal fault；相同参数重入返回
同一 `PhysicalAttemptCommit`，不同参数拒绝。`terminalize_session_fault_once` 的顺序
固定为 SafetyFault→safety、typed allowlist TechnicalFault→technical、
OperatorCancelled→operator_cancel、其余→internal_fault/`UNCLASSIFIED_INTERNAL_FAULT`；
它先调用一次 session abort，再做 secondary 分类/记录，并在 abort 自己于 physical fsync
后抛错时只取 attached/journal commit。不得把 operator cancel 或任意 AssertionError
偷映射成可重采的 `SOFTWARE_PROCESS_CRASH`。最终 `finally`/RAII 还必须断言 watchdog 不在
`ARMED_IDLE/EXECUTING`；失败则独立 high-priority zero 并进入
`PERSISTENCE_CORRUPT`，但不能覆写已提交 terminal。

`NavigationEpisodeOutcome` 至少引用 immutable episode artifact、physical/scientific/
checkpoint commit hashes，并有 `requires_cli_exit_4`。COLLISION 物理状态为
`safety_abort`，科学上仍为 protocol-complete algorithm outcome、消耗 unit、禁止重采；
只有 scientific+checkpoint 已 durable 且 live cursor 已安装后，该 flag 才为 true，外层
立即停止整个 run 并令 CLI exit 4。TIMEOUT 同样 protocol-complete、前移 cursor但不
latch；technical/pre-measure 留在当前 unit 的 `AWAIT_EXPLICIT_RERUN_TECH`，operator
cancel 留在 `PAUSED_OPERATOR_DECISION`，internal fault 留在
`PAUSED_INTERNAL_REVIEW`。所有失败 episode 的
`episode_metrics.completion_time_s` 按 handoff 固定为 `timeout_s`；raw artifact 仍保留
真实终止时间。打开的 block/method bag 只提交 range，不伪造 segment hash。
top-level CLI 捕获 `DeferredPostCommitFault` 后先验证 embedded scientific/checkpoint
hash：safety/collision exit 4，allowlist technical 或 internal exit 5，operator pause exit 3；
不得回到 map/method loop，也不得因 Python exception 覆盖已经安装的 cursor。

故障注入必须逐点覆盖 prepare、open、stabilize、publish、close、abort、physical fsync、
metrics write、scientific fsync、checkpoint fsync 和 live-cursor swap 的前/后崩溃；每个
case 断言 recorder finalize count=1、physical/scientific commit 各至多且最终恰一、
zero/latch 正确、posterior 不变、cursor/retry 状态正确，resume 不再次运动。

### 15.2 提取并共享 waypoint 数学

将 P7 下列纯函数无逻辑变化地迁移到
`src/calibagent/core/navigation/waypoint.py`，P7 runner 再 import 它们：

```text
_planner_command → planner_command
_slew_limit      → slew_limit
_near_obstacle   → near_obstacle
_planner_hash    → planner_hash
```

原 P7 tests 必须继续通过，并新增 fixed inputs 的 old/new parity test。实机 runner
不得手抄另一套 waypoint 公式。
实机 map loader 在边界上将 `center_xy/size_xy` 显式转成 pure helper
的 legacy `center/size` 2D view，并保留原始 height/material 给 recorder；不修改
`near_obstacle` 内部数学来逃避 parity。

核心 planner：

```python
delta_world = target_xy - pose_xy
delta_body = R(-yaw) @ delta_world
distance = norm(delta_body)
speed = min(cruise_speed, position_gain * distance)
desired = [
    speed * delta_body[0] / distance,
    clip(speed * delta_body[1] / distance, -lateral_cap, lateral_cap),
    clip(heading_gain * atan2(delta_body[1], delta_body[0]), -yaw_cap, yaw_cap),
]
```

冻结默认：planner 10 Hz、control record ≥50 Hz、reference 目标 ≥50 Hz（硬下限
40 Hz）、cruise 0.18 m/s、
lateral cap 0.14 m/s、yaw cap 0.25 rad/s、waypoint/goal radius 0.25 m、timeout
60 s；所有实机数值仍须通过 DEV safety freeze。

### 15.3 每个 control tick 的唯一顺序

1. `CommandSession.snapshot()` 以同一 cut 读取 reference/onboard/fault controller snapshot；
2. controller 只读取状态和 terminal flags；不得自行宣布 logical/wire safety accepted；
3. 若为 planner tick，先用 raw causal velocity 更新一次 EMA，再推进 waypoint、
   生成 desired 并更新 stall/recovery state；
4. recovery active 时立即生成 zero；否则 `B0` 使用 raw desired，其他方法
   按 startup/recovery delay 决定是否启用 causal velocity feedback，再调用
   `ConstrainedInverseCompensator.solve`；
5. 非 recovery 路径先对 proposed 判定 planner-rate height guard，再相对上一
   `compensated` 做 `slew_limit`，最后对 slewed command 施加 height guard derating；
6. 每个 control-rate sample（包含 planner tick）再评估 high-rate predictive height
   interlock；active 时将持久 `compensated` 和当前 candidate 立即置 zero；
7. runner 只构造 `CommandProposal(planned,candidate,...)`；
8. `CommandSession.publish_tick` 在 scheduler deadline 取 safety cut，执行 state/freshness
   与 `P8SafetyPort.evaluate_logical`，生成 `CommandIntent.safe=model_input`；
9. 独立 relay 执行 identity R1（NAV）和 final wire amplitude/slew/horizon safety，
   再 publish vendor command；
10. session 验证 telemetry acceptance，发送带 lease deadline 的 heartbeat，并记录
    controller cut、safety cut、proposal、intent、receipt。

顺序不得因 method 改变，唯一区别是 B0 跳过 feedback/inverse。stall recovery
与 high-rate interlock 会强制 zero；planner-rate height guard 不是 zero override，它严格
复刻 P7，只将 planar linear norm derate 到冻结上限，yaw 不变。

#### 15.3.1 `NavigationControllerState` 是唯一状态源

以 `sim/isaaclab/calibagent_sim/p7_runner.py::_run_navigation` 当前行为为冻结
oracle，将其 controller lifecycle 无逻辑变化地提取到
`src/calibagent/core/navigation/controller_state.py`。P7 和 P8 都 import 这一实现；
不允许在 ROS runner 中按文字重写一份。纯状态机不读 clock、ROS、模型全局
变量或磁盘，每次 transition 只接受 immutable state/input/config 与 deterministic
inverse-solver callback，返回新 state/output，不就地修改 ndarray。

最低状态字段冻结为：

```python
@dataclass(frozen=True)
class NavigationControllerState:
    phase: Literal["WARMUP", "ACTIVE", "TERMINAL"]
    active_sample_index: int
    waypoint_index: int
    desired: Vec3
    inverse_target: Vec3
    filtered_velocity: Vec3
    compensated: Vec3
    inverse_objective: float                 # 无 inverse/recovery 时 NaN
    stall_ticks: int
    recovery_ticks: int
    recovery_attempts: int                  # regular + emergency
    regular_recovery_attempts: int
    emergency_recovery_attempts: int
    recovery_active: bool
    emergency_recovery_active: bool
    feedback_active: bool
    feedback_updates: int
    feedback_resume_after_s: float
    height_guard_ticks: int
    height_guard_active: bool
    height_guard_updates: int
    high_rate_interlock_active: bool
    high_rate_interlock_updates: int
    previous_planner_height_m: float
    previous_sample_height_m: float
    finished: bool
```

`Vec3` 在 transition 内以 `np.float64[3]` 做与 P7 相同顺序的运算，返回时复制；
不得换成 float32、不得重排算式或在帧间共享 mutable vector。`compensated`
是本 sample 的 controller candidate 和下一 planner tick 的 slew history。未 finished 时它
即 pre-relay candidate；finished 在非 planner sample 到达时，P7 先保留该 history、仍调
`distortion.step`，然后以 `effective[finished]=zero` 覆盖输出，直到下一 planner
tick 才清 `compensated`。P8 没有 simulator distortion，但必须同样在任何 terminal
flag 可见的第一个 sample 将 proposal candidate 覆盖为 zero，同时保留未到 planner
tick 前的 internal `compensated` 以供 golden trace。R1、
wire safety 和实机 telemetry 不得回写它。

#### 15.3.2 频率、计数器和初始化

P8 config 的 `navigation.control_rate_hz` 等于 P7 的 `sample_rate_hz`。freeze 必须要求
两者为正整数、`control_rate_hz % planner_rate_hz == 0`，并按下式一次派生：

```python
dt = 1.0 / control_rate_hz
control_dt = 1.0 / planner_rate_hz
decimation = control_rate_hz // planner_rate_hz
warmup_steps = round(initial_stabilization_s * control_rate_hz)
height_guard_hold_ticks = max(1, round(hold_s * planner_rate_hz))
recovery_detection_ticks = max(1, round(detection_s * planner_rate_hz))
recovery_zero_ticks = max(1, round(zero_command_s * planner_rate_hz))
emergency_zero_ticks = max(1, round(emergency_zero_command_s * planner_rate_hz))
```

P8-NAV CONFIRM 冻结为 `control_rate_hz=50,planner_rate_hz=10,decimation=5`，与 P7
confirmatory config 一致。DEV 可为 timing pilot 使用其他正整数倍，但不得进入
CONFIRM 混用；55/10 这类非整数 decimation 配置必须在解析时拒绝。

`round` 就是 Python 内建 round（ties-to-even），不得用 floor/ceil。active episode 的
planner tick 严格为 `active_sample_index % decimation == 0`，因此 index 0 是第一个
planner tick；时间每次从 `t_s = active_sample_index * dt` 重算，不做浮点累加。
实机 scheduler 用 absolute deadline 触发同一 index；丢 tick 走 typed technical abort，
禁止连续补跑多个 transition。
本次 output/metadata 使用递增前的 index，完成 planner/high-rate transition 后新 state
才令 `active_sample_index += 1`。非 planner sample 不更新 EMA、waypoint、stall、
recovery ticks、feedback、inverse、slew、height-guard state，而是持有上一个
planner 值，然后仅跑本 sample 的 high-rate interlock。

在 initial stabilization **之前**用 episode reset cut 初始化：所有向量为 zero、
`inverse_objective=NaN`、所有 ticks/counters 为 0、所有 active flag 为 false、
`feedback_resume_after_s=startup_delay_s`，两个 previous-height 都等于 reset cut 的 base
height。WARMUP 恰发 `warmup_steps` 个 zero sample，不更新 EMA、counter、height
baseline 或 active index。进入 ACTIVE 时只将 `active_sample_index=0`；严格保留
P7 的行为：**不用 warmup 末的高度重置 previous-height**。如果要改这一
行为，必须作为新 protocol version 重跑 P7，不能在 P8 实现中悄然“修正”。
`execute_navigation_scientific_episode` 必须在调用 `session.stabilize_zero` 之前就构造
该 state，让同一实例跨过全部 WARMUP；进入 `NAVIGATE_START` 时严禁重建
state 或从最新 height 重置 baseline。

#### 15.3.3 planner-rate transition（与 P7 语句顺序一致）

在每个 planner tick，先执行三轴 EMA；它只以 planner rate 更新，初值为
zero，即使处于 startup delay、recovery 或 B0 也照常更新：

```python
filtered_velocity = (
    ema_alpha * raw_causal_control_velocity
    + (1.0 - ema_alpha) * previous_filtered_velocity
)
```

这一更新发生在 finished 分支之前。finished 在 planner tick 将
`desired/inverse_target/compensated=zero`、feedback/height guard inactive、
`height_guard_ticks=0`，但不清累计 counters，也不改
`inverse_objective/stall_ticks/recovery_ticks/recovery_active/
emergency_recovery_active/feedback_resume_after_s`。未 finished 时，先按第 15.2/15.4 节
推进 waypoint、判定 goal 并生成 desired，再执行：

```python
actual_speed = norm(raw_causal_control_velocity[:2])  # 不是 EMA velocity
stalled = (
    norm(desired[:2]) >= minimum_desired_speed_mps
    and actual_speed <= maximum_actual_speed_mps
    and base_height_m <= maximum_base_height_m
)
stall_ticks = stall_ticks + 1 if stalled else 0
emergency_trigger = base_height_m <= emergency_base_height_m
regular_trigger = stall_ticks >= recovery_detection_ticks

use_emergency = (
    emergency_trigger
    and emergency_recovery_attempts < maximum_emergency_attempts
)
use_regular = (
    not use_emergency
    and regular_trigger
    and regular_recovery_attempts < maximum_attempts
)
if recovery_ticks == 0 and (use_emergency or use_regular):
    recovery_ticks = emergency_zero_ticks if use_emergency else recovery_zero_ticks
    recovery_attempts += 1
    regular_recovery_attempts += int(use_regular)
    emergency_recovery_attempts += int(use_emergency)
    emergency_recovery_active = use_emergency
    stall_ticks = 0

recovery_active = recovery_ticks > 0  # 必须在本 tick 递减前求值
```

stall detection 在已 active 的 zero-recovery tick 也继续更新，只是
`recovery_ticks != 0` 时不得新开 recovery。emergency 优先于 regular；
`maximum_attempts` 只约束 regular counter，emergency 有独立 budget，`recovery_attempts`
只是两者之和。不得用 total counter 提前耗尽 regular budget。

recovery active 的本 planner interval 严格执行：

```python
proposed = zero
inverse_target = desired
feedback_active = False
inverse_objective = NaN
recovery_ticks -= 1
if recovery_ticks == 0:
    emergency_recovery_active = False
    feedback_resume_after_s = max(
        feedback_resume_after_s,
        t_s + recovery_reengagement_delay_s,
    )
compensated = zero          # 跳过 inverse、slew 和 height guard
height_guard_active = False
height_guard_ticks = 0
```

因为 `recovery_active` 不在递减后重算，N 个 zero ticks 恰好保持 N 个完整
planner interval。末一个 zero tick 以本 tick `t_s` 设置 reengagement deadline；下一
planner tick 仍使用严格比较 `t_s < feedback_resume_after_s`。不清 EMA，不重置
feedback update counter。

非 recovery 时分支冻结为：

- B0：`proposed=desired,inverse_target=desired,feedback_active=false,
  inverse_objective=NaN`，不调 inverse solver，startup/reengagement deadline 不改变该分支；
- 其他方法且 `t_s < feedback_resume_after_s`：`inverse_target=desired`、feedback
  inactive，但仍调一次 inverse solver；
- 其他方法且 deadline 已到：用共享
  `bounded_velocity_feedback_target(desired,filtered_velocity,...)`；且仅当
  `norm(inverse_target-desired) > 1e-9` 时令 feedback active 并将
  `feedback_updates += 1`，然后调一次 inverse solver。

inverse solver 始终获得本 tick state 和上一个持久 `compensated` 作为 history。
解出 `proposed` 后，非 recovery 路径必须以下列两次 guard 顺序执行：

```python
_, guard_now = height_rate_guarded_command(
    proposed,
    base_height_m=base_height,
    previous_base_height_m=previous_planner_height,
    force_active=(height_guard_ticks > 0),
    ...,
)
slewed = slew_limit(proposed, previous_compensated, config, control_dt)
compensated, _ = height_rate_guarded_command(
    slewed,
    base_height_m=base_height,
    previous_base_height_m=previous_planner_height,
    force_active=guard_now,
    ...,
)
if guard_now:
    if height_guard_ticks == 0:
        height_guard_ticks = height_guard_hold_ticks
    height_guard_active = True
    height_guard_updates += 1       # active tick count，不是 rising-edge count
    height_guard_ticks -= 1         # 触发当 tick 就递减
else:
    height_guard_active = False
previous_planner_height = base_height
```

孤立触发恰 active `height_guard_hold_ticks` 个 planner ticks。countdown 尚未到 0
时的新 drop 不重载长 latch；只有下一 tick 已到 0 且自然触发仍成立才重载。
recovery 可清空 height-guard latch；feedback 自身不被 height guard 禁用。
`previous_planner_height=base_height` 是 planner tick 末的全局无条件更新；finished、
goal-success 和 recovery 分支也必须执行，不能因上面的 early branch 跳过。

#### 15.3.4 control-rate high-rate interlock

在每个 ACTIVE control sample，且在本 sample 的 planner transition 之后，使用
当前 cut 的 height 和上一 sample height：

```python
drop = max(previous_sample_height - base_height, 0.0)
projected_height = base_height - prediction_steps * drop
trigger = (
    base_height <= activation_height
    or projected_height <= safety_min_base_height + minimum_clearance
)
recovered = (
    base_height >= release_height
    and base_height >= previous_sample_height
)
high_rate_interlock_active = trigger or (
    previous_high_rate_interlock_active and not recovered
)
if high_rate_interlock_active:
    compensated = zero
    feedback_active = False
    high_rate_interlock_updates += 1  # 每个 active sample 加 1
previous_sample_height = base_height
```

finished 时本 sample 先将 interlock active 清 false，但仍更新 previous sample height。
interlock disabled 时完全跳过该 transition，包括不更新 previous sample height。
interlock 的 zero 会写回持久 `compensated`；若它在非 planner sample 释放，不得
立即恢复旧 inverse command，candidate 保持 zero 直到下一 planner tick 重算。它不更新
`feedback_resume_after_s`、不清 EMA、不消耗 recovery budget；它可与 recovery
同时 active。这些都是 P7 行为，禁止用“更平滑”的实现替代。

#### 15.3.5 共享提取和 P7 不变性

提取前先从未修改的 P7 runner 产生
`tests/fixtures/p7_navigation_controller_golden_v1.json`，并把 raw-byte SHA-256 写入
fixture manifest。fixture 每 sample 包含 controller input、planner flag、所有上述 state
before/after、inverse solver request/result 和 candidate。然后再让 P7 runner 与 P8 runner 共用
`advance_navigation_controller_state`。验收要求：

- 对同一 input/golden inverse result，所有 bool/int/enum/NaN placement 完全一致，
  float64 vector 逐位 bitwise 一致；
- P7 六图 end-to-end replay 的 terminal flags、waypoint index、command trace、六类
  update/attempt counter 和 episode metrics 与提取前 golden 一致；
- P7 config、method、seed、distortion、planner/inverse 数学和任何论文选择规则均不变。

如果无法将 P7 改为共享 import 而不改 golden，允许 P7 暂时保留原代码，但 P8
状态机必须通过同一逐 sample golden trace；禁止以“结果看起来相近”代替 parity。
P7 的 `CommandDistortion.step(compensated,dt)` 保持在共享 controller 之后，不得移入
状态机或改变调用次数；P8 的 R1/wire transform 同样位于 controller candidate
之后的第 8–9 步。

NAV `CommandProposal.metadata` 不得自由命名，required key/type 固定为：

```text
waypoint_index:int,target_x:float,target_y:float,
active_sample_index:int,planner_tick:bool,
desired_vx/vy/wz:float,inverse_target_vx/vy/wz:float,
filtered_velocity_vx/vy/wz:float,compensated_vx/vy/wz:float,posterior_version:int,
velocity_feedback_active:bool,velocity_feedback_updates:int,
feedback_resume_after_s:float,height_guard_active:bool,height_guard_ticks:int,
height_guard_updates:int,high_rate_interlock_active:bool,
high_rate_interlock_updates:int,stall_ticks:int,recovery_ticks:int,
stall_recovery_active:bool,stall_recovery_attempts:int,
regular_recovery_attempts:int,emergency_recovery_active:bool,
emergency_recovery_attempts:int,controller_cut_monotonic_ns:int
```

B0 的 `inverse_target_*` 等于 desired，pre-slew `proposed` 也等于 desired；
`compensated_*` 必须是经共享 slew/height guard/interlock 后的真值，可与 desired
不同，但不得为 null。trial
proposal metadata 至少固定 `posterior_version,planner_step,source,command_id`；不适用
值使用显式 `NOT_APPLICABLE`。这些 key 同时由 contracts validator、recorder 和
exporter 读取，禁止三处各自约定临时 dict。

### 15.4 waypoint 和终止

- 进入当前 waypoint radius 才推进；
- 最终 goal radius 内且无 collision/abort 才 success；
- collision 在线只由冻结几何/contact 规则触发；视频仅事后盲审；
- timeout、algorithm safety abort、collision 均是有效失败；
- failed episode 的 `completion_time_s=60.0`；
- path length 用独立 reference 相邻位置累计；
- 每个 episode 恰有一个 terminal reason；
- navigation 不 update model，不改变 transformer/history/planner posterior。

同一 control tick 有多个终止事件时优先级固定为：

```text
SAFETY_ABORT > COLLISION > TECH_ABORT > SUCCESS > TIMEOUT
```

低优先级 flag 仍可保留作 diagnostics，但 `terminal_reason` 只有一个。
恰在 deadline 进入 goal 时 SUCCESS 胜过 TIMEOUT；同 tick contact 胜过 SUCCESS。

### 15.5 NAV cardinality assertion

runner 启动 CONFIRM 前必须打印并写 machine-readable plan：

```json
{
  "blocks": 30,
  "methods": 8,
  "maps": 2,
  "calibration_trials": 3060,
  "validation_trials": 1920,
  "navigation_episodes": 480
}
```

任何实际/期望数量不符均使 preflight 非零退出。

---

## 16. P8-SHIFT runner

### 16.1 模块隔离

`shift_runner.py` 分成三层：

```text
ShiftOrchestrator   # 知道 frozen schedule、operator barrier、raw marker
ShiftPolicy         # 只知道 method、model、detector、task、observation
ShiftActuator       # R1 软件或 R2–R4 人工/硬件 changeover
```

`ShiftPolicy` 的方法签名不得出现 `shift_id`、`context_stage`、matrix、payload、
surface、shift marker 或 activation time。它也不得接收现有
`TrialObservation`，因为其 `RobotContext.terrain_id/payload_kg` 会泄漏 R2–R4。
`shift_runner.py` 定义下列最小盲化 view：

```python
@dataclass(frozen=True)
class PolicyObservation:
    command: tuple[float, float, float]
    command_duration_s: float
    command_frame: Literal["base"]
    mean_velocity: tuple[float, float, float]
    observation_covariance: tuple[float, ...]  # row-major 3x3
    timestamps_s: tuple[float, float]
    quality: Mapping[str, JSONScalar]
    valid: bool
    invalid_reason_codes: tuple[str, ...]

@dataclass(frozen=True)
class ResidualEvidence:
    residual: tuple[float, float, float]
    prediction_covariance: tuple[float, ...]   # row-major 3x3
    observation_covariance: tuple[float, ...]  # row-major 3x3
    innovation_covariance: tuple[float, ...]   # exact sum of the two above
    scheduled_monitor_index: int
```

orchestrator 保留完整 `TrialObservation` 给 recorder/evaluator，只把上述 copy
交给 policy。R4 可见 task change 只以当前 numeric commands+normalized
weights 传入 planner，不含 profile ID/hash/stage。detector 的唯一输入保持：

为兼容现有 `BayesianBasisModel.update(TrialObservation)`，新增
`BlindModelAdapter.update(PolicyObservation)`；它在适配器内构造一个 context 恒为
`RobotContext("BLINDED",0.0,1.0,"BLINDED","BLINDED")` 的临时 observation。
该 context 不写回 evaluator/raw，仅满足冻结 model API；policy 无法持有完整
observation 引用。adapter 必须使用 view 中的 duration/frame/timestamps/quality 构造
`VelocityCommand/TrialObservation`，令 `safety_events=[]、raw_ref=None`；不得填当前
terrain/payload/session。`quality["valid"]` 必须与顶层 `valid` 相等。adapter 同时提供
只接收 numeric command 的 `predict/predict_batch`，不把 dummy context 暴露给 policy。

每条 valid monitor 的 residual 是 `y_obs-mu_pred`，detector covariance 精确为
`Sigma_innovation = Sigma_pred + Sigma_obs`；三者先对称化并验证 shape/finite/PSD，
然后断言 serialized `innovation_covariance` 与两者之和 `rtol=1e-12,atol=1e-12`。
`DomainShiftDetector` 再且只再加 config 的 `covariance_jitter*I` 做数值求解；禁止只用
prediction covariance、只用 observation covariance或把 jitter 加两次。prediction
必须在执行该 monitor 前由当时 posterior 产生。

```python
detection = detector.update(
    residual=evidence.residual,
    covariance=evidence.innovation_covariance,
    trial=evidence.scheduled_monitor_index,
)
```

通过 type/API test 和 subscription whitelist 证明隔离，而不是依赖开发者自觉。

### 16.2 sequence 的精确流程

进入每个 `shift × block × method` sequence 前，按第 15.1 节同一
`authorize_scope → register_scope_authorization` 事务建立 scope，
`maximum_attempts=47`（45 primary + initial set 的 2 sentinel）。每个 trial spec 都显式
携带该 scope；不能从 module global 取“当前授权”。conditional sentinel set 每次另建
只覆盖其两个新 unit 的 scope authorization；RERUN_TECH 同样使用独立一单元 scope。
changeover 和 context-return 使用各自 operator gate，不消耗这 47 条 motion quota。
主 scope request 必须逐字段取
`shift_id=<R1..R4>,scope_id=f"{run_id}/{session_id}/{shift_id}/{block_id}/{method_id}",
authorization_purpose="PRIMARY_BATCH",parent=None,retry=None,activation=None`；在
`authorize_scope` 后先注册其 typed gate receipt，再注册 scope authorization。四个 shift
即使 block/method 同名也有不同 logical scope/quota/lineage。conditional sentinel、
controlled context return、RERUN_TECH 和 resume 构造器必须复用同一 shift-scoped
`scope_id`，并分别填第 5.5 节冻结 purpose/parent/retry/activation 组合，不得退回 NAV 的
`NOT_APPLICABLE`。

```python
sequence_state = resume_manager.open_shift_sequence(shift_id, block_id, method_id)
if sequence_state.is_new:
    model = fresh_m2_identity_prior()
    detector = DomainShiftDetector(frozen_config)
    alarm_handled = False
    recovered_at = None
    init_tx = initialize_runtime_state_transaction(
        shift_runtime_identity(
            run_id, session_id, shift_id, block_id, method_id
        ),
        posterior_candidate=model,
        runtime_state_candidate=fresh_shift_sequence_state(
            detector=detector,
            alarm_handled=alarm_handled,
            recovered_at=recovered_at,
            first_cursor="A_CALIBRATION/1",
        ),
    )
    sequence_state = resume_manager.open_shift_sequence_from_init_checkpoint(init_tx)
else:
    model, detector, alarm_handled, recovered_at = restore_shift_state_exact(
        sequence_state.posterior_ref,
        sequence_state.detector_state,
        sequence_state.alarm_handled,
        sequence_state.recovered_at,
        sequence_state.planner_history,
        sequence_state.rolling_validation_slots,
        sequence_state.nominal_restore_reference_sha256,
        sequence_state.actuator_cursor,
    )

# A--F 是由 durable stage cursor 调用的 idempotent handlers；只运行当前 pending row。

def materialize_gated_shift_trial(unit_stub, command_materializer):
    # 与 NAV 相同：先 gate/必要回位，再冻结 state cut，最后才 propose/preauthorize。
    gate = ensure_start_pose_or_context_return(
        unit_stub.identity, pose_role="calibration", map_id="NOT_APPLICABLE"
    )
    safety_snapshot = capture_frozen_preauthorization_snapshot(
        start_pose_gate=gate,
        maximum_age_ms=config.calibration_start_gate.maximum_start_pose_gate_age_ms,
    )
    return materialize_shift_unit_from_cursor(
        unit_stub=unit_stub,
        command_materializer=command_materializer,
        prior_shift_state=current_detached_shift_state(),
        start_pose_gate=gate,
        safety_snapshot=safety_snapshot,
        scope_authorization=current_shift_scope_authorization,
    )

def execute_gated_shift_unit(spec, hook):
    if spec.planning_outcome == "ALL_CANDIDATES_REJECTED":
        require_equal(spec.planning.planning_kind, "ADAPTIVE_ALL_REJECTED")
        rejection_hook = hook.for_algorithm_safety_rejection()
        outcome = execute_algorithm_safety_rejection(
            spec, shift_hook=rejection_hook
        )
        # rejection hook保持posterior，记录decision/本stage缺失结果，并继承A12 freeze flag。
        raise PostCommitSafetyStop(outcome.scientific_commit_sha256)
    return execute_shift_scientific_unit(spec, hook=hook)

# A. nominal calibration: 6 frozen axis seeds + 6 online task-aware IVR
for row_index, unit_stub in enumerate(six_pre_calibration_seed_rows, 1):
    spec = materialize_gated_shift_trial(
        unit_stub, fixed_command_materializer(unit_stub)
    )
    execute_gated_shift_unit(
        spec, hook=calibration_hook(freeze_nominal_reference=False)
    )
for step in range(6):
    unit_stub = current_shift_unit_identity_from_cursor()
    spec = materialize_gated_shift_trial(
        unit_stub,
        task_aware_ivr_materializer(model, history),
    )
    # planner decision只留在 spec 的内存 preimage；shared helper负责唯一持久化。
    execute_gated_shift_unit(
        spec,
        hook=calibration_hook(freeze_nominal_reference=(step == 5)),
    )
# 第12条的 hook 已把 nominal reference写进同一 scientific/checkpoint；这里不得另存。

# B. pre-shift monitor, monitor_index 1..4
for index, unit_stub in enumerate(pre_monitor_table, 1):
    spec = materialize_gated_shift_trial(
        unit_stub, fixed_command_materializer(unit_stub)
    )
    execute_gated_shift_unit(spec, hook=monitor_hook(index))

# C. zero/changeover barrier
zero_disarm_and_confirm()
apply_identity = next_planned_changeover_attempt(
    block_id, method_id, shift_id, kind="APPLY"
)
nominal_evidence = actuator.verify_nominal(
    with_changeover_phase(apply_identity, action="apply", phase="precheck")
)
apply_gate = operator_gate.authorize_changeover(
    with_changeover_phase(apply_identity, action="apply", phase="actuate"),
    evidence_sha256=nominal_evidence.bundle_sha256,
)
require_equal(
    watchdog.register_operator_gate_receipt(apply_gate), apply_gate.receipt_sha256
)
actuation = actuator.apply(
    with_changeover_phase(apply_identity, action="apply", phase="actuate"),
    apply_gate,
    nominal_evidence,
)
shifted_evidence = actuator.verify_shifted(
    with_changeover_phase(apply_identity, action="apply", phase="postcheck")
)
apply_receipt = commit_changeover_transaction(
    actuation, nominal_evidence, shifted_evidence
)
rearm_after_full_preflight()

# D. post-shift monitor, monitor_index 5..9
for local_index, unit_stub in enumerate(post_monitor_table, 1):
    monitor_index = 4 + local_index
    spec = materialize_gated_shift_trial(
        unit_stub, fixed_command_materializer(unit_stub)
    )
    execute_gated_shift_unit(spec, hook=monitor_hook(monitor_index))

# E. exactly 12 recovery + 12 validation
for recovery_index in range(1, 13):
    recovery_stub = recovery_unit_stub(recovery_index)
    spec = materialize_gated_shift_trial(
        recovery_stub, recovery_command_materializer(recovery_index)
    )
    execute_gated_shift_unit(spec, hook=recovery_update_hook(recovery_index))
    validation_stub = validation_unit_stub(recovery_index)
    execute_gated_shift_unit(
        materialize_gated_shift_trial(
            validation_stub, fixed_command_materializer(validation_stub)
        ),
        hook=rolling_validation_hook(recovery_index),
    )

# F. restore nominal and two out-of-endpoint sentinels
zero_disarm_and_confirm()
restore_identity = next_planned_changeover_attempt(
    block_id, method_id, shift_id, kind="RESTORE"
)
restore_pre_evidence = actuator.verify_shifted(
    with_changeover_phase(restore_identity, action="restore", phase="precheck")
)
restore_gate = operator_gate.authorize_changeover(
    with_changeover_phase(restore_identity, action="restore", phase="actuate"),
    evidence_sha256=restore_pre_evidence.bundle_sha256,
)
require_equal(
    watchdog.register_operator_gate_receipt(restore_gate), restore_gate.receipt_sha256
)
restore_actuation = actuator.restore(
    with_changeover_phase(restore_identity, action="restore", phase="actuate"),
    restore_gate,
    restore_pre_evidence,
)
restored_evidence = actuator.verify_restored(
    with_changeover_phase(restore_identity, action="restore", phase="postcheck")
)
restore_receipt = commit_changeover_transaction(
    restore_actuation, restore_pre_evidence, restored_evidence
)
for sentinel_index in (1, 2):
    sentinel_stub = sentinel_unit_stub(verification_set_id, sentinel_index)
    execute_gated_shift_unit(
        materialize_gated_shift_trial(
            sentinel_stub, fixed_command_materializer(sentinel_stub)
        ),
        hook=sentinel_hook(verification_set_id, sentinel_index=sentinel_index),
    )
require_nominal_restoration_before_next_method()
```

`hook` 不是 scientific commit 之后执行的 callback，也不允许直接修改 live object。实现必须
冻结以下唯一接口；SHIFT 的 calibration、monitor、recovery、validation 和 sentinel 都只能
通过该接口改变运行状态：

```python
@dataclass(frozen=True)
class DetachedPosteriorCandidate:
    mode: Literal["REUSE_EXISTING_REF", "NEW_CANONICAL_PREIMAGE"]
    existing_path: str | None
    existing_sha256: str | None
    canonical_preimage: PosteriorState | None
    target_version: int

@dataclass(frozen=True)
class NominalRestoreReferenceCandidate:
    mode: Literal["REUSE_EXISTING_REF", "NEW_CANONICAL_PREIMAGE"]
    existing_path: str | None
    existing_sha256: str | None
    canonical_preimage: NominalRestoreReference | None
    source_posterior_sha256: str
    source_posterior_version: int

@dataclass(frozen=True)
class SentinelScheduledSlot:
    verification_set_id: int
    sentinel_index: Literal[1, 2]
    scientific_unit_id: str
    observation_sha256: str | None
    observation_available: bool
    observation_valid: bool | None
    terminal_reason: str

@dataclass(frozen=True)
class ShiftScientificCandidate:
    detached_posterior_candidate: DetachedPosteriorCandidate
    detector_state: DetectorState
    alarm_handled: bool
    rolling_validation_slots: tuple[ValidationSlot, ...]  # 始终保留最近4个 scheduled slot
    recovered_at: int | None
    nominal_restore_reference_candidate: NominalRestoreReferenceCandidate | None
    planner_history: tuple[PlannerDecision, ...]
    attempted_logical_commands: tuple[VelocityCommand, ...]
    sentinel_set_slots: tuple[SentinelScheduledSlot, ...]  # 当前/最近 verification set的0..2条
    sentinel_set_verdict: SentinelSetVerdict | None
    pre_checkpoint_event_intents: tuple[PendingProtocolEventIntent, ...]
    next_schedule_cursor: ShiftScheduleCursor

@dataclass(frozen=True)
class ShiftTerminalOutcome:
    outcome_class: Literal["RUNTIME_SAFETY", "RUNTIME_TECHNICAL",
                           "OPERATOR_CANCELLED", "INTERNAL_FAULT"]
    terminal_phase: Literal["PRE_MEASURE", "MEASURE_OR_LATER"]
    status: Literal["pre_measure_abort", "technical_abort", "safety_abort"]
    terminal_reason: str
    protocol_complete: bool
    retry_permitted: bool

class ShiftScientificHook(Protocol):
    def __call__(
        self,
        *,
        prior: DetachedShiftState,
        observation: Observation,
        spec: ShiftTrialSpec,
    ) -> ShiftScientificCandidate: ...

    def for_terminal_outcome(
        self,
        *,
        prior: DetachedShiftState,
        spec: ShiftTrialSpec,
        terminal: ShiftTerminalOutcome,
    ) -> ShiftScientificCandidate: ...

    def for_algorithm_safety_rejection(self) -> "ShiftRejectionHook": ...

class ShiftRejectionHook(Protocol):
    def __call__(
        self,
        *,
        prior: DetachedShiftState,
        spec: ShiftTrialSpec,
        rejection_decision: PlannerDecision,
    ) -> ShiftScientificCandidate: ...
```

`execute_algorithm_safety_rejection` 必须以以上三个 keyword-only 参数调用返回的 adapter；
不得把它当单参 callback，也不得再次调用原 hook。adapter 返回的 candidate 使用
`observation=None` 语义、REUSE posterior、追加 rejection decision，并继承原 hook 的 stage/
freeze/cursor flags。

`observation=None` 不允许调用 `hook.__call__`：已有 physical commit但因运行时安全/
技术终止而没有 observation 时，`execute_shift_scientific_unit` 必须且只能调用一次
`hook.for_terminal_outcome(prior=...,spec=...,terminal=...)`。普通低质量测量仍是
`Observation(valid=false)` 并走 `__call__`；`ALL_CANDIDATES_REJECTED` 仍只走
`for_algorithm_safety_rejection()`，不得再叠加 terminal adapter。`ShiftTerminalOutcome`
必须从 immutable physical/scientific classification 构造，组合仅允许：

| `outcome_class` | `terminal_reason` | `status` | `protocol_complete` | `retry_permitted` |
|---|---|---|---:|---:|
| `RUNTIME_SAFETY` | handoff §14.2 safety code（含 `COLLISION/FINAL_ZERO_NOT_CONFIRMED`） | `safety_abort` | true | false |
| `RUNTIME_TECHNICAL` | handoff §14.2 technical allowlist | PRE_MEASURE 为 `pre_measure_abort`，否则 `technical_abort` | false | true |
| `OPERATOR_CANCELLED` | 字面量 `OPERATOR_CANCELLED` | PRE_MEASURE 为 `pre_measure_abort`，否则 `technical_abort` | false | false |
| `INTERNAL_FAULT` | 字面量 `UNCLASSIFIED_INTERNAL_FAULT` | PRE_MEASURE 为 `pre_measure_abort`，否则 `technical_abort` | false | false |

adapter 入口先重算上表；任一 caller-supplied 组合不符即
`PERSISTENCE_CORRUPT`，不允许由 hook 自由决定 budget/retry。`RUNTIME_SAFETY`的
`terminal_reason` 若是 serious candidate 仍由 safety review 链决定 serious；hook 不改写分类。

`for_terminal_outcome` 为五类 scientific phase 执行下列唯一状态推进。所有
protocol-complete 分支都令 `observation_available=false,observation_valid=null`，posterior
使用 `REUSE_EXISTING_REF`、`posterior_transition_kind=NONE`，不调用 model/detector update：

1. **A/calibration**：追加 spec 中已冻结的 selected proposal/command 到
   `attempted_logical_commands`；如为 adaptive selected decision，同时追加原决策到
   `planner_history`，不生成新 decision。未选中 command 不伪造 append。cursor 消耗本
   scheduled row 并前移一格。非 A12 保持 nominal reference；A12 必须返回
   `NEW_CANONICAL_PREIMAGE` reference，source 绑定未变 posterior-after、transformer
   以及包含本次已尝试 command/decision 的 calibration history，然后进入 B/1。
2. **B/D monitor**：把本 `scheduled_monitor_index` 记为 gap；detector 的
   `last_scheduled_index` 前移到该 index，但 CUSUM/positive window/latch 逐位不变，
   不提交 residual。无 observation 绝不能产生 first alarm/inflation，`alarm_handled`
   保持 before；cursor 前移到下一 monitor 或冻结的下一 stage。
3. **E/recovery motion**：消耗本 recovery row，posterior/detector/rolling slots/
   `recovered_at` 不变，禁止 update。若本条有已冻结 adaptive selected decision/command，
   按普通 recovery hook 的同一历史规则追加，不能因 safety outcome 删掉已发生
   的 selection。cursor 只前移到同 index 的 validation。
4. **E/rolling validation**：在长度 4 deque 加入该 scheduled index 的
   `INVALID` slot，`observation_sha256=null,invalid_reason=
   ATTEMPT_ABORTED_BEFORE_OBSERVATION,q=0.25**2`，超过 4 时仅弹出最旧 scheduled
   slot。按第 16.5 节对最近 `min(k,4)` 个 q 重算 rolling RMSE 和冻结
   recovery rule；`recovered_at` 已 non-null 时保持，否则只能在该规则本次
   首次满足时设为 k。然后 cursor 进入 recovery k+1 或 F/RESTORE。
5. **F/restore sentinel**：把本条追加为
   `SentinelScheduledSlot(observation_available=false,observation_valid=null,
   observation_sha256=null,terminal_reason=<exact code>)`。第 1 条只保存一条
   `sentinel_set_slots`、`sentinel_set_verdict=null`，cursor 指向同 set 第 2 条；
   第 2 条必须以两个 slot 构造 `set_passed=false` verdict。若还有预展开 set，
   只在该第 2 条的 `pre_checkpoint_event_intents` 生成一个冻结
   `CONDITIONAL_UNIT_ACTIVATED` intent，cursor 保持 DISARMED 并指向下一 set/1；
   registry 用尽则不生成 intent并进入 `PAUSED_SENTINEL_EXHAUSTED`。不允许省略
   第 2 条或在第 1 条提前领取 conditional ID。

`terminal.protocol_complete=false` 是上述的唯一总例外：candidate 的 posterior/
detector/alarm/rolling/recovered/reference/planner history/attempted commands/sentinel slots/
verdict/cursor 必须与 `prior` 逐字节相同，
`nominal_restore_reference_candidate=null`、`pre_checkpoint_event_intents=()`。即使失败发生在
A12，也不得冻结 nominal reference；后续 RERUN_TECH 仍从同一 before hash/
cursor 重建。顶层 scientific result/diagnostic 仍由共享 helper 持久化，“state 不变”
不等于跳过 scientific commit/checkpoint。

上述 ordinary/rejection/terminal 路径返回的 candidate 都只是内存 tagged
union，不是已经落盘的 ref。每个 hook 都必须返回全量 state；本 phase 不修改的
`attempted_logical_commands/sentinel_set_slots`等字段逐字节继承 prior，不允许依赖
dataclass default 隐式清空。
`REUSE_EXISTING_REF` 要求 path/hash 都等于 before checkpoint、preimage=null、version不变；
posterior 的 `NEW_CANONICAL_PREIMAGE` 要求 path/hash=null、preimage non-null、target
version恰为 before+1；ordinary no-update 使用 REUSE，model update/alarm inflation 使用 NEW。
nominal-reference 的 NEW 则有独立 content hash/version语义：其
`source_posterior_sha256/version` 必须等于本 scientific result 的 posterior-after，可等于
before（第12条 invalid/no-update）或 before+1（valid update），不强制自己的 reference
sequence等于 posterior version。它可以复用既有 ref，或以 new preimage 表示“candidate
posterior+transformer+history”的快照。只有共享 helper 有权把 new preimage 序列化成真正 immutable
path/hash并回填 scientific result/checkpoint；hook 内写文件或提前构造虚假 ref 均由 type/
architecture test拒绝。

`execute_shift_scientific_unit` 是 SHIFT trial 的唯一 scientific transaction owner。它先用
第 12 节 physical-only executor 得到或从 journal 恢复唯一 `PhysicalAttemptCommit`，再从
paired checkpoint 克隆 `DetachedShiftState`，确定性构造 observation，并且只调用一次
`ShiftScientificHook`。hook 返回值的每个字段都是 scientific result/checkpoint 的 preimage；
不得在 hook 内写 live posterior、detector、deque、reference、alarm flag、actuator cursor 或
schedule cursor。随后它只调用共享 `commit_scientific_from_physical`，顺序固定为：

```text
ATTEMPT_PHYSICAL_COMMIT
→ deterministic observation + detached hook
→ immutable observation/posterior/detector/sequence-state artifacts
→ SCIENTIFIC_UNIT_COMMIT
→ materialize + append+fsync pre_checkpoint_event_intents（若有）
→ immutable checkpoint（绑定上述 event_id/event_sha256 和完整 candidate state）
→ CHECKPOINT_COMMIT
→ 一次性 install posterior + detector + sequence state + cursor
```

因此 `commit_scientific_from_physical` 必须接受
`detached_state_candidate` 与 `pre_checkpoint_event_intents`。hook 返回的 intent 只含
immutable semantic payload 和幂等 key，明确不含 `event_id,event_sequence,
previous_journal_event_sha256,event_sha256`；这些 envelope/link 字段在此时尚不可知。
shared helper 在 scientific commit fsync 后读取新的 journal tail，才按顺序 materialize
canonical event envelope并 append+fsync。checkpoint 写入 ordered
`pre_checkpoint_event_refs` 并令
`previous_journal_event_sha256` 指向最后一个事件。空 tuple 时仍显式写 `[]`。同
`physical_commit_sha256 + event kind + triggering_scientific_unit_id + conditional_unit_id +
ordinal` 的 intent 重放必须解析到同一
既有 event；首次 materialize 后完整 event bytes 固定，
同 key 不同 bytes 是 `PERSISTENCE_CORRUPT`。crash 在 event fsync 后、checkpoint 前时，
resume 只补同一 checkpoint，绝不能再领取 conditional ID。

五类 hook 的语义逐项冻结如下：

- `calibration_hook`：只对 valid observation 在 detached posterior 上执行该 method 的冻结
  update；invalid row 保持 posterior 不变但仍记录 scheduled row。每个
  protocol-complete selected proposal 按上述 terminal 分支的同一规则追加
  `attempted_logical_commands`，adaptive decision 同时追加 `planner_history`。A 阶段第 12 条结束时，
  无论该条是否 valid，都把“该条决定后的 candidate posterior + transformer + calibration
  history”写成 immutable `nominal_restore_reference`，其 hash 与本条 posterior-after 同属
  一个 scientific/checkpoint pair；不得在循环后另存 reference。
- `hook.for_algorithm_safety_rejection()` 不是自由 adapter：它必须保留原 hook 的 stage、
  next-cursor 和 `freeze_nominal_reference` flag，只把 observation/update 改成 algorithm-safety
  no-arm outcome并把 rejection-inclusive planner history加入 candidate。特别是 A 阶段第 12 条
  （overall A12）all-rejected 时，仍必须在同一 scientific/checkpoint pair 创建
  `NEW_CANONICAL_PREIMAGE` nominal reference；其 source 精确绑定“未改变的
  posterior-after + 含本次拒绝 decision 的 calibration history”。否则 B 阶段不得开始。
  非 A12 rejection 不得意外创建 nominal reference。
- `monitor_hook`：prediction 必须来自本条开始前的 detached posterior。valid observation
  才把 residual 连同原 scheduled monitor index 送入 CUSUM；invalid observation 只记录
  scheduled gap，不重编号、不伪造 residual。首次 alarm 的 `alarm_handled=true` 必须成为
  触发该 alarm 的同一 shift-state-after。passive/full 同时把 posterior covariance inflation
  `8.0` 写成该 monitor 的 posterior-after，result 固定
  `update_enabled=false,model_update_applied=false,
  posterior_transition_kind=ALARM_INFLATION,factor=8.0`；frozen 不 inflate，固定
  `posterior_transition_kind=NONE,factor=null` 且 posterior before/after逐位相同。三者都不能
  先 commit monitor、随后游离地改 alarm/posterior。
- `recovery_update_hook`：按冻结 method policy 在 detached posterior/history 上完成本条唯一
  update 或 no-update 决策，并把 candidate/history 一起返回；selected adaptive
  command/decision 与 terminal 分支使用同一 append 规则。无论 method 是否更新，都不能
  在 scientific commit 之后再调用 `model.update`。
- `rolling_validation_hook`：posterior 保持不变，把本 scheduled index 的 `VALID/INVALID`、
  metric 和 threshold decision 作为一个 slot 压入长度 4 的 deque；只在本次 candidate deque
  首次满足冻结 recovery rule 时设置 `recovered_at`，之后不可改写。invalid slot 也占自己的
  scheduled 位置。
- `sentinel_hook`：每条都先追加一个 `SentinelScheduledSlot`；第 1 条只持久化
  长度 1 的 partial `sentinel_set_slots`并把 cursor 指向同 set 第 2 条；第 2 条
  用两条已绑定结果计算唯一 `SentinelSetVerdict`。pass 时 cursor 前移到下一 method/sequence；
  fail 时选择 registry 中最低未使用的下一 verification set，在
  `pre_checkpoint_event_intents` 中产生且只产生一个语义 intent
  `CONDITIONAL_UNIT_ACTIVATED{registry_sha256,triggering_scientific_unit_id,
  registry_root_planned_unit_id,conditional_unit_id,ordinal}`；direct trigger 固定为当前失败
  verification set 的第 2 条（可 planned 或 conditional），root 固定为 set 1 第 2 条；
  shared helper 再补 journal envelope/link/hash。cursor 保持
  DISARMED 并指向该
  conditional set 的第 1 条。达到 `maximum_verification_sets` 时不生成事件，cursor 进入
  `PAUSED_SENTINEL_EXHAUSTED`，禁止进入下一 method。

typed scientific-stage failure 或 unknown internal failure 都必须丢弃整个
`ShiftScientificCandidate`：posterior/detector/deque/reference/history/alarm/cursor 全部保持
paired checkpoint 的 before 值；按第 12 节分别进入显式技术重采或 internal review。若
`SCIENTIFIC_UNIT_COMMIT` 已 fsync，则后续错误只能幂等补 protocol events/checkpoint/install，
不得再改 outcome。`require_nominal_restoration_before_next_method()` 因而只能读取已安装的
paired checkpoint，断言 sentinel pass、restored actuator evidence、nominal reference 和
next cursor 一致；它不得计算 verdict、写状态、激活 conditional ID 或前移 cursor。

实现测试必须在每一种 hook 的 detached calculation 前后、scientific fsync 前后、每个
pre-checkpoint event fsync 前后、checkpoint fsync 前后和 live install 前后注入崩溃，比较
uninterrupted run：physical/scientific/event/checkpoint 各恰一份，posterior bytes、CUSUM、
alarm flag、rolling slots、`recovered_at`、nominal reference、sentinel verdict、conditional
activation 和 cursor 全部逐字节相同。另做静态/API test，禁止 SHIFT runner 直接调用
`model.update/inflate_posterior/update_detector/deque.append/save_snapshot` 或写 live cursor。
对 terminal adapter 另外必须有下列独立的 table/property/golden tests：

- `inspect.signature` 断言 `for_terminal_outcome` 只有上述三个 keyword-only 参数；
  `__call__(observation=None)`、terminal 路径二次调 hook、all-rejected 再调 terminal 都失败；
- 对 calibration A1/A12、pre/post monitor、recovery、validation k=1/4/12、sentinel
  set 第 1/2 条和registry-exhausted 分别注入 protocol-complete `RUNTIME_SAFETY`，逐字段
  断言上述 cursor、history、gap、q/deque、reference、verdict和intent；
- 对五类 phase 分别注入 `RUNTIME_TECHNICAL/OPERATOR_CANCELLED/INTERNAL_FAULT`，
  property-test 断言除顶层 immutable result/diagnostic 外所有 after-state bytes/hash 与before完全相同，
  A12 reference仍为 null、cursor未前移且没有 event intent；
- 对上表每个非法 status/reason/complete/retry/phase 组合做拒绝测试，断言在任何
  content-addressed write/journal append 之前失败；
- 以相同 physical commit 在 terminal candidate 前后、scientific result/commit、sentinel
  activation event、checkpoint和install 各点注入 crash，resume 后与 uninterrupted 的
  `ScientificUnitResult`、`ShiftScientificCandidate`、`SentinelScheduledSlot`、journal bytes/hash
  逐位相同，且 adapter 有效调用次数恰为一。

上面 A–F 不能实现为每次进程启动都从 A 顺序执行的普通脚本。
`open_shift_sequence` 从最后一个 scientific/changeover paired checkpoint 恢复
`stage∈{A_CALIBRATION,B_PRE_MONITOR,C_APPLY,D_POST_MONITOR,E_RECOVERY_VALIDATION,
F_RESTORE,F_SENTINEL,COMPLETE}` 及 stage 内 row index。每个 `for` 在真实实现中必须等价于
`while cursor.stage==...: materialize_exact_current_row(); execute_once(); reload_cursor()`；
完成行从不再次 materialize。resume 必须恢复 posterior/transformer、candidate history、
detector CUSUM/latch/last scheduled index、alarm flag、rolling deque、recovered_at、nominal
reference 和 actuator/changeover registry；不得 fresh 或清零。

C/F 如果已有完整 `CHANGEOVER_CHECKPOINT_COMMIT` 直接进入下一 stage；只有 incomplete
changeover 才按 §16.6 恢复矩阵补 marker/checkpoint或 RECOVER_NOMINAL，绝不重新 apply/
restore。已完成 sequence/method 整体跳过；只有全新 sequence 才建 identity prior。
resume scope 使用同 shift-scoped `RESUME_RENEWAL` 和 parent 剩余 quota，不能建第二个
PRIMARY_BATCH。fault-injection 要覆盖 A–F 每个 scientific row 间、APPLY/RESTORE 三 commit
间、sentinel set 两行间及 sequence/method 边界，验证 no duplicate motion/changeover、
posterior/detector lineage 和 cursor 完全一致。

monitor index 只在实际向 detector 提交 valid residual 时调用，但传入的是冻结
scheduled index，允许有 gap，绝不重编号或伪造 residual。无有效 residual 的
protocol-complete monitor 保留为 missed evidence。

上述所有 45 个 primary trial 和 2 个 sentinel 都经过与 NAV 相同的
per-trial `calibration_start_gate`。超出容差时必须 zero/disarm 后回位，
回位 attempt 写 `unit_type=context_return`，不送给 model/detector/endpoint。
回位后重新验证当前 nominal/shifted actuator evidence，禁止回位时偷偷
恢复 payload/surface/transform/task。

`next_planned_changeover_attempt` 不是随机 helper；它只能从第 14.4/16.6 节冻结 registry
领取 APPLY/RESTORE unit 的下一个合法 attempt identity，并以 journal compare-and-swap
持久化 index/retry link。`with_changeover_phase` 只替换 phase/action，unit/kind/index/UID/
retry/parent 必须逐位不变。validator 从 schedule 和 journal 机械重算。apply/restore
及各自 evidence/marker 是 protocol changeover，
不是 primary motion unit，不增加上述 `45 + 2`、不调用 `prepare_attempt/arm`，也不进入
任何 calibration/recovery trial ID。只有随后显式的 motion attempt 才消耗 arm lease。

### 16.3 alarm 的唯一路径

```python
def handle_first_alarm_detached(prior, detection, candidate_posterior):
    candidate_alarm_handled = prior.alarm_handled
    transition_kind = "NONE"
    transition_factor = None
    if detection.alarm and not candidate_alarm_handled:
        if method_id in {"passive", "full"}:
            candidate_posterior.inflate_covariance(8.0)
            transition_kind = "ALARM_INFLATION"
            transition_factor = 8.0
        candidate_alarm_handled = True
    return (candidate_posterior, candidate_alarm_handled,
            transition_kind, transition_factor)
```

该纯逻辑只在 `monitor_hook` 的 detached candidate 内运行；snapshot 由共享 scientific
helper 写入并成为同一 monitor 的 posterior-after。不得从本函数保存文件或修改 live
`model/alarm_handled`。
tracked golden cases 对 frozen/passive/full 的首次 pre/post alarm逐一断言上述 kind/factor/
version/hash组合，防止 frozen 被伪报 inflation或 passive/full 漏掉原子 posterior-after。

pre-shift false alarm 也立即执行相同逻辑。禁止写成
`if context_stage == post_shift and alarm`，否则 policy 已获得真实阶段。

pre-shift alarm 后，post-shift detection endpoint 记为 missed/提前 false alarm，
不能把已 latch 状态算作正确 post-shift detection。

primary false-alarm、detection/delay 和 recovery/rate 全部取 `full` method；
`passive`/`frozen` 的对应量作为 secondary diagnostics。若 full 在 post-shift
monitor index `5..9` 首次 alarm，endpoint delay=`monitor_index-4`，范围 `1..5`。

### 16.4 recovery 的三方法

```python
if recovered_at is not None:
    command = passive_recovery[recovery_index - 1]
    source = "post_recovery_monitor"
    update_enabled = False
elif method_id == "full" and detector.latched:
    command = select_first_safe_task_weighted_ivr()
    source = "active"
    update_enabled = True
else:
    command = passive_recovery[recovery_index - 1]
    source = "fixed"
    update_enabled = method_id == "passive" and detector.latched

# 以下 decision/update 只在 recovery hook 的 detached candidate 内运行；运动与 observation
# 已由 execute_shift_scientific_unit 的 physical/build 阶段完成。
observation = make_blind_policy_observation(committed_full_observation)
if method_id in {"passive", "full"} and detector.latched \
        and update_enabled and observation.valid:
    candidate_blind_model.update(observation)
```

`frozen` 始终不 update。未 detect 时 passive/full 也不 update。达到 recovery 后
剩余 step 继续执行相同 recovery index 的固定安全命令，但不再 update；每步后的
validation 仍执行。这样保持完整预算和运动暴露，不根据结果早停。

### 16.5 validation、target 和缺失值

每个 recovery step 后：

1. recovery 与 validation 是两个独立 scientific units：前者
   `unit_type=shift_recovery`，后者 `unit_type=shift_recovery_validation`，使用不同稳定 ID/
   attempt identity；
2. 用 `validation_commands[(recovery_index-1) % 8]` predict；
3. 执行 held-out trial；
4. 断言 posterior version/hash 不变；
5. 无论 valid 与否，都把该 **scheduled validation slot** 加入长度 4 deque；valid令
   `q=(e_vx²+e_vy²+(0.30*e_wz)²)/3`，observation unavailable/invalid令 `q=0.25²`；
6. step k的 rolling RMSE精确为最近 `min(k,4)` 个 scheduled q 的
   `sqrt(mean(q))`；只有 k≥4、当前 deque 恰含连续四个 scheduled index、四槽全部
   `observation_available=true,observation_valid=true` 且当前 rolling RMSE≤target 才可首次判
   recovered。invalid penalty仍进入 early/terminal RMSE，但任何 unavailable/invalid slot
   都使包含它的四槽窗口不具 recovery 资格，绝不以三个低 q 抵消一次缺测。

sequence target：

```python
target_rmse = clip(pre_monitor_rmse * 1.30, 0.075, 0.140)
```

`pre_monitor_rmse` 对四个 scheduled pre-monitor用同一 q公式；若任一 observation无效，
target仍可确定性计算但该 sequence固定 recovery failure。early=`mean(step 4..9 rolling)`，
terminal=`step 12 rolling`；每个 shift/block先形成 passive-full paired difference，再以block
bootstrap。所有 joint/rolling/target单位为 m/s-equivalent，0.30 m yaw lever arm必须同时出现在
analysis plan/manifest。禁止跨过 invalid slot；也禁止把“窗含任一invalid”整窗硬设0.25，
因为唯一规则是该 slot贡献0.25²后再与其余slot聚合。

### 16.6 四个 actuator

`shift_actuators.py` 定义统一 port：

```python
class ShiftActuator(Protocol):
    def verify_nominal(self, identity: ChangeoverIdentity) -> EvidenceBundleContent: ...
    def apply(
        self,
        identity: ChangeoverIdentity,
        authorization: OperatorGateReceipt,
        pre_evidence: EvidenceBundle,
    ) -> ActuationReceipt: ...
    def verify_shifted(self, identity: ChangeoverIdentity) -> EvidenceBundleContent: ...
    def verify_context(self, identity: ChangeoverIdentity) -> EvidenceBundleContent: ...
    def restore(
        self,
        identity: ChangeoverIdentity,
        authorization: OperatorGateReceipt,
        pre_evidence: EvidenceBundle,
    ) -> ActuationReceipt: ...
    def verify_restored(self, identity: ChangeoverIdentity) -> EvidenceBundleContent: ...
```

`EvidenceBundleContent`、`EvidenceBundle` 和 `ShiftReceipt` 不得留成 Any dict。
`schemas/p8/shift_evidence_content.schema.json` 与 `shift_evidence.schema.json` 固定：

```text
EvidenceBundleContent:
  schema_version,dataset_role,run_id,session_id,block_id,method_id,shift_id,
  changeover_unit_id,changeover_kind,changeover_attempt_index,changeover_uid,
  retry_of_changeover_uid,parent_changeover_uid,action,phase,
  changeover_attempt_identity_sha256,changeover_phase_identity_sha256,context_state,
  captured_utc,captured_monotonic_ns,instrument_id,
  instrument_calibration_utc,items[],content_preimage_sha256
EvidenceBundle:
  schema_version,content_path,content_preimage_sha256,
  approval_request_path,approval_request_sha256,
  operator_approval_path,operator_approval_sha256,
  safety_operator_approval_path,safety_operator_approval_sha256,bundle_sha256
EvidenceItem:
  evidence_type,path,file_sha256,measured_value,unit,
  installation_frame,installation_coordinates,notes
ActuationReceipt:
  dataset_role,run_id,session_id,block_id,method_id,shift_id,
  changeover_unit_id,changeover_kind,changeover_attempt_index,changeover_uid,
  retry_of_changeover_uid,parent_changeover_uid,action,
  changeover_attempt_identity_sha256,actuation_phase_identity_sha256,
  accepted,effective_monotonic_ns,pre_bundle_sha256,
  operator_gate_receipt_sha256,readback_sha256,activation_record_sha256,
  reason_codes,receipt_sha256
ShiftReceipt:
  dataset_role,run_id,session_id,block_id,method_id,shift_id,
  changeover_unit_id,changeover_kind,changeover_attempt_index,changeover_uid,
  retry_of_changeover_uid,parent_changeover_uid,action,
  changeover_attempt_identity_sha256,precheck_phase_identity_sha256,
  actuation_phase_identity_sha256,postcheck_phase_identity_sha256,
  accepted,effective_monotonic_ns,
  pre_bundle_sha256,post_bundle_sha256,actuation_receipt_sha256,
  operator_gate_receipt_sha256,
  readback_sha256,status,terminal_phase,failure_code,protocol_complete,effective_for_protocol,
  context_before,context_after,actuator_cursor_before,actuator_cursor_after,
  reason_codes,receipt_sha256
```

`EvidenceBundleContent.schema_version=p8.shift-evidence-content.v1`；
`content_preimage_sha256=sha256(JCS(content 排除 content_preimage_sha256))`。verify port只能返回
该 approval-free content，coordinator先把它写入
`changeover_evidence_contents/<raw_sha256>.json` 并 fsync，随后调用第 6.5.2 同一 factory（或
等价 library API）生成 `purpose=CHANGEOVER,subject_kind=EVIDENCE_BUNDLE_CONTENT,
subject_id=changeover_uid/phase,subject_sha256=content_preimage_sha256` request。两人签名后，
唯一 `finalize_evidence_bundle(content_ref,request_ref,operator_approval,
safety_operator_approval)` 才可构造 final `EvidenceBundle`；
`bundle_sha256=sha256(JCS(bundle 排除 bundle_sha256))`。finalizer重算 content identity/hash、
request purpose/subject/TTL、两签 person/key/role/nonce，且 bundle path解析到同 run content。
precheck与postcheck各自 content/phase/hash不同，必须各有自己的 request/两签；不得把 pre签名
复制给 post。verify函数不得返回含空 approval的“半成品 EvidenceBundle”，signer也不得接受
尚未持久化/strict-valid的 content。这样顺序唯一为
`verify → content commit → approval request → two approvals → final bundle → gate/receipt`，无
bundle/approval self-cycle。

`EvidenceBundleContent/EvidenceBundle/ActuationReceipt/ShiftReceipt` **禁止**出现
`attempt_uid/scientific_unit_id/unit_type`。changeover 是
非运动 protocol event，不得构造 fake `AttemptIdentity`。`changeover_uid` 在整个
delivery 全局唯一；同一次物理 apply 或 restore 的 precheck/actuate/postcheck 共用一个
attempt UID。`ChangeoverIdentity.action` 只允许导出兼容值 `apply|restore`，验证阶段机械映射为：

```text
verify_nominal  -> action=apply,   phase=precheck
apply           -> action=apply,   phase=actuate
verify_shifted  -> action=apply,   phase=postcheck
verify_shifted  -> action=restore, phase=precheck  # restore 前重新采当前 shifted evidence
restore         -> action=restore, phase=actuate
verify_restored -> action=restore, phase=postcheck
verify_context  -> action=restore, phase=precheck  # RECOVER_NOMINAL，或 linked RESTORE retry
```

每个 actuator method 必须 assert 上述 identity/action/phase；不得从 method 名另造
export action。`apply` 只接受 `changeover_kind=APPLY`；planned `restore` 只接受 RESTORE，
补偿 restore 只接受 RECOVER_NOMINAL。RESTORE index=1 的 precheck 必须
`verify_shifted`；RESTORE index>1 只有在它引用的失败前序 attempt 已有 complete
RECOVER_NOMINAL child 时才可 `verify_context`，且 context 必须为 nominal。apply/restore 前由 `OperatorGate.authorize_changeover(identity,
evidence_sha256=pre_evidence.bundle_sha256)` 返回已 fsync 的双人 receipt，actuator 必须
核对 receipt identity/hash 后才动作；这里 `pre_evidence` 必须是 finalized
EvidenceBundle，不是 content。actuator 返回 immutable `ActuationReceipt`；orchestrator 对
postcheck content完成独立 request/两签并得到 finalized post bundle后，才构造同时绑定
pre/post/readback 的最终
`ShiftReceipt`；随后只能交给下述 `commit_changeover_transaction`。单独写 receipt 文件
不等于 protocol cursor 已完成。`ChangeoverEvent`、`ChangeoverMarker.msg` 和
`ShiftReceipt` 使用同一 `changeover_uid`；它们不进入 45 个 primary motion units、
2 个 sentinel、posterior version 或 scientific denominator。
`ShiftReceipt.operator_gate_receipt_sha256` 与
`actuation_receipt_sha256/effective_monotonic_ns/post_bundle_sha256/readback_sha256` 依
failed phase conditional nullable；complete 必须有 gate/actuation/effective/post，R1
complete 还必须有 readback，R2–R4 readback 固定 null。pre-gate failure 的 gate/operator
字段由 exporter 留空，不能生成占位 receipt。
R1 actuation 成功后的 `ActuationReceipt.activation_record_sha256` 必须等于
`SetCommandTransform.srv` response，R2–R4 及 pre-actuation failure 固定 null。
failure receipt 也必须交给同一 `commit_changeover_transaction`，完成 RESULT→MARKER_ACK→
CHANGEOVER_CHECKPOINT 三步后才可激活 recovery；失败只改变 receipt status/effective flag，
不允许使用较弱的持久化路径。

changeover 有独立的 durable non-motion 事务，不能等下一条 scientific trial checkpoint
“顺便记住”。`commit_changeover_transaction` 的唯一顺序为：

`derive_changeover_state_after(prior_checkpoint_state, receipt)` 是纯函数，禁止 caller传
自报 cursor。receipt 的 `context_before/actuator_cursor_before` 必须等于 prior paired
checkpoint；after字段必须等于下表函数输出，否则拒绝：

| kind/result | prior context | context_after | actuator fields | schedule cursor after |
|---|---|---|---|---|
| APPLY complete+effective | NOMINAL | SHIFTED | last_effective=本 unit/UID；in_progress=null；evidence=post bundle；R1 readback=receipt，其余null | `D_POST_MONITOR/1` |
| RESTORE complete+effective | SHIFTED；linked no-op可为NOMINAL且有RECOVER parent proof | NOMINAL | last_effective=本 unit/UID；in_progress=null；evidence=post bundle；R1 identity readback或其余null | `F_SENTINEL/1` |
| RECOVER_NOMINAL complete+non-effective | UNKNOWN或receipt证明的SHIFTED/NOMINAL | NOMINAL | last_effective保留 prior planned effective值；in_progress=null；evidence=post bundle；R1 identity readback或其余null | `RETRY_PARENT_CHANGEOVER/<parent_uid>` |
| planned APPLY/RESTORE failure at precheck、尚未actuate | 逐位取 prior | prior context | last_effective/evidence/readback保留 prior；in_progress=本 planned unit/UID | `RECOVER_NOMINAL_REQUIRED/<failed_planned_uid>` |
| planned APPLY/RESTORE failure at actuate/postcheck或phase不确定 | 任意合法 prior | UNKNOWN | last_effective保留 prior；in_progress=本 planned unit/UID；evidence=最后 hash-valid pre/post（无则prior）；R1 readback取receipt若存在，否则null | `RECOVER_NOMINAL_REQUIRED/<failed_planned_uid>` |
| RECOVER_NOMINAL failure（任意 phase） | prior绑定同一 original parent planned UID | precheck且未actuate则prior，否则UNKNOWN | last_effective保留 prior；in_progress保持 original parent planned unit/UID；保存本 recovery failure UID作retry tail | `RETRY_RECOVER_NOMINAL/<original_parent_planned_uid>` |

planned APPLY/RESTORE complete要求
`status=complete,protocol_complete=true,effective_for_protocol=true`；RECOVER_NOMINAL
complete固定 `complete,true,false`，不得进入 planned effective denominator。failure三者
固定为 `technical_abort|safety_abort,false,false`，`terminal_phase` required；status由
handoff §14.2 failure-code 类别机械决定，不允许 caller自报。failure即使precheck看似未动作也统一
走 recovery verification，避免猜 context。after cursor、context、last/in-progress IDs、
evidence/readback逐项写入 receipt、RESULT_COMMIT和 shift-state-after；同 receipt+prior只能
产生一种 canonical bytes。

strict typing：`status∈{complete,technical_abort,safety_abort}`；complete令
`terminal_phase=null,failure_code=null,protocol_complete=true`，两类 abort 令
`terminal_phase∈{precheck,actuate,postcheck,unknown}`、failure code required且
`protocol_complete=false`。这是 auxiliary changeover outcome 的成功完成 flag；failure虽为
false，仍必须完整执行 RESULT→MARKER_ACK→CHANGEOVER_CHECKPOINT 并进入冻结 recovery cursor，
不走 scientific `RERUN_TECH`。
`context_before/context_after∈{NOMINAL,SHIFTED,UNKNOWN}`。EvidenceBundle的
`context_state` 使用同一 enum：verify_nominal/restored=NOMINAL、verify_shifted=SHIFTED、
无法完成验证=UNKNOWN。`actuator_cursor_before/after` 不是自由 string，精确对象为
`{stage,changeover_unit_id,changeover_kind,attempt_index,changeover_uid,
original_parent_planned_uid,state}`，state只允许 `PENDING|RECOVERY_REQUIRED|
RETRY_RECOVERY|RETRY_PARENT|COMPLETE`；planned 的 parent为自身 UID，RECOVER必须保持原
planned UID。RECOVER失败只递增同 compensating unit 的 attempt index、`retry_of`指上一
recovery UID，绝不能把 recovery UID登记为新 parent或递归分配新 recovery unit。

```text
0. 从前一 paired checkpoint克隆 DetachedShiftState，验证 receipt identity/action/pre refs，
   调上述纯函数并核对receipt before/after字段，构造唯一 detached shift-state-after
1. content-addressed write + file/directory fsync immutable ShiftReceipt 和
   shift-state-after artifact（live state仍不变）
2. append+fsync CHANGEOVER_RESULT_COMMIT{
     changeover_uid,changeover_attempt_identity_sha256,
     precheck/actuation/postcheck_phase_identity_sha256,shift_receipt_path/hash,
     status,protocol_complete,effective_for_protocol,context_before/context_after,
     actuator_cursor_before/after,
     shift_state_before_path/hash,shift_state_after_path/hash,
     nominal_restore_reference_path/hash,previous_protocol_checkpoint_sha256}
3. 构造 typed ChangeoverMarkerRecord，以 result event_id/hash 为 idempotency key调用
   P8Recorder.commit_changeover_marker；它向当前 segment 发布 ChangeoverMarker、fsync
   marker index并返回 ChangeoverMarkerAck
4. append+fsync CHANGEOVER_MARKER_ACK{
     ChangeoverMarkerAck 的全部字段}
5. 写 checkpoint_kind=CHANGEOVER 的 immutable protocol checkpoint；posterior path/hash/
   version与 nominal-reference path/hash逐位继承前一 checkpoint，shift-state-before/after
   逐位等于 RESULT_COMMIT，只通过 after state 更新 actuator context、changeover registry
   cursor、schedule stage/cursor、journal tail和上述 result/marker hashes；planner/
   transition-trace/scientific/inventory refs为 null
6. append+fsync CHANGEOVER_CHECKPOINT_COMMIT{
     checkpoint path/hash/sequence/previous hash,
     changeover_result_commit_sha256,changeover_marker_ack_sha256}
7. atomic install shift-state-after + live protocol cursor；此后才可 preflight 下一 motion unit
```

同 result event 在 crash 后可发布到新 segment；recorder 用 event ID 去重，同一 segment
重复只返回原 ack，跨 segment 重放在 index 中标 `replayed=true` 且 exporter 选择第一个
hash-valid ack，绝不再次 actuator.apply/restore。恢复矩阵是机械的：

```text
receipt 文件存在、无 RESULT_COMMIT：
  若 pre/actuation/post hashes、operator gate、zero/context readback 全部完整，幂等补同一
  RESULT_COMMIT；否则封 failure receipt，走 RECOVER_NOMINAL，绝不猜已完成。
RESULT_COMMIT、无 MARKER_ACK：不做物理动作；向新/当前 segment重发同 event并补 ACK。
RESULT+ACK、无 CHANGEOVER_CHECKPOINT_COMMIT：从两 commit重建同一 checkpoint。
三者配对、live pointer旧：只安装该 checkpoint。
无完整 result且 evidence显示 mid-actuation：先 zero/motion-inhibit，封 failed attempt，
  激活 RECOVER_NOMINAL；绝不重放原 APPLY/RESTORE。
```

resume 先从最后 hash-valid protocol checkpoint 重放 journal tail，比较
`changeover_uid/result/marker/checkpoint`，再决定上述分支；不能仅凭上一个 scientific
checkpoint 的 stale `context_state` 重复物理动作。`CHANGEOVER_RESULT_COMMIT`、
`CHANGEOVER_MARKER_ACK`、`CHANGEOVER_CHECKPOINT_COMMIT` 的 event ID/hash 与 state-machine
cursor 都必须进入 schema/golden/fault-injection tests。每个步骤前后崩溃测试断言物理
actuation count≤1、marker 可幂等重放、posterior/nominal reference不变、shift-state artifact
write/result/checkpoint/install无 torn state、下一 motion只在第 6 步后开放。failure与
RECOVER_NOMINAL也必须走相同 before/after state binding，不能只给 success 写 state。

changeover unit 与 attempt identity 冻结为：

```text
planned unit:
{run}/SHIFT/{shift}/{block}/{method}/CHANGEOVER/{APPLY|RESTORE}
planned attempt UID:
{changeover_unit_id}/ATTEMPT/{changeover_attempt_index:03d}

compensating unit:
{run}/SHIFT/{shift}/{block}/{method}/CHANGEOVER/RECOVER_NOMINAL/
FROM_{APPLY|RESTORE}_{failed_planned_attempt_index:03d}
compensating attempt UID:
{changeover_unit_id}/ATTEMPT/{changeover_attempt_index:03d}
```

APPLY/RESTORE unit 必须在 `planned_changeover_unit_ids`；所有可能的 compensating unit
必须按 `maximum_changeover_attempts` 在
`conditional_changeover_recovery_unit_ids` 预展开。planned attempt 的
`parent_changeover_uid=null`；同 unit 第 2 次起 `retry_of_changeover_uid` 指向上一
attempt。RECOVER_NOMINAL 的 `parent_changeover_uid` 恒指触发它的失败 planned attempt，
自己的 technical retry 仍用 retry link。UID 全局唯一且每个 unit index 从 1 连续递增。
领取 recovery unit 前必须 append+fsync
`CHANGEOVER_RECOVERY_ACTIVATED{registry_sha256,parent_changeover_uid,
changeover_unit_id}`；相同 parent 幂等映射到同一 unit，不同映射判 corruption。

planned attempt 只有完整 pre/actuate/postcheck 并 fsync `ShiftReceipt(status=complete,
protocol_complete=true)` 才完成；每个 planned unit 的第一个 complete attempt 机械设
`effective_for_protocol=true`。technical/safety abort 全保留且 false；RECOVER_NOMINAL
即使 complete 也固定 `effective_for_protocol=false`。mid-changeover crash 的唯一恢复为：

`finalize_failed_changeover_attempt` 在任何 phase error/crash 后先 zero/motion-inhibit，
以现存的 evidence/actuation hashes 写 immutable failure receipt 和 journal event；尚未产生
的 post/readback hash 为 null，不能伪造。该 failure row fsync 前不得领取 recovery unit。
其签名必须显式接收
`operator_gate_receipt: OperatorGateReceipt | None,failed_phase`：若 precheck/evidence 在
gate 前失败，receipt/operator IDs 必须 null、`gate_passed=false`；若 authorize 已成功或
已进入 actuate/postcheck，则 receipt required 且必须已向 watchdog 注册。不能为了满足
non-null schema 伪造“系统 operator”，也不能在已有物理动作后丢掉 gate hash。最终导出
严格遵守 handoff §12.9.1 的 conditional nullable 规则。

```text
失败 planned attempt → technical_abort / SOFTWARE_PROCESS_CRASH
→ 领取其预注册 RECOVER_NOMINAL unit，verify_context → restore → verify_restored
→ nominal evidence 通过
→ 原 planned unit 用递增 attempt index 闭合：APPLY 从 nominal precheck 重做；
  RESTORE 以 linked nominal precheck 执行双人批准的 idempotent restore/no-op 再 postcheck
```

补偿动作的调用合同精确为：

```python
recovery = activate_recover_nominal_identity(failed_planned_attempt_record)
pre = actuator.verify_context(
    with_changeover_phase(recovery, action="restore", phase="precheck")
)
gate = operator_gate.authorize_changeover(
    with_changeover_phase(recovery, action="restore", phase="actuate"),
    evidence_sha256=pre.bundle_sha256,
)
require_equal(
    watchdog.register_operator_gate_receipt(gate), gate.receipt_sha256
)
actuation = actuator.restore(
    with_changeover_phase(recovery, action="restore", phase="actuate"),
    gate,
    pre,
)
post = actuator.verify_restored(
    with_changeover_phase(recovery, action="restore", phase="postcheck")
)
receipt = commit_changeover_transaction(actuation, pre, post)
require_complete_nominal_recovery(receipt, post)
```

`verify_context` 可报告 `nominal|shifted|partial|unknown`；后 3 种必须由对应 actuator 的
安全人工流程恢复，nominal 可产生经过双人 gate 的 idempotent no-op actuation receipt。
任何状态都不能跳过 postcheck。

原 planned unit 的 retry 分支固定为：

```python
retry = next_planned_changeover_attempt_after_recovery(recovery_receipt)
if retry.changeover_kind == "APPLY":
    pre = actuator.verify_nominal(
        with_changeover_phase(retry, action="apply", phase="precheck")
    )
    # 随后执行标准 apply → verify_shifted
elif retry.changeover_kind == "RESTORE":
    pre = actuator.verify_context(
        with_changeover_phase(retry, action="restore", phase="precheck")
    )
    require_context_state(pre, "nominal")
    # 随后执行双人批准的 idempotent restore/no-op → verify_restored
else:
    raise ProtocolCorruption("recovery cannot close this planned kind")
```

该 RESTORE retry 仍是原 planned RESTORE unit 的递增 attempt，
`retry_of_changeover_uid` 指失败 RESTORE；complete 后可成为该 planned unit 唯一
`effective_for_protocol=true` row。RECOVER_NOMINAL row 自身仍为 false，因此没有一行
同时冒充两个 unit。

恢复 unit 失败时只可在同 unit 上显式递增 attempt；超过
`maximum_changeover_attempts`、registry 缺失或 nominal 未验证都保持 DISARMED 并终止
当日。不得复用失败 UID、提前使用 planned RESTORE UID补偿 APPLY，或让 recovery row
占 10,800/480/11,280 任一 motion count。

EvidenceBundle 必须引用一个 operator与一个safety_operator的第6.5.2节HumanApproval，
person/key不同。hash 无循环的精确定义为：

```text
content_preimage = JCS(EvidenceBundle 排除 approval request/两approval refs/bundle_sha256)
content_preimage_sha256 = sha256(content_preimage)
approval request: purpose=CHANGEOVER,subject_kind=EVIDENCE_BUNDLE_CONTENT,
                  subject_id=changeover_uid/phase,
                  subject_sha256=content_preimage_sha256
两份 HumanApproval.approval_request_sha256相同并分别有效验签
bundle_preimage = JCS(已含 request与两approval ContentAddressedRef 的 EvidenceBundle
                      排除 bundle_sha256)
bundle_sha256 = sha256(bundle_preimage)
```

两个人签的是同一个 content preimage；任一 approval 后不得回头修改items。changeover
OperatorGate验证两 approval和content preimage后，receipt再绑定最终 bundle hash，不要求第三/
第四次签字。`bundle_sha256` 连同原始照片/称重/摩擦代理文件的 file hash
一起进 release manifest。R2 要求 added/total mass、bracket-frame COM xyz、
称/安装照片；R3 要求 material/batch/surface state/friction proxy/instrument/
照片；R4 要求 R2/R3 子 bundle 和 pre/post task file hash。

`ActuationReceipt.receipt_sha256` 与 `ShiftReceipt.receipt_sha256` 都精确为
`sha256(canonical_json(asdict(receipt) 排除 receipt_sha256))`，沿用第 5.3 节 finite
float/UTF-8/sorted-key/no-unknown-key 规则。ShiftReceipt 的
`actuation_receipt_sha256` 必须等于对应 immutable ActuationReceipt hash，pre/post bundle
和 base/三 phase identity hashes 必须逐项回链；同一 changeover UID+attempt index 的相同
bytes重放幂等，不同 bytes/hashes 判 integrity corruption。EvidenceBundle、Actuation、
ShiftReceipt 各提供 tracked golden canonical bytes/hash vector，覆盖 nullable pre-gate
failure、R1 success 与 R2 success。

| Shift | 代码职责 | 人工/物理职责 |
|---|---|---|
| R1 | 在 relay 中原子启用冻结 A；readback/hash；二次 wire safety | 安全员确认零与人员清场 |
| R2 | inhibit motion、称重/坐标/照片文件存在与 hash、operator 双确认 | 安装快拆载荷、二次防脱、测量 COM |
| R3 | inhibit motion、surface ID/batch/measurement/photo evidence gate | 铺设/切换预测中低摩擦材料 |
| R4 | 验证小载荷+friction+`T_pre/T_post` hashes，在一个 marker 后生效 | 完成所有物理项并双确认 |

R2–R4 的代码不得假装能够自动称重或判断材料；缺少现场 evidence 就保持
motion-inhibited。R4 的 task profile 是可见部署任务输入，detector 仍看不到
profile ID 或 marker；论文必须称其为“可见 task change + 隐藏 dynamics change”
混合条件。

### 16.7 nominal restore sentinel

每个 method sequence 后：identity R1、卸载/恢复 payload、恢复 nominal surface/
task，再执行 2 个冻结 sentinel。`restore_sentinel.csv` 必须恰有：

```csv
sentinel_id,source_table,source_command_id,profile_id
SENTINEL_01,pre_monitor.csv,SHIFT_PRE_MON_01,p8_trial_4s
SENTINEL_02,pre_monitor.csv,SHIFT_PRE_MON_04,p8_trial_4s
```

因此 `pre_monitor.csv` 的 4 行 ID 必须精确为
`SHIFT_PRE_MON_01..04`。sentinel 使用同一 0.6/0.8/2.0/0.6 s profile，
`source=nominal_restore_sentinel`、`unit_type=restore_sentinel`，且绝不 update model/
detector。schedule 中每个 sequence 预留两个 sentinel slot/template，但实际
`scientific_unit_id` 必须包含 verification set：
`SHIFT/{shift}/{block}/{method}/SENTINEL/{verification_set_id}/{sentinel_id}`。
初始 set 固定 `verification_set_id=1`。

比较对象不是 shift-adapted posterior，而是第 16.2 节在 12 个 nominal
calibration 后、任何 pre-monitor alarm/inflation 前保存的只读
`nominal_restore_reference` 快照。`nominal_restore_thresholds.yaml` 顶层字段精确为：

```yaml
schema_version: p8.nominal_restore.v1
require_both_valid: true
maximum_joint_rmse_mps_equivalent: REQUIRED_BEFORE_ARM
maximum_abs_axis_residual_vx_vy_wz: REQUIRED_BEFORE_ARM
maximum_start_position_error_m: REQUIRED_BEFORE_ARM
maximum_start_yaw_error_rad: REQUIRED_BEFORE_ARM
stationary_window_s: REQUIRED_BEFORE_ARM
maximum_stationary_speed_mps: REQUIRED_BEFORE_ARM
required_control_mode: REQUIRED_BEFORE_ARM
required_gait_id: REQUIRED_BEFORE_ARM
maximum_reference_gap_s: REQUIRED_BEFORE_ARM
forbid_any_safety_event: true
```

CONFIRM 中所有占位必须换成 DEV 冻结数值。对 2×3 residual matrix
`E[i,:]=observed_mean[i,:]-nominal_snapshot.predict(model_input[i]).mean`，
令 `E_equiv[:,2]=0.30*E[:,2]`、其余两轴不变；精确 pass 公式为：两个 observation valid，
`sqrt(mean(E_equiv**2)) <= maximum_joint_rmse_mps_equivalent`，每轴
`max(abs(E[:,axis]))`
不超过三轴阈值，并同时通过 pose/stationary/mode/gait/reference/safety gate。
joint threshold单位为 m/s-equivalent；轴向阈值仍依次为 m/s,m/s,rad/s。

失败时不删前一 sequence；立即保持 DISARMED，修复 context 后以递增
`verification_set_id` 重做完整两条。新 set 的两个 ID 是两个新的
`scientific_unit_id`，均为 `attempt_role=PRIMARY,attempt_index=1,
retry_of_attempt_uid=None`，不是旧 sentinel unit 的 outcome-based retry。只有同一
verification set 内发生 handoff §14.2 客观 technical failure 时，才保持该
scientific unit ID 并使用 `RERUN_TECH`/新 attempt UID。所有失败/通过集均导出，
不选“最好一次”。额外 verification set 不增加预注册的 480 planned sentinel slot
计数，但 manifest 必须另报实际 verification units/attempts。超过冻结
`maximum_verification_sets` 则终止当日。只有最后完整集 pass 才可启动
下一 method。

### 16.8 SHIFT cardinality assertion

CONFIRM preflight 写出：

```json
{
  "shifts": 4,
  "blocks_per_shift": 20,
  "methods": 3,
  "sequences": 240,
  "primary_motion_trials": 10800,
  "initial_planned_restore_sentinel_units": 480,
  "actual_restore_sentinel_units": "480 + 2 * activated_conditional_sets",
  "actual_restore_sentinel_attempts": ">= actual_restore_sentinel_units",
  "planned_motion_units": 11280
}
```

---

## 17. Recorder、journal、posterior 和 crash resume

### 17.1 在线 source of truth

在线证据由五部分组成：

```text
rosbag2 raw channels
append-only event_journal.jsonl
atomic posterior snapshots
attempt ledger + video/reference indices
immutable scientific result + per-unit bag-range inventory/checkpoint
```

CSV 是离线导出物，不是在线唯一真相。禁止只写汇总 CSV 后删除 bag。
物理事实以 `ATTEMPT_PHYSICAL_COMMIT` 为权威；observation、model outcome、protocol
completeness、retry 和 selection 以 `SCIENTIFIC_UNIT_COMMIT` 为权威。前者不能冒充
后者，ledger 行必须同时验证两条 commit link。

### 17.2 bag 粒度

每个 `block/method`（NAV）或完整 method sequence（SHIFT）使用一个 bag，trial/
episode 用 marker 和时间范围索引。不要每 4 s 重启 recorder。bag 必须在第一个
attempt marker 前启动，并在最后 zero-confirm marker 后停止；bag split 大小/
时间在 DEV 中冻结。

进程 crash/resume 后绝不向旧 rosbag2 directory 追加。同一 logical bag
group 新建不可变 `segment_000N/`，`bag_segment_index.json` 以
`segment_ordinal,boot_id,resume_epoch,start/end_monotonic_ns,storage_id,
segment_sha256,metadata_sha256,preceding_idle_gap_reason` 排序。ordinal 必须从 0
严格连续且时间区间不得重叠；crash、operator gate、换电或 resume 造成的 segment
间 idle time gap 是合法事实，必须保留并写 reason，不能伪造连续采样。只有 ordinal
gap/duplicate、时间 overlap，或一个 attempt 的 START→FINALIZED marker 区间内 required
channel 出现没有对应 technical event/quality reason 的 gap 才报错。

attempt finalize 时只提交 `BagRangeRef`；bag group 最后 zero-confirm 后
`seal_group()` 才计算 segment/metadata hash，写新的 content-addressed
`bag_segment_index_<hash>.json` 并 journal `BAG_GROUP_SEALED`。delivery exporter 通过
`bag_group_id+segment_id+range` join sealed index；不得回写旧 attempt artifact 或给
未封口 directory 填 provisional hash。

每个 scientific unit（包括 no-update/invalid/safety/technical/cancellation）在写
`SCIENTIFIC_UNIT_COMMIT` 前必须写一份 immutable、content-addressed range snapshot：

```text
<run_root>/bag_range_inventory/
  bag_range_inventory_s<inventory_sequence:020d>_<inventory_sha256>.json

schema_version == "p8.bag-range-inventory.v1"
run_id,inventory_sequence,previous_inventory_sha256,inventory_sha256
bag_group_id,through_scientific_unit_id,created_utc
ranges[]:
  identity,physical_commit_event_sha256,segment_id,
  start_monotonic_ns,end_monotonic_ns,start_marker_sha256,end_marker_sha256,
  attempt_artifact_uri,raw_uri
segments[]:
  segment_id,segment_ordinal,boot_id,resume_epoch,uri,state,
  start_monotonic_ns,end_monotonic_ns,segment_sha256,metadata_sha256
```

`inventory_sha256` 的 preimage 排除自身；`ranges` 按 physical commit sequence，
`segments` 按 ordinal 排序。`state` 只允许 `OPEN|SEALED|RECOVERED_SEALED`；OPEN 时
end/hash 字段为 null，其他状态必须 non-null。snapshot 只绑定截至该 unit 已 durable
commit 的 range，并可合法描述仍打开的 group/segment；它**不依赖** group 末尾才出现的
`bag_segment_index`。每个 `SCIENTIFIC_UNIT_COMMIT` 和紧随其后的
`CHECKPOINT_COMMIT` 都绑定同一 inventory path/hash/sequence。

group 最终 seal 后 exporter 用 `(bag_group_id,segment_id)` 将每个旧 snapshot 的 range
join 到 final `bag_segment_index_<hash>.json`，并验证 range 落在 segment 时间界内、
marker/hash 一致。crash/resume 可从 checkpoint 引用的 OPEN snapshot 恢复：旧进程的
open directory 只读恢复并 seal 为 `RECOVERED_SEALED`（无法恢复则按 exact technical
code fail），新进程从下一 ordinal 新建 segment；logical group 和已经 commit 的 range
继续有效，不要求为了每个 unit 提前 seal 整组 bag。

### 17.3 hash-chain journal

每个 JSONL event 至少含：

```text
schema_version,event_id,event_sequence,boot_id,run_id,identity_kind,
attempt_uid,changeover_uid,
source_timestamp_ns,receive_timestamp_ns,monotonic_ns,event_type,
source_commit,config_sha256,schedule_sha256,payload,
previous_event_sha256,event_sha256
```

`identity_kind=attempt` 时 `attempt_uid` non-null、`changeover_uid=null`；
`identity_kind=changeover` 时相反，且 payload 必须含完整 `ChangeoverIdentity`。run-level
commit（例如 genesis）两者均 null。这样 changeover 不需要 fake attempt identity。

每行 canonical JSON，写入后 `flush+fsync`。精确 preimage 为“该行包含
`previous_event_sha256` 在内的全部字段，但排除 `event_sha256`”的 canonical JSON
bytes；`event_sha256=sha256(preimage)`。因此 identity、event type、timestamps、
source/config/schedule hash 和 payload 都受保护，不是只 hash payload。第一行的
`previous_event_sha256` 固定 64 个 `0`。重放时 sequence gap、hash break、duplicate
ID、non-canonical serialization 均失败。

### 17.4 posterior 原子保存

```text
open same-directory unique `.<runtime-id-hash>.<version>.<uuid>.tmp` binary handle
→ deterministic NPZ serialization directly to that handle（禁止让 NumPy 自动追加 `.npz`）
→ flush+fsync file → compute full SHA-256 from temp bytes
→ atomic rename to `posterior_vNNNN_<full-sha256>.npz`
→ fsync directory → reopen并核对 full SHA-256
→ 保持 candidate，不更新 live pointer/index
```

同 final path 已存在且 full bytes 相同则幂等复用；同名但 full hash/bytes 不同立即判
collision/corruption。content hash 未算出前禁止把未知 prefix 写进 temp 名。

每-scope initial v0000、每次 valid model update、inflation 后都保存。validation/navigation/
monitor no-update 不得创建虚假 version；可写 marker 引用现有 version。
只有 hash-valid `RUNTIME_STATE_INITIALIZED_COMMIT` 或 `SCIENTIFIC_UNIT_COMMIT` 引用且有
配对 `CHECKPOINT_COMMIT` 的 snapshot 才可成为下一 unit 的 live posterior；CHANGEOVER
checkpoint 只延续原 posterior。crash 遗留的未提交 candidate 不删除，在 replay 中标为
orphan；content-addressed suffix 保证同 version 重写不覆盖它。每个 initial v0000 由
第 13.1.1 节自己的 `RUNTIME_STATE_INITIALIZED_COMMIT` + INIT checkpoint绑定；alarm inflation 必须作为触发它的 monitor
scientific result 的 posterior-after，而不是游离的额外 live update。

posterior 不是唯一需要提交的运行状态。每个 scientific unit 后写不可变、
content-addressed checkpoint：

```text
serialize state → protocol_checkpoint_sNNNN_<content-hash-prefix>.json.tmp
→ fsync file → atomic rename → fsync directory → verify full SHA-256
→ append+fsync CHECKPOINT_COMMIT{
       checkpoint_kind=SCIENTIFIC,path,sha256,sequence,previous_checkpoint_sha256,
       initialization_commit_sha256,initialization_result_path,
       initialization_result_sha256,scientific_unit_commit_sha256,
       changeover_result_commit_sha256,changeover_marker_ack_sha256,
       posterior_sha256,
       bag_range_inventory_path,bag_range_inventory_sha256,
       bag_range_inventory_sequence}
→ 可选 atomic replace protocol_checkpoint_current.json pointer
```

上例显示 SCIENTIFIC branch；INIT/CHANGEOVER 按本节下方 conditional rule切换 required/null，
不是伪填 scientific hash。

在写 checkpoint 前，executor 已按第 12 节 append+fsync
`SCIENTIFIC_UNIT_COMMIT{scientific_result_path/hash,physical_commit_event_sha256,
unit_artifact_kind,unit_artifact_path/hash,planner_decision_path/hash,
posterior_before/after_path/hash,posterior_before/after_version,
posterior_transition_kind,posterior_transition_factor,
method_state_before/after_path/hash,shift_state_before/after_path/hash,
nominal_restore_reference_before/after_path/hash,
bag_range_inventory_path/hash/sequence,transition_trace_path/hash}`。随后
`unit_artifact_kind` 只允许 `TRIAL_OBSERVATION|NAV_EPISODE_METRICS|NONE`：trial observation
与 NAV metrics 分别要求对应 immutable path/hash，physical outcome 无可用 observation
时为 NONE 且 path/hash null。不得同时填 observation 和 episode metrics 两套条件列。
`CHECKPOINT_COMMIT.scientific_unit_commit_sha256` 必须引用它。一个 scientific commit
最多配一个 checkpoint；同 hash 重放幂等，不同 checkpoint 直接 integrity failure。

pointer 不是权威；resume 认 journal 中最后一个完整且顺序配对的
`RUNTIME_STATE_INITIALIZED_COMMIT → CHECKPOINT_COMMIT`、
`SCIENTIFIC_UNIT_COMMIT → CHECKPOINT_COMMIT` 或第 16.6 节
`CHANGEOVER_RESULT_COMMIT → CHANGEOVER_MARKER_ACK →
CHANGEOVER_CHECKPOINT_COMMIT`。crash 在 scientific commit 前，从
physical raw 确定性重建 scientific candidate；crash 在 scientific 与 checkpoint 间，
只补相同 checkpoint；commit 前留下的文件保留为 orphan，不覆盖前一 checkpoint。
checkpoint 内容为：

```text
schema_version,checkpoint_kind,run_id,resume_epoch,last_committed_unit_id,next_unit_id,
posterior_path/posterior_sha256/posterior_version,
posterior_transition_kind/posterior_transition_factor,
planner_decision_path/planner_decision_sha256,
method_state_before_path/method_state_before_sha256,
method_state_after_path/method_state_after_sha256,
shift_state_before_path/shift_state_before_sha256,
shift_state_after_path/shift_state_after_sha256,
transformer_sha256,planner_history,attempted_logical_commands,
candidate_cursor,schedule_cursor,
detector{cusum,positive_window,last_trial,latched},
alarm_handled,rolling_validation_slots[4],recovered_at,
attempted_logical_commands,sentinel_set_slots[0..2],sentinel_set_verdict,
nominal_restore_reference_path,nominal_restore_reference_sha256,
actuator{shift_id,context_state,evidence_bundle_sha256,transform_readback_sha256,
         last_effective_changeover_unit_id,last_effective_changeover_uid,
         in_progress_changeover_unit_id,in_progress_changeover_uid},
bag_group_id,last_known_segment,bag_range_inventory_path,
bag_range_inventory_sha256,bag_range_inventory_sequence,
transition_trace_path,transition_trace_sha256,
scientific_unit_commit_sha256,boot_id,previous_journal_event_sha256,
changeover_result_commit_sha256,changeover_marker_ack_sha256,
initialization_commit_sha256,initialization_result_path,initialization_result_sha256,
pre_checkpoint_event_refs[],
checkpoint_sequence,previous_checkpoint_sha256
```

NAV scientific checkpoint 要求 method-state refs non-null、shift-state refs null；SHIFT 相反。
`planner_decision` 只对 adaptive proposal/all-rejected non-null。context return 按所属暂停
cursor 选择一组 runtime-state refs。`pre_checkpoint_event_refs[]` 只含在对应 scientific
commit 后、checkpoint 前由 semantic intent materialize 并 fsync 的 ordered event
`{event_id,event_sha256}`；普通 unit 写 `[]`。这些 conditional rules 与第 5.3 节
`ScientificUnitResult` 完全相同，schema 拒绝半空 path/hash pair。

nominal-reference 四列也使用严格 path/hash pair：NAV 全 null；SHIFT A1--A11 的 before/after
全 null；A12 若 `protocol_complete=false`（technical/pre-measure/operator/internal）则
before/after仍全 null、cursor停在 A12。A12 的首个 protocol-complete outcome才要求 before
null、after required；这包括 valid、invalid、ALL_CANDIDATES_REJECTED、runtime safety或
collision/no-observation outcome，所有这些 terminal adapter都必须调用继承 freeze flag 的
detached hook。A12 之后所有 unit 的 before/after都 required且逐位相同（该 reference 只在
下一 sequence 重新初始化）。RERUN_TECH按是否首次形成 protocol-complete A12应用同一条件。
`SCIENTIFIC_UNIT_COMMIT` 四列与 result逐位相等，
checkpoint/runtime-state 的 after path/hash等于 result after；对象必须存在于 delivery 的
`nominal_restore_references/` 并通过 strict schema。缺 reference时 B 阶段不可运行。

机器 invariant 还必须断言：`SCIENTIFIC_UNIT_COMMIT.posterior_transition_kind/factor` 与其
ScientificUnitResult逐位相等；commit 的 posterior before/after hash/version 与 result
逐位相等，SCIENTIFIC checkpoint 的 kind/factor、posterior-after path/hash/version 与
commit 逐位相等。result、commit、checkpoint 的 transition-trace path/hash 必须逐位相等，
并能读取同一 content-addressed state-machine trace；禁止只有 hash 而无权威 bytes。
CHANGEOVER checkpoint 固定
`posterior_transition_kind=NONE,factor=null` 且 posterior before/after完全不变。
`TRIAL_OBSERVATION` 要求 `observation_valid` non-null并等于 observation artifact 的 valid；
`NAV_EPISODE_METRICS|NONE` 要求 `observation_valid=null`。任何一处不一致均为
`PERSISTENCE_CORRUPT`，不能由 exporter修补。

`protocol_checkpoint.schema.json` 的三分支 `oneOf` 逐字段冻结如下；“一组 ref”表示 path/hash
同时 required或同时 null：

| field family | RUNTIME_STATE_INITIALIZED | SCIENTIFIC | CHANGEOVER |
|---|---|---|---|
| commit refs | init commit + init-result refs required；scientific/changeover null | scientific commit required；init/changeover null | result+marker ACK required；init/scientific null |
| last/next unit | last null，next=该 scope首个 planned unit | last=本 scientific unit，next=committed cursor（失败可仍指本 unit/AWAIT） | last继承前 checkpoint，next按 changeover cursor；通常可相同 |
| posterior | v0000 after ref required；kind=`INITIAL`,factor=null | after ref/kind/factor等于 scientific commit | ref/version逐位继承；kind=`NONE`,factor=null |
| planner decision | null | 仅 ADAPTIVE_SAFE_SELECTION/ADAPTIVE_ALL_REJECTED required，其他 null | null |
| method/shift state | before两组null；NAV method-after或SHIFT shift-after恰一组 required | NAV method before/after或SHIFT shift before/after恰一类 required | method refs null；shift before/after required并等于 changeover result |
| nominal reference | null | 按 A12 protocol-complete矩阵切换/继承 | path/hash逐位继承前 checkpoint |
| bag range inventory | path/hash/sequence null | required并等于 scientific commit | null |
| transition trace | null | path/hash required并等于 result/commit | null |
| bag group/segment | null | required，允许指 OPEN segment | marker ACK 的 group/segment required；无 inventory |
| pre-checkpoint events | `[]` | ordered semantic-intent refs，可为空 | `[]`；result/marker已有专门 refs |

INIT 的 detector/actuator/history/cursor写各协议初值；SCIENTIFIC与其 after runtime state逐位
一致；CHANGEOVER与 shift-state-after逐位一致。任何 branch 的非适用字段必须 JSON null，
不能用空 string/0/`NOT_APPLICABLE`绕过。`schedule_cursor` 在 CHANGEOVER 必须按
success/failure/recovery结果前移或进入相应 recovery cursor，而不是机械总前移。
三类 checkpoint 共用全局严格递增 sequence/previous hash 链；不能各维护一条链或让
scientific checkpoint 覆盖更新后的 actuator state。

`previous_journal_event_sha256` 是开始写 checkpoint 时已 fsync 的
journal tail；它不能引用尚未产生的 CHECKPOINT_COMMIT 形成循环。checkpoint 另含
`checkpoint_sequence,previous_checkpoint_sha256`。相同 sequence+content 的重试幂等，
相同 sequence 不同 content 直接 integrity failure。

模型与 checkpoint 的可见性顺序不可交换：先写 immutable observation/posterior/
scientific result/inventory，后 fsync `SCIENTIFIC_UNIT_COMMIT`，再写并 fsync checkpoint
与 `CHECKPOINT_COMMIT`，最后才 atomic 更新 live posterior/index/cursor。任何进程都只
从 paired checkpoint 加载 live model；不得在 model.update 后、checkpoint 前让下一个
unit 读取内存对象。

NAV 不使用 detector/recovery 字段，必须显式写 `NOT_APPLICABLE`；SHIFT
必须全部恢复，禁止只 load posterior 后把 CUSUM/deque/history 清零。
rolling slots 保留 `VALID/INVALID` 和 scheduled index，不只保留 residual 数组。

### 17.5 write-once 与 resume

新 run 默认拒绝 non-empty output。唯一例外：显式
`--resume-run-id EXISTING_RUN_ID`，且同时满足：

- source commit、container、config、schedule、map、command hashes 完全一致；
- journal hash chain 完整；
- 最后配对的 initialization、scientific 或 changeover commit chain、checkpoint、posterior 和
  per-unit bag-range inventory 的 path/hash/sequence 互相一致且均可读；任何一个被替换
  或只更新其中一部分都拒绝直接 resume，先走 deterministic recovery；
- ledger/bag marker 没有 identity 冲突；
- 只从已提交 INIT、scientific unit 或 changeover 边界恢复；crash 在 INIT paired
  checkpoint 后、首个 unit 前必须直接恢复 INIT after refs/cursor，不得拒绝或重建 v0000；
- mid-trial、mid-episode 或 mid-changeover 永不续跑；
- checkpoint inventory 可以引用 OPEN bag group；resume 按第 17.2 节只读恢复旧 segment、
  新建下一 ordinal，并保留全部 committed ranges，不要求已有 group-final seal index；
- resume 后先 query watchdog 的持久状态，ordinary command lane 保持禁止；若为 latch/
  TECH_ABORT 则必须走原显式 reset/ack，绝不自动改成 DISARMED；
- operator 再次 preflight 和显式 `--arm`。

mid-trial/mid-episode 原 attempt 关闭为 technical failure，如冻结词表允许，
以同 scientific unit ID+新 attempt UID 从起点重做；不从中间 pose 继续。
mid-changeover 表示物理 context 未知，必须把当次 planned changeover attempt 以
`technical_abort/SOFTWARE_PROCESS_CRASH` 封口，再严格执行第 16.6 节预注册
`RECOVER_NOMINAL` identity、验证 nominal，并用原 planned unit 的递增 attempt index
重做整个 changeover；不得借用 planned RESTORE、复用失败 UID 或运行时造 recovery ID。
若 checkpoint 已提交“shifted + verified”，
resume 仍要在 DISARMED 状态重验该 evidence 才能执行 next unit。

watchdog sequence 不从 Python checkpoint 强行写回：resume 查询 C++
`boot_id/command_sequence`；同 boot 从当前值继续递增，新 boot 从 1 开始并记
新 `resume_epoch`。两种情况都先保持 zero/query-only，再按实际持久状态完成
ack/reset（如需要）、preflight 和新 arm。

crash 时未完成 attempt 写 `SOFTWARE_PROCESS_CRASH`；磁盘错误写
`STORAGE_IO_FAILURE`。不得自动 retry；是否以新 attempt ID 技术重采由冻结规则
和 operator 明确执行。

“未完成 attempt”不包括已有 hash-valid `ATTEMPT_PHYSICAL_COMMIT`、只是缺少
`SCIENTIFIC_UNIT_COMMIT` 的情况；后者必须从 immutable raw 确定性补 scientific result、
inventory 和 checkpoint，不重新 arm、不重走运动，也不分配 RERUN_TECH。

显式入口由目标源码 `src/calibagent/cli/p8_retry_unit.py` 实现，唯一参数、eligibility、
UUID/UID crash state machine 和 scope transaction 以 §19.1 为准。CLI **不接受**
`technical-failure-code`；code 只能从 immutable scientific result 读取。不得保留旧式
`--request-uuid/--unit-id/--failed-attempt-uid` alias，以免形成第二套协议。

### 17.6 attempt selection

第一个 protocol-complete attempt 进入分析。只有 handoff 冻结词表中的客观
technical failure 可以重采。原 attempt 永不删除，`selected_for_export` 由
validator 根据规则机械判定，不能由 RMSE/成功率决定。

该判定只遍历 hash-valid `SCIENTIFIC_UNIT_COMMIT`，并从其
`ScientificUnitResult.protocol_complete/retry_permitted/scientific_outcome` 重算；只有
physical commit、只有 artifact、只有 checkpoint candidate 或只有 ledger CSV 的 attempt
都不得被选择。每条 selected row 必须能反向 join 到唯一 scientific commit、唯一
physical commit、对应 bag-range inventory，以及最终 sealed segment index。

`restore_sentinel` 是明确的例外流程而不是 outcome-based scientific retry：所有
verification set 都导出且 `selected_for_export=false`（sentinel 不进 primary
analysis）；restore gate 只按 execution order 检查最后一个**完整**两行 set 是否 pass，
并同时证明此前失败 set 全保留。它不得套用“第一个 protocol-complete attempt”去阻止
协议规定的 context 修复复验，也不得从多个 set 选择最低 RMSE。

### 17.7 blind safety review（不改变重采资格）

每个 `safety_abort`、COLLISION、E-stop/人员接触候选和 online
`serious_safety_event=true` 都必须在 reviewer 获得任何 outcome table、且 data lock前完成
一次独立 review。写
`schemas/p8/safety_review.schema.json` 和 immutable record：

```text
schema_version,review_id,identity_kind,run_id,safety_event_id,
review_token,blinded_bundle_sha256,blind_decision_path,blind_decision_sha256,
blind_review_receipt_sha256,custodian_link_sha256,
approval_request_path,approval_request_sha256,
reviewer_approval_path,reviewer_approval_sha256,
safety_reviewer_approval_path,safety_reviewer_approval_sha256,
run_level_journal_event_sha256,attempt_uid,scientific_unit_id,
physical_commit_sha256,scientific_commit_sha256,
online_serious_safety_event,reviewer_id,safety_reviewer_id,
method_and_metric_blinding_attested,criteria_path,criteria_sha256,
video_uri,video_sha256,video_start_ns,video_end_ns,
sensor_evidence_sha256,contact_evidence_sha256,geometry_evidence_sha256,
review_verdict_serious,verdict_reason_codes,reviewed_utc,
previous_safety_review_sha256,safety_review_sha256
```

criteria 不是 CLI 临时文件。source
`configs/experiments/p8_safety_review_criteria.yaml` 在 freeze时原样复制到 release
`protocol/`，NAV/SHIFT config均以 path+raw hash引用。它的 strict key为
`schema_version,criteria_id,serious_conditions,evidence_requirements,
event_class_rules,verdict_reason_codes,conservative_unknown_is_serious,approved_by,
approved_utc`，且所有 nested object 也是 `additionalProperties=false`。
`schema_version="p8.safety-review-criteria.v1"`；`criteria_id` 是非空稳定 ID。
其 nested contract 精确为：

```text
serious_conditions: [
  PERSON_OR_ANIMAL_CONTACT,
  FALL_OR_ROLLOVER,
  UNCONTROLLED_MOTION_REQUIRING_INTERVENTION,
  PHYSICAL_ESTOP_ACTIVATION,
  WORKSPACE_BOUNDARY_EXIT,
  ROBOT_OR_ENVIRONMENT_DAMAGE,
  MEDICAL_EVENT,
  ONLINE_SERIOUS_FLAG
]
evidence_requirements: {
  pre_event_window_ns,post_event_window_ns,
  neutral_video_required=true,neutral_sensor_required=true,
  allowed_video_transform{LOSSLESS_COPY,APPROVED_LOSSLESS_REDACTION},
  required_sensor_channels[],contact_evidence_event_classes[],
  geometry_evidence_event_classes[]
}
event_class_rules: [{
  event_class,required_evidence[],serious_condition_ids[],
  online_serious_candidate_forces_serious=true,
  missing_required_evidence_forces_serious=true
}]
verdict_reason_codes: {serious[],not_serious[]}
approved_by: [{person_id,key_id,role}]
```

`serious_conditions` 是上述八个值的指定顺序数组，不得增删或换同义词。
`pre_event_window_ns/post_event_window_ns` 是正整数；`required_sensor_channels`
是非空、排序去重的 topic-map logical-name 数组。`event_class_rules`
必须按此顺序各有且仅有一条
`PERSON_CONTACT,ESTOP,COLLISION,SAFETY_ABORT,ONLINE_SERIOUS_CANDIDATE`；
`required_evidence` 只允许 `VIDEO|SENSOR|CONTACT|GEOMETRY`，且必须同
`evidence_requirements` 两个 event-class 数组机械一致。一个 event 同时命中多类时，
按上述顺序取第一个 class，不由人工选。`serious_condition_ids`
是 `serious_conditions` 的非空子集。`verdict_reason_codes.serious` 必须至少一对一
包含八个 serious condition code 和 `REQUIRED_EVIDENCE_MISSING`；
`not_serious` 是与 serious 集不相交的非空冻结数组。decision 的 reason code
必须全部来自其 verdict 对应数组。`conservative_unknown_is_serious=true`是 const。
`approved_by` 必须恰含不同 person/key 的 `safety_lead` 和 `pi` 两项，顺序固定；
person/key 必须在同一 trust registry 有效。`approved_utc` 为规范 UTC。最终 Gate D
对包含 criteria raw bytes 的 candidate 签名，不另造无签名的现场 override。

`online=true` 永不降级；required evidence缺失按冻结 conservative rule判 serious
且 Gate D incomplete，不能让 reviewer自由忽略。
`calibagent-p8-review-safety prepare-bundle --config`只接受 resolved config中绑定的
criteria path/raw hash，任意 override立即退出 2。schema为
`safety_review_criteria.schema.json`，criteria hash进入 release manifest、bundle、review record
和 data-lock commit。

neutral `SafetyReviewBundle` 由 `safety_review_bundle.schema.json` 验证，顶层
exact fields 为：

```text
schema_version,review_token,event_class,online_serious_candidate,
criteria_path,criteria_sha256,
neutral_video_path,neutral_video_sha256,video_start_ns,video_end_ns,
neutral_sensor_path,neutral_sensor_sha256,
neutral_contact_path,neutral_contact_sha256,
neutral_geometry_path,neutral_geometry_sha256,bundle_sha256
```

`schema_version="p8.safety-review-bundle.v1"`；`event_class` 只允许上述五值；
`review_token` 是 128-bit 不可预测随机值的 32 位小写 hex。criteria/video/sensor
path/hash pair 必填；contact/geometry 依命中 rule 各自必填，否则两字段均为
JSON null。所有 path 是 bundle root 内不含绝对路径、`..`、symlink 的中性相对路径；
basename/embedded metadata 不得含 run/session/block/method/attempt/scientific-unit ID。
`video_start_ns < video_end_ns`，且覆盖 criteria 要求窗口。每个 `*_sha256` 对实际
raw bytes 重算；`criteria_sha256` 等于 resolved config 绑定值。
`bundle_sha256=sha256(JCS(record 排除 bundle_sha256))`。

blind reviewer先产生 strict `SafetyReviewDecision`，由
`schemas/p8/safety_review_decision.schema.json` 验证，exact fields 为
`schema_version,review_token,bundle_sha256,criteria_sha256,verdict,reason_codes,
decided_utc,decision_sha256`。version=`p8.blind-safety-decision.v1`；verdict只允许
`serious|not_serious`；reason codes必须来自 frozen criteria、非空、排序去重；bundle/criteria
hash逐位等于 neutral bundle。`decision_sha256=sha256(JCS(record 排除 decision_sha256))`。
两份 `purpose=SAFETY_REVIEW` approval 的 subject必须是该 decision hash，而不是 bundle hash；
因此 verdict/reasons/时间任一变化都需要新 request和新签名，不能复用旧 approval。

`identity_kind=attempt` 时 attempt/scientific/physical hashes required、run-level journal
hash null；`identity_kind=run_level`（如 PREPARED 前 E-stop/person contact）时
`safety_event_id+run_level_journal_event_sha256` required，其余 attempt hashes null。两
reviewer ID 不同；collision 的 video/sensor/geometry evidence required，其他 event按
criteria conditional required。`safety_review_sha256=sha256(canonical JSON(record 排除
safety_review_sha256))`。review tool append+fsync
`SAFETY_REVIEW_COMMIT{record_path/hash,identity_kind,对应 attempt hashes 或 run-level
event hash,review_token,blinded_bundle_sha256,blind_decision_sha256,blind_review_receipt_sha256,
custodian_link_sha256}`，同 safety event 只允许一个
effective review；相同 bytes 幂等，不同 verdict拒绝并走 protocol deviation，不允许挑
较轻结论。

exporter 定义
`serious_safety_event = online_serious_safety_event OR review_verdict_serious`；review 永不
改变 status、protocol_complete、retry_permitted、selected_for_export 或 cursor，因而不是
第 14.3 节已禁止的 integrity reclassification。任一 required event 缺 review、blinding/
criteria/video hash无效时 delivery/Gate D fail；Gate C/D 和论文 serious=0 只读这个 OR 后
字段。测试覆盖 online false→review true、online true→review false仍 true、缺 review fail。

这里“blind”精确指 safety reviewer 在作 verdict 前只能看到第 19.2 节 opaque neutral bundle，
不能看到 method/outcome metrics或可泄漏它们的路径；canonical raw/export在 data custodian
边界内仍保留真实 method ID，不声称整套实验对 operator/分析者使用加密方法标签。

---

## 18. Export、delivery validation 和 analysis

### 18.1 schema

`docs/p8_go2_real_deployment_data_handoff_zh.md` 第 12 节是 human-readable
权威。coding agent 必须把每张表转换为 `schemas/p8/exported_tables/*.schema.json`，
并让 exporter/validator 共同读取 schema，不能各自手写不同 required columns。

`p8_go2_real_delivery/exported/` 的 required-files allowlist 必须与 handoff §11 完全
一致，至少逐项验证下列文件存在、schema-valid 且被 manifest/checksum 覆盖：

```text
session_metadata.csv
block_schedule_executed.csv
attempt_ledger.csv
calibration_samples.csv.gz
calibration_trials.csv
validation_trials.csv
planner_candidates.csv.gz
navigation_trace.csv.gz
episode_metrics.csv
shift_monitor_metrics.csv
shift_recovery_metrics.csv
nominal_restore_sentinel_metrics.csv
changeover_evidence_index.csv
safety_events.csv
safety_review_index.csv
state_machine_trace.csv
time_sync_diagnostics.csv
posterior_index.csv
```

其中 `nominal_restore_sentinel_metrics.csv` 物理保存每个 verification set 的两条
sentinel 和 set-level pass，禁止只在日志写“恢复完成”；
`changeover_evidence_index.csv` 以全局唯一 `changeover_uid` 为主键，连接 planned
APPLY/RESTORE 及 conditional RECOVER_NOMINAL attempts 的 pre/post evidence、
actuation/operator receipts 和 recorder marker，检查 index/retry/parent/effective 约束，
且不允许 motion attempt identity 列伪装 changeover。缺少任一文件必须使 validator
非零退出。

特别注意：

- trial `cmd_v*` = pre-R1 `model_input`；
- `transmitted_cmd_v*` = post-transform actual sent command；
- sample 表同时保留 planned/candidate/safe/model_input/post-transform/transmitted/ACK；
- SHIFT 全部 unit 及 NAV calibration/validation/posterior
  `map_id=NOT_APPLICABLE`；NAV episode-start `context_return` 写所属真实 map，
  其余 context return 写 `NOT_APPLICABLE`；
- failed NAV `completion_time_s=timeout_s`；
- validation leakage check 必须证明 posterior 不变。

唯一键和 nullable 必须逐字实现 handoff 第 12.12 节。validator 不得
对整表泛化 `np.isfinite`；只对 non-null numeric 检查 finite，并依
`status/phase/ack_available/success/valid` 运行 conditional required/null rules。

### 18.2 exporter

`export.py`：

1. reopen bag 和 journal；
2. 验证所有 marker/attempt/time ranges；
3. 从 reference raw +外参重建 base pose；
4. 从 measure window 构造 `RawTrialData(model_input, reference pose)`；
5. 调同一 `MeasurementPipeline`；
6. 导出 handoff 全部表；
7. 从 trace 重算 episode metrics、NIS/CUSUM、rolling RMSE；
8. 建立 raw refs、video refs、posterior refs；
9. 写 `manifests/input_lock_manifest.json`，不写 analysis/final delivery manifest/checksums。

同一 frozen input 重跑 exporter 必须语义和行排序确定；时间型 provenance 字段可
单独放 build metadata，不能破坏数据表 reproducibility。

### 18.3 delivery validator

`validate_delivery.py` 至少检查：

- required files、schema、dtype、conditional nullability、non-null finite、ID uniqueness；
- checksum 覆盖所有文件且路径安全；
- bag 可打开、抽样 ≥5% playback；
- ledger 每个 planned ID 有 outcome；
- technical retry 合法且第一个 complete 被选；
- raw→trial→metric 可重算；
- posterior version/hash chain；
- candidate selected 行存在且安全；
- cardinality 按 role 分支：DEV NAV 期望 `510/320/80`，CONFIRM NAV 期望
  `3060/1920/480`；
- DEV SHIFT 期望 `60 sequences/2700 primary/120 initial planned sentinel`，CONFIRM SHIFT
  期望 `240/10800/480`；实际 sentinel scientific units 必须等于 role 的 initial count
  `+ 2×activated_conditional_sets`，actual attempts 还可因合法 RERUN_TECH 增加，二者
  不得被 initial-count assertion 拒绝；
- 两个 NAV map ID 精确匹配；四个 shift 精确匹配；
- serious event、latency、reference/time sync 完整；
- DEV 与 CONFIRM 不混合；DEV `pilot_n` 每 cell 恰为 5，CONFIRM analyzer 仍只接受
  NAV 30/SHIFT 20 的独立 block namespace。

validator 只报告完整性/协议 pass，不把统计结果好坏写成数据完整性失败。

### 18.4 confirmatory analyzer

`analysis_plan.yaml` 必须通过 strict `p8.analysis-plan.v1` schema，顶层 key精确为
`schema_version,protocol_version,estimands,primary_gates,secondary_descriptive,
bootstrap,rate_intervals,nav,shift,missingness,power_plan,mixed_effects,
multiplicity,safety_latency,software`，顶层和任意 nested mapping 都必须
`additionalProperties=false`。每个顶层对象的 exact required keys 为：

```text
estimands = hypothesis_id_separator,hypothesis_id_templates,
            global_endpoint_formulas,
            nav_map_endpoint_keys,nav_comparison_endpoint_keys,
            nav_method_endpoint_keys,shift_endpoint_keys,
            shift_method_endpoint_keys,global_endpoint_keys,
            expected_primary_hypothesis_id_count,
            expected_secondary_hypothesis_id_count,
            expected_total_hypothesis_id_count
primary_gates = decision_rule,nav,shift,global
secondary_descriptive = gate_status,enters_overall_gate,p_adjusted,report_p_raw,
                        median_quantile_method,p95_quantile_method,
                        continuous_summaries,hypothesis_id_templates,
                        nav_comparison_endpoint_keys,nav_method_rate_endpoint_keys,
                        shift_detector_method_ids,shift_detector_endpoint_keys,
                        shift_rate_method_ids,shift_rate_interval_endpoint_keys,
                        formulas,expected_hypothesis_id_count
bootstrap = replicates,rng_constructor,bit_generator,seeds,ci,
            nav_resampling,shift_resampling
rate_intervals = method,sides,confidence_level,alpha,lower_formula,upper_formula,
                 implementation,denominator_policy
nav = map_ids,method_ids,primary_method_id,raw_baseline_id,dense_baseline_id,
      matched_baseline_ids,calibrated_method_ids,planned_blocks,timeout_s,
      formulas,completion_time_failure_encoding,time_ratio_aggregation,
      completion_time_tie_win_value,ni_gate_bound,time_ratio_gate_bound,
      valid_calibration_gate_aggregation
shift = shift_ids,method_ids,frozen_method_id,passive_method_id,primary_method_id,
        planned_blocks_per_shift,monitor,rmse,comparisons,aggregates,
        valid_observation_ratio
missingness = delete_protocol_complete_outcomes,interpolate_missing_observations,
              survivor_only_summaries,nav_failed_completion_time_s,
              shift_invalid_slot_q,shift_detection_delay_penalty_trials,
              shift_recovery_trials_penalty,rate_denominator_policy,
              invalid_pre_monitor_policy,invalid_post_before_first_alarm_policy,
              invalid_post_after_first_valid_alarm_policy
power_plan = method,alpha,target_marginal_power,minimum_pilot_n_per_cell,
             required_pilot_n_per_cell,pilot_dataset_role,
             pilot_input_lock_manifest_raw_sha256,pilot_cardinality,
             continuous_family,discrete_family,sd_estimator,
             sd_upper_confidence_level,sd_upper_formula,zero_or_nonfinite_sd_policy,
             df_formula,ncp_formula,critical_value_formula,power_formula,
             required_cell_report_fields,family_decision_rule,interpretation
mixed_effects = role,eligible_endpoint_class,excluded_endpoint_classes,
                nav,shift,fit,report_fields
multiplicity = primary,secondary,primary_p_adjusted,secondary_p_adjusted,
               overall_gate_operator,select_favorable_baseline
safety_latency = timing_required_sources,timing_required_event_types,
                 latency_formula_ms,require_nonnegative_latency,threshold_ms,
                 missing_zero_publish_policy,required_count_zero_fallback,
                 gate_c_schema_version,gate_c_id,gate_c_required_status,report_fields
software = analyzer_entrypoint,analysis_environment_lock,
           analysis_environment_lock_sha256,rng_api,bit_generator_api,
           quantile_api,clopper_pearson_api,wilcoxon_api,mixedlm_api
```

所有对象的 nested keys、列表 enum/顺序、公式字符串、seed、threshold
和单位必须逐字采用 handoff §15.1 的 canonical nested YAML，禁止
flat aliases 和默认值。生成 schema 时只有
`pilot_input_lock_manifest_raw_sha256` 和 `analysis_environment_lock_sha256` 是匹配
`^[0-9a-f]{64}$` 的冻结动态值；其余都用 `const`、闭合 `enum`、
固定 `prefixItems` 或明确 numeric bound 表达。schema 必须拒绝 YAML
duplicate keys、anchors/aliases、非字符串 mapping key、NaN/Inf 和隐式 timestamp。
tracked `configs/experiments/p8_analysis_plan_template.yaml` 不是 final plan：它在且只在
`power_plan.pilot_input_lock_manifest_raw_sha256` 使用 JSON/YAML `null`。freeze
prepare 必须在 DEV exporter + pre-lock validator 完成后，以 DEV
`input_lock_manifest_raw_sha256` 填充该字段，并证明 template/final 的 canonical
parse tree 除该 leaf 外逐位相同。final `protocol/analysis_plan.yaml` 只接受 64-hex，
不引用 DEV delivery manifest，从而不与 Gate D/final release 形成环。

`hypothesis_id` 按 handoff §15.1 的六个 template 和 endpoint/baseline/method
enum 机械展开，保留 ID 原始大小写和下划线；不允许随机 UUID、
序号或随运行顺序变化的 ID。analyzer 启动时先生成 expected ID set，
其 primary exact cardinality 为 116。secondary 使用 handoff 冻结的 `D::`
namespace 和三个 template，exact cardinality 为 142；全部 expected endpoint ID
总数固定为 258。对缺失/额外/重复 ID 必须 fail closed。每个 primary
和 secondary endpoint 均必须在 `confirmatory_analysis.json` 有且只有一条记录。

SHIFT detector 不得跳过 invalid/unavailable monitor：analyzer 必须依 handoff
§15.1 先构造 `E_i`，再按 pre-alarm → invalid pre evidence → invalid post
prefix → miss → detected 的冻结顺序派生结果。invalid pre evidence
计 primary false-alarm gate failure；任一 invalid post slot 若位于首个 valid
alarm 之前，则不允许用更晚 alarm 挽回 detection。全部 pre-alarm/
invalid/miss 分支均固定 `detected=false,detection_delay_trials=6`；首个
valid alarm 之后的 invalid slot 不反向改写 detection。golden fixture 至少分别覆盖
这五条分支和边界 index 4/5/9。

plan raw hash写 config/release/input-lock/data-lock/report，CONFIRM后不可变。DEV schedule
cardinality 必须精确为 NAV 5 blocks、每个 SHIFT 5 blocks，且每个 readiness cell
`pilot_n=5`；NAV 的 `planned_n=30`、SHIFT 的 `planned_n=20`，`df/ncp` 只用
planned n。Gate D 按 handoff §15.1 的固定顺序重算 22 个 continuous cells 与 62 个
discrete checks。continuous cell 使用 DEV `ddof=1` SD 的一侧 95% chi-square 上界；
`sd<=0` 或任何 nonfinite 值固定 `power=null`/FAIL，绝不映射为 power=1。22 个 cell
逐项 marginal power≥0.80 且 62 个 exact attainable/resolution check 全通过才可 PASS。
这一结果不是 family-wise/joint power 声明。机器报告必须区分 `pilot_n,planned_n,
sd_unbiased,sd_upper_95,df,ncp,power,failure_reason`；不得让变量名 `n` 同时承载
两种样本量，也不得混入 CONFIRM。

为避免 data lock与分析输出自循环，全部 blind safety review 必须先按 §17.7/§19.2
完成 decision签名、custodian ingest 和 main-journal `SAFETY_REVIEW_COMMIT`；exporter随后才生成
`manifests/input_lock_manifest.json`。它覆盖 frozen_release、raw、除 `post_lock/` 外的
protocol artifacts、exported、posterior、reference、maps和metadata，明确排除 analysis、
final delivery manifest/checksums与整个 post-lock subtree。第 19.2 节 DataLock record精确含
`schema_version,lock_id,dataset_role,run_id,input_lock_manifest_path,
input_lock_manifest_semantic_sha256,input_lock_manifest_raw_sha256,analysis_plan_sha256,
safety_review_criteria_sha256,safety_review_chain_tail_sha256,
required_review_count,completed_review_count,approval_request_path,approval_request_sha256,
pi_approval_path,pi_approval_sha256,data_custodian_approval_path,
data_custodian_approval_sha256,locked_utc,data_lock_sha256`；两 approval
分别要求 PI/data_custodian role并签同一 request。request、两 approval、DataLock和 detached
DataLockCommit 都写入 `protocol_artifacts/<run>/post_lock/`，不 append/修改已锁 main journal。
analyzer只读锁定 inputs并输出 analysis；
最终 delivery manifest/checksums再覆盖 input subtree+lock+analysis，validator证明 input class
indices/raw hashes逐位未变。

`schemas/p8/data_lock_commit.schema.json` 固定唯一 detached commit，顶层 exact fields 为：

```text
schema_version,commit_id,dataset_role,run_id,input_lock_manifest_path,
input_lock_manifest_semantic_sha256,input_lock_manifest_raw_sha256,
data_lock_path,data_lock_sha256,approval_request_path,approval_request_sha256,
pi_approval_path,pi_approval_sha256,data_custodian_approval_path,
data_custodian_approval_sha256,analysis_plan_sha256,safety_review_criteria_sha256,
safety_review_chain_tail_sha256,main_journal_tail_sha256,created_utc,commit_sha256
```

`schema_version=p8.data-lock-commit.v1`。path 的 root 约束不可概化为“全部在 post-lock”：
`input_lock_manifest_path` 必须逐字符等于同 delivery 的
`manifests/input_lock_manifest.json`；`data_lock_path,approval_request_path,
pi_approval_path,data_custodian_approval_path` 必须分别解析到同 run 的
`protocol_artifacts/<run>/post_lock/{data_locks,human_approval_requests,
human_approvals,human_approvals}/`。所有 path/hash pair required，且每个 hash 对解析后字节和
semantic self-hash 均重算相等；任一 path 落到错误 root 即退出 6。
`main_journal_tail_sha256` 必须等于 input-lock file list中 journal最后一条
已锁 event，且此后 journal bytes保持不变。`commit_id="P8-DATALOCK-COMMIT-"+
data_lock_sha256[0:16]`；`commit_sha256=sha256(JCS(record 排除 commit_sha256))`。
每 run只允许一个 hash-valid DataLockCommit；相同 bytes幂等，不同 commit是 integrity failure。
analyzer 的 `--data-lock-commit PATH` 必须直接指向这个 content-addressed JSON，不接受 JSONL、
event ID、目录或裸 hash。

input lock 不得复用 delivery manifest 或它的暂存版本。唯一 schema 是
`schemas/p8/input_lock_manifest.schema.json`，`schema_version=p8.input-lock-manifest.v1`、
`additionalProperties=false`。其顶层 exact fields、固定 include/exclude roots、`files[]`、
`class_indices[]`、排序、path safety、class-index hash、`input_tree_sha256`、确定性 `lock_id` 和
self-hash preimage **逐字采用 handoff §11**；exporter与validator import同一个 model/hasher。
其中 `files[]` 必须包含 `manifests/run_manifests/` 和 `manifests/bag_metadata/`，不得只锁 CSV；
`analysis/`、`protocol_artifacts/*/post_lock/`、自身、final manifest和checksums必须不在
file list。golden test至少
覆盖：canonical重跑逐字一致；改 1 byte raw/posterior/exported 即失败；增删文件、symlink、
path traversal、重排/伪造 class index、semantic/raw任一 hash不符即失败；生成 DataLock/analysis/
final manifest 后重新验证，锁定 input tree hash仍逐位相同。

`input_lock_manifest.analysis_plan_sha256` 的 role conditional 逐字采用 handoff §11：DEV
绑定 DEV release 中 analysis-plan template raw hash，CONFIRM 绑定 final analysis plan raw hash；
`release_manifest_sha256` 同理分别绑定 dev/final release manifest raw hash。schema不增加第二个
nullable alias，prepare/validator根据 `dataset_role` 和 release schema机械选择，交叉绑定退出 6。

`analysis.py`/`eval/p8_real.py` 不复用 P7 map-count validator，但可复用 metrics
helper。handoff 第 15.1 节的 seed、PCG64、percentile CI、quantile method、
NI sign、ratio-of-means、miss penalty、valid-ratio 分母和 Wilcoxon options 是逐字权威；
analyzer 不可在此处发明另一个版本。其余规则：

- paired bootstrap 10,000 次，固定 seed；
- NAV 以完整 block 为 resampling unit，保留 8 methods ×2 maps；
- rate/时间/NI gate 两图分别计算；不能池化成 `n=60`；
- tie 对 B8-vs-B0 completion win 计 0，与 P7 strict `<` 一致；
- matched baselines 五个分别比较，不挑最有利者；
- SHIFT 每个 shift 分别计算，block 内保留三方法配对；
- SHIFT primary false-alarm/detection/recovery rate 来自 full；passive/frozen rate
  作为 secondary diagnostics；
- missing validation window 用 0.25 penalty；
- 报告 point estimate、effect、CI 和 failures；
- mixed-effects 仅 sensitivity analysis，不能替代 paired primary analysis。

输出 `analysis/confirmatory_analysis.json` 必须通过
`p8.confirmatory-analysis.v1`，顶层精确含
`schema_version,dataset_role,run_id,input_lock_manifest_sha256,data_lock_commit_sha256,
analysis_plan_sha256,release_manifest_sha256,analyzer_source_commit,tools_manifest_sha256,
environment_lock_sha256,endpoints,safety_latency,mixed_effects,overall_gate,reason_codes,
report_sha256`。每个 endpoint精确含
`hypothesis_id,family,protocol,map_id,shift_id,method_id,baseline_id,statistic,
alternative,n_blocks,n_observations,estimate,effect,ci_low,ci_high,p_raw,p_adjusted,
gate_operator,gate_threshold,gate_status,reason_codes`；primary/secondary的 `p_adjusted=null`，
secondary gate_status=`DESCRIPTIVE_ONLY`。overall gate是全部 primary IUT与global safety/
integrity条件的机械 AND。report hash排除自身字段；同锁定input重跑除独立build metadata外
逐字确定。

`safety_latency` nested object 的 exact fields 逐字采用 handoff §15.3，必须区分
`timing_required_event_count`、真正有两端 timestamp 的 `eligible_event_count` 与
`missing_zero_publish_count/missing_zero_publish_event_ids`。后者非零直接令
`overall_gate=NO_GO`；只有 required count 本身为 0 才允许 Gate C fallback。validator/analyzer
不得把 `zero_publish_available=false` 的真实失败删成空 eligible set。

两图通过只能支持两个预注册固定室内路线。P8-SHIFT 没有导航 episode，不能从
SHIFT 结果声称“shift 后导航恢复”。

### 18.5 P8 manifest

不要硬套现有 `RunManifest`：它含 Isaac 字段且 config hash 只有 16 hex。新增
`p8.delivery.v1` manifest。`schemas/p8/delivery_manifest.schema.json` 顶层 exact fields 为：

```text
schema_version,dataset_role,run_id,source_commit,
release_manifest_path,release_manifest_sha256,tools_manifest_sha256,
environment_lock_sha256,analysis_plan_sha256,
input_lock_manifest_path,input_lock_manifest_semantic_sha256,
input_lock_manifest_raw_sha256,input_tree_sha256,
data_lock_commit_path,data_lock_commit_sha256,
confirmatory_analysis_path,confirmatory_analysis_raw_sha256,
confirmatory_analysis_report_sha256,overall_gate,
planned_counts,activated_counts,actual_counts,class_indices,files,
total_file_count,total_bytes,delivery_tree_sha256,
delivery_manifest_sha256
```

top-level 及所有 nested 均 `additionalProperties=false`。四个 path 必须分别等于
`frozen_release/release_manifest.json,manifests/input_lock_manifest.json,
protocol_artifacts/<run>/post_lock/data_lock_commits/<raw_sha256>.json,
analysis/confirmatory_analysis.json`，且每个 semantic/raw hash 均重算相等。
`overall_gate` 只允许 `GO|NO_GO|TEST_FIXTURE_VERIFIED`，逐字等于 analysis。

`planned_counts` exact fields 为：

```text
nav_calibration_trials,nav_validation_trials,nav_navigation_episodes,
shift_sequences,shift_primary_units,initial_planned_sentinel_units,
planned_changeover_units
```

schema 对 `dataset_role` 使用条件分支：DEV 固定为
`510,320,80,60,2700,120,120`，CONFIRM 固定为
`3060,1920,480,240,10800,480,480`；TEST fixture 使用§18.6 固定 mini 数。
DEV delivery 的 `confirmatory_analysis_*`/DataLock final-only fields 依 phase schema 为 null，
但 `planned_counts` 不得省略或伪装成 CONFIRM。`activated_counts` exact fields 为
`conditional_sentinel_sets,conditional_sentinel_units,conditional_context_return_units,
recover_nominal_units,effective_planned_changeovers`，必须由 hash-valid activation/changeover
journal 重算。`actual_counts` exact fields 为：

```text
selected_primary_units,protocol_complete_units,technical_retry_attempts,
no_arm_protocol_complete_units,arm_leases_consumed,unused_lease_quota,
actual_sentinel_attempts,actual_changeover_attempts,changeover_failures,
serious_safety_events
```

这些物理分列禁止用单一 `sentinel_count/changeover_count` 混合计划 unit、
conditional unit 和 retry attempt。`class_indices[]` item 逐字采用 input-lock class-index
shape，但覆盖 final tree全部 artifact class；`files[]` item 逐字采用 input-lock
file shape，按 relative path UTF-8 bytes 排序，覆盖 delivery 中除
`manifests/delivery_manifest.json,checksums.sha256` 外所有 regular files。输入锁定 files/
class indices 必须作为它们的逐位子集，不得改 hash/count。

`total_file_count/total_bytes` 从 files 重算。
`delivery_tree_sha256=sha256(JCS({dataset_role,run_id,source_commit,
release_manifest_sha256,tools_manifest_sha256,environment_lock_sha256,
analysis_plan_sha256,input_lock_manifest_semantic_sha256,
input_lock_manifest_raw_sha256,input_tree_sha256,data_lock_commit_sha256,
confirmatory_analysis_raw_sha256,confirmatory_analysis_report_sha256,overall_gate,
planned_counts,activated_counts,actual_counts,class_indices,files,
total_file_count,total_bytes}))`。
`delivery_manifest_sha256=sha256(JCS(完整 record 排除 delivery_manifest_sha256))`。
manifest 的 raw SHA-256 只由 root `checksums.sha256` 绑定，不写回自身。

`seal-final` 先在 delivery 同文件系统临时目录生成/`fsync` manifest bytes 和
checksums bytes；checksums 按 relative path UTF-8 bytes 排序，覆盖完整 tree 包括
delivery manifest，不包含自身。commit 顺序是 manifest atomic rename+directory fsync 后，
checksums atomic rename+directory fsync；checksums 是 seal commit marker。若崩溃只留 manifest，重试仅在
重算 bytes 逐字相同时允许补写 checksums；任一已有文件 bytes 不同都退出 6，
绝不 overwrite。两者都存在且验证通过时幂等返回原 report。

### 18.6 分析依赖与 golden fixture

`env/analysis/requirements-p8.lock.txt` 必须 pin direct+transitive dependencies。职责
固定为：NumPy（数组/PCG64）、SciPy（CP/Wilcoxon）、pandas（表）、
PyYAML（config）、jsonschema（schema）、`rosbags`（非 ROS 分析容器读
rosbag2）和 statsmodels（mixed-effects sensitivity）。机器人 ROS 容器用
`rosbag2_py`控制写入，不在纯分析 package import `rclpy`。

`tests/replay/p8/fixtures/golden_delivery` 是小型 `TEST_FIXTURE`：2 个 NAV paired
blocks（仍包 8 methods×2 maps）、每个 shift 1 个 SHIFT block（仍包 3
methods）、一组技术重试、一个 invalid window 和一个 R1 trace。它不伪装
30/20-block CONFIRM。mini 的固定 cardinality 为 NAV calibration=204、validation=128、
episodes=32；SHIFT sequences=12、primary=540、planned sentinel=24。所有 fixture
`AttemptIdentity.dataset_role=TEST_FIXTURE`；技术重试使用
`attempt_role=RERUN_TECH`。validator 只在 manifest `dataset_role=TEST_FIXTURE` 且 CLI
`--fixture-profile mini` 时使用缩小 cardinality。analyzer 对它必须使用
`--verification-only --expected tests/replay/p8/fixtures/golden_expected.json`，比较冻结
statistics 并返回 0；禁止产生 GO。生产命令不接受 fixture profile，数据不足返回 6，
完整但统计 NO-GO 返回 7。

`golden_expected.json` 固定含 `schema_version,fixture_manifest_sha256,statistics,
rtol,atol`，其中 `rtol=1e-10,atol=1e-12`；comparison 逐 key、拒绝额外/缺失 key。
expected 由独立 direct-formula fixture builder 生成并经人工 review 后 tracked，测试和
analyzer 永不提供“从当前输出更新 expected”的路径，避免实现与 oracle 同错。

---

## 19. CLI 和退出码

在 `pyproject.toml` 注册：

```text
calibagent-p8-config-validate
calibagent-p8-schedule
calibagent-p8-preflight
calibagent-p8-run-nav
calibagent-p8-run-shift
calibagent-p8-retry-unit
calibagent-p8-review-safety
calibagent-p8-reset-abort
calibagent-p8-sign-approval
calibagent-p8-replay
calibagent-p8-export
calibagent-p8-validate-delivery
calibagent-p8-analyze
calibagent-p8-freeze-release
```

共同规则：

- `--help` 不需要 ROS graph/机器人；
- run/retry 默认 dry-run；只有显式 `--arm` 才允许请求非零运动命令；
  static preflight 不接受 `--arm`，任何路径都不建 attempt/scope/lease，且只允许
  heartbeat、状态查询和零命令读回；
- `CONFIRM` 禁止 `--overwrite`、ad-hoc command、ad-hoc waypoint、临时 seed；
- 所有 run/retry 接受 `--config`、`--schedule`、`--release-root`、
  `--output-root`、`--robot-state-root`、`--approval-inbox`、`--dataset-role`；
  static preflight 的精确子集见§19.4.3；output/global 两个 root 都按第 6.1 节
  sentinel 解析；`--arm` 时 approval inbox required且必须在 output/global roots外只读挂载；
- resume 只接受 `--resume-run-id`，不能自动发现“最近 run”；
- config/hash/frame/topic/readiness 错误在运动前退出；
- stdout 给人读，machine report 写 JSON；
- secrets、age identity、Ed25519 private key、SDK token 不写日志。

冻结退出码：

```text
0  success
2  config/schema/hash error
3  preflight/readiness failure
4  safety latch/emergency stop
5  runtime/technical failure
6  data integrity/delivery validation failure
7  confirmatory statistical gate NO-GO
```

统计 NO-GO 不等于程序崩溃；仍须生成完整 report，退出 7。

### 19.1 显式技术重采事务

`calibagent-p8-retry-unit` 是 `RERUN_TECH` 的唯一入口；普通 NAV/SHIFT runner 和
`--resume-run-id` 永不自动重跑当前 unit。参数精确为（只有末行可选）：

```text
--run-id RUN
--scientific-unit-id UNIT
--previous-attempt-uid UID
--retry-request-uuid UUID
--config PATH
--schedule PATH
--release-root PATH
--output-root PATH
--robot-state-root ABS_DURABLE_PATH
--approval-inbox ABS_READ_ONLY_PATH
--dataset-role DEV|CONFIRM
--report NEW_FILE
[--arm]
```

还必须从 frozen release manifest 解析 source/config/schedule hashes，禁止 CLI 覆盖
command/map/shift/method。没有 `--arm` 只输出 eligibility report，不分配 attempt、scope
或 lease。armed 路径的唯一事务为：

```text
1. 验证最后 paired checkpoint cursor == AWAIT_EXPLICIT_RERUN_TECH 且 current UNIT 相等；
2. 载入 UNIT 最后一条 immutable ScientificUnitResult，要求 protocol_complete=false、
   retry_permitted=true、technical_failure_code 属于 handoff §14.2、previous UID精确相等，
   并证明该 UNIT 不存在任何 protocol-complete attempt；
3. 只接受 watchdog 当前为 `DISARMED`。若为 `TECH_ABORT_DISARMED`，先单独运行第 19.3 节
   `calibagent-p8-reset-abort --mode technical-ack` 完成 CAS，再重新调用 retry；retry 本身
   不接收 reset receipt、不猜“最新授权”。它必须验证 readiness 的
   `last_consumed_reset_authorization_sha256`（通过 atomic state proof）回链本 failed unit；
   safety latch、operator/internal pause 一律拒绝；
4. append+fsync RETRY_REQUEST_ACCEPTED{request_uuid,unit,previous_uid,
   failed_attempt_issuing_scope_sha256,lineage_root_scope_sha256,
   next_attempt_index,next_attempt_uid,source/config/schedule hashes}，以 request UUID 做 CAS；
5. motion unit 建 RERUN_TECH ScopeAuthorization：parent=failed attempt 的真实 issuing scope
   hash，lineage root=该链 method PRIMARY root，
   retry_request_uuid=本 UUID，activation=null，allowed=[UNIT]，maximum_attempts=1；注册 typed
   scope receipt和 scope authorization；
6. 按 unit_type 调同一个 trial/manual-return/NAV scientific transaction，identity 固定
   attempt_role=RERUN_TECH,index=previous+1,retry_of=previous UID；
7. 只有 paired CHECKPOINT_COMMIT durable 后，protocol-complete 才前移原 stage cursor；
   再次 exact technical failure仍停在 AWAIT，新的 retry必须用新 UUID/新 scope/next UID。
```

watchdog 从 previous attempt 的 ArmAuthorization/lease quota record重算 issuing scope，并沿
parent/root 链验证 conditional activation/unit registry；caller提供的两个 scope hash不能
自证。`manual_reposition_disarmed` 从未注册 motion scope，因此步骤 5 不适用：coordinator
验证原 CONTEXT_RETURN activation和 previous manual attempt chain，签/注册新的 typed
context-return gate receipt，但保持 watchdog DISARMED、零 scope quota/lease；approved
controlled return 则按真实 CONTEXT_RETURN/RERUN issuing scope执行步骤 5。

同 UUID 的相同 request 在 crash 后幂等恢复步骤 4 分配的同一 UID/index；同 UUID 不同
unit/previous/config 直接 integrity failure。request 状态机固定为
`ALLOCATED → ATTEMPT_RESERVED → PREPARED → PHYSICAL → SCIENTIFIC → CHECKPOINTED`，另有
terminal `PREPARATION_FAILED_BEFORE_BOUNDARY`。crash 且没有 terminal preparation event时，
同 UUID继续同一 allocated UID（这是幂等完成同一 allocation，不叫 UID reuse）；若已写
boundary 前 terminal failure，该 UUID/UID 永久关闭且 UID burned，新请求必须用新 UUID/
新 UID。因为没有 attempt row，新请求的 `attempt_index` 仍为
`last_actual_attempt_index+1`；一旦 PREPARED 已创建 attempt row，后续 request 才递增。
绝不能在同一 UUID 下另分 UID隐藏 crash。

每 unit 的最大 RERUN attempt rows 精确取 frozen
`resume.maximum_rerun_tech_attempts_per_unit`（PRIMARY 不计），达到上限进入
`TECH_RETRY_EXHAUSTED`、令 delivery incomplete并退出 5。RERUN 不改变 dataset role、planned command、route、shift、method、
posterior-before或 stage order。

普通 run/resume 读取 cursor 时必须先 dispatch：

```text
AWAIT_EXPLICIT_RERUN_TECH  -> 不 materialize unit；打印精确 retry 命令；exit 5
PAUSED_OPERATOR_DECISION   -> 不执行；要求冻结人工决定；exit 3
PAUSED_INTERNAL_REVIEW     -> 不执行且不可 retry；exit 5
TECH_RETRY_EXHAUSTED       -> 不执行；delivery incomplete；exit 5
SAFETY_ABORT_LATCHED       -> 不执行；exit 4
RUNNABLE                   -> 才进入第 15/16 节 cursor loop
```

machine report 必须写到 `--report`，且路径在 output root 内但不得已存在；它必须严格通过
§19.4 的 `p8.operation-report.v1`，其中 `operation=RETRY_UNIT`、
`request_uuid=retry_request_uuid`、`previous_attempt_uid` 与 argv 逐字相等，其余 generic
fields也全部存在；不得另造一个缺少 common provenance 的 retry report schema。
无 `--arm` 的 eligibility 检查只写该 report，不修改 run/global state。退出类型精确为
0=eligibility PASS 或已完成，2=config/schema/hash，3=approval/readiness，4=safety latch，
5=technical/persistence/retry exhausted，6=immutable lineage/integrity 不一致。

`RESUME_RENEWAL` 的 allowed pending set 必须排除以上 blocked unit，直到相应 coordinator
事务解除；否则 resume scope 会成为隐式 retry 后门。

### 19.2 blind safety review 与 data lock CLI

`calibagent-p8-review-safety` 是第 17.7 节链路的唯一入口，使用 required subcommand；禁止
提供一个能把 method/outcome 表和视频一起交给 reviewer 的捷径。

```text
prepare-bundle
  --run-root PATH --safety-event-id ID --config PATH
  --video PATH --sensor-evidence PATH
  [--contact-evidence PATH] [--geometry-evidence PATH]
  --age-recipient RECIPIENT --output-dir NEW_PATH

prepare-decision
  --bundle PATH --verdict serious|not_serious
  --reason-code CODE [--reason-code CODE ...] --output NEW_FILE

prepare-review-request
  --run-root PATH --bundle PATH --decision PATH --custodian-link PATH
  --age-identity-fd N --trust-registry PATH --output NEW_FILE

commit-review
  --bundle PATH --decision PATH --approval-request PATH
  --reviewer-approval PATH --safety-reviewer-approval PATH --output NEW_FILE

ingest-review
  --run-root PATH --bundle PATH --decision PATH --approval-request PATH
  --reviewer-approval PATH --safety-reviewer-approval PATH
  --blind-receipt PATH --custodian-link PATH
  --age-identity-fd N --output-root PATH [--commit]

prepare-lock-request
  --delivery-root PATH --input-lock-manifest PATH --output-root PATH

lock
  --delivery-root PATH --input-lock-manifest PATH --approval-request PATH
  --pi-approval PATH --data-custodian-approval PATH
  --output-root PATH [--commit]

```

共同规则：`prepare-bundle/prepare-decision/prepare-review-request/commit-review` 因必填 NEW
output而直接写新的离线输出；`ingest-review` 默认只 validate/打印 plan，必须显式 `--commit`
才 append **pre-lock main journal**。`prepare-lock-request` 在 input lock 后只写 derived
`protocol_artifacts/<run>/post_lock/human_approval_requests/`；`lock --commit` 只写同一
excluded post-lock subtree，绝不 append main journal。`--age-identity-fd`
只读 inherited already-open descriptor，CLI 不接受私钥字符串/path/env，不写 argv/stdout/log，
读取后立即清空 buffer/关闭 fd。age X25519 实现和版本固定在 container/tools manifest。

`prepare-bundle` 是 custodian-side 操作。它以 safety event ID 做幂等 reservation，生成随机
opaque `review_token` 和中性文件名；相同 event crash-resume复用同 token。reviewer bundle
只允许第 17.7 节 `p8.safety-review-bundle.v1` 的完整 exact fields，其中
`video_start_ns/video_end_ns` 是独立顶层字段，所有 path/hash 都是两个独立字段，
不存在名为 `criteria_path/hash` 或 `neutral_video_path/hash/start/end` 的字段。禁止 run/session/block/
method/scientific-unit/attempt ID、command、posterior、algorithm outcome、endpoint metric和
可反推 method 的原始路径/metadata。中性媒体是 raw evidence 的字节相同 copy或批准的
lossless redaction；hash linkage写入仅 custodian 可解密的
`custodian_links/<object_sha256>.age`，内容为 token→完整 event/attempt/commit/evidence refs。

`prepare-decision` 不访问 run root，只从 neutral bundle和 frozen criteria构造 §17.7 strict
`SafetyReviewDecision`；verdict/reasons进入 `decision_sha256`。
`prepare-review-request` 是 custodian-side：它解密 link取得 robot/run/dataset context，验证
decision→bundle→criteria，随后用第 6.5.2 节 factory产生
`purpose=SAFETY_REVIEW,subject_kind=BLIND_SAFETY_VERDICT,
subject_sha256=decision_sha256` 的 HumanApprovalRequest。CLI 不接受 subject/roles/TTL override。

`commit-review` 不访问 run root；它验证 decision、共同 approval request、两个 approval 的
reviewer IDs/key/nonce不同、bundle/criteria和 required evidence，且从 decision读取 verdict/
reasons（argv没有第二份 verdict入口），输出 strict
`BlindSafetyReviewReceipt{schema_version,review_token,bundle_sha256,
decision_path,decision_sha256,approval_request_path,approval_request_sha256,
reviewer_approval_path,reviewer_approval_sha256,
safety_reviewer_approval_path,safety_reviewer_approval_sha256,
reviewer_id,safety_reviewer_id,method_and_metric_blinding_attested=true,verdict,reason_codes,
reviewed_utc,receipt_sha256}`；两 approval均为 purpose=SAFETY_REVIEW、共同 subject
等于 decision hash，roles分别为 safety_reviewer与safety_operator且person/key不同。
receipt 的 path 是可预计算的 content-addressed class-relative destination；ingest后必须解析。
`ingest-review` 在 custodian 侧解密 link、逐 hash回链原始证据，并把 bundle/decision/request/
approvals/receipt copy进各自 content-addressed pre-lock目录，
构造含真实 identity refs 的最终 SafetyReview record并 append+fsync
`SAFETY_REVIEW_COMMIT`；reviewer从未看到 mapping。相同 token/receipt 幂等，不同 verdict或
link是 integrity failure。

所有 required review ingest完成且 main journal封口后，exporter才可生成 input lock。
`prepare-lock-request` 重扫 strict input lock、确认其 safety-review tail/count与 journal一致，
构造第 6.5.2 节 `data_lock_approval_subject_sha256` 和唯一
`purpose=DATA_LOCK` HumanApprovalRequest；request直接写 post-lock request class，输出 canonical
path/hash供 PI/data custodian signer使用。它不得写 DataLock或主 journal。

`lock` 必须验证全部 required safety event已有有效 review、raw/export/input-lock hash固定、
没有 pending unit/review/deviation，且两份 approval签同一 `prepare-lock-request` output；
无 `--commit` 只打印 plan且不写。`--commit` 把两 approval content-addressed copy到 post-lock，
再写 §18.4 exact DataLock record和 `p8.data-lock-commit.v1` detached object。`--output-root`
必须逐位等于从 delivery/run 推导的 `protocol_artifacts/<run>/post_lock`，不能另选目录。
相同完整 request幂等返回同 paths；同 run的不同 effective lock拒绝。
canonical raw/export保留真实 method ID，但 blind reviewer
永远只收到 opaque bundle，不能访问 run root或 outcome tables；本协议不生成虚假的
method-blinding key/unblinding mapping。analyzer 必填
`--data-lock-commit PATH` 并逐 hash验证；缺 lock/review任一环节退出 6，不产生统计 GO。

### 19.3 watchdog abort reset CLI

`calibagent-p8-reset-abort` 是 `AcknowledgeTechnicalAbort` 与 `ResetAbortLatch` 的唯一人工
coordinator；run/retry/resume不得内嵌或猜测 reset receipt。参数精确为：

```text
calibagent-p8-reset-abort prepare
  --mode technical-ack|safety-reset
  --run-id RUN --robot-id ROBOT --dataset-role DEV|CONFIRM
  --config PATH --output-root PATH --robot-state-root ABS_DURABLE_PATH
  --reason TEXT --expected-latch-reason CODE --trust-registry PATH
  --reset-request-output NEW_FILE --approval-request-output NEW_FILE
  --report NEW_FILE

calibagent-p8-reset-abort apply
  --reset-request PATH --approval-request PATH --config PATH
  --output-root PATH --robot-state-root ABS_DURABLE_PATH
  --operator-approval PATH --safety-operator-approval PATH
  --report NEW_FILE
```

`prepare` 调一次 `GetReadiness`，要求 stationary+zero且 mode/reason匹配当前 latch；它把
atomic challenge（boot/state sequence/state hash及 quota/receipt/active-scope/last-reset heads）
冻结为 strict `ResetAuthorizationRequest`，并通过第 6.5.2 factory产生
`purpose=RESET` HumanApprovalRequest。两个 NEW output和 report可写 run protocol artifacts，
但不注册 receipt、不改 robot-global state。随后两个人员用 signer `sign` 子命令签共同 request。

`apply` 不再接受 mode/run/robot/dataset/reason/target override；全部从两个 request读取并交叉
验证。它重新取 atomic readiness，要求仍逐位等于 frozen target challenge且 approval未过期，
然后构造/持久化本地 `p8.gate.reset.v1` receipt →
`RegisterOperatorGateReceipt` → 构造 authorization → mode technical 调
`AcknowledgeTechnicalAbort`，mode safety 调 `ResetAbortLatch` → 重新取 atomic readiness并
验证 DISARMED、旧 target hash和 consumed authorization hash。任一 head在中途变化则 CAS
失败并要求重新 `prepare`；不得重用旧 challenge或在 CLI 指定目标 state/hash。

输出 `reset_abort_report.json` 至 run protocol artifacts，含 request/receipt/authorization/
service response path/hash、before/after status cut和 exit code；相同 authorization+target在
response丢失后幂等返回同 report。operator approval不含私钥，只是已签 canonical approval
文件。prepare/apply各自 output type和path/hash都写 report。exit 0=完成，2=config/schema，
3=readiness/approval，4=safety仍 latched或CAS冲突，
5=technical/persistence failure。

### 19.4 十四个 wrapper 的 exact executable contract

本节把入口名单转换为可直接实现的命令合同。未出现在下列 argv 的选项必须被
argument parser 拒绝；不得增加 `--method`、`--route`、`--map`、`--command`、
`--seed`、`--skip-*`、`--overwrite` 或任意降低计划数的快捷参数。只读 input `PATH` 全部先做
`resolve(strict=True)`、symlink/ownership/root sentinel 检查；`NEW_FILE/NEW_DIR/ABS_NEW_PATH`
只对已存在父目录 `resolve(strict=True)`，随后要求 leaf `lstat` 不存在，并使用
same-filesystem temp + fsync + atomic rename 创建。runner 的 fresh `--output-root` 使用该
ABS_NEW_PATH 规则；显式 `--resume-run-id` 时 output root 必须已存在、strict resolve且其
run/sentinel/hash与 resume ID相符。`--help`
在任何输入缺失时仍 exit 0，不 import ROS graph、不读机器人、不写文件。

除已有更严格 typed output 的 static preflight/review/reset/sign/analyze 外，下文的 `--report`
必须通过 `schemas/p8/operation_report.schema.json`。顶层 key 精确为
`schema_version,operation,mode,dataset_role,run_id,block_id,shift_id,
scientific_unit_id,request_uuid,previous_attempt_uid,dry_run,armed,input_refs,read_paths,written_paths,state_before,
state_after,artifact_refs,started_utc,finished_utc,exit_code,reason_codes,report_sha256`；
`schema_version="p8.operation-report.v1"`。`dataset_role` 仅在
`CONFIG_VALIDATE/TRACKED` 和 `FREEZE/STAGE_INTEGRATION` 的 `dataset_role` 为 JSON null；
`FREEZE/SEAL_DEV` 从 stage 推导为 `DEV`，`FREEZE/PREPARE|SEAL` 推导为 `CONFIRM`；
config release 及其余操作必须从被验证输入推导出 non-null role。`run_id` 在 config/freeze 为 null，在
schedule/run/retry/replay/export/validate 为 non-null；`block_id` 仅两个 runner
和 retry 为 non-null；`shift_id` 仅 SHIFT runner/SHIFT retry 为 non-null；
`scientific_unit_id` 仅 retry 为 non-null。不适用字段使用 JSON `null`，不用空串。
`request_uuid` 与 `previous_attempt_uid` 也仅 retry 为 non-null，分别逐字等于
`retry_request_uuid` 和其 previous attempt；其他 operation 二者都为 null。
`operation/mode` 的唯一配对为
`CONFIG_VALIDATE/TRACKED|RELEASE`、`SCHEDULE/GENERATE|VALIDATE`、
`RUN_NAV/PAIRED_BLOCK`、
`RUN_SHIFT/SHIFT_PAIRED_BLOCK`、`RETRY_UNIT/SCIENTIFIC_UNIT`、
`REPLAY/VERIFY_ONLY`、`EXPORT/BUILD_INPUT_LOCK|SEAL_FINAL`、
`VALIDATE/PRE_LOCK|FINAL`、`FREEZE/STAGE_INTEGRATION|SEAL_DEV|PREPARE|SEAL`；
schema用条件分支拒绝其他组合。
dry-run/armed/resume 不另造 mode，分别由 `dry_run,armed` 和 input refs/state证明。
`armed=true` 只允许带 `--arm` 的 RUN_NAV/RUN_SHIFT/RETRY_UNIT；这些 operation省略
`--arm` 时固定 `dry_run=true,armed=false`。其余 operation固定
`dry_run=false,armed=false`（它们是在真实执行只读/生成动作，不是假装执行运动）。
`input_refs/artifact_refs` 的每个 item 恰为第 5.3 节 `ContentAddressedRef` 的五个字段
`relative_path,semantic_sha256,raw_sha256,size_bytes,schema_version`，并统一按
`(semantic_sha256,relative_path,raw_sha256,size_bytes,schema_version)` 排序；不存在未定义的
`logical_role` 或 `path` alias。`read_paths/written_paths/reason_codes` 是排序去重数组；
`state_before/state_after` 是 nullable `GlobalStateProof` ref。`report_sha256` 按排除自身后的
JCS bytes 计算。report 可以放在 run root 的明确 report leaf，但 export/freeze 的
report 必须位于新 delivery/release exact allowlist 之外，避免污染被 seal 的树。

| wrapper | 读取 | 唯一允许的写入/外部状态变更 | 一次 invocation 的粒度 | 可返回的 exit |
|---|---|---|---|---|
| `config_validate_p8` | repository 或 frozen release | 仅 `--report` | 一个 tracked tree 或一个 release | 0,2,6 |
| `generate_p8_schedules` | generate读两个 role-matched config template；validate读 materialized config | 新 schedule dir 和 `--report`；无 robot/run state | 同一 `run_id` 的三份 schedule+manifest | 0,2,6 |
| `preflight_p8` | release/config/schedule 与可选现场状态 | 仅 strict `p8.static-preflight-report.v1`；`--contact-robot` 只做短命 heartbeat/零命令/readback | 单个 NAV 或 SHIFT static snapshot | 0,2,3,4,5 |
| `run_p8_nav` | 冻结 NAV block 及 live state | armed 时写 raw/journal/protocol/global records并发命令 | 一个完整 paired NAV block | 0,2,3,4,5,6 |
| `run_p8_shift` | 冻结 shift×block 及 live state | armed 时写 raw/journal/protocol/global records并调用 changeover | 一个完整 shift×paired block | 0,2,3,4,5,6 |
| `retry_p8_unit` | 一个 blocked unit 的完整 lineage | 仅 armed 时写一个 RERUN_TECH transaction | 一个精确 scientific unit | 0,2,3,4,5,6 |
| `review_p8_safety` | 指定 event/bundle/decision/request/approval/receipt/lock input | 七个子命令依次只写 `SafetyReviewBundle`、`SafetyReviewDecision`、SAFETY_REVIEW request、`BlindSafetyReviewReceipt`、`SafetyReview+SAFETY_REVIEW_COMMIT`、DATA_LOCK request、`DataLock+DataLockCommit` | 一 event、一 receipt 或一 dataset lock | 0,2,3,5,6 |
| `reset_p8_abort` | prepare读 atomic cut；apply另读共同 request与两 approval | prepare写两 request；apply做一次 CAS reset/ack及 report | 一个 latched/technical-abort target | 0,2,3,4,5 |
| `sign_p8_approval` | prepare读 strict subject；preview/sign读 request/registry；sign另读 inherited key fd | prepare写一 request；sign写一 HumanApproval | 一 subject request或一 person×role approval | 0,2,3,5 |
| `replay_p8` | 一 run 的 immutable prefix | 仅新 replay report；不 repair | 从 INIT 到指定 checkpoint 的完整 prefix | 0,2,5,6 |
| `export_p8_delivery` | build读 sealed run/release；seal-final读锁定 delivery/DataLock/analysis | build新建 input-locked delivery tree；seal-final只写 final delivery manifest/checksums；两者写外部 report | 整个 run/delivery，不支持 method/block 子集 | 0,2,5,6 |
| `validate_p8_delivery` | 一 delivery 及 release | 仅外部 report | 整个 pre-lock 或 final delivery | 0,2,5,6 |
| `analyze_p8_confirmatory` | DataLock 锁定的整个 delivery input | 仅新 confirmatory analysis JSON | 整个 run 的预注册分析 | 0,2,5,6,7 |
| `freeze_p8_release` | repository/remote/gates/integration stage/candidate/DEV delivery | build/finalize 写 typed gate report；stage写 immutable integration tree；seal-dev/prepare/seal分别写 DEV release/candidate/final release；stage/seal-dev/prepare/seal 另写外部 operation report | 一 gate、stage、DEV release、candidate 或完整 CONFIRM release | 0,2,3,5,6 |

#### 19.4.1 config validator

只有下列两种调用：

```text
calibagent-p8-config-validate tracked
  --repository-root PATH --report NEW_FILE

calibagent-p8-config-validate release
  --release-root PATH --dataset-role DEV|CONFIRM --report NEW_FILE
```

`tracked` 按第 3 节目标树检查全部 P8 schema/config template/map/command/test fixture、
console entry 和 source→release mapping；`release --dataset-role DEV` 检查第 19.4.7 节
`p8.dev-release.v1`，`release --dataset-role CONFIRM` 按 handoff §3.1 exact allowlist 检查
`p8.release.v1`。两者都验证 manifest/checksums、materialized-config provenance和十四
wrapper `--help`，且纯只读，
绝不会自动格式化或填默认值。schema/config/hash 错误 exit 2；release bytes/
allowlist/checksum 错误 exit 6。
两种模式的 `--report` 都必须位于被检查的 repository/release root 之外；否则在读任何
input 前 exit 2，不能用 validator report 污染被声明只读或 exact-allowlist 的目标。

#### 19.4.2 schedule generator/validator

```text
calibagent-p8-schedule generate
  --nav-template PATH --shift-template PATH --run-id RUN
  --dataset-role DEV|CONFIRM --output-dir NEW_DIR --report NEW_FILE

calibagent-p8-schedule validate
  --nav-config PATH --shift-config PATH --schedule-dir PATH
  --dataset-role DEV|CONFIRM --report NEW_FILE
```

`generate` 只接受 `p8.nav|shift-*-template.v1` 且 role/run ID 与 argv 逐位相同的
两份 template，从其已冻结 seed 产生且只产生
`nav_block_schedule.csv,shift_block_schedule.csv,shift_date_order.csv,
schedule_manifest.json`；不接受 CLI seed。一次必须生成 NAV 和 SHIFT 全套，
不能只生成一个 protocol。schedule manifest 必须记录两份 template raw hash，不引用
尚未生成的 materialized config hash。`validate` 只接受 materialized NAV/SHIFT config，
重算 template provenance、现有目录顺序、balance、cardinality
和 manifest hash，不改任何 byte。CONFIRM 的 NAV 必须是 30 blocks、8 methods、
仅按 canonical order `real_offset_slalom|real_weighted_arc` 两 route；SHIFT 必须是
`R1_command_gain_coupling|R2_payload_com|R3_surface_friction|R4_mixed_context`
×20 blocks×3 methods。DEV 则必须是 NAV 5 blocks×8 methods×2 routes 和
SHIFT 4 shifts×5 blocks×3 methods，并满足第 14 节 DEV exact entry/unit counts；
两种 role 的 run ID、seed、schedule manifest 和 block namespace 不得复用。缺文件/非法 config exit 2，已存 schedule 与重算结果不一致
exit 6。
`--report` 必须在 `--output-dir` 或被检查的 `--schedule-dir` 之外；因此 generate 的新
schedule dir 始终恰有上述四个文件，validate 也不能把 report 写进被验证目录。

#### 19.4.3 static no-motion preflight

```text
calibagent-p8-preflight static-no-motion
  --config PATH --schedule PATH --release-root PATH
  --output-root PATH --robot-state-root ABS_DURABLE_PATH
  --dataset-role DEV|CONFIRM --report NEW_FILE [--contact-robot]
```

`--schedule` 必须指向 `schedule_manifest.json`。无 `--contact-robot` 时只做 release/config/
path/schema/hash 和静态 graph expectation 检查；有该 flag 时还读取 topic/QoS/
clock/reference/firmware/battery/E-stop/watchdog readiness，并只允许发短命 heartbeat和
zero/readback challenge。它永不创建 `PreparedAttempt`、Scope/ArmAuthorization、quota、
lease、scientific cursor 或 attempt journal event。attempt-bound `RunPreflight.srv` 只能由 armed
runner 在 durable `PREPARED_ATTEMPT` 之后内部调用，没有第二个 standalone CLI。

static CLI 的 `--report` 是 operation-report 共同规则的 **typed exception**，只能
通过 `schemas/p8/static_preflight_report.schema.json`，不得写成
`p8.operation-report.v1`。该 schema 的顶层 key 精确为：

```text
schema_version,operation,mode,protocol,dataset_role,robot_id,run_id,
release_kind,root_manifest_path,root_manifest_sha256,source_commit,
config_path,config_sha256,schedule_manifest_path,schedule_manifest_sha256,
contact_robot,nonzero_command_count,release_verified,config_verified,
schedule_verified,topic_contract_passed,qos_passed,single_writer_passed,
zero_readback_passed,estop_ready,watchdog_ready,clock_ready,reference_ready,
firmware_ready,battery_ready,ready,started_utc,finished_utc,exit_code,
reason_codes,report_sha256
```

`additionalProperties=false`，且以上字段全部 required。常量为
`schema_version="p8.static-preflight-report.v1",operation="PREFLIGHT",
mode="STATIC_NO_MOTION"`；`protocol ∈ {NAV,SHIFT}`，`dataset_role ∈ {DEV,CONFIRM}`，
`release_kind ∈ {INTEGRATION_STAGE,DEV_RELEASE,CONFIRM_RELEASE}`。
`root_manifest_path` 依 release kind 只能是
`integration_stage_manifest.json|dev_release_manifest.json|release_manifest.json`；三个
`*_sha256` 均是对应已读 regular file 的 raw SHA-256，path 必须 strict-resolve 到
root 内且与 manifest/config/schedule 的相互引用逐位一致。`robot_id/run_id/source_commit`
从 root manifest 和 materialized config 共同推导，CLI 不接受覆盖。

`contact_robot=false` 时 `nonzero_command_count=0`，十个 live-check 字段
`topic_contract_passed,qos_passed,single_writer_passed,zero_readback_passed,
estop_ready,watchdog_ready,clock_ready,reference_ready,firmware_ready,battery_ready`
必须是 JSON `null`。`contact_robot=true` 时它们必须全为
boolean，`nonzero_command_count` 仍必须为 0；任一 live check 为 false 则
`ready=false,exit_code≠0`。`release_verified/config_verified/schedule_verified` 始终是
boolean；`ready=true` 当且仅当三项都 true，且在 contact mode 下十项 live check
也全 true。`exit_code=0` 当且仅当 `ready=true`；`reason_codes` 是 UTF-8 bytes
排序去重数组，PASS 时为空。`report_sha256=sha256(JCS(record 排除
report_sha256))`。文件 raw SHA-256 由 Gate B evidence filename/manifest 绑定，不回写自身。
attempt-bound backend `PreflightReport` 继续按第 5 节的完整 dataclass 和
`schemas/p8/preflight_report.schema.json` 持久化；两种 schema 不做 `oneOf`、不共用
schema version，runner 的 invocation-level `--report` 仍是 operation report。

`--release-root` 通常必须是 role-matched sealed DEV/final release；唯一例外是
Gate B 可将 strict `p8.integration-stage.v1` 作为 root，但必须使用 stage 内 CONFIRM
config/CONFIRM schedule、`dataset-role=CONFIRM`、`--contact-robot`，且仍只能 zero/readback。
static preflight report 必须按上述 typed schema 显式写 release kind 及 root manifest
path/hash；该 stage 例外不能被 runner 或 attempt-bound preflight继承。
readiness 不足 exit 3，已 latched exit 4，ROS/SDK 技术故障 exit 5。

#### 19.4.4 NAV/SHIFT runners

```text
calibagent-p8-run-nav
  --config PATH --schedule PATH --release-root PATH
  --output-root PATH --robot-state-root ABS_DURABLE_PATH
  --approval-inbox ABS_READ_ONLY_PATH --dataset-role DEV|CONFIRM
  --block-id BLOCK --report NEW_FILE [--resume-run-id RUN] [--arm]

calibagent-p8-run-shift
  --config PATH --schedule PATH --release-root PATH
  --output-root PATH --robot-state-root ABS_DURABLE_PATH
  --approval-inbox ABS_READ_ONLY_PATH --dataset-role DEV|CONFIRM
  --shift-id R1_command_gain_coupling|R2_payload_com|R3_surface_friction|R4_mixed_context
  --block-id BLOCK --report NEW_FILE [--resume-run-id RUN] [--arm]
```

`--schedule` 同样是 manifest path；新 run 的 `run_id` 只能来自 config/schedule，不接受
CLI 覆盖。省略 `--resume-run-id` 只允许在该 run namespace 不存在时创建新 run；
已存在时必须显式给出与 config/schedule/last checkpoint 全部相同的
`--resume-run-id`。它既用于 crash resume，也用于后续 invocation 从已完成 block
checkpoint 继续；从不自动搜索“最近 run”。`--block-id/--shift-id` 只是对冻结
next cursor 的二次确认，不是调度选择器；不匹配 exit 2。

runner 在任何 plan/arm 之前先检查 release kind：`dataset-role=DEV` 只接受
`p8.dev-release.v1` 与其 DEV config/schedule；`dataset-role=CONFIRM` 只接受
`p8.release.v1` 与其 CONFIRM config/schedule。integration stage、candidate、错 role config/
schedule/release 或缺 Gate 签名一律 exit 6，在拒绝前不创建 output root、不联机、
不发 heartbeat/zero/非零命令。

无 `--arm` 只做 plan/eligibility 并写 report，不创建 session/attempt/scope/lease。armed NAV
每次精确执行一个 paired block：8 methods 按 schedule 顺序，共 102 calibration
trials、64 validation trials、16 navigation episodes；每个 method 两个 episode 的 route
只能是 `real_offset_slalom` 和 `real_weighted_arc`，执行顺序由 schedule 决定。
armed SHIFT 每次精确执行一个冻结 shift×block 的 3-method paired set：
135 primary units 和 6 个 initial planned sentinel units，另加由已冻结失败条件
机械触发的 conditional sentinel/context return；不能按 method/stage 分开调用。

runner 是唯一能改 run cursor 的进程，必须严格走第 15–17 节交易。正常只在
paired block checkpoint 后 exit 0；blocked cursor 的 exit 按§19.1 dispatch table。SIGINT/SIGTERM
不跳过当前 unit：watchdog 先 zero，runner 写 typed terminal outcome，然后依 fault table
停在 durable checkpoint 或 blocked cursor。

#### 19.4.5 replay

```text
calibagent-p8-replay
  --run-root PATH --release-root PATH --run-id RUN
  --through-checkpoint latest|SHA256 --output NEW_FILE --verify-only
```

`--verify-only` 是必填的 safety acknowledgement，不提供 repair/apply 模式。工具在内存中从 INIT
按 journal sequence 重放到指定 checkpoint，重算 state/cursor/posterior/selection/
global-proof/bag range 并与已持久化对象逐 hash 比较。`--output` 是
`p8.operation-report.v1`，必须位于被重放 run root 之外。它不连接 ROS/
机器人，不删除 orphan candidate，不补写 journal/checkpoint。hash/lineage/replay mismatch
exit 6，读取/解码技术失败 exit 5。

#### 19.4.6 exporter, validator 和 analyzer

```text
calibagent-p8-export build
  --run-root PATH --frozen-release PATH --output-dir NEW_DIR
  --dataset-role DEV|CONFIRM|TEST_FIXTURE
  --build-input-lock-manifest --report NEW_FILE

calibagent-p8-export seal-final
  --delivery-root PATH --frozen-release PATH
  --input-lock-manifest PATH --data-lock-commit PATH
  --analysis PATH --report NEW_FILE

calibagent-p8-validate-delivery
  --delivery-root PATH --frozen-release PATH --phase pre-lock|final
  --report NEW_FILE [--fixture-profile mini]

calibagent-p8-analyze
  --delivery-root PATH --input-lock-manifest PATH
  --data-lock-commit PATH --analysis-plan PATH --output NEW_FILE
  [--verification-only --expected PATH]
```

`build` 一次消费整个 sealed run，新建 handoff §11 delivery tree、所有 exported
tables/class indices 和 `manifests/input_lock_manifest.json`。`--build-input-lock-manifest`
必须显式出现，防止产生一个看似完整但无法 DataLock 的目录。export
必须在创建任何 output byte 前确认 run 无 pending attempt/review/deviation；不接受
block/method 子集，不回写 run/global state，不覆盖 output。`--report` 不能位于
`--output-dir`下。raw/journal 解码故障 exit 5，任何 identity/hash/cardinality/
recompute mismatch exit 6。

`seal-final` 只允许 `dataset_role=CONFIRM|TEST_FIXTURE`；role 从 delivery/release推导，
不接受 argv override。五个 input path 必须分别等于同 delivery/frozen release 的固定
allowlist path；analysis 必须是 analyzer 已完成的
`analysis/confirmatory_analysis.json`，GO 或 NO_GO 都可 seal，不允许只 seal 有利结果。
它先完整重跑 pre-lock validation、DataLockCommit 回链、analysis plan/report self-hash 和所有
input class index/raw hash，确认 `manifests/delivery_manifest.json` 与 root
`checksums.sha256` 尚不存在，再生成下文 strict final artifacts。不重写任何锁定
input、post-lock object 或 analysis。

validator `pre-lock` 允许缺 DataLock、analysis、final manifest/checksums，但必须验证
input subtree 和 input-lock 的全部 allowlist/hash/class index/replay/cardinality；`final` 要求
第 11 节整树、DataLock、analysis、final manifest/checksums 全部存在且 locked input
未变。它只读且 report 必须在 delivery root 外。`--fixture-profile mini` 仅能
与 manifest `dataset_role=TEST_FIXTURE` 一起使用；生产数据出现该 flag exit 2。
validator 不返回 7。

analyzer按来源分别验证三个 hash-bound input，不能要求尚未生成的 final delivery manifest：
`analysis_plan` 必须解析到 frozen release manifest/checksums，且 raw hash等于 input-lock、
DataLock和DataLockCommit所绑定值；`input_lock_manifest` 必须位于 delivery固定路径，通过自身
raw/semantic hash，并被 DataLock/DataLockCommit逐位引用；`data_lock_commit` 必须位于同 run
excluded post-lock allowlist、通过 strict schema/self-hash并解析其 DataLock/request/approvals。
analyzer启动时 `manifests/delivery_manifest.json` 和 final `checksums.sha256` 必须尚不存在；
它们只在 analysis成功写出后由 final seal生成并覆盖 analysis/post-lock。
`--output` 对生产数据必须精确是不存在的
`<delivery-root>/analysis/confirmatory_analysis.json`。生产模式不允许
`--verification-only/--expected`；TEST_FIXTURE 则必须两者同时出现，只做 golden
comparison、绝不产生 GO。完整性/锁定错误 exit 6，分析环境或计算失败 exit 5；
生产统计 GO exit 0，完整输出 NO-GO report 后 exit 7，fixture 精确匹配 exit 0。

#### 19.4.7 freeze release

```text
calibagent-p8-freeze-release build-gate-a
  --repository-root PATH --nav-template PATH --shift-template PATH
  --remote-ref REF --evidence-dir ABS_NEW_PATH --output NEW_FILE

calibagent-p8-freeze-release finalize-gate-report
  --unsigned-report PATH --approval-request PATH
  --approval PATH [--approval PATH ...]
  --trust-registry PATH --artifact-root ABS_EXISTING_PATH
  --output NEW_FILE

calibagent-p8-freeze-release stage-integration
  --repository-root PATH --nav-template PATH --shift-template PATH
  --dev-schedule-dir PATH --confirm-schedule-dir PATH
  --topic-map PATH --safety PATH --extrinsic PATH
  --trust-registry PATH --criteria PATH --analysis-plan-template PATH
  --container-image-digest-file PATH --gate-a PATH
  --gate-approval-root PATH --gate-evidence-root PATH
  --output-dir NEW_DIR --report NEW_FILE

calibagent-p8-freeze-release build-gate-b
  --integration-stage PATH --output-root ABS_NEW_PATH
  --robot-state-root ABS_DURABLE_PATH --output NEW_FILE

calibagent-p8-freeze-release build-gate-c
  --repository-root PATH --integration-stage PATH --gate-b PATH
  --gate-approval-root PATH --hil-evidence-dir NEW_DIR --output NEW_FILE

calibagent-p8-freeze-release seal-dev
  --integration-stage PATH --gate-b PATH --gate-c PATH
  --gate-approval-root PATH --gate-evidence-root PATH
  --output-dir NEW_DIR --report NEW_FILE

calibagent-p8-freeze-release prepare
  --repository-root PATH --integration-stage PATH --remote-ref REF
  --gate-b PATH --gate-c PATH --dev-delivery-root PATH
  --output-dir NEW_DIR --report NEW_FILE

calibagent-p8-freeze-release build-gate-d
  --candidate PATH --dev-delivery-root PATH --output NEW_FILE

calibagent-p8-freeze-release seal
  --candidate PATH --gate-d PATH --gate-approval-root PATH
  --output-dir NEW_DIR --report NEW_FILE
```

四个 `build-gate-*` 是 Gate report 的唯一 generator，输出 `signatures=[]` 且已计算
`report_preimage_sha256` 的 strict `p8.gate.v1`；不接受调用者传 status/metrics/command
result。A 工具先 fetch `--remote-ref`，将解析得到的 40-hex remote commit、
`HEAD` 和 clean-worktree 状态写入 report，再执行本节下列冻结 source-only command
allowlist并从真实退出码生成 metrics。无法 fetch 或 HEAD 不等于 remote commit 仍输出
`status=FAIL`、`remote_synced=false`的 unsigned report；此时 `remote_commit=null`
仅允许在 FAIL report 中出现。PASS 必须 remote commit 为 40 位 hex且等于
`source_commit`。

Gate A 是 **source-only** gate，不得把尚未存在的 integration stage、DEV/final release、
现场 topic 或 HIL 当输入。build tool 先以 `mkdtemp` 在 repository 外创建
`GATE_A_TMP`，再按下列顺序执行恰好 14 条 command（`PY` 是当前 frozen
Python absolute path）：

Gate A 的两个 template argv 和内部派生量只有下列一种解释：

```text
--nav-template     = REPO/configs/experiments/p8_real_nav_confirmatory_template.yaml
--shift-template   = REPO/configs/experiments/p8_real_shift_confirmatory_template.yaml
NAV_DEV_TEMPLATE   = REPO/configs/experiments/p8_real_nav_dev_template.yaml
SHIFT_DEV_TEMPLATE = REPO/configs/experiments/p8_real_shift_dev_template.yaml
NAV_CONFIRM_TEMPLATE   = --nav-template 的 resolved path
SHIFT_CONFIRM_TEMPLATE = --shift-template 的 resolved path
DEV_RUN     = nav-dev.run_id = shift-dev.run_id
CONFIRM_RUN = nav-confirm.run_id = shift-confirm.run_id
```

DEV path 只能用对应 confirmatory basename 末尾的
`_confirmatory_template.yaml` 替换为 `_dev_template.yaml` 派生；不搜索目录、
不接受第三个 path override，不跟随 symlink。四份文件都必须是
REPO 内 tracked regular file，NAV/SHIFT 的 `protocol` 必须分别为 `NAV/SHIFT`，
DEV pair 的 `dataset_role` 必须均为 `DEV`，confirm pair 必须均为
`CONFIRM`。`DEV_RUN`/`CONFIRM_RUN` 是直接从四份 typed template 的 `run_id`
读取的非空字符串，不从 basename、日期或 argv 猜测；两者必须不同。
Gate A report 的 `run_id` 恒等于 `CONFIRM_RUN`。任一 basename、role、
protocol 或 pair run-ID 不等都是 Gate A integrity failure，07/08 不得用单侧
run ID 继续生成一份伪匹配 schedule。

```text
01 git diff --check
02 ruff check .
03 mypy src/calibagent ros2/calibagent_go2 scripts/build_readme_figures.py scripts/build_isaac_response_card.py
04 env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PY -m pytest -p pytest_cov
   --cov=calibagent --cov-branch --cov-fail-under=85 --cov-report=term-missing
   --cov-report=json:GATE_A_TMP/coverage.json
   --junitxml=GATE_A_TMP/pytest_non_hil.xml -o junit_family=legacy -m "not p8_hil"
05 env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PY -m pytest
   tests/replay/p8/test_golden_pipeline.py
   --junitxml=GATE_A_TMP/pytest_golden.xml -o junit_family=legacy
06 calibagent-p8-config-validate tracked --repository-root REPO
   --report GATE_A_TMP/config_tracked.json
07 calibagent-p8-schedule generate --nav-template NAV_DEV_TEMPLATE
   --shift-template SHIFT_DEV_TEMPLATE --run-id DEV_RUN --dataset-role DEV
   --output-dir GATE_A_TMP/dev_schedule --report GATE_A_TMP/dev_schedule_report.json
08 calibagent-p8-schedule generate --nav-template NAV_CONFIRM_TEMPLATE
   --shift-template SHIFT_CONFIRM_TEMPLATE --run-id CONFIRM_RUN --dataset-role CONFIRM
   --output-dir GATE_A_TMP/confirm_schedule --report GATE_A_TMP/confirm_schedule_report.json
09 PY -m calibagent.cli.audit_p8_source --repository-root REPO
   --dev-schedule GATE_A_TMP/dev_schedule --confirm-schedule GATE_A_TMP/confirm_schedule
   --output GATE_A_TMP/source_audit.json
10 colcon build --symlink-install
11 colcon test --event-handlers console_direct+
12 colcon test-result --verbose
13 PY -m calibagent.cli.audit_p8_cli_help --repository-root REPO --expected-wrapper-count 14
   --output GATE_A_TMP/cli_help_audit.json
14 git status --porcelain=v1 --untracked-files=all
```

01–09/13–14 的 `working_directory=REPO`，10–12 的 `working_directory=REPO/ros2`。
command 04 必须包含 golden pipeline；05 是独立、可见的二次确认。command 14 的
stdout 必须为空；全部临时 schedule/report 都在 `GATE_A_TMP`，不会伪造 clean
worktree。`commands[].argv` 是 string array，不经 shell；上面换行只为文档展示。
`required_command_count=14,passed_command_count=sum(exit_code==0)`。coverage 指标只能从
04 的 coverage JSON artifact 重算，不能采用 terminal summary。P8-owned production source
allowlist 精确为第 3 节目标树中的
`src/calibagent/core/navigation/**/*.py,src/calibagent/hardware/go2/**/*.py,
src/calibagent/backends/go2_ros.py,src/calibagent/eval/p8_real.py`，以及第 3 节列出的 16 个
P8 CLI Python files；`__init__.py` 或其他文件只有在 coverage JSON 的
`summary.num_statements>0` 时才进入 executable denominator。builder 把 coverage JSON path
严格归一化为 REPO-relative POSIX path，拒绝 absolute/relative alias collision，并要求上述
每个 tracked executable P8 file 恰出现一次。聚合 line/branch coverage 分别按所有 P8 file 的
`sum(covered_lines)/sum(num_statements)` 与
`sum(covered_branches)/sum(num_branches)` 重算；分母为 0、文件缺失或任何 nonfinite 值均 FAIL。
每文件 line coverage 同样从 integer counts 重算，不相信 JSON 中已格式化百分比。

`p8_test_count/p8_test_passed` 从 04+05 的 legacy JUnit XML 重建 node ID 后去重重算；合法 P8
node ID 的 source file 只能位于以下三个 fixed directories 或两个 exact governance files，
路径比较前只做 REPO-relative POSIX
normalization，不做 basename 模糊匹配：

```text
tests/unit/hardware/go2/
tests/integration/p8/
tests/replay/p8/
tests/governance/test_p8_source_delivery.py
tests/governance/test_p8_protocol_scope.py
```

node ID 由 legacy JUnit 的 `file,classname,name` 无损重建；缺属性、同一 node ID 的结果冲突、
`failure|error|skipped` 子节点或 collection warning 都不计 PASS并令 Gate A FAIL。05 的 node ID
set 必须非空、全部属于 `tests/replay/p8/test_golden_pipeline.py`，并且是 04 node set 的子集；
因此二次运行不虚增计数。Gate A 的 frozen minimum 是 120 个去重 non-HIL P8 node IDs；这是
S0–S10 实现后的软件充分性底线，不可用 P0–P7 tests 或 HIL 参数化 case 填充。

Gate A PASS 的机械谓词唯一为：14/14 command exit 0；P8 aggregate line coverage ≥90.0%；
P8 aggregate branch coverage ≥80.0%；每个 executable P8 file line coverage ≥70.0%；
`p8_test_count>=120` 且 `p8_test_passed==p8_test_count`；上述 source/JUnit set、04/05 subset 与
evidence hash检查全部成立。command 04 的 `--cov-fail-under=85` 是整个 `calibagent` 的额外
process-level backstop，不能代替这些 P8-only signed metrics。任一命令缺失、重排、用一条 shell
串替代或 exit非0都使 Gate A FAIL。§25 的 end-to-end acceptance 不是 Gate A
command allowlist，不得在此处要求未来 release。

09/13 是 tracked internal audit module，不是公开 wrapper。两者只接受上列 argv，`--output`
必须是不存在且位于 `GATE_A_TMP` 的 regular JSON file；成功时 stdout/stderr 均为空。
`audit_p8_source` 输出 strict `p8.source-audit-report.v1`，顶层 exact fields 为
`schema_version,repository_commit,dev_schedule_manifest_sha256,
confirm_schedule_manifest_sha256,audited_paths,violations,status,report_sha256`；
`audited_paths` 与 `violations` 均按 UTF-8 bytes 排序去重，PASS 要求 violations 为空。
`audit_p8_cli_help` 输出 strict `p8.cli-help-audit-report.v1`，顶层 exact fields 为
`schema_version,repository_commit,expected_wrapper_count,observed_wrapper_count,
entries,status,report_sha256`；entries 按第 19.4 节 14-entry 顺序，每项 exact fields 为
`logical_name,console_entry,source_module_path,help_exit_code,help_stdout_sha256,
help_stderr_sha256`，PASS 要求 count=14、所有 help exit 0 且 stderr 为空。两 report 的
self-hash 均为排除 `report_sha256` 后的 JCS SHA-256。退出码统一为 0=PASS，2=argv/schema/
path，5=subprocess/I/O，6=source/schedule/entry/hash integrity；即使 status=FAIL，只要 output
可安全创建也必须写 machine report，不能只打印自然语言。

B 工具只针对下述 immutable integration stage，内部用两份 **CONFIRM** config
与 stage 中唯一 CONFIRM `schedule_manifest.json`各调用一次§19.4.3 exact
static preflight（`dataset-role=CONFIRM`、强制 `--contact-robot`），并证明
nonzero command count=0。这两次调用只做 zero/readback，不解锁 CONFIRM runner；
Gate B 未 PASS 或 stage schema 不是 final release 时，任一 runner 都必须拒绝。
C 工具在联机或执行测试前必须验证 `--gate-b` 是 signed PASS，其
stage/commit/robot/run/role 与 `--integration-stage` 逐位相同。它必须从
`--gate-approval-root` 只解析 stage 内 signed Gate A 和该 signed Gate B 引用的
approval request/approval raw bytes，用 stage 内 frozen registry 离线验证两个 gate 的
request、preimage、role/person/key/nonce/TTL 和 Ed25519 签名。输入 root 若缺任一
A/B artifact、多 orphan artifact、已出现 Gate C/D artifact、错 stage/FAIL 或验签失败，
均 exit 3 且不创建 `--hil-evidence-dir`、不启动 HIL。通过后 C 工具才执行
冻结 `pytest -m p8_hil` 命令并按 §7.2 schema重算
`--hil-evidence-dir/hil_event_log.json`，不接受手填
max latency。D 工具先以生产 DEV role完整 validate/replay `--dev-delivery-root`，再从 frozen
analysis power plan重算 22 个 continuous cells、62 个 discrete checks、DEV 5-block
cardinality、map/shift counts和 serious event。证据不足只能产 FAIL report，
不能拒绝写报告或让 operator手填 PASS。

`build-gate-c` 的 `--hil-evidence-dir` 是本次 invocation 的 **NEW_DIR output**，
不是可读旧 evidence。tool 在确认 leaf 不存在后生成 fresh 128-bit
`hil_run_id`，以固定 environment
`CALIBAGENT_P8_HIL_RUN_ID=<id>,CALIBAGENT_P8_HIL_EVIDENCE_ROOT=<absolute-new-dir>`
启动 pytest；唯一 repository HIL event-collector fixture 使用 exclusive-create 写出 strict
`<root>/hil_event_log.json` (`p8.hil-event-log.v1`)。顶层 exact fields 为：

```text
schema_version,hil_run_id,dataset_role,robot_id,run_id,
integration_stage_manifest_sha256,source_commit,pytest_command_sha256,
command_started_utc,command_finished_utc,boot_ids,
scenario_summaries,case_refs,events,log_sha256
```

`dataset_role="DEV",robot_id=stage.robot_id,run_id=stage.dev_run_id`。`boot_ids` 是按首次出现
排序去重的 non-empty boot ID 数组；允许 fault matrix 真实重启 supervisor，但每个
timing-required event 的 decision/zero timestamp 必须属于同 `boot_id`。`events[]` 每项是
§7.2 strict SafetyEvent wire 的全部字段（`source_stamp` 编码为 exact
`{sec:int32,nanosec:uint32}` object，其余保持 wire 字段名/类型），再恰好增加
`hil_run_id,robot_id,source_commit,event_sequence,observed_utc`五字段。不重复新增
wire 已有的 `dataset_role/run_id`。item 也是 `additionalProperties=false`，按
`(boot_id,event_sequence,event_id)` 排序；ID 和 `(boot,sequence)` 均唯一。
每项 `hil_run_id/dataset_role/run_id/robot_id/source_commit` 与顶层相同，
`observed_utc` 在 command
window 内，且必须能从本次 pytest recorder/event journal 唯一回链；
`log_sha256=sha256(JCS(record 排除 log_sha256))`。pytest exit 0 但文件缺失/空、
旧 file、run/stage/time/sequence 不符或 orphan event 仍使 Gate C FAIL。log raw hash 必须出现在
Gate C `artifacts[]`。Gate C report 的共同 identity 仍是将来 CONFIRM candidate identity；
DEV HIL evidence identity 只出现在该 bound artifact/Gate C metrics，两者不得混成同一 run ID。

HIL scenario 次序/最少次数是 const，不由 pytest collection 结果或现场人员缩减：

```text
scenario_id              required_count  required_event_type
RESET_ZERO                    100         NONE
LOW_SPEED_TRIAL                30         NONE
NETWORK_CRASH                  10         TECHNICAL_STOP
REFERENCE_CRASH                10         TECHNICAL_STOP
STATE_CRASH                    10         TECHNICAL_STOP
RUNNER_CRASH                   10         TECHNICAL_STOP
ILLEGAL_COMMAND                10         SAFETY_STOP
WATCHDOG_TIMEOUT               10         TECHNICAL_STOP
BRIDGE_TIMEOUT                 10         TECHNICAL_STOP
PHYSICAL_ESTOP                 10         ESTOP
MODE_MISMATCH                  10         TECHNICAL_STOP
```

因此 required invocation 总数固定为 220。`scenario_summaries` 是上述顺序的
11 项，每项 exact fields 为
`scenario_id,required_count,required_event_type,executed_count,passed_count,failed_count`；
前三字段用上表 const，后三者从 `case_refs` 重算。`case_refs` 长度恰好 220，按上表
顺序再按 ordinal 1-based 排序；每项 exact fields 为
`case_id,scenario_id,ordinal,path,semantic_sha256,raw_sha256,passed,
related_event_ids`，path 固定为 future release-relative
`test_reports/p8_gate_evidence/gate_c/cases/<raw_sha256>.json`。

每个 case file 通过 strict `p8.hil-case-result.v1`，顶层 exact fields 为：

```text
schema_version,hil_run_id,case_id,scenario_id,ordinal,case_nonce_hex,
dataset_role,robot_id,run_id,source_commit,integration_stage_manifest_sha256,
started_utc,finished_utc,boot_id_before,boot_id_after,
trigger_ref,result_ref,zero_receipt_ref,safety_event_ids,
passed,reason_codes,case_sha256
```

`case_nonce_hex` 是每 invocation fresh 128-bit lowercase hex，220 个值唯一；
`case_id="P8-HIL/"+hil_run_id+"/"+scenario_id+"/"+ordinal(3 digits)`。
`trigger_ref,result_ref,zero_receipt_ref` 每项 exact fields 为
`schema_version,path,semantic_sha256,raw_sha256,size_bytes,media_type`，path 必须解析到
同 evidence root 的 `artifacts/<raw_sha256>.bin`，`media_type="application/json"`；
schema version 按顺序必须是
`p8.hil-trigger.v1|p8.hil-result.v1|p8.hil-zero-receipt.v1`。三个 artifact 都是
UTF-8 JCS JSON bytes，`raw_sha256` 对完整 bytes 计算，`semantic_sha256`
等于下文指定的 detached self-hash。zero receipt 必须证明本 case 最终
zero/readback，不能 null。
fault scenarios 的 `safety_event_ids` 至少一个且全部 join event log；
RESET_ZERO/LOW_SPEED_TRIAL 可为空，但 result/zero receipt 必须 pass。
每个 fault case 至少一个 joined event 的 `event_type` 必须等于上表
`required_event_type`，且 joined event 的 wire `hil_case_nonce_hex` 必须逐字符等于
case nonce；别的故障事件不能借用。`case.safety_event_ids` 必须与
result artifact 的 `observed_safety_event_ids` 完全同序相等。
`case_sha256=sha256(JCS(record 排除 case_sha256))`，case/trigger/result/receipt 的
hil-run/case/scenario/ordinal/nonce/run/source/stage identity 必须逐位一致，各自
timestamp 必须满足下文的有序时间窗而不是彼此相等。同 scenario/ordinal
只运行一次；失败 case 不得被第二个成功
case 覆盖，需要重做必须新 Gate C/hil_run_id 从 220 个 case 整套重跑。

三种 artifact 的 strict schema 均为 `additionalProperties=false`：

```text
p8.hil-trigger.v1:
schema_version,hil_run_id,case_id,scenario_id,ordinal,case_nonce_hex,
dataset_role,robot_id,run_id,source_commit,integration_stage_manifest_sha256,
boot_id,trigger_kind,requested_utc,requested_monotonic_ns,
target_component,fault_action,dwell_ms,
command_vx_mps,command_vy_mps,command_wz_radps,
trigger_acknowledged,trigger_sha256

p8.hil-result.v1:
schema_version,hil_run_id,case_id,scenario_id,ordinal,case_nonce_hex,
dataset_role,robot_id,run_id,source_commit,integration_stage_manifest_sha256,
started_utc,finished_utc,boot_id_before,boot_id_after,
trigger_semantic_sha256,trigger_raw_sha256,required_event_type,
observed_safety_event_ids,pytest_node_id,
assertions[{assertion_id,passed,observed_value_json}],
outcome,process_exit_code,result_sha256

p8.hil-zero-receipt.v1:
schema_version,hil_run_id,case_id,scenario_id,ordinal,case_nonce_hex,
dataset_role,robot_id,run_id,source_commit,integration_stage_manifest_sha256,
trigger_semantic_sha256,trigger_raw_sha256,receipt_observed_utc,
receipt,zero_receipt_sha256
```

`trigger_sha256|result_sha256|zero_receipt_sha256` 分别等于对排除自身 self-hash
字段的完整 record 做 JCS SHA-256。公共 identity 字段必须等于 case；
`dataset_role="DEV"`。`trigger_kind` 逐字符等于 `scenario_id`；
`target_component/fault_action` 的唯一映射为：

```text
RESET_ZERO       watchdog       reset_zero
LOW_SPEED_TRIAL  runner         low_speed_trial
NETWORK_CRASH    network_proxy  crash
REFERENCE_CRASH  reference_node crash
STATE_CRASH      state_node     crash
RUNNER_CRASH     runner         crash
ILLEGAL_COMMAND  command_relay  inject_illegal_command
WATCHDOG_TIMEOUT watchdog       withhold_lease
BRIDGE_TIMEOUT   bridge         suppress_ack
PHYSICAL_ESTOP   physical_estop press
MODE_MISMATCH    backend        set_mode_mismatch
```

`dwell_ms` 是 nonnegative integer。仅 `LOW_SPEED_TRIAL|ILLEGAL_COMMAND` 的三个
command 分量为 finite JSON number；其他 scenario 三项全为 JSON null，不得用
0 代替 null。`trigger_acknowledged=true` 才可判 case pass。result 的
`required_event_type` 逐字符等于冻结 matrix，RESET/LOW_SPEED 为字符串
`"NONE"`；两者不要求关联 SafetyEvent，也不得伪造 event 填数。
`outcome` 只允许 `PASS|FAIL`，`assertions` item 也是 strict object，
`observed_value_json` 是无末尾 LF 的 JCS JSON value 字符串。
`receipt` 是第 7.2 节 `ZeroReceipt.msg` 的 strict JSON 投影：`source_stamp`
为 `{sec:int32,nanosec:uint32}`，其余字段名/类型与 wire 完全一致；
`receipt.hil_case_nonce_hex=case_nonce_hex`，`zero_confirmed=true` 且
`robot_stationary=true` 才可 pass。`result.trigger_*` 和 `receipt.trigger_*` 都必须等于
case `trigger_ref`；case 的三个 ref semantic/raw/size 必须对实际 bytes 重算。
所有 UTC 都是 RFC 3339 UTC，必须满足下列非严格顺序：

```text
command_started_utc
  <= case.started_utc
  <= result.started_utc
  <= trigger.requested_utc
  <= zero_receipt.receipt_observed_utc
  <= result.finished_utc
  <= case.finished_utc
  <= command_finished_utc
```

`receipt.source_stamp` 转 UTC 后必须位于
`[trigger.requested_utc,receipt_observed_utc]`；每个 joined SafetyEvent 的
`observed_utc` 必须位于 `[trigger.requested_utc,result.finished_utc]`。
同 boot 时，`trigger.requested_monotonic_ns <= receipt.decision_monotonic_ns <=
receipt.zero_publish_monotonic_ns`，随后仅对 available 的 bridge-ACK/measured-stop 继续单调；
若 fault 真实导致 boot 变化，必须
`trigger.boot_id=result.boot_id_before`、`receipt.boot_id=result.boot_id_after`，不得跨 boot
比较 monotonic 值。未重启时 before/after/trigger/receipt boot ID 四者相等。

SafetyEvent 不新增 case ID 或 trigger hash；它的唯一完整 join key 是
`(hil_run_id,dataset_role,run_id,robot_id,source_commit,
integration_stage_manifest_sha256,hil_case_nonce_hex)`，其中前六项由 event-log
顶层/对应 item 与 case 逐位比较，nonce 来自 SafetyEvent wire。另外必须同时
满足上述 UTC/boot 窗、event ID 全 log 唯一、event ID 恰好出现在一个
result/case，且 220 个 case nonce 全局唯一。这些条件共同防止旧 event/
receipt 跨 case 重放。collector 不允许从 timestamp 或 active-case 全局变量推断 nonce，
validator 必须做
`trigger ↔ case ↔ result ↔ ZeroReceipt ↔ SafetyEvent` 的逐字段机械 join。

pytest exact argv 为
`[PY,"-m","pytest","-m","p8_hil","tests/hil/p8",
"--p8-hil-run-id",hil_run_id,"--p8-hil-evidence-root",root]`，
`working_directory=REPO`；除上述两个固定 env 外不注入跳过/计数 override。
pytest collection 必须恰好 220 个 node ID，每个 node ID 与 case ID 一对一。

Gate C report 的 `commands` 长度必须恰好为 1，`commands[0].argv` 就是上述
JSON string array（`PY`/`root` 已替换为实际 absolute string）。命令哈希的唯一
preimage/encoding 固定为 `UTF-8(JCS(commands[0].argv))`，无 BOM、无末尾 LF；
`pytest_command_sha256` 恒等于该 bytes 的 lowercase-hex SHA-256。environment、
working directory、stdout/stderr 和文档中的折行不属于该 preimage。builder
必须用同一个 in-memory argv array 启动 subprocess、写 `commands[0].argv` 和计算
hash；validator 必须从 signed Gate C report 重算，并要求其与
`gate_metrics.pytest_command_sha256` 和 `hil_event_log.pytest_command_sha256` 两者逐位相等。
任何 shell 串、参数重排、
相对/absolute path 替换或只改 log 字段都使 Gate C FAIL。

Gate A/B/C evidence root 均以 strict `p8.gate-evidence-manifest.v1` 封口。manifest 顶层
exact fields 为 `schema_version,gate_id,source_commit,
integration_stage_manifest_sha256,files,total_file_count,total_bytes,
evidence_tree_sha256,manifest_sha256`；`files[]` item 为
`artifact_kind,relative_path,semantic_sha256,raw_sha256,size_bytes`，按 path 排序并覆盖
除 manifest/局部 checksums 外的所有 evidence。tree/self-hash 分别对 counts+files 和排除
self 的完整 record 做 JCS SHA-256；局部 `checksums.sha256` 覆盖 manifest+files
不包含自身。Gate A 尚无 stage，因此它的 `integration_stage_manifest_sha256=null`，B/C
必须为同一 stage semantic hash。

Gate A PASS evidence 的 exact tree 是：

```text
gate_a/
├── logs/                         # 01..14 各一份 stdout.bin 与 stderr.bin，空输出也保留零字节文件
├── coverage.json
├── pytest_non_hil.xml
├── pytest_golden.xml
├── config_tracked.json
├── source_audit.json
├── cli_help_audit.json
├── dev_schedule_report.json
├── confirm_schedule_report.json
├── dev_schedule/                 # 三份 CSV + schedule_manifest.json
├── confirm_schedule/             # 三份 CSV + schedule_manifest.json
├── evidence_manifest.json
└── checksums.sha256
```

`build-gate-a --evidence-dir` 必须是尚不存在的
`reports/p8_gate_evidence/gate_a`。工具在 repository 外创建 private `GATE_A_TMP`，运行完
14 条命令后以 exclusive-create 将上树逐字节搬入 evidence dir，再封口 manifest/checksums；
不论 PASS/FAIL 都保留已经产生的 stdout/stderr，只有上树完整且可重算时 Gate A 才可 PASS。
Gate A `commands[i].stdout_sha256` 必须逐字节匹配固定 release-relative
`test_reports/p8_gate_evidence/gate_a/logs/<NN>.stdout.bin`；对应 stderr raw bytes/hash由
evidence manifest 的固定 `<NN>.stderr.bin` item 绑定；
`artifacts[]` 必须引用 Gate A evidence manifest。临时目录删除不影响离线复核。
Gate B root 恰含两份 preflight report；Gate C root 恰含 event log、
220 case JSON 和它们去重引用的 artifacts。Gate report 必须将 evidence manifest
path/semantic/raw hash 写入 `artifacts[]`，seal-dev/candidate/final 逐字节复制到 handoff
固定子树；对应 `artifact_kind` 唯一为
`GATE_A_EVIDENCE_MANIFEST|GATE_B_EVIDENCE_MANIFEST|GATE_C_EVIDENCE_MANIFEST`。

每个 unsigned report随后由 signer `prepare-request --purpose GATE_REPORT --subject <report>`
产生共同 request，各 required role签名；`finalize-gate-report` 只接受同一 request/preimage的
恰好所需 approvals，按 role/person/key排序写 signatures并输出 signed report。它不重算
preimage、不改变 status/metrics/artifacts。它使用 `--trust-registry` 对每个 key ID 查找
Ed25519 public key，验证 registry raw hash等于 request/approval/config/stage/candidate 绑定值，
并重算 request、approval payload/self-hash、role/person/key/nonce/TTL 和签名。CLI 不接受
public-key override；缺 registry 或任一验签失败 exit 3。A/B/C/D output basename分别固定为
`gate_a_software.json,gate_b_static_integration.json,gate_c_hil.json,
gate_d_confirm_ready.json`；unsigned文件必须在临时 report root，final signed文件写
`reports/p8_gates/` 的相应 NEW path。由其他脚本或人工编辑的 report一律不被 stage/prepare/seal
接受。实现 source 就是 tracked `src/calibagent/cli/freeze_p8_release.py` 与
`hardware/go2/release.py`，不新增第十五个 hidden CLI。

`--artifact-root` 必须逐字符等于 repository 外层生成物 root
`reports/p8_gate_approvals`。finalizer 将 request/approvals 的原始 canonical bytes 以
exclusive-create/idempotent-same-bytes 写入
`{requests,approvals}/<raw_sha256>.json`，再把 future release-relative path
`test_reports/p8_gate_approvals/...` 写入 signature projection。若同 raw-hash filename 已有
不同 bytes、artifact root 有 symlink/额外类型，或 report 与 copies 无法离线验签，退出 6。
stage/seal-dev/prepare/seal 各自只复制其纳入 Gate 所引用的 exact request/approval
subset，final release 的合集不得有 orphan approval。

`--gate-approval-root` 必须 strict-resolve 到 finalizer 使用的同一
`reports/p8_gate_approvals`，其一级只允许 `requests,approvals`；调用者不能传
某个人的单文件或其他 root。phase 的 **artifact exact allowlist** 为：
`stage-integration` 只有 signed Gate A 引用集；`build-gate-c` 入口只有
signed Gate A+Gate B 引用集；`seal-dev` 只有 A+B+C 引用集；`seal` 在
candidate 已含 A/B/C 的基础上只从外部 root 解析 Gate D 引用集。每个阶段的
exact set 是所述 signed gate `signatures[]` 中 request/approval path+raw hash 的去重并集；
缺失、额外 regular file、symlink 或同 hash 异 bytes 全部失败。
`--gate-evidence-root` 必须 strict-resolve 到共同生成物 root
`reports/p8_gate_evidence`。phase allowlist 固定为：build A 后及
`stage-integration` 时一级恰含 `gate_a`；build B 后恰含 `gate_a,gate_b`；build C 后及
`seal-dev` 时恰含 `gate_a,gate_b,gate_c`。Gate A 的 `--evidence-dir`、Gate B 的
`--output-root`、Gate C 的 `--hil-evidence-dir` 必须分别是尚不存在的
`<root>/gate_a|gate_b|gate_c`；不得用删除已有子树来“重跑”。stage 只验证并复制 Gate A
evidence；seal-dev 通过三个 evidence manifest/checksums 和 signed report artifact refs 找 raw bytes，不使用 report 中的
future release-relative path 猜 source path。prepare 不再读外部 root；它只从 DEV delivery 锁定的
`frozen_release/test_reports/` 验证/复制 A–C approvals/evidence。

`stage-integration` 验证 signed Gate A 后，从 fixed source→release mapping解析 runtime bytes；
`--nav-template/--shift-template` 必须是 tracked confirmatory template，对应 DEV template由冻结
basename rule自动定位并纳入；`--dev-schedule-dir` 和 `--confirm-schedule-dir` 各恰含一套由对应
role 的 NAV/SHIFT template 生成的
`nav_block_schedule.csv,shift_block_schedule.csv,shift_date_order.csv,schedule_manifest.json`；
digest file只含一个 OCI
`sha256:<64hex>`。它生成 immutable `p8.integration-stage.v1`，其 runtime subset逐字等于最终
release runtime superset，但另含 DEV schedule 和 analysis-plan template；以
`integration_stage_manifest.json/checksums.sha256` 替代尚不存在的 DEV/final release manifest。
stage 只允许 Gate B 的 CONFIRM static-no-motion 与 Gate C 的 DEV HIL；所有 runner
均拒绝该 schema。

integration stage 的顶层 exact allowlist 为：

```text
p8_integration_stage/
├── common/
│   ├── protocol/          # 两份 docs + criteria + analysis-plan template
│   ├── configs/           # safety/topic/extrinsic/trust registry
│   ├── maps/
│   ├── commands/
│   ├── schemas/
│   ├── environment/
│   │   ├── analysis_requirements.lock.txt
│   │   ├── robot.Dockerfile
│   │   ├── robot_requirements.lock.txt
│   │   ├── rosdep.lock-or-install-manifest.txt
│   │   ├── third_party_robot_dependencies.yaml
│   │   └── dependency_evidence/ # 三 license + manifest 声明为 PATCHED 的 patch
│   ├── tools/
│   ├── tools_manifest.json
│   └── test_reports/      # signed Gate A + approvals + frozen gate_a evidence
├── views/
│   ├── DEV/
│   │   ├── configs/       # nav/shift DEV materialized configs only
│   │   └── schedules/     # DEV four-file schedule
│   └── CONFIRM/
│       ├── configs/       # nav/shift CONFIRM materialized configs only
│       └── schedules/     # CONFIRM four-file schedule
├── integration_stage_manifest.json
└── checksums.sha256
```

`common/` 内的展开子树逐项等于 handoff §3.1 对应子树，但不含 final
analysis plan、backend hardware report、Gate B–D、candidate/release manifest 或 final checksums。
其中 `common/environment/` 只允许 §4.2/§23.2 的 manifest-projected 文件；它们分别与同一 stage 后生成的
DEV release、candidate 和 final release 根目录下同名 `environment/` 文件逐字节相同。
`views/DEV` 和 `views/CONFIRM` 各只有上述 2+4 个 files；不允许同一
`schedules/schedule_manifest.json` 被两个 role 共用。stage checksum 使用这些完整
stage-relative path，不使用虚拟 overlay。`seal-dev` 将 `common/` 去掉前缀复制到
DEV release root，再将 `views/DEV/{configs,schedules}` 去掉两层前缀合并；
`prepare` 对 `views/CONFIRM` 做同样的确定性合并。目标路径冲突、多源同名
或 hash 不同立即退出 6。

`integration_stage_manifest.json` 必须通过
`schemas/p8/integration_stage_manifest.schema.json`，顶层 exact fields 为：

```text
schema_version,stage_id,dataset_role,robot_id,run_id,dev_run_id,
source_commit,remote_ref,remote_commit,
container_image_digest,gate_a_path,gate_a_sha256,runtime_paths,
config_materializations,
dev_schedule_manifest_path,dev_schedule_manifest_sha256,
confirm_schedule_manifest_path,confirm_schedule_manifest_sha256,
analysis_plan_template_path,analysis_plan_template_sha256,
runtime_subset_sha256,created_utc,stage_manifest_sha256
```

`schema_version="p8.integration-stage.v1",dataset_role="CONFIRM"`。`robot_id` 是 DEV/CONFIRM
两套 schedule 全部 row 的唯一共同 robot ID；`run_id` 是两份 CONFIRM template/
schedule 的 run ID，`dev_run_id` 是两份 DEV template/schedule 的 run ID，两者必须不同。
`source_commit=remote_commit` 且两者等于 signed
Gate A，`remote_ref` 也与 Gate A 逐字相同。`runtime_paths[]` 每项 exact fields 为
`relative_path,raw_sha256,size_bytes`，按 relative path UTF-8 bytes 排序，不含 symlink、
Gate B–D、candidate/final manifest 或自身 checksums。
`config_materializations` 是按
`DEV/NAV,DEV/SHIFT,CONFIRM/NAV,CONFIRM/SHIFT` 顺序的四项数组，每项 exact
fields 为 `dataset_role,protocol,template_path,template_raw_sha256,
materialized_path,materialized_raw_sha256,schedule_manifest_raw_sha256`，并按第 6.1 节
重放物化后逐字节相同。
`runtime_subset_sha256=sha256(JCS(runtime_paths))`；
`stage_id="P8-STAGE-"+runtime_subset_sha256[0:16]`；
`stage_manifest_sha256=sha256(JCS(record 排除 stage_manifest_sha256))`。stage 的
`checksums.sha256` 覆盖 manifest raw bytes 及所有 runtime path，不包含自身。
Gate B/C 必须从该 manifest派生 `source_commit,remote_ref,remote_commit,robot_id,run_id,
dataset_role`，不接受同名 CLI override。

`seal-dev` 生成的 `p8_dev_release/` 是 handoff §3.1 exact final tree 按下列变换得到
的 exact allowlist，除下列变换外不允许再增删 path：

- 移除 `protocol/analysis_plan.yaml`，保留
  `protocol/analysis_plan_template.yaml`，bytes 逐字等于 tracked template；
- `configs/` 保留四个 hardware config，并以 `views/DEV` 的
  `p8_real_nav_dev.yaml,p8_real_shift_dev.yaml` 取代 final tree 的两份 confirmatory config；
- `schedules/` 的四个 path 以 stage `views/DEV` 的四个 bytes 取代 CONFIRM bytes；
- `test_reports/p8_gates/` 只含 signed Gate A/B/C，不得有 Gate D；
- `test_reports/p8_gate_approvals/` 只含 Gate A/B/C 引用的 request/approval bytes；
- `test_reports/p8_gate_evidence/` 恰含 manifest/checksum 完整的 `gate_a,gate_b,gate_c`；
- 移除根目录 `candidate_manifest.json`；
- `release_manifest.json` 替换为 `dev_release_manifest.json`，其余 docs/maps/
  commands/schemas/environment/tools 与 stage 绑定 runtime bytes一致。

`dev_release_manifest.json` 通过 strict
`schemas/p8/dev_release_manifest.schema.json`，顶层 exact fields 为：

```text
schema_version,release_id,dataset_role,robot_id,run_id,source_commit,remote_ref,remote_commit,
container_image_digest,integration_stage_manifest_sha256,
gate_report_refs,gate_approval_artifact_refs,tools_manifest_sha256,dev_schedule_manifest_sha256,
analysis_plan_template_sha256,release_paths,created_utc,
dev_release_manifest_sha256
```

`schema_version="p8.dev-release.v1",dataset_role="DEV"`；`robot_id=stage.robot_id,
run_id=stage.dev_run_id`。`gate_report_refs` 是按 A/B/C
顺序的三个 strict `{gate_id,path,sha256,report_preimage_sha256}` item，三者必须
PASS、验签成功、绑定同 stage/commit。`gate_approval_artifact_refs` 的 item
shape/path/hash 约束与 candidate 相同，且只能是 A/B/C 的完整去重集。
`release_paths[]` 每项 exact fields 为
`relative_path,raw_sha256,size_bytes`，按 UTF-8 path bytes 排序，覆盖上述 allowlist
除 manifest/checksums 外的全部 regular files。
`release_id="P8-DEV-"+sha256(JCS(release_paths))[0:16]`；
`dev_release_manifest_sha256=sha256(JCS(record 排除 dev_release_manifest_sha256))`；
root `checksums.sha256` 按 raw bytes 覆盖 manifest 与全部 release paths，不包含自身。

DEV runner/preflight/replay/export/validator 的 `--release-root/--frozen-release` 必须是该
`p8.dev-release.v1`，且 config/schedule/CLI `dataset_role` 全部为 DEV；CONFIRM runner
必须是 handoff §3.1 sealed final `p8.release.v1`。两种 role/release 任一交叉
都退出 6。integration stage 只是 no-motion/HIL input，candidate 也不是 release，
二者均不得传给 runner。DEV release 只解锁 DEV motion，不可用于 CONFIRM或论文
确认性 GO。

`prepare` 的 candidate 也有 exact allowlist。它以 handoff §3.1 final tree 为基础，
包含两份 Markdown、criteria、analysis-plan template 与已物化 final plan、两份
CONFIRM materialized config、CONFIRM schedule、maps/commands/schemas/environment/tools、
backend hardware report、signed Gate A/B/C 及其 request/approval artifacts；唯一变换为：

- 移除 Gate D report 及其 request/approvals；
- 根目录只写 `candidate_manifest.json,candidate_checksums.sha256`，不写
  `release_manifest.json,checksums.sha256`。

除这两条外不允许任何额外/缺失 path。
`candidate_manifest.json` 必须通过 strict
`schemas/p8/candidate_manifest.schema.json`，顶层 exact fields 为：

```text
schema_version,candidate_id,dataset_role,robot_id,run_id,
source_commit,remote_ref,remote_commit,container_image_digest,
integration_stage_manifest_sha256,dev_release_manifest_sha256,
config_materializations,gate_report_refs,gate_approval_artifact_refs,
tools_manifest_sha256,analysis_plan_template_sha256,
pilot_input_lock_manifest_semantic_sha256,
pilot_input_lock_manifest_raw_sha256,pilot_input_tree_sha256,
analysis_plan_sha256,candidate_paths,created_utc,candidate_manifest_sha256
```

`schema_version="p8.release-candidate.v1",dataset_role="CONFIRM"`。
`config_materializations` 是 stage 的四项 exact array；`gate_report_refs` 是 A/B/C 三项；
`gate_approval_artifact_refs` 是这三个 Gate 全部 request/approval 的有序去重数组，
每项 exact fields 为 `artifact_kind,path,semantic_sha256,raw_sha256,size_bytes`。
`candidate_paths[]` 每项 exact fields 为 `relative_path,raw_sha256,size_bytes`，按 UTF-8 path
bytes 排序，覆盖 candidate allowlist 除 manifest/checksums 外全部 regular files。所有 nested
object/array item 均 `additionalProperties=false`。

`candidate_id` 无自循环地定义为
`"P8-CANDIDATE-"+sha256(JCS({source_commit,integration_stage_manifest_sha256,
pilot_input_lock_manifest_raw_sha256,analysis_plan_sha256,candidate_paths}))[0:16]`；
`candidate_manifest_sha256=sha256(JCS(record 排除 candidate_manifest_sha256))`。manifest
以 JCS bytes 原样写盘，因此它的 raw SHA-256 唯一定义
`candidate_release_sha256`；该 raw hash 不写回 manifest，而由 candidate 目录名、
Gate D body/signatures 和 final `release_manifest.json` 绑定。
`candidate_checksums.sha256` 按 relative path UTF-8 bytes 排序，覆盖
`candidate_manifest.json` 与 candidate_paths，不包含自身。一个合法 candidate 必须同时
重算 semantic self-hash、manifest raw hash、每个 path raw hash 和 checksums；任一相等关系
缺失都退出 6。

`seal-dev` 只在 signed Gate B/C 均绑定同 stage 且 PASS 后生成下文 strict
`p8.dev-release.v1`；这是唯一合法的 DEV motion release。
`prepare` 再要求 `--dev-delivery-root` 是用该 DEV release 采集、export 且
`validate-delivery --phase pre-lock` 成功的完整 DEV delivery；它重扫 input-lock 及 raw/
exported/posterior，从 input-lock raw hash 物化 final analysis plan，然后重验 clean source、
Gate A–C、pins/serious=0 与 `--remote-ref==HEAD==stage.remote_commit`。candidate 只装入
stage 的 CONFIRM runtime bytes、生成的 final plan、signed A–C 和 DEV input-lock identity；
任一 runtime byte变化都失败。`build-gate-d` 要求其 `--dev-delivery-root` 的
input-lock raw hash 逐位等于 candidate/final plan，再独立重算 22 个 continuous cells
和 62 个 discrete checks。
`seal`只验证 candidate+signed Gate D后新建 handoff §3.1 exact final release，不重生成
config/schedule/tool/plan。stage/seal-dev/prepare/seal 的 `--report` 必须在 output dir外。
Gate/approval不足 exit 3，source/release/candidate/hash/remote完整性错误 exit 6，schema/config
错误 exit 2，I/O/container技术故障 exit 5。

#### 19.4.8 review/reset/sign 的补充输出约束

第 19.2 节七个 review/data-lock subcommand 的 argv 就是 exact public API；typed outputs依次为
`SafetyReviewBundle`、`SafetyReviewDecision`、`HumanApprovalRequest(SAFETY_REVIEW)`、
`BlindSafetyReviewReceipt`、`SafetyReview+SAFETY_REVIEW_COMMIT`、
`HumanApprovalRequest(DATA_LOCK)`、`DataLock+DataLockCommit`。ingest无 `--commit` 只打印
pre-lock plan；lock无 `--commit` 只打印 post-lock plan。只有 ingest可 append main journal，
且必须发生在 input lock前；lock永不 append。完整性/解密/evidence linkage 错误 exit 6，
approval/readiness 错误 exit 3，持久化/工具故障 exit 5。

第 19.3 节 reset `prepare|apply` argv 是 exact public API，只额外允许标准 `--help`；不得增加
`--force`、`--target-state`、旧式 `--apply` flag 或嵌入 runner 的捷径。第 6.5.2 节 signer
`prepare-request|preview|sign` argv 同样是 exact public API：prepare-request只写 request，
preview只给 canonical request/payload hash；sign仅以
exclusive-create 写 `--output`，不触碰 run/global state；三者 argv不得混用。request/registry/role 错误 exit 2，
key/person/expiry/approval policy 错误 exit 3，fd/crypto/write 技术失败 exit 5。

---

## 20. 测试合同

### 20.1 纯 Python unit tests

必须新增并覆盖：

```text
tests/unit/hardware/go2/test_config.py
tests/unit/hardware/go2/test_frames.py
tests/unit/hardware/go2/test_reference.py
tests/unit/hardware/go2/test_command_path.py
tests/unit/hardware/go2/test_backend.py
tests/unit/hardware/go2/test_command_session.py
tests/unit/hardware/go2/test_watchdog.py
tests/unit/hardware/go2/test_trial_executor.py
tests/unit/hardware/go2/test_model_factory.py
tests/unit/hardware/go2/test_methods.py
tests/unit/hardware/go2/test_schedule.py
tests/unit/hardware/go2/test_nav_runner.py
tests/unit/hardware/go2/test_navigation_controller_state.py
tests/unit/hardware/go2/test_shift_actuators.py
tests/unit/hardware/go2/test_shift_runner.py
tests/unit/hardware/go2/test_journal.py
tests/unit/hardware/go2/test_export.py
tests/unit/hardware/go2/test_validate_delivery.py
tests/unit/hardware/go2/test_analysis.py
```

最低 cases：

- unknown/missing/UNSET/NaN config fail；
- frame direction、SE(2) causal velocity、clock jump；
- same-cut snapshot、cross-stream skew、boot/monotonic scope；
- 100 次 reset/zero；
- stale/nonfinite/frame/mode/BMS/motor/network/heartbeat 全 fail closed；
- persisted latch 在 backend/watchdog restart/reset 后不自动恢复；
- readiness/safety failure 在 PREPARED boundary 前不创建 attempt，boundary 后按
  technical-vs-safety 唯一分类并产生 scientific commit；
- typed OperatorCancelled、allowlist TechnicalFault 与未知 AssertionError/ValueError 三分，
  unknown 必为 UNCLASSIFIED_INTERNAL_FAULT/PAUSED_INTERNAL_REVIEW，不得伪装 cancel 或取得 retry；
- process heartbeat 可在 DISARMED/preflight 建立，但不授权 command；scope/attempt
  authorization 各自 canonical hash、scope quota、fresh preflight binding、同 attempt
  幂等 lease、跨 attempt/reused report 必拒绝；
- 逐一构造/round-trip `PRIMARY_BATCH/RERUN_TECH/RESUME_RENEWAL/
  CONDITIONAL_SENTINEL/CONTEXT_RETURN` ScopeAuthorizationRequest，验证 shift-scoped
  scope ID、parent/retry/activation nullable、wire hash 和 quota；NAV 必为
  NOT_APPLICABLE，四个 SHIFT scope 互不碰撞；
- 五种 typed gate payload、receipt sequence/previous hash、register service、scope/arm/
  changeover/context-return/reset receipt 交叉绑定；gap/rollback/同 ID 不同 bytes 拒绝；
- scheduler deadline 与 lease deadline 不混用；runner 不能绕过
  proposal→logical safety→relay wire safety；
- driver publish 显式 identity+lease；旧 lease、跨 attempt、并发 session 和隐式 current
  attempt 均拒绝并 zero；
- R1 model_input 与 transmitted 分离，model/detector 看不到 matrix；
- `CommandTelemetry` requested/relay-receive/publish/ACK monotonic 映射和 ordering；
- post-transform unsafe 不 clip、直接 latch；
- logical/wire 两条 slew history 和 full-horizon R1 preauthorization；
- B0 0、B1 30、其余 12；
- B0 posterior version 永远 0；
- validation/NAV posterior hash 不变；
- 八方法无共享 mutable state；
- B6 runtime 不调用 RNG；
- no-update state transition 不伪记 update；
- pre-shift alarm 走同一 inflation path；
- missed detection/invalid window/penalty；
- stage-blind `PolicyObservation` 无 context leakage；
- recovery 后固定命令且 no update；
- sentinel 两命令、nominal snapshot、阈值、复验集；
- conditional sentinel/context-return ID allocator crash replay，planned/conditional/attempt
  计数分层；
- calibration start gate/context-return 不进 endpoint；
- manual context-return 的 MANUAL_DISARMED prepared boundary、零 CommandPacket、crash/
  cancel/safety/technical physical→scientific→checkpoint 与 RERUN chain；
- changeover planned attempt、mid-changeover crash、RECOVER_NOMINAL、递增 retry/parent link
  与 effective selection；
- changeover result→marker ACK→protocol checkpoint 每个写点 crash，断言 actuator count≤1、
  marker idempotent replay、pre-gate nullable operator receipt、posterior不变；
- NAV command session DEV 50/100 Hz 与 CONFIRM 固定 50 Hz、initial stabilization、
  NavigationMarker wire/golden、幂等
  close/abort 和终止优先级；
- controller cadence 严格验证 integer decimation、active index 0 为 planner tick、Python
  ties-to-even `round`、CONFIRM 50/10/5、拒绝 55/10、按 index 重算 `t_s` 和
  absolute missed-deadline 不 catch-up；
- controller init/warmup 验证所有 zero/NaN/counter/flag、
  `feedback_resume_after_s=startup_delay_s`，以及 warmup 结束不重置两个
  previous-height 的 P7 parity；断言 state 在 `stabilize_zero` 前创建并以同一
  lifecycle identity 跨过 WARMUP/NAVIGATE_START；
- EMA 仅在 planner tick 以 raw causal 三轴 velocity 更新，且在 B0、startup
  delay、recovery 和 finished 分支也按同样顺序更新；检查连续 sample 的精确 EMA
  vector，并断言 terminal clear 发生在该 tick EMA 之后；
- feedback startup/reengagement 严格使用 `<` boundary；delay 内仍单次 inverse、
  deadline 后只在 correction norm `>1e-9` 时累加 update，B0/recovery 的 inverse
  callback call count 必须为 0；
- regular stall 在 detection threshold 前/当 tick，emergency 优先，N 个 zero ticks 恰覆盖
  N 个完整 planner interval，末 zero tick 设 reengagement deadline；zero 期间 stall 仍更新；
- total/regular/emergency recovery counters 分别累加，emergency 不消耗 regular
  budget；覆盖 emergency budget 耗尽后 regular trigger、连续 emergency retrigger 和两类
  budget 都耗尽；
- height guard 严格覆盖 unslewed detect→slew→slewed derate 两次调用、触发 tick
  即递减、孤立 latch 恰 N ticks、active-tick update counter、yaw 不变、未到 0
  不延长以及 recovery 清 latch；
- high-rate interlock 覆盖 direct-height 与 projected-height 两种 trigger、迟滞保持、
  `height>=release && height>=previous` 释放、每 active sample 累加 counter、将
  持久 compensated 置 zero、非 planner sample 释放后仍 zero 至下一 planner tick、
  不改 feedback deadline/EMA/recovery budget，以及 disabled 时 previous-sample height 不更新；
- recovery、height guard、high-rate interlock 重叠及 finished 分支，检查 zero 优先级、
  flag/counter 和下一 planner tick 的 slew history；特别检查 terminal 在非 planner
  sample 到达时 internal compensated 保留而 published/effective candidate 立即为 zero；
- `p7_navigation_controller_golden_v1.json` 逐 sample 重放；bool/int/enum/NaN
  placement 完全相同，float64 state/candidate bitwise 相同，且 P7/P8 都通过
  同一 fixture；
- NAV SUCCESS/TIMEOUT/COLLISION/technical/operator/internal 的 physical→metrics→scientific→
  checkpoint 全事务；open/close/abort/fsync异常 finalize count=1，collision 只在 post-commit
  exit 4；
- NAV/SHIFT 在 calibration、validation、episode、A–F stage 和 method/sequence 边界 resume，
  只恢复 checkpoint cursor/model/planner/detector/actuator state，不重复 motion；
- two-map/8-method/30-block cardinality；
- four-shift/20-block/3-method/45-trial cardinality；
- journal 每个写点 crash 后只恢复到最后 commit；
- full-row journal hash、immutable checkpoint/CHECKPOINT_COMMIT、合法 segment idle gap；
- TEST_FIXTURE identity/cardinality、blind innovation covariance=`pred+obs`；
- Gate D prepare→digest/sign→seal，无 self-hash 或 Gate D/freeze 循环；
- checksum 无 self-entry。

### 20.2 integration/fake tests

`fake.py` 提供 deterministic clock、driver、reference、state、recorder、watchdog。
integration 必测：

- 完整 trial raw→MeasurementPipeline；
- fake NAV 两图终止、collision、timeout；
- fake SHIFT 四 actuator/三方法；
- process crash、write-once、explicit resume；
- bag-like raw fixture→export→validate→analyze；
- P1 fixture replay observation parity；
- P6 fixture 在首个 alarm 之前的 NIS/CUSUM 数学 parity；pre-shift alarm 立即
  inflation、recovered 后固定命令是 P8 有意改动，用独立 golden tests，不谎称
  与 P6 全 trace parity；
- P7 fixture planner/slew/goal parity，以及六图 controller lifecycle end-to-end golden；
  提取前/后的 terminal flags、waypoint index、每 sample desired/inverse target/
  compensated/effective command、feedback/height/interlock flags、total/regular/emergency
  recovery counters、三类 update counters 和 episode metrics 必须一致；
- failed scientific outcome 保留，technical retry 机械选择。
- post-scientific integrity failure 不改写原 commit、不允许局部 RERUN_TECH，并令 affected
  block/sequence delivery fail。

### 20.3 ROS tests

colcon test 至少覆盖：

- 缺 topic/type/QoS/publisher rate；
- `RegisterScopeAuthorization`、per-attempt `ArmMotion` 的 hash/quota/idempotency；
- `RegisterOperatorGateReceipt` strict JSON/payload/sequence/persistence，以及 reset service
  必须引用已注册 typed receipt；
- telemetry 四个 monotonic 时刻缺失、乱序、跨 boot 均拒绝；
- vendor motion topic 多 publisher；
- 无 `--arm` 时 vendor topic 无非零；
- kill runner/reference/state/heartbeat 后 relay zero；
- kill recorder 时拒绝新 motion；
- command lease expiry；
- latch/reset service 权限和状态；
- R1 SetCommandTransform 必须绑定 changeover identity/pre-evidence/已注册双人 receipt，
  atomic activation/readback/persistence，旁路或 UID 不同内容重放拒绝；
- marker、telemetry、bag 时间边界；
- NavigationMarker/ChangeoverMarker exact type、RELIABLE+TRANSIENT_LOCAL QoS、single
  publisher、recorder fsync ACK/de-dup，detector subscription whitelist；
- runner 重启后保持 DISARMED。

### 20.4 HIL tests

在支架/低速批准条件下：

- 100 次 reset/zero；
- 30 次完整低速 trial profile；
- network、reference、state、runner crash、illegal command 各至少 10 次；
- watchdog/bridge timeout、物理 E-stop、mode mismatch；
- 最大 decision→zero publish ≤40 ms；
- physical stop latency 单列；
- 0 serious event。

### 20.5 CI

标准分析 CI：

```bash
ruff check .
mypy src/calibagent ros2/calibagent_go2 scripts/build_readme_figures.py scripts/build_isaac_response_card.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p pytest_cov --cov=calibagent --cov-report=term-missing
python -m calibagent.cli.audit_readiness --workspace .
```

新增 ROS container workflow：

```bash
cd ros2
colcon build --symlink-install
colcon test --event-handlers console_direct+
colcon test-result --verbose
cd ..
```

P8 完成后 `go2_ros.py`、P8 CLI/runner 都不在 coverage omit；不得被
legacy `run_*.py` glob 误排除。`.gitignore` 必须覆盖
`ros2/{build,install,log}/`。source-delivery audit 必须要求所有 P8
source/config/map/schema/launch/test、SDK pin 和 lock 被 Git 跟踪。

---

## 21. Coding agent 的实现顺序

每一步先写 test，再实现，再运行该步 gate。不得跳到机器人上边调边补架构。

### S0：保护现有证据

- 运行当前 pytest/ruff/mypy/audits；
- 记录 `reports/p8_implementation/s0_baseline.json`；字段为
  `source_commit,dirty_paths,command,exit_code,started_utc,ended_utc,stdout_sha256,
  artifact_paths`，stdout 原文存同目录文件；
- 不修改 P6/P7 frozen config/evidence；
- 新增 ADR-003 command boundaries。

通过：现有 suite 全绿，P7 六图仍完整。

### S1：纯 navigation 提取

- 新建 `core/navigation/waypoint.py`；
- P7 runner 改 import；
- old/new parity tests。

标准 CI 不安装 Isaac Lab，所以在删除旧函数之前先用 AST 只提取
`_planner_command/_slew_limit/_near_obstacle/_planner_hash` 四个 function node，
在仅注入 `numpy/json/hashlib/typing.Any` 的 namespace 执行 20 组 fixed cases，
生成 `tests/fixtures/p7_waypoint_legacy_cases.json`。fixture 保存旧
`p7_runner.py` full SHA-256、inputs、outputs、`rtol=1e-12,atol=1e-12`。新 pure
module 在无 Isaac 环境下与这个 oracle 比较。禁止在新/旧两边复制同一
段新实现后声称 parity。

通过：P7 unit tests 与 evidence governance 不变。

### S2：contracts/config/schema

- 建 target dataclasses/ports；
- NAV/SHIFT/hardware/map/topic schemas；
- strict loaders/full hashes；
- tracked command table generator 只用于 DEV/release build。

通过：所有 invalid config tests，CONFIRM cardinality tests。

### S3：fakes、clock、frames、reference

- deterministic fakes；
- source/receive/monotonic；
- extrinsic transform；
- causal velocity；
- rich state/freshness。

通过：golden frame/SE(2)/stale tests。

### S4：command path/watchdog state machine

- logical/post-transform/transmitted boundaries；
- R1 transform；
- two-stage safety；
- lease/latch/zero priority；
- no-update state event。

通过：fault matrix、R1 leakage、100 zero tests。

### S5：backend/trial executor

- 实现四 backend methods；
- absolute deadline profile；
- measure-only RawTrialData；
- finally-zero；
- attempt identity。

通过：fake full trial、fault at every phase、measurement parity。

### S6：method factory/schedule

- identity priors M1/M2；
- eight NAV methods including B6；
- SHIFT fresh models；
- Williams/near-balanced schedules；
- posterior atomic snapshots。

通过：budget、isolation、balance、hash tests。

### S7：NAV runner

- block orchestration；
- two map loader；
- 10/50 Hz controller；
- B0 ablation；
- terminal metrics。

通过：`3060/1920/480` plan、fake two-map integration、no update。

### S8：SHIFT runner/actuators

- exact 45-trial sequence；
- stage-blind policy；
- R1–R4 evidence gates；
- recovery/rolling target/sentinel。

通过：`240/10800/480 initial planned sentinel` plan、conditional-set/
attempt 分层计数、alarm/penalty/leakage tests。

### S9：journal/export/validator/analyzer

- append-only hash chain；
- explicit resume；
- all handoff schemas；
- raw replay；
- paired analysis。

通过：crash matrix、golden delivery、two-map fixed-effect checks。

### S10：ROS packages

- messages、gateways、generic C++ Twist command adapter、relay/watchdog、launch；
- graph/type/QoS/single-writer checks；
- rosbag controls。

通过：colcon tests 和 fake ROS graph fault injection。

### S11：现场 Unitree adapter

只有拿到第 22 节硬件事实后：

- 实现薄 vendor adapter；
- pin SDK/bridge/reference；
- 无运动 graph gate；
- HIL/低速 gate。

通过：`backend_hardware_gate_report.json`。

### S12：release/freeze

- 现场完成两地图 survey、四 shift DEV、safety threshold；
- 生成 schedules、command CSV、analysis plan、container digest/checksums；
- 运行 `freeze-release stage-integration`，完成 signed Gate B/C 后用
  `freeze-release prepare` 生成 immutable candidate digest；
- `freeze-release build-gate-d`生成报告，四方签署并 finalize Gate D 后运行
  `freeze-release seal`。

通过：`CONFIRM_READY` report；仍不代表 P8 数据已采完。

### 21.1 每阶段的交付矩阵

每阶段都写 `reports/p8_implementation/sNN.json`，使用
`stage_id,status,source_commit,inputs,created_files,commands,artifacts,blockers`。命令任一
非零就 `status=FAIL`，不得继续下一阶段。

| Stage | 必须输入 | 主要新增/修改 | 最小 gate command | 硬停条件 |
|---|---|---|---|---|
| S0 | clean tracked P0–P7 | baseline report、ADR-003 | 现有全 suite/audits | baseline 非绿且未解释 |
| S1 | legacy P7 source hash | `core/navigation/waypoint.py`、legacy oracle fixture | `pytest ...test_waypoint_parity.py` | 任一 1e-12 parity 失败 |
| S2 | 第 5/6 节 contracts | contracts、四 YAML examples、JSON schemas、CSV fixtures | `pytest tests/unit/hardware/go2/test_config.py` | unknown/UNSET/self-hash 不 fail closed |
| S3 | 外参/clock fixture | clock/frames/reference/snapshot/fakes | frames/reference tests | same-cut/skew/stale 不可判定 |
| S4 | safety YAML + message vectors | command path、watchdog、ADR tests | watchdog/command-path tests | 非零可绕 relay，latch 可自解 |
| S5 | S2 ports + S3/S4 fakes | backend、trial executor、command session | backend/executor/session tests | 任一 exception path 不 zero/finalize |
| S6 | command/reference/task fixtures | model/method factory、schedule、atomic checkpoint | model/method/schedule tests | prior 不唯一、carryover 不平衡 |
| S7 | 两 map TEST fixtures | NAV runner/evaluator/plan | NAV unit + fake integration | 不是 3060/1920/480 或 posterior 变化 |
| S8 | 四 shift evidence fixtures | SHIFT runner/actuators/sentinel | SHIFT unit + fake integration | context leakage、非 10800/480 initial planned 或 conditional 计数不守恒 |
| S9 | mini golden raw delivery | journal/export/schema/validator/analyzer | replay→validate→analyze verification | raw 不可复算、stats 不匹配 golden |
| S10 | ROS container + fake graph | msgs/gateways/relay/watchdog/launch | colcon build/test | QoS/single-writer/kill tests 任一失败 |
| S11 | 第 22 节十项现场事实 | Unitree adapter/pins/B+C reports | no-motion + `pytest -m p8_hil` | 输入缺失或 serious>0 |
| S12 | 两图/四 shift DEV evidence | signed A → stage → signed B/C → DEV release → locked DEV pilot → candidate → signed D → CONFIRM release | freeze-release exact subcommands + remote source audit | 占位、unpushed、签字/hash 缺失 |

S2 的“四 YAML examples”精确指 NAV/SHIFT 的 DEV/CONFIRM 四个文件；
DEV 可带占位但永不 arm，CONFIRM example 在单元测试中用 TEST fixture 数值填满。

---

## 22. Coding agent 不能猜的现场输入

在以下信息缺失时，agent 可以完成 S0–S10，但必须停在
`SOFTWARE_COMPLETE`，不能宣称 backend 已实机完成：

1. Unitree bridge/SDK repo URL、40 位 commit、license 和本地 patch；
2. 固件版本、control mode、gait、arm/stand/damping/zero 的精确语义；
3. vendor command topic、完整 message type、字段、单位、frame、QoS；
4. transmitted echo/ACK 的定义：代表 publish、bridge accept 还是 controller apply；
5. onboard state、IMU、height、BMS、motor fault/temperature message 字段；
6. bridge 自身 command timeout 和断线 zero 行为；
7. 物理 E-stop I/O、测试方法和 reset 权限；
8. mocap/LiDAR reference topic/type/covariance/health、外参和时钟；
9. 实际 robot model/serial、payload bracket limit、场地/workspace；
10. 两图 survey、R2/R4 payload、R3 material 和 R4 task profile。

generic ROS Twist command adapter 和 fake/HIL 不可替代这些事实。禁止 dynamic introspection
后“猜字段”、依赖未 pin 的 Unitree 版本或把第三方源码私藏在机器人主机。

所有项目自有 Python/C++/launch/config/schema/test 必须提交 GitHub；第三方依赖
记录 URL/commit/license/patch，不通过复制源码规避许可证。raw bag/video 不进
Git，放受控数据存储并交 checksum/manifest。

---

## 23. Freeze release

### 23.1 Gate A–D 定义

所有 gate report 使用 `p8.gate.v1` schema，共同字段为：

```text
gate_id,status{PASS,FAIL},robot_id,run_id,dataset_role,source_commit,worktree_clean,remote_synced,
remote_ref,remote_commit,candidate_release_sha256,
started_utc,ended_utc,commands[{working_directory,argv,exit_code,stdout_sha256}],
artifacts[{artifact_kind,path,semantic_sha256,raw_sha256,size_bytes}],
gate_metrics,serious_safety_events,blockers[],
report_preimage_sha256,
signatures[{role,person_id,signed_utc,report_preimage_sha256,
            key_id,candidate_release_sha256,
            approval_request_path,approval_request_sha256,
            human_approval_path,human_approval_sha256}]
```

无自引用的签名规则固定为：先令 `signatures=[]` 并排除
`report_preimage_sha256` 字段，对其余完整 report 做 canonical JSON hash，写入
`report_preimage_sha256`；每条 signature 必须绑定该值。Gate D 还必须在 report body
和每条 signature 中绑定同一个非空 `candidate_release_sha256`；A–C 统一写
`NOT_APPLICABLE`。签名加入后不重算 preimage。完整 signed report 的 file hash 由
外层 artifact/checksums 记录，不写回自身。
`artifacts[]` item 也是 `additionalProperties=false`；`path` 是 candidate/final
release-relative path，`semantic_sha256` 按目标 strict schema 的 detached/self-hash
preimage 重算，`raw_sha256` 对文件完整 bytes 重算，`size_bytes` 是同一 bytes
的长度。目标 schema 无 detached/self-hash 时
`semantic_sha256=raw_sha256`。`artifact_kind` 必须是对应 gate 的 strict schema
所允许值；不得用旧式 `{path,sha256}` 或用一个 hash 同时冒充 semantic/raw。
四个 report 的 `robot_id,run_id,dataset_role=CONFIRM` 必须逐位等于同一 candidate release的
resolved confirmatory config/schedule，不能用 `NOT_APPLICABLE`；Gate D引用的 DEV evidence
通过其 manifest hash另行绑定，不把 gate report role改成 DEV。
这个“同一 candidate”关系在 A–C 时通过 integration-stage manifest 预绑定：Gate A
从两个 tracked CONFIRM config/schedule 解析 identity，stage 继承 Gate A，Gate B/C 又继承
stage，prepare 只能用该 stage。`remote_ref` 在 Gate A argv 冻结，B/C 从 stage继承，
D 从 candidate继承。`remote_commit` 只可在 `status=FAIL,remote_synced=false` 时为 JSON
null；任一 PASS report 都要求 40-hex、等于 `source_commit`，且
`remote_synced=true`。
每条 signature 必须是第 6.5.2 节 `HumanApproval(purpose=GATE_REPORT,
subject_sha256=report_preimage_sha256)` 的可验证投影；Gate D还绑定 candidate digest。所需不同
person/role按表执行，不能手填 person_id冒充签名。
`approval_request_path` 必须是
`test_reports/p8_gate_approvals/requests/<request_raw_sha256>.json`，
`human_approval_path` 必须是同 root 的
`approvals/<approval_raw_sha256>.json`；两个 hash 字段分别是对象的 semantic
self-hash，raw hash 由 filename/release checksums 另行绑定。validator 必须解析这两份
bytes、读取 frozen registry public key、重算 request/approval/preimage和 Ed25519 签名；
只验证 report 中 projection 或只比较 person ID 不合格。

`gate_metrics` 由 `gate_id` 选择 strict `oneOf`（所有 nested
`additionalProperties=false`），exact fields 为：

```text
A: schema_version="p8.gate-a-metrics.v1",required_command_count,
   passed_command_count,p8_executable_file_count,
   p8_files_meeting_line_minimum_count,p8_line_coverage_percent,
   p8_branch_coverage_percent,minimum_p8_file_line_coverage_percent,
   required_p8_test_count,p8_test_count,p8_test_passed
B: schema_version="p8.gate-b-metrics.v1",static_preflight_reports,
   contact_robot,nonzero_command_count,topic_contract_passed,qos_passed,
   single_writer_passed,zero_readback_passed,estop_ready
C: schema_version="p8.gate-c-metrics.v1",required_invocation_count,
   completed_invocation_count,passed_invocation_count,pytest_command_sha256,
   scenario_summaries,hil_event_count,
   timing_required_event_count,eligible_event_count,missing_decision_count,
   missing_zero_publish_count,max_zero_command_latency_ms,max_latency_event_id,
   boot_id_count,cross_boot_timing_count,serious_safety_events
D: schema_version="p8.gate-d-metrics.v1",continuous_power_cell_count,
   continuous_power_cells_passing,minimum_marginal_power,
   discrete_check_count,discrete_checks_passing,discrete_design_ready,
   dev_nav_blocks,dev_shift_blocks_per_shift,
   dev_input_lock_manifest_semantic_sha256,
   dev_input_lock_manifest_raw_sha256,dev_input_tree_sha256,
   map_count,shift_count,power_cells,discrete_checks
```

Gate A schema 将 `required_command_count=14,required_p8_test_count=120` 写成 `const`；
三个 coverage percent 都是 finite `[0,100]` 数，不是格式化字符串。
`p8_executable_file_count` 必须等于从 tracked P8-owned allowlist 和 coverage statement count
重算的非零值，`p8_files_meeting_line_minimum_count` 逐文件按 ≥70.0% 计数。PASS 必须满足
`passed_command_count=14,p8_line_coverage_percent>=90.0,
p8_branch_coverage_percent>=80.0,minimum_p8_file_line_coverage_percent>=70.0,
p8_files_meeting_line_minimum_count=p8_executable_file_count,
p8_test_count>=required_p8_test_count,p8_test_passed=p8_test_count`；任一值只出现在 report
而无法从 frozen coverage/JUnit evidence 重算时 report 无效。这样旧 P0–P7 的高覆盖率不能
掩盖 P8 文件未执行，也不能用一个 smoke test 得到 Software PASS。

Gate D 的 `power_cells` 是长度恰好 22 的有序数组，顺序固定为：先按
`real_offset_slalom,real_weighted_arc` 放 2 个 NAV B8-vs-B0 time-superiority cell；
再按同一 map order、每图按
`B1_dense,B2_lhs,B3_sobol,B4_d_opt,B5_active_no_task,B6_random` 放 12 个
time-ratio-NI cell；再按 R1→R4 放 4 个 SHIFT early-RMSE-superiority cell和 4 个
terminal-RMSE-threshold cell。每项 nested
`additionalProperties=false`，exact fields 为：

```text
cell_id,protocol,map_id,shift_id,endpoint,comparison_id,transformed_difference,
pilot_input_lock_manifest_raw_sha256,pilot_n,planned_n,mde_absolute,unit,
sd_unbiased,sd_upper_95,df,ncp,power,failure_reason,
target_marginal_power,passes_target
```

NAV item 的 `map_id` 是真实 route、`shift_id=null`、`planned_n=30`；SHIFT item
的 `map_id=null`、`shift_id` 是真实 R1–R4、`planned_n=20`。22 项的 endpoint/
comparison/transformation/MDE/unit/target逐字等于 frozen analysis plan，
`pilot_input_lock_manifest_raw_sha256` 逐项等于 Gate D 顶层的
`dev_input_lock_manifest_raw_sha256`、candidate 和 final plan 绑定值。Gate D 顶层的
semantic/raw/tree 三个 hash 必须从 `--dev-delivery-root/manifests/input_lock_manifest.json`
及其锁定文件树重算，不从 final delivery manifest 或自然语言报告取值。
`pilot_n` 是 DEV 完整 paired difference 数且必须恰为 5；`sd_unbiased` 使用
`ddof=1`，`sd_upper_95` 和 `ncp/power` 按 handoff §15.1 重算。zero/nonfinite SD 或
上界固定 `power=null,failure_reason=ZERO_OR_NONFINITE_PILOT_SD,passes_target=false`；
其他项 `failure_reason=null`。`passes_target := pilot_n==5 AND finite(sd_upper_95)
AND sd_upper_95>0 AND power>=target_marginal_power`。

`discrete_checks` 是长度恰好 62 的数组：先按 map order/endpoint 展开 6 个 NAV
absolute-rate check，再按 map/`success_NI,collision_NI`/六 baseline 展开 24 个 binary-NI
lattice check，再按 shift/R1→R4 和 rate-key 展开 12 个 SHIFT rate check，最后按 shift
展开四个 ordinal-quantile 和一个 Wilcoxon check，共 20。每项 exact fields 为：

```text
check_id,check_kind,map_id,shift_id,endpoint,baseline_id,planned_n,rule_id,
passing_values,lattice_step,margin,min_attainable_p,passes
```

不适用字段必须为 JSON null；`passing_values` 是升序整数或 queried order-statistic tuple canonical object
的有序数组。generator 必须执行 frozen Clopper–Pearson、point-rate、paired lattice、
`numpy.quantile(method=linear|higher)` 或 scipy Wilcoxon call，不接受手填 true。
ordinal check 只枚举 handoff §15.1 冻结的第 10/11/20 个 order statistic 及其
长度 20 可补全性，不枚举指数量级的全 histogram 空间。
`continuous_power_cell_count=22,discrete_check_count=62,dev_nav_blocks=5,
dev_shift_blocks_per_shift=5,map_count=2,shift_count=4`；passing counts 从数组重算。
任一 power 为 null 时 `minimum_marginal_power=null`，否则取 22 项最小值；
`discrete_design_ready=(discrete_checks_passing==62)`。Gate D PASS 要求 22/22 power cells
与 62/62 discrete checks 全 true。它只证明逐-cell marginal readiness和有限离散设计
可辨识性，不得表述为联合/family-wise 80% power，也不接受只有汇总值的报告。

Gate B 的 `static_preflight_reports` 是长度恰好 2 的数组，按
`NAV,SHIFT` 顺序固定；每项 nested `additionalProperties=false`，exact fields 为
`protocol,config_path,config_sha256,schedule_manifest_path,
schedule_manifest_sha256,preflight_report_path,preflight_report_sha256,exit_code`。
`protocol` 只允许 `NAV|SHIFT`，两项 schedule path/hash 必须逐位相同，path 逐字为
canonical `schedules/schedule_manifest.json`，并通过
`ValidatedStageRoleView(stage, CONFIRM)` 解析到 CONFIRM manifest；两项 config path 分别
逐字为 `configs/p8_real_nav_confirmatory.yaml` 和
`configs/p8_real_shift_confirmatory.yaml`，也只能通过同一 role-view 解析。report 中不得写
`views/CONFIRM/...` 物理 stage path或 config-relative path。每份 static preflight report
都必须通过 §19.4.3 的
`schemas/p8/static_preflight_report.schema.json`，在 Gate B evidence manifest/局部
checksums 中按 raw hash 绑定；`preflight_report_sha256` 精确等于该 raw file
SHA-256，不是内层 `report_sha256`。报告必须
`schema_version=p8.static-preflight-report.v1,operation=PREFLIGHT,
mode=STATIC_NO_MOTION,release_kind=INTEGRATION_STAGE,dataset_role=CONFIRM,
contact_robot=true,nonzero_command_count=0,ready=true,exit_code=0`，其 protocol/config/
schedule/root-manifest/robot/run/source 身份与本 Gate B item 及 integration stage 逐位一致，
三项 static verification 和十项 live check 全 true。Gate B 顶层
`nonzero_command_count` 是两报告重算之和。缺任一份或把两份 hash 折叠成一个
无 schema 聚合字符串都不合法。

Gate C PASS 机械要求 `required_invocation_count=220,
completed_invocation_count=passed_invocation_count=220`，11 个 `scenario_summaries`
的 executed/passed 均等于各自 required、failed=0，并且 `hil_event_count>0,timing_required_event_count>0,
eligible_event_count=timing_required_event_count,missing_decision_count=0,
missing_zero_publish_count=0,cross_boot_timing_count=0,
max_zero_command_latency_ms<=40,serious_safety_events=0`，且 max/event ID non-null。
handoff §15.3 的 `gate_c_max_latency_ms` 唯一取该 signed Gate C report 的
`gate_metrics.max_zero_command_latency_ms`；analyzer同时验证 report preimage/signatures/hash，
不得从自然语言、stdout或另一个 HIL 文件抄数。

| Gate | 输入/命令 | 固定 report | PASS/签字 | 解锁状态 |
|---|---|---|---|---|
| A Software | S0–S10；Python CI、mini replay/export/validate/analyze verification、colcon fake graph、source audit | `reports/p8_gates/gate_a_software.json` | 全部 exit 0；P8 coverage/mypy/schema/cardinality 通过；software lead | `SOFTWARE_COMPLETE` |
| B Static integration | 现场 SDK/topic/reference pins；`calibagent-p8-preflight static-no-motion` 按 §19.4.3 exact argv并带 `--contact-robot`；graph/QoS/single-writer/zero-only/E-stop readiness | `reports/p8_gates/gate_b_static_integration.json` | 不发非零命令；全 health/readback 通过；deployment lead + safety operator | 允许 HIL |
| C HIL/safety | 第 20.4 节完整 HIL matrix；`pytest -m p8_hil`；实际 bridge timeout/E-stop/lease/crash | `reports/p8_gates/gate_c_hil.json` | decision→zero publish ≤40 ms；serious=0；hardware lead + safety lead | `HARDWARE_INTEGRATED` |
| D Freeze | DEV exact 5-block pilot、两图 survey、四 shift、全 config/threshold/commands/schedules、analysis plan、remote audit；`freeze-release prepare`后用 `build-gate-d` 生成 candidate-bound report | `reports/p8_gates/gate_d_confirm_ready.json` | 22/22 marginal-power cells、62/62 discrete checks、candidate checksum/digest 通过，并被 software/data/safety/PI 四方签字；随后 `freeze-release seal` | `CONFIRM_READY` |

Gate B/C 需要第 22 节现场输入；Gate D 需要实机 DEV 数值。coding agent
可完整实现 report schema/generator/test，但不得在没有现场证据时伪造
PASS。`backend_hardware_gate_report.json` 是 Gate B+C 的聚合 view，不是第五个 gate。
它由 `seal-dev` 在验证 signed B/C 后唯一生成，`prepare/seal` 必须从输入
Gate B/C 重算出逐字节相同的对象，不接受一份手写 input。它必须通过
`schemas/p8/backend_hardware_gate_report.schema.json`，顶层 exact fields 为：

```text
schema_version,robot_id,confirm_run_id,dev_run_id,source_commit,
integration_stage_manifest_sha256,
gate_b_path,gate_b_sha256,gate_b_report_preimage_sha256,
gate_c_path,gate_c_sha256,gate_c_report_preimage_sha256,
static_preflight_reports,required_invocation_count,completed_invocation_count,
passed_invocation_count,pytest_command_sha256,scenario_summaries,hil_event_count,timing_required_event_count,
eligible_event_count,missing_decision_count,missing_zero_publish_count,
max_zero_command_latency_ms,max_latency_event_id,cross_boot_timing_count,
serious_safety_events,hardware_integrated,evidence_utc,report_sha256
```

`schema_version="p8.backend-hardware-gate.v1"`；Gate path 固定为 release-relative
`test_reports/p8_gates/gate_{b_static_integration,c_hil}.json`。
`static_preflight_reports` 与 Gate B metrics 逐字相同，所有 HIL/timing/safety 字段与
Gate C metrics 逐字相同；`hardware_integrated := GateB.status=PASS AND
GateC.status=PASS`，只允许 true 的 aggregate 进入 DEV/candidate/final release。
`evidence_utc=max(GateB.ended_utc,GateC.ended_utc)`，不读当前时钟；
`report_sha256=sha256(JCS(record 排除 report_sha256))`。这一 deterministic time 规则保证
seal-dev/prepare/seal 重建 bytes 相同。

### 23.2 freeze 工具

freeze 是不可省略的有向事务链，唯一公开 argv 是第 19.4.7 节的九个
subcommand；不存在旧式 `--prepare/--seal` flag。顺序精确为：

1. `build-gate-a --remote-ref ...` 绑定 clean local HEAD 与 fetched remote commit，运行
   software matrix；用 generic signer 产生 request/approval，再以
   `finalize-gate-report` 生成 signed Gate A。
2. `stage-integration ... --gate-a ...` 从该 exact commit 和 fixed mapping 生成 immutable
   integration stage；它提前绑定后续 candidate 的 robot/run/CONFIRM identity、remote ref/commit
   和全部 runtime bytes，但不允许 CONFIRM motion。
3. `build-gate-b` 仅对该 stage 做 NAV/SHIFT 两份 CONFIRM static/contact-robot
   zero-only preflight，签署/finalize 得到 Gate B。
4. `build-gate-c --gate-b ... --gate-approval-root ...` 先按当前 A+B exact artifact
   allowlist 离线验证 signed PASS Gate A/B 与同 stage，再执行 DEV HIL matrix 和
   safety-event 重算，签署/finalize 得到 Gate C。
5. `seal-dev --gate-b ... --gate-c ...` 新建 immutable `p8.dev-release.v1`。只有该
   release 可解锁 DEV motion。按 DEV schedule 精确采集 NAV 5 blocks 和每个 R1–R4
   各 5 blocks（全 methods/两 routes），完成
   blind safety review、export 和 `validate-delivery --phase pre-lock`；其 input-lock raw hash
   是后续唯一 pilot identity。
6. `prepare --integration-stage ... --gate-b ... --gate-c ... --dev-delivery-root ...
   --remote-ref ...` 重验 stage、A–C、remote、pins、DEV input-lock、config/map/
   command/schedule/template hashes 和 serious=0，物化 final analysis plan；它不要求 Gate D，
   输出 immutable
   `p8_release_candidate_<digest>/candidate_manifest.json` 与
   `candidate_checksums.sha256`，以 manifest canonical bytes SHA-256 作为
   `candidate_release_sha256`。
7. `build-gate-d --candidate ... --dev-delivery-root ...` 重算 22 个 continuous cells、
   62 个 discrete checks 和 DEV exact cardinality并绑定
   candidate digest。四个 role 只对该 Gate D preimage/candidate digest 签名，再由
   `finalize-gate-report` 生成 `gate_d_confirm_ready.json`；candidate bytes 不得再变。
8. `seal --candidate ... --gate-d ...` 重验 candidate 全 hash、Gate A–D、四个 Gate D
   签名、remote commit 和 serious=0，只复制 candidate bytes、加入 signed Gate D/最终
   manifest，再生成 `p8_frozen_release/checksums.sha256`。它不重新生成
   schedule/config/统计文件。

第 1、3、4、7 步后都各有一次 `finalize-gate-report`，因此九个 public
subcommand 会按上述四处重复调用 finalizer；这不是额外 hidden API。

最终 `release_manifest.json` 必须通过 strict `p8.release.v1`，顶层 exact fields 为：

```text
schema_version,dataset_role,robot_id,run_id,candidate_release_sha256,
candidate_manifest_path,candidate_manifest_semantic_sha256,
source_commit,remote_ref,remote_commit,container_image_digest,
integration_stage_manifest_sha256,dev_release_manifest_sha256,
pilot_input_lock_manifest_semantic_sha256,
pilot_input_lock_manifest_raw_sha256,pilot_input_tree_sha256,
analysis_plan_template_sha256,analysis_plan_sha256,config_materializations,
gate_report_refs,gate_approval_artifact_refs,tools_manifest_sha256,
release_paths,created_utc
```

`schema_version="p8.release.v1",dataset_role="CONFIRM"`；candidate path 固定为根目录
`candidate_manifest.json`，其 semantic/raw hash 分别等于 candidate 内部 self-hash 和
`candidate_release_sha256`。`gate_report_refs` 按 A/B/C/D，
`gate_approval_artifact_refs` 覆盖四个 Gate 所有 request/approval；两者 item shape 与 candidate
定义相同。`config_materializations` 继承 stage 四项 provenance，但 final
`release_paths` 只包两份 CONFIRM materialized config。
`release_paths[]` 是 handoff §3.1 exact allowlist 中除
`release_manifest.json,checksums.sha256` 外的有序列表，每项 exact fields 为
`relative_path,raw_sha256,size_bytes`，按 relative path UTF-8 bytes 排序；其中必须包含
`candidate_manifest.json`。manifest 及所有 nested item 均 `additionalProperties=false`，不含自己的 hash；
其 raw-byte SHA-256 由 `checksums.sha256` 记录，并作为运行期
`release_manifest_sha256`。

`tools_manifest.json` 必须通过 strict `schemas/p8/tools_manifest.schema.json`，顶层
exact fields 为：

```text
schema_version,source_commit,container_image_digest,python_version,
entries,lock_files,manifest_sha256
```

`schema_version="p8.tools-manifest.v1"`。`entries` 长度恰好 14，按第 19.4 节 wrapper
表顺序；每项 nested `additionalProperties=false`，exact fields 为：

```text
logical_name,console_entry,source_module_path,source_module_sha256,
release_wrapper_path,release_wrapper_sha256,release_mode,help_stdout_sha256
```

`logical_name` 精确为 wrapper 表左列 ID，`console_entry` 必须与 tracked
`pyproject.toml` 全名匹配，source module 必须是第 3 节列出的 14 个 CLI file，
release wrapper 必须是 `tools/<logical_name>`。`release_mode` 固定为整数
`365`（octal `0555`）；wrapper bytes 是只设定 frozen Python/container entry 的生成 launcher，
其 hash 不假定等于 Python source hash。`help_stdout_sha256` 从该 release wrapper
`--help` exit 0 的 raw stdout 计算，stderr 必须为空。

`lock_files` 按 `logical_name` UTF-8 bytes 排序。固定 8 项为：

| `logical_name` | `source_path` | `release_path` |
|---|---|---|
| `analysis_requirements` | `env/analysis/requirements-p8.lock.txt` | `environment/analysis_requirements.lock.txt` |
| `robot_container_recipe` | `env/robot/Dockerfile` | `environment/robot.Dockerfile` |
| `robot_python_requirements` | `env/robot/requirements.lock.txt` | `environment/robot_requirements.lock.txt` |
| `robot_rosdep_install_manifest` | `env/robot/rosdep.lock-or-install-manifest.txt` | `environment/rosdep.lock-or-install-manifest.txt` |
| `third_party_robot_dependencies` | `env/robot/third_party_robot_dependencies.yaml` | `environment/third_party_robot_dependencies.yaml` |
| `unitree_sdk_license` | `env/robot/dependency_evidence/unitree_sdk.LICENSE.txt` | `environment/dependency_evidence/unitree_sdk.LICENSE.txt` |
| `command_bridge_license` | `env/robot/dependency_evidence/command_bridge.LICENSE.txt` | `environment/dependency_evidence/command_bridge.LICENSE.txt` |
| `reference_stack_license` | `env/robot/dependency_evidence/reference_stack.LICENSE.txt` | `environment/dependency_evidence/reference_stack.LICENSE.txt` |

manifest 中每个 `patch_status=PATCHED` 的 dependency 再恰增加一项
`<id-lower>_patch`，source/release path 必须等于 §4.2 该 item 已签 hash 的固定 patch
path；`CLEAN` 不增加，`UNSET` 不能进入 freeze。因此长度只能为 8–11，且由 manifest
唯一投影，不能接受 argv 或 glob 增项。

每项 exact fields 为
`logical_name,source_path,source_raw_sha256,release_path,release_raw_sha256`，且
`source_raw_sha256=release_raw_sha256=sha256(source raw bytes)`；源/目标 bytes
必须逐字相同，不得只列版本字符串。该表同时是 integration stage
`common/environment/`、DEV release、candidate 和 final release 的 exact environment
allowlist：除 stage 多一层 `common/` 前缀外，四者 relative path 和 raw bytes 必须完全一致。
根目录 `container_image_digest.txt` 只由 container provenance 合同管理，不在
`environment/` 内复制，也不进入 `lock_files`。manifest URL/commit/license/patch-status 与
上述 raw evidence 必须一起离线复核；不得只锁一个 commit 文本或省略 bridge/reference。
`manifest_sha256=sha256(JCS(record 排除 manifest_sha256))`；其 raw hash 另由 stage/
candidate/release manifest和checksums绑定。顶层、entries、lock_files 均
`additionalProperties=false`。

`prepare` 必须拒绝 dirty/untracked P8 **source/config/protocol**、unpushed commit、
`UNSET` pin、缺输入、hash mismatch、测试失败或 Gate A–C 缺失；`seal` 另外拒绝
Gate D 缺失/签名或 candidate digest mismatch。gate/report/candidate 输出路径是明确
allowlist 的生成物，不计入 source `worktree_clean`；clean 状态在写 report 前记录，
不得通过忽略真实 source 修改来得到 PASS。

seal 成功输出：

```text
p8_frozen_release/
├── RELEASE_README.md
├── source_commit.txt
├── container_image_digest.txt
├── backend_hardware_gate_report.json
├── protocol/
├── configs/
├── schedules/
├── maps/
├── commands/
├── schemas/
├── environment/
├── test_reports/
├── tools/
├── tools_manifest.json
├── candidate_manifest.json
├── release_manifest.json
└── checksums.sha256
```

该顶层树及每个子目录的 exact allowlist 必须与 handoff §3.1 的展开树逐项相同；seal 和
delivery validator 共同读取同一 allowlist 常量，禁止两份手写列表。repository
`schemas/p8/ → schemas/`、`reports/p8_gates/ → test_reports/p8_gates/` 以及 CLI/lock
source→release 的唯一映射同样以 handoff §3.1 为准。checksums 不包含自身。release 中
每个 CLI 提供 `--help` 和一个不运动的 dry-run 示例。CONFIRM 使用 detached frozen
commit/container，不在机器人上临时 patch。

---

## 24. Definition of Done

### 24.1 `SOFTWARE_COMPLETE`

- Gate A PASS；S0–S10 所有项目自有路径无 TODO/pass/NotImplemented/fake fallback；
- 冻结 `RobotBackend` 四方法和 NAV `CommandSession` 在 fake/ROS graph 通过；
- NAV 八方法×两图×30 blocks 与 SHIFT 三方法×四 shift×20 blocks 计划通过；
- R1 边界、stage blindness、no-update、sentinel、resume、raw replay 通过；
- ruff、strict mypy、coverage、pytest、colcon、governance audit 全绿。

此状态允许 `unitree_vendor_adapter.cpp` 仍 fail closed 且 SDK pin 仍
`UNSET-P8-NOT-INTEGRATED`，因为它属于 S11；但 generic adapter 不得被偷当真机完成。

### 24.2 `HARDWARE_INTEGRATED`

- Gate A、B、C PASS；
- Unitree/reference URL、40 位 commits、license/patch/firmware/topic contract 全 pin，无 `UNSET`；
- 真实 adapter 无运动 graph gate 和 HIL 通过；single-writer/watchdog/E-stop/bridge timeout
  已实测；serious event=0。

### 24.3 `CONFIRM_READY`

- Gate A–D 全 PASS；
- 两图/四 shift/阈值/命令/schedule/analysis plan/release 全 hash；
- clean commit 已 push 且能从 GitHub clone/checkout；冻结 container/release 可复现；
- 四方签字完整。

只有采完、delivery validation 通过并满足第 15 节统计 gate 后，才是
`P8_EVIDENCE_GO`。任一软件/硬件/release 状态都不代表论文结果 GO。

---

## 25. 最终验收命令清单

coding agent 交付时必须在报告中给出这些命令的真实输出摘要和 artifact 路径：
以下 `P8_*` 变量必须由 CI 指向本次新建的 schedule/release/run/delivery/report
workspace，不得指向 CONFIRM 正式采集目录或已存输出文件：

```bash
git status --short
git rev-parse HEAD
ruff check .
mypy src/calibagent ros2/calibagent_go2 scripts/build_readme_figures.py scripts/build_isaac_response_card.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p pytest_cov --cov=calibagent --cov-report=term-missing
calibagent-p8-config-validate tracked --repository-root . --report "$P8_REPORT_ROOT/config_validate.json"
calibagent-p8-schedule validate --nav-config "$P8_RELEASE_ROOT/configs/p8_real_nav_confirmatory.yaml" --shift-config "$P8_RELEASE_ROOT/configs/p8_real_shift_confirmatory.yaml" --schedule-dir "$P8_RELEASE_ROOT/schedules" --dataset-role CONFIRM --report "$P8_REPORT_ROOT/schedule_validate.json"
calibagent-p8-preflight static-no-motion --config "$P8_RELEASE_ROOT/configs/p8_real_nav_confirmatory.yaml" --schedule "$P8_RELEASE_ROOT/schedules/schedule_manifest.json" --release-root "$P8_RELEASE_ROOT" --output-root "$P8_DEV_OUTPUT_ROOT" --robot-state-root "$P8_ROBOT_STATE_ROOT" --dataset-role CONFIRM --report "$P8_REPORT_ROOT/preflight_nav.json"
calibagent-p8-preflight static-no-motion --config "$P8_RELEASE_ROOT/configs/p8_real_shift_confirmatory.yaml" --schedule "$P8_RELEASE_ROOT/schedules/schedule_manifest.json" --release-root "$P8_RELEASE_ROOT" --output-root "$P8_DEV_OUTPUT_ROOT" --robot-state-root "$P8_ROBOT_STATE_ROOT" --dataset-role CONFIRM --report "$P8_REPORT_ROOT/preflight_shift.json"
calibagent-p8-replay --run-root "$P8_GOLDEN_RUN_ROOT" --release-root "$P8_GOLDEN_RELEASE_ROOT" --run-id "$P8_GOLDEN_RUN_ID" --through-checkpoint latest --output "$P8_REPORT_ROOT/golden_replay.json" --verify-only
calibagent-p8-validate-delivery --delivery-root "$P8_GOLDEN_WORKTREE" --frozen-release "$P8_GOLDEN_RELEASE_ROOT" --phase pre-lock --report "$P8_REPORT_ROOT/golden_validate_pre_lock.json" --fixture-profile mini
calibagent-p8-analyze --delivery-root "$P8_GOLDEN_WORKTREE" --input-lock-manifest "$P8_GOLDEN_WORKTREE/manifests/input_lock_manifest.json" --data-lock-commit "$P8_GOLDEN_DATA_LOCK_COMMIT" --analysis-plan "$P8_GOLDEN_RELEASE_ROOT/protocol/analysis_plan.yaml" --output "$P8_GOLDEN_WORKTREE/analysis/confirmatory_analysis.json" --verification-only --expected tests/replay/p8/fixtures/golden_expected.json
calibagent-p8-export seal-final --delivery-root "$P8_GOLDEN_WORKTREE" --frozen-release "$P8_GOLDEN_RELEASE_ROOT" --input-lock-manifest "$P8_GOLDEN_WORKTREE/manifests/input_lock_manifest.json" --data-lock-commit "$P8_GOLDEN_DATA_LOCK_COMMIT" --analysis "$P8_GOLDEN_WORKTREE/analysis/confirmatory_analysis.json" --report "$P8_REPORT_ROOT/golden_seal_final.json"
calibagent-p8-validate-delivery --delivery-root "$P8_GOLDEN_WORKTREE" --frozen-release "$P8_GOLDEN_RELEASE_ROOT" --phase final --report "$P8_REPORT_ROOT/golden_validate_final.json" --fixture-profile mini
(cd ros2 && colcon build --symlink-install)
(cd ros2 && colcon test --event-handlers console_direct+)
(cd ros2 && colcon test-result --verbose)
git fetch origin main
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
./scripts/audit_source_delivery.sh --require-remote-ref origin/main
```

真实 robot 的 `--arm` 命令不写成可盲目复制的一行。它只能从冻结 release、现场
runbook 和已签字 schedule 启动，并由独立安全员确认。

---

## 26. 最短阅读路径

coding agent 开始实现前按顺序读：

1. `docs/p8_go2_real_deployment_data_handoff_zh.md`
2. 本文
3. `docs/architecture.md`、ADR-001/002
4. `src/calibagent/interfaces/types.py`、`protocols.py`
5. `src/calibagent/measurement/pipeline.py`
6. safety、state machine、model、planning、shift、compensation core
7. P1 field runner
8. P6 runner 的 monitor/recovery loop
9. P7 runner 的 calibration/navigation loop
10. 现有 tests 和 CI

实现中若发现本文又与实际源码不一致，应新增一个 failing regression test、修订
本文/ADR，再实现；不能把新的隐含选择只留在代码里。
