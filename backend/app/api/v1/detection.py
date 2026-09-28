"""Vehicle detection inspection and visual debug REST endpoints.

Protocol Standards:
- docs/api-contract.md Section 6.
- Stage 6 Directive Section 23 (Visual debugging utility: DEBUG / TEST).
- Preserves stream camera_id and video_pts_ms.
"""

from typing import List
import cv2
from fastapi import APIRouter, HTTPException, Response, status

from backend.app.schemas.detection import (
    NormalizedVehicleDetection,
    DetectorStatusResponse
)
from backend.app.services.streaming.manager import stream_manager
from backend.app.services.detection.service import detection_service

router = APIRouter(prefix="/detection", tags=["detection"])


@router.get("/status", response_model=DetectorStatusResponse)
def get_detector_status() -> DetectorStatusResponse:
    """Fetch runtime telemetry and metadata for the active vehicle detector."""
    return detection_service.get_status()


@router.post("/detect-snapshot/{camera_id}", response_model=List[NormalizedVehicleDetection])
def detect_vehicles_on_latest_frame(camera_id: str) -> List[NormalizedVehicleDetection]:
    """Execute vehicle detection on the latest frame in an active camera stream buffer."""
    with stream_manager._workers_lock:
        worker = stream_manager._workers.get(camera_id)

    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active stream worker for camera '{camera_id}'."
        )

    latest_frame = worker.ring_buffer.peek_latest()
    if latest_frame is None or latest_frame.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No decoded video frames available in stream buffer for camera '{camera_id}'."
        )

    detections = detection_service.process_frame(latest_frame)
    return detections


@router.get("/debug-snapshot/{camera_id}")
def get_debug_annotated_snapshot(camera_id: str, quality: int = 80) -> Response:
    """Return latest frame with bounding boxes and PTS metadata rendered (DEBUG / TEST ONLY)."""
    with stream_manager._workers_lock:
        worker = stream_manager._workers.get(camera_id)

    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active stream worker for camera '{camera_id}'."
        )

    latest_frame = worker.ring_buffer.peek_latest()
    if latest_frame is None or latest_frame.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No decoded video frames available in stream buffer for camera '{camera_id}'."
        )

    detections = detection_service.process_frame(latest_frame)
    debug_img = detection_service.render_debug_frame(
        frame_data=latest_frame.data,
        detections=detections,
        camera_id=latest_frame.camera_id,
        pts_ms=latest_frame.pts_ms
    )

    success, encoded_img = cv2.imencode(
        ".jpg",
        debug_img,
        [int(cv2.IMWRITE_JPEG_QUALITY), max(10, min(100, quality))]
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to encode annotated debug frame as JPEG."
        )

    return Response(
        content=encoded_img.tobytes(),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Content-Type": "image/jpeg"
        }
    )
