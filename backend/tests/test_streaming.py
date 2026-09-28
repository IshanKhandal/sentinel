"""Automated unit and integration tests for Sentinel Stream Ingestion Subsystem.

Protocol Standards:
- docs/engineering-rules.md Rules 29, 30, 31.
- Stage 5 Directive Sections 6, 9, 10, 11, 12, 13, 17, 20, 21, 26, 27.
"""

import time
import uuid
import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.db.session import SessionLocal
from backend.app.models.access import Department
from backend.app.models.surveillance import Location, Camera
from backend.app.services.streaming.models import (
    StreamState,
    DecodedFrame,
    sanitize_stream_url
)
from backend.app.services.streaming.backoff import ExponentialBackoff
from backend.app.services.streaming.ring_buffer import FrameRingBuffer
from backend.app.services.streaming.worker import StreamWorker
from backend.app.services.streaming.manager import StreamManager


@pytest.fixture
def client(db_session):
    """FastAPI TestClient fixture with isolated test database."""
    from backend.app.db.session import get_db
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)



@pytest.fixture
def registered_camera(db_session):
    """Seed an isolated camera for streaming tests."""
    dept = db_session.query(Department).filter_by(code="GJ-TEST-STREAM").first()
    if not dept:
        dept = Department(name="Stream Test Department", code="GJ-TEST-STREAM")
        db_session.add(dept)
        db_session.commit()
        db_session.refresh(dept)

    loc = db_session.query(Location).filter_by(name="Stream Test Site").first()
    if not loc:
        loc = Location(
            name="Stream Test Site",
            latitude=23.0225,
            longitude=72.5714,
            city="Ahmedabad",
            state="Gujarat"
        )
        db_session.add(loc)
        db_session.commit()
        db_session.refresh(loc)

    cam = Camera(
        name="Sentinel-Test-Stream-01",
        rtsp_url="rtsp://unconfigured/stream/test01",
        stream_type="LIVE",
        status="OFFLINE",
        location_id=loc.id,
        department_id=dept.id,
        resolution="1920x1080",
        fps_target=10
    )
    db_session.add(cam)
    db_session.commit()
    db_session.refresh(cam)
    return cam


# ---------------------------------------------------------------------------
# 1. URL Credential Sanitization (Section 26, 32)
# ---------------------------------------------------------------------------

def test_sanitize_stream_url_masks_passwords():
    raw_url = "rtsp://police_admin:SuperSecret42@10.20.30.40:8554/stream/cam1"
    clean_url = sanitize_stream_url(raw_url)
    assert "SuperSecret42" not in clean_url
    assert clean_url == "rtsp://police_admin:***@10.20.30.40:8554/stream/cam1"


def test_sanitize_stream_url_unauthenticated():
    raw_url = "rtsp://10.20.30.40:8554/stream/cam1"
    clean_url = sanitize_stream_url(raw_url)
    assert clean_url == raw_url


def test_sanitize_stream_url_none():
    assert sanitize_stream_url(None) == "rtsp://unconfigured"


# ---------------------------------------------------------------------------
# 2. Exponential Backoff with Jitter (Section 13)
# ---------------------------------------------------------------------------

def test_exponential_backoff_progression_and_cap():
    backoff = ExponentialBackoff(base_delay=2.0, max_delay=30.0, factor=2.0, jitter_ratio=0.0)
    
    # attempt 0: 2.0 * (2^0) = 2.0
    d0 = backoff.next_delay()
    assert d0 == 2.0
    assert backoff.attempt == 1

    # attempt 1: 2.0 * (2^1) = 4.0
    d1 = backoff.next_delay()
    assert d1 == 4.0

    # attempt 2: 2.0 * (2^2) = 8.0
    d2 = backoff.next_delay()
    assert d2 == 8.0

    # attempt 3: 16.0
    d3 = backoff.next_delay()
    assert d3 == 16.0

    # attempt 4: 32.0 capped at 30.0
    d4 = backoff.next_delay()
    assert d4 == 30.0

    # reset
    backoff.reset()
    assert backoff.attempt == 0
    assert backoff.peek_delay() == 0.0


def test_exponential_backoff_jitter_bounds():
    backoff = ExponentialBackoff(base_delay=10.0, max_delay=30.0, factor=1.0, jitter_ratio=0.10)
    # With 10% jitter on 10.0s base: delay should fall within [9.0, 11.0]
    for _ in range(20):
        d = backoff.next_delay()
        assert 9.0 <= d <= 11.0


# ---------------------------------------------------------------------------
# 3. Bounded Ring Buffer & Drop Telemetry (Section 12)
# ---------------------------------------------------------------------------

def test_ring_buffer_fifo_mechanics():
    buf = FrameRingBuffer(capacity=3)
    frame1 = DecodedFrame(frame_index=1, camera_id="c1", pts_ms=100.0, data=np.zeros((10, 10, 3)), width=10, height=10, monotonic_ts=1.0)
    frame2 = DecodedFrame(frame_index=2, camera_id="c1", pts_ms=200.0, data=np.zeros((10, 10, 3)), width=10, height=10, monotonic_ts=1.1)

    assert buf.push(frame1) is True
    assert buf.push(frame2) is True
    assert buf.size == 2
    assert buf.dropped_count == 0

    popped = buf.pop(timeout=0.1)
    assert popped is not None
    assert popped.frame_index == 1
    assert buf.size == 1


def test_ring_buffer_drops_oldest_under_backpressure():
    buf = FrameRingBuffer(capacity=2)
    f1 = DecodedFrame(frame_index=1, camera_id="c1", pts_ms=100.0, data=np.zeros((10, 10, 3)), width=10, height=10, monotonic_ts=1.0)
    f2 = DecodedFrame(frame_index=2, camera_id="c1", pts_ms=200.0, data=np.zeros((10, 10, 3)), width=10, height=10, monotonic_ts=1.1)
    f3 = DecodedFrame(frame_index=3, camera_id="c1", pts_ms=300.0, data=np.zeros((10, 10, 3)), width=10, height=10, monotonic_ts=1.2)

    buf.push(f1)
    buf.push(f2)
    assert buf.size == 2
    assert buf.dropped_count == 0

    # 3rd push exceeds capacity 2 -> drops oldest (f1)
    buf.push(f3)
    assert buf.size == 2
    assert buf.dropped_count == 1

    # First pop should yield f2, then f3
    popped = buf.pop(timeout=0.1)
    assert popped.frame_index == 2
    popped2 = buf.pop(timeout=0.1)
    assert popped2.frame_index == 3


def test_ring_buffer_peek_latest_and_clear():
    buf = FrameRingBuffer(capacity=5)
    f1 = DecodedFrame(frame_index=1, camera_id="c1", pts_ms=100.0, data=np.zeros((10, 10, 3)), width=10, height=10, monotonic_ts=1.0)
    buf.push(f1)

    peeked = buf.peek_latest()
    assert peeked is not None
    assert peeked.frame_index == 1
    assert buf.size == 1  # Not removed

    buf.clear()
    assert buf.size == 0
    assert buf.peek_latest() is None


# ---------------------------------------------------------------------------
# 4. Stream Worker Mechanics (Section 9, 10, 11, 14, 17)
# ---------------------------------------------------------------------------

def test_worker_halts_on_unconfigured_host():
    worker = StreamWorker(
        camera_id="cam-unconf",
        stream_url="rtsp://unconfigured/stream/cam1"
    )
    worker.start()
    time.sleep(0.1)
    worker.stop(timeout=1.0)

    info = worker.get_session_info()
    assert info.connection_state == "OFFLINE" or info.connection_state == "NOT_CONFIGURED"
    assert info.frames_received == 0


def test_worker_synthetic_frame_decoding_and_pts():
    """Verify worker PTS extraction, irregular interval tolerance, and loop discontinuity."""
    worker = StreamWorker(
        camera_id="cam-synthetic",
        stream_url="rtsp://mock-host:8554/stream/test"
    )

    # Mock cv2.VideoCapture to simulate frames and PTS
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True

    # Simulate sequence of frames:
    # Frame 1: PTS 1000.0 ms
    # Frame 2: PTS 1066.0 ms
    # Frame 3: PTS 1300.0 ms (irregular interval)
    # Frame 4: PTS 0.0 ms (scene loop discontinuity jump!)
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    read_returns = [
        (True, dummy_frame),
        (True, dummy_frame),
        (True, dummy_frame),
        (True, dummy_frame),
        (False, None)  # Stream ends
    ]
    mock_cap.read.side_effect = read_returns

    pts_values = [1000.0, 1066.0, 1300.0, 0.0, 0.0]
    mock_cap.get.side_effect = lambda prop: pts_values.pop(0) if pts_values else 0.0

    with patch("cv2.VideoCapture", return_value=mock_cap):
        worker.start()
        time.sleep(0.3)
        worker.stop(timeout=1.0)

    info = worker.get_session_info()
    # At least 4 frames decoded
    assert info.frames_received >= 4
    assert info.resolution == "640x480"
    assert info.codec == "H.264"
    # Latest frame peekable in ring buffer
    latest = worker.ring_buffer.peek_latest()
    assert latest is not None
    assert latest.width == 640
    assert latest.height == 480


# ---------------------------------------------------------------------------
# 5. Stream Manager Lifecycle & Controlled Activation (Section 20, 21)
# ---------------------------------------------------------------------------

def test_stream_manager_lifecycle():
    manager = StreamManager()
    cam_id = str(uuid.uuid4())

    # Controlled activation: start
    session = manager.start_stream(
        camera_id=cam_id,
        rtsp_url="rtsp://unconfigured/stream/1"
    )
    assert session.camera_id == cam_id
    assert session.connection_state in ("NOT_CONFIGURED", "CONNECTING", "OFFLINE")

    active = manager.list_active_streams()
    assert any(s.camera_id == cam_id for s in active)

    # Stop
    stopped = manager.stop_stream(cam_id)
    assert stopped is True
    assert manager.get_stream_session(cam_id) is None


def test_stream_manager_snapshot_generation():
    manager = StreamManager()
    cam_id = str(uuid.uuid4())

    # Pre-populate a worker's ring buffer with a valid frame
    worker = StreamWorker(camera_id=cam_id, stream_url="rtsp://test/1")
    test_img = np.zeros((100, 100, 3), dtype=np.uint8)
    # Draw a colored square so JPEG encoding produces valid image
    test_img[20:80, 20:80] = [0, 255, 0]

    worker.ring_buffer.push(DecodedFrame(
        frame_index=1,
        camera_id=cam_id,
        pts_ms=100.0,
        data=test_img,
        width=100,
        height=100,
        monotonic_ts=time.monotonic()
    ))
    manager._workers[cam_id] = worker

    jpeg_bytes = manager.get_snapshot_jpeg(cam_id)
    assert jpeg_bytes is not None
    assert len(jpeg_bytes) > 0
    # Valid JPEG magic header 0xFFD8
    assert jpeg_bytes[:2] == b"\xff\xd8"

    manager.stop_stream(cam_id)


# ---------------------------------------------------------------------------
# 6. REST API Integration (docs/api-contract.md)
# ---------------------------------------------------------------------------

def test_api_list_active_streams(client):
    response = client.get("/api/v1/streams")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_get_stream_status_registered_camera(client, registered_camera):
    response = client.get(f"/api/v1/streams/{registered_camera.id}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["camera_id"] == str(registered_camera.id)
    assert data["connection_state"] == "NOT_CONFIGURED"
    assert "rtsp://unconfigured" in data["stream_url"]


def test_api_get_stream_status_unknown_camera(client):
    fake_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/streams/{fake_id}/status")
    assert response.status_code == 404


def test_api_start_stream_unconfigured_host_returns_blocked(client, registered_camera):
    response = client.post(f"/api/v1/streams/{registered_camera.id}/start")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "BLOCKED"
    assert "SENTINEL_STREAM_HOST is unset" in data["message"]


def test_api_stop_inactive_stream(client):
    fake_id = str(uuid.uuid4())
    response = client.post(f"/api/v1/streams/{fake_id}/stop")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "NOT_RUNNING"


def test_api_get_snapshot_404_when_inactive(client, registered_camera):
    response = client.get(f"/api/v1/streams/{registered_camera.id}/snapshot")
    assert response.status_code == 404
