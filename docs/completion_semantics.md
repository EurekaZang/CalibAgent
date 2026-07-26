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
python -m calibagent.cli.audit_strong_readiness --workspace . --require-ready
python -m calibagent.cli.audit_strong_readiness --workspace . --raw --require-ready
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
| P6 | L3 for strong frozen simulated shift claim | Four held-out shifts, frozen/passive/full controls, 72 seeds each, exact rate bounds, early active-over-passive effect, absolute terminal accuracy, trace safety, and provenance pass |
| P7 | L3 for strong frozen simulated navigation claim | First confirmation retained as NO-GO; a disjoint replication on six new maps, seven controls, and 72 new seeds passes exact rate and dense/matched-control noninferiority gates |
| P8 | L0 protocol only | Online Go2 backend, hardware gates, confirmatory P8-NAV/P8-SHIFT raw data, and independent analysis are still pending |

Overall ICRA readiness is **GO** for the frozen P0–P7 claim set. The live audit
recomputes 39/39 checks from frozen evidence. P6/P7 are pinned Isaac
Lab/PhysX results, not hardware results. P8 real-robot online execution of the
active planner remains explicitly outside this claim.

The stronger P6/P7 audit independently passes 12/12 additional checks. Its
default path recomputes endpoints from versioned per-seed evidence and
hash-bound trace receipts; `--raw` re-hashes and scans every full-resolution
trajectory. A failed confirmation followed by a corrected, disjoint,
prospectively frozen replication is reported as such—“eventual GO” may not be
backdated to the first run.
