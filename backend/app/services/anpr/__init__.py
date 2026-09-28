"""Sentinel Stage 7: License Plate Detection, Preprocessing, and OCR Package."""

from backend.app.schemas.anpr import (
    ANPRStatus,
    PlateDetectionResult,
    OCRResult,
    ANPRResult,
    ANPRStatusResponse
)
from backend.app.services.anpr.crop import (
    safe_extract_crop,
    transform_plate_to_frame_coords
)
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
from backend.app.services.anpr.pipeline import (
    ANPRPipelineService,
    anpr_pipeline_service
)

__all__ = [
    "ANPRStatus",
    "PlateDetectionResult",
    "OCRResult",
    "ANPRResult",
    "ANPRStatusResponse",
    "safe_extract_crop",
    "transform_plate_to_frame_coords",
    "normalize_plate_text",
    "contextual_plate_correction",
    "INDIAN_STANDARD_PLATE_REGEX",
    "INDIAN_BHARAT_SERIES_REGEX",
    "PlatePreprocessor",
    "PlateDetector",
    "MockPlateDetector",
    "ONNXRuntimePlateDetector",
    "OCRProvider",
    "MockOCRProvider",
    "ONNXRuntimeOCRProvider",
    "ANPRPipelineService",
    "anpr_pipeline_service",
]
