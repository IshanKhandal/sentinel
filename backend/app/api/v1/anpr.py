"""ANPR inspection and visual debug REST endpoints.

Protocol Standards:
- docs/api-contract.md Section 6.
- Stage 7 Directive Sections 3, 15, 19, 23.
- Consumes Stage 6 vehicle detections on Stage 5 stream frames.
- Preserves authoritative stream camera_id and video_pts_ms.
"""

from typing import List, Optional
import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Response, status, UploadFile, File, Form

from backend.app.schemas.anpr import ANPRResult, ANPRStatusResponse
from backend.app.schemas.detection import BoundingBox, NormalizedVehicleDetection
from backend.app.services.streaming.manager import stream_manager
from backend.app.services.streaming.models import DecodedFrame
from backend.app.services.detection.service import detection_service
from backend.app.services.anpr.pipeline import anpr_pipeline_service

router = APIRouter(prefix="/anpr", tags=["anpr"])


@router.get("/status", response_model=ANPRStatusResponse)
def get_anpr_status() -> ANPRStatusResponse:
    """Fetch runtime telemetry and metadata for the active ANPR subsystem."""
    return anpr_pipeline_service.get_status()


@router.post("/process-snapshot/{camera_id}", response_model=List[ANPRResult])
def process_anpr_on_latest_frame(camera_id: str) -> List[ANPRResult]:
    """Execute complete ANPR pipeline on the latest frame in an active camera stream buffer."""
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

    # 1. Run Stage 6 Vehicle Detection
    vehicle_detections = detection_service.process_frame(latest_frame)

    # 2. Run Stage 7 ANPR Pipeline
    anpr_results = anpr_pipeline_service.process_frame(latest_frame, vehicle_detections)
    return anpr_results


@router.get("/debug-snapshot/{camera_id}")
def get_debug_anpr_snapshot(camera_id: str, quality: int = 80) -> Response:
    """Return latest frame with vehicle and plate annotations rendered (DEBUG / TEST ONLY)."""
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

    vehicle_detections = detection_service.process_frame(latest_frame)
    anpr_results = anpr_pipeline_service.process_frame(latest_frame, vehicle_detections)

    debug_img = anpr_pipeline_service.render_debug_anpr_frame(
        frame_data=latest_frame.data,
        anpr_results=anpr_results,
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


@router.post("/process-image", response_model=List[ANPRResult])
async def process_anpr_test_image(
    file: UploadFile = File(...),
    camera_id: str = Form(default="TEST_CAMERA_UPLOAD"),
    pts_ms: float = Form(default=0.0)
) -> List[ANPRResult]:
    """Execute ANPR pipeline on an uploaded test image (FOR OFFLINE / BENCHMARK / CI TESTING)."""
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to decode uploaded image file."
        )

    frame = DecodedFrame(
        frame_index=1,
        camera_id=camera_id,
        pts_ms=pts_ms,
        data=img,
        width=img.shape[1],
        height=img.shape[0],
        monotonic_ts=float(pts_ms / 1000.0)
    )

    # 1. Detect vehicles
    vehicle_detections = detection_service.process_frame(frame)

    # If vehicle detector returned nothing (e.g. if test image is a close-up vehicle), treat whole image as vehicle
    if not vehicle_detections:
        h, w = img.shape[:2]
        vehicle_detections = [
            NormalizedVehicleDetection(
                camera_id=camera_id,
                video_pts_ms=pts_ms,
                class_id=2,
                class_name="car",
                confidence=0.95,
                bbox=BoundingBox(x1=0.0, y1=0.0, x2=float(w), y2=float(h)),
                frame_index=1,
                inference_time_ms=0.0,
                model_version="test-fallback"
            )
        ]

    # 2. Process ANPR
    results = anpr_pipeline_service.process_frame(frame, vehicle_detections)
    return results
