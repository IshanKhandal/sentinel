# Sentinel Gap Analysis

> **Protocol Note:** In accordance with Phase 0 Directive 14, this document contrasts the verified current project baseline against the target functional domain requirements for Sentinel.

---

## Gap Comparison Matrix

| ID | Requirement Area | Current State | Missing Functionality | Difficulty | Dependencies | Risk | Recommended Order |
|---|---|---|---|---|---|---|---|
| GAP-01 | **Camera Registry & Video Ingestion** | NON-EXISTENT (No camera tables, stream decoders, or RTSP readers) | Camera CRUD API, RTSP stream reader, frame buffer, stream health monitor, synthetic stream test fixture | MEDIUM | OpenCV / FFmpeg | Medium (RTSP network instability, codec variations) | 1 |
| GAP-02 | **Database Models & Persistence** | NON-EXISTENT (No DB schema or migration scripts) | Camera, Detection, Vehicle, Watchlist, Alert, and Audit log tables; repository persistence layer | LOW | SQLite / PostgreSQL | Low | 2 |
| GAP-03 | **Vehicle Detection & Classification** | NON-EXISTENT (No ML code or model weights) | Inference pipeline for vehicle localization (car, bus, truck, motorcycle), bounding box extraction, confidence thresholding | MEDIUM | PyTorch / ONNX Runtime / Ultralytics | Medium (CPU inference latency on edge machines) | 3 |
| GAP-04 | **License Plate Recognition (ANPR / OCR)** | NON-EXISTENT (No plate detection or OCR code) | License plate region localization, image preprocessing (deskew, binarization), character recognition OCR | HIGH | OCR engine (PaddleOCR/EasyOCR) | High (Indian plate font diversity, motion blur, nighttime illumination) | 4 |
| GAP-05 | **Vehicle Tracking & Trajectory Reconstruction** | NON-EXISTENT (No tracker or route mapping) | Intra-camera multi-object tracking (ByteTrack/SORT), cross-camera spatial-temporal correlation, vehicle journey route assembly | HIGH | Tracking algorithms, GIS spatial engine | High (ID switching, timestamp sync across cameras) | 5 |
| GAP-06 | **Watchlist Matching & Real-Time Alert Engine** | NON-EXISTENT (No matching rules or alert dispatch) | Real-time plate matching against hotlists (stolen, wanted), priority alert generation, alert deduplication | LOW | Event bus / DB lookup | Low | 6 |
| GAP-07 | **Backend REST & WebSocket API** | NON-EXISTENT (No API server) | FastAPI server, REST routes for management, WebSocket broadcaster for live telemetry and alert feeds | MEDIUM | FastAPI, Uvicorn, WebSockets | Low | 7 |
| GAP-08 | **Frontend Tactical UI & GIS Map** | NON-EXISTENT (No UI files) | Modern command dashboard, interactive GIS map (Leaflet), multi-camera grid with data-state badges (`LIVE`/`DEMO`), alert ticker | MEDIUM | React / Vite or Vanilla JS, CSS, Leaflet | Medium (Browser rendering performance with multiple video feeds) | 8 |
| GAP-09 | **Demo Mode & Synthetic Data Fixtures** | SPECIFIED IN DOCS, UNIMPLEMENTED IN CODE | Isolated mock data generator, prerecorded test clip loopers, verifiable sample scenarios | LOW | Video assets, mock generators | Low (Must strictly prevent bleeding into live logic) | 9 |
| GAP-10 | **Audit Logging & Security Controls** | SPECIFIED IN DOCS, UNIMPLEMENTED IN CODE | User action audit trail, authentication tokens, secret sanitization | LOW | Auth middleware | Low | 10 |

---

## Detailed Gap Analyses

### 1. Camera Ingestion & Stream Management (GAP-01)
- **Requirement:** System must connect to video feeds (RTSP/HLS/MP4), decode frames, and monitor stream health.
- **Current State:** Zero stream ingestion code. System PATH does not contain `ffmpeg`.
- **Missing Functionality:** Python-based multi-threaded stream ingestion, reconnect logic, frame dropping strategy under backpressure.
- **Difficulty:** Medium.
- **Risk:** Unreliable RTSP camera connections or high CPU usage without hardware acceleration.

### 2. ANPR & OCR Pipeline (GAP-04)
- **Requirement:** Accurately extract Indian vehicle license plates from video frames.
- **Current State:** Zero computer vision or OCR libraries installed or implemented.
- **Missing Functionality:** Two-stage detector: vehicle crop -> plate crop -> OCR character parser with regex validation for Indian registration numbers (e.g., `GJ-01-XX-1234`).
- **Difficulty:** High.
- **Risk:** Poor image resolution, angled cameras, non-standard fonts, dirty plates.

### 3. Route Reconstruction & Spatial Tracking (GAP-05)
- **Requirement:** Reconstruct a vehicle's path across multiple cameras with timestamps and map visualization.
- **Current State:** Zero spatial data, zero tracking code.
- **Missing Functionality:** Spatio-temporal graph algorithm matching plate detections across camera nodes with estimated velocity and direction.
- **Difficulty:** High.
- **Risk:** False positive plate matches generating erratic or impossible jump trajectories.
