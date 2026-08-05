# CalibAgent manuscript evidence matrix

Status: **FROZEN FOR OUTLINE — 2026-08-05**

This matrix is the claim ledger for the first manuscript draft. A sentence in
the paper may be no stronger than its row here. `GO` denotes a scoped evidence
gate, not general real-world deployment readiness.

## Primary manuscript claims

| ID | Permitted claim | Independent unit and scale | Machine-readable source | Statistical/evidence rule | Boundary |
|---|---|---|---|---|---|
| C1 | A cross-axis affine command model improves held-out velocity prediction over raw commands and a diagonal affine model on the supplied passive Go2 dataset. | Three leave-one-session-out folds; 61 trials/session; 183 valid trials total. | `evidence/p1_real/baseline_fold_metrics.csv`, `baseline_metrics.csv`, `delivery_verification.json` | Report each held-out session and the pooled RMSE; no population-level p-value from three sessions. | Same date, environment, and robot; passive replay only. |
| C2 | Task-weighted active design reaches the frozen joint RMSE/uncertainty target with fewer trials than LHS, random, Sobol, D-optimal, and active-without-task controls in the registered synthetic families. | Seed is the independent unit; 20 seeds; three families averaged within each seed. | `evidence/p3_main/paired_statistics.json` and sequential records | Paired seed bootstrap CI and one-sided paired Wilcoxon. Primary LHS reduction 39.52%, 12.20 trials saved, 95% CI [10.73, 13.73]. | Synthetic identifiability/sample-efficiency evidence only. |
| C3 | The stopping rule avoids premature stopping and adds two trials after the oracle target in the frozen replay benchmark. | 60 frozen active trajectories. | `evidence/p4_main/summary.json` plus trajectory CSVs | Premature-stop rate 0%; median/p95 extra trials both 2. | Replay result, not hardware stopping latency. |
| C4 | The hard filter rejects every registered injected hazard and the runtime monitor detects every injected fault within the registered bound. | 300 proposal hazards, 20 safe controls, 160 runtime faults. | `evidence/p4_main/summary.json` plus fault traces | Hazard rejection 100%; safe false rejection 0%; maximum recorded latency 0 ms; serious events 0. | Fault injection/replay, not deployment safety certification. |
| C5 | Twelve-trial active calibration reduces held-out velocity RMSE across four pinned Isaac Lab scenarios. | Paired simulator seed; 20 seeds/scenario; 12 calibration trials and 8 held-out commands. | `evidence/p5_main/summary.json`, scenario seed metrics and traces | Paired 95% improvement CI must remain above zero; reductions are 9.30%–31.70%. | Fixed policy in Isaac Lab/PhysX; no sim-to-real claim. |
| C6 | Under four registered in-place shifts, the full method detects the shift and improves early-window post-shift RMSE over passive updating while meeting the absolute terminal RMSE gate. | Paired simulator seed; 72 seeds/shift; frozen/passive/full controls. | `evidence/p6_strong_confirmatory/summary.json` and recovery curves | 4,000-sample paired bootstrap, one-sided paired Wilcoxon, exact binomial rate intervals. Early passive-minus-full effects 0.00761–0.01691, all CIs > 0. | Do not claim terminal superiority over passive; no arbitrary-shift or real-robot recovery claim. |
| C7 | After retaining a failed first confirmation and correcting the high-rate guard, a prospectively frozen disjoint replication shows that B8 navigation beats raw control and is noninferior to dense and matched-budget controls on registered simulator endpoints. | Paired simulator seed; 6 maps × 7 methods × 72 seeds = 3,024 episodes. | `evidence/p7_strong_confirmatory_v2/summary.json`, episode metrics and traces | Exact rate CIs and 4,000-sample paired bootstrap; registered noninferiority margins. | Claim rests on the second replication, not the failed first confirmation; no real navigation claim. |

## Exact result anchors

| Evidence block | Values approved for prose/figures |
|---|---|
| P1 passive Go2 | Pooled RMSE: raw 0.06605, M0 0.04563, M1 0.03009; M1 reductions 54.45% vs raw and 34.07% vs M0. Session M1 RMSE: 0.02888, 0.03158, 0.02974. The 30-trial LHS M1 is 3.33% above the 122-trial dense M1 reference (0.02912). |
| P3 sample efficiency | Active 18.67 trials. LHS 30.87 (39.52% reduction), random 30.67 (39.13%), Sobol 25.72 (27.41%), D-optimal 23.00 (18.84%), no-task 25.67 (27.27%). Final active RMSE 0.008462 vs dense 0.007916; predictive coverage 94.14%. |
| P4 safety/stopping | 60/60 trajectories; 0% premature stops; median/p95 extra trials = 2/2. 300/300 hazards rejected, 0/20 safe controls rejected, 160 runtime faults, 0 ms maximum recorded abort-detection latency, 0 serious events. |
| P5 closed-loop simulation | RMSE raw→calibrated: affine 0.15199→0.10635; deadzone 0.15054→0.10282; friction+payload 0.10741→0.09742; rough 0.09554→0.07849. Paired absolute-improvement CIs: [0.04290, 0.04780], [0.04495, 0.05002], [0.00981, 0.01017], [0.01477, 0.01889]. |
| P6 shift recovery | Early passive-minus-full RMSE mean [95% CI]: friction+payload 0.00761 [0.00537, 0.00981]; gain recoupling 0.00974 [0.00804, 0.01145]; mixed 0.01691 [0.01536, 0.01848]; payload/COM 0.01012 [0.00825, 0.01194]. Full terminal RMSE means 0.12241, 0.11694, 0.11010, 0.10898. Worst p95 detection/recovery delay: 4/6 trials. |
| P7 navigation | B8 success: 1.0 on five maps and 70/72 = 0.9722 on weighted arc; collision count 0 on every B8 map. B8/raw completion-time gain CIs range from [23.453, 26.736] to [32.675, 34.924] s. Worst B8/dense ratio CI upper 1.0736; worst matched-budget ratio CI upper 1.0901. |

## Required narrative around failed confirmations

The results section must state that P5, P6, and P7 contain retained failed or
development attempts. For P7, the manuscript must describe this sequence:

1. the first frozen strong confirmation failed registered navigation gates;
2. trace inspection identified a 10 Hz base-height guard blind interval;
3. a 50 Hz predictive height interlock was developed and frozen; and
4. the positive result comes from new maps and seeds in the later prospective
   replication.

This history is scientific evidence about the correction process and cannot be
collapsed into an unqualified “all experiments passed” statement.

## Prohibited claims until P8 closes

- online active calibration has been demonstrated on a real Go2;
- real-robot domain-shift detection or recovery has been demonstrated;
- real-robot navigation improves after CalibAgent calibration;
- the simulator safety results establish deployment safety;
- CalibAgent is robust to arbitrary terrain, payload, hardware, or controller
  shifts;
- sim-to-real transfer has been established;
- CalibAgent is the first online quadruped adaptation method;
- the full P6 method is terminally superior to passive updating.

## Planned P8 insertion points

P8-NAV now covers only Weighted Arc and Offset Slalom on hardware. P8-SHIFT
retains R1 command gain/coupling, R2 payload/COM, R3 surface friction, and R4
mixed context. When—and only when—the registered artifacts pass audit, the
paper can replace the current passive-real/simulation bridge with direct
hardware evidence in the abstract, results, and conclusion.
