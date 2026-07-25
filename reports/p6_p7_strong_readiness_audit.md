# P6–P7 strong ICRA-readiness audit

## Decision

**GO for the frozen P6/P7 simulator claim boundary.**

The decision requires 12/12 independent checks:

- retained and hash-matched P7 first-confirmation `NO_GO`;
- disjoint, descendant-commit P7 replication;
- 149/149 compact P6 artifacts and 158/158 full-source artifacts;
- 527/527 compact P7 artifacts and 566/566 full-source artifacts;
- pinned simulator, policy, config, and source provenance;
- complete seed/method/scenario or map coverage;
- independent recomputation of every registered effect and confidence bound;
- full-resolution trace, abort, posterior, launch, and serious-event checks.

Both audit modes return `GO`:

```bash
calibagent-audit-strong --workspace . --require-ready
calibagent-audit-strong --workspace . --raw --require-ready
```

The default mode is reproducible from versioned evidence. The raw mode requires
the local/supplemental `outputs/p6_strong_confirmatory` and
`outputs/p7_strong_confirmatory_v2` trees and re-hashes/scans all 1.06 GB of
source output.

## Publication interpretation

P6 supports early active-recovery benefit over passive updating plus absolute
terminal accuracy, detection/recovery, and safety in pinned simulation. P7
supports navigation benefit over raw control and noninferiority to dense and
four matched-budget controls in a prospective disjoint simulator replication.

The project is not yet a complete hardware paper result. Online real-Go2
deployment is planned and remains the explicit external-validity gap; no
simulator result in this audit is labeled as real-world validation.
