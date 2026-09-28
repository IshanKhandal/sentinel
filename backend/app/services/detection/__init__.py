"""Sentinel vehicle detection service package."""

from backend.app.schemas.detection import (
    BoundingBox,
    NormalizedVehicleDetection,
    DetectorStatusResponse
)
from backend.app.services.detection.base import ObjectDetector, DEFAULT_COCO_VEHICLE_CLASSES
from backend.app.services.detection.preprocessing import letterbox, reverse_letterbox_bbox
from backend.app.services.detection.mock_detector import MockObjectDetector
from backend.app.services.detection.onnx_detector import ONNXRuntimeObjectDetector
from backend.app.services.detection.service import VehicleDetectionService, detection_service

__all__ = [
    "BoundingBox",
    "NormalizedVehicleDetection",
    "DetectorStatusResponse",
    "ObjectDetector",
    "DEFAULT_COCO_VEHICLE_CLASSES",
    "letterbox",
    "reverse_letterbox_bbox",
    "MockObjectDetector",
    "ONNXRuntimeObjectDetector",
    "VehicleDetectionService",
    "detection_service",
]
