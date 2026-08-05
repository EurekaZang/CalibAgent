# Long-horizon detector development exposure

This tree preserves the preregistered, negative long-horizon result that
motivated the paired command-response signature detector. The original
absolute-NIS CUSUM was evaluated in four fixed Isaac Lab contexts with 30
independent seeds and 100 monitor commands per context--seed sequence. It
raised a false alarm in 66/120 sequences (55.0%, exact 95% CI
45.65--64.09%) despite zero serious safety events. The frozen verdict is
therefore `NO_GO`.

The failure is retained as an algorithm ablation rather than excluded from
the record. `manifest.json` binds every full source artifact, including the
unpromoted compressed pose traces, by SHA-256. The compact tree includes all
monitor rows needed to recompute sequence-level false alarms and detector
diagnostics. A disjoint-seed confirmatory protocol tests the repaired paired
signature detector without modifying this result.
