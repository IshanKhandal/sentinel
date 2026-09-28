# Sentinel Realtime WebSocket Contract

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md))  
> **WebSocket Gateway Endpoint:** `ws://<host>:<port>/api/v1/ws/events`  
> **Authentication:** Ticket / Token passed via query string (`?token=<jwt_access_token>`) or first message payload.

---

## 1. Connection Lifecycle & Protocols

### Handshake & Authentication
1. Client establishes connection to `/api/v1/ws/events?token=<JWT>`.
2. Server validates token. If invalid or expired, server closes connection with WebSocket code `4401 Unauthorized`.
3. If valid, server responds with `connection.acknowledged` packet:
   ```json
   {
     "event": "connection.acknowledged",
     "session_id": "ws-sess-7b19-482a",
     "timestamp": "2026-09-28T18:10:00Z"
   }
   ```

### Heartbeat / Ping-Pong
- **Interval:** 15 seconds.
- Client sends `{"type": "ping"}`; Server responds `{"type": "pong"}`.
- If no ping received within 45 seconds, server terminates the connection.

### Reconnection Strategy
- Frontend uses exponential backoff reconnect: `min(1000 * 2^attempt, 30000)` ms with 10% jitter.
- Upon reconnection, client queries REST API: `GET /api/v1/alerts?since=<last_received_alert_id>` to backfill missed alerts during the disconnect window.

---

## 2. Event Specifications

Only events directly required for tactical operations are defined. No superfluous events are permitted.

---

### Event 1: `camera.status_changed`
- **Purpose:** Notify UI operator immediately when a surveillance stream goes offline or recovers.
- **Payload:**
  ```json
  {
    "event": "camera.status_changed",
    "timestamp": "2026-09-28T18:10:15Z",
    "data": {
      "camera_id": "c1a2b3c4-0000-0000-0000-000000000001",
      "camera_name": "Junction 04 - Ashram Road",
      "previous_status": "DEMO",
      "current_status": "OFFLINE",
      "reason": "RTSP socket timeout after 3 reconnect retries"
    }
  }
  ```
- **Producer:** Stream Ingestion Worker / Health Monitor.
- **Consumer:** Frontend Camera Grid & GIS Map Marker layer (toggles marker color from green to grey/red).
- **Deduplication Strategy:** State-transition check: event is emitted ONLY when `current_status != previous_status`.
- **Reconnection Behavior:** On reconnect, client refreshes complete camera status list via `GET /api/v1/cameras`.

---

### Event 2: `alert.created`
- **Purpose:** Immediate dispatch of a high-priority watchlist match to operator tactical dashboard.
- **Payload:**
  ```json
  {
    "event": "alert.created",
    "timestamp": "2026-09-28T18:10:30Z",
    "data": {
      "alert_id": "a1b2c3d4-0000-0000-0000-000000000001",
      "severity": "CRITICAL",
      "plate_number": "GJ01AB1234",
      "watchlist_category": "STOLEN",
      "camera_id": "c1a2b3c4-0000-0000-0000-000000000001",
      "camera_name": "Junction 04 - Ashram Road",
      "snapshot_url": "/media/detections/2026-09-28/d1e2f3a4.jpg",
      "plate_crop_url": "/media/detections/2026-09-28/p1e2f3a4.jpg",
      "fir_number": "FIR-2026-4421-AHM",
      "notes": "Stolen white sedan reported 2 hours ago"
    }
  }
  ```
- **Producer:** Alert Engine.
- **Consumer:** Frontend Alert Ticker, Audio Chime trigger, GIS Map blinking target marker.
- **Deduplication Strategy:** Backend enforces a 60-second suppression window per `(plate_number, camera_id)` pair before emitting a new alert.
- **Reconnection Behavior:** Client queries `GET /api/v1/alerts?status=NEW` to populate missed alerts.

---

### Event 3: `alert.updated`
- **Purpose:** Synchronize alert status when another operator acknowledges or dismisses an alert.
- **Payload:**
  ```json
  {
    "event": "alert.updated",
    "timestamp": "2026-09-28T18:11:00Z",
    "data": {
      "alert_id": "a1b2c3d4-0000-0000-0000-000000000001",
      "previous_status": "NEW",
      "current_status": "ACKNOWLEDGED",
      "acknowledged_by_badge": "badge_1042",
      "resolution_notes": "Unit 4 dispatched to intercept"
    }
  }
  ```
- **Producer:** Alerts REST endpoint handler (`PATCH /api/v1/alerts/{id}/acknowledge`).
- **Consumer:** Frontend Alert Ticker (removes blinking urgency badge; updates row state).
- **Deduplication Strategy:** Emitted only upon verified database transaction commit.
- **Reconnection Behavior:** Syncs automatically on next alerts list refresh.

---

### Event 4: `system.health_changed`
- **Purpose:** Broadcast critical system state shifts (e.g., storage capacity > 90%, AI pipeline degraded).
- **Payload:**
  ```json
  {
    "event": "system.health_changed",
    "timestamp": "2026-09-28T18:12:00Z",
    "data": {
      "overall_status": "DEGRADED",
      "subsystem": "INFERENCE",
      "issue": "Inference latency exceeded 200ms threshold (measured: 340ms)",
      "is_demo_mode": true
    }
  }
  ```
- **Producer:** System Health Monitor.
- **Consumer:** Global UI State Banner (Rule 30 enforcement).
- **Deduplication Strategy:** Emitted on state transition with a 120-second minimum re-notification throttle.
- **Reconnection Behavior:** Re-fetched via `GET /api/v1/system/health`.
