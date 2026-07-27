# Go2 P1 采集脚本使用说明

本说明配套 `p1_go2_real_data_collection_handoff_zh.md` 和冻结 `plan.csv`。脚本目标是按冻结计划让 Go2 做速度 trial，用独立 LiDAR odometry `/Odometry` 记录 `measure` 窗口位姿，并在场地有限时让狗回到采集原点。

> 这是已经执行过的 **P1 离线采集参考**，不是 P8 在线 backend/NAV/SHIFT
> runner。P8 开发必须先读
> `docs/p8_go2_implementation_guide_zh.md`。仓库中的 20 Hz wrapper 只用于复现
> 既有 P1 条件，不满足 P8 的 ≥40 Hz 硬门槛。

## 1. 推荐使用哪个工作区

- **建图/纯定位**：优先用 `/home/unitree/ws_localization`。
  - 它是纯 FAST-LIO/global_reloc 定位工作区。
  - 关键参考位姿 topic：`/Odometry`。
- **自动发布速度命令跑狗并采集**：用 `/home/unitree/ws_fastlio`。
  - 它包含 `/cmd_vel -> SportClient.Move` 的 `go2_cmd_vel` bridge。
  - 本次已让 bridge 发布经过限速、死区、定位门控、前方急停后的实际下发命令：`/go2_capture/actual_cmd_vel`。

正式 P1 采集建议组合：

```text
/home/unitree/ws_fastlio/run_localization.sh      # 定位 /Odometry + /loc_health
/home/unitree/ws_fastlio/run_cmd_vel_bridge.sh    # /cmd_vel -> SportClient.Move + /go2_capture/actual_cmd_vel
/home/unitree/lly/go2_plan_capture_runner.py      # 读取 plan.csv、执行 trial、导出 CSV
```

## 2. 采集前准备

### 2.1 建图和重定位数据库

如果还没有地图，先建图并生成重定位数据库。可二选一：

```bash
cd /home/unitree/ws_localization
./run_mapping.sh
./build_reloc_db.sh
```

或用完整导航工作区：

```bash
cd /home/unitree/ws_fastlio
./run_mapping.sh
./build_reloc_db.sh
```

### 2.2 重新编译控制桥

已修改 `/home/unitree/ws_fastlio/src/go2_cmd_vel/src/cmd_vel_bridge.cpp`，所以需要编译一次：

```bash
cd /home/unitree/ws_fastlio
colcon build --packages-select go2_cmd_vel --symlink-install
```

### 2.3 启动定位

```bash
cd /home/unitree/ws_fastlio
./run_localization.sh norviz
```

等待：

```bash
ros2 topic echo /loc_health
```

需要看到 `READY|...` 后再继续。

### 2.4 启动控制桥

另开终端：

```bash
cd /home/unitree/ws_fastlio
./run_cmd_vel_bridge.sh
```

空跑测试时可用：

```bash
cd /home/unitree/ws_fastlio
./run_cmd_vel_bridge.sh dry_run
```

确认实际命令 topic 存在：

```bash
ros2 topic echo /go2_capture/actual_cmd_vel
```

## 3. 采集脚本位置

仓库内位置：

```text
data/calibration_extracted/calibration/go2_plan_capture_runner.py
```

脚本默认读取仓库内冻结计划：

```text
evidence/p1_capture/plan.csv
evidence/p1_capture/plan.manifest.json
```

并强制校验 `plan.csv` 的 SHA-256：

```text
7393222a654e488132be235cffef81d13776d5b6f93f2bb844fa7dc5401f821c
```

如果 plan 被改过，脚本会拒绝运行。

## 4. 强烈建议先做 preflight

```bash
cd /home/unitree/lly
source /home/unitree/ws_fastlio/setup_nav_env.sh
python3 go2_plan_capture_runner.py --preflight-only
```

它会检查：

- `/loc_health` 是否 READY；
- `/Odometry` 是否有 pose；
- `/go2_capture/actual_cmd_vel` 是否存在；
- `/Odometry` 中位频率是否在 45–55 Hz；
- 最大相邻 pose gap 是否不超过 0.10 s。

如果 `/Odometry` 只有约 20 Hz，脚本会按 md 要求拒绝正式采集。不要复制或插值低频数据伪造成 50 Hz。

## 5. 小范围试跑

默认不加 `--arm` 时，脚本不会发布非零速度，也不会写最终 CSV。真正跑狗必须显式加 `--arm`。

建议先只跑一个 trial：

```bash
cd /home/unitree/lly
source /home/unitree/ws_fastlio/setup_nav_env.sh
python3 go2_plan_capture_runner.py \
  --arm \
  --session-id go2-session-01 \
  --trials 0 \
  --output-dir /home/unitree/lly/p1_go2_real_delivery \
  --overwrite \
  --terrain-id lab_flat \
  --payload-kg 2.35 \
  --battery-ratio 0.91 \
  --gait-id trot \
  --return-home every-trial \
  --max-radius-m 1.8 \
  --hard-radius-m 2.2
```

字段说明：

- `--arm`：允许发布非零 `/cmd_vel`，没有它狗不会动；
- `--session-id` / `--trials`：选择要跑的冻结 trial；
- `--overwrite`：重建输出 CSV/ledger；正式采集续跑时用 `--append`；
- `--return-home every-trial`：每个 trial 后回到启动时记录的原点；
- `--max-radius-m`：trial 中离原点超过该半径就中止并停狗；
- `--hard-radius-m`：回原点时也不能超过的硬边界；
- `--terrain-id`、`--payload-kg`、`--battery-ratio`、`--gait-id`：写入最终 CSV 的上下文字段。

## 6. 正式 session 采集

每个 session 单独启动记录、单独初始化定位、单独完成 warm-up。建议一条命令只采一个 session：

```bash
cd /home/unitree/lly
source /home/unitree/ws_fastlio/setup_nav_env.sh
python3 go2_plan_capture_runner.py \
  --arm \
  --session-id go2-session-01 \
  --output-dir /home/unitree/lly/p1_go2_real_delivery \
  --append \
  --terrain-id lab_flat \
  --payload-kg 2.35 \
  --battery-ratio 0.91 \
  --gait-id trot \
  --return-home every-trial \
  --max-radius-m 1.8 \
  --hard-radius-m 2.2
```

然后按 md 要求停止记录、重新初始化定位和检查，再执行：

```bash
python3 go2_plan_capture_runner.py --arm --session-id go2-session-02 --output-dir /home/unitree/lly/p1_go2_real_delivery --append ...
python3 go2_plan_capture_runner.py --arm --session-id go2-session-03 --output-dir /home/unitree/lly/p1_go2_real_delivery --append ...
```

不要把一段连续日志人工拆成三个 session。

## 7. 回原点逻辑

脚本启动后第一次收到 `/Odometry` 时，会把该 pose 作为默认原点：

```text
home = first /Odometry pose
```

每个 trial 后默认执行 `return_home`：

1. 用当前 `map` 系位姿计算到 home 的误差；
2. 将 map 误差转换到 Go2 body 系；
3. 发布小速度 `/cmd_vel` 返回；
4. 到达 `--home-xy-tolerance-m` 和 `--home-yaw-tolerance-rad` 后停下并等待；
5. 若定位掉 READY、实际命令 topic 丢失或超过硬边界，则立即停狗并报错。

如果你想固定原点而不是用启动 pose，可手动给：

```bash
--home-x 0.0 --home-y 0.0 --home-yaw 0.0
```

场地更小时，把速度和半径调小：

```bash
--max-radius-m 1.2 --hard-radius-m 1.5 --home-max-vx 0.18 --home-max-vy 0.12 --home-max-wz 0.35
```

## 8. 输出文件

默认输出目录：

```text
/home/unitree/lly/p1_go2_real_delivery/
```

主要文件：

```text
capture_plan/plan.csv
capture_plan/plan.manifest.json
exported/go2_raw_trials.csv
metadata/trial_ledger.csv
metadata/trial_velocity_summary.csv
raw/<session_id>/reference_native/trial_XX_attempt_YY.csv
```

### `exported/go2_raw_trials.csv`

只包含 `measure` 窗口样本，字段按 md：

```text
trial_id,session_id,timestamp,cmd_vx,cmd_vy,cmd_wz,pose_x,pose_y,pose_yaw,terrain_id,payload_kg,battery_ratio,gait_id
```

其中 `cmd_vx/cmd_vy/cmd_wz` 默认来自 `/go2_capture/actual_cmd_vel`，即 bridge 经过限速、定位门控、前方急停后的实际下发 setpoint。

### `metadata/trial_velocity_summary.csv`

这是辅助检查文件，不替代最终逐样本 CSV。它从 `measure` 窗口连续 pose 拟合速度：

```text
est_vx_body, est_vy_body, est_wz
```

用于现场快速看每个 trial 的实际速度量级。

### `metadata/trial_ledger.csv`

记录每个 attempt：

```text
complete, pre_measure_abort, technical_abort, safety_abort
```

如果定位掉线、样本少于 90、timestamp gap 超过 0.10 s、越界等，脚本会标记为技术/安全中止，且不会把该 attempt 写入最终 CSV。

## 9. md 合规注意事项

- 只接受独立参考位姿：`/Odometry` 来自 FAST-LIO/LiDAR odometry；不能用 Go2 onboard state 当真值。
- 最终 CSV 是逐 pose 样本，不是 trial 均值表。
- `ramp_in`、`settle`、`ramp_out` 不进入最终 CSV。
- 命令必须与冻结 plan 匹配；本次把 bridge 配置改为 P1 限速：`vx=0.60`、`vy=0.30`、`wz=0.80`，并关闭低速地板和死区，避免实际命令被静默改写。
- 如果前方急停、定位门控或 timeout 让实际命令变为 0，脚本会从 `/go2_capture/actual_cmd_vel` 记录实际值，质量检查会阻止不合规 attempt 进入最终 CSV。
- 不要根据模型误差选择性删除或重采。完整合规完成的第一个 attempt 应保留。
- 原始 rosbag、LiDAR 原生日志、外参、time sync、README topic mapping、checksums 仍需按 md 另外归档；本脚本不能替代这些原始证据。

## 10. 后处理

采集完成后先跑 md 中的静态检查，再回到 CalibAgent：

```bash
calibagent-real-replay /home/unitree/lly/p1_go2_real_delivery/exported/go2_raw_trials.csv \
  --output outputs/p1_real \
  --source-kind real_robot \
  --robot-model unitree_go2 \
  --reference-sensor lidar_odometry \
  --capture-plan outputs/p1_capture/plan.csv \
  --budget 30

calibagent-audit --workspace . --require-ready
```

如果最终不达标，应如实报告 `NO-GO`，不要编辑 CSV、metrics 或 manifest。
