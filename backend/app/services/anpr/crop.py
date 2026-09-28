"""Safe image crop extraction and cross-space coordinate transformations.

Protocol Standards:
- Stage 7 Directive Sections 7 & 8.
- Explicit coordinate space separation: Frame vs Vehicle Crop vs Plate Crop.
- Bounds clamping, zero-area protection, and minimal dimension thresholds.
"""

from typing import Optional, Tuple
import numpy as np
from backend.app.schemas.detection import BoundingBox


def safe_extract_crop(
    image: Optional[np.ndarray],
    bbox: BoundingBox,
    min_width: int = 16,
    min_height: int = 16
) -> Optional[Tuple[np.ndarray, BoundingBox]]:
    """Extract a cropped sub-image bounded safely within image boundaries.

    Handles:
    - Bounding boxes exceeding image boundaries (clamps safely)
    - Zero-area or inverted boxes
    - Sub-resolution crops (< min_width or min_height)
    - None or empty source image

    Returns:
        (cropped_image, clamped_bbox) or None if crop is invalid or unusable.
    """
    if image is None or image.size == 0:
        return None

    img_h, img_w = image.shape[:2]
    if img_h <= 0 or img_w <= 0:
        return None

    # Safe boundary clamping
    x1 = max(0, min(img_w, int(round(bbox.x1))))
    y1 = max(0, min(img_h, int(round(bbox.y1))))
    x2 = max(0, min(img_w, int(round(bbox.x2))))
    y2 = max(0, min(img_h, int(round(bbox.y2))))

    # Check for degenerate or inverted boxes
    crop_w = x2 - x1
    crop_h = y2 - y1

    if crop_w < min_width or crop_h < min_height:
        return None

    # Slice numpy array [y1:y2, x1:x2]
    cropped = image[y1:y2, x1:x2].copy()

    clamped_box = BoundingBox(
        x1=float(x1),
        y1=float(y1),
        x2=float(x2),
        y2=float(y2)
    )

    return cropped, clamped_box


def transform_plate_to_frame_coords(
    plate_bbox_vehicle: BoundingBox,
    vehicle_bbox_frame: BoundingBox,
    frame_shape: Tuple[int, int]
) -> BoundingBox:
    """Transform plate bounding box from vehicle-crop coordinate space to original frame space.

    Formula:
        x_frame = x_vehicle + vehicle_bbox.x1
        y_frame = y_vehicle + vehicle_bbox.y1

    Args:
        plate_bbox_vehicle: Plate box relative to the vehicle crop origin (0, 0)
        vehicle_bbox_frame: Vehicle box relative to the source frame origin (0, 0)
        frame_shape: (frame_width, frame_height) for bounds clamping
    """
    frame_w, frame_h = frame_shape

    abs_x1 = max(0.0, min(float(frame_w), vehicle_bbox_frame.x1 + plate_bbox_vehicle.x1))
    abs_y1 = max(0.0, min(float(frame_h), vehicle_bbox_frame.y1 + plate_bbox_vehicle.y1))
    abs_x2 = max(0.0, min(float(frame_w), vehicle_bbox_frame.x1 + plate_bbox_vehicle.x2))
    abs_y2 = max(0.0, min(float(frame_h), vehicle_bbox_frame.y1 + plate_bbox_vehicle.y2))

    # Guard against degenerate boxes
    if abs_x2 <= abs_x1:
        abs_x2 = min(float(frame_w), abs_x1 + 1.0)
    if abs_y2 <= abs_y1:
        abs_y2 = min(float(frame_h), abs_y1 + 1.0)

    return BoundingBox(
        x1=abs_x1,
        y1=abs_y1,
        x2=abs_x2,
        y2=abs_y2
    )
