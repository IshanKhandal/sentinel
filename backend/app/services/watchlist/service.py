"""Watchlist and WatchlistEntry management service (CRUD, validation, and audit).

Protocol Standards:
- docs/database-design.md Domain 4 (Watchlists).
- docs/api-contract.md Section 8.
- Stage 9 Directive Sections 7, 14, 17, 18, 23, 24.
- Deterministic plate sanitization on enrollment.
- UniqueConstraint enforcement per watchlist.
- Audit log emission for administrative actions.
"""

import uuid
import logging
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.app.models.watchlists import Watchlist, WatchlistEntry
from backend.app.models.access import User, Department, Role
from backend.app.models.audit import AuditLog
from backend.app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistUpdate,
    WatchlistEntryCreate,
    WatchlistEntryUpdate,
)
from backend.app.services.watchlist.matcher import clean_plate_text

logger = logging.getLogger("sentinel.watchlist.service")


class WatchlistServiceError(Exception):
    """Base exception for watchlist domain service errors."""
    pass


class WatchlistNotFoundError(WatchlistServiceError):
    """Raised when a referenced watchlist ID does not exist."""
    pass


class WatchlistDuplicateError(WatchlistServiceError):
    """Raised when creating a watchlist with a duplicate title."""
    pass


class WatchlistEntryDuplicateError(WatchlistServiceError):
    """Raised when enrolling a license plate already present in the target watchlist."""
    pass


class WatchlistValidationError(WatchlistServiceError):
    """Raised when watchlist or entry data fails business validation."""
    pass


def get_or_create_system_user(db: Session) -> User:
    """Resolve an existing user or initialize a default system operator.
    
    Ensures referential integrity for created_by_user_id without requiring
    an active RBAC session during automated testing or initial prototype execution.
    """
    user = db.query(User).first()
    if user:
        return user

    # Ensure system department exists
    dept = db.query(Department).filter_by(code="SYS_ADMIN").first()
    if not dept:
        dept = Department(
            id=uuid.uuid4(),
            name="State Police Surveillance HQ",
            code="SYS_ADMIN"
        )
        db.add(dept)
        db.flush()

    # Ensure system role exists
    role = db.query(Role).filter_by(name="SuperAdmin").first()
    if not role:
        role = Role(
            id=uuid.uuid4(),
            name="SuperAdmin",
            description="System Master Administrative Role"
        )
        db.add(role)
        db.flush()

    system_user = User(
        id=uuid.uuid4(),
        department_id=dept.id,
        role_id=role.id,
        badge_number="SYS001",
        full_name="Sentinel System Administrator",
        email="admin@sentinel.internal",
        hashed_password="system_internal_placeholder_hash",
        is_active=True
    )
    db.add(system_user)
    db.commit()
    db.refresh(system_user)
    return system_user


def _record_audit_log(
    db: Session,
    user_id: Optional[uuid.UUID],
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    payload_summary: Optional[str] = None,
    ip_address: str = "127.0.0.1",
) -> None:
    """Record administrative mutation in immutable audit log."""
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


class WatchlistService:
    """Domain service for Watchlist and WatchlistEntry CRUD operations."""

    # ------------------------------------------------------------------------
    # Watchlist Operations
    # ------------------------------------------------------------------------

    @classmethod
    def create_watchlist(
        cls,
        db: Session,
        data: WatchlistCreate,
        ip_address: str = "127.0.0.1"
    ) -> Watchlist:
        """Create a new watchlist hotlist container."""
        # Check uniqueness of name
        existing = db.query(Watchlist).filter(Watchlist.name == data.name).first()
        if existing:
            raise WatchlistDuplicateError(f"Watchlist with name '{data.name}' already exists.")

        # Resolve enrolling user
        user_id = data.created_by_user_id
        if not user_id:
            sys_user = get_or_create_system_user(db)
            user_id = sys_user.id
        else:
            user_exists = db.query(User).filter_by(id=user_id).first()
            if not user_exists:
                raise WatchlistValidationError(f"User with ID '{user_id}' does not exist.")

        wl = Watchlist(
            id=uuid.uuid4(),
            name=data.name.strip(),
            category=data.category.value if hasattr(data.category, "value") else str(data.category),
            severity=data.severity.value if hasattr(data.severity, "value") else str(data.severity),
            is_active=data.is_active,
            created_by_user_id=user_id,
        )

        try:
            db.add(wl)
            db.commit()
            db.refresh(wl)
        except IntegrityError as exc:
            db.rollback()
            raise WatchlistDuplicateError(f"Watchlist with name '{data.name}' already exists.") from exc

        _record_audit_log(
            db=db,
            user_id=user_id,
            action="WATCHLIST_CREATE",
            resource_type="WATCHLIST",
            resource_id=str(wl.id),
            payload_summary=f"Created watchlist '{wl.name}' (Category: {wl.category}, Severity: {wl.severity})",
            ip_address=ip_address,
        )
        db.commit()
        return wl

    @classmethod
    def get_watchlist(cls, db: Session, watchlist_id: uuid.UUID) -> Optional[Watchlist]:
        """Retrieve a watchlist by UUID."""
        return db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()

    @classmethod
    def list_watchlists(
        cls,
        db: Session,
        is_active: Optional[bool] = None,
        category: Optional[str] = None,
        limit: int = 50,
        skip: int = 0
    ) -> Tuple[List[Watchlist], int]:
        """List watchlists with optional active and category filtering."""
        query = db.query(Watchlist)
        if is_active is not None:
            query = query.filter(Watchlist.is_active == is_active)
        if category:
            query = query.filter(Watchlist.category == category.upper())

        total = query.count()
        items = query.order_by(Watchlist.created_at.desc()).offset(skip).limit(limit).all()
        return items, total

    @classmethod
    def update_watchlist(
        cls,
        db: Session,
        watchlist_id: uuid.UUID,
        data: WatchlistUpdate,
        user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1"
    ) -> Watchlist:
        """Update an existing watchlist hotlist."""
        wl = cls.get_watchlist(db, watchlist_id)
        if not wl:
            raise WatchlistNotFoundError(f"Watchlist '{watchlist_id}' not found.")

        if data.name is not None:
            existing = db.query(Watchlist).filter(
                Watchlist.name == data.name.strip(),
                Watchlist.id != watchlist_id
            ).first()
            if existing:
                raise WatchlistDuplicateError(f"Watchlist with name '{data.name}' already exists.")
            wl.name = data.name.strip()

        if data.category is not None:
            wl.category = data.category.value if hasattr(data.category, "value") else str(data.category)

        if data.severity is not None:
            wl.severity = data.severity.value if hasattr(data.severity, "value") else str(data.severity)

        if data.is_active is not None:
            wl.is_active = data.is_active

        db.commit()
        db.refresh(wl)

        _record_audit_log(
            db=db,
            user_id=user_id or wl.created_by_user_id,
            action="WATCHLIST_UPDATE",
            resource_type="WATCHLIST",
            resource_id=str(wl.id),
            payload_summary=f"Updated watchlist '{wl.name}' (Active: {wl.is_active})",
            ip_address=ip_address,
        )
        db.commit()
        return wl

    @classmethod
    def delete_watchlist(
        cls,
        db: Session,
        watchlist_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1"
    ) -> bool:
        """Delete a watchlist and its cascading enrolled entries."""
        wl = cls.get_watchlist(db, watchlist_id)
        if not wl:
            raise WatchlistNotFoundError(f"Watchlist '{watchlist_id}' not found.")

        wl_name = wl.name
        db.delete(wl)
        db.commit()

        _record_audit_log(
            db=db,
            user_id=user_id,
            action="WATCHLIST_DELETE",
            resource_type="WATCHLIST",
            resource_id=str(watchlist_id),
            payload_summary=f"Deleted watchlist '{wl_name}' and all associated entries",
            ip_address=ip_address,
        )
        db.commit()
        return True

    # ------------------------------------------------------------------------
    # Watchlist Entry Operations
    # ------------------------------------------------------------------------

    @classmethod
    def enroll_plate(
        cls,
        db: Session,
        watchlist_id: uuid.UUID,
        data: WatchlistEntryCreate,
        user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1"
    ) -> WatchlistEntry:
        """Enroll a target license plate onto a police watchlist."""
        wl = cls.get_watchlist(db, watchlist_id)
        if not wl:
            raise WatchlistNotFoundError(f"Watchlist '{watchlist_id}' not found.")

        clean_plate = clean_plate_text(data.plate_number)
        if not clean_plate:
            raise WatchlistValidationError("plate_number must contain at least one alphanumeric character.")

        # Check unique constraint per (watchlist_id, plate_number)
        existing = db.query(WatchlistEntry).filter(
            WatchlistEntry.watchlist_id == watchlist_id,
            WatchlistEntry.plate_number == clean_plate
        ).first()

        if existing:
            raise WatchlistEntryDuplicateError(
                f"Plate '{clean_plate}' is already enrolled in watchlist '{wl.name}'."
            )

        entry = WatchlistEntry(
            id=uuid.uuid4(),
            watchlist_id=watchlist_id,
            plate_number=clean_plate,
            vehicle_make_model=data.vehicle_make_model.strip() if data.vehicle_make_model else None,
            fir_number=data.fir_number.strip() if data.fir_number else None,
            notes=data.notes.strip() if data.notes else None,
            is_active=data.is_active,
        )

        try:
            db.add(entry)
            db.commit()
            db.refresh(entry)
        except IntegrityError as exc:
            db.rollback()
            raise WatchlistEntryDuplicateError(
                f"Plate '{clean_plate}' is already enrolled in watchlist '{wl.name}'."
            ) from exc

        _record_audit_log(
            db=db,
            user_id=user_id or wl.created_by_user_id,
            action="WATCHLIST_ENTRY_ADD",
            resource_type="WATCHLIST_ENTRY",
            resource_id=str(entry.id),
            payload_summary=f"Enrolled plate '{clean_plate}' onto watchlist '{wl.name}' (FIR: {entry.fir_number})",
            ip_address=ip_address,
        )
        db.commit()
        return entry

    @classmethod
    def get_entry(cls, db: Session, entry_id: uuid.UUID) -> Optional[WatchlistEntry]:
        """Retrieve a specific watchlist entry by UUID."""
        return db.query(WatchlistEntry).filter(WatchlistEntry.id == entry_id).first()

    @classmethod
    def list_entries(
        cls,
        db: Session,
        watchlist_id: Optional[uuid.UUID] = None,
        is_active: Optional[bool] = None,
        plate_search: Optional[str] = None,
        limit: int = 50,
        skip: int = 0
    ) -> Tuple[List[WatchlistEntry], int]:
        """List watchlist entries with optional filtering by watchlist, status, or plate."""
        query = db.query(WatchlistEntry)
        if watchlist_id:
            query = query.filter(WatchlistEntry.watchlist_id == watchlist_id)
        if is_active is not None:
            query = query.filter(WatchlistEntry.is_active == is_active)
        if plate_search:
            clean_search = clean_plate_text(plate_search)
            query = query.filter(WatchlistEntry.plate_number.like(f"%{clean_search}%"))

        total = query.count()
        items = query.order_by(WatchlistEntry.created_at.desc()).offset(skip).limit(limit).all()
        return items, total

    @classmethod
    def update_entry(
        cls,
        db: Session,
        entry_id: uuid.UUID,
        data: WatchlistEntryUpdate,
        user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1"
    ) -> WatchlistEntry:
        """Update an existing watchlist entry or toggle its active state."""
        entry = cls.get_entry(db, entry_id)
        if not entry:
            raise WatchlistNotFoundError(f"Watchlist entry '{entry_id}' not found.")

        if data.plate_number is not None:
            clean_plate = clean_plate_text(data.plate_number)
            if not clean_plate:
                raise WatchlistValidationError("plate_number must contain at least one alphanumeric character.")
            
            # Check duplicate in same watchlist
            dup = db.query(WatchlistEntry).filter(
                WatchlistEntry.watchlist_id == entry.watchlist_id,
                WatchlistEntry.plate_number == clean_plate,
                WatchlistEntry.id != entry_id
            ).first()
            if dup:
                raise WatchlistEntryDuplicateError(
                    f"Plate '{clean_plate}' is already enrolled in this watchlist."
                )
            entry.plate_number = clean_plate

        if data.vehicle_make_model is not None:
            entry.vehicle_make_model = data.vehicle_make_model.strip() if data.vehicle_make_model else None

        if data.fir_number is not None:
            entry.fir_number = data.fir_number.strip() if data.fir_number else None

        if data.notes is not None:
            entry.notes = data.notes.strip() if data.notes else None

        if data.is_active is not None:
            entry.is_active = data.is_active

        db.commit()
        db.refresh(entry)

        _record_audit_log(
            db=db,
            user_id=user_id,
            action="WATCHLIST_ENTRY_UPDATE",
            resource_type="WATCHLIST_ENTRY",
            resource_id=str(entry.id),
            payload_summary=f"Updated entry '{entry.plate_number}' (Active: {entry.is_active})",
            ip_address=ip_address,
        )
        db.commit()
        return entry

    @classmethod
    def delete_entry(
        cls,
        db: Session,
        entry_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        ip_address: str = "127.0.0.1"
    ) -> bool:
        """Remove a plate entry from a watchlist."""
        entry = cls.get_entry(db, entry_id)
        if not entry:
            raise WatchlistNotFoundError(f"Watchlist entry '{entry_id}' not found.")

        plate = entry.plate_number
        db.delete(entry)
        db.commit()

        _record_audit_log(
            db=db,
            user_id=user_id,
            action="WATCHLIST_ENTRY_DELETE",
            resource_type="WATCHLIST_ENTRY",
            resource_id=str(entry_id),
            payload_summary=f"Deleted entry for plate '{plate}'",
            ip_address=ip_address,
        )
        db.commit()
        return True
