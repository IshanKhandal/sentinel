"""Thread-safe bounded ring buffer for decoded video frames.

Protocol Standard: Section 12 of Stage 5 Directive.
Prevents memory exhaustion, drops oldest frames under downstream backpressure,
records frame drop telemetry, and provides clean thread synchronization.
"""

from collections import deque
import threading
from typing import Optional
from backend.app.services.streaming.models import DecodedFrame


class FrameRingBuffer:
    """Thread-safe bounded ring buffer with explicit frame drop tracking."""

    def __init__(self, capacity: int = 15) -> None:
        if capacity < 1:
            raise ValueError(f"Ring buffer capacity must be at least 1: {capacity}")
        self._capacity = capacity
        self._buffer: deque[DecodedFrame] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._dropped_count: int = 0
        self._closed: bool = False

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._buffer)

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped_count

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def push(self, frame: DecodedFrame) -> bool:
        """Push a newly decoded frame into the bounded buffer.
        
        If buffer is full at maxlen, deque automatically evicts the oldest frame;
        we track this eviction explicitly to increment dropped_count.
        """
        with self._cond:
            if self._closed:
                return False

            if len(self._buffer) >= self._capacity:
                self._dropped_count += 1

            self._buffer.append(frame)
            self._cond.notify()
            return True

    def pop(self, timeout: Optional[float] = None) -> Optional[DecodedFrame]:
        """Pop the oldest frame from the buffer for downstream consumption.
        
        Blocks up to timeout seconds if the buffer is empty.
        Returns None on timeout or if the buffer is closed.
        """
        with self._cond:
            while not self._buffer and not self._closed:
                if not self._cond.wait(timeout=timeout):
                    return None  # Timed out

            if self._buffer:
                return self._buffer.popleft()
            return None

    def peek_latest(self) -> Optional[DecodedFrame]:
        """Inspect the most recently pushed frame without popping it (e.g. for snapshots)."""
        with self._lock:
            if self._buffer:
                return self._buffer[-1]
            return None

    def clear(self) -> None:
        """Empty all frames currently in the buffer."""
        with self._cond:
            self._buffer.clear()

    def close(self) -> None:
        """Mark the buffer as closed and notify all waiting threads."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()
