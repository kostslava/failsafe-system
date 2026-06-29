import logging
import sys
import threading
import time
from typing import Any

from camera_handler import CameraHandler
from cerebras_client import CerebrasVisionClient
from config import settings
from mcu_serial import MCUSerialClient
from printer_client import PauseResult, PrinterClient
from web_client import WebDashboardClient, utc_now_iso

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("orchestrator")


class FailSafeOrchestrator:
    def __init__(self) -> None:
        self.camera = CameraHandler()
        self.printer = PrinterClient()
        self.cerebras = CerebrasVisionClient()
        self.mcu = MCUSerialClient()
        self.dashboard = WebDashboardClient()
        self.system_status = "INITIALIZING"
        self.ai_logs: list[str] = []
        self.halted = False
        self._reset_event = threading.Event()
        self._printer_started = False
        self._halt_lock = threading.Lock()
        self._halt_started_at: float | None = None
        self._pause_result: PauseResult | None = None
        self._last_snapshot_at: str | None = None
        self._last_frame_b64: str | None = None

    def _append_log(self, message: str) -> None:
        timestamp = utc_now_iso()
        entry = f"[{timestamp}] {message}"
        self.ai_logs.append(entry)
        self.ai_logs = self.ai_logs[-100:]

    def _publish(
        self,
        image_b64: str | None = None,
        analysis: str = "",
        print_status: str = "nominal",
        issue_detected: bool = False,
        time_info: dict[str, Any] | None = None,
        snapshot_at: str | None = None,
        analyzing: bool = False,
    ) -> None:
        payload = {
            "system_status": self.system_status,
            "image_base64": image_b64,
            "snapshot_at": snapshot_at,
            "analyzing": analyzing,
            "print_progress": self.printer.print_progress,
            "analysis": analysis,
            "print_status": print_status,
            "issue_detected": issue_detected,
            "time_info": time_info or {},
            "ai_logs": self.ai_logs,
            "updated_at": utc_now_iso(),
        }
        self.dashboard.push_state(payload)

    def request_reset(self) -> bool:
        if not self.halted:
            return False
        self._reset_event.set()
        return True

    def run_forever(self) -> None:
        logger.info("Starting Vision-Loop FailSafe orchestrator")
        self.camera.open()

        while True:
            self._run_monitoring_cycle()
            logger.info("Monitoring halted — waiting for reset from dashboard")
            self._reset_event.wait()
            self._reset_event.clear()
            logger.info("Reset received — resuming monitoring")

    def run(self) -> None:
        self.run_forever()

    def _trigger_emergency_halt(self) -> None:
        with self._halt_lock:
            if self.halted:
                return

            self.halted = True
            self.system_status = "EMERGENCY HALT"
            self._halt_started_at = time.perf_counter()

            self.mcu.send_command("STATUS_FAIL")
            self._pause_result = self.printer.emergency_pause()

            self._publish(
                image_b64=self._last_frame_b64,
                analysis="Critical failure detected — halting printer now...",
                print_status="critical_failure",
                issue_detected=True,
                snapshot_at=self._last_snapshot_at,
                analyzing=True,
                time_info={
                    "halt_trigger": "stream",
                    "printer_state": self.printer.gcode_state,
                },
            )

    def _run_monitoring_cycle(self) -> None:
        self.halted = False
        self.system_status = "RUNNING SAFELY"
        self._halt_started_at = None
        self._pause_result = None

        if not self._printer_started:
            self.printer.start()
            self._printer_started = True

        self._publish(analysis="FailSafe monitoring initialized.")
        self.mcu.send_command("STATUS_OK")

        while not self.halted:
            loop_started = time.perf_counter()
            snapshot_at = utc_now_iso()
            self._last_snapshot_at = snapshot_at

            frame_b64 = self.camera.capture_frame_base64()
            if frame_b64 is None:
                self._append_log("Camera frame capture failed; retrying next cycle.")
                self._publish(analysis="Waiting for camera frame...")
                time.sleep(settings.loop_interval_seconds)
                continue

            self._last_frame_b64 = frame_b64
            self.mcu.send_command("STATUS_THINKING")
            self._publish(
                image_b64=frame_b64,
                analysis="Analyzing frame with Gemma 4...",
                snapshot_at=snapshot_at,
                analyzing=True,
            )

            analysis_result = self.cerebras.analyze_frame(
                frame_b64,
                on_critical_detected=self._trigger_emergency_halt,
            )
            if analysis_result is None:
                self._append_log("Cerebras inference unavailable; keeping last safe state.")
                self.mcu.send_command("STATUS_OK")
                self._publish(
                    image_b64=frame_b64,
                    analysis="Inference temporarily unavailable.",
                    snapshot_at=snapshot_at,
                    analyzing=False,
                    time_info={"error": "cerebras_request_failed"},
                )
                self._sleep_until_next_cycle(loop_started)
                continue

            self._append_log(analysis_result.analysis)

            if analysis_result.print_status == "critical_failure":
                if not self.halted:
                    self._trigger_emergency_halt()

                pause_result = self._pause_result or PauseResult()
                halt_latency = (
                    time.perf_counter() - self._halt_started_at
                    if self._halt_started_at is not None
                    else time.perf_counter() - loop_started
                )

                pause_detail = "confirmed" if pause_result.confirmed else "NOT confirmed"
                if pause_result.error:
                    pause_detail = f"{pause_detail} — {pause_result.error}"

                halt_message = (
                    f"CRITICAL FAILURE detected. Halt latency: {halt_latency:.3f}s. "
                    f"Printer pause: {pause_detail}."
                )
                self._append_log(halt_message)
                logger.error(halt_message)

                self._publish(
                    image_b64=frame_b64,
                    analysis=analysis_result.analysis,
                    print_status=analysis_result.print_status,
                    issue_detected=analysis_result.issue_detected,
                    snapshot_at=snapshot_at,
                    analyzing=False,
                    time_info={
                        **analysis_result.time_info,
                        "halt_latency_seconds": round(halt_latency, 4),
                        "printer_pause_confirmed": pause_result.confirmed,
                        "printer_gcode_state": pause_result.gcode_state or self.printer.gcode_state,
                        "printer_pause_error": pause_result.error,
                    },
                )
                return

            self.mcu.send_command("STATUS_OK")
            self.system_status = "RUNNING SAFELY"
            self._publish(
                image_b64=frame_b64,
                analysis=analysis_result.analysis,
                print_status=analysis_result.print_status,
                issue_detected=analysis_result.issue_detected,
                snapshot_at=snapshot_at,
                analyzing=False,
                time_info=analysis_result.time_info,
            )

            self._sleep_until_next_cycle(loop_started)

    def _sleep_until_next_cycle(self, loop_started: float) -> None:
        elapsed = time.perf_counter() - loop_started
        remaining = settings.loop_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def shutdown(self) -> None:
        from live_camera import get_live_camera

        get_live_camera().stop()
        self.printer.stop()
        self.mcu.close()
        self.dashboard.close()


def main() -> None:
    orchestrator = FailSafeOrchestrator()
    try:
        orchestrator.run_forever()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        orchestrator.shutdown()


if __name__ == "__main__":
    main()
