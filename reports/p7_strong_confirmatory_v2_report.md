# P7 strong-confirmatory replication report

## Verdict

**GO for the scoped simulator navigation claim after a prospective
replication.** The successful frozen run passed all 14 registered gates on six
new maps, 72 new paired seeds per map, and seven controls. The audit recomputed
every primary endpoint from 3,024 episode records, scanned all 42
full-resolution navigation traces, validated posterior/launch artifacts, and
verified all 566 source-artifact hashes.

The first strong-confirmatory run remains a versioned `NO_GO`; it is not
silently pooled, relabeled as a pilot, or omitted.

## Failure, correction, and replication chronology

1. The first frozen run at source commit `8f3c256` failed four primary gate
   groups. B8 success was 68/72 on `confirm_dual_gate` and 50/72 on
   `confirm_loaded_arc`; some time-ratio CI upper bounds reached 1.347.
2. Trace diagnosis found a 10 Hz guard blind interval: base height could cross
   the 0.15 m hard limit in 60–80 ms. A 50 Hz predictive height interlock was
   introduced without relaxing the hard safety envelope.
3. Five explicitly development-only pilots selected the interlock setting.
   Failed and intermediate settings remain documented.
4. Commit `2a25201` froze a new confirmatory protocol before execution: six
   disjoint maps, seeds 10501–10572, and new simulator seeds. Git ancestry,
   rather than the human-entered wall-clock labels, is the authoritative
   ordering record.

This sequence prevents the corrected result from being represented as the
original confirmation. The positive claim rests on the later, disjoint
replication.

## Frozen replication design

- Source commit: `2a25201e7e20042a5a471062b186ed8bebb93b35`
- Isaac Lab: `37ddf626871758333d6ed89cf64ad702aef127d0`
- Methods: raw B0, dense B1, matched-budget LHS B2, Sobol B3, D-optimal B4,
  active-without-task B5, and full B8
- Calibration trials: B1 = 30; B2/B3/B4/B5/B8 = 12
- Independent unit: paired simulator seed; 72 per map
- Primary navigation endpoints: success, collision, completion time
- Inference: exact Clopper–Pearson rate intervals and 4,000-sample paired
  bootstrap intervals
- Registered noninferiority margin: 0.05 for success/collision; completion-time
  ratio CI upper bound ≤ 1.25

Calibration-validation RMSE is retained as a diagnostic. It cannot override a
failed downstream navigation endpoint.

## Results

| New map | B8 success (exact lower) | Collision (exact upper) | B8 − raw time gain 95% CI [s] | B8/dense mean (CI upper) | Worst matched CI upper |
|---|---:|---:|---:|---:|---:|
| double chicane | 1.000 (0.950) | 0.000 (0.050) | [32.675, 34.924] | 0.984 (1.023) | 1.048 |
| extended lane | 1.000 (0.950) | 0.000 (0.050) | [23.453, 26.736] | 1.037 (1.074) | 1.090 |
| narrow lane | 1.000 (0.950) | 0.000 (0.050) | [26.057, 28.692] | 0.999 (1.037) | 1.079 |
| offset slalom | 1.000 (0.950) | 0.000 (0.050) | [30.058, 31.931] | 0.981 (1.017) | 1.049 |
| S-bend | 1.000 (0.950) | 0.000 (0.050) | [28.897, 30.999] | 1.036 (1.069) | 1.063 |
| weighted arc | 0.972 (0.903) | 0.000 (0.050) | [25.364, 29.060] | 0.962 (1.006) | 1.069 |

The minimum B8 success rate was 70/72 = 0.9722, every collision count was
0/72, the worst B8/dense completion-time CI upper bound was 1.0736, and the
worst B8/matched-baseline upper bound was 1.0901. The minimum valid-observation
ratio was 0.99969, maximum abort latency was 20 ms, and serious events were 0.

![P7 strong-confirmatory replication](figures/p7_strong_confirmatory_v2.png)

## Independent evidence audit

The audit independently verifies:

- the 566-entry source manifest, config/policy/runtime locks, and frozen commit;
- six maps × seven methods × 72 unique seeds, with the registered calibration
  budget for each control;
- identical planner hashes across methods;
- exact success/collision bounds and all paired time, success, collision, and
  matched-control noninferiority intervals;
- held-out calibration-validation coverage without treating it as a primary
  navigation endpoint;
- one successful launch per method/map, finite serialized posteriors, finite
  unique trace samples, and zero serious safety events.

## Claim boundary

Supported wording:

> After retaining an initial failed confirmation and correcting a trace-identified
> controller defect, a prospectively frozen replication on disjoint maps and
> seeds showed that budgeted B8 navigation outperformed raw control and was
> noninferior to dense and matched-budget controls under the registered
> simulator endpoints.

Not supported:

- that the first strong confirmation passed;
- that threshold-selection pilots are confirmatory evidence;
- superiority to every matched method on every secondary calibration metric;
- real-robot navigation, sim-to-real robustness, or deployment safety.
