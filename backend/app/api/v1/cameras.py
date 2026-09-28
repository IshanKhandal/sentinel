"""Camera REST API endpoints.

Protocol Standard: Section 18 of Phase 3 Directive & docs/api-contract.md.
"""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.core.auth import require_permission
from backend.app.core.permissions import PERMISSION_CAMERAS_READ, PERMISSION_CAMERAS_WRITE
from backend.app.models.access import User
from backend.app.models.surveillance import Camera
from backend.app.schemas.camera import CameraResponse, CameraCreate, CameraSyncResponse
from backend.app.services.camera_registry import CameraRegistryService
from backend.app.services.catalogue_client import (
    SentinelCatalogueClient,
    CatalogueHostNotConfiguredError,
    CatalogueConnectionError,
    CatalogueResponseError,
)

router = APIRouter(prefix="/cameras", tags=["Cameras"])


@router.get("", response_model=List[CameraResponse])
def list_cameras(
    status_filter: Optional[str] = Query(None, alias="status"),
    stream_type: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_permission(PERMISSION_CAMERAS_READ)),
    db: Session = Depends(get_db)
):
    """Retrieve list of all surveillance cameras with current stream states."""
    cameras = CameraRegistryService.list_cameras(
        db=db,
        status=status_filter,
        stream_type=stream_type,
        skip=skip,
        limit=limit
    )
    return cameras


@router.get("/{camera_id}", response_model=CameraResponse)
def get_camera(
    camera_id: uuid.UUID,
    current_user: User = Depends(require_permission(PERMISSION_CAMERAS_READ)),
    db: Session = Depends(get_db)
):
    """Retrieve a single surveillance camera by UUID."""
    camera = CameraRegistryService.get_camera(db=db, camera_id=camera_id)
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera with ID {camera_id} not found."
        )
    return camera


@router.post("", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
def create_camera(
    camera_in: CameraCreate,
    current_user: User = Depends(require_permission(PERMISSION_CAMERAS_WRITE)),
    db: Session = Depends(get_db)
):
    """Manually register a surveillance camera."""
    camera = Camera(
        location_id=camera_in.location_id,
        department_id=camera_in.department_id,
        name=camera_in.name,
        rtsp_url=camera_in.rtsp_url,
        stream_type=camera_in.stream_type,
        direction_heading=camera_in.direction_heading,
        fps_target=camera_in.fps_target,
        resolution=camera_in.resolution,
        status="OFFLINE",
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


@router.post("/sync", response_model=CameraSyncResponse)
def sync_camera_catalogue(
    current_user: User = Depends(require_permission(PERMISSION_CAMERAS_WRITE)),
    db: Session = Depends(get_db)
):
    """Trigger synchronization against the official Sentinel camera catalogue (GET /api/ingest).

    If SENTINEL_STREAM_HOST is not configured, returns a truthful BLOCKED status.
    """
    client = SentinelCatalogueClient()

    if not client.is_configured:
        return CameraSyncResponse(
            status="BLOCKED",
            message="SENTINEL_STREAM_HOST is not configured. Stream host is UNKNOWN / BLOCKED.",
            results=None
        )

    try:
        catalogue_cameras = client.fetch_catalogue()
    except CatalogueConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to connect to official Sentinel catalogue: {exc}"
        ) from exc
    except CatalogueResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Invalid catalogue response from Sentinel host: {exc}"
        ) from exc

    results = CameraRegistryService.sync_catalogue(db=db, catalogue_cameras=catalogue_cameras)
    return CameraSyncResponse(
        status="SUCCESS",
        message=f"Synchronized {results['total_catalogue']} cameras from official catalogue.",
        results=results
    )

