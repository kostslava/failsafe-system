import logging
from typing import Optional

from live_camera import get_live_camera, start_live_camera

logger = logging.getLogger(__name__)


class CameraHandler:
    def __init__(self) -> None:
        self._live = get_live_camera()

    def open(self) -> None:
        start_live_camera()

    def close(self) -> None:
        # Keep the live stream running for the dashboard after monitoring halts.
        pass

    def capture_frame_base64(self) -> Optional[str]:
        return self._live.capture_snapshot_base64()
