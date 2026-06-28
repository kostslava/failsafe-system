import base64
import logging
from typing import Optional

import cv2

from config import settings

logger = logging.getLogger(__name__)


class CameraHandler:
    def __init__(
        self,
        device: str = settings.camera_device,
        width: int = settings.camera_width,
        height: int = settings.camera_height,
    ) -> None:
        self.device = device
        self.width = width
        self.height = height
        self._capture: Optional[cv2.VideoCapture] = None

    def open(self) -> None:
        if self._capture is not None and self._capture.isOpened():
            return

        capture = cv2.VideoCapture(self.device)
        if not capture.isOpened():
            raise RuntimeError(f"Unable to open camera device {self.device}")

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._capture = capture
        logger.info("Camera opened on %s at %dx%d", self.device, self.width, self.height)

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def capture_frame_base64(self) -> Optional[str]:
        if self._capture is None or not self._capture.isOpened():
            self.open()

        assert self._capture is not None
        ok, frame = self._capture.read()
        if not ok or frame is None:
            logger.warning("Failed to read frame from %s", self.device)
            return None

        resized = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        encode_ok, buffer = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not encode_ok:
            logger.warning("Failed to encode frame as JPEG")
            return None

        return base64.b64encode(buffer.tobytes()).decode("ascii")
