"""Per-client WebSocket connection context and bounded queue manager.

Protocol Standards:
- docs/realtime-contract.md
- Stage 14 Directive Sections 6, 9, 10, 11, 13
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Set
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.app.core.config import settings
from backend.app.services.realtime.envelope import (
    RealtimeEventEnvelope,
    TOPIC_TO_EVENT_TYPES,
)

logger = logging.getLogger(__name__)


class WebSocketConnection:
    """Encapsulates an active client WebSocket connection, its bounded egress queue,
    subscription filters, and delivery worker task.
    """

    def __init__(
        self,
        websocket: WebSocket,
        session_id: str,
        token: Optional[str] = None,
        auth_verified: bool = False,
        queue_size: Optional[int] = None,
    ) -> None:
        self.websocket = websocket
        self.session_id = session_id
        self.token = token
        self.auth_verified = auth_verified
        self.connected_at = datetime.now(timezone.utc).isoformat()
        self.last_heartbeat: float = time.monotonic()
        
        # Subscriptions default to 'all' topics for tactical monitoring
        self.subscribed_topics: Set[str] = {"all"}
        
        # Bounded egress queue preventing memory leaks under backpressure
        max_q_size = queue_size or settings.WS_CLIENT_QUEUE_SIZE
        self.queue: asyncio.Queue[RealtimeEventEnvelope] = asyncio.Queue(maxsize=max_q_size)
        
        self._send_task: Optional[asyncio.Task] = None
        self._closed: bool = False
        self._dropped_count: int = 0
        self._delivered_count: int = 0

    def start(self, on_disconnect: Callable[["WebSocketConnection", int, Optional[str]], Any]) -> None:
        """Launch the background asynchronous sender worker task for this client."""
        self._send_task = asyncio.create_task(self._send_worker(on_disconnect))

    def update_heartbeat(self) -> None:
        """Record receipt of a client ping or interaction to prevent stale reaper termination."""
        self.last_heartbeat = time.monotonic()

    def matches_topic(self, event_type: str) -> bool:
        """Check whether this client's subscription filters match the given event type."""
        if "all" in self.subscribed_topics or "*" in self.subscribed_topics:
            return True
        if event_type in self.subscribed_topics:
            return True
        for topic in self.subscribed_topics:
            allowed_events = TOPIC_TO_EVENT_TYPES.get(topic, set())
            if event_type in allowed_events:
                return True
        return False

    def enqueue(self, envelope: RealtimeEventEnvelope) -> bool:
        """Attempt to enqueue an event envelope for transmission.
        
        Implements strict backpressure:
        - If queue has space: immediate non-blocking enqueue.
        - If queue is full and event is non-critical: drop immediately without blocking.
        - If queue is full and event is critical (alert.created): attempt to drop an older
          non-critical event from the buffer to guarantee critical alert transmission.
        """
        if self._closed:
            return False

        if not self.queue.full():
            try:
                self.queue.put_nowait(envelope)
                return True
            except asyncio.QueueFull:
                pass  # Fall through to backpressure logic

        # Queue is full — apply backpressure policy
        if envelope.is_critical:
            # Critical alert: try to evict the oldest non-critical item
            evicted = False
            temp_items = []
            while not self.queue.empty():
                try:
                    item = self.queue.get_nowait()
                    if not item.is_critical and not evicted:
                        evicted = True
                        self._dropped_count += 1
                    else:
                        temp_items.append(item)
                except asyncio.QueueEmpty:
                    break

            for item in temp_items:
                try:
                    self.queue.put_nowait(item)
                except asyncio.QueueFull:
                    break

            if evicted and not self.queue.full():
                try:
                    self.queue.put_nowait(envelope)
                    return True
                except asyncio.QueueFull:
                    pass

            # If all items were critical or queue remains full, evict oldest to preserve latest critical alert
            try:
                _ = self.queue.get_nowait()
                self._dropped_count += 1
                self.queue.put_nowait(envelope)
                return True
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                self._dropped_count += 1
                return False
        else:
            # Non-critical event: drop immediately to avoid slow-consumer backpressure
            self._dropped_count += 1
            logger.debug(
                f"Backpressure: dropped non-critical event {envelope.event_type} for client {self.session_id}"
            )
            return False

    async def send_direct(self, payload: Dict[str, Any]) -> bool:
        """Directly transmit a control frame (e.g. handshake ack, pong, subscription ack)
        bypassing the asynchronous event queue.
        """
        if self._closed or self.websocket.client_state != WebSocketState.CONNECTED:
            return False
        try:
            await self.websocket.send_json(payload)
            return True
        except (WebSocketDisconnect, ConnectionResetError, RuntimeError) as exc:
            logger.debug(f"Direct send failed for session {self.session_id}: {exc}")
            return False

    async def _send_worker(
        self,
        on_disconnect: Callable[["WebSocketConnection", int, Optional[str]], Any]
    ) -> None:
        """Worker loop continuously popping queued events and transmitting via WebSocket."""
        close_code = 1000
        close_reason = "Normal closure"
        try:
            while not self._closed:
                envelope = await self.queue.get()
                try:
                    if self.websocket.client_state == WebSocketState.CONNECTED:
                        await self.websocket.send_json(envelope.to_dict())
                        self._delivered_count += 1
                    else:
                        break
                except (WebSocketDisconnect, ConnectionResetError, RuntimeError):
                    close_code = 1006
                    close_reason = "Connection reset"
                    break
                except Exception as exc:
                    logger.warning(f"Error transmitting to client {self.session_id}: {exc}")
                    close_code = 1011
                    close_reason = "Internal transmission error"
                    break
                finally:
                    self.queue.task_done()
        except asyncio.CancelledError:
            close_code = 1000
            close_reason = "Sender task cancelled"
        finally:
            await self.close(code=close_code, reason=close_reason)
            # Notify manager to perform registry cleanup
            try:
                res = on_disconnect(self, close_code, close_reason)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                logger.error(f"Error during disconnect callback for {self.session_id}: {exc}")

    async def close(self, code: int = 1000, reason: Optional[str] = None) -> None:
        """Terminate the client connection safely and cancel background worker tasks."""
        if self._closed:
            return
        self._closed = True

        if self._send_task and not self._send_task.done() and asyncio.current_task() != self._send_task:
            self._send_task.cancel()

        if self.websocket.client_state == WebSocketState.CONNECTED:
            try:
                await self.websocket.close(code=code, reason=reason or "Connection closed")
            except Exception:
                pass
