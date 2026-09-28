"""Automated unit and integration tests for Sentinel Stage 7 ANPR Subsystem.

Protocol Standards:
- docs/engineering-rules.md Rules 29, 30, 31.
- Stage 7 Directive Sections 1, 2, 4, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 23.
"""

import io
import time
import uuid
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas.detection import BoundingBox, NormalizedVehicleDetection
from backend.app.schemas.anpr import (
    ANPRResult,
    ANPRStatus,
    PlateDetectionResult,
    OCRResult,
    ANPRStatusResponse
)
from backend.app.services.anpr.crop import safe_extract_crop, transform_plate_to_frame_coords
from backend.app.services.anpr.normalization import (
    normalize_plate_text,
    contextual_plate_correction,
    INDIAN_STANDARD_PLATE_REGEX,
    INDIAN_BHARAT_SERIES_REGEX
)
from backend.app.services.anpr.preprocessing import PlatePreprocessor
from backend.app.services.anpr.plate_detector import (
    PlateDetector,
    MockPlateDetector,
    ONNXRuntimePlateDetector
)
from backend.app.services.anpr.ocr_provider import (
    OCRProvider,
    MockOCRProvider,
    ONNXRuntimeOCRProvider
)
from backend.app.services.anpr.pipeline import ANPRPipelineService, anpr_pipeline_service
from backend.app.services.streaming.models import DecodedFrame
import cv2


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Safe Crop Extraction (Section 8, 23)
# ---------------------------------------------------------------------------

def test_safe_extract_crop_normal():
    img = np.zeros((200, 300, 3), dtype=np.uint8)
    img[20:100, 30:150] = (255, 255, 255)
    bbox = BoundingBox(x1=30.0, y1=20.0, x2=150.0, y2=100.0)

    res = safe_extract_crop(img, bbox, min_width=16, min_height=16)
    assert res is not None
    crop, clamped = res
    assert crop.shape == (80, 120, 3)
    assert clamped.x1 == 30.0
    assert clamped.y1 == 20.0
    assert clamped.x2 == 150.0
    assert clamped.y2 == 100.0


def test_safe_extract_crop_exceeding_boundaries_clamps_safely():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    # Box claims coordinates extending beyond image bounds
    bbox = BoundingBox(x1=50.0, y1=50.0, x2=150.0, y2=150.0)

    res = safe_extract_crop(img, bbox, min_width=16, min_height=16)
    assert res is not None
    crop, clamped = res
    assert crop.shape == (50, 50, 3)
    assert clamped.x2 == 100.0
    assert clamped.y2 == 100.0


def test_safe_extract_crop_rejects_sub_minimal_crop():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    # 5x5 crop is smaller than min_width=16
    bbox = BoundingBox(x1=10.0, y1=10.0, x2=15.0, y2=15.0)

    res = safe_extract_crop(img, bbox, min_width=16, min_height=16)
    assert res is None


def test_safe_extract_crop_none_or_empty_image():
    bbox = BoundingBox(x1=10.0, y1=10.0, x2=50.0, y2=50.0)
    assert safe_extract_crop(None, bbox) is None
    assert safe_extract_crop(np.zeros((0, 0, 3), dtype=np.uint8), bbox) is None


# ---------------------------------------------------------------------------
# 2. Coordinate Transformation: Vehicle Crop -> Frame Space (Section 7, 23)
# ---------------------------------------------------------------------------

def test_transform_plate_to_frame_coords_correct_offset():
    # Vehicle is located at (100, 200) to (500, 600) in frame
    veh_box = BoundingBox(x1=100.0, y1=200.0, x2=500.0, y2=600.0)
    # Plate is detected inside vehicle crop at (50, 150) to (150, 200)
    plate_veh = BoundingBox(x1=50.0, y1=150.0, x2=150.0, y2=200.0)

    frame_box = transform_plate_to_frame_coords(
        plate_bbox_vehicle=plate_veh,
        vehicle_bbox_frame=veh_box,
        frame_shape=(1920, 1080)
    )

    # Expected absolute frame coordinates:
    # x1 = 100 + 50 = 150
    # y1 = 200 + 150 = 350
    # x2 = 100 + 150 = 250
    # y2 = 200 + 200 = 400
    assert frame_box.x1 == 150.0
    assert frame_box.y1 == 350.0
    assert frame_box.x2 == 250.0
    assert frame_box.y2 == 400.0


def test_transform_plate_to_frame_coords_clamps_to_frame_limits():
    veh_box = BoundingBox(x1=900.0, y1=900.0, x2=1000.0, y2=1000.0)
    plate_veh = BoundingBox(x1=80.0, y1=80.0, x2=200.0, y2=200.0)

    frame_box = transform_plate_to_frame_coords(
        plate_bbox_vehicle=plate_veh,
        vehicle_bbox_frame=veh_box,
        frame_shape=(1000, 1000)
    )
    assert frame_box.x2 == 1000.0
    assert frame_box.y2 == 1000.0


# ---------------------------------------------------------------------------
# 3. Normalization & Contextual Safety (Section 12, 13, 23)
# ---------------------------------------------------------------------------

def test_normalization_preserves_raw_text():
    raw = "  GJ 01 AB 1234  "
    norm, is_valid, was_corrected = normalize_plate_text(raw)
    assert norm == "GJ01AB1234"
    assert is_valid is True
    assert was_corrected is False


def test_normalization_validates_gujarat_and_other_indian_plates():
    plates = [
        ("GJ01AB1234", True),
        ("GJ27CD5678", True),
        ("MH12DE3333", True),
        ("DL3CAA1111", True),
        ("22BH1234AA", True),   # Bharat Series
        ("INVALID123", False),
        ("12345", False),
        ("", False)
    ]
    for p, expected in plates:
        norm, is_valid, _ = normalize_plate_text(p)
        assert is_valid == expected, f"Failed for plate '{p}'"


def test_contextual_correction_repairs_positional_ambiguity_safely():
    # If state code has '0' instead of 'O', or trailing numbers have 'O'/'I'/'B'/'S'
    # "GJ01AB123O" (trailing letter 'O' instead of digit '0')
    confused = "GJ01AB123O"
    norm, is_valid, _ = normalize_plate_text(confused)
    assert is_valid is False  # Fails initial regex because last char is 'O'

    corrected, is_valid_after, was_corrected = contextual_plate_correction(norm)
    assert corrected == "GJ01AB1230"
    assert is_valid_after is True
    assert was_corrected is True


def test_normalization_never_blindly_replaces_characters_globally():
    # "GJ01BB1234" - BB in series must NOT be replaced with 88!
    norm, is_valid, was_corrected = normalize_plate_text("GJ01BB1234")
    assert is_valid is True
    assert "BB" in norm
    assert "88" not in norm


# ---------------------------------------------------------------------------
# 4. Plate Preprocessing (Section 9)
# ---------------------------------------------------------------------------

def test_preprocessing_variants():
    crop = np.full((50, 100, 3), 128, dtype=np.uint8)

    # Standard (CLAHE + Bilateral)
    std_img, variant = PlatePreprocessor.preprocess(crop, variant="standard", target_height=64)
    assert variant == "standard"
    assert std_img.shape[0] == 64
    assert len(std_img.shape) == 2  # Grayscale result

    # Raw
    raw_img, variant = PlatePreprocessor.preprocess(crop, variant="raw", target_height=64)
    assert variant == "raw"
    assert raw_img.shape[0] == 64
    assert len(raw_img.shape) == 3

    # Grayscale
    gray_img, variant = PlatePreprocessor.preprocess(crop, variant="grayscale", target_height=64)
    assert variant == "grayscale"
    assert gray_img.shape[0] == 64
    assert len(gray_img.shape) == 2


# ---------------------------------------------------------------------------
# 5. Plate Detector & OCR Provider Contracts (Section 4, 11, 14, 23)
# ---------------------------------------------------------------------------

def test_mock_plate_detector_contract():
    detector = MockPlateDetector(confidence_threshold=0.30)
    detector.load()
    assert detector.is_loaded is True

    veh_crop = np.zeros((100, 200, 3), dtype=np.uint8)
    veh_det = NormalizedVehicleDetection(
        camera_id="CAM_TEST_01",
        video_pts_ms=1500.0,
        class_id=2,
        class_name="car",
        confidence=0.92,
        bbox=BoundingBox(x1=100.0, y1=200.0, x2=300.0, y2=300.0),
        frame_index=15,
        inference_time_ms=5.0,
        model_version="mock-v1.0"
    )

    plates = detector.detect_plates(veh_crop, veh_det, frame_shape=(1280, 720))
    assert len(plates) == 1
    p = plates[0]
    assert 0.0 <= p.confidence <= 1.0
    assert p.bbox_relative.x1 >= 0
    assert p.bbox_frame.x1 >= veh_det.bbox.x1
    assert p.inference_latency_ms >= 0.0


def test_mock_ocr_provider_contract():
    provider = MockOCRProvider(confidence_threshold=0.50, deterministic_transcription="GJ 01 CD 5678")
    provider.load()
    assert provider.is_loaded is True

    plate_crop = np.zeros((32, 100, 3), dtype=np.uint8)
    res = provider.recognize_text(plate_crop)

    assert res.raw_text == "GJ 01 CD 5678"
    assert res.normalized_text == "GJ01CD5678"
    assert res.is_valid_format is True
    assert res.confidence is not None and res.confidence >= 0.50
    assert res.provider == "MOCK"


def test_onnx_plate_detector_missing_file_raises_explicit():
    detector = ONNXRuntimePlateDetector(model_path="nonexistent_plate_model.onnx")
    with pytest.raises(FileNotFoundError, match="ONNX plate detector model file not found"):
        detector.load()


def test_onnx_ocr_provider_missing_file_raises_explicit():
    provider = ONNXRuntimeOCRProvider(model_path="nonexistent_ocr_model.onnx")
    with pytest.raises(FileNotFoundError, match="ONNX OCR model file not found"):
        provider.load()


# ---------------------------------------------------------------------------
# 6. Metadata Propagation (PTS, Camera ID, Vehicle Reference) (Section 6, 23)
# ---------------------------------------------------------------------------

def test_anpr_pipeline_preserves_pts_and_camera_id():
    service = ANPRPipelineService()
    cam_id = f"CAM_{uuid.uuid4().hex[:6]}"
    pts = 12345.67

    # Create dummy frame
    frame_img = np.zeros((480, 640, 3), dtype=np.uint8)
    frame = DecodedFrame(
        frame_index=42,
        camera_id=cam_id,
        pts_ms=pts,
        data=frame_img,
        width=640,
        height=480,
        monotonic_ts=float(pts / 1000.0)
    )

    # Upstream vehicle detection
    veh_det = NormalizedVehicleDetection(
        camera_id=cam_id,
        video_pts_ms=pts,
        class_id=2,
        class_name="car",
        confidence=0.88,
        bbox=BoundingBox(x1=50.0, y1=50.0, x2=250.0, y2=250.0),
        frame_index=42,
        inference_time_ms=10.0,
        model_version="mock-v1.0"
    )

    results = service.process_frame(frame, [veh_det])
    assert len(results) >= 1

    r = results[0]
    assert r.camera_id == cam_id
    assert r.video_pts_ms == pts
    assert r.frame_index == 42
    assert r.vehicle_class == "car"
    assert r.vehicle_bbox.as_tuple() == (50.0, 50.0, 250.0, 250.0)
    assert r.status == "OCR_SUCCESS"
    assert r.raw_text is not None
    assert r.normalized_text is not None
    assert r.plate_detector_confidence is not None
    assert r.ocr_confidence is not None
    assert r.vehicle_confidence == 0.88


# ---------------------------------------------------------------------------
# 7. Multiple Vehicles & Multiple Plates (Section 17, 23)
# ---------------------------------------------------------------------------

def test_anpr_pipeline_multiple_vehicles():
    service = ANPRPipelineService()
    frame_img = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame = DecodedFrame(
        frame_index=1,
        camera_id="CAM_MULTI",
        pts_ms=100.0,
        data=frame_img,
        width=1280,
        height=720,
        monotonic_ts=0.1
    )

    veh1 = NormalizedVehicleDetection(
        camera_id="CAM_MULTI",
        video_pts_ms=100.0,
        class_id=2,
        class_name="car",
        confidence=0.90,
        bbox=BoundingBox(x1=50.0, y1=100.0, x2=300.0, y2=350.0),
        frame_index=1,
        inference_time_ms=8.0,
        model_version="mock-v1.0"
    )
    veh2 = NormalizedVehicleDetection(
        camera_id="CAM_MULTI",
        video_pts_ms=100.0,
        class_id=7,
        class_name="truck",
        confidence=0.85,
        bbox=BoundingBox(x1=400.0, y1=100.0, x2=800.0, y2=500.0),
        frame_index=1,
        inference_time_ms=8.0,
        model_version="mock-v1.0"
    )

    results = service.process_frame(frame, [veh1, veh2])
    assert len(results) == 2
    assert results[0].vehicle_class == "car"
    assert results[1].vehicle_class == "truck"


# ---------------------------------------------------------------------------
# 8. Failure Isolation (Section 23)
# ---------------------------------------------------------------------------

def test_anpr_failure_isolation_invalid_crop_does_not_crash_pipeline():
    service = ANPRPipelineService()
    frame_img = np.zeros((480, 640, 3), dtype=np.uint8)
    frame = DecodedFrame(
        frame_index=1,
        camera_id="CAM_FAIL_ISOLATION",
        pts_ms=200.0,
        data=frame_img,
        width=640,
        height=480,
        monotonic_ts=0.2
    )

    # Malformed vehicle: degenerate 1-pixel box (unusable crop)
    veh_bad = NormalizedVehicleDetection(
        camera_id="CAM_FAIL_ISOLATION",
        video_pts_ms=200.0,
        class_id=2,
        class_name="car",
        confidence=0.80,
        bbox=BoundingBox(x1=10.0, y1=10.0, x2=11.0, y2=11.0),
        frame_index=1,
        inference_time_ms=5.0,
        model_version="mock-v1.0"
    )
    # Valid vehicle
    veh_good = NormalizedVehicleDetection(
        camera_id="CAM_FAIL_ISOLATION",
        video_pts_ms=200.0,
        class_id=2,
        class_name="car",
        confidence=0.90,
        bbox=BoundingBox(x1=100.0, y1=100.0, x2=350.0, y2=350.0),
        frame_index=1,
        inference_time_ms=5.0,
        model_version="mock-v1.0"
    )

    results = service.process_frame(frame, [veh_bad, veh_good])
    assert len(results) == 2
    assert results[0].status == "INVALID_CROP"
    assert results[1].status == "OCR_SUCCESS"


# ---------------------------------------------------------------------------
# 9. ANPR REST API Endpoints (Section 15, 23)
# ---------------------------------------------------------------------------

def test_api_anpr_status(client):
    res = client.get("/api/v1/anpr/status")
    assert res.status_code == 200
    data = res.json()
    assert "plate_detector_backend" in data
    assert "ocr_provider_backend" in data
    assert "ocr_confidence_threshold" in data


def test_api_anpr_process_snapshot_404_when_no_active_worker(client):
    res = client.post("/api/v1/anpr/process-snapshot/nonexistent_camera_id")
    assert res.status_code == 404
    assert "No active stream worker" in res.json()["detail"]


def test_api_anpr_process_image_upload(client):
    # Create test JPEG in-memory
    test_img = np.zeros((300, 400, 3), dtype=np.uint8)
    # Draw a simulated vehicle block
    test_img[50:250, 50:350] = (100, 150, 200)
    _, encoded = cv2.imencode(".jpg", test_img)
    img_bytes = encoded.tobytes()

    res = client.post(
        "/api/v1/anpr/process-image",
        files={"file": ("test_plate.jpg", img_bytes, "image/jpeg")},
        data={"camera_id": "CAM_UPLOAD_TEST", "pts_ms": 500.0}
    )
    assert res.status_code == 200
    results = res.json()
    assert isinstance(results, list)
    assert len(results) >= 1
    assert results[0]["camera_id"] == "CAM_UPLOAD_TEST"
    assert results[0]["video_pts_ms"] == 500.0
    assert results[0]["status"] == "OCR_SUCCESS"
