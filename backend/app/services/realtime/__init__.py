"""Realtime WebSocket streaming services and event dispatch layer.

Protocol Standards:
- docs/realtime-contract.md
- Stage 14 Directive Sections 2, 3, 5, 7, 8, 14, 15
"""

from backend.app.services.realtime.envelope import (
    EventType,
    RealtimeEventEnvelope,
    SUPPORTED_TOPICS,
    TOPIC_TO_EVENT_TYPES,
)
from backend.app.services.realtime.event_bus import (
    EventBus,
    event_bus,
)
from backend.app.services.realtime.connection import (
    WebSocketConnection,
)
from backend.app.services.realtime.manager import (
    WebSocketManager,
    WebSocketMetrics,
    websocket_manager,
)

__all__ = [
    "EventType",
    "RealtimeEventEnvelope",
    "SUPPORTED_TOPICS",
    "TOPIC_TO_EVENT_TYPES",
    "EventBus",
    "event_bus",
    "WebSocketConnection",
    "WebSocketManager",
    "WebSocketMetrics",
    "websocket_manager",
]
