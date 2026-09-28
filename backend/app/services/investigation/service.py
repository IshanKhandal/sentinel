"""Domain service implementing Sentinel Stage 13 Investigation Engine.

Protocol Standards:
- docs/engineering-rules.md (Rule 23, 24, 25, 36).
- docs/database-design.md Domain 5 (investigations, investigation_events, evidence).
- Stage 13 Directive Sections 1-28.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError

from backend.app.models.investigation import Investigation, InvestigationEvent, Evidence
from backend.app.models.intelligence import Detection
from backend.app.models.alerts import Alert
from backend.app.models.access import User, Department, Role
from backend.app.models.audit import AuditLog
from backend.app.schemas.investigation import (
    InvestigationCreate,
    InvestigationUpdate,
    InvestigationRead,
    InvestigationEventCreate,
    InvestigationEventRead,
    EvidenceCreate,
    EvidenceRead,
    VALID_STATUS_TRANSITIONS,
    INVESTIGATION_STATUS_OPEN,
)
from backend.app.services.correlation import (
    CorrelationService,
    DEFAULT_MAX_SPEED_THRESHOLD_KMH,
)

logger = logging.getLogger(__name__)


class InvestigationServiceError(Exception):
    """Base exception for investigation operations."""
    pass


class InvestigationNotFoundError(InvestigationServiceError):
    """Raised when an investigation UUID is not found."""
    pass


class InvestigationValidationError(InvestigationServiceError):
    """Raised when investigation data or status transition fails validation."""
    pass


class InvestigationDuplicateError(InvestigationServiceError):
    """Raised when creating an investigation with an existing case number."""
    pass


class InvestigationEventDuplicateError(InvestigationServiceError):
    """Raised when attempting to attach an event already present in the investigation."""
    pass


class InvestigationEventNotFoundError(InvestigationServiceError):
    """Raised when an investigation event record is not found."""
    pass


class ReferencedEntityNotFoundError(InvestigationServiceError):
    """Raised when a referenced detection or alert does not exist in the database."""
    pass


def get_or_create_system_user(db: Session) -> User:
    """Resolve an existing user or initialize a default system operator.
    
    Ensures referential integrity for lead_detective_id without requiring
    an active RBAC session during automated testing or initial prototype execution.
    """
    user = db.query(User).first()
    if user:
        return user

    dept = db.query(Department).filter_by(code="SYS_ADMIN").first()
    if not dept:
        dept = Department(
            id=uuid.uuid4(),
            name="State Police Surveillance HQ",
            code="SYS_ADMIN"
        )
        db.add(dept)
        db.flush()

    role = db.query(Role).filter_by(name="Investigator").first()
    if not role:
        role = Role(
            id=uuid.uuid4(),
            name="Investigator",
            description="Police Investigation Officer Role"
        )
        db.add(role)
        db.flush()

    system_user = User(
        id=uuid.uuid4(),
        department_id=dept.id,
        role_id=role.id,
        badge_number="INV001",
        full_name="Lead Investigative Officer",
        email="detective@sentinel.internal",
        hashed_password="system_internal_placeholder_hash",
        is_active=True
    )
    db.add(system_user)
    db.commit()
    db.refresh(system_user)
    return system_user


def _record_audit_log(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    ip_address: str = "127.0.0.1",
    payload_summary: Optional[str] = None,
) -> None:
    """Append immutable audit log entry for investigation operations."""
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
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            payload_summary=payload_summary,
        )
        db.add(log_entry)
        db.flush()
    except Exception as exc:
        logger.warning("Failed to record audit log: %s", exc)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class InvestigationService:
    """Domain service for managing police investigation cases, attached events, and evidence metadata."""

    # ------------------------------------------------------------------------
    # 1. Investigation Lifecycle & CRUD
    # ------------------------------------------------------------------------

    @staticmethod
    def create_investigation(
        db: Session,
        data: InvestigationCreate,
        operator_user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1",
    ) -> Investigation:
        """Create a new police investigation case file."""
        # Uniqueness check on case_number
        existing = db.query(Investigation).filter_by(case_number=data.case_number).first()
        if existing:
            raise InvestigationDuplicateError(
                f"Investigation with case number '{data.case_number}' already exists."
            )

        # Resolve lead detective
        lead_id = data.lead_detective_id or operator_user_id
        if lead_id:
            lead_user = db.query(User).filter_by(id=lead_id).first()
            if not lead_user:
                lead_user = get_or_create_system_user(db)
                lead_id = lead_user.id
        else:
            lead_user = get_or_create_system_user(db)
            lead_id = lead_user.id

        inv = Investigation(
            id=uuid.uuid4(),
            case_number=data.case_number,
            title=data.title,
            description=data.description,
            target_plate=data.target_plate,
            status=INVESTIGATION_STATUS_OPEN,
            lead_detective_id=lead_id,
        )

        try:
            db.add(inv)
            db.flush()

            _record_audit_log(
                db=db,
                action="INVESTIGATION_CREATE",
                resource_type="INVESTIGATION",
                resource_id=str(inv.id),
                user_id=lead_id,
                ip_address=ip_address,
                payload_summary=f"Case: {inv.case_number}, Title: {inv.title}, Plate: {inv.target_plate}",
            )

            db.commit()
            db.refresh(inv)
            return inv
        except IntegrityError as exc:
            db.rollback()
            raise InvestigationDuplicateError(
                f"Integrity violation creating case '{data.case_number}': {exc}"
            )
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_investigation_entity(
        db: Session,
        investigation_id: uuid.UUID,
    ) -> Investigation:
        """Retrieve an Investigation model with relationships eagerly loaded."""
        inv = (
            db.query(Investigation)
            .options(
                joinedload(Investigation.events).joinedload(InvestigationEvent.detection),
                joinedload(Investigation.events).joinedload(InvestigationEvent.alert),
                joinedload(Investigation.evidence_items),
            )
            .filter_by(id=investigation_id)
            .first()
        )
        if not inv:
            raise InvestigationNotFoundError(
                f"Investigation case '{investigation_id}' does not exist."
            )
        return inv

    @classmethod
    def get_investigation(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
    ) -> InvestigationRead:
        """Retrieve investigation case details serialized with deterministic event ordering."""
        inv = cls.get_investigation_entity(db, investigation_id)
        return cls._serialize_investigation(inv)

    @classmethod
    def list_investigations(
        cls,
        db: Session,
        status: Optional[str] = None,
        target_plate: Optional[str] = None,
        case_number: Optional[str] = None,
        limit: int = 50,
        skip: int = 0,
    ) -> Tuple[List[InvestigationRead], int]:
        """List and search investigations with filtering and pagination."""
        query = db.query(Investigation)

        if status:
            clean_status = status.strip().upper()
            query = query.filter(Investigation.status == clean_status)

        if target_plate:
            clean_plate = target_plate.strip().upper()
            query = query.filter(Investigation.target_plate == clean_plate)

        if case_number:
            clean_case = case_number.strip()
            query = query.filter(Investigation.case_number.ilike(f"%{clean_case}%"))

        total = query.count()
        results = (
            query.options(
                joinedload(Investigation.events).joinedload(InvestigationEvent.detection),
                joinedload(Investigation.events).joinedload(InvestigationEvent.alert),
                joinedload(Investigation.evidence_items),
            )
            .order_by(Investigation.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        serialized = [cls._serialize_investigation(inv) for inv in results]
        return serialized, total

    @classmethod
    def update_investigation(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        data: InvestigationUpdate,
        operator_user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1",
    ) -> InvestigationRead:
        """Update case metadata or progress lifecycle status."""
        inv = cls.get_investigation_entity(db, investigation_id)

        # Validate lifecycle status transition
        if data.status and data.status != inv.status:
            allowed = VALID_STATUS_TRANSITIONS.get(inv.status, set())
            if data.status not in allowed:
                raise InvestigationValidationError(
                    f"Illegal status transition from '{inv.status}' to '{data.status}'. Allowed: {sorted(allowed)}"
                )

            old_status = inv.status
            inv.status = data.status

            _record_audit_log(
                db=db,
                action="INVESTIGATION_STATUS_CHANGE",
                resource_type="INVESTIGATION",
                resource_id=str(inv.id),
                user_id=operator_user_id or inv.lead_detective_id,
                ip_address=ip_address,
                payload_summary=f"Status changed from {old_status} to {inv.status}",
            )

        if data.title is not None:
            inv.title = data.title
        if data.description is not None:
            inv.description = data.description
        if data.target_plate is not None:
            inv.target_plate = data.target_plate
        if data.lead_detective_id is not None:
            lead_user = db.query(User).filter_by(id=data.lead_detective_id).first()
            if not lead_user:
                raise ReferencedEntityNotFoundError(
                    f"User '{data.lead_detective_id}' not found in user registry."
                )
            inv.lead_detective_id = data.lead_detective_id

        try:
            _record_audit_log(
                db=db,
                action="INVESTIGATION_UPDATE",
                resource_type="INVESTIGATION",
                resource_id=str(inv.id),
                user_id=operator_user_id or inv.lead_detective_id,
                ip_address=ip_address,
                payload_summary=f"Updated investigation {inv.case_number}",
            )
            db.commit()
            db.refresh(inv)
            return cls._serialize_investigation(inv)
        except Exception:
            db.rollback()
            raise

    # ------------------------------------------------------------------------
    # 2. Event Attachment & Ordering
    # ------------------------------------------------------------------------

    @classmethod
    def attach_event(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        data: InvestigationEventCreate,
        operator_user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1",
    ) -> InvestigationEventRead:
        """Attach a verified detection or operational alert to the investigation case."""
        inv = cls.get_investigation_entity(db, investigation_id)

        # Validate detection reference
        if data.detection_id:
            detection = db.query(Detection).filter_by(id=data.detection_id).first()
            if not detection:
                raise ReferencedEntityNotFoundError(
                    f"Detection '{data.detection_id}' does not exist."
                )
            # Duplicate check
            existing_det = (
                db.query(InvestigationEvent)
                .filter_by(investigation_id=inv.id, detection_id=data.detection_id)
                .first()
            )
            if existing_det:
                raise InvestigationEventDuplicateError(
                    f"Detection '{data.detection_id}' is already attached to investigation '{inv.case_number}'."
                )

        # Validate alert reference
        if data.alert_id:
            alert = db.query(Alert).filter_by(id=data.alert_id).first()
            if not alert:
                raise ReferencedEntityNotFoundError(
                    f"Alert '{data.alert_id}' does not exist."
                )
            # Duplicate check
            existing_alert = (
                db.query(InvestigationEvent)
                .filter_by(investigation_id=inv.id, alert_id=data.alert_id)
                .first()
            )
            if existing_alert:
                raise InvestigationEventDuplicateError(
                    f"Alert '{data.alert_id}' is already attached to investigation '{inv.case_number}'."
                )

        # Compute next sequence order monotonically
        max_seq = (
            db.query(func.max(InvestigationEvent.sequence_order))
            .filter_by(investigation_id=inv.id)
            .scalar()
        )
        sequence_order = (max_seq or 0) + 1

        inv_event = InvestigationEvent(
            id=uuid.uuid4(),
            investigation_id=inv.id,
            detection_id=data.detection_id,
            alert_id=data.alert_id,
            sequence_order=sequence_order,
            notes=data.notes,
        )

        try:
            db.add(inv_event)
            db.flush()

            ref_desc = f"detection={data.detection_id}" if data.detection_id else f"alert={data.alert_id}"
            _record_audit_log(
                db=db,
                action="INVESTIGATION_EVENT_ATTACH",
                resource_type="INVESTIGATION",
                resource_id=str(inv.id),
                user_id=operator_user_id or inv.lead_detective_id,
                ip_address=ip_address,
                payload_summary=f"Attached {ref_desc} (seq: {sequence_order})",
            )

            db.commit()
            db.refresh(inv_event)
            return cls._serialize_event(inv_event)
        except Exception:
            db.rollback()
            raise

    @classmethod
    def attach_vehicle_history(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        detection_ids: Optional[List[uuid.UUID]] = None,
        notes: Optional[str] = None,
        operator_user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1",
    ) -> List[InvestigationEventRead]:
        """Attach historical observations for the case's target plate or specific detection UUIDs."""
        inv = cls.get_investigation_entity(db, investigation_id)

        target_detections: List[Detection] = []

        if detection_ids:
            for det_id in detection_ids:
                d = db.query(Detection).filter_by(id=det_id).first()
                if not d:
                    raise ReferencedEntityNotFoundError(f"Detection '{det_id}' not found.")
                target_detections.append(d)
        else:
            if not inv.target_plate:
                raise InvestigationValidationError(
                    "Investigation has no target_plate specified. Provide explicit detection_ids."
                )
            target_detections = (
                db.query(Detection)
                .filter_by(plate_number=inv.target_plate)
                .order_by(Detection.detected_at.asc(), Detection.id.asc())
                .all()
            )

        attached_events: List[InvestigationEventRead] = []
        for det in target_detections:
            # Skip if already attached
            existing = (
                db.query(InvestigationEvent)
                .filter_by(investigation_id=inv.id, detection_id=det.id)
                .first()
            )
            if existing:
                continue

            event_read = cls.attach_event(
                db=db,
                investigation_id=inv.id,
                data=InvestigationEventCreate(
                    detection_id=det.id,
                    notes=notes or f"Attached from historical sighting of {det.plate_number}",
                ),
                operator_user_id=operator_user_id,
                ip_address=ip_address,
            )
            attached_events.append(event_read)

        return attached_events

    @classmethod
    def detach_event(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        event_id: uuid.UUID,
        operator_user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1",
    ) -> None:
        """Detach an event record from an active investigation case."""
        inv = cls.get_investigation_entity(db, investigation_id)

        event = (
            db.query(InvestigationEvent)
            .filter_by(id=event_id, investigation_id=inv.id)
            .first()
        )
        if not event:
            raise InvestigationEventNotFoundError(
                f"Investigation event '{event_id}' not found in case '{inv.case_number}'."
            )

        try:
            db.delete(event)
            _record_audit_log(
                db=db,
                action="INVESTIGATION_EVENT_DETACH",
                resource_type="INVESTIGATION",
                resource_id=str(inv.id),
                user_id=operator_user_id or inv.lead_detective_id,
                ip_address=ip_address,
                payload_summary=f"Detached event {event_id}",
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

    @classmethod
    def get_investigation_events(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
    ) -> List[InvestigationEventRead]:
        """Retrieve all events attached to an investigation ordered deterministically."""
        inv = cls.get_investigation_entity(db, investigation_id)
        events = (
            db.query(InvestigationEvent)
            .options(
                joinedload(InvestigationEvent.detection),
                joinedload(InvestigationEvent.alert),
            )
            .filter_by(investigation_id=inv.id)
            .order_by(InvestigationEvent.sequence_order.asc())
            .all()
        )
        return [cls._serialize_event(e) for e in events]

    # ------------------------------------------------------------------------
    # 3. Evidence Metadata Management (Section 15, 16)
    # ------------------------------------------------------------------------

    @classmethod
    def attach_evidence(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        data: EvidenceCreate,
        operator_user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1",
    ) -> EvidenceRead:
        """Attach verified forensic evidence metadata with cryptographic SHA-256 hash."""
        inv = cls.get_investigation_entity(db, investigation_id)

        user_id = data.generated_by_user_id or operator_user_id
        if user_id:
            user = db.query(User).filter_by(id=user_id).first()
            if not user:
                user = get_or_create_system_user(db)
                user_id = user.id
        else:
            user = get_or_create_system_user(db)
            user_id = user.id

        evidence = Evidence(
            id=uuid.uuid4(),
            investigation_id=inv.id,
            file_path=data.file_path,
            file_type=data.file_type,
            sha256_hash=data.sha256_hash,
            file_size_bytes=data.file_size_bytes,
            generated_by_user_id=user_id,
        )

        try:
            db.add(evidence)
            db.flush()

            _record_audit_log(
                db=db,
                action="INVESTIGATION_EVIDENCE_ATTACH",
                resource_type="INVESTIGATION",
                resource_id=str(inv.id),
                user_id=user_id,
                ip_address=ip_address,
                payload_summary=f"Attached evidence {evidence.file_type}: {evidence.sha256_hash[:16]}... ({evidence.file_size_bytes} bytes)",
            )

            db.commit()
            db.refresh(evidence)
            return EvidenceRead.model_validate(evidence)
        except Exception:
            db.rollback()
            raise

    @classmethod
    def list_evidence(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
    ) -> List[EvidenceRead]:
        """List all registered forensic evidence records for an investigation."""
        inv = cls.get_investigation_entity(db, investigation_id)
        evidence_items = (
            db.query(Evidence)
            .filter_by(investigation_id=inv.id)
            .order_by(Evidence.created_at.asc())
            .all()
        )
        return [EvidenceRead.model_validate(item) for item in evidence_items]

    # ------------------------------------------------------------------------
    # 4. Cross-Camera Correlation Integration (Stage 12 Output Consumption)
    # ------------------------------------------------------------------------

    @classmethod
    def get_investigation_correlation(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        max_speed_kmh: Optional[float] = None,
    ):
        """Retrieve Stage 12 cross-camera correlation for the investigation's target plate.
        
        Directly consumes the Stage 12 CorrelationService without recalculating
        or duplicating spatial algorithms inside the investigation engine.
        """
        inv = cls.get_investigation_entity(db, investigation_id)
        if not inv.target_plate:
            raise InvestigationValidationError(
                f"Investigation '{inv.case_number}' has no target_plate configured for correlation."
            )

        speed_threshold = max_speed_kmh if max_speed_kmh is not None else DEFAULT_MAX_SPEED_THRESHOLD_KMH
        return CorrelationService.correlate_vehicle_journey(
            db=db,
            plate_number=inv.target_plate,
            start_time=start_time,
            end_time=end_time,
            max_speed_threshold_kmh=speed_threshold,
        )

    # ------------------------------------------------------------------------
    # 5. Serialization & Provenance Helpers
    # ------------------------------------------------------------------------

    @classmethod
    def _serialize_event(cls, e: InvestigationEvent) -> InvestigationEventRead:
        obs_time: Optional[datetime] = None
        plate: Optional[str] = None
        cam_id: Optional[uuid.UUID] = None
        is_demo: bool = False

        if e.detection:
            obs_time = _ensure_utc(e.detection.detected_at)
            plate = e.detection.plate_number
            cam_id = e.detection.camera_id
            is_demo = e.detection.is_demo
        elif e.alert:
            obs_time = _ensure_utc(e.alert.created_at)
            plate = e.alert.plate_number
            cam_id = e.alert.camera_id
            # Determine is_demo if linked detection exists on alert
            if getattr(e.alert, "detection", None):
                is_demo = e.alert.detection.is_demo

        return InvestigationEventRead(
            id=e.id,
            investigation_id=e.investigation_id,
            detection_id=e.detection_id,
            alert_id=e.alert_id,
            sequence_order=e.sequence_order,
            notes=e.notes,
            added_at=_ensure_utc(e.added_at),
            observation_timestamp=obs_time,
            plate_number=plate,
            camera_id=cam_id,
            is_demo=is_demo,
        )

    @classmethod
    def _serialize_investigation(cls, inv: Investigation) -> InvestigationRead:
        events_serialized = [cls._serialize_event(e) for e in (inv.events or [])]
        # Order events deterministically: observation_timestamp ASC (if known) or added_at, then sequence_order
        events_serialized.sort(
            key=lambda ev: (
                ev.observation_timestamp or ev.added_at,
                ev.sequence_order,
            )
        )

        evidence_serialized = [EvidenceRead.model_validate(item) for item in (inv.evidence_items or [])]

        return InvestigationRead(
            id=inv.id,
            case_number=inv.case_number,
            title=inv.title,
            description=inv.description,
            target_plate=inv.target_plate,
            status=inv.status,
            lead_detective_id=inv.lead_detective_id,
            created_at=_ensure_utc(inv.created_at),
            updated_at=_ensure_utc(inv.updated_at),
            event_count=len(events_serialized),
            evidence_count=len(evidence_serialized),
            events=events_serialized,
            evidence_items=evidence_serialized,
        )
