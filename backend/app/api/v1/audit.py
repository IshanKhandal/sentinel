"""Immutable Audit Trail REST API endpoints.

Protocol Standards:
- docs/security-architecture.md Section 5 (Audit Logging & Non-Repudiation)
- docs/api-contract.md Section 15 & 16
- Clearance required: SuperAdmin or Auditor role (PERMISSION_AUDIT_READ)
- Invariant: Strictly append-only; NO PUT/PATCH/DELETE endpoints exposed.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.core.auth import require_permission
from backend.app.core.permissions import PERMISSION_AUDIT_READ
from backend.app.models.access import User
from backend.app.models.audit import AuditLog
from backend.app.schemas.audit import AuditLogRead, AuditLogListResponse

router = APIRouter(prefix="/audit-logs", tags=["Audit Trail"])


@router.get("", response_model=AuditLogListResponse, summary="Query immutable audit trail")
def list_audit_logs(
    action: Optional[str] = Query(None, description="Filter by action code"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type (USER, WATCHLIST, ALERT, INVESTIGATION)"),
    badge_number: Optional[str] = Query(None, description="Filter by officer badge number"),
    skip: int = Query(0, ge=0, description="Offset pagination"),
    limit: int = Query(50, ge=1, le=200, description="Page limit (max 200)"),
    current_user: User = Depends(require_permission(PERMISSION_AUDIT_READ)),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    """Inspect system audit records in reverse chronological order (SuperAdmin / Auditor only).
    
    Append-only guarantee: Audit records are permanently preserved and cannot be altered or deleted.
    """
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if badge_number:
        query = query.filter(AuditLog.badge_number == badge_number)

    total = query.count()
    items = query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).offset(skip).limit(limit).all()

    return AuditLogListResponse(
        total=total,
        items=[
            AuditLogRead(
                id=log.id,
                user_id=log.user_id,
                badge_number=log.badge_number,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                ip_address=log.ip_address,
                payload_summary=log.payload_summary,
                timestamp=log.timestamp,
            )
            for log in items
        ],
    )
