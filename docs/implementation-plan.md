# Sentinel Phased Implementation Plan

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md))  
> **Strict Prerequisite:** No code implementation begins until Phase 1 architecture is formally approved.

---

## 1. Dependency-Driven Implementation Sequence

Every stage strictly builds on the verified output of preceding stages. The sequencing below eliminates circular dependencies:

```text
 [1. Foundation & Env]
         │
         ▼
 [2. Database & ORM Layer]
         │
         ▼
 [3. Camera Registry API] ────────► [4. GIS & Spatial Mapping]
         │
         ▼
 [5. Stream Ingestion Worker]
         │
         ▼
 [6. Vehicle Detection Pipeline]
         │
         ▼
 [7. ANPR & Plate OCR Engine]
         │
         ▼
 [8. Event Storage & Persistence]
         │
         ▼
 [9. Watchlists Engine] ──────────► [10. Alert Generator]
         │                                   │
         ▼                                   ▼
 [11. Vehicle History] ───────────► [14. Realtime WebSockets]
         │                                   │
         ▼                                   ▼
 [12. Cross-Camera Correlation] ──► [15. Security & RBAC]
         │                                   │
         ▼                                   ▼
 [13. Investigation Engine] ──────► [16. Frontend Dashboard UI]
                                             │
                                             ▼
                                    [17. End-to-End Verification]
```

---

## 2. Detailed Phase Breakdown & Dependency Rationale

### Phase 1: Architectural Foundation & Project Tooling (COMPLETED)
- **Deliverables:** Architecture freeze, evidence-first governance rules, database design, API & realtime contracts.
- **Dependencies:** None.

### Phase 2: Database Schema & Entity Models
- **Deliverables:** SQLAlchemy 2.0 ORM models for all tables, SQLite/PostgreSQL configuration, Alembic migration scripts.
- **Dependencies:** Database design ([docs/database-design.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/database-design.md)).
- **Rationale:** All backend services, ingestion workers, and query endpoints depend on concrete database entity models.

### Phase 3: Camera Registry & REST CRUD Service
- **Deliverables:** Camera schema validation, status tracking, CRUD REST endpoints (`/api/v1/cameras`).
- **Dependencies:** Phase 2 (Database models).
- **Rationale:** Video ingestion and GIS mapping cannot operate without registered camera endpoints and coordinates.

### Phase 4: GIS & Spatial Mapping Module
- **Deliverables:** GeoJSON export endpoint, coordinate validation, Haversine nearby camera lookup.
- **Dependencies:** Phase 3 (Camera Registry).
- **Rationale:** Establishes spatial topology prior to processing moving vehicles.

### Phase 5: Stream Ingestion & Frame Ring Buffer
- **Deliverables:** Multi-threaded stream worker, OpenCV/RTSP over TCP reader, synthetic MP4 test loop adapter, exponential backoff reconnection.
- **Dependencies:** Phase 3 (Camera Registry).
- **Rationale:** AI inference requires a steady, thread-safe stream of decoded video frames.

### Phase 6: Vehicle Detection Pipeline
- **Deliverables:** Pluggable `ObjectDetector` interface, ONNX Runtime / YOLO wrapper, standardized frame preprocessor.
- **Dependencies:** Phase 5 (Decoded video frames).
- **Rationale:** Plate detection and tracking depend directly on located vehicle bounding boxes.

### Phase 7: ANPR & Plate OCR Engine
- **Deliverables:** `PlateDetector` and `OCRProvider` implementations, Indian license plate syntax regex validator, plate crop saver.
- **Dependencies:** Phase 6 (Vehicle bounding boxes).
- **Rationale:** Watchlists and vehicle journeys depend on extracted plate text.

### Phase 8: Event Normalization & Detection Persistence
- **Deliverables:** Normalizer pipeline writing detections and cropped snapshots to database.
- **Dependencies:** Phase 2 (Database), Phase 6 & 7 (AI outputs).
- **Rationale:** Detections must be persisted before watchlists or history can query them.

### Phase 9: Watchlists & Hotlist Manager
- **Deliverables:** In-memory plate hash set index, watchlist REST management APIs.
- **Dependencies:** Phase 2 (Database).
- **Rationale:** Alert generation requires an active watchlist to compare detections against.

### Phase 10: Real-Time Alert Engine & Deduplication
- **Deliverables:** Watchlist matching rule evaluator, 60-second duplicate suppression window, alert persistence.
- **Dependencies:** Phase 8 (Detections), Phase 9 (Watchlists).
- **Rationale:** Alerts are triggered by matching detections against watchlists.

### Phase 11: Vehicle History & Trajectory Reconstruction
- **Deliverables:** Plate history query API, chronological camera sequencing, inter-camera velocity estimation.
- **Dependencies:** Phase 8 (Historical detections), Phase 4 (GIS coordinates).
- **Rationale:** Journey mapping requires both stored timestamps and camera GPS locations.

### Phase 12: Cross-Camera Correlation
- **Deliverables:** Spatio-temporal route graph linking detections across camera nodes.
- **Dependencies:** Phase 11 (Vehicle History).

### Phase 13: Investigation Dossier Engine
- **Deliverables:** Investigation case file manager, evidence attachment, cryptographic SHA-256 PDF/ZIP dossier export.
- **Dependencies:** Phase 10 (Alerts), Phase 11 (Journeys).
- **Rationale:** Investigators package alerts and journeys into formal evidence packages.

### Phase 14: Realtime WebSocket Gateway
- **Deliverables:** WebSocket connection manager, subscription channels, alert and status broadcast dispatcher.
- **Dependencies:** Phase 3 (Camera status), Phase 10 (Alerts).
- **Rationale:** Frontend requires real-time push for live monitoring.

### Phase 15: Security, RBAC & Audit Middleware
- **Deliverables:** JWT authentication, role-based route guards, automatic `audit_logs` persistence middleware.
- **Dependencies:** Phase 2 (Users table), all state-changing endpoints.
- **Rationale:** Must secure all endpoints before frontend integration.

### Phase 16: Tactical Command Frontend UI
- **Deliverables:** Single-page command dashboard (Leaflet map, multi-camera grid, live alert ticker, investigation workbench), trustworthy data-state chips (`LIVE`/`DEMO`).
- **Dependencies:** All backend REST APIs and WebSocket gateway.
- **Rationale:** Frontend consumes all underlying verified APIs.

### Phase 17: Comprehensive End-to-End Testing & Verification
- **Deliverables:** Automated test suite (unit, integration, load), performance benchmark logs, demo scenario scripts.
- **Dependencies:** Fully integrated frontend and backend.
- **Rationale:** Validates adherence to the Definition of Done.
