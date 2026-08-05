# Phase 1 literature search report

Status: **COMPLETE — 2026-08-05**

## Search strategy

The search was organized around four concepts from the confirmed research
question:

1. robot calibration and optimal excitation;
2. Bayesian or task-/goal-oriented experimental design;
3. learned command-to-motion models for mobile and legged robots; and
4. online adaptation, domain shift, and quadruped navigation.

The primary English search strings were:

```text
(robot calibration OR system identification) AND
  (active calibration OR optimal experiment design OR pose selection)

(Bayesian experimental design OR integrated variance reduction) AND
  (task-oriented OR goal-oriented OR quantity of interest)

(quadruped OR legged robot) AND
  (velocity command OR black-box controller) AND
  (motion model OR online calibration OR adaptation)

(quadruped locomotion) AND
  (domain shift OR payload OR friction OR embodiment adaptation)
```

- Databases and primary-source surfaces: IEEE Xplore/DOI records, publisher
  pages, RSS proceedings, PMLR proceedings, arXiv, author-hosted manuscripts,
  and the official Isaac Lab repository.
- Search dates: 2026-08-04 to 2026-08-05.
- Date policy: 2016–2026 for current work, with older foundational calibration
  and optimal-design papers retained.
- Language: English.
- Inclusion: primary research that directly informs active calibration,
  task-oriented design, command-level motion modeling, online legged
  adaptation, or the simulator/evaluation setting.
- Exclusion: papers focused only on low-level gait synthesis, semantic command
  generation, or unrelated manipulation-domain randomization.
- Domain evidence profile: `cs_ml`. Peer-reviewed proceedings and journals are
  preferred; directly relevant archival preprints are admitted and explicitly
  labeled.

### Screening results

- Recorded, deduplicated candidate set: 24 sources.
- Retained after title/abstract screening: 21 sources.
- Retained after primary-source assessment: 18 sources.
- Excluded after assessment: 6 sources, principally because they addressed
  gait generation or manipulation robustness without calibrating the
  command-to-motion interface.

The search met four stopping conditions: the conference-paper source target
was exceeded; each literature theme has at least three sources; both
foundational and 2024–2026 work are represented; and the final focused queries
did not reveal another method combining task-weighted physical command
selection, posterior uncertainty, a black-box quadruped velocity interface,
hard safety/stopping, shift recovery, and downstream navigation.

That last statement is search-bounded, not an absolute novelty claim. The
nearest prior works are Taouil et al. (learned black-box command motion models),
Carrillo et al. and Attia et al. (task-/goal-oriented design), and recent
embodiment-adaptation methods.

## Coverage distribution advisory

`DISTRIBUTIONAL_SKEW_ADVISORY`

- Dimension: methodological distribution.
- Concentration: computational or robot-experimental studies = 16/18 (88.9%).
- Advisory: this reflects the engineering research question rather than a
  defect, but it means the review does not represent qualitative, human-factor,
  or deployment-governance work.
- Search response: no expansion. Those evidence families do not bear directly
  on the scoped ICRA technical claims.

No single venue family accounts for 70% of the included sources. Nine of 18
sources are from 2021–2026, while the older half supplies the calibration and
optimal-design foundations.

## Annotated bibliography

### Hollerbach and Wampler (1996), “The Calibration Index and Taxonomy for Robot Kinematic Calibration Methods”

- Type/quality: peer-reviewed IJRR article; high, foundational.
- Method/finding: unifies robot kinematic calibration formulations and surveys
  scaling, rank, pose selection, and measurement-noise issues.
- Relevance/stance: supports the calibration problem framing and the need to
  treat experiment design and numerical conditioning explicitly.
- Use: related work and problem formulation.
- DOI: <https://doi.org/10.1177/027836499601500604>

### Calafiore, Indri, and Bona (2001), “Robot Dynamic Calibration: Optimal Excitation Trajectories and Experimental Parameter Estimation”

- Type/quality: peer-reviewed Journal of Robotic Systems article; high.
- Method/finding: optimizes excitation trajectories using conditioning and
  Fisher-information objectives, then validates parameter estimation on a
  SCARA robot.
- Relevance/stance: supports active excitation as a means of improving robot
  calibration; neutral on task weighting.
- Use: related work on excitation design.
- DOI: <https://doi.org/10.1002/1097-4563(200102)18:2%3C55::AID-ROB1005%3E3.0.CO;2-O>

### Sun and Hollerbach (2008a), “Observability Index Selection for Robot Calibration”

- Type/quality: peer-reviewed ICRA paper; high.
- Method/finding: connects robot observability indices to alphabetic optimal
  design and distinguishes parameter-variance and end-effector objectives.
- Relevance/stance: motivates D-optimal as a parameter-space baseline and
  clarifies why a downstream task objective can rank experiments differently.
- Use: related work and baseline rationale.
- DOI: <https://doi.org/10.1109/ROBOT.2008.4543308>

### Sun and Hollerbach (2008b), “Active Robot Calibration Algorithm”

- Type/quality: peer-reviewed ICRA paper; high.
- Method/finding: develops an efficient sequential pose-selection update for
  active kinematic calibration.
- Relevance/stance: supports sequential active selection; the CalibAgent
  distinction is the task-weighted predictive velocity objective and safety
  architecture.
- Use: active-calibration related work.
- DOI: <https://doi.org/10.1109/ROBOT.2008.4543379>

### Carrillo et al. (2013), “On Task-Oriented Criteria for Configurations Selection in Robot Calibration”

- Type/quality: peer-reviewed ICRA paper; high and directly relevant.
- Method/finding: selects calibration configurations by their effect on
  end-effector task error rather than only parameter covariance.
- Relevance/stance: the closest conceptual precedent for task-oriented
  calibration; supports the principle, while CalibAgent targets a black-box
  quadruped velocity interface and sequential shift recovery.
- Use: introduction, related work, and novelty boundary.
- DOI: <https://doi.org/10.1109/ICRA.2013.6631090>

### Krause, Singh, and Guestrin (2008), “Near-Optimal Sensor Placements in Gaussian Processes”

- Type/quality: peer-reviewed JMLR article; high.
- Method/finding: analyzes greedy information-based sensor placement and its
  approximation behavior under submodularity.
- Relevance/stance: supports greedy uncertainty-reduction design in a broader
  probabilistic setting; not a direct robot-calibration predecessor.
- Use: method context for finite-pool greedy acquisition.
- URL: <https://www.jmlr.org/papers/v9/krause08a.html>

### Attia, Alexanderian, and Saibaba (2018), “Goal-Oriented Optimal Design of Experiments for Large-Scale Bayesian Linear Inverse Problems”

- Type/quality: peer-reviewed Inverse Problems article; high.
- Method/finding: minimizes posterior uncertainty in a quantity of interest
  instead of the latent parameter field.
- Relevance/stance: supplies the Bayesian goal-oriented design principle behind
  weighting uncertainty over deployment-relevant commands.
- Use: method motivation and relation to goal-oriented OED.
- DOI: <https://doi.org/10.1088/1361-6420/aad210>

### Hwangbo et al. (2019), “Learning Agile and Dynamic Motor Skills for Legged Robots”

- Type/quality: peer-reviewed Science Robotics article; high.
- Method/finding: trains locomotion policies in simulation and transfers them
  to a physical quadruped using actuator modeling and randomization.
- Relevance/stance: establishes the learned-controller and sim-to-real context;
  unlike CalibAgent, it changes the locomotion policy rather than calibrating a
  fixed command interface.
- Use: related work and discussion.
- DOI: <https://doi.org/10.1126/scirobotics.aau5872>

### Lee et al. (2020), “Learning Quadrupedal Locomotion over Challenging Terrain”

- Type/quality: peer-reviewed Science Robotics article; high.
- Method/finding: obtains robust proprioceptive locomotion through simulation
  training and demonstrates real-world terrain generalization.
- Relevance/stance: provides the fixed low-level policy context and highlights
  that robust locomotion does not guarantee an accurate user-level velocity
  interface.
- Use: introduction and related work.
- DOI: <https://doi.org/10.1126/scirobotics.abc5986>

### Kumar et al. (2021), “RMA: Rapid Motor Adaptation for Legged Robots”

- Type/quality: peer-reviewed RSS paper; high.
- Method/finding: infers latent environment properties from recent interaction
  history to condition a trained locomotion policy in real time.
- Relevance/stance: a central adaptation comparator. It adapts policy behavior,
  whereas CalibAgent identifies and compensates the external command-to-motion
  map without retraining or instrumenting the low-level controller.
- Use: related work and discussion.
- DOI: <https://doi.org/10.15607/RSS.2021.XVII.011>

### Sun et al. (2021), “Online Learning of Unknown Dynamics for Model-Based Controllers in Legged Locomotion”

- Type/quality: peer-reviewed IEEE RA-L article; high.
- Method/finding: learns a time-varying locally linear residual dynamics model
  online to improve a model-based legged controller.
- Relevance/stance: supports online residual learning for legged locomotion;
  differs in controller access, target dynamics, and experiment-selection
  objective.
- Use: related work on online adaptation.
- DOI: <https://doi.org/10.1109/LRA.2021.3108510>

### Rudin et al. (2022), “Learning to Walk in Minutes Using Massively Parallel Deep Reinforcement Learning”

- Type/quality: peer-reviewed CoRL/PMLR paper; high.
- Method/finding: uses thousands of parallel environments and a curriculum to
  train quadruped locomotion policies rapidly, followed by hardware transfer.
- Relevance/stance: supports the use of parallel simulation for legged-robot
  evidence; not a calibration or online-identification method.
- Use: simulation context.
- URL: <https://proceedings.mlr.press/v164/rudin22a.html>

### Li and Stückler (2022), “Visual-Inertial Odometry with Online Calibration of Velocity-Control Based Kinematic Motion Models”

- Type/quality: peer-reviewed IEEE RA-L article; high and directly relevant.
- Method/finding: jointly estimates visual-inertial motion and a
  velocity-control-based wheeled-robot kinematic model using radial-basis
  command features.
- Relevance/stance: the nearest online command-interface calibration work for
  mobile robots. It is estimator-coupled and passive, whereas CalibAgent uses
  external motion measurements, active task weighting, and explicit recovery.
- Use: related work and novelty boundary.
- DOI: <https://doi.org/10.1109/LRA.2022.3169837>

### Taouil et al. (2023), “Quadrupedal Footstep Planning Using Learned Motion Models of a Black-Box Controller”

- Type/quality: peer-reviewed IROS paper; high and the closest application
  match.
- Method/finding: learns command-to-CoM and footstep models for a black-box
  velocity controller and integrates them into a planner.
- Relevance/stance: establishes that black-box command models can improve
  quadruped planning. It does not provide uncertainty-aware active calibration,
  registered stopping/safety gates, or shift-triggered recovery.
- Use: introduction, related work, and discussion.
- DOI: <https://doi.org/10.1109/IROS55552.2023.10342440>

### Fey et al. (2024), “A Learning-Based Framework to Adapt Legged Robots On-the-Fly to Unexpected Disturbances”

- Type/quality: peer-reviewed L4DC/PMLR paper; high.
- Method/finding: learns steady-state and local dynamics models to stabilize a
  Mini Cheetah under disturbances, including a carried water payload.
- Relevance/stance: directly informs online steady-state response adaptation;
  differs because CalibAgent actively chooses calibration commands and exposes
  posterior uncertainty and stopping.
- Use: related work and discussion.
- URL: <https://proceedings.mlr.press/v242/fey24a.html>

### Curtis et al. (2025), “Flow-Based Domain Randomization for Learning and Sequencing Robotic Skills”

- Type/quality: peer-reviewed ICML/PMLR paper; medium for this RQ.
- Method/finding: learns flexible domain-randomization distributions and studies
  out-of-distribution detection in uncertainty-aware planning.
- Relevance/stance: supplies recent context on robustness distributions and OOD
  detection, but its experiments concern manipulation rather than quadrupeds.
- Use: discussion only.
- URL: <https://proceedings.mlr.press/v267/curtis25a.html>

### Mittal et al. (2025), “Isaac Lab: A GPU-Accelerated Simulation Framework for Multi-Modal Robot Learning”

- Type/quality: official archival preprint and framework citation; high for
  simulator provenance, not for method novelty.
- Method/finding: documents the GPU-accelerated Isaac Lab framework used by the
  P5–P7 experiments.
- Relevance/stance: supports only the simulator description.
- Use: experimental setup.
- URL: <https://arxiv.org/abs/2511.04831>

### Li et al. (2026), “Rapid Embodiment Adaptation for Quadrupedal Locomotion”

- Type/quality: recent arXiv preprint; medium pending peer review, highly
  relevant to novelty risk.
- Method/finding: infers embodiment parameters from short histories and
  conditions a generalist policy; reports real-Go2 tests with joint constraints
  and payload changes.
- Relevance/stance: the newest close comparator for rapid hardware adaptation.
  It adapts an embodiment-conditioned policy, whereas CalibAgent calibrates the
  user-level velocity interface by actively chosen trials and quantifies task
  uncertainty. Its existence prevents broad “first online quadruped
  adaptation” wording.
- Use: related work, limitations, and final novelty audit.
- URL: <https://arxiv.org/abs/2608.01506>

## Literature matrix

| Source | Calibration/OED | Task objective | Command model | Online shift/adaptation | Legged navigation | Quality |
|---|---:|---:|---:|---:|---:|---|
| Hollerbach & Wampler 1996 | main |  |  |  |  | High |
| Calafiore et al. 2001 | main |  |  |  |  | High |
| Krause et al. 2008 | main |  |  |  |  | High |
| Sun & Hollerbach 2008a | main | x |  |  |  | High |
| Sun & Hollerbach 2008b | main |  |  | x |  | High |
| Carrillo et al. 2013 | main | main |  |  |  | High |
| Attia et al. 2018 | main | main |  |  |  | High |
| Hwangbo et al. 2019 |  |  |  | x | x | High |
| Lee et al. 2020 |  |  |  | x | main | High |
| Kumar et al. 2021 |  |  |  | main | x | High |
| Sun et al. 2021 |  |  | x | main | x | High |
| Rudin et al. 2022 |  |  |  | x | x | High |
| Li & Stückler 2022 | x |  | main | main |  | High |
| Taouil et al. 2023 | x |  | main |  | main | High |
| Fey et al. 2024 |  | x | main | main | x | High |
| Curtis et al. 2025 | x | x |  | x |  | Medium |
| Mittal et al. 2025 |  |  |  |  | x | High (tool) |
| Li et al. 2026 | x |  | x | main | main | Medium (preprint) |

## Identified gaps

1. Existing robot-calibration OED typically selects kinematic poses or dynamic
   trajectories; it does not directly study a commercial quadruped's opaque
   user-level velocity command interface.
2. Existing command-motion models for mobile and quadruped robots are largely
   passive or planning-specific; the located work does not combine task-weighted
   posterior variance reduction with hard pre-execution safety and validated
   stopping.
3. Legged adaptation methods commonly alter or condition the locomotion
   controller. There is less evidence on recovering an external command
   interface when the low-level controller remains inaccessible.
4. The current CalibAgent evidence still lacks the decisive cross-day,
   cross-surface real-Go2 active-calibration, shift-recovery, and navigation
   results specified by P8.

## Recommended sources by paper section

| Section | Key sources |
|---|---|
| Introduction | Carrillo 2013; Taouil 2023; Kumar 2021; Li et al. 2026 |
| Related work: calibration/OED | Hollerbach 1996; Calafiore 2001; Sun 2008a/b; Carrillo 2013; Attia 2018 |
| Related work: command models/adaptation | Li & Stückler 2022; Taouil 2023; Sun et al. 2021; Kumar 2021; Fey 2024; Li et al. 2026 |
| Method | Attia 2018; Carrillo 2013; Krause 2008 |
| Experimental setup | Rudin 2022; Mittal 2025 |
| Discussion | Taouil 2023; Fey 2024; Kumar 2021; Li et al. 2026 |
