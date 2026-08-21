# DCLP Unitree Go2 + Livox MID360 ROS2 Deploy

> 这是上游组件说明的副本。复现实验请从
> `/home/unitree/qyw/dclp_20260710_reproduction/README.md` 和
> `experiments/run_experiment.sh` 开始，不要直接照本文件中的旧源目录命令运行。

This directory contains the Unitree Go2 hardware chain for DCLP real-robot deployment. The hardware side follows the tested Go2 style: Livox MID360 -> `/scan`, `/sportmodestate` -> `/odom`, optional SLAM/AMCL, optional UWB goal bridge, and ZMQ -> Unitree `SportClient.Move(v, 0, w)`.

DCLP policy logic is independent from MAER:

- Input is DCLP `548-D`: `90 * [cos, sin, distance, length1, length2, width] + 8-tail`.
- The real 360 deg `/scan` is transformed into `base_link`, then pooled into DCLP's 90 full-circle groups.
- The default backend is PyTorch `.pth`; deterministic action selects the highest-weight GMM component and returns `tanh(mu)`.
- The policy output is normalized `[-1, 1]`; the node converts it to physical `cmd_vel` with DCLP speed and acceleration limits.
- `/go2_policy/cmd_vel` is a diagnostic ROS2 topic. Real base control goes through ZMQ to `go2_zmq_sport_client.py`.

## Model Path

Default scripts try this checkpoint when it exists:

```bash
models/dclp/V1_41lambda1_101.pth
```

For deployment, explicitly set the model path:

```bash
export MODEL_PATH=/abs/path/to/V1_41lambda1_101.pth
```

The default Go2 DCLP Python is:

```bash
/home/unitree/miniconda3/envs/go2/bin/python
```

It must be able to import `torch`, `rclpy`, `tf2_ros`, `numpy`, and `zmq` with
`PYTHONNOUSERSITE=1`.

For the optional legacy TensorFlow checkpoint:

```bash
export POLICY_BACKEND=legacy_tf
export MODEL_PATH=/abs/path/to/tf_checkpoint_prefix
```

## Defaults

All Go2 scripts load:

```bash
dclp_deploy/robots/unitree_go2/default_params.yaml
```

Environment variables override YAML values. Example:

```bash
MIN_HEIGHT=0.1 MAX_HEIGHT=0.9 MODEL_PATH=/home/unitree/workspace/xh/Offline_DVST/models/dclp/V1_41lambda1_101.pth \
  bash dclp_deploy/robots/unitree_go2/bringup_all.sh
```

## SLAM

Build a 2D map:

```bash
cd /home/unitree/workspace/xh/Offline_DVST
SLAM_MODE=slam \
  bash dclp_deploy/robots/unitree_go2/bringup_all.sh
```

Save the map:

```bash
MAP_NAME=go2_lab \
  bash dclp_deploy/robots/unitree_go2/save_map.sh
```

## AMCL Navigation

Start localization first and do not autolaunch the policy:

```bash
SLAM_MODE=amcl \
AMCL_MAP=/abs/path/to/map.yaml \
AUTOLAUNCH_POLICY=0 \
  bash dclp_deploy/robots/unitree_go2/bringup_all.sh
```

Set the initial pose in RViz2 with `2D Pose Estimate`. After AMCL converges, start policy, ZMQ control, and the goal sequencer:

```bash
bash dclp_deploy/robots/unitree_go2/stop_nav_task.sh

MODEL_PATH=/home/unitree/workspace/xh/Offline_DVST/models/dclp/V1_41lambda1_101.pth \
GOAL_LIST=/abs/path/to/goals.yaml \
  bash dclp_deploy/robots/unitree_go2/start_goals_policy.sh
```

For a single goal, start `start_policy.sh` and `start_go2_zmq_sport_client.sh`, then publish RViz2 `2D Nav Goal` to `/move_base_simple/goal`.

## AMCL 定位主路径（不使用 UWB）

如果你当前不打算使用 UWB，而是希望像常规 2D 导航那样先建图、再 AMCL 定位、最后运行
DCLP policy，那么推荐直接使用下面这条主路径。

注意：

- 不要启动 `start_uwb_policy.sh`
- 不要打开 `AUTOLAUNCH_UWB_GOAL`
- 定位阶段不要自动启动 policy，先让 AMCL 收敛

### 1. 建图

```bash
cd /home/unitree/workspace/xh/Offline_DVST

SLAM_MODE=slam \
AUTOLAUNCH_POLICY=0 \
AUTOLAUNCH_UWB_GOAL=0 \
bash dclp_deploy/robots/unitree_go2/bringup_all.sh
```

建图时建议先确认：

```bash
ros2 topic hz /livox/lidar
ros2 topic hz /scan
ros2 topic hz /odom
ros2 run tf2_ros tf2_echo odom base_link
```

### 2. 保存地图

```bash
cd /home/unitree/workspace/xh/Offline_DVST

MAP_NAME=go2_lab \
bash dclp_deploy/robots/unitree_go2/save_map.sh
```

得到：

- `/abs/path/to/go2_lab.yaml`
- `/abs/path/to/go2_lab.pgm`

### 3. 用 AMCL 载入地图并手动定位

```bash
cd /home/unitree/workspace/xh/Offline_DVST

SLAM_MODE=amcl \
AMCL_MAP=/abs/path/to/go2_lab.yaml \
AUTOLAUNCH_POLICY=0 \
AUTOLAUNCH_UWB_GOAL=0 \
bash dclp_deploy/robots/unitree_go2/bringup_all.sh
```

然后在 RViz2 中：

- 用 `2D Pose Estimate` 设置初始位姿
- 等待 `map -> odom -> base_link` 稳定

可检查：

```bash
ros2 run tf2_ros tf2_echo map base_link
ros2 topic hz /scan
ros2 topic hz /odom
```

### 4. AMCL 收敛后再启动 DCLP policy

```bash
cd /home/unitree/workspace/xh/Offline_DVST

MODEL_PATH=/home/unitree/workspace/xh/Offline_DVST/models/dclp/V1_41lambda1_101.pth \
bash dclp_deploy/robots/unitree_go2/start_policy.sh
```

### 5. 启动 Go2 ZMQ 控制客户端

```bash
cd /home/unitree/workspace/xh/Offline_DVST

bash dclp_deploy/robots/unitree_go2/start_go2_zmq_sport_client.sh
```

### 6. 发送目标点

单目标：

- 直接在 RViz2 使用 `2D Nav Goal`
- 目标话题是 `/move_base_simple/goal`

多目标：

```bash
cd /home/unitree/workspace/xh/Offline_DVST

GOAL_LIST=/abs/path/to/goals.yaml \
bash dclp_deploy/robots/unitree_go2/start_goals_policy.sh
```

### 7. 这条链路的关键原则

- 先建图，再 AMCL
- 先定位收敛，再启动 policy
- 不使用 `start_uwb_policy.sh`
- 不依赖 `/uwbstate`
- 运行 DCLP 时，目标点仍然统一发布到 `/move_base_simple/goal`

## UWB Navigation

Go2 UWB experiments do not require a map. Start the base sensor chain and UWB task:

```bash
SLAM_MODE=slam NO_RVIZ=1 AUTOLAUNCH_POLICY=0 \
  bash dclp_deploy/robots/unitree_go2/bringup_all.sh

MODEL_PATH=/home/unitree/workspace/xh/Offline_DVST/models/dclp/V1_41lambda1_101.pth \
  bash dclp_deploy/robots/unitree_go2/start_uwb_policy.sh
```

`start_uwb_policy.sh` launches:

- `dclp_go2_policy_ros2.py`
- `go2_uwb_ros_goal_bridge.py`, converting `/uwbstate` to `/move_base_simple/goal`
- `go2_zmq_sport_client.py`

## Key Parameters

| Variable | Default | Meaning |
|---|---|---|
| `MODEL_PATH` / `POLICY_MODEL_PATH` | empty or built-in pth if present | DCLP checkpoint path |
| `POLICY_BACKEND` | `pth` | `pth` or `legacy_tf` |
| `POLICY_DEVICE` | `cpu` | PyTorch device for `.pth` backend |
| `POLICY_SCRIPT` | `dclp_go2_policy_ros2.py` | ROS2 DCLP controller |
| `DCLP_LENGTH1/2/WIDTH` | `0.504/0.504/0.4464` | DCLP footprint fields in the 548-D observation |
| `POLICY_SCAN_INVALID_FILL` | `2.0` | Empty DCLP scan-group range |
| `POLICY_MAX_LINEAR` | `0.66` | DCLP max linear speed |
| `POLICY_MAX_ANGULAR` | `0.56` | DCLP max angular speed |
| `POLICY_MAX_LINEAR_ACC` | `2.0` | DCLP linear acceleration limit |
| `POLICY_MAX_ANGULAR_ACC` | `2.0` | DCLP angular acceleration limit |
| `POLICY_CMD_VEL_V_CAP` | `0.66` | Final Go2 linear hard cap |
| `POLICY_CMD_VEL_W_CAP` | `0.56` | Final Go2 angular hard cap |
| `POLICY_STRAIGHTEN_FRONT_GOAL_ANGLE` | `0.20` | Clear-front goals within this target angle suppress yaw bias |
| `POLICY_STRAIGHTEN_FRONT_CLEAR_RANGE` | `1.2` | Minimum front-sector range required before straightening |
| `POLICY_ZMQ_BIND` | `tcp://*:5596` | Policy ZMQ publisher address |
| `GO2_ZMQ_ENDPOINT` | `tcp://192.168.123.222:5596` | Sport client ZMQ subscriber endpoint |
| `GO2_IFACE` | `auto` | Unitree SDK network interface |
| `GO2_GAIT` | `economic` | SportClient gait after startup |

## Topics / TF

| Item | Default |
|---|---|
| Livox point cloud | `/livox/lidar` |
| LaserScan | `/scan` |
| Unitree state | `/sportmodestate` |
| Odometry | `/odom` |
| Goal | `/move_base_simple/goal` |
| UWB input | `/uwbstate` |
| Policy status | `/nav_status` |
| Diagnostic cmd_vel | `/go2_policy/cmd_vel` |
| Real base control | ZMQ `tcp://*:5596` -> `tcp://192.168.123.222:5596` |
| TF | `map -> odom -> base_link -> livox_frame` |

## Stop

Stop only navigation task processes and keep localization running:

```bash
bash dclp_deploy/robots/unitree_go2/stop_nav_task.sh
```

Stop the whole Go2 deploy chain:

```bash
bash dclp_deploy/robots/unitree_go2/stop_stack.sh
```
