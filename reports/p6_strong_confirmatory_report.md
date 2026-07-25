# P6 strong-confirmatory report

## Verdict

**GO for the scoped simulator claim.** The frozen confirmatory protocol passed
all 15 registered gates on four held-out domain shifts, 72 paired seeds per
shift, and the `frozen`/`passive`/`full` controls. The independent audit
recomputed the registered endpoints from per-seed records, scanned every
full-resolution pose trace, and verified all 158 source-artifact hashes.

This result supports a narrow claim: under the pinned Isaac Lab/PhysX Go2
setup, the full method detects the registered in-place shifts and improves
early post-shift RMSE over passive updating while meeting an absolute terminal
RMSE gate. It does not establish real-robot recovery or terminal superiority
over passive updating.

## Frozen design

- Source commit: `8f3c256a592a6133ac6fe3f206b5ef901b37f417`
- Isaac Lab: `37ddf626871758333d6ed89cf64ad702aef127d0`
- Isaac Sim: `5.1.0-rc.19`
- Independent unit: paired simulator seed
- Sample size: 4 shifts × 72 seeds × 3 controls
- Primary recovery window: trials 4–9, with a preregistered `0.25` penalty for
  a missing rolling-RMSE window
- Inference: 4,000-sample paired bootstrap and one-sided paired Wilcoxon test;
  exact Clopper–Pearson intervals for rates
- Safety: hard envelope, maximum registered abort latency 40 ms, zero serious
  events required

## Results

| Held-out shift | Detection (exact lower) | Recovery (exact lower) | Passive − full early RMSE, mean [95% CI] | One-sided p | Full final RMSE, mean [95% upper] |
|---|---:|---:|---:|---:|---:|
| friction + payload | 1.000 (0.950) | 1.000 (0.950) | 0.00761 [0.00537, 0.00981] | 4.56e-9 | 0.12241 [upper 0.12564] |
| gain recoupling | 1.000 (0.950) | 1.000 (0.950) | 0.00974 [0.00804, 0.01145] | 2.02e-12 | 0.11694 [upper 0.11978] |
| mixed context | 1.000 (0.950) | 1.000 (0.950) | 0.01691 [0.01536, 0.01848] | 8.29e-14 | 0.11010 [upper 0.11247] |
| payload/COM only | 0.986 (0.925) | 1.000 (0.950) | 0.01012 [0.00825, 0.01194] | 3.34e-12 | 0.10898 [upper 0.11234] |

Across shifts, the worst p95 detection and recovery delays were 4 and 6 trials.
The lowest full-versus-frozen final-improvement CI lower bound was 0.01677.
The minimum valid-observation ratio was 0.9364, maximum observed abort latency
was 20 ms, and serious safety events were 0.

![P6 strong-confirmatory effects](figures/p6_strong_confirmatory.png)

## Independent evidence audit

The audit does not trust the producer's root `GO` field. It independently:

1. verifies all 158 original SHA-256 records, the source config hash, source
   commit, policy checkpoint, Isaac runtime, and GPU/driver metadata;
2. checks the complete scenario/method/seed Cartesian product and rejects
   duplicate or non-finite per-seed records;
3. reconstructs early recovery from the recovery curves, including missing
   window penalties, then reruns the paired bootstrap and Wilcoxon test;
4. recomputes exact false-alarm, detection, and recovery intervals and every
   registered aggregate gate;
5. scans all 12 compressed pose traces for unique sample keys, finite state,
   exact row/seed coverage, shift identity, abort response, and serious events.

The versioned compact evidence contains every non-trajectory artifact. Its
trace receipt is bound to the original trajectory hashes in
`source_manifest.json`; mounting the full supplemental archive and running
`calibagent-audit-strong --raw` repeats the complete trace scan.

## Claim boundary

Supported wording:

> In pinned simulation across four held-out in-place domain shifts, active
> recovery improved preregistered early-window RMSE over passive updating and
> satisfied detection, recovery, terminal-accuracy, and safety gates.

Not supported:

- terminal RMSE superiority over passive updating;
- recovery on arbitrary or unregistered shifts;
- sim-to-real transfer or online real-Go2 recovery.
