"""ANPR pipeline coordination service connecting Stage 6 vehicle detections to Stage 7 ANPR results.

Protocol Standards:
- docs/ai-architecture.md Section 2 (ANPR Pipeline).
- Stage 7 Directive Sections 3, 6, 7, 8, 9, 14, 15, 16, 17, 21.
- Strict isolation of Stage 7: No event persistence, no watchlists, no alert generation.
- Strict propagation of authoritative video PTS and camera_id.
- Explicit coordinate space separation (frame vs vehicle crop vs plate crop).
"""

import time
import logging
import threading
from typing import List, Optional, Dict, Any, Tuple
import cv2
import numpy as np

from backend.app.core.config import settings
from backend.app.schemas.detection import BoundingBox, NormalizedVehicleDetection
from backend.app.schemas.anpr import (
    ANPRResult,
    ANPRStatus,
    PlateDetectionResult,
    OCRResult,
    ANPRStatusResponse
)
from backend.app.services.anpr.crop import safe_extract_crop
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
from backend.app.services.streaming.models import DecodedFrame

logger = logging.getLogger("sentinel.anpr.pipeline")


class ANPRPipelineService:
    """Central domain service orchestrating license plate localization, preprocessing, and OCR."""

    _instance: Optional["ANPRPipelineService"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ANPRPipelineService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_service()
        return cls._instance

    def _init_service(self) -> None:
        """Initialize plate detector, OCR provider, and diagnostic telemetry."""
        # Telemetry counters
        self._plates_detected_total: int = 0
        self._ocr_reads_total: int = 0
        self._valid_format_reads: int = 0
        self._telemetry_lock = threading.Lock()

        # Instantiation
        self.plate_detector = self._create_plate_detector()
        self.ocr_provider = self._create_ocr_provider()

    def _create_plate_detector(self) -> PlateDetector:
        backend = settings.PLATE_DETECTOR_BACKEND.upper()
        conf_thresh = settings.PLATE_CONFIDENCE_THRESHOLD

        if backend == "ONNX_RUNTIME" and settings.PLATE_DETECTOR_MODEL_PATH:
            try:
                detector = ONNXRuntimePlateDetector(
                    model_path=settings.PLATE_DETECTOR_MODEL_PATH,
                    confidence_threshold=conf_thresh
                )
                detector.load()
                return detector
            except Exception as exc:
                logger.warning(
                    "Failed to initialize ONNXRuntimePlateDetector (%s). Falling back to MockPlateDetector.",
                    exc
                )

        mock = MockPlateDetector(confidence_threshold=conf_thresh)
        mock.load()
        return mock

    def _create_ocr_provider(self) -> OCRProvider:
        backend = settings.OCR_PROVIDER_BACKEND.upper()
        conf_thresh = settings.OCR_CONFIDENCE_THRESHOLD

        if backend == "ONNX_RUNTIME" and settings.OCR_MODEL_PATH:
            try:
                provider = ONNXRuntimeOCRProvider(
                    model_path=settings.OCR_MODEL_PATH,
                    confidence_threshold=conf_thresh
                )
                provider.load()
                return provider
            except Exception as exc:
                logger.warning(
                    "Failed to initialize ONNXRuntimeOCRProvider (%s). Falling back to MockOCRProvider.",
                    exc
                )

        mock = MockOCRProvider(confidence_threshold=conf_thresh)
        mock.load()
        return mock

    def process_frame(
        self,
        frame: DecodedFrame,
        vehicle_detections: List[NormalizedVehicleDetection]
    ) -> List[ANPRResult]:
        """Execute Stage 7 ANPR pipeline on Stage 6 vehicle detections.

        Strict Invariants:
        - Authoritative video PTS and camera_id preserved from Stage 5 frame.
        - Multiple vehicles and multiple plates per vehicle supported.
        - Invalid crops or unreadable plates yield explicit status rather than hallucinations.
        """
        if frame is None or frame.data is None or frame.data.size == 0:
            return []

        if not vehicle_detections:
            return []

        frame_h, frame_w = frame.data.shape[:2]
        frame_shape = (frame_w, frame_h)
        anpr_results: List[ANPRResult] = []

        for v_idx, v_det in enumerate(vehicle_detections):
            t_vehicle_start = time.perf_counter_ns()

            # 1. Safe extraction of vehicle crop
            v_crop_res = safe_extract_crop(
                image=frame.data,
                bbox=v_det.bbox,
                min_width=16,
                min_height=16
            )

            if v_crop_res is None:
                # Malformed or out-of-bounds vehicle crop
                anpr_results.append(
                    ANPRResult(
                        camera_id=frame.camera_id,
                        video_pts_ms=frame.pts_ms,
                        frame_index=frame.frame_index,
                        vehicle_class=v_det.class_name,
                        vehicle_bbox=v_det.bbox,
                        status="INVALID_CROP",
                        total_latency_ms=round((time.perf_counter_ns() - t_vehicle_start) / 1_000_000.0, 2)
                    )
                )
                continue

            vehicle_crop, _ = v_crop_res

            # 2. Plate Localization / Detection
            try:
                plate_detections = self.plate_detector.detect_plates(
                    vehicle_crop=vehicle_crop,
                    vehicle_detection=v_det,
                    frame_shape=frame_shape
                )
            except Exception as exc:
                logger.error("Plate detector error for camera %s: %s", frame.camera_id, exc)
                anpr_results.append(
                    ANPRResult(
                        camera_id=frame.camera_id,
                        video_pts_ms=frame.pts_ms,
                        frame_index=frame.frame_index,
                        vehicle_class=v_det.class_name,
                        vehicle_bbox=v_det.bbox,
                        status="OCR_ERROR",
                        total_latency_ms=round((time.perf_counter_ns() - t_vehicle_start) / 1_000_000.0, 2)
                    )
                )
                continue

            if not plate_detections:
                anpr_results.append(
                    ANPRResult(
                        camera_id=frame.camera_id,
                        video_pts_ms=frame.pts_ms,
                        frame_index=frame.frame_index,
                        vehicle_class=v_det.class_name,
                        vehicle_bbox=v_det.bbox,
                        status="NO_PLATE",
                        total_latency_ms=round((time.perf_counter_ns() - t_vehicle_start) / 1_000_000.0, 2)
                    )
                )
                continue

            with self._telemetry_lock:
                self._plates_detected_total += len(plate_detections)

            # 3. For each detected plate: Crop -> Preprocessing -> OCR
            for p_det in plate_detections:
                t_plate_start = time.perf_counter_ns()

                # Extract plate crop relative to vehicle crop
                p_crop_res = safe_extract_crop(
                    image=vehicle_crop,
                    bbox=p_det.bbox_relative,
                    min_width=8,
                    min_height=8
                )

                if p_crop_res is None:
                    anpr_results.append(
                        ANPRResult(
                            camera_id=frame.camera_id,
                            video_pts_ms=frame.pts_ms,
                            frame_index=frame.frame_index,
                            vehicle_class=v_det.class_name,
                            vehicle_bbox=v_det.bbox,
                            plate_bbox_frame=p_det.bbox_frame,
                            plate_bbox_vehicle=p_det.bbox_relative,
                            plate_detector_confidence=p_det.confidence,
                            status="INVALID_CROP",
                            total_latency_ms=round((time.perf_counter_ns() - t_plate_start) / 1_000_000.0, 2)
                        )
                    )
                    continue

                plate_crop, _ = p_crop_res

                # Modular Preprocessing
                prep_variant = settings.ANPR_PREPROCESSING_VARIANT
                prep_img, applied_variant = PlatePreprocessor.preprocess(
                    plate_crop=plate_crop,
                    variant=prep_variant
                )

                # OCR Inference
                try:
                    ocr_res = self.ocr_provider.recognize_text(prep_img)
                except Exception as exc:
                    logger.error("OCR provider error for camera %s: %s", frame.camera_id, exc)
                    anpr_results.append(
                        ANPRResult(
                            camera_id=frame.camera_id,
                            video_pts_ms=frame.pts_ms,
                            frame_index=frame.frame_index,
                            vehicle_class=v_det.class_name,
                            vehicle_bbox=v_det.bbox,
                            plate_bbox_frame=p_det.bbox_frame,
                            plate_bbox_vehicle=p_det.bbox_relative,
                            plate_detector_confidence=p_det.confidence,
                            preprocessing_variant=applied_variant,
                            status="OCR_ERROR",
                            total_latency_ms=round((time.perf_counter_ns() - t_plate_start) / 1_000_000.0, 2)
                        )
                    )
                    continue

                with self._telemetry_lock:
                    self._ocr_reads_total += 1
                    if ocr_res.is_valid_format:
                        self._valid_format_reads += 1

                # Determine authoritative status
                if not ocr_res.raw_text:
                    status: ANPRStatus = "OCR_EMPTY"
                elif ocr_res.confidence is not None and ocr_res.confidence < settings.OCR_CONFIDENCE_THRESHOLD:
                    status = "OCR_LOW_CONFIDENCE"
                else:
                    status = "OCR_SUCCESS"

                latency_ms = round((time.perf_counter_ns() - t_plate_start) / 1_000_000.0, 2)

                anpr_results.append(
                    ANPRResult(
                        camera_id=frame.camera_id,
                        video_pts_ms=frame.pts_ms,
                        frame_index=frame.frame_index,
                        vehicle_class=v_det.class_name,
                        vehicle_bbox=v_det.bbox,
                        plate_bbox_frame=p_det.bbox_frame,
                        plate_bbox_vehicle=p_det.bbox_relative,
                        raw_text=ocr_res.raw_text,
                        normalized_text=ocr_res.normalized_text,
                        is_valid_format=ocr_res.is_valid_format,
                        plate_detector_confidence=p_det.confidence,
                        ocr_confidence=ocr_res.confidence,
                        ocr_provider=ocr_res.provider,
                        ocr_model_version=ocr_res.model_version,
                        preprocessing_variant=applied_variant,
                        status=status,
                        total_latency_ms=latency_ms
                    )
                )

        return anpr_results

    def render_debug_anpr_frame(
        self,
        frame_data: np.ndarray,
        anpr_results: List[ANPRResult],
        camera_id: str = "UNKNOWN",
        pts_ms: float = 0.0
    ) -> np.ndarray:
        """Render debug visualization with vehicle boxes, plate boxes, and transcriptions.

        Explicitly marked: DEBUG / TEST ONLY.
        """
        debug_img = frame_data.copy()
        h, w = debug_img.shape[:2]

        # Top diagnostic banner
        banner_text = f"[DEBUG/TEST ONLY] CAM: {camera_id[:8]} | PTS: {pts_ms:.0f}ms | PLATES READ: {len(anpr_results)}"
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

        for res in anpr_results:
            # Draw vehicle bounding box in light blue
            vx1, vy1 = int(res.vehicle_bbox.x1), int(res.vehicle_bbox.y1)
            vx2, vy2 = int(res.vehicle_bbox.x2), int(res.vehicle_bbox.y2)
            cv2.rectangle(debug_img, (vx1, vy1), (vx2, vy2), (200, 150, 50), 1)

            # Draw plate bounding box if localized
            if res.plate_bbox_frame:
                px1, py1 = int(res.plate_bbox_frame.x1), int(res.plate_bbox_frame.y1)
                px2, py2 = int(res.plate_bbox_frame.x2), int(res.plate_bbox_frame.y2)

                # Color: Green if valid format / success, Amber if low conf, Red if error
                if res.status == "OCR_SUCCESS" and res.is_valid_format:
                    p_color = (0, 255, 0)
                elif res.status == "OCR_LOW_CONFIDENCE":
                    p_color = (0, 165, 255)
                else:
                    p_color = (0, 255, 255)

                cv2.rectangle(debug_img, (px1, py1), (px2, py2), p_color, 2)

                label_text = f"{res.normalized_text or res.status} ({int((res.ocr_confidence or 0.0) * 100)}%)"
                label_size, _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(
                    debug_img,
                    (px1, max(0, py1 - 20)),
                    (px1 + label_size[0] + 6, max(0, py1)),
                    p_color,
                    -1
                )
                cv2.putText(
                    debug_img,
                    label_text,
                    (px1 + 3, max(14, py1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 0, 0),
                    1,
                    cv2.LINE_AA
                )

        return debug_img

    def get_status(self) -> ANPRStatusResponse:
        """Fetch runtime diagnostics and active configuration."""
        p_meta = self.plate_detector.metadata()
        o_meta = self.ocr_provider.metadata()

        with self._telemetry_lock:
            return ANPRStatusResponse(
                plate_detector_backend=p_meta.get("backend", "UNKNOWN"),
                plate_detector_model=p_meta.get("model_name", "unknown"),
                plate_confidence_threshold=self.plate_detector.confidence_threshold,
                ocr_provider_backend=o_meta.get("backend", "UNKNOWN"),
                ocr_provider_model=o_meta.get("model_name") or o_meta.get("provider_name", "unknown"),
                ocr_confidence_threshold=self.ocr_provider.confidence_threshold,
                preprocessing_variant=settings.ANPR_PREPROCESSING_VARIANT,
                plates_detected_total=self._plates_detected_total,
                ocr_reads_total=self._ocr_reads_total,
                valid_format_reads=self._valid_format_reads
            )


# Global singleton instance
anpr_pipeline_service = ANPRPipelineService()
