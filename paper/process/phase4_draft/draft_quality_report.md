# Draft Quality Report

## Build state

- Manuscript: `paper/main.tex`
- Compiled artifact: `paper/main.pdf`
- Format: official `ieeeconf` class, US Letter, 10 pt, two columns
- Authorship state: anonymous
- Length: 7 pages including 18 references
- Structure: Introduction; Related Work; GAUGE; combined Experiments and Results;
  Discussion and Limitations; Conclusion
- Figures: four composite publication figures. Fig. 1 presents the GAUGE
  lifecycle and a qualitative physical comparison; Fig. 2 establishes model
  need and task-weighted calibration efficiency; Fig. 3 isolates shift and
  recovery; Fig. 4 connects calibration to six-map navigation.
- Build command: `cd paper && make all`
- Build result: pass; citations and cross-references resolved; no overfull boxes
- Compliance result: official anonymous IEEE conference format, 7 pages, PDF
  1.4, all fonts embedded, no Type 3 fonts
- Simulation-evidence audit: pass; six unique map images and the recovery
  figure match their registered inputs and output hashes

## Evidence and claim checks

| Claim family | Manuscript location | Evidence status |
|---|---|---|
| Coupled interface-model need | Abstract, Sec. IV-A | 183 passive Go2 trials plus controlled Isaac interventions; hardware claim remains scoped to passive data |
| Task-weighted trial efficiency | Abstract, Sec. IV-B | Paired synthetic comparisons, no-task ablation, and task-support negative control |
| Authorization and stopping | Sec. III-D, Sec. IV-C | Replay and fault injection; explicitly not physical safety certification |
| Shift detection and active recovery | Abstract, Sec. III-E, Sec. IV-C | Stationary false-alarm control, two disjoint recovery blocks, and selector ablation |
| Navigation consequence | Abstract, Sec. IV-D | Six held-out Isaac Sim maps, matched-budget validation, and dense-reference noninferiority |
| Physical navigation evidence | Fig. 1, Sec. IV-D | One run per condition; explicitly qualitative and not a replicated trajectory endpoint |

## Writing-contract self-check

- The manuscript has one mother claim: GAUGE turns an opaque velocity interface
  into a task-conditioned calibrated control variable.
- Introduction uses five paragraphs for problem, nearest gap, method boundary,
  lifecycle, and three contributions.
- Experiments answer four explicit questions, with protocol and result adjacent.
- The paper contains no internal phase labels, model codes, hashes, repository
  identifiers, development chronology, AI statements, or author identities.
- “Safety” is restricted to cited prior work or an explicit statement that the
  implemented authorization tests are not a physical safety guarantee.
- Hardware, synthetic, fixed-configuration Isaac, held-out navigation, and
  qualitative physical evidence are separated by claim scope.

## Remaining publication gate

Replicated physical evaluation of online active acquisition, structured shifts,
and recovery remains the principal evidence needed to validate the complete
lifecycle beyond the fixed simulator configuration.
