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

