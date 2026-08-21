# DCLP 2026-07-10 Go2 实机实验复现包

这是一份独立于原部署目录的复现副本。所有复现适配都位于：

```text
/home/unitree/qyw/dclp_20260710_reproduction
```

原始代码目录 `/home/unitree/workspace/xh/Offline_DVST` 没有被修改。本包复制了 model101、Go2/MID360/ROS2 部署链、7 月 10 日历史源码快照，并在副本中加入了 profile、安全解锁、每次运行独立日志、有效配置指纹和分析工具。

## 能复现什么，不能复现什么

可以精确冻结和重放：

- model101（SHA256 `dacaf9fc45da536ae6b45cdbedc949370b7828fac4cadcf40ebedabc4080c452`）；
- scan 270° 分配、正确/旧动作映射、两类 acceleration limiter；
- 各历史速度范围、hard cap、`L1/L2/W`、正前方 `w=0` 开关；
- compensation OFF、直接 ON（无 guard）、guarded ON；
- 每次实际加载的参数、code/model hash、guard 接受率、轨迹和 rosbag。

不能声称精确复现 7 月 10 日的物理现场，因为历史没有保存每次障碍物的坐标、尺寸、朝向、起点复位误差和完整视频。正确做法是：先复现软件状态，再让所有 profile 在同一个重新测量的标准场景中比较。

## 目录

```text
dclp_deploy/                 Go2 DCLP 部署副本
models/dclp/                 V1_41lambda1_101.pth
experiments/profiles/        历史状态和补充消融 profile
experiments/run_experiment.sh 单次实验入口，默认不运动
experiments/preflight.sh     静态/真机预检
experiments/tools/           profile 校验、smoke test、单次结果分析
experiments/design/          实验矩阵、场景和运行顺序
provenance/                  未改动的历史源码快照和来源说明
runs/                        运行后自动创建；每次独立归档
```

## 安全要求

真机运行至少需要两人：一人执行命令，一人始终持有物理急停/遥控接管。使用宽阔区域和轻质软障碍，禁止拿人、动物、玻璃或固定重物充当障碍。开始时机器人四周应有足够制动空间。

`REACHED` 只代表进入 0.4 m 目标半径，不代表没有碰撞。发生接触、人工中止、外部安全停止或超时，都必须保留数据并计为失败。

`h0_off_025629_legacy`、`h3_on_034223_raw_v6` 和 `h5_on_guard_v7_double` 是极高风险历史状态。它们默认只能做 dry-run；不要把 `--allow-extreme-historical` 当作普通启动选项。

任意时刻停止软件链：

```bash
cd /home/unitree/qyw/dclp_20260710_reproduction
./experiments/stop_experiment.sh
```

这个命令不能替代物理急停。

## 第一次部署：从零开始

### 1. 硬件和场地

- Go2、MID360 和部署电脑上电；电池建议高于 60%。
- `eth0` 固定为 `192.168.123.222/24`。
- MID360、Go2、主机时钟和 TF 安装位姿不变。
- 地面贴出起点中心、朝向线、目标点和障碍物轮廓。
- 起点复位误差建议不超过 2 cm，yaw 不超过 1°。
- 给每次实验准备同名视频标牌，视频中可见运行 ID。

把场景模板复制一份并实测填写，真机命令建议始终传入：

```bash
mkdir -p experiments/design/scenes
cp experiments/design/scene_measurement_template.yaml experiments/design/scenes/S0.yaml
# 编辑 S0.yaml，填入实测尺寸、照片名和说明
```

### 2. 完全离线的代码/model 检查

```bash
cd /home/unitree/qyw/dclp_20260710_reproduction

./experiments/preflight.sh
./experiments/tools/validate_profiles.py

set +u
source /opt/ros/foxy/setup.bash
source /home/unitree/project/ros2_ws/install/setup.bash
set -u
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 /home/unitree/miniconda3/envs/go2/bin/python \
  ./experiments/tools/smoke_test.py
```

预期：preflight 为 `failures=0`，23 个 profile 全部列出，smoke test 最后打印 `smoke tests passed`。

### 3. 真机只读预检

```bash
./experiments/preflight.sh --live
```

它检查依赖、model/hash、`eth0`、TCP 5596 和残留控制进程，不发送运动指令。

当前主机的一个外部依赖必须保留：`unitree_sdk2py` 是 editable install，实际指向 `/home/unitree/workspace/unitree_sdk2_python2/unitree_sdk2py`。若迁移到另一台主机，必须重新安装或 vendor 该 SDK。

### 4. 先做 dry-run

以下命令会启动传感器、odom、policy 和记录链，但 ZMQ 客户端不调用 `SportClient.Move`；30 秒后自动结束：

```bash
./experiments/run_experiment.sh h9_final_on 0 4 \
  --scene S0 --repeat 1 --dry-run --operator qyw
```

检查最近一次运行：

```bash
latest_run="$(find runs -mindepth 1 -maxdepth 1 -type d | sort | tail -1)"
sed -n '1,220p' "${latest_run}/policy_effective_config.json"
tail -80 "${latest_run}/component_logs/policy.log"
```

dry-run 不产生 `REACHED`，不能作为导航成功。

### 5. 再做 zero-motion

这个阶段会初始化 Unitree SDK、切换远程控制相关状态，但所有 `Move` 强制为零，仍需架空/清场和物理急停：

```bash
./experiments/run_experiment.sh h9_final_on 0 4 \
  --scene S0 --repeat 2 --zero-motion --operator qyw
```

### 6. 最终配置的第一次低风险真机试验

先在空场做最终 OFF，再做最终 ON。`--live` 和 `--armed` 缺一不可：

```bash
./experiments/run_experiment.sh c1_final_off 0 4 \
  --scene S0 --scene-file experiments/design/scenes/S0.yaml \
  --repeat 1 --live --armed --operator qyw

./experiments/run_experiment.sh h9_final_on 0 4 \
  --scene S0 --scene-file experiments/design/scenes/S0.yaml \
  --repeat 1 --live --armed --operator qyw
```

高风险 profile 还需要 `--allow-high-risk`；极高风险 profile 还需要 `--allow-extreme-historical`。必须先通过 dry-run 和 zero-motion，且只在安全评审后使用。

单独查看状态：

```bash
./experiments/status.sh
```

每个 runner 调用都会先清理旧链、重新启动 policy、创建独立 run 目录、结束 rosbag 并停止整套链，避免前一次命令状态污染下一次实验。

## 每次实验会保存什么

`runs/<RUN_ID>/` 中包含：

- `run_manifest.env`：profile、场景、重复号、操作者和 code/model/profile hash；
- `requested_effective_environment.txt`：白名单内的全部控制环境变量；
- `policy_effective_config.json`：policy 进程实际读取后的配置；
- `trajectory/trajectory.csv`：轨迹、action、目标命令、补偿前后命令、guard 原因；
- `rosbag/`：`/scan /odom /sportmodestate /go2_policy/cmd_vel /nav_status /dclp_relative_goal`；
- `component_logs/`：MID360、TF、pc2scan、odom、policy、ZMQ、watchdog、rosbag 日志；
- `operator_outcome.env`：人工标注接触、手停、视频、电池和复位误差；
- `run_result.env`：进程返回值和自动 REACHED 声明。

实验结束后立即编辑 `operator_outcome.env`。值使用 `yes/no`，不要删除失败 run。

分析单次运行：

```bash
./experiments/tools/analyze_run.py /absolute/path/to/runs/RUN_ID
```

它会打印并保存 `analysis.json`。只有 `REACHED`、无接触、无手停、无外部安全停止且在目标内保持 1 秒，`no_collision_success` 才为 true。

## 先做哪些实验

不要直接按历史时间顺序把所有状态各跑一次，然后把最后一次成功归因于补偿。历史中速度、guard 和几何同时变化，必须补最终配置的纯 OFF。

最低建议分三阶段：

1. 历史软件签名：H1/H2/H3/H9，先 dry-run；极端 H0/H5 只做 shadow 诊断。
2. 最小因果矩阵：最终 ON/OFF、guard、速度包、几何消融，在空场 S0 和中央软障碍 S1 各至少 5 次。
3. 主结论扩样：`h9_final_on` 对 `c1_final_off`，在 S0/S1/左右镜像场景中各至少 10 次/条件，按 block 交替顺序。

具体 profile、场景、次数、随机顺序和指标见 [EXPERIMENT_MATRIX.md](experiments/design/EXPERIMENT_MATRIX.md)；逐条可复制命令见 [COMMANDS.md](experiments/design/COMMANDS.md)。

## 结果解释边界

- `h9_final_on - c1_final_off` 才是最终栈上补偿的净效应。
- `h3_on_034223_raw_v6 - h4_on_guard_v6` 主要回答 guard 是否消除补偿饱和，不回答最终成功是否来自补偿。
- `h0/h1/h2 -> h9` 是跨配置历史复现，只能描述现象，不能做 compensation 因果结论。
- guarded ON 中每轴都可能回退为未补偿命令。必须报告 guard 接受率；不能只按启动 flag 把整条轨迹称为“全程使用后标定”。
- 改动速度上限同时改变 548-D observation 尾部，改动 `L1/L2/W` 会改变 270 个 observation 元素；两者都不是单纯末端限幅。
