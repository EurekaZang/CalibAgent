"""P8 real-robot experiment runtime.

This subpackage is intentionally Python 3.8 compatible because the Go2 ROS 2
Foxy image cannot import the Python 3.10-only research runtime.
"""

SCHEMA_VERSION = "calibagent.p8.real.v1"

__all__ = ["SCHEMA_VERSION"]
