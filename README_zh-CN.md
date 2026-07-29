# CalibAgent

[English](README.md) | [简体中文](README_zh-CN.md)

[![Software CI](https://github.com/EurekaZang/CalibAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/EurekaZang/CalibAgent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.12-3776AB)
![License](https://img.shields.io/badge/License-MIT-2F855A)
![Scoped publication audit](https://img.shields.io/badge/P0--P7%20scoped%20audit-GO-1F883D)

**面向四足机器人的安全、不确定性感知主动速度标定。**

CalibAgent 是一项面向 ICRA 投稿研究的科研代码库。它研究四足机器人
如何在安全约束下主动选择少量速度指令，学习“指令到实际运动”的映射，
量化认知不确定性，并将标定模型用于导航与域偏移后的在线恢复。

> **ICRA readiness：冻结的 P0–P7 论点为 GO。P6/P7 强仿真 readiness
> 也为 GO。**第一次 P7 强确认实验失败并继续保留在证据记录中；正面的导航
> 论点只来自随后执行的独立复现实验。CalibAgent 不主张 P3–P7 已在真实
> Go2 上在线运行，也不主张已经证明 sim-to-real 稳健性。真实机器人在线
> 主动标定仍属于 P8。

## 摘要

腿式机器人不会精确执行速度指令。执行器动态、学习式运动策略、地形、
载荷和饱和约束会共同形成从机体速度指令
`u = (vx, vy, wz)` 到实测速度 `y` 的上下文相关映射。CalibAgent 将这种
偏差建模为序贯实验设计问题：贝叶斯基函数模型估计映射和预测不确定性；
任务加权的积分方差缩减规划器选择信息量高的标定指令；非学习式安全过滤器
与验证门控的停止规则约束实际执行。

冻结证据覆盖合成实验、183 条 Unitree Go2 被动实机试验、故障注入和固定
Isaac Lab/PhysX 环境。在合成主实验中，主动标定达到联合精度与不确定性
目标所需试验数比 LHS 少 39.52%。在强确认性仿真中，主动恢复在四类留出
域偏移上降低了相对被动更新的早期误差。随后冻结的独立导航复现实验在
六张新地图上评估 3,024 个 episode：B8 在每张地图上至少成功 70/72 次、
碰撞为零，并满足相对 dense 与同预算基线的注册非劣效门槛。除明确标注的
真实 Go2 离线回放结果外，上述结论均限定在仿真范围内。

## 研究问题

> 四足机器人能否用少于被动采样的安全试验，识别与下游任务相关的
> 指令—运动映射，同时保持校准良好的不确定性、受控的停止行为、
> 域偏移后的恢复能力和下游导航性能？

CalibAgent 将这一问题拆分为分阶段证据链：

- **P0–P1：**冻结可移植接口，并用真实 Go2/LiDAR 里程计数据验证被动标定；
- **P2–P3：**在可控合成映射中检验不确定性校准与任务感知主动设计；
- **P4：**独立于学习模型验证停止规则和 fail-closed 安全逻辑；
- **P5–P7：**在固定仿真器中验证完整闭环、域偏移恢复和固定规划器导航；
- **P8：**按照冻结的实机协议完成在线 Go2 确认性实验。

## 方法

```mermaid
flowchart LR
    T["下游任务分布"] --> P["安全候选指令池"]
    M["贝叶斯指令—运动模型"] --> A["任务加权 IVR 规划器"]
    P --> A
    A --> S["非学习式安全过滤器"]
    S --> B["RobotBackend<br/>Isaac Lab · 回放 · Go2（P8）"]
    B --> R["原始位姿 / 指令 / 健康状态"]
    R --> O["SE(2) 测量管线"]
    O --> M
    M --> C["验证集 + 不确定性停止"]
    C -->|继续| A
    C -->|接受| I["逆模型补偿"]
    I --> N["固定规划器导航"]
    O --> D["域偏移检测器"]
    D -->|偏移锁存| X["后验膨胀 + 主动恢复"]
    X --> A
```

数值核心既不导入 Isaac Lab，也不导入 ROS 2。所有环境通过统一的
`RobotBackend`/`RawTrialData` 契约接入，共享测量管线在任何模型更新前
统一产生 `TrialObservation`。这一 ports-and-adapters 边界将算法论点与
仿真器或机器人集成清晰分离。

### 核心组成

1. **不确定性感知模型：**M2 贝叶斯基函数模型包含跨轴、hinge 与交互项，
   支持后验序列化和预测认知方差。
2. **任务感知采集：**规划器最小化声明任务指令分布上的积分后验方差。
   Random、LHS、Sobol、贝叶斯 D-optimal、no-task 和 dense 控制组遵守
   一致的数据访问规则。
3. **独立安全层：**硬指令/状态包络过滤所有候选；运行时状态机锁存
   abort 并输出零速度，安全责任不交给学习模型。
4. **域偏移响应：**有界证据累积检测持续变化，对已失效的后验置信度
   进行膨胀，并分配固定的主动恢复预算。
5. **下游评估：**不同标定方法使用完全相同的 waypoint 规划器、地图、
   运动策略、物理参数、随机种子和安全限制。

## 证据与主要结果

| 阶段 | 实验设计与独立统计单元 | 冻结的主要结果 | 论点边界 |
|---|---|---|---|
| **P1 真实回放** | 183 条有效 Go2 试验；三个采集 session；留一 session 交叉评估 | M1 的 pooled RMSE 相对 **raw 降低 54.45%**，相对 **M0 降低 34.07%** | 单机器人、单日期、单环境上的被动离线标定 |
| **P2–P3 合成实验** | 20 个独立 seed；三类重复失真条件；六个采集控制组 | Active 用 18.67 次试验达到联合目标，LHS 为 30.87 次，即 **减少 39.52%**（`p = 9.54e-7`） | 可控合成映射 |
| **P4 安全/停止** | 60 条停止轨迹、300 个危险注入、160 个运行时故障 | 提前停止率 0%；额外试验中位数/p95 为 2/2；危险拒绝率 100%；**严重事件 0** | 回放与故障注入证据 |
| **P5 仿真闭环** | 四类 Isaac Lab 场景 × 20 个配对 seed；12 次主动试验 | 最差场景 RMSE 降低 **9.30%**；全部配对 CI 下界为正；最大 abort 响应 20 ms | 固定 Isaac Lab/PhysX 与官方 Go2 策略 |
| **P6 强域偏移** | 四类留出偏移 × 72 个配对 seed × frozen/passive/full | Passive−full 早期 RMSE 的 CI 下界为 **0.00537–0.01536**；终端 RMSE CI 上界 ≤ 0.12564；**严重事件 0** | 注册仿真偏移；不主张终端优于 passive |
| **P7 强导航** | 六张新地图 × 72 个配对 seed × 七种方法 = **3,024 episodes** | B8 最低成功率 **70/72**；每张地图碰撞均为 **0/72**；相对 dense/同预算基线的最差时间比 CI 上界为 **1.074/1.090** | 正面结论仅来自独立复现实验 |

详细证据映射见
[`docs/requirements_matrix.md`](docs/requirements_matrix.md)，完整数值结果、
estimand、区间和局限性见 [`reports/`](reports/)。

## 仿真结果

### Isaac Sim 实验图库——29 张证据内容互不重复的图片

图库覆盖全部 20 组冻结 P5–P7 仿真配置，并删除了无法从外观区分的重复静态
场景。P7 的九张几何结构不同的地图各保留全局与机器人视角，共 18 张
1280×720 原生 RGB 帧。P5/P6 的 11 组配置各保留一张 1600×900 响应事实
卡：卡内包含两个注册验证指令的 Isaac Sim 原生帧、对应的实际仿真 XY
响应轨迹，以及冻结物理、失真、seed、checkpoint 和终态数值。

全部仿真帧均使用 Isaac Lab v2.3.2
（`37ddf626871758333d6ed89cf64ad702aef127d0`）与 Isaac Sim
5.1.0-rc.19。P5/P6 响应卡会明确标注为组合展示，不被当作新增定量证据；
原生源帧哈希与响应轨迹哈希保存在对应 provenance 中。

P7 画面中的青色线段和球体表示冻结规划器的路径与航点，绿色球体表示注册
目标点。这些标记由版本化场景配置直接生成，仅用于抓帧读图，不参与碰撞，
不改变 episode，也不作为定量证据。

每张 P5/P6 响应卡执行实验代码中索引为 2 和 7 的注册验证指令。黄色表示
起点，绿色表示注册测量窗终点，彩色线由实际仿真机体位姿轨迹重放得到。
轨迹几何不参与碰撞，仅用于读图。

#### P7 独立强确认复现——全部六张地图

<table>
  <tr>
    <th width="20%">冻结地图</th>
    <th width="40%">全局视角</th>
    <th width="40%">机器人视角</th>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p7_replicate_double_chicane_capture.json"><strong>Double chicane</strong></a><br>连续两次横向换向。</td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_double_chicane_overview.png" alt="P7 double-chicane 强确认复现地图的 Isaac Sim 全局视角。"></td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_double_chicane_robot_view.png" alt="P7 double-chicane 强确认复现地图的 Isaac Sim 机器人视角。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p7_replicate_extended_lane_capture.json"><strong>Extended lane</strong></a><br>长时域跟踪与停车。</td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_extended_lane_overview.png" alt="P7 extended-lane 强确认复现地图的 Isaac Sim 全局视角。"></td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_extended_lane_robot_view.png" alt="P7 extended-lane 强确认复现地图的 Isaac Sim 机器人视角。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p7_replicate_narrow_lane_capture.json"><strong>Narrow lane</strong></a><br>受限横向净空。</td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_narrow_lane_overview.png" alt="P7 narrow-lane 强确认复现地图的 Isaac Sim 全局视角。"></td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_narrow_lane_robot_view.png" alt="P7 narrow-lane 强确认复现地图的 Isaac Sim 机器人视角。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p7_replicate_offset_slalom_capture.json"><strong>Offset slalom</strong></a><br>交替偏置障碍物。</td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_offset_slalom_overview.png" alt="P7 offset-slalom 强确认复现地图的 Isaac Sim 全局视角。"></td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_offset_slalom_robot_view.png" alt="P7 offset-slalom 强确认复现地图的 Isaac Sim 机器人视角。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p7_replicate_s_bend_capture.json"><strong>S-bend</strong></a><br>连续双向曲率。</td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_s_bend_overview.png" alt="P7 S-bend 强确认复现地图的 Isaac Sim 全局视角。"></td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_s_bend_robot_view.png" alt="P7 S-bend 强确认复现地图的 Isaac Sim 机器人视角。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p7_replicate_weighted_arc_capture.json"><strong>Weighted arc</strong></a><br>非对称曲线路径跟踪。</td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_weighted_arc_overview.png" alt="P7 weighted-arc 强确认复现地图的 Isaac Sim 全局视角。"></td>
    <td><img src="docs/assets/readme/isaac_sim/p7_replicate_weighted_arc_robot_view.png" alt="P7 weighted-arc 强确认复现地图的 Isaac Sim 机器人视角。"></td>
  </tr>
</table>

#### P7 主导航实验——三张开发地图

<table>
  <tr>
    <th width="20%">冻结地图</th>
    <th width="40%">全局视角</th>
    <th width="40%">机器人视角</th>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p7_main_narrow_corridor_capture.json"><strong>Narrow corridor</strong></a><br>受限走廊穿越。</td>
    <td><img src="docs/assets/readme/isaac_sim/p7_main_narrow_corridor_overview.png" alt="P7 主实验 narrow-corridor 地图的 Isaac Sim 全局视角。"></td>
    <td><img src="docs/assets/readme/isaac_sim/p7_main_narrow_corridor_robot_view.png" alt="P7 主实验 narrow-corridor 地图的 Isaac Sim 机器人视角。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p7_main_open_field_capture.json"><strong>Open field</strong></a><br>无约束目标接近。</td>
    <td><img src="docs/assets/readme/isaac_sim/p7_main_open_field_overview.png" alt="P7 主实验 open-field 地图的 Isaac Sim 全局视角。"></td>
    <td><img src="docs/assets/readme/isaac_sim/p7_main_open_field_robot_view.png" alt="P7 主实验 open-field 地图的 Isaac Sim 机器人视角。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p7_main_slalom_capture.json"><strong>Slalom</strong></a><br>三障碍物交替路线。</td>
    <td><img src="docs/assets/readme/isaac_sim/p7_main_slalom_overview.png" alt="P7 主实验 slalom 地图的 Isaac Sim 全局视角。"></td>
    <td><img src="docs/assets/readme/isaac_sim/p7_main_slalom_robot_view.png" alt="P7 主实验 slalom 地图的 Isaac Sim 机器人视角。"></td>
  </tr>
</table>

#### P5 闭环标定——四类注册场景

<table>
  <tr>
    <th width="22%">冻结场景</th>
    <th width="78%">注册响应事实卡</th>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p5_tier_a_affine_capture.json"><strong>Tier-A affine</strong></a><br>平地与仿射执行失真。</td>
    <td><img src="docs/assets/readme/isaac_sim/p5_tier_a_affine_experiment_card.png" alt="P5 Tier-A affine Isaac Sim 响应事实卡，包含两个注册探测、实际轨迹和冻结参数。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p5_tier_a_deadzone_capture.json"><strong>Tier-A deadzone</strong></a><br>平地与指令死区。</td>
    <td><img src="docs/assets/readme/isaac_sim/p5_tier_a_deadzone_experiment_card.png" alt="P5 Tier-A deadzone Isaac Sim 响应事实卡，包含两个注册探测、实际轨迹和冻结参数。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p5_tier_b_friction_payload_capture.json"><strong>Tier-B friction + payload</strong></a><br>低摩擦、+2.0 kg 载荷、+0.02 m 质心偏移。</td>
    <td><img src="docs/assets/readme/isaac_sim/p5_tier_b_friction_payload_experiment_card.png" alt="P5 Tier-B 摩擦载荷 Isaac Sim 响应事实卡，包含两个注册探测、实际轨迹和冻结参数。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p5_tier_b_rough_capture.json"><strong>Tier-B rough</strong></a><br>程序化崎岖地形与偏移载荷。</td>
    <td><img src="docs/assets/readme/isaac_sim/p5_tier_b_rough_experiment_card.png" alt="P5 Tier-B 崎岖地形 Isaac Sim 响应事实卡，包含两个注册探测、实际轨迹和冻结参数。"></td>
  </tr>
</table>

#### P6 主域偏移恢复实验——三类注册偏移

<table>
  <tr>
    <th width="22%">偏移后场景</th>
    <th width="78%">注册响应事实卡</th>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p6_main_friction_payload_gain_shift_capture.json"><strong>摩擦 + 载荷 + 增益</strong></a><br>摩擦 0.90→0.25、+3.0 kg、+0.03 m 质心。</td>
    <td><img src="docs/assets/readme/isaac_sim/p6_main_friction_payload_gain_shift_experiment_card.png" alt="P6 主实验摩擦载荷增益偏移 Isaac Sim 响应事实卡，包含两个注册探测、实际轨迹和冻结参数。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p6_main_gain_coupling_shift_capture.json"><strong>增益重耦合</strong></a><br>保持物理参数，仅改变注册执行映射。</td>
    <td><img src="docs/assets/readme/isaac_sim/p6_main_gain_coupling_shift_experiment_card.png" alt="P6 主实验增益耦合偏移 Isaac Sim 响应事实卡，包含两个注册探测、实际轨迹和冻结参数。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p6_main_mixed_context_shift_capture.json"><strong>混合上下文</strong></a><br>摩擦 0.80→0.40、+2.0 kg、+0.02 m 质心。</td>
    <td><img src="docs/assets/readme/isaac_sim/p6_main_mixed_context_shift_experiment_card.png" alt="P6 主实验混合上下文偏移 Isaac Sim 响应事实卡，包含两个注册探测、实际轨迹和冻结参数。"></td>
  </tr>
</table>

#### P6 强确认恢复实验——四类留出偏移

<table>
  <tr>
    <th width="22%">偏移后场景</th>
    <th width="78%">注册响应事实卡</th>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p6_confirm_friction_payload_capture.json"><strong>摩擦 + 载荷</strong></a><br>摩擦 0.92→0.28、+2.8 kg、+0.028 m 质心。</td>
    <td><img src="docs/assets/readme/isaac_sim/p6_confirm_friction_payload_experiment_card.png" alt="P6 强确认摩擦载荷偏移 Isaac Sim 响应事实卡，包含两个注册探测、实际轨迹和冻结参数。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p6_confirm_gain_recoupling_capture.json"><strong>增益重耦合</strong></a><br>保持摩擦与载荷，使用留出增益映射。</td>
    <td><img src="docs/assets/readme/isaac_sim/p6_confirm_gain_recoupling_experiment_card.png" alt="P6 强确认增益重耦合偏移 Isaac Sim 响应事实卡，包含两个注册探测、实际轨迹和冻结参数。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p6_confirm_mixed_context_capture.json"><strong>混合上下文</strong></a><br>摩擦 0.80→0.42、+2.2 kg、−0.022 m 质心。</td>
    <td><img src="docs/assets/readme/isaac_sim/p6_confirm_mixed_context_experiment_card.png" alt="P6 强确认混合上下文偏移 Isaac Sim 响应事实卡，包含两个注册探测、实际轨迹和冻结参数。"></td>
  </tr>
  <tr>
    <td><a href="docs/assets/readme/isaac_sim/p6_confirm_payload_com_only_capture.json"><strong>仅载荷 + 质心</strong></a><br>保持摩擦，+3.0 kg、−0.032 m 质心。</td>
    <td><img src="docs/assets/readme/isaac_sim/p6_confirm_payload_com_only_experiment_card.png" alt="P6 强确认仅载荷质心偏移 Isaac Sim 响应事实卡，包含两个注册探测、实际轨迹和冻结参数。"></td>
  </tr>
</table>

每个场景标题链接到对应抓帧记录，其中保存冻结场景/配置哈希、策略
checkpoint 哈希、选定 seed、运行时身份、相机位姿、注册探测指令、失真
参数、响应轨迹哈希、标记语义和 PNG SHA-256。可复现实现为
[`capture_readme_scene.py`](sim/isaaclab/scripts/capture_readme_scene.py)与
[`build_isaac_response_card.py`](scripts/build_isaac_response_card.py)。
治理测试会拒绝完全重复和近重复的图库图片。这些图片用于记录仿真设置与
定性响应；统计论点仍以版本化 manifest、episode 表和审计输出为依据。

### 样本效率与模型不确定性

<p align="center">
  <img src="evidence/p3_main/sample_efficiency.png"
       alt="主动与被动采集方法随有效标定试验数变化的任务加权 RMSE 和认知方差。"
       width="900">
</p>

任务加权主动方法更早达到注册的联合目标；右图给出积分认知方差的同步
下降。统计推断使用 20 个独立 seed，而没有把 60 个重复的
seed×distortion-family 条件错误地视为独立样本。

### 域偏移恢复与下游导航

<table>
  <tr>
    <td width="50%">
      <img src="reports/figures/p6_strong_confirmatory.png"
           alt="P6 强确认性主动恢复效应和带 95% bootstrap 区间的终端 RMSE。">
    </td>
    <td width="50%">
      <img src="reports/figures/p7_strong_confirmatory_v2.png"
           alt="P7 强确认性导航成功率区间与配对完成时间非劣效结果。">
    </td>
  </tr>
  <tr>
    <td><strong>P6：</strong>完整主动恢复在注册早期窗口中优于被动更新，
      同时满足绝对终端 RMSE 门槛。</td>
    <td><strong>P7：</strong>独立复现实验通过成功率、碰撞率精确区间门槛
      和配对完成时间非劣效门槛。</td>
  </tr>
</table>

第一次 P7 强确认实验失败，其证据继续保存在
[`evidence/p7_strong_confirmatory_failed/`](evidence/p7_strong_confirmatory_failed/)。
成功结果使用新的地图、新的 seed 和预先冻结的协议；失败实验与开发实验
没有被并入正面估计。

<p align="center">
  <img src="docs/assets/readme/p7_slalom_seed_8006.png"
       alt="P7 绕桩配对轨迹：未标定控制超时，十二次主动标定后进入目标区域。"
       width="900">
</p>

<p align="center">
  <em>具有代表性的 P7 配对 episode（seed 8006），与总体统计分开解释。
  B0 未标定控制超时；B8 使用 12 次标定试验后进入目标区域。地图、轨迹与
  <a href="scripts/build_readme_figures.py">绘图脚本</a>均已纳入版本控制。</em>
</p>

## 发表完整性设计

- **协议隔离：**开发与确认性 seed 不重叠；任务指令和留出评估指令使用
  不同的固定 seed。
- **正确统计单元：**配对仿真 seed 是独立单元，重复场景或地图不被当作
  独立重复。
- **终点纪律：**有利的标定诊断指标不能挽救失败的下游导航终点。
- **保留失败：**失败的确认实验与修复过程中使用的 pilot 均保留版本记录，
  且不进入确认性估计。
- **可执行审计：**发表审计重新计算统计量，并验证哈希、manifest、运行时
  锁、轨迹覆盖、安全响应和 Git ancestry，不信任生产端自行写入的 `GO`。
- **论点隔离：**软件 CI、仿真 readiness、真实数据回放和在线实机确认是
  不同的证据门槛。

参见冻结的
[`实验协议`](docs/experiment_protocol.md)、
[`强确认性实验协议`](docs/p6_p7_strong_confirmatory_protocol.md)和
[`完成语义`](docs/completion_semantics.md)。

## 复现已审计的软件包

### 1. 安装

```bash
git clone https://github.com/EurekaZang/CalibAgent.git
cd CalibAgent
python -m venv .venv
.venv/bin/pip install \
  -r env/analysis/requirements.lock.txt \
  -r env/analysis/requirements-dev.lock.txt
.venv/bin/pip install --no-deps -e .
```

### 2. 执行软件与发表门槛

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/pytest -p pytest_cov --cov=calibagent
.venv/bin/ruff check .
.venv/bin/mypy src/calibagent
.venv/bin/calibagent-audit --workspace . --require-ready
.venv/bin/calibagent-audit-strong --workspace . --require-ready
./scripts/audit_source_delivery.sh
```

挂载 1.06 GB 全分辨率补充轨迹后，可重复完整轨迹与哈希审计：

```bash
.venv/bin/calibagent-audit-strong \
  --workspace . --raw --require-ready
```

### 3. 重建 README 图片

```bash
.venv/bin/python -m calibagent.cli.build_figures \
  --registry evidence/p3_main/trial_trace.csv \
  --output evidence/p3_main/sample_efficiency.png \
  --uncertainty-slice evidence/p3_main/uncertainty_slice.csv
.venv/bin/python scripts/build_readme_figures.py
```

复现 P5–P7 还需要固定的 Isaac Lab v2.3.2/Isaac Sim 环境和官方 Unitree
Go2 策略 checkpoint。命令与运行时锁详见
[`docs/experiment_registry.md`](docs/experiment_registry.md)。
README 中的原生仿真画面可由
[`sim/isaaclab/scripts/capture_readme_scene.py`](sim/isaaclab/scripts/capture_readme_scene.py)
复现；其输入与精确输出哈希保存在相邻的 P5/P7 抓帧记录中。

## 仓库结构

| 路径 | 用途 |
|---|---|
| [`src/calibagent/core/`](src/calibagent/core/) | 贝叶斯模型、主动规划器、停止、安全与域偏移检测 |
| [`src/calibagent/interfaces/`](src/calibagent/interfaces/) | 与 backend 无关的数据和执行契约 |
| [`src/calibagent/backends/`](src/calibagent/backends/) | 回放、Isaac Lab 与 fail-closed Go2 适配器 |
| [`src/calibagent/eval/`](src/calibagent/eval/) | 冻结 benchmark 与发表审计实现 |
| [`configs/experiments/`](configs/experiments/) | 版本化的开发和确认性实验协议 |
| [`evidence/`](evidence/) | 实时审计需要的紧凑、哈希绑定证据 |
| [`reports/`](reports/) | 阶段报告、审计记录和发表图表 |
| [`docs/`](docs/) | 架构决策、协议、论点矩阵与实机交接 |
| [`tests/`](tests/) | 单元、集成、回归和治理测试 |

## 真实机器人 P8

P1 已提供真实 Go2 被动回放证据，但在线 P8 边界尚未闭合。
`Go2RosBackend` 目前有意保持 fail-closed；只有完成 ROS 2/Unitree 接入、
独立 watchdog、P8-NAV/P8-SHIFT runner 和硬件门控后，才能开始正式采集。

实机同事应首先阅读：

- [Go2 实机软件实现与仿真代码导读](docs/p8_go2_implementation_guide_zh.md)；
- [完整实机实验、数据采集与交付规范](docs/p8_go2_real_deployment_data_handoff_zh.md)。

## 数据与溯源

可重新生成的输出默认被 gitignore。冻结的紧凑证据存储在 `evidence/`；
manifest 将每个产物绑定到源代码 commit、配置、运行时版本、策略哈希和
补充全分辨率轨迹。Dense-oracle 评估点不参与模型拟合、规划器调参或特征
缩放。完整数据访问规则见
[`docs/experiment_protocol.md`](docs/experiment_protocol.md)。

## 引用

公开预印本发布后将补充正式论文引用。在此之前，请引用实际使用的仓库版本：

```bibtex
@software{calibagent_2026,
  author  = {{CalibAgent contributors}},
  title   = {CalibAgent: Safe and Uncertainty-Aware Active Velocity
             Calibration for Quadruped Robots},
  year    = {2026},
  version = {0.1.0},
  url     = {https://github.com/EurekaZang/CalibAgent}
}
```

## 许可证

CalibAgent 使用 [MIT License](LICENSE)。
