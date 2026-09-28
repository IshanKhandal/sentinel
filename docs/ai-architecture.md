# Sentinel AI & Inference Architecture

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md))  
> **Mandatory Rule 10 Enforcement:** No accuracy or benchmark numbers (e.g., mAP, precision, recall, FPS) may be claimed without reproducible, recorded benchmark logs from actual hardware tests.

---

## 1. Modular Interface Design

To prevent vendor and model lock-in, all computer vision tasks are decoupled through abstract Python interfaces (`typing.Protocol` / `abc.ABC`). The pipeline can swap underlying providers (e.g., ONNX Runtime, PyTorch, TensorRT, or Mock Fixtures) without modifying business logic.

```text
 ┌──────────────────────────────────────────────────────────────┐
 │                     RAW VIDEO FRAME                          │
 └──────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │             ObjectDetector (Vehicle Localization)            │
 └──────────────────────────────┬───────────────────────────────┘
                                │ [Vehicle Bounding Boxes]
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │              PlateDetector (LP Sub-Region Cropping)          │
 └──────────────────────────────┬───────────────────────────────┘
                                │ [Plate Crop Tensors]
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │               OCRProvider (Character Recognition)            │
 └──────────────────────────────┬───────────────────────────────┘
                                │ [Plate Text & Regex Validation]
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │                VehicleTracker (Intra-Camera Tracks)          │
 └──────────────────────────────────────────────────────────────┘
```

---

## 2. Pluggable Interface Specifications

### Interface 1: `ObjectDetector`
- **Purpose:** Locate and classify vehicles within a video frame.
- **Python Signature:**
  ```python
  class ObjectDetector(abc.ABC):
      @abc.abstractmethod
      def detect(self, frame: np.ndarray) -> List[ObjectDetectionResult]:
          """
          Input: frame (H, W, 3) BGR uint8 NumPy array
          Output: List of ObjectDetectionResult
          """
          pass
  ```
- **Input:** Raw decoded frame tensor (`numpy.ndarray`, shape `(H, W, 3)`, dtype `uint8`).
- **Output:** `ObjectDetectionResult` containing:
  - `bbox`: Tuple `(x1, y1, x2, y2)` normalized to `[0.0, 1.0]`.
  - `class_name`: `VehicleClass` (`CAR`, `TRUCK`, `BUS`, `MOTORCYCLE`).
  - `confidence`: `float` between `0.0` and `1.0`.
  - `model_version`: `str` (e.g., `yolov8n-onnx-v1.0`).
  - `inference_latency_ms`: `float` (measured execution time).
- **Failure Behavior:** If an exception occurs during tensor conversion or inference, catches error, logs stack trace, increments `inference_errors` counter, and returns an empty list `[]` to avoid pipeline crash.

---

### Interface 2: `PlateDetector`
- **Purpose:** Locate the precise license plate rectangle on a detected vehicle crop.
- **Python Signature:**
  ```python
  class PlateDetector(abc.ABC):
      @abc.abstractmethod
      def detect_plate(self, vehicle_crop: np.ndarray) -> Optional[PlateDetectionResult]:
          pass
  ```
- **Input:** Cropped vehicle image (`numpy.ndarray`).
- **Output:** Optional `PlateDetectionResult`:
  - `bbox_relative`: `(x1, y1, x2, y2)` relative to vehicle crop.
  - `confidence`: `float` (`0.0` to `1.0`).
  - `plate_crop`: Cropped BGR array of the license plate.
  - `model_version`: `str`.
  - `inference_latency_ms`: `float`.
- **Failure Behavior:** Returns `None` if no plate candidate exceeds the detection threshold (default: `0.50`).

---

### Interface 3: `OCRProvider`
- **Purpose:** Transcribe alphanumeric characters from the cropped license plate image.
- **Python Signature:**
  ```python
  class OCRProvider(abc.ABC):
      @abc.abstractmethod
      def recognize_text(self, plate_crop: np.ndarray) -> Optional[OCRResult]:
          pass
  ```
- **Input:** High-contrast cropped license plate image.
- **Output:** Optional `OCRResult`:
  - `raw_text`: Direct model text output (e.g., `"GJ 01 AB 1234"`).
  - `normalized_text`: Sanitized, uppercase, unspaced string (e.g., `"GJ01AB1234"`).
  - `char_confidences`: List of per-character confidence scores.
  - `is_valid_format`: Boolean indicating compliance with Indian registration syntax regex (`^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$`).
  - `model_version`: `str`.
  - `inference_latency_ms`: `float`.
- **Failure Behavior:** If character confidence is low or text fails basic character validation, returns raw text with `is_valid_format: False`.

---

### Interface 4: `VehicleTracker`
- **Purpose:** Associate vehicle detections across consecutive frames to maintain consistent identities within a camera stream.
- **Python Signature:**
  ```python
  class VehicleTracker(abc.ABC):
      @abc.abstractmethod
      def update(self, detections: List[ObjectDetectionResult], frame_timestamp: float) -> List[TrackedVehicle]:
          pass
  ```
- **Input:** List of current-frame vehicle detections + presentation timestamp (PTS).
- **Output:** List of `TrackedVehicle` records containing `track_id`, `state` (`ACTIVE`, `LOST`), and smoothed trajectory history.
- **Failure Behavior:** If tracker loses tracklet for more than 30 frames, marks tracklet as `CLOSED` and archives tracklet duration.

---

### Interface 5: `VehicleReIdentification` (Target Architecture)
- **Purpose:** Extract high-dimensional feature embeddings (ReID vectors) to correlate vehicles across different cameras without relying solely on OCR.
- **Python Signature:**
  ```python
  class VehicleReIdentification(abc.ABC):
      @abc.abstractmethod
      def extract_features(self, vehicle_crop: np.ndarray) -> np.ndarray:
          """Output: 512-dimensional normalized float32 feature embedding"""
          pass
  ```
- **Input:** Cropped vehicle image.
- **Output:** 512-dim normalized feature vector.
- **Failure Behavior:** Returns zero-vector if crop is too small (< 64x64) or occluded.

---

## 3. Latency Measurement & Performance Tracking

Every inference call is wrapped in a high-resolution timer (`time.perf_counter_ns`):
```python
t_start = time.perf_counter_ns()
result = model.predict(tensor)
latency_ms = (time.perf_counter_ns() - t_start) / 1_000_000.0
```
- In-memory rolling circular buffer maintains latency history over the last 1,000 frames.
- If rolling average latency exceeds `150ms` per frame, the frame processor enables adaptive frame-skipping (processing every Nth frame) to prevent queue overflow.

---

## 4. Current Verification Baseline

- **Verified Models in Workspace:** None currently present.
- **Claimed Accuracies:** 0.0% (Strict Rule 10 adherence: no accuracy claims permitted until tested against verified validation datasets).
- **Supported Implementations to be Built:**
  1. `MockInferenceProvider` (For offline integration and unit testing).
  2. `ONNXRuntimeProvider` (For CPU/GPU production execution).
