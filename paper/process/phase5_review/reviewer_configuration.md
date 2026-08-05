# Field Analysis and Reviewer Configuration

Status: **AWAITING AUTHOR CONFIRMATION**

No substantive panel review may begin until the author confirms or edits these
reviewer identities.

## Paper basic information

- Title: *GAUGE: Bridging the Command–Motion Gap in Black-Box Quadrupeds*
- Language: English
- Abstract length: approximately 239 words
- Full-text length: approximately 6,111 PDF words across 8 pages
- References: 18
- Target venue: IEEE International Conference on Robotics and Automation (ICRA)

## Field analysis

| Dimension | Analysis |
|---|---|
| Primary discipline | Robotics: legged-robot calibration and adaptive control |
| Secondary disciplines | Bayesian experimental design; system identification; field-robot safety and navigation |
| Research paradigm | Quantitative experimental systems research |
| Methodology | Bayesian regression and sequential design evaluated with passive hardware data, controlled synthetic experiments, fault injection, and paired physics simulation |
| Target tier | Top-tier robotics conference. The scope and evidence ladder target ICRA; active hardware validation remains the decisive readiness gate. |
| Paper maturity | Revised anonymous submission draft. Structure, figures, citations, and numerical claims are complete for the current simulation evidence; active hardware evaluation remains planned. |

## Venue positioning

1. **ICRA** — primary target; strong fit for a calibrated command interface, active experiment design, and system-level validation.
2. **IEEE Robotics and Automation Letters (RA-L)** — suitable alternative if the contribution is reframed as a compact robotics system with completed hardware experiments.
3. **IEEE Transactions on Robotics (T-RO)** — longer-term target only with broader multi-robot or multi-day hardware evidence and deeper analysis.

## Reviewer Configuration Card 1

- **Role**: EIC
- **Display role**: ICRA Journal-Fit Reviewer
- **Identity description**: Senior ICRA Area Chair in legged robotics and autonomous systems, with editorial experience evaluating system papers that combine learning, control, and hardware experiments.
**Review focus**:

1. Whether the command-interface calibration problem is important to ICRA readers.
2. Whether the contribution is distinct from policy adaptation, residual control, and conventional robot calibration.
3. Whether the evidence package is sufficiently complete for a top-tier robotics conference.

- **Will particularly care about**: A concise contribution boundary and whether passive hardware plus simulated active operation is adequate before P8 arrives.
**Possible blind spots**: May not audit every statistical dependency or runtime safety detail.

## Reviewer Configuration Card 2

- **Role**: Peer Reviewer 1
- **Display role**: Methodology Reviewer
- **Identity description**: Researcher in Bayesian optimal experimental design and robot system identification, specializing in sequential design, posterior predictive uncertainty, and paired simulation studies.
**Review focus**:

1. Correctness of the Bayesian updates, IVR objective, and covariance-only fantasy selection.
2. Statistical units, paired estimands, uncertainty intervals, stopping targets, and multiplicity discipline.
3. Fairness of LHS, Sobol, D-optimal, no-task, and dense-budget comparisons.

- **Will particularly care about**: Whether task weighting, model class, and acquisition rule are separated experimentally, and whether seed-level inference supports every numerical conclusion.
**Possible blind spots**: May underweight locomotion-specific deployment constraints.

## Reviewer Configuration Card 3

- **Role**: Peer Reviewer 2
- **Display role**: Legged-Robotics Domain Reviewer
- **Identity description**: Senior quadruped-locomotion researcher working on learned controllers, online adaptation, state estimation, and planner--controller interfaces for Unitree-class platforms.
**Review focus**:

1. Physical meaning and adequacy of the steady command-to-motion model.
2. Novelty relative to rapid motor adaptation, residual dynamics learning, and black-box quadruped motion models.
3. Whether calibration improvements translate to meaningful navigation behavior.

- **Will particularly care about**: Hidden gait and history dependence, estimator bias, controller-specificity, and whether the method remains useful beyond the tested policy.
**Possible blind spots**: May accept standard statistical procedures without reconstructing them in detail.

## Reviewer Configuration Card 4

- **Role**: Peer Reviewer 3
- **Display role**: Field-Systems and Safety Reviewer
- **Identity description**: Field-robotics systems researcher specializing in safety monitors, experiment operations, localization failure modes, and repeatable hardware evaluation of autonomous mobile robots.
**Review focus**:

1. Separation between learned acquisition and hard execution authority.
2. Runtime monitor frequency, fault coverage, fail-closed behavior, and operational recovery budgets.
3. Reproducibility and feasibility of the P8 gain/coupling, payload/COM, surface-friction, mixed-shift, weighted-arc, and offset-slalom protocol.

- **Will particularly care about**: Whether software replay results are described without implying physical certification and whether the real-robot protocol can expose unsafe or nonstationary failure modes.
**Possible blind spots**: May prioritize deployability over theoretical optimality.

## Reviewer Configuration Card 5

- **Role**: Devil's Advocate
- **Display role**: Core-Argument Challenger
- **Identity description**: Adversarial reviewer with expertise in nonlinear system identification and empirical robotics, tasked with constructing the strongest evidence-based alternative explanation for every central claim.
**Review focus**:

1. Whether the apparent active-learning gain is caused by favorable synthetic families, candidate pools, thresholds, or budget definitions.
2. Whether a compact steady-state model can justify downstream navigation claims under temporal dynamics and estimator coupling.
3. Whether the failed P7 confirmation and subsequent interlock change introduce researcher degrees of freedom despite the disjoint replication.

- **Will particularly care about**: The single-robot passive hardware dataset, the absence of active P8 evidence, and any wording that turns simulator confirmation into a hardware claim.
**Possible blind spots**: The deliberately adversarial stance may undervalue engineering utility unless checked against the registered endpoints.

## Panel complementarity

The five seats are intentionally non-overlapping: venue significance, statistical
validity, legged-robot domain validity, field deployment, and adversarial causal
alternatives. The editorial synthesis must adjudicate every critical Devil's
Advocate finding explicitly rather than counting reviewer votes.
