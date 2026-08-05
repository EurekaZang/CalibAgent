# Frozen 0.40 long-null confirmation

With threshold 0.40 frozen before execution, the paired-signature detector
produces 0/120 false-alarm sequences (exact 95% CI 0--3.03%) across four
stationary contexts, 12,000 monitor trials, and 31,200 s of aggregate
robot-equivalent command time. Every monitor observation is valid and no
serious safety event occurs. The concurrent non-controlling absolute-NIS
CUSUM alarms in 56/120 sequences.

This result confirms long-horizon specificity at 0.40. The corresponding
shift confirmation misses the 95% detection gate for weak gain/coupling
changes, so it is retained as boundary evidence rather than the final detector
setting. `manifest.json` binds the complete source artifact tree.
