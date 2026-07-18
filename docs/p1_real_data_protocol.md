# P1 real Go2 replay protocol

P1 real evidence must originate from raw, timestamped Unitree Go2 trials. A
fixture, simulator rollout, retargeted trajectory, or manually authored
manifest is not real-robot evidence.

The input CSV contains one row per reference-pose sample and the columns
`trial_id`, `session_id`, `timestamp`, `cmd_vx`, `cmd_vy`, `cmd_wz`, `pose_x`,
`pose_y`, and `pose_yaw`. Optional context columns are `terrain_id`,
`payload_kg`, `battery_ratio`, and `gait_id`. Timestamps must be monotonic within
each trial, commands constant during the measurement window, and sampling must
satisfy the common measurement quality gates.

Collect at least three independent sessions and 150 valid trials spanning both
signs of every command axis. Preserve the raw reference output from LiDAR
odometry or motion capture; do not label onboard state estimation as ground
truth. Build the evidence bundle with:

```bash
calibagent-real-replay path/to/go2_raw_trials.csv \
  --output outputs/p1_real \
  --source-kind real_robot \
  --robot-model unitree_go2 \
  --reference-sensor lidar_odometry \
  --budget 30
```

The command copies the raw table into the evidence bundle, processes every
trial through `MeasurementPipeline`, performs a session-grouped baseline split,
and records SHA-256 hashes. Using `--source-kind synthetic_fixture` is supported
for integration tests but is rejected by the publication audit.
