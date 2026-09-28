"""Automated unit and integration tests for Sentinel Stage 12 Cross-Camera Correlation.

Protocol Standards:
- docs/engineering-rules.md Rule 36 (Observation != Route).
- docs/final-architecture.md FLOW G & FLOW H.
- docs/gis-architecture.md Section 3.2.
- Stage 12 Directive Sections 1-28.
"""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.db.session import get_db
from backend.app.models.intelligence import Detection, Vehicle
from backend.app.models.surveillance import Camera, Location
from backend.app.models.access import Department
from backend.app.services.correlation import (
    CorrelationService,
    CorrelationValidationError,
    DEFAULT_MAX_SPEED_THRESHOLD_KMH,
)
from backend.app.services.gis_service import GISService


@pytest.fixture
def client(db_session: Session):
    """FastAPI TestClient fixture with database session override."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def create_test_location(
    db: Session,
    name: str = "Test Junction",
    lat: float = 23.0225,
    lon: float = 72.5714,
    city: str = "Ahmedabad"
) -> Location:
    """Helper to create a Location record with coordinates."""
    loc = Location(
        id=uuid.uuid4(),
        name=name,
        latitude=lat,
        longitude=lon,
        city=city,
        state="Gujarat"
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


def create_test_camera(
    db: Session,
    name: str = "Test Camera",
    location_id: Optional[uuid.UUID] = None,
    stream_type: str = "LIVE",
    status: str = "ACTIVE",
) -> Camera:
    """Helper to create a Camera record linked to a Location."""
    dept = Department(
        id=uuid.uuid4(),
        name=f"Traffic Division {uuid.uuid4().hex[:6]}",
        code=f"TD-{uuid.uuid4().hex[:4]}"
    )
    db.add(dept)
    db.flush()

    cam = Camera(
        id=uuid.uuid4(),
        name=name,
        location_id=location_id,
        department_id=dept.id,
        rtsp_url="rtsp://localhost:8554/stream/test",
        stream_type=stream_type,
        status=status
    )
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


def create_test_detection(
    db: Session,
    camera_id: uuid.UUID,
    plate_number: str,
    detected_at: datetime,
    is_demo: bool = False,
    video_pts_ms: float = 1000.0,
    vehicle_type: str = "CAR",
    confidence_vehicle: float = 0.95,
) -> Detection:
    """Helper to create a Detection record."""
    det = Detection(
        id=uuid.uuid4(),
        camera_id=camera_id,
        plate_number=plate_number,
        raw_text=plate_number,
        vehicle_type=vehicle_type,
        confidence_vehicle=confidence_vehicle,
        confidence_plate=0.92,
        bbox_vehicle=[10.0, 10.0, 100.0, 100.0],
        bbox_plate=[20.0, 30.0, 80.0, 60.0],
        snapshot_path=f"snapshots/{camera_id}/{int(video_pts_ms)}.jpg",
        is_demo=is_demo,
        detected_at=detected_at,
        detection_metadata={"video_pts_ms": video_pts_ms, "frame_index": 1}
    )
    db.add(det)
    db.commit()
    db.refresh(det)
    return det


# ---------------------------------------------------------------------------
# 1. Chronological Ordering & Deterministic Tie-Breaking (Section 6)
# ---------------------------------------------------------------------------

def test_correlation_chronological_ordering_with_tie_breaker(db_session: Session):
    """Verify observations are ordered strictly by detected_at ASC with Detection.id tie-breaking."""
    loc = create_test_location(db_session, "Navrangpura", 23.0365, 72.5611)
    cam = create_test_camera(db_session, "Cam-Navrangpura", loc.id)

    plate = "GJ01CHRONO01"
    t1 = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 29, 10, 5, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 29, 10, 10, 0, tzinfo=timezone.utc)

    # Insert out of order
    d3 = create_test_detection(db_session, cam.id, plate, t3, video_pts_ms=600000.0)
    d1 = create_test_detection(db_session, cam.id, plate, t1, video_pts_ms=0.0)
    d2 = create_test_detection(db_session, cam.id, plate, t2, video_pts_ms=300000.0)

    journey = CorrelationService.correlate_vehicle_journey(db_session, plate)

    assert journey.total_observations == 3
    observed_ids = [o.detection_id for o in journey.observations]
    assert observed_ids == [d1.id, d2.id, d3.id]


# ---------------------------------------------------------------------------
# 2. Same-Camera Aggregation vs Camera Transitions (Section 7)
# ---------------------------------------------------------------------------

def test_correlation_same_camera_aggregation_and_transitions(db_session: Session):
    """Verify A -> A -> B -> B -> C produces waypoints [A, B, C] and transitions [A->B, B->C]."""
    locA = create_test_location(db_session, "Paldi", 23.0135, 72.5624)
    locB = create_test_location(db_session, "Ellisbridge", 23.0232, 72.5714)
    locC = create_test_location(db_session, "Ashram Road", 23.0305, 72.5714)

    camA = create_test_camera(db_session, "Cam-Paldi", locA.id)
    camB = create_test_camera(db_session, "Cam-Ellisbridge", locB.id)
    camC = create_test_camera(db_session, "Cam-AshramRoad", locC.id)

    plate = "GJ01SEQ0001"
    base = datetime(2026, 9, 29, 8, 0, 0, tzinfo=timezone.utc)

    # 2 observations at Cam A
    dA1 = create_test_detection(db_session, camA.id, plate, base)
    dA2 = create_test_detection(db_session, camA.id, plate, base + timedelta(seconds=15))

    # 2 observations at Cam B (5 minutes later)
    dB1 = create_test_detection(db_session, camB.id, plate, base + timedelta(minutes=5))
    dB2 = create_test_detection(db_session, camB.id, plate, base + timedelta(minutes=5, seconds=20))

    # 1 observation at Cam C (10 minutes later)
    dC1 = create_test_detection(db_session, camC.id, plate, base + timedelta(minutes=10))

    journey = CorrelationService.correlate_vehicle_journey(db_session, plate)

    assert journey.total_observations == 5
    assert journey.total_waypoints == 3
    assert journey.total_camera_transitions == 2
    assert journey.correlation_status == "CORRELATED"

    def to_utc(dt: datetime) -> datetime:
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

    # Verify waypoints
    wpA, wpB, wpC = journey.waypoints
    assert wpA.camera_id == camA.id
    assert wpA.observation_count == 2
    assert wpA.first_detected_at == to_utc(dA1.detected_at)
    assert wpA.last_detected_at == to_utc(dA2.detected_at)

    assert wpB.camera_id == camB.id
    assert wpB.observation_count == 2
    assert wpB.first_detected_at == to_utc(dB1.detected_at)
    assert wpB.last_detected_at == to_utc(dB2.detected_at)

    assert wpC.camera_id == camC.id
    assert wpC.observation_count == 1
    assert wpC.first_detected_at == to_utc(dC1.detected_at)
    assert wpC.last_detected_at == to_utc(dC1.detected_at)

    # Verify transitions
    t1, t2 = journey.transitions
    # Transition 1: departure at Cam A (dA2) -> arrival at Cam B (dB1)
    assert t1.from_camera_id == camA.id
    assert t1.from_detection_id == dA2.id
    assert t1.to_camera_id == camB.id
    assert t1.to_detection_id == dB1.id
    assert t1.elapsed_seconds == 285.0  # 300s - 15s = 285s
    assert t1.distance_km is not None
    assert t1.distance_km > 0.5
    assert t1.plausibility_status == "PLAUSIBLE"

    # Transition 2: departure at Cam B (dB2) -> arrival at Cam C (dC1)
    assert t2.from_camera_id == camB.id
    assert t2.from_detection_id == dB2.id
    assert t2.to_camera_id == camC.id
    assert t2.to_detection_id == dC1.id
    assert t2.elapsed_seconds == 280.0  # 600s - 320s = 280s
    assert t2.distance_km is not None
    assert t2.plausibility_status == "PLAUSIBLE"


# ---------------------------------------------------------------------------
# 3. Distance Calculation & Haversine Accuracy (Section 8, 9)
# ---------------------------------------------------------------------------

def test_correlation_haversine_distance_known_coordinates(db_session: Session):
    """Verify calculated distance between known coordinates matches GISService.haversine_distance_km."""
    lat1, lon1 = 23.0305, 72.5714  # Income Tax Circle
    lat2, lon2 = 23.0450, 72.5200  # Drive-In Road
    expected_dist = round(GISService.haversine_distance_km(lat1, lon1, lat2, lon2), 3)

    loc1 = create_test_location(db_session, "Income Tax", lat1, lon1)
    loc2 = create_test_location(db_session, "Drive-In", lat2, lon2)
    cam1 = create_test_camera(db_session, "Cam-IT", loc1.id)
    cam2 = create_test_camera(db_session, "Cam-DI", loc2.id)

    plate = "GJ01DIST001"
    t1 = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 29, 12, 20, 0, tzinfo=timezone.utc)  # 20 min elapsed

    create_test_detection(db_session, cam1.id, plate, t1)
    create_test_detection(db_session, cam2.id, plate, t2)

    journey = CorrelationService.correlate_vehicle_journey(db_session, plate)

    assert journey.total_camera_transitions == 1
    transition = journey.transitions[0]
    assert transition.distance_km == expected_dist
    assert journey.total_distance_km == expected_dist


# ---------------------------------------------------------------------------
# 4. Missing Coordinates & Unmapped Cameras (Section 8, 24)
# ---------------------------------------------------------------------------

def test_correlation_unmapped_camera_distance_unknown_never_zero(db_session: Session):
    """Verify cameras with missing coordinates report distance=None (UNKNOWN), never 0.0 or 0,0."""
    loc_mapped = create_test_location(db_session, "Mapped Loc", 23.0225, 72.5714)
    cam_mapped = create_test_camera(db_session, "Cam-Mapped", loc_mapped.id)

    # Camera with Location having NULL coordinates
    loc_unmapped = Location(
        id=uuid.uuid4(),
        name="Unmapped Loc",
        latitude=None,
        longitude=None,
        city="Ahmedabad",
        state="Gujarat"
    )
    db_session.add(loc_unmapped)
    db_session.commit()
    cam_unmapped = create_test_camera(db_session, "Cam-Unmapped", loc_unmapped.id)

    plate = "GJ01UNMAPPED"
    t1 = datetime(2026, 9, 29, 9, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 29, 9, 15, 0, tzinfo=timezone.utc)

    create_test_detection(db_session, cam_mapped.id, plate, t1)
    create_test_detection(db_session, cam_unmapped.id, plate, t2)

    journey = CorrelationService.correlate_vehicle_journey(db_session, plate)

    assert journey.total_camera_transitions == 1
    t = journey.transitions[0]
    assert t.distance_km is None
    assert t.implied_speed_kmh is None
    assert t.plausibility_status == "PLAUSIBILITY_UNKNOWN"
    assert journey.correlation_status == "PARTIALLY_CORRELATED"
    assert len(journey.unmapped_waypoints) == 1
    assert journey.unmapped_waypoints[0].camera_id == cam_unmapped.id


# ---------------------------------------------------------------------------
# 5. Physical Plausibility & Speed Anomalies (Section 11, 12)
# ---------------------------------------------------------------------------

def test_correlation_speed_anomaly_flagged_for_excessive_speed(db_session: Session):
    """Verify transitions implying speed > 180 km/h are flagged as ANOMALY with has_speed_anomaly=True."""
    # Two cameras 50 km apart in Gujarat
    loc1 = create_test_location(db_session, "Ahmedabad East", 23.0225, 72.5714)
    loc2 = create_test_location(db_session, "Nadiad", 22.6916, 72.8634)
    cam1 = create_test_camera(db_session, "Cam-Ahm", loc1.id)
    cam2 = create_test_camera(db_session, "Cam-Nad", loc2.id)

    plate = "GJ01SPEEDANOM"
    t1 = datetime(2026, 9, 29, 14, 0, 0, tzinfo=timezone.utc)
    # Travelled ~47 km in 3 minutes (180s) -> ~940 km/h (impossible for a road vehicle)
    t2 = datetime(2026, 9, 29, 14, 3, 0, tzinfo=timezone.utc)

    create_test_detection(db_session, cam1.id, plate, t1)
    create_test_detection(db_session, cam2.id, plate, t2)

    journey = CorrelationService.correlate_vehicle_journey(db_session, plate)

    assert journey.total_camera_transitions == 1
    t = journey.transitions[0]
    assert t.implied_speed_kmh is not None
    assert t.implied_speed_kmh > 180.0
    assert t.plausibility_status == "ANOMALY"
    assert "exceeds maximum plausibility threshold" in (t.anomaly_reason or "")
    assert journey.has_speed_anomaly is True
    assert journey.correlation_status == "PARTIALLY_CORRELATED"


def test_correlation_simultaneous_distinct_location_detection_flagged_anomaly(db_session: Session):
    """Verify simultaneous detections at distinct camera locations (elapsed=0, distance>50m) are flagged ANOMALY."""
    loc1 = create_test_location(db_session, "Site 1", 23.0225, 72.5714)
    loc2 = create_test_location(db_session, "Site 2", 23.0500, 72.6000)
    cam1 = create_test_camera(db_session, "Cam-1", loc1.id)
    cam2 = create_test_camera(db_session, "Cam-2", loc2.id)

    plate = "GJ01CLONED"
    same_time = datetime(2026, 9, 29, 15, 0, 0, tzinfo=timezone.utc)

    create_test_detection(db_session, cam1.id, plate, same_time)
    create_test_detection(db_session, cam2.id, plate, same_time)

    journey = CorrelationService.correlate_vehicle_journey(db_session, plate)

    assert journey.total_camera_transitions == 1
    t = journey.transitions[0]
    assert t.elapsed_seconds == 0.0
    assert t.plausibility_status == "ANOMALY"
    assert "Simultaneous detection" in (t.anomaly_reason or "")
    assert journey.has_speed_anomaly is True


# ---------------------------------------------------------------------------
# 6. Single Camera / No Transitions & Empty History (Section 15, 19)
# ---------------------------------------------------------------------------

def test_correlation_single_camera_produces_no_transitions(db_session: Session):
    """Verify observations at a single camera produce NO_TRANSITION and 0 transitions."""
    loc = create_test_location(db_session, "Vastrapur", 23.0350, 72.5293)
    cam = create_test_camera(db_session, "Cam-Vastrapur", loc.id)

    plate = "GJ01SINGLE01"
    t1 = datetime(2026, 9, 29, 11, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 29, 11, 2, 0, tzinfo=timezone.utc)

    create_test_detection(db_session, cam.id, plate, t1)
    create_test_detection(db_session, cam.id, plate, t2)

    journey = CorrelationService.correlate_vehicle_journey(db_session, plate)

    assert journey.total_observations == 2
    assert journey.total_waypoints == 1
    assert journey.total_camera_transitions == 0
    assert journey.correlation_status == "NO_TRANSITION"
    assert journey.transitions == []


def test_correlation_empty_history_returns_insufficient_data(db_session: Session):
    """Verify searching an unobserved plate returns INSUFFICIENT_DATA without fabricating records."""
    journey = CorrelationService.correlate_vehicle_journey(db_session, "GJ01NEVEREXISTS")

    assert journey.plate_number == "GJ01NEVEREXISTS"
    assert journey.correlation_status == "INSUFFICIENT_DATA"
    assert journey.total_observations == 0
    assert journey.total_waypoints == 0
    assert journey.total_camera_transitions == 0
    assert journey.total_distance_km == 0.0
    assert journey.observations == []
    assert journey.waypoints == []
    assert journey.transitions == []
    assert journey.geojson_route is None


# ---------------------------------------------------------------------------
# 7. No Route Hallucination & GeoJSON LineString (Section 3, 13, 24)
# ---------------------------------------------------------------------------

def test_correlation_geojson_line_string_connects_cameras_only(db_session: Session):
    """Verify GeoJSON LineString connects camera coordinates only, explicitly indicating no route inference."""
    loc1 = create_test_location(db_session, "Site A", 23.0100, 72.5100)
    loc2 = create_test_location(db_session, "Site B", 23.0200, 72.5200)
    loc3 = create_test_location(db_session, "Site C", 23.0300, 72.5300)

    cam1 = create_test_camera(db_session, "Cam-A", loc1.id)
    cam2 = create_test_camera(db_session, "Cam-B", loc2.id)
    cam3 = create_test_camera(db_session, "Cam-C", loc3.id)

    plate = "GJ01NOINFER"
    base = datetime(2026, 9, 29, 16, 0, 0, tzinfo=timezone.utc)

    create_test_detection(db_session, cam1.id, plate, base)
    create_test_detection(db_session, cam2.id, plate, base + timedelta(minutes=5))
    create_test_detection(db_session, cam3.id, plate, base + timedelta(minutes=10))

    journey = CorrelationService.correlate_vehicle_journey(db_session, plate)

    assert journey.geojson_route is not None
    feat = journey.geojson_route
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] == "LineString"
    # GeoJSON coordinates order: [longitude, latitude]
    coords = feat["geometry"]["coordinates"]
    assert coords == [[72.5100, 23.0100], [72.5200, 23.0200], [72.5300, 23.0300]]

    # Strict non-hallucination property assertions
    props = feat["properties"]
    assert props["observation_type"] == "INTER_CAMERA_SEQUENCE"
    assert props["route_inference"] == "NONE_CAMERA_POINTS_ONLY"
    assert props["waypoints_count"] == 3


# ---------------------------------------------------------------------------
# 8. REST API Endpoints: /journey & /correlation (Section 22, 23)
# ---------------------------------------------------------------------------

def test_api_vehicle_journey_endpoint_success(client: TestClient, db_session: Session):
    """Verify GET /api/v1/vehicles/{plate}/journey returns 200 OK with full correlation payload."""
    loc1 = create_test_location(db_session, "Junction 1", 23.0200, 72.5500)
    loc2 = create_test_location(db_session, "Junction 2", 23.0300, 72.5600)
    cam1 = create_test_camera(db_session, "Cam-J1", loc1.id)
    cam2 = create_test_camera(db_session, "Cam-J2", loc2.id)

    plate = "GJ01APITEST"
    t1 = datetime(2026, 9, 29, 17, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 29, 17, 10, 0, tzinfo=timezone.utc)

    create_test_detection(db_session, cam1.id, plate, t1)
    create_test_detection(db_session, cam2.id, plate, t2)

    # 1. Primary endpoint /journey
    res = client.get(f"/api/v1/vehicles/{plate}/journey")
    assert res.status_code == 200
    data = res.json()
    assert data["plate_number"] == plate
    assert data["correlation_status"] == "CORRELATED"
    assert data["total_observations"] == 2
    assert data["total_camera_transitions"] == 1
    assert len(data["transitions"]) == 1
    assert data["geojson_route"] is not None

    # 2. Alias endpoint /correlation
    res_alias = client.get(f"/api/v1/vehicles/{plate}/correlation")
    assert res_alias.status_code == 200
    assert res_alias.json()["plate_number"] == plate


def test_api_vehicle_journey_invalid_time_range_returns_400(client: TestClient):
    """Verify invalid time window (start_time > end_time) returns HTTP 400 Bad Request."""
    res = client.get(
        "/api/v1/vehicles/GJ01VALIDATION/journey",
        params={
            "start_time": "2026-09-29T18:00:00Z",
            "end_time": "2026-09-29T10:00:00Z"
        }
    )
    assert res.status_code == 400
    assert "start_time must be prior to end_time" in res.json()["detail"]


def test_api_vehicle_journey_custom_max_speed_threshold(client: TestClient, db_session: Session):
    """Verify custom max_speed_kmh query parameter applies to transition plausibility evaluation."""
    loc1 = create_test_location(db_session, "Loc 1", 23.0000, 72.5000)
    loc2 = create_test_location(db_session, "Loc 2", 23.0100, 72.5100)
    cam1 = create_test_camera(db_session, "Cam-L1", loc1.id)
    cam2 = create_test_camera(db_session, "Cam-L2", loc2.id)

    plate = "GJ01SPEEDPARAM"
    t1 = datetime(2026, 9, 29, 18, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 29, 18, 1, 0, tzinfo=timezone.utc)  # 1 min for ~1.5 km (~90 km/h)

    create_test_detection(db_session, cam1.id, plate, t1)
    create_test_detection(db_session, cam2.id, plate, t2)

    # With default threshold 180 km/h -> PLAUSIBLE
    res_default = client.get(f"/api/v1/vehicles/{plate}/journey")
    assert res_default.status_code == 200
    assert res_default.json()["has_speed_anomaly"] is False

    # With strict custom threshold 50 km/h -> ANOMALY
    res_strict = client.get(f"/api/v1/vehicles/{plate}/journey?max_speed_kmh=50.0")
    assert res_strict.status_code == 200
    assert res_strict.json()["has_speed_anomaly"] is True
    assert res_strict.json()["transitions"][0]["plausibility_status"] == "ANOMALY"
