# ICRA audit: strong P6/P7 simulator claims

Date: 2026-07-25  
Decision: **GO, scoped to pinned simulation**

## Audit question

Do the strong-confirmatory P6 and P7 artifacts support paper-facing claims at
ICRA evidence quality, independent of the benchmark producer's own verdict?

## Finding

Yes, within the explicitly simulated claim boundary. The versioned audit
passes 12/12 checks, and the full-output audit reaches the same decision after
hashing/scanning 1.06 GB of output.

- P6: four held-out shifts, 72 paired seeds, frozen/passive/full controls,
  exact rate bounds, preregistered active-over-passive early recovery,
  absolute terminal accuracy, and zero serious events.
- P7: the first strong confirmation is retained as `NO_GO`; a later
  descendant-commit protocol uses six disjoint maps and 72 disjoint seeds with
  raw, dense, four matched-budget, and full controls. All registered
  replication gates pass.
- Provenance: 158/158 P6 and 566/566 P7 full-source artifacts hash-match.
  Twelve P6 and 42 P7 full-resolution traces pass unique-key, finite-state,
  identity, coverage, and serious-event checks.

## Bias audit

The main historical risk was treating engineering completion or an eventual
successful run as publication completion. This audit blocks that failure mode:

- a producer `GO` field is never accepted without recomputation;
- failed confirmation and development pilots remain separate from the
  confirmatory estimate;
- the successful P7 result must use disjoint seeds/maps and a later immutable
  source commit;
- secondary calibration diagnostics cannot override downstream navigation;
- P6 wording is limited to early recovery benefit and absolute terminal
  accuracy, not terminal superiority over passive updating.

The human-entered `protocol_frozen_utc` labels are not used to establish the P7
failure-to-replication order because their values are not chronologically
reliable. Git commit ancestry, frozen config hashes, disjoint identities, and
source manifests are the authoritative chronology.

## Remaining external-validity gap

No claim here is a real-robot online result. Planned Go2 deployment remains
necessary for hardware and sim-to-real claims. The correct current label is
“strong ICRA-ready simulator evidence for P6/P7,” not “complete real-world
validation.”

Machine-readable snapshot:
`reports/p6_p7_strong_readiness_latest.json`.
