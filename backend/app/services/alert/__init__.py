"""Real-time Alert Engine and Lifecycle Management module.

Protocol Standards:
- Stage 10 Directive Sections 3-21.
- Strict isolation from external notifications (SMS, email, WebSockets).
- 60-second deduplication per (camera_id, plate_number, watchlist_entry_id).
"""

from backend.app.services.alert.engine import (
    AlertEngine,
    AlertEngineError,
    AlertProvenanceError,
    AlertValidationError,
    record_alert_audit_log,
)
from backend.app.services.alert.service import (
    AlertService,
    AlertNotFoundError,
    AlertLifecycleError,
)

__all__ = [
    "AlertEngine",
    "AlertService",
    "AlertEngineError",
    "AlertProvenanceError",
    "AlertValidationError",
    "AlertNotFoundError",
    "AlertLifecycleError",
    "record_alert_audit_log",
]
