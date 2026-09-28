# Sentinel Demo vs. Live Operational Modes

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md), Rules 5, 6, 29, 30, 31)

---

## 1. The Two Operational States

The system formally supports **EXACTLY TWO** mutually isolated operational modes:

### `DEMO` MODE
- **Definition:** The platform operates using local synthetic fixtures, sample test videos, or mock API responses.
- **Purpose:** Development, automated continuous integration tests, and offline hackathon demonstration.
- **Labeling Standard:** Every UI component, camera feed, map marker, and report generated in DEMO mode MUST display a persistent, high-contrast badge: `[DEMO]`.
- **Constraint:** Demo data must NEVER be claimed or presented as real surveillance feeds or government records.

### `LIVE` MODE
- **Definition:** The platform processes exclusively genuine, verified surveillance streams, real hardware sensor packets, and authenticated government databases.
- **Rule on Missing Dependencies:** If a configured live integration (e.g., an RTSP camera stream or police database) becomes unreachable or is not yet configured:
  - The component **MUST NEVER** silently switch to `DEMO` mode or show simulated data.
  - The component **MUST** display:
    ```text
    UNAVAILABLE
    ```
    or
    ```text
    OFFLINE
    ```
  - It must **NEVER** display `LIVE` or `CONNECTED` unless live telemetry packets are actively flowing and verified.

---

## 2. UI Component Data-State Table

| Data State | When to Display | Visual Presentation |
|---|---|---|
| **`LIVE`** | Active, real-time data streaming from a verified authentic source. | Emerald Green badge with subtle pulse indicator |
| **`DEMO`** | Synthetic, mock, or prerecorded playback data in demo mode. | Amber Orange badge with bold `[DEMO]` label |
| **`OFFLINE`** | Live source configured, but connection dropped or timed out. | Dark Grey badge with slash icon |
| **`UNAVAILABLE`** | Resource not configured or required external service missing. | Crimson Red badge with warning indicator |
| **`UNKNOWN`** | Telemetry source provenance cannot be conclusively verified. | Muted Purple badge with question mark |

---

## 3. Code Isolation Architecture

- **Backend Flag:** `SENTINEL_OPERATION_MODE=DEMO` vs `SENTINEL_OPERATION_MODE=LIVE`.
- **Directory Isolation:** All mock datasets, video loops, and synthetic generator scripts reside strictly under `tests/fixtures/` and `src/mock/`.
- **Fail-Safe Guard:** Under `SENTINEL_OPERATION_MODE=LIVE`, all mock generator modules are completely bypassed and deactivated. An unconfigured live resource throws an explicit `IntegrationUnavailableException`.

---

## 4. GIS & Map Data Fidelity Rules

- **Zero Coordinate Hallucination:** A camera without verified latitude/longitude from the official catalogue must NEVER be placed on the map (no (0, 0), no Gujarat geographic center, no fake police stations).
- **Map Badge Statuses:**
  - `EMPTY (0 MAPPED)`: Default state when the camera registry has no cameras with verified GPS coordinates.
  - `DEMO DATA`: Displayed only when synthetic fixtures are explicitly loaded in testing or demo runs.
  - `MAP TILES UNAVAILABLE`: Displayed when network connection to the tile server fails or times out.
  - `LIVE DATA`: Displayed only when verified camera coordinates from the official Sentinel catalogue are actively plotted.
- **Unmapped Camera Drawer:** Cameras lacking verified coordinates are explicitly listed in an "Unmapped Cameras" panel with their ID and reason (`No verified coordinates`), ensuring operator visibility without geographic fabrication.
 
---

## 5. ANPR & OCR Visual Debugger Data-State Fidelity

- **Visual Annotations Banner:** Every debug snapshot rendered via `/api/v1/anpr/debug-snapshot/{camera_id}` carries an explicit banner:
  ```text
  [DEBUG/TEST ONLY] CAM: <camera_id> | PTS: <pts_ms> | PLATES READ: <count>
  ```
- **Fidelity Guarantee:**
  - Bounding boxes are rendered in the exact source camera frame pixel coordinates.
  - OCR transcription is rendered with raw character confidence.
  - Invalid crops or unreadable plates are labeled `INVALID_CROP` or `OCR_UNREADABLE`; plate text is NEVER fabricated.

---

## 6. Event Persistence Data Fidelity & Provenance

- **`is_demo` Column Guarantee:** Every detection persisted into the `detections` table explicitly sets `is_demo = TRUE` if the source stream or environment mode is `DEMO`.
- **Zero Masquerading:** Test fixtures, synthetic detections, and demo stream frames are NEVER stored with `is_demo = FALSE`.
- **Zero Fake Seed Data:** No synthetic plates, vehicles, or detections are pre-seeded in the database to simulate live traffic. Real database tables remain completely unpopulated until valid observations are processed.

---

## 7. Watchlist Matching Data Fidelity & Provenance

- **`is_demo` Match Propagation:** Every match result evaluated from a DEMO detection or observation explicitly carries `is_demo = True` in its `WatchlistMatchResult` contract.
- **Zero Masquerading:** DEMO matches are NEVER presented or persisted as verified LIVE police watchlist hits.
- **Zero Fake Seed Hotlists:** No synthetic wanted persons, fake FIR numbers, or mock stolen vehicle hotlists are pre-seeded into the production database. The live database tables `watchlists` and `watchlist_entries` remain at 0 rows until authorized officers configure them.
- **Accuracy Invariant:** Watchlist matching performance is reported strictly as `Matching accuracy: NOT BENCHMARKED` until verified benchmarks on representative datasets are performed.

---

## 8. Alert Engine Data Fidelity & Provenance

- **`is_demo` Alert Provenance:** Every alert created from a DEMO detection strictly exposes `is_demo = True` via its underlying detection association in `AlertRead`.
- **Zero Alert Fabrication:** Alerts are generated exclusively upon verified Stage 9 watchlist match events. No synthetic alerts are fabricated to populate dashboards or mock system activity.
- **Live Database Invariant:** The live database table `alerts` remains strictly at 0 rows until authentic matches are processed.
- **Performance Invariant:** Alert generation throughput and deduplication latency are explicitly reported as `Alert performance: NOT BENCHMARKED` until verified benchmarks are conducted.

---

## 9. Vehicle History Data Fidelity & Provenance

- **`is_demo` Provenance Preservation:** Every historical observation item returned in `VehicleObservationItem` preserves the `is_demo` flag from the underlying `Detection` entity. Demo observations are never disguised as live Sentinel Gujarat Police surveillance history.
- **Zero History Fabrication:** When a plate search matches no persisted detections in the database, the API returns a truthful empty response (`total_observations: 0`, `items: []`). No synthetic observations, mock camera sightings, or fabricated route timestamps are generated.
- **Missing Coordinate Invariant:** Unmapped cameras or missing registry coordinates serialize strictly as `null` and are never replaced with placeholder coordinates like `(0.0, 0.0)`.
- **Performance Invariant:** Vehicle history retrieval throughput is reported strictly as `Vehicle history performance: NOT BENCHMARKED` until formal database load tests are conducted.

---

## 10. Cross-Camera Correlation Data Fidelity & Provenance

- **`is_demo` Journey Provenance:** If any underlying observation in the journey sequence is marked `is_demo = True`, `VehicleJourneyResponse.is_demo` is set to `True`. Demo-derived journeys are never presented as live police intelligence.
- **Zero Route Fabrication:** A correlated sequence of camera sightings is strictly represented as verified camera waypoints with GeoJSON property `route_inference: "NONE_CAMERA_POINTS_ONLY"`. Road network routing, turn-by-turn navigation, and intermediate interpolation are strictly prohibited.
- **Zero Coordinate Fabrication:** Unmapped camera waypoints serialize with `latitude: null, longitude: null` and transitions involving them report `distance_km: null` and `plausibility_status: "PLAUSIBILITY_UNKNOWN"`. Coordinates are never fabricated as `0,0`.
- **Empty History Fidelity:** If a plate has never been detected, the journey endpoint returns `correlation_status: "INSUFFICIENT_DATA"` with 0 waypoints and 0 transitions.
- **Performance Invariant:** Multi-camera graph traversal and trajectory correlation throughput are explicitly reported as `Correlation performance: NOT BENCHMARKED` until formal benchmarks are conducted.

---

## 11. Investigation Engine Data Fidelity & Provenance

- **`is_demo` Event Provenance:** When observations or alerts originating from DEMO mode or test fixtures are attached to an investigation, `InvestigationEventRead.is_demo` remains `True`. Synthetic events are never disguised as real police intelligence.
- **Zero Case File Pre-Seeding:** The production tables `investigations`, `investigation_events`, and `evidence` remain at 0 rows until authorized officers open real case files. No synthetic criminal case files or fabricated investigations are pre-populated.
- **Zero Evidence File Fabrication:** Digital evidence metadata requires genuine file paths and cryptographic SHA-256 hashes. Creating fake evidence files or fabricated cryptographic hashes is strictly prohibited.
- **Evidence Export Reservation:** Cryptographic evidence export (ZIP/PDF dossier) is reserved for the export engine and returns `EVIDENCE EXPORT NOT IMPLEMENTED` (HTTP 501).
- **Performance Invariant:** Investigation graph retrieval and case timeline indexing are explicitly reported as `Investigation performance: NOT BENCHMARKED` until formal database load tests are conducted.

---

## 12. Realtime WebSocket Gateway Data Fidelity & Provenance

- **`mode` Envelope Field Guarantee:** Every realtime event envelope broadcast over WebSockets explicitly carries a `mode` field (`DEMO` or `LIVE`). Any event originating from demo feeds, synthetic test fixtures, or demo streams sets `mode = "DEMO"`.
- **Zero Event Simulation / Fabrication:** When no live detection, camera status change, alert, or investigation update occurs in the system, the event bus remains strictly idle. Synthetic alerts, mock sightings, or fake vehicles are NEVER pushed over the WebSocket to make a dashboard look active.
- **Ephemeral Transport Invariant:** WebSockets serve strictly as an ephemeral push notification transport. Database persistence remains the single authoritative source of truth. WebSockets do not manufacture state or replay synthetic history upon connection.
- **Performance Invariant:** Realtime WebSocket gateway throughput, broadcast latency under 1000 concurrent connections, and backpressure eviction rates are explicitly reported as `WebSocket performance: NOT BENCHMARKED` until verified benchmarks are conducted.

---

## 13. Security, RBAC & Audit Data Fidelity & Provenance

- **Demo Credentials & Officer Separation:** Seeded credentials created for demonstration (`SYS001: SentinelAdmin2026!`, `INV001: Investigator2026!`, `OP001: Operator2026!`, `AUD001: Auditor2026!`) are strictly classified as local demonstration identities. Production deployments require authoritative officer badge provisioning and secret rotation.
- **Zero Tampering Endpoints:** Audit records stored in `audit_logs` are immutable and append-only. No API endpoint or administrative interface allows updating, editing, or deleting audit log entries.
- **Zero Role Escalation:** Operators, Investigators, and Auditors cannot grant themselves administrative privileges. Role modifications require an authenticated `SuperAdmin` session.
- **Performance Invariant:** Cryptographic password hashing (Bcrypt cost 12) and JWT verification latency under concurrent load are explicitly reported as `Auth performance: NOT BENCHMARKED` until formal benchmarks are conducted.

---

## 14. Tactical Operational UI & End-to-End Demonstration Guidelines

- **Real Data Integrity Invariant:** The tactical web application at `GET /` consumes authentic REST endpoints and the `/api/v1/ws` WebSocket exclusively. Zero simulated canvas feeds, mock random tickers, or synthetic counters are permitted.
- **Multi-State Visual Coding Standard:**
  - `LIVE` (Emerald Green): Active, authenticated real-world CCTV streams and telemetry.
  - `DEMO` (Amber Orange): Explicit synthetic fixtures generated by `scripts/seed_demo_data.py` or automated tests.
  - `OFFLINE` (Dark Grey): Registered cameras or streams whose connection has timed out.
  - `UNAVAILABLE` (Crimson Red): Unconfigured external dependencies (e.g., live RTSP host or external Vahan DB).
  - `UNKNOWN` (Muted Purple): Observations or telemetry with incomplete provenance.
- **Demonstration Flow Execution:**
  - Launch API server: `python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`.
  - Ensure demo data is seeded: `python scripts/seed_demo_data.py`.
  - Open `http://localhost:8000` in browser.
  - Authenticate using `SYS001` or `INV001`.
  - Search target plate: `GJ01AB1234` to inspect chronological sightings, speed anomalies, camera waypoints, and the non-hallucinated GIS observation route.
  - Navigate to **Hotlists & Alerts** to review the active match and acknowledge it.
  - Navigate to **Investigations** to inspect case `CASE-E2E-2026` with attached events and verified SHA-256 evidence metadata.

