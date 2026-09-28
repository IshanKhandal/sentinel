"""Exponential backoff algorithm with jitter for stream reconnection.

Protocol Standard: Section 13 of Stage 5 Directive & docs/streaming-architecture.md.
Backoff progression: 2s -> 4s -> 8s -> 16s -> 30s maximum (with 10% jitter).
"""

import random
from typing import Optional


class ExponentialBackoff:
    """Thread-safe exponential backoff calculator with jitter."""

    def __init__(
        self,
        base_delay: float = 2.0,
        max_delay: float = 30.0,
        factor: float = 2.0,
        jitter_ratio: float = 0.10
    ) -> None:
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.factor = factor
        self.jitter_ratio = jitter_ratio
        self.attempt: int = 0
        self._last_delay: float = 0.0

    def next_delay(self) -> float:
        """Calculate next backoff delay in seconds and increment attempt count."""
        # Unjittered exponential calculation: base * (factor ^ attempt)
        raw_delay = min(self.base_delay * (self.factor ** self.attempt), self.max_delay)
        
        # Apply jitter: e.g. [1.0 - 0.10, 1.0 + 0.10]
        if self.jitter_ratio > 0:
            jitter = random.uniform(1.0 - self.jitter_ratio, 1.0 + self.jitter_ratio)
            delay = round(raw_delay * jitter, 2)
        else:
            delay = round(raw_delay, 2)

        self._last_delay = delay
        self.attempt += 1
        return delay

    def peek_delay(self) -> float:
        """Get the current backoff delay without incrementing attempt."""
        return self._last_delay

    def reset(self) -> None:
        """Reset backoff attempt counter after a stable connection is established."""
        self.attempt = 0
        self._last_delay = 0.0
