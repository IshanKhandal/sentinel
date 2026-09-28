# Sentinel Target Architecture Proposal

> **Protocol Note:** In accordance with Phase 0 Directive 13, this document describes the proposed target architecture to evolve toward. **NO COMPONENT IN THIS DOCUMENT HAS BEEN IMPLEMENTED YET.**

---

## 1. High-Level System Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        SENTINEL SYSTEM OVERVIEW                        │
└────────────────────────────────────────────────────────────────────────┘

  [ VIDEO INGESTION LAYER ]
       │
       ├── Live CCTV Streams (RTSP / HLS / WebRTC)
       └── Prerecorded / Synthetic Demo Videos (Explicit DEMO mode)
       │
       ▼
  [ VIDEO PROCESSING & INFERENCE PIPELINE ] (Python / OpenCV / YOLO / OCR)
       │
       ├── Stream Demuxer & Frame Buffer (Threaded / Async)
       ├── Object Detection (Vehicle / Person bounding boxes)
       ├── License Plate Recognition (ANPR / OCR)
       ├── Feature Extraction & Re-Identification (Cross-camera matching)
       └── Rule Engine (Speed violation, wrong-way, geofence, watchlist check)
       │
       ▼
  [ DATA PERSISTENCE & EVENT BROKER ]
       │
       ├── Event Broker / Cache (Redis Pub/Sub or In-Memory Queue)
       ├── Relational & Spatial Database (PostgreSQL + PostGIS or SQLite/SpatiaLite)
       └── Media Storage (Snapshots, cropped plate crops, evidence clips)
       │
       ▼
  [ BACKEND CORE API & REAL-TIME DISPATCHER ] (FastAPI / WebSockets)
       │
       ├── REST Endpoints: Cameras, Detections, Watchlists, Investigations, Audit Log
       ├── WebSocket Gateway: Real-time telemetry, alert push, stream signaling
       └── RBAC & Security Guard: Token validation, audit trail logging
       │
       ▼
  [ FRONTEND COMMAND & CONTROL DASHBOARD ] (Vite / React or Vanilla Web Components)
       │
       ├── Tactical GIS Map: Live camera markers, vehicle trajectories, heatmaps
       ├── Surveillance Grid: Multi-stream video monitoring with data-state badges
       ├── Real-Time Alert Ticker: Prioritized watchlist matches with evidence review
       ├── Investigation Workbench: Historical search, plate lookup, journey reconstruction
       └── System Health & Provenance Panel: Live vs Demo indicators, stream latency
```

---

## 2. Layer Specifications

### 2.1 Video Ingestion Layer
- **Ingestion Engine:** OpenCV VideoCapture with fallback adapter for synthetic video loops.
- **Protocol Support:** RTSP, HTTP/HLS, MP4 test clips.
- **Failover / Provenance:** Explicit stream status reporting (`LIVE`, `DEMO`, `OFFLINE`).

### 2.2 Inference & Analytics Engine
- **Vehicle Detection Model:** Lightweight CNN (e.g., YOLOv8n / YOLOv11n) for real-time bounding box extraction (`car`, `truck`, `bus`, `motorcycle`).
- **Plate Detection & OCR:** Dual-stage pipeline: (1) License plate locator, (2) Character OCR (PaddleOCR or EasyOCR or specialized ANPR network).
- **Tracker:** ByteTRACK or DeepSORT for intra-camera tracking; color/attribute extraction for cross-camera trajectory correlation.

### 2.3 Persistence Layer
- **Primary Data Store:** PostgreSQL with PostGIS extension (for geographic coordinates and trajectory queries) or SQLite with spatial extension during local development.
- **Entity Schemas:**
  - `cameras`: ID, name, location (lat, lng), RTSP URL, status, zone.
  - `vehicles`: License plate, make, model, color, first_seen, last_seen.
  - `detections`: Camera ID, vehicle ID, timestamp, bbox, plate_crop_path, confidence.
  - `watchlists`: Plate number, category (Stolen, Wanted, Suspect), priority, notes.
  - `alerts`: Detection ID, watchlist ID, timestamp, status (New, Acknowledged, Dismissed).
  - `audit_logs`: User ID, action, timestamp, IP, details.

### 2.4 API & WebSocket Layer
- **Framework:** Python FastAPI (asynchronous, high performance, native OpenAPI documentation).
- **Real-Time Push:** WebSocket server broadcasting detection events, tracking updates, and critical watchlist alerts to connected frontend clients.

### 2.5 Frontend Tactical Dashboard
- **Visual Design:** High-contrast tactical command center aesthetics, dark mode theme, GIS map visualization (Leaflet / MapLibre).
- **Trustworthy State UI:** Every stream and detection widget incorporates mandatory state chips (`LIVE`, `DEMO`, `OFFLINE`, `UNAVAILABLE`) adhering to Rule 30.

---

## 3. Implementation Phasing Strategy

1. **Phase 1:** Core Data Contracts, Schema Models, and Ingestion Adapter (supporting both synthetic fixtures and real stream endpoints).
2. **Phase 2:** Computer Vision Pipeline (Vehicle Detection + ANPR + Tracking).
3. **Phase 3:** Backend API & WebSocket Service (Camera Registry, Watchlist Engine, Alert Dispatcher).
4. **Phase 4:** Frontend Command & Control UI (GIS Map, Live Stream Grid, Real-Time Alert Feed).
5. **Phase 5:** End-to-End Verification, Benchmark Logging, and Submission Preparation.
