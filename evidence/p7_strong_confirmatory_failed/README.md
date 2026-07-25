# P7 strong-confirmatory failure snapshot

This directory is an immutable, publication-facing snapshot of the first
strong P7 confirmatory execution. It is a **negative result** and must never be
pooled with a later confirmatory run.

- Frozen source config:
  `configs/experiments/p7_navigation_strong_confirmatory.yaml`
- Source commit: `8f3c256`
- Independent units: 72 paired simulator seeds per map
- Coverage: six held-out maps, seven methods, 3,024 navigation episodes
- Frozen verdict: `NO_GO`

The root and per-map summaries, the complete paired episode tables and all
held-out calibration-validation records are retained here. `source_manifest.json`
is the original run manifest and records SHA-256 hashes for the complete
write-once output, including the large raw navigation traces. The full
612 MiB trace tree remains in the local write-once output at
`outputs/p7_strong_confirmatory/`; it is not duplicated in this compact
repository snapshot.

The failure is not attributed to collision, numerical failure or a serious
simulator safety event. The primary observed failure mode is a hard-envelope
base-height abort occurring between 10 Hz planner ticks. The development fix
and any later confirmation must use disjoint output roots and must retain this
snapshot unchanged.
