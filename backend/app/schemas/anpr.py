"""Pydantic schemas for Plate Detection, OCR, and Normalized ANPR Results.

Protocol Standards:
- docs/ai-architecture.md Section 2 (PlateDetector, OCRProvider).
- Stage 7 Directive Sections 7, 12, 14, 15, 16.
- Strict separation between plate_detector_confidence and ocr_confidence.
- Strict preservation of raw_text vs normalized_text.
- Coordinates explicitly separated: bbox_frame vs bbox_vehicle.
"""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field

from backend.app.schemas.detection import BoundingBox

ANPRStatus = Literal[
    "NO_VEHICLE",
    "NO_PLATE",
    "INVALID_CROP",
    "PLATE_DETECTED",
    "OCR_SUCCESS",
    "OCR_EMPTY",
    "OCR_LOW_CONFIDENCE",
    "OCR_UNREADABLE",
    "OCR_ERROR",
    "PROVIDER_UNAVAILABLE"
]


class PlateDetectionResult(BaseModel):
    """Plate detection bounding box in both vehicle crop and frame coordinate systems."""

    bbox_relative: BoundingBox = Field(..., description="Plate box relative to vehicle crop coordinates")
    bbox_frame: BoundingBox = Field(..., description="Plate box relative to original source camera frame coordinates")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Plate localization model confidence score")
    model_version: str = Field(default="unknown", description="Plate detector model identifier")
    inference_latency_ms: float = Field(default=0.0, ge=0.0, description="Plate detection inference duration in ms")


class OCRResult(BaseModel):
    """Raw and normalized transcription result from an OCR provider."""

    raw_text: str = Field(..., description="Unmodified transcription directly returned by the OCR model")
    normalized_text: str = Field(..., description="Sanitized, uppercase, alphanumeric registration string")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="OCR text recognition confidence score")
    char_confidences: List[float] = Field(default_factory=list, description="Per-character recognition confidence scores")
    is_valid_format: bool = Field(default=False, description="Whether normalized text strictly matches registration syntax regex")
    provider: str = Field(default="unknown", description="OCR provider backend name (e.g. MOCK, ONNX, TESSERACT)")
    model_version: str = Field(default="unknown", description="OCR model architecture and weights version")
    inference_latency_ms: float = Field(default=0.0, ge=0.0, description="OCR inference duration in ms")


class ANPRResult(BaseModel):
    """Canonical Stage 7 output combining vehicle detection, plate localization, and OCR transcription.
    
    Hard Scope Invariant:
    Does NOT contain track_id, watchlist_id, or alert_status (deferred to Stages 9-11).
    """

    camera_id: str = Field(..., description="Originating surveillance camera UUID from Stage 5 stream")
    video_pts_ms: float = Field(..., ge=0.0, description="Authoritative video presentation timestamp from Stage 5")
    frame_index: Optional[int] = Field(default=None, description="Sequential stream frame index")
    vehicle_class: str = Field(..., description="Detected vehicle category (e.g. car, truck, bus, motorcycle)")
    vehicle_bbox: BoundingBox = Field(..., description="Vehicle bounding box in original frame pixel coordinates")
    vehicle_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Vehicle detector confidence score")
    plate_bbox_frame: Optional[BoundingBox] = Field(default=None, description="Plate bounding box in original frame pixel coordinates")
    plate_bbox_vehicle: Optional[BoundingBox] = Field(default=None, description="Plate bounding box in vehicle crop coordinates")
    raw_text: Optional[str] = Field(default=None, description="Raw transcription directly from OCR engine")
    normalized_text: Optional[str] = Field(default=None, description="Cleaned uppercase alphanumeric registration plate")
    is_valid_format: bool = Field(default=False, description="Compliance with Indian vehicle registration regex")
    plate_detector_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Plate detection confidence")
    ocr_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="OCR transcription confidence")
    ocr_provider: str = Field(default="unknown", description="OCR engine backend used")
    ocr_model_version: str = Field(default="unknown", description="OCR model version")
    preprocessing_variant: str = Field(default="standard", description="Applied image preprocessing variant")
    status: ANPRStatus = Field(..., description="Authoritative ANPR processing state")
    total_latency_ms: float = Field(default=0.0, ge=0.0, description="Total pipeline latency (crop + plate + ocr) in ms")


class ANPRStatusResponse(BaseModel):
    """Runtime diagnostics and metadata for active ANPR subsystem."""

    plate_detector_backend: str = Field(..., description="Active plate detector backend (MOCK or ONNX_RUNTIME)")
    plate_detector_model: str = Field(..., description="Plate detector model identifier")
    plate_confidence_threshold: float = Field(..., description="Plate detection threshold")
    ocr_provider_backend: str = Field(..., description="Active OCR engine backend (MOCK or ONNX_RUNTIME)")
    ocr_provider_model: str = Field(..., description="OCR model identifier")
    ocr_confidence_threshold: float = Field(..., description="Minimum OCR confidence threshold")
    preprocessing_variant: str = Field(..., description="Active image preprocessing filter")
    plates_detected_total: int = Field(default=0, ge=0, description="Total plates localized")
    ocr_reads_total: int = Field(default=0, ge=0, description="Total OCR transcriptions attempted")
    valid_format_reads: int = Field(default=0, ge=0, description="Transcriptions adhering to valid syntax")
