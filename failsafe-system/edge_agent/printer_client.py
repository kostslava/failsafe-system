import json
import logging
import ssl
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

from config import settings

logger = logging.getLogger(__name__)

PAUSE_STATES = {"PAUSE", "PAUSED"}
ACTIVE_PRINT_STATES = {"RUNNING", "PREPARE", "SLICING"}


@dataclass
class PauseResult:
    confirmed: bool = False
    gcode_state: str = ""
    attempts: int = 0
    last_result: str = ""
    hms_errors: list[Any] = field(default_factory=list)
    error: str = ""


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
        self._connect_event = threading.Event()
        self._pause_confirmed = threading.Event()
        self._sequence_id = 0
        self._print_progress = 0.0
        self._gcode_state = ""
        self._last_command_result = ""
        self._last_hms: list[Any] = []
        self._loop_started = False

    @property
    def print_progress(self) -> float:
        with self._lock:
            return self._print_progress

    @property
    def gcode_state(self) -> str:
        with self._lock:
            return self._gcode_state

    def _report_topic(self) -> str:
        return f"device/{self.serial_number}/report"

    def _request_topic(self) -> str:
        return f"device/{self.serial_number}/request"

    def _next_sequence_id(self) -> str:
        with self._lock:
            self._sequence_id += 1
            return str(self._sequence_id)

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
        if rc != 0:
            logger.error("MQTT connect failed with rc=%s", rc)
            return

        self._connected = True
        self._connect_event.set()
        client.subscribe(self._report_topic(), qos=0)
        logger.info("MQTT connected; subscribed to %s", self._report_topic())
        self._publish({"pushing": {"sequence_id": self._next_sequence_id(), "command": "pushall"}})

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        self._connected = False
        self._connect_event.clear()
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

        print_data = payload.get("print")
        if not isinstance(print_data, dict):
            return

        with self._lock:
            if "gcode_state" in print_data:
                self._gcode_state = str(print_data["gcode_state"])
                if self._gcode_state in PAUSE_STATES:
                    self._pause_confirmed.set()

            if "result" in print_data:
                self._last_command_result = str(print_data.get("result", ""))

            if print_data.get("hms"):
                self._last_hms = print_data["hms"]
                logger.error("Printer HMS report: %s", self._last_hms)

            if print_data.get("print_error") or print_data.get("fail_reason"):
                logger.error(
                    "Printer error report: print_error=%s fail_reason=%s",
                    print_data.get("print_error"),
                    print_data.get("fail_reason"),
                )

            if print_data.get("command") in {"pause", "stop"}:
                logger.info(
                    "Printer command ack: command=%s result=%s reason=%s",
                    print_data.get("command"),
                    print_data.get("result"),
                    print_data.get("reason"),
                )

        progress = self._extract_progress(payload)
        if progress is not None:
            with self._lock:
                self._print_progress = progress
            if self.on_progress is not None:
                try:
                    self.on_progress(progress)
                except Exception as exc:
                    logger.warning("Progress callback failed: %s", exc)

    def _publish(self, payload: dict[str, Any]) -> bool:
        if not self._connected:
            logger.error("Cannot publish — MQTT not connected")
            return False

        try:
            result = self._client.publish(
                self._request_topic(),
                json.dumps(payload),
                qos=1,
            )
            result.wait_for_publish(timeout=5.0)
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as exc:
            logger.error("MQTT publish failed: %s", exc)
            return False

    def _send_print_command(self, command: str, param: str = "") -> bool:
        payload = {
            "print": {
                "sequence_id": self._next_sequence_id(),
                "command": command,
                "param": param,
            }
        }
        logger.warning("Sending printer command: %s", payload)
        return self._publish(payload)

    def start(self) -> None:
        if self._loop_started:
            return

        try:
            self._client.connect(self.broker_host, self.broker_port, keepalive=60)
            self._client.loop_start()
            self._loop_started = True
        except Exception as exc:
            logger.error("MQTT startup failed: %s", exc)
            return

        if not self._connect_event.wait(timeout=10.0):
            logger.error("MQTT connect timed out for %s:%s", self.broker_host, self.broker_port)

    def pause_print(self) -> bool:
        return self.emergency_pause().confirmed

    def emergency_pause(self) -> PauseResult:
        result = PauseResult(gcode_state=self.gcode_state)

        if self.gcode_state in PAUSE_STATES:
            result.confirmed = True
            return result

        if not self._connected:
            result.error = "MQTT not connected"
            logger.error(result.error)
            return result

        self._pause_confirmed.clear()

        for attempt in range(1, 4):
            result.attempts = attempt
            sent = self._send_print_command("pause", "")
            if not sent:
                result.error = "Failed to publish pause command"
                time.sleep(0.4)
                continue

            if self._pause_confirmed.wait(timeout=4.0):
                result.confirmed = True
                result.gcode_state = self.gcode_state
                result.last_result = self._last_command_result
                logger.warning("Printer pause confirmed (state=%s)", self.gcode_state)
                return result

            with self._lock:
                result.gcode_state = self._gcode_state
                result.last_result = self._last_command_result
                result.hms_errors = list(self._last_hms)

            if self._gcode_state in PAUSE_STATES:
                result.confirmed = True
                return result

            logger.warning(
                "Pause attempt %s not confirmed (state=%s result=%s)",
                attempt,
                self._gcode_state,
                self._last_command_result,
            )
            time.sleep(0.5)

        if self._last_hms:
            result.error = (
                "Printer rejected pause command (HMS error). "
                "Enable LAN-Only mode and Developer Mode on the A1, "
                "then close Bambu Studio and Bambu Handy while FailSafe runs."
            )
        elif self.gcode_state in ACTIVE_PRINT_STATES:
            result.error = "Pause command sent but printer still reports RUNNING"
            logger.error("Attempting emergency STOP fallback")
            if self._send_print_command("stop", ""):
                time.sleep(2.0)
                result.gcode_state = self.gcode_state
                if self._gcode_state not in ACTIVE_PRINT_STATES:
                    result.confirmed = True
                    result.error = "Pause failed; sent STOP instead"
        else:
            result.error = "Pause command did not change printer state"

        logger.error("Emergency pause failed: %s", result.error)
        return result

    def stop(self) -> None:
        if self._loop_started:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._loop_started = False

        self._connected = False
        self._connect_event.clear()
