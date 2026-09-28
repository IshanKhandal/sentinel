"""Watchlist and WatchlistEntry Pydantic schemas and Match contracts.

Protocol Standards:
- docs/api-contract.md Section 8 (Watchlists).
- docs/database-design.md Domain 4 (Watchlists).
- Stage 9 Directive Sections 12, 13, 14, 15, 18.
- Match contract preserving complete observation provenance without alert firing.
"""

import uuid
from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class WatchlistCategory(str, Enum):
    """Authoritative police hotlist category metadata."""
    STOLEN = "STOLEN"
    WANTED = "WANTED"
    SUSPECT = "SUSPECT"
    EXPIRED = "EXPIRED"


class WatchlistSeverity(str, Enum):
    """Watchlist priority rating (metadata only, not real-time threat score)."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class WatchlistMatchMethod(str, Enum):
    """Method by which candidate observation matched enrolled watchlist entry."""
    EXACT = "EXACT"
    FUZZY = "FUZZY"


# ============================================================================
# Watchlist Core Schemas
# ============================================================================

class WatchlistBase(BaseModel):
    name: str = Field(..., max_length=150, description="Unique human-readable watchlist title")
    category: WatchlistCategory = Field(default=WatchlistCategory.SUSPECT, description="Operational classification")
    severity: WatchlistSeverity = Field(default=WatchlistSeverity.MEDIUM, description="Associated watchlist severity")
    is_active: bool = Field(default=True, description="Master operational toggle for this hotlist")


class WatchlistCreate(WatchlistBase):
    created_by_user_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Enrolling officer user UUID. If omitted, resolved to system user."
    )


class WatchlistUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=150)
    category: Optional[WatchlistCategory] = None
    severity: Optional[WatchlistSeverity] = None
    is_active: Optional[bool] = None


class WatchlistRead(WatchlistBase):
    id: uuid.UUID
    created_by_user_id: uuid.UUID
    created_at: datetime
    entries_count: Optional[int] = Field(default=0, description="Total active enrolled license plates")

    model_config = ConfigDict(from_attributes=True)


class WatchlistListResponse(BaseModel):
    total: int
    items: List[WatchlistRead]


# ============================================================================
# Watchlist Entry Schemas
# ============================================================================

class WatchlistEntryBase(BaseModel):
    plate_number: str = Field(..., max_length=20, description="Vehicle registration plate text")
    vehicle_make_model: Optional[str] = Field(default=None, max_length=100, description="Vehicle make/model description")
    fir_number: Optional[str] = Field(default=None, max_length=100, description="Official First Information Report reference")
    notes: Optional[str] = Field(default=None, description="Investigative notes or context")
    is_active: bool = Field(default=True, description="Entry active status")


class WatchlistEntryCreate(WatchlistEntryBase):
    pass


class WatchlistEntryUpdate(BaseModel):
    plate_number: Optional[str] = Field(default=None, max_length=20)
    vehicle_make_model: Optional[str] = Field(default=None, max_length=100)
    fir_number: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class WatchlistEntryRead(WatchlistEntryBase):
    id: uuid.UUID
    watchlist_id: uuid.UUID
    created_at: datetime
    watchlist_name: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class WatchlistEntryListResponse(BaseModel):
    total: int
    items: List[WatchlistEntryRead]


# ============================================================================
# Watchlist Match Result Contract (Stage 9 Directive Section 12)
# ============================================================================

class WatchlistMatchResult(BaseModel):
    """Complete provenance contract explaining a watchlist observation hit."""
    match_id: str = Field(..., description="Unique transient identifier for this match evaluation")
    detection_id: Optional[uuid.UUID] = Field(default=None, description="Persisted Stage 8 detection UUID")
    camera_id: Optional[uuid.UUID] = Field(default=None, description="Surveillance camera device UUID")
    camera_name: Optional[str] = Field(default=None, description="Human readable camera designation")
    detected_at: Optional[datetime] = Field(default=None, description="Authoritative observation UTC timestamp")
    video_pts_ms: Optional[float] = Field(default=None, description="Upstream video presentation timestamp in ms")
    is_demo: bool = Field(default=False, description="Whether observation originated from synthetic DEMO stream")
    
    # Observed plate data
    observed_raw_plate: Optional[str] = Field(default=None, description="Raw OCR character sequence before normalization")
    observed_normalized_plate: str = Field(..., description="Normalized alphanumeric license plate string")
    
    # Matched watchlist metadata
    watchlist_id: uuid.UUID = Field(..., description="Parent watchlist UUID")
    watchlist_name: str = Field(..., description="Parent watchlist title")
    watchlist_category: str = Field(..., description="Watchlist category (e.g. STOLEN, WANTED)")
    watchlist_severity: str = Field(..., description="Watchlist severity rating")
    watchlist_entry_id: uuid.UUID = Field(..., description="Matched target entry UUID")
    matched_plate: str = Field(..., description="Target plate enrolled in the watchlist entry")
    vehicle_make_model: Optional[str] = Field(default=None, description="Enrolled vehicle make/model")
    fir_number: Optional[str] = Field(default=None, description="Enrolled police FIR reference")
    notes: Optional[str] = Field(default=None, description="Enrolled operational notes")
    
    # Matching provenance
    match_method: WatchlistMatchMethod = Field(..., description="EXACT or FUZZY matching algorithm")
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="Normalized similarity rating [0.0 - 1.0]")
    edit_distance: int = Field(..., ge=0, description="Levenshtein character edit distance")
    ocr_confidence: Optional[float] = Field(default=None, description="Upstream OCR confidence rating")
    matcher_version: str = Field(default="1.0.0", description="Watchlist matching engine algorithm version")


class PlateMatchRequest(BaseModel):
    """Request schema for on-demand plate matching."""
    plate_number: str = Field(..., description="Target license plate string to test against watchlists")
    raw_text: Optional[str] = Field(default=None, description="Optional raw OCR observation text")
    camera_id: Optional[uuid.UUID] = Field(default=None, description="Optional camera UUID for provenance")
    video_pts_ms: Optional[float] = Field(default=None, description="Optional video PTS timestamp in milliseconds")
    ocr_confidence: Optional[float] = Field(default=None, description="Optional upstream OCR confidence rating")
    is_demo: bool = Field(default=False, description="Flag indicating synthetic DEMO observation")


class WatchlistMatchResponse(BaseModel):
    """Batch response of zero or more matching watchlist entries."""
    observed_plate: str
    total_matches: int
    matches: List[WatchlistMatchResult]
    evaluated_at: datetime
