"""Pydantic schemas for Sentinel stream ingestion and health telemetry.

Protocol Standard: Stage 5 Stream Ingestion Directive and docs/streaming-architecture.md.
"""

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


StreamState = Literal[
    "NOT_CONFIGURED",
    "CONNECTING",
    "LIVE",
    "RECONNECTING",
    "OFFLINE",
    "ERROR",
    "UNAVAILABLE",
    "UNKNOWN"
]


class StreamSessionResponse(BaseModel):
    """Authoritative telemetry for an active or managed video stream session."""

    camera_id: str = Field(..., description="Unique camera UUID or Sentinel catalogue ID")
    stream_url: str = Field(..., description="Sanitized RTSP stream URL with credentials masked")
    protocol: str = Field(default="RTSP", description="Ingestion protocol (always RTSP over TCP)")
    codec: Optional[str] = Field(default=None, description="Demuxed bitstream codec (e.g. H.264, H.265)")
    resolution: Optional[str] = Field(default=None, description="Observed video dimensions (e.g. 1920x1080)")
    connection_state: StreamState = Field(..., description="Authoritative connection state")
    frames_received: int = Field(default=0, ge=0, description="Total frames decoded successfully")
    frames_dropped: int = Field(default=0, ge=0, description="Frames dropped due to buffer backpressure")
    reconnect_count: int = Field(default=0, ge=0, description="Total reconnect attempts")
    decoder_errors: int = Field(default=0, ge=0, description="Non-fatal decoder warning/error count")
    last_pts_ms: Optional[float] = Field(default=None, description="Authoritative Presentation Timestamp in ms")
    pts_delta_ms: Optional[float] = Field(default=None, description="Interval between last two PTS timestamps in ms")
    fps_measured: Optional[float] = Field(default=None, description="Real measured decoding frame rate")
    current_backoff_seconds: float = Field(default=0.0, description="Active backoff delay before next retry")
    buffer_depth: int = Field(default=0, ge=0, description="Current number of unconsumed frames in ring buffer")
    buffer_capacity: int = Field(default=15, ge=1, description="Maximum bounded ring buffer capacity")
    last_error: Optional[str] = Field(default=None, description="Most recent connection or decoder error")
    started_at: Optional[datetime] = Field(default=None, description="Timestamp when stream session started")
    last_frame_at: Optional[datetime] = Field(default=None, description="Timestamp when latest frame arrived")


class StreamActionResponse(BaseModel):
    """Response payload for stream start/stop control actions."""

    camera_id: str
    status: Literal["STARTED", "STOPPED", "ALREADY_RUNNING", "NOT_RUNNING", "BLOCKED", "ERROR"]
    message: str
    session: Optional[StreamSessionResponse] = None
