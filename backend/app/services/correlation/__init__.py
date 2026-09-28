"""Cross-Camera Correlation service package."""

from backend.app.services.correlation.service import (
    CorrelationService,
    CorrelationError,
    CorrelationValidationError,
    DEFAULT_MAX_SPEED_THRESHOLD_KMH,
)

__all__ = [
    "CorrelationService",
    "CorrelationError",
    "CorrelationValidationError",
    "DEFAULT_MAX_SPEED_THRESHOLD_KMH",
]
