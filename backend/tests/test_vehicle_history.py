"""Comprehensive automated tests for Stage 11 Vehicle History.

Protocol Standards:
- docs/engineering-rules.md Rules 1-43.
- Stage 11 Directive Sections 2-25.
- Tests chronological observation retrieval, deterministic ordering, tie-breaking,
  camera & location association from registry, time-range filtering, pagination,
  empty history truthfulness, missing metadata preservation (no 0,0), provenance retention,
  canonical vehicle profile lookup, watchlist status linkage, and 501 journey guard.
- STRICT ISOLATION: No route reconstruction, speed estimation, or next-camera prediction.
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
from backend.app.models.intelligence import Detection, Vehicle
from backend.app.models.watchlists import Watchlist, WatchlistEntry
from backend.app.schemas.vehicle import (
    VehicleProfileRead,
    VehicleObservationItem,
    VehicleHistoryResponse,
)
from backend.app.services.vehicle import (
    VehicleService,
    VehicleNotFoundError,
    VehicleHistoryValidationError,
)


@pytest.fixture
def vehicle_test_setup(db_session: Session):
    """Seed test department, role, user, locations, cameras, vehicle profile, and detections."""
    dept = Department(
        id=uuid.uuid4(),
        name="Traffic Control Directorate",
        code="TCD_GUJ_01"
    )
    role = Role(
        id=uuid.uuid4(),
        name="InvestigatorRole",
        description="Traffic Crime Investigator"
    )
    db_session.add_all([dept, role])
    db_session.flush()

    user = User(
        id=uuid.uuid4(),
        department_id=dept.id,
        role_id=role.id,
        badge_number="INV-9901",
        full_name="Insp. K. Patel",
        email="k.patel@police.gujarat.gov.in",
        hashed_password="secure_hash_placeholder",
        is_active=True
    )
    db_session.add(user)

    # Location 1: Ashram Road (with coordinates)
    loc1 = Location(
        id=uuid.uuid4(),
        name="Ashram Road Junction",
        latitude=23.0305,
        longitude=72.5714,
        address="Near Income Tax Circle, Ashram Road",
        city="Ahmedabad",
        state="Gujarat"
    )
    # Location 2: SG Highway (with coordinates)
    loc2 = Location(
        id=uuid.uuid4(),
        name="SG Highway Flyover",
        latitude=23.0525,
        longitude=72.5120,
        address="Near Thaltej Cross Roads, SG Highway",
        city="Ahmedabad",
        state="Gujarat"
    )
    # Location 3: Unmapped Rural Site (simulating missing coordinates in registry)
    # In SQLite, latitude and longitude can be tested, but Location table has NOT NULL in schema.
    # To test missing location relationship: camera with no location or camera whose location coordinates are evaluated.
    db_session.add_all([loc1, loc2])
    db_session.flush()

    cam1 = Camera(
        id=uuid.uuid4(),
        location_id=loc1.id,
        department_id=dept.id,
        name="CAM-ASHRAM-01",
        rtsp_url="rtsp://127.0.0.1:8554/stream/ashram01",
        stream_type="DEMO",
        status="DEMO"
    )
    cam2 = Camera(
        id=uuid.uuid4(),
        location_id=loc2.id,
        department_id=dept.id,
        name="CAM-SGHIGHWAY-02",
        rtsp_url="rtsp://127.0.0.1:8554/stream/sghighway02",
        stream_type="DEMO",
        status="DEMO"
    )
    db_session.add_all([cam1, cam2])
    db_session.flush()

    # Active Watchlist and Entry for target plate
    wl = Watchlist(
        id=uuid.uuid4(),
        name="Stolen Sedans Hotlist",
        category="STOLEN",
        severity="HIGH",
        is_active=True,
        created_by_user_id=user.id,
    )
    db_session.add(wl)
    db_session.flush()

    target_plate = "GJ01XY1234"
    entry = WatchlistEntry(
        id=uuid.uuid4(),
        watchlist_id=wl.id,
        plate_number=target_plate,
        vehicle_make_model="Honda City White",
        fir_number="FIR/TRAFFIC/2026/102",
        is_active=True,
    )
    db_session.add(entry)
    db_session.flush()

    # Canonical Vehicle Profile
    t0 = datetime(2026, 9, 29, 8, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 29, 8, 15, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 29, 8, 30, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 29, 8, 45, 0, tzinfo=timezone.utc)

    vehicle = Vehicle(
        id=uuid.uuid4(),
        plate_number=target_plate,
        vehicle_type="CAR",
        color="WHITE",
        first_seen_at=t0,
        last_seen_at=t3,
        total_detections_count=4,
    )
    db_session.add(vehicle)

    # Detections:
    # Obs 0: t0 at Cam 1
    det0 = Detection(
        id=uuid.uuid4(),
        camera_id=cam1.id,
        vehicle_id=vehicle.id,
        plate_number=target_plate,
        raw_text="GJ 01 XY 1234",
        vehicle_type="CAR",
        confidence_vehicle=0.96,
        confidence_plate=0.94,
        bbox_vehicle=[10, 10, 200, 200],
        bbox_plate=[50, 50, 150, 100],
        snapshot_path="snapshots/cam1/0.jpg",
        detection_metadata={"video_pts_ms": 0.0, "frame_index": 0},
        is_demo=True,
        detected_at=t0,
    )
    # Obs 1: t1 at Cam 1 (repeated observation at same camera - tests non-deduplication)
    det1 = Detection(
        id=uuid.uuid4(),
        camera_id=cam1.id,
        vehicle_id=vehicle.id,
        plate_number=target_plate,
        raw_text="GJ01 XY 1234",
        vehicle_type="CAR",
        confidence_vehicle=0.95,
        confidence_plate=0.92,
        bbox_vehicle=[12, 12, 205, 205],
        bbox_plate=[52, 52, 152, 102],
        snapshot_path="snapshots/cam1/900000.jpg",
        detection_metadata={"video_pts_ms": 900000.0, "frame_index": 9000},
        is_demo=True,
        detected_at=t1,
    )
    # Obs 2: t2 at Cam 2
    det2 = Detection(
        id=uuid.uuid4(),
        camera_id=cam2.id,
        vehicle_id=vehicle.id,
        plate_number=target_plate,
        raw_text="GJ 01 XY 1234",
        vehicle_type="CAR",
        confidence_vehicle=0.98,
        confidence_plate=0.96,
        bbox_vehicle=[20, 20, 220, 220],
        bbox_plate=[60, 60, 160, 110],
        snapshot_path="snapshots/cam2/1800000.jpg",
        detection_metadata={"video_pts_ms": 1800000.0, "frame_index": 18000},
        is_demo=True,
        detected_at=t2,
    )
    # Obs 3: t3 at Cam 2
    det3 = Detection(
        id=uuid.uuid4(),
        camera_id=cam2.id,
        vehicle_id=vehicle.id,
        plate_number=target_plate,
        raw_text="GJ 01 XY 1234",
        vehicle_type="CAR",
        confidence_vehicle=0.97,
        confidence_plate=0.95,
        bbox_vehicle=[25, 25, 225, 225],
        bbox_plate=[65, 65, 165, 115],
        snapshot_path="snapshots/cam2/2700000.jpg",
        detection_metadata={"video_pts_ms": 2700000.0, "frame_index": 27000},
        is_demo=True,
        detected_at=t3,
    )
    # Different plate detection to test plate isolation
    det_other = Detection(
        id=uuid.uuid4(),
        camera_id=cam1.id,
        plate_number="GJ05AA5555",
        raw_text="GJ 05 AA 5555",
        vehicle_type="TRUCK",
        confidence_vehicle=0.90,
        confidence_plate=0.89,
        bbox_vehicle=[30, 30, 300, 300],
        snapshot_path="snapshots/cam1/other.jpg",
        is_demo=True,
        detected_at=t1,
    )

    db_session.add_all([det0, det1, det2, det3, det_other])
    db_session.commit()

    return {
        "user": user,
        "cam1": cam1,
        "cam2": cam2,
        "loc1": loc1,
        "loc2": loc2,
        "wl": wl,
        "entry": entry,
        "vehicle": vehicle,
        "target_plate": target_plate,
        "t0": t0,
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "det0": det0,
        "det1": det1,
        "det2": det2,
        "det3": det3,
    }


# ============================================================================
# 1. Basic History & Chronological Ordering Tests (Sections 2, 9, 15)
# ============================================================================

def test_get_vehicle_history_chronological_ordering(db_session: Session, vehicle_test_setup):
    """Verify all qualifying records are returned in strict chronological order."""
    data = vehicle_test_setup
    items, total = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"],
        order="asc"
    )

    assert total == 4
    assert len(items) == 4

    # Verify chronological ordering by observation timestamp (detected_at)
    timestamps = [item.detected_at for item in items]
    assert timestamps == sorted(timestamps)

    # First observation should be det0, last should be det3
    assert items[0].detection_id == data["det0"].id
    assert items[1].detection_id == data["det1"].id
    assert items[2].detection_id == data["det2"].id
    assert items[3].detection_id == data["det3"].id


def test_get_vehicle_history_descending_ordering(db_session: Session, vehicle_test_setup):
    """Verify observations ordered latest-first when order='desc'."""
    data = vehicle_test_setup
    items, total = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"],
        order="desc"
    )

    assert total == 4
    assert items[0].detection_id == data["det3"].id
    assert items[1].detection_id == data["det2"].id
    assert items[2].detection_id == data["det1"].id
    assert items[3].detection_id == data["det0"].id


def test_deterministic_tie_breaking_on_equal_timestamps(db_session: Session, vehicle_test_setup):
    """Verify equal timestamps break ties deterministically using Detection.id."""
    data = vehicle_test_setup
    cam1 = data["cam1"]
    same_time = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)

    # Create two detections with identical detected_at
    id_a = uuid.UUID("11111111-0000-0000-0000-000000000001")
    id_b = uuid.UUID("22222222-0000-0000-0000-000000000002")

    det_a = Detection(
        id=id_a,
        camera_id=cam1.id,
        plate_number="GJ02BB2222",
        vehicle_type="CAR",
        confidence_vehicle=0.9,
        bbox_vehicle=[10, 10, 100, 100],
        snapshot_path="snap_a.jpg",
        is_demo=True,
        detected_at=same_time,
    )
    det_b = Detection(
        id=id_b,
        camera_id=cam1.id,
        plate_number="GJ02BB2222",
        vehicle_type="CAR",
        confidence_vehicle=0.9,
        bbox_vehicle=[10, 10, 100, 100],
        snapshot_path="snap_b.jpg",
        is_demo=True,
        detected_at=same_time,
    )
    db_session.add_all([det_b, det_a])  # inserted in reverse id order
    db_session.commit()

    items_asc, _ = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number="GJ02BB2222",
        order="asc"
    )
    assert len(items_asc) == 2
    # Ascending secondary order: id_a then id_b
    assert items_asc[0].detection_id == id_a
    assert items_asc[1].detection_id == id_b

    items_desc, _ = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number="GJ02BB2222",
        order="desc"
    )
    assert len(items_desc) == 2
    # Descending secondary order: id_b then id_a
    assert items_desc[0].detection_id == id_b
    assert items_desc[1].detection_id == id_a


# ============================================================================
# 2. Filtering & Scope Isolation Tests (Sections 4, 7, 8, 10, 15)
# ============================================================================

def test_plate_number_isolation_and_whitespace_sanitization(db_session: Session, vehicle_test_setup):
    """Verify only observations for searched plate are returned, ignoring other vehicles."""
    data = vehicle_test_setup
    # Input with leading/trailing spaces and lowercase
    items, total = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number="  gj01xy1234  "
    )
    assert total == 4
    for item in items:
        assert item.plate_number == "GJ01XY1234"

    # Search the other plate
    items_other, total_other = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number="GJ05AA5555"
    )
    assert total_other == 1
    assert items_other[0].plate_number == "GJ05AA5555"
    assert items_other[0].vehicle_type == "TRUCK"


def test_camera_id_filtering(db_session: Session, vehicle_test_setup):
    """Verify camera filtering limits history to observations at that specific camera."""
    data = vehicle_test_setup
    cam1 = data["cam1"]
    cam2 = data["cam2"]

    # Filter Cam 1 (should return 2 observations: det0, det1)
    items_cam1, total_cam1 = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"],
        camera_id=cam1.id
    )
    assert total_cam1 == 2
    for item in items_cam1:
        assert item.camera_id == cam1.id
        assert item.camera_name == "CAM-ASHRAM-01"

    # Filter Cam 2 (should return 2 observations: det2, det3)
    items_cam2, total_cam2 = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"],
        camera_id=cam2.id
    )
    assert total_cam2 == 2
    for item in items_cam2:
        assert item.camera_id == cam2.id
        assert item.camera_name == "CAM-SGHIGHWAY-02"


def test_time_range_filtering(db_session: Session, vehicle_test_setup):
    """Verify time range lower, upper, and bounded interval filtering."""
    data = vehicle_test_setup
    t0 = data["t0"]
    t1 = data["t1"]
    t2 = data["t2"]
    t3 = data["t3"]

    # 1. Lower bound (start_time = t2): should return t2 and t3
    items_start, total_start = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"],
        start_time=t2
    )
    assert total_start == 2
    assert [i.detection_id for i in items_start] == [data["det2"].id, data["det3"].id]

    # 2. Upper bound (end_time = t1): should return t0 and t1
    items_end, total_end = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"],
        end_time=t1
    )
    assert total_end == 2
    assert [i.detection_id for i in items_end] == [data["det0"].id, data["det1"].id]

    # 3. Interval [t1, t2]: should return exactly t1 and t2
    items_window, total_window = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"],
        start_time=t1,
        end_time=t2
    )
    assert total_window == 2
    assert [i.detection_id for i in items_window] == [data["det1"].id, data["det2"].id]


def test_invalid_time_range_raises_validation_error(db_session: Session, vehicle_test_setup):
    """Verify start_time > end_time raises explicit VehicleHistoryValidationError."""
    data = vehicle_test_setup
    with pytest.raises(VehicleHistoryValidationError) as exc_info:
        VehicleService.get_vehicle_history(
            db=db_session,
            plate_number=data["target_plate"],
            start_time=data["t3"],
            end_time=data["t0"]
        )
    assert "start_time must be prior to end_time" in str(exc_info.value)


def test_repeated_observations_not_deduplicated(db_session: Session, vehicle_test_setup):
    """Verify observations at same camera within short interval are NOT suppressed in history (Section 15)."""
    data = vehicle_test_setup
    items_cam1, total_cam1 = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"],
        camera_id=data["cam1"].id
    )
    # Both appearances must be retained
    assert total_cam1 == 2
    assert items_cam1[0].detection_id == data["det0"].id
    assert items_cam1[1].detection_id == data["det1"].id


# ============================================================================
# 3. Provenance & Missing Metadata Invariants (Sections 5, 7, 8, 19, 20)
# ============================================================================

def test_provenance_and_location_data_retrieval(db_session: Session, vehicle_test_setup):
    """Verify camera, location, video PTS, raw OCR text, and demo flag are preserved."""
    data = vehicle_test_setup
    items, _ = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"]
    )

    first_item = items[0]
    assert first_item.detection_id == data["det0"].id
    assert first_item.camera_id == data["cam1"].id
    assert first_item.camera_name == "CAM-ASHRAM-01"
    assert first_item.location_id == data["loc1"].id
    assert first_item.location_name == "Ashram Road Junction"
    assert first_item.latitude == 23.0305
    assert first_item.longitude == 72.5714
    assert first_item.city == "Ahmedabad"
    assert first_item.state == "Gujarat"

    # Upstream video PTS preservation
    assert first_item.video_pts_ms == 0.0
    # Raw OCR text preservation alongside normalized plate
    assert first_item.raw_text == "GJ 01 XY 1234"
    assert first_item.plate_number == "GJ01XY1234"
    assert first_item.confidence_plate == 0.94
    assert first_item.confidence_vehicle == 0.96
    assert first_item.is_demo is True
    assert first_item.snapshot_path == "snapshots/cam1/0.jpg"


def test_missing_coordinates_remain_none_never_zero_zero():
    """Verify missing coordinates or unmapped locations serialize as None, NEVER 0,0 (Section 8, 19)."""
    # Create detection with unmapped camera
    det_unmapped = Detection(
        id=uuid.uuid4(),
        camera_id=uuid.uuid4(),
        plate_number="GJ09ZZ0001",
        raw_text="GJ 09 ZZ 0001",
        vehicle_type="MOTORCYCLE",
        confidence_vehicle=0.91,
        confidence_plate=0.88,
        bbox_vehicle=[10, 10, 50, 50],
        snapshot_path="snap_unmapped.jpg",
        is_demo=True,
        detected_at=datetime(2026, 9, 29, 9, 0, 0, tzinfo=timezone.utc),
    )
    # det_unmapped has no associated camera/location in relationship
    det_unmapped.camera = None

    obs = VehicleService.build_observation_item(det_unmapped)
    assert obs.location_id is None
    assert obs.location_name is None
    # Crucial assertion: Must be None, NEVER 0.0 or 0
    assert obs.latitude is None
    assert obs.longitude is None
    assert obs.city is None
    assert obs.latitude != 0.0
    assert obs.longitude != 0.0


def test_empty_history_returns_truthful_empty_result(db_session: Session, vehicle_test_setup):
    """Verify query for plate with no observations returns empty result, not demo or fabricated data."""
    items, total = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number="GJ99NONEXISTENT"
    )
    assert total == 0
    assert items == []


# ============================================================================
# 4. Pagination & Query Plan Tests (Sections 11, 12)
# ============================================================================

def test_pagination_limits_and_offsets(db_session: Session, vehicle_test_setup):
    """Verify limit and skip parameters yield non-overlapping pages."""
    data = vehicle_test_setup

    # Page 1 (limit 2, skip 0)
    p1_items, p1_total = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"],
        limit=2,
        skip=0
    )
    assert p1_total == 4
    assert len(p1_items) == 2
    assert [i.detection_id for i in p1_items] == [data["det0"].id, data["det1"].id]

    # Page 2 (limit 2, skip 2)
    p2_items, p2_total = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"],
        limit=2,
        skip=2
    )
    assert p2_total == 4
    assert len(p2_items) == 2
    assert [i.detection_id for i in p2_items] == [data["det2"].id, data["det3"].id]

    # Page 3 (limit 2, skip 4 -> empty)
    p3_items, p3_total = VehicleService.get_vehicle_history(
        db=db_session,
        plate_number=data["target_plate"],
        limit=2,
        skip=4
    )
    assert p3_total == 4
    assert len(p3_items) == 0


# ============================================================================
# 5. Canonical Vehicle Profile Tests (docs/api-contract.md Section 7)
# ============================================================================

def test_get_vehicle_profile_registered_and_watchlist_match(db_session: Session, vehicle_test_setup):
    """Verify vehicle profile returns summary stats and active watchlist enrollment status."""
    data = vehicle_test_setup
    profile = VehicleService.get_vehicle_profile(
        db=db_session,
        plate_number=data["target_plate"]
    )
    assert profile is not None
    assert profile.plate_number == "GJ01XY1234"
    assert profile.vehicle_type == "CAR"
    assert profile.color == "WHITE"
    assert profile.total_detections == 4
    assert profile.first_seen_at == data["t0"]
    assert profile.last_seen_at == data["t3"]
    # Watchlist match check
    assert profile.is_on_watchlist is True
    assert profile.watchlist_category == "STOLEN"


def test_get_vehicle_profile_not_on_watchlist(db_session: Session, vehicle_test_setup):
    """Verify vehicle profile returns is_on_watchlist=False when plate is not on hotlist."""
    profile = VehicleService.get_vehicle_profile(
        db=db_session,
        plate_number="GJ05AA5555"
    )
    assert profile is not None
    assert profile.plate_number == "GJ05AA5555"
    assert profile.vehicle_type == "TRUCK"
    assert profile.is_on_watchlist is False
    assert profile.watchlist_category is None


def test_get_vehicle_profile_non_existent_returns_none(db_session: Session, vehicle_test_setup):
    """Verify non-existent plate returns None."""
    profile = VehicleService.get_vehicle_profile(
        db=db_session,
        plate_number="GJ99BOGUS9999"
    )
    assert profile is None


# ============================================================================
# 6. REST API Endpoints & Boundary Guard Tests (Section 2, 21, 31)
# ============================================================================

def test_api_get_vehicle_profile_success(db_session: Session, vehicle_test_setup):
    """Verify GET /api/v1/vehicles/{plate_number} returns 200 with vehicle profile."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        response = client.get("/api/v1/vehicles/GJ01XY1234")
        assert response.status_code == 200
        data = response.json()
        assert data["plate_number"] == "GJ01XY1234"
        assert data["vehicle_type"] == "CAR"
        assert data["total_detections"] == 4
        assert data["is_on_watchlist"] is True
        assert data["watchlist_category"] == "STOLEN"
    finally:
        app.dependency_overrides.clear()


def test_api_get_vehicle_profile_404_when_not_found(db_session: Session):
    """Verify GET /api/v1/vehicles/{plate_number} returns 404 for unknown plate."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        response = client.get("/api/v1/vehicles/UNKNOWNPLATE")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_api_get_vehicle_history_success_and_filtering(db_session: Session, vehicle_test_setup):
    """Verify GET /api/v1/vehicles/{plate_number}/history returns paginated observation list."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        data = vehicle_test_setup

        response = client.get(
            "/api/v1/vehicles/GJ01XY1234/history",
            params={"order": "asc", "limit": 2, "skip": 0}
        )
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["plate_number"] == "GJ01XY1234"
        assert res_data["total_observations"] == 4
        assert res_data["limit"] == 2
        assert res_data["skip"] == 0
        assert len(res_data["items"]) == 2
        assert res_data["items"][0]["camera_name"] == "CAM-ASHRAM-01"
    finally:
        app.dependency_overrides.clear()


def test_api_get_vehicle_history_invalid_time_range_returns_400():
    """Verify invalid start_time > end_time returns 400 Bad Request."""
    client = TestClient(app)
    response = client.get(
        "/api/v1/vehicles/GJ01XY1234/history",
        params={
            "start_time": "2026-09-29T18:00:00Z",
            "end_time": "2026-09-29T10:00:00Z"
        }
    )
    assert response.status_code == 400
    assert "start_time must be prior to end_time" in response.json()["detail"]


def test_api_get_vehicle_journey_stage_12_endpoint():
    """Verify GET /api/v1/vehicles/{plate_number}/journey returns 200 OK with Stage 12 correlation schema."""
    client = TestClient(app)
    response = client.get("/api/v1/vehicles/GJ01XY1234/journey")
    assert response.status_code == 200
    data = response.json()
    assert data["plate_number"] == "GJ01XY1234"
    assert data["correlation_status"] == "INSUFFICIENT_DATA"
    assert data["total_observations"] == 0
    assert data["total_camera_transitions"] == 0
    assert data["waypoints"] == []
    assert data["transitions"] == []
