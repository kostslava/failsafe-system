import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


class WebDashboardClient:
    def __init__(self, base_url: str = settings.web_app_url) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=2.0)

    def push_state(self, payload: dict[str, Any]) -> None:
        try:
            response = self._client.post(f"{self.base_url}/api/state", json=payload)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to push dashboard state: %s", exc)

    def close(self) -> None:
        self._client.close()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
