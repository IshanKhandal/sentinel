"""Centralized stream ingestion manager for surveillance cameras.

Protocol Standards:
- Section 20 & 21: Controlled activation (never open every camera automatically).
- Section 25: Exposes stream status, start/stop, snapshot generation.
- Clean shutdown on application lifecycle events.
"""

import logging
import threading
from typing import Dict, List, Optional
import cv2

from backend.app.schemas.streaming import StreamSessionResponse
from backend.app.services.streaming.worker import StreamWorker
from backend.app.services.streaming.models import sanitize_stream_url

logger = logging.getLogger("sentinel.streaming.manager")


class StreamManager:
    """Singleton stream session manager controlling lifecycle and telemetry."""

    _instance: Optional["StreamManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "StreamManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._workers: Dict[str, StreamWorker] = {}
                cls._instance._workers_lock = threading.Lock()
        return cls._instance

    def start_stream(
        self,
        camera_id: str,
        rtsp_url: str,
        codec: Optional[str] = None
    ) -> StreamSessionResponse:
        """Controlled activation of a video stream worker."""
        with self._workers_lock:
            if camera_id in self._workers:
                worker = self._workers[camera_id]
                if worker.is_running:
                    logger.debug("Stream already active for camera %s", camera_id)
                    return worker.get_session_info()
                else:
                    # Stale worker reference; clean up and recreate
                    worker.stop()
                    del self._workers[camera_id]

            worker = StreamWorker(
                camera_id=camera_id,
                stream_url=rtsp_url,
                codec=codec or "H.264"
            )
            self._workers[camera_id] = worker
            worker.start()

        return worker.get_session_info()

    def stop_stream(self, camera_id: str) -> bool:
        """Stop an active stream worker and release all decoder resources."""
        with self._workers_lock:
            worker = self._workers.pop(camera_id, None)

        if worker:
            worker.stop()
            return True
        return False

    def get_stream_session(self, camera_id: str) -> Optional[StreamSessionResponse]:
        """Fetch current telemetry for an active stream session."""
        with self._workers_lock:
            worker = self._workers.get(camera_id)

        if worker:
            return worker.get_session_info()
        return None

    def list_active_streams(self) -> List[StreamSessionResponse]:
        """List telemetry for all currently active stream workers."""
        with self._workers_lock:
            workers = list(self._workers.values())

        return [w.get_session_info() for w in workers]

    def get_snapshot_jpeg(self, camera_id: str, quality: int = 80) -> Optional[bytes]:
        """Extract latest decoded frame as compressed JPEG bytes."""
        with self._workers_lock:
            worker = self._workers.get(camera_id)

        if not worker:
            return None

        latest_frame = worker.ring_buffer.peek_latest()
        if latest_frame is None or latest_frame.data is None:
            return None

        success, encoded_img = cv2.imencode(
            ".jpg",
            latest_frame.data,
            [int(cv2.IMWRITE_JPEG_QUALITY), max(10, min(100, quality))]
        )
        if success:
            return encoded_img.tobytes()
        return None

    def shutdown_all(self) -> None:
        """Cleanly terminate all stream workers on server shutdown."""
        with self._workers_lock:
            workers = list(self._workers.values())
            self._workers.clear()

        logger.info("Shutting down %d active stream workers", len(workers))
        for worker in workers:
            try:
                worker.stop()
            except Exception as exc:
                logger.error("Error stopping worker %s: %s", worker.camera_id, exc)


# Global singleton instance
stream_manager = StreamManager()
