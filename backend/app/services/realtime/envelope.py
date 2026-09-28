"""Realtime event envelope and vocabulary definitions.

Protocol Standards:
- docs/realtime-contract.md
- Stage 14 Directive Sections 7, 8, 16
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

from backend.app.core.config import settings


class EventType(str, Enum):
    """Canonical event vocabulary supported by Sentinel Gujarat architecture."""
    ALERT_CREATED = "alert.created"
    ALERT_UPDATED = "alert.updated"
    CAMERA_STATUS_CHANGED = "camera.status_changed"
    SYSTEM_HEALTH_CHANGED = "system.health_changed"
    INVESTIGATION_UPDATED = "investigation.updated"
    DETECTION_CREATED = "detection.created"


# Mapping from coarse topic subscriptions to fine-grained event types
TOPIC_TO_EVENT_TYPES: Dict[str, Set[str]] = {
    "alerts": {EventType.ALERT_CREATED.value, EventType.ALERT_UPDATED.value},
    "cameras": {EventType.CAMERA_STATUS_CHANGED.value},
    "system": {EventType.SYSTEM_HEALTH_CHANGED.value},
    "investigations": {EventType.INVESTIGATION_UPDATED.value},
    "detections": {EventType.DETECTION_CREATED.value},
    "all": {
        EventType.ALERT_CREATED.value,
        EventType.ALERT_UPDATED.value,
        EventType.CAMERA_STATUS_CHANGED.value,
        EventType.SYSTEM_HEALTH_CHANGED.value,
        EventType.INVESTIGATION_UPDATED.value,
        EventType.DETECTION_CREATED.value,
    },
    "*": {
        EventType.ALERT_CREATED.value,
        EventType.ALERT_UPDATED.value,
        EventType.CAMERA_STATUS_CHANGED.value,
        EventType.SYSTEM_HEALTH_CHANGED.value,
        EventType.INVESTIGATION_UPDATED.value,
        EventType.DETECTION_CREATED.value,
    },
}

SUPPORTED_TOPICS: Set[str] = set(TOPIC_TO_EVENT_TYPES.keys())


class RealtimeEventEnvelope(BaseModel):
    """Canonical realtime event envelope for WebSocket streaming.
    
    Adheres strictly to docs/realtime-contract.md and Phase 14 Directive Section 7.
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique event UUID")
    event_type: str = Field(..., description="Dot-notated domain event type (e.g. alert.created)")
    event: str = Field(..., description="Alias matching docs/realtime-contract.md 'event' field")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 UTC timestamp of event creation"
    )
    source: str = Field(..., description="Subsystem or service producing this event")
    mode: str = Field(
        default=settings.SENTINEL_OPERATION_MODE,
        description="System operation mode: LIVE, DEMO, TEST, or UNKNOWN (Rule 29 & docs/demo-mode.md)"
    )
    data: Dict[str, Any] = Field(default_factory=dict, description="Event payload dictionary")

    @classmethod
    def create(
        cls,
        event_type: str,
        source: str,
        data: Dict[str, Any],
        mode: Optional[str] = None,
        event_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> "RealtimeEventEnvelope":
        """Factory method to construct a canonical envelope with automatic alias."""
        ev_id = event_id or str(uuid.uuid4())
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        op_mode = mode or settings.SENTINEL_OPERATION_MODE
        return cls(
            event_id=ev_id,
            event_type=event_type,
            event=event_type,
            timestamp=ts,
            source=source,
            mode=op_mode,
            data=data,
        )

    @property
    def is_critical(self) -> bool:
        """Determines whether this event must be prioritized under buffer backpressure."""
        return self.event_type == EventType.ALERT_CREATED.value

    def to_dict(self) -> Dict[str, Any]:
        """Convert envelope to serializable dictionary."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event": self.event,
            "timestamp": self.timestamp,
            "source": self.source,
            "mode": self.mode,
            "data": self.data,
        }
