# Draft Quality Report

## Build state

- Manuscript: `paper/main.tex`
- Compiled artifact: `paper/main.pdf`
- Format: official `ieeeconf` class, US Letter, 10 pt, two columns
- Authorship state: anonymous
- Length: 6 pages including 18 references; approximately 3,915 PDF words
- Figures: one six-map Isaac Sim overview, one vector method diagram, and four
  data-driven vector figures. Fig. 3 and Fig. 4 integrate registered P5/P6
  response trajectories with the corresponding multi-seed effects.
- Build command: `cd paper && make all`
- Build result: pass; citations and cross-references resolved; no overfull boxes
- Simulation-evidence audit: pass; six unique map images match their companion
  capture JSONs, and two data-driven simulation figures trace to ten hashed
  capture/summary sources

## Evidence and claim checks

| Claim family | Manuscript location | Evidence status |
|---|---|---|
| Passive hardware model need | Abstract, Sec. V-A | P1 artifacts; scoped to one Go2 and passive same-day data |
| Task-weighted sample efficiency | Abstract, Sec. V-A | P3 paired seed-level analysis; inferential unit stated |
| Safety and stopping implementation | Sec. III-C, Sec. V-B | P4 replay and fault injection; explicitly not physical certification |
| Closed-loop calibration | Abstract, Sec. V-A | P5 paired Isaac Lab experiments |
| Shift recovery | Abstract, Sec. V-B | P6 early-window contrast and absolute terminal gate; no terminal-superiority claim |
| Navigation consequence | Abstract, Sec. V-C | P7 disjoint prospective replication; failed confirmation retained |
| Hardware readiness boundary | Abstract, Introduction, Discussion, Conclusion | P8 described only as planned work; no active-hardware or sim-to-real claim |

## Writing-contract self-check

- D1 attribution fidelity: pass. Literature claims are cited; experimental claims point to frozen local artifacts through the evidence matrix.
- D2 paraphrase discipline: pass. No copied source sentences were introduced.
- D3 epistemic precision: pass. Hardware, synthetic, simulator, and planned evidence are distinguished.
- D4 argumentative synthesis: pass. Related work is organized around experimental design and quadruped adaptation rather than as a paper list.
- D5 citation placement: pass. Citations follow the claims they support.
- D6 evidentiary fit: pass. Strong results are numerical; unsupported active-hardware and sim-to-real claims are prohibited.
- D7 novelty discipline: pass. The draft does not claim to be the first general online adaptation method.

## Language pass

The draft uses direct claim--evidence sentences and removes apology-like framing,
empty intensifiers, and generic novelty assertions. Necessary limitations are
retained as evidence boundaries rather than hedges.

## Remaining publication gates

1. Complete the frozen P8 active-hardware protocol and replace the planned-work boundary with results only if its gates pass.
2. Run the confirmed five-seat independent reviewer panel and resolve its critical findings.
3. Recheck page balance and submission metadata after the hardware results are inserted.
