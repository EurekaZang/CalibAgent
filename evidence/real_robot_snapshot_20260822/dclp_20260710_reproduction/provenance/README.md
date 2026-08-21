# Provenance

复制来源：`/home/unitree/workspace/xh/Offline_DVST` 和本地 Claude file-history session `d23ea13c-8362-427a-89a9-93d2fbbeb386`。

关键未修改快照：

| 文件 | SHA256 | 含义 |
|---|---|---|
| `historical_snapshots/core/dclp_deploy_core_v3.py` | `df6c78b263454c8bf8fb616de9dff7d268f6f48fe40127c299dd56455464e7de` | 270° scan 分配最终 core |
| `historical_snapshots/policy/dclp_go2_policy_ros2_v3.py` | `215175cd7f7a7c960d637802aff528a38407b0ab0a7875a256e6c8239d5b7b7d` | 正确 range mapping + dt limiter，guard 前 |
| `historical_snapshots/policy/dclp_go2_policy_ros2_v4.py` | `f6768172ee30d71192f8cd1392967d993e6b065216c2866ef04ff12c93a750bb` | guard 后 policy |
| `historical_snapshots/launcher/start_dclp_nav_final_041531.sh` | `17c934f00f16cd7f4f4090cc263064ea2b9c67c41a7347db055b6304d24a5075` | 04:15:31 最终历史 launcher，含最终几何 |
| `models/dclp/V1_41lambda1_101.pth` | `dacaf9fc45da536ae6b45cdbedc949370b7828fac4cadcf40ebedabc4080c452` | model101 |

`historical_snapshots/launcher/start_dclp_nav_v10.sh` 仍是修改几何前的 `.42/.42/.372`，不能当作最终 launcher；最终原件单独保存为 `start_dclp_nav_final_041531.sh`。

活动文件 `dclp_deploy/robots/unitree_go2/start_dclp_nav.sh` 和 `dclp_go2_policy_ros2.py` 是复现 instrumentation 版本，不与历史原件逐字节相同。它们只在 qyw 副本内增加 profile 模式、安全门、rosbag、有效配置指纹、guard 诊断和旧控制模式选择。历史原件保留在本目录用于核对。

没有 git commit 可引用：来源目录不是 Git worktree，因此以本地历史快照、时间戳和 SHA256 为准。

未复制：运行日志、旧轨迹、PID、`__pycache__`、`.pyc`、TurtleBot2/ROS1 部署，以及源目录中误生成的五个 0-byte `--duration/--max-age-ms/--min-rate/--topic/--type` 文件。
