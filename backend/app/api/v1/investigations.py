"""REST API endpoints for Sentinel Stage 13 Investigation Engine.

Protocol Standards:
- docs/api-contract.md Section 10 (Investigations).
- Stage 13 Directive Sections 1-28.
- RFC 7807 compliant error handling.
"""

import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.investigation import (
    InvestigationCreate,
    InvestigationUpdate,
    InvestigationRead,
    InvestigationListResponse,
    InvestigationEventCreate,
    InvestigationEventRead,
    EvidenceCreate,
    EvidenceRead,
    AttachVehicleHistoryRequest,
    AttachAlertRequest,
)
from backend.app.schemas.correlation import VehicleJourneyResponse
from backend.app.services.investigation import (
    InvestigationService,
    InvestigationNotFoundError,
    InvestigationValidationError,
    InvestigationDuplicateError,
    InvestigationEventDuplicateError,
    InvestigationEventNotFoundError,
    ReferencedEntityNotFoundError,
)
from backend.app.services.correlation import CorrelationValidationError
from backend.app.services.realtime.envelope import EventType, RealtimeEventEnvelope
from backend.app.services.realtime.event_bus import event_bus

router = APIRouter(prefix="/investigations", tags=["Investigations"])


def _extract_client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


# ---------------------------------------------------------------------------
# 1. Investigation CRUD & Search Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=InvestigationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create police investigation case",
)
def create_investigation(
    data: InvestigationCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> InvestigationRead:
    """Create a new police case dossier to track vehicles or incident timelines."""
    try:
        inv = InvestigationService.create_investigation(
            db=db,
            data=data,
            ip_address=_extract_client_ip(request),
        )
        return InvestigationService._serialize_investigation(inv)
    except InvestigationDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except InvestigationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=InvestigationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List and search investigations",
)
def list_investigations(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by case status: OPEN, IN_PROGRESS, CLOSED, ARCHIVED"),
    target_plate: Optional[str] = Query(None, description="Filter by target vehicle license plate"),
    case_number: Optional[str] = Query(None, description="Filter by case number (partial or exact)"),
    limit: int = Query(50, ge=1, le=100, description="Pagination limit"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
) -> InvestigationListResponse:
    """List investigation cases with filtering and deterministic pagination."""
    items, total = InvestigationService.list_investigations(
        db=db,
        status=status_filter,
        target_plate=target_plate,
        case_number=case_number,
        limit=limit,
        skip=skip,
    )
    return InvestigationListResponse(
        items=items,
        total=total,
        limit=limit,
        skip=skip,
    )


@router.get(
    "/{investigation_id}",
    response_model=InvestigationRead,
    status_code=status.HTTP_200_OK,
    summary="Get investigation case details",
)
def get_investigation(
    investigation_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> InvestigationRead:
    """Retrieve full investigation case dossier with attached events and evidence counts."""
    try:
        return InvestigationService.get_investigation(
            db=db,
            investigation_id=investigation_id,
        )
    except InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{investigation_id}",
    response_model=InvestigationRead,
    status_code=status.HTTP_200_OK,
    summary="Update case metadata or progress lifecycle",
)
def update_investigation(
    investigation_id: uuid.UUID,
    data: InvestigationUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> InvestigationRead:
    """Update case description, target plate, lead detective, or advance lifecycle status."""
    try:
        updated = InvestigationService.update_investigation(
            db=db,
            investigation_id=investigation_id,
            data=data,
            ip_address=_extract_client_ip(request),
        )
        event_bus.publish_sync(
            RealtimeEventEnvelope.create(
                event_type=EventType.INVESTIGATION_UPDATED.value,
                source="investigation_service",
                data={
                    "investigation_id": str(updated.id),
                    "case_number": updated.case_number,
                    "status": updated.status,
                    "update_type": "lifecycle_update",
                }
            )
        )
        return updated
    except InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvestigationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ReferencedEntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# 2. Event Attachment Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{investigation_id}/events",
    response_model=InvestigationEventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Attach observation or alert to investigation",
)
def attach_event(
    investigation_id: uuid.UUID,
    data: InvestigationEventCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> InvestigationEventRead:
    """Tag and attach a verified detection or operational alert to the investigation timeline."""
    try:
        ev = InvestigationService.attach_event(
            db=db,
            investigation_id=investigation_id,
            data=data,
            ip_address=_extract_client_ip(request),
        )
        event_bus.publish_sync(
            RealtimeEventEnvelope.create(
                event_type=EventType.INVESTIGATION_UPDATED.value,
                source="investigation_service",
                data={
                    "investigation_id": str(investigation_id),
                    "event_id": str(ev.id),
                    "attached_event_type": "DETECTION" if data.detection_id else "ALERT",
                    "update_type": "event_attached",
                }
            )
        )
        return ev
    except InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ReferencedEntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvestigationEventDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except InvestigationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/{investigation_id}/events",
    response_model=List[InvestigationEventRead],
    status_code=status.HTTP_200_OK,
    summary="Get attached events timeline",
)
def get_investigation_events(
    investigation_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> List[InvestigationEventRead]:
    """Retrieve all observation and alert events attached to this investigation in chronological sequence."""
    try:
        return InvestigationService.get_investigation_events(
            db=db,
            investigation_id=investigation_id,
        )
    except InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{investigation_id}/events/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach event from investigation",
)
def detach_event(
    investigation_id: uuid.UUID,
    event_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """Remove an attached observation or alert reference from an investigation."""
    try:
        InvestigationService.detach_event(
            db=db,
            investigation_id=investigation_id,
            event_id=event_id,
            ip_address=_extract_client_ip(request),
        )
    except (InvestigationNotFoundError, InvestigationEventNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/{investigation_id}/attach-history",
    response_model=List[InvestigationEventRead],
    status_code=status.HTTP_201_CREATED,
    summary="Attach verified vehicle history sightings",
)
def attach_vehicle_history(
    investigation_id: uuid.UUID,
    data: AttachVehicleHistoryRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> List[InvestigationEventRead]:
    """Attach verified detection records for target plate (or explicit detection UUIDs) from Stage 11."""
    try:
        return InvestigationService.attach_vehicle_history(
            db=db,
            investigation_id=investigation_id,
            detection_ids=data.detection_ids,
            notes=data.notes,
            ip_address=_extract_client_ip(request),
        )
    except InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ReferencedEntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvestigationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# 3. Stage 12 Cross-Camera Correlation Reference Integration
# ---------------------------------------------------------------------------

@router.get(
    "/{investigation_id}/correlation",
    response_model=VehicleJourneyResponse,
    status_code=status.HTTP_200_OK,
    summary="Get cross-camera correlation for target vehicle",
)
def get_investigation_correlation(
    investigation_id: uuid.UUID,
    start_time: Optional[datetime] = Query(None, description="Optional window start ISO timestamp"),
    end_time: Optional[datetime] = Query(None, description="Optional window end ISO timestamp"),
    max_speed_kmh: Optional[float] = Query(None, gt=0, description="Plausibility threshold km/h"),
    db: Session = Depends(get_db),
) -> VehicleJourneyResponse:
    """Retrieve Stage 12 cross-camera correlation for target plate without recalculating GIS/spatial graph."""
    try:
        return InvestigationService.get_investigation_correlation(
            db=db,
            investigation_id=investigation_id,
            start_time=start_time,
            end_time=end_time,
            max_speed_kmh=max_speed_kmh,
        )
    except InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvestigationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except CorrelationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# 4. Evidence Metadata Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{investigation_id}/evidence",
    response_model=EvidenceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Attach verified evidence metadata",
)
def attach_evidence(
    investigation_id: uuid.UUID,
    data: EvidenceCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> EvidenceRead:
    """Register verified digital evidence asset metadata with cryptographic SHA-256 hash."""
    try:
        return InvestigationService.attach_evidence(
            db=db,
            investigation_id=investigation_id,
            data=data,
            ip_address=_extract_client_ip(request),
        )
    except InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvestigationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/{investigation_id}/evidence",
    response_model=List[EvidenceRead],
    status_code=status.HTTP_200_OK,
    summary="List evidence assets",
)
def list_evidence(
    investigation_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> List[EvidenceRead]:
    """List registered forensic evidence items for an investigation."""
    try:
        return InvestigationService.list_evidence(
            db=db,
            investigation_id=investigation_id,
        )
    except InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# 5. Evidence Export Guard (Section 17: EVIDENCE EXPORT NOT IMPLEMENTED)
# ---------------------------------------------------------------------------

@router.post(
    "/{investigation_id}/export",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Export cryptographic evidence dossier (Reserved)",
)
def export_investigation_dossier(
    investigation_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Evidence export placeholder adhering strictly to Stage 13 Directive Section 17.
    
    Status: EVIDENCE EXPORT NOT IMPLEMENTED.
    Cryptographic dossier generation and ZIP/PDF packaging are reserved for export engine.
    """
    # Verify case exists first
    try:
        InvestigationService.get_investigation_entity(db, investigation_id)
    except InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="EVIDENCE EXPORT NOT IMPLEMENTED: Dossier generation and cryptographic packaging is reserved for export engine.",
    )
