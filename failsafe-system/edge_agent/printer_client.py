import json
import logging
import ssl
import threading
import time
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

from config import settings

logger = logging.getLogger(__name__)


class PrinterClient:
    def __init__(
        self,
        broker_host: str = settings.bambu_broker_host,
        broker_port: int = settings.bambu_broker_port,
        serial_number: str = settings.bambu_serial_number,
        access_code: str = settings.bambu_access_code,
        username: str = settings.bambu_username,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.serial_number = serial_number
        self.access_code = access_code
        self.username = username
        self.on_progress = on_progress

        self._client = mqtt.Client(protocol=mqtt.MQTTv311)
        self._client.username_pw_set(self.username, self.access_code)
        self._client.tls_set(cert_reqs=ssl.CERT_NONE)
        self._client.tls_insecure_set(True)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        self._lock = threading.Lock()
        self._connected = False
        self._print_progress = 0.0
        self._stop_event = threading.Event()
        self._loop_thread: Optional[threading.Thread] = None

    @property
    def print_progress(self) -> float:
        with self._lock:
            return self._print_progress

    def _report_topic(self) -> str:
        return f"device/{self.serial_number}/report"

    def _request_topic(self) -> str:
        return f"device/{self.serial_number}/request"

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
        if rc != 0:
            logger.error("MQTT connect failed with rc=%s", rc)
            return

        self._connected = True
        topic = self._report_topic()
        client.subscribe(topic, qos=0)
        logger.info("MQTT connected; subscribed to %s", topic)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        self._connected = False
        if rc != 0:
            logger.warning("MQTT disconnected unexpectedly (rc=%s)", rc)

    def _extract_progress(self, payload: dict) -> Optional[float]:
        print_data = payload.get("print")
        if not isinstance(print_data, dict):
            return None

        if "gcode_start_percent" in print_data:
            return float(print_data["gcode_start_percent"])

        if "mc_percent" in print_data:
            return float(print_data["mc_percent"])

        return None

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.debug("Ignoring malformed MQTT payload: %s", exc)
            return

        progress = self._extract_progress(payload)
        if progress is None:
            return

        with self._lock:
            self._print_progress = progress

        if self.on_progress is not None:
            try:
                self.on_progress(progress)
            except Exception as exc:
                logger.warning("Progress callback failed: %s", exc)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self._connected:
                    self._client.connect(self.broker_host, self.broker_port, keepalive=60)
                self._client.loop(timeout=1.0)
            except Exception as exc:
                logger.warning("MQTT loop error: %s", exc)
                self._connected = False
                try:
                    self._client.disconnect()
                except Exception:
                    pass
                time.sleep(2.0)

    def start(self) -> None:
        if self._loop_thread is not None and self._loop_thread.is_alive():
            return

        self._stop_event.clear()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

    def pause_print(self) -> bool:
        payload = {"print": {"sequence_id": "0", "command": "pause"}}
        try:
            result = self._client.publish(
                self._request_topic(),
                json.dumps(payload),
                qos=1,
            )
            result.wait_for_publish(timeout=5.0)
            logger.warning("Pause command published to %s", self._request_topic())
            return True
        except Exception as exc:
            logger.error("Failed to publish pause command: %s", exc)
            return False

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
