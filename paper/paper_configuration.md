# GAUGE ICRA 2027 paper configuration

Status: **CONFIRMED BY AUTHOR ON 2026-08-05**

This record freezes the proposed manuscript scope before drafting. It follows
the ICRA 2027 initial-submission requirements published by the conference:
double-anonymous review, IEEE two-column format, and an eight-page total limit
including text, figures, acknowledgments, and references.

## Proposed identity

- Working title: **GAUGE: Bridging the Command–Motion Gap in Black-Box
  Quadrupeds**
- Article type: contributed conference paper
- Target venue: IEEE International Conference on Robotics and Automation
  (ICRA 2027)
- Primary field: legged robotics, robot calibration, and safe adaptation
- Main language: English
- Citation style: IEEE numeric
- Initial-submission authorship: anonymous
- Output package: LaTeX source, BibTeX database, compliant PDF, vector PDF
  figures, and 300 dpi PNG previews
- Separate author-facing artifact: Chinese abstract and plain-language summary;
  neither is included in the eight-page submission unless the authors request
  it

## Research question

Can a task-weighted Bayesian calibration agent reduce the number of physical
command trials required to identify a quadruped's command-to-motion mapping,
while preserving hard safety constraints and recovering useful downstream
navigation after structured domain shifts?

## Central claim

GAUGE combines uncertainty-aware command-to-motion modeling,
task-weighted integrated variance reduction, independently enforced safety and
stopping rules, and shift-triggered active recovery. The existing evidence
supports sample-efficient calibration, bounded simulator recovery, and
downstream navigation under the registered conditions. A fixed-planner Go2
comparison additionally supports qualitative reductions in hesitation and
contact across two static scenes and one crossing-pedestrian scene.

## Evidence boundary

The first draft may claim only the following:

1. Passive Unitree Go2 data from 183 valid trials across three sessions show
   that the cross-axis M1 model reduces held-out velocity RMSE relative to raw
   commands and the diagonal M0 model.
2. Frozen synthetic experiments show that task-weighted active design reaches
   joint accuracy and uncertainty targets with fewer trials than the registered
   passive and active-design baselines.
3. Replay and fault-injection experiments support the stopping and hard-safety
   implementation claims.
4. Pinned Isaac Lab experiments support closed-loop calibration, structured
   shift detection and recovery, and navigation on registered simulated
   scenarios and maps.
5. Three real-Go2 navigation scenes compare direct DRL-DCLP commands with the
   frozen GAUGE inverse over five repetitions per condition. This supports a
   qualitative planner-facing navigation claim, but not online active
   calibration, physical shift recovery, deployment safety, trajectory-level
   effect sizes, or broad sim-to-real transfer.

## Proposed contributions

1. A probabilistic command-to-motion calibration formulation that represents
   cross-axis coupling, asymmetric response, measurement uncertainty, and
   posterior epistemic uncertainty in a compact online model.
2. A task-weighted integrated-variance acquisition rule that selects safe
   commands according to downstream relevance rather than global parameter
   identification alone.
3. A deployment architecture that separates learned calibration from hard
   safety filtering, validated stopping, shift detection, and bounded active
   recovery.
4. A staged evaluation spanning real passive Go2 measurements, synthetic
   identifiability controls, fault injection, pinned Isaac Lab domain shifts,
   and six-map navigation with retained failed confirmations and prospective
   replication.

## Eight-page allocation

The current anonymous draft compiles to eight pages including references; the
table below records its maximum-length allocation envelope.

| Content | Target pages |
|---|---:|
| Abstract and introduction | 0.85 |
| Related work | 0.55 |
| Problem formulation and method | 1.65 |
| Safety, stopping, and shift recovery | 0.75 |
| Experimental protocol | 0.75 |
| Results | 2.15 |
| Discussion, limitations, and conclusion | 0.55 |
| References | 0.75 |
| **Total** | **8.00** |

## Figures

1. **Six-map simulation overview**: elevated views of all six prospectively
   frozen P7 maps, with registered waypoints and obstacles.
2. **Method overview** (`research-figure`, TikZ): command candidates -> safety
   filter -> robot/backend -> measurement pipeline -> Bayesian update ->
   task-weighted acquisition, with a shift-detection/recovery loop.
3. **P5 registered response and calibration** (`plot-from-data`): four
   machine-readable body-displacement traces, raw-to-calibrated held-out RMSE,
   and seed-paired bootstrap effects.
4. **P6 registered shifts and recovery** (`plot-from-data`): four response
   traces, an exact pre-to-post shift matrix, early-window passive-minus-full
   effects, and absolute terminal accuracy.
5. **Calibration evidence** (`plot-from-data`): real P1 held-out calibration
   error and P3 paired trials-to-target effects.
6. **Navigation consequence** (`plot-from-data`): P7 success and completion-time
   comparisons over six prospectively frozen replication maps and seven
   methods.
7. **Real-Go2 navigation** (`research-figure`): matched-time direct-command and
   GAUGE-compensated sequences for two static-obstacle scenes and one
   crossing-pedestrian scene.

Every quantitative panel will be rebuilt from versioned CSV/JSON evidence. No
value will be copied from prose when a machine-readable source exists.
Every direct simulator image is checked against its tracked capture record and
must have a unique SHA-256 before the manuscript build passes. The P5/P6 vector
figures are regenerated from registered capture trajectories and frozen
multi-seed JSON summaries; their source hashes are recorded separately.
The real-Go2 figure is decoded from the retained source video at twelve unique,
predeclared timestamps; both conditions use matched elapsed times within each
scene.

## Required author inputs before final submission

- final title choice;
- author names, affiliations, and ordering for the camera-ready version;
- CRediT roles;
- funding sources and grant identifiers;
- conflicts of interest;
- whether an accompanying video will be submitted;

These items do not block anonymous technical drafting, but they block a final
submission package.
