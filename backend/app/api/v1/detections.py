"""Detections query and persistence REST API endpoints.

Protocol Standards:
- docs/api-contract.md Section 6.
- Stage 8 Directive Sections 4, 15, 21, 22.
- RFC 7807 structured error responses.
- Temporal and plate queries backed by database indexes.
"""

import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.core.auth import require_permission
from backend.app.core.permissions import PERMISSION_DETECTIONS_READ
from backend.app.models.access import User
from backend.app.schemas.detection import DetectionRead, DetectionListResponse
from backend.app.schemas.anpr import ANPRResult
from backend.app.services.event_persistence import (
    EventPersistenceService,
    CameraNotRegisteredError,
    EventValidationError,
    PersistenceError
)
from backend.app.services.realtime.envelope import EventType, RealtimeEventEnvelope
from backend.app.services.realtime.event_bus import event_bus

router = APIRouter(prefix="/detections", tags=["detections"])


@router.get("", response_model=DetectionListResponse)
def list_detections(
    plate_number: Optional[str] = Query(default=None, description="License plate search string (supports wildcards % _)"),
    camera_id: Optional[uuid.UUID] = Query(default=None, description="Filter by camera UUID"),
    vehicle_type: Optional[str] = Query(default=None, description="Filter by vehicle type (CAR, TRUCK, BUS, MOTORCYCLE)"),
    start_time: Optional[datetime] = Query(default=None, description="Start time range filter (UTC ISO 8601)"),
    end_time: Optional[datetime] = Query(default=None, description="End time range filter (UTC ISO 8601)"),
    limit: int = Query(default=50, ge=1, le=200, description="Page limit (max 200)"),
    skip: int = Query(default=0, ge=0, description="Offset pagination"),
    current_user: User = Depends(require_permission(PERMISSION_DETECTIONS_READ)),
    db: Session = Depends(get_db)
) -> DetectionListResponse:
    """Search and filter historical vehicle detections across the camera network."""
    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must be prior to end_time."
        )

    items, total = EventPersistenceService.query_detections(
        db=db,
        plate_number=plate_number,
        camera_id=camera_id,
        vehicle_type=vehicle_type,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        skip=skip
    )

    response_items = []
    for item in items:
        cam_name = item.camera.name if item.camera else None
        read_obj = DetectionRead(
            id=item.id,
            camera_id=item.camera_id,
            camera_name=cam_name,
            vehicle_id=item.vehicle_id,
            plate_number=item.plate_number,
            raw_text=item.raw_text,
            vehicle_type=item.vehicle_type,
            confidence_vehicle=item.confidence_vehicle,
            confidence_plate=item.confidence_plate,
            bbox_vehicle=item.bbox_vehicle,
            bbox_plate=item.bbox_plate,
            snapshot_path=item.snapshot_path,
            plate_crop_path=item.plate_crop_path,
            is_demo=item.is_demo,
            detected_at=item.detected_at,
            created_at=item.created_at,
            detection_metadata=item.detection_metadata
        )
        response_items.append(read_obj)

    return DetectionListResponse(total=total, items=response_items)


@router.get("/{detection_id}", response_model=DetectionRead)
def get_detection(
    detection_id: uuid.UUID,
    current_user: User = Depends(require_permission(PERMISSION_DETECTIONS_READ)),
    db: Session = Depends(get_db)
) -> DetectionRead:
    """Retrieve details for a single detection observation by UUID."""
    detection = EventPersistenceService.get_detection_by_id(db, detection_id)
    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Detection with ID '{detection_id}' not found."
        )

    cam_name = detection.camera.name if detection.camera else None
    return DetectionRead(
        id=detection.id,
        camera_id=detection.camera_id,
        camera_name=cam_name,
        vehicle_id=detection.vehicle_id,
        plate_number=detection.plate_number,
        raw_text=detection.raw_text,
        vehicle_type=detection.vehicle_type,
        confidence_vehicle=detection.confidence_vehicle,
        confidence_plate=detection.confidence_plate,
        bbox_vehicle=detection.bbox_vehicle,
        bbox_plate=detection.bbox_plate,
        snapshot_path=detection.snapshot_path,
        plate_crop_path=detection.plate_crop_path,
        is_demo=detection.is_demo,
        detected_at=detection.detected_at,
        created_at=detection.created_at,
        detection_metadata=detection.detection_metadata
    )


@router.post("", response_model=DetectionRead, status_code=status.HTTP_201_CREATED)
def persist_detection_event(
    anpr_result: ANPRResult,
    current_user: User = Depends(require_permission(PERMISSION_DETECTIONS_READ)),
    db: Session = Depends(get_db)
) -> DetectionRead:
    """Persist an upstream Stage 7 ANPRResult into the permanent detections store."""
    try:
        detection = EventPersistenceService.persist_anpr_result(
            db=db,
            anpr_result=anpr_result
        )
        event_bus.publish_sync(
            RealtimeEventEnvelope.create(
                event_type=EventType.DETECTION_CREATED.value,
                source="event_persistence",
                data={
                    "detection_id": str(detection.id),
                    "camera_id": str(detection.camera_id),
                    "plate_number": detection.plate_number,
                    "vehicle_type": detection.vehicle_type,
                    "confidence_plate": detection.confidence_plate,
                    "detected_at": detection.detected_at.isoformat() if detection.detected_at else None,
                }
            )
        )
        cam_name = detection.camera.name if detection.camera else None
        return DetectionRead(
            id=detection.id,
            camera_id=detection.camera_id,
            camera_name=cam_name,
            vehicle_id=detection.vehicle_id,
            plate_number=detection.plate_number,
            raw_text=detection.raw_text,
            vehicle_type=detection.vehicle_type,
            confidence_vehicle=detection.confidence_vehicle,
            confidence_plate=detection.confidence_plate,
            bbox_vehicle=detection.bbox_vehicle,
            bbox_plate=detection.bbox_plate,
            snapshot_path=detection.snapshot_path,
            plate_crop_path=detection.plate_crop_path,
            is_demo=detection.is_demo,
            detected_at=detection.detected_at,
            created_at=detection.created_at,
            detection_metadata=detection.detection_metadata
        )
    except CameraNotRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        ) from exc
    except EventValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc)
        ) from exc
    except PersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc)
        ) from exc
