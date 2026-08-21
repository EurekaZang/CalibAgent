# Go2 real-robot snapshot — 2026-08-22

This snapshot is the byte-preserving handoff of the real Unitree Go2 work used
by CalibAgent through 2026-08-22.

Included:

- the complete `/home/unitree/lly/p8_real` tree, including all official NAV and
  SHIFT runs present at snapshot time, raw rosbag databases, traces, posteriors,
  frozen configs, input checks, smoke runs, and stack logs;
- the complete DCLP reproduction/deployment tree, including its real-run bags,
  MID360 evidence, deployment source, calibration/model artifacts, and prior
  real Go2 runs;
- localization source, launch files, operator scripts, third-party relocation
  source, the active `scans.pcd`, and the exact active relocation database;
- Livox ROS 2 driver and pointcloud conversion sources used on the robot;
- `SNAPSHOT_METADATA.json` with source roots and upstream source revisions;
- `SNAPSHOT_MANIFEST.sha256`, which covers every snapshot file except itself.

The localization workspace's derived `build/`, `install/`, and compiler `log/`
trees are reproducible products and are not copied. Historical PCD backups not
referenced by the frozen P8 manifests are also excluded; the active map and
relocation database referenced by every formal P8 run are included exactly.

Raw `.db3`, `.pcd`, and `.pth` artifacts are stored with Git LFS. Clone with
Git LFS installed, then verify the handoff from this directory:

```bash
sha256sum --check SNAPSHOT_MANIFEST.sha256
```

The CSV/JSON/JSONL/YAML files remain ordinary Git objects so experiment status,
quality metrics, and provenance can be inspected without downloading bags.
