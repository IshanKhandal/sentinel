"""Vehicle detection coordination service with frame sampling and visual debugging.

Protocol Standards:
- Stage 6 Directive Sections 7, 13, 14, 15, 16, 23.
- Connects directly to Stage 5 DecodedFrame input.
- Frame sampling decimation policy (inference_fps_limit).
- Visual debugging overlay for test frames (DEBUG/TEST ONLY).
"""

import time
import logging
import threading
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import cv2
import numpy as np

from backend.app.core.config import settings
from backend.app.schemas.detection import (
    NormalizedVehicleDetection,
    DetectorStatusResponse
)
from backend.app.services.detection.base import ObjectDetector
from backend.app.services.detection.mock_detector import MockObjectDetector
from backend.app.services.detection.onnx_detector import ONNXRuntimeObjectDetector
from backend.app.services.streaming.models import DecodedFrame

logger = logging.getLogger("sentinel.detection.service")


class VehicleDetectionService:
    """Central domain service managing model lifecycle, frame decimation, and telemetry."""

    _instance: Optional["VehicleDetectionService"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "VehicleDetectionService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_service()
        return cls._instance

    def _init_service(self) -> None:
        """Initialize detector backend and diagnostic telemetry."""
        self.fps_limit = settings.DETECTION_FPS_LIMIT
        self.min_interval_sec = 1.0 / self.fps_limit if self.fps_limit > 0 else 0.0

        # Frame rate decimation state per camera
        self._last_processed_time: Dict[str, float] = {}

        # Telemetry
        self._frames_processed: int = 0
        self._frames_skipped: int = 0
        self._total_vehicles_detected: int = 0
        self._last_latency_ms: Optional[float] = None
        self._telemetry_lock = threading.Lock()

        # Detector instantiation
        self.detector = self._create_detector()

    def _create_detector(self) -> ObjectDetector:
        """Instantiate configured detector backend."""
        backend = settings.VEHICLE_DETECTOR_BACKEND.upper()
        conf_thresh = settings.VEHICLE_CONFIDENCE_THRESHOLD

        if backend == "ONNX_RUNTIME" and settings.VEHICLE_DETECTOR_MODEL_PATH:
            try:
                detector = ONNXRuntimeObjectDetector(
                    model_path=settings.VEHICLE_DETECTOR_MODEL_PATH,
                    confidence_threshold=conf_thresh,
                    iou_threshold=settings.VEHICLE_IOU_THRESHOLD
                )
                detector.load()
                return detector
            except Exception as exc:
                logger.warning(
                    "Failed to initialize ONNXRuntimeObjectDetector (%s). Falling back to MockObjectDetector.",
                    exc
                )

        # Default fallback: Mock detector
        mock = MockObjectDetector(confidence_threshold=conf_thresh)
        mock.load()
        return mock

    def process_frame(self, frame: DecodedFrame) -> List[NormalizedVehicleDetection]:
        """Process incoming decoded video frame through sampling policy and detector.

        Strict Invariants:
        - Preserves frame.camera_id and frame.pts_ms.
        - Frame decimation: skips frames exceeding fps_limit.
        """
        if frame is None or frame.data is None:
            return []

        now_mono = time.monotonic()
        cam_id = frame.camera_id

        # 1. Frame Sampling / Decimation Policy (Section 16)
        if self.min_interval_sec > 0:
            last_time = self._last_processed_time.get(cam_id, 0.0)
            if now_mono - last_time < self.min_interval_sec:
                with self._telemetry_lock:
                    self._frames_skipped += 1
                return []

        self._last_processed_time[cam_id] = now_mono

        # 2. Execute Detection
        detections = self.detector.detect(frame)

        # 3. Update Telemetry
        with self._telemetry_lock:
            self._frames_processed += 1
            self._total_vehicles_detected += len(detections)
            if detections:
                self._last_latency_ms = detections[0].inference_time_ms

        return detections

    def render_debug_frame(
        self,
        frame_data: np.ndarray,
        detections: List[NormalizedVehicleDetection],
        camera_id: str = "UNKNOWN",
        pts_ms: float = 0.0
    ) -> np.ndarray:
        """Render debug overlay on image for developer verification (Section 23).
        
        Explicitly marked: DEBUG / TEST ONLY.
        """
        debug_img = frame_data.copy()
        h, w = debug_img.shape[:2]

        # Draw top telemetry banner
        banner_text = f"[DEBUG/TEST] CAM: {camera_id[:8]} | PTS: {pts_ms:.0f}ms | VEHICLES: {len(detections)}"
        cv2.rectangle(debug_img, (0, 0), (w, 32), (30, 30, 30), -1)
        cv2.putText(
            debug_img,
            banner_text,
            (10, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            1,
            cv2.LINE_AA
        )

        # Draw bounding boxes and labels
        color_map = {
            "car": (0, 255, 0),        # Green
            "truck": (0, 165, 255),    # Orange
            "bus": (255, 255, 0),      # Cyan
            "motorcycle": (255, 0, 255) # Magenta
        }

        for det in detections:
            x1, y1, x2, y2 = int(det.bbox.x1), int(det.bbox.y1), int(det.bbox.x2), int(det.bbox.y2)
            color = color_map.get(det.class_name.lower(), (0, 255, 0))

            # Bounding box rectangle
            cv2.rectangle(debug_img, (x1, y1), (x2, y2), color, 2)

            # Label banner
            label = f"{det.class_name} {int(det.confidence * 100)}%"
            label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(
                debug_img,
                (x1, max(0, y1 - 20)),
                (x1 + label_size[0] + 6, max(0, y1)),
                color,
                -1
            )
            cv2.putText(
                debug_img,
                label,
                (x1 + 3, max(14, y1 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 0),
                1,
                cv2.LINE_AA
            )

        return debug_img

    def get_status(self) -> DetectorStatusResponse:
        """Fetch runtime diagnostics and detector metadata."""
        meta = self.detector.metadata()
        with self._telemetry_lock:
            return DetectorStatusResponse(
                backend=meta.get("backend", "UNKNOWN"),
                model_name=meta.get("model_name", "unknown"),
                model_version=meta.get("model_version", "unknown"),
                confidence_threshold=self.detector.confidence_threshold,
                fps_limit=self.fps_limit,
                supported_classes=meta.get("supported_classes", []),
                frames_processed=self._frames_processed,
                frames_skipped=self._frames_skipped,
                total_vehicles_detected=self._total_vehicles_detected,
                last_inference_latency_ms=self._last_latency_ms
            )


# Global singleton instance
detection_service = VehicleDetectionService()
