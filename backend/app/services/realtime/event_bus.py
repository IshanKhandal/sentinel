"""In-process asynchronous event bus for domain event dispatching.

Protocol Standards:
- Stage 14 Directive Sections 3, 4, 23
- Decouples domain services (Alerts, Cameras, Investigations) from WebSocket transport.
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, List, Set
from backend.app.services.realtime.envelope import RealtimeEventEnvelope

logger = logging.getLogger(__name__)

# Type alias for async event listeners
EventListener = Callable[[RealtimeEventEnvelope], Coroutine[Any, Any, None]]


class EventBus:
    """Thread-safe, asynchronous in-memory event dispatcher."""

    def __init__(self) -> None:
        self._listeners: Set[EventListener] = set()
        self._lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register the primary asyncio event loop for cross-thread sync dispatch."""
        self._loop = loop

    def subscribe(self, listener: EventListener) -> None:
        """Register an async callback listener to receive dispatched events."""
        self._listeners.add(listener)

    def unsubscribe(self, listener: EventListener) -> None:
        """Unregister an async callback listener."""
        self._listeners.discard(listener)

    async def publish(self, envelope: RealtimeEventEnvelope) -> None:
        """Asynchronously dispatch an event envelope to all registered listeners.
        
        Isolates exceptions so one failing listener never interrupts dispatch to others.
        """
        # Automatically cache running loop
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        if not self._listeners:
            return

        listeners_copy = list(self._listeners)
        coros = [listener(envelope) for listener in listeners_copy]
        results = await asyncio.gather(*coros, return_exceptions=True)
        
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"EventBus listener {listeners_copy[idx].__name__ if hasattr(listeners_copy[idx], '__name__') else listeners_copy[idx]} "
                    f"failed on event {envelope.event_type}: {result}",
                    exc_info=result
                )

    def publish_sync(self, envelope: RealtimeEventEnvelope) -> None:
        """Synchronous bridge for dispatching events from synchronous services or endpoints.
        
        Works both when called within an async event loop thread and from threadpool worker threads.
        """
        # 1. Try running loop in current thread
        try:
            current_loop = asyncio.get_running_loop()
            if current_loop.is_running():
                if self._loop is None:
                    self._loop = current_loop
                current_loop.create_task(self.publish(envelope))
                return
        except RuntimeError:
            pass

        # 2. If called from a threadpool worker thread, dispatch via registered main loop
        if self._loop is not None and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self.publish(envelope), self._loop)
            except Exception as exc:
                logger.warning(f"Failed scheduling event dispatch across threads: {exc}")


# Global singleton event bus instance
event_bus = EventBus()
