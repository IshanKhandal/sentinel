"""Abstract base class interface for pluggable object detection.

Protocol Standard: docs/ai-architecture.md Section 2 (ObjectDetector).
Decouples application logic from underlying ML inference engines (ONNX, PyTorch, Mock).
"""

import abc
from typing import List, Dict, Any, Optional
from backend.app.services.streaming.models import DecodedFrame
from backend.app.schemas.detection import NormalizedVehicleDetection


# Standard COCO vehicle class mappings
DEFAULT_COCO_VEHICLE_CLASSES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


class ObjectDetector(abc.ABC):
    """Abstract interface defining the contract for all vehicle detection models."""

    def __init__(self, confidence_threshold: float = 0.25) -> None:
        self.confidence_threshold = confidence_threshold
        self._is_loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    @abc.abstractmethod
    def load(self) -> None:
        """Initialize and allocate inference session or model weights."""
        pass

    @abc.abstractmethod
    def detect(self, frame: DecodedFrame) -> List[NormalizedVehicleDetection]:
        """Execute detection on a single decoded frame.

        Args:
            frame: DecodedFrame object from Stage 5 stream ingestion layer
                   containing raw BGR image array, camera_id, and video_pts_ms.

        Returns:
            List of NormalizedVehicleDetection objects.
        """
        pass

    @abc.abstractmethod
    def metadata(self) -> Dict[str, Any]:
        """Return runtime metadata describing model architecture, backend, and version."""
        pass
