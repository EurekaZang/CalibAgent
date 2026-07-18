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

## Current status (2026-07-18)

| Phase | Highest supported level | Status |
|---|---|---|
| P0 | L1 | Software structure verified; versioned provenance and real CI evidence missing |
| P1 | L1 | Components verified; replay-measurement vertical slice and real dense-data evidence fail |
| P2 | L1, partial synthetic L2 evidence | BLR formulas verified; synthetic noise contract is inconsistent |
| P3 | L1 | Planner formula verified; independent-unit LHS significance and main-effect gates fail |

Overall ICRA readiness is **NO_GO**.

