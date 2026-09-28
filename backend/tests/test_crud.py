"""Automated tests for CRUD operations using temporary test fixtures."""

import uuid
from datetime import datetime, timezone
from backend.app.models import (
    Department,
    Role,
    User,
    Location,
    Camera,
    Vehicle,
    Detection,
    Watchlist,
    WatchlistEntry,
    Alert,
    Investigation,
    InvestigationEvent,
    Evidence,
    AuditLog,
)


def test_crud_lifecycle_all_entities(db_session):
    """Create and retrieve test fixture records for all required entities."""
    now = datetime.now(timezone.utc)

    # 1. Department, Role, User
    dept = Department(name="Unit Test Department", code="GJ-TEST-01")
    role = Role(name="TestInvestigator", description="Test role for CRUD verification")
    db_session.add_all([dept, role])
    db_session.commit()

    user = User(
        department_id=dept.id,
        role_id=role.id,
        badge_number="TEST_BADGE_101",
        full_name="Test Officer A",
        email="officer.a@test.sentinel",
        hashed_password="secure_hashed_dummy_pw",
    )
    db_session.add(user)
    db_session.commit()

    # 2. Location & Camera
    loc = Location(
        name="Test Junction 01",
        latitude=23.0225,
        longitude=72.5714,
        city="TestCity",
        state="Gujarat",
    )
    db_session.add(loc)
    db_session.commit()

    cam = Camera(
        location_id=loc.id,
        department_id=dept.id,
        name="Test Camera 01",
        rtsp_url="rtsp://127.0.0.1:8554/live/test",
        stream_type="DEMO",
        status="DEMO",
    )
    db_session.add(cam)
    db_session.commit()

    retrieved_cam = db_session.query(Camera).filter_by(id=cam.id).first()
    assert retrieved_cam is not None
    assert retrieved_cam.name == "Test Camera 01"

    # 3. Vehicle
    veh = Vehicle(
        plate_number="GJ01TT1111",
        vehicle_type="CAR",
        color="SILVER",
        first_seen_at=now,
        last_seen_at=now,
        total_detections_count=1,
    )
    db_session.add(veh)
    db_session.commit()

    retrieved_veh = db_session.query(Vehicle).filter_by(plate_number="GJ01TT1111").first()
    assert retrieved_veh is not None
    assert retrieved_veh.color == "SILVER"

    # 4. Detection
    det = Detection(
        camera_id=cam.id,
        vehicle_id=veh.id,
        plate_number="GJ01TT1111",
        vehicle_type="CAR",
        confidence_vehicle=0.96,
        confidence_plate=0.91,
        bbox_vehicle=[100, 150, 400, 350],
        bbox_plate=[220, 310, 320, 340],
        snapshot_path="/test/snapshots/test_det_01.jpg",
        is_demo=True,
        detected_at=now,
    )
    db_session.add(det)
    db_session.commit()

    retrieved_det = db_session.query(Detection).filter_by(id=det.id).first()
    assert retrieved_det is not None
    assert retrieved_det.confidence_vehicle == 0.96

    # 5. Watchlist & WatchlistEntry
    wl = Watchlist(
        name="Test Stolen Vehicles",
        category="STOLEN",
        severity="CRITICAL",
        created_by_user_id=user.id,
    )
    db_session.add(wl)
    db_session.commit()

    entry = WatchlistEntry(
        watchlist_id=wl.id,
        plate_number="GJ01TT1111",
        vehicle_make_model="Test Sedan",
        notes="Test vehicle reported stolen in simulation",
    )
    db_session.add(entry)
    db_session.commit()

    retrieved_entry = db_session.query(WatchlistEntry).filter_by(plate_number="GJ01TT1111").first()
    assert retrieved_entry is not None
    assert retrieved_entry.watchlist_id == wl.id

    # 6. Alert
    alert = Alert(
        detection_id=det.id,
        watchlist_entry_id=entry.id,
        camera_id=cam.id,
        plate_number="GJ01TT1111",
        severity="CRITICAL",
        status="NEW",
    )
    db_session.add(alert)
    db_session.commit()

    retrieved_alert = db_session.query(Alert).filter_by(id=alert.id).first()
    assert retrieved_alert is not None
    assert retrieved_alert.severity == "CRITICAL"

    # 7. Investigation & Evidence
    inv = Investigation(
        case_number="CASE-TEST-2026-001",
        title="Test Incident Investigation",
        target_plate="GJ01TT1111",
        lead_detective_id=user.id,
    )
    db_session.add(inv)
    db_session.commit()

    inv_event = InvestigationEvent(
        investigation_id=inv.id,
        detection_id=det.id,
        alert_id=alert.id,
        sequence_order=1,
        notes="Initial trigger detection",
    )
    db_session.add(inv_event)
    db_session.commit()

    ev = Evidence(
        investigation_id=inv.id,
        file_path="/test/evidence/test_dossier.pdf",
        file_type="PDF_DOSSIER",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        file_size_bytes=1048576,
        generated_by_user_id=user.id,
    )
    db_session.add(ev)
    db_session.commit()

    retrieved_inv = db_session.query(Investigation).filter_by(id=inv.id).first()
    assert retrieved_inv is not None
    assert len(retrieved_inv.events) == 1
    assert len(retrieved_inv.evidence_items) == 1

    # 8. Audit Log
    audit = AuditLog(
        user_id=user.id,
        badge_number=user.badge_number,
        action="TEST_ACTION_EXECUTE",
        resource_type="INVESTIGATION",
        resource_id=str(inv.id),
        ip_address="127.0.0.1",
        payload_summary="Executed automated test case verification",
    )
    db_session.add(audit)
    db_session.commit()

    retrieved_audit = db_session.query(AuditLog).filter_by(id=audit.id).first()
    assert retrieved_audit is not None
    assert retrieved_audit.action == "TEST_ACTION_EXECUTE"
