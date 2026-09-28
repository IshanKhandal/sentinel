"""Deterministic Mock Vehicle Detector for testing, CI, and offline operation.

Protocol Standards:
- docs/ai-architecture.md Section 4 (MockInferenceProvider).
- Stage 6 Directive Section 8 (Explicit DEMO / TEST labeling).
- Strictly preserves camera_id and video_pts_ms from Stage 5 frame.
"""

import time
from typing import List, Dict, Any, Optional
import numpy as np

from backend.app.schemas.detection import BoundingBox, NormalizedVehicleDetection
from backend.app.services.detection.base import ObjectDetector, DEFAULT_COCO_VEHICLE_CLASSES
from backend.app.services.streaming.models import DecodedFrame


class MockObjectDetector(ObjectDetector):
    """Deterministic vehicle detector for test suites and offline verification."""

    def __init__(
        self,
        confidence_threshold: float = 0.25,
        deterministic_detections: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        super().__init__(confidence_threshold=confidence_threshold)
        self.deterministic_detections = deterministic_detections
        self.supported_classes = DEFAULT_COCO_VEHICLE_CLASSES

    def load(self) -> None:
        """Initialize mock detector resources."""
        self._is_loaded = True

    def detect(self, frame: DecodedFrame) -> List[NormalizedVehicleDetection]:
        """Execute mock detection, strictly preserving camera_id and video_pts_ms."""
        if not self._is_loaded:
            self.load()

        t_start = time.perf_counter_ns()

        if frame is None or frame.data is None or frame.data.size == 0:
            return []

        h, w = frame.data.shape[:2]
        detections: List[NormalizedVehicleDetection] = []

        if self.deterministic_detections is not None:
            # Use explicitly supplied test detections
            for d in self.deterministic_detections:
                conf = float(d.get("confidence", 0.85))
                if conf < self.confidence_threshold:
                    continue

                bbox = BoundingBox(
                    x1=min(w - 2.0, max(0.0, float(d.get("x1", 50)))),
                    y1=min(h - 2.0, max(0.0, float(d.get("y1", 50)))),
                    x2=min(float(w), max(1.0, float(d.get("x2", 200)))),
                    y2=min(float(h), max(1.0, float(d.get("y2", 150)))),
                )

                det = NormalizedVehicleDetection(
                    camera_id=frame.camera_id,
                    video_pts_ms=frame.pts_ms,
                    class_id=int(d.get("class_id", 2)),
                    class_name=d.get("class_name", "car"),
                    confidence=conf,
                    bbox=bbox,
                    frame_index=frame.frame_index,
                    inference_time_ms=round((time.perf_counter_ns() - t_start) / 1_000_000.0, 2),
                    model_version="mock-v1.0"
                )
                detections.append(det)
        else:
            # Default deterministic behavior: if frame contains color content, generate realistic sample box
            # For example, a single verified car in the center region
            if w >= 100 and h >= 100:
                conf = 0.88
                if conf >= self.confidence_threshold:
                    box_w = int(w * 0.35)
                    box_h = int(h * 0.25)
                    x1 = int(w * 0.30)
                    y1 = int(h * 0.40)
                    x2 = x1 + box_w
                    y2 = y1 + box_h

                    bbox = BoundingBox(x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2))
                    det = NormalizedVehicleDetection(
                        camera_id=frame.camera_id,
                        video_pts_ms=frame.pts_ms,
                        class_id=2,
                        class_name="car",
                        confidence=conf,
                        bbox=bbox,
                        frame_index=frame.frame_index,
                        inference_time_ms=round((time.perf_counter_ns() - t_start) / 1_000_000.0, 2),
                        model_version="mock-v1.0"
                    )
                    detections.append(det)

        return detections

    def metadata(self) -> Dict[str, Any]:
        return {
            "model_name": "mock-vehicle-detector",
            "model_version": "mock-v1.0",
            "backend": "MOCK",
            "supported_classes": list(self.supported_classes.values()),
            "confidence_threshold": self.confidence_threshold,
            "license": "Project Internal (Test Only)",
            "is_loaded": self._is_loaded,
        }
