# Completion semantics and claim governance

The project uses four evidence levels. They are deliberately non-equivalent.

| Level | Meaning | Required evidence |
|---|---|---|
| L0 Implemented | Named source/config/artifact exists | File and API inspection |
| L1 Software-verified | Implementation behaves as specified in component tests | Unit/integration tests, lint, typing |
| L2 Phase-evidenced | The phase completion definition is supported by independent end-to-end evidence | Frozen protocol, valid statistical unit, required input data, reproducible run |
| L3 Publication-ready | The evidence supports the intended paper claim under the publication protocol | Main seeds, strong baselines/ablations, effect-size gate, immutable provenance, paper-ready statistics |

“Complete” must always include its level. L0/L1 completion may not be reported as
phase completion or publication readiness. A checksum proves artifact integrity,
not scientific validity. A green software CI proves software quality, not a paper
claim. Missing external evidence is a failed or pending gate, never an implicit
pass.

## Independent completion audit

The evidence producer must not be the sole authority for its own completion.
Publication status is computed from raw artifacts with:

```bash
python -m calibagent.cli.audit_readiness --workspace .
python -m calibagent.cli.audit_readiness --workspace . --require-ready
```

The second command exits non-zero until every publication criterion passes.
Governance tests require README/report claims to agree with this verdict.

## Current status (2026-07-24)

| Phase | Highest supported level | Status |
|---|---|---|
| P0 | L3 for P0 scope | Versioned provenance, pinned environment and source-linked manifests pass |
| P1 | L3 for passive real replay claim | 183 real Go2 trials, native traceability, LOSO improvement and sampling sensitivity pass |
| P2 | L3 for frozen synthetic claim | Noise contract and overall/stratified coverage pass |
| P3 | L3 for frozen synthetic claim | Main seeds, primary effect, strong baselines, ablation and dense gap pass |
| P4 | L3 for frozen safety/stopping claim | 60 frozen stopping runs, 300 hazard injections, 160 runtime faults, and state-machine terminal traces pass |
| P5 | L3 for frozen simulation claim | Four pinned Isaac Lab Go2 scenarios, 20 paired seeds each, positive paired CIs, physical variation, pose traces, and safety response pass |

Overall ICRA readiness is **GO** for the frozen P0–P5 claim set. The live audit
recomputes 29/29 gates from frozen evidence. Real-robot online execution of the
active planner and P6 sim-to-real/domain-shift validation remain explicitly
outside that claim.
