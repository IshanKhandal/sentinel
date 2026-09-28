# Sentinel Internal REST API Contract

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md))  
> **Base Path:** `/api/v1`  
> **Note on Scope:** This document defines the internal REST API implemented by the Sentinel backend server for client applications (Frontend Dashboard, CLI tools). It does NOT invent external police/government endpoints.

---

## Standard Error Envelope (RFC 7807 Compliant)

All non-2xx responses follow this uniform structure:
```json
{
  "type": "https://sentinel.local/errors/{error_code}",
  "title": "Short title describing the error",
  "status": 400,
  "detail": "Specific message explaining the validation or business logic failure",
  "instance": "/api/v1/resource/endpoint",
  "timestamp": "2026-09-28T18:00:00Z"
}
```

---

## 1. Authentication

### `POST /api/v1/auth/login`
- **Purpose:** Authenticate police personnel and issue JWT access token.
- **Request Body:**
  ```json
  {
    "username": "badge_1042",
    "password": "SecurePassword123!"
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
    "token_type": "bearer",
    "expires_in": 28800,
    "user": {
      "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "badge_number": "badge_1042",
      "full_name": "Insp. R. Sharma",
      "role": "Investigator"
    }
  }
  ```
- **Authentication:** None (Public login endpoint).
- **Authorization:** N/A.
- **Validation:** Username and password strings must be non-empty. Rate-limited to 5 attempts per IP per minute.
- **Error Responses:** 401 Unauthorized (`INVALID_CREDENTIALS`), 429 Too Many Requests.

### `POST /api/v1/auth/logout`
- **Purpose:** Invalidate client session / revoke refresh token.
- **Authentication:** Bearer Token.
- **Response (204 No Content):** Empty.

---

## 2. Users & Personnel

### `GET /api/v1/users`
- **Purpose:** List registered police operators and clearance levels.
- **Query Params:** `skip` (default 0), `limit` (default 20, max 100), `role` (optional).
- **Response (200 OK):** Array of user summary objects.
- **Authentication:** Bearer Token.
- **Authorization:** `SuperAdmin` role required.
- **Error Responses:** 401 Unauthorized, 403 Forbidden.

### `POST /api/v1/users`
- **Purpose:** Provision a new operator or investigator account.
- **Request Body:** `{ "badge_number", "full_name", "email", "password", "role_id", "department_id" }`.
- **Response (201 Created):** Created user summary object.
- **Authorization:** `SuperAdmin` role required.

---

## 3. Cameras

### `GET /api/v1/cameras`
- **Purpose:** Retrieve list of all surveillance cameras with current stream states.
- **Query Params:** `status` (`LIVE`, `DEMO`, `OFFLINE`, `UNAVAILABLE`), `zone` (string), `limit` (int).
- **Response (200 OK):**
  ```json
  [
    {
      "id": "c1a2b3c4-0000-0000-0000-000000000001",
      "name": "Junction 04 - Ashram Road",
      "rtsp_url": "rtsp://192.168.1.100:554/live",
      "stream_type": "DEMO",
      "status": "DEMO",
      "latitude": 23.0305,
      "longitude": 72.5714,
      "fps_target": 10,
      "resolution": "1920x1080",
      "last_heartbeat_at": "2026-09-28T18:01:00Z"
    }
  ]
  ```
- **Authentication:** Bearer Token.
- **Authorization:** Any authenticated role.

### `POST /api/v1/cameras`
- **Purpose:** Register a new surveillance camera in the registry.
- **Request Body:** `{ "name", "rtsp_url", "stream_type", "location_id", "department_id", "fps_target", "resolution" }`.
- **Response (201 Created):** Created camera entity.
- **Authorization:** `SuperAdmin` or `Investigator`.
- **Validation:** RTSP URL must match valid URI scheme; coordinates must fall within valid lat/lng boundaries.

---

## 4. Camera Health

### `GET /api/v1/cameras/{camera_id}/health`
- **Purpose:** Retrieve stream uptime history, measured FPS, and frame drop telemetry.
- **Query Params:** `duration_hours` (default: 24).
- **Response (200 OK):**
  ```json
  {
    "camera_id": "c1a2b3c4-0000-0000-0000-000000000001",
    "uptime_percentage": 99.4,
    "current_fps": 9.8,
    "dropped_frames_last_hour": 3,
    "status": "DEMO",
    "telemetry": [
      { "timestamp": "2026-09-28T18:00:00Z", "is_reachable": true, "fps": 9.8, "latency_ms": 18 }
    ]
  }
  ```
- **Error Responses:** 404 Not Found (`CAMERA_NOT_FOUND`).

---

## 5. Streams

### `GET /api/v1/streams/{camera_id}/snapshot`
- **Purpose:** Fetch the latest cached JPEG frame snapshot from a given camera stream.
- **Response (200 OK):** `image/jpeg` binary payload.
- **Failure Behavior:** If camera is `OFFLINE` or buffer is empty, returns 404 with custom error header or fallback placeholder graphic.
- **Authorization:** Authenticated user.

---

## 6. Detections

### `GET /api/v1/detections`
- **Purpose:** Search and filter historical vehicle detections across the camera network.
- **Query Params:**
  - `plate_number` (optional, prefix/wildcard supported)
  - `camera_id` (optional, UUID)
  - `vehicle_type` (optional: `CAR`, `TRUCK`, `MOTORCYCLE`, `BUS`)
  - `start_time` (ISO 8601 UTC)
  - `end_time` (ISO 8601 UTC)
  - `limit` (default: 50, max: 200)
- **Response (200 OK):**
  ```json
  {
    "total": 1,
    "items": [
      {
        "id": "d1e2f3a4-0000-0000-0000-000000000001",
        "camera_id": "c1a2b3c4-0000-0000-0000-000000000001",
        "camera_name": "Junction 04 - Ashram Road",
        "plate_number": "GJ01AB1234",
        "vehicle_type": "CAR",
        "confidence_vehicle": 0.94,
        "confidence_plate": 0.88,
        "snapshot_path": "/media/detections/2026-09-28/d1e2f3a4.jpg",
        "is_demo": true,
        "detected_at": "2026-09-28T17:45:12Z"
      }
    ]
  }
  ```
- **Validation:** `start_time` must be prior to `end_time`. Max time range query is 30 days.

---

## 7. Vehicles & Journey

### `GET /api/v1/vehicles/{plate_number}`
- **Purpose:** Retrieve vehicle profile, summary stats, observation frequency, and active watchlist enrollment status.
- **Status:** `VERIFIED WORKING` (Stage 11).
- **Response (200 OK):**
  ```json
  {
    "plate_number": "GJ01AB1234",
    "vehicle_type": "CAR",
    "color": "WHITE",
    "first_seen_at": "2026-09-20T08:12:00Z",
    "last_seen_at": "2026-09-28T17:45:12Z",
    "total_detections": 14,
    "is_on_watchlist": true,
    "watchlist_category": "STOLEN"
  }
  ```
- **Error Responses:** 404 Not Found (`VEHICLE_NOT_FOUND`).

### `GET /api/v1/vehicles/{plate_number}/history`
- **Purpose:** Query chronological observation history for a searched license plate across all camera locations.
- **Status:** `VERIFIED WORKING` (Stage 11).
- **Query Params:**
  - `start_time` (optional, ISO 8601 UTC timestamp filter)
  - `end_time` (optional, ISO 8601 UTC timestamp filter)
  - `camera_id` (optional, filter by camera UUID)
  - `order` (`asc` default for earliest-to-latest chronological timeline, `desc` for latest first; secondary deterministic tie-breaking on `detection.id`)
  - `limit` (default: 50, ge=1, le=200)
  - `skip` (default: 0, ge=0)
- **Response (200 OK):**
  ```json
  {
    "plate_number": "GJ01AB1234",
    "total_observations": 14,
    "query_window": {
      "start_time": "2026-09-20T00:00:00Z",
      "end_time": "2026-09-28T23:59:59Z"
    },
    "limit": 50,
    "skip": 0,
    "items": [
      {
        "detection_id": "d1e2f3a4-0000-0000-0000-000000000001",
        "camera_id": "c1a2b3c4-0000-0000-0000-000000000001",
        "camera_name": "Junction 04 - Ashram Road",
        "location_id": "l1a2b3c4-0000-0000-0000-000000000001",
        "location_name": "Ashram Road Junction",
        "latitude": 23.0305,
        "longitude": 72.5714,
        "city": "Ahmedabad",
        "state": "Gujarat",
        "detected_at": "2026-09-28T17:45:12Z",
        "video_pts_ms": 10000.0,
        "vehicle_type": "CAR",
        "confidence_vehicle": 0.94,
        "confidence_plate": 0.88,
        "plate_number": "GJ01AB1234",
        "raw_text": "GJ 01 AB 1234",
        "snapshot_path": "snapshots/cam01/10000.jpg",
        "plate_crop_path": null,
        "is_demo": true,
        "detection_metadata": { "video_pts_ms": 10000.0, "frame_index": 100 },
        "created_at": "2026-09-28T17:45:13Z"
      }
    ]
  }
  ```
- **Empty Result Semantics:** Returns 200 OK with `total_observations: 0` and `items: []`. Does NOT fabricate demo records or historical events.
- **Missing Data Semantics:** If camera or location is unmapped or coordinates are unavailable, `latitude` and `longitude` are returned as `null` (NEVER placeholder `0,0`).
- **No Route Inference Guarantee:** Returns observations only. Does NOT infer travel paths, speed, estimated travel time, or next-camera transitions.
- **Validation:** `start_time` must be prior to `end_time` (returns 400 Bad Request otherwise).

### `GET /api/v1/vehicles/{plate_number}/journey` (Alias: `GET /api/v1/vehicles/{plate_number}/correlation`)
- **Purpose:** Cross-camera sequential trajectory reconstruction, inter-camera temporal intervals, Haversine geographic distance, and physical transition plausibility analysis.
- **Status:** `IMPLEMENTED (Stage 12 Cross-Camera Correlation)`
- **Query Params:**
  - `start_time`: ISO 8601 UTC timestamp filter.
  - `end_time`: ISO 8601 UTC timestamp filter.
  - `max_speed_kmh`: Float (default: `180.0`). Transition velocity threshold above which inter-camera travel is flagged as `ANOMALY`. Must be > 0.
- **Response (200 OK):** `VehicleJourneyResponse`
  ```json
  {
    "plate_number": "GJ01AB1234",
    "correlation_status": "CORRELATED",
    "total_observations": 5,
    "total_waypoints": 3,
    "total_camera_transitions": 2,
    "total_distance_km": 14.25,
    "total_elapsed_seconds": 1200.0,
    "is_demo": false,
    "has_speed_anomaly": false,
    "max_speed_threshold_kmh": 180.0,
    "observations": [ ... ],
    "waypoints": [
      {
        "sequence": 1,
        "camera_id": "uuid",
        "camera_name": "Junction 1",
        "location_id": "uuid",
        "location_name": "Paldi",
        "latitude": 23.0135,
        "longitude": 72.5624,
        "city": "Ahmedabad",
        "state": "Gujarat",
        "first_detected_at": "2026-09-29T08:00:00Z",
        "last_detected_at": "2026-09-29T08:00:15Z",
        "observation_count": 2,
        "detection_ids": ["uuid", "uuid"],
        "is_demo": false
      }
    ],
    "transitions": [
      {
        "from_camera_id": "uuid",
        "from_camera_name": "Junction 1",
        "from_detected_at": "2026-09-29T08:00:15Z",
        "from_detection_id": "uuid",
        "to_camera_id": "uuid",
        "to_camera_name": "Junction 2",
        "to_detected_at": "2026-09-29T08:05:00Z",
        "to_detection_id": "uuid",
        "elapsed_seconds": 285.0,
        "distance_km": 2.15,
        "implied_speed_kmh": 27.16,
        "plausibility_status": "PLAUSIBLE",
        "anomaly_reason": null
      }
    ],
    "unmapped_waypoints": [],
    "geojson_route": {
      "type": "Feature",
      "geometry": {
        "type": "LineString",
        "coordinates": [[72.5624, 23.0135], [72.5714, 23.0232]]
      },
      "properties": {
        "plate_number": "GJ01AB1234",
        "waypoints_count": 2,
        "observation_type": "INTER_CAMERA_SEQUENCE",
        "route_inference": "NONE_CAMERA_POINTS_ONLY"
      }
    }
  }
  ```
- **Correlation Status Values:**
  - `CORRELATED`: >= 2 waypoints, all mapped, no speed anomalies.
  - `PARTIALLY_CORRELATED`: >= 2 waypoints, but contains unmapped cameras or flagged transition anomalies.
  - `NO_TRANSITION`: All observations occurred at a single camera.
  - `INSUFFICIENT_DATA`: 0 observations found for searched plate.
- **Physical Plausibility States:**
  - `PLAUSIBLE`: `implied_speed_kmh <= max_speed_threshold_kmh`.
  - `ANOMALY`: `implied_speed_kmh > max_speed_threshold_kmh` OR simultaneous detections at distinct camera locations.
  - `PLAUSIBILITY_UNKNOWN`: Distance or time could not be reliably calculated due to unmapped camera coordinates or missing timestamps.
- **Strict Invariants:**
  - `Observation != Route`: The GeoJSON LineString connects verified camera points only with explicit property `"route_inference": "NONE_CAMERA_POINTS_ONLY"`. Road network routing, turn-by-turn navigation, and intermediate interpolation are strictly prohibited.
  - `Unmapped Cameras`: Distances involving unmapped cameras are reported as `null` (never `0.0` or `0,0`).
  - `Consecutive Observations`: Multiple consecutive observations at the same camera are aggregated into a single `JourneyWaypoint`; camera transitions are generated only when the physical camera changes.


---

## 8. Watchlists

### `GET /api/v1/watchlists`
- **Purpose:** List active hotlists.
- **Response (200 OK):** Array of watchlist metadata.

### `POST /api/v1/watchlists/{watchlist_id}/entries`
- **Purpose:** Enroll a target license plate onto a police watchlist.
- **Request Body:**
  ```json
  {
    "plate_number": "GJ01XY9999",
    "vehicle_make_model": "Mahindra Scorpio",
    "fir_number": "FIR-2026-4421-AHM",
    "notes": "Wanted in connection with Case 4421"
  }
  ```
- **Response (201 Created):** Created entry entity.
- **Authorization:** `Investigator` or `SuperAdmin`.
- **Audit Logging:** Triggers automatic audit entry in `audit_logs`.

---

## 9. Alerts

### `GET /api/v1/alerts`
- **Purpose:** Query real-time and historical watchlist match alerts.
- **Query Params:** `status` (`NEW`, `ACKNOWLEDGED`, `RESOLVED`, `DISMISSED`), `severity` (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), `camera_id`, `plate_number`, `start_time`, `end_time`, `limit`, `skip`.
- **Response (200 OK):** `AlertListResponse` with total count and array of alert items with full provenance sorted by `created_at` descending.

### `GET /api/v1/alerts/{alert_id}`
- **Purpose:** Retrieve single operational alert by UUID with joined observation and watchlist provenance.
- **Response (200 OK):** `AlertRead` entity.

### `PATCH /api/v1/alerts/{alert_id}/acknowledge`
- **Purpose:** Acknowledge and claim an alert by a responding police officer.
- **Request Body:** `{ "resolution_notes": "Officer unit 12 dispatched to intercept", "acknowledged_by_user_id": "optional-uuid" }`.
- **Response (200 OK):** Updated alert entity with `status = "ACKNOWLEDGED"` and `acknowledged_at`.
- **Authorization:** Any authenticated operator.
- **Audit Logging:** Mandated in `audit_logs`.

### `PATCH /api/v1/alerts/{alert_id}/status`
- **Purpose:** Transition operational alert disposition (e.g. `RESOLVED`, `DISMISSED`).
- **Request Body:** `{ "status": "RESOLVED", "resolution_notes": "Suspect vehicle intercepted", "user_id": "optional-uuid" }`.
- **Response (200 OK):** Updated alert entity.
- **Audit Logging:** Mandated in `audit_logs`.

### `POST /api/v1/alerts/evaluate-matches`
- **Purpose:** Evaluate Stage 9 watchlist matches through Alert Engine with 60-second deduplication.
- **Request Body:** Array of `WatchlistMatchResult` objects.
- **Response (201 Created):** `AlertEngineResult` with created alerts and deduplicated count.

---

## 10. Investigations

### `POST /api/v1/investigations`
- **Purpose:** Create an investigative case dossier.
- **Status:** `IMPLEMENTED (Stage 13 Investigation Engine)`
- **Request Body:** `{ "case_number": "FIR-2026-AHM-001", "title": "Suspect Tracking", "description": "...", "target_plate": "GJ01AB1234", "lead_detective_id": "optional-uuid" }`
- **Response (201 Created):** `InvestigationRead` entity.
- **Audit Logging:** Mandated action `INVESTIGATION_CREATE`.

### `GET /api/v1/investigations`
- **Purpose:** Search and list investigation cases with pagination.
- **Query Params:** `status` (`OPEN`, `IN_PROGRESS`, `CLOSED`, `ARCHIVED`), `target_plate`, `case_number`, `limit`, `skip`.
- **Response (200 OK):** `InvestigationListResponse` with count and list of case summaries.

### `GET /api/v1/investigations/{investigation_id}`
- **Purpose:** Retrieve single investigation case with attached event timeline and registered evidence items.
- **Response (200 OK):** `InvestigationRead` entity.

### `PATCH /api/v1/investigations/{investigation_id}`
- **Purpose:** Update case details or progress lifecycle status.
- **Request Body:** `{ "title": "...", "description": "...", "target_plate": "...", "status": "IN_PROGRESS", "lead_detective_id": "..." }`
- **Response (200 OK):** Updated `InvestigationRead` entity.
- **Audit Logging:** Mandated actions `INVESTIGATION_UPDATE`, `INVESTIGATION_STATUS_CHANGE`.

### `POST /api/v1/investigations/{investigation_id}/events`
- **Purpose:** Tag and attach an existing detection or alert to the case timeline.
- **Request Body:** `{ "detection_id": "uuid", "alert_id": "optional-uuid", "notes": "Observed near crime scene" }`
- **Response (201 Created):** `InvestigationEventRead` entity with monotonic `sequence_order`.
- **Audit Logging:** Mandated action `INVESTIGATION_EVENT_ATTACH`.

### `GET /api/v1/investigations/{investigation_id}/events`
- **Purpose:** Retrieve all events attached to an investigation ordered chronologically by observation time.
- **Response (200 OK):** Array of `InvestigationEventRead` entities.

### `DELETE /api/v1/investigations/{investigation_id}/events/{event_id}`
- **Purpose:** Detach an event reference from an investigation.
- **Response (204 No Content):** Event removed.
- **Audit Logging:** Mandated action `INVESTIGATION_EVENT_DETACH`.

### `POST /api/v1/investigations/{investigation_id}/attach-history`
- **Purpose:** Attach verified historical vehicle observations from Stage 11 for the target plate or explicit detection IDs.
- **Request Body:** `{ "detection_ids": ["uuid", ...], "notes": "Attached from historical sightings" }`
- **Response (201 Created):** Array of attached `InvestigationEventRead` entities.

### `GET /api/v1/investigations/{investigation_id}/correlation`
- **Purpose:** Retrieve Stage 12 cross-camera correlation output for the investigation's target plate without recalculating GIS/spatial graph.
- **Query Params:** `start_time`, `end_time`, `max_speed_kmh`.
- **Response (200 OK):** `VehicleJourneyResponse`.

### `POST /api/v1/investigations/{investigation_id}/evidence`
- **Purpose:** Register verified digital evidence asset metadata with cryptographic SHA-256 hash.
- **Request Body:** `{ "file_path": "evidence/FIR-01.pdf", "file_type": "PDF_DOSSIER", "sha256_hash": "...", "file_size_bytes": 1048576 }`
- **Response (201 Created):** `EvidenceRead` entity.
- **Audit Logging:** Mandated action `INVESTIGATION_EVIDENCE_ATTACH`.

### `GET /api/v1/investigations/{investigation_id}/evidence`
- **Purpose:** List registered evidence assets for an investigation case.
- **Response (200 OK):** Array of `EvidenceRead` entities.

### `POST /api/v1/investigations/{investigation_id}/export`
- **Purpose:** Generate and download a cryptographic PDF/ZIP evidence package.
- **Status:** `EVIDENCE EXPORT NOT IMPLEMENTED` (Returns HTTP 501 Not Implemented; cryptographic packaging and file rendering are reserved for the export engine).

---

## 11. GIS & Spatial Endpoints

### `GET /api/v1/gis/cameras.geojson`
- **Purpose:** Export all registered camera markers formatted as standard GeoJSON `FeatureCollection`.
- **Response (200 OK):** GeoJSON object with properties `{ id, name, status, stream_type, zone }`.

### `GET /api/v1/gis/nearby-cameras`
- **Purpose:** Find cameras within a radial distance from a given point.
- **Query Params:** `latitude` (float), `longitude` (float), `radius_km` (float, max 50).
- **Response (200 OK):** Array of camera items ordered by ascending distance.

---

## 12. Analytics

### `GET /api/v1/analytics/summary`
- **Purpose:** Aggregate statistics for dashboard summary widgets.
- **Response (200 OK):**
  ```json
  {
    "total_cameras": 12,
    "active_streams": 12,
    "detections_today": 4820,
    "alerts_today": 3,
    "unresolved_alerts": 1,
    "top_vehicle_types": { "CAR": 3200, "MOTORCYCLE": 1100, "TRUCK": 380, "BUS": 140 }
  }
  ```

---

## 13. System Health

### `GET /api/v1/system/health`
- **Purpose:** Overall health probe for monitoring, load balancers, and UI state banner.
- **Response (200 OK):**
  ```json
  {
    "status": "HEALTHY",
    "app_version": "1.0.0",
    "timestamp": "2026-09-28T18:05:00Z",
    "database": { "status": "CONNECTED", "latency_ms": 2 },
    "streams": { "total": 4, "live": 0, "demo": 4, "offline": 0 },
    "inference": { "engine": "ONNX_RUNTIME", "loaded_models": ["yolov8n", "plate_ocr"] }
  }
  ```
- **Authentication:** Public / Internal.
