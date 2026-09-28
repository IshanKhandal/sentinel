"""Event persistence domain service for vehicle detections and ANPR observations.

Protocol Standards:
- docs/database-design.md Domain 3 (Detections, Vehicles).
- Stage 8 Directive Sections 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 17, 21, 22.
- Authoritative observation timestamp bound strictly to upstream video PTS.
- Strict camera registry verification: raises explicit CameraNotRegisteredError if camera missing.
- Canonical Vehicle profile updates on recognized plate registration.
- Atomic database transactions with rollback on failure.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.app.core.config import settings
from backend.app.models.surveillance import Camera
from backend.app.models.intelligence import Detection, Vehicle
from backend.app.schemas.anpr import ANPRResult
from backend.app.schemas.detection import NormalizedVehicleDetection

logger = logging.getLogger("sentinel.persistence")


class PersistenceError(Exception):
    """Base exception for persistence failures."""
    pass


class CameraNotRegisteredError(PersistenceError):
    """Raised when an observation references a camera ID not found in the camera registry."""
    pass


class EventValidationError(PersistenceError):
    """Raised when an observation fails data contract validation."""
    pass


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime has timezone set to UTC (handles SQLite naive timestamps)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class EventPersistenceService:
    """Domain service managing transactional persistence and querying of video detections."""

    @staticmethod
    def _parse_camera_uuid(camera_id_str: str) -> uuid.UUID:
        """Validate and parse string camera_id into standard UUID."""
        try:
            return uuid.UUID(str(camera_id_str))
        except (ValueError, AttributeError, TypeError) as exc:
            raise EventValidationError(
                f"Invalid camera_id '{camera_id_str}'. Must be a valid RFC 4122 UUID."
            ) from exc

    @staticmethod
    def _convert_pts_to_detected_at(video_pts_ms: float) -> datetime:
        """Convert authoritative upstream video presentation timestamp to UTC datetime.
        
        Strict Invariant (Section 5):
        Never substitute datetime.now(), frame arrival time, or processing time.
        """
        if video_pts_ms is None or video_pts_ms < 0:
            raise EventValidationError(
                f"Invalid video_pts_ms '{video_pts_ms}'. Must be a non-negative float."
            )
        try:
            return datetime.fromtimestamp(float(video_pts_ms) / 1000.0, tz=timezone.utc)
        except (OverflowError, ValueError, OSError) as exc:
            raise EventValidationError(
                f"Failed to convert video_pts_ms '{video_pts_ms}' to UTC datetime: {exc}"
            ) from exc

    @classmethod
    def get_or_create_vehicle_profile(
        cls,
        db: Session,
        plate_number: str,
        vehicle_type: Optional[str],
        detected_at: datetime
    ) -> Vehicle:
        """Find or create canonical Vehicle profile, updating observation counters and timeline."""
        clean_plate = plate_number.strip().upper()
        vehicle = db.query(Vehicle).filter(Vehicle.plate_number == clean_plate).first()

        if not vehicle:
            try:
                with db.begin_nested():
                    vehicle = Vehicle(
                        id=uuid.uuid4(),
                        plate_number=clean_plate,
                        vehicle_type=vehicle_type.upper() if vehicle_type else None,
                        first_seen_at=detected_at,
                        last_seen_at=detected_at,
                        total_detections_count=1
                    )
                    db.add(vehicle)
                    db.flush()
                return vehicle
            except IntegrityError:
                # Concurrent insert conflict on plate_number uniqueness; query existing profile
                vehicle = db.query(Vehicle).filter(Vehicle.plate_number == clean_plate).first()
                if not vehicle:
                    raise

        # Update existing profile
        dt_aware = ensure_utc(detected_at)
        last_aware = ensure_utc(vehicle.last_seen_at)
        first_aware = ensure_utc(vehicle.first_seen_at)

        if dt_aware > last_aware:
            vehicle.last_seen_at = detected_at
        if dt_aware < first_aware:
            vehicle.first_seen_at = detected_at
        vehicle.total_detections_count = Vehicle.total_detections_count + 1
        if not vehicle.vehicle_type and vehicle_type:
            vehicle.vehicle_type = vehicle_type.upper()
        db.flush()

        return vehicle

    @classmethod
    def persist_anpr_result(
        cls,
        db: Session,
        anpr_result: ANPRResult,
        snapshot_path: Optional[str] = None,
        plate_crop_path: Optional[str] = None
    ) -> Detection:
        """Persist a single Stage 7 ANPRResult atomically into the database.

        Strict Invariants:
        - Source camera MUST exist in cameras registry table.
        - Observation timestamp derived strictly from video_pts_ms.
        - raw_text is preserved unmodified alongside sanitized normalized plate_number.
        - Separate confidences (confidence_vehicle, confidence_plate) maintained.
        - Rollback on failure with structured error logging.
        """
        camera_uuid = cls._parse_camera_uuid(anpr_result.camera_id)
        detected_at = cls._convert_pts_to_detected_at(anpr_result.video_pts_ms)

        # 1. Verify Camera Association in Registry (Section 6)
        camera = db.query(Camera).filter(Camera.id == camera_uuid).first()
        if not camera:
            raise CameraNotRegisteredError(
                f"Cannot persist detection: Camera '{camera_uuid}' is not registered in camera catalogue."
            )

        # 2. Extract Geometry & Confidences
        v_bbox = [
            float(anpr_result.vehicle_bbox.x1),
            float(anpr_result.vehicle_bbox.y1),
            float(anpr_result.vehicle_bbox.x2),
            float(anpr_result.vehicle_bbox.y2),
        ]
        p_bbox = None
        if anpr_result.plate_bbox_frame:
            p_bbox = [
                float(anpr_result.plate_bbox_frame.x1),
                float(anpr_result.plate_bbox_frame.y1),
                float(anpr_result.plate_bbox_frame.x2),
                float(anpr_result.plate_bbox_frame.y2),
            ]

        # 3. Handle Canonical Vehicle Profile Linkage
        vehicle_id = None
        clean_plate = None
        if anpr_result.normalized_text and anpr_result.status in ("OCR_SUCCESS", "OCR_LOW_CONFIDENCE"):
            clean_plate = anpr_result.normalized_text.strip().upper()
            vehicle = cls.get_or_create_vehicle_profile(
                db=db,
                plate_number=clean_plate,
                vehicle_type=anpr_result.vehicle_class,
                detected_at=detected_at
            )
            vehicle_id = vehicle.id

        # 4. Resolve Snapshot & Demo States
        is_demo = (
            settings.SENTINEL_OPERATION_MODE == "DEMO"
            or camera.stream_type == "DEMO"
        )
        resolved_snapshot = (
            snapshot_path
            or f"snapshots/{camera_uuid}/{int(anpr_result.video_pts_ms)}.jpg"
        )

        metadata = {
            "video_pts_ms": anpr_result.video_pts_ms,
            "frame_index": anpr_result.frame_index,
            "vehicle_confidence": anpr_result.vehicle_confidence,
            "plate_detector_confidence": anpr_result.plate_detector_confidence,
            "ocr_confidence": anpr_result.ocr_confidence,
            "ocr_provider": anpr_result.ocr_provider,
            "ocr_model_version": anpr_result.ocr_model_version,
            "preprocessing_variant": anpr_result.preprocessing_variant,
            "is_valid_format": anpr_result.is_valid_format,
            "anpr_status": anpr_result.status,
            "total_latency_ms": anpr_result.total_latency_ms,
        }

        # 5. Create Detection Record
        conf_vehicle = (
            float(anpr_result.vehicle_confidence)
            if anpr_result.vehicle_confidence is not None
            else None
        )
        detection = Detection(
            id=uuid.uuid4(),
            camera_id=camera_uuid,
            vehicle_id=vehicle_id,
            plate_number=clean_plate,
            raw_text=anpr_result.raw_text,
            vehicle_type=anpr_result.vehicle_class.upper(),
            confidence_vehicle=conf_vehicle,
            confidence_plate=anpr_result.ocr_confidence,
            bbox_vehicle=v_bbox,
            bbox_plate=p_bbox,
            snapshot_path=resolved_snapshot,
            plate_crop_path=plate_crop_path,
            detection_metadata=metadata,
            is_demo=is_demo,
            detected_at=detected_at
        )

        try:
            db.add(detection)
            db.commit()
            db.refresh(detection)
            return detection
        except Exception as exc:
            db.rollback()
            logger.error(
                "Failed to persist ANPR detection for camera %s at PTS %s: %s",
                camera_uuid,
                anpr_result.video_pts_ms,
                exc,
                extra={"camera_id": str(camera_uuid), "pts_ms": anpr_result.video_pts_ms}
            )
            raise PersistenceError(f"Database persistence failure: {exc}") from exc

    @classmethod
    def persist_vehicle_detection(
        cls,
        db: Session,
        vehicle_det: NormalizedVehicleDetection,
        snapshot_path: Optional[str] = None
    ) -> Detection:
        """Persist a Stage 6 vehicle detection (without plate/OCR) atomically."""
        camera_uuid = cls._parse_camera_uuid(vehicle_det.camera_id)
        detected_at = cls._convert_pts_to_detected_at(vehicle_det.video_pts_ms)

        camera = db.query(Camera).filter(Camera.id == camera_uuid).first()
        if not camera:
            raise CameraNotRegisteredError(
                f"Cannot persist detection: Camera '{camera_uuid}' is not registered in camera catalogue."
            )

        v_bbox = [
            float(vehicle_det.bbox.x1),
            float(vehicle_det.bbox.y1),
            float(vehicle_det.bbox.x2),
            float(vehicle_det.bbox.y2),
        ]

        is_demo = (
            settings.SENTINEL_OPERATION_MODE == "DEMO"
            or camera.stream_type == "DEMO"
        )
        resolved_snapshot = (
            snapshot_path
            or f"snapshots/{camera_uuid}/{int(vehicle_det.video_pts_ms)}.jpg"
        )

        metadata = {
            "video_pts_ms": vehicle_det.video_pts_ms,
            "frame_index": vehicle_det.frame_index,
            "class_id": vehicle_det.class_id,
            "detector_model_version": vehicle_det.model_version,
            "inference_time_ms": vehicle_det.inference_time_ms,
        }

        detection = Detection(
            id=uuid.uuid4(),
            camera_id=camera_uuid,
            vehicle_id=None,
            plate_number=None,
            raw_text=None,
            vehicle_type=vehicle_det.class_name.upper(),
            confidence_vehicle=float(vehicle_det.confidence),
            confidence_plate=None,
            bbox_vehicle=v_bbox,
            bbox_plate=None,
            snapshot_path=resolved_snapshot,
            plate_crop_path=None,
            detection_metadata=metadata,
            is_demo=is_demo,
            detected_at=detected_at
        )

        try:
            db.add(detection)
            db.commit()
            db.refresh(detection)
            return detection
        except Exception as exc:
            db.rollback()
            logger.error(
                "Failed to persist vehicle detection for camera %s at PTS %s: %s",
                camera_uuid,
                vehicle_det.video_pts_ms,
                exc
            )
            raise PersistenceError(f"Database persistence failure: {exc}") from exc

    @classmethod
    def persist_anpr_batch(
        cls,
        db: Session,
        anpr_results: List[ANPRResult]
    ) -> List[Detection]:
        """Persist a batch of Stage 7 ANPRResults in a single atomic transaction."""
        if not anpr_results:
            return []

        # Validate all cameras in batch up-front
        cam_ids = {cls._parse_camera_uuid(r.camera_id) for r in anpr_results}
        existing_cams = {
            c.id: c for c in db.query(Camera).filter(Camera.id.in_(cam_ids)).all()
        }

        for cam_id in cam_ids:
            if cam_id not in existing_cams:
                raise CameraNotRegisteredError(
                    f"Batch persistence aborted: Camera '{cam_id}' is not registered in camera catalogue."
                )

        persisted_records: List[Detection] = []

        try:
            for r in anpr_results:
                camera_uuid = cls._parse_camera_uuid(r.camera_id)
                camera = existing_cams[camera_uuid]
                detected_at = cls._convert_pts_to_detected_at(r.video_pts_ms)

                v_bbox = [
                    float(r.vehicle_bbox.x1),
                    float(r.vehicle_bbox.y1),
                    float(r.vehicle_bbox.x2),
                    float(r.vehicle_bbox.y2),
                ]
                p_bbox = None
                if r.plate_bbox_frame:
                    p_bbox = [
                        float(r.plate_bbox_frame.x1),
                        float(r.plate_bbox_frame.y1),
                        float(r.plate_bbox_frame.x2),
                        float(r.plate_bbox_frame.y2),
                    ]

                vehicle_id = None
                clean_plate = None
                if r.normalized_text and r.status in ("OCR_SUCCESS", "OCR_LOW_CONFIDENCE"):
                    clean_plate = r.normalized_text.strip().upper()
                    vehicle = cls.get_or_create_vehicle_profile(
                        db=db,
                        plate_number=clean_plate,
                        vehicle_type=r.vehicle_class,
                        detected_at=detected_at
                    )
                    vehicle_id = vehicle.id

                is_demo = (
                    settings.SENTINEL_OPERATION_MODE == "DEMO"
                    or camera.stream_type == "DEMO"
                )

                metadata = {
                    "video_pts_ms": r.video_pts_ms,
                    "frame_index": r.frame_index,
                    "vehicle_confidence": r.vehicle_confidence,
                    "plate_detector_confidence": r.plate_detector_confidence,
                    "ocr_confidence": r.ocr_confidence,
                    "ocr_provider": r.ocr_provider,
                    "ocr_model_version": r.ocr_model_version,
                    "preprocessing_variant": r.preprocessing_variant,
                    "is_valid_format": r.is_valid_format,
                    "anpr_status": r.status,
                    "total_latency_ms": r.total_latency_ms,
                }

                conf_v = (
                    float(r.vehicle_confidence)
                    if r.vehicle_confidence is not None
                    else None
                )
                det = Detection(
                    id=uuid.uuid4(),
                    camera_id=camera_uuid,
                    vehicle_id=vehicle_id,
                    plate_number=clean_plate,
                    raw_text=r.raw_text,
                    vehicle_type=r.vehicle_class.upper(),
                    confidence_vehicle=conf_v,
                    confidence_plate=r.ocr_confidence,
                    bbox_vehicle=v_bbox,
                    bbox_plate=p_bbox,
                    snapshot_path=f"snapshots/{camera_uuid}/{int(r.video_pts_ms)}.jpg",
                    plate_crop_path=None,
                    detection_metadata=metadata,
                    is_demo=is_demo,
                    detected_at=detected_at
                )
                db.add(det)
                persisted_records.append(det)

            db.commit()
            for det in persisted_records:
                db.refresh(det)
            return persisted_records

        except Exception as exc:
            db.rollback()
            logger.error("Failed batch persistence of %d ANPR results: %s", len(anpr_results), exc)
            raise PersistenceError(f"Batch persistence failure: {exc}") from exc

    @staticmethod
    def get_detection_by_id(db: Session, detection_id: uuid.UUID) -> Optional[Detection]:
        """Query single detection record by primary key UUID."""
        return db.query(Detection).filter(Detection.id == detection_id).first()

    @staticmethod
    def query_detections(
        db: Session,
        plate_number: Optional[str] = None,
        camera_id: Optional[uuid.UUID] = None,
        vehicle_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
        skip: int = 0
    ) -> Tuple[List[Detection], int]:
        """Search and filter historical vehicle detections across the surveillance network.

        Indexes Utilized (docs/database-design.md):
        - idx_detections_plate_time on (plate_number, detected_at)
        - idx_detections_cam_time on (camera_id, detected_at)
        - idx_detections_detected_at on (detected_at)
        """
        query = db.query(Detection)

        if plate_number:
            clean = plate_number.strip().upper()
            if "%" in clean or "_" in clean:
                query = query.filter(Detection.plate_number.like(clean))
            else:
                query = query.filter(Detection.plate_number == clean)

        if camera_id:
            query = query.filter(Detection.camera_id == camera_id)

        if vehicle_type:
            query = query.filter(Detection.vehicle_type == vehicle_type.strip().upper())

        if start_time:
            query = query.filter(Detection.detected_at >= start_time)

        if end_time:
            query = query.filter(Detection.detected_at <= end_time)

        total = query.count()
        items = query.order_by(Detection.detected_at.desc()).offset(skip).limit(min(limit, 200)).all()
        return items, total

    @classmethod
    def persist_and_match(
        cls,
        db: Session,
        anpr_result: ANPRResult,
        snapshot_path: Optional[str] = None,
        plate_crop_path: Optional[str] = None,
    ) -> Tuple[Detection, List[Any]]:
        """Persist an ANPR detection (Stage 8) and evaluate against active watchlists (Stage 9).
        
        Boundary Enforcement:
        - Executes Stage 8 transactional event persistence.
        - Invokes Stage 9 deterministic watchlist matching engine.
        - STRICT INVARIANT: Does NOT create alerts or trigger notifications (Stage 10 boundary).
        """
        from backend.app.services.watchlist.matcher import WatchlistMatcher

        # Stage 8: Persist detection
        detection = cls.persist_anpr_result(
            db=db,
            anpr_result=anpr_result,
            snapshot_path=snapshot_path,
            plate_crop_path=plate_crop_path,
        )

        # Stage 9: Evaluate against configured watchlists
        matches = WatchlistMatcher.match_detection(db=db, detection=detection)

        return detection, matches
