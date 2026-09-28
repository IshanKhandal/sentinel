"""Plate detection abstraction and detector implementations.

Protocol Standards:
- docs/ai-architecture.md Section 2 (PlateDetector).
- Stage 7 Directive Sections 4, 5, 6, 7, 8, 14, 17.
- Coordinate transformation: Transforms vehicle-crop coordinates to frame coordinates.
- Pluggable backends: MockPlateDetector (offline/CI/demo) and ONNXRuntimePlateDetector.
"""

import abc
import os
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np

from backend.app.schemas.detection import BoundingBox, NormalizedVehicleDetection
from backend.app.schemas.anpr import PlateDetectionResult
from backend.app.services.anpr.crop import transform_plate_to_frame_coords
from backend.app.services.detection.preprocessing import letterbox, reverse_letterbox_bbox

logger = logging.getLogger("sentinel.anpr.plate_detector")


class PlateDetector(abc.ABC):
    """Abstract interface defining the contract for all license plate localization models."""

    def __init__(self, confidence_threshold: float = 0.30) -> None:
        self.confidence_threshold = confidence_threshold
        self._is_loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    @abc.abstractmethod
    def load(self) -> None:
        """Initialize inference engine or session resources."""
        pass

    @abc.abstractmethod
    def detect_plates(
        self,
        vehicle_crop: np.ndarray,
        vehicle_detection: NormalizedVehicleDetection,
        frame_shape: Tuple[int, int]
    ) -> List[PlateDetectionResult]:
        """Detect license plate regions within a cropped vehicle sub-image.

        Args:
            vehicle_crop: (H, W, 3) cropped vehicle image array
            vehicle_detection: Upstream Stage 6 vehicle detection containing frame coordinates
            frame_shape: (frame_width, frame_height) of the original source video frame

        Returns:
            List of PlateDetectionResult with both vehicle-relative and frame coordinates.
        """
        pass

    @abc.abstractmethod
    def metadata(self) -> Dict[str, Any]:
        """Return runtime metadata describing detector architecture and backend."""
        pass


class MockPlateDetector(PlateDetector):
    """Deterministic plate detector for unit testing, offline CI, and demo verification."""

    def __init__(
        self,
        confidence_threshold: float = 0.30,
        deterministic_plates: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        super().__init__(confidence_threshold=confidence_threshold)
        self.deterministic_plates = deterministic_plates

    def load(self) -> None:
        self._is_loaded = True

    def detect_plates(
        self,
        vehicle_crop: np.ndarray,
        vehicle_detection: NormalizedVehicleDetection,
        frame_shape: Tuple[int, int]
    ) -> List[PlateDetectionResult]:
        if not self._is_loaded:
            self.load()

        t_start = time.perf_counter_ns()

        if vehicle_crop is None or vehicle_crop.size == 0:
            return []

        h, w = vehicle_crop.shape[:2]
        if h < 16 or w < 16:
            return []

        results: List[PlateDetectionResult] = []

        if self.deterministic_plates is not None:
            # Explicit test fixture plates
            for p in self.deterministic_plates:
                conf = float(p.get("confidence", 0.90))
                if conf < self.confidence_threshold:
                    continue

                rel_box = BoundingBox(
                    x1=max(0.0, float(p.get("x1", 10))),
                    y1=max(0.0, float(p.get("y1", 10))),
                    x2=min(float(w), float(p.get("x2", w - 10))),
                    y2=min(float(h), float(p.get("y2", h - 10))),
                )
                frame_box = transform_plate_to_frame_coords(
                    plate_bbox_vehicle=rel_box,
                    vehicle_bbox_frame=vehicle_detection.bbox,
                    frame_shape=frame_shape
                )
                results.append(
                    PlateDetectionResult(
                        bbox_relative=rel_box,
                        bbox_frame=frame_box,
                        confidence=conf,
                        model_version="mock-plate-v1.0",
                        inference_latency_ms=round((time.perf_counter_ns() - t_start) / 1_000_000.0, 2)
                    )
                )
        else:
            # Realistic default: plate centered horizontally in lower third of vehicle
            conf = 0.91
            if conf >= self.confidence_threshold:
                pw = max(16, int(w * 0.45))
                ph = max(10, int(h * 0.18))
                px1 = max(0, int((w - pw) / 2))
                py1 = max(0, int(h * 0.70))
                px2 = min(w, px1 + pw)
                py2 = min(h, py1 + ph)

                rel_box = BoundingBox(
                    x1=float(px1),
                    y1=float(py1),
                    x2=float(px2),
                    y2=float(py2)
                )
                frame_box = transform_plate_to_frame_coords(
                    plate_bbox_vehicle=rel_box,
                    vehicle_bbox_frame=vehicle_detection.bbox,
                    frame_shape=frame_shape
                )
                results.append(
                    PlateDetectionResult(
                        bbox_relative=rel_box,
                        bbox_frame=frame_box,
                        confidence=conf,
                        model_version="mock-plate-v1.0",
                        inference_latency_ms=round((time.perf_counter_ns() - t_start) / 1_000_000.0, 2)
                    )
                )

        return results

    def metadata(self) -> Dict[str, Any]:
        return {
            "model_name": "mock-plate-detector",
            "model_version": "mock-plate-v1.0",
            "backend": "MOCK",
            "confidence_threshold": self.confidence_threshold,
            "license": "Project Internal (Test Only)",
            "is_loaded": self._is_loaded,
        }


class ONNXRuntimePlateDetector(PlateDetector):
    """Plate detector running ONNX models for license plate localization."""

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.30,
        iou_threshold: float = 0.45,
        providers: Optional[List[str]] = None
    ) -> None:
        super().__init__(confidence_threshold=confidence_threshold)
        self.model_path = model_path
        self.iou_threshold = iou_threshold
        self.preferred_providers = providers

        self._session = None
        self._input_name: str = ""
        self._output_name: str = ""
        self._input_shape: Tuple[int, int] = (320, 320)  # (H, W)
        self._active_provider: str = "UNINITIALIZED"

    def load(self) -> None:
        if not self.model_path or not os.path.exists(self.model_path):
            raise FileNotFoundError(f"ONNX plate detector model file not found at: {self.model_path}")

        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required for ONNXRuntimePlateDetector but is not installed."
            ) from exc

        available = ort.get_available_providers()
        selected = []
        if self.preferred_providers:
            for p in self.preferred_providers:
                if p in available:
                    selected.append(p)
        if not selected:
            selected = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            selected = [p for p in selected if p in available]

        session_opts = ort.SessionOptions()
        session_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._session = ort.InferenceSession(self.model_path, sess_options=session_opts, providers=selected)
        self._active_provider = self._session.get_providers()[0]

        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        self._input_name = inputs[0].name
        self._output_name = outputs[0].name

        shape = inputs[0].shape
        if len(shape) == 4:
            h = shape[2] if isinstance(shape[2], int) and shape[2] > 0 else 320
            w = shape[3] if isinstance(shape[3], int) and shape[3] > 0 else 320
            self._input_shape = (h, w)

        self._is_loaded = True
        logger.info(
            "ONNXRuntimePlateDetector loaded '%s' with %s, input shape: %s",
            self.model_path,
            self._active_provider,
            self._input_shape
        )

    def detect_plates(
        self,
        vehicle_crop: np.ndarray,
        vehicle_detection: NormalizedVehicleDetection,
        frame_shape: Tuple[int, int]
    ) -> List[PlateDetectionResult]:
        if not self._is_loaded:
            self.load()

        t_start = time.perf_counter_ns()

        if vehicle_crop is None or vehicle_crop.size == 0:
            return []

        h_orig, w_orig = vehicle_crop.shape[:2]
        if h_orig < 16 or w_orig < 16:
            return []

        target_h, target_w = self._input_shape
        padded_img, ratio, (pad_w, pad_h) = letterbox(
            vehicle_crop,
            new_shape=(target_w, target_h),
            auto=False,
            scaleup=True
        )

        blob = padded_img.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))
        blob = np.expand_dims(blob, axis=0)

        outputs = self._session.run([self._output_name], {self._input_name: blob})
        raw_output = outputs[0]

        # Parse boxes, assuming standard YOLO format [batch, num_boxes, 5+]: cx, cy, w, h, conf
        if len(raw_output.shape) == 3 and raw_output.shape[1] < raw_output.shape[2]:
            preds = np.transpose(raw_output[0], (1, 0))
        elif len(raw_output.shape) == 3:
            preds = raw_output[0]
        else:
            preds = raw_output

        boxes = []
        confidences = []

        for row in preds:
            conf = float(row[4]) if len(row) > 4 else 0.0
            if conf >= self.confidence_threshold:
                cx, cy, bw, bh = row[0], row[1], row[2], row[3]
                bx1 = cx - bw / 2.0
                by1 = cy - bh / 2.0
                boxes.append([bx1, by1, bw, bh])
                confidences.append(conf)

        if not boxes:
            return []

        indices = cv2.dnn.NMSBoxes(
            bboxes=[[int(b[0]), int(b[1]), int(b[2]), int(b[3])] for b in boxes],
            scores=confidences,
            score_threshold=self.confidence_threshold,
            nms_threshold=self.iou_threshold
        )

        results: List[PlateDetectionResult] = []
        latency_ms = round((time.perf_counter_ns() - t_start) / 1_000_000.0, 2)

        for idx in indices:
            i = int(idx[0]) if isinstance(idx, (list, tuple, np.ndarray)) else int(idx)
            b = boxes[i]
            x1, y1 = b[0], b[1]
            x2, y2 = b[0] + b[2], b[1] + b[3]

            rel_box = reverse_letterbox_bbox(
                x1=x1, y1=y1, x2=x2, y2=y2,
                ratio=ratio,
                pad_w=pad_w,
                pad_h=pad_h,
                orig_shape=(h_orig, w_orig)
            )

            frame_box = transform_plate_to_frame_coords(
                plate_bbox_vehicle=rel_box,
                vehicle_bbox_frame=vehicle_detection.bbox,
                frame_shape=frame_shape
            )

            results.append(
                PlateDetectionResult(
                    bbox_relative=rel_box,
                    bbox_frame=frame_box,
                    confidence=confidences[i],
                    model_version=f"onnx-plate-{os.path.basename(self.model_path)}",
                    inference_latency_ms=latency_ms
                )
            )

        return results

    def metadata(self) -> Dict[str, Any]:
        return {
            "model_path": self.model_path,
            "model_name": os.path.basename(self.model_path),
            "backend": "ONNX_RUNTIME",
            "active_provider": self._active_provider,
            "confidence_threshold": self.confidence_threshold,
            "iou_threshold": self.iou_threshold,
            "input_shape": self._input_shape,
            "is_loaded": self._is_loaded,
        }
