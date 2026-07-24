# P7 simulated navigation main report

**Verdict: GO.** The independent 60-seed confirmation was generated from
CalibAgent commit `d988774cf2834e2d8e17ebef0d68817b38360eeb`, Isaac Lab
v2.3.2 commit `37ddf626871758333d6ed89cf64ad702aef127d0`, Isaac Sim
`5.1.0-rc.19+release.26219.9c81211b.gl`, PhysX enhanced determinism, and the
SHA-256-pinned official Go2 flat-policy checkpoint.

The frozen evidence contains three maps, B0 raw/B1 dense/B8 full controls, 60
paired seeds per map, and therefore 540 episode records. Each of the nine
method/map jobs completed in one startup attempt and preserves calibration
rows, a finite posterior, full navigation traces, map geometry, distortion
parameters, planner hashes, logs, and 116 hash-bound artifacts.

## Main result

| Map | B8 success / collision | B8 vs B0 time improvement, 95% CI | B8/B1 mean time ratio | B8/B1 ratio 95% CI |
|---|---:|---:|---:|---:|
| Open field | 100% / 0% | 44.645 s [43.912, 45.315] | 1.0446 | [0.9965, 1.0937] |
| Slalom | 100% / 0% | 39.690 s [38.690, 40.622] | 1.0105 | [0.9539, 1.0714] |
| Narrow corridor | 100% / 0% | 43.948 s [42.486, 45.268] | 0.9901 | [0.8693, 1.1236] |

B8 succeeds on 60/60 seeds in every map with no collision or serious event.
Its worst B8-versus-B0 improvement CI lower bound is 38.69 s. Its worst
B8/B1 mean ratio is 1.0446 against the 1.15 gate, and its worst ratio CI upper
bound is 1.1236 against the 1.25 gate. B8 uses 12 trials versus B1's 30, so the
calibration budget ratio is exactly 0.40. The minimum valid-observation ratio is
99.9586%; maximum abort latency is 20 ms.

## Powered replication and scope

The preceding 30-seed main result had 100% B8 success and no collision, but its
narrow-corridor B8/B1 ratio CI upper bound was 1.2816, narrowly above 1.25.
The 60-seed run uses new seeds 8001–8060. The P7 controller is byte-identical
to the 30-seed frozen controller; effect, noninferiority, budget, validity, and
safety thresholds were not relaxed. The minimum seed gate was raised from 30
to 60 before the independent replication.

P7 supports a downstream-navigation claim in pinned simulation with a fixed
local planner. It is not real-robot navigation evidence and does not replace
P8 hardware validation.
