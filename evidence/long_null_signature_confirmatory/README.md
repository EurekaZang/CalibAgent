# Paired-signature long-null development confirmation

This disjoint-seed Isaac Lab exposure evaluates the paired command-response
signature detector in four stationary contexts. The frozen 0.70 detector
records 0/120 false-alarm sequences (exact 95% CI 0--3.03%) across 12,000
monitor trials and 31,200 s of aggregate robot-equivalent command time. Every
sequence has 100% valid monitor observations, with zero serious safety events.
The original absolute-NIS CUSUM, logged concurrently without controlling
adaptation, alarms in 45/120 sequences.

After the independent shift pilot identified 0.40 as the sensitivity needed
for the weakest shifts, replay of the frozen signatures at 0.40 also yields
0/120 alarms. This is development evidence used only to choose the final
threshold; a new seed block is frozen for confirmation. `manifest.json` binds
the complete source tree, including unpromoted compressed pose traces.
