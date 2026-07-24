# P1 real Unitree Go2 calibration report

## Verdict

**PASS for the frozen P1 passive real-replay claim.** The evidence contains 183
valid Unitree Go2 trials from three acquisition sessions. Every final row is
hash-bound and traced to the unique selected native attempt; command-plan match
and plan completion are both 100%.

This report does not claim real-robot online execution of the P3 active
planner.

## Data and processing

- Robot: Unitree Go2.
- Independent reference: Livox MID360 FAST-LIO/global localization,
  `map -> base_link`.
- Sessions: `go2-session-01`, `go2-session-02`, `go2-session-03`.
- Trials: 61 per session, 183 total, 183 valid.
- Primary evaluation: leave one complete session out, repeated for all three
  sessions.
- Sampling budget: 30 training trials for grid/random/LHS/Sobol; 122 for the
  dense reference.
- Measurement: robust SE(2) body twist with a fixed 0.30 s local consistency
  window. This avoids the noise amplification caused by adjacent-pose second
  differences while retaining a fail-closed transient check.

## Primary LHS result

| Evaluation | Raw RMSE | M0 RMSE | M1 RMSE | M1 vs raw | M1 vs M0 |
|---|---:|---:|---:|---:|---:|
| Three-fold pooled | 0.06605 | 0.04563 | 0.03009 | 54.45% | 34.07% |
| Hold out session 01 | 0.06465 | 0.04703 | 0.02888 | 55.33% | 38.59% |
| Hold out session 02 | 0.06517 | 0.04516 | 0.03158 | 51.55% | 30.08% |
| Hold out session 03 | 0.06827 | 0.04467 | 0.02974 | 56.44% | 33.43% |

The frozen gate requires at least 5% reduction against both raw commands and
M0. The pooled result and every held-out session exceed both thresholds.

The 30-trial LHS M1 RMSE is 3.33% above the 122-trial dense M1 reference
(0.02912), showing that the result is also close to the available-data fit.

## Reference-rate sensitivity

The source LiDAR odometry was approximately 20 Hz, below the original 50 Hz
target. No samples were duplicated or interpolated. To test whether the result
depends on the available rate, every trial was independently decimated into
even and odd approximately 10 Hz views:

| Decimation | Valid | Velocity RMSE vs 20 Hz | M1 vs raw | M1 vs M0 |
|---|---:|---:|---:|---:|
| Even samples | 183/183 | 0.00118 | 54.33% | 33.92% |
| Odd samples | 183/183 | 0.00497 | 54.30% | 34.11% |

Both half-rate views preserve all trials and the scientific conclusion. The
live audit hash-checks this sensitivity artifact and enforces a maximum
velocity RMSE of 0.01.

## Provenance

- Source archive SHA-256:
  `273d3f5f367cccb9002edb26e5256c8b6a9de5b08b36913613595805b12b978b`.
- Final raw CSV SHA-256:
  `961850368430ebd5e5af91f404caf59104e908c2e042a6d31810bf706e83f8fb`.
- Frozen plan SHA-256:
  `7393222a654e488132be235cffef81d13776d5b6f93f2bb844fa7dc5401f821c`.
- Evidence-producing source commit:
  `100fe68378a7966d0fb6b0d686cf9a247c604f19`.
- Delivery verification: 195 non-self checksum entries pass; all 183 selected
  trials trace exactly to native attempt rows; the single rejected attempt is
  retained with a technical exclusion reason.

## Known limitations

- Reference sampling was 20 Hz rather than the originally targeted 50 Hz.
  The versioned sensitivity result reduces, but does not erase, this protocol
  deviation.
- No full rosbag or external video was recorded. The archive instead preserves
  per-trial native pose/command/phase/health streams.
- Robot serial, firmware/localization revision, exact session start/end
  metadata and battery endpoints contain 21 `unknown` cells.
- The supplied checksum file includes a checksum of itself, which cannot be
  self-consistent. The verifier explicitly ignores only that entry; all other
  listed files and the immutable outer archive are verified.
- The three sessions were collected on one date in the same environment.
  Leave-one-session-out consistency is demonstrated, but cross-day,
  cross-terrain and cross-robot generalization are not claimed.

These limitations must remain in any paper artifact or rebuttal. They do not
invalidate the scoped P1 claim, but they prohibit broader hardware
generalization language.

## Reproduce

The frozen bundle is `evidence/p1_real/`. From the repository root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -p pytest_cov --cov=calibagent
.venv/bin/ruff check src tests
.venv/bin/mypy
.venv/bin/calibagent-audit --workspace . --require-ready
sha256sum -c reports/artifact_checksums.sha256
```
