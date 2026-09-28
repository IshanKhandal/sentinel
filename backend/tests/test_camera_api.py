"""Automated integration tests for Camera REST API endpoints."""

import uuid
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.db.session import get_db
from backend.app.models.surveillance import Location, Camera
from backend.app.models.access import Department


def test_api_list_cameras_empty(test_engine):
    """Verify listing cameras when registry is empty."""
    client = TestClient(app)
    response = client.get("/api/v1/cameras")
    assert response.status_code == 200
    assert response.json() == []


def test_api_get_camera_not_found(test_engine):
    """Verify 404 error envelope when camera UUID does not exist."""
    client = TestClient(app)
    random_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/cameras/{random_id}")
    assert response.status_code == 404
    assert f"Camera with ID {random_id} not found" in response.json()["detail"]


def test_api_sync_returns_blocked_when_host_unconfigured(monkeypatch):
    """Verify that triggering sync when SENTINEL_STREAM_HOST is unset returns BLOCKED."""
    client = TestClient(app)
    # Ensure SENTINEL_STREAM_HOST is None
    from backend.app.core.config import settings
    monkeypatch.setattr(settings, "SENTINEL_STREAM_HOST", None)

    response = client.post("/api/v1/cameras/sync")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "BLOCKED"
    assert "UNKNOWN / BLOCKED" in data["message"]
    assert data["results"] is None


def test_health_check_endpoint():
    """Verify health endpoint accurately reports stream host configuration."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["operation_mode"] == "DEMO"
