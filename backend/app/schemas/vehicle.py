"""Vehicle intelligence and chronological observation history Pydantic schemas.

Protocol Standards:
- docs/api-contract.md Section 7 (Vehicles & Journey).
- docs/database-design.md Domain 3 (Vehicles, Detections).
- Stage 11 Directive: Chronological observation history from persisted detection records.
- STRICT PROVENANCE: Observation timestamps derived strictly from upstream video PTS.
- STRICT ISOLATION: No route reconstruction, speed estimation, or next-camera prediction (Stage 12).
- UNKNOWN DATA: Missing coordinates serialized as None (never 0,0).
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class VehicleProfileRead(BaseModel):
    """Canonical vehicle profile with observation statistics and active watchlist status."""
    model_config = ConfigDict(from_attributes=True)

    plate_number: str = Field(..., description="Normalized vehicle registration plate")
    vehicle_type: Optional[str] = Field(default=None, description="Vehicle classification (CAR, TRUCK, etc.)")
    color: Optional[str] = Field(default=None, description="Vehicle exterior color if identified")
    first_seen_at: datetime = Field(..., description="Earliest recorded observation timestamp")
    last_seen_at: datetime = Field(..., description="Most recent recorded observation timestamp")
    total_detections: int = Field(..., description="Total count of recorded observations")
    is_on_watchlist: bool = Field(default=False, description="Whether plate is actively enrolled on a watchlist")
    watchlist_category: Optional[str] = Field(default=None, description="Category of active watchlist if enrolled")


class VehicleObservationItem(BaseModel):
    """Single chronological observation of a vehicle at a camera site."""
    model_config = ConfigDict(from_attributes=True)

    detection_id: uuid.UUID = Field(..., description="Unique detection observation UUID")
    camera_id: uuid.UUID = Field(..., description="Camera identifier where observed")
    camera_name: Optional[str] = Field(default=None, description="Human-readable camera designation")
    location_id: Optional[uuid.UUID] = Field(default=None, description="Associated location identifier")
    location_name: Optional[str] = Field(default=None, description="Location/Junction name")
    latitude: Optional[float] = Field(default=None, description="Latitude coordinate from registry (None if unmapped)")
    longitude: Optional[float] = Field(default=None, description="Longitude coordinate from registry (None if unmapped)")
    city: Optional[str] = Field(default=None, description="City municipality")
    state: Optional[str] = Field(default=None, description="State jurisdiction")
    detected_at: datetime = Field(..., description="Authoritative observation timestamp derived from video PTS")
    video_pts_ms: Optional[float] = Field(default=None, description="Video presentation timestamp in milliseconds")
    vehicle_type: str = Field(..., description="Classified vehicle type")
    confidence_vehicle: Optional[float] = Field(default=None, description="Vehicle detection model confidence score")
    confidence_plate: Optional[float] = Field(default=None, description="Plate OCR confidence score")
    plate_number: Optional[str] = Field(default=None, description="Sanitized normalized license plate")
    raw_text: Optional[str] = Field(default=None, description="Raw unmodified OCR provider transcription")
    snapshot_path: str = Field(..., description="Path to captured full-frame snapshot")
    plate_crop_path: Optional[str] = Field(default=None, description="Path to cropped plate image if extracted")
    is_demo: bool = Field(default=False, description="Data provenance indicator: True if synthetic/demo stream")
    detection_metadata: Optional[Dict[str, Any]] = Field(default=None, description="Inference engine & frame metadata")
    created_at: datetime = Field(..., description="Database record insertion timestamp")


class VehicleQueryWindow(BaseModel):
    """Query temporal filtering window."""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class VehicleHistoryResponse(BaseModel):
    """Paginated chronological observation history response."""
    plate_number: str = Field(..., description="Normalized plate number searched")
    total_observations: int = Field(..., description="Total matching observations across query window")
    query_window: VehicleQueryWindow = Field(default_factory=VehicleQueryWindow)
    limit: int = Field(default=50, description="Page limit applied")
    skip: int = Field(default=0, description="Offset skip applied")
    items: List[VehicleObservationItem] = Field(default_factory=list, description="Chronological observations")


# Re-export Stage 12 Cross-Camera Correlation schemas
from backend.app.schemas.correlation import (  # noqa: E402
    CameraTransition,
    JourneyWaypoint,
    UnmappedWaypoint,
    VehicleJourneyResponse,
)

__all__ = [
    "VehicleProfileRead",
    "VehicleObservationItem",
    "VehicleQueryWindow",
    "VehicleHistoryResponse",
    "CameraTransition",
    "JourneyWaypoint",
    "UnmappedWaypoint",
    "VehicleJourneyResponse",
]
