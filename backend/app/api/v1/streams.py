"""Stream ingestion and snapshot REST endpoints.

Protocol Standards:
- docs/api-contract.md Section 5.
- Controlled activation (no auto-opening every stream).
- Never report LIVE without verified frame decoding.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.surveillance import Camera
from backend.app.schemas.streaming import StreamSessionResponse, StreamActionResponse
from backend.app.services.streaming.manager import stream_manager
from backend.app.services.streaming.models import sanitize_stream_url

router = APIRouter(prefix="/streams", tags=["streams"])


@router.get("", response_model=List[StreamSessionResponse])
def list_active_streams() -> List[StreamSessionResponse]:
    """List all currently active camera stream sessions and real-time telemetry."""
    return stream_manager.list_active_streams()


@router.get("/{camera_id}/status", response_model=StreamSessionResponse)
def get_stream_status(camera_id: str, db: Session = Depends(get_db)) -> StreamSessionResponse:
    """Fetch current telemetry and health status for a camera stream."""
    session = stream_manager.get_stream_session(camera_id)
    if session:
        return session

    # Check database camera registry if stream is not currently active
    try:
        cam_uuid = uuid.UUID(camera_id)
        camera = db.query(Camera).filter(Camera.id == cam_uuid).first()
    except ValueError:
        camera = db.query(Camera).filter(Camera.name.ilike(f"%{camera_id}%")).first()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera with ID '{camera_id}' not found in registry."
        )

    # Return inactive / OFFLINE representation
    return StreamSessionResponse(
        camera_id=str(camera.id),
        stream_url=sanitize_stream_url(camera.rtsp_url),
        protocol="RTSP",
        codec=None,
        resolution=camera.resolution,
        connection_state="OFFLINE" if "unconfigured" not in camera.rtsp_url else "NOT_CONFIGURED",
        frames_received=0,
        frames_dropped=0,
        reconnect_count=0,
        decoder_errors=0,
        last_pts_ms=None,
        pts_delta_ms=None,
        fps_measured=None,
        current_backoff_seconds=0.0,
        buffer_depth=0,
        buffer_capacity=15,
        last_error="Stream worker not started (controlled activation policy)",
        started_at=None,
        last_frame_at=None
    )


@router.post("/{camera_id}/start", response_model=StreamActionResponse)
def start_camera_stream(camera_id: str, db: Session = Depends(get_db)) -> StreamActionResponse:
    """Initiate video stream ingestion worker for a registered camera."""
    try:
        cam_uuid = uuid.UUID(camera_id)
        camera = db.query(Camera).filter(Camera.id == cam_uuid).first()
    except ValueError:
        camera = db.query(Camera).filter(Camera.name.ilike(f"%{camera_id}%")).first()

    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found in registry."
        )

    if "unconfigured" in camera.rtsp_url:
        return StreamActionResponse(
            camera_id=str(camera.id),
            status="BLOCKED",
            message="Stream cannot be started: SENTINEL_STREAM_HOST is unset / stream host is UNKNOWN.",
            session=None
        )

    session = stream_manager.start_stream(
        camera_id=str(camera.id),
        rtsp_url=camera.rtsp_url
    )

    return StreamActionResponse(
        camera_id=str(camera.id),
        status="STARTED",
        message="Stream ingestion worker started successfully.",
        session=session
    )


@router.post("/{camera_id}/stop", response_model=StreamActionResponse)
def stop_camera_stream(camera_id: str) -> StreamActionResponse:
    """Stop an active camera stream worker and release decoder resources."""
    stopped = stream_manager.stop_stream(camera_id)
    if stopped:
        return StreamActionResponse(
            camera_id=camera_id,
            status="STOPPED",
            message="Stream ingestion worker stopped.",
            session=None
        )

    return StreamActionResponse(
        camera_id=camera_id,
        status="NOT_RUNNING",
        message="Stream worker was not running.",
        session=None
    )


@router.get("/{camera_id}/snapshot")
def get_camera_snapshot(camera_id: str) -> Response:
    """Retrieve the latest cached JPEG frame snapshot from an active stream."""
    jpeg_bytes = stream_manager.get_snapshot_jpeg(camera_id)
    if not jpeg_bytes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No cached frame available for camera '{camera_id}'. Stream may be offline or inactive."
        )

    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Content-Type": "image/jpeg"
        }
    )
