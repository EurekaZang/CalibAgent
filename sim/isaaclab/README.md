# CalibAgent Isaac Lab external project

This directory is the P5 simulator adapter. It is launched by a compatible
Isaac Lab checkout rather than imported by the analysis Python environment.

Frozen compatibility:

- Isaac Lab `v2.3.2`, commit
  `37ddf626871758333d6ed89cf64ad702aef127d0`;
- Isaac Sim `5.1.0`;
- official Unitree Go2 flat/rough assets and published locomotion checkpoints;
- PhysX GPU simulation.

The runner uses the official manager-based locomotion scene as a fixed
low-level controller. CalibAgent remains outside the RL environment: it
selects safe velocity experiments, injects the declared Tier-A command
distortion when configured, processes root-pose measurements, and updates its
posterior. Tier-B scenarios change physical friction, payload/COM, and terrain.

Run the full paired 20-environment suite from the repository root:

```bash
PYTHONPATH=src .venv/bin/python -m calibagent.cli.run_p5_isaaclab \
  --config configs/experiments/p5_isaaclab_main.yaml \
  --isaaclab-root /path/to/IsaacLab-v2.3.2
```

The host launcher rejects any Isaac Lab commit, Isaac Sim version, or policy
hash that differs from the frozen configuration.
