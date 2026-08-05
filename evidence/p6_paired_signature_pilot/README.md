# Paired-signature threshold pilot

This eight-seed-per-context pilot is deliberately retained with its frozen
`NO_GO` verdict. The paired-signature detector at distance threshold 0.70
detects only 2/8 gain/coupling and friction/payload shifts and 3/8 payload/COM
shifts, while detecting 8/8 mixed-context shifts. It produces no pre-shift
false alarms and no serious safety events.

A declared threshold sensitivity replay on the unchanged monitor signatures
shows that 0.40 satisfies the two-of-four evidence rule for 32/32
context--seed shifts. Recovery outcomes from missed 0.70 alarms are not
reinterpreted. The threshold is tested again in disjoint long-null and shift
confirmatory seed blocks. `manifest.json` binds all full source artifacts.
