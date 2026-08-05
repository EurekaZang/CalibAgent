# Phase 3 argument blueprint

Status: **COMPLETE — 2026-08-05**

## Central thesis

CalibAgent makes calibration of an opaque quadruped velocity interface
task-efficient and operationally auditable by combining a compact Bayesian
command-to-motion model with task-weighted active trial selection, independent
hard safety and stopping rules, and shift-triggered bounded recovery. The
current evidence supports this thesis for passive real-Go2 model identification
and registered synthetic and Isaac Lab experiments; active hardware deployment
remains the P8 test.

## Sub-arguments

### A1. The exposed velocity interface requires a coupled calibration model

- **Claim:** Stable locomotion does not imply that requested planar velocity is
  realized accurately or independently along each command axis.
- **Evidence:** On 183 passive Go2 trials, M1 reduces pooled held-out RMSE from
  0.06605 for raw commands and 0.04563 for M0 to 0.03009; the ordering holds in
  each leave-one-session-out fold.
- **Literature:** Li and Stückler calibrate velocity-control kinematic models;
  Taouil et al. learn motion models for a black-box quadruped controller.
- **Reasoning:** A diagonal correction cannot account for the cross-axis
  response observed in held-out data, so downstream compensation needs a
  coupled map.
- **Counter-argument:** Three same-day sessions on one robot can reflect a
  local artifact rather than a general interface problem.
- **Response:** Treat P1 as evidence of model need in this robot/session scope,
  not as a cross-robot generalization. P8 supplies the missing cross-context
  active hardware test.

### A2. Task weighting reduces trials by spending information where deployment uses it

- **Claim:** Task-weighted predictive variance reduction reaches the registered
  calibration target with fewer trials than passive designs, parameter-space
  D-optimality, and active selection without task weighting.
- **Evidence:** Across 20 independent synthetic seeds, CalibAgent uses 18.67
  trials versus 30.87 LHS, 30.67 random, 25.72 Sobol, 23.00 D-optimal, and
  25.67 no-task trials. Every paired trials-saved interval is positive.
- **Literature:** Carrillo et al. optimize task error rather than only parameter
  covariance; Attia et al. formalize goal-oriented posterior design.
- **Reasoning:** The no-task and D-optimal controls isolate the effect of the
  deployment distribution from generic sequential informativeness.
- **Counter-argument:** Synthetic families may align unusually well with the
  fixed M2 basis and frozen task distribution.
- **Response:** Use P3 for the causal algorithmic comparison and P5/P7 for
  closed-loop consequence under physics simulation; do not infer hardware
  sample efficiency until P8.

### A3. Safety and stopping are enforceable because they are outside the learned ranker

- **Claim:** CalibAgent's acquisition score cannot bypass its command/state
  envelope, and target stopping requires held-out validation plus repeated
  confirmation.
- **Evidence:** P4 rejects 300/300 registered proposal hazards, falsely rejects
  0/20 safe controls, catches 160/160 runtime faults, and produces no premature
  stop over 60 trajectories; median and p95 overshoot are two trials.
- **Reasoning:** Separation of ranking from enforcement is architectural, and
  the frozen fault-injection traces test the relevant state-machine branches.
- **Counter-argument:** Fault injection is not evidence of physical deployment
  safety.
- **Response:** State the tested software property directly. Never use
  certification, deployment-safe, or hardware-latency language.

### A4. Shift-triggered active recovery improves early adaptation under registered shifts

- **Claim:** Following structured in-place shifts, the full method detects the
  shift and lowers early recovery RMSE relative to passive posterior updates
  while satisfying an absolute terminal-accuracy gate.
- **Evidence:** Across four shifts and 72 paired seeds each, passive-minus-full
  early RMSE effects range from 0.00761 to 0.01691 with positive 95% CIs;
  detection is at least 71/72, recovery is 72/72, and worst p95 delays are four
  and six trials.
- **Reasoning:** The frozen/passive/full controls separate stale calibration,
  generic updating, and active recovery during the registered early window.
- **Counter-argument:** Passive updating can match or outperform the full method
  at the terminal window.
- **Response:** Concede and preserve this endpoint distinction. The supported
  result is early recovery plus absolute terminal accuracy, not terminal
  superiority over passive updating.

### A5. Calibration matters only if downstream task outcomes survive confirmatory testing

- **Claim:** Under the registered simulator protocol, budgeted CalibAgent
  navigation improves over raw control and is noninferior to dense and
  matched-budget calibration on success, collision, and completion time.
- **Evidence:** The disjoint P7 replication comprises 3,024 episodes. B8 succeeds
  on at least 70/72 trials per map, records zero collisions, yields positive
  paired time gains over raw control, and keeps worst time-ratio CI upper bounds
  at 1.0736 versus dense and 1.0901 versus matched controls.
- **Reasoning:** Navigation endpoints test the consequence of calibration under
  a common planner; validation RMSE cannot override a failed task endpoint.
- **Counter-argument:** The positive replication followed a failed confirmation
  and development pilots, creating researcher-degrees-of-freedom risk.
- **Response:** Report the failed confirmation, trace diagnosis, interlock
  change, frozen new protocol, and disjoint maps/seeds. Base the claim only on
  the later prospective replication.

## Synthesis

A1 establishes the estimand; A2 establishes why trial selection should be
task-aware; A3 establishes enforceable operational constraints; A4 establishes
bounded post-shift adaptation; and A5 connects calibration to navigation. The
streams do not jointly establish sim-to-real deployment. They establish a
method and a reproducible evidence ladder that P8 is designed to close.

## Logical flow

```text
Opaque command interface
  -> coupled probabilistic model is needed (P1)
  -> task-weighted design reduces calibration trials (P3)
  -> independent safety/stopping constrains the loop (P4)
  -> closed-loop calibration improves held-out motion (P5)
  -> shift detection and active selection accelerate early recovery (P6)
  -> calibrated motion improves registered navigation outcomes (P7)
  -> P8 tests whether the chain transfers to active hardware operation
```

## Strength assessment

| Sub-argument | Evidence strength | Logic | Counter-argument risk |
|---|---|---|---|
| A1 coupled model need | Moderate | Valid within P1 scope | High: single robot/day |
| A2 task-weighted efficiency | Strong | Valid causal comparison in simulation | Medium: synthetic basis match |
| A3 enforceable safeguards | Strong for software behavior | Valid | High if phrased as deployment safety |
| A4 early shift recovery | Strong in pinned simulation | Valid with endpoint qualifier | Medium: no terminal superiority |
| A5 navigation consequence | Strong in prospective simulation replication | Valid | Medium: prior failure must remain visible |

## Draft-writer instructions

- Lead paragraphs with the result or design decision, not with throat-clearing.
- Use strong verbs for directly recomputed registered endpoints and scope them
  in the same sentence.
- Preserve the three protected limitations: passive-only P1, pinned-simulation
  P5–P7, and incomplete P8.
- Never use “first,” “only,” “proves safety,” “robust in the real world,” or
  “sim-to-real.”
- Explain the failed P7 confirmation before presenting the positive replication.
- Prefer exact counts, effects, and intervals to evaluative adjectives.
