# 单次实验命令

所有命令从下列目录执行：

```bash
cd /home/unitree/qyw/dclp_20260710_reproduction
```

## 历史软件状态

先将每条命令作为 dry-run 执行；以下不会调用 `SportClient.Move`：

```bash
# 025629：5 m，旧 OFF 失败锚点
./experiments/run_experiment.sh h0_off_025629_legacy 0 5 \
  --scene S0 --repeat 1 --dry-run --operator qyw

# 033014：5 m；033218：4 m，二者是同一 v5 OFF 软件状态
./experiments/run_experiment.sh h1_off_0330_v5 0 5 \
  --scene S0 --repeat 1 --dry-run --operator qyw
./experiments/run_experiment.sh h1_off_0330_v5 0 4 \
  --scene S0 --repeat 2 --dry-run --operator qyw

# 033524：3 m；033843/034020：4 m，三者是同一 v6 OFF 软件状态
./experiments/run_experiment.sh h2_off_0334_v6 0 3 \
  --scene S1 --repeat 1 --dry-run --operator qyw
./experiments/run_experiment.sh h2_off_0334_v6 0 4 \
  --scene S1 --repeat 2 --dry-run --operator qyw
./experiments/run_experiment.sh h2_off_0334_v6 0 4 \
  --scene S1 --repeat 3 --dry-run --operator qyw

# 034223：首版直接 ON，无 guard
./experiments/run_experiment.sh h3_on_034223_raw_v6 0 4 \
  --scene S1 --repeat 1 --dry-run --operator qyw

# guard、target/cap、角速度、线速度、几何的历史阶段
./experiments/run_experiment.sh h4_on_guard_v6 0 4 \
  --scene S1 --repeat 1 --dry-run --operator qyw
./experiments/run_experiment.sh h5_on_guard_v7_double 0 4 \
  --scene S0 --repeat 1 --dry-run --operator qyw
./experiments/run_experiment.sh h6_on_guard_v8 0 4 \
  --scene S1 --repeat 1 --dry-run --operator qyw
./experiments/run_experiment.sh h7_on_guard_v9_angular 0 4 \
  --scene S1 --repeat 1 --dry-run --operator qyw
./experiments/run_experiment.sh h8_on_guard_v10_linear 0 4 \
  --scene S1 --repeat 1 --dry-run --operator qyw
./experiments/run_experiment.sh h9_final_on 0 4 \
  --scene S1 --repeat 1 --dry-run --operator qyw
```

这里的 S0/S1 是新标准化场景，不是对未知历史障碍布局的声明。

## 最小因果矩阵真机命令

每次只运行一条，结束后人工复位机器人和障碍，再递增 `--repeat`。

```bash
SCENE_FILE=experiments/design/scenes/S1.yaml

# M1 最终 ON
./experiments/run_experiment.sh h9_final_on 0 4 \
  --scene S1 --scene-file "${SCENE_FILE}" --repeat 1 --live --armed --operator qyw

# M2 最终 OFF：主反事实
./experiments/run_experiment.sh c1_final_off 0 4 \
  --scene S1 --scene-file "${SCENE_FILE}" --repeat 1 --live --armed --operator qyw

# M3 最终参数、ON、无 guard
./experiments/run_experiment.sh c2_final_on_raw 0 4 \
  --scene S1 --scene-file "${SCENE_FILE}" --repeat 1 --live --armed --allow-high-risk --operator qyw

# M4 仅恢复旧几何
./experiments/run_experiment.sh c3_final_on_old_geometry 0 4 \
  --scene S1 --scene-file "${SCENE_FILE}" --repeat 1 --live --armed --operator qyw

# M5 同时撤销角×0.8和线×0.9
./experiments/run_experiment.sh c4_final_on_pre_speed 0 4 \
  --scene S1 --scene-file "${SCENE_FILE}" --repeat 1 --live --armed --allow-high-risk --operator qyw

# M6 只保留线×0.9
./experiments/run_experiment.sh c5_final_on_linear_only 0 4 \
  --scene S1 --scene-file "${SCENE_FILE}" --repeat 1 --live --armed --allow-high-risk --operator qyw

# M7 只保留角×0.8
./experiments/run_experiment.sh c6_final_on_angular_only 0 4 \
  --scene S1 --scene-file "${SCENE_FILE}" --repeat 1 --live --armed --allow-high-risk --operator qyw
```

在 S0 中将 `--scene S1` 改成 `--scene S0`，其余参数不变。S2L/S2R 同理，但必须先按测量模板固定镜像布局。

## 极高风险历史状态

完成 dry-run、zero-motion 和安全评审后，runner 技术上要求以下额外解锁：

```text
--live --armed --allow-extreme-historical
```

这只是一道防误触门槛，不是建议真机运行。H0 的 3 m/s、H3 的无 guard 补偿和 H5 的 2.1 m/s 临时状态应优先留在 shadow/架空测试；为了安全而降速时，结果必须标为“缩放复现”，不能称精确历史复现。

## 中止、标注和分析

另一终端始终准备：

```bash
./experiments/stop_experiment.sh
```

结束后：

```bash
latest_run="$(find runs -mindepth 1 -maxdepth 1 -type d | sort | tail -1)"
sed -n '1,120p' "${latest_run}/operator_outcome.env"
./experiments/tools/analyze_run.py "${latest_run}"
```

修改 `operator_outcome.env` 后再运行分析，才能得到有效的 `no_collision_success`。
