"""Real-time Alert Engine: converts Stage 9 watchlist matches into operational alerts.

Protocol Standards:
- docs/final-architecture.md Flow F (Watchlist Match -> Alert).
- docs/realtime-contract.md Section 4 (60-second suppression window).
- docs/database-design.md Domain 4 (Alerts).
- Stage 10 Directive Sections 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 19, 20.
- STRICT BOUNDARY: NO notification dispatch (SMS, email, push, WebSockets).
- STRICT PROVENANCE: Alerts bind strictly to source Detection, Camera, and WatchlistEntry.
"""

import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.app.core.config import settings
from backend.app.models.alerts import Alert
from backend.app.models.intelligence import Detection
from backend.app.models.surveillance import Camera
from backend.app.models.watchlists import WatchlistEntry
from backend.app.models.audit import AuditLog
from backend.app.models.access import User
from backend.app.schemas.watchlist import WatchlistMatchResult
from backend.app.schemas.alert import (
    AlertRead,
    AlertEngineResult,
    AlertStatus,
    AlertSeverity,
)

logger = logging.getLogger("sentinel.alert.engine")


class AlertEngineError(Exception):
    """Base exception for Alert Engine processing failures."""
    pass


class AlertProvenanceError(AlertEngineError):
    """Raised when an alert references non-existent or orphan detection, camera, or entry."""
    pass


class AlertValidationError(AlertEngineError):
    """Raised when alert data fails contract validation."""
    pass


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime has timezone set to UTC (handles SQLite naive timestamps)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def record_alert_audit_log(
    db: Session,
    user_id: Optional[uuid.UUID],
    action: str,
    alert_id: str,
    payload_summary: Optional[str] = None,
    ip_address: str = "127.0.0.1",
) -> None:
    """Record alert administrative or generation action in immutable audit log."""
    try:
        badge = "SYSTEM"
        if user_id:
            user = db.query(User).filter_by(id=user_id).first()
            if user:
                badge = user.badge_number

        log_entry = AuditLog(
            user_id=user_id,
            badge_number=badge,
            action=action,
            resource_type="ALERT",
            resource_id=str(alert_id),
            ip_address=ip_address,
            payload_summary=payload_summary,
        )
        db.add(log_entry)
        db.flush()
    except Exception as exc:
        logger.warning("Failed to record alert audit log: %s", exc)


class AlertEngine:
    """Core domain service for deterministic alert generation and deduplication."""

    @classmethod
    def check_deduplication(
        cls,
        db: Session,
        camera_id: uuid.UUID,
        plate_number: str,
        watchlist_entry_id: uuid.UUID,
        observation_time: datetime,
        window_seconds: Optional[int] = None,
    ) -> bool:
        """Evaluate 60-second alert suppression window.
        
        Rule (docs/realtime-contract.md Line 87 & docs/final-architecture.md Line 315):
        Suppresses duplicate alerts for the same plate and camera within the configured
        window (default 60 seconds) to prevent alert flooding on continuous video streams.
        
        Deduplication Identity: (camera_id, plate_number, watchlist_entry_id)
        Observation Window: [observation_time - window, observation_time + window]
        
        Returns:
            True if a qualifying prior alert exists within the window (DEDUPLICATE / SUPPRESS).
            False if no duplicate exists (QUALIFIES FOR ALERT CREATION).
        """
        win_sec = (
            window_seconds
            if window_seconds is not None
            else settings.ALERT_DEDUPLICATION_WINDOW_SECONDS
        )
        if win_sec <= 0:
            return False

        obs_utc = ensure_utc(observation_time)
        delta = timedelta(seconds=win_sec)
        min_time = obs_utc - delta
        max_time = obs_utc + delta

        # Query existing alerts matching deduplication key within observation time window
        existing = (
            db.query(Alert)
            .join(Detection, Alert.detection_id == Detection.id)
            .filter(
                Alert.camera_id == camera_id,
                Alert.plate_number == plate_number,
                Alert.watchlist_entry_id == watchlist_entry_id,
                Detection.detected_at >= min_time,
                Detection.detected_at <= max_time,
            )
            .first()
        )

        return existing is not None

    @classmethod
    def process_match(
        cls,
        db: Session,
        match: WatchlistMatchResult,
        window_seconds: Optional[int] = None,
        ip_address: str = "127.0.0.1",
    ) -> Optional[Alert]:
        """Convert a single Stage 9 WatchlistMatchResult into an Alert record.
        
        Pipeline:
        1. Provenance Verification: Verify existence of Detection, Camera, WatchlistEntry.
        2. Deduplication Check: Check 60-second window; suppress if duplicate.
        3. Alert Creation: Instantiate Alert with status="NEW", severity from match metadata.
        4. Audit Log: Record alert creation event.
        5. Atomic Commit: Commit transaction or rollback on error.
        
        Returns:
            Alert instance if created, or None if deduplicated.
        """
        # 1. Validate Provenance Existence (Section 6, 19)
        if not match.detection_id:
            raise AlertProvenanceError(
                "Cannot create alert: WatchlistMatchResult lacks a valid detection_id."
            )
        if not match.camera_id:
            raise AlertProvenanceError(
                "Cannot create alert: WatchlistMatchResult lacks a valid camera_id."
            )
        if not match.watchlist_entry_id:
            raise AlertProvenanceError(
                "Cannot create alert: WatchlistMatchResult lacks a valid watchlist_entry_id."
            )

        detection = db.query(Detection).filter(Detection.id == match.detection_id).first()
        if not detection:
            raise AlertProvenanceError(
                f"Cannot create alert: Source Detection '{match.detection_id}' does not exist in database."
            )

        camera = db.query(Camera).filter(Camera.id == match.camera_id).first()
        if not camera:
            raise AlertProvenanceError(
                f"Cannot create alert: Referenced Camera '{match.camera_id}' does not exist in registry."
            )

        entry = db.query(WatchlistEntry).filter(WatchlistEntry.id == match.watchlist_entry_id).first()
        if not entry:
            raise AlertProvenanceError(
                f"Cannot create alert: Referenced WatchlistEntry '{match.watchlist_entry_id}' does not exist."
            )

        clean_plate = match.observed_normalized_plate.strip().upper()
        obs_time = ensure_utc(detection.detected_at)

        # 2. 60-Second Deduplication Check (Section 11, 12)
        is_dup = cls.check_deduplication(
            db=db,
            camera_id=match.camera_id,
            plate_number=clean_plate,
            watchlist_entry_id=match.watchlist_entry_id,
            observation_time=obs_time,
            window_seconds=window_seconds,
        )
        if is_dup:
            logger.info(
                "Suppressed duplicate alert for plate %s on camera %s (within %ss window)",
                clean_plate,
                match.camera_id,
                window_seconds or settings.ALERT_DEDUPLICATION_WINDOW_SECONDS,
                extra={"plate": clean_plate, "camera_id": str(match.camera_id)}
            )
            return None

        # 3. Resolve Severity from Matched Watchlist Metadata (Section 9)
        # Severity is inherited deterministically from the matched watchlist container.
        valid_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
        severity = match.watchlist_severity.upper() if match.watchlist_severity else "MEDIUM"
        if severity not in valid_severities:
            severity = "MEDIUM"

        # 4. Instantiate Alert Entity (Section 8: Status default "NEW")
        alert = Alert(
            id=uuid.uuid4(),
            detection_id=detection.id,
            watchlist_entry_id=entry.id,
            camera_id=camera.id,
            plate_number=clean_plate,
            severity=severity,
            status=AlertStatus.NEW.value,
        )

        try:
            db.add(alert)
            db.flush()

            # Record audit log
            record_alert_audit_log(
                db=db,
                user_id=None,
                action="ALERT_GENERATE",
                alert_id=str(alert.id),
                payload_summary=(
                    f"Generated {severity} alert for plate {clean_plate} at camera {camera.name} "
                    f"matching watchlist '{match.watchlist_name}' (Method: {match.match_method})"
                ),
                ip_address=ip_address,
            )

            db.commit()
            db.refresh(alert)
            logger.info(
                "Created alert %s for plate %s on camera %s (Severity: %s)",
                alert.id,
                clean_plate,
                camera.id,
                severity,
                extra={"alert_id": str(alert.id), "plate": clean_plate, "camera_id": str(camera.id)}
            )
            return alert

        except Exception as exc:
            db.rollback()
            logger.error("Failed to persist alert for plate %s: %s", clean_plate, exc)
            raise AlertEngineError(f"Database transaction failure creating alert: {exc}") from exc

    @classmethod
    def process_matches(
        cls,
        db: Session,
        matches: List[WatchlistMatchResult],
        window_seconds: Optional[int] = None,
        ip_address: str = "127.0.0.1",
    ) -> AlertEngineResult:
        """Process a batch of Stage 9 WatchlistMatchResult objects.
        
        Handles multiple watchlist matches independently without arbitrary dropping.
        Returns detailed summary of created alerts and deduplicated events.
        """
        created_alerts: List[AlertRead] = []
        deduplicated_count = 0

        for match in matches:
            alert = cls.process_match(
                db=db,
                match=match,
                window_seconds=window_seconds,
                ip_address=ip_address,
            )
            if alert:
                read_dto = cls.build_alert_read_dto(alert)
                created_alerts.append(read_dto)
            else:
                deduplicated_count += 1

        return AlertEngineResult(
            alerts_created=created_alerts,
            deduplicated_count=deduplicated_count,
            total_matches_evaluated=len(matches),
        )

    @classmethod
    def build_alert_read_dto(cls, alert: Alert) -> AlertRead:
        """Map ORM Alert model with joined Detection, Camera, and Entry into AlertRead DTO."""
        det = alert.detection
        entry = alert.watchlist_entry
        wl = entry.watchlist if entry else None
        cam = det.camera if det else None

        pts_ms = None
        if det and isinstance(det.detection_metadata, dict):
            pts_ms = det.detection_metadata.get("video_pts_ms")

        return AlertRead(
            id=alert.id,
            detection_id=alert.detection_id,
            watchlist_entry_id=alert.watchlist_entry_id,
            camera_id=alert.camera_id,
            camera_name=cam.name if cam else None,
            plate_number=alert.plate_number,
            severity=alert.severity,
            status=alert.status,
            acknowledged_by_user_id=alert.acknowledged_by_user_id,
            acknowledged_at=alert.acknowledged_at,
            resolution_notes=alert.resolution_notes,
            created_at=alert.created_at,
            observed_at=det.detected_at if det else None,
            video_pts_ms=pts_ms,
            is_demo=det.is_demo if det else False,
            raw_text=det.raw_text if det else None,
            snapshot_path=det.snapshot_path if det else None,
            watchlist_id=wl.id if wl else None,
            watchlist_name=wl.name if wl else None,
            watchlist_category=wl.category if wl else None,
            vehicle_make_model=entry.vehicle_make_model if entry else None,
            fir_number=entry.fir_number if entry else None,
        )
