"""Pytest configuration and test database fixtures."""

import os
import sqlite3
import pytest
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Base

TEST_DB_PATH = "test_sentinel_temp.db"
TEST_DATABASE_URL = f"sqlite:///{TEST_DB_PATH}"


@pytest.fixture(scope="session")
def test_engine():
    """Create a temporary SQLite engine with foreign key enforcement."""
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass

    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass


@pytest.fixture(scope="function")
def db_session(test_engine) -> Generator[Session, None, None]:
    """Provide a clean database session for each test function."""
    SessionTest = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = SessionTest()

    yield session

    session.close()
    # Clean table data between test functions to ensure isolation
    with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture(autouse=True)
def default_auth_context(db_session: Session):
    """Seed standard roles/permissions and set default SuperAdmin test user for regression tests."""
    import uuid
    from backend.app.core.auth import get_current_user
    from backend.app.core.permissions import seed_roles_and_permissions, ROLE_SUPER_ADMIN
    from backend.app.models.access import Department, Role, User
    from backend.app.main import app

    seed_roles_and_permissions(db_session)
    dept = db_session.query(Department).filter_by(code="GJ-AMD-01").first()
    if not dept:
        dept = Department(name="Ahmedabad Central", code="GJ-AMD-01")
        db_session.add(dept)
        db_session.flush()

    role = db_session.query(Role).filter_by(name=ROLE_SUPER_ADMIN).first()
    test_user = db_session.query(User).filter_by(badge_number="SYS001").first()
    if not test_user:
        test_user = User(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            badge_number="SYS001",
            full_name="Sentinel System Administrator",
            email="admin@sentinel.internal",
            hashed_password="bcrypt_dummy_hash",
            role_id=role.id,
            department_id=dept.id,
            is_active=True,
        )
        db_session.add(test_user)
        db_session.commit()
        db_session.refresh(test_user)

    from backend.app.db.session import get_db

    def override_get_db():
        yield db_session

    def override_current_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    yield test_user
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)

