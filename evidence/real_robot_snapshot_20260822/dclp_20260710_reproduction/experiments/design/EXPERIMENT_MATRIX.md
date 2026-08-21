# 实验矩阵

## 1. 历史状态复现

| Profile | 对应历史 | 关键状态 | 建议 |
|---|---|---|---|
| `h0_off_025629_legacy` | 早期明确 OFF 失败锚点 | 旧 action×max+floor、odom fixed limiter、3.0/3.1416、正前方强制 w=0 | 极高风险；shadow 为主 |
| `h1_off_0330_v5` | `033014/033218` | 正确 range mapping、dt limiter、OFF、v 0.5–1.5、w 0.5236–1.5708 | 解释前两条到点 |
| `h2_off_0334_v6` | `033524/033843/034020` | OFF、v 0.35–1.05、w 0.36652–1.09956 | 解释后三条到点 |
| `h3_on_034223_raw_v6` | 第一条明确 ON | v6 速度、直接补偿、无 guard | 极高风险；复现长段 cap 饱和 |
| `h4_on_guard_v6` | 03:49 后 | 只加入逐轴 guard | 隔离 guard 的第一步 |
| `h5_on_guard_v7_double` | 03:53 临时状态 | 速度/上下限全部×2 | 极高风险；通常不需实机 |
| `h6_on_guard_v8` | 04:03 | target 与 hard cap 分离 | 历史阶段复现 |
| `h7_on_guard_v9_angular` | 04:09 | 角速度范围×0.8 | 历史阶段复现 |
| `h8_on_guard_v10_linear` | 04:13 | 再将线速度范围×0.9 | 历史阶段复现 |
| `h9_final_on` | `042250` | 再将几何放大至 .504/.504/.4464 | 最终历史组合 |

历史物理布局未知，所以这一组验证“软件行为签名”，不能声称重走原障碍路线。签名包括 action/command 范围、cap 平台、guard 回退率、轨迹形态和 REACHED/中止结果。

## 2. 最低必做因果矩阵

| ID | Profile | 相对于最终 ON 的变化 | 回答的问题 |
|---|---|---|---|
| M1 | `h9_final_on` | 无 | 最终组合能否稳定重复 |
| M2 | `c1_final_off` | 仅 compensation OFF | 后标定在最终栈上的净贡献 |
| M3 | `c2_final_on_raw` | 仅 guard OFF | guard 的净贡献与饱和机制 |
| M4 | `c3_final_on_old_geometry` | 仅恢复旧几何 | 04:15 几何放大的贡献 |
| M5 | `c4_final_on_pre_speed` | 同时撤销角×0.8、线×0.9 | 最终速度包的总贡献 |
| M6 | `c5_final_on_linear_only` | 只保留线×0.9 | 线速度修改的贡献 |
| M7 | `c6_final_on_angular_only` | 只保留角×0.8 | 角速度修改的贡献 |

最低运行 S0、S1 两个场景，每个 `profile × scene` 5 次，共 70 次。5 次只够发现大效应；任一单元若成功率在 1/5 到 4/5 之间，扩到至少 10 次。主比较 M1/M2 建议一开始就做 10 次/条件/场景。

## 3. 场景

采用机器人初始机体坐标：`forward` 为前方，`right` 为右方。runner 的两个数值参数依次是 `RIGHT_M FORWARD_M`。

### S0：空场直线

- 目标：`right=0, forward=4 m`。
- 目标线两侧至少 1.5 m 无障碍。
- 用途：测 yaw bias、空场晃动、路径效率，不得将弯行误称为绕障。

### S1：中央软障碍

- 目标：`right=0, forward=4 m`。
- 障碍中心：`right=0, forward=2.0 m`。
- 建议障碍外形约 `0.6 m` 宽、`0.4 m` 深，材质轻软且 MID360 可稳定检测。
- 测试区总宽至少 3 m，两侧净空对称。

### S2L / S2R：严格镜像

- 目标仍为 4 m 正前方。
- 障碍中心：`forward=2.0 m, right=-0.35 m` 与 `right=+0.35 m`。
- 障碍尺寸、朝向、地面和灯光严格相同。
- 用途：分辨机械左右不对称、场地偏置和补偿方向效应。

### S3：S 形通道

- 两个软障碍参考中心：`(right=+0.40, forward=1.6)` 与 `(right=-0.40, forward=2.7)`。
- 开始前按 Go2 实际尺寸和安全净距重新核定通道，不能照抄坐标后直接上机。
- 用途：要求至少一次转向换侧，观察振荡、后退和恢复能力。

每个场景都要保存平面测量图、障碍尺寸/材质、地面照片和起终点坐标。

## 4. 完整因果矩阵

如果最低矩阵显示有差异，完整核心设计使用四个因素：

- C：compensation OFF/ON；
- G：guard OFF/ON，仅 C=ON 有意义；
- S：最终速度包/04:03 未缩速包；
- J：最终几何/旧几何。

有效组合为：OFF 下 `2S × 2J = 4`，ON 下 `2G × 2S × 2J = 8`，共 12 个配置。它能估计 compensation、guard、速度、几何主效应，以及 guard×速度、compensation×速度和 compensation×几何交互。

12 个可直接运行的 profile 映射见 `core_factorial_profiles.csv`。

完整核心 12 配置 × S0/S1/S2L/S2R 4 场景 × 10 次 = 480 次。主比较最终 ON/OFF 可提高到 20 次/场景，其余消融 10 次。

guard 的接受边界使用 policy target min/max，而不是较高 hard cap，因此必须保留 guard×速度交互；不能把 guard 当成与速度无关的开关。

## 5. 运行顺序

不能先跑完全部 OFF 再跑全部 ON。以“场景 + 重复 block”为单位：

1. 固定场景并复位起点和障碍。
2. 同一 block 内重启 policy 后运行一个 profile。
3. 最终 ON/OFF 使用平衡顺序：奇数 block `OFF, ON, ON, OFF`；偶数 block `ON, OFF, OFF, ON`。
4. 下一 block 重新检查障碍坐标、起点误差和电池。
5. S2L/S2R 的先后顺序也必须平衡。

模板见 `primary_ab_schedule.csv`。

## 6. 成功和指标

主结果“无碰撞成功”需要同时满足：

- 60 秒内 `REACHED`；
- 目标距离 ≤0.4 m，并保持至少 1 秒；
- 无障碍接触；
- 无人工停止和外部安全停止。

必须分别报告：

- `REACHED` 率、无碰撞成功率、接触率、手停率、超时率；
- 完成时间、路径长度、直线效率、最大横偏；
- 后退命令次数、角速度 RMS/峰值/符号翻转；
- 最小激光回波，但不能把全局 `min_pooled_range` 当成障碍净距真值；
- target/hard-cap 饱和比例及最长恒定平台；
- guarded ON 的 v 接受率、w 接受率、双轴接受率和每类回退原因；
- 视频或外部测量得到的真实最小净距；
- 起点误差、电池、操作者、地面和实验顺序。

安全停止和失败 run 不得删除。视频评分最好对 ON/OFF 盲法。

最终因果判断使用同一 block 内 `h9_final_on - c1_final_off` 的配对差。历史 H0/H1/H2 到 H9 的变化只用于描述复现，不用于声称“后标定导致成功”。
