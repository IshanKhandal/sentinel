"""Camera request and response validation schemas."""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class CameraBase(BaseModel):
    """Common properties for surveillance camera entities."""

    name: str = Field(..., max_length=150, description="Camera label or junction designation")
    rtsp_url: str = Field(..., max_length=500, description="RTSP stream URL (must force TCP)")
    stream_type: Literal["LIVE", "DEMO"] = Field(default="LIVE", description="Stream operational type")
    direction_heading: Optional[int] = Field(default=None, ge=0, le=360, description="Direction heading in degrees")
    fps_target: int = Field(default=10, ge=1, le=60, description="Target decoding FPS")
    resolution: str = Field(default="1920x1080", max_length=20, description="Stream video resolution")


class CameraCreate(CameraBase):
    """Schema for manual camera creation."""

    location_id: uuid.UUID = Field(..., description="ID of associated physical location")
    department_id: uuid.UUID = Field(..., description="ID of owning police department")


class CameraResponse(CameraBase):
    """Schema for camera entity responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    department_id: uuid.UUID
    status: Literal["LIVE", "DEMO", "OFFLINE", "UNAVAILABLE", "UNKNOWN"]
    last_heartbeat_at: Optional[datetime] = None
    created_at: datetime


class CameraSyncResponse(BaseModel):
    """Response payload for catalogue synchronization operations."""

    status: Literal["SUCCESS", "BLOCKED", "ERROR"]
    message: str
    results: Optional[Dict[str, Any]] = None
