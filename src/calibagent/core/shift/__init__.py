"""Domain-shift detection and adaptation primitives."""

from calibagent.core.shift.detector import (
    DomainShiftConfig,
    DomainShiftDetector,
    PairedSignatureConfig,
    PairedSignatureDetection,
    PairedSignatureDetector,
    ShiftDetection,
)

__all__ = [
    "DomainShiftConfig",
    "DomainShiftDetector",
    "PairedSignatureConfig",
    "PairedSignatureDetection",
    "PairedSignatureDetector",
    "ShiftDetection",
]
