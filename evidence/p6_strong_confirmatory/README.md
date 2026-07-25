# P6 strong-confirmatory evidence

This versioned tree contains every non-trajectory artifact from the frozen run. Full-resolution trajectories are intentionally kept in the supplemental output archive because they exceed practical Git size. `source_manifest.json` records the SHA-256 of every original artifact, including every trajectory. `trace_audit.json` records an independent finite/identity/uniqueness/safety scan of each trajectory and binds that scan to the same hashes.

The compact tree is sufficient to recompute every registered endpoint from per-seed records. Use `calibagent-audit-strong --raw` when the full supplemental output trees are mounted to re-hash and rescan them.
