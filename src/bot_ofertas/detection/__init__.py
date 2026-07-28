"""Public contracts for pure deal detection."""

from bot_ofertas.detection.engine import (
    DealClassification,
    DealDetector,
    DetectionDecision,
    DetectorConfig,
    ExpectedProductContext,
    RejectionReason,
    SignalAssessment,
    SignalKind,
    SignalThresholds,
    canonicalize_variant,
    detect_deal,
)

__all__ = [
    "DealClassification",
    "DealDetector",
    "DetectionDecision",
    "DetectorConfig",
    "ExpectedProductContext",
    "RejectionReason",
    "SignalAssessment",
    "SignalKind",
    "SignalThresholds",
    "canonicalize_variant",
    "detect_deal",
]
