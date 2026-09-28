"""Pydantic schemas for immutable operational audit logs.

Protocol Standards:
- docs/security-architecture.md Section 5 (Audit Logging & Non-Repudiation)
- docs/database-design.md Domain 6 (audit_logs)
"""

import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class AuditLogRead(BaseModel):
    """Immutable audit record representation."""
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: int = Field(..., description="Monotonic integer audit sequence identifier")
    user_id: Optional[uuid.UUID] = Field(None, description="Acting user UUID if authenticated")
    badge_number: str = Field(..., description="Badge identifier of acting officer")
    action: str = Field(..., description="Action code (e.g. AUTH_LOGIN_SUCCESS, WATCHLIST_CREATE)")
    resource_type: str = Field(..., description="Target resource domain (USER, WATCHLIST, ALERT, INVESTIGATION)")
    resource_id: Optional[str] = Field(None, description="Target resource identifier")
    ip_address: str = Field(..., description="Client IP address recorded at request time")
    payload_summary: Optional[str] = Field(None, description="Sanitized summary JSON of the event")
    timestamp: datetime = Field(..., description="UTC creation timestamp")


class AuditLogListResponse(BaseModel):
    """Paginated list of immutable audit records."""
    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., ge=0, description="Total audit records matching filters")
    items: List[AuditLogRead] = Field(..., description="Audit record objects in reverse chronological order")
