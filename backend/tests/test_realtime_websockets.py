"""Comprehensive test suite for Sentinel Stage 14 Realtime WebSockets.

Protocol Standards:
- docs/realtime-contract.md
- Stage 14 Directive Sections 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 22, 23, 24, 25
"""

import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.core.config import settings
from backend.app.core.security import create_access_token
from backend.app.core.permissions import ROLE_INVESTIGATOR
from backend.app.db.session import get_db
from backend.app.models.access import Department, Role, User
from backend.app.models.surveillance import Location, Camera
from backend.app.models.intelligence import Detection, Vehicle
from backend.app.models.watchlists import Watchlist, WatchlistEntry
from backend.app.services.realtime.envelope import (
    EventType,
    RealtimeEventEnvelope,
    SUPPORTED_TOPICS,
)
from backend.app.services.realtime.event_bus import event_bus
from backend.app.services.realtime.manager import websocket_manager


@pytest.fixture(autouse=True)
def clean_websocket_state():
    """Ensure websocket manager and connections are clean before and after each test."""
    # Reset active connections
    websocket_manager._connections.clear()
    websocket_manager.metrics.active_connections = 0
    yield
    websocket_manager._connections.clear()
    websocket_manager.metrics.active_connections = 0


# ============================================================================
# 1. Connection Lifecycle & Handshake Tests
# ============================================================================

def test_websocket_connect_and_handshake():
    """Verify client connects to /api/v1/ws/events and receives connection.acknowledged."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        # First message must be the connection acknowledgment packet
        data = websocket.receive_json()
        assert data["event"] == "connection.acknowledged"
        assert "session_id" in data
        assert data["session_id"].startswith("ws-sess-")
        assert "timestamp" in data


def test_websocket_alias_endpoint():
    """Verify fallback alias endpoint /api/v1/ws functions identically."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws") as websocket:
        data = websocket.receive_json()
        assert data["event"] == "connection.acknowledged"
        assert "session_id" in data


def test_websocket_clean_disconnect_and_cleanup():
    """Verify client disconnection removes session from active connections registry."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        data = websocket.receive_json()
        session_id = data["session_id"]
        assert session_id in websocket_manager._connections
        assert websocket_manager.metrics.active_connections == 1

    # Once context exits, connection must be cleaned up
    assert session_id not in websocket_manager._connections
    assert websocket_manager.metrics.active_connections == 0
    assert websocket_manager.metrics.disconnects >= 1


# ============================================================================
# 2. Authentication Boundary Tests (Stage 14 -> Stage 15 boundary)
# ============================================================================

def test_websocket_auth_explicit_invalid_token_rejected():
    """Verify explicit invalid or expired token is rejected with WebSocket close code 4401."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/api/v1/ws/events?token=invalid"):
            pass
    assert excinfo.value.code == 4401


def test_websocket_auth_valid_token_accepted():
    """Verify connection with valid token succeeds."""
    token = create_access_token({
        "sub": "00000000-0000-0000-0000-000000000001",
        "badge": "TEST_BADGE",
        "role": ROLE_INVESTIGATOR,
        "dept": "CYBER_CRIME",
    })
    client = TestClient(app)
    with client.websocket_connect(f"/api/v1/ws/events?token={token}") as websocket:
        data = websocket.receive_json()
        assert data["event"] == "connection.acknowledged"


# ============================================================================
# 3. Heartbeat / Keepalive Ping-Pong Tests
# ============================================================================

def test_websocket_ping_pong():
    """Verify client ping yields immediate server pong with UTC timestamp."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        _ = websocket.receive_json()  # Handshake ack

        # Send ping
        websocket.send_json({"type": "ping"})
        response = websocket.receive_json()
        assert response["type"] == "pong"
        assert "timestamp" in response


def test_websocket_stale_connection_reaper():
    """Verify check_stale_connections detects and terminates inactive sessions."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        data = websocket.receive_json()
        session_id = data["session_id"]
        conn = websocket_manager._connections[session_id]

        # Simulate last heartbeat was 60 seconds ago (exceeding 45s threshold)
        conn.last_heartbeat = time.monotonic() - 60.0

        # Run reaper check
        reaped = asyncio.run(websocket_manager.check_stale_connections(timeout_seconds=45.0))
        assert session_id in reaped
        assert session_id not in websocket_manager._connections


# ============================================================================
# 4. Canonical Event Envelope & Mode Preservation Tests
# ============================================================================

def test_event_envelope_structure_and_modes():
    """Verify canonical envelope contains all required fields and preserves TEST/DEMO/LIVE."""
    # Test envelope in TEST mode
    test_env = RealtimeEventEnvelope.create(
        event_type=EventType.ALERT_CREATED.value,
        source="test_runner",
        mode="TEST",
        data={"plate_number": "GJ01AB1234", "severity": "CRITICAL"},
    )
    env_dict = test_env.to_dict()
    assert env_dict["event_type"] == "alert.created"
    assert env_dict["event"] == "alert.created"
    assert env_dict["mode"] == "TEST"
    assert env_dict["source"] == "test_runner"
    assert env_dict["data"]["plate_number"] == "GJ01AB1234"
    assert "event_id" in env_dict
    assert "timestamp" in env_dict
    assert test_env.is_critical is True

    # Non-critical event
    non_crit = RealtimeEventEnvelope.create(
        event_type=EventType.CAMERA_STATUS_CHANGED.value,
        source="stream_manager",
        mode="DEMO",
        data={"camera_id": "cam-1", "current_status": "ONLINE"},
    )
    assert non_crit.is_critical is False
    assert non_crit.mode == "DEMO"


# ============================================================================
# 5. Event Broadcasting & Subscription Filtering Tests
# ============================================================================

def test_broadcast_reaches_subscribed_client():
    """Verify published event envelope is received by connected client."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        _ = websocket.receive_json()  # Handshake ack

        # Dispatch an alert.created event
        envelope = RealtimeEventEnvelope.create(
            event_type=EventType.ALERT_CREATED.value,
            source="alert_engine",
            mode="DEMO",
            data={
                "alert_id": "a1b2c3d4-0000-0000-0000-000000000001",
                "severity": "CRITICAL",
                "plate_number": "GJ01AB1234",
            }
        )
        asyncio.run(websocket_manager.broadcast(envelope))

        received = websocket.receive_json()
        assert received["event"] == "alert.created"
        assert received["event_type"] == "alert.created"
        assert received["source"] == "alert_engine"
        assert received["data"]["plate_number"] == "GJ01AB1234"


def test_subscription_filtering_topic_isolation():
    """Verify client subscribed only to 'cameras' does NOT receive 'alerts' events."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        _ = websocket.receive_json()  # Handshake ack

        # Client explicitly subscribes only to 'cameras'
        websocket.send_json({"action": "subscribe", "topics": ["cameras"]})
        ack = websocket.receive_json()
        assert ack["event"] == "subscription.acknowledged"

        # Also unsubscribe from 'all'
        websocket.send_json({"action": "unsubscribe", "topics": ["all"]})
        _ = websocket.receive_json()

        # Broadcast an alert event
        alert_env = RealtimeEventEnvelope.create(
            event_type=EventType.ALERT_CREATED.value,
            source="alert_engine",
            mode="TEST",
            data={"plate_number": "GJ01CD5678"}
        )
        asyncio.run(websocket_manager.broadcast(alert_env))

        # Broadcast a camera event
        cam_env = RealtimeEventEnvelope.create(
            event_type=EventType.CAMERA_STATUS_CHANGED.value,
            source="stream_manager",
            mode="TEST",
            data={"camera_id": "c1", "current_status": "ONLINE"}
        )
        asyncio.run(websocket_manager.broadcast(cam_env))

        # Client must receive ONLY the camera event, NOT the alert event
        received = websocket.receive_json()
        assert received["event"] == "camera.status_changed"
        assert received["data"]["camera_id"] == "c1"


def test_invalid_subscription_topic_rejected():
    """Verify invalid subscription topics are rejected with structured error."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        _ = websocket.receive_json()  # Handshake ack

        websocket.send_json({"action": "subscribe", "topics": ["unsupported_topic_xyz"]})
        resp = websocket.receive_json()
        assert resp["error"] == "INVALID_SUBSCRIPTION"
        assert "unsupported_topic_xyz" in resp["message"]


# ============================================================================
# 6. Client Message Validation & Error Handling
# ============================================================================

def test_malformed_json_handling():
    """Verify malformed non-JSON frame returns structured MALFORMED_JSON error."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        _ = websocket.receive_json()  # Handshake ack

        websocket.send_text("THIS IS NOT JSON {{{")
        resp = websocket.receive_json()
        assert resp["error"] == "MALFORMED_JSON"
        assert websocket_manager.metrics.malformed_messages >= 1


def test_oversized_payload_handling():
    """Verify payload exceeding size limit is rejected with PAYLOAD_TOO_LARGE."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        _ = websocket.receive_json()  # Handshake ack

        oversized_str = json.dumps({"type": "ping", "junk": "X" * 70000})
        websocket.send_text(oversized_str)
        resp = websocket.receive_json()
        assert resp["error"] == "PAYLOAD_TOO_LARGE"


def test_unknown_action_handling():
    """Verify unsupported action returns structured UNKNOWN_ACTION error."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        _ = websocket.receive_json()  # Handshake ack

        websocket.send_json({"action": "unsupported_action_123"})
        resp = websocket.receive_json()
        assert resp["error"] == "UNKNOWN_ACTION"


# ============================================================================
# 7. Backpressure & Bounded Queue Handling
# ============================================================================

def test_backpressure_bounded_queue_and_critical_prioritization():
    """Verify slow consumer backpressure sheds non-critical events while prioritizing critical alerts."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        data = websocket.receive_json()
        session_id = data["session_id"]
        conn = websocket_manager._connections[session_id]

        # Stop worker temporarily to simulate frozen/slow consumer queue filling up
        if conn._send_task and not conn._send_task.done():
            conn._send_task.cancel()

        # Re-initialize a tiny queue of size 3 to test boundary behavior deterministically
        conn.queue = asyncio.Queue(maxsize=3)

        # 1. Fill queue with non-critical events
        env1 = RealtimeEventEnvelope.create(
            event_type=EventType.DETECTION_CREATED.value,
            source="pipeline",
            mode="TEST",
            data={"id": 1}
        )
        env2 = RealtimeEventEnvelope.create(
            event_type=EventType.CAMERA_STATUS_CHANGED.value,
            source="pipeline",
            mode="TEST",
            data={"id": 2}
        )
        env3 = RealtimeEventEnvelope.create(
            event_type=EventType.SYSTEM_HEALTH_CHANGED.value,
            source="pipeline",
            mode="TEST",
            data={"id": 3}
        )

        assert conn.enqueue(env1) is True
        assert conn.enqueue(env2) is True
        assert conn.enqueue(env3) is True
        assert conn.queue.full() is True

        # 2. Enqueue another non-critical event — must be DROPPED
        env_dropped = RealtimeEventEnvelope.create(
            event_type=EventType.DETECTION_CREATED.value,
            source="pipeline",
            mode="TEST",
            data={"id": 4}
        )
        assert conn.enqueue(env_dropped) is False
        assert conn._dropped_count >= 1

        # 3. Enqueue CRITICAL event (alert.created) — must evict non-critical to fit
        crit_env = RealtimeEventEnvelope.create(
            event_type=EventType.ALERT_CREATED.value,
            source="alert_engine",
            mode="TEST",
            data={"alert_id": "crit-001"}
        )
        assert conn.enqueue(crit_env) is True
        assert conn.queue.full() is True


# ============================================================================
# 8. Observability Metrics Endpoint Tests
# ============================================================================

def test_websocket_metrics_endpoint():
    """Verify /api/v1/ws/metrics REST endpoint returns accurate operational metrics."""
    client = TestClient(app)
    response = client.get("/api/v1/ws/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ONLINE"
    assert "metrics" in body
    metrics = body["metrics"]
    assert "active_connections" in metrics
    assert "connection_attempts" in metrics
    assert "events_published" in metrics
    assert "events_delivered" in metrics
    assert "dropped_events" in metrics


# ============================================================================
# 9. End-to-End Realtime Integration Flow Tests
# ============================================================================

def test_end_to_end_event_bus_to_websocket_delivery():
    """Verify publishing to global event_bus delivers event to WebSocket connected client."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as websocket:
        _ = websocket.receive_json()  # Handshake ack

        # Dispatch through global event bus
        envelope = RealtimeEventEnvelope.create(
            event_type=EventType.SYSTEM_HEALTH_CHANGED.value,
            source="health_monitor",
            mode="TEST",
            data={
                "overall_status": "HEALTHY",
                "subsystem": "INFERENCE",
                "issue": "All models operational",
            }
        )
        asyncio.run(event_bus.publish(envelope))

        received = websocket.receive_json()
        assert received["event"] == "system.health_changed"
        assert received["source"] == "health_monitor"
        assert received["mode"] == "TEST"
        assert received["data"]["overall_status"] == "HEALTHY"


def test_concurrent_clients_independent_delivery():
    """Verify multiple connected clients receive independent copies of broadcast events."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as ws1:
        ack1 = ws1.receive_json()
        with client.websocket_connect("/api/v1/ws/events") as ws2:
            ack2 = ws2.receive_json()
            assert ack1["session_id"] != ack2["session_id"]
            assert websocket_manager.metrics.active_connections == 2

            # Dispatch an event
            env = RealtimeEventEnvelope.create(
                event_type=EventType.ALERT_CREATED.value,
                source="test_runner",
                mode="TEST",
                data={"alert_id": "test-multicast-123"}
            )
            asyncio.run(websocket_manager.broadcast(env))

            # Both clients must receive the event independently
            recv1 = ws1.receive_json()
            recv2 = ws2.receive_json()
            assert recv1["data"]["alert_id"] == "test-multicast-123"
            assert recv2["data"]["alert_id"] == "test-multicast-123"


def test_client_abrupt_disconnect_isolation():
    """Verify that an abrupt disconnect of one client does not impede delivery to remaining clients."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/events") as ws_healthy:
        _ = ws_healthy.receive_json()

        # Connect and immediately exit second client
        with client.websocket_connect("/api/v1/ws/events") as ws_exiting:
            _ = ws_exiting.receive_json()

        # ws_exiting is now closed
        assert websocket_manager.metrics.active_connections == 1

        # Broadcast event
        env = RealtimeEventEnvelope.create(
            event_type=EventType.CAMERA_STATUS_CHANGED.value,
            source="test_runner",
            mode="TEST",
            data={"camera_id": "cam-surviving", "current_status": "ONLINE"}
        )
        asyncio.run(websocket_manager.broadcast(env))

        recv = ws_healthy.receive_json()
        assert recv["data"]["camera_id"] == "cam-surviving"


def test_end_to_end_alert_evaluation_and_acknowledgment_over_websocket(db_session: Session):
    """Verify full end-to-end flow: evaluate-matches generates alert.created over WebSocket,
    and acknowledge_alert generates alert.updated over WebSocket.
    """
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        # 1. Seed surveillance and detection fixtures
        dept = Department(id=uuid.uuid4(), name="Traffic Police WS", code="TP_WS_01")
        role = Role(id=uuid.uuid4(), name="OfficerRoleWS", description="WS Test Officer")
        db_session.add_all([dept, role])
        db_session.flush()

        user = User(
            id=uuid.uuid4(),
            department_id=dept.id,
            role_id=role.id,
            badge_number="WS_OFFICER_01",
            full_name="WS Officer Singh",
            email="ws_singh@gujaratpolice.gov.in",
            hashed_password="mock_hash",
            is_active=True,
        )
        loc = Location(
            id=uuid.uuid4(),
            name="Ring Road Junction WS",
            latitude=23.0300,
            longitude=72.5800,
            city="Ahmedabad",
            state="Gujarat"
        )
        db_session.add_all([user, loc])
        db_session.flush()

        cam = Camera(
            id=uuid.uuid4(),
            location_id=loc.id,
            department_id=dept.id,
            name="CAM-WS-01",
            rtsp_url="rtsp://sentinel.local/cam_ws_01",
            stream_type="PROCESSED",
            status="ONLINE"
        )
        db_session.add(cam)
        db_session.flush()

        vp = Vehicle(
            id=uuid.uuid4(),
            plate_number="GJ01WS9999",
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc)
        )
        db_session.add(vp)
        db_session.flush()

        detection = Detection(
            id=uuid.uuid4(),
            camera_id=cam.id,
            vehicle_id=vp.id,
            plate_number="GJ01WS9999",
            raw_text="GJ01WS9999",
            vehicle_type="CAR",
            confidence_plate=0.95,
            bbox_vehicle=[50, 50, 250, 250],
            bbox_plate=[100, 150, 200, 180],
            snapshot_path="snapshots/cam01/ws_snap.jpg",
            is_demo=True,
            detected_at=datetime.now(timezone.utc)
        )
        db_session.add(detection)
        db_session.flush()

        wl = Watchlist(
            id=uuid.uuid4(),
            name="Stolen Luxury Vehicles",
            category="STOLEN",
            severity="CRITICAL",
            is_active=True,
            created_by_user_id=user.id,
        )
        db_session.add(wl)
        db_session.flush()

        entry = WatchlistEntry(
            id=uuid.uuid4(),
            watchlist_id=wl.id,
            plate_number="GJ01WS9999",
            is_active=True,
        )
        db_session.add(entry)
        db_session.commit()

        # 2. Connect WebSocket client
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/events") as websocket:
            handshake = websocket.receive_json()
            assert handshake["event"] == "connection.acknowledged"

            # 3. Post evaluate-matches request
            match_payload = [
                {
                    "match_id": str(uuid.uuid4()),
                    "detection_id": str(detection.id),
                    "camera_id": str(cam.id),
                    "camera_name": cam.name,
                    "detected_at": detection.detected_at.isoformat(),
                    "observed_normalized_plate": "GJ01WS9999",
                    "watchlist_id": str(wl.id),
                    "watchlist_name": wl.name,
                    "watchlist_entry_id": str(entry.id),
                    "watchlist_category": "STOLEN",
                    "watchlist_severity": "CRITICAL",
                    "matched_plate": "GJ01WS9999",
                    "match_method": "EXACT",
                    "similarity_score": 1.0,
                    "edit_distance": 0,
                }
            ]
            post_resp = client.post("/api/v1/alerts/evaluate-matches", json=match_payload)
            assert post_resp.status_code == 201
            created_alert_id = post_resp.json()["alerts_created"][0]["id"]

            # 4. Client receives alert.created envelope via WebSocket!
            ws_alert_msg = websocket.receive_json()
            assert ws_alert_msg["event"] == "alert.created"
            assert ws_alert_msg["event_type"] == "alert.created"
            assert ws_alert_msg["source"] == "alert_engine"
            assert ws_alert_msg["data"]["alert_id"] == created_alert_id
            assert ws_alert_msg["data"]["plate_number"] == "GJ01WS9999"
            assert ws_alert_msg["data"]["severity"] == "CRITICAL"

            # 5. Acknowledge alert via REST API
            ack_resp = client.patch(
                f"/api/v1/alerts/{created_alert_id}/acknowledge",
                json={
                    "acknowledged_by_user_id": str(user.id),
                    "resolution_notes": "Unit 2 deployed for intercept"
                }
            )
            assert ack_resp.status_code == 200

            # 6. Client receives alert.updated envelope via WebSocket!
            ws_update_msg = websocket.receive_json()
            assert ws_update_msg["event"] == "alert.updated"
            assert ws_update_msg["source"] == "alert_service"
            assert ws_update_msg["data"]["alert_id"] == created_alert_id
            assert ws_update_msg["data"]["current_status"] == "ACKNOWLEDGED"
            assert "Unit 2 deployed" in ws_update_msg["data"]["resolution_notes"]

    finally:
        app.dependency_overrides.pop(get_db, None)
