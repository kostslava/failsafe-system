import logging
import threading
import time
from typing import Optional

import cv2

from config import settings

logger = logging.getLogger(__name__)

_INSTANCE: Optional["LiveCamera"] = None
_INSTANCE_LOCK = threading.Lock()


class LiveCamera:
    """Background camera capture for live MJPEG and AI snapshots."""

    def __init__(
        self,
        device: str = settings.camera_device,
        width: int = settings.camera_width,
        height: int = settings.camera_height,
        fps: float = 12.0,
    ) -> None:
        self.device = device
        self.width = width
        self.height = height
        self.frame_interval = 1.0 / max(fps, 1.0)

        self._capture: Optional[cv2.VideoCapture] = None
        self._latest_jpeg: Optional[bytes] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            self._running = True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        with self._lock:
            if self._capture is not None:
                self._capture.release()
                self._capture = None
            self._latest_jpeg = None
            self._running = False

    def _ensure_open(self) -> cv2.VideoCapture:
        if self._capture is not None and self._capture.isOpened():
            return self._capture

        capture = cv2.VideoCapture(self.device)
        if not capture.isOpened():
            raise RuntimeError(f"Unable to open camera device {self.device}")

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._capture = capture
        logger.info("Live camera opened on %s at %dx%d", self.device, self.width, self.height)
        return capture

    def _encode_frame(self, frame) -> Optional[bytes]:
        resized = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        ok, buffer = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return None
        return buffer.tobytes()

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            loop_start = time.perf_counter()
            try:
                capture = self._ensure_open()
                ok, frame = capture.read()
                if ok and frame is not None:
                    jpeg = self._encode_frame(frame)
                    if jpeg is not None:
                        with self._lock:
                            self._latest_jpeg = jpeg
                else:
                    logger.warning("Live camera read failed on %s", self.device)
                    time.sleep(0.2)
            except Exception as exc:
                logger.warning("Live camera loop error: %s", exc)
                with self._lock:
                    if self._capture is not None:
                        self._capture.release()
                        self._capture = None
                time.sleep(0.5)

            elapsed = time.perf_counter() - loop_start
            remaining = self.frame_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def capture_snapshot_base64(self) -> Optional[str]:
        import base64

        with self._lock:
            if self._latest_jpeg is None:
                return None
            return base64.b64encode(self._latest_jpeg).decode("ascii")


def get_live_camera() -> LiveCamera:
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            import os

            fps = float(os.getenv("LIVE_STREAM_FPS", "12"))
            _INSTANCE = LiveCamera(fps=fps)
        return _INSTANCE


def start_live_camera() -> LiveCamera:
    camera = get_live_camera()
    camera.start()
    return camera
