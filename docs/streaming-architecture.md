# Sentinel CCTV Streaming Architecture

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md))  
> **Supported Network Protocols:** RTSP (over TCP), Local MP4 Synthetic Loop (DEMO).  
> **Supported Video Codecs:** H.264 (AVC), H.265 (HEVC).

---

## 1. Stream Processing Pipeline

```text
┌──────────────────────────────────────────────────────────────┐
│                    1. CAMERA REGISTRY                        │
│ (Loads camera URI, credentials reference, stream_type, zone) │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    2. STREAM DISCOVERY                       │
│    (Validates URI scheme, checks host network reachability)  │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    3. STREAM MANAGER                         │
│  (Worker process/thread supervisor, lifecycle & health loop) │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    4. RTSP OVER TCP                          │
│   (Interleaved RTP over TCP socket: avoids UDP packet drops) │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    5. HARDWARE/SOFTWARE DECODER              │
│       (H.264 / H.265 bitstream demuxer to raw RGB/BGR)       │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│             6. PTS-AWARE FRAME PROCESSOR                     │
│    (Timestamp normalization, frame decimation, FPS pacing)   │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    7. AI INFERENCE PIPELINE                  │
│    (Bounded ring buffer handoff to YOLO & ANPR workers)      │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Ingestion Protocol & Transport Rules

### Mandatory Transport: RTSP over TCP (Interleaved)
- **Problem with UDP in Surveillance:** CCTV surveillance feeds transmitted over UDP frequently suffer from lost packets, macroblocking, packet reordering, and green smear artifacts under real-world police networks.
- **Enforcement:** All RTSP client connections MUST mandate TCP transport via OpenCV / FFmpeg flags:
  ```python
  # Mandatory transport configuration
  os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"
  ```
- **Socket Timeout:** `stimeout` set to `5,000,000` microseconds (5 seconds). Prevents worker thread deadlocks if an IP camera stops responding.

---

## 3. Codec & Resolution Handling

### Codec Support: H.264 & H.265
- **H.264 (AVC):** Primary standard for legacy urban CCTV feeds. High compatibility, low CPU decode overhead.
- **H.265 (HEVC):** Deployed on modern 4K and highway surveillance cameras. High compression efficiency; decoded via software CPU fallback or hardware NVDEC where available.

### Mixed Resolutions
- Cameras across Gujarat police jurisdictions vary from 720p (`1280x720`), 1080p (`1920x1080`), to 4K (`3840x2160`).
- **Aspect-Ratio Preserving Letterboxing:** The PTS-aware frame processor resizes incoming frames dynamically to the model's standardized input tensor dimension (e.g., `640x640`) using letterbox padding. No stretching or distortion of license plate characters is allowed.

---

## 4. Reconnection & Resilience Strategy

Surveillance cameras in real-world deployments frequently restart, experience switch reboots, or suffer transient link dropouts.

```text
[Stream Lost / EOF]
       │
       ▼
 [Record OFFLINE] ────► [Emit camera.status_changed]
       │
       ▼
 [Backoff Wait] (1s -> 2s -> 4s -> 8s -> 16s -> max 30s)
       │
       ▼
 [Retry Connection]
       │
       ├─── SUCCESS ────► [Drain stale buffer] ──► [Reset backoff] ──► [Mark LIVE]
       │
       └─── FAILURE ────► [Increment attempt] ───► [Repeat Backoff]
```

### Exponential Backoff Algorithm
```python
def calculate_reconnect_delay(attempt: int) -> float:
    base_delay = 1.0
    max_delay = 30.0
    factor = 2.0
    # Add 10% jitter to prevent thundering herd when network switch recovers
    jitter = random.uniform(0.9, 1.1)
    delay = min(base_delay * (factor ** attempt), max_delay) * jitter
    return delay
```

---

## 5. Decoder Warnings, Irregular Intervals & PTS Timestamps

### Presentation Timestamps (PTS)
- **Irregular Frame Delivery:** IP cameras rarely output frames at perfectly spaced intervals. Frame intervals jitter due to network contention and variable bitrate (VBR) encoding.
- **PTS Handling:** The frame manager must NEVER assume fixed `1/30s` deltas. It reads the hardware PTS timestamp embedded in the video stream:
  - If hardware PTS is absent, the system attaches monotonic clock time (`time.monotonic()`) at the exact moment the frame was decoded.
  - All detection records and tracking calculations reference this absolute timestamp.

### Decoder Warnings & Corruption
- If the decoder encounters macroblocking, corrupt NAL units, or keyframe desync:
  - Discards the corrupted frame.
  - Logs a warning metric (`decoder_errors_total`).
  - Waits for the next recovery IDR/I-Frame before resuming AI handoff.

---

## 6. Stream Health Telemetry

Every stream worker publishes a periodic heartbeat every 5 seconds to the internal health registry:
- `fps_measured`: Real-time decoded frames per second.
- `bitrate_kbps`: Ingestion data rate.
- `frame_drop_count`: Number of dropped frames due to inference backpressure.
- `last_frame_pts`: Timestamp of the latest successfully decoded frame.

If `time.now() - last_frame_pts > 10 seconds`, the stream supervisor forcefully terminates the decoder thread and triggers the reconnection sequence.
