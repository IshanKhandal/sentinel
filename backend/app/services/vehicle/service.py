"""Vehicle intelligence and chronological observation history domain service.

Protocol Standards:
- docs/api-contract.md Section 7 (Vehicles & Journey).
- docs/database-design.md Domain 3 (Vehicles, Detections).
- Stage 11 Directive Sections 2-25.
- STRICT CHRONOLOGY: Order strictly by observation timestamp (detected_at), with Detection.id tie-breaker.
- STRICT PROVENANCE: Preserves upstream video PTS, raw OCR text, and is_demo indicators.
- STRICT ISOLATION: No route reconstruction, speed estimation, or next-camera predictions (Stage 12).
- UNKNOWN DATA: Missing location coordinates serialized as None (never 0,0).
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from backend.app.models.intelligence import Vehicle, Detection
from backend.app.models.surveillance import Camera, Location
from backend.app.models.watchlists import Watchlist, WatchlistEntry
from backend.app.schemas.vehicle import (
    VehicleProfileRead,
    VehicleObservationItem,
    VehicleHistoryResponse,
    VehicleQueryWindow,
)

logger = logging.getLogger("sentinel.vehicle.service")


class VehicleServiceError(Exception):
    """Base exception for vehicle service domain failures."""
    pass


class VehicleNotFoundError(VehicleServiceError):
    """Raised when a requested vehicle plate has no profile or observation records."""
    pass


class VehicleHistoryValidationError(VehicleServiceError):
    """Raised when query parameters fail contract validation."""
    pass


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime has timezone set to UTC (handles SQLite naive timestamps)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class VehicleService:
    """Domain service for querying vehicle profiles and chronological observation history."""

    @classmethod
    def get_vehicle_profile(
        cls,
        db: Session,
        plate_number: str
    ) -> Optional[VehicleProfileRead]:
        """Retrieve canonical vehicle profile, observation statistics, and active watchlist status.
        
        Contract: docs/api-contract.md Section 7 (`GET /api/v1/vehicles/{plate_number}`).
        
        Returns:
            VehicleProfileRead if vehicle exists in records, None if not found.
        """
        if not plate_number or not plate_number.strip():
            raise VehicleHistoryValidationError("Plate number must be non-empty.")

        clean_plate = plate_number.strip().upper()

        # 1. Check canonical vehicle registry
        vehicle = (
            db.query(Vehicle)
            .filter(Vehicle.plate_number == clean_plate)
            .first()
        )

        # 2. Check active watchlist enrollment
        active_entry = (
            db.query(WatchlistEntry)
            .join(Watchlist, WatchlistEntry.watchlist_id == Watchlist.id)
            .filter(
                WatchlistEntry.plate_number == clean_plate,
                WatchlistEntry.is_active == True,
                Watchlist.is_active == True,
            )
            .first()
        )
        is_on_watchlist = active_entry is not None
        watchlist_category = active_entry.watchlist.category if active_entry else None

        if vehicle:
            return VehicleProfileRead(
                plate_number=vehicle.plate_number,
                vehicle_type=vehicle.vehicle_type,
                color=vehicle.color,
                first_seen_at=ensure_utc(vehicle.first_seen_at),
                last_seen_at=ensure_utc(vehicle.last_seen_at),
                total_detections=vehicle.total_detections_count,
                is_on_watchlist=is_on_watchlist,
                watchlist_category=watchlist_category,
            )

        # 3. Fallback: Check if detections exist even if Vehicle table row is missing
        detections = (
            db.query(Detection)
            .filter(Detection.plate_number == clean_plate)
            .order_by(Detection.detected_at.asc())
            .all()
        )

        if not detections:
            return None

        first_det = detections[0]
        last_det = detections[-1]

        return VehicleProfileRead(
            plate_number=clean_plate,
            vehicle_type=last_det.vehicle_type,
            color=None,
            first_seen_at=ensure_utc(first_det.detected_at),
            last_seen_at=ensure_utc(last_det.detected_at),
            total_detections=len(detections),
            is_on_watchlist=is_on_watchlist,
            watchlist_category=watchlist_category,
        )

    @classmethod
    def get_vehicle_history(
        cls,
        db: Session,
        plate_number: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        camera_id: Optional[uuid.UUID] = None,
        order: str = "asc",
        limit: int = 50,
        skip: int = 0
    ) -> Tuple[List[VehicleObservationItem], int]:
        """Query chronological observation history for a license plate.
        
        Strict Invariants:
        - Query Database, Not Video: Evaluates persisted Detection records only.
        - Primary Ordering: Observation timestamp (Detection.detected_at).
        - Secondary Ordering: Detection.id for deterministic tie-breaking.
        - Location Resolution: Follows detection -> camera -> location registry.
        - Missing Coordinates: Represented as None (NEVER fabricated 0,0).
        - No Route Inference: Reports individual observations only.
        - Indexed Execution: Utilizes idx_detections_plate_time.
        
        Returns:
            Tuple of (list of observation items, total matching count).
        """
        if not plate_number or not plate_number.strip():
            raise VehicleHistoryValidationError("Plate number must be non-empty.")

        clean_plate = plate_number.strip().upper()

        # Validate time range
        if start_time and end_time:
            s_utc = ensure_utc(start_time)
            e_utc = ensure_utc(end_time)
            if s_utc > e_utc:
                raise VehicleHistoryValidationError("start_time must be prior to end_time.")

        # Build indexed query with eager relationship loading to eliminate N+1 overhead
        query = (
            db.query(Detection)
            .options(
                joinedload(Detection.camera).joinedload(Camera.location)
            )
            .filter(Detection.plate_number == clean_plate)
        )

        if camera_id:
            query = query.filter(Detection.camera_id == camera_id)

        if start_time:
            query = query.filter(Detection.detected_at >= ensure_utc(start_time))

        if end_time:
            query = query.filter(Detection.detected_at <= ensure_utc(end_time))

        total = query.count()

        # Deterministic ordering by observation timestamp (Section 9)
        sort_desc = (order.lower() == "desc")
        if sort_desc:
            query = query.order_by(Detection.detected_at.desc(), Detection.id.desc())
        else:
            query = query.order_by(Detection.detected_at.asc(), Detection.id.asc())

        # Pagination
        paged_detections = (
            query.offset(skip)
            .limit(min(limit, 200))
            .all()
        )

        items = [cls.build_observation_item(det) for det in paged_detections]
        return items, total

    @classmethod
    def build_observation_item(cls, det: Detection) -> VehicleObservationItem:
        """Map a Detection ORM record with joined Camera and Location into VehicleObservationItem."""
        cam = det.camera
        loc = cam.location if cam else None

        # Coordinates from camera registry (Section 8 & 19: NEVER use 0,0 as placeholder)
        lat = float(loc.latitude) if (loc and loc.latitude is not None) else None
        lon = float(loc.longitude) if (loc and loc.longitude is not None) else None

        # Extract video PTS from metadata
        pts_ms = None
        if det.detection_metadata and isinstance(det.detection_metadata, dict):
            pts_ms = det.detection_metadata.get("video_pts_ms")

        return VehicleObservationItem(
            detection_id=det.id,
            camera_id=det.camera_id,
            camera_name=cam.name if cam else None,
            location_id=loc.id if loc else None,
            location_name=loc.name if loc else None,
            latitude=lat,
            longitude=lon,
            city=loc.city if loc else None,
            state=loc.state if loc else None,
            detected_at=ensure_utc(det.detected_at),
            video_pts_ms=pts_ms,
            vehicle_type=det.vehicle_type,
            confidence_vehicle=det.confidence_vehicle,
            confidence_plate=det.confidence_plate,
            plate_number=det.plate_number,
            raw_text=det.raw_text,
            snapshot_path=det.snapshot_path,
            plate_crop_path=det.plate_crop_path,
            is_demo=det.is_demo,
            detection_metadata=det.detection_metadata,
            created_at=ensure_utc(det.created_at) or ensure_utc(det.detected_at) or datetime.now(timezone.utc),
        )
