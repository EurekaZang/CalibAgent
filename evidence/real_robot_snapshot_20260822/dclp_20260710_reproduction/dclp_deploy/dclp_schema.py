"""Local DCLP deploy schema constants.

These values describe the observation/action contract used by the deploy-time
PyTorch policy and the scan pooling logic in this package.
"""

from __future__ import annotations

SCAN_GROUPS = 90
SCAN_GROUP_SIZE = 6
BEAM_NUM = SCAN_GROUPS * SCAN_GROUP_SIZE

TAIL_DIM = 8
OBS_DIM = BEAM_NUM + TAIL_DIM
ACT_DIM = 2

CONTROL_PERIOD_SEC = 0.2

DEFAULT_MAX_LINEAR_SPEED = 0.7
DEFAULT_MAX_ANGULAR_SPEED = 1.5707963267948966
DEFAULT_MAX_LINEAR_ACC = 2.0
DEFAULT_MAX_ANGULAR_ACC = 2.0
