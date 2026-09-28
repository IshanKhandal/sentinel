# Sentinel Database Architecture Specification

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md))  
> **Target Storage Engine:** PostgreSQL 16 with PostGIS (Production) / SQLite 3 with WAL Mode (Development / Local Test Fixture)  
> **ORM Layer:** SQLAlchemy 2.0 (Declarative Mapping) with Alembic migration versioning.

---

## 1. Schema Overview & Entity Relationship Summary

The schema is organized into 6 logical domains designed to avoid redundancy while supporting fast spatial, temporal, and plate-search queries:
1. **Access Control & Organization:** `departments`, `roles`, `permissions`, `role_permissions`, `users`
2. **Surveillance & Ingestion Topology:** `locations`, `cameras`, `camera_health`, `system_events`
3. **Computer Vision & Tracking:** `vehicles`, `detections`, `tracks`
4. **Threat Detection & Watchlists:** `watchlists`, `watchlist_entries`, `alerts`
5. **Investigation & Digital Forensics:** `investigations`, `investigation_events`, `evidence`
6. **Compliance & Accountability:** `audit_logs`

```text
┌────────────────┐       ┌─────────────────┐       ┌────────────────┐
│   locations    │◄──────┤     cameras     │◄──────┤ camera_health  │
└────────────────┘       └────────┬────────┘       └────────────────┘
                                  │
                                  ▼
┌────────────────┐       ┌─────────────────┐       ┌────────────────┐
│    vehicles    │◄──────┤   detections    │◄──────┤     tracks     │
└───────┬────────┘       └────────┬────────┘       └────────────────┘
        │                         │
        ▼                         ▼
┌────────────────┐       ┌─────────────────┐       ┌────────────────┐
│watchlist_entry │──────►│     alerts      │◄──────┤ investigations │
└────────────────┘       └─────────────────┘       └───────┬────────┘
                                                           ▼
                                                   ┌────────────────┐
                                                   │    evidence    │
                                                   └────────────────┘
```

---

## 2. Table Specifications

### Domain 1: Access Control & Organization

#### `departments`
- **Purpose:** Represents police jurisdictional divisions, stations, or city zones.
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `name`: `VARCHAR(100)` (Not Null, Unique)
  - `code`: `VARCHAR(20)` (Not Null, Unique, e.g., `GJ-AMD-01`)
  - `created_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`)
- **Foreign Keys:** None
- **Indexes:** `idx_departments_code` ON (`code`)
- **Constraints:** `UNIQUE(name)`, `UNIQUE(code)`

#### `roles`
- **Purpose:** Defines police clearance roles (`SuperAdmin`, `Investigator`, `Operator`, `Auditor`).
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `name`: `VARCHAR(50)` (Not Null, Unique)
  - `description`: `TEXT` (Nullable)
- **Foreign Keys:** None
- **Indexes:** `idx_roles_name` ON (`name`)
- **Constraints:** `UNIQUE(name)`

#### `permissions`
- **Purpose:** Granular permission flags (e.g., `camera:read`, `watchlist:write`, `investigation:export`).
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `code`: `VARCHAR(100)` (Not Null, Unique)
  - `description`: `TEXT` (Nullable)
- **Foreign Keys:** None
- **Indexes:** `idx_permissions_code` ON (`code`)
- **Constraints:** `UNIQUE(code)`

#### `role_permissions`
- **Purpose:** Many-to-many relationship between roles and permissions.
- **Columns:**
  - `role_id`: `UUID` (Foreign Key -> `roles.id` ON DELETE CASCADE)
  - `permission_id`: `UUID` (Foreign Key -> `permissions.id` ON DELETE CASCADE)
- **Primary Key:** `(role_id, permission_id)`

#### `users`
- **Purpose:** Police personnel authorized to access the Sentinel platform.
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `department_id`: `UUID` (Foreign Key -> `departments.id` ON DELETE RESTRICT)
  - `role_id`: `UUID` (Foreign Key -> `roles.id` ON DELETE RESTRICT)
  - `badge_number`: `VARCHAR(50)` (Not Null, Unique)
  - `full_name`: `VARCHAR(150)` (Not Null)
  - `email`: `VARCHAR(255)` (Not Null, Unique)
  - `hashed_password`: `VARCHAR(255)` (Not Null)
  - `is_active`: `BOOLEAN` (Default: `TRUE`)
  - `last_login_at`: `TIMESTAMPTZ` (Nullable)
  - `created_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`)
- **Indexes:**
  - `idx_users_email` ON (`email`)
  - `idx_users_badge` ON (`badge_number`)

---

### Domain 2: Surveillance & Ingestion Topology

#### `locations`
- **Purpose:** Physical landmarks, traffic junctions, and highway toll points where cameras are mounted.
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `name`: `VARCHAR(150)` (Not Null)
  - `latitude`: `NUMERIC(10, 7)` (Nullable; `None` if camera site is unmapped / coordinates pending GPS verification; never fabricated as `0.0`)
  - `longitude`: `NUMERIC(10, 7)` (Nullable; `None` if camera site is unmapped / coordinates pending GPS verification; never fabricated as `0.0`)
  - `address`: `TEXT` (Nullable)
  - `city`: `VARCHAR(100)` (Not Null, e.g., `Ahmedabad`)
  - `state`: `VARCHAR(100)` (Default: `Gujarat`)
- **Indexes:**
  - `idx_locations_lat_lon` ON (`latitude`, `longitude`)
- **Constraints:**
  - `CHECK (latitude BETWEEN -90 AND 90)`
  - `CHECK (longitude BETWEEN -180 AND 180)`

#### `cameras`
- **Purpose:** Registry of video surveillance devices and stream ingestion configurations.
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `location_id`: `UUID` (Foreign Key -> `locations.id` ON DELETE RESTRICT)
  - `department_id`: `UUID` (Foreign Key -> `departments.id` ON DELETE RESTRICT)
  - `name`: `VARCHAR(150)` (Not Null)
  - `rtsp_url`: `VARCHAR(500)` (Not Null)
  - `stream_type`: `VARCHAR(20)` (Not Null, `LIVE` or `DEMO`)
  - `direction_heading`: `INTEGER` (Nullable, 0-360 degrees)
  - `fps_target`: `INTEGER` (Default: 10)
  - `resolution`: `VARCHAR(20)` (Default: `1920x1080`)
  - `status`: `VARCHAR(20)` (Default: `OFFLINE`, Allowed: `LIVE`, `DEMO`, `OFFLINE`, `UNAVAILABLE`)
  - `last_heartbeat_at`: `TIMESTAMPTZ` (Nullable)
  - `created_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`)
- **Indexes:**
  - `idx_cameras_status` ON (`status`)
  - `idx_cameras_location` ON (`location_id`)
  - `idx_cameras_stream_type` ON (`stream_type`)

#### `camera_health`
- **Purpose:** Time-series telemetry recording stream uptime, latency, and frame drops.
- **Columns:**
  - `id`: `BIGSERIAL` (Primary Key)
  - `camera_id`: `UUID` (Foreign Key -> `cameras.id` ON DELETE CASCADE)
  - `recorded_at`: `TIMESTAMPTZ` (Not Null, Default: `CURRENT_TIMESTAMP`)
  - `is_reachable`: `BOOLEAN` (Not Null)
  - `latency_ms`: `INTEGER` (Nullable)
  - `fps_measured`: `FLOAT` (Nullable)
  - `dropped_frames_count`: `INTEGER` (Default: 0)
- **Indexes:**
  - `idx_camera_health_cam_time` ON (`camera_id`, `recorded_at` DESC)

#### `system_events`
- **Purpose:** System-level operational events (worker crash, reconnect, failover).
- **Columns:**
  - `id`: `BIGSERIAL` (Primary Key)
  - `subsystem`: `VARCHAR(50)` (Not Null, e.g., `INGESTION`, `INFERENCE`, `DATABASE`)
  - `severity`: `VARCHAR(20)` (Not Null, `INFO`, `WARNING`, `ERROR`, `CRITICAL`)
  - `message`: `TEXT` (Not Null)
  - `details`: `JSONB` (Nullable)
  - `created_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`)
- **Indexes:**
  - `idx_system_events_created` ON (`created_at` DESC)
  - `idx_system_events_severity` ON (`severity`)

---

### Domain 3: Computer Vision & Tracking

#### `vehicles`
- **Purpose:** Canonical identity records for recognized vehicle registration numbers.
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `plate_number`: `VARCHAR(20)` (Not Null, Unique, sanitized uppercase)
  - `vehicle_type`: `VARCHAR(30)` (Nullable, e.g., `CAR`, `TRUCK`, `MOTORCYCLE`, `BUS`)
  - `color`: `VARCHAR(30)` (Nullable)
  - `first_seen_at`: `TIMESTAMPTZ` (Not Null)
  - `last_seen_at`: `TIMESTAMPTZ` (Not Null)
  - `total_detections_count`: `INTEGER` (Default: 1)
- **Indexes:**
  - `idx_vehicles_plate` ON (`plate_number`)
  - `idx_vehicles_last_seen` ON (`last_seen_at` DESC)
- **Constraints:**
  - `UNIQUE(plate_number)`

#### `detections`
- **Purpose:** High-throughput transactional table recording every frame-level vehicle and plate observation.
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `camera_id`: `UUID` (Foreign Key -> `cameras.id` ON DELETE RESTRICT)
  - `vehicle_id`: `UUID` (Foreign Key -> `vehicles.id` ON DELETE SET NULL, Nullable)
  - `plate_number`: `VARCHAR(20)` (Nullable, Null if plate obscured or vehicle detected without plate; sanitized normalized uppercase)
  - `raw_text`: `VARCHAR(50)` (Nullable, added in migration `f1a891746c72`; unmodified OCR provider transcription)
  - `vehicle_type`: `VARCHAR(30)` (Not Null, e.g. `CAR`, `TRUCK`, `BUS`, `MOTORCYCLE`)
  - `confidence_vehicle`: `FLOAT` (Nullable, None when vehicle detector score unavailable)
  - `confidence_plate`: `FLOAT` (Nullable)
  - `bbox_vehicle`: `JSONB` (Not Null, `[x1, y1, x2, y2]`)
  - `bbox_plate`: `JSONB` (Nullable, `[x1, y1, x2, y2]`)
  - `snapshot_path`: `VARCHAR(500)` (Not Null)
  - `plate_crop_path`: `VARCHAR(500)` (Nullable)
  - `detection_metadata`: `JSONB` (Nullable, added in migration `f1a891746c72`; stores OCR provider, model version, PTS, preprocessing variant)
  - `is_demo`: `BOOLEAN` (Not Null, Default: FALSE)
  - `detected_at`: `TIMESTAMPTZ` (Not Null, Authoritative video PTS as UTC timestamp)
  - `created_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`, Database record insertion timestamp)
- **Crucial Indexes for Performance:**
  - `idx_detections_plate_time` ON (`plate_number`, `detected_at` DESC) — **Primary Plate Search Index**
  - `idx_detections_cam_time` ON (`camera_id`, `detected_at` DESC) — **Camera Stream Query Index**
  - `idx_detections_detected_at` ON (`detected_at` DESC) — **Global Timeline Filter**
  - `idx_detections_vehicle_id` ON (`vehicle_id`)
- **Partitioning Strategy (Production Scalability):** Range partitioned by `detected_at` month.

#### `tracks`
- **Purpose:** Intra-camera continuous tracklets tying frame-by-frame bounding boxes of a single vehicle pass.
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `camera_id`: `UUID` (Foreign Key -> `cameras.id` ON DELETE CASCADE)
  - `detection_id_start`: `UUID` (Foreign Key -> `detections.id` ON DELETE CASCADE)
  - `detection_id_end`: `UUID` (Foreign Key -> `detections.id` ON DELETE CASCADE)
  - `track_tracker_id`: `INTEGER` (ByteTrack internal ID)
  - `duration_seconds`: `FLOAT` (Not Null)
  - `estimated_speed_kmh`: `FLOAT` (Nullable)
  - `direction`: `VARCHAR(20)` (Nullable, e.g., `NORTH_BOUND`)
- **Indexes:**
  - `idx_tracks_camera` ON (`camera_id`)

---

### Domain 4: Threat Detection & Watchlists

#### `watchlists`
- **Purpose:** Categorized hotlist containers (e.g., "Stolen Vehicles - Ahmedabad", "Suspect Vehicles - Operation X").
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `name`: `VARCHAR(150)` (Not Null, Unique)
  - `category`: `VARCHAR(50)` (Not Null, e.g., `STOLEN`, `WANTED`, `SUSPECT`, `EXPIRED`)
  - `severity`: `VARCHAR(20)` (Not Null, `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`)
  - `is_active`: `BOOLEAN` (Default: `TRUE`)
  - `created_by_user_id`: `UUID` (Foreign Key -> `users.id` ON DELETE RESTRICT)
  - `created_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`)
- **Indexes:**
  - `idx_watchlists_active` ON (`is_active`)

#### `watchlist_entries`
- **Purpose:** Individual target license plates registered on a watchlist.
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `watchlist_id`: `UUID` (Foreign Key -> `watchlists.id` ON DELETE CASCADE)
  - `plate_number`: `VARCHAR(20)` (Not Null)
  - `vehicle_make_model`: `VARCHAR(100)` (Nullable)
  - `fir_number`: `VARCHAR(100)` (Nullable, Police First Information Report reference)
  - `notes`: `TEXT` (Nullable)
  - `is_active`: `BOOLEAN` (Default: `TRUE`)
  - `created_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`)
- **Crucial Indexes:**
  - `idx_watchlist_entries_plate_active` ON (`plate_number`, `is_active`) — **Real-Time Watchlist Matcher Index**
- **Constraints:**
  - `UNIQUE(watchlist_id, plate_number)`
- **Stage 9 Implementation Status:** VERIFIED WORKING. Matching queries utilize `idx_watchlist_entries_plate_active` joining `idx_watchlists_active` on (`is_active = True`). Exact matches take precedence; configurable Levenshtein fuzzy matching evaluates secondary candidates.
- **Stage 10 Boundary Invariant:** Stage 9 outputs transient `WatchlistMatchResult` instances preserving complete observation provenance. Strictly NO rows are inserted into the `alerts` table during Stage 9; alert generation belongs exclusively to Stage 10.

#### `alerts`
- **Purpose:** Incident notifications raised when a detected vehicle matches an active watchlist entry.
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `detection_id`: `UUID` (Foreign Key -> `detections.id` ON DELETE RESTRICT)
  - `watchlist_entry_id`: `UUID` (Foreign Key -> `watchlist_entries.id` ON DELETE RESTRICT)
  - `camera_id`: `UUID` (Foreign Key -> `cameras.id` ON DELETE RESTRICT)
  - `plate_number`: `VARCHAR(20)` (Not Null)
  - `severity`: `VARCHAR(20)` (Not Null)
  - `status`: `VARCHAR(30)` (Default: `NEW`, Allowed: `NEW`, `ACKNOWLEDGED`, `RESOLVED`, `DISMISSED`)
  - `acknowledged_by_user_id`: `UUID` (Foreign Key -> `users.id` ON DELETE SET NULL, Nullable)
  - `acknowledged_at`: `TIMESTAMPTZ` (Nullable)
  - `resolution_notes`: `TEXT` (Nullable)
  - `created_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`)
- **Indexes:**
  - `idx_alerts_status_created` ON (`status`, `created_at` DESC) — **Live Ticker Index**
  - `idx_alerts_plate` ON (`plate_number`)
  - `idx_alerts_camera` ON (`camera_id`)
- **Stage 10 Implementation Status:** VERIFIED WORKING. Alert entities are generated deterministically from Stage 9 watchlist matches with default status `NEW` and severity inherited from `Watchlist.severity`. Symmetrical 60-second observation suppression window enforced per `(camera_id, plate_number, watchlist_entry_id)`.
- **Stage 11 Implementation Status:** VERIFIED WORKING. Vehicle observation history queries utilize `idx_detections_plate_time` ON (`plate_number`, `detected_at`), joined with camera and location registries. Strict observation timestamp ordering with `Detection.id` tie-breaking is enforced.
- **Stage 12 Boundary Invariant:** Stage 11 provides chronological observation history only; cross-camera trajectory reconstruction, graph correlation, and velocity estimation belong strictly to Stage 12.


---

### Domain 5: Investigation & Digital Forensics

#### `investigations`
- **Purpose:** Case files opened by police officers to track specific vehicles or suspect timelines.
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `case_number`: `VARCHAR(100)` (Not Null, Unique)
  - `title`: `VARCHAR(255)` (Not Null)
  - `description`: `TEXT` (Nullable)
  - `target_plate`: `VARCHAR(20)` (Nullable)
  - `status`: `VARCHAR(30)` (Default: `OPEN`, Allowed: `OPEN`, `IN_PROGRESS`, `CLOSED`, `ARCHIVED`)
  - `lead_detective_id`: `UUID` (Foreign Key -> `users.id` ON DELETE RESTRICT)
  - `created_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`)
  - `updated_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`)
- **Indexes:**
  - `idx_investigations_case` ON (`case_number`)
  - `idx_investigations_plate` ON (`target_plate`)

#### `investigation_events`
- **Purpose:** Specific detections or alerts tagged and attached to an investigation case.
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `investigation_id`: `UUID` (Foreign Key -> `investigations.id` ON DELETE CASCADE)
  - `detection_id`: `UUID` (Foreign Key -> `detections.id` ON DELETE SET NULL, Nullable)
  - `alert_id`: `UUID` (Foreign Key -> `alerts.id` ON DELETE SET NULL, Nullable)
  - `sequence_order`: `INTEGER` (Not Null)
  - `notes`: `TEXT` (Nullable)
  - `added_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`)
- **Indexes:**
  - `idx_inv_events_timeline` ON (`investigation_id`, `sequence_order`)

#### `evidence`
- **Purpose:** Immutable digital forensic assets (packaged ZIPs, PDF dossiers, cryptographic hashes).
- **Columns:**
  - `id`: `UUID` (Primary Key)
  - `investigation_id`: `UUID` (Foreign Key -> `investigations.id` ON DELETE CASCADE)
  - `file_path`: `VARCHAR(500)` (Not Null)
  - `file_type`: `VARCHAR(50)` (Not Null, `PDF_DOSSIER`, `CROP_ARCHIVE`, `EXPORT_JSON`)
  - `sha256_hash`: `VARCHAR(64)` (Not Null, Cryptographic proof of integrity)
  - `file_size_bytes`: `BIGINT` (Not Null)
  - `generated_by_user_id`: `UUID` (Foreign Key -> `users.id` ON DELETE RESTRICT)
  - `created_at`: `TIMESTAMPTZ` (Default: `CURRENT_TIMESTAMP`)
- **Indexes:**
  - `idx_evidence_inv` ON (`investigation_id`)

---

### Domain 6: Compliance & Accountability

#### `audit_logs`
- **Purpose:** Immutable, non-deletable audit trail recording every state-changing and sensitive police operation.
- **Columns:**
  - `id`: `BIGSERIAL` (Primary Key)
  - `user_id`: `UUID` (Foreign Key -> `users.id` ON DELETE SET NULL, Nullable)
  - `badge_number`: `VARCHAR(50)` (Not Null)
  - `action`: `VARCHAR(100)` (Not Null, e.g., `WATCHLIST_CREATE`, `ALERT_ACKNOWLEDGE`, `SEARCH_PLATE`, `EXPORT_DOSSIER`)
  - `resource_type`: `VARCHAR(50)` (Not Null, e.g., `ALERT`, `WATCHLIST`, `INVESTIGATION`)
  - `resource_id`: `VARCHAR(100)` (Nullable)
  - `ip_address`: `VARCHAR(45)` (Not Null)
  - `payload_summary`: `TEXT` (Nullable)
  - `timestamp`: `TIMESTAMPTZ` (Not Null, Default: `CURRENT_TIMESTAMP`)
- **Indexes:**
  - `idx_audit_logs_user` ON (`user_id`, `timestamp` DESC)
  - `idx_audit_logs_action` ON (`action`, `timestamp` DESC)
  - `idx_audit_logs_time` ON (`timestamp` DESC)
- **Constraint:** Read-only table. Application database user is granted `SELECT` and `INSERT` permissions only; `UPDATE` and `DELETE` privileges are strictly revoked at the database role level.

---

### Migration History

1. `c1a5639ce6ba` — Initial schema creation (all core tables, foreign keys, and indexes).
2. `f1a891746c72` — Add `raw_text` and `detection_metadata` columns to `detections` table (Stage 8 Event Persistence).
3. `a7c8e9d01234` — Alter `locations.latitude` and `locations.longitude` to `nullable=True` to support unmapped camera sites without coordinate fabrication (Stage 12 Cross-Camera Correlation).
4. `b8d9e0f12345` — Alter `detections.confidence_vehicle` column to `nullable=True` to allow null confidence when vehicle detector score is unavailable.


