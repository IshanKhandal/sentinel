"""Automated tests for Sentinel Stage 16 (Tactical UI) & Stage 17 (End-to-End Verification).

Protocol Standards:
- docs/engineering-rules.md (Rules 1-43)
- docs/demo-mode.md (Explicit DEMO labeling, zero coordinate hallucination, explicit UNMAPPED handling)
- Phase 16 & 17 Directives: Primary & Secondary End-to-End Verification Flows
"""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.db.session import get_db
from backend.app.core.security import create_access_token
from backend.app.core.permissions import (
    seed_roles_and_permissions,
    ROLE_SUPER_ADMIN,
    ROLE_INVESTIGATOR,
    ROLE_OPERATOR,
    ROLE_AUDITOR,
)
from backend.app.models.access import Department, Role, User
from backend.app.models.surveillance import Location, Camera
from backend.app.models.intelligence import Detection, Vehicle
from backend.app.models.watchlists import Watchlist, WatchlistEntry
from backend.app.models.alerts import Alert
from backend.app.models.investigation import Investigation, InvestigationEvent
from backend.app.models.audit import AuditLog


@pytest.fixture
def e2e_seeded_db(db_session: Session):
    """Seed comprehensive end-to-end testing pipeline in database."""
    seed_roles_and_permissions(db_session)
    roles = {r.name: r for r in db_session.query(Role).all()}

    dept = Department(
        id=uuid.uuid4(),
        name="Gujarat Police Command Center",
        code="GJ-POL-TEST",
    )
    db_session.add(dept)
    db_session.flush()

    # Create Users
    admin_user = User(
        id=uuid.uuid4(),
        badge_number="TEST-SYS01",
        full_name="Admin User",
        email="admin@test.gov.in",
        hashed_password="bcrypt_mock_hash",
        role_id=roles[ROLE_SUPER_ADMIN].id,
        department_id=dept.id,
        is_active=True,
    )
    inv_user = User(
        id=uuid.uuid4(),
        badge_number="TEST-INV01",
        full_name="Detective User",
        email="inv@test.gov.in",
        hashed_password="bcrypt_mock_hash",
        role_id=roles[ROLE_INVESTIGATOR].id,
        department_id=dept.id,
        is_active=True,
    )
    db_session.add_all([admin_user, inv_user])
    db_session.flush()

    # Create Locations & Cameras: 2 Mapped, 1 Unmapped
    loc1 = Location(id=uuid.uuid4(), name="SG Highway Pakwan", city="Ahmedabad", latitude=23.0338, longitude=72.5078)
    loc2 = Location(id=uuid.uuid4(), name="ISKCON Circle", city="Ahmedabad", latitude=23.0278, longitude=72.5085)
    loc_unmapped = Location(id=uuid.uuid4(), name="Rural Checkpoint", city="Surat", latitude=None, longitude=None)
    db_session.add_all([loc1, loc2, loc_unmapped])
    db_session.flush()

    cam1 = Camera(id=uuid.uuid4(), name="CAM-AMD-01", department_id=dept.id, location_id=loc1.id, status="DEMO", stream_type="DEMO", rtsp_url="rtsp://test/1")
    cam2 = Camera(id=uuid.uuid4(), name="CAM-AMD-02", department_id=dept.id, location_id=loc2.id, status="DEMO", stream_type="DEMO", rtsp_url="rtsp://test/2")
    cam_unmapped = Camera(id=uuid.uuid4(), name="CAM-SURAT-09", department_id=dept.id, location_id=loc_unmapped.id, status="OFFLINE", stream_type="DEMO", rtsp_url="rtsp://test/3")
    db_session.add_all([cam1, cam2, cam_unmapped])
    db_session.flush()

    # Create Watchlist & Target Plate
    target_plate = "GJ01XY9999"
    watchlist = Watchlist(id=uuid.uuid4(), name="Hotlist Grand Theft", category="STOLEN", severity="CRITICAL", is_active=True, created_by_user_id=admin_user.id)
    db_session.add(watchlist)
    db_session.flush()

    entry = WatchlistEntry(id=uuid.uuid4(), watchlist_id=watchlist.id, plate_number=target_plate, vehicle_make_model="Hyundai Creta", is_active=True)
    db_session.add(entry)
    db_session.flush()

    # Create Detections sequence (Cross-camera journey)
    now = datetime.now(timezone.utc)
    t1 = now - timedelta(minutes=15)
    t2 = now - timedelta(minutes=5)

    det1 = Detection(
        id=uuid.uuid4(),
        camera_id=cam1.id,
        detected_at=t1,
        plate_number=target_plate,
        raw_text=target_plate,
        confidence_vehicle=0.97,
        confidence_plate=0.95,
        vehicle_type="car",
        bbox_vehicle=[100, 200, 300, 400],
        snapshot_path="/snapshots/det1.jpg",
        is_demo=True,
    )
    det2 = Detection(
        id=uuid.uuid4(),
        camera_id=cam2.id,
        detected_at=t2,
        plate_number=target_plate,
        raw_text=target_plate,
        confidence_vehicle=0.98,
        confidence_plate=0.96,
        vehicle_type="car",
        bbox_vehicle=[150, 220, 350, 420],
        snapshot_path="/snapshots/det2.jpg",
        is_demo=True,
    )
    db_session.add_all([det1, det2])
    db_session.flush()

    # Create Alert
    alert = Alert(
        id=uuid.uuid4(),
        watchlist_entry_id=entry.id,
        detection_id=det2.id,
        camera_id=cam2.id,
        plate_number=target_plate,
        severity="CRITICAL",
        status="NEW",
        created_at=t2,
    )
    db_session.add(alert)
    db_session.flush()

    # Create Investigation
    inv = Investigation(
        id=uuid.uuid4(),
        case_number="CASE-E2E-2026",
        title="Operation Rapid Intercept",
        target_plate=target_plate,
        status="IN_PROGRESS",
        lead_detective_id=inv_user.id,
    )
    db_session.add(inv)
    db_session.flush()

    inv_event = InvestigationEvent(
        id=uuid.uuid4(),
        investigation_id=inv.id,
        detection_id=det2.id,
        alert_id=alert.id,
        sequence_order=1,
        notes="Suspect vehicle observed at ISKCON Circle node.",
    )
    db_session.add(inv_event)
    db_session.commit()

    return {
        "admin_user": admin_user,
        "inv_user": inv_user,
        "cam1": cam1,
        "cam2": cam2,
        "cam_unmapped": cam_unmapped,
        "target_plate": target_plate,
        "det1": det1,
        "det2": det2,
        "alert": alert,
        "inv": inv,
    }


@pytest.fixture
def client(db_session: Session):
    """Test client with db override."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 1. Stage 16: Tactical UI Serving & Static Asset Tests
# ---------------------------------------------------------------------------

def test_ui_serves_html_dashboard(client):
    """Verify GET / returns 200 and serves the Tactical Command Center HTML."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "SENTINEL" in response.text
    assert "GUJARAT POLICE" in response.text
    assert "GIS Command Map" in response.text
    assert "gis-map-canvas" in response.text


def test_ui_serves_static_assets(client):
    """Verify /static/style.css and /static/app.js are correctly mounted and served with light-theme design system."""
    css_resp = client.get("/static/style.css")
    assert css_resp.status_code == 200
    assert "text/css" in css_resp.headers.get("content-type", "")
    assert "--bg-canvas" in css_resp.text
    assert "--bg-darkest" in css_resp.text

    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "javascript" in js_resp.headers.get("content-type", "")
    assert "Sentinel Gujarat" in js_resp.text


def test_system_data_sources_endpoint(client):
    """Verify first-class data source abstraction and truthful two-source validation status."""
    resp = client.get("/api/v1/system/data-sources")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_source"] == "DEMO"
    assert "DEMO" in data["active_source_label"]

    # Sentinel Live is BLOCKED because stream host is unconfigured
    assert data["sentinel_live"]["status"] == "BLOCKED"
    assert "unset" in data["sentinel_live"]["reason"].lower() or "not provided" in data["sentinel_live"]["reason"].lower()

    # Custom Dataset is NOT PROVIDED
    assert data["custom_dataset"]["status"] == "NOT PROVIDED"

    # Demo Data is AVAILABLE
    assert data["demo_data"]["status"] == "AVAILABLE"
    assert data["demo_data"]["is_synthetic"] is True

    # Supported sources list
    source_ids = [s["id"] for s in data["supported_sources"]]
    assert "SENTINEL_LIVE" in source_ids
    assert "SENTINEL_TEST" in source_ids
    assert "CUSTOM_DATASET" in source_ids
    assert "DEMO" in source_ids
    assert "TEST" in source_ids

    # Two source validation matrix
    matrix = data["two_source_validation"]
    assert matrix["sentinel_dataset"]["status"] == "BLOCKED"
    assert matrix["custom_dataset"]["status"] == "NOT PROVIDED"
    assert "VERIFIED" in matrix["demo_dataset"]["status"]


def test_ui_security_headers_present(client):
    """Verify defensive security headers are attached on UI page responses."""
    resp = client.get("/")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "mode=block" in resp.headers.get("X-XSS-Protection", "")
    assert "Strict-Transport-Security" in resp.headers


# ---------------------------------------------------------------------------
# 2. Stage 17: Primary End-to-End Test Case (Section 24)
# ---------------------------------------------------------------------------

def test_primary_e2e_vehicle_search_to_investigation_flow(client, e2e_seeded_db):
    """Execute the central demonstration pipeline:
    INPUT: Vehicle Plate
      ➔ Search vehicle history
      ➔ Observation timestamps & camera locations
      ➔ Cross-camera observation sequence
      ➔ GIS Route visualization
      ➔ Related watchlist alert
      ➔ Investigation workspace attachment
    """
    target_plate = e2e_seeded_db["target_plate"]

    # 1. Vehicle Search & History
    hist_resp = client.get(f"/api/v1/vehicles/{target_plate}/history")
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    assert hist["plate_number"] == target_plate
    assert hist["total_observations"] == 2
    assert len(hist["items"]) == 2

    # Verify timestamps and camera names
    obs = hist["items"]
    assert obs[0]["camera_id"] == str(e2e_seeded_db["cam1"].id)
    assert obs[1]["camera_id"] == str(e2e_seeded_db["cam2"].id)

    # 2. Cross-Camera Correlation (Stage 12)
    corr_resp = client.get(f"/api/v1/vehicles/{target_plate}/correlation")
    assert corr_resp.status_code == 200
    corr = corr_resp.json()
    assert corr["plate_number"] == target_plate
    assert corr["total_camera_transitions"] >= 1
    assert len(corr["transitions"]) >= 1
    assert corr["correlation_status"] in ("CORRELATED", "PARTIALLY_CORRELATED")

    # 3. GIS Route Preview from Observations
    waypoints = [
        {"latitude": obs[0]["latitude"], "longitude": obs[0]["longitude"], "sequence": 1},
        {"latitude": obs[1]["latitude"], "longitude": obs[1]["longitude"], "sequence": 2},
    ]
    route_resp = client.post("/api/v1/gis/route-preview", json={"waypoints": waypoints})
    assert route_resp.status_code == 200
    route_data = route_resp.json()
    assert route_data["geometry"]["type"] == "LineString"
    assert len(route_data["geometry"]["coordinates"]) == 2
    assert route_data["properties"]["total_distance_km"] > 0

    # 4. Related Alert Retrieval
    alerts_resp = client.get("/api/v1/alerts")
    assert alerts_resp.status_code == 200
    alerts = alerts_resp.json()["items"]
    matched_alerts = [a for a in alerts if a["plate_number"] == target_plate]
    assert len(matched_alerts) == 1
    assert matched_alerts[0]["severity"] == "CRITICAL"
    assert matched_alerts[0]["status"] == "NEW"

    # 5. Investigation Workspace Linkage
    invs_resp = client.get("/api/v1/investigations")
    assert invs_resp.status_code == 200
    invs = invs_resp.json()["items"]
    matched_inv = [i for i in invs if i["target_plate"] == target_plate]
    assert len(matched_inv) == 1
    assert matched_inv[0]["case_number"] == "CASE-E2E-2026"

    # Verify attached event in investigation
    inv_id = matched_inv[0]["id"]
    events_resp = client.get(f"/api/v1/investigations/{inv_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert len(events) == 1
    assert events[0]["alert_id"] == str(e2e_seeded_db["alert"].id)


# ---------------------------------------------------------------------------
# 3. Secondary End-to-End Test Cases (Section 25)
# ---------------------------------------------------------------------------

def test_camera_registry_and_gis_unmapped_flow(client, e2e_seeded_db):
    """Verify camera catalogue, registry status, and explicit UNMAPPED handling."""
    # Camera list
    cam_resp = client.get("/api/v1/cameras")
    assert cam_resp.status_code == 200
    cams = cam_resp.json()
    assert len(cams) >= 3

    # GeoJSON export excludes unmapped cameras
    geojson_resp = client.get("/api/v1/gis/cameras.geojson")
    assert geojson_resp.status_code == 200
    features = geojson_resp.json()["features"]
    mapped_ids = [f["properties"]["camera_id"] for f in features]
    assert str(e2e_seeded_db["cam1"].id) in mapped_ids
    assert str(e2e_seeded_db["cam2"].id) in mapped_ids
    assert str(e2e_seeded_db["cam_unmapped"].id) not in mapped_ids

    # Unmapped camera API explicitly lists unmapped cameras
    unmapped_resp = client.get("/api/v1/gis/unmapped")
    assert unmapped_resp.status_code == 200
    unmapped_data = unmapped_resp.json()
    assert unmapped_data["unmapped_count"] >= 1
    unmapped_ids = [u["camera_id"] for u in unmapped_data["unmapped_cameras"]]
    assert str(e2e_seeded_db["cam_unmapped"].id) in unmapped_ids


def test_alert_acknowledgement_lifecycle(client, e2e_seeded_db):
    """Verify alert status transition: NEW -> ACKNOWLEDGED -> RESOLVED."""
    alert_id = str(e2e_seeded_db["alert"].id)

    # Acknowledge
    ack_resp = client.patch(f"/api/v1/alerts/{alert_id}/status", json={"status": "ACKNOWLEDGED"})
    assert ack_resp.status_code == 200
    assert ack_resp.json()["status"] == "ACKNOWLEDGED"

    # Resolve
    res_resp = client.patch(f"/api/v1/alerts/{alert_id}/status", json={"status": "RESOLVED", "resolution_notes": "Suspect apprehended"})
    assert res_resp.status_code == 200
    assert res_resp.json()["status"] == "RESOLVED"


# ---------------------------------------------------------------------------
# 4. Realistic Failure & Boundary Testing (Section 26)
# ---------------------------------------------------------------------------

def test_nonexistent_vehicle_history_returns_404(client):
    """Verify querying profile for unknown plate returns 404, and history returns empty total=0."""
    resp = client.get("/api/v1/vehicles/UNKNOWN9999")
    assert resp.status_code == 404

    hist_resp = client.get("/api/v1/vehicles/UNKNOWN9999/history")
    assert hist_resp.status_code == 200
    assert hist_resp.json()["total_observations"] == 0
    assert len(hist_resp.json()["items"]) == 0


def test_malformed_route_preview_returns_422(client):
    """Verify invalid route coordinates are rejected with 422."""
    resp = client.post("/api/v1/gis/route-preview", json={
        "waypoints": [{"latitude": 195.0, "longitude": 72.0, "sequence": 1}]
    })
    assert resp.status_code == 422


def test_unauthenticated_api_call_rejected(client):
    """Verify API rejects requests when token is invalid or missing without override."""
    # Pop override to test real auth
    from backend.app.core.auth import get_current_user
    app.dependency_overrides.pop(get_current_user, None)

    resp = client.get("/api/v1/watchlists")
    assert resp.status_code == 401
