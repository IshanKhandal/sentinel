"""Production ONNX Runtime vehicle detector implementation.

Protocol Standards:
- docs/ai-architecture.md Section 2 & Section 4.
- Stage 6 Directive Sections 4, 5, 6, 9, 10, 11, 13, 14, 17, 20, 21.
- Validates model file existence, execution providers, and NMS box filtering.
- Reverses letterbox padding to maintain pixel accuracy in source frame coordinates.
"""

import os
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np

from backend.app.schemas.detection import BoundingBox, NormalizedVehicleDetection
from backend.app.services.detection.base import ObjectDetector, DEFAULT_COCO_VEHICLE_CLASSES
from backend.app.services.detection.preprocessing import letterbox, reverse_letterbox_bbox
from backend.app.services.streaming.models import DecodedFrame

logger = logging.getLogger("sentinel.detection.onnx")


class ONNXRuntimeObjectDetector(ObjectDetector):
    """Vehicle detector using ONNX Runtime with pluggable execution providers."""

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        providers: Optional[List[str]] = None,
        vehicle_classes: Optional[Dict[int, str]] = None
    ) -> None:
        super().__init__(confidence_threshold=confidence_threshold)
        self.model_path = model_path
        self.iou_threshold = iou_threshold
        self.preferred_providers = providers
        self.vehicle_classes = vehicle_classes or DEFAULT_COCO_VEHICLE_CLASSES

        self._session = None
        self._input_name: str = ""
        self._output_name: str = ""
        self._input_shape: Tuple[int, int] = (640, 640)  # (H, W)
        self._active_provider: str = "UNINITIALIZED"

    def load(self) -> None:
        """Initialize ONNX Runtime inference session with available execution providers."""
        if not self.model_path or not os.path.exists(self.model_path):
            raise FileNotFoundError(f"ONNX model file not found at: {self.model_path}")

        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required for ONNXRuntimeObjectDetector but is not installed."
            ) from exc

        # Probe available execution providers (CPUExecutionProvider, CUDAExecutionProvider)
        available_providers = ort.get_available_providers()
        selected_providers = []

        if self.preferred_providers:
            for p in self.preferred_providers:
                if p in available_providers:
                    selected_providers.append(p)

        if not selected_providers:
            # Fallback to available providers prioritizing CUDA if present, then CPU
            if "CUDAExecutionProvider" in available_providers:
                selected_providers.append("CUDAExecutionProvider")
            if "CPUExecutionProvider" in available_providers:
                selected_providers.append("CPUExecutionProvider")
            else:
                selected_providers = available_providers

        logger.info(
            "Initializing ONNX session for %s with providers: %s",
            self.model_path, selected_providers
        )
        self._session = ort.InferenceSession(self.model_path, providers=selected_providers)
        self._active_provider = self._session.get_providers()[0] if self._session.get_providers() else "UNKNOWN"

        # Query input and output node metadata
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        self._input_name = inputs[0].name
        self._output_name = outputs[0].name

        # Parse expected input height and width (e.g. [1, 3, 640, 640])
        shape = inputs[0].shape
        if len(shape) == 4 and isinstance(shape[2], int) and isinstance(shape[3], int):
            self._input_shape = (shape[2], shape[3])
        else:
            self._input_shape = (640, 640)

        self._is_loaded = True
        logger.info(
            "ONNX detector loaded successfully: input=%s %s, provider=%s",
            self._input_name, self._input_shape, self._active_provider
        )

    def detect(self, frame: DecodedFrame) -> List[NormalizedVehicleDetection]:
        """Preprocess frame, run ONNX inference, apply NMS, and emit normalized detections."""
        if not self._is_loaded:
            self.load()

        if frame is None or frame.data is None or frame.data.size == 0:
            return []

        t_start = time.perf_counter_ns()
        orig_h, orig_w = frame.data.shape[:2]

        # 1. Letterbox preprocessing (Aspect-ratio preserved)
        padded_img, scale, pad = letterbox(frame.data, target_shape=self._input_shape)

        # 2. Convert BGR to RGB, normalize to [0.0, 1.0], and format as [1, 3, H, W]
        rgb = cv2.cvtColor(padded_img, cv2.COLOR_BGR2RGB)
        tensor = rgb.astype(np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))  # (3, H, W)
        tensor = np.expand_dims(tensor, axis=0)   # (1, 3, H, W)

        # 3. ONNX Runtime inference execution
        raw_outputs = self._session.run([self._output_name], {self._input_name: tensor})
        output = raw_outputs[0]  # Standard YOLO shape: (1, 84, 8400) or (1, 8400, 84)

        if len(output.shape) == 3:
            if output.shape[1] < output.shape[2]:
                # Transpose from (1, 84, 8400) -> (1, 8400, 84)
                output = np.transpose(output, (0, 2, 1))
            output = output[0]  # (8400, 84)

        # 4. Box extraction and vehicle class filtering
        candidate_boxes = []
        confidences = []
        class_ids = []
        class_names = []

        num_classes = output.shape[1] - 4

        for row in output:
            box_cx, box_cy, box_w, box_h = row[0:4]
            class_scores = row[4:]

            best_class_idx = int(np.argmax(class_scores))
            score = float(class_scores[best_class_idx])

            # Filter by confidence threshold and supported vehicle class
            if score >= self.confidence_threshold and best_class_idx in self.vehicle_classes:
                # Convert center xywh to xyxy in letterbox space
                x1 = box_cx - (box_w / 2.0)
                y1 = box_cy - (box_h / 2.0)
                candidate_boxes.append([int(x1), int(y1), int(box_w), int(box_h)])
                confidences.append(score)
                class_ids.append(best_class_idx)
                class_names.append(self.vehicle_classes[best_class_idx])

        # 5. Non-Maximum Suppression (NMS)
        detections: List[NormalizedVehicleDetection] = []
        if candidate_boxes:
            indices = cv2.dnn.NMSBoxes(
                candidate_boxes,
                confidences,
                score_threshold=self.confidence_threshold,
                nms_threshold=self.iou_threshold
            )

            if len(indices) > 0:
                indices = indices.flatten()
                for idx in indices:
                    c_box = candidate_boxes[idx]
                    box_xyxy = (
                        float(c_box[0]),
                        float(c_box[1]),
                        float(c_box[0] + c_box[2]),
                        float(c_box[1] + c_box[3])
                    )
                    # Reverse letterbox transformation back to original frame coordinates
                    rev_bbox = reverse_letterbox_bbox(
                        bbox_xyxy=box_xyxy,
                        scale=scale,
                        pad=pad,
                        orig_shape=(orig_w, orig_h)
                    )

                    det = NormalizedVehicleDetection(
                        camera_id=frame.camera_id,
                        video_pts_ms=frame.pts_ms,
                        class_id=class_ids[idx],
                        class_name=class_names[idx],
                        confidence=round(confidences[idx], 4),
                        bbox=rev_bbox,
                        frame_index=frame.frame_index,
                        inference_time_ms=round((time.perf_counter_ns() - t_start) / 1_000_000.0, 2),
                        model_version=f"onnx-{os.path.basename(self.model_path)}"
                    )
                    detections.append(det)

        return detections

    def metadata(self) -> Dict[str, Any]:
        return {
            "model_name": os.path.basename(self.model_path) if self.model_path else "none",
            "model_version": f"onnx-{os.path.basename(self.model_path)}" if self.model_path else "unconfigured",
            "backend": "ONNX_RUNTIME",
            "active_provider": self._active_provider,
            "supported_classes": list(self.vehicle_classes.values()),
            "confidence_threshold": self.confidence_threshold,
            "iou_threshold": self.iou_threshold,
            "input_shape": self._input_shape,
            "is_loaded": self._is_loaded,
        }
