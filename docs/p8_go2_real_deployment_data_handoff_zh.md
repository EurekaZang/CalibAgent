# CalibAgent P8：Unitree Go2 在线实机实验、数据采集与交付规范

> 文档用途：直接交给实机部署、参考定位、场地、安全、数据记录和导出人员执行。
> 文档日期：2026-07-31。
> 当前状态：**正式采集前冻结草案**。软件团队完成第 3 节全部前置物并提交冻结 commit/hash 后，才可将本草案标记为 `FROZEN`。
> 目标：补齐在线实机主动标定、实机域偏移恢复和实机下游导航证据；不是只录几段演示视频。
> 适用机器人：Unitree Go2；具体型号、序列号、固件和 SDK 版本必须在正式采集前写入元数据。

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan
- Origin Date: 2026-07-26
- Verification Status: REVIEWED AGAINST CURRENT P1/P6/P7 CONTRACTS
- Version Label: `p8_go2_real_handoff_v2_two_map_nav`
- Local evidence basis:
  - `docs/p1_go2_real_data_collection_handoff_zh.md`
  - `docs/p6_p7_strong_confirmatory_protocol.md`
  - `configs/experiments/p6_domain_shift_strong_confirmatory.yaml`
  - `configs/experiments/p7_navigation_strong_confirmatory_v2.yaml`
  - `src/calibagent/interfaces/types.py`
  - `src/calibagent/core/safety/filter.py`

---

## 本版冻结范围

- P8-NAV 实机只执行 `real_offset_slalom` 和 `real_weighted_arc` 两条预注册路线；
- P7 的六地图 Isaac Lab 实验和证据保持不变，其余四类不再进入 P8 实机采集；
- P8-SHIFT 不缩减，`R1_command_gain_coupling`–`R4_mixed_context` 全部保留；
- 相应的 P8-NAV 正式规模为 30 个 paired blocks，共 3,060 个 calibration trials、
  1,920 个 validation trials 和 480 个 navigation episodes。
- Gate D 之前另采一套严格隔离的 `DEV` pilot：P8-NAV 5 个 paired blocks，
  P8-SHIFT 每个 shift 5 个 paired blocks。DEV 只用于方差/可执行性估计，不能计入
  下述 30/20-block `CONFIRM` 样本量。

这一缩减只改变 P8-NAV 的实机外部有效性范围，不修改 P0–P7 已冻结的仿真结果，
也不授权把两条实机路线写成“六类实机地图”或“未知地图泛化”。

| 项目 | 原六路线设想 | 本版冻结值 | 变化 |
|---|---:|---:|---:|
| 每 block 导航 | 48 episodes | 16 episodes | -32 |
| 30 blocks 导航 | 1,440 episodes | 480 episodes | -960（-66.7%） |
| calibration / validation | 3,060 / 1,920 trials | 3,060 / 1,920 trials | 不变 |
| P8-SHIFT | R1–R4 | R1–R4 | 不变 |

---

## 0. 给未参与仿真的实机同事：项目已经做了什么

### 0.1 一句话理解 CalibAgent

Go2 接收到命令速度 `u=(vx, vy, wz)` 后，真实运动速度通常不是完全相同的
`y=(vx, vy, wz)`。地面、载荷、质心、控制器、死区和轴间耦合都会改变
`u→y` 的映射。CalibAgent 的工作是：

1. 从一个冻结且安全的候选命令池选择少量标定命令；
2. 在每个 trial 中执行命令并用独立参考定位测量真实运动；
3. 在线更新带不确定性的命令到速度模型；
4. 用该模型把导航所需速度反解为更合适的 Go2 命令；
5. 如果残差突然变大，检测到环境/动力学变化并主动重新标定。

核心目标不是让机器人“学会走路”。底层 Go2 locomotion controller 保持冻结；
本项目标定的是上层速度命令到实际机身速度的映射。

### 0.2 P0–P7 分别完成了什么

| 阶段 | 实际完成的工作 | 证据环境 | 对 P8 的意义 |
|---|---|---|---|
| P0 | 冻结命令、状态、trial、backend、模型和 planner 接口；建立可追溯 manifest | 软件测试 | 实机代码必须实现同一个 `RobotBackend` contract |
| P1 | 在 183 个真实 Go2 trial 上验证 raw pose→SE(2) 速度观测和被动 affine 标定 | 真实 Go2，离线回放 | 证明真实数据管线可用，但没有在线主动选择或导航 |
| P2 | 验证噪声只计一次、posterior uncertainty 和覆盖率 | 合成映射 | 证明模型的不确定性计算没有明显实现错误 |
| P3 | 比较 random/LHS/Sobol/D-opt/no-task/dense/full，验证 12-trial task-aware active planner | 合成映射 | 给出 P8-NAV 的标定方法和候选选择逻辑 |
| P4 | 验证 hard safety filter、trial state machine、故障注入和 validation-gated stopping | 软件/冻结 replay | 给出 P8 必须复用并实机化的 fail-closed 流程 |
| P5 | 将同一模型、planner 和 safety 接到 Isaac Lab/PhysX Go2 与官方 locomotion policy | Isaac Lab | 证明算法可在有动力学的闭环中运行，不等于真机验证 |
| P6 | 机器人运行中施加 gain、friction、payload、COM 等 shift；比较 frozen/passive/full | Isaac Lab | 形成 P8-SHIFT 的 detector、posterior inflation 和恢复流程 |
| P7 | 标定后用同一固定 planner 导航；比较 raw、dense 和 12-trial controls | Isaac Lab | 形成 P8-NAV 的地图、导航、inverse compensation 和 endpoint |

P6 强确认使用 4 类 shift、每类 72 个 paired seeds、3 种方法。P7 强确认使用
6 张地图、每图 72 个 paired seeds、7 种方法；第一次 P7 确认失败被保留，
之后才在不重叠地图和 seeds 上做冻结 replication。仿真结果支持实验设计和
软件逻辑，不支持“真机已经成功”。

### 0.3 仿真中的 P8-NAV 原型具体怎样运行

每种方法先得到一个 command→velocity posterior：

- `B0_raw` 不标定；
- `B1_dense` 执行 30 个冻结 dense commands；
- LHS、Sobol、D-opt、no-task 等 controls 各执行 12 个 commands；
- `B5_active_no_task` 与 `B8_full` 都执行冻结的 12-trial active protocol：前
  6 个 trial 共用 `active_seed.csv` 的 signed-axis seeds，后 6 个 trial 才依据
  当前 posterior 在线选择 IVR 命令；B5 使用 uniform/no-task distribution，B8
  使用冻结的双路线 task distribution。

导航 planner 对所有方法完全相同。planner 给出期望机身速度后，
`ConstrainedInverseCompensator` 在冻结候选池里寻找一个安全 Go2 命令，使
posterior 预测速度尽量接近期望速度；再经过 bounded feedback、height guard、
stall recovery 和 hard safety filter。最终比较成功、碰撞、完成时间和预算。

### 0.4 仿真中的 P8-SHIFT 原型具体怎样运行

每条 sequence 先在 nominal context 建立 posterior，然后在算法不知道真实
shift label 和时刻的情况下改变命令映射或物理条件。detector 根据
预测残差和预测 covariance 计算 normalized innovation energy，并用有界
CUSUM/evidence window 判断是否发生 shift：

- `frozen`：检测但不更新，用于证明“不适应会怎样”；
- `passive`：检测后按固定安全设计收数据；
- `full`：检测后扩大 posterior covariance，再由 task-aware planner 主动选择
  最有价值的恢复命令。

每个 recovery step 后用 held-out command 检查 rolling RMSE。主要问题是：
full 是否比 passive 更早降低误差、是否在 12-step 预算内恢复、最终误差是否
达标，而不是只看 detector 有没有报警。

### 0.5 哪些东西能从仿真直接继承，哪些不能

可以继承并应尽量复用：

- public data contracts、Bayesian model、feature transform；
- candidate pool、LHS/Sobol/random/D-opt/IVR planners；
- task distribution、posterior save/load；
- shift detector、inverse compensator、state machine、stopping rules；
- 统计单位、方法隔离、失败保留、manifest 和审计逻辑。

必须在真机重新确定，禁止直接复制：

- ROS topic 名、QoS、Unitree SDK 调用和 control mode；
- base height、roll/pitch、workspace、slew、速度和载荷阈值；
- 网络/heartbeat timeout、物理制动时间和 E-stop 行为；
- mocap/LiDAR 外参、参考定位频率和时间同步；
- 地图几何、摩擦材料、payload 支架和 COM；
- Isaac Lab policy checkpoint、仿真 friction/mass 数字及仿真随机 seeds。

代码入口、ROS/Unitree adapter 的实现边界和逐步联调方法见
`docs/p8_go2_implementation_guide_zh.md`。实机团队应先阅读该实现指南，
再执行本文第 3 节以后的采集协议。

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
| `P8-NAV` | 在线标定是否改善两个预注册真实路线上的下游导航，且保持预算/安全优势 | `paired_block_id` | 30 个完整 paired blocks | 必须 |
| `P8-SHIFT` | 受控实机域偏移后，full 是否优于 passive 的早期恢复 | 每个 shift 内的 `paired_block_id` | 4 shifts × 20 paired blocks | 必须（R1–R4 全部保留） |

两个数据包不能互相替代：

- 只有 `P8-NAV`：只是未完成的部分交付，可写已获得的真实在线标定/导航结果，但不满足
  本冻结 P8 的 `P8_EVIDENCE_GO`；P6 域偏移仍只能写仿真；
- 只有 `P8-SHIFT`：同样只是未完成的部分交付，可写真实恢复，但不满足本冻结 P8 的
  `P8_EVIDENCE_GO`，也不能证明下游导航；
- 两者都完成：可闭合当前 P6/P7 对应的实机证据，但 P8-NAV 的实机外部有效性只覆盖 `real_offset_slalom` 与 `real_weighted_arc`，不能表述成六类实机地图或未知地图泛化。

上述部分交付说明只限定“已经得到的数据可以支持什么表述”，不是授权删除或延期
P8-SHIFT。当前冻结 scope 的 `P8_EVIDENCE_GO` 条件始终是 P8-NAV 两路线与
P8-SHIFT R1–R4 全部完成。`CONFIRM_READY` 是采集前 Gate A–D、冻结 release
和签字全部通过后的解锁状态；它不要求正式数据已经采完。

所有开发、联调、pilot 和失败确认必须保留，但不得与正式确认性数据合并。

### 2.1 工作量和排期底线

仅按机器人运动时间计算：

- P8-NAV calibration 至少 `3,060 × 4 s = 3.4 h`；
- P8-NAV validation 至少 `1,920 × 4 s = 2.1 h`；
- P8-NAV navigation 为 480 个 episode，最坏 timeout 总时长 8 h；
- P8-SHIFT primary 为 `10,800 × 4 s = 12 h`；另有 480 个 nominal-restore
  sentinel（约 0.53 h commanded-motion），因此计划包含 11,280 个
  motion units、约 12.53 h commanded-motion。sentinel 修复后复验会使实际 raw
  attempts 大于这个计划值。

这些数字不包含 reset、回到起点、地图检查、换电、载荷安装、参考重定位、
QC、备份和技术故障。现场排期应为：

- backend/HIL/安全 commissioning：至少 3–5 个工作日；
- P8-NAV 正式采集：建议预留 7–10 个运行日，以 DEV dry run 的真实周转时间为准；
- P8-SHIFT 正式采集：通常再需 10–20 个运行日；
- 数据导出、视频复核、raw 重放和补齐技术无效 run：至少 3–5 个工作日。

不得通过复用不同方法的 calibration、缩短 trial、在 CONFIRM 冻结后再减少这
两张地图、跳过失败 run 或把同一 block 拆成伪独立重复来压缩工作量。

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
│   ├── p8_go2_implementation_guide_zh.md
│   ├── p8_safety_review_criteria.yaml
│   ├── analysis_plan_template.yaml
│   └── analysis_plan.yaml
├── configs/
│   ├── p8_real_safety.yaml
│   ├── topic_map.yaml
│   ├── reference_to_base_extrinsic.yaml
│   ├── human_trust_registry.yaml
│   ├── p8_real_nav_confirmatory.yaml
│   └── p8_real_shift_confirmatory.yaml
├── schedules/
│   ├── nav_block_schedule.csv
│   ├── shift_block_schedule.csv
│   ├── shift_date_order.csv
│   └── schedule_manifest.json
├── maps/
│   ├── real_offset_slalom.yaml
│   ├── real_weighted_arc.yaml
│   └── evidence/
│       ├── real_offset_slalom/
│       │   ├── survey.csv
│       │   └── overview_photo.jpg
│       └── real_weighted_arc/
│           ├── survey.csv
│           └── overview_photo.jpg
├── commands/
│   ├── nav/
│   │   ├── candidate_pool.csv
│   │   ├── feature_reference_pool.csv
│   │   ├── dense_design.csv
│   │   ├── lhs_design.csv
│   │   ├── sobol_design.csv
│   │   ├── random_design.csv
│   │   ├── active_seed.csv
│   │   ├── validation_commands.csv
│   │   └── task_distribution.csv
│   └── shift/
│       ├── candidate_pool.csv
│       ├── feature_reference_pool.csv
│       ├── pre_calibration_seed.csv
│       ├── pre_monitor.csv
│       ├── post_monitor.csv
│       ├── validation_commands.csv
│       ├── passive_recovery.csv
│       ├── task_nominal.csv
│       ├── r4_task_pre.csv
│       ├── r4_task_post.csv
│       ├── restore_sentinel.csv
│       └── nominal_restore_thresholds.yaml
├── schemas/
│   ├── common.schema.json
│   ├── topic_map.schema.json
│   ├── safety_config.schema.json
│   ├── reference_extrinsic.schema.json
│   ├── nav_config_template.schema.json
│   ├── shift_config_template.schema.json
│   ├── nav_config.schema.json
│   ├── shift_config.schema.json
│   ├── schedule.schema.json
│   ├── schedule_manifest.schema.json
│   ├── map_geometry.schema.json
│   ├── map_survey.schema.json
│   ├── shift_evidence_content.schema.json
│   ├── shift_evidence.schema.json
│   ├── preflight_report.schema.json
│   ├── static_preflight_report.schema.json
│   ├── operation_report.schema.json
│   ├── resolved_config.schema.json
│   ├── event_journal.schema.json
│   ├── protocol_checkpoint.schema.json
│   ├── block_session_initialization.schema.json
│   ├── runtime_initialization_result.schema.json
│   ├── scientific_unit_result.schema.json
│   ├── planner_decision.schema.json
│   ├── runtime_state.schema.json
│   ├── transition_trace.schema.json
│   ├── prepared_attempt.schema.json
│   ├── frozen_safety_state.schema.json
│   ├── command_preauthorization.schema.json
│   ├── physical_attempt_artifact.schema.json
│   ├── unit_artifact.schema.json
│   ├── nominal_restore_reference.schema.json
│   ├── actuation_receipt.schema.json
│   ├── shift_receipt.schema.json
│   ├── transform_proof.schema.json
│   ├── global_state_proof.schema.json
│   ├── quota_record.schema.json
│   ├── reset_authorization.schema.json
│   ├── bag_segment_index.schema.json
│   ├── bag_range_inventory.schema.json
│   ├── watchdog_state.schema.json
│   ├── human_trust_registry.schema.json
│   ├── human_approval_request.schema.json
│   ├── human_approval.schema.json
│   ├── operator_gate_receipt.schema.json
│   ├── scope_authorization_request.schema.json
│   ├── scope_authorization.schema.json
│   ├── arm_authorization.schema.json
│   ├── safety_review.schema.json
│   ├── safety_review_criteria.schema.json
│   ├── safety_review_bundle.schema.json
│   ├── safety_review_decision.schema.json
│   ├── safety_review_receipt.schema.json
│   ├── data_lock.schema.json
│   ├── data_lock_commit.schema.json
│   ├── gate_report.schema.json
│   ├── backend_hardware_gate_report.schema.json
│   ├── hil_event_log.schema.json
│   ├── hil_case_result.schema.json
│   ├── hil_trigger.schema.json
│   ├── hil_result.schema.json
│   ├── hil_zero_receipt.schema.json
│   ├── gate_evidence_manifest.schema.json
│   ├── source_audit_report.schema.json
│   ├── cli_help_audit_report.schema.json
│   ├── robot_dependency_manifest.schema.json
│   ├── integration_stage_manifest.schema.json
│   ├── dev_release_manifest.schema.json
│   ├── candidate_manifest.schema.json
│   ├── tools_manifest.schema.json
│   ├── release_manifest.schema.json
│   ├── analysis_plan_template.schema.json
│   ├── analysis_plan.schema.json
│   ├── confirmatory_analysis.schema.json
│   ├── input_lock_manifest.schema.json
│   ├── golden_expected.schema.json
│   ├── delivery_manifest.schema.json
│   └── exported_tables/
│       ├── session_metadata.schema.json
│       ├── block_schedule_executed.schema.json
│       ├── attempt_ledger.schema.json
│       ├── calibration_samples.schema.json
│       ├── calibration_trials.schema.json
│       ├── validation_trials.schema.json
│       ├── planner_candidates.schema.json
│       ├── navigation_trace.schema.json
│       ├── episode_metrics.schema.json
│       ├── shift_monitor_metrics.schema.json
│       ├── shift_recovery_metrics.schema.json
│       ├── nominal_restore_sentinel_metrics.schema.json
│       ├── changeover_evidence_index.schema.json
│       ├── safety_events.schema.json
│       ├── safety_review_index.schema.json
│       ├── state_machine_trace.schema.json
│       ├── time_sync_diagnostics.schema.json
│       └── posterior_index.schema.json
├── tools/
│   ├── config_validate_p8
│   ├── generate_p8_schedules
│   ├── preflight_p8
│   ├── run_p8_nav
│   ├── run_p8_shift
│   ├── retry_p8_unit
│   ├── export_p8_delivery
│   ├── validate_p8_delivery
│   ├── analyze_p8_confirmatory
│   ├── review_p8_safety
│   ├── reset_p8_abort
│   ├── sign_p8_approval
│   ├── replay_p8
│   └── freeze_p8_release
├── environment/
│   ├── analysis_requirements.lock.txt
│   ├── robot.Dockerfile
│   ├── robot_requirements.lock.txt
│   ├── rosdep.lock-or-install-manifest.txt
│   ├── third_party_robot_dependencies.yaml
│   └── dependency_evidence/
│       ├── unitree_sdk.LICENSE.txt
│       ├── command_bridge.LICENSE.txt
│       ├── reference_stack.LICENSE.txt
│       └── patches/                  # 仅 manifest 中 PATCHED 的固定 patch files
├── test_reports/
│   ├── p8_gates/
│   │   ├── gate_a_software.json
│   │   ├── gate_b_static_integration.json
│   │   ├── gate_c_hil.json
│   │   └── gate_d_confirm_ready.json
│   ├── p8_gate_approvals/
│   │   ├── requests/
│   │   │   └── [raw_sha256].json
│   │   └── approvals/
│   │       └── [raw_sha256].json
│   └── p8_gate_evidence/
│       ├── gate_a/
│       │   ├── logs/                 # 01..14 stdout/stderr raw bytes
│       │   ├── coverage.json
│       │   ├── pytest_non_hil.xml
│       │   ├── pytest_golden.xml
│       │   ├── config_tracked.json
│       │   ├── source_audit.json
│       │   ├── cli_help_audit.json
│       │   ├── dev_schedule_report.json
│       │   ├── confirm_schedule_report.json
│       │   ├── dev_schedule/
│       │   ├── confirm_schedule/
│       │   ├── evidence_manifest.json
│       │   └── checksums.sha256
│       ├── gate_b/
│       │   ├── preflight_reports/[raw_sha256].json
│       │   ├── evidence_manifest.json
│       │   └── checksums.sha256
│       └── gate_c/
│           ├── hil_event_log.json
│           ├── cases/[raw_sha256].json
│           ├── artifacts/[raw_sha256].bin
│           ├── evidence_manifest.json
│           └── checksums.sha256
├── tools_manifest.json
├── candidate_manifest.json
├── release_manifest.json
└── checksums.sha256
```

以上是最终 seal 的 exact allowlist；目录外额外文件与缺文件同样失败。repository
`schemas/p8/` 的内容逐字节复制到 release `schemas/`，不得同时维护
`protocol/exported_table_schemas/` 第二份副本。source gate report
`reports/p8_gates/<name>` 在 seal 中逐字节复制到
`test_reports/p8_gates/<name>`。每个 signed Gate report 引用的 strict
`HumanApprovalRequest/HumanApproval` bytes 从
`reports/p8_gate_approvals/{requests,approvals}/` 按 raw hash 逐字节复制到
`test_reports/p8_gate_approvals/{requests,approvals}/`；文件名必须恰等于内容 raw
SHA-256，额外/缺失/重名不同 bytes 都失败。所有文件必须由
`checksums.sha256` 覆盖；校验文件本身不
列入自身，避免不可能的 self-hash。

`environment/dependency_evidence/patches/` 是唯一的 manifest-projected conditional
allowlist：每个 `PATCHED` dependency 恰有实现指南 §4.2 固定 basename 的一个 patch，`CLEAN` 不得有，
`UNSET-P8-NOT-INTEGRATED` 使 freeze 失败。除此之外上树没有 optional file 或 glob。

Gate A 的 14 条冻结命令 stdout/stderr、coverage、JUnit、tracked-config report、两套
schedule/report、source audit 与 CLI-help audit，Gate B 的两份 static preflight raw report，
以及 Gate C 本次 HIL 的 event log/case/
strict typed trigger/result/zero-receipt artifacts 也必须按实现指南 §19.4.7 复制到
`test_reports/p8_gate_evidence/`，并由各自 strict evidence manifest 和局部 checksums
覆盖。signed Gate report 中的 artifact
`{artifact_kind,path,semantic_sha256,raw_sha256,size_bytes}` 必须解析到这个 release 内子树；
只留外部路径、stdout hash 或 summary 不算可离线复核的 frozen release。
Gate B 的两份报告必须通过
`schemas/static_preflight_report.schema.json`（`p8.static-preflight-report.v1`），而不是
invocation-level `operation_report.schema.json`；`schemas/preflight_report.schema.json` 仍只服务
runner 内部 attempt-bound preflight 持久对象。两种 preflight schema 不得混用。

protocol 的 source→release mapping 同样唯一：两份 Markdown 从 `docs/` 逐字节复制；
`configs/experiments/p8_safety_review_criteria.yaml` 复制为
`protocol/p8_safety_review_criteria.yaml`；
`protocol/analysis_plan.yaml` 不是现场手改文件；它由
`configs/experiments/p8_analysis_plan_template.yaml` 和已通过 pre-lock validation 的
DEV `manifests/input_lock_manifest.json` 按实现指南 §3/§19.4.7 唯一规则生成。
template 中 `power_plan.pilot_input_lock_manifest_raw_sha256=null`；final copy 仅将该值
替换为 DEV input-lock raw hash，其他 bytes 的 semantic value不得改变。
禁止在 freeze 当天从 notebook、邮件或未跟踪路径另取 analysis plan。
四份 tracked source 是
`configs/experiments/p8_real_{nav,shift}_{dev,confirmatory}_template.yaml`，不是可运行
config。`stage-integration` 按实现指南 §6.1 的唯一规则填入 commit/container/
role-matched schedule provenance，生成 release 中无 `_template` 后缀的四份 config；
除明列 derived fields 外的 semantic value 必须与 template 相同。
`configs/hardware/go2/` 中冻结后的
`p8_real_safety.yaml,topic_map.yaml,reference_to_base_extrinsic.yaml,
human_trust_registry.yaml` 也按 basename复制。final `p8_frozen_release` 只含两份
`_confirmatory` materialized config 和一套 CONFIRM schedule；两份 `_dev` config 及 DEV
schedule 只存在实现指南 §19.4.7 的独立 `p8_dev_release`。role/file/release
交叉、release外 config 或 hash不符均 exit 2。

所有冻结只读 ref 使用一套路径语义：字面值是 validated release root-relative POSIX path，
绝不相对 config 或 map YAML 所在目录解析。实机 runtime 先验证 `--release-root` 的 manifest/
checksums/exact allowlist，再从该 root 读取；integration stage 内部则用实现指南 §6.1 的
`ValidatedStageRoleView(stage, DEV|CONFIRM)` 将同一 canonical namespace 确定性映射到
`common/` 与对应 `views/<ROLE>/`，不得把物理 `views/...` path 写回 report/config。
tracked template 只保存 canonical release refs，由唯一 `RepositorySourceMap` 定位 repository
source。关键字面值固定为：`schedules/schedule_manifest.json`、
`maps/{real_offset_slalom,real_weighted_arc}.yaml`、`commands/nav/...`、
`commands/shift/...` 和 `maps/evidence/<map_id>/{survey.csv,overview_photo.jpg}`；absolute、
config-relative/map-relative、`../`、symlink 或 release 外 hash-identical fallback 都失败。

正式数据的 canonical raw/export表保留真实 `method_id`；它们只交给 runner/data custodian，
不直接交 blind safety reviewer。安全盲审由实现指南 §19.2 的 opaque review token、中性
路径和最小字段 bundle完成，并在任何 outcome table审阅/统计分析前锁定。当前协议**不生成**
method-blinding key、`blinded_method_id` 或 `UNBLINDING_COMMIT`，避免一边明文导出 method、
一边声称方法解盲。confirmatory analyzer只需验证
hash-valid `p8.data-lock-commit.v1` 后读取 canonical `method_id`。
十四个工具必须有 `--help`、非零失败退出码和一个已通过的 DEV dry-run 示例。
实机团队不应现场手写汇总指标或猜测 schema。

release tree 中的文件名是冻结的分发名，不是另三套实现。source→console→release 映射
唯一为：

| repository source | `pyproject.toml` console entry | release path |
|---|---|---|
| `src/calibagent/cli/p8_config_validate.py` | `calibagent-p8-config-validate` | `tools/config_validate_p8` |
| `src/calibagent/cli/p8_generate_schedules.py` | `calibagent-p8-schedule` | `tools/generate_p8_schedules` |
| `src/calibagent/cli/p8_preflight.py` | `calibagent-p8-preflight` | `tools/preflight_p8` |
| `src/calibagent/cli/run_p8_nav.py` | `calibagent-p8-run-nav` | `tools/run_p8_nav` |
| `src/calibagent/cli/run_p8_shift.py` | `calibagent-p8-run-shift` | `tools/run_p8_shift` |
| `src/calibagent/cli/p8_retry_unit.py` | `calibagent-p8-retry-unit` | `tools/retry_p8_unit` |
| `src/calibagent/cli/export_p8_delivery.py` | `calibagent-p8-export` | `tools/export_p8_delivery` |
| `src/calibagent/cli/validate_p8_delivery.py` | `calibagent-p8-validate-delivery` | `tools/validate_p8_delivery` |
| `src/calibagent/cli/analyze_p8_confirmatory.py` | `calibagent-p8-analyze` | `tools/analyze_p8_confirmatory` |
| `src/calibagent/cli/p8_review_safety.py` | `calibagent-p8-review-safety` | `tools/review_p8_safety` |
| `src/calibagent/cli/p8_reset_abort.py` | `calibagent-p8-reset-abort` | `tools/reset_p8_abort` |
| `src/calibagent/cli/p8_sign_approval.py` | `calibagent-p8-sign-approval` | `tools/sign_p8_approval` |
| `src/calibagent/cli/p8_replay.py` | `calibagent-p8-replay` | `tools/replay_p8` |
| `src/calibagent/cli/freeze_p8_release.py` | `calibagent-p8-freeze-release` | `tools/freeze_p8_release` |

`freeze_p8_release.py` 必须从上述十四个 installed entry 生成带固定 Python interpreter/container
入口的 POSIX executable wrapper，wrapper 只调用对应 module `main()`，不复制业务逻辑；
release validator 对 wrapper path、mode 和 `--help` 做 exact check。环境输入的唯一
source→release 映射为：

| `tools_manifest.lock_files[].logical_name` | repository `source_path` | release `release_path` |
|---|---|---|
| `analysis_requirements` | `env/analysis/requirements-p8.lock.txt` | `environment/analysis_requirements.lock.txt` |
| `robot_container_recipe` | `env/robot/Dockerfile` | `environment/robot.Dockerfile` |
| `robot_python_requirements` | `env/robot/requirements.lock.txt` | `environment/robot_requirements.lock.txt` |
| `robot_rosdep_install_manifest` | `env/robot/rosdep.lock-or-install-manifest.txt` | `environment/rosdep.lock-or-install-manifest.txt` |
| `third_party_robot_dependencies` | `env/robot/third_party_robot_dependencies.yaml` | `environment/third_party_robot_dependencies.yaml` |
| `unitree_sdk_license` | `env/robot/dependency_evidence/unitree_sdk.LICENSE.txt` | `environment/dependency_evidence/unitree_sdk.LICENSE.txt` |
| `command_bridge_license` | `env/robot/dependency_evidence/command_bridge.LICENSE.txt` | `environment/dependency_evidence/command_bridge.LICENSE.txt` |
| `reference_stack_license` | `env/robot/dependency_evidence/reference_stack.LICENSE.txt` | `environment/dependency_evidence/reference_stack.LICENSE.txt` |

`lock_files` 必须有上述 8 个固定项；manifest 中每个 `PATCHED` dependency 再按实现指南
§4.2 固定 path 增加对应 `<id-lower>_patch` 项，因此总数只能为 8–11，并按
`logical_name` UTF-8 bytes 排序。每项的 source/release raw bytes 和 SHA-256 必须相同。
这些 target 同时是 integration stage
`common/environment/`、DEV release、candidate 和 final release `environment/` 的 exact
allowlist，各阶段不得增删或重新 resolve。根目录 `container_image_digest.txt` 不在
`environment/` 内重复，也不进入 `lock_files`。strict manifest 是 Unitree SDK、command
bridge、reference stack 的 URL/40-hex commit/SPDX license/patch status 唯一机器真源；允许
tracked 骨架暂写 `UNSET-P8-NOT-INTEGRATED`，但任何 freeze/PASS Gate 遇到它必须失败。
license bytes 和 PATCHED patch bytes 必须按 manifest 投影复制，不得 glob 或引用机器人主机文件。
禁止实机人员手工重命名或现场重新 resolve dependencies。
十四个入口的 exact argv、读写边界、一次执行粒度、machine output 和 exit code
统一以实现指南 §19.1–19.4 为权威；`RELEASE_README.md` 只能逐字摘录该
合同和不运动示例，不得为实机现场另定一套参数。

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
4. 在两张实机地图的 start/goal/极端位置各静止 10 s，确认无遮挡失锁；
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
- 方法顺序使用冻结的 near-balanced Williams/Latin schedule；因为 `30/8`
  不是整数，每种方法在每个顺序位置出现 3 或 4 次，任意方法间的位置计数差
  不超过 1；
- 8 种方法的 56 个 ordered predecessor pairs 在所有 block 相邻位置的
  出现次数差不超过 1；
- 两个地图在每种方法内部使用冻结的 `AB/BA` 顺序，30 个 blocks 中精确各
  15 次；
- 电池、地面、地图和 robot 状态记录；
- 方法不能固定绑定某一天、电池或地图顺序。
- `map_order×method_position` 和 `method_position×date_slot` 可行 cell 计数差
  不超过 1，randomization audit 交付完整 contingency table。

P8-SHIFT 每个 shift 的 20 个 blocks：

- 至少分布在 4 个独立日期/时间块；
- 每个 block 内 frozen/passive/full 使用冻结的 near-balanced 顺序，各位置出现
  6 或 7 次，6 种 ordered predecessor pair 的出现次数差不超过 1；
- 四个 shift 在 date slot/日内顺序中使用冻结 4-shift Williams allocation，
  不得让某个 shift 永远在某天第一个或最后一个执行；
- 三个方法使用相同 prior、初始设计、monitor commands、validation commands
  和 shift 定义，但每种方法必须独立执行 12 个 pre-shift calibration trial，
  不得共享实际 observation 或 posterior；
- 任何 complete 失败都保留。

三份 schedule source 必须由一个非自引用 manifest 分别绑定，不能把三个 hash 填进同一
scalar 字段：

```text
schedule_manifest.json:
  schema_version = "p8.schedule-manifest.v1"
  entries = [
    {schedule_id,schedule_path,schedule_sha256,generator_version,schedule_seed,
     expected_rows,planned_primary_units,planned_sentinel_units,
     maximum_conditional_sentinel_units,maximum_conditional_context_return_units,
     planned_changeover_units,maximum_conditional_changeover_recovery_units}
  ]
```

`schedule_id` 恰为 `nav_block_schedule`、`shift_block_schedule`、
`shift_date_order` 各一条；path 必须分别指向第 4 节三份 CSV，hash 是 raw bytes
SHA-256。date-order entry 的 unit-count 字段全为 0。NAV/SHIFT block schedule 每行是
一个 `block × method`，并分别展开 `planned_unit_ids`、conditional sentinel、conditional
context-return、planned changeover 与 conditional changeover-recovery registry；具体列和
allocator 以实现指南 §14.4/§16.6 为准。manifest 自身不写自己的 hash，由 release 外层
checksums 覆盖。
CONFIRM `run_id` 必须在 schedule 生成前冻结，物理出现在三份 source CSV，并与 config、
manifest 和所有展开的 `AUX/{run}/...` ID 相等；不得到现场才给预注册 ID 替换占位符。
除 `block_schedule_executed.schedule_sha256` 按该行 `schedule_id` 取 entry source hash 外，
config/preflight/authorization/journal 中单数 `schedule_sha256` 一律指整个
`schedule_manifest.json` 的 raw-byte SHA-256。

schedule schema 必须按 `dataset_role` 强制 exact counts：DEV 的 NAV entry 为
`expected_rows=40,planned_primary_units=910`，SHIFT entry 为
`expected_rows=60,planned_primary_units=2700,planned_sentinel_units=120,
planned_changeover_units=120`；CONFIRM 对应为 NAV `240/5460`、SHIFT
`240/10800/480/480`。`shift_date_order` 的 unit-count 字段始终全 0。任何 DEV manifest
若携带 CONFIRM 30/20-block counts，或反之，均为 schema/validator failure。

### 7.3 开发和确认分离

数据角色和 attempt 角色必须分开，禁止用“重采”改变 estimand：

- `dataset_role` 只能是 `DEV`、`CONFIRM` 或 `TEST_FIXTURE`；
- `attempt_role` 只能是 `PRIMARY` 或 `RERUN_TECH`；
- 技术重采保持原 `dataset_role`、`run_id`、`scientific_unit_id`、`unit_type`、
  block/method/map/shift identity 和原计划 estimand；只分配新的 `attempt_uid` 与
  递增 `attempt_index`，并用 `retry_of_attempt_uid` 指向紧邻的上一 attempt；
- `RERUN-TECH-*` 只能作为 attempt UID/现场标签前缀，绝不是第四种
  `dataset_role`；`TEST_FIXTURE` 永不进入论文确认性分析。

两种真实数据角色使用不同且精确的 schedule cardinality：

| role | P8-NAV | P8-SHIFT | 用途 |
|---|---:|---:|---|
| `DEV` | 5 个完整 paired blocks | 每个 R1–R4 各 5 个完整 paired blocks | Gate D pilot；只估计预注册 readiness family |
| `CONFIRM` | 30 个完整 paired blocks | 每个 R1–R4 各 20 个完整 paired blocks | 唯一确认性结果 |

DEV 仍执行 NAV 全部 8 methods、每个 method 的两条路线，以及 SHIFT 全部 3 methods/
4 shifts，因而每个 Gate D comparison cell 都有恰好 5 个完整 paired differences。
DEV 的精确计划量为 NAV `510` calibration trials、`320` validation trials、`80`
navigation episodes；SHIFT 为 `60` sequences、`2,700` primary motion trials 和
`120` initial planned sentinel units。DEV validator 必须按这些数字验收；不得套用
CONFIRM 的 `3060/1920/480` 或 `240/10800/480`，也不得以技术重采增加独立 `pilot_n`。

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
| `B5_active_no_task` | 6 fixed seeds + 6 online uniform/no-task IVR | 12 | task ablation |
| `B6_random` | 冻结安全候选池随机采样 | 12 | 经典随机基线 |
| `B8_full` | 6 fixed seeds + 6 online task-weighted IVR | 12 | 主方法 |

因此“12-trial active protocol”是方法总预算，不表示 12 次都在线选择；真正依据
当前 posterior 在线 propose 的只有后 6 次。实机 runner、方法表、图注和论文表述
必须使用这一精确定义。

每个方法必须使用：

- 相同 `M1 affine` feature set；
- 相同 prior；
- 相同安全候选池；
- 相同 8 个 held-out validation commands；
- 相同 waypoint planner、gait、slew、height/interlock、stall recovery 和 hard
  safety；除 `B0_raw` 外的七种方法共用相同 inverse compensator 与 velocity feedback，
  `B0_raw` 是预注册的 raw-stack 消融；planner desired 只绕过 posterior inverse
  和 outer velocity feedback，之后仍通过与其他方法完全相同的 slew、
  height/interlock/stall、pre-transform 及 wire hard-safety 链；
- posterior reset；
- 不得让 validation commands 进入模型更新。

### 8.2 每个 P8-NAV block 的数据量

每个 block 包含：

- calibration：`30 + 6×12 = 102` 个 trial；
- validation：`8 methods × 8 commands = 64` 个 trial；
- navigation：`8 methods × 2 maps = 16` 个 episode。

30 个完整 blocks 的目标总量：

| 数据 | 数量 |
|---|---:|
| calibration trials | 3,060 |
| held-out validation trials | 1,920 |
| navigation episodes | 480 |
| method-level posterior states | 至少 240 份 |

这些数字是正式计划，不是最少录几条即可的参考值。

### 8.3 calibration trial 时序

实机使用 P1 已验证的 4.0 s commanded-motion profile；`precheck/warm-up` 在这
4.0 s 之外另计，因此一次正常 attempt 的总墙钟时间不少于 4.5 s：

| phase | 时长 | 是否进入 calibration measurement |
|---|---:|---|
| precheck/warm-up | ≥0.5 s | 否 |
| ramp-in | 0.6 s | 否 |
| settle | 0.8 s | 否 |
| measure | 2.0 s | 是 |
| ramp-out | 0.6 s | 否 |

measure 内 `model_input` 必须恒定；不得用 planned/candidate 冒充它。R1 还必须
同时记录矩阵后的 transmitted command；其余 shift 也保留两条通道。每个 trial
必须保留完整 ramp 和安全 trace。

每个 calibration/validation/SHIFT trial 前都必须重新检查冻结
calibration start pose/yaw 容差和 stationary window。超差时先 zero/disarm，
本冻结 CONFIRM 只允许 `manual_reposition_disarmed` 回位；
`approved_controlled_return` 为 DEV-only future extension且当前 runner fail closed。回位有独立 marker/raw/ledger，不进 model、
detector、trial budget 或 endpoint。

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

### 8.5 两个真实地图

地图 ID 固定为：

1. `real_offset_slalom`
2. `real_weighted_arc`

两图是从 P7 六类仿真任务中选出的实机确认子集。实机坐标、障碍物尺寸和
waypoint 必须在 DEV 中按场地重新设计、测量和冻结；不得直接复制 Isaac Lab
数值坐标。`real_offset_slalom` 检查交替横向修正与轴间耦合，
`real_weighted_arc` 检查连续非对称曲线跟踪。它们不构成未知地图分布样本。

每个 `real_offset_slalom.yaml`/`real_weighted_arc.yaml` 必须包含：

- world frame；
- start pose 和容差；
- `intermediate_waypoints` 坐标和顺序；执行 target 序列精确为
  `intermediate_waypoints + [goal]`，goal 不在 waypoint 中重复；
- goal 坐标、`goal_radius=0.25 m`；
- 软障碍物 `center_xy[2]`、`size_xy[2]`、`height_m`、安全材料；
- 机器人圆形 footprint `type=circle,radius_m`；
- 在线 collision 判据：footprint margin、contact topic/力阈值；视频仅事后盲审；
- timeout，默认 60 s；
- 现场实测坐标和测量工具；
- 一张带标尺的俯视图/照片；
- 文件 SHA-256，只写 release manifest/checksums，不写回被 hash 的 YAML。

所有方法使用同一地图、同一 waypoint planner 和同一成功/碰撞判据。每种
方法只标定和 validation 一次，再用同一冻结 posterior 依次执行两图；禁止按
地图重新标定或在 navigation 中更新 posterior。

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
同一 control tick 的终止优先级固定为
`SAFETY_ABORT > COLLISION > TECH_ABORT > SUCCESS > TIMEOUT`；每个 episode 只有一个
`terminal_reason`。失败 episode 的 completion time 统一 timeout-code 为 60 s。

timeout 和算法性 abort 是失败结果，不能当技术故障排除。

---

## 9. P8-SHIFT：实机域偏移检测与恢复

### 9.1 方法

| ID | 说明 |
|---|---|
| `frozen` | 检测后也不更新 posterior |
| `passive` | 检测后按冻结安全设计更新 |
| `full` | 检测、posterior inflation、task-aware active recovery |

三种方法必须共享相同 prior、pre-calibration 设计、pre/post monitor commands、
validation commands 和 shift 定义，但必须分别执行 calibration 并建立各自的
posterior；不得跨方法复用真实 observation 或 posterior。

P8-SHIFT 冻结使用与 P6 相同的 `m2_affine_cross_hinge` feature set；P8-NAV
使用 `m1_affine`。两者不得由 runner 根据数据自动选择。pre-calibration 的前
6 个 axis seed、4/5 个 monitor、12 个 passive recovery 和 8 个 validation 命令
必须在 tracked CSV 中逐行冻结并写入完整 SHA-256；后 6 个 pre-calibration
trial 使用相同冻结 candidate pool/task/config 在线执行 task-aware IVR。三种方法
的后 6 个实际命令可因各自 observation/posterior 不同而不同，但选择代码、pool、
task 和预算必须相同，且全 candidate table 必须记录。正式运行不得现场重新采样
固定表或重排。

### 9.2 四类受控 shift

| Shift ID | 具体实现 | 必须记录 |
|---|---|---|
| `R1_command_gain_coupling` | 在命令接口加入冻结、可逆的 gain/coupling matrix | 矩阵、启用时刻、代码/config hash |
| `R2_payload_com` | 快拆支架增加额外载荷；建议目标 2.0 kg，前向 COM 偏置不超过 20 mm | 所有既有+新增载荷、称重、安装坐标、照片 |
| `R3_surface_friction` | 从 nominal 地面进入预先测量的中等低摩擦安全材料 | 材料、批次、表面状态、摩擦代理测量、照片 |
| `R4_mixed_context` | 批准的小载荷 + 中等 friction shift + 冻结的 pre/post task profile | 每个组成量、pre/post task-distribution hash 及统一启用时刻 |

安全约束：

- `R2/R4` 的总附加载荷不得超过厂商/本地/支架批准值中的最小值；
- 推荐 2.0 kg 是实验目标上限，不是厂商额定值；
- 载荷必须刚性固定，有二次防脱落；
- 低摩擦表面不得造成不可控滑倒；
- 正式 shift 参数只可由 DEV commissioning 决定一次；
- shift 必须可重复测量，不能使用“地面大概更滑”等描述。

R4 的 task profile 是部署任务输入，不是 shift label。`T_pre`、`T_post`、各自
command/weight CSV 和 hash 必须在 DEV 后冻结；物理变化与 `T_post` 生效只写
一个统一 `shift_effective_at`。detector 不接收 profile ID、hash 或生效 marker；
`full` 仅在固定 recovery 阶段使用当前冻结 task distribution 选择候选。论文需
明确 R4 是可见任务目标变化与隐藏动力学变化的混合条件。

### 9.3 每个 shift sequence

每个 method/shift/block 需要 45 个 motion trials：

| 阶段 | trial 数 | 目的 |
|---|---:|---|
| pre-shift calibration | 12 | 6 个冻结 axis seed + 6 个在线 task-aware IVR；每方法独立建立 nominal posterior |
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
标记为 `post_recovery_monitor`。该命令固定为同一 recovery index 对应的
`passive_recovery.csv` 行，不发新的 active candidate，也不更新 posterior；
随后的 held-out validation 仍照常执行。因此样本量不随算法是否早恢复而变化。
`10,800` 是进入主分析的计划 trial 数，不包含 DEV、故障注入、上下文恢复
sentinel 或技术无效 attempt；这些额外数据仍全部保留。

### 9.4 shift 执行规则

- algorithm 不接收 shift label 或 shift time，也不接收含
  `terrain_id/payload_kg` 的完整 `RobotContext`；policy 只获得盲化的
  command/measurement/covariance/valid view；
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

两个 sentinel 不是现场自选命令；`restore_sentinel.csv` 精确引用
`pre_monitor.csv` 的 `SHIFT_PRE_MON_01` 和 `SHIFT_PRE_MON_04`，两者都使用
4.0 s trial profile。它们的 residual 与“12 个 nominal calibration 后、任何
pre-monitor alarm 前”保存的只读 nominal posterior 比较，不与 shift-adapted
posterior 比较。通过要求：两个 observation 均 valid；2×3 residual 的
joint RMSE 和三轴 maximum absolute residual 均低于 DEV 冻结阈值；start
pose、stationary、mode、gait、reference 和 safety 同时通过。

失败时保持 DISARMED，修复 context 后以新 `verification_set_id` 重做
完整两条。`SENTINEL_01/02` command ID 不变，但新 set 的两条记录分别使用包含
新 set ID 的新 `scientific_unit_id`、新 `attempt_uid`，且各自从
`attempt_role=PRIMARY,attempt_index=1` 开始；它们不是旧 unit 的技术重采。所有失败/
通过集均保留。因此 480 是 initial planned sentinel units，实际 sentinel scientific
units 和 raw attempts 可更多。
为了使这些条件复验仍可追溯，冻结 schedule 的
`planned_unit_ids` 只列 set 1，另以 `conditional_sentinel_unit_ids` 预先展开
set `2..maximum_verification_sets` 的所有稳定 ID。只能在前一整 set
失败且 context 修复/preflight 通过后顺序解锁；不得现场生成或跳过
ID。conditional IDs 不进入 480 planned sentinel 分母，但必须在 manifest
单独报告实际启用数。
精确字段与公式见实现指南第 16.7 节。

detector 的 trial index 跨 4 个 pre-monitor 与 5 个 post-monitor 严格使用
`1..9`。任何首次 alarm——包括 pre-shift false alarm——都立即触发该方法的
冻结 `on_alarm` 逻辑：`passive/full` 只做一次 posterior inflation，`frozen`
不 inflation；不能只在 post-shift 代码分支响应 alarm，否则算法实际上获得了
真实 shift 阶段。技术无效 monitor 可依规则重采；protocol-complete 但没有
有效 residual 的 monitor 不向 detector 伪造数值，保留为 missed evidence。

### 9.5 P8-SHIFT 主要 endpoint

- `full` 的 pre-shift false alarm；
- `full` 的 detection success 和 detection delay；
- `full` 的 recovery success 和 recovery trials；
- recovery trials 4–9 的早期 rolling RMSE；
- `passive early RMSE - full early RMSE`；
- full terminal RMSE；
- valid observation ratio；
- safety abort、zero-command latency 和 serious event。

缺失 rolling window 使用冻结 penalty `0.25`，不得删除该 block 或插值。
`passive`/`frozen` 的 detector rate 和 delay 完整报告为 secondary diagnostics，
但不替代上述 `full` primary rate gate。post-shift detector index 为 `5..9` 时，
endpoint delay 定义为 `index−4`，即 `1..5`；pre-shift alarm 计 false alarm，不能
再计作正确 post-shift detection。

---

## 10. 必须记录的原始逻辑通道

具体 ROS topic 名可由现场决定，但 `topic_map.yaml` 必须把每个 topic 映射到以下逻辑通道。

| 逻辑通道 | 最低要求 | 用途 |
|---|---|---|
| planner desired command | 每次 planner tick | 任务要求 |
| candidate commands + scores | 每次 propose | 复算 active/D-opt/安全选择 |
| safety decision | 每个候选和每个 monitor tick | accepted、reason codes |
| inverse compensated command | 每次控制 tick | 复查 compensator |
| model-input logical command | 每个控制 tick | 模型所标定的安全接口命令；R1 中位于矩阵之前 |
| post-transform command | ≥50 Hz | R1 矩阵之后、final wire safety 之前的命令 |
| transmitted command | ≥50 Hz | final wire safety 通过后真正送往 bridge 的 setpoint |
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
| navigation marker | episode start、stabilize、navigate start、waypoint、goal、timeout、collision/abort、zero-confirm | endpoint |
| collision/safety event | 事件发生时 | 原因、来源、operator confirmation |
| state-machine transition | 每次 transition | 检查合法流程 |
| network/clock diagnostics | ≥1 Hz 和事件触发 | latency/同步 |
| fixed overview video | 全程 ≥25 fps | 独立碰撞和安全复核 |

禁止只保存汇总 CSV 后删除 rosbag。
`navigation marker` 必须使用实现指南 §7.2 冻结的 `NavigationMarker.msg`，完整携带
AttemptIdentity、连续 event sequence、waypoint index/target、terminal reason 和 posterior
hash；不得复用缺少这些字段的 generic ExperimentMarker。raw marker 与 journal/export
按 `(attempt_uid,event_sequence)` 唯一 join。

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
├── protocol_artifacts/
│   └── [run_id]/
│       ├── journal/event_journal.jsonl
│       ├── block_sessions/[sha256].json
│       ├── initialization_results/[sha256].json
│       ├── scientific_results/[sha256].json
│       ├── planner_decisions/[sha256].json
│       ├── prepared_attempts/[sha256].json
│       ├── preflight_reports/[sha256].json
│       ├── human_approval_requests/[sha256].json
│       ├── human_approvals/[sha256].json
│       ├── safety_states/[sha256].json
│       ├── command_preauthorizations/[sha256].json
│       ├── physical_attempt_artifacts/[sha256].json
│       ├── unit_artifacts/[sha256].json
│       ├── runtime_states/[sha256].json
│       ├── nominal_restore_references/[sha256].json
│       ├── transition_traces/[sha256].json
│       ├── checkpoints/[sha256].json
│       ├── bag_range_inventories/[sha256].json
│       ├── bag_segment_indices/[sha256].json
│       ├── changeover_evidence_contents/[sha256].json
│       ├── changeover_evidence/[sha256].json
│       ├── actuation_receipts/[sha256].json
│       ├── shift_receipts/[sha256].json
│       ├── transform_proofs/[sha256].json
│       ├── safety_reviews/[sha256].json
│       ├── blinded_review_bundles/[sha256].json
│       ├── safety_review_decisions/[sha256].json
│       ├── blind_review_receipts/[sha256].json
│       ├── custodian_links/[sha256].age
│       ├── operator_receipt_refs/[sha256].json
│       ├── supervisor_records/[sha256].json
│       ├── quota_records/[sha256].json
│       ├── scope_authorizations/[sha256].json
│       ├── arm_authorizations/[sha256].json
│       ├── reset_authorizations/[sha256].json
│       ├── global_state_proofs/[sha256].json
│       └── post_lock/
│           ├── human_approval_requests/[sha256].json
│           ├── human_approvals/[sha256].json
│           ├── data_locks/[sha256].json
│           └── data_lock_commits/[sha256].json
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
│   ├── nominal_restore_sentinel_metrics.csv
│   ├── changeover_evidence_index.csv
│   ├── safety_events.csv
│   ├── safety_review_index.csv
│   ├── state_machine_trace.csv
│   ├── time_sync_diagnostics.csv
│   └── posterior_index.csv
├── posterior/
│   └── objects/posterior_v[version]_[full-sha256].npz
├── analysis/
│   └── confirmatory_analysis.json
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
│   ├── input_lock_manifest.json
│   └── delivery_manifest.json
└── checksums.sha256
```

`protocol_artifacts/[run_id]` 的一级/二级目录名是 exact allowlist；`[sha256].json`/`.age`
的文件名使用最终 raw bytes 的 64 位小写 `raw_sha256`，不能用任意说明性名字。journal
文件名字面固定。对象内部/commit引用的 `*_sha256` 是各 schema 定义的
`semantic_sha256`（通常对排除自身 hash 字段的 canonical preimage计算）；它不假定等于 raw
hash。每个 leaf directory 必须有 manifest class index，按 semantic hash 唯一解析到 raw
path/hash；semantic collision、一个 semantic hash映射多组不同 raw bytes、或绕过 index按
文件名猜 ref均失败。每个对象由对应 strict schema 验证，
其中 runtime state 用 `runtime_state.schema.json` 的 NAV/SHIFT `oneOf`；
`changeover_evidence_contents/` 只存 approval-free `EvidenceBundleContent` 并使用
`shift_evidence_content.schema.json`；`changeover_evidence/` 只存签名完成的 EvidenceBundle并
使用 `shift_evidence.schema.json`，两类不得混放或把 content冒充 final bundle；
`global_state_proofs/` 使用 `global_state_proof.schema.json`，至少绑定同一
atomic cut 的 supervisor state/quota/receipt/active-scope heads、起止 sequence、引用过的
scope/arm/reset hashes与逐链 record path/hash。所有 path必须解析到本 delivery 的
`supervisor_records/quota_records/operator_receipt_refs/scope_authorizations/
arm_authorizations/reset_authorizations`，不得指机器人上的外部 global root；validator 在
离线、无机器人/ROS条件下仅靠这些副本重算每条 chain/head。delivery manifest
必须逐类给 `expected_logical_ref_count,actual_logical_ref_count,unique_object_count,
total_bytes,class_index_sha256,journal_event_count`，并覆盖 session init、
INIT result/commit、scientific result/commit、planner decision、runtime state、transition
trace、checkpoint、bag inventory/segment index、safety review、operator receipt ref 和
robot-global state proof，以及 exact tree 中其他每个 object leaf directory；journal replay
重算的 refs/counts/class indices 必须逐项相等。缺目录、缺
referenced object、orphan 被误列为 effective、额外非 allowlist 文件或 checksum 漏项都使
validator 退出 6。

`class_index_sha256` 精确为
`sha256(canonical_json(sorted([{relative_path,semantic_sha256,raw_sha256,size_bytes,
schema_version},...], key=(semantic_sha256,relative_path))))`；
不使用未定义的 Merkle tree。`unique_object_count` 按 path/hash 去重，logical ref count 按
journal/commit 引用计数，两者不得混为一谈；`journal_event_count` 只对有对应 event 的类别
填写，否则为 0。若某 schema 没有 detached/self hash，`semantic_sha256=raw_sha256`；
`checksums.sha256` 永远验证 raw bytes，protocol joins永远使用 semantic hash。

seal顺序固定为：全部 required blind safety decision/approval/ingest 与
`SAFETY_REVIEW_COMMIT` 完成 → exporter生成 tables与 input-lock manifest → pre-lock validate →
在 excluded `post_lock/` 中生成 DataLock request/approvals/DataLock/detached commit →
confirmatory analysis → final delivery manifest/checksums。`input_lock_manifest.json` 覆盖
analyzer所有科研输入（包括 safety review records、receipt和此时已封口的 main journal），
但明确排除 `analysis/`、`protocol_artifacts/*/post_lock/`、final manifest/checksums及自身。
input lock生成后 main journal 不得再 append；DataLock 使用 post-lock detached commit，不伪装
成 journal event。final manifest覆盖 input subtree、input-lock、完整 post-lock subtree与analysis，
并证明被锁input的每个 class index/raw hash未变。不得先锁后补 safety review、替换
exported/posterior，或要求DataLock hash一个尚未生成的analysis文件。

`manifests/input_lock_manifest.json` 必须通过 strict
`p8.input-lock-manifest.v1`（`additionalProperties=false`，包括所有 nested object）。顶层字段
只能是：

```text
schema_version,lock_id,dataset_role,run_id,release_manifest_sha256,
analysis_plan_sha256,tools_manifest_sha256,environment_lock_sha256,
included_roots,excluded_paths,files,class_indices,total_file_count,total_bytes,
input_tree_sha256,input_lock_manifest_sha256
```

这两个 provenance hash 有 role-aware 但唯一的语义：`dataset_role=DEV` 时，
`release_manifest_sha256` 是 `dev_release_manifest.json` 的 raw SHA-256，
`analysis_plan_sha256` 是该 DEV release 内
`protocol/analysis_plan_template.yaml` 的 raw SHA-256；`dataset_role=CONFIRM` 时，两者分别是
final `release_manifest.json` 和 `protocol/analysis_plan.yaml` 的 raw SHA-256。
`TEST_FIXTURE` 由 fixture manifest 的 frozen refs逐字指定。DEV template hash不是把 template
伪称为确认性 plan；字段名为保持同一 input-lock wire schema，role conditional必须由 schema/
validator执行。`freeze-release prepare` 还必须重算 DEV release/template/input-lock三条链，
不能仅信 manifest内的字符串。

`included_roots` 是按 UTF-8 byte 排序的固定数组
`[exported,frozen_release,manifests/bag_metadata,manifests/run_manifests,maps,metadata,
posterior,protocol_artifacts,raw,reference]`；`excluded_paths` 是固定排序数组
`[analysis,checksums.sha256,manifests/delivery_manifest.json,
manifests/input_lock_manifest.json,protocol_artifacts/*/post_lock]`。glob 只允许这一个字面
pattern；不得让用户传入额外 include/exclude。每个 symlink、absolute path、`..`、重复 normalized
path、未列 root 或落入 exclude 的 file 都拒绝。

`files[]` 每项字段精确为
`relative_path,artifact_class,schema_version,semantic_sha256,raw_sha256,size_bytes`；无 detached
semantic hash 的文件令 semantic=raw，不写 null。按 `relative_path` 的 UTF-8 bytes 排序并覆盖
所有 included regular file。`class_indices[]` 每项字段精确为
`artifact_class,root_path,expected_logical_ref_count,actual_logical_ref_count,
unique_object_count,total_bytes,class_index_sha256,journal_event_count`，按
`(artifact_class,root_path)` 排序；其 `class_index_sha256` 使用本节前述唯一公式。
`files[]` 中每个 `(artifact_class,所属 root_path)` 恰由一个 class-index item覆盖，反向也不
允许没有 file/ref依据的 class；protocol journal 重算的 logical refs/counts 必须与它相等。
两个数组均不允许额外或缺失 key。

`total_file_count/total_bytes` 必须等于 `files[]` 重算值。
`input_tree_sha256=sha256(canonical_json({dataset_role,run_id,release_manifest_sha256,
analysis_plan_sha256,tools_manifest_sha256,environment_lock_sha256,included_roots,
excluded_paths,files,class_indices,total_file_count,total_bytes}))`；
`lock_id="P8-INPUT-"+input_tree_sha256[0:16]`。
`input_lock_manifest_sha256` 是排除该字段后对**完整 manifest**做 canonical JSON 的 SHA-256；
manifest最终 raw bytes SHA-256 不写回自身，而由 DataLock 的
`input_lock_manifest_raw_sha256` 绑定。validator必须同时重扫文件树、重算 class indices、
semantic self-hash 和 raw hash；仅检查一张预先生成的 file list 不算锁定。

DataLock之后不写 main journal，而在 excluded
`protocol_artifacts/[run_id]/post_lock/data_lock_commits/[sha256].json` 写 strict
`p8.data-lock-commit.v1`。其 exact fields、self-hash和唯一性采用实现指南 §18.4；它至少同时
绑定 input-lock semantic/raw hash、DataLock、共同 approval request、两份 approval、analysis
plan、criteria/safety-review tail 与已锁 main-journal tail。analyzer 的
`--data-lock-commit` 只接受这个 JSON path。

posterior 使用全局 immutable content-addressed object store，full hash 必须同时出现在
文件名、`posterior_index.snapshot_path/snapshot_sha256` 和 protocol commit。每个 index row
仍携带完整 runtime identity；相同初始 prior bytes可以去重，但 method/sequence live pointer、
runtime state、history、cursor 和更新事务不可共享。validator 按 identity 重放链，禁止以
相同 `posterior_version` 当全 run 唯一键，也禁止覆盖另一 scope 的 v0000。

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

### 12.0 统一 identity、attempt 和选择语义

所有 attempt-bound 表必须物理包含以下字段；不能只靠文件路径推断：

```text
dataset_role,attempt_role,run_id,session_id,block_id,shift_id,map_id,method_id,
scientific_unit_id,unit_type,attempt_uid,attempt_index,retry_of_attempt_uid,
selected_for_export,protocol_complete,valid,invalid_reason
observation_available,observation_valid,prediction_available
```

枚举和含义冻结如下：

- `dataset_role ∈ {DEV,CONFIRM,TEST_FIXTURE}`；技术重采不改变它；
- `attempt_role ∈ {PRIMARY,RERUN_TECH}`；第一次 attempt 为 `PRIMARY`，只有第 14 节
  允许的技术失败后才可用 `RERUN_TECH`；
- `attempt_uid` 在整个 delivery 内全局唯一；`attempt_index` 对同一
  `scientific_unit_id` 从 1 严格递增；`retry_of_attempt_uid` 在 PRIMARY 为空，在
  RERUN_TECH 必须等于同一 unit 的 `attempt_index-1`；
- `scientific_unit_id` 是冻结计划中的科学单元 ID，重采时不变。格式只能是：
  `NAV/{block}/{method}/CAL/{trial}`、`NAV/{block}/{method}/VAL/{trial}`、
  `NAV/{block}/{method}/EP/{map}/{episode}`、
  `SHIFT/{shift}/{block}/{method}/{phase}/{trial}`、
  `SHIFT/{shift}/{block}/{method}/SENTINEL/{verification_set}/{sentinel}`，或不进入 endpoint 的
  `AUX/{run}/{block}/{method}/{shift_or_NOT_APPLICABLE}/CONTEXT_RETURN/{return_id}`；
- primary 和 initial sentinel ID 必须出现在 `planned_unit_ids`；额外 sentinel 必须出现在
  `conditional_sentinel_unit_ids`；运行时触发的回位也不允许现场造 ID，只能按 journal
  顺序领取 `conditional_context_return_unit_ids` 中最小未使用的 AUX ID。三类 registry
  均在 CONFIRM release 前冻结；NAV 的 `{shift_or_NOT_APPLICABLE}` 写字面量
  `NOT_APPLICABLE`，SHIFT 写实际 shift ID；AUX registry 用尽就停机，不扩大现场
  namespace；
- `unit_type` 只能是 `nav_calibration`、`nav_validation`、`nav_episode`、
  `shift_pre_calibration`、`shift_pre_monitor`、`shift_post_monitor`、
  `shift_recovery`、`shift_recovery_validation`、`restore_sentinel`、
  `context_return`；planner candidate 继承它所服务的 unit type，不新造科学单元；
- `selected_for_export=true` 的准确含义是“进入 canonical scientific analysis
  view”，不是删除其他 attempt。所有 raw、ledger 和失败 attempt 都必须交付；
- 每个 planned primary scientific unit 恰有一个 `selected_for_export=true` 的
  attempt，机械选择第一个 `protocol_complete=true` 的 attempt。此前技术失败均为
  false；一旦已有 protocol-complete attempt，禁止再创建该 unit 的 attempt；
- `protocol_complete=true` 表示该计划单元已经形成冻结协议定义的科学 outcome 并
  消耗预算。算法 safety abort、timeout、collision、missed detection、slow/no
  recovery、高 RMSE 和 protocol-complete invalid observation 均属于这种情况；
- `valid` 与 `protocol_complete`、算法成败是三件不同的事；它投影 immutable
  `scientific_valid`，表示 protocol result结构/证据有效。`observation_available=true` 只允许
  TRIAL_OBSERVATION，届时 `observation_valid` required；没有 observation 的 all-rejected/
  pre-measure safety/NAV metrics/context-return令前者false、后者空。valid-ratio、模型更新、
  monitor NIS和rolling penalty只读 `observation_available && observation_valid`，不得用
  `valid=true` 冒充观测。`valid=false` 必须有冻结 `invalid_reason`；`valid=true` 时该字段为空。
  `prediction_available` 独立投影 posterior-before prediction是否持久；NIS/residual必须同时
  有 prediction与valid observation，不能从任一 `valid` flag猜测。

`restore_sentinel` 和 `context_return` 不属于 primary estimand，固定
`selected_for_export=false`。sentinel 的每个 verification set 全部保留；其通过规则
由 `set_passed` 决定。每个 sentinel verification set 都创建两个新的 scientific
units，均为 `attempt_role=PRIMARY,attempt_index=1,retry_of_attempt_uid` 为空；context
restore 失败后的新 set 不是旧 unit 的重采。`TEST_FIXTURE` 可以验证同一选择算法，
但 analyzer 不得产生 GO。

每个 selected planned unit即使 `unit_artifact_kind=NONE` 也必须有 ledger及对应计划级表行；
数值 measurement/residual列为空，observation_available=false/observation_valid空，不能整行
删除。all-rejected和pre-observation safety golden fixtures必须覆盖此规则。NAV episode/
trace/metrics的 observation字段固定 false/空（episode数值仍由 `valid` 判断）；SHIFT
monitor/window遇 observation不可用或invalid时按预注册 miss/0.25 penalty，不从分母删除。

#### 12.0.1 人工批准 artifact 的交付合同

`human_approval_requests/` 中每个对象必须通过 strict
`p8.human-approval-request.v1`，顶层字段精确为
`schema_version,request_id,approval_purpose,subject_kind,subject_id,subject_sha256,
robot_id,run_id,dataset_role,required_roles,minimum_distinct_people,
minimum_distinct_keys,issued_utc,expires_utc,trust_registry_sha256,request_sha256`。
`request_sha256=sha256(JCS(record 排除 request_sha256))`，approval 中的
`approval_request_sha256` 必须引用该 semantic hash。trust registry 角色 allowlist 为
`operator,safety_operator,safety_reviewer,pi,data_custodian,software_lead,
deployment_lead,hardware_lead,safety_lead,data_lead`。purpose/subject/roles/maximum TTL 必须
精确匹配：

对应 `HumanApproval` signed record 必须物理包含 `dataset_role`，枚举同样只允许
`DEV|CONFIRM|TEST_FIXTURE`，并与 request 的 purpose/subject/robot/run/dataset/trust-registry
逐位相同；不允许由文件路径推断 dataset role。

| purpose/对象 | subject | required roles | TTL |
|---|---|---|---:|
| `SCOPE` | `SCOPE_AUTHORIZATION_REQUEST` / scope request hash | operator + safety_operator | 43,200 s |
| `CHANGEOVER` | `EVIDENCE_BUNDLE_CONTENT` / content preimage hash | operator + safety_operator | 900 s |
| `CONTEXT_RETURN` | `CONTEXT_RETURN_GATE_PAYLOAD` / typed payload hash | operator + safety_operator | 900 s |
| `RESET` | `RESET_AUTHORIZATION_REQUEST` / reset request hash | operator + safety_operator | 600 s |
| `SAFETY_REVIEW` | `BLIND_SAFETY_VERDICT` / strict decision hash（含 bundle/verdict/reasons） | safety_operator + safety_reviewer | 604,800 s |
| `GATE_REPORT/A` | gate report preimage | software_lead | 604,800 s |
| `GATE_REPORT/B` | gate report preimage | deployment_lead + safety_operator | 604,800 s |
| `GATE_REPORT/C` | gate report preimage | hardware_lead + safety_lead | 604,800 s |
| `GATE_REPORT/D` | gate report preimage | data_lead + pi + safety_lead + software_lead | 604,800 s |
| `DATA_LOCK` | frozen input-set composite hash | data_custodian + pi | 86,400 s |

每个 required role 恰好一份 approval，person/key/nonce 两两不同；详细
subject ID/preimage、UTC consume-time 验证和 no-cycle hash 见实现指南 §6.5.2。
不存在 `approval_purpose=ATTEMPT`：`p8.gate.attempt.v1` 的两组 approval
path/hash 必须与 parent scope receipt 逐位相同，仅将 fresh
prepared/preflight/watchdog/start-pose evidence 自动绑入 attempt receipt。任意 per-attempt
人工 request、新签名或 subject=attempt 的 approval 都使 delivery validator 退出 6。

DataLock 的人工引用不得用 `path/hash` 缩写；record 必须先物理包含
`approval_request_path,approval_request_sha256`，再包含四个
独立字段 `pi_approval_path,pi_approval_sha256,
data_custodian_approval_path,data_custodian_approval_sha256`，且两者引用同一
`purpose=DATA_LOCK,subject_kind=DATA_LOCK_INPUT_SET` request；五个对象均位于 excluded
post-lock subtree并由 detached DataLockCommit覆盖。

#### 12.0.2 SHIFT 无 observation terminal outcome

已有 physical commit 但运行时 safety/technical terminal 无法形成 observation 时，实现必须
只调用一次实现指南 §16.2 的 exact API
`ShiftScientificHook.for_terminal_outcome(*,prior,spec,terminal)`；不能调
`__call__(observation=None)`或专用 writer。交付验收的 deterministic after-state 为：

| SHIFT unit | `protocol_complete=true` 无 observation 时的必须推进 |
|---|---|
| calibration | posterior no-update；有 selected command 则记录 attempted/history；cursor 前移；A12 以未变 posterior + 已尝试 history 冻结 nominal reference |
| pre/post monitor | 记录 scheduled gap；CUSUM/window/latch 不变；无 residual 不能产生 first alarm；cursor 前移 |
| recovery motion | 消耗 row但不 update；已冻结 selection 仍保留；cursor 进入同 index validation |
| rolling validation | 插入 `INVALID,q=0.25²` scheduled slot，保留最近 4 格并重算 rolling/recovered rule |
| restore sentinel | 第 1 条保存 unavailable partial slot并进入第 2 条；第 2 条形成 fail verdict，顺序激活下一预展开 set，或进入 exhausted pause |

上述分支均为 `observation_available=false,observation_valid=null`、posterior
before/after 相同、transition `NONE`。`protocol_complete=false` 时则所有 SHIFT
state/history/slots/verdict/reference/cursor 与 before 逐字节相同，A12 不生成 reference，
不生成 conditional event；但 scientific result/commit/checkpoint 仍必须存在。validator
必须覆盖五类 phase、A12、validation deque、sentinel 1/2/exhaustion 和 crash-resume
golden bytes，任一 cursor/state 偷跑都退出 6。

### 12.1 `session_metadata.csv`

```text
dataset_role,run_id,session_id,date_id,start_utc,end_utc,robot_id,robot_model,
robot_serial,firmware_version,sdk_version,source_commit,container_digest,
config_sha256,reference_sensor,reference_serial,reference_config_sha256,
extrinsic_sha256,time_sync_method,time_offset_ms,time_jitter_ms,terrain_id,
surface_id,payload_total_kg,payload_added_kg,payload_com_x_m,payload_com_y_m,
gait_id,battery_id,battery_start_ratio,battery_end_ratio,operator_id,
safety_operator_id,location,weather_or_indoor,floor_temperature_c,notes
```

正式数据中 required 字段不得填 `unknown` 或猜测值；非适用枚举字段使用本节规定的
`NOT_APPLICABLE`，真正 missing 才使用空 field。
session 精确对应 paired block：DEV NAV 5 行、SHIFT 20 行；CONFIRM NAV 30 行、SHIFT
每个 shift×block 一行、共 80 行；ID
格式和 lifecycle 按实现指南 §5.2.1。block 内 methods/crash resume/技术重采不得换
session/battery/reference；SHIFT metadata填 nominal baseline，计划 shift变化另由 changeover
表记录。`block_schedule_executed.session_id` 与相应 metadata/全部 attempt逐字相同。

### 12.2 `block_schedule_executed.csv`

```text
dataset_role,run_id,session_id,block_id,robot_id,date_id,shift_id,schedule_id,
planned_method_order,executed_method_order,planned_map_order_by_method_json,
executed_map_order_by_method_json,schedule_seed,schedule_sha256,
date_order_schedule_sha256,start_utc,end_utc,deviation,approved_deviation_reason
```

NAV 两个 map-order 字段必须是 key 恰为八个 method ID、value 恰为
`["real_offset_slalom","real_weighted_arc"]` 或反序的 canonical JSON object；SHIFT
写 `{}`。不得把八个不同顺序压成一个 `AB/BA` 字符串。`schedule_id` 对 NAV/SHIFT 分别为
`nav_block_schedule`/`shift_block_schedule`；`schedule_sha256` 从 release manifest 中
唯一满足 `entry.schedule_id == schedule_id` 的 entry 取 source CSV raw-bytes hash。
SHIFT 另填 `shift_date_order` entry 的 hash，NAV 的
`date_order_schedule_sha256=NOT_APPLICABLE`。这些 hash 可出现在执行后表中，但不出现在
被 hash 的 source CSV 本身。

### 12.3 `attempt_ledger.csv`

```text
dataset_role,attempt_role,run_id,session_id,block_id,shift_id,map_id,method_id,
scientific_unit_id,unit_type,trial_or_episode_id,attempt_uid,attempt_index,
retry_of_attempt_uid,retry_request_uuid,execution_order,bag_path,video_path,
start_timestamp_ns,end_timestamp_ns,physical_status,physical_terminal_reason,
physical_technical_failure_code,physical_measurement_constructed,
status,terminal_reason,
technical_failure_code,algorithm_outcome,posterior_transition_kind,
posterior_transition_factor,selected_for_export,protocol_complete,
valid,invalid_reason,observation_available,observation_valid,prediction_available,
reference_valid,command_log_valid,safety_abort,collision,
online_serious_safety_event,serious_safety_event,safety_review_commit_sha256,
operator_notes
```

`status ∈ {complete,pre_measure_abort,technical_abort,safety_abort,timeout}`。
`physical_status/physical_terminal_reason/physical_technical_failure_code/
physical_measurement_constructed` 从 immutable `ATTEMPT_PHYSICAL_COMMIT` 导出；
`status/terminal_reason/technical_failure_code` 从 immutable `SCIENTIFIC_UNIT_COMMIT` 的
effective scientific eligibility 导出。通常两者相同；若 physical complete 后、
scientific commit 前同步发现允许的 storage/integrity fault，前者仍 complete，后者才是
technical_abort。禁止回写 physical commit 来制造一致。
`timeout`、算法性 safety abort、碰撞和未到达均是有效 outcome，不是技术排除理由。
`retry_request_uuid` 与 `retry_of_attempt_uid` 仅在 `attempt_role=RERUN_TECH` required。
`posterior_transition_kind ∈ {NONE,MODEL_UPDATE,ALARM_INFLATION}`；只有后者的 factor 为
`8.0`，其他两类 factor 为空。`NONE` 要求 before/after posterior完全相同，
`MODEL_UPDATE` 要求 valid assimilation且 version+1，`ALARM_INFLATION` 要求首次 SHIFT
monitor alarm、`model_update_applied=false` 且 version+1。validator 从 scientific commit
重算，不从 posterior 文件数量猜测。

CSV `valid` 只投影 immutable `ScientificUnitResult.scientific_valid`，不从
`observation_sha256` 是否为空推断。`context_return` 没有 TrialObservation：fresh reference
终点验证通过，或有效测得 target 未到时，均 `valid=true,invalid_reason` 为空；前者 outcome
为 `CONTEXT_RETURN_COMPLETE`，后者为 `CONTEXT_RETURN_TARGET_NOT_REACHED`。无法得到终点
verification 时 `valid=false`：reference/frame/time-sync 根因使用对应 canonical code，
其他原因用 `MEASUREMENT_WINDOW_UNAVAILABLE`。成功 AUX 禁止写
`ATTEMPT_ABORTED_BEFORE_OBSERVATION`；该 code 只适用于原本要求 trial observation 的
planned measurement unit。protocol-complete safety outcome 也不是 observation invalid。

`invalid_reason` 是 immutable ScientificUnitResult 中 `primary_invalid_reason` 的 CSV
projection；完整多原因 tuple 保存在 scientific result，不用逗号拼进单元格。冻结词表及
由高到低的 primary priority 精确为：

```text
NONFINITE_VALUE
TIMESTAMP_NON_MONOTONIC
FRAME_MISMATCH
REFERENCE_INVALID
REFERENCE_SAMPLE_COUNT_LOW
REFERENCE_RATE_OUT_OF_RANGE
REFERENCE_GAP_EXCEEDED
REFERENCE_VALID_RATIO_LOW
TIME_SYNC_OFFSET_EXCEEDED
CROSS_STREAM_SKEW
CONTROL_TRACE_COVERAGE_LOW
COMMAND_DEVIATION_EXCEEDED
STEADY_RATIO_LOW
MEASUREMENT_WINDOW_UNAVAILABLE
PREDICTION_UNAVAILABLE
METRIC_RECONSTRUCTION_FAILED
ATTEMPT_ABORTED_BEFORE_OBSERVATION
```

`invalid_reason_codes` 去重后按上述 priority 排序，`primary_invalid_reason` 必须等于第一项；
同 priority 不存在。`valid=true` 时 primary=null 且 tuple为空；`valid=false` 时两者均
required。所有导出表的 `invalid_reason` 必须与 ledger 的 primary逐字相同，不能各自
挑一个原因或用 technical fault code替代 invalid reason。

现有 `MeasurementPipeline` 内部 reason 不能原样进入上述 enum。唯一允许的 canonical
mapping 为：

```text
INSUFFICIENT_SAMPLES         -> REFERENCE_SAMPLE_COUNT_LOW
NON_MONOTONIC_TIMESTAMP      -> TIMESTAMP_NON_MONOTONIC
TIMESTAMP_GAP                -> REFERENCE_GAP_EXCEEDED
EXCESSIVE_DROP_RATE          -> REFERENCE_VALID_RATIO_LOW
INSUFFICIENT_STEADY_RATIO    -> STEADY_RATIO_LOW
NONFINITE_ESTIMATE           -> NONFINITE_VALUE
COMMAND_NOT_CONSTANT         -> COMMAND_DEVIATION_EXCEEDED
```

frame/reference/time-sync preprocessor、pipeline mapping 和 prediction/metric 层先分别通过
各自 allowlist，再合并、去重并严格按上面的全局 priority 排序；来源顺序不影响 primary。
导出器只读取 immutable `ScientificUnitResult.primary_invalid_reason`，不得再次解析
`quality.reason_codes` 或自行选择原因。完整接口与未知 code 的 fail-closed 规则见实现指南
§9.5。

### 12.4 `calibration_samples.csv.gz`

每行是一条真实采样，不是 trial 均值：

```text
dataset_role,attempt_role,run_id,session_id,block_id,shift_id,map_id,method_id,
scientific_unit_id,unit_type,attempt_uid,attempt_index,retry_of_attempt_uid,
selected_for_export,protocol_complete,valid,invalid_reason,
observation_available,observation_valid,prediction_available,trial_id,phase,
sample_index,source_timestamp_ns,receive_timestamp_ns,monotonic_ns,
command_boot_id,command_sequence,command_requested_monotonic_ns,
relay_receive_monotonic_ns,command_published_monotonic_ns,ack_monotonic_ns,
posterior_version,planned_vx,planned_vy,planned_wz,candidate_vx,candidate_vy,
candidate_wz,safe_vx,safe_vy,safe_wz,model_input_vx,model_input_vy,
model_input_wz,post_transform_vx,post_transform_vy,post_transform_wz,
transmitted_vx,transmitted_vy,transmitted_wz,ack_vx,ack_vy,ack_wz,
ack_available,ref_pose_x,ref_pose_y,ref_pose_yaw,ref_cov_xx,ref_cov_xy,
ref_cov_xyaw,ref_cov_yy,ref_cov_yyaw,ref_cov_yawyaw,reference_tracking_state,
reference_frame_id,onboard_pose_x,onboard_pose_y,onboard_pose_yaw,velocity_vx,
velocity_vy,velocity_wz,base_height,roll,pitch,battery_ratio,
localization_valid,safety_accepted,safety_reason_codes,aborted,abort_reason
```

### 12.5 `calibration_trials.csv` / `validation_trials.csv`

```text
dataset_role,attempt_role,run_id,session_id,block_id,shift_id,map_id,method_id,
scientific_unit_id,unit_type,attempt_uid,attempt_index,retry_of_attempt_uid,
selected_for_export,protocol_complete,valid,invalid_reason,
observation_available,observation_valid,prediction_available,trial_id,source,
posterior_version,posterior_transition_kind,posterior_transition_factor,
cmd_vx,cmd_vy,cmd_wz,post_transform_cmd_vx,
post_transform_cmd_vy,post_transform_cmd_wz,transmitted_cmd_vx,
transmitted_cmd_vy,transmitted_cmd_wz,transform_id,transform_sha256,
measured_vx,measured_vy,measured_wz,predicted_vx,predicted_vy,predicted_wz,
residual_vx,residual_vy,residual_wz,cov_xx,cov_xy,cov_xw,cov_yy,cov_yw,
cov_ww,sample_count,duration_s,median_rate_hz,max_gap_s,clock_offset_ms,
steady_ratio,command_deviation,safety_events,raw_bag_ref,raw_time_start_ns,
raw_time_end_ns
```

validation 行必须标明 `source=held_out_validation`，并证明未用于 update。
本表单列 `posterior_version` 固定表示 command selection/prediction 使用的 before version；
若 `posterior_transition_kind!=NONE`，after version 必须通过同 attempt 的 scientific commit
连接 `posterior_index`，不得把 after 回填到该列。validation 必须 transition=`NONE`。
这里的 `cmd_vx/vy/wz` 固定表示 `model_input`：nominal、R2、R3、R4 中通常与
transmitted 相同；R1 中是 gain/coupling matrix 之前的安全逻辑命令。
`transmitted_cmd_*` 表示矩阵之后实际发送命令。模型、planner 和 detector 只能
读取前者；watchdog、raw recorder 和 evaluator 必须同时记录两者。

### 12.6 `planner_candidates.csv.gz`

```text
dataset_role,attempt_role,run_id,session_id,block_id,shift_id,map_id,method_id,
scientific_unit_id,unit_type,attempt_uid,attempt_index,retry_of_attempt_uid,
selected_for_export,protocol_complete,valid,invalid_reason,
observation_available,observation_valid,prediction_available,trial_id,planner_step,
posterior_version,candidate_rank,cmd_vx,cmd_vy,cmd_wz,score,information_gain,
cost,task_weighted,safety_accepted,safety_reason_codes,selected,
candidate_pool_sha256,planner_config_sha256
```

这里的 `selected` 只表示该 candidate 是否被 planner/safety adapter 选中；不得与
attempt 级 `selected_for_export` 混用。

### 12.7 `navigation_trace.csv.gz`

```text
dataset_role,attempt_role,run_id,session_id,block_id,shift_id,map_id,method_id,
scientific_unit_id,unit_type,attempt_uid,attempt_index,retry_of_attempt_uid,
selected_for_export,protocol_complete,valid,invalid_reason,
observation_available,observation_valid,prediction_available,episode_id,sample_index,
source_timestamp_ns,receive_timestamp_ns,monotonic_ns,posterior_version,
command_boot_id,command_sequence,command_requested_monotonic_ns,
relay_receive_monotonic_ns,command_published_monotonic_ns,ack_monotonic_ns,
waypoint_index,target_x,target_y,desired_vx,desired_vy,desired_wz,
inverse_target_vx,inverse_target_vy,inverse_target_wz,compensated_vx,
compensated_vy,compensated_wz,model_input_vx,model_input_vy,model_input_wz,
post_transform_vx,post_transform_vy,post_transform_wz,transmitted_vx,
transmitted_vy,transmitted_wz,ack_vx,ack_vy,ack_wz,ack_available,
velocity_feedback_active,height_guard_active,high_rate_interlock_active,
stall_recovery_active,stall_recovery_attempts,ref_pose_x,ref_pose_y,ref_pose_yaw,
ref_cov_xx,ref_cov_xy,ref_cov_xyaw,ref_cov_yy,ref_cov_yyaw,ref_cov_yawyaw,
reference_tracking_state,reference_frame_id,onboard_pose_x,onboard_pose_y,
onboard_pose_yaw,base_height,roll,pitch,velocity_vx,velocity_vy,velocity_wz,
localization_valid,collision,success,finished,safety_accepted,
safety_reason_codes,serious_safety_event
```

### 12.8 `episode_metrics.csv`

```text
dataset_role,attempt_role,run_id,session_id,block_id,shift_id,map_id,method_id,
scientific_unit_id,unit_type,attempt_uid,attempt_index,retry_of_attempt_uid,
selected_for_export,protocol_complete,valid,invalid_reason,
observation_available,observation_valid,prediction_available,episode_id,
terminal_reason,success,collision,timeout,safety_abort,arrival_time_s,
completion_time_s,path_length_m,arrival_x,arrival_y,goal_distance_at_arrival_m,
final_x,final_y,goal_distance_m,stall_recovery_attempts,height_guard_updates,
high_rate_interlock_updates,minimum_base_height_m,maximum_abs_roll_rad,
maximum_abs_pitch_rad,maximum_zero_command_latency_ms,reference_valid_ratio,
serious_safety_event,raw_bag_ref,video_ref
```

失败 episode 的 `completion_time_s` 统一写 frozen timeout，不得缺失或只对成功
episode 计算。即使 `valid=false`，protocol-complete episode 仍保留、消耗预算，且
以 frozen timeout 进入 outcome 分析；无法复算的其他连续指标按 12.12 置空。

### 12.9 P8-SHIFT 表

`shift_monitor_metrics.csv`：

```text
dataset_role,attempt_role,run_id,session_id,block_id,shift_id,map_id,method_id,
scientific_unit_id,unit_type,attempt_uid,attempt_index,retry_of_attempt_uid,
selected_for_export,protocol_complete,valid,invalid_reason,
observation_available,observation_valid,prediction_available,monitor_trial_id,
context_stage,monitor_trial,cmd_vx,cmd_vy,cmd_wz,measured_vx,measured_vy,
measured_wz,predicted_vx,predicted_vy,predicted_wz,normalized_nis,cusum,
positive_evidence_count,alarm,detected,detection_delay_trials,
posterior_before_version,posterior_after_version,posterior_transition_kind,
posterior_transition_factor,
post_transform_vx,post_transform_vy,post_transform_wz,transmitted_vx,
transmitted_vy,transmitted_wz,transform_id,transform_sha256,safety_events,
shift_marker_timestamp_ns,raw_bag_ref,raw_time_start_ns,raw_time_end_ns
```

`shift_recovery_metrics.csv`：

```text
dataset_role,attempt_role,run_id,session_id,block_id,shift_id,map_id,method_id,
scientific_unit_id,unit_type,attempt_uid,attempt_index,retry_of_attempt_uid,
selected_for_export,protocol_complete,valid,invalid_reason,
observation_available,observation_valid,prediction_available,recovery_trial,phase,
trial_id,source,cmd_vx,cmd_vy,cmd_wz,measured_vx,measured_vy,measured_wz,
predicted_vx,predicted_vy,predicted_wz,rolling_rmse,target_rmse,
post_transform_vx,post_transform_vy,post_transform_wz,transmitted_vx,
transmitted_vy,transmitted_wz,transform_id,transform_sha256,recovered,
posterior_version,posterior_transition_kind,posterior_transition_factor,
safety_events,raw_bag_ref,raw_time_start_ns,raw_time_end_ns
```

每个 `recovery_trial=1..12` 恰有两种 planned unit：`phase=recovery` 和
`phase=validation`；它们有不同 `scientific_unit_id`、`trial_id` 和 attempt chain。
rolling RMSE 只在 validation 行上定义，recovery 行留空。
本表单列 `posterior_version` 同样表示 recovery/validation prediction 的 before version；
transition kind/factor 与 scientific commit连接 after snapshot。validation row 必须 NONE，
recovery valid assimilation可为 MODEL_UPDATE。`shift_monitor_metrics` 已显式使用
before/after 两列，禁止再把其中任一解释成单列语义。

`nominal_restore_sentinel_metrics.csv`：

```text
dataset_role,attempt_role,run_id,session_id,block_id,shift_id,map_id,method_id,
scientific_unit_id,unit_type,attempt_uid,attempt_index,retry_of_attempt_uid,
selected_for_export,protocol_complete,valid,invalid_reason,
observation_available,observation_valid,prediction_available,sentinel_id,
verification_set_id,source_command_id,nominal_reference_posterior_version,
nominal_reference_posterior_sha256,cmd_vx,cmd_vy,cmd_wz,measured_vx,
measured_vy,measured_wz,predicted_vx,predicted_vy,predicted_wz,residual_vx,
residual_vy,residual_wz,joint_set_rmse,post_transform_vx,post_transform_vy,
post_transform_wz,transmitted_vx,transmitted_vy,transmitted_wz,transform_id,
transform_sha256,set_passed,safety_events,raw_bag_ref,raw_time_start_ns,
raw_time_end_ns
```

`set_passed` 在同一 `verification_set_id` 的两行上相同；少一行就是 false。
sentinel 不进入 primary SHIFT endpoint，但每个失败/通过 verification set 都必须与
raw/ledger 回链。sentinel 因 context 未恢复而复验是预注册 gate 逻辑，不得冒充
primary technical retry；新 `verification_set_id` 生成两个新的
`SHIFT/.../SENTINEL/{verification_set}/{sentinel}` scientific units，各自
`PRIMARY/index=1`，并保留完整旧 set。

#### 12.9.1 `changeover_evidence_index.csv`

R1 启用/恢复、R2–R4 物理安装/恢复位于两个 motion attempt 之间，
是 auxiliary changeover，不是 scientific motion unit。它们使用独立
`changeover_uid`，不得借用前一或后一 trial 的 `attempt_uid`：

每次 pre/post evidence 均先产生 approval-free strict `EvidenceBundleContent` 并写入
`changeover_evidence_contents/`；其 content hash生成 CHANGEOVER approval request，两人签名后
才 finalize `changeover_evidence/` 中的 EvidenceBundle。CSV 的 `*_evidence_bundle_sha256`
只引用 final bundle；validator继续解析其 `content_path/content_preimage_sha256` 和 request/
两 approval。缺 content、把 content hash冒充 bundle hash、pre签名复用到post或 bundle/approval
self-cycle均退出 6。exact workflow以实现指南 §16.6 为准。

```text
dataset_role,run_id,session_id,block_id,shift_id,method_id,
changeover_unit_id,changeover_kind,changeover_attempt_index,changeover_uid,
retry_of_changeover_uid,parent_changeover_uid,action,context_from,context_to,start_monotonic_ns,
effective_monotonic_ns,end_monotonic_ns,zero_confirmed,motion_inhibited,
pre_evidence_bundle_sha256,post_evidence_bundle_sha256,transform_readback_sha256,
transform_activation_record_sha256,
operator_id,safety_operator_id,operator_gate_receipt_sha256,status,failure_code,
protocol_complete,effective_for_protocol,gate_passed,reason_codes,journal_event_id,
changeover_result_commit_sha256,changeover_marker_ack_sha256,
changeover_checkpoint_commit_sha256
```

`changeover_kind ∈ {APPLY,RESTORE,RECOVER_NOMINAL}`、`action ∈ {apply,restore}`；
`changeover_uid` 是 attempt UID，在 delivery 内全局唯一。它不含
`scientific_unit_id/unit_type/attempt_role/selected_for_export`，不进入 10,800 primary
或 480 initial planned sentinel 计数。每个 evidence bundle 只能绑定一个
`changeover_uid`，并必须与 append-only journal marker 回链。

planned APPLY/RESTORE unit 与 attempt UID、补偿 RECOVER_NOMINAL unit、递增 index、
retry/parent link 的唯一格式按实现指南 §16.6。`status ∈
{complete,technical_abort,safety_abort}`；只有完整 pre/actuate/postcheck 才可
`protocol_complete=true`；所有 technical/safety failure（gate 前后均同）固定
`protocol_complete=false,effective_for_protocol=false`，但仍须完成三段 durable
changeover commit并转入 recovery cursor。每个 planned unit 的第一个 complete attempt 恰有一行
`effective_for_protocol=true`；失败 attempts 与所有 compensating recovery rows 均为
false。RECOVER_NOMINAL complete 后必须重做原 planned unit，不能用 recovery row 冒充
planned APPLY/RESTORE。APPLY failure 恢复 nominal 后从 normal precheck 重做 APPLY；
RESTORE failure 恢复 nominal 后，原 RESTORE 以递增 attempt index、linked recovery evidence
执行一次双人批准的 idempotent restore/no-op 与 postcheck，complete 后才可成为 planned
RESTORE 的 effective row。它不得再次要求 shifted precheck，也不得把 recovery row 自身
标 effective。manifest 分别报告 planned changeover units、actual changeover
attempts、activated recovery units 和 failed attempts。

nullable/phase 规则必须由 schema 条件验证：在 operator gate **之前**的 precheck/evidence
失败允许 `operator_id,safety_operator_id,operator_gate_receipt_sha256=null`，此时只允许
`status=technical_abort|safety_abort,gate_passed=false,protocol_complete=false,
effective_for_protocol=false`；一旦 gate 已签出，三个字段全部 required、两个人员 ID
不同，receipt 必须反向绑定同一 changeover identity 和 pre-evidence hash。任何
`status=complete` 行必须 `gate_passed=true` 且三字段 non-null。pre-evidence 在尚未成功
采集即失败时可 null；post-evidence 仅完整 postcheck 后 non-null；R1 的 transform
readback 在 actuation 已发生后 required，R2–R4 按 actuator schema 条件 required/null，
不能填假 hash。failure 行 `failure_code/reason_codes` required，complete 行 failure null。

三条 commit hash 分别对应实现指南 §16.6 的 durable result、marker ack、protocol
checkpoint；complete 或 failure 的每一行在最终 delivery 中都必须三者 non-null。
gate 前/中途失败同样走完整 transaction；marker/checkpoint 若因 crash 暂缺，由 resume
补齐后 exporter 才可出最终表。delivery validator 不接受“receipt 文件存在但 result
commit 缺失”，也不从空 operator 字段推断匿名批准。

### 12.10 `safety_events.csv`

```text
event_id,identity_kind,dataset_role,attempt_role,run_id,session_id,block_id,method_id,shift_id,
map_id,scientific_unit_id,unit_type,trial_or_episode_id,attempt_uid,attempt_index,
retry_of_attempt_uid,selected_for_export,protocol_complete,valid,invalid_reason,
observation_available,observation_valid,prediction_available,
decision_available,zero_publish_available,event_timestamp_ns,event_source,boot_id,event_type,reason_codes,decision_timestamp_ns,
zero_command_timestamp_ns,zero_command_latency_ms,measured_stop_timestamp_ns,
physical_stop_latency_ms,manual_estop,collision,online_serious_safety_event,
serious_safety_event,safety_review_commit_sha256,operator_confirmation,
bag_ref,video_ref,notes
```

`identity_kind ∈ {attempt,run_level}`。run-level facility/preflight event 只要求
`event_id,dataset_role,run_id,event timestamps/source/type/reasons` 及适用 stop/review evidence；
`attempt_role,session/block/method/shift/map/scientific_unit/unit_type/
trial_or_episode_id/attempt_uid/attempt_index/retry_of_attempt_uid` 和 attempt-derived
selection/protocol/valid/invalid flags 全部为空，不写字符串 `NOT_APPLICABLE`，尤其不得向
integer `attempt_index` 塞字符串。attempt row 的上述字段全部 required且按 applicability
使用 `NOT_APPLICABLE`。schema 用 identity_kind conditional branch，不能伪造 UID。

`decision_available` 和 `zero_publish_available` 对 attempt/run-level 两个分支都是 non-null
boolean，逐位来自 `SafetyEvent.msg` 的同名字段，不允许 exporter 根据结果补写。flag 为 false
时对应 timestamp 和 `zero_command_latency_ms` 必须为 null；`decision_available=true` 时
`decision_timestamp_ns` 必须 non-null；`zero_publish_available=true` 时
`zero_command_timestamp_ns` 必须 non-null。只有两个 flag 都为 true 时 latency 才 non-null，且
精确等于 `(zero_command_timestamp_ns-decision_timestamp_ns)/1e6`、必须 ≥0。
`zero_publish_available=true` 蕴含 `decision_available=true`；反向不强制，因为
`decision=true,zero=false` 必须能忠实表示“已作 stop 决策但零命令没有成功发布”的真实安全失败。
此时 reason 必须含 `ZERO_PUBLISH_MISSING`、`online_serious_safety_event=true`，并按 §15.3
自动 NO-GO，不能被空集 fallback 掩盖。对冻结 safety/technical stop 类型，decision flag
必须 true；false 是完整性失败。wire 中 flag=false 时占位的 uint64 `0` 在 export 必须转 null，
不能把 epoch 0 当真实时间。run-level 事件采用完全相同的 flag/timestamp 条件，不因没有
attempt UID 而豁免。

`event_source,boot_id,event_type` 全部 non-null并逐位来自 wire；source/type枚举和
timing-required 笛卡尔集合唯一采用实现指南 §7.2。所有 monotonic timing 必须属于该
`boot_id`；exporter不得根据 reason code猜 source，也不得用 receive-process UUID替代 supervisor
boot。CSV 中未知 source/type、空 boot或跨 boot时间链均为完整性失败。

`online_serious_safety_event` 来自实时 watchdog/session；`serious_safety_event` 精确等于
online 值 OR 下述 blind review verdict。每个 safety abort/collision/E-stop/person-contact
候选都必须有 non-null `safety_review_commit_sha256`，普通 non-safety row 可空；offline
review 不能把 online true 降为 false，也不能改变 retry/selection。

#### 12.10.1 `safety_review_index.csv`

```text
review_id,identity_kind,run_id,safety_event_id,run_level_journal_event_sha256,
scientific_unit_id,attempt_uid,physical_commit_sha256,scientific_commit_sha256,
review_token,blinded_bundle_sha256,blind_decision_sha256,blind_review_receipt_sha256,
approval_request_sha256,reviewer_approval_sha256,safety_reviewer_approval_sha256,
custodian_link_sha256,
online_serious_safety_event,reviewer_id,
safety_reviewer_id,method_and_metric_blinding_attested,criteria_path,
criteria_sha256,video_uri,video_sha256,video_start_ns,video_end_ns,
sensor_evidence_sha256,contact_evidence_sha256,geometry_evidence_sha256,
review_verdict_serious,verdict_reason_codes,reviewed_utc,
previous_safety_review_sha256,safety_review_sha256,safety_review_commit_sha256
```

规则以实现指南 §17.7 为准。collision 的 video/sensor/geometry hash 全 required；其他
safety event 依 criteria conditional required。两 reviewer 不同，blinding 必须 true；
两 approval的共同 subject必须等于 `blind_decision_sha256`，且 decision逐 hash绑定 bundle、
verdict和reasons；
一条 attempt 最多一个 effective review。缺行、hash/commit断链或 verdict矛盾使 delivery
失败，不允许为得到 serious=0 而挑选 review。
attempt review 要求四个 attempt/scientific链接且 run-level hash为空；run-level review
要求 safety event/journal hash且 attempt字段为空，不能伪造 PREPARED boundary。

### 12.11 其余必需索引表

`posterior_index.csv`：

```text
dataset_role,run_id,session_id,block_id,shift_id,map_id,method_id,
posterior_version,posterior_transition_kind,posterior_transition_factor,
created_timestamp_ns,source_scientific_unit_id,
source_unit_type,source_attempt_uid,source_attempt_index,
source_selected_for_export,source_protocol_complete,valid,invalid_reason,
source_observation_available,source_observation_valid,
transition_source_trial_id,feature_set,prior_scale,mean_shape,covariance_shape,
noise_variance_json,snapshot_path,snapshot_sha256,planner_config_sha256,
validation_leakage_check
```

`posterior_version=0` 是 initial prior，kind=`INITIAL`、factor为空，所有 `source_*` 和
`transition_source_trial_id` 为空，`valid=true,invalid_reason` 为空且
`validation_leakage_check=true`；其余 row 的 kind 只允许
`MODEL_UPDATE|ALARM_INFLATION` 且 source provenance required。前者 factor为空；后者
factor恰为 `8.0`。ordinary validation/monitor/NAV 的 `NONE` transition 不创建新的
posterior_index row。

`state_machine_trace.csv`：

```text
dataset_role,attempt_role,run_id,session_id,block_id,shift_id,map_id,method_id,
scientific_unit_id,unit_type,attempt_uid,attempt_index,retry_of_attempt_uid,
selected_for_export,protocol_complete,valid,invalid_reason,
observation_available,observation_valid,prediction_available,transition_index,
timestamp_ns,previous_state,event,next_state,transition_legal,reason_code,
posterior_version,trial_or_episode_id,safety_latched,operator_action
```

`time_sync_diagnostics.csv`：

```text
dataset_role,run_id,session_id,diagnostic_index,timestamp_ns,clock_source,
peer_or_sensor_id,offset_ms,jitter_ms,round_trip_ms,sync_locked,
source_timestamp_valid,diagnostic_source,valid,invalid_reason
```

`delivery_manifest.json` 至少包含：

- dataset title、protocol version、`dataset_role` 枚举和 attempt-role 计数；
- source commit、container digest、全部 config/schedule/map/command hashes；
- robot/session/block/method/map/shift/scientific-unit 的期望和实际计数；planned counts
  必须按 role：DEV 为 NAV `510/320/80`、SHIFT `60/2700/120`，CONFIRM 为 NAV
  `3060/1920/480`、SHIFT `240/10800/480`；sentinel 必须分开报告 role 对应的
  `initial_planned_units`、activated conditional sets/units 与 actual attempts；
- primary/RERUN_TECH、protocol-complete、selected、valid/invalid 的交叉计数；
- planned APPLY/RESTORE units、actual changeover attempts、activated RECOVER_NOMINAL units、
  failed/effective counts、唯一 UID 与 evidence-bundle hash 覆盖率；
- raw、exported、posterior、video、reference 文件计数和总字节数；
- 技术无效、算法失败、安全 abort、collision、serious event 计数；
- 生成时间、生成工具版本和生成者；
- checksums 文件名；不得把 manifest 中自报的 `GO` 当验收结论。

### 12.12 唯一键、map applicability 和 nullable 规则

#### 12.12.1 主键和 selection 约束

```text
session_metadata: (dataset_role, run_id, session_id)
block_schedule_executed: (dataset_role, run_id, block_id, shift_id, schedule_id)
attempt_ledger: (attempt_uid)
attempt_chain: UNIQUE(dataset_role, scientific_unit_id, attempt_index)
selected_primary_ledger: UNIQUE(dataset_role, scientific_unit_id)
                  WHERE selected_for_export=true
calibration_samples: (attempt_uid, phase, sample_index)
calibration/validation_trials: (attempt_uid)
planner_candidates: (attempt_uid, planner_step, candidate_rank)
navigation_trace: (attempt_uid, sample_index)
episode_metrics: (attempt_uid)
shift_monitor: (attempt_uid)
shift_recovery: (attempt_uid)
restore_sentinel: (attempt_uid)
changeover_evidence_index: (changeover_uid)
safety_events: (event_id)
posterior_index: (dataset_role, run_id, block_id, shift_id, method_id,
                  posterior_version)
state_machine_trace: (attempt_uid, transition_index)
time_sync_diagnostics: (dataset_role, run_id, session_id, diagnostic_index,
                        peer_or_sensor_id)
```

`attempt_uid` 的全局唯一性和上述 row PK 都必须检查。delivery 完整时，每个
schedule 中的 planned primary `scientific_unit_id` 必须恰有一个 selected attempt；
不能用全局唯一 attempt UID 掩盖重复执行同一 planned unit。所有 attempt-bound
派生表的 identity/selection/protocol/valid flags 必须与 ledger 精确相等。

#### 12.12.2 `map_id` / `shift_id` applicability

| unit/table | `map_id` | `shift_id` |
|---|---|---|
| NAV calibration、validation、其 planner candidates | `NOT_APPLICABLE` | `NOT_APPLICABLE` |
| NAV posterior_index（两图共享同一 posterior） | `NOT_APPLICABLE` | `NOT_APPLICABLE` |
| NAV episode、navigation trace、episode metrics | `real_offset_slalom` 或 `real_weighted_arc` | `NOT_APPLICABLE` |
| 全部 SHIFT primary、sentinel、posterior | `NOT_APPLICABLE` | 四个冻结 shift ID 之一 |
| context return | 只有 NAV episode start return 写该 episode 的真实 map；其余一律 `NOT_APPLICABLE` | 按所在协议填写或 `NOT_APPLICABLE` |

禁止把 NAV calibration/validation/posterior 复制成两图各一份，也禁止任意绑定到
其中一图；它们每个 block×method 只存在一次。字符串 `NOT_APPLICABLE` 是显式
非适用值，不是 missing。

#### 12.12.3 conditional nullability

CSV missing 只编码为空 field，读入后为 `None`；禁止文字
`NaN,+Inf,-Inf,null,unknown`。非空数值一律 finite。除下表外不得为空：

| 字段 | 允许空的唯一条件 |
|---|---|
| safety_events 的 attempt-bound identity/flags | `identity_kind=run_level`；attempt 时 required |
| `retry_of_attempt_uid,retry_request_uuid` | `attempt_role=PRIMARY`；RERUN_TECH 时二者 required |
| `technical_failure_code` | terminal 非 §14.2 allowlist technical；allowlist technical 时 required；`OPERATOR_CANCELLED/UNCLASSIFIED_INTERNAL_FAULT` 必须为空并由 terminal reason 表示 |
| `physical_technical_failure_code` | physical terminal 非 §14.2 allowlist technical；physical technical 时 required；不得复制 scientific-stage code 冒充 physical fault |
| `algorithm_outcome` | `protocol_complete=false`；protocol-complete 时 required |
| `invalid_reason` | `valid=true`；`valid=false` 时 required 且来自冻结词表 |
| `approved_deviation_reason` | `deviation=false`；deviation=true 时 required 且必须有批准记录 |
| `operator_notes,notes` | 没有补充说明；不得用它代替结构化 failure/reason code |
| `retry_of_changeover_uid` | `changeover_attempt_index=1`；index>1 时必须指同 unit 前一 attempt |
| `parent_changeover_uid` | planned APPLY/RESTORE 时为空；RECOVER_NOMINAL 时 required 且指失败 planned attempt |
| changeover `failure_code` | `status=complete`；abort 时 required 且来自冻结 technical/safety 词表 |
| changeover `operator_id,safety_operator_id,operator_gate_receipt_sha256` | 仅 authorize gate 前的 precheck/evidence abort；此时 `gate_passed=false`；gate 后及 complete 全部 required |
| changeover `pre_evidence_bundle_sha256,post_evidence_bundle_sha256,effective_monotonic_ns` | attempt 在相应 phase 前 abort；`status=complete` 时全部 required |
| changeover `transform_readback_sha256` | R2–R4 不使用 software transform，或 R1 在 actuation 前 abort；R1 actuation 后 required |
| changeover `transform_activation_record_sha256` | R2–R4，或 R1 在 SetCommandTransform durable transition 前 abort；R1 actuation 后 required并回链 relay supervisor state |
| ACK 数值/时间 | `ack_available=false` |
| measured/covariance | `observation_available=false`，或 available但 invalid且无法构造数值estimate |
| `observation_valid` | `observation_available=false`；available=true时 required bool |
| predicted | `prediction_available=false`；该 flag独立于 observation/scientific valid |
| `abort_reason` | `aborted=false`；aborted=true 时 required |
| NAV `arrival_*`/arrival time | `success=false` |
| NAV final pose/path length | technical reference loss 使其无法复算；此时 `valid=false`、invalid reason 和 timeout-coded completion required |
| `detection_delay_trials` | 除首次有效 post-shift alarm 行外；sequence-level analyzer 对 pre-alarm/miss/invalid evidence机械赋 penalty 6 |
| residual、monitor NIS/CUSUM | `prediction_available=false` 或没有 available+valid observation |
| recovery `rolling_rmse` | `phase=recovery`；validation行始终按最近scheduled slots的q公式计算，invalid slot贡献`0.25²`而非留空/整窗强制0.25 |
| recovery `target_rmse` | 仅 `phase=recovery` motion 行；每个 validation 行即使 pre-monitor 有 invalid 也按 penalty q 确定性计算并 non-null，但该 sequence 固定 `recovered=false` |
| posterior `source_*`/`transition_source_trial_id` | 仅 `posterior_version=0` initial prior |
| `posterior_transition_factor` | `posterior_transition_kind=NONE|MODEL_UPDATE|INITIAL`；只有 `ALARM_INFLATION` 时 required 且精确为 `8.0` |
| `operator_action` | 自动 state transition，无人工动作 |
| `round_trip_ms` | 冻结 topic contract 声明该 sensor/peer 只有单向时钟诊断 |
| safety stop/ACK 时间与 latency | 对应 ACK/reference 通道按冻结合同不可用；event 必须 `valid=false` 并给 reason |
| `safety_review_commit_sha256` | 非 safety/collision/E-stop/person-contact candidate；required candidate 不允许为空 |
| video path | 协议明确不要求视频的 non-navigation DEV attempt |

identity、key、attempt/status/terminal reason、布尔 flag、适用的 raw reference 和
non-null reason code 永不为空。`pre_measure_abort` 可只出现在 ledger，不伪造
measurement row。JSON Schema 必须对 `attempt_role/status/phase/success/valid/
ack_available/deviation/posterior_version` 实现条件分支；不得用全表
`dropna()`、默认零或字符串 sentinel 偷渡 missing。

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
- 每个 sample key `(attempt_uid, sample_index)` 唯一；
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

### 14.1 先分开“机器人如何停”和“该数据能否排除”

紧急 zero、disarm 或 latch 是实时安全反应；`protocol_complete`、预算消耗和是否
允许技术重采是科学分类。两者不得混为一谈：通信、reference、recorder 或进程故障
也必须立即 zero，但仍可属于客观技术无效；反过来，算法 safety abort 即使运动很短，
仍是 protocol-complete 科学失败，必须消耗预算且不可重采。

实时分类只依赖冻结 fault code、发生状态和时间戳，不读取 RMSE、success、方法排名
或统计 gate。若同 tick 有多个事件，NAV 终止优先级仍为
`SAFETY_ABORT > COLLISION > TECH_ABORT > SUCCESS > TIMEOUT`；安全/碰撞证据不能被
同时发生的技术故障覆盖。任何未知 code 都先 fail closed、zero/disarm、退出 5，
但在协议修订和独立批准前 **不具备** RERUN_TECH 资格。

### 14.2 冻结 fault code 词表

以下 code 可作为客观 technical failure；原 attempt、raw、journal、视频和 ledger
全部保留：

```text
RECORDER_NOT_STARTED
RECORDER_NOT_READY
BAG_CORRUPT
REFERENCE_DROPOUT
REFERENCE_FRAME_JUMP
REFERENCE_STALE
REFERENCE_INVALID
TIME_SYNC_UNLOCKED
CROSS_STREAM_SKEW
CONFIG_OR_SCHEDULE_MISMATCH
EXTERNAL_NETWORK_OR_POWER
NETWORK_FAULT
RUNNER_HEARTBEAT_STALE
COMMAND_LEASE_EXPIRED
COMMAND_SEQUENCE_INVALID
ACK_STALE
STATE_STALE
STATE_NONFINITE
START_POSE_DRIFT_AFTER_PRECHECK
IMU_OR_HEIGHT_STALE
BMS_STALE
CONTROL_MODE_MISMATCH
GAIT_MISMATCH
MULTIPLE_VENDOR_COMMAND_PUBLISHERS
SOFTWARE_PROCESS_CRASH
STORAGE_IO_FAILURE
UNPLANNED_HUMAN_ENTRY
MARKER_UNRECOVERABLE
FACILITY_INTERRUPTION
```

以下 watchdog/physical code 是 safety outcome code，不是技术排除 code：

```text
LOW_BATTERY
MOTOR_FAULT
MOTOR_TEMPERATURE_LIMIT
PHYSICAL_ESTOP
ROLL_LIMIT
PITCH_LIMIT
BASE_HEIGHT_LIMIT
WORKSPACE_LIMIT
WIRE_COMMAND_OUT_OF_ENVELOPE
FINAL_ZERO_NOT_CONFIRMED
COLLISION
ALGORITHM_SAFETY_ABORT
```

`UNCLASSIFIED_INTERNAL_FAULT` 是 fail-closed execution-control terminal，不属于上述
technical allowlist 或 safety outcome。它只用于未匹配 typed fault 的程序异常：立即
zero→`TECH_ABORT_DISARMED`，`protocol_complete=false,retry_permitted=false`，暂停该 run
供 protocol review；不得把任意 exception 自动伪成 `SOFTWARE_PROCESS_CRASH`。

若 E-stop 是对 `UNPLANNED_HUMAN_ENTRY` 或有时间戳的 facility interruption 的响应，
primary classification 取已先发生的 technical trigger，event log 仍记录
`PHYSICAL_ESTOP`。没有该客观先行 trigger 时，`PHYSICAL_ESTOP` 一律按 safety outcome，
operator 不得事后改成技术故障。新增或合并 code 必须在看 CONFIRM outcome 前由数据
负责人、独立审计者和安全负责人批准，更新 protocol version/JSON Schema，并写入
`deviations.md`；禁止 `POOR_RESULT`、`HIGH_RMSE` 或同义 code。

### 14.3 穷尽 fault/outcome → response/selection 矩阵

| fault/outcome 和发生条件 | watchdog 即时响应/终态 | ledger `status` / `terminal_reason` | `protocol_complete` | primary budget | 是否允许 RERUN_TECH | CLI exit |
|---|---|---|---:|---:|---|---:|
| config/schema/hash/schedule mismatch，在实现指南定义的 `PREPARED_ATTEMPT` durable boundary 前 | 拒绝 arm，保持 `DISARMED` | 只写 run-level preparation event，不创建 attempt | false | 不消耗 | 修复为原冻结 bytes 后执行原 PRIMARY | 2 |
| 任一 readiness code 在 durable boundary 前：`RECORDER_NOT_STARTED/NOT_READY, REFERENCE_DROPOUT/STALE/INVALID, TIME_SYNC_UNLOCKED, CROSS_STREAM_SKEW, STATE_STALE/NONFINITE, IMU_OR_HEIGHT_STALE, BMS_STALE, CONTROL_MODE_MISMATCH, GAIT_MISMATCH, ACK_STALE, NETWORK_FAULT, MULTIPLE_VENDOR_COMMAND_PUBLISHERS, LOW_BATTERY` | 拒绝 arm；safety code 仍按安全规则 zero/latch | 只写 identity=`NOT_APPLICABLE` 的 run-level preparation/safety event，不创建 attempt | false | 不消耗 | 修复后原 PRIMARY 仍 pending | 3（safety latch 为 4） |
| 已跨 durable boundary、尚未运动时出现 config 或 §14.2 technical code | zero，保持/回到 `DISARMED` | `pre_measure_abort / exact_code` | false | 不消耗 | 是；同 unit 新 UID/index，显式 RERUN_TECH | 2/3/5 |
| runtime infrastructure code：`RECORDER_NOT_STARTED/NOT_READY, REFERENCE_DROPOUT/FRAME_JUMP/STALE/INVALID, TIME_SYNC_UNLOCKED, CROSS_STREAM_SKEW, EXTERNAL_NETWORK_OR_POWER, NETWORK_FAULT, RUNNER_HEARTBEAT_STALE, COMMAND_LEASE_EXPIRED, COMMAND_SEQUENCE_INVALID, ACK_STALE, STATE_STALE/NONFINITE, IMU_OR_HEIGHT_STALE, BMS_STALE, CONTROL_MODE_MISMATCH, GAIT_MISMATCH, MULTIPLE_VENDOR_COMMAND_PUBLISHERS, SOFTWARE_PROCESS_CRASH, STORAGE_IO_FAILURE, UNPLANNED_HUMAN_ENTRY, FACILITY_INTERRUPTION` | high-priority zero；运动中到 `TECH_ABORT_DISARMED`，未运动则 `DISARMED` | measure 前 `pre_measure_abort`，否则 `technical_abort`；terminal 保留 exact code | false | 不消耗 | 是；同 dataset/estimand/unit，新 UID/index，链到上一 attempt；禁止自动 retry | 5 |
| 未匹配 typed fault 的 `UNCLASSIFIED_INTERNAL_FAULT` | high-priority zero→`TECH_ABORT_DISARMED` | `pre_measure_abort|technical_abort / UNCLASSIFIED_INTERNAL_FAULT` | false | 不消耗 | 否；暂停 run，修复后按 deviation 新开 run | 5 |
| `BAG_CORRUPT, MARKER_UNRECOVERABLE, STORAGE_IO_FAILURE` 在 `SCIENTIFIC_UNIT_COMMIT` 前同步发现 | zero/`TECH_ABORT_DISARMED` | 初次 immutable scientific result 写 `technical_abort / exact_code` | false | 不消耗 | 是；显式 RERUN_TECH | 5 |
| 同一 integrity 问题在 `SCIENTIFIC_UNIT_COMMIT` 后才发现 | 机器人已 `DISARMED`；不重放该 unit | 原 physical/scientific commit 不改写；delivery deviation 标记 affected block/sequence unusable | 保持原 immutable 值 | 不事后重算 | 否；可无歧义修复 raw 时交付修复派生物与完整 provenance，否则新 run 重采整个 affected block/sequence | 6 |
| durable boundary 后任意 runtime safety code（即使尚未 arm/运动）：`LOW_BATTERY, MOTOR_FAULT, MOTOR_TEMPERATURE_LIMIT, PHYSICAL_ESTOP, ROLL_LIMIT, PITCH_LIMIT, BASE_HEIGHT_LIMIT, WORKSPACE_LIMIT, WIRE_COMMAND_OUT_OF_ENVELOPE` | high-priority zero → `SAFETY_ABORT_LATCHED`；仅双人显式 reset | `safety_abort / exact_code` | true | 消耗 | 否 | 4 |
| `FINAL_ZERO_NOT_CONFIRMED` 或无法确认物理停止 | 重复 high-priority zero/批准 safe mode → latch；serious candidate | `safety_abort / FINAL_ZERO_NOT_CONFIRMED` | true | 消耗 | 否 | 4 |
| `ALGORITHM_SAFETY_ABORT`，包括全 candidate 被冻结 safety 拒绝 | zero → latch；不得改写成技术故障 | `safety_abort / ALGORITHM_SAFETY_ABORT` | true | 消耗 | 否 | 4 |
| `COLLISION`，即使同 tick 还有 reference/network fault | zero → latch，保留 contact/视频证据 | `safety_abort / COLLISION`，`collision=true` | true | 消耗 | 否 | 4 |
| NAV `TIMEOUT`/未到达；或普通 trial 完成 | zero + stationary → `DISARMED` | `timeout / TIMEOUT` 或 `complete / TRIAL_COMPLETE` | true | 消耗 | 否 | 0 |
| protocol-complete invalid observation、低 sample/steady ratio、command deviation 超线 | 正常 zero；不更新 model | `complete / INVALID_OBSERVATION`，`valid=false`+exact invalid reason | true | 消耗 | 否 | 0 |
| missed detection、false alarm、slow/no recovery、高/penalty RMSE、B8 输给 baseline | 正常执行完整冻结 sequence | `complete / exact algorithm_outcome` | true | 消耗 | 否 | 0 |
| nominal-restore sentinel set 不通过 | zero、`DISARMED`，禁止下一 method | 两条均 `complete`；`set_passed=false` | true | 不进入 primary budget | 不是 primary RERUN_TECH；修复 context 后按 9.4 重做完整新 verification set | 3 |

`context_return` 是 auxiliary unit，继承上表的实时 fault response，但任何结果都不改变
primary planned unit 的 budget/selection。发生 safety fault 时仍必须 latch 和退出 4。

### 14.4 技术重采与机械选择

RERUN_TECH 必须同时满足：上一 attempt `protocol_complete=false`、failure code 在
14.2 technical 词表、raw/journal 可回链、`retry_of_attempt_uid` 指向紧邻上一
attempt、request UUID 未使用、且该 `scientific_unit_id` 尚无 protocol-complete
attempt。dataset role、run/block/method/map/shift、unit type 和 planned command/
waypoint 全部不变。operator 必须显式执行 retry CLI；backend 不自动重试。
已经存在 hash-valid `SCIENTIFIC_UNIT_COMMIT(protocol_complete=true)` 的 attempt 不得通过
append-only note/adjudication 覆写为 technical retry eligibility；post-commit integrity
failure 按上表令 affected block/sequence 不可用，避免 calibration posterior 已影响后续
unit 后只局部重采造成时序和模型 lineage 不可比。

每个 planned primary scientific unit 的第一个 protocol-complete attempt 机械设为
`selected_for_export=true`；valid 或算法表现不影响选择。此前 technical attempts
保持 false 但全部交付。若第一个 protocol-complete attempt 是 invalid、timeout、
safety abort、collision、miss/recovery failure，它仍被选择并消耗预算；禁止第 2 次
“为了得到有效/更好结果”重采。一个 unit 若始终没有 protocol-complete attempt，
delivery 为 incomplete，不能通过 cardinality gate。

### 14.5 不可因结果重采

RMSE 高、active 选到表现不佳但安全的命令、invalid observation、false alarm、
未检测 shift、恢复慢/未恢复、timeout、算法 safety abort、碰撞、路径长和 B8 输给
baseline 都是预注册 outcome。不得把它们映射到 technical code，也不得以换电、
重定位或“再试一次确认”为理由覆盖。

### 14.6 样本量规则

- Gate D 的 DEV pilot 预先计划 NAV 5 个完整 paired blocks、每个 SHIFT cell 5 个完整
  paired blocks；每个功效 cell 的 `pilot_n` 必须恰为 5；
- P8-NAV 预先计划 30 个完整 paired blocks；
- P8-SHIFT 每个 shift 预先计划 20 个完整 paired blocks；
- 技术无效只沿同 `scientific_unit_id` attempt chain 补齐，不新造独立 n；若故障影响
  整个 block，其所有受影响 units 分别保留 retry chain；
- 不根据 p-value、效果大小或“看起来已经够好”提前停止；
- 若误建额外 planned block，必须作为 deviation 报告；在预注册规则决定纳入前不得
  挑选其结果，且不能替代较差的原 block；
- confirmatory 数据开始后不得降低 n。

上面第一项是独立 DEV 计划，后两项是独立 CONFIRM 计划。两个 run ID、release、schedule、
input lock 和 block-ID namespace 必须不同；`5+30` 不得报成 NAV `n=35`，`5+20`
不得报成任一 SHIFT `n=25`。

---

## 15. 预注册统计分析和发表门槛

### 15.1 通用

本节是 `protocol/analysis_plan.yaml` 的机器权威。文件必须通过
strict `p8.analysis-plan.v1` schema：下方每个 mapping 显示的 key 全部
required，每一层都是 `additionalProperties=false`；列表顺序、值和大小写
全部冻结且 `uniqueItems=true`。除两个 64-hex provenance hash 外，不得用
现场数据填充任何字段；不得接受旧的 flat aliases，例如
`bootstrap_replicates` 或 `bootstrap_seeds`。

```yaml
schema_version: p8.analysis-plan.v1
protocol_version: p8.go2.real.v1

estimands:
  hypothesis_id_separator: "::"
  hypothesis_id_templates:
    nav_map: "P8NAV::<map_id>::<endpoint_key>"
    nav_comparison: "P8NAV::<map_id>::<endpoint_key>::<comparison_id>"
    nav_method: "P8NAV::GLOBAL::<endpoint_key>::<method_id>"
    shift: "P8SHIFT::<shift_id>::<endpoint_key>"
    shift_method: "P8SHIFT::<shift_id>::<endpoint_key>::<method_id>"
    global: "P8GLOBAL::<endpoint_key>"
  global_endpoint_formulas:
    nav_map_coverage: "count(map_id with exactly 30 complete paired blocks)"
    nav_paired_blocks_per_map: "min(count(complete distinct block_id) grouped by required map_id)"
    nav_B8_over_B1_calibration_budget: "planned_calibration_units_B8_full/planned_calibration_units_B1_dense"
    shift_coverage: "count(shift_id with exactly 20 complete frozen-passive-full paired blocks)"
    shift_paired_blocks_per_shift: "min(count(complete distinct block_id) grouped by required shift_id)"
    serious_safety_events: "count(distinct event_id where serious_safety_event=true)"
    software_zero_command_latency_ms: "safety_latency.max_latency_ms; Gate-C fallback only when timing_required_event_count=0"
    gate_d_min_power: "min(conservative marginal power over the 22 preregistered continuous readiness cells)"
    gate_d_discrete_design_ready: "all 62 preregistered exact-attainability/resolution checks pass"
  nav_map_endpoint_keys:
    - b8_success_point
    - b8_success_cp_lower
    - b8_collision_point
    - b8_collision_cp_upper
    - time_improvement_B0_ci_lower
    - win_rate_B0
  nav_comparison_endpoint_keys:
    success_NI_ci_lower: [B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random]
    collision_NI_ci_lower: [B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random]
    time_ratio_ci_upper: [B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random]
  nav_method_endpoint_keys:
    valid_calibration_ratio: [B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random, B8_full]
  shift_endpoint_keys:
    - false_alarm_point
    - detection_rate
    - recovery_rate
    - detection_delay_median
    - detection_delay_p95
    - recovery_trials_median
    - recovery_trials_p95
    - passive_minus_full_early_rmse_ci_lower
    - passive_greater_full_early_rmse_wilcoxon_p
    - full_terminal_rmse_ci_upper
  shift_method_endpoint_keys:
    valid_observation_ratio: [frozen, passive, full]
  global_endpoint_keys:
    - nav_map_coverage
    - nav_paired_blocks_per_map
    - nav_B8_over_B1_calibration_budget
    - shift_coverage
    - shift_paired_blocks_per_shift
    - serious_safety_events
    - software_zero_command_latency_ms
    - gate_d_min_power
    - gate_d_discrete_design_ready
  expected_primary_hypothesis_id_count: 116
  expected_secondary_hypothesis_id_count: 142
  expected_total_hypothesis_id_count: 258

primary_gates:
  decision_rule: CONJUNCTIVE_INTERSECTION_UNION_ALL_REQUIRED
  nav:
    scope: PER_MAP_CONJUNCTIVE
    per_map_gate_keys: [b8_success_point, b8_success_cp_lower, b8_collision_point, b8_collision_cp_upper, time_improvement_B0_ci_lower, win_rate_B0, success_NI_ci_lower, collision_NI_ci_lower, time_ratio_ci_upper]
    global_gate_keys: [nav_map_coverage, nav_paired_blocks_per_map, nav_B8_over_B1_calibration_budget, valid_calibration_ratio]
    required_map_ids: [real_offset_slalom, real_weighted_arc]
    map_coverage_required: 2
    paired_blocks_per_map_min: 30
    b8_success_point_min: 0.90
    b8_success_cp_lower_min: 0.80
    b8_collision_point_max: 0.05
    b8_collision_cp_upper_max: 0.15
    time_improvement_B0_ci_lower_strict_min_s: 0.0
    win_rate_B0_min: 0.80
    success_NI_ci_lower_min: -0.10
    collision_NI_ci_lower_min: -0.10
    time_ratio_ci_upper_max: 1.25
    calibration_budget_B8_over_B1_max: 0.40
    valid_calibration_ratio_min: 0.90
  shift:
    scope: PER_SHIFT_CONJUNCTIVE
    per_shift_gate_keys: [false_alarm_point, detection_rate, recovery_rate, detection_delay_median, detection_delay_p95, recovery_trials_median, recovery_trials_p95, passive_minus_full_early_rmse_ci_lower, passive_greater_full_early_rmse_wilcoxon_p, full_terminal_rmse_ci_upper]
    global_gate_keys: [shift_coverage, shift_paired_blocks_per_shift, valid_observation_ratio]
    required_shift_ids: [R1_command_gain_coupling, R2_payload_com, R3_surface_friction, R4_mixed_context]
    shift_coverage_required: 4
    paired_blocks_per_shift_min: 20
    false_alarm_point_max: 0.05
    detection_rate_min: 0.90
    recovery_rate_min: 0.90
    detection_delay_median_max_trials: 5
    detection_delay_p95_max_trials: 5
    recovery_trials_median_max: 10
    recovery_trials_p95_max: 12
    passive_minus_full_early_rmse_ci_lower_strict_min: 0.0
    passive_greater_full_wilcoxon_p_max: 0.05
    full_terminal_rmse_ci_upper_max_mps_equivalent: 0.14
    valid_observation_ratio_min: 0.85
  global:
    serious_safety_events_max: 0
    software_zero_command_latency_ms_max: 40.0
    gate_d_marginal_cell_power_min: 0.80
    gate_d_discrete_design_ready_required: true

secondary_descriptive:
  gate_status: DESCRIPTIVE_ONLY
  enters_overall_gate: false
  p_adjusted: null
  report_p_raw: true
  median_quantile_method: linear
  p95_quantile_method: higher
  continuous_summaries: [mean_difference, median_difference, percentile_ci_95, win_rate]
  hypothesis_id_templates:
    nav_comparison: "D::P8NAV::<map_id>::<endpoint_key>::<comparison_id>"
    nav_method: "D::P8NAV::<map_id>::<endpoint_key>::<method_id>"
    shift_method: "D::P8SHIFT::<shift_id>::<endpoint_key>::<method_id>"
  nav_comparison_endpoint_keys:
    completion_time_mean_difference: [B0_raw, B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random]
    completion_time_median_difference: [B0_raw, B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random]
    completion_time_win_rate: [B0_raw, B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random]
  nav_method_rate_endpoint_keys:
    success_cp_interval: [B0_raw, B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random, B8_full]
    collision_cp_interval: [B0_raw, B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random, B8_full]
  shift_detector_method_ids: [frozen, passive]
  shift_detector_endpoint_keys: [false_alarm_point, detection_rate, detection_delay_median, detection_delay_p95]
  shift_rate_method_ids: [frozen, passive, full]
  shift_rate_interval_endpoint_keys: [false_alarm_cp_interval, detection_cp_interval, recovery_cp_interval]
  formulas:
    completion_time_mean_difference: "mean(t_baseline-t_B8_full)"
    completion_time_median_difference: "numpy.quantile(t_baseline-t_B8_full,0.5,method='linear')"
    completion_time_win_rate: "mean(I(t_B8_full<t_baseline))"
    success_cp_interval: "clopper_pearson(sum(I(success_method)),30,0.95)"
    collision_cp_interval: "clopper_pearson(sum(I(collision_method)),30,0.95)"
    shift_false_alarm_point: "mean(I(false_alarm_for_gate) over 20 sequences)"
    shift_detection_rate: "mean(I(detected) over 20 sequences)"
    shift_detection_delay_median: "numpy.quantile(20 delay values,0.5,method='linear')"
    shift_detection_delay_p95: "numpy.quantile(20 delay values,0.95,method='higher')"
    shift_rate_cp_interval: "clopper_pearson(sum(binary endpoint),20,0.95)"
  expected_hypothesis_id_count: 142

bootstrap:
  replicates: 10000
  rng_constructor: numpy.random.Generator
  bit_generator: PCG64
  seeds:
    nav: 20260731
    shift:
      R1_command_gain_coupling: 20260741
      R2_payload_com: 20260742
      R3_surface_friction: 20260743
      R4_mixed_context: 20260744
  ci:
    method: percentile
    sides: two_sided
    confidence_level: 0.95
    lower_quantile: 0.025
    upper_quantile: 0.975
    quantile_method: linear
  nav_resampling:
    unit: block_id
    matrix_shape: [10000, 30]
    preserve_within_unit: ALL_8_METHODS_X_2_MAPS
    shared_matrix_for_all_endpoints: true
    pool_maps: false
  shift_resampling:
    unit: block_id
    matrix_shape: [10000, 20]
    preserve_within_unit: FROZEN_PASSIVE_FULL
    shared_matrix_for_all_endpoints: true
    pool_shifts: false

rate_intervals:
  method: clopper_pearson
  sides: two_sided
  confidence_level: 0.95
  alpha: 0.05
  lower_formula: "x==0 ? 0 : scipy.stats.beta.ppf(0.025,x,n-x+1)"
  upper_formula: "x==n ? 1 : scipy.stats.beta.ppf(0.975,x+1,n-x)"
  implementation: src/calibagent/eval/metrics.py::clopper_pearson_interval
  denominator_policy: ALL_PLANNED_PROTOCOL_COMPLETE_BLOCKS

nav:
  map_ids: [real_offset_slalom, real_weighted_arc]
  method_ids: [B0_raw, B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random, B8_full]
  primary_method_id: B8_full
  raw_baseline_id: B0_raw
  dense_baseline_id: B1_dense
  matched_baseline_ids: [B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random]
  calibrated_method_ids: [B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random, B8_full]
  planned_blocks: 30
  timeout_s: 60.0
  formulas:
    b8_success_point: "mean(I(success_B8_full))"
    b8_success_cp_lower: "clopper_pearson_lower(x=sum(I(success_B8_full)),n=30)"
    b8_collision_point: "mean(I(collision_B8_full))"
    b8_collision_cp_upper: "clopper_pearson_upper(x=sum(I(collision_B8_full)),n=30)"
    success_NI: "mean(I(success_B8_full)-I(success_baseline))"
    collision_NI: "mean(I(collision_baseline)-I(collision_B8_full))"
    time_improvement_B0: "mean(t_B0_raw-t_B8_full)"
    time_ratio: "mean(t_B8_full)/mean(t_baseline)"
    win_rate_B0: "mean(I(t_B8_full<t_B0_raw))"
    calibration_budget_B8_over_B1: "planned_calibration_units_B8_full/planned_calibration_units_B1_dense"
    valid_calibration_ratio: "count(selected AND observation_available AND observation_valid)/planned_calibration_units"
  completion_time_failure_encoding: TIMEOUT_CODED_60_S
  time_ratio_aggregation: RATIO_OF_MEANS
  completion_time_tie_win_value: 0
  ni_gate_bound: BOOTSTRAP_LOWER
  time_ratio_gate_bound: BOOTSTRAP_UPPER
  valid_calibration_gate_aggregation: MIN_OVER_7_CALIBRATED_METHODS

shift:
  shift_ids: [R1_command_gain_coupling, R2_payload_com, R3_surface_friction, R4_mixed_context]
  method_ids: [frozen, passive, full]
  frozen_method_id: frozen
  passive_method_id: passive
  primary_method_id: full
  planned_blocks_per_shift: 20
  monitor:
    scheduled_indices: [1, 2, 3, 4, 5, 6, 7, 8, 9]
    pre_indices: [1, 2, 3, 4]
    post_indices: [5, 6, 7, 8, 9]
    evidence_valid_formula: "E_i=selected_for_export AND protocol_complete AND observation_available AND observation_valid AND prediction_available AND finite(normalized_nis,cusum) AND integer(positive_evidence_count)>=0 AND boolean(alarm)"
    observed_pre_alarm_formula: "any(E_i AND alarm_i for i in 1..4)"
    pre_evidence_complete_formula: "all(E_i for i in 1..4)"
    false_alarm_gate_formula: "observed_pre_alarm OR NOT pre_evidence_complete"
    first_post_alarm_formula: "min({i in 5..9 | E_i AND alarm_i}); empty->null"
    post_prefix_valid_formula: "j!=null AND all(E_i for i in 5..j)"
    detected_formula: "pre_evidence_complete AND NOT observed_pre_alarm AND first_post_alarm!=null AND post_prefix_valid(first_post_alarm)"
    outcome_precedence: [PRE_ALARM, INVALID_PRE_EVIDENCE, INVALID_POST_PREFIX_EVIDENCE, MISS, DETECTED]
    detection_delay_formula: "detected ? first_post_alarm-4 : 6"
    detection_delay_penalty_trials: 6
    denominator: 20
  rmse:
    yaw_lever_arm_m: 0.30
    slot_usable_formula: "selected_for_export AND protocol_complete AND observation_available AND observation_valid AND prediction_available AND finite(e_vx,e_vy,e_wz)"
    valid_slot_q_formula: "(e_vx^2+e_vy^2+(0.30*e_wz)^2)/3"
    invalid_slot_residual_mps_equivalent: 0.25
    invalid_slot_q: 0.0625
    rolling_window_slots: 4
    rolling_formula: "sqrt(mean(q[max(1,k-3)..k]))"
    pre_rmse_formula: "sqrt(mean(q_pre_1..q_pre_4))"
    target_formula: "clip(1.30*pre_rmse,0.075,0.140)"
    target_min_mps_equivalent: 0.075
    target_max_mps_equivalent: 0.140
    early_validation_steps: [4, 5, 6, 7, 8, 9]
    terminal_validation_step: 12
    early_rmse_formula: "mean(rolling_rmse_k for k in 4..9)"
    terminal_rmse_formula: "rolling_rmse_12"
    recovered_formula: "pre_evidence_complete AND exists k in 4..12: all 4 validation slots at k-3..k satisfy slot_usable_formula AND rolling_rmse_k<=target"
    recovery_trials_formula: "min(recovered k); empty->13"
    recovery_trials_penalty: 13
    recovery_summary_conditioning: UNCONDITIONAL_ALL_20
  comparisons:
    early_difference_formula: "early_rmse_passive-early_rmse_full"
    early_difference_pairing: SAME_SHIFT_AND_BLOCK
    terminal_full_statistic: "mean(terminal_rmse_full over 20 blocks)"
    wilcoxon_call: "scipy.stats.wilcoxon(passive,full,alternative='greater',zero_method='pratt',method='approx',correction=False)"
  aggregates:
    false_alarm_point: "mean(I(false_alarm_for_gate) over all 20 full sequences)"
    detection_rate: "mean(I(detected) over all 20 full sequences)"
    recovery_rate: "mean(I(recovered) over all 20 full sequences)"
    detection_delay_median: "numpy.quantile(20 delay values,0.5,method='linear')"
    detection_delay_p95: "numpy.quantile(20 delay values,0.95,method='higher')"
    recovery_trials_median: "numpy.quantile(20 recovery values,0.5,method='linear')"
    recovery_trials_p95: "numpy.quantile(20 recovery values,0.95,method='higher')"
    passive_minus_full_early_rmse_ci_lower: "bootstrap_quantile(mean(early_passive-early_full),0.025,method='linear')"
    passive_greater_full_early_rmse_wilcoxon_p: "comparisons.wilcoxon_call.pvalue"
    full_terminal_rmse_ci_upper: "bootstrap_quantile(mean(terminal_rmse_full),0.975,method='linear')"
  valid_observation_ratio:
    numerator: COUNT_SELECTED_PRIMARY_AVAILABLE_AND_VALID_ROWS
    denominator_per_shift_method: 900
    denominator_formula: "20*45"
    sentinel_in_denominator: false
    gate_aggregation: MIN_OVER_4_SHIFTS_X_3_METHODS

missingness:
  delete_protocol_complete_outcomes: false
  interpolate_missing_observations: false
  survivor_only_summaries: false
  nav_failed_completion_time_s: 60.0
  shift_invalid_slot_q: 0.0625
  shift_detection_delay_penalty_trials: 6
  shift_recovery_trials_penalty: 13
  rate_denominator_policy: ALL_20_PLANNED_BLOCKS_PER_CELL
  invalid_pre_monitor_policy: COUNT_AS_FALSE_ALARM_GATE_FAILURE_AND_DETECTION_FAILURE
  invalid_post_before_first_alarm_policy: DETECTION_FAILURE_NO_SKIP_FORWARD
  invalid_post_after_first_valid_alarm_policy: DOES_NOT_REVERSE_DETECTION

power_plan:
  method: preregistered_mixed_readiness_family
  alpha: 0.05
  target_marginal_power: 0.80
  minimum_pilot_n_per_cell: 5
  required_pilot_n_per_cell: 5
  pilot_dataset_role: DEV
  pilot_input_lock_manifest_raw_sha256: "<64-hex DEV pre-lock input-lock raw SHA-256>"
  pilot_cardinality:
    nav_blocks: 5
    shift_blocks_per_shift: 5
    nav_methods: [B0_raw, B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random, B8_full]
    shift_methods: [frozen, passive, full]
  continuous_family:
    method: block_level_noncentral_t_lower_bound_with_sd_upper_95
    expected_cell_count: 22
    map_ids: [real_offset_slalom, real_weighted_arc]
    nav_baseline_ids: [B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random]
    shift_ids: [R1_command_gain_coupling, R2_payload_com, R3_surface_friction, R4_mixed_context]
    cell_order:
      - NAV_TIME_SUPERIORITY_BY_MAP
      - NAV_TIME_RATIO_NI_BY_MAP_THEN_BASELINE
      - SHIFT_EARLY_SUPERIORITY_BY_SHIFT
      - SHIFT_TERMINAL_THRESHOLD_BY_SHIFT
    nav_time_superiority:
      endpoint: time_improvement_B0
      transformed_difference: "t_B0_raw-t_B8_full"
      alternative_margin_distance_absolute: 1.0
      unit: s
      planned_n: 30
    nav_time_ratio_ni:
      endpoint: time_ratio
      transformed_difference: "1.25*t_baseline-t_B8_full"
      alternative_margin_distance_absolute: 1.0
      unit: s
      planned_n: 30
    shift_early_superiority:
      endpoint: passive_minus_full_early_rmse
      transformed_difference: "early_rmse_passive-early_rmse_full"
      alternative_margin_distance_absolute: 0.02
      unit: m/s_equivalent
      planned_n: 20
    shift_terminal_threshold:
      endpoint: full_terminal_rmse
      transformed_difference: "0.14-terminal_rmse_full"
      alternative_margin_distance_absolute: 0.02
      unit: m/s_equivalent
      planned_n: 20
  discrete_family:
    method: exact_attainability_and_lattice_resolution
    expected_check_count: 62
    nav_absolute_rate_checks: [b8_success, b8_collision, win_rate_B0]
    nav_binary_ni_checks: [success_NI, collision_NI]
    nav_binary_ni_baseline_ids: [B1_dense, B2_lhs, B3_sobol, B4_d_opt, B5_active_no_task, B6_random]
    shift_rate_checks: [false_alarm_point, detection_rate, recovery_rate]
    shift_ordinal_checks: [detection_delay_median, detection_delay_p95, recovery_trials_median, recovery_trials_p95]
    shift_signed_rank_checks: [passive_greater_full_early_rmse_wilcoxon_p]
    binomial_rule: "enumerate x=0..planned_n; evaluate every frozen point and Clopper-Pearson gate; passing_counts must be nonempty"
    paired_binary_ni_rule: "lattice_step=1/planned_n; require NI_margin/lattice_step>=3 and an integer acceptance lattice point"
    shift_rate_rule: "enumerate x=0..20 against the frozen point gate; passing_counts must be nonempty"
    shift_ordinal_rule: "enumerate only the queried nondecreasing order-statistic tuples with a feasible length-20 completion on detection support 1..6 or recovery support 4..13; frozen linear/higher quantiles must have a nonempty passing set"
    shift_signed_rank_rule: "evaluate the frozen scipy Wilcoxon call on deterministic differences [1,2,...,20]; finite minimum-attainable p must be <=0.05"
    decision_rule: ALL_62_CHECKS_PASS
  sd_estimator: UNBIASED_SAMPLE_SD_DDOF_1
  sd_upper_confidence_level: 0.95
  sd_upper_formula: "sd_unbiased*sqrt((pilot_n-1)/scipy.stats.chi2.ppf(0.05,pilot_n-1))"
  zero_or_nonfinite_sd_policy: FAIL_CELL_POWER_NULL
  df_formula: "planned_n-1"
  ncp_formula: "(MDE/sd_upper_95)*sqrt(planned_n)"
  critical_value_formula: "scipy.stats.t.ppf(0.975,df)"
  power_formula: "1-scipy.stats.nct.cdf(critical,df,ncp)"
  required_cell_report_fields: [cell_id, pilot_n, planned_n, mde_absolute, sd_unbiased, sd_upper_95, df, ncp, power, failure_reason, passes_target]
  family_decision_rule: "all 22 continuous cells have pilot_n=5, finite sd_unbiased>0, finite sd_upper_95>0, power>=0.80; and all 62 discrete checks pass"
  interpretation: MARGINAL_CELL_READINESS_NOT_JOINT_FAMILY_POWER

mixed_effects:
  role: SENSITIVITY_ONLY_NO_GATE_EFFECT
  eligible_endpoint_class: CONTINUOUS_PRIMARY_BLOCK_LEVEL
  excluded_endpoint_classes: [BINARY, RATE, DISCRETE_DELAY, SAMPLE_LEVEL, TICK_LEVEL]
  nav:
    fit_scope: EACH_ENDPOINT_X_MAP_SEPARATELY
    formula: "y ~ C(method, Treatment(reference='B0_raw'))"
    groups: block_id
    variance_components: {day: "0+C(date_id)", robot: "0+C(robot_id)"}
    pooled_map_effect: false
  shift:
    fit_scope: EACH_ENDPOINT_X_SHIFT_SEPARATELY
    formula: "y ~ C(method, Treatment(reference='frozen'))"
    groups: block_id
    variance_components: {day: "0+C(date_id)", robot: "0+C(robot_id)"}
  fit:
    api: statsmodels.regression.mixed_linear_model.MixedLM.from_formula
    reml: false
    method: lbfgs
    maxiter: 2000
    disp: false
    wald_ci_level: 0.95
    single_level_action: DROP_COMPONENT_AND_REPORT_NOT_ESTIMABLE_SINGLE_LEVEL
    failure_action: REPORT_SENSITIVITY_NOT_ESTIMABLE
    optimizer_fallback: false
  report_fields: [fixed_coefficient, standard_error, wald_ci_low, wald_ci_high, variance_components, n_blocks, n_day_levels, n_robot_levels, converged, status, warnings]

multiplicity:
  primary: CONJUNCTIVE_IUT_NO_ADJUSTMENT
  secondary: DESCRIPTIVE_ONLY_NO_ADJUSTMENT
  primary_p_adjusted: null
  secondary_p_adjusted: null
  overall_gate_operator: AND_ALL_PRIMARY_AND_GLOBAL_SAFETY_INTEGRITY
  select_favorable_baseline: false

safety_latency:
  timing_required_sources: [watchdog, command_relay, runner_safety_monitor]
  timing_required_event_types: [SAFETY_STOP, TECHNICAL_STOP, COLLISION, ESTOP, PERSON_CONTACT, ZERO_PUBLISH_FAILURE, PHYSICAL_STOP_TIMEOUT]
  latency_formula_ms: "(zero_command_timestamp_ns-decision_timestamp_ns)/1e6"
  require_nonnegative_latency: true
  threshold_ms: 40.0
  missing_zero_publish_policy: AUTOMATIC_NO_GO
  required_count_zero_fallback: SIGNED_GATE_C_ONLY
  gate_c_schema_version: p8.gate.v1
  gate_c_id: C
  gate_c_required_status: PASS
  report_fields: [timing_required_event_count, eligible_event_count, missing_zero_publish_count, missing_zero_publish_event_ids, max_latency_ms, max_event_id, confirm_status, gate_c_report_sha256, gate_c_max_latency_ms]

software:
  analyzer_entrypoint: src/calibagent/eval/p8_real.py
  analysis_environment_lock: env/analysis/requirements-p8.lock.txt
  analysis_environment_lock_sha256: "<64-hex frozen analysis environment lock SHA-256>"
  rng_api: numpy.random.Generator
  bit_generator_api: numpy.random.PCG64
  quantile_api: numpy.quantile
  clopper_pearson_api: src/calibagent/eval/metrics.py::clopper_pearson_interval
  wilcoxon_api: scipy.stats.wilcoxon
  mixedlm_api: statsmodels.regression.mixed_linear_model.MixedLM.from_formula
```

上方两个带尖括号的 hash 是文档元变量，不是 final YAML 可接受的
字面值；final 中两者都必须替换为对应的 lowercase 64-hex SHA-256。
template 的唯一例外是后文规定的 pilot input-lock hash `null`。

`hypothesis_id` 只能按 `estimands` 中的 template 逐字符串展开：不转换
大小写、不删下划线、不使用列表下标、不使用随机 UUID。每个
NAV map 展开 6 个 map endpoint，再对三个 comparison endpoint 各展开
6 个 baseline；`valid_calibration_ratio` 在 `GLOBAL` 作用域展开 7 个 method。
每个 shift 展开 10 个 shift endpoint 和 3 个 method validity endpoint。
`global_endpoint_keys` 每项只展开一次。展开后的 ID 必须全局唯一，
exact expected cardinality 是 `2×(6+3×6)+7+4×(10+3)+9=116`。
secondary ID 按 `secondary_descriptive.hypothesis_id_templates` 逐字展开，
`D::` 是字面 namespace；其 exact cardinality 是
`2×(3×7+2×8)+4×(4×2+3×3)=142`。因此输出的 expected endpoint ID
总数是 258，其中 primary 116、secondary 142。analyzer 遇到缺失、
额外或重复 ID 必须非零退出，不得现场加 endpoint。

SHIFT monitor 的 primary 派生值按以下顺序计算，这一顺序是
schema test 和 golden fixture 的必测项：

1. 先对选中的 protocol-complete monitor row 计算 `E_i`。不可用默认
   `alarm=false`、填 0 NIS 或向前/向后填充伪造 `E_i=true`。
2. 在 `1..4` 先计算 `observed_pre_alarm`和 `pre_evidence_complete`。
   primary false-alarm gate 的二元分子是
   `false_alarm_for_gate = observed_pre_alarm OR NOT pre_evidence_complete`；因此缺失/
   invalid pre evidence 不能被计成“没有误报”。同时另报
   `observed_pre_alarm`，以区分真实 detector alarm 和证据失败。
3. 若有 observed pre alarm，reason=`PRE_ALARM`；否则若 pre evidence 不完整，
   reason=`INVALID_PRE_EVIDENCE`。两者均强制 `detected=false,
   detection_delay_trials=6`，不再尝试用后续 alarm 挽回 endpoint。
4. 只在 pre 完整且无 pre alarm 时扫描 `5..9`。最早的 valid alarm
   之前若出现任一 `E_i=false`，必须立即以
   `INVALID_POST_PREFIX_EVIDENCE` 失败，不得跳过该 slot 去寻找更晚 alarm。
   若最早 valid alarm 在 `j`且 `E_5..E_j` 全真，则
   `detected=true,delay=j-4`；该 alarm 之后的 invalid monitor 不反向改写已发生的
   detection。全部 `5..9` valid 但无 alarm 为 `MISS`。所有 detection failure
   都取 delay penalty 6。

false-alarm/detection 的分母始终是每 shift 全部 20 个 `full` sequence，
不是 valid-only subgroup。recovery 不因 pre-alarm 或 detection failure 被删除：
它仍对 20 个 sequence 按 rolling endpoint 无条件计算；但 pre evidence
不完整时，target 仍按 penalty `q` 生成 numeric 值，`recovered` 必须为
false。每个 invalid/unavailable validation slot 取 `q=0.25²`并进入 early/
terminal summary，但包含它的四槽窗口不得 recovered。delay/recovery
median 使用 `linear`，p95 使用 `higher`，且均在包含 penalty 6/13
的全 20 个值上计算，禁止 survivor-only summary。

主要重采样单位是 paired block。NAV 的两图是同 block 重复测量，
不得池化为 `n=60`；每个 map 共用同一个 `10000×30` block-index
matrix。每个 shift 使用自己的 `10000×20` matrix，并在块内同时保留
frozen/passive/full。CI 取 bootstrap statistic 的 0.025/0.975 percentile；
NAV NI 取 lower bound，ratio 取 upper bound，且 ratio 是 ratio of means。

tracked `configs/experiments/p8_analysis_plan_template.yaml` 中唯一允许待填充的
统计字段是 `power_plan.pilot_input_lock_manifest_raw_sha256: null`。DEV 数据
先完成 exporter 和 pre-lock validation，prepare 再且只能将该 null 替换为
`manifests/input_lock_manifest.json` 的 64-hex raw SHA-256，生成 final
`protocol/analysis_plan.yaml`；其他 byte 必须与 template 的 canonical parse tree 相同。
final plan 不允许 null，也不得引用尚未生成的 DEV delivery manifest。

Gate D 只从该 raw SHA 绑定的 DEV pre-lock input tree计算 readiness；DEV schedule 必须
恰为 NAV 5 blocks、每个 SHIFT 5 blocks，故每个 cell 的 `pilot_n` 必须恰为 5。
`planned_n` 仍固定为 NAV 30、SHIFT 20，严禁用 5 替代或混入 CONFIRM。

连续 family 有且只有 22 个有序 cell：两路线的 B8-vs-B0 completion-time superiority
2 个、两路线×六 baseline 的 completion-time-ratio NI 12 个、四 shift 的
passive-vs-full early-RMSE superiority 4 个、四 shift 的 full terminal-RMSE threshold
4 个。每个 cell 先用 DEV paired differences 计算 `ddof=1` SD，再以一侧 95% chi-square
上界 `sd_upper_95` 代入 planned 30/20 的 noncentral-t 公式。`sd_unbiased<=0`、NaN、Inf、
chi-square 上界非 finite 或 `pilot_n!=5` 时，该 cell 的 `power=null`、
`failure_reason` 非空并直接 FAIL；禁止把 zero pilot SD 报成 power=1。22 个 cell 的
**边际** conservative power 都必须≥0.80。

离散 family 有且只有 62 个 check：每路线 3 个 NAV absolute-rate check，共 6；
每路线×success/collision NI×六 baseline 的 paired-binary lattice check，共 24；
每 shift 的 false-alarm/detection/recovery point-rate check，共 12；每 shift 的四个
detection/recovery ordinal quantile check 与一个 Wilcoxon attainable-p check，共 20。
binomial check 必须
枚举全部整数计数并用冻结的 Clopper–Pearson/point gate求非空 passing set；paired NI
必须证明 `1/30` lattice 对 0.10 margin 至少有 3 个步长和可达到的 acceptance point。
ordinal check 只枚举该 quantile 真正读取的非递减 order-statistic tuple，
并检查其能否补全成长度 20 的冻结 support 序列；不得枚举全部整数 histogram。
对 `n=20`，`linear` median 只读排序后第 10/11 个值（一基），
`higher` p95 只读第 20 个值；因此每个 check 的候选 tuple 有明确小上界。
Wilcoxon check 用冻结 API/参数对确定性严格正差向量 `[1..20]` 计算最小可达 p。
这 62 项是 exact attainable/resolution guard，不冒充 80% power。Gate D PASS 要求
22+62 全通过；`gate_d_min_power` 只报告 22 个边际功效的最小值，另由
`gate_d_discrete_design_ready` 报离散 family。协议明确不声称 family-wise/joint
power≥0.80，也不声称 Gate D 预先保证实际结果会通过。若失败，只能在首个 CONFIRM datum
之前发布新 protocol version；本版不得偷偷增加/减少 30/20 CONFIRM cardinality。

mixed-effects 只对已有连续 block-level primary endpoint 运行，并严格使用
YAML 中唯一 formula/optimizer。单一 day/robot level 机械删除对应 variance
component 并报 `NOT_ESTIMABLE_SINGLE_LEVEL`；Hessian 非正定、boundary
variance 或不收敛时报 `SENSITIVITY_NOT_ESTIMABLE`，不得换 optimizer。
混合模型报告 YAML 中的全部 `report_fields`，永不替代 paired primary
analysis，也永不改变 GO/NO-GO。

### 15.2 P8-NAV primary gates

除明确写为全局检查的 budget、validity 和 safety 项外，下表的 rate、时间、
win-rate 和 noninferiority gate 必须在 **2 个地图上分别通过**。不允许将
简单地图和困难地图池化后掩盖单图失败。matched comparison 必须对
`B2_lhs`、`B3_sobol`、`B4_d_opt`、`B5_active_no_task` 和 `B6_random`
分别计算；不能先挑出最有利的 baseline。

| Gate | 门槛 |
|---|---:|
| map coverage | 2/2 |
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

在当前双侧 95% Clopper–Pearson 定义下，离散门槛意味着 B8 每图至少需要
`29/30` success，且 collision 必须为 `0/30`；`28/30` success 或 `1/30`
collision 均不通过相应 interval gate。completion-time win 严格定义为
`B8_time < B0_time`，tie 计为 0 个 win，与 P7 evaluator 保持一致。

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
| full terminal RMSE bootstrap upper | ≤0.14 m/s-equivalent |
| minimum valid observation ratio | ≥0.85 |
| maximum serious safety events | 0 |
| maximum software zero-command latency | ≤40 ms |

software zero-latency的 eligible set精确为 `safety_events.csv` 中
`decision_available=true,zero_publish_available=true,event_source∈{watchdog,command_relay,
runner_safety_monitor}` 且 `event_type` 属于实现指南 §7.2 的 frozen timing-required set 的行；
`latency_ms=(zero_command_timestamp_ns-decision_timestamp_ns)/1e6`，要求 nonnegative。
CONFIRM有eligible行时全取，
不挑最快/仅严重事件；任一 >40 ms立即NO-GO。若 n=0，report必须写
`CONFIRM_STATUS=NOT_OBSERVED,n=0,max=null,event_id=null`，绝不能将空集max当0；全局门槛仍要求
冻结 release中的 Gate C HIL report PASS且其注入事件 max≤40 ms。analysis report物理输出
`timing_required_event_count,eligible_event_count,missing_zero_publish_count,
missing_zero_publish_event_ids,max_latency_ms,max_event_id,confirm_status,
gate_c_report_sha256,gate_c_max_latency_ms`。对相同 source/type 的 required timing population，
`decision_available=false` 或 availability 列缺失是 delivery integrity failure；
`decision=true,zero=false` 是可表示但自动 NO-GO 的 safety failure，并进入
`missing_zero_publish_*`，不得从 eligible set静默消失。n=0 fallback 只允许
`timing_required_event_count=0`；若 required count>0但 eligible=0，仍为 NO-GO。
timestamp倒序是 delivery integrity failure。
`gate_c_max_latency_ms` 只能读取 frozen release中 signed `p8.gate.v1(gate_id=C)` 的
`gate_metrics.max_zero_command_latency_ms`；该 nested schema与 PASS约束逐字采用实现指南
§23.1。report hash/signature、eligible=required>0、missing counts=0、cross-boot=0 任一不满足，
n=0 fallback也失败；不得从 Gate C 的自然语言或 stdout解析 40 ms 证据。

这里有一个有意的强联合门槛：在 `n=20`、`descriptive_p95_quantile_method=higher`
且 miss/no-recovery 分别编码为 `6/13` 的定义下，任何一个 miss 都会令 p95 变成
`6`，任何一个未恢复都会令 p95 变成 `13`。所以 rate gate `≥0.90` 与 p95 gate
联合起来，实际上要求每个 shift 的 full 方法 **20/20 检测且 20/20 恢复**。
这是预注册协议意图，不得把它实现成“18/20 也通过”，也不得在看见数据后更换
quantile、penalty 或门槛。

每个 shift 只有 20 个 paired blocks，rate 的 exact interval 必须如实报告。
即使 `20/20`，双侧 95% exact lower bound 也约为 0.832；即使 `0/20` false
alarm，upper bound 也约为 0.168。因此本设计预注册的是 point-estimate rate
gate 加透明 interval 报告，不能写成“以 95% 置信度证明 detection/recovery
rate ≥0.90 或 false alarm ≤0.05”。

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
- [ ] navigation 480 episodes。
- [ ] 2 个 map 的几何、照片和 survey 齐全。
- [ ] complete failures 未排除。

### P8-SHIFT

- [ ] 4 个 shift 定义全部冻结且可测量。
- [ ] 每个 shift ≥20 个完整 paired triplets。
- [ ] 240 个 sequences、10,800 motion trials 目标完整。
- [ ] initial set 的 480 个 nominal-restore sentinel 均在 raw/ledger；所有已激活
  conditional set 和其中技术重采的 attempts 也完整保留并分层计数。
- [ ] frozen/passive/full 使用相同 prior、设计和 context gate，并各自独立标定。
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

> CalibAgent 在冻结的真实 Go2 在线实验中，以 12-trial active protocol
> （6 个冻结 signed-axis seeds + 6 个 online task-weighted IVR trials）
> 在两个预注册的固定航点室内路线——Offset slalom 与 Weighted arc——上
> 改善了相对 raw 的 timeout-coded completion time，同时通过绝对
> success/collision 门槛，并在预注册门槛内与 30-trial dense 和多个
> matched-budget controls 非劣。

若 P8-SHIFT 也通过，可以支持：

> 在三类隐藏动力学干预和一类“可见 task change + 隐藏 dynamics
> change”混合干预下，full 方法相对 passive 更新改善了
> 早期恢复误差，并满足检测、恢复、终端精度和安全门槛。

不能自动支持：

- 所有 Go2 个体或所有四足机器人上的泛化；
- 户外、楼梯、高速、拥挤人群或未知地形安全；
- 未测试 payload/friction/firmware 的泛化；
- 无监督长期自主部署；
- 比所有 calibration 方法普遍优越；
- 六类实机地图、未知地图或地图分布上的泛化；
- shift 后的导航性能恢复；P8-SHIFT 只测命令模型的检测与恢复，没有与
  P8-NAV 做交叉实验；
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
- P8 Go2 实机软件实现与仿真代码导读：
  `docs/p8_go2_implementation_guide_zh.md`
- CalibAgent GitHub：
  <https://github.com/EurekaZang/CalibAgent>

正式实验必须以现场实际型号的最新厂商手册和本地安全制度为准；产品页中的最大性能不能作为实验命令目标。
