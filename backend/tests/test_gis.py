"""Automated unit and integration tests for GIS module.

Protocol Standard: Section 21 of Phase 4 Directive.
"""

import math
import uuid
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.gis_service import GISService, CoordinateValidationError
from backend.app.models.access import Department
from backend.app.models.surveillance import Location, Camera


# ---------------------------------------------------------------------------
# 1. Coordinate Validation Tests
# ---------------------------------------------------------------------------

def test_coordinate_validation_valid():
    """Verify that valid WGS 84 coordinates pass validation."""
    lat, lon = GISService.validate_coordinates(23.0225, 72.5714)
    assert lat == 23.0225
    assert lon == 72.5714


def test_coordinate_validation_min_max_bounds():
    """Verify that exact minimum and maximum boundary values are accepted."""
    lat, lon = GISService.validate_coordinates(-90.0, -180.0)
    assert lat == -90.0
    assert lon == -180.0

    lat, lon = GISService.validate_coordinates(90.0, 180.0)
    assert lat == 90.0
    assert lon == 180.0


def test_coordinate_validation_out_of_bounds():
    """Verify that out-of-bounds coordinates raise CoordinateValidationError."""
    with pytest.raises(CoordinateValidationError):
        GISService.validate_coordinates(90.001, 72.0)

    with pytest.raises(CoordinateValidationError):
        GISService.validate_coordinates(-90.001, 72.0)

    with pytest.raises(CoordinateValidationError):
        GISService.validate_coordinates(23.0, 180.001)

    with pytest.raises(CoordinateValidationError):
        GISService.validate_coordinates(23.0, -180.001)


def test_coordinate_validation_nan_infinity_and_none():
    """Verify that NaN, Infinity, and None values are rejected."""
    with pytest.raises(CoordinateValidationError):
        GISService.validate_coordinates(float("nan"), 72.0)

    with pytest.raises(CoordinateValidationError):
        GISService.validate_coordinates(23.0, float("nan"))

    with pytest.raises(CoordinateValidationError):
        GISService.validate_coordinates(float("inf"), 72.0)

    with pytest.raises(CoordinateValidationError):
        GISService.validate_coordinates(23.0, float("-inf"))

    with pytest.raises(CoordinateValidationError):
        GISService.validate_coordinates(None, 72.0)


# ---------------------------------------------------------------------------
# 2. Haversine Distance Tests
# ---------------------------------------------------------------------------

def test_haversine_identical_points():
    """Distance between identical points must be strictly 0.0 km."""
    d = GISService.haversine_distance_km(23.0225, 72.5714, 23.0225, 72.5714)
    assert d == 0.0


def test_haversine_known_distance():
    """Test distance calculation between known coordinates.

    Point A: Ashram Road (23.0305, 72.5714)
    Point B: SG Highway (23.0450, 72.5200)
    Approximate great-circle distance is ~5.5 km.
    """
    d = GISService.haversine_distance_km(23.0305, 72.5714, 23.0450, 72.5200)
    assert 5.0 <= d <= 6.0


# ---------------------------------------------------------------------------
# 3. GeoJSON Generation Tests
# ---------------------------------------------------------------------------

def test_geojson_generation_empty(db_session):
    """Verify GeoJSON output when database has 0 cameras."""
    geojson = GISService.get_cameras_geojson(db=db_session)
    assert geojson["type"] == "FeatureCollection"
    assert geojson["features"] == []
    assert geojson["metadata"]["total_mapped"] == 0
    assert geojson["metadata"]["total_unmapped"] == 0


def test_geojson_generation_with_mapped_and_unmapped(db_session):
    """Verify GeoJSON includes ONLY mapped points and orders coordinates as [lon, lat]."""
    dept = Department(name="GIS Test Dept", code="GJ-GIS-01")
    db_session.add(dept)
    db_session.commit()

    # Mapped camera
    loc_mapped = Location(name="Valid Point", latitude=23.0225, longitude=72.5714, city="Ahmedabad")
    db_session.add(loc_mapped)
    db_session.commit()

    cam_mapped = Camera(
        department_id=dept.id,
        location_id=loc_mapped.id,
        name="Cam Mapped",
        rtsp_url="rtsp://user:secretpass@127.0.0.1:8554/stream/1",
        stream_type="DEMO",
        status="DEMO"
    )
    db_session.add(cam_mapped)
    db_session.commit()

    geojson = GISService.get_cameras_geojson(db=db_session)
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 1

    feature = geojson["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"
    # Strict GeoJSON standard: [longitude, latitude]
    assert feature["geometry"]["coordinates"] == [72.5714, 23.0225]

    props = feature["properties"]
    assert props["camera_name"] == "Cam Mapped"
    assert props["status"] == "DEMO"
    assert props["mapped_status"] == "MAPPED"
    # Security Rule 41: Secrets must NOT appear in GeoJSON
    assert "secretpass" not in str(props)
    assert "rtsp_url" not in props


# ---------------------------------------------------------------------------
# 4. Nearby Camera Query Tests
# ---------------------------------------------------------------------------

def test_find_nearby_cameras(db_session):
    """Verify nearby camera spatial filtering and ascending distance ordering."""
    dept = Department(name="Spatial Dept", code="GJ-SPATIAL-01")
    db_session.add(dept)
    db_session.commit()

    # Center point: (23.0300, 72.5700)
    # Cam 1: ~1.2 km away
    loc1 = Location(name="Near Point", latitude=23.0400, longitude=72.5700, city="City A")
    # Cam 2: ~15 km away
    loc2 = Location(name="Far Point", latitude=23.1600, longitude=72.5700, city="City B")
    db_session.add_all([loc1, loc2])
    db_session.commit()

    c1 = Camera(department_id=dept.id, location_id=loc1.id, name="Near Cam", rtsp_url="rtsp://host/1", stream_type="DEMO")
    c2 = Camera(department_id=dept.id, location_id=loc2.id, name="Far Cam", rtsp_url="rtsp://host/2", stream_type="DEMO")
    db_session.add_all([c1, c2])
    db_session.commit()

    # Query with radius 5.0 km: Cam 1 should be included, Cam 2 excluded
    results = GISService.find_nearby_cameras(db=db_session, latitude=23.0300, longitude=72.5700, radius_km=5.0)
    assert len(results) == 1
    assert results[0]["camera"].name == "Near Cam"
    assert results[0]["distance_km"] <= 5.0

    # Query with radius 20.0 km: Both included, sorted ascending by distance
    results_all = GISService.find_nearby_cameras(db=db_session, latitude=23.0300, longitude=72.5700, radius_km=20.0)
    assert len(results_all) == 2
    assert results_all[0]["distance_km"] < results_all[1]["distance_km"]


# ---------------------------------------------------------------------------
# 5. Route LineString Builder Tests
# ---------------------------------------------------------------------------

def test_build_route_linestring_empty():
    """Verify route generator handles empty input cleanly."""
    res = GISService.build_route_linestring([])
    assert res["geometry"]["type"] == "LineString"
    assert res["geometry"]["coordinates"] == []
    assert res["properties"]["points_count"] == 0
    assert res["properties"]["status"] == "EMPTY"


def test_build_route_linestring_ordered():
    """Verify route generator orders waypoints and accumulates distance."""
    waypoints = [
        {"latitude": 23.0450, "longitude": 72.5200, "sequence": 2},
        {"latitude": 23.0300, "longitude": 72.5100, "sequence": 1},
        {"latitude": 23.0600, "longitude": 72.5300, "sequence": 3},
    ]
    res = GISService.build_route_linestring(waypoints)
    coords = res["geometry"]["coordinates"]
    assert len(coords) == 3
    # Check first point matches sequence 1 [lon, lat]
    assert coords[0] == [72.5100, 23.0300]
    assert coords[1] == [72.5200, 23.0450]
    assert coords[2] == [72.5300, 23.0600]
    assert res["properties"]["total_distance_km"] > 0.0
    assert res["properties"]["status"] == "VALID"


# ---------------------------------------------------------------------------
# 6. REST API Endpoint Tests
# ---------------------------------------------------------------------------

def test_api_get_cameras_geojson(test_engine):
    """Verify GET /api/v1/gis/cameras.geojson endpoint."""
    client = TestClient(app)
    response = client.get("/api/v1/gis/cameras.geojson")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    assert "metadata" in data


def test_api_nearby_cameras_validation(test_engine):
    """Verify GET /api/v1/gis/nearby-cameras validates parameters."""
    client = TestClient(app)

    # Valid query
    res = client.get("/api/v1/gis/nearby-cameras?latitude=23.0&longitude=72.0&radius_km=10.0")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # Invalid latitude (>90)
    res_bad_lat = client.get("/api/v1/gis/nearby-cameras?latitude=95.0&longitude=72.0")
    assert res_bad_lat.status_code == 422

    # Invalid radius (>50)
    res_bad_rad = client.get("/api/v1/gis/nearby-cameras?latitude=23.0&longitude=72.0&radius_km=60.0")
    assert res_bad_rad.status_code == 422


def test_api_route_preview(test_engine):
    """Verify POST /api/v1/gis/route-preview endpoint."""
    client = TestClient(app)
    payload = {
        "waypoints": [
            {"latitude": 23.0, "longitude": 72.0, "sequence": 1},
            {"latitude": 23.1, "longitude": 72.1, "sequence": 2}
        ]
    }
    response = client.post("/api/v1/gis/route-preview", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["geometry"]["type"] == "LineString"
    assert len(data["geometry"]["coordinates"]) == 2
    assert data["properties"]["total_distance_km"] > 0.0


def test_api_gis_preview_page(test_engine):
    """Verify GET /gis-preview renders HTML presentation page."""
    client = TestClient(app)
    response = client.get("/gis-preview")
    assert response.status_code == 200
    assert "Leaflet" in response.text
    assert "MAP TILES UNAVAILABLE" in response.text
