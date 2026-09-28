"""Aspect-ratio preserving frame preprocessing and coordinate transforms.

Protocol Standard: Stage 6 Directive Sections 9, 20, 21.
Ensures image aspect ratio is preserved during neural network tensor resizing,
and reverses letterbox offsets cleanly back to original camera coordinate space.
"""

from typing import Tuple
import cv2
import numpy as np

from backend.app.schemas.detection import BoundingBox


def letterbox(
    image: np.ndarray,
    target_shape: Tuple[int, int] = (640, 640),
    color: Tuple[int, int, int] = (114, 114, 114),
    auto_stride: int = 32
) -> Tuple[np.ndarray, float, Tuple[int, int]]:
    """Resize image to target shape with aspect-ratio preserving symmetric padding.

    Returns:
        padded_image: Resized and padded image (target_shape[0], target_shape[1], 3)
        scale_ratio: Rescaling multiplier applied to original dimensions
        (pad_x, pad_y): Padding offsets added to left and top
    """
    orig_h, orig_w = image.shape[:2]
    target_h, target_w = target_shape

    # Calculate uniform scaling factor
    scale = min(target_w / orig_w, target_h / orig_h)
    new_unpad_w = int(round(orig_w * scale))
    new_unpad_h = int(round(orig_h * scale))

    # Calculate padding offsets
    pad_w = target_w - new_unpad_w
    pad_h = target_h - new_unpad_h

    # Divide padding into equal two sides
    pad_left = pad_w // 2
    pad_right = pad_w - pad_left
    pad_top = pad_h // 2
    pad_bottom = pad_h - pad_top

    # Resize image if dimensions changed
    if (orig_w, orig_h) != (new_unpad_w, new_unpad_h):
        resized = cv2.resize(image, (new_unpad_w, new_unpad_h), interpolation=cv2.INTER_LINEAR)
    else:
        resized = image

    # Add border padding
    padded = cv2.copyMakeBorder(
        resized,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=color
    )

    return padded, scale, (pad_left, pad_top)


def reverse_letterbox_bbox(
    bbox_xyxy: Tuple[float, float, float, float],
    scale: float,
    pad: Tuple[int, int],
    orig_shape: Tuple[int, int]
) -> BoundingBox:
    """Reverse letterbox padding and scaling back to original frame pixel coordinates.

    Args:
        bbox_xyxy: (x1, y1, x2, y2) in letterboxed image space
        scale: Rescaling factor returned by letterbox()
        pad: (pad_left, pad_top) returned by letterbox()
        orig_shape: (orig_width, orig_height) of source frame
    """
    if scale <= 0:
        raise ValueError(f"Scale must be strictly positive: {scale}")

    pad_x, pad_y = pad
    orig_w, orig_h = orig_shape

    # Unpad coordinates
    unpad_x1 = (bbox_xyxy[0] - pad_x) / scale
    unpad_y1 = (bbox_xyxy[1] - pad_y) / scale
    unpad_x2 = (bbox_xyxy[2] - pad_x) / scale
    unpad_y2 = (bbox_xyxy[3] - pad_y) / scale

    # Clamp to original frame boundaries
    clamped_x1 = max(0.0, min(float(orig_w), unpad_x1))
    clamped_y1 = max(0.0, min(float(orig_h), unpad_y1))
    clamped_x2 = max(0.0, min(float(orig_w), unpad_x2))
    clamped_y2 = max(0.0, min(float(orig_h), unpad_y2))

    # Guard against invalid degenerate boxes
    if clamped_x2 <= clamped_x1:
        clamped_x2 = min(float(orig_w), clamped_x1 + 1.0)
    if clamped_y2 <= clamped_y1:
        clamped_y2 = min(float(orig_h), clamped_y1 + 1.0)

    return BoundingBox(
        x1=clamped_x1,
        y1=clamped_y1,
        x2=clamped_x2,
        y2=clamped_y2
    )
