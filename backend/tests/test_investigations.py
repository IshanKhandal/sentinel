"""Automated unit and integration tests for Sentinel Stage 13 Investigation Engine.

Protocol Standards:
- docs/engineering-rules.md (Rule 23, 24, 25, 36).
- docs/database-design.md Domain 5 (investigations, investigation_events, evidence).
- Stage 13 Directive Sections 1-28.
- RFC 7807 compliant error responses.
"""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.db.session import get_db
from backend.app.models.investigation import Investigation, InvestigationEvent, Evidence
from backend.app.models.intelligence import Detection
from backend.app.models.alerts import Alert
from backend.app.models.watchlists import Watchlist, WatchlistEntry
from backend.app.models.surveillance import Camera, Location
from backend.app.models.access import Department, User, Role
from backend.app.models.audit import AuditLog
from backend.app.schemas.investigation import (
    InvestigationCreate,
    InvestigationUpdate,
    InvestigationEventCreate,
    EvidenceCreate,
    INVESTIGATION_STATUS_OPEN,
    INVESTIGATION_STATUS_IN_PROGRESS,
    INVESTIGATION_STATUS_CLOSED,
    INVESTIGATION_STATUS_ARCHIVED,
)
from backend.app.services.investigation import (
    InvestigationService,
    InvestigationNotFoundError,
    InvestigationValidationError,
    InvestigationDuplicateError,
    InvestigationEventDuplicateError,
    InvestigationEventNotFoundError,
    ReferencedEntityNotFoundError,
)


@pytest.fixture
def client(db_session: Session):
    """FastAPI TestClient fixture with database session override."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def create_test_setup(db: Session):
    """Helper to create minimal database entities for testing."""
    dept = Department(
        id=uuid.uuid4(),
        name=f"Crime Branch {uuid.uuid4().hex[:6]}",
        code=f"CB-{uuid.uuid4().hex[:4]}",
    )
    db.add(dept)
    db.flush()

    role = Role(
        id=uuid.uuid4(),
        name=f"Detective-{uuid.uuid4().hex[:4]}",
        description="Investigator Role",
    )
    db.add(role)
    db.flush()

    user = User(
        id=uuid.uuid4(),
        department_id=dept.id,
        role_id=role.id,
        badge_number=f"DET-{uuid.uuid4().hex[:6]}",
        full_name="Inspector Vijay Patel",
        email=f"vpatel-{uuid.uuid4().hex[:4]}@gujaratpolice.gov.in",
        hashed_password="mock_password_hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    loc = Location(
        id=uuid.uuid4(),
        name="SG Highway Junction",
        latitude=23.0500,
        longitude=72.5000,
        city="Ahmedabad",
        state="Gujarat",
    )
    db.add(loc)
    db.flush()

    cam = Camera(
        id=uuid.uuid4(),
        name="Cam-SG-01",
        location_id=loc.id,
        department_id=dept.id,
        rtsp_url="rtsp://localhost:8554/live/sg01",
        stream_type="LIVE",
        status="ACTIVE",
    )
    db.add(cam)
    db.flush()

    db.commit()
    return user, cam


def create_test_detection(
    db: Session,
    camera_id: uuid.UUID,
    plate_number: str = "GJ01INV001",
    detected_at: Optional[datetime] = None,
    is_demo: bool = False,
) -> Detection:
    det = Detection(
        id=uuid.uuid4(),
        camera_id=camera_id,
        plate_number=plate_number,
        raw_text=plate_number,
        vehicle_type="CAR",
        confidence_vehicle=0.94,
        confidence_plate=0.91,
        bbox_vehicle=[10.0, 10.0, 100.0, 100.0],
        bbox_plate=[20.0, 30.0, 80.0, 60.0],
        snapshot_path="snapshots/inv/test.jpg",
        is_demo=is_demo,
        detected_at=detected_at or datetime.now(timezone.utc),
    )
    db.add(det)
    db.commit()
    db.refresh(det)
    return det


def create_test_alert(
    db: Session,
    detection_id: uuid.UUID,
    camera_id: uuid.UUID,
    plate_number: str = "GJ01INV001",
) -> Alert:
    user = db.query(User).first()
    if not user:
        user, _ = create_test_setup(db)

    wl = Watchlist(
        id=uuid.uuid4(),
        name=f"Hotlist-{uuid.uuid4().hex[:6]}",
        category="STOLEN_VEHICLE",
        severity="HIGH",
        is_active=True,
        created_by_user_id=user.id,
    )
    db.add(wl)
    db.flush()

    entry = WatchlistEntry(
        id=uuid.uuid4(),
        watchlist_id=wl.id,
        plate_number=plate_number,
        is_active=True,
    )
    db.add(entry)
    db.flush()

    alert = Alert(
        id=uuid.uuid4(),
        detection_id=detection_id,
        watchlist_entry_id=entry.id,
        camera_id=camera_id,
        plate_number=plate_number,
        severity="HIGH",
        status="NEW",
        created_at=datetime.now(timezone.utc),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


# ---------------------------------------------------------------------------
# 1. Investigation Creation & Metadata Tests (Section 5)
# ---------------------------------------------------------------------------

def test_create_investigation_success(db_session: Session):
    """Verify creating a valid investigation initializes status to OPEN with timestamps and audit log."""
    user, _ = create_test_setup(db_session)

    data = InvestigationCreate(
        case_number="FIR-2026-AHM-001",
        title="Armed Robbery Getaway Vehicle Tracking",
        description="Vehicle observed fleeing robbery site near SG Highway.",
        target_plate="GJ01AB1234",
        lead_detective_id=user.id,
    )

    inv = InvestigationService.create_investigation(db_session, data, operator_user_id=user.id)

    assert inv.id is not None
    assert inv.case_number == "FIR-2026-AHM-001"
    assert inv.title == "Armed Robbery Getaway Vehicle Tracking"
    assert inv.status == "OPEN"
    assert inv.target_plate == "GJ01AB1234"
    assert inv.lead_detective_id == user.id
    assert inv.created_at is not None
    assert inv.updated_at is not None

    # Verify audit log emission
    audit = db_session.query(AuditLog).filter_by(
        action="INVESTIGATION_CREATE",
        resource_id=str(inv.id),
    ).first()
    assert audit is not None
    assert audit.resource_type == "INVESTIGATION"
    assert audit.badge_number == user.badge_number


def test_create_investigation_duplicate_case_number_fails(db_session: Session):
    """Verify creating an investigation with duplicate case_number raises InvestigationDuplicateError."""
    user, _ = create_test_setup(db_session)
    data = InvestigationCreate(case_number="FIR-DUPLICATE-001", title="Case 1")
    InvestigationService.create_investigation(db_session, data, operator_user_id=user.id)

    data_dup = InvestigationCreate(case_number="FIR-DUPLICATE-001", title="Case 2")
    with pytest.raises(InvestigationDuplicateError):
        InvestigationService.create_investigation(db_session, data_dup, operator_user_id=user.id)


def test_create_investigation_fallback_system_user_when_omitted(db_session: Session):
    """Verify lead_detective_id falls back to provisioned system user if omitted."""
    data = InvestigationCreate(case_number="FIR-SYSTEM-FALLBACK-01", title="Automated System Case")
    inv = InvestigationService.create_investigation(db_session, data)

    assert inv.lead_detective_id is not None
    lead = db_session.query(User).filter_by(id=inv.lead_detective_id).first()
    assert lead is not None


# ---------------------------------------------------------------------------
# 2. Lifecycle Status & Transitions (Section 6)
# ---------------------------------------------------------------------------

def test_investigation_status_lifecycle_transitions(db_session: Session):
    """Verify valid status progression and rejection of invalid status transitions."""
    user, _ = create_test_setup(db_session)
    inv = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-LIFECYCLE-001", title="Lifecycle Test"),
        operator_user_id=user.id,
    )
    assert inv.status == "OPEN"

    # OPEN -> IN_PROGRESS: Valid
    updated = InvestigationService.update_investigation(
        db_session,
        inv.id,
        InvestigationUpdate(status=INVESTIGATION_STATUS_IN_PROGRESS),
        operator_user_id=user.id,
    )
    assert updated.status == "IN_PROGRESS"

    # IN_PROGRESS -> CLOSED: Valid
    updated = InvestigationService.update_investigation(
        db_session,
        inv.id,
        InvestigationUpdate(status=INVESTIGATION_STATUS_CLOSED),
        operator_user_id=user.id,
    )
    assert updated.status == "CLOSED"

    # CLOSED -> ARCHIVED: Valid
    updated = InvestigationService.update_investigation(
        db_session,
        inv.id,
        InvestigationUpdate(status=INVESTIGATION_STATUS_ARCHIVED),
        operator_user_id=user.id,
    )
    assert updated.status == "ARCHIVED"

    # ARCHIVED -> IN_PROGRESS: Invalid transition according to state machine
    with pytest.raises(InvestigationValidationError) as exc:
        InvestigationService.update_investigation(
            db_session,
            inv.id,
            InvestigationUpdate(status=INVESTIGATION_STATUS_IN_PROGRESS),
            operator_user_id=user.id,
        )
    assert "Illegal status transition" in str(exc.value)


# ---------------------------------------------------------------------------
# 3. Event Attachment, Uniqueness & Deterministic Ordering (Section 7, 8, 9)
# ---------------------------------------------------------------------------

def test_attach_events_to_investigation_and_ordering(db_session: Session):
    """Verify attaching detections and alerts, monotonic sequence ordering, and deterministic sorting."""
    user, cam = create_test_setup(db_session)
    inv = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-EVENTS-001", title="Event Attachment Test"),
        operator_user_id=user.id,
    )

    t1 = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 29, 10, 15, 0, tzinfo=timezone.utc)
    d1 = create_test_detection(db_session, cam.id, "GJ01EV001", detected_at=t1)
    d2 = create_test_detection(db_session, cam.id, "GJ01EV001", detected_at=t2)
    alert = create_test_alert(db_session, d1.id, cam.id, "GJ01EV001")

    # Attach detection 1
    ev1 = InvestigationService.attach_event(
        db_session,
        inv.id,
        InvestigationEventCreate(detection_id=d1.id, notes="Initial camera observation"),
    )
    assert ev1.sequence_order == 1
    assert ev1.detection_id == d1.id
    assert ev1.plate_number == "GJ01EV001"

    # Attach alert
    ev2 = InvestigationService.attach_event(
        db_session,
        inv.id,
        InvestigationEventCreate(alert_id=alert.id, notes="Watchlist hit alert triggered"),
    )
    assert ev2.sequence_order == 2
    assert ev2.alert_id == alert.id

    # Attach detection 2
    ev3 = InvestigationService.attach_event(
        db_session,
        inv.id,
        InvestigationEventCreate(detection_id=d2.id, notes="Subsequent sighting"),
    )
    assert ev3.sequence_order == 3

    # Retrieve all events
    events = InvestigationService.get_investigation_events(db_session, inv.id)
    assert len(events) == 3
    assert [e.sequence_order for e in events] == [1, 2, 3]

    # Verify duplicate attachment rejection
    with pytest.raises(InvestigationEventDuplicateError):
        InvestigationService.attach_event(
            db_session,
            inv.id,
            InvestigationEventCreate(detection_id=d1.id),
        )


def test_attach_vehicle_history_and_selective_attachment(db_session: Session):
    """Verify attaching historical sightings for target plate and selective subset attachment."""
    user, cam = create_test_setup(db_session)
    plate = "GJ01HIST99"
    inv = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-HIST-001", title="History Case", target_plate=plate),
        operator_user_id=user.id,
    )

    t1 = datetime(2026, 9, 29, 8, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 29, 8, 30, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 29, 9, 0, 0, tzinfo=timezone.utc)

    d1 = create_test_detection(db_session, cam.id, plate, detected_at=t1)
    d2 = create_test_detection(db_session, cam.id, plate, detected_at=t2)
    d3 = create_test_detection(db_session, cam.id, plate, detected_at=t3)

    # Attach all sightings for target_plate automatically
    attached = InvestigationService.attach_vehicle_history(db_session, inv.id)
    assert len(attached) == 3
    assert [a.detection_id for a in attached] == [d1.id, d2.id, d3.id]

    # Running again should skip already attached detections without duplication
    attached_again = InvestigationService.attach_vehicle_history(db_session, inv.id)
    assert len(attached_again) == 0

    # Test case with selective subset
    inv2 = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-SELECTIVE-002", title="Selective Sighting"),
    )
    selective = InvestigationService.attach_vehicle_history(
        db_session,
        inv2.id,
        detection_ids=[d2.id],
    )
    assert len(selective) == 1
    assert selective[0].detection_id == d2.id


def test_detach_event_from_investigation(db_session: Session):
    """Verify detaching an event removes it cleanly and logs audit record."""
    user, cam = create_test_setup(db_session)
    inv = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-DETACH-001", title="Detach Case"),
        operator_user_id=user.id,
    )
    d = create_test_detection(db_session, cam.id, "GJ01DETACH")
    ev = InvestigationService.attach_event(
        db_session,
        inv.id,
        InvestigationEventCreate(detection_id=d.id),
    )

    assert len(InvestigationService.get_investigation_events(db_session, inv.id)) == 1

    InvestigationService.detach_event(db_session, inv.id, ev.id)
    assert len(InvestigationService.get_investigation_events(db_session, inv.id)) == 0

    # Non-existent event detachment raises 404
    with pytest.raises(InvestigationEventNotFoundError):
        InvestigationService.detach_event(db_session, inv.id, uuid.uuid4())


# ---------------------------------------------------------------------------
# 4. Cross-Camera Correlation Integration (Section 11)
# ---------------------------------------------------------------------------

def test_investigation_correlation_delegates_to_stage_12(db_session: Session):
    """Verify get_investigation_correlation consumes Stage 12 CorrelationService output without recalculating."""
    user, cam = create_test_setup(db_session)
    plate = "GJ01CORRINV"
    inv = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-CORR-001", title="Corr Case", target_plate=plate),
        operator_user_id=user.id,
    )

    t1 = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
    create_test_detection(db_session, cam.id, plate, detected_at=t1)

    journey = InvestigationService.get_investigation_correlation(db_session, inv.id)
    assert journey.plate_number == plate
    assert journey.total_observations == 1
    assert journey.correlation_status == "NO_TRANSITION"


# ---------------------------------------------------------------------------
# 5. Evidence Metadata Registration (Section 15, 16)
# ---------------------------------------------------------------------------

def test_attach_and_list_evidence_metadata(db_session: Session):
    """Verify evidence metadata registration with valid SHA-256 hash and audit trail."""
    user, _ = create_test_setup(db_session)
    inv = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-EVID-001", title="Evidence Case"),
        operator_user_id=user.id,
    )

    # 64-character SHA-256 hex string
    valid_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    evidence_data = EvidenceCreate(
        file_path="evidence/dossiers/FIR-2026-001-summary.pdf",
        file_type="PDF_DOSSIER",
        sha256_hash=valid_hash,
        file_size_bytes=1048576,
        generated_by_user_id=user.id,
    )

    evidence_read = InvestigationService.attach_evidence(db_session, inv.id, evidence_data)
    assert evidence_read.id is not None
    assert evidence_read.investigation_id == inv.id
    assert evidence_read.file_type == "PDF_DOSSIER"
    assert evidence_read.sha256_hash == valid_hash
    assert evidence_read.file_size_bytes == 1048576

    # List evidence
    items = InvestigationService.list_evidence(db_session, inv.id)
    assert len(items) == 1
    assert items[0].id == evidence_read.id

    # Verify audit entry
    audit = db_session.query(AuditLog).filter_by(
        action="INVESTIGATION_EVIDENCE_ATTACH",
        resource_id=str(inv.id),
    ).first()
    assert audit is not None


# ---------------------------------------------------------------------------
# 6. REST API Endpoints Integration Tests (Section 18, 19, 22)
# ---------------------------------------------------------------------------

def test_api_investigation_crud_endpoints(client: TestClient, db_session: Session):
    """Verify full HTTP REST API CRUD lifecycle for investigations."""
    # 1. Create Investigation (POST /api/v1/investigations)
    res_create = client.post(
        "/api/v1/investigations",
        json={
            "case_number": "FIR-API-TEST-001",
            "title": "API Integration Case",
            "description": "Test case description",
            "target_plate": "GJ01API001",
        },
    )
    assert res_create.status_code == 201
    created_data = res_create.json()
    inv_id = created_data["id"]
    assert created_data["case_number"] == "FIR-API-TEST-001"
    assert created_data["status"] == "OPEN"

    # 2. List Investigations (GET /api/v1/investigations)
    res_list = client.get("/api/v1/investigations?target_plate=GJ01API001")
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert list_data["total"] >= 1
    assert any(item["id"] == inv_id for item in list_data["items"])

    # 3. Get Single Investigation (GET /api/v1/investigations/{id})
    res_get = client.get(f"/api/v1/investigations/{inv_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == inv_id

    # 4. Update Investigation (PATCH /api/v1/investigations/{id})
    res_update = client.patch(
        f"/api/v1/investigations/{inv_id}",
        json={"status": "IN_PROGRESS", "title": "Updated Title"},
    )
    assert res_update.status_code == 200
    assert res_update.json()["status"] == "IN_PROGRESS"
    assert res_update.json()["title"] == "Updated Title"

    # 5. Non-existent Case returns 404
    res_404 = client.get(f"/api/v1/investigations/{uuid.uuid4()}")
    assert res_404.status_code == 404


def test_api_attach_events_and_detach(client: TestClient, db_session: Session):
    """Verify HTTP endpoints for attaching and detaching events."""
    user, cam = create_test_setup(db_session)
    d = create_test_detection(db_session, cam.id, "GJ01APIEV")

    inv = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-API-ATTACH", title="API Attach Test"),
    )

    # Attach event (POST /api/v1/investigations/{id}/events)
    res_attach = client.post(
        f"/api/v1/investigations/{inv.id}/events",
        json={"detection_id": str(d.id), "notes": "Attached via HTTP"},
    )
    assert res_attach.status_code == 201
    ev_data = res_attach.json()
    assert ev_data["detection_id"] == str(d.id)
    ev_id = ev_data["id"]

    # Get events (GET /api/v1/investigations/{id}/events)
    res_events = client.get(f"/api/v1/investigations/{inv.id}/events")
    assert res_events.status_code == 200
    assert len(res_events.json()) == 1

    # Detach event (DELETE /api/v1/investigations/{id}/events/{event_id})
    res_detach = client.delete(f"/api/v1/investigations/{inv.id}/events/{ev_id}")
    assert res_detach.status_code == 204

    # Verify detached
    res_after = client.get(f"/api/v1/investigations/{inv.id}/events")
    assert len(res_after.json()) == 0


def test_api_evidence_export_not_implemented_guard(client: TestClient, db_session: Session):
    """Verify POST /api/v1/investigations/{id}/export returns 501 Not Implemented per Section 17."""
    inv = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-EXPORT-GUARD", title="Export Guard Test"),
    )

    res = client.post(f"/api/v1/investigations/{inv.id}/export")
    assert res.status_code == 501
    assert "EVIDENCE EXPORT NOT IMPLEMENTED" in res.json()["detail"]


def test_api_investigation_invalid_status_transition_returns_400(client: TestClient, db_session: Session):
    """Verify attempting an illegal status transition returns HTTP 400 Bad Request."""
    inv = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-INVALID-STATUS", title="Invalid Status Test"),
    )
    # Move to ARCHIVED
    InvestigationService.update_investigation(
        db_session,
        inv.id,
        InvestigationUpdate(status=INVESTIGATION_STATUS_ARCHIVED),
    )

    # ARCHIVED -> IN_PROGRESS is illegal
    res = client.patch(
        f"/api/v1/investigations/{inv.id}",
        json={"status": "IN_PROGRESS"},
    )
    assert res.status_code == 400
    assert "Illegal status transition" in res.json()["detail"]


def test_api_attach_event_non_existent_detection_returns_404(client: TestClient, db_session: Session):
    """Verify attaching a non-existent detection UUID returns HTTP 404 Not Found."""
    inv = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-DET-404", title="Det 404 Test"),
    )
    res = client.post(
        f"/api/v1/investigations/{inv.id}/events",
        json={"detection_id": str(uuid.uuid4())},
    )
    assert res.status_code == 404
    assert "does not exist" in res.json()["detail"]


def test_api_correlation_without_target_plate_returns_400(client: TestClient, db_session: Session):
    """Verify requesting cross-camera correlation for case without target_plate returns 400."""
    inv = InvestigationService.create_investigation(
        db_session,
        InvestigationCreate(case_number="FIR-NOPLATE-CORR", title="No Plate Case"),
    )
    res = client.get(f"/api/v1/investigations/{inv.id}/correlation")
    assert res.status_code == 400
    assert "no target_plate configured" in res.json()["detail"]


def test_evidence_validation_rejects_invalid_hash_and_type():
    """Verify EvidenceCreate schema enforces valid 64-character hex hash and allowed types."""
    # Bad SHA-256 (too short)
    with pytest.raises(ValueError):
        EvidenceCreate(
            file_path="evidence/file.pdf",
            file_type="PDF_DOSSIER",
            sha256_hash="tooshort",
            file_size_bytes=100,
        )

    # Bad file_type
    with pytest.raises(ValueError):
        EvidenceCreate(
            file_path="evidence/file.bin",
            file_type="INVALID_TYPE",
            sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            file_size_bytes=100,
        )

