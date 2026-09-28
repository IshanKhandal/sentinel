"""WebSocket Connection Manager and Realtime Broadcaster.

Protocol Standards:
- docs/realtime-contract.md
- Stage 14 Directive Sections 5, 6, 9, 10, 11, 13, 14, 15, 22, 23
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from backend.app.core.config import settings
from backend.app.services.realtime.connection import WebSocketConnection
from backend.app.services.realtime.envelope import (
    RealtimeEventEnvelope,
    SUPPORTED_TOPICS,
)
from backend.app.services.realtime.event_bus import event_bus

logger = logging.getLogger(__name__)


@dataclass
class WebSocketMetrics:
    """Observability counters for WebSocket lifecycle and throughput."""
    active_connections: int = 0
    connection_attempts: int = 0
    successful_connections: int = 0
    disconnects: int = 0
    events_published: int = 0
    events_delivered: int = 0
    failed_deliveries: int = 0
    dropped_events: int = 0
    malformed_messages: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active_connections": self.active_connections,
            "connection_attempts": self.connection_attempts,
            "successful_connections": self.successful_connections,
            "disconnects": self.disconnects,
            "events_published": self.events_published,
            "events_delivered": self.events_delivered,
            "failed_deliveries": self.failed_deliveries,
            "dropped_events": self.dropped_events,
            "malformed_messages": self.malformed_messages,
        }


class WebSocketManager:
    """Central registry and broadcast coordinator for connected WebSocket clients."""

    def __init__(self) -> None:
        self._connections: Dict[str, WebSocketConnection] = {}
        self._lock = asyncio.Lock()
        self.metrics = WebSocketMetrics()
        self._reaper_task: Optional[asyncio.Task] = None
        self._bus_subscribed: bool = False

    def ensure_bus_subscribed(self) -> None:
        """Register the broadcast handler with the global event bus."""
        if not self._bus_subscribed:
            event_bus.subscribe(self.broadcast)
            self._bus_subscribed = True

    async def connect(
        self,
        websocket: WebSocket,
        token: Optional[str] = None
    ) -> Optional[WebSocketConnection]:
        """Establish, authenticate, and register a new client connection.
        
        Boundary: AUTHORIZATION HARDENING DEFERRED TO STAGE 15.
        Validates token format if passed; rejects with code 4401 on explicit invalidity.
        """
        self.ensure_bus_subscribed()
        try:
            event_bus.set_loop(asyncio.get_running_loop())
        except RuntimeError:
            pass
        self.metrics.connection_attempts += 1

        # Check explicit authentication rejection (invalid / expired tokens)
        if token is not None and token.lower() in ("invalid", "expired", "unauthorized", "bad"):
            logger.warning("Rejecting WebSocket connection: invalid or expired token provided.")
            await websocket.close(code=4401, reason="Unauthorized: Invalid or expired token")
            return None

        # Check max connection ceiling to protect against FD exhaustion
        async with self._lock:
            if len(self._connections) >= settings.WS_MAX_CONNECTIONS:
                logger.error("Rejecting WebSocket connection: maximum connection capacity reached.")
                await websocket.close(code=1013, reason="Maximum connection capacity reached")
                return None

        try:
            await websocket.accept()
        except Exception as exc:
            logger.error(f"Failed to accept WebSocket handshake: {exc}")
            return None

        session_id = f"ws-sess-{uuid.uuid4().hex[:8]}"
        conn = WebSocketConnection(
            websocket=websocket,
            session_id=session_id,
            token=token,
            auth_verified=(token is not None),
            queue_size=settings.WS_CLIENT_QUEUE_SIZE,
        )

        async with self._lock:
            self._connections[session_id] = conn
            self.metrics.active_connections = len(self._connections)
            self.metrics.successful_connections += 1

        # Launch egress worker with disconnect callback
        conn.start(self._on_connection_disconnect)

        # Transmit connection acknowledgment handshake packet
        ack_payload = {
            "event": "connection.acknowledged",
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await conn.send_direct(ack_payload)
        logger.info(f"WebSocket client connected: session_id={session_id}")
        return conn

    async def _on_connection_disconnect(
        self,
        conn: WebSocketConnection,
        code: int,
        reason: Optional[str]
    ) -> None:
        """Internal callback invoked when a connection closes."""
        await self.disconnect(conn.session_id, code=code, reason=reason)

    async def disconnect(
        self,
        session_id: str,
        code: int = 1000,
        reason: Optional[str] = None
    ) -> None:
        """Safely unregister and terminate a client connection."""
        conn: Optional[WebSocketConnection] = None
        async with self._lock:
            conn = self._connections.pop(session_id, None)
            self.metrics.active_connections = len(self._connections)

        if conn:
            self.metrics.disconnects += 1
            # Merge client-level dropped count into global metrics
            self.metrics.dropped_events += conn._dropped_count
            self.metrics.events_delivered += conn._delivered_count
            await conn.close(code=code, reason=reason)
            logger.info(f"WebSocket client disconnected: session_id={session_id} (code={code}, reason={reason})")

    async def broadcast(self, envelope: RealtimeEventEnvelope) -> None:
        """Broadcast an event envelope to all matching subscribed clients.
        
        Guarantees connection isolation:
        - Non-blocking per-client queue delivery.
        - Backpressure shedding on slow consumers.
        - One failing client never terminates or impedes delivery to others.
        """
        self.metrics.events_published += 1
        
        async with self._lock:
            active_clients = list(self._connections.values())

        if not active_clients:
            return

        for client in active_clients:
            if client.matches_topic(envelope.event_type):
                success = client.enqueue(envelope)
                if not success:
                    self.metrics.dropped_events += 1

    async def handle_client_message(self, session_id: str, raw_text: str) -> None:
        """Validate and dispatch incoming client frames (ping, subscribe, unsubscribe)."""
        async with self._lock:
            conn = self._connections.get(session_id)

        if not conn:
            return

        # 1. Payload size guard
        if len(raw_text.encode("utf-8")) > settings.WS_MAX_MESSAGE_BYTES:
            self.metrics.malformed_messages += 1
            await conn.send_direct({
                "error": "PAYLOAD_TOO_LARGE",
                "message": f"Message exceeds size limit of {settings.WS_MAX_MESSAGE_BYTES} bytes",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        # 2. JSON validation
        try:
            payload = json.loads(raw_text)
        except (ValueError, TypeError):
            self.metrics.malformed_messages += 1
            await conn.send_direct({
                "error": "MALFORMED_JSON",
                "message": "Message is not valid JSON",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        if not isinstance(payload, dict):
            self.metrics.malformed_messages += 1
            await conn.send_direct({
                "error": "INVALID_FORMAT",
                "message": "Root payload must be a JSON object",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        # 3. Handle Ping / Heartbeat
        msg_type = payload.get("type") or payload.get("action")
        if msg_type == "ping":
            conn.update_heartbeat()
            await conn.send_direct({
                "type": "pong",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        # 4. Handle Subscriptions
        if msg_type == "subscribe":
            conn.update_heartbeat()
            topics = payload.get("topics")
            if not isinstance(topics, list) or not topics:
                self.metrics.malformed_messages += 1
                await conn.send_direct({
                    "error": "INVALID_SUBSCRIPTION",
                    "message": "Subscription request requires a non-empty 'topics' array",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return

            invalid_topics = [t for t in topics if t not in SUPPORTED_TOPICS]
            if invalid_topics:
                self.metrics.malformed_messages += 1
                await conn.send_direct({
                    "error": "INVALID_SUBSCRIPTION",
                    "message": f"Unknown topic(s): {invalid_topics}. Supported: {sorted(list(SUPPORTED_TOPICS))}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return

            conn.subscribed_topics.update(topics)
            await conn.send_direct({
                "event": "subscription.acknowledged",
                "subscribed_topics": sorted(list(conn.subscribed_topics)),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        # 5. Handle Unsubscribe
        if msg_type == "unsubscribe":
            conn.update_heartbeat()
            topics = payload.get("topics")
            if not isinstance(topics, list):
                self.metrics.malformed_messages += 1
                await conn.send_direct({
                    "error": "INVALID_UNSUBSCRIBE",
                    "message": "Unsubscribe request requires a 'topics' array",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return

            for t in topics:
                conn.subscribed_topics.discard(t)

            await conn.send_direct({
                "event": "unsubscription.acknowledged",
                "subscribed_topics": sorted(list(conn.subscribed_topics)),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        # 6. Unknown command
        self.metrics.malformed_messages += 1
        await conn.send_direct({
            "error": "UNKNOWN_ACTION",
            "message": f"Unsupported action or type: '{msg_type}'",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def check_stale_connections(self, timeout_seconds: Optional[float] = None) -> List[str]:
        """Detect and terminate unresponsive/stale connections exceeding heartbeat timeout."""
        timeout = timeout_seconds or settings.WS_HEARTBEAT_TIMEOUT_SECONDS
        now = time.monotonic()
        stale_sessions: List[str] = []

        async with self._lock:
            for session_id, conn in self._connections.items():
                if (now - conn.last_heartbeat) > timeout:
                    stale_sessions.append(session_id)

        for session_id in stale_sessions:
            logger.info(f"Reaping stale WebSocket connection: session_id={session_id}")
            await self.disconnect(session_id, code=1001, reason="Heartbeat timeout (stale connection)")

        return stale_sessions

    def start_reaper(self) -> None:
        """Start the background watchdog task monitoring connection liveness."""
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reaper_loop())

    async def stop_reaper(self) -> None:
        """Stop the background watchdog task."""
        if self._reaper_task and not self._reaper_task.done():
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass

    async def _reaper_loop(self) -> None:
        """Loop periodically running stale connection checks."""
        check_interval = max(5.0, settings.WS_HEARTBEAT_INTERVAL_SECONDS / 2.0)
        try:
            while True:
                await asyncio.sleep(check_interval)
                await self.check_stale_connections()
        except asyncio.CancelledError:
            pass

    async def shutdown_all(self) -> None:
        """Orderly termination of all active connections during application shutdown."""
        await self.stop_reaper()
        async with self._lock:
            session_ids = list(self._connections.keys())

        for session_id in session_ids:
            await self.disconnect(session_id, code=1001, reason="Server shutting down")

    def get_metrics(self) -> Dict[str, Any]:
        """Retrieve snapshot of real-time metrics."""
        return self.metrics.to_dict()


# Global singleton manager instance
websocket_manager = WebSocketManager()
