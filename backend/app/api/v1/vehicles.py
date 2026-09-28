"""Vehicle profile and chronological observation history REST API endpoints.

Protocol Standards:
- docs/api-contract.md Section 7 (Vehicles & Journey).
- Stage 11 Directive Sections 2-25.
- RFC 7807 compliant error responses.
- STRICT ISOLATION: No route reconstruction or speed inference (reserved for Stage 12).
"""

import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.vehicle import (
    VehicleProfileRead,
    VehicleHistoryResponse,
    VehicleQueryWindow,
    VehicleJourneyResponse,
)
from backend.app.services.vehicle import (
    VehicleService,
    VehicleNotFoundError,
    VehicleHistoryValidationError,
)
from backend.app.services.correlation import (
    CorrelationService,
    CorrelationValidationError,
    DEFAULT_MAX_SPEED_THRESHOLD_KMH,
)

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("/{plate_number}", response_model=VehicleProfileRead)
def get_vehicle_profile(
    plate_number: str,
    db: Session = Depends(get_db)
) -> VehicleProfileRead:
    """Retrieve canonical vehicle profile, observation statistics, and active watchlist status.
    
    Contract: docs/api-contract.md Section 7 (`GET /api/v1/vehicles/{plate_number}`).
    """
    clean_plate = plate_number.strip().upper()
    try:
        profile = VehicleService.get_vehicle_profile(db=db, plate_number=clean_plate)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vehicle '{clean_plate}' not found."
            )
        return profile
    except VehicleHistoryValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc


@router.get("/{plate_number}/history", response_model=VehicleHistoryResponse)
def get_vehicle_history(
    plate_number: str,
    start_time: Optional[datetime] = Query(default=None, description="Start observation timestamp filter (ISO 8601 UTC)"),
    end_time: Optional[datetime] = Query(default=None, description="End observation timestamp filter (ISO 8601 UTC)"),
    camera_id: Optional[uuid.UUID] = Query(default=None, description="Filter observations by specific camera UUID"),
    order: str = Query(default="asc", pattern="^(asc|desc|ASC|DESC)$", description="Sort order: 'asc' (chronological) or 'desc' (latest first)"),
    limit: int = Query(default=50, ge=1, le=200, description="Page limit (max 200)"),
    skip: int = Query(default=0, ge=0, description="Offset pagination"),
    db: Session = Depends(get_db)
) -> VehicleHistoryResponse:
    """Query chronological observation history for a license plate.
    
    Strict Invariants (Stage 11 Directive):
    - Reads persisted detections only (does not scan video streams).
    - Preserves authoritative observation timestamp from video PTS.
    - Resolves camera and location metadata from camera registry.
    - Unknown or unmapped coordinates returned as None (NEVER 0,0).
    - Empty searches return truthful empty result (200 OK with total=0, items=[]).
    - STRICTLY NO route reconstruction, speed estimation, or trajectory inference.
    """
    clean_plate = plate_number.strip().upper()
    try:
        items, total = VehicleService.get_vehicle_history(
            db=db,
            plate_number=clean_plate,
            start_time=start_time,
            end_time=end_time,
            camera_id=camera_id,
            order=order.lower(),
            limit=limit,
            skip=skip,
        )

        return VehicleHistoryResponse(
            plate_number=clean_plate,
            total_observations=total,
            query_window=VehicleQueryWindow(
                start_time=start_time,
                end_time=end_time,
            ),
            limit=limit,
            skip=skip,
            items=items,
        )
    except VehicleHistoryValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc


@router.get("/{plate_number}/journey", response_model=VehicleJourneyResponse)
@router.get("/{plate_number}/correlation", response_model=VehicleJourneyResponse)
def get_vehicle_journey(
    plate_number: str,
    start_time: Optional[datetime] = Query(default=None, description="Start observation timestamp filter (ISO 8601 UTC)"),
    end_time: Optional[datetime] = Query(default=None, description="End observation timestamp filter (ISO 8601 UTC)"),
    max_speed_kmh: float = Query(default=DEFAULT_MAX_SPEED_THRESHOLD_KMH, gt=0.0, description="Maximum physically plausible speed threshold in km/h"),
    limit: int = Query(default=500, ge=1, le=1000, description="Maximum observations to correlate"),
    db: Session = Depends(get_db)
) -> VehicleJourneyResponse:
    """Reconstruct cross-camera vehicle observation sequence, camera transitions, and implied velocity.

    Contract: docs/api-contract.md Section 7 (`GET /api/v1/vehicles/{plate_number}/journey`).

    Strict Invariants (Stage 12 Directive):
    - Reads persisted detections only (does not scan live streams).
    - Preserves authoritative observation timestamp from video PTS.
    - Groups consecutive same-camera detections into waypoints.
    - Computes inter-camera transitions (delta_t, Haversine distance, implied speed).
    - Flags physically implausible transitions (> max_speed_kmh) as ANOMALY.
    - Missing coordinates remain None (never 0,0); unmapped cameras excluded from polyline.
    - STRICTLY NO road route inference: LineString connects camera coordinates only.
    """
    clean_plate = plate_number.strip().upper()
    try:
        return CorrelationService.correlate_vehicle_journey(
            db=db,
            plate_number=clean_plate,
            start_time=start_time,
            end_time=end_time,
            max_speed_threshold_kmh=max_speed_kmh,
            limit=limit,
        )
    except CorrelationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc

