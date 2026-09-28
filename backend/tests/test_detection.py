"""Automated unit and integration tests for Sentinel Vehicle Detection Subsystem.

Protocol Standards:
- docs/engineering-rules.md Rules 29, 30, 31.
- Stage 6 Directive Sections 1, 2, 4, 5, 6, 9, 12, 13, 14, 20, 21, 23, 24, 31.
"""

import time
import uuid
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas.detection import (
    BoundingBox,
    NormalizedVehicleDetection,
    DetectorStatusResponse
)
from backend.app.services.detection.preprocessing import letterbox, reverse_letterbox_bbox
from backend.app.services.detection.base import DEFAULT_COCO_VEHICLE_CLASSES
from backend.app.services.detection.mock_detector import MockObjectDetector
from backend.app.services.detection.onnx_detector import ONNXRuntimeObjectDetector
from backend.app.services.detection.service import VehicleDetectionService, detection_service
from backend.app.services.streaming.models import DecodedFrame
from backend.app.services.streaming.worker import StreamWorker
from backend.app.services.streaming.manager import stream_manager


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. BoundingBox Schema & Geometry Validation (Section 20, 21)
# ---------------------------------------------------------------------------

def test_bounding_box_valid_geometry():
    box = BoundingBox(x1=10.0, y1=20.0, x2=110.0, y2=120.0)
    assert box.width == 100.0
    assert box.height == 100.0
    assert box.area == 10000.0
    assert box.center == (60.0, 70.0)
    assert box.as_tuple() == (10.0, 20.0, 110.0, 120.0)


def test_bounding_box_rejects_inverted_x():
    with pytest.raises(ValueError, match="x1 .* must be strictly less than x2"):
        BoundingBox(x1=100.0, y1=10.0, x2=50.0, y2=80.0)


def test_bounding_box_rejects_inverted_y():
    with pytest.raises(ValueError, match="y1 .* must be strictly less than y2"):
        BoundingBox(x1=10.0, y1=100.0, x2=50.0, y2=50.0)


def test_bounding_box_rejects_negative_or_nan():
    with pytest.raises(ValueError, match="Coordinate cannot be negative"):
        BoundingBox(x1=-5.0, y1=10.0, x2=50.0, y2=80.0)

    with pytest.raises(ValueError, match="Coordinate cannot be NaN"):
        BoundingBox(x1=float("nan"), y1=10.0, x2=50.0, y2=80.0)


def test_bounding_box_normalization():
    box = BoundingBox(x1=100.0, y1=200.0, x2=500.0, y2=600.0)
    norm = box.to_normalized(frame_width=1000, frame_height=1000)
    assert norm == (0.1, 0.2, 0.5, 0.6)


# ---------------------------------------------------------------------------
# 2. Aspect-Ratio Preserving Letterbox & Reversal (Section 9, 21)
# ---------------------------------------------------------------------------

def test_letterbox_preserves_aspect_ratio_and_pads():
    # Source image: 1280x720 (16:9)
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    padded, scale, (pad_x, pad_y) = letterbox(img, target_shape=(640, 640))

    assert padded.shape == (640, 640, 3)
    # Scale = 640 / 1280 = 0.5
    assert scale == 0.5
    # Scaled width = 640, scaled height = 360 -> pad_y = (640 - 360) / 2 = 140
    assert pad_x == 0
    assert pad_y == 140


def test_reverse_letterbox_bbox_recovers_original_coordinates():
    # Source: 1280x720
    # Scaled by 0.5, pad_y=140
    # A box in letterbox space: x1=50, y1=190, x2=250, y2=340
    orig_shape = (1280, 720)
    scale = 0.5
    pad = (0, 140)

    box_letterbox = (50.0, 190.0, 250.0, 340.0)
    reversed_box = reverse_letterbox_bbox(box_letterbox, scale=scale, pad=pad, orig_shape=orig_shape)

    # unpad_x1 = 50 / 0.5 = 100
    # unpad_y1 = (190 - 140) / 0.5 = 100
    # unpad_x2 = 250 / 0.5 = 500
    # unpad_y2 = (340 - 140) / 0.5 = 400
    assert reversed_box.x1 == 100.0
    assert reversed_box.y1 == 100.0
    assert reversed_box.x2 == 500.0
    assert reversed_box.y2 == 400.0


# ---------------------------------------------------------------------------
# 3. Detector Interface, PTS & Camera ID Propagation (Section 5, 13, 14)
# ---------------------------------------------------------------------------

def test_mock_detector_metadata_and_classes():
    detector = MockObjectDetector(confidence_threshold=0.30)
    detector.load()
    assert detector.is_loaded is True

    meta = detector.metadata()
    assert meta["backend"] == "MOCK"
    assert meta["confidence_threshold"] == 0.30
    assert "car" in meta["supported_classes"]
    assert "truck" in meta["supported_classes"]


def test_mock_detector_propagates_camera_id_and_pts():
    detector = MockObjectDetector(confidence_threshold=0.25)
    test_cam_id = str(uuid.uuid4())
    test_pts = 42850.5  # 42.85 seconds video PTS from Stage 5

    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame = DecodedFrame(
        frame_index=15,
        camera_id=test_cam_id,
        pts_ms=test_pts,
        data=dummy_frame,
        width=640,
        height=480,
        monotonic_ts=time.monotonic()
    )

    detections = detector.detect(frame)
    assert len(detections) > 0

    det = detections[0]
    # Critical verification: camera_id and video_pts_ms are strictly preserved
    assert det.camera_id == test_cam_id
    assert det.video_pts_ms == test_pts
    assert det.frame_index == 15
    assert det.class_name in ("car", "motorcycle", "bus", "truck")
    assert 0.0 <= det.confidence <= 1.0
    assert det.bbox.x2 <= 640.0
    assert det.bbox.y2 <= 480.0


def test_mock_detector_handles_empty_or_none_frame():
    detector = MockObjectDetector()
    assert detector.detect(None) == []

    empty_frame = DecodedFrame(
        frame_index=0,
        camera_id="cam-1",
        pts_ms=0.0,
        data=np.array([]),
        width=0,
        height=0,
        monotonic_ts=time.monotonic()
    )
    assert detector.detect(empty_frame) == []


def test_onnx_detector_raises_on_missing_model():
    detector = ONNXRuntimeObjectDetector(model_path="non_existent_weights.onnx")
    with pytest.raises(FileNotFoundError, match="ONNX model file not found"):
        detector.load()


# ---------------------------------------------------------------------------
# 4. Frame Sampling Decimation & Visual Debugger (Section 16, 23)
# ---------------------------------------------------------------------------

def test_detection_service_frame_sampling_decimation():
    service = VehicleDetectionService()
    # Force FPS limit to 2.0 (500ms min interval)
    service.fps_limit = 2.0
    service.min_interval_sec = 0.5
    cam_id = "test-decimate-cam"

    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    f1 = DecodedFrame(frame_index=1, camera_id=cam_id, pts_ms=100.0, data=dummy_frame, width=640, height=480, monotonic_ts=time.monotonic())
    f2 = DecodedFrame(frame_index=2, camera_id=cam_id, pts_ms=133.0, data=dummy_frame, width=640, height=480, monotonic_ts=time.monotonic())

    # First frame processes
    dets1 = service.process_frame(f1)
    assert len(dets1) > 0

    # Second frame arrives immediately (within 500ms) -> skipped
    dets2 = service.process_frame(f2)
    assert dets2 == []


def test_render_debug_frame_produces_annotated_image():
    service = VehicleDetectionService()
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    det = NormalizedVehicleDetection(
        camera_id="cam-debug-01",
        video_pts_ms=12500.0,
        class_id=2,
        class_name="car",
        confidence=0.92,
        bbox=BoundingBox(x1=50.0, y1=60.0, x2=200.0, y2=180.0),
        frame_index=1,
        inference_time_ms=12.4,
        model_version="mock-v1.0"
    )

    annotated = service.render_debug_frame(
        frame_data=img,
        detections=[det],
        camera_id="cam-debug-01",
        pts_ms=12500.0
    )

    assert annotated.shape == (480, 640, 3)
    # Banner area at y < 32 should have non-zero pixels
    assert np.any(annotated[:32, :, :] > 0)


# ---------------------------------------------------------------------------
# 5. REST API Integration (Section 23, docs/api-contract.md)
# ---------------------------------------------------------------------------

def test_api_get_detector_status(client):
    response = client.get("/api/v1/detection/status")
    assert response.status_code == 200
    data = response.json()
    assert "backend" in data
    assert "confidence_threshold" in data
    assert "supported_classes" in data
    assert "car" in data["supported_classes"]


def test_api_detect_snapshot_404_when_inactive(client):
    fake_id = str(uuid.uuid4())
    response = client.post(f"/api/v1/detection/detect-snapshot/{fake_id}")
    assert response.status_code == 404
    assert f"No active stream worker for camera '{fake_id}'" in response.json()["detail"]


def test_api_debug_snapshot_404_when_inactive(client):
    fake_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/detection/debug-snapshot/{fake_id}")
    assert response.status_code == 404


def test_api_detect_snapshot_with_active_stream_buffer(client):
    """Test detect-snapshot and debug-snapshot on an active worker with cached frame."""
    cam_id = str(uuid.uuid4())
    worker = StreamWorker(camera_id=cam_id, stream_url="rtsp://test/cam")
    test_img = np.zeros((480, 640, 3), dtype=np.uint8)

    worker.ring_buffer.push(DecodedFrame(
        frame_index=10,
        camera_id=cam_id,
        pts_ms=5000.0,
        data=test_img,
        width=640,
        height=480,
        monotonic_ts=time.monotonic()
    ))
    stream_manager._workers[cam_id] = worker

    try:
        # Test detection endpoint
        resp = client.post(f"/api/v1/detection/detect-snapshot/{cam_id}")
        assert resp.status_code == 200
        detections = resp.json()
        assert isinstance(detections, list)
        if detections:
            assert detections[0]["camera_id"] == cam_id
            assert detections[0]["video_pts_ms"] == 5000.0
            assert "bbox" in detections[0]

        # Test debug-snapshot image endpoint
        img_resp = client.get(f"/api/v1/detection/debug-snapshot/{cam_id}")
        assert img_resp.status_code == 200
        assert img_resp.headers["Content-Type"] == "image/jpeg"
        assert img_resp.content[:2] == b"\xff\xd8"  # JPEG magic bytes
    finally:
        stream_manager.stop_stream(cam_id)
