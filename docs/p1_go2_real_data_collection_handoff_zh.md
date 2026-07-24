# CalibAgent P1：Unitree Go2 实机数据采集与交付规范

> 文档用途：直接交给实机采集、参考定位和数据导出人员执行。
> 目标：生成能够通过当前 P0–P3 ICRA publication audit 的真实 P1 证据，而不仅是“有一份实机日志”。
> 冻结实验：`p1_go2_real_capture`
> 冻结计划：`outputs/p1_capture/plan.csv`
> 计划 SHA-256：`7393222a654e488132be235cffef81d13776d5b6f93f2bb844fa7dc5401f821c`

## 1. 最终需要交付什么

实机同事应交付一个完整、只读备份的数据目录，至少包含：

1. 三个独立 session 的原始 rosbag、动捕日志或 LiDAR odometry 日志；
2. 一份逐参考位姿采样导出的 `go2_raw_trials.csv`；
3. 未修改的冻结采集计划 `plan.csv`；
4. session 元数据、trial/attempt 台账、坐标系与时间同步说明；
5. 参考传感器到 Go2 `base` 的外参和外参获得方法；
6. 所有交付文件的 SHA-256 校验值；
7. 所有中止、重采、丢帧、定位失败和安全事件的记录。

推荐目录结构：

```text
p1_go2_real_delivery/
├── README.md
├── capture_plan/
│   ├── plan.csv
│   └── plan.manifest.json
├── raw/
│   ├── go2-session-01/
│   │   ├── attempt_bags/
│   │   └── reference_native/
│   ├── go2-session-02/
│   │   ├── attempt_bags/
│   │   └── reference_native/
│   └── go2-session-03/
│       ├── attempt_bags/
│       └── reference_native/
├── exported/
│   └── go2_raw_trials.csv
├── metadata/
│   ├── session_metadata.csv
│   ├── trial_ledger.csv
│   ├── coordinate_frames.md
│   └── time_sync.md
├── calibration/
│   ├── reference_to_base_extrinsic.yaml
│   └── calibration_notes.md
└── checksums.sha256
```

`go2_raw_trials.csv` 是当前软件入口；原始日志、元数据和校准文件是论文真实性、可追溯性和问题复查所必需的证据。不能只交 CSV 后删除原始日志。

## 2. 完成定义和硬门槛

下列条件必须同时成立：

| 项目 | 硬性要求 |
|---|---|
| 机器人 | 真实 `Unitree Go2` |
| 参考测量 | 独立 LiDAR odometry 或 motion capture |
| 独立 session | 至少 3 个，必须使用冻结 ID |
| 冻结计划 | 3 × 61，共 183 个计划 trial |
| 计划完成率 | 至少 82%，即至少 151 个不同的计划 `(session_id, trial_id)` 被记录 |
| 有效观测 | 至少 150 个 trial 通过测量质量检查 |
| 计划命令匹配率 | 至少 99%；现场执行目标应为 100% |
| 命令容差 | 每轴与计划值的绝对偏差不超过 `1e-3` |
| 轴向覆盖 | `vx`、`vy`、`wz` 每一轴的正负方向都必须在有效数据中达到至少 `0.10` 的绝对幅值 |
| 数据真实性 | 必须保留原始数据、数据集和计划文件的可复验 SHA-256 |
| 泛化评估 | 按 session 分组训练/验证，不能将同一 session 泄漏到两侧 |
| 最终效果 | M1 相对 raw-command RMSE 降低至少 5%，且相对 M0 RMSE 降低至少 5% |

虽然审计只要求 151 个计划 trial 被记录、150 个有效，但这种采法几乎没有失败余量。**现场必须以完成全部 183 个 trial 为目标**。不得把最低拒收线当成采集目标。

最后两项 RMSE 提升是数据产生后的结果，不可通过编辑数据、选择有利 trial 或修改 manifest 获得。如果真实结果没有达到门槛，应如实报告 `NO-GO`。

## 3. 冻结采集计划

必须逐行执行随本文一起交付的 `plan.csv`，不得自行重新随机、调整速度、交换正负号、缩放命令或重新编号。采集前运行：

```bash
sha256sum plan.csv
```

输出必须为：

```text
7393222a654e488132be235cffef81d13776d5b6f93f2bb844fa7dc5401f821c  plan.csv
```

计划包含三个 session：

- `go2-session-01`：`trial_id=0..60`
- `go2-session-02`：`trial_id=0..60`
- `go2-session-03`：`trial_id=0..60`

每一行已经指定：

- `cmd_vx`, `cmd_vy`, `cmd_wz`；
- 设计类型 `anchor`、`sentinel` 或 `lhs`；
- ramp、settle、measure、ramp-out 时长；
- 目标采样频率。

建议严格按文件行顺序执行，以保留已冻结的时序随机化和 sentinel 重复设计。若出于安全原因必须改变实际执行顺序，不能改变 `(session_id, trial_id)` 和命令的对应关系，并必须在 `trial_ledger.csv` 中记录实际顺序和原因。

冻结命令范围：

| 轴 | 范围 | 单位/定义 |
|---|---:|---|
| `vx` | `[-0.60, 0.60]` | Go2 base 机体系前后速度，m/s |
| `vy` | `[-0.30, 0.30]` | Go2 base 机体系左右速度，m/s |
| `wz` | `[-0.80, 0.80]` | 绕 base z 轴偏航角速度，rad/s |
| 平移范数 | `sqrt(vx²+vy²) <= 0.65` | m/s |

坐标正方向采用 ROS 常用约定：`+x` 向前、`+y` 向左、`+z` 向上、`+wz` 逆时针。若 Go2 的控制接口采用不同符号或坐标定义，必须在发送层做一次固定、可审计的转换，使最终 CSV 与上述定义一致，并在 `coordinate_frames.md` 中写明。禁止采完后根据结果逐 trial 猜测或翻转符号。

## 4. 实验场地和机器人状态

### 4.1 主实验条件

本 P1 主数据应在以下条件下采集：

- 平整、坚硬、无明显坡度、摩擦条件一致的地面；
- 足够大的无障碍区域，保证最高速度 trial 可完成 ramp 和完整测量窗口；
- 固定步态、控制模式、机器人配置和参考定位配置；
- 固定或明确记录负载，包括 LiDAR、计算单元、动捕标记架和线缆；
- 禁止在一个 session 中途更换足端、负载、步态、定位算法参数或控制器版本；
- 如不可避免地发生配置变化，应结束当前 session，记录原因，不得继续沿用原 session ID。

每个 session 开始前记录：

- 日期、开始/结束时间和实验地点；
- Go2 序列号、固件版本、SDK/控制器版本或 commit；
- 参考传感器型号、序列号、算法版本和参数文件 hash；
- 地面类型、估计坡度、是否潮湿或污染；
- gait/control mode；
- 额外 payload 定义及质量；
- 电池开始/结束比例；
- 操作者、急停人员和安全区域说明；
- 坐标外参标定 ID、时间同步方式和同步误差估计。

### 4.2 三个 session 如何才算独立

三个 session 不能由一段连续日志改三个名字得到。每个 session 至少应执行：

1. 独立停止并重新开始数据记录；
2. 重新初始化参考定位；
3. 重新完成静止检查和坐标方向检查；
4. 记录新的 session 起止时间和电池状态；
5. 最好在不同时间块进行；若条件允许，可在不同日期进行。

主实验条件应保持一致，以便将 session 差异解释为重复实验波动，而不是未经控制的地形或 gait 域迁移。

## 5. 独立参考位姿要求

### 5.1 可接受来源

只接受以下之一：

- `mocap`：外部动作捕捉系统直接提供经标定的 Go2 base 位姿；
- `lidar_odometry`：由独立 LiDAR 数据计算的定位/里程计，不能直接复用 Go2 onboard state 作为真值。

不可接受：

- Go2 自带速度或位姿估计冒充 ground truth；
- 从命令积分得到的位姿；
- 仿真、回放 fixture、轨迹重定向或手工生成数据；
- 用被评估模型自身的输出作为参考；
- 没有原始输出可追溯的人工汇总值。

Go2 onboard state、IMU、足端状态可以作为诊断通道保留，但必须与独立参考位姿清楚区分，不能写入 `pose_x/y/yaw`。

### 5.2 参考位姿必须代表 base，而不是传感器本体

`pose_x`, `pose_y`, `pose_yaw` 必须描述 Go2 base 在同一个固定 world/map 坐标系中的 SE(2) 位姿。

如果参考系统输出的是 LiDAR 或 marker rigid body 的位姿，必须使用固定外参转换到 Go2 base：

```text
T_world_base(t) = T_world_reference(t) × T_reference_base
```

必须交付：

- `T_reference_base` 的平移和旋转；
- 父子 frame 名称和单位；
- 外参标定方法、日期和重复性检查；
- 实际用于导出 CSV 的外参文件。

旋转 trial 中，直接把偏置安装的 LiDAR/marker 位姿当 base 位姿会产生杠杆臂线速度，污染 `vx/vy`，因此不可省略外参转换。

### 5.3 参考系统现场检查

正式采集前完成不计入 183 个计划 trial 的 warm-up：

1. 静止至少 10 s，检查位姿无跳变、跟踪不中断；
2. 手动或低速向前移动，确认 `+x`；
3. 向左移动，确认 `+y`；
4. 原地逆时针旋转，确认 `+yaw/+wz`；
5. 检查 world 平移和 yaw 使用同一个一致坐标系；
6. 检查 yaw 单位为 rad，不是 degree；
7. 检查参考位姿没有在 trial 测量窗口中重定位、回环跳变或 frame reset。

warm-up 数据单独保存，不写入最终 `go2_raw_trials.csv`。

## 6. 时间同步和采样

命令与参考位姿必须能够在同一时间轴上对齐。要求：

- CSV 的每一行以该行参考位姿的采样时刻为准；
- `timestamp` 使用数值秒，保留至少微秒级小数精度；
- 同一 trial 内必须严格递增，不能重复、倒退或混用两个时钟域；
- 命令与参考位姿应来自同一时钟，或通过有记录、可复验的 offset/clock mapping 转换；
- 记录同步方法、估计 offset、抖动和同步检查时间；
- 工程目标为绝对对齐误差不超过 5 ms，超过 10 ms 应停止并排查；
- 不得通过复制低频位姿样本伪造 50 Hz；不得无说明地对参考位姿做平滑或插值。

参考位姿输出和最终测量表的目标频率为 50 Hz，目标间隔 0.020 s。2.0 s 窗口通常得到约 101 个包含首尾端点的样本。

现场加严验收线：

- 每个完整 trial 目标不少于 90 个真实参考样本；
- 采样频率中位数应在 45–55 Hz；
- 任意相邻样本时间间隔不超过 0.10 s；
- 不应把软件的最低 `30 samples` 拒收线当作采集目标。

如果现有 LiDAR odometry 不能输出足够频率，应在正式实验前更换/调整独立参考方案。不要先用 10 Hz 采完再复制或插值成 50 Hz。

## 7. 每个 trial 的标准操作

每个计划 trial 的完整时长为 4.0 s：

| 阶段 | 时长 | 操作 | 是否进入最终 CSV |
|---|---:|---|---|
| `ramp_in` | 0.6 s | 从当前安全状态平滑升到计划命令 | 否 |
| `settle` | 0.8 s | 保持计划命令，等待运动稳定 | 否 |
| `measure` | 2.0 s | 命令恒定，记录用于估计的参考位姿 | 是 |
| `ramp_out` | 0.6 s | 平滑降到零或下一个安全状态 | 否 |

逐 trial 操作：

1. 从 `plan.csv` 读取当前 `session_id`、`trial_id` 和三轴命令；
2. 在原始日志写入 trial marker，至少包含 session、trial、attempt 和 phase；
3. 检查参考定位有效、急停可用、区域无障碍；
4. 执行 0.6 s ramp-in；
5. 保持目标命令并 settle 0.8 s；
6. 打开精确的 2.0 s measure 标记；
7. measure 期间持续记录实际发出的三轴命令和独立 base 位姿；
8. 执行 0.6 s ramp-out；
9. 记录 trial 状态、安全事件、定位质量和是否需要技术性重采；
10. 只有完成现场质检后才进入下一 trial。

最终 CSV 只能包含 `measure` 窗口。若把 ramp-in、settle 或 ramp-out 混入，命令会被判为不恒定，且瞬态加速度会造成稳态比例失败。

### 7.1 命令记录的含义

`cmd_vx/vy/wz` 必须是控制接口实际发出的 setpoint，而不是：

- 从计划表复制但实际未发送的值；
- onboard 估计的已实现速度；
- 参考系统测得的速度；
- 控制器限幅前、且未被机器人接受的候选值。

measure 窗口内命令应恒定。程序按每个样本的三轴命令计算均值，并要求样本命令相对均值的三维范数最大值 `<1e-3`。若控制层发生安全裁剪或限幅，必须在台账中记录；不能把原计划值写回 CSV 掩盖实际执行。

## 8. 最终 CSV 规范

### 8.1 文件级要求

- 文件名：`go2_raw_trials.csv`；
- UTF-8、逗号分隔、首行为字段名；
- 小数点使用 `.`，不能带单位字符串；
- 不保存 pandas index 或空的 `Unnamed: 0` 列；
- 数值不得含空值、`NaN`、`inf` 或 `-inf`；
- 命令至少保留 6 位小数，timestamp 应保留足够精度表达 20 ms 间隔；
- 一行是一条真实参考位姿样本，不是一条 trial 汇总；
- 同一 `(session_id, trial_id)` 在最终 CSV 中只能对应一个被预先规则选定的 attempt。

### 8.2 必需字段

字段名必须完全一致：

| 字段 | 类型 | 含义 | 约束 |
|---|---|---|---|
| `trial_id` | int/string | plan 中 trial ID | 必须与 plan 精确对应，不得重新编号 |
| `session_id` | string | 独立 session ID | 只能使用三个冻结 ID |
| `timestamp` | float | 参考位姿采样时刻，s | trial 内严格递增 |
| `cmd_vx` | float | 实际发出的 base-x 命令，m/s | measure 内恒定，匹配 plan |
| `cmd_vy` | float | 实际发出的 base-y 命令，m/s | measure 内恒定，匹配 plan |
| `cmd_wz` | float | 实际发出的 base-yaw 命令，rad/s | measure 内恒定，匹配 plan |
| `pose_x` | float | 独立参考的 world→base x，m | 有限实数 |
| `pose_y` | float | 独立参考的 world→base y，m | 有限实数 |
| `pose_yaw` | float | 独立参考的 world→base yaw，rad | 有限实数；允许常规 ±π wrap |

示例：

```csv
trial_id,session_id,timestamp,cmd_vx,cmd_vy,cmd_wz,pose_x,pose_y,pose_yaw,terrain_id,payload_kg,battery_ratio,gait_id
0,go2-session-01,1721500000.000000,0.250000,0.000000,-0.500000,1.203411,-0.114020,0.482011,lab_flat,2.35,0.91,trot
0,go2-session-01,1721500000.020000,0.250000,0.000000,-0.500000,1.208305,-0.111144,0.471992,lab_flat,2.35,0.91,trot
```

### 8.3 论文交付中要求同时提供的上下文字段

以下字段对当前解析器是可选的，但对本次论文交付应当提供：

| 字段 | 含义 | 填写规则 |
|---|---|---|
| `terrain_id` | 地面条件 ID | 同一主实验保持一致；使用可追溯名称 |
| `payload_kg` | 约定定义下的额外负载 kg | trial 内为常数，并在元数据解释是否包含参考传感器 |
| `battery_ratio` | 测量开始时电池比例 | `[0,1]`，不得写百分数 91 代替 0.91 |
| `gait_id` | 实际 gait/control mode | 使用真实名称，不得依赖默认值猜测 |

当前处理程序读取一个 trial 第一行的上下文，因此这些上下文字段在同一 trial 内必须一致。

### 8.4 不要交 trial 汇总表代替逐样本表

以下形式不合格：

```csv
trial_id,mean_vx,mean_vy,mean_wz
0,0.23,0.01,-0.46
```

系统需要原始时间序列来完成 SE(2) 速度估计、稳态检查、丢帧检查、协方差估计和异常值鲁棒处理。每个 trial 只有一行均值无法形成论文证据。

## 9. 原始日志必须包含的逻辑通道

具体 ROS topic 名可以按现场系统确定，但 `README.md` 必须给出 topic 到下列逻辑通道的映射：

| 逻辑通道 | 必需性 | 内容 |
|---|---|---|
| actual command | 必需 | 控制接口实际发出的 `vx,vy,wz` 和时间戳 |
| independent reference pose | 必需 | 原生 LiDAR odometry 或 mocap 6-DoF/SE(2) 位姿和时间戳 |
| trial/phase marker | 必需 | session、trial、attempt、ramp/settle/measure/ramp-out 边界 |
| TF / static TF | 必需 | world、reference sensor、marker rigid body、Go2 base 的关系 |
| reference health | 必需 | tracking valid、定位状态、协方差/质量标志（若系统提供） |
| robot mode/gait | 强烈建议 | 实际控制模式及切换事件 |
| battery and safety state | 强烈建议 | 电池、急停、保护、限幅或故障事件 |
| onboard state/IMU/feet | 建议 | 仅作诊断，不作为 ground truth |
| time-sync diagnostics | 强烈建议 | clock offset、同步状态或 PTP/NTP 统计 |

建议保留一台固定相机的视频，用于复查打滑、碰撞、线缆拉扯和动捕遮挡；视频不是 CSV 的替代品。

## 10. 测量质量判定

当前 `MeasurementPipeline` 对每个 `(session_id, trial_id)` 独立处理。代码拒收条件包括：

| 检查 | 代码门槛 | 现场要求 |
|---|---:|---|
| 样本数 | 少于 30 判无效 | 目标约 101，少于 90 应重查采集系统 |
| timestamp | 非递增判无效 | 原始导出顺序即严格递增 |
| 最大时间间隔 | `>0.10 s` 判无效 | 正常应接近 0.020 s |
| 估计丢帧率 | `>15%` 判无效 | 目标接近 0 |
| 稳态比例 | `<65%` 判无效 | ramp/settle 不进入测量窗口 |
| 稳态一致性 | 0.30 s 固定窗 SE(2) twist；线速度容差 0.10 m/s、角速度容差 0.15 rad/s | 避免对参考位姿做相邻二阶差分，同时拒绝测量窗内 ramp、碰撞或明显速度变化 |
| 命令恒定性 | 三维偏差范数必须 `<1e-3` | 目标完全恒定 |
| 数值有效性 | 速度/协方差非有限则无效 | 禁止 NaN/inf 和 frame jump |

程序会使用 trial 起始位姿到后续位姿的 SE(2) 对数估计 body twist，并进行鲁棒均值与协方差计算。因此以下问题会直接污染结果：

- 参考位姿 frame 在窗口中跳变；
- yaw 使用 degree；
- 传感器位姿未转换到 base；
- 命令与位姿时钟错位；
- ramp 段混入 measure；
- 位姿重复填充或过度平滑；
- 地面打滑、线缆牵引或外部接触未记录。

## 11. 中止、失败和重采规则

解析器会把相同 `(session_id, trial_id)` 的所有 CSV 行视为同一个 trial。因此不能把多个 attempt 直接拼进最终 CSV。

必须在采集前采用以下固定规则：

1. **measure 开始前中止**：不进入最终 CSV；可以使用同一 trial ID 重新执行。原始日志和中止原因仍保留在 attempt 台账。
2. **measure 期间发生明确技术故障**，如动捕完全丢失、rosbag 写入失败、急停、人员进入安全区：该 attempt 标为 `technical_abort`，保留原始文件，可重采；最终选择必须基于预先定义的技术状态，而不能基于模型误差大小。
3. **完整完成 measure，但机器人运动表现“不理想”**，如真实打滑、真实控制偏差或噪声较大：不得因为结果不好而选择性重采/替换。第一个完整协议合规 attempt 应进入最终 CSV，并由质量流水线决定有效性。
4. 每个 attempt 均写入 `trial_ledger.csv`，包括未进入最终 CSV 的 attempt；不得静默删除。
5. 最终 CSV 对每个 `(session_id, trial_id)` 只能保留一个 attempt，且 `trial_ledger.csv` 必须明确 `selected_for_csv=true/false`。

推荐 `trial_ledger.csv` 字段：

```text
session_id,trial_id,attempt_id,execution_order,bag_path,
measure_start_timestamp,measure_end_timestamp,status,exclusion_reason,
selected_for_csv,safety_event,reference_valid,operator_notes
```

允许的 `status` 建议固定为：

- `complete`
- `pre_measure_abort`
- `technical_abort`
- `safety_abort`

不允许使用“结果不好”“误差太大”“不利于模型”等结果相关理由排除数据。

## 12. 每个 session 结束后的现场质检

完成每个 session 后、拆设备或改变环境前，至少检查：

- 61 个计划 trial 的台账是否完整；
- 每个完整 trial 是否存在 measure marker；
- 最终选中 attempt 是否唯一；
- 每个 measure 窗口是否约 2.0 s、约 101 个真实参考样本；
- timestamp 是否严格递增且最大 gap 不超过 0.10 s；
- 命令是否恒定并与 plan 对应；
- pose 是否为有限值且没有 frame reset；
- 正向、侧向和旋转的符号是否仍正确；
- reference health 是否在测量窗内有效；
- 电池、gait、payload、地面和配置变化是否记录；
- 原始日志是否能够重新打开并导出；
- session 原始目录是否已做第二份备份和 SHA-256。

不要等三个 session 全部结束后才第一次检查导出流程。

## 13. CSV 快速静态检查

下面的脚本只检查格式、计划对齐和基础采样，不替代 CalibAgent 的正式 SE(2) 处理与 publication audit。将 `RAW` 和 `PLAN` 改为实际路径后运行：

```python
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path("go2_raw_trials.csv")
PLAN = Path("plan.csv")

required = {
    "trial_id", "session_id", "timestamp",
    "cmd_vx", "cmd_vy", "cmd_wz",
    "pose_x", "pose_y", "pose_yaw",
}
raw = pd.read_csv(RAW)
plan = pd.read_csv(PLAN)

missing = sorted(required - set(raw.columns))
assert not missing, f"missing columns: {missing}"
assert not raw[list(required - {"session_id", "trial_id"})].isna().any().any()

numeric = [
    "timestamp", "cmd_vx", "cmd_vy", "cmd_wz",
    "pose_x", "pose_y", "pose_yaw",
]
assert np.isfinite(raw[numeric].to_numpy(dtype=float)).all()

summary = []
for (session_id, trial_id), group in raw.groupby(["session_id", "trial_id"], sort=False):
    t = group["timestamp"].to_numpy(float)
    cmd = group[["cmd_vx", "cmd_vy", "cmd_wz"]].to_numpy(float)
    dt = np.diff(t)
    cmd_mean = cmd.mean(axis=0)
    summary.append({
        "session_id": str(session_id),
        "trial_id": str(trial_id),
        "samples": len(group),
        "duration_s": t[-1] - t[0],
        "strictly_monotonic": bool(len(dt) and np.all(dt > 0)),
        "max_gap_s": float(dt.max()) if len(dt) else np.inf,
        "median_hz": float(1.0 / np.median(dt)) if len(dt) else 0.0,
        "command_deviation": float(np.linalg.norm(cmd - cmd_mean, axis=1).max()),
        "cmd_vx": cmd_mean[0],
        "cmd_vy": cmd_mean[1],
        "cmd_wz": cmd_mean[2],
    })

trials = pd.DataFrame(summary)
assert len(trials) == len(trials[["session_id", "trial_id"]].drop_duplicates())
assert trials["strictly_monotonic"].all()
assert (trials["max_gap_s"] <= 0.10).all()
assert (trials["command_deviation"] < 1e-3).all()

for frame in (trials, plan):
    frame["session_id"] = frame["session_id"].astype(str)
    frame["trial_id"] = frame["trial_id"].astype(str)

joined = trials.merge(
    plan[["session_id", "trial_id", "cmd_vx", "cmd_vy", "cmd_wz"]],
    on=["session_id", "trial_id"], how="left", suffixes=("_raw", "_plan"),
    indicator=True,
)
identity_match = joined["_merge"].eq("both").to_numpy()
command_match = identity_match.copy()
for axis in ("vx", "vy", "wz"):
    command_match &= (
        joined[f"cmd_{axis}_raw"] - joined[f"cmd_{axis}_plan"]
    ).abs().le(1e-3).to_numpy()

completion = len(trials) / len(plan)
match_ratio = command_match.mean() if len(command_match) else 0.0
print(trials[["samples", "duration_s", "max_gap_s", "median_hz", "command_deviation"]].describe())
print(f"trials={len(trials)}, completion={completion:.3%}, command_match={match_ratio:.3%}")
print(trials.groupby("session_id").size())

assert completion >= 0.82
assert match_ratio >= 0.99
```

现场还应查看所有不满足以下加严目标的 trial，而不是直接删除：

```python
print(trials[
    (trials["samples"] < 90)
    | ~trials["duration_s"].between(1.90, 2.10)
    | ~trials["median_hz"].between(45.0, 55.0)
])
```

## 14. 回到 CalibAgent 后的正式处理与验收

将最终 CSV 放回项目后，使用真实参考系统对应的命令。LiDAR odometry：

```bash
calibagent-real-replay path/to/go2_raw_trials.csv \
  --output outputs/p1_real \
  --source-kind real_robot \
  --robot-model unitree_go2 \
  --reference-sensor lidar_odometry \
  --capture-plan outputs/p1_capture/plan.csv \
  --delivery-root path/to/p1_go2_real_delivery \
  --source-archive path/to/calibration.zip \
  --budget 30

calibagent-audit --workspace . --require-ready
```

动捕则仅将参数替换为：

```text
--reference-sensor mocap
```

处理程序将：

1. 复制并 hash 原始 CSV；
2. 按 `(session_id, trial_id)` 形成 trial；
3. 通过 SE(2) 测量流水线生成速度、协方差和质量标志；
4. 保存全部有效和无效观测；
5. 按 session 隔离训练/验证；
6. 比较 `B0_raw`、`M0_diagonal_affine` 和 `M1_full_affine`；
7. 验证冻结计划完成率和命令匹配率；
8. 生成带 git commit 和 SHA-256 的 `outputs/p1_real/manifest.json`。

最终三个 publication checks 必须全部通过：

- `p1_real_data_evidence`
- `p1_real_data_scale_coverage`
- `p1_real_baseline_improvement`

禁止手工编写或修改 `manifest.json`、`baseline_metrics.csv` 或 `observations.parquet` 来改变结论。

## 15. 明确禁止的数据处理

下列行为会使数据不能作为本项目的真实发表证据：

- 使用 simulator、fixture、synthetic CSV 或 retargeted trajectory；
- 将 onboard state 标为独立参考真值；
- 只保存每个 trial 的平均速度，不保存逐样本位姿；
- 删除原始日志，只保留清洗后的表；
- 根据模型误差选择 trial 或 attempt；
- 将一个连续 session 人工拆成三个 session ID；
- 修改 `trial_id` 来绕过计划不匹配；
- 用计划命令覆盖实际发送命令；
- 复制、插值或平滑低质量参考数据而不保留原始值和处理记录；
- 静默删除定位失败、安全中止或控制限幅事件；
- 为达到提升门槛而手工编辑位姿、命令、metrics 或 manifest；
- 在看到主实验结果后修改阈值、划分规则或冻结计划。

## 16. 交付前签字式检查表

### 采集计划

- [ ] 使用的 `plan.csv` SHA-256 与本文一致。
- [ ] 三个 session 均使用冻结 ID。
- [ ] 目标完成全部 183 个计划 trial。
- [ ] 未改变 plan 中命令与 trial ID 的对应关系。

### 参考系统

- [ ] 参考来源是 mocap 或独立 LiDAR odometry。
- [ ] `pose_x/y/yaw` 已转换为 world→Go2-base，而非传感器自身位姿。
- [ ] 外参文件、标定方法和 frame 说明已经交付。
- [ ] 命令与参考位姿使用同一时间轴，误差和同步方式已有记录。

### CSV

- [ ] 一行对应一个真实参考位姿样本。
- [ ] 九个必需字段名称完全正确。
- [ ] measure 窗口约 2.0 s、50 Hz、命令恒定。
- [ ] ramp/settle/ramp-out 未进入最终 CSV。
- [ ] 没有 NaN、inf、重复或倒退 timestamp。
- [ ] 每个 `(session_id, trial_id)` 只包含一个选定 attempt。
- [ ] 命令匹配率至少 99%，计划完成率至少 82%。
- [ ] 上下文字段和 session/trial 台账齐全。

### 原始证据与科研完整性

- [ ] 所有原始日志和失败 attempt 均保留。
- [ ] 所有排除均有预先允许的技术或安全原因。
- [ ] 没有根据模型结果进行选择性删除或重采。
- [ ] 原始文件已有第二份备份和 SHA-256。
- [ ] 能从原始日志重新导出同一份 CSV。

### 最终验收

- [ ] 至少 150 个 trial 被正式流水线判为有效。
- [ ] 三个 session 均贡献有效数据。
- [ ] 三轴正负方向覆盖通过。
- [ ] M1 相对 raw 和 M0 的验证 RMSE 均至少降低 5%。
- [ ] `calibagent-audit --workspace . --require-ready` 返回成功。

## 17. 本规范能够支撑的主张边界

该数据闭合的是当前 P1 真实被动回放证据，并使当前冻结范围内的 P0–P3 publication audit 有机会由 `NO-GO` 转为 `GO`。

它不能单独证明 P3 主动规划器已经在真实 Go2 上在线闭环运行。如果论文要提出“主动策略真机在线优于 LHS/random/Sobol/D-opt”等更强主张，还需要另行冻结并执行真机在线主动采集、matched baselines、多次独立 run 和相应安全协议；不能用本 P1 被动数据替代该证据。
