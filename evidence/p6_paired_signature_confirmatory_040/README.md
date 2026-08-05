# Frozen 0.40 shift confirmation

This disjoint 72-seed-per-context confirmation is retained with its frozen
`NO_GO` verdict. Threshold 0.40 detects 68/72 gain/coupling, 72/72
friction/payload, 72/72 mixed-context, and 71/72 payload/COM shifts. The
minimum rate (94.44%, exact 95% CI 86.38--98.47%) misses the 95% rate gate and
the 0.90 lower-confidence gate. All other aggregate gates except the coupled
rate-confidence check pass, including early active-over-passive recovery,
terminal accuracy, safety, and finite outputs.

Replay of unchanged monitor signatures at threshold 0.30 detects 71/72,
72/72, 72/72, and 72/72 respectively. Because recovery depends on alarm
timing, no 0.30 recovery result is inferred from this run; a new seed block is
required. `manifest.json` binds every full source artifact.
