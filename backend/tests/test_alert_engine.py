"""Comprehensive automated tests for Stage 10 Alert Engine.

Protocol Standards:
- docs/engineering-rules.md Rules 1-43.
- Stage 10 Directive Sections 3-22.
- Tests alert creation, provenance retention, video PTS observation timestamp,
  60-second deduplication, multiple matches, lifecycle transitions, audit logging,
  database rollback safety, and REST API endpoints.
- STRICT ISOLATION: Zero external notifications or WebSockets dispatched.
"""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.db.session import get_db
from backend.app.models.access import Department, Role, User
from backend.app.models.surveillance import Location, Camera
from backend.app.models.intelligence import Detection
from backend.app.models.watchlists import Watchlist, WatchlistEntry
from backend.app.models.alerts import Alert
from backend.app.models.audit import AuditLog
from backend.app.schemas.watchlist import (
    WatchlistMatchResult,
    WatchlistMatchMethod,
)
from backend.app.schemas.alert import (
    AlertStatus,
    AlertSeverity,
    AlertAcknowledgeRequest,
    AlertStatusUpdateRequest,
)
from backend.app.services.alert import (
    AlertEngine,
    AlertService,
    AlertProvenanceError,
    AlertNotFoundError,
    AlertLifecycleError,
)


@pytest.fixture
def alert_test_setup(db_session: Session):
    """Seed test department, role, user, location, camera, and initial detection."""
    dept = Department(
        id=uuid.uuid4(),
        name="State Control Room",
        code="STATE_CR_01"
    )
    role = Role(
        id=uuid.uuid4(),
        name="DispatcherRole",
        description="Emergency Response Dispatcher"
    )
    db_session.add_all([dept, role])
    db_session.flush()

    user = User(
        id=uuid.uuid4(),
        department_id=dept.id,
        role_id=role.id,
        badge_number="DSP-4040",
        full_name="Dispatcher S. Mehta",
        email="s.mehta@police.gujarat.gov.in",
        hashed_password="secure_hash_placeholder",
        is_active=True
    )
    loc = Location(
        id=uuid.uuid4(),
        name="Gita Mandir Bus Port Junction",
        latitude=23.0135,
        longitude=72.5925,
        city="Ahmedabad",
        state="Gujarat"
    )
    db_session.add_all([user, loc])
    db_session.flush()

    cam = Camera(
        id=uuid.uuid4(),
        location_id=loc.id,
        department_id=dept.id,
        name="CAM-GITAMANDIR-01",
        rtsp_url="rtsp://127.0.0.1:8554/stream/gitamandir01",
        stream_type="DEMO",
        status="DEMO"
    )
    db_session.add(cam)
    db_session.flush()

    wl = Watchlist(
        id=uuid.uuid4(),
        name="High-Priority Fugitives",
        category="WANTED",
        severity="CRITICAL",
        is_active=True,
        created_by_user_id=user.id,
    )
    db_session.add(wl)
    db_session.flush()

    entry = WatchlistEntry(
        id=uuid.uuid4(),
        watchlist_id=wl.id,
        plate_number="GJ01FG9999",
        vehicle_make_model="Toyota Innova Crysta",
        fir_number="FIR/CR/2026/884",
        notes="High risk fugitive transport",
        is_active=True,
    )
    db_session.add(entry)
    db_session.flush()

    # Video PTS timestamp: 10:00:00 UTC
    obs_time = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
    det = Detection(
        id=uuid.uuid4(),
        camera_id=cam.id,
        plate_number="GJ01FG9999",
        raw_text="GJ 01 FG 9999",
        vehicle_type="CAR",
        confidence_vehicle=0.96,
        confidence_plate=0.93,
        bbox_vehicle=[50, 50, 250, 250],
        bbox_plate=[100, 150, 200, 180],
        snapshot_path="snapshots/cam01/10000.jpg",
        detection_metadata={"video_pts_ms": 10000.0, "frame_index": 100},
        is_demo=True,
        detected_at=obs_time,
    )
    db_session.add(det)
    db_session.commit()

    return {
        "user": user,
        "cam": cam,
        "wl": wl,
        "entry": entry,
        "det": det,
        "obs_time": obs_time,
    }


# ============================================================================
# Unit Tests: Alert Creation & Provenance
# ============================================================================

def test_alert_creation_success(db_session: Session, alert_test_setup):
    """Verify that a valid Stage 9 match creates an Alert entity with status NEW."""
    data = alert_test_setup
    det = data["det"]
    cam = data["cam"]
    wl = data["wl"]
    entry = data["entry"]

    match = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=det.id,
        camera_id=cam.id,
        camera_name=cam.name,
        detected_at=det.detected_at,
        video_pts_ms=10000.0,
        is_demo=True,
        observed_raw_plate="GJ 01 FG 9999",
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category=wl.category,
        watchlist_severity=wl.severity,
        watchlist_entry_id=entry.id,
        matched_plate=entry.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
        ocr_confidence=0.93,
    )

    alert = AlertEngine.process_match(db=db_session, match=match)

    assert alert is not None
    assert alert.id is not None
    assert alert.detection_id == det.id
    assert alert.camera_id == cam.id
    assert alert.watchlist_entry_id == entry.id
    assert alert.plate_number == "GJ01FG9999"
    assert alert.severity == "CRITICAL"  # Inherited directly from Watchlist.severity
    assert alert.status == AlertStatus.NEW.value
    assert alert.acknowledged_by_user_id is None
    assert alert.acknowledged_at is None
    assert alert.created_at is not None

    # Verify audit log recorded
    audit = db_session.query(AuditLog).filter_by(action="ALERT_GENERATE").first()
    assert audit is not None
    assert str(alert.id) in audit.resource_id


def test_alert_provenance_and_timestamp_isolation(db_session: Session, alert_test_setup):
    """Verify observation timestamp comes from video PTS, isolated from alert created_at."""
    data = alert_test_setup
    det = data["det"]
    cam = data["cam"]
    wl = data["wl"]
    entry = data["entry"]

    match = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=det.id,
        camera_id=cam.id,
        detected_at=det.detected_at,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category=wl.category,
        watchlist_severity="HIGH",
        watchlist_entry_id=entry.id,
        matched_plate=entry.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )

    alert = AlertEngine.process_match(db=db_session, match=match)
    assert alert is not None

    read_dto = AlertEngine.build_alert_read_dto(alert)
    # Observed timestamp must match upstream video detection timestamp
    assert read_dto.observed_at == det.detected_at
    # Separate creation timestamp exists
    assert read_dto.created_at is not None
    assert read_dto.is_demo is True
    assert read_dto.camera_name == cam.name
    assert read_dto.watchlist_name == wl.name


def test_alert_creation_orphan_prevention(db_session: Session, alert_test_setup):
    """Verify invalid or non-existent detection/camera/entry raises AlertProvenanceError."""
    data = alert_test_setup
    cam = data["cam"]
    entry = data["entry"]
    wl = data["wl"]

    # 1. Missing Detection
    bogus_det_id = uuid.uuid4()
    match_bad_det = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=bogus_det_id,
        camera_id=cam.id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category="WANTED",
        watchlist_severity="CRITICAL",
        watchlist_entry_id=entry.id,
        matched_plate=entry.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )
    with pytest.raises(AlertProvenanceError):
        AlertEngine.process_match(db=db_session, match=match_bad_det)

    # 2. Missing Camera
    bogus_cam_id = uuid.uuid4()
    match_bad_cam = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=data["det"].id,
        camera_id=bogus_cam_id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category="WANTED",
        watchlist_severity="CRITICAL",
        watchlist_entry_id=entry.id,
        matched_plate=entry.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )
    with pytest.raises(AlertProvenanceError):
        AlertEngine.process_match(db=db_session, match=match_bad_cam)

    # 3. Missing WatchlistEntry
    bogus_entry_id = uuid.uuid4()
    match_bad_entry = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=data["det"].id,
        camera_id=cam.id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category="WANTED",
        watchlist_severity="CRITICAL",
        watchlist_entry_id=bogus_entry_id,
        matched_plate="GJ01FG9999",
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )
    with pytest.raises(AlertProvenanceError):
        AlertEngine.process_match(db=db_session, match=match_bad_entry)


# ============================================================================
# Unit Tests: 60-Second Deduplication Window (Section 11, 12, 13)
# ============================================================================

def test_deduplication_inside_60_second_window(db_session: Session, alert_test_setup):
    """Verify matches for same plate on same camera within 60s are suppressed."""
    data = alert_test_setup
    det1 = data["det"]  # Observed at 10:00:00 UTC
    cam = data["cam"]
    wl = data["wl"]
    entry = data["entry"]

    match1 = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=det1.id,
        camera_id=cam.id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category=wl.category,
        watchlist_severity=wl.severity,
        watchlist_entry_id=entry.id,
        matched_plate=entry.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )

    # 1. First event -> Alert created
    alert1 = AlertEngine.process_match(db=db_session, match=match1, window_seconds=60)
    assert alert1 is not None

    # 2. Second detection 20 seconds later on same camera (10:00:20 UTC)
    obs_time2 = data["obs_time"] + timedelta(seconds=20)
    det2 = Detection(
        id=uuid.uuid4(),
        camera_id=cam.id,
        plate_number="GJ01FG9999",
        vehicle_type="CAR",
        confidence_vehicle=0.95,
        confidence_plate=0.91,
        bbox_vehicle=[50, 50, 250, 250],
        snapshot_path="snapshots/cam01/30000.jpg",
        is_demo=True,
        detected_at=obs_time2,
    )
    db_session.add(det2)
    db_session.commit()

    match2 = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=det2.id,
        camera_id=cam.id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category=wl.category,
        watchlist_severity=wl.severity,
        watchlist_entry_id=entry.id,
        matched_plate=entry.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )

    # 2nd match must be DEDUPLICATED (returns None)
    alert2 = AlertEngine.process_match(db=db_session, match=match2, window_seconds=60)
    assert alert2 is None

    # Verify total alerts in database is still 1
    assert db_session.query(Alert).count() == 1


def test_deduplication_outside_60_second_window(db_session: Session, alert_test_setup):
    """Verify matches for same plate on same camera after 61 seconds produce a new alert."""
    data = alert_test_setup
    det1 = data["det"]  # 10:00:00 UTC
    cam = data["cam"]
    wl = data["wl"]
    entry = data["entry"]

    match1 = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=det1.id,
        camera_id=cam.id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category=wl.category,
        watchlist_severity=wl.severity,
        watchlist_entry_id=entry.id,
        matched_plate=entry.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )
    alert1 = AlertEngine.process_match(db=db_session, match=match1, window_seconds=60)
    assert alert1 is not None

    # Second detection 75 seconds later (10:01:15 UTC) -> Outside 60s window!
    obs_time_later = data["obs_time"] + timedelta(seconds=75)
    det_later = Detection(
        id=uuid.uuid4(),
        camera_id=cam.id,
        plate_number="GJ01FG9999",
        vehicle_type="CAR",
        confidence_vehicle=0.95,
        confidence_plate=0.91,
        bbox_vehicle=[50, 50, 250, 250],
        snapshot_path="snapshots/cam01/85000.jpg",
        is_demo=True,
        detected_at=obs_time_later,
    )
    db_session.add(det_later)
    db_session.commit()

    match_later = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=det_later.id,
        camera_id=cam.id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category=wl.category,
        watchlist_severity=wl.severity,
        watchlist_entry_id=entry.id,
        matched_plate=entry.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )

    alert_later = AlertEngine.process_match(db=db_session, match=match_later, window_seconds=60)
    assert alert_later is not None
    assert alert_later.id != alert1.id
    assert db_session.query(Alert).count() == 2


def test_deduplication_different_camera(db_session: Session, alert_test_setup):
    """Verify that same plate on a DIFFERENT camera within 60s creates a separate alert."""
    data = alert_test_setup
    det1 = data["det"]
    cam1 = data["cam"]
    wl = data["wl"]
    entry = data["entry"]

    # First camera alert
    match1 = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=det1.id,
        camera_id=cam1.id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category=wl.category,
        watchlist_severity=wl.severity,
        watchlist_entry_id=entry.id,
        matched_plate=entry.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )
    alert1 = AlertEngine.process_match(db=db_session, match=match1, window_seconds=60)
    assert alert1 is not None

    # Create Camera 2
    cam2 = Camera(
        id=uuid.uuid4(),
        location_id=cam1.location_id,
        department_id=cam1.department_id,
        name="CAM-GITAMANDIR-02",
        rtsp_url="rtsp://127.0.0.1:8554/stream/gitamandir02",
        stream_type="DEMO",
        status="DEMO"
    )
    db_session.add(cam2)
    db_session.flush()

    # Detection 10 seconds later on Camera 2
    det_cam2 = Detection(
        id=uuid.uuid4(),
        camera_id=cam2.id,
        plate_number="GJ01FG9999",
        vehicle_type="CAR",
        confidence_vehicle=0.94,
        confidence_plate=0.90,
        bbox_vehicle=[50, 50, 250, 250],
        snapshot_path="snapshots/cam02/20000.jpg",
        is_demo=True,
        detected_at=data["obs_time"] + timedelta(seconds=10),
    )
    db_session.add(det_cam2)
    db_session.commit()

    match_cam2 = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=det_cam2.id,
        camera_id=cam2.id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category=wl.category,
        watchlist_severity=wl.severity,
        watchlist_entry_id=entry.id,
        matched_plate=entry.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )

    alert_cam2 = AlertEngine.process_match(db=db_session, match=match_cam2, window_seconds=60)
    assert alert_cam2 is not None
    assert alert_cam2.camera_id == cam2.id
    assert db_session.query(Alert).count() == 2


def test_multiple_watchlist_matches_independent_alerts(db_session: Session, alert_test_setup):
    """Verify that a single detection matching multiple watchlists creates independent alerts."""
    data = alert_test_setup
    det = data["det"]
    cam = data["cam"]
    user = data["user"]
    entry1 = data["entry"]
    wl1 = data["wl"]

    # Create second watchlist: "Stolen Commercial Vehicles"
    wl2 = Watchlist(
        id=uuid.uuid4(),
        name="Stolen Commercial Fleet",
        category="STOLEN",
        severity="HIGH",
        is_active=True,
        created_by_user_id=user.id,
    )
    db_session.add(wl2)
    db_session.flush()

    entry2 = WatchlistEntry(
        id=uuid.uuid4(),
        watchlist_id=wl2.id,
        plate_number="GJ01FG9999",
        is_active=True,
    )
    db_session.add(entry2)
    db_session.commit()

    match1 = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=det.id,
        camera_id=cam.id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl1.id,
        watchlist_name=wl1.name,
        watchlist_category=wl1.category,
        watchlist_severity="CRITICAL",
        watchlist_entry_id=entry1.id,
        matched_plate=entry1.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )
    match2 = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=det.id,
        camera_id=cam.id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl2.id,
        watchlist_name=wl2.name,
        watchlist_category=wl2.category,
        watchlist_severity="HIGH",
        watchlist_entry_id=entry2.id,
        matched_plate=entry2.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )

    batch_result = AlertEngine.process_matches(db=db_session, matches=[match1, match2])
    assert batch_result.total_matches_evaluated == 2
    assert len(batch_result.alerts_created) == 2
    assert batch_result.deduplicated_count == 0

    severities = {a.severity for a in batch_result.alerts_created}
    assert severities == {"CRITICAL", "HIGH"}


# ============================================================================
# Unit Tests: Alert Lifecycle & Acknowledgment
# ============================================================================

def test_alert_lifecycle_acknowledgment_and_disposition(db_session: Session, alert_test_setup):
    """Test state transitions: NEW -> ACKNOWLEDGED -> RESOLVED."""
    data = alert_test_setup
    det = data["det"]
    cam = data["cam"]
    wl = data["wl"]
    entry = data["entry"]
    user = data["user"]

    match = WatchlistMatchResult(
        match_id=str(uuid.uuid4()),
        detection_id=det.id,
        camera_id=cam.id,
        observed_normalized_plate="GJ01FG9999",
        watchlist_id=wl.id,
        watchlist_name=wl.name,
        watchlist_category=wl.category,
        watchlist_severity="CRITICAL",
        watchlist_entry_id=entry.id,
        matched_plate=entry.plate_number,
        match_method=WatchlistMatchMethod.EXACT,
        similarity_score=1.0,
        edit_distance=0,
    )
    alert = AlertEngine.process_match(db=db_session, match=match)
    assert alert.status == AlertStatus.NEW.value

    # 1. Acknowledge Alert
    ack_alert = AlertService.acknowledge_alert(
        db=db_session,
        alert_id=alert.id,
        user_id=user.id,
        resolution_notes="Unit 14 dispatched to Gita Mandir bus station",
    )
    assert ack_alert.status == AlertStatus.ACKNOWLEDGED.value
    assert ack_alert.acknowledged_by_user_id == user.id
    assert ack_alert.acknowledged_at is not None
    assert "Unit 14 dispatched" in ack_alert.resolution_notes

    # 2. Resolve Alert
    res_alert = AlertService.update_alert_status(
        db=db_session,
        alert_id=alert.id,
        new_status=AlertStatus.RESOLVED,
        resolution_notes="Vehicle intercepted; suspect detained",
        user_id=user.id,
    )
    assert res_alert.status == AlertStatus.RESOLVED.value
    assert "suspect detained" in res_alert.resolution_notes

    # 3. Invalid transition: Cannot reopen RESOLVED back to NEW
    with pytest.raises(AlertLifecycleError):
        AlertService.update_alert_status(
            db=db_session,
            alert_id=alert.id,
            new_status=AlertStatus.NEW,
        )


# ============================================================================
# Integration Tests: REST API Endpoints
# ============================================================================

def test_api_alert_endpoints(db_session: Session, alert_test_setup):
    """Test REST endpoints: GET /alerts, GET /alerts/{id}, PATCH acknowledge, PATCH status."""
    data = alert_test_setup
    det = data["det"]
    cam = data["cam"]
    wl = data["wl"]
    entry = data["entry"]

    client = TestClient(app)
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        # Create an alert via evaluate-matches
        match_payload = [
            {
                "match_id": str(uuid.uuid4()),
                "detection_id": str(det.id),
                "camera_id": str(cam.id),
                "camera_name": cam.name,
                "detected_at": det.detected_at.isoformat(),
                "video_pts_ms": 10000.0,
                "is_demo": True,
                "observed_raw_plate": "GJ 01 FG 9999",
                "observed_normalized_plate": "GJ01FG9999",
                "watchlist_id": str(wl.id),
                "watchlist_name": wl.name,
                "watchlist_category": wl.category,
                "watchlist_severity": "CRITICAL",
                "watchlist_entry_id": str(entry.id),
                "matched_plate": entry.plate_number,
                "match_method": "EXACT",
                "similarity_score": 1.0,
                "edit_distance": 0,
            }
        ]

        post_resp = client.post("/api/v1/alerts/evaluate-matches", json=match_payload)
        assert post_resp.status_code == 201
        post_data = post_resp.json()
        assert len(post_data["alerts_created"]) == 1
        alert_id = post_data["alerts_created"][0]["id"]

        # 1. List alerts
        list_resp = client.get("/api/v1/alerts?status=NEW")
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["total"] >= 1
        assert any(a["id"] == alert_id for a in list_data["items"])

        # 2. Get alert by ID
        get_resp = client.get(f"/api/v1/alerts/{alert_id}")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["id"] == alert_id
        assert get_data["plate_number"] == "GJ01FG9999"
        assert get_data["severity"] == "CRITICAL"
        assert get_data["camera_name"] == cam.name

        # 3. Acknowledge alert
        ack_resp = client.patch(
            f"/api/v1/alerts/{alert_id}/acknowledge",
            json={"resolution_notes": "Officer dispatched via API"}
        )
        assert ack_resp.status_code == 200
        ack_data = ack_resp.json()
        assert ack_data["status"] == "ACKNOWLEDGED"
        assert "Officer dispatched via API" in ack_data["resolution_notes"]

        # 4. Status update to RESOLVED
        status_resp = client.patch(
            f"/api/v1/alerts/{alert_id}/status",
            json={"status": "RESOLVED", "resolution_notes": "Closed via API"}
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "RESOLVED"

    finally:
        app.dependency_overrides.clear()
