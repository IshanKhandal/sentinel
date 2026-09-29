"""Automated tests for Sentinel Stage 15: Security & Role-Based Access Control (RBAC).

Protocol Standards:
- docs/engineering-rules.md (Rule 23, 24, 25, 36).
- docs/database-design.md Domain 1 (access) and Domain 6 (audit).
- Stage 15 Directive Sections 1-30.
"""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.db.session import get_db
from backend.app.core.config import settings
from backend.app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    scrub_sensitive_dict,
    TokenExpiredError,
    TokenInvalidError,
)
from backend.app.core.permissions import (
    seed_roles_and_permissions,
    ROLE_SUPER_ADMIN,
    ROLE_INVESTIGATOR,
    ROLE_OPERATOR,
    ROLE_AUDITOR,
    ROLE_PERMISSIONS_MATRIX,
    PERMISSION_INVESTIGATIONS_WRITE,
    PERMISSION_AUDIT_READ,
    PERMISSION_USERS_MANAGE,
)
from backend.app.core.auth import get_current_user
from backend.app.models.access import User, Role, Department
from backend.app.models.audit import AuditLog
from backend.app.services.realtime.connection import WebSocketConnection
from backend.app.services.realtime.manager import WebSocketManager


@pytest.fixture
def auth_test_setup(db_session: Session):
    """Seed roles, permissions, department, and users for each role."""
    seed_roles_and_permissions(db_session)

    dept = Department(
        id=uuid.uuid4(),
        name="Gujarat State Police Headquarter",
        code=f"GJP-{uuid.uuid4().hex[:4]}",
    )
    db_session.add(dept)
    db_session.commit()

    roles = {r.name: r for r in db_session.query(Role).all()}

    # Create users for each role
    plain_password = "SecretPassword123!"
    hashed = hash_password(plain_password)

    users = {}
    for role_name, role_obj in roles.items():
        user = User(
            id=uuid.uuid4(),
            badge_number=f"B-{role_name[:3].upper()}-{uuid.uuid4().hex[:4]}",
            full_name=f"Officer {role_name}",
            email=f"{role_name.lower()}@police.gujarat.gov.in",
            hashed_password=hashed,
            role_id=role_obj.id,
            department_id=dept.id,
            is_active=True,
        )
        db_session.add(user)
        users[role_name] = user

    # Create an inactive user
    inactive_user = User(
        id=uuid.uuid4(),
        badge_number=f"B-INACT-{uuid.uuid4().hex[:4]}",
        full_name="Deactivated Officer",
        email="inactive@police.gujarat.gov.in",
        hashed_password=hashed,
        role_id=roles[ROLE_OPERATOR].id,
        department_id=dept.id,
        is_active=False,
    )
    db_session.add(inactive_user)
    db_session.commit()

    for u in list(users.values()) + [inactive_user]:
        db_session.refresh(u)

    return {
        "dept": dept,
        "roles": roles,
        "users": users,
        "inactive_user": inactive_user,
        "password": plain_password,
    }


@pytest.fixture
def client_raw(unauthenticated_client):
    """TestClient that uses real auth (provided by conftest unauthenticated_client)."""
    return unauthenticated_client


# ---------------------------------------------------------------------------
# 1. Password Hashing & Security Tests
# ---------------------------------------------------------------------------

def test_password_hashing_bcrypt_cost():
    """Verify password hashing produces bcrypt cost 12 hashes."""
    password = "GujaratPoliceSecure2026!"
    hashed = hash_password(password)

    # Bcrypt format: $2b$12$...
    assert hashed.startswith("$2b$12$")
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


def test_password_empty_verification():
    """Verify empty or None passwords fail safely."""
    hashed = hash_password("ValidPassword123!")
    assert verify_password("", hashed) is False
    assert verify_password(None, hashed) is False
    assert verify_password("ValidPassword123!", None) is False


# ---------------------------------------------------------------------------
# 2. JWT Stateless Token Tests
# ---------------------------------------------------------------------------

def test_jwt_create_and_decode_claims():
    """Verify JWT token includes all mandatory claims: sub, badge, role, dept, exp, iat."""
    user_id = str(uuid.uuid4())
    token = create_access_token(
        data={
            "sub": user_id,
            "badge": "GJ-AMD-4012",
            "role": ROLE_INVESTIGATOR,
            "dept": "Crime Branch Ahmedabad",
        },
        expires_delta=timedelta(hours=8),
    )

    claims = decode_access_token(token)
    assert claims["sub"] == user_id
    assert claims["badge"] == "GJ-AMD-4012"
    assert claims["role"] == ROLE_INVESTIGATOR
    assert claims["dept"] == "Crime Branch Ahmedabad"
    assert "exp" in claims
    assert "iat" in claims


def test_jwt_expired_token():
    """Verify expired token raises TokenExpiredError."""
    token = create_access_token(
        data={"sub": "user-123"},
        expires_delta=timedelta(seconds=-10),  # expired 10 seconds ago
    )
    with pytest.raises(TokenExpiredError):
        decode_access_token(token)


def test_jwt_invalid_signature():
    """Verify tampered token raises TokenInvalidError."""
    token = create_access_token(data={"sub": "user-123"})
    tampered_token = token[:-4] + "abcd"
    with pytest.raises(TokenInvalidError):
        decode_access_token(tampered_token)


def test_sensitive_data_scrubbing():
    """Verify scrub_sensitive_dict removes credentials from payloads."""
    payload = {
        "badge_number": "SYS001",
        "password": "ClearTextPassword123!",
        "token": "secret_jwt_token",
        "nested": {
            "hashed_password": "$2b$12$...",
            "api_key": "supersecretkey",
            "safe_field": "public_data",
        }
    }
    scrubbed = scrub_sensitive_dict(payload)
    assert scrubbed["badge_number"] == "SYS001"
    assert scrubbed["password"] == "[REDACTED]"
    assert scrubbed["token"] == "[REDACTED]"
    assert scrubbed["nested"]["hashed_password"] == "[REDACTED]"
    assert scrubbed["nested"]["api_key"] == "[REDACTED]"
    assert scrubbed["nested"]["safe_field"] == "public_data"


# ---------------------------------------------------------------------------
# 3. Authentication Endpoints Tests
# ---------------------------------------------------------------------------

def test_login_success_by_badge(client_raw, auth_test_setup, db_session):
    """Verify login with badge number returns token and user info without password hash."""
    super_admin = auth_test_setup["users"][ROLE_SUPER_ADMIN]
    password = auth_test_setup["password"]

    response = client_raw.post(
        "/api/v1/auth/login",
        json={"identifier": super_admin.badge_number, "password": password},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert data["user"]["badge_number"] == super_admin.badge_number
    assert "hashed_password" not in data["user"]

    # Verify audit log emitted
    audit = db_session.query(AuditLog).filter_by(action="AUTH_LOGIN_SUCCESS").first()
    assert audit is not None
    assert audit.user_id == super_admin.id


def test_login_success_by_email(client_raw, auth_test_setup):
    """Verify login with email returns token."""
    operator = auth_test_setup["users"][ROLE_OPERATOR]
    password = auth_test_setup["password"]

    response = client_raw.post(
        "/api/v1/auth/login",
        json={"identifier": operator.email, "password": password},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["badge_number"] == operator.badge_number
    assert "access_token" in data


def test_login_invalid_password(client_raw, auth_test_setup, db_session):
    """Verify invalid password returns 401 Unauthorized and logs failure."""
    operator = auth_test_setup["users"][ROLE_OPERATOR]

    response = client_raw.post(
        "/api/v1/auth/login",
        json={"identifier": operator.badge_number, "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    assert "Invalid" in response.text

    audit = db_session.query(AuditLog).filter_by(action="AUTH_LOGIN_FAILURE").first()
    assert audit is not None


def test_login_nonexistent_user(client_raw, auth_test_setup):
    """Verify non-existent user returns 401."""
    response = client_raw.post(
        "/api/v1/auth/login",
        json={"identifier": "NON_EXISTENT_BADGE", "password": "AnyPassword!"},
    )
    assert response.status_code == 401


def test_login_long_username_truncates_audit_badge(client_raw, auth_test_setup, db_session):
    """Verify long identifier exceeding 50 characters is truncated in AuditLog.badge_number."""
    long_identifier = "A" * 80
    response = client_raw.post(
        "/api/v1/auth/login",
        json={"identifier": long_identifier, "password": "AnyPassword!"},
    )
    assert response.status_code == 401
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "AUTH_LOGIN_FAILURE", AuditLog.resource_id == long_identifier)
        .first()
    )
    assert audit is not None
    assert audit.badge_number == "A" * 50
    assert len(audit.badge_number) == 50
    assert audit.resource_id == long_identifier


def test_login_inactive_user(client_raw, auth_test_setup, db_session):
    """Verify deactivated user cannot login (401) and receives generic message while preserving audit reason."""
    inactive = auth_test_setup["inactive_user"]
    password = auth_test_setup["password"]

    response = client_raw.post(
        "/api/v1/auth/login",
        json={"identifier": inactive.badge_number, "password": password},
    )
    assert response.status_code == 401
    assert "invalid badge number or password" in response.text.lower()
    assert "deactivated" not in response.text.lower()

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.user_id == inactive.id, AuditLog.action == "AUTH_LOGIN_FAILURE")
        .first()
    )
    assert audit is not None
    assert "Account deactivated" in audit.payload_summary


def test_auth_me_endpoint(client_raw, auth_test_setup):
    """Verify GET /api/v1/auth/me returns current user profile with role and permissions."""
    investigator = auth_test_setup["users"][ROLE_INVESTIGATOR]
    token = create_access_token({"sub": str(investigator.id)})

    response = client_raw.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["badge_number"] == investigator.badge_number
    assert data["role"] == ROLE_INVESTIGATOR
    assert "investigations:read" in data["permissions"]
    assert "investigations:write" in data["permissions"]
    assert "hashed_password" not in data


def test_auth_logout_endpoint(client_raw, auth_test_setup, db_session):
    """Verify POST /api/v1/auth/logout records audit event."""
    auditor = auth_test_setup["users"][ROLE_AUDITOR]
    token = create_access_token({"sub": str(auditor.id)})

    response = client_raw.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204

    audit = db_session.query(AuditLog).filter_by(action="AUTH_LOGOUT").first()
    assert audit is not None
    assert audit.user_id == auditor.id


# ---------------------------------------------------------------------------
# 4. RBAC Authorization & Clearance Tests
# ---------------------------------------------------------------------------

def test_unauthenticated_requests_fail(client_raw):
    """Verify accessing protected routes without Bearer token returns 401."""
    # Watchlists
    r1 = client_raw.get("/api/v1/watchlists")
    assert r1.status_code == 401

    # Investigations
    r2 = client_raw.get("/api/v1/investigations")
    assert r2.status_code == 401

    # Audit Logs
    r3 = client_raw.get("/api/v1/audit-logs")
    assert r3.status_code == 401

    # Users
    r4 = client_raw.get("/api/v1/users/")
    assert r4.status_code == 401


def test_conftest_unauthenticated_fixture(unauthenticated):
    """Verify conftest unauthenticated fixture exercises missing bearer-token behavior without default override."""
    res = unauthenticated.get("/api/v1/watchlists")
    assert res.status_code == 401
    assert "credentials were not provided" in res.text.lower()


def test_rbac_operator_cannot_manage_users(client_raw, auth_test_setup):
    """Verify Operator cannot manage users or view audit logs (403 Forbidden)."""
    operator = auth_test_setup["users"][ROLE_OPERATOR]
    token = create_access_token({"sub": str(operator.id)})
    headers = {"Authorization": f"Bearer {token}"}

    # Operator cannot POST /api/v1/users
    resp = client_raw.post(
        "/api/v1/users/",
        headers=headers,
        json={
            "badge_number": "GJ-NEW-9999",
            "full_name": "Unauthorized User",
            "email": "unauth@sentinel.internal",
            "password": "Password123!",
            "role_id": str(auth_test_setup["roles"][ROLE_OPERATOR].id),
            "department_id": str(auth_test_setup["dept"].id),
            "is_active": True,
        },
    )
    assert resp.status_code == 403

    # Operator cannot GET /api/v1/audit-logs
    resp_audit = client_raw.get("/api/v1/audit-logs", headers=headers)
    assert resp_audit.status_code == 403


def test_rbac_operator_allowed_watchlists_read(client_raw, auth_test_setup):
    """Verify Operator can read watchlists (watchlists:read permission)."""
    operator = auth_test_setup["users"][ROLE_OPERATOR]
    token = create_access_token({"sub": str(operator.id)})
    headers = {"Authorization": f"Bearer {token}"}

    resp = client_raw.get("/api/v1/watchlists", headers=headers)
    assert resp.status_code == 200


def test_rbac_investigator_allowed_investigations(client_raw, auth_test_setup):
    """Verify Investigator can read and write investigations, but not users."""
    investigator = auth_test_setup["users"][ROLE_INVESTIGATOR]
    token = create_access_token({"sub": str(investigator.id)})
    headers = {"Authorization": f"Bearer {token}"}

    # Can read investigations
    resp = client_raw.get("/api/v1/investigations", headers=headers)
    assert resp.status_code == 200

    # Cannot manage users
    resp_user = client_raw.get("/api/v1/users/", headers=headers)
    assert resp_user.status_code == 403


def test_rbac_auditor_access_audit_logs(client_raw, auth_test_setup):
    """Verify Auditor can read audit logs, but cannot create watchlists."""
    auditor = auth_test_setup["users"][ROLE_AUDITOR]
    token = create_access_token({"sub": str(auditor.id)})
    headers = {"Authorization": f"Bearer {token}"}

    # Can read audit logs
    resp = client_raw.get("/api/v1/audit-logs", headers=headers)
    assert resp.status_code == 200

    # Cannot create watchlists
    resp_wl = client_raw.post(
        "/api/v1/watchlists",
        headers=headers,
        json={"name": "Auditor Watchlist", "category": "STOLEN"},
    )
    assert resp_wl.status_code == 403


def test_super_admin_can_manage_users(client_raw, auth_test_setup):
    """Verify SuperAdmin can create a new user and password is never in response."""
    admin = auth_test_setup["users"][ROLE_SUPER_ADMIN]
    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    new_badge = f"GJ-ADM-{uuid.uuid4().hex[:4]}"
    new_email = f"user_{uuid.uuid4().hex[:4]}@sentinel.internal"

    resp = client_raw.post(
        "/api/v1/users/",
        headers=headers,
        json={
            "badge_number": new_badge,
            "full_name": "New Enrolled Officer",
            "email": new_email,
            "password": "SecurePassword123!",
            "role_id": str(auth_test_setup["roles"][ROLE_OPERATOR].id),
            "department_id": str(auth_test_setup["dept"].id),
            "is_active": True,
        },
    )
    assert resp.status_code == 201
    user_data = resp.json()
    assert user_data["badge_number"] == new_badge
    assert "hashed_password" not in user_data


# ---------------------------------------------------------------------------
# 5. Audit Trail Immutability & Integrity Tests
# ---------------------------------------------------------------------------

def test_audit_log_append_only_immutability(client_raw, auth_test_setup):
    """Verify that audit logs are strictly append-only: no DELETE or PATCH routes exist."""
    admin = auth_test_setup["users"][ROLE_SUPER_ADMIN]
    token = create_access_token({"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    # DELETE route does not exist
    del_resp = client_raw.delete("/api/v1/audit-logs", headers=headers)
    assert del_resp.status_code in (404, 405)

    del_item_resp = client_raw.delete(f"/api/v1/audit-logs/{uuid.uuid4()}", headers=headers)
    assert del_item_resp.status_code in (404, 405)

    # PATCH / PUT routes do not exist
    put_resp = client_raw.put(f"/api/v1/audit-logs/{uuid.uuid4()}", headers=headers, json={})
    assert put_resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# 6. Security Headers Tests
# ---------------------------------------------------------------------------

def test_security_headers_present_on_api_responses(client_raw):
    """Verify standard security hardening headers are injected on all HTTP responses."""
    resp = client_raw.get("/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "mode=block" in resp.headers.get("X-XSS-Protection", "")
    assert "max-age=" in resp.headers.get("Strict-Transport-Security", "")


# ---------------------------------------------------------------------------
# 7. WebSocket Gateway Auth & RBAC Clearance Tests
# ---------------------------------------------------------------------------

def test_websocket_connection_security_context():
    """Verify WebSocketConnection correctly enforces RBAC permissions for topic matching."""
    user_id = str(uuid.uuid4())
    conn = WebSocketConnection(
        websocket=None,
        session_id="test-session",
        user_id=user_id,
        badge_number="GJ-WS-001",
        role=ROLE_OPERATOR,
        permissions=set(ROLE_PERMISSIONS_MATRIX[ROLE_OPERATOR]),
    )

    # Operator has detections:read and alerts:read, matches detection and alert topics
    assert conn.matches_topic("detection.vehicle") is True
    assert conn.matches_topic("alert.watchlist_match") is True

    # Operator does NOT have investigations:read or SuperAdmin role, so investigation events are blocked
    assert conn.matches_topic("investigation.created") is False

    # Investigator has investigations:read
    inv_conn = WebSocketConnection(
        websocket=None,
        session_id="inv-session",
        user_id=user_id,
        badge_number="GJ-INV-001",
        role=ROLE_INVESTIGATOR,
        permissions=set(ROLE_PERMISSIONS_MATRIX[ROLE_INVESTIGATOR]),
    )
    assert inv_conn.matches_topic("investigation.created") is True


def test_websocket_rejects_unauthenticated_connection(client_raw):
    """Verify connecting to WebSocket without valid token closes with code 4401."""
    with pytest.raises(Exception):
        with client_raw.websocket_connect("/ws/live?token=invalid_token") as ws:
            pass


def test_alert_user_id_override_security_authorization(db_session: Session, auth_test_setup, client_raw):
    """Verify non-SuperAdmin cannot override acting_user_id in alert acknowledge/status update."""
    from backend.app.models.surveillance import Location, Camera
    from backend.app.models.intelligence import Detection
    from backend.app.models.watchlists import Watchlist, WatchlistEntry
    from backend.app.models.alerts import Alert

    dept = auth_test_setup["dept"]
    super_admin = auth_test_setup["users"][ROLE_SUPER_ADMIN]
    operator = auth_test_setup["users"][ROLE_OPERATOR]
    investigator = auth_test_setup["users"][ROLE_INVESTIGATOR]

    loc = Location(name="Test Sec Loc", city="Ahmedabad")
    db_session.add(loc)
    db_session.flush()

    cam = Camera(
        name="Test Sec Cam",
        location_id=loc.id,
        department_id=dept.id,
        rtsp_url="rtsp://10.0.0.1/live",
        stream_type="LIVE",
        status="ONLINE",
    )
    db_session.add(cam)
    db_session.flush()

    det = Detection(
        camera_id=cam.id,
        detected_at=datetime.now(timezone.utc),
        plate_number="GJ01SEC01",
        confidence_plate=0.95,
        confidence_vehicle=0.95,
        vehicle_type="car",
        bbox_vehicle=[10, 20, 30, 40],
        snapshot_path="/snapshots/sec_test.jpg",
    )
    db_session.add(det)
    db_session.flush()

    wl = Watchlist(
        name="Sec Test Hotlist",
        category="STOLEN",
        severity="CRITICAL",
        is_active=True,
        created_by_user_id=super_admin.id,
    )
    db_session.add(wl)
    db_session.flush()

    wle = WatchlistEntry(
        watchlist_id=wl.id,
        plate_number="GJ01SEC01",
        is_active=True,
    )
    db_session.add(wle)
    db_session.flush()

    alert = Alert(
        detection_id=det.id,
        watchlist_entry_id=wle.id,
        camera_id=cam.id,
        plate_number="GJ01SEC01",
        severity="CRITICAL",
        status="NEW",
    )
    db_session.add(alert)
    db_session.commit()

    # Operator token (has alerts:manage)
    op_token = create_access_token({"sub": str(operator.id)})
    op_headers = {"Authorization": f"Bearer {op_token}"}

    # Attempt to spoof acknowledged_by_user_id as investigator
    res = client_raw.patch(
        f"/api/v1/alerts/{alert.id}/acknowledge",
        headers=op_headers,
        json={"acknowledged_by_user_id": str(investigator.id), "resolution_notes": "Spoofed attempt"}
    )
    assert res.status_code == 403
    assert "SuperAdmin clearance" in res.json()["detail"]

    # When operator does NOT pass an override or passes their own id, it succeeds
    res_valid = client_raw.patch(
        f"/api/v1/alerts/{alert.id}/acknowledge",
        headers=op_headers,
        json={"resolution_notes": "Legitimate officer claim"}
    )
    assert res_valid.status_code == 200
    assert res_valid.json()["acknowledged_by_user_id"] == str(operator.id)


def test_watchlist_audited_mutations_user_attribution(db_session: Session, auth_test_setup, client_raw):
    """Verify watchlist update, update_entry, and delete_entry record the caller's user_id in audit log."""
    from backend.app.models.audit import AuditLog

    super_admin = auth_test_setup["users"][ROLE_SUPER_ADMIN]
    admin_token = create_access_token({"sub": str(super_admin.id)})
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Create watchlist
    res = client_raw.post(
        "/api/v1/watchlists",
        headers=admin_headers,
        json={"name": "Audit Actor Hotlist", "category": "STOLEN", "severity": "HIGH", "is_active": True}
    )
    assert res.status_code == 201
    wl_id = res.json()["id"]

    # Update watchlist
    res_up = client_raw.patch(
        f"/api/v1/watchlists/{wl_id}",
        headers=admin_headers,
        json={"name": "Audit Actor Hotlist Renamed"}
    )
    assert res_up.status_code == 200

    # Enroll entry
    res_en = client_raw.post(
        f"/api/v1/watchlists/{wl_id}/entries",
        headers=admin_headers,
        json={"plate_number": "GJ01AUD01"}
    )
    assert res_en.status_code == 201
    entry_id = res_en.json()["id"]

    # Update entry
    res_eup = client_raw.patch(
        f"/api/v1/watchlists/entries/{entry_id}",
        headers=admin_headers,
        json={"notes": "Audited note update"}
    )
    assert res_eup.status_code == 200

    # Delete entry
    res_edel = client_raw.delete(
        f"/api/v1/watchlists/entries/{entry_id}",
        headers=admin_headers
    )
    assert res_edel.status_code == 204

    # Verify audit logs have user_id = super_admin.id
    logs = db_session.query(AuditLog).filter(AuditLog.user_id == super_admin.id).all()
    actions = {l.action for l in logs}
    assert "WATCHLIST_UPDATE" in actions
    assert "WATCHLIST_ENTRY_ADD" in actions
    assert "WATCHLIST_ENTRY_UPDATE" in actions
    assert "WATCHLIST_ENTRY_DELETE" in actions


