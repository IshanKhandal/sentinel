"""OCR provider abstraction and inference implementations for license plate reading.

Protocol Standards:
- docs/ai-architecture.md Section 2 (OCRProvider).
- Stage 7 Directive Sections 11, 12, 13, 14, 16.
- Strict separation of raw_text vs normalized_text.
- Pluggable backends: MockOCRProvider (offline/CI/demo) and ONNXRuntimeOCRProvider.
"""

import abc
import os
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np

from backend.app.schemas.anpr import OCRResult
from backend.app.services.anpr.normalization import (
    normalize_plate_text,
    contextual_plate_correction
)

logger = logging.getLogger("sentinel.anpr.ocr_provider")


class OCRProvider(abc.ABC):
    """Abstract interface defining the contract for all license plate text recognition engines."""

    def __init__(self, confidence_threshold: float = 0.50) -> None:
        self.confidence_threshold = confidence_threshold
        self._is_loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    @abc.abstractmethod
    def load(self) -> None:
        """Initialize OCR engine resources and vocabulary."""
        pass

    @abc.abstractmethod
    def recognize_text(self, plate_crop: np.ndarray) -> OCRResult:
        """Execute text recognition on preprocessed license plate crop.

        Args:
            plate_crop: Preprocessed license plate sub-image (grayscale or BGR)

        Returns:
            OCRResult containing raw_text, normalized_text, confidence, and format validity.
        """
        pass

    @abc.abstractmethod
    def metadata(self) -> Dict[str, Any]:
        """Return runtime metadata describing OCR model architecture, vocabulary, and backend."""
        pass


class MockOCRProvider(OCRProvider):
    """Deterministic OCR provider for unit testing, offline CI, and demo verification."""

    def __init__(
        self,
        confidence_threshold: float = 0.50,
        deterministic_transcription: Optional[str] = None,
        deterministic_confidence: float = 0.94
    ) -> None:
        super().__init__(confidence_threshold=confidence_threshold)
        self.deterministic_transcription = deterministic_transcription
        self.deterministic_confidence = deterministic_confidence

    def load(self) -> None:
        self._is_loaded = True

    def recognize_text(self, plate_crop: np.ndarray) -> OCRResult:
        if not self._is_loaded:
            self.load()

        t_start = time.perf_counter_ns()

        if plate_crop is None or plate_crop.size == 0:
            return OCRResult(
                raw_text="",
                normalized_text="",
                confidence=0.0,
                char_confidences=[],
                is_valid_format=False,
                provider="MOCK",
                model_version="mock-ocr-v1.0",
                inference_latency_ms=0.0
            )

        h, w = plate_crop.shape[:2]
        if h < 8 or w < 16:
            return OCRResult(
                raw_text="",
                normalized_text="",
                confidence=0.0,
                char_confidences=[],
                is_valid_format=False,
                provider="MOCK",
                model_version="mock-ocr-v1.0",
                inference_latency_ms=round((time.perf_counter_ns() - t_start) / 1_000_000.0, 2)
            )

        # Determine raw text transcription
        if self.deterministic_transcription is not None:
            raw_text = self.deterministic_transcription
        else:
            # Deterministic default plate reading representing Gujarat state registration
            raw_text = "GJ 01 AB 1234"

        # Apply normalization and contextual correction
        norm_text, is_valid, was_corrected = normalize_plate_text(raw_text)
        if not is_valid:
            norm_text, is_valid, was_corrected = contextual_plate_correction(norm_text)

        latency_ms = round((time.perf_counter_ns() - t_start) / 1_000_000.0, 2)

        # Character-level confidence distribution
        char_confs = [self.deterministic_confidence] * len(norm_text) if norm_text else []

        return OCRResult(
            raw_text=raw_text,
            normalized_text=norm_text,
            confidence=self.deterministic_confidence,
            char_confidences=char_confs,
            is_valid_format=is_valid,
            provider="MOCK",
            model_version="mock-ocr-v1.0",
            inference_latency_ms=latency_ms
        )

    def metadata(self) -> Dict[str, Any]:
        return {
            "provider_name": "mock-ocr-provider",
            "model_version": "mock-ocr-v1.0",
            "backend": "MOCK",
            "confidence_threshold": self.confidence_threshold,
            "license": "Project Internal (Test Only)",
            "is_loaded": self._is_loaded,
        }


class ONNXRuntimeOCRProvider(OCRProvider):
    """Production ONNX Runtime OCR engine (CRNN / CTC architecture) for license plates."""

    # Default uppercase alphanumeric vocabulary for vehicle plates
    DEFAULT_VOCABULARY = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.50,
        vocabulary: Optional[str] = None,
        providers: Optional[List[str]] = None
    ) -> None:
        super().__init__(confidence_threshold=confidence_threshold)
        self.model_path = model_path
        self.vocabulary = vocabulary or self.DEFAULT_VOCABULARY
        self.preferred_providers = providers

        self._session = None
        self._input_name: str = ""
        self._output_name: str = ""
        self._input_shape: Tuple[int, int] = (32, 100)  # (H, W)
        self._input_channels: int = 1  # Grayscale default for CRNN
        self._active_provider: str = "UNINITIALIZED"

    def load(self) -> None:
        if not self.model_path or not os.path.exists(self.model_path):
            raise FileNotFoundError(f"ONNX OCR model file not found at: {self.model_path}")

        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required for ONNXRuntimeOCRProvider but is not installed."
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
            self._input_channels = shape[1] if isinstance(shape[1], int) and shape[1] > 0 else 1
            h = shape[2] if isinstance(shape[2], int) and shape[2] > 0 else 32
            w = shape[3] if isinstance(shape[3], int) and shape[3] > 0 else 100
            self._input_shape = (h, w)

        self._is_loaded = True
        logger.info(
            "ONNXRuntimeOCRProvider loaded '%s' with %s, input shape: %s (ch=%d)",
            self.model_path,
            self._active_provider,
            self._input_shape,
            self._input_channels
        )

    def recognize_text(self, plate_crop: np.ndarray) -> OCRResult:
        if not self._is_loaded:
            self.load()

        t_start = time.perf_counter_ns()

        if plate_crop is None or plate_crop.size == 0:
            return OCRResult(
                raw_text="",
                normalized_text="",
                confidence=0.0,
                char_confidences=[],
                is_valid_format=False,
                provider="ONNX_RUNTIME",
                model_version=f"onnx-ocr-{os.path.basename(self.model_path)}",
                inference_latency_ms=0.0
            )

        target_h, target_w = self._input_shape

        # Preprocess input image to match tensor dimensions
        if self._input_channels == 1:
            if len(plate_crop.shape) == 3:
                img = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
            else:
                img = plate_crop.copy()
            resized = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_CUBIC)
            blob = resized.astype(np.float32) / 255.0
            blob = np.expand_dims(blob, axis=0)  # (1, H, W)
            blob = np.expand_dims(blob, axis=0)  # (1, 1, H, W)
        else:
            if len(plate_crop.shape) == 2:
                img = cv2.cvtColor(plate_crop, cv2.COLOR_GRAY2BGR)
            else:
                img = plate_crop.copy()
            resized = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_CUBIC)
            blob = resized.astype(np.float32) / 255.0
            blob = np.transpose(blob, (2, 0, 1))  # (3, H, W)
            blob = np.expand_dims(blob, axis=0)  # (1, 3, H, W)

        outputs = self._session.run([self._output_name], {self._input_name: blob})
        logits = outputs[0]  # Shape typically (time_steps, batch, num_classes) or (batch, time_steps, num_classes)

        if len(logits.shape) == 3 and logits.shape[1] == 1:
            # (time_steps, 1, num_classes)
            probs = logits[:, 0, :]
        elif len(logits.shape) == 3 and logits.shape[0] == 1:
            # (1, time_steps, num_classes)
            probs = logits[0, :, :]
        else:
            probs = logits

        # Softmax over vocabulary classes
        exp_p = np.exp(probs - np.max(probs, axis=-1, keepdims=True))
        softmax_probs = exp_p / np.sum(exp_p, axis=-1, keepdims=True)

        pred_indices = np.argmax(softmax_probs, axis=-1)
        step_confidences = np.max(softmax_probs, axis=-1)

        # Greedy CTC decoding (0 index represents blank CTC token)
        raw_chars: List[str] = []
        char_confs: List[float] = []
        prev_idx = -1

        for idx, conf in zip(pred_indices, step_confidences):
            if idx != 0 and idx != prev_idx:
                # Map to character: vocabulary index = idx - 1 (since 0 is blank)
                vocab_idx = idx - 1
                if 0 <= vocab_idx < len(self.vocabulary):
                    raw_chars.append(self.vocabulary[vocab_idx])
                    char_confs.append(float(conf))
            prev_idx = idx

        raw_text = "".join(raw_chars)
        overall_conf = float(np.mean(char_confs)) if char_confs else 0.0

        # Run normalization
        norm_text, is_valid, was_corrected = normalize_plate_text(raw_text)
        if not is_valid:
            norm_text, is_valid, was_corrected = contextual_plate_correction(norm_text)

        latency_ms = round((time.perf_counter_ns() - t_start) / 1_000_000.0, 2)

        return OCRResult(
            raw_text=raw_text,
            normalized_text=norm_text,
            confidence=round(overall_conf, 3),
            char_confidences=[round(c, 3) for c in char_confs],
            is_valid_format=is_valid,
            provider="ONNX_RUNTIME",
            model_version=f"onnx-ocr-{os.path.basename(self.model_path)}",
            inference_latency_ms=latency_ms
        )

    def metadata(self) -> Dict[str, Any]:
        return {
            "model_path": self.model_path,
            "model_name": os.path.basename(self.model_path),
            "backend": "ONNX_RUNTIME",
            "active_provider": self._active_provider,
            "confidence_threshold": self.confidence_threshold,
            "vocabulary_length": len(self.vocabulary),
            "input_shape": self._input_shape,
            "is_loaded": self._is_loaded,
        }
