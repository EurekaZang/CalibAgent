# Phase 2 ICRA paper outline

Status: **SUPERSEDED BY THE CURRENT Q1--Q4 MANUSCRIPT — 2026-08-20**

This outline is retained as a historical structure artifact. It must not
override `paper/main.tex` or claim manifest 2.0, and it must not reintroduce
development chronology into the publication.

## Structure pattern

Compact empirical conference paper: problem-driven introduction, integrated
related work, method, registered experiments, results, limitations, and
conclusion. The target is approximately 3,500 body words plus a 160-word
abstract, four compact figures, and references within the ICRA eight-page total
limit.

## Narrative overview

The paper begins from a practical mismatch: a quadruped may be stable while its
high-level velocity command interface is inaccurate, coupled, and mutable. It
then separates CalibAgent from policy adaptation and classical manipulator
calibration. The method is presented as a closed, auditable loop: probabilistic
command modeling, task-weighted command selection, non-learned safety,
validation-based stopping, constrained inverse compensation, and
shift-triggered recovery. The experiments deliberately climb an evidence
ladder from passive Go2 measurements through synthetic controls and
fault-injection to pinned Isaac Lab calibration, shifts, and downstream
navigation. The discussion states exactly what remains unproven until P8.

## Detailed outline

### Abstract (~160 words)

**Purpose:** State the problem, method, strongest quantitative evidence, and
hardware boundary without treating P8 as completed.

**Content:**

- Opaque velocity controllers can preserve balance while distorting requested
  planar motion.
- CalibAgent learns a compact probabilistic command-to-motion map and chooses
  task-relevant calibration trials under an independent safety envelope.
- Lead with P3 sample efficiency, then P5–P7 simulator scale, and include P1 as
  passive real evidence.
- End with a scoped statement: existing results establish a reproducible
  calibration/recovery pipeline in simulation and passive real-Go2 model need;
  active real-world deployment remains the P8 experiment.

**Evidence:** C1, C2, C5, C6, C7.

### I. Introduction (~520 words)

**Purpose:** Define command-interface calibration as a distinct, consequential
problem and state the bounded contribution.

**Content:**

1. A learned or proprietary locomotion controller exposes desired
   \(u=[v_x,v_y,\omega_z]\), but realized steady motion can show gains,
   cross-axis coupling, dead zones, and context dependence.
2. Passive dense calibration wastes hardware trials away from the navigation
   task; blind online updating lacks a principled stopping criterion.
3. Closest work covers task-oriented manipulator calibration, passive
   command-motion learning, or policy adaptation, but the located literature
   does not close this precise combination.
4. State the research question and four contributions from the confirmed paper
   configuration.
5. End with the evidence ladder and an explicit statement that P8 hardware
   active deployment is not yet a result.

**Sources:** Carrillo 2013; Attia 2018; Taouil 2023; Kumar 2021; Fey 2024; Li
et al. 2026.

**Transition:** The problem sits between calibration, experimental design, and
legged adaptation, so the next section distinguishes these bodies of work.

### II. Related Work (~420 words)

#### A. Robot calibration and task-oriented experiment design

- Classical observability, optimal excitation, and sequential pose selection.
- Parameter-space D-optimality versus task-/goal-space uncertainty.
- Position CalibAgent as predictive task-command calibration, not kinematic
  parameter identification.

**Sources:** Hollerbach 1996; Calafiore 2001; Sun 2008a/b; Carrillo 2013;
Krause 2008; Attia 2018.

#### B. Command models and legged adaptation

- Passive velocity-control kinematic calibration and black-box quadruped
  motion models.
- Policy-level and model-based online legged adaptation.
- Explicitly acknowledge 2026 rapid embodiment adaptation and avoid broad
  priority claims.

**Sources:** Li & Stückler 2022; Taouil 2023; Sun et al. 2021; Kumar 2021;
Fey 2024; Li et al. 2026.

**Transition:** These precedents motivate a method that targets uncertainty in
deployment commands while leaving the low-level locomotion controller fixed.

### III. CalibAgent (~1,050 words)

#### A. Probabilistic command-to-motion model

**Purpose:** Specify the estimand, feature map, observation model, and posterior
update reproducibly.

- Command \(u\in\mathbb{R}^3\); robust steady body velocity observation
  \(y\in\mathbb{R}^3\) with per-trial covariance.
- M2 fixed feature vector: intercept, three affine terms, three pairwise
  products, and positive/negative hinge terms per axis.
- Reference-grid standardization is frozen before sequential trials to prevent
  outcome leakage.
- Three independent Bayesian linear regressions with fixed diagonal process
  noise plus measurement covariance.
- Give the information-form posterior equations and predictive covariance.

**Evidence/code anchors:** `features.py`, `bayesian.py`,
`configs/model/m2_basis_blr.yaml`.

#### B. Task-weighted integrated variance reduction

**Purpose:** Derive the trial-selection objective and distinguish it from
parameter-space D-optimality.

- A frozen task grid \(\{g_j,w_j\}\) represents expected deployment commands.
- For candidate feature \(\phi(c)\), sum the closed-form reduction in
  predictive epistemic variance over task points and output axes.
- Rank a finite safe candidate pool; subtract optional frozen risk and motion
  costs; exclude near-duplicates.
- For batches, update covariance with outcome-independent fantasies.
- State that the main planner uses 512 candidates, an eight-command seed design,
  a 400-point task grid, and 0.025 normalized duplicate distance.

**Sources:** Carrillo 2013; Attia 2018; Krause 2008.
**Evidence/code anchors:** `ivr.py`, `task.py`, `candidates.py`, planner config.

#### C. Safety, stopping, compensation, and shift recovery

**Purpose:** Show that learned ranking cannot override execution constraints.

- Hard safety filter checks state, command bounds, coupled load, slew,
  workspace projection, localization, battery, pose, and base height before
  execution; runtime monitoring can zero commands independently.
- Stop only after minimum trials, coverage, held-out validation, and repeated
  uncertainty/accuracy or low-gain confirmation; hard time, distance, battery,
  and trial budgets dominate.
- The inverse compensator searches the same bounded candidate space for a safe
  command minimizing predicted task error, regularization, and posterior risk.
- A one-sided CUSUM on normalized innovation energy requires accumulated,
  repeated evidence and latches the shift; recovery inflates epistemic
  covariance and resumes bounded active trials.
- Describe the independent 50 Hz monitor as part of the frozen authorization
  architecture.

**Evidence/code anchors:** `filter.py`, `rules.py`, `inverse.py`, `detector.py`.

**Figure 1:** TikZ system diagram of the nominal loop and shift-recovery branch.

**Transition:** The components imply distinct claims, so the experiments are
organized as a staged evidence ladder rather than a single pooled benchmark.

### IV. Experimental Design (~450 words)

**Purpose:** Define independent units, controls, frozen protocols, and the
real/synthetic/simulator boundary.

#### A. Passive hardware and synthetic controls

- P1: 183 valid Unitree Go2 trials, three 61-trial sessions, Livox MID360
  FAST-LIO/global localization, leave-one-session-out evaluation.
- P3: 20 disjoint seeds; three synthetic distortion families averaged within
  seed; LHS, random, Sobol, D-optimal, no-task, and dense controls.

#### B. Safety and pinned simulation

- P4 replay/fault injection scale.
- P5: four scenarios × 20 paired seeds, 12 calibration trials, eight validation
  commands.
- P6: four held-out shifts × 72 paired seeds × frozen/passive/full.
- P7: six new maps × seven methods × 72 seeds; 30-trial dense and 12-trial
  matched/full budgets; 3,024 episodes.
- Isaac Lab/Sim version, commit, GPU/driver, seed isolation, hash manifests,
  paired bootstrap, exact rate intervals, and retained failures.

**Sources:** Mittal 2025; Rudin 2022.

**Transition:** The result order follows the same ladder: model need, trial
efficiency, safeguards, closed-loop calibration, recovery, then task outcome.

### V. Results (~820 words)

#### A. Calibration model and trial efficiency

- P1 raw/M0/M1 held-out RMSE per session and pooled.
- P3 trials-to-target with paired CIs and dense-oracle final accuracy.
- P5 paired raw-to-calibrated RMSE for four scenarios.

**Figure 2:** Three-panel calibration figure sourced only from P1/P3/P5
machine-readable artifacts.

**Claims:** C1, C2, C5.

#### B. Safety, stopping, and shift recovery

- Compact P4 numerical paragraph/table.
- P6 early passive-minus-full forest plot, terminal RMSE intervals, detection
  and recovery rates/delays.
- State plainly that terminal passive superiority is not tested/supported.

**Figure 3:** P6 early effect and terminal-accuracy forest panels.

**Claims:** C3, C4, C6.

#### C. Navigation consequence and prospective replication

- Describe the frozen final interlock, disjoint maps and seeds, and registered
  endpoints before giving the navigation results.
- Report B8 success/collision, B8-vs-raw time gains, dense noninferiority, and
  matched-budget noninferiority over all six maps.
- Calibration RMSE remains diagnostic and cannot rescue a failed navigation
  endpoint.

**Figure 4:** Six-map success heatmap plus completion-time and noninferiority
panels.

**Claims:** C7.

**Transition:** The evidence supports the method under registered conditions,
but its hardware generality remains sharply bounded.

### VI. Discussion and Limitations (~280 words)

**Purpose:** Interpret what task weighting changes and define the remaining
scientific risk without defensive prose.

- P3 no-task and D-optimal controls isolate task weighting from generic active
  selection.
- P7 establishes that held-out command RMSE is not a substitute for downstream
  navigation endpoints.
- The system complements rather than replaces policy adaptation: it calibrates
  the exposed command layer.
- P1 is passive, same-day, single-robot data; P5–P7 are pinned simulation.
- P8 must test active Go2 calibration, four structured shifts, and navigation
  on Weighted Arc and Offset Slalom before any sim-to-real or deployment claim.
- The compact basis may not cover strongly dynamic, history-dependent, or
  gait-switching command responses.

**Sources:** Taouil 2023; Kumar 2021; Fey 2024; Li et al. 2026.

**Transition:** The conclusion restates the demonstrated contribution at this
exact level.

### VII. Conclusion (~160 words)

**Purpose:** Answer the research question with evidence-calibrated language.

- CalibAgent provides an auditable task-aware calibration and shift-recovery
  architecture for an opaque quadruped velocity interface.
- Existing evidence supports passive real-Go2 model need, synthetic sample
  efficiency, simulator closed-loop improvement, registered shift recovery,
  and navigation consequence.
- Hardware active deployment remains the planned P8 closure experiment.

## Evidence-to-section map

| Section | Internal evidence | Literature role |
|---|---|---|
| Introduction | C1–C7 scope only | Problem, nearest work, bounded gap |
| Related work | None | Calibration/OED, command models, adaptation |
| Method | Unit tests/configs/source | Mathematical and architectural provenance |
| Experimental design | Registry, configs, manifests | Simulator/tool provenance |
| Results A | C1, C2, C5 | Comparison framing only |
| Results B | C3, C4, C6 | Shift-adaptation context |
| Results C | C7 | Black-box navigation context |
| Discussion | All claim boundaries | Contrast with closest work |
| Conclusion | C1, C2, C5–C7 | No new claims |

## Word-count summary

| Section | Target words |
|---|---:|
| Abstract | 160 |
| Introduction | 520 |
| Related work | 420 |
| CalibAgent method | 1,050 |
| Experimental design | 450 |
| Results | 820 |
| Discussion and limitations | 280 |
| Conclusion | 160 |
| **Body total excluding abstract** | **3,700** |

The page allocation, not word count alone, is the controlling ICRA constraint.
Figure heights will be tuned after the first compiled draft. If the initial PDF
exceeds eight pages, text compression will begin in related work and protocol
detail; claim-defining limitations and statistical units will not be removed.

## Author approval gate

Academic-research-suite requires explicit approval of this outline before the
argument blueprint and manuscript draft are written. Approval freezes the
section order, evidence assignment, and current claim boundary; later P8 data
can still be inserted through the declared replacement points.
