# CalibAgent P8：Go2 实机最小实现清单

P8 的实验设计以 `docs/p8_go2_real_deployment_data_handoff_zh.md` 为唯一来源。
本文只列出执行该实验所缺的最小软件，不定义额外流程。

## 1. 当前实现

P8 实机代码位于 `src/calibagent/p8/`，配置位于 `configs/p8/`。已实现 NAV/SHIFT
runner、Go2 ROS 2 backend、fake backend、schedule、append-only recorder、resume、export、
paired-block analyzer 和统一 CLI。狗上入口为 `scripts/p8_experiment.sh`，DCLP planner、
MID360 scan 与 FAST-LIO2 reference 的启动入口为 `scripts/p8_stack.sh`。

## 2. 最小运行链路

运行链包含：

1. Go2 command adapter：发送 `(vx, vy, wz)`，并记录实际发送值和时间戳；
2. reference adapter：输出统一时钟下的 `x, y, yaw` 和 measurement timestamp；
3. trial executor：执行 0.6/0.8/2.0/0.6 s 四阶段 profile；
4. NAV runner：按 schedule 完成 calibration、validation 和两图 navigation；
5. SHIFT runner：按 schedule 完成 monitor、shift、recovery 和 validation；
6. recorder：写入 bag、trial/episode/sequence 表、posterior 和 manifest；
7. analyzer：以 paired block 为单位生成 NAV/SHIFT 指标和置信区间。

命令链固定为：

```text
NAV: planner desired velocity -> calibration transform -> Go2 command adapter
SHIFT trial: scheduled/planner command -> calibration transform -> Go2 command adapter
```

除 policy/planner 和 calibration transform 外，不增加速度限幅、加速度限幅、slew、
反馈修正、避障接管或其他 locomotion 干预。`B0_raw` 跳过 calibration transform。
calibration transform 对 DCLP 的精确零动作做零值透传，避免逆模型改变 policy 的停止
决定；这属于 calibration 接口语义，不引入第三个控制模块。

## 3. 时间与数据合同

- policy、scan、reference、robot state、planned action 和 sent action 都使用消息时间戳；
- 每个 action 记录其输入 scan/reference/state 的 age；
- observation 只使用 trial 的 2.0 s measure window；
- validation observation 不更新 posterior；
- NAV 在两张路线之间不更新 posterior；
- SHIFT 三种方法不共享 observation 或 posterior；
- 每个 planned unit 有稳定 ID，技术重跑使用新的 attempt ID；
- 原始 bag 和表格必须能由时间戳双向定位。

## 4. 配置

冻结文件为：

```text
configs/p8/
├── nav.yaml
├── shift.yaml
├── topic_map.yaml
├── reference_extrinsic.yaml
├── maps/
│   ├── real_offset_slalom.yaml
│   └── real_weighted_arc.yaml
├── commands/
│   ├── nav_*.csv
│   └── shift_*.csv
└── schedules/
    ├── nav_blocks.csv
    └── shift_blocks.csv
```

配置加载后输出 resolved config 和全部输入文件 SHA-256。

## 5. CLI

狗上从仓库根目录调用：

```bash
./scripts/p8_stack.sh start
./scripts/p8_experiment.sh validate-nav
./scripts/p8_experiment.sh validate-shift
./scripts/p8_experiment.sh io-check --duration 60
./scripts/p8_experiment.sh nav <run_id>
./scripts/p8_experiment.sh shift <run_id>
./scripts/p8_experiment.sh resume-nav <run_id>
./scripts/p8_experiment.sh resume-shift <run_id>
./scripts/p8_experiment.sh export /home/unitree/lly/p8_real/<run_id>
./scripts/p8_experiment.sh analyze /home/unitree/lly/p8_real/<run_id>
./scripts/p8_stack.sh stop --with-localization
```

`validate` 只检查实验所需的文件、字段、ID、数量和 hash。`nav`/`shift` 支持从最后
完整 planned unit 继续运行，不覆盖已有记录。技术故障留下 `INVALID` attempt，修复后用
同一 `run_id` 的 resume 命令生成新 attempt；每次启动或恢复的 rosbag 写入新的
`*_part_NN` 目录。

单 block/方法调试示例：

```bash
./scripts/p8_experiment.sh nav nav_b01_b8 --blocks NAV_BLOCK_01 --methods B8_full
./scripts/p8_experiment.sh shift shift_r1_b01_full \
  --shifts R1_command_gain_coupling --blocks SHIFT_BLOCK_01 --methods full
```

实机入口直接发布 `/api/sport/request`，不经过含有额外门控的 `cmd_vel_bridge`。
外置头顶 MID360 的 PointCloud2 输入固定为 `/livox/lidar_pc2`；`/livox/lidar` 是 Livox
`CustomMsg`，不能交给 PointCloud2-to-scan 节点。

## 6. 验证条件

- fake/replay 能完整跑完一个缩小 schedule；
- trial phase、posterior 更新边界和方法隔离符合实验计划；
- NAV/SHIFT 数量检查与计划一致；
- 导出结果可从表格追溯到 bag、config、posterior 和 commit；
- 实机入口输出 policy 输入 age、policy action age 和 sent action age；
- 代码中不存在 policy/calibration 之外的 locomotion 限幅或接管路径。

2026-08-21 的 60 s 实机只读验收：scan 1200 帧、19.995 Hz、最大 age 108.4 ms、
最小有效 beam 917、零有效-beam 帧 0；reference 20.012 Hz、最大 age 103.4 ms；
policy action 24.994 Hz、最大间隔 44.0 ms、结束时接收 age 26.5 ms。
