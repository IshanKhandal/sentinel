"""Alert query, generation, and lifecycle REST API endpoints.

Protocol Standards:
- docs/api-contract.md Section 9 (Alerts).
- Stage 10 Directive Sections 3, 6, 7, 8, 9, 16, 17, 18, 19, 20.
- RFC 7807 compliant error responses.
- Stage 10 Boundary: NO external notifications or WebSocket delivery.
"""

import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.alert import (
    AlertRead,
    AlertListResponse,
    AlertAcknowledgeRequest,
    AlertStatusUpdateRequest,
    AlertEngineResult,
)
from backend.app.schemas.watchlist import WatchlistMatchResult
from backend.app.services.alert import (
    AlertEngine,
    AlertService,
    AlertNotFoundError,
    AlertLifecycleError,
    AlertProvenanceError,
    AlertValidationError,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=AlertListResponse)
def list_alerts(
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (NEW, ACKNOWLEDGED, RESOLVED, DISMISSED)"),
    severity: Optional[str] = Query(default=None, description="Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)"),
    camera_id: Optional[uuid.UUID] = Query(default=None, description="Filter by camera UUID"),
    plate_number: Optional[str] = Query(default=None, description="Filter by plate number (supports wildcards % _)"),
    start_time: Optional[datetime] = Query(default=None, description="Start created_at timestamp filter"),
    end_time: Optional[datetime] = Query(default=None, description="End created_at timestamp filter"),
    limit: int = Query(default=50, ge=1, le=200, description="Page limit (max 200)"),
    skip: int = Query(default=0, ge=0, description="Offset pagination"),
    db: Session = Depends(get_db)
) -> AlertListResponse:
    """Query real-time and historical watchlist match alerts (docs/api-contract.md Section 9)."""
    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must be prior to end_time."
        )

    alerts, total = AlertService.list_alerts(
        db=db,
        status=status_filter,
        severity=severity,
        camera_id=camera_id,
        plate_number=plate_number,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        skip=skip
    )

    items = [AlertEngine.build_alert_read_dto(alert) for alert in alerts]
    return AlertListResponse(total=total, items=items)


@router.get("/{alert_id}", response_model=AlertRead)
def get_alert(
    alert_id: uuid.UUID,
    db: Session = Depends(get_db)
) -> AlertRead:
    """Retrieve details and complete observation provenance of a single alert."""
    alert = AlertService.get_alert(db=db, alert_id=alert_id)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert '{alert_id}' not found."
        )
    return AlertEngine.build_alert_read_dto(alert)


@router.patch("/{alert_id}/acknowledge", response_model=AlertRead)
def acknowledge_alert(
    alert_id: uuid.UUID,
    payload: AlertAcknowledgeRequest,
    db: Session = Depends(get_db)
) -> AlertRead:
    """Acknowledge and claim an alert by a responding police officer (docs/api-contract.md Section 9)."""
    try:
        alert = AlertService.acknowledge_alert(
            db=db,
            alert_id=alert_id,
            user_id=payload.acknowledged_by_user_id,
            resolution_notes=payload.resolution_notes,
        )
        return AlertEngine.build_alert_read_dto(alert)
    except AlertNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        ) from exc
    except AlertLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc


@router.patch("/{alert_id}/status", response_model=AlertRead)
def update_alert_status(
    alert_id: uuid.UUID,
    payload: AlertStatusUpdateRequest,
    db: Session = Depends(get_db)
) -> AlertRead:
    """Update lifecycle disposition of an alert (e.g. RESOLVED, DISMISSED)."""
    try:
        alert = AlertService.update_alert_status(
            db=db,
            alert_id=alert_id,
            new_status=payload.status,
            resolution_notes=payload.resolution_notes,
            user_id=payload.user_id,
        )
        return AlertEngine.build_alert_read_dto(alert)
    except AlertNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        ) from exc
    except AlertLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc


@router.post("/evaluate-matches", response_model=AlertEngineResult, status_code=status.HTTP_201_CREATED)
def evaluate_matches(
    matches: List[WatchlistMatchResult],
    window_seconds: Optional[int] = Query(default=None, ge=0, le=3600, description="Override 60-second deduplication window"),
    db: Session = Depends(get_db)
) -> AlertEngineResult:
    """Evaluate a batch of Stage 9 WatchlistMatchResults through the Alert Engine.
    
    Creates qualifying alert records with 60-second deduplication.
    """
    try:
        return AlertEngine.process_matches(
            db=db,
            matches=matches,
            window_seconds=window_seconds,
        )
    except AlertProvenanceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc
    except AlertValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc
