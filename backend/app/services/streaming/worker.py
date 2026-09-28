"""Isolated, thread-safe stream worker for RTSP video ingestion.

Protocol Standards:
- Section 6: RTSP MUST force TCP (OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp").
- Section 8: cv2.CAP_FFMPEG backend used for capture.
- Section 9: PTS is the authoritative source of video time (CAP_PROP_POS_MSEC).
- Section 10: Never trust CAP_PROP_FPS; calculate measured FPS dynamically.
- Section 11: Irregular frame intervals tolerated without false disconnects.
- Section 13: Exponential backoff with jitter on disconnect.
- Section 14: Mid-stream decoder join warnings are non-fatal.
- Section 17: Looping scene PTS discontinuities handled gracefully.
- Section 20: Clean resource cleanup on stop().
"""

import os
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Tuple
import cv2
import numpy as np

from backend.app.core.config import settings
from backend.app.schemas.streaming import StreamSessionResponse, StreamState
from backend.app.services.streaming.models import DecodedFrame, sanitize_stream_url
from backend.app.services.streaming.ring_buffer import FrameRingBuffer
from backend.app.services.streaming.backoff import ExponentialBackoff

logger = logging.getLogger("sentinel.streaming.worker")


class StreamWorker:
    """Manages an isolated RTSP video capture thread for a single surveillance camera."""

    def __init__(
        self,
        camera_id: str,
        stream_url: str,
        codec: Optional[str] = None,
        ring_buffer: Optional[FrameRingBuffer] = None,
        backoff: Optional[ExponentialBackoff] = None,
    ) -> None:
        self.camera_id = camera_id
        self.stream_url = stream_url
        self.codec = codec or "H.264"
        self.ring_buffer = ring_buffer or FrameRingBuffer(capacity=settings.STREAM_RING_BUFFER_SIZE)
        self.backoff = backoff or ExponentialBackoff(
            base_delay=settings.STREAM_RECONNECT_BASE_DELAY,
            max_delay=settings.STREAM_RECONNECT_MAX_DELAY,
            factor=settings.STREAM_RECONNECT_FACTOR,
        )

        # Thread synchronization
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Telemetry & State
        self._state: StreamState = "NOT_CONFIGURED"
        self._frames_received: int = 0
        self._reconnect_count: int = 0
        self._decoder_errors: int = 0
        self._last_pts_ms: Optional[float] = None
        self._pts_delta_ms: Optional[float] = None
        self._last_frame_mono: Optional[float] = None
        self._last_frame_at: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._started_at: Optional[datetime] = None
        self._resolution: Optional[Tuple[int, int]] = None
        self._fps_measured: Optional[float] = None

        # FPS measurement sliding window
        self._fps_window_start: float = time.monotonic()
        self._fps_window_frames: int = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def state(self) -> StreamState:
        with self._lock:
            return self._state

    def start(self) -> None:
        """Start the video ingestion worker thread."""
        with self._lock:
            if self.is_running:
                logger.warning("Stream worker %s already running", self.camera_id)
                return

            self._stop_event.clear()
            self._started_at = datetime.now(timezone.utc)
            self._thread = threading.Thread(
                target=self._run_loop,
                name=f"StreamWorker-{self.camera_id[:8]}",
                daemon=True
            )
            self._thread.start()
            logger.info("Started stream worker for camera %s on %s", self.camera_id, sanitize_stream_url(self.stream_url))

    def stop(self, timeout: float = 3.0) -> None:
        """Signal the worker thread to stop and clean up resources."""
        self._stop_event.set()
        self.ring_buffer.close()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        with self._lock:
            self._state = "OFFLINE"
            self._thread = None

        logger.info("Stopped stream worker for camera %s", self.camera_id)

    def get_session_info(self) -> StreamSessionResponse:
        """Compile a thread-safe snapshot of session telemetry."""
        with self._lock:
            res_str = f"{self._resolution[0]}x{self._resolution[1]}" if self._resolution else None
            return StreamSessionResponse(
                camera_id=self.camera_id,
                stream_url=sanitize_stream_url(self.stream_url),
                protocol="RTSP",
                codec=self.codec,
                resolution=res_str,
                connection_state=self._state,
                frames_received=self._frames_received,
                frames_dropped=self.ring_buffer.dropped_count,
                reconnect_count=self._reconnect_count,
                decoder_errors=self._decoder_errors,
                last_pts_ms=self._last_pts_ms,
                pts_delta_ms=self._pts_delta_ms,
                fps_measured=self._fps_measured,
                current_backoff_seconds=self.backoff.peek_delay(),
                buffer_depth=self.ring_buffer.size,
                buffer_capacity=self.ring_buffer.capacity,
                last_error=self._last_error,
                started_at=self._started_at,
                last_frame_at=self._last_frame_at,
            )

    def _configure_rtsp_environment(self) -> None:
        """Enforce strict TCP transport and timeout parameters for OpenCV FFmpeg backend."""
        # Section 6: MANDATORY TCP INVARIANT
        timeout_us = settings.RTSP_CONNECT_TIMEOUT_MS * 1000
        opts = f"rtsp_transport;{settings.RTSP_TRANSPORT}|stimeout;{timeout_us}"
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = opts

    def _is_unconfigured_or_invalid_url(self) -> bool:
        """Verify if URL points to an unconfigured Sentinel placeholder."""
        if not self.stream_url:
            return True
        lowered = self.stream_url.lower()
        if "unconfigured" in lowered or "none" in lowered or not lowered.startswith("rtsp://"):
            return True
        return False

    def _run_loop(self) -> None:
        """Main supervisory and decoding loop."""
        self._configure_rtsp_environment()

        # Check for unconfigured stream
        if self._is_unconfigured_or_invalid_url():
            with self._lock:
                self._state = "NOT_CONFIGURED"
                self._last_error = "RTSP stream URL is unconfigured (SENTINEL_STREAM_HOST unset)"
            logger.info("Camera %s stream is NOT_CONFIGURED. Halting worker loop.", self.camera_id)
            return

        consecutive_frames = 0

        while not self._stop_event.is_set():
            with self._lock:
                self._state = "CONNECTING"

            cap: Optional[cv2.VideoCapture] = None
            try:
                # Open capture forcing CAP_FFMPEG backend
                logger.debug("Opening RTSP connection for %s (TCP forced)", self.camera_id)
                cap = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)

                if not cap.isOpened():
                    raise ConnectionError(f"Failed to open RTSP stream at {sanitize_stream_url(self.stream_url)}")

                consecutive_frames = 0
                logger.info("RTSP connection established for camera %s", self.camera_id)

                while not self._stop_event.is_set():
                    ret, frame = cap.read()

                    if not ret or frame is None or frame.size == 0:
                        # Non-fatal decoder hiccup / mid-join warning tolerance (Section 14)
                        with self._lock:
                            self._decoder_errors += 1
                        logger.debug("Decoder read hiccup for %s, retrying frame read", self.camera_id)
                        
                        # Check if connection completely died
                        if not cap.isOpened():
                            raise ConnectionError("VideoCapture reported closed socket during read")
                        time.sleep(0.01)
                        continue

                    # Frame successfully decoded
                    now_mono = time.monotonic()
                    now_utc = datetime.now(timezone.utc)

                    # Section 9: Authoritative PTS handling
                    # CAP_PROP_POS_MSEC returns millisecond presentation timestamp
                    raw_pts = cap.get(cv2.CAP_PROP_POS_MSEC)
                    is_discontinuity = False

                    if raw_pts > 0:
                        pts = float(raw_pts)
                    else:
                        # Fallback when hardware PTS is absent: attach monotonic-based relative ms
                        pts = (now_mono - self._fps_window_start) * 1000.0

                    # Section 17: Looping scene PTS discontinuity detection
                    with self._lock:
                        if self._last_pts_ms is not None:
                            delta = pts - self._last_pts_ms
                            if delta < -1000.0:
                                # Negative PTS jump indicates looped recording reset
                                logger.info("Detected looping stream PTS discontinuity on %s: delta=%.1fms", self.camera_id, delta)
                                is_discontinuity = True
                                self._pts_delta_ms = 0.0
                            else:
                                self._pts_delta_ms = round(delta, 2)
                        else:
                            self._pts_delta_ms = 0.0

                        self._last_pts_ms = pts
                        self._last_frame_mono = now_mono
                        self._last_frame_at = now_utc
                        self._frames_received += 1
                        height, width = frame.shape[:2]
                        self._resolution = (width, height)
                        self._state = "LIVE"

                    consecutive_frames += 1
                    if consecutive_frames >= settings.STREAM_CONSECUTIVE_FRAMES_FOR_HEALTH:
                        self.backoff.reset()

                    # Push decoded frame into bounded ring buffer
                    decoded_obj = DecodedFrame(
                        frame_index=self._frames_received,
                        camera_id=self.camera_id,
                        pts_ms=pts,
                        data=frame,
                        width=width,
                        height=height,
                        monotonic_ts=now_mono,
                        pts_delta_ms=self._pts_delta_ms,
                        is_loop_discontinuity=is_discontinuity,
                    )
                    self.ring_buffer.push(decoded_obj)

                    # Update rolling measured FPS (Section 10: Never trust CAP_PROP_FPS)
                    self._fps_window_frames += 1
                    elapsed = now_mono - self._fps_window_start
                    if elapsed >= 2.0:
                        with self._lock:
                            self._fps_measured = round(self._fps_window_frames / elapsed, 1)
                        self._fps_window_frames = 0
                        self._fps_window_start = now_mono

            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                    self._state = "RECONNECTING"
                    self._reconnect_count += 1
                    delay = self.backoff.next_delay()

                logger.warning(
                    "Stream connection lost for %s (%s). Reconnecting in %.2fs (attempt %d)",
                    self.camera_id, exc, delay, self.backoff.attempt
                )

                if self._stop_event.wait(timeout=delay):
                    break

            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

        with self._lock:
            self._state = "OFFLINE"
