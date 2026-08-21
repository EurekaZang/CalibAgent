"""CalibAgent public package.

The research package targets Python 3.10+.  The P8 field entry point is also
kept importable on the Go2's ROS 2 Foxy Python 3.8 runtime; avoid importing the
3.10-only typed public contracts on that runtime.
"""

import sys

if sys.version_info >= (3, 10):  # noqa: UP036 - Go2 field runtime is Python 3.8.
    from calibagent.interfaces.types import (
        PredictiveDistribution,
        RobotContext,
        TrialObservation,
        VelocityCommand,
    )

    __all__ = [
        "PredictiveDistribution",
        "RobotContext",
        "TrialObservation",
        "VelocityCommand",
    ]
else:  # pragma: no cover - exercised on the Go2 ROS 2 Foxy runtime.
    __all__ = []

__version__ = "0.1.0"
