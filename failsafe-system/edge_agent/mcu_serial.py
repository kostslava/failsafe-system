import logging
import socket
import threading
from typing import Optional

import msgpack

from config import settings

logger = logging.getLogger(__name__)

try:
    from arduino.app_utils import Bridge as AppBridge  # type: ignore

    _HAS_APP_BRIDGE = True
except ImportError:
    AppBridge = None
    _HAS_APP_BRIDGE = False


class MCUSerialClient:
    """Non-blocking MCU command transport for the Uno Q router bridge."""

    def __init__(
        self,
        socket_path: str = settings.arduino_router_socket,
        method_name: str = settings.mcu_rpc_method,
    ) -> None:
        self.socket_path = socket_path
        self.method_name = method_name
        self._lock = threading.Lock()
        self._socket: Optional[socket.socket] = None

    def _connect(self) -> socket.socket:
        if self._socket is not None:
            return self._socket

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(self.socket_path)
        client.setblocking(True)
        self._socket = client
        return client

    def _send_notify(self, command: str) -> None:
        payload = msgpack.packb([2, self.method_name, [command]])
        client = self._connect()
        client.sendall(payload)

    def send_command(self, command: str) -> None:
        def _worker() -> None:
            try:
                if _HAS_APP_BRIDGE and AppBridge is not None:
                    AppBridge.notify(self.method_name, command)
                    return
                self._send_notify(command)
            except Exception as exc:
                logger.warning("MCU command %s failed: %s", command, exc)
                self._socket = None

        threading.Thread(target=_worker, daemon=True).start()

    def close(self) -> None:
        with self._lock:
            if self._socket is not None:
                try:
                    self._socket.close()
                except OSError:
                    pass
                self._socket = None
