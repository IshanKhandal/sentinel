"""Automated tests verifying foreign keys, uniqueness, check constraints, and cascades."""

import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError

from backend.app.models import (
    Department,
    Role,
    User,
    Location,
    Camera,
    Vehicle,
    Watchlist,
    WatchlistEntry,
)


def test_foreign_key_enforcement(db_session):
    """Verify that foreign key constraints reject records with invalid foreign keys."""
    # Attempt to insert a user with a non-existent department_id and role_id
    invalid_user = User(
        department_id=uuid.uuid4(),
        role_id=uuid.uuid4(),
        badge_number="BADGE_FAKE_99",
        full_name="Invalid Test Officer",
        email="invalid@sentinel.test",
        hashed_password="hashed_pw_test",
    )
    db_session.add(invalid_user)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unique_constraint_enforcement(db_session):
    """Verify that unique constraints reject duplicate records."""
    dept = Department(name="Cyber Crime Unit", code="GJ-CYBER-01")
    db_session.add(dept)
    db_session.commit()

    # Attempt to add another department with the same code
    duplicate_dept = Department(name="Cyber Crime Division", code="GJ-CYBER-01")
    db_session.add(duplicate_dept)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Attempt to add duplicate vehicle plate
    now = datetime.now(timezone.utc)
    v1 = Vehicle(plate_number="GJ01TEST99", first_seen_at=now, last_seen_at=now)
    v2 = Vehicle(plate_number="GJ01TEST99", first_seen_at=now, last_seen_at=now)
    db_session.add(v1)
    db_session.commit()

    db_session.add(v2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_cascade_delete(db_session):
    """Verify that deleting a parent entity cascades appropriately."""
    dept = Department(name="Traffic North", code="GJ-TRAF-N")
    role = Role(name="TestAdmin")
    db_session.add_all([dept, role])
    db_session.commit()

    user = User(
        department_id=dept.id,
        role_id=role.id,
        badge_number="BADGE_CASCADE_01",
        full_name="Cascade Test Officer",
        email="cascade@sentinel.test",
        hashed_password="hashed_pw_test",
    )
    db_session.add(user)
    db_session.commit()

    wl = Watchlist(
        name="Test Hotlist",
        category="STOLEN",
        severity="HIGH",
        created_by_user_id=user.id,
    )
    db_session.add(wl)
    db_session.commit()

    entry = WatchlistEntry(
        watchlist_id=wl.id,
        plate_number="GJ01CAS999",
    )
    db_session.add(entry)
    db_session.commit()

    # Verify entry exists
    assert db_session.query(WatchlistEntry).filter_by(watchlist_id=wl.id).count() == 1

    # Delete parent watchlist
    db_session.delete(wl)
    db_session.commit()

    # Verify child entry was cascade deleted
    assert db_session.query(WatchlistEntry).filter_by(plate_number="GJ01CAS999").count() == 0
