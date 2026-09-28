"""Alert query and lifecycle management service (acknowledgment, disposition, audit).

Protocol Standards:
- docs/api-contract.md Section 9.
- docs/database-design.md Domain 4 (Alerts).
- Stage 10 Directive Sections 8, 16, 17, 18, 24.
- Mandatory audit logging on acknowledgment and disposition.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from backend.app.models.alerts import Alert
from backend.app.models.access import User
from backend.app.schemas.alert import AlertStatus, AlertSeverity
from backend.app.services.alert.engine import (
    AlertEngine,
    record_alert_audit_log,
    AlertEngineError,
)
from backend.app.services.watchlist.service import get_or_create_system_user

logger = logging.getLogger("sentinel.alert.service")


class AlertNotFoundError(AlertEngineError):
    """Raised when an alert ID is not found in database."""
    pass


class AlertLifecycleError(AlertEngineError):
    """Raised when an alert status transition is invalid."""
    pass


class AlertService:
    """Domain service managing operational alert lifecycle and queries."""

    # ------------------------------------------------------------------------
    # Query Operations
    # ------------------------------------------------------------------------

    @classmethod
    def get_alert(cls, db: Session, alert_id: uuid.UUID) -> Optional[Alert]:
        """Retrieve an operational alert by UUID."""
        return db.query(Alert).filter(Alert.id == alert_id).first()

    @classmethod
    def list_alerts(
        cls,
        db: Session,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        camera_id: Optional[uuid.UUID] = None,
        plate_number: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
        skip: int = 0
    ) -> Tuple[List[Alert], int]:
        """Search and filter alerts utilizing database indexes.
        
        Indexes Utilized:
        - idx_alerts_status_created on (status, created_at)
        - idx_alerts_plate on (plate_number)
        - idx_alerts_camera on (camera_id)
        """
        query = db.query(Alert)

        if status:
            query = query.filter(Alert.status == status.upper())

        if severity:
            query = query.filter(Alert.severity == severity.upper())

        if camera_id:
            query = query.filter(Alert.camera_id == camera_id)

        if plate_number:
            clean = plate_number.strip().upper()
            if "%" in clean or "_" in clean:
                query = query.filter(Alert.plate_number.like(clean))
            else:
                query = query.filter(Alert.plate_number == clean)

        if start_time:
            query = query.filter(Alert.created_at >= start_time)

        if end_time:
            query = query.filter(Alert.created_at <= end_time)

        total = query.count()
        items = (
            query.order_by(Alert.created_at.desc())
            .offset(skip)
            .limit(min(limit, 200))
            .all()
        )
        return items, total

    # ------------------------------------------------------------------------
    # Lifecycle Operations
    # ------------------------------------------------------------------------

    @classmethod
    def acknowledge_alert(
        cls,
        db: Session,
        alert_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        resolution_notes: Optional[str] = None,
        ip_address: str = "127.0.0.1",
    ) -> Alert:
        """Acknowledge and claim an alert by a responding police officer (docs/api-contract.md)."""
        alert = cls.get_alert(db, alert_id)
        if not alert:
            raise AlertNotFoundError(f"Alert '{alert_id}' not found.")

        # Resolve user
        resolved_user_id = user_id
        if not resolved_user_id:
            sys_user = get_or_create_system_user(db)
            resolved_user_id = sys_user.id
        else:
            user_exists = db.query(User).filter_by(id=resolved_user_id).first()
            if not user_exists:
                raise AlertLifecycleError(f"User with ID '{resolved_user_id}' does not exist.")

        alert.status = AlertStatus.ACKNOWLEDGED.value
        alert.acknowledged_by_user_id = resolved_user_id
        alert.acknowledged_at = datetime.now(timezone.utc)

        if resolution_notes:
            existing_notes = alert.resolution_notes or ""
            timestamp_tag = f"[{alert.acknowledged_at.isoformat()}]"
            new_note = f"{timestamp_tag} ACKNOWLEDGED: {resolution_notes.strip()}"
            alert.resolution_notes = f"{existing_notes}\n{new_note}".strip()

        db.flush()

        record_alert_audit_log(
            db=db,
            user_id=resolved_user_id,
            action="ALERT_ACKNOWLEDGE",
            alert_id=str(alert.id),
            payload_summary=(
                f"Acknowledged {alert.severity} alert for plate {alert.plate_number}. "
                f"Notes: {resolution_notes or 'None'}"
            ),
            ip_address=ip_address,
        )

        db.commit()
        db.refresh(alert)
        return alert

    @classmethod
    def update_alert_status(
        cls,
        db: Session,
        alert_id: uuid.UUID,
        new_status: AlertStatus,
        resolution_notes: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1",
    ) -> Alert:
        """Update operational disposition of an alert (e.g. RESOLVED, DISMISSED)."""
        alert = cls.get_alert(db, alert_id)
        if not alert:
            raise AlertNotFoundError(f"Alert '{alert_id}' not found.")

        # Transition validation
        target_val = new_status.value if hasattr(new_status, "value") else str(new_status)
        if alert.status in (AlertStatus.RESOLVED.value, AlertStatus.DISMISSED.value):
            if target_val == AlertStatus.NEW.value:
                raise AlertLifecycleError(
                    f"Cannot reopen {alert.status} alert back to NEW state."
                )

        # Resolve user
        resolved_user_id = user_id
        if not resolved_user_id:
            sys_user = get_or_create_system_user(db)
            resolved_user_id = sys_user.id

        now = datetime.now(timezone.utc)
        prev_status = alert.status
        alert.status = target_val

        if target_val == AlertStatus.ACKNOWLEDGED.value and not alert.acknowledged_at:
            alert.acknowledged_at = now
            alert.acknowledged_by_user_id = resolved_user_id

        if resolution_notes:
            existing_notes = alert.resolution_notes or ""
            timestamp_tag = f"[{now.isoformat()}]"
            new_note = f"{timestamp_tag} STATUS_CHANGE ({prev_status} -> {target_val}): {resolution_notes.strip()}"
            alert.resolution_notes = f"{existing_notes}\n{new_note}".strip()

        db.flush()

        record_alert_audit_log(
            db=db,
            user_id=resolved_user_id,
            action=f"ALERT_{target_val}",
            alert_id=str(alert.id),
            payload_summary=(
                f"Transitioned alert status from {prev_status} to {target_val}. "
                f"Notes: {resolution_notes or 'None'}"
            ),
            ip_address=ip_address,
        )

        db.commit()
        db.refresh(alert)
        return alert
