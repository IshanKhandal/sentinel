"""Alert engine Pydantic schemas and response contracts.

Protocol Standards:
- docs/api-contract.md Section 9 (Alerts).
- docs/database-design.md Domain 4 (Alerts).
- Stage 10 Directive Sections 3, 6, 7, 8, 9, 16, 17, 18, 19, 20.
- Preserves full provenance chain: Alert -> Watchlist Match -> Detection -> Camera.
"""

import uuid
from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class AlertStatus(str, Enum):
    """Lifecycle states of an operational alert."""
    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class AlertSeverity(str, Enum):
    """Priority severity classifications inherited from matched watchlist."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ============================================================================
# Alert Request Schemas
# ============================================================================

class AlertAcknowledgeRequest(BaseModel):
    """Payload for acknowledging and claiming an incident alert."""
    resolution_notes: Optional[str] = Field(
        default=None,
        description="Operational notes or dispatch details by responding officer"
    )
    acknowledged_by_user_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Responding officer user UUID (resolved to system user if omitted)"
    )


class AlertStatusUpdateRequest(BaseModel):
    """Payload for updating the status of an alert (e.g. RESOLVED, DISMISSED)."""
    status: AlertStatus = Field(..., description="Target lifecycle state")
    resolution_notes: Optional[str] = Field(
        default=None,
        description="Detailed notes explaining disposition or resolution"
    )
    user_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Officer user UUID modifying the alert status"
    )


# ============================================================================
# Alert Response & Provenance Schemas
# ============================================================================

class AlertRead(BaseModel):
    """Authoritative alert entity with full observation provenance."""
    id: uuid.UUID
    detection_id: uuid.UUID
    watchlist_entry_id: uuid.UUID
    camera_id: uuid.UUID
    camera_name: Optional[str] = None
    plate_number: str
    severity: str
    status: str
    acknowledged_by_user_id: Optional[uuid.UUID] = None
    acknowledged_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    created_at: datetime  # Alert record insertion timestamp

    # Observation Provenance (Section 6, 7, 20)
    observed_at: Optional[datetime] = Field(
        default=None,
        description="Authoritative video observation timestamp derived from upstream video PTS"
    )
    video_pts_ms: Optional[float] = Field(
        default=None,
        description="Upstream video presentation timestamp in milliseconds"
    )
    is_demo: bool = Field(
        default=False,
        description="Whether observation originated from synthetic DEMO stream"
    )
    raw_text: Optional[str] = Field(
        default=None,
        description="Raw OCR plate text before normalization"
    )
    snapshot_path: Optional[str] = Field(
        default=None,
        description="Path to stored camera frame snapshot image"
    )

    # Watchlist Provenance
    watchlist_id: Optional[uuid.UUID] = None
    watchlist_name: Optional[str] = None
    watchlist_category: Optional[str] = None
    vehicle_make_model: Optional[str] = None
    fir_number: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AlertListResponse(BaseModel):
    """Paginated list of operational alerts."""
    total: int
    items: List[AlertRead]


class AlertEngineResult(BaseModel):
    """Summary of alert processing for a batch of watchlist matches."""
    alerts_created: List[AlertRead]
    deduplicated_count: int
    total_matches_evaluated: int
