"""Pydantic schemas for vehicle detection and normalized detection contracts.

Protocol Standards:
- docs/ai-architecture.md Section 2 (ObjectDetector).
- Stage 6 Directive Sections 12, 13, 14, 20, 21.
- Strict non-hallucination: NO track_id, NO plate_text, NO vehicle_id in this stage.
- Canonical coordinate standard: (x1, y1, x2, y2) in original source frame pixels.
"""

import math
from typing import Optional, List, Tuple, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class BoundingBox(BaseModel):
    """Canonical 2D bounding box in source frame pixel coordinates [x1, y1, x2, y2]."""

    x1: float = Field(..., description="Left horizontal boundary coordinate in pixels")
    y1: float = Field(..., description="Top vertical boundary coordinate in pixels")
    x2: float = Field(..., description="Right horizontal boundary coordinate in pixels")
    y2: float = Field(..., description="Bottom vertical boundary coordinate in pixels")

    @field_validator("x1", "y1", "x2", "y2")
    @classmethod
    def validate_coordinate_values(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"Coordinate cannot be NaN or Infinite: {v}")
        if v < 0:
            raise ValueError(f"Coordinate cannot be negative: {v}")
        return round(float(v), 2)

    @model_validator(mode="after")
    def validate_box_geometry(self) -> "BoundingBox":
        if self.x1 >= self.x2:
            raise ValueError(f"x1 ({self.x1}) must be strictly less than x2 ({self.x2})")
        if self.y1 >= self.y2:
            raise ValueError(f"y1 ({self.y1}) must be strictly less than y2 ({self.y2})")
        return self

    @property
    def width(self) -> float:
        return round(self.x2 - self.x1, 2)

    @property
    def height(self) -> float:
        return round(self.y2 - self.y1, 2)

    @property
    def area(self) -> float:
        return round(self.width * self.height, 2)

    @property
    def center(self) -> Tuple[float, float]:
        return (round((self.x1 + self.x2) / 2.0, 2), round((self.y1 + self.y2) / 2.0, 2))

    def as_tuple(self) -> Tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)

    def to_normalized(self, frame_width: int, frame_height: int) -> Tuple[float, float, float, float]:
        """Convert pixel coordinates to normalized [0.0, 1.0] range."""
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError(f"Invalid frame dimensions for normalization: {frame_width}x{frame_height}")
        return (
            round(min(1.0, max(0.0, self.x1 / frame_width)), 4),
            round(min(1.0, max(0.0, self.y1 / frame_height)), 4),
            round(min(1.0, max(0.0, self.x2 / frame_width)), 4),
            round(min(1.0, max(0.0, self.y2 / frame_height)), 4),
        )


class NormalizedVehicleDetection(BaseModel):
    """Canonical normalized vehicle detection object emitted by Stage 6.
    
    Hard Scope Constraint:
    Does NOT contain track_id, plate_text, or vehicle_id.
    Those belong to future stages (ANPR Stage 7, Tracking Stage 11).
    """

    camera_id: str = Field(..., description="Originating camera UUID from stream session")
    video_pts_ms: float = Field(..., ge=0.0, description="Authoritative video presentation timestamp in ms")
    class_id: int = Field(..., ge=0, description="Model-specific vehicle class ID")
    class_name: str = Field(..., description="Verified vehicle category (e.g. car, motorcycle, bus, truck)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence score in [0.0, 1.0]")
    bbox: BoundingBox = Field(..., description="Bounding box in source frame pixel coordinates")
    frame_index: Optional[int] = Field(default=None, ge=0, description="Sequential stream frame index")
    inference_time_ms: float = Field(default=0.0, ge=0.0, description="Measured inference execution time in ms")
    model_version: str = Field(default="unknown", description="Detector model version and backend identifier")


class DetectorStatusResponse(BaseModel):
    """Runtime diagnostics and metadata for active vehicle detector."""

    backend: str = Field(..., description="Active detector backend (MOCK or ONNX_RUNTIME)")
    model_name: str = Field(..., description="Model identifier")
    model_version: str = Field(..., description="Model release/version tag")
    confidence_threshold: float = Field(..., description="Current minimum confidence filtering threshold")
    fps_limit: float = Field(..., description="Max target detection sampling FPS")
    supported_classes: List[str] = Field(default_factory=list, description="Vehicle classes detected by this model")
    frames_processed: int = Field(default=0, ge=0, description="Total frames processed by detector")
    frames_skipped: int = Field(default=0, ge=0, description="Frames skipped due to FPS sampling decimation")
    total_vehicles_detected: int = Field(default=0, ge=0, description="Total vehicle objects detected")
    last_inference_latency_ms: Optional[float] = Field(default=None, description="Most recent inference duration in ms")
