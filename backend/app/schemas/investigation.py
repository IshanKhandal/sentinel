"""Pydantic schemas for Sentinel Stage 13 Investigation Engine."""

import re
import uuid
from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

# Allowed lifecycle statuses (docs/database-design.md Domain 5)
INVESTIGATION_STATUS_OPEN = "OPEN"
INVESTIGATION_STATUS_IN_PROGRESS = "IN_PROGRESS"
INVESTIGATION_STATUS_CLOSED = "CLOSED"
INVESTIGATION_STATUS_ARCHIVED = "ARCHIVED"

VALID_INVESTIGATION_STATUSES = {
    INVESTIGATION_STATUS_OPEN,
    INVESTIGATION_STATUS_IN_PROGRESS,
    INVESTIGATION_STATUS_CLOSED,
    INVESTIGATION_STATUS_ARCHIVED,
}

VALID_STATUS_TRANSITIONS = {
    INVESTIGATION_STATUS_OPEN: {INVESTIGATION_STATUS_IN_PROGRESS, INVESTIGATION_STATUS_CLOSED, INVESTIGATION_STATUS_ARCHIVED},
    INVESTIGATION_STATUS_IN_PROGRESS: {INVESTIGATION_STATUS_OPEN, INVESTIGATION_STATUS_CLOSED, INVESTIGATION_STATUS_ARCHIVED},
    INVESTIGATION_STATUS_CLOSED: {INVESTIGATION_STATUS_OPEN, INVESTIGATION_STATUS_IN_PROGRESS, INVESTIGATION_STATUS_ARCHIVED},
    INVESTIGATION_STATUS_ARCHIVED: {INVESTIGATION_STATUS_OPEN, INVESTIGATION_STATUS_CLOSED},
}

# Allowed forensic evidence types (docs/database-design.md Domain 5)
EVIDENCE_TYPE_PDF_DOSSIER = "PDF_DOSSIER"
EVIDENCE_TYPE_CROP_ARCHIVE = "CROP_ARCHIVE"
EVIDENCE_TYPE_EXPORT_JSON = "EXPORT_JSON"

VALID_EVIDENCE_TYPES = {
    EVIDENCE_TYPE_PDF_DOSSIER,
    EVIDENCE_TYPE_CROP_ARCHIVE,
    EVIDENCE_TYPE_EXPORT_JSON,
}

SHA256_REGEX = re.compile(r"^[a-fA-F0-9]{64}$")


class InvestigationEventCreate(BaseModel):
    """Payload to attach an observation or alert to an active case."""
    detection_id: Optional[uuid.UUID] = Field(None, description="Persisted vehicle detection UUID")
    alert_id: Optional[uuid.UUID] = Field(None, description="Persisted operational alert UUID")
    notes: Optional[str] = Field(None, max_length=1000, description="Investigator notes on attached event")

    @model_validator(mode="after")
    def validate_event_reference(self) -> "InvestigationEventCreate":
        if not self.detection_id and not self.alert_id:
            raise ValueError("At least one of detection_id or alert_id must be provided to attach an event.")
        return self


class InvestigationEventRead(BaseModel):
    """Attached event reference with joined detection/alert provenance."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    investigation_id: uuid.UUID
    detection_id: Optional[uuid.UUID] = None
    alert_id: Optional[uuid.UUID] = None
    sequence_order: int
    notes: Optional[str] = None
    added_at: datetime
    # Provenance fields extracted from referenced source event
    observation_timestamp: Optional[datetime] = None
    plate_number: Optional[str] = None
    camera_id: Optional[uuid.UUID] = None
    is_demo: bool = False


class EvidenceCreate(BaseModel):
    """Payload to register verified digital evidence metadata with SHA-256 integrity."""
    file_path: str = Field(..., min_length=1, max_length=500, description="Storage path of digital evidence asset")
    file_type: str = Field(..., description="Evidence asset type: PDF_DOSSIER, CROP_ARCHIVE, EXPORT_JSON")
    sha256_hash: str = Field(..., description="Cryptographic SHA-256 hash (64 hex characters) of evidence file")
    file_size_bytes: int = Field(..., ge=0, description="Exact size of digital evidence asset in bytes")
    generated_by_user_id: Optional[uuid.UUID] = Field(None, description="Authoring user UUID")

    @field_validator("file_type")
    @classmethod
    def validate_file_type(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean not in VALID_EVIDENCE_TYPES:
            raise ValueError(f"Invalid file_type '{v}'. Allowed types: {sorted(VALID_EVIDENCE_TYPES)}")
        return clean

    @field_validator("sha256_hash")
    @classmethod
    def validate_sha256(cls, v: str) -> str:
        clean = v.strip().lower()
        if not SHA256_REGEX.match(clean):
            raise ValueError("sha256_hash must be exactly 64 hexadecimal characters.")
        return clean


class EvidenceRead(BaseModel):
    """Forensic evidence metadata entity."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    investigation_id: uuid.UUID
    file_path: str
    file_type: str
    sha256_hash: str
    file_size_bytes: int
    generated_by_user_id: uuid.UUID
    created_at: datetime


class InvestigationCreate(BaseModel):
    """Payload to open a new police investigation case."""
    case_number: str = Field(..., min_length=1, max_length=100, description="Unique police case identifier (e.g. FIR-2026-0042)")
    title: str = Field(..., min_length=1, max_length=255, description="Investigation case title")
    description: Optional[str] = Field(None, description="Detailed case narrative or incident synopsis")
    target_plate: Optional[str] = Field(None, max_length=20, description="Target vehicle registration plate")
    lead_detective_id: Optional[uuid.UUID] = Field(None, description="Assigned lead investigator user UUID")

    @field_validator("case_number", "title")
    @classmethod
    def sanitize_non_empty(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Field cannot be empty or purely whitespace.")
        return clean

    @field_validator("target_plate")
    @classmethod
    def sanitize_plate(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = re.sub(r"[^A-Za-z0-9]", "", v).upper()
        return clean if clean else None


class InvestigationUpdate(BaseModel):
    """Payload to update investigation case details or progress lifecycle."""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    target_plate: Optional[str] = Field(None, max_length=20)
    status: Optional[str] = Field(None, description="New status: OPEN, IN_PROGRESS, CLOSED, ARCHIVED")
    lead_detective_id: Optional[uuid.UUID] = None

    @field_validator("title")
    @classmethod
    def sanitize_title(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip()
        if not clean:
            raise ValueError("title cannot be empty or purely whitespace.")
        return clean

    @field_validator("target_plate")
    @classmethod
    def sanitize_plate(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = re.sub(r"[^A-Za-z0-9]", "", v).upper()
        return clean if clean else None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip().upper()
        if clean not in VALID_INVESTIGATION_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Allowed statuses: {sorted(VALID_INVESTIGATION_STATUSES)}")
        return clean


class InvestigationRead(BaseModel):
    """Authoritative investigation case record with summary counts."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_number: str
    title: str
    description: Optional[str] = None
    target_plate: Optional[str] = None
    status: str
    lead_detective_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    event_count: int = 0
    evidence_count: int = 0
    events: Optional[List[InvestigationEventRead]] = None
    evidence_items: Optional[List[EvidenceRead]] = None


class InvestigationListResponse(BaseModel):
    """Paginated list of investigation cases."""
    items: List[InvestigationRead]
    total: int
    limit: int
    skip: int


class AttachVehicleHistoryRequest(BaseModel):
    """Payload to attach historical vehicle observations to an investigation."""
    detection_ids: Optional[List[uuid.UUID]] = Field(
        None,
        description="Explicit list of detection UUIDs to attach. If omitted, all verified detections for target_plate are attached."
    )
    notes: Optional[str] = Field(None, max_length=1000, description="Notes to associate with attached observation items")


class AttachAlertRequest(BaseModel):
    """Payload to attach an operational alert to an investigation."""
    alert_id: uuid.UUID = Field(..., description="Operational alert UUID to attach")
    notes: Optional[str] = Field(None, max_length=1000, description="Notes to associate with attached alert")
