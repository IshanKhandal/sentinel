# Sentinel Final Implementation Architecture

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md))  
> **Repository Baseline:** Verified Greenfield Repository (0 legacy source files, 7 governance docs committed).

---

## 1. Architectural Strategy Decision

### Decision: Option C — Create a Clean, Modular Architecture Preserving Existing Governance
- **Options Evaluated:**
  - **A. Extend the existing project:** Not applicable. Phase 0 audit verified 0 pre-existing application files (no legacy backend, frontend, database, or ML scripts).
  - **B. Partially refactor the existing project:** Not applicable. There is no existing codebase to refactor.
  - **C. Clean Architecture Migration (Chosen):** Establish a clean, decoupled modular architecture from scratch while preserving and strictly honoring the established governance framework ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md), [docs/demo-mode.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/demo-mode.md), [docs/requirements-traceability.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/requirements-traceability.md)).
- **Evidence Justification:** Terminal outputs from `Get-ChildItem -Recurse`, `git log --all`, and `git fsck` confirm that no application code was inherited from earlier projects. Clean layered architecture avoids phantom technical debt and enforces strict interface boundaries.

---

## 2. Component Specifications (19 Layers)

### 1. Frontend Command Dashboard
- **Purpose:** Provide police operators and investigators with a tactical command center for surveillance, GIS mapping, real-time alert triage, and journey investigations.
- **Technology:** Modern Web SPA (Vite + React / TypeScript or Vanilla Web Components with high-performance Canvas/WebGL rendering).
- **Input:** User interactions, REST API responses, WebSocket telemetry streams.
- **Output:** DOM updates, interactive GIS renders, alert notifications, investigation exports.
- **Dependencies:** Backend REST API, WebSocket Gateway, Map tile provider.
- **Failure Behavior:** If backend disconnects, displays clear `OFFLINE` banner; renders cached data with stale warning; disables write actions.
- **Current Implementation:** Non-existent (0 files).
- **Target Implementation:** Tactical dark-mode single-page application with Leaflet GIS map, 4-camera grid, live alert ticker, and filterable investigation view.
- **Verification Method:** Vitest unit tests, Playwright browser end-to-end tests, bundle build verification (`npm run build`).

### 2. API Gateway / Backend Core
- **Purpose:** Serve as the unified entry point for all client requests, coordinate internal micro-services/modules, enforce business rules, and validate payloads.
- **Technology:** Python FastAPI + Uvicorn (Asynchronous ASGI framework).
- **Input:** HTTP/JSON client requests, internal worker events.
- **Output:** Validated JSON responses, WebSocket event broadcasts, HTTP status codes.
- **Dependencies:** Database engine, Cache/Event bus, Auth service.
- **Failure Behavior:** Returns structured RFC 7807 error envelopes (`{ detail, code, timestamp }`); logs stack trace internally; does not expose system internals.
- **Current Implementation:** Non-existent.
- **Target Implementation:** FastAPI application with modular routers (`/api/v1/cameras`, `/api/v1/detections`, `/api/v1/alerts`, etc.).
- **Verification Method:** Pytest suite, OpenAPI schema validation, HTTP status code assertions.

### 3. Authentication & RBAC Service
- **Purpose:** Secure endpoints and enforce role-based access controls across police operator clearance tiers.
- **Technology:** Passlib (bcrypt password hashing), PyJWT (RS256 / HS256 tokens).
- **Input:** Login credentials (username, password), Bearer tokens in HTTP headers.
- **Output:** Cryptographic JWT access tokens, role claims (`SuperAdmin`, `Investigator`, `Operator`, `Auditor`).
- **Dependencies:** Users and Roles database tables.
- **Failure Behavior:** Rejects invalid/expired credentials with HTTP 401 Unauthorized; rejects unauthorized actions with HTTP 403 Forbidden; audits failed attempts.
- **Current Implementation:** Non-existent.
- **Target Implementation:** OAuth2 password bearer flow with FastAPI security dependency injection.
- **Verification Method:** Automated auth unit tests verifying token expiration, tampering rejection, and permission matrix checks.

### 4. Camera Registry
- **Purpose:** Manage lifecycle, network configuration, geographical coordinates, physical location details, and operational status of all surveillance cameras.
- **Technology:** Relational DB repository with Pydantic validation schemas.
- **Input:** Camera metadata (name, IP/RTSP URI, lat/lng, zone, resolution, fps, credentials reference).
- **Output:** Camera configuration entities, stream endpoint references.
- **Dependencies:** Database engine, GIS validation.
- **Failure Behavior:** Validates RTSP format; if camera is unreachable, records status as `OFFLINE` without blocking registry.
- **Current Implementation:** Non-existent.
- **Target Implementation:** CRUD service with spatial location validation and status query methods.
- **Verification Method:** CRUD unit tests, geospatial coordinate validation tests.

### 5. Stream Ingestion Worker
- **Purpose:** Connect to external video sources (RTSP over TCP, local MP4 fixtures), handle frame demuxing, maintain frame buffers, and manage reconnection backoff.
- **Technology:** OpenCV (`cv2.VideoCapture`) with fallback to PyAV / FFmpeg bindings where available.
- **Input:** RTSP URL or synthetic demo file path.
- **Output:** Decoded RGB/BGR frame buffers with presentation timestamps (PTS).
- **Dependencies:** Camera Registry, System video codecs.
- **Failure Behavior:** If connection drops, triggers exponential backoff reconnect (1s, 2s, 4s, up to 30s); marks camera as `OFFLINE`; drains stale buffer.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Multi-threaded or asynchronous worker pool isolating each stream to prevent single-camera stalls from blocking others.
- **Verification Method:** Connection tests against local RTSP server and synthetic MP4 loop fixtures.

### 6. Video Processing & Frame Manager
- **Purpose:** Preprocess raw decoded frames (resizing, letterboxing, colorspace conversion, frame skipping / decimation to target FPS) before feeding into AI inference.
- **Technology:** NumPy, OpenCV.
- **Input:** Decoded raw video frames + camera metadata.
- **Output:** Standardized normalized tensor/array (e.g., 640x640x3 float32) with timestamp metadata.
- **Dependencies:** Stream Ingestion.
- **Failure Behavior:** Drops corrupted frames; logs warning count; if frame drop exceeds 20 consecutive frames, raises stream degradation alert.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Pipeline processor with configurable target FPS (e.g., 5-10 FPS for detection) to prevent GPU/CPU saturation.
- **Verification Method:** Frame dimension, type, and FPS rate benchmark tests.

### 7. AI Inference Engine
- **Purpose:** Execute deep learning models for vehicle detection (YOLO), license plate localization, and character recognition (OCR).
- **Technology:** Pluggable interface (`ObjectDetector`, `PlateDetector`, `OCRProvider`) supporting ONNX Runtime, Ultralytics YOLO, and PaddleOCR/EasyOCR.
- **Input:** Standardized frame tensors.
- **Output:** Detection bounding boxes, class labels (`car`, `truck`, `bus`, `motorcycle`), confidence scores, cropped plate images, recognized plate text.
- **Dependencies:** Model weight files, ONNX/PyTorch runtime.
- **Failure Behavior:** If inference fails or model raises exception, logs error, outputs empty detection list, and increments failure metric without crashing pipeline.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Abstract Base Class interface layer with mock/dummy provider for testing and production ONNX/YOLO provider.
- **Verification Method:** Inference unit tests using standardized test image fixtures with ground-truth bounding box comparisons.

### 8. Event Normalization Layer
- **Purpose:** Transform raw model predictions into canonical, schema-compliant system events.
- **Technology:** Pydantic models.
- **Input:** Raw model output dicts + camera ID + timestamp.
- **Output:** Normalized `DetectionEvent` objects (plate text standardized via Indian registration regex, confidence normalized to 0.0–1.0, UTC ISO timestamp).
- **Dependencies:** AI Inference Engine.
- **Failure Behavior:** Rejects malformed predictions; sanitizes non-alphanumeric noise from plate text.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Pure-function event normalizer with strict validation rules.
- **Verification Method:** Unit tests covering invalid plate formats, unicode noise, and boundary timestamps.

### 9. Watchlist Matching Engine
- **Purpose:** Compare normalized vehicle license plates in real time against high-priority police watchlists (e.g., Stolen, Wanted, Suspect, Surveillance).
- **Technology:** In-memory Bloom filter / hash set index with secondary fuzzy Levenshtein distance matcher for OCR error tolerance.
- **Input:** Normalized `DetectionEvent`.
- **Output:** `WatchlistMatchEvent` containing matched watchlist entry, similarity score, and priority level.
- **Dependencies:** Watchlist repository / cache.
- **Failure Behavior:** If lookup index is unavailable, queries primary database directly; logs delay warning.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Exact-match dictionary index with configurable 1-character edit distance tolerance for OCR misreads.
- **Verification Method:** Matching tests against test watchlists with exact and fuzzy OCR match test cases.

### 10. Alert Engine
- **Purpose:** Generate, prioritize, deduplicate, and route alerts triggered by watchlist matches or geofence/behavior violations.
- **Technology:** Event-driven rule engine.
- **Input:** `WatchlistMatchEvent`.
- **Output:** Persisted `Alert` record + dispatched notification payload.
- **Dependencies:** Watchlist Matching Engine, Database, WebSocket Broadcaster.
- **Failure Behavior:** If notification dispatch fails, alert remains saved in database with status `PENDING_DELIVERY`.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Alert generator with 60-second duplicate suppression window (prevents single vehicle sitting at traffic light from firing 50 alerts).
- **Verification Method:** Alert creation and deduplication window unit tests.

### 11. Vehicle Correlation & Tracking Engine
- **Purpose:** Track vehicle identities across sequential frames (intra-camera tracking) and correlate detections across multiple geographic cameras (cross-camera ReID / trajectory).
- **Technology:** ByteTrack algorithm / spatial-temporal correlation logic.
- **Input:** Sequence of `DetectionEvent` objects across multiple cameras.
- **Output:** Unified `VehicleTrajectory` (chronological camera waypoints, timestamps, estimated speed, direction).
- **Dependencies:** Detection database, Camera Registry GIS coordinates.
- **Failure Behavior:** If a vehicle's plate is partially obscured, links trajectory based on camera topology and timestamp feasibility (checks maximum possible speed between cameras).
- **Current Implementation:** Non-existent.
- **Target Implementation:** Trajectory assembler that queries detections by plate and sorts by timestamp with velocity sanity checks.
- **Verification Method:** Trajectory calculation tests with multi-camera timestamp sequences.

### 12. Investigation Engine
- **Purpose:** Provide investigative search, journey playback, pattern analysis, and exportable forensic dossiers for police detectives.
- **Technology:** FastAPI service + PDF/JSON report generator.
- **Input:** Search parameters (plate prefix, date/time window, camera zone, vehicle type/color).
- **Output:** Chronological detection history, mapped journey route, cropped evidence photos, printable PDF dossier.
- **Dependencies:** Database, Vehicle Correlation Engine, File Storage.
- **Failure Behavior:** Returns empty result set with appropriate message if no matches found; bounds query limits (max 500 records) to prevent DB exhaustion.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Query builder with composite index utilization and evidence packaging.
- **Verification Method:** Integration tests verifying query filters, pagination, and dossier report generation.

### 13. GIS / Geospatial Service
- **Purpose:** Provide geospatial mapping, camera coordinate projections, vehicle trajectory lines, and spatial radius searches.
- **Technology:** GeoJSON standards, SpatiaLite (local) / PostGIS (production), Leaflet.js frontend.
- **Input:** GPS coordinates (Latitude, Longitude), camera IDs, bounding boxes.
- **Output:** GeoJSON FeatureCollections (markers, lines, heatmaps).
- **Dependencies:** Camera Registry, Vehicle Trajectory data.
- **Failure Behavior:** Filters out invalid coordinates (lat outside [-90, 90], lng outside [-180, 180]); displays warning badge for unmapped cameras.
- **Current Implementation:** Non-existent.
- **Target Implementation:** GeoJSON formatting module and Haversine distance calculator for nearby camera queries.
- **Verification Method:** Geospatial unit tests with verified coordinates and distance formulas.

### 14. Database Persistence Layer
- **Purpose:** Store system entities, configuration, detection events, watchlists, alerts, and audit trails with ACID guarantees.
- **Technology:** SQLAlchemy 2.0 ORM with Alembic migrations; SQLite (development/local) and PostgreSQL (production).
- **Input:** Structured ORM domain entities.
- **Output:** Persisted records, indexed query results.
- **Dependencies:** File system / database server.
- **Failure Behavior:** Transaction rollback on integrity violations; connection retry pool.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Fully normalized relational schema with explicit indexes for plates, timestamps, and camera IDs.
- **Verification Method:** Automated migration tests, schema constraint tests, and index verification.

### 15. Cache & Event Bus
- **Purpose:** Low-latency intermediate message exchange between ingestion workers, detection pipelines, alert dispatchers, and WebSocket workers.
- **Technology:** In-memory asynchronous `asyncio.Queue` / dictionary cache (development/local), Redis Pub/Sub (production).
- **Input:** Internal application events (`detection`, `alert`, `health`).
- **Output:** Delivered event messages to subscribed workers.
- **Dependencies:** In-memory loop or Redis server.
- **Failure Behavior:** Drops non-critical telemetry if queue reaches maximum capacity; logs queue saturation warning.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Pluggable event bus interface allowing seamless switch between in-memory async bus and Redis.
- **Verification Method:** Bus publish/subscribe throughput and message delivery unit tests.

### 16. Realtime / WebSocket Gateway
- **Purpose:** Maintain persistent bidirectional connections with frontend operator dashboards for instant delivery of alerts and camera status changes.
- **Technology:** FastAPI WebSockets (`starlette.websockets`).
- **Input:** Internal event bus messages.
- **Output:** JSON-formatted WebSocket message packets.
- **Dependencies:** API Gateway, Event Bus, Auth token validator.
- **Failure Behavior:** Automatically disconnects dead sockets; frontend initiates reconnection with exponential backoff.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Connection manager maintaining active client registry with subscription channels (`all`, `alerts`, `camera:{id}`).
- **Verification Method:** WebSocket connection, authentication, and broadcast test scripts.

### 17. System Health & Provenance Monitoring
- **Purpose:** Track real-time operational status of all streams, workers, database connections, and model inference latency; enforce trustworthy UI state badges.
- **Technology:** Prometheus-style metrics collectors / FastAPI `/health` endpoint.
- **Input:** Heartbeat pings from ingestion workers and DB ping checks.
- **Output:** Structured health payload (`{ status: "healthy", components: { db, streams, models }, timestamp }`).
- **Dependencies:** All active subsystems.
- **Failure Behavior:** Marks unhealthy subsystems as `DEGRADED` or `DOWN`; triggers operator notification.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Central health service aggregating heartbeat checks every 10 seconds.
- **Verification Method:** Health check integration tests asserting status transitions on simulated worker failure.

### 18. Audit & Forensic Logging Service
- **Purpose:** Record immutable, tamper-evident logs of every sensitive police action (watchlist modifications, alert dismissals, video export, suspect searches).
- **Technology:** Structured JSON logging + dedicated relational `audit_logs` table.
- **Input:** User context, action name, target entity, request IP, timestamp, change diff.
- **Output:** Persisted audit record with SHA-256 integrity hash.
- **Dependencies:** Database engine, Authentication service.
- **Failure Behavior:** Audit logging is mandatory; if audit write fails, the enclosing sensitive transaction is rolled back.
- **Current Implementation:** Non-existent.
- **Target Implementation:** Audit middleware automatically intercepting POST/PUT/DELETE operations on sensitive routes.
- **Verification Method:** Audit log generation tests for all state-changing API endpoints.

### 19. Scalability Infrastructure (Target Specification)
- **Purpose:** Architecture blueprint for horizontally scaling stream ingestion and inference to large-scale camera footprints (~80,000 cameras).
- **Technology:** Regional Stream Gateways, Kubernetes / Docker Compose worker pools, Kafka / Redis message brokers, Object Storage (S3 / MinIO) for evidence images.
- **Input:** Distributed multi-district camera feeds.
- **Output:** Centralized event stream and distributed video buffer.
- **Dependencies:** Container orchestration, high-bandwidth network fabric.
- **Failure Behavior:** Automatic pod restarts; partition tolerance via distributed queue consumers.
- **Current Implementation:** Documented target blueprint only (no cluster deployed).
- **Target Implementation:** Fully documented in [docs/scalability-architecture.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/scalability-architecture.md).
- **Verification Method:** Architecture review and theoretical capacity calculations.

---

## 3. End-to-End Data Flows (A through J)

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        DATA FLOW ARCHITECTURE                          │
└────────────────────────────────────────────────────────────────────────┘

 [FLOW A: Camera Discovery]
   Admin/Config ────────► API Gateway ────────► Camera Registry ────────► Database

 [FLOW B: CCTV Stream Ingestion]
   Camera Registry ─────► Stream Ingestion ───► Frame Manager ──────────► Ingestion Buffer

 [FLOW C: Frame → AI Inference]
   Frame Buffer ────────► Preprocessor ───────► Object & Plate Detector ─► Raw Predictions

 [FLOW D: Detection → Database]
   Raw Predictions ─────► Normalizer ─────────► Persistence Layer ──────► Detections DB

 [FLOW E: Detection → Watchlist]
   Normalized Event ────► Watchlist Matcher ──► Hotlist Index ──────────► Match Evaluator

 [FLOW F: Watchlist Match → Alert]
   Match Evaluator ─────► Alert Engine ───────► Deduplication Filter ───► Alerts DB

 [FLOW G: Vehicle → Cross-Camera Journey]
   Plate / Time Query ──► Correlation Engine ─► Spatial Sort ───────────► Vehicle Trajectory

 [FLOW H: Journey → GIS]
   Vehicle Trajectory ──► GIS Service ────────► GeoJSON Assembler ──────► Map Dashboard

 [FLOW I: Alert → Realtime Dashboard]
   Alert Engine ────────► Event Bus ──────────► WebSocket Gateway ──────► Tactical UI Ticker

 [FLOW J: Investigation → Evidence Report]
   Investigator Query ──► Dossier Builder ────► Evidence Packager ──────► PDF / JSON Export
```

### Detailed Flow Specifications

#### FLOW A: Camera Discovery & Registration
- **Input:** Camera registration request (IP/RTSP, name, geographic latitude/longitude, zone).
- **Processing:** Payload validation (Pydantic), coordinate range check, initial RTSP handshake ping.
- **Output:** Created camera record with unique UUID and initial status (`UNVERIFIED` / `OFFLINE`).
- **Storage:** Persisted in `cameras` table.
- **Realtime Behavior:** Dispatches `camera.status_changed` event over WebSocket.
- **Failure Handling:** If initial connection fails, camera is still saved but flagged `OFFLINE`; error reported in response.

#### FLOW B: CCTV Stream Ingestion
- **Input:** Registered camera RTSP URL or synthetic MP4 demo file.
- **Processing:** VideoCapture demuxer opens TCP stream, decodes video frames, inspects PTS timestamps, monitors packet loss.
- **Output:** Decoded RGB frames placed into fixed-size circular ring buffer.
- **Storage:** Stored temporarily in-memory (max 30 frames); keyframe thumbnails saved to disk for alert events.
- **Realtime Behavior:** Emits periodic heartbeat metric every 5s; emits `camera.status_changed` if stream drops.
- **Failure Handling:** Exponential backoff reconnection loop (1s, 2s, 4s, ..., max 30s). Drains buffer on stall.

#### FLOW C: Frame → AI Inference
- **Input:** Raw decoded frame from ring buffer.
- **Processing:** Resize/letterbox to model dimension (640x640), normalize pixel values, batch inference through YOLO vehicle detector, crop license plate sub-regions, pass plate crop to OCR engine.
- **Output:** List of detections `{ bbox, vehicle_type, plate_text, confidence, crop_image }`.
- **Storage:** Inference metrics (latency, FPS) recorded in-memory.
- **Realtime Behavior:** Non-blocking asynchronous processing pipeline.
- **Failure Handling:** If OCR fails or confidence < threshold, vehicle detection is kept with `plate_text: null`.

#### FLOW D: Detection → Database
- **Input:** Validated detection predictions from AI engine.
- **Processing:** Normalization into canonical `Detection` model; image cropping and saving of evidence snapshot to disk (`/media/detections/YYYY-MM-DD/`).
- **Output:** Inserted database record ID.
- **Storage:** Row written to `detections` table and linked `vehicles` table.
- **Realtime Behavior:** Optional broadcast of `detection.created` on high-verbosity debug channels.
- **Failure Handling:** Database write retry loop (up to 3 attempts); if DB is unreachable, detection is written to emergency disk buffer (`.jsonl`).

#### FLOW E: Detection → Watchlist
- **Input:** Normalized vehicle plate string and camera metadata.
- **Processing:** Exact plate lookup against in-memory indexed hash table of active watchlists; secondary fuzzy distance check if exact match fails.
- **Output:** `WatchlistMatch` object (target plate, category, matched plate, similarity score) or `null`.
- **Storage:** None at this step.
- **Realtime Behavior:** Synchronous in-memory lookup (< 2ms latency).
- **Failure Handling:** If in-memory index is uninitialized, performs fallback SQL query against `watchlist_entries` table.

#### FLOW F: Watchlist Match → Alert
- **Input:** `WatchlistMatch` object.
- **Processing:** Deduplication check against `alerts` table (suppresses matches for same plate on same camera within 60-second window); assigns alert priority (`CRITICAL`, `HIGH`, `MEDIUM`).
- **Output:** Created `Alert` entity.
- **Storage:** Inserted into `alerts` table with initial status `NEW`.
- **Realtime Behavior:** Immediate publish to internal event bus topic `alerts.new`.
- **Failure Handling:** If persistence fails, alerts are held in memory queue and logged to emergency disk log.

#### FLOW G: Vehicle → Cross-Camera Journey
- **Input:** Target license plate number + date/time window.
- **Processing:** Query all historical detections for target plate; group by camera ID; sort chronologically by timestamp; calculate inter-camera travel duration and implied velocity.
- **Output:** Chronological list of camera waypoints with timestamps and travel time deltas.
- **Storage:** In-memory query result object (optionally saved in `investigations` table if linked to an active case).
- **Realtime Behavior:** On-demand REST API query (`GET /api/v1/vehicles/{plate}/journey`).
- **Failure Handling:** Returns partial journey if timestamps indicate impossible speeds (> 180 km/h), tagging flagged hops as `ANOMALY`.

#### FLOW H: Journey → GIS Mapping
- **Input:** Chronological camera waypoints from Journey engine.
- **Processing:** Joins camera IDs with geographical coordinates (lat/lng) from Camera Registry; constructs GeoJSON `LineString` and `FeatureCollection` of waypoint markers.
- **Output:** GeoJSON payload formatted for Leaflet polyline rendering.
- **Storage:** Computed on-the-fly; cached in memory for 60 seconds.
- **Realtime Behavior:** Sent over REST API or WebSocket to client map view.
- **Failure Handling:** Cameras missing coordinates are excluded from polyline and listed in an `unmapped_waypoints` metadata array.

#### FLOW I: Alert → Realtime Dashboard
- **Input:** New alert published to event bus.
- **Processing:** WebSocket gateway serializes alert payload into JSON event `alert.created`; formats toast summary; checks client clearance level.
- **Output:** Frame pushed down open WebSocket socket connections to authenticated operator browsers.
- **Storage:** None at gateway layer (already stored in DB).
- **Realtime Behavior:** Sub-100ms transit from alert generation to client UI arrival.
- **Failure Handling:** If client connection is severed, client triggers auto-reconnect and queries `GET /api/v1/alerts?since={last_seen_id}`.

#### FLOW J: Investigation → Evidence Report
- **Input:** Investigation ID or custom search filter submitted by authorized detective.
- **Processing:** Gathers case details, linked detections, full journey route, cropped evidence snapshots, operator audit trail; compiles into structured PDF/JSON package.
- **Output:** Downloadable ZIP or PDF dossier with digital integrity hash (SHA-256).
- **Storage:** Dossier file stored in `/media/reports/`; audit record inserted into `audit_logs`.
- **Realtime Behavior:** Long-running report generation executed as background task; status polled or notified via WebSocket.
- **Failure Handling:** If generation fails, error logged to audit table and HTTP 500 returned with user-friendly error envelope.
