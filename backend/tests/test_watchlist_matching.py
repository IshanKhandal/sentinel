"""Comprehensive automated tests for Stage 9 Watchlist Matching & Management.

Protocol Standards:
- docs/engineering-rules.md Rules 1-43.
- Stage 9 Directive Section 25.
- Tests exact matching, fuzzy matching, active/inactive lifecycle, multiple matches,
  normalization, provenance preservation, CRUD operations, error handling, and API endpoints.
- STAGE 10 BOUNDARY INVARIANT: Zero alerts created in alerts table across all tests.
"""

import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.db.session import get_db
from backend.app.models.access import Department, Role, User
from backend.app.models.surveillance import Location, Camera
from backend.app.models.intelligence import Detection, Vehicle
from backend.app.models.watchlists import Watchlist, WatchlistEntry
from backend.app.models.alerts import Alert
from backend.app.models.audit import AuditLog
from backend.app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistUpdate,
    WatchlistCategory,
    WatchlistSeverity,
    WatchlistEntryCreate,
    WatchlistEntryUpdate,
    WatchlistMatchMethod,
)
from backend.app.schemas.anpr import ANPRResult
from backend.app.schemas.detection import BoundingBox
from backend.app.services.watchlist.matcher import (
    WatchlistMatcher,
    clean_plate_text,
    levenshtein_distance,
    string_similarity,
)
from backend.app.services.watchlist.service import (
    WatchlistService,
    WatchlistNotFoundError,
    WatchlistDuplicateError,
    WatchlistEntryDuplicateError,
    WatchlistValidationError,
    get_or_create_system_user,
)
from backend.app.services.event_persistence import EventPersistenceService


@pytest.fixture
def base_test_data(db_session: Session):
    """Seed foundational test user, location, and camera records."""
    dept = Department(
        id=uuid.uuid4(),
        name="Gujarat State Police Intelligence Wing",
        code="INT_WING_01"
    )
    role = Role(
        id=uuid.uuid4(),
        name="InvestigatorRole",
        description="Investigative Inspector"
    )
    db_session.add_all([dept, role])
    db_session.flush()

    user = User(
        id=uuid.uuid4(),
        department_id=dept.id,
        role_id=role.id,
        badge_number="GJ-POL-8841",
        full_name="Inspector R. Patel",
        email="r.patel@police.gujarat.gov.in",
        hashed_password="secure_hash_placeholder",
        is_active=True
    )
    loc = Location(
        id=uuid.uuid4(),
        name="SG Highway Iskcon Crossroad",
        latitude=23.0285,
        longitude=72.5065,
        city="Ahmedabad",
        state="Gujarat"
    )
    db_session.add_all([user, loc])
    db_session.flush()

    cam = Camera(
        id=uuid.uuid4(),
        location_id=loc.id,
        department_id=dept.id,
        name="CAM-SG-01-NORTH",
        rtsp_url="rtsp://127.0.0.1:8554/stream/cam01",
        stream_type="DEMO",
        status="DEMO"
    )
    db_session.add(cam)
    db_session.commit()

    return {
        "dept": dept,
        "role": role,
        "user": user,
        "loc": loc,
        "cam": cam,
    }


# ============================================================================
# Unit Tests: Plate Sanitization & Levenshtein Algorithms
# ============================================================================

def test_clean_plate_text():
    """Verify plate normalization strips noise, hyphens, and whitespace."""
    assert clean_plate_text("GJ 01 AB 1234") == "GJ01AB1234"
    assert clean_plate_text("gj-01-ab-1234") == "GJ01AB1234"
    assert clean_plate_text("GJ.01.AB.1234") == "GJ01AB1234"
    assert clean_plate_text("  GJ01XY9999 \n") == "GJ01XY9999"
    assert clean_plate_text("") == ""
    assert clean_plate_text(None) == ""


def test_levenshtein_distance_and_similarity():
    """Verify standard Levenshtein distance calculations."""
    assert levenshtein_distance("GJ01AB1234", "GJ01AB1234") == 0
    assert string_similarity("GJ01AB1234", "GJ01AB1234") == 1.0

    # 1 substitution: edit distance 1 on length 10 -> similarity 0.90
    assert levenshtein_distance("GJ01AB1234", "GJ01AB1235") == 1
    assert string_similarity("GJ01AB1234", "GJ01AB1235") == 0.90

    # 1 deletion / insertion:
    assert levenshtein_distance("GJ01AB1234", "GJ01AB123") == 1

    # Empty string edge cases:
    assert levenshtein_distance("", "ABC") == 3
    assert levenshtein_distance("ABC", "") == 3
    assert string_similarity("", "") == 1.0


# ============================================================================
# Unit Tests: Watchlist & Entry CRUD Lifecycle
# ============================================================================

def test_watchlist_crud_lifecycle(db_session: Session, base_test_data):
    """Test full CRUD lifecycle of Watchlist model."""
    user = base_test_data["user"]

    # 1. Create
    create_dto = WatchlistCreate(
        name="Stolen Sedans Q3",
        category=WatchlistCategory.STOLEN,
        severity=WatchlistSeverity.HIGH,
        is_active=True,
        created_by_user_id=user.id,
    )
    wl = WatchlistService.create_watchlist(db=db_session, data=create_dto)
    assert wl.id is not None
    assert wl.name == "Stolen Sedans Q3"
    assert wl.category == "STOLEN"
    assert wl.severity == "HIGH"
    assert wl.is_active is True
    assert wl.created_by_user_id == user.id

    # 2. Retrieve
    retrieved = WatchlistService.get_watchlist(db=db_session, watchlist_id=wl.id)
    assert retrieved is not None
    assert retrieved.id == wl.id

    # 3. Duplicate title rejection
    with pytest.raises(WatchlistDuplicateError):
        WatchlistService.create_watchlist(db=db_session, data=create_dto)

    # 4. Update
    update_dto = WatchlistUpdate(
        name="Stolen Vehicles Q3 - All Categories",
        severity=WatchlistSeverity.CRITICAL,
        is_active=False
    )
    updated = WatchlistService.update_watchlist(db=db_session, watchlist_id=wl.id, data=update_dto)
    assert updated.name == "Stolen Vehicles Q3 - All Categories"
    assert updated.severity == "CRITICAL"
    assert updated.is_active is False

    # 5. List with filters
    items, total = WatchlistService.list_watchlists(db=db_session, is_active=False)
    assert total >= 1
    assert any(w.id == wl.id for w in items)

    # 6. Delete
    deleted = WatchlistService.delete_watchlist(db=db_session, watchlist_id=wl.id)
    assert deleted is True
    assert WatchlistService.get_watchlist(db=db_session, watchlist_id=wl.id) is None


def test_watchlist_entry_crud_and_uniqueness(db_session: Session, base_test_data):
    """Test enrollment, sanitization, uniqueness constraints, and entry lifecycle."""
    user = base_test_data["user"]
    wl = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="Organized Crime Target Vehicles",
            category=WatchlistCategory.WANTED,
            severity=WatchlistSeverity.CRITICAL,
            created_by_user_id=user.id,
        )
    )

    # 1. Enroll plate with unnormalized formatting ("GJ 01 AB 1234")
    entry_dto = WatchlistEntryCreate(
        plate_number="GJ 01 AB 1234",
        vehicle_make_model="Toyota Fortuner White",
        fir_number="FIR/AHM/2026/0991",
        notes="Suspect vehicle fleeing scene",
        is_active=True,
    )
    entry = WatchlistService.enroll_plate(db=db_session, watchlist_id=wl.id, data=entry_dto)
    assert entry.id is not None
    assert entry.plate_number == "GJ01AB1234"  # Normalized!
    assert entry.watchlist_id == wl.id
    assert entry.is_active is True

    # 2. Duplicate plate enrollment in SAME watchlist must fail
    with pytest.raises(WatchlistEntryDuplicateError):
        WatchlistService.enroll_plate(
            db=db_session,
            watchlist_id=wl.id,
            data=WatchlistEntryCreate(plate_number="GJ-01-AB-1234")
        )

    # 3. Same plate in a DIFFERENT watchlist is permitted
    wl2 = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="Inter-State Surveillance",
            category=WatchlistCategory.SUSPECT,
            severity=WatchlistSeverity.MEDIUM,
            created_by_user_id=user.id,
        )
    )
    entry2 = WatchlistService.enroll_plate(
        db=db_session,
        watchlist_id=wl2.id,
        data=WatchlistEntryCreate(plate_number="GJ01AB1234")
    )
    assert entry2.id != entry.id
    assert entry2.watchlist_id == wl2.id

    # 4. Update entry
    updated_entry = WatchlistService.update_entry(
        db=db_session,
        entry_id=entry.id,
        data=WatchlistEntryUpdate(notes="Updated suspect status", is_active=False)
    )
    assert updated_entry.notes == "Updated suspect status"
    assert updated_entry.is_active is False

    # 5. Delete entry
    deleted = WatchlistService.delete_entry(db=db_session, entry_id=entry.id)
    assert deleted is True
    assert WatchlistService.get_entry(db=db_session, entry_id=entry.id) is None


def test_system_user_auto_provisioning(db_session: Session):
    """Verify system operator auto-provisioning ensures referential integrity."""
    sys_user = get_or_create_system_user(db_session)
    assert sys_user is not None
    assert sys_user.id is not None
    assert sys_user.badge_number == "SYS001"

    # Creating watchlist without specifying created_by_user_id succeeds using sys_user
    wl = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="Auto User Test Watchlist",
            category=WatchlistCategory.EXPIRED,
            severity=WatchlistSeverity.LOW
        )
    )
    assert wl.created_by_user_id == sys_user.id


# ============================================================================
# Unit Tests: Watchlist Matching Engine (Stage 9 Directive)
# ============================================================================

def test_exact_matching_success(db_session: Session, base_test_data):
    """Verify normalized exact plate match returns EXACT match result."""
    user = base_test_data["user"]
    cam = base_test_data["cam"]

    wl = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="High-Value Robbery Hotlist",
            category=WatchlistCategory.STOLEN,
            severity=WatchlistSeverity.CRITICAL,
            created_by_user_id=user.id,
        )
    )
    WatchlistService.enroll_plate(
        db=db_session,
        watchlist_id=wl.id,
        data=WatchlistEntryCreate(
            plate_number="GJ01AB1234",
            vehicle_make_model="Hyundai Creta",
            fir_number="FIR-2026-001"
        )
    )

    matches = WatchlistMatcher.match_plate(
        db=db_session,
        plate_number="GJ 01 AB 1234",  # With spaces
        raw_text="GJ 01 AB 1234",
        camera_id=cam.id,
        camera_name=cam.name,
        video_pts_ms=14500.0,
        ocr_confidence=0.94,
    )

    assert len(matches) == 1
    m = matches[0]
    assert m.match_method == WatchlistMatchMethod.EXACT
    assert m.similarity_score == 1.0
    assert m.edit_distance == 0
    assert m.observed_normalized_plate == "GJ01AB1234"
    assert m.matched_plate == "GJ01AB1234"
    assert m.watchlist_name == "High-Value Robbery Hotlist"
    assert m.watchlist_category == "STOLEN"
    assert m.watchlist_severity == "CRITICAL"
    assert m.camera_id == cam.id
    assert m.camera_name == cam.name
    assert m.video_pts_ms == 14500.0
    assert m.ocr_confidence == 0.94


def test_exact_matching_no_match(db_session: Session, base_test_data):
    """Verify non-matching plates return empty list without false positives."""
    user = base_test_data["user"]

    wl = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="Stolen Vehicles Hotlist",
            category=WatchlistCategory.STOLEN,
            severity=WatchlistSeverity.HIGH,
            created_by_user_id=user.id,
        )
    )
    WatchlistService.enroll_plate(
        db=db_session,
        watchlist_id=wl.id,
        data=WatchlistEntryCreate(plate_number="GJ01AB1234")
    )

    # Substring does NOT match exact
    matches_sub = WatchlistMatcher.match_plate(
        db=db_session,
        plate_number="GJ01AB123",
        enable_fuzzy=False
    )
    assert len(matches_sub) == 0

    # Completely different plate
    matches_diff = WatchlistMatcher.match_plate(
        db=db_session,
        plate_number="MH12CD5678",
        enable_fuzzy=False
    )
    assert len(matches_diff) == 0


def test_inactive_status_semantics(db_session: Session, base_test_data):
    """Verify that inactive entries or inactive parent watchlists produce NO MATCH."""
    user = base_test_data["user"]

    wl = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="Active Watchlist With Inactive Entry",
            category=WatchlistCategory.SUSPECT,
            severity=WatchlistSeverity.MEDIUM,
            is_active=True,
            created_by_user_id=user.id,
        )
    )
    entry = WatchlistService.enroll_plate(
        db=db_session,
        watchlist_id=wl.id,
        data=WatchlistEntryCreate(
            plate_number="GJ01DE5555",
            is_active=False  # INACTIVE ENTRY!
        )
    )

    # 1. Inactive entry must NOT produce match
    matches = WatchlistMatcher.match_plate(db=db_session, plate_number="GJ01DE5555")
    assert len(matches) == 0

    # 2. Reactivating entry produces match
    WatchlistService.update_entry(
        db=db_session,
        entry_id=entry.id,
        data=WatchlistEntryUpdate(is_active=True)
    )
    matches_active = WatchlistMatcher.match_plate(db=db_session, plate_number="GJ01DE5555")
    assert len(matches_active) == 1

    # 3. Deactivating the PARENT watchlist silences matches for all its entries
    WatchlistService.update_watchlist(
        db=db_session,
        watchlist_id=wl.id,
        data=WatchlistUpdate(is_active=False)
    )
    matches_wl_inactive = WatchlistMatcher.match_plate(db=db_session, plate_number="GJ01DE5555")
    assert len(matches_wl_inactive) == 0


def test_multiple_watchlist_matches(db_session: Session, base_test_data):
    """Verify plate enrolled in multiple active watchlists returns all matching results."""
    user = base_test_data["user"]

    wl_stolen = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="State Stolen Registry",
            category=WatchlistCategory.STOLEN,
            severity=WatchlistSeverity.CRITICAL,
            created_by_user_id=user.id,
        )
    )
    wl_narcotics = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="Narcotics Cell Surveillance",
            category=WatchlistCategory.WANTED,
            severity=WatchlistSeverity.HIGH,
            created_by_user_id=user.id,
        )
    )

    # Enroll SAME plate on both hotlists
    WatchlistService.enroll_plate(
        db=db_session,
        watchlist_id=wl_stolen.id,
        data=WatchlistEntryCreate(plate_number="GJ01XY7777", notes="Reported stolen")
    )
    WatchlistService.enroll_plate(
        db=db_session,
        watchlist_id=wl_narcotics.id,
        data=WatchlistEntryCreate(plate_number="GJ01XY7777", notes="Drug transport suspect")
    )

    matches = WatchlistMatcher.match_plate(db=db_session, plate_number="GJ01XY7777")
    assert len(matches) == 2

    categories = {m.watchlist_category for m in matches}
    assert categories == {"STOLEN", "WANTED"}


def test_fuzzy_matching_behavior(db_session: Session, base_test_data):
    """Verify fuzzy matching on single character substitutions, precedence, and thresholds."""
    user = base_test_data["user"]

    wl = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="Target Fugitive Vehicles",
            category=WatchlistCategory.WANTED,
            severity=WatchlistSeverity.HIGH,
            created_by_user_id=user.id,
        )
    )
    WatchlistService.enroll_plate(
        db=db_session,
        watchlist_id=wl.id,
        data=WatchlistEntryCreate(plate_number="GJ01AB1234")
    )

    # 1. Near match: 1 character difference ("GJ01AB1235")
    # Length 10, edit distance 1 -> similarity 0.90 >= threshold 0.85
    matches_fuzzy = WatchlistMatcher.match_plate(
        db=db_session,
        plate_number="GJ01AB1235",
        enable_fuzzy=True,
        fuzzy_threshold=0.85,
        fuzzy_max_distance=1
    )
    assert len(matches_fuzzy) == 1
    fm = matches_fuzzy[0]
    assert fm.match_method == WatchlistMatchMethod.FUZZY
    assert fm.edit_distance == 1
    assert fm.similarity_score == 0.90
    assert fm.observed_normalized_plate == "GJ01AB1235"
    assert fm.matched_plate == "GJ01AB1234"

    # 2. Too far match: 3 character differences ("GJ01AB9999") -> NO MATCH
    matches_far = WatchlistMatcher.match_plate(
        db=db_session,
        plate_number="GJ01AB9999",
        enable_fuzzy=True,
        fuzzy_threshold=0.85,
        fuzzy_max_distance=1
    )
    assert len(matches_far) == 0

    # 3. Exact match takes precedence: if candidate is exact "GJ01AB1234"
    matches_exact = WatchlistMatcher.match_plate(
        db=db_session,
        plate_number="GJ01AB1234",
        enable_fuzzy=True
    )
    assert len(matches_exact) == 1
    assert matches_exact[0].match_method == WatchlistMatchMethod.EXACT
    assert matches_exact[0].similarity_score == 1.0

    # 4. Disabling fuzzy matching suppresses near-match
    matches_disabled = WatchlistMatcher.match_plate(
        db=db_session,
        plate_number="GJ01AB1235",
        enable_fuzzy=False
    )
    assert len(matches_disabled) == 0


def test_match_persisted_detection_provenance(db_session: Session, base_test_data):
    """Verify match_detection preserves full provenance from persisted Detection."""
    user = base_test_data["user"]
    cam = base_test_data["cam"]

    wl = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="Amber Alert Hotlist",
            category=WatchlistCategory.CRITICAL if hasattr(WatchlistCategory, "CRITICAL") else WatchlistCategory.SUSPECT,
            severity=WatchlistSeverity.CRITICAL,
            created_by_user_id=user.id,
        )
    )
    WatchlistService.enroll_plate(
        db=db_session,
        watchlist_id=wl.id,
        data=WatchlistEntryCreate(
            plate_number="GJ05CD9876",
            vehicle_make_model="Maruti Swift Red",
            fir_number="AMBER-2026-44"
        )
    )

    # Create persisted Detection (Stage 8)
    det_time = datetime(2026, 9, 28, 14, 30, 0, tzinfo=timezone.utc)
    detection = Detection(
        id=uuid.uuid4(),
        camera_id=cam.id,
        plate_number="GJ05CD9876",
        raw_text="GJ 05 CD 9876",
        vehicle_type="CAR",
        confidence_vehicle=0.95,
        confidence_plate=0.88,
        bbox_vehicle=[100, 100, 300, 300],
        bbox_plate=[150, 200, 250, 240],
        snapshot_path="snapshots/cam01/14500.jpg",
        detection_metadata={"video_pts_ms": 14500.0, "frame_index": 145},
        is_demo=True,
        detected_at=det_time,
    )
    db_session.add(detection)
    db_session.commit()

    # Match via WatchlistMatcher.match_detection
    matches = WatchlistMatcher.match_detection(db=db_session, detection=detection)
    assert len(matches) == 1
    m = matches[0]

    assert m.detection_id == detection.id
    assert m.camera_id == cam.id
    assert m.camera_name == cam.name
    assert m.detected_at == det_time
    assert m.video_pts_ms == 14500.0
    assert m.observed_raw_plate == "GJ 05 CD 9876"
    assert m.observed_normalized_plate == "GJ05CD9876"
    assert m.ocr_confidence == 0.88
    assert m.is_demo is True
    assert m.match_method == WatchlistMatchMethod.EXACT


def test_stage_10_boundary_zero_alerts_created(db_session: Session, base_test_data):
    """STRICT INVARIANT: Verify that watchlist matches NEVER insert rows into alerts table."""
    user = base_test_data["user"]
    cam = base_test_data["cam"]

    wl = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="Critical Suspect Hotlist",
            category=WatchlistCategory.WANTED,
            severity=WatchlistSeverity.CRITICAL,
            created_by_user_id=user.id,
        )
    )
    WatchlistService.enroll_plate(
        db=db_session,
        watchlist_id=wl.id,
        data=WatchlistEntryCreate(plate_number="GJ01CR9999")
    )

    # Initial alert count must be 0
    assert db_session.query(Alert).count() == 0

    # Perform matching
    matches = WatchlistMatcher.match_plate(
        db=db_session,
        plate_number="GJ01CR9999",
        camera_id=cam.id
    )
    assert len(matches) == 1

    # Stage 10 Alert Engine boundary check: alerts table MUST STILL BE ZERO!
    assert db_session.query(Alert).count() == 0


def test_persist_and_match_integration(db_session: Session, base_test_data):
    """Test EventPersistenceService.persist_and_match pipeline integration."""
    user = base_test_data["user"]
    cam = base_test_data["cam"]

    wl = WatchlistService.create_watchlist(
        db=db_session,
        data=WatchlistCreate(
            name="Pipeline Integration Hotlist",
            category=WatchlistCategory.STOLEN,
            severity=WatchlistSeverity.HIGH,
            created_by_user_id=user.id,
        )
    )
    WatchlistService.enroll_plate(
        db=db_session,
        watchlist_id=wl.id,
        data=WatchlistEntryCreate(plate_number="GJ01PI1234")
    )

    anpr_result = ANPRResult(
        plate_crop=None,
        plate_bbox_frame=BoundingBox(x1=10, y1=10, x2=50, y2=30),
        vehicle_bbox=BoundingBox(x1=5, y1=5, x2=100, y2=100),
        raw_text="GJ 01 PI 1234",
        normalized_text="GJ01PI1234",
        is_valid_format=True,
        plate_detector_confidence=0.92,
        ocr_confidence=0.89,
        ocr_provider="MOCK",
        ocr_model_version="mock-v1",
        preprocessing_variant="standard",
        total_latency_ms=12.5,
        status="OCR_SUCCESS",
        camera_id=str(cam.id),
        video_pts_ms=5000.0,
        frame_index=50,
        vehicle_class="car",
    )

    detection, matches = EventPersistenceService.persist_and_match(
        db=db_session,
        anpr_result=anpr_result,
        snapshot_path="snapshots/cam01/5000.jpg"
    )

    assert detection.id is not None
    assert detection.plate_number == "GJ01PI1234"
    assert len(matches) == 1
    assert matches[0].detection_id == detection.id
    assert matches[0].match_method == WatchlistMatchMethod.EXACT
    # Verify zero alerts fired
    assert db_session.query(Alert).count() == 0


# ============================================================================
# Integration Tests: REST API Endpoints
# ============================================================================

def test_api_watchlist_endpoints(db_session: Session, base_test_data):
    """Test REST API endpoints for Watchlists and Entries."""
    client = TestClient(app)
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        # 1. Create watchlist
        create_resp = client.post(
            "/api/v1/watchlists",
            json={
                "name": "API Test Hotlist",
                "category": "STOLEN",
                "severity": "CRITICAL",
                "is_active": True,
            }
        )
        assert create_resp.status_code == 201
        wl_data = create_resp.json()
        wl_id = wl_data["id"]
        assert wl_data["name"] == "API Test Hotlist"

        # 2. List watchlists
        list_resp = client.get("/api/v1/watchlists")
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] >= 1

        # 3. Get watchlist by ID
        get_resp = client.get(f"/api/v1/watchlists/{wl_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == wl_id

        # 4. Enroll plate entry
        enroll_resp = client.post(
            f"/api/v1/watchlists/{wl_id}/entries",
            json={
                "plate_number": "GJ 01 ZZZ 9999",
                "vehicle_make_model": "Honda City",
                "fir_number": "FIR-API-001",
                "notes": "API test vehicle"
            }
        )
        assert enroll_resp.status_code == 201
        entry_data = enroll_resp.json()
        entry_id = entry_data["id"]
        assert entry_data["plate_number"] == "GJ01ZZZ9999"

        # 5. List entries
        entries_resp = client.get(f"/api/v1/watchlists/{wl_id}/entries")
        assert entries_resp.status_code == 200
        assert entries_resp.json()["total"] == 1

        # 6. Test on-demand plate match endpoint
        match_resp = client.post(
            "/api/v1/watchlists/match-plate",
            json={"plate_number": "GJ01ZZZ9999"}
        )
        assert match_resp.status_code == 200
        match_data = match_resp.json()
        assert match_data["total_matches"] == 1
        assert match_data["matches"][0]["match_method"] == "EXACT"

        # 7. Test fuzzy match endpoint
        fuzzy_resp = client.post(
            "/api/v1/watchlists/match-plate?enable_fuzzy=true&fuzzy_threshold=0.80&fuzzy_max_distance=1",
            json={"plate_number": "GJ01ZZZ9998"}
        )
        assert fuzzy_resp.status_code == 200
        f_data = fuzzy_resp.json()
        assert f_data["total_matches"] == 1
        assert f_data["matches"][0]["match_method"] == "FUZZY"

        # 8. Delete entry and watchlist
        del_entry = client.delete(f"/api/v1/watchlists/entries/{entry_id}")
        assert del_entry.status_code == 204

        del_wl = client.delete(f"/api/v1/watchlists/{wl_id}")
        assert del_wl.status_code == 204

    finally:
        app.dependency_overrides.clear()
