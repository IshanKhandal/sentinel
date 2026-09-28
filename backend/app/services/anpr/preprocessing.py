"""Modular plate crop preprocessing filters for OCR enhancement.

Protocol Standard: Stage 7 Directive Section 9.
Supports non-destructive enhancement variants (CLAHE, grayscale, bilateral denoising)
and preserves the exact preprocessing variant used in the result telemetry.
"""

from typing import Tuple
import cv2
import numpy as np


class PlatePreprocessor:
    """Modular image preprocessor enhancing cropped license plates for OCR models."""

    @classmethod
    def preprocess(
        cls,
        plate_crop: np.ndarray,
        variant: str = "standard",
        target_height: int = 64
    ) -> Tuple[np.ndarray, str]:
        """Apply requested preprocessing filter to cropped license plate.

        Args:
            plate_crop: (H, W, 3) BGR image array
            variant: "standard", "clahe", "grayscale", "raw"
            target_height: Normalized height preserving aspect ratio

        Returns:
            (preprocessed_image, variant_name)
        """
        if plate_crop is None or plate_crop.size == 0:
            return plate_crop, "invalid"

        h, w = plate_crop.shape[:2]
        if h <= 0 or w <= 0:
            return plate_crop, "invalid"

        # 1. Resize to target height while preserving aspect ratio
        if h != target_height and target_height > 0:
            scale = target_height / float(h)
            new_w = max(16, int(round(w * scale)))
            resized = cv2.resize(plate_crop, (new_w, target_height), interpolation=cv2.INTER_CUBIC)
        else:
            resized = plate_crop.copy()

        # 2. Apply requested variant
        v = variant.lower()

        if v == "raw":
            return resized, "raw"

        # Grayscale conversion
        if len(resized.shape) == 3 and resized.shape[2] == 3:
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        else:
            gray = resized.copy()

        if v == "grayscale":
            return gray, "grayscale"

        # CLAHE (Contrast Limited Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        if v == "clahe":
            return enhanced, "clahe"

        # Standard: CLAHE + Bilateral filtering (preserves text edges while smoothing sensor noise)
        denoised = cv2.bilateralFilter(enhanced, d=5, sigmaColor=50, sigmaSpace=50)
        return denoised, "standard"
