"""Core data models and URL sanitization for stream ingestion.

Protocol Standards:
- Section 5 & Section 26 of Stage 5 Directive.
- Strict separation between video PTS and system arrival time.
- Mandatory credential masking in URLs.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple
import re
import numpy as np


class StreamState(str, Enum):
    """Authoritative connection states for a stream worker."""
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONNECTING = "CONNECTING"
    LIVE = "LIVE"
    RECONNECTING = "RECONNECTING"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass
class DecodedFrame:
    """Decoded video frame container with authoritative presentation timestamp (PTS)."""

    frame_index: int
    camera_id: str
    pts_ms: float
    data: np.ndarray
    width: int
    height: int
    monotonic_ts: float
    pts_delta_ms: Optional[float] = None
    is_loop_discontinuity: bool = False

    @property
    def resolution_str(self) -> str:
        return f"{self.width}x{self.height}"


def sanitize_stream_url(url: Optional[str]) -> str:
    """Mask credentials in RTSP/HTTP URLs for logging and client exposure.
    
    Transforms:
        rtsp://admin:secret123@10.0.0.1:8554/stream -> rtsp://admin:***@10.0.0.1:8554/stream
    """
    if not url:
        return "rtsp://unconfigured"
    # Matches ://user:password@
    return re.sub(r"://([^:@\s]+):([^@\s]+)@", r"://\1:***@", url)
