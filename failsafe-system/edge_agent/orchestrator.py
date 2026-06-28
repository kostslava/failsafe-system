import logging
import sys
import time
from typing import Any

from camera_handler import CameraHandler
from cerebras_client import CerebrasVisionClient
from config import settings
from mcu_serial import MCUSerialClient
from printer_client import PrinterClient
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
        self.system_status = "RUNNING SAFELY"
        self.ai_logs: list[str] = []
        self.halted = False

    def _append_log(self, message: str) -> None:
        timestamp = utc_now_iso()
        entry = f"[{timestamp}] {message}"
        self.ai_logs.append(entry)
        self.ai_logs = self.ai_logs[-100:]

    def _publish(
        self,
        image_b64: str | None,
        analysis: str = "",
        print_status: str = "nominal",
        issue_detected: bool = False,
        time_info: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "system_status": self.system_status,
            "image_base64": image_b64,
            "print_progress": self.printer.print_progress,
            "analysis": analysis,
            "print_status": print_status,
            "issue_detected": issue_detected,
            "time_info": time_info or {},
            "ai_logs": self.ai_logs,
            "updated_at": utc_now_iso(),
        }
        self.dashboard.push_state(payload)

    def run(self) -> None:
        logger.info("Starting Vision-Loop FailSafe orchestrator")
        self.camera.open()
        self.printer.start()

        self._publish(image_b64=None, analysis="FailSafe monitoring initialized.")
        self.mcu.send_command("STATUS_OK")

        while not self.halted:
            loop_started = time.perf_counter()

            frame_b64 = self.camera.capture_frame_base64()
            if frame_b64 is None:
                self._append_log("Camera frame capture failed; retrying next cycle.")
                self._publish(image_b64=None)
                time.sleep(settings.loop_interval_seconds)
                continue

            self.mcu.send_command("STATUS_THINKING")
            self._publish(image_b64=frame_b64, analysis="Analyzing frame with Gemma 4...")

            analysis_result = self.cerebras.analyze_frame(frame_b64)
            if analysis_result is None:
                self._append_log("Cerebras inference unavailable; keeping last safe state.")
                self.mcu.send_command("STATUS_OK")
                self._publish(
                    image_b64=frame_b64,
                    analysis="Inference temporarily unavailable.",
                    time_info={"error": "cerebras_request_failed"},
                )
                self._sleep_until_next_cycle(loop_started)
                continue

            self._append_log(analysis_result.analysis)

            if analysis_result.print_status == "critical_failure":
                halt_latency = time.perf_counter() - loop_started
                self.system_status = "EMERGENCY HALT"
                self.halted = True

                self.mcu.send_command("STATUS_FAIL")
                pause_ok = self.printer.pause_print()

                halt_message = (
                    f"CRITICAL FAILURE detected. End-to-end halt latency: "
                    f"{halt_latency:.3f}s. Pause command sent: {pause_ok}."
                )
                self._append_log(halt_message)
                logger.error(halt_message)

                self._publish(
                    image_b64=frame_b64,
                    analysis=analysis_result.analysis,
                    print_status=analysis_result.print_status,
                    issue_detected=analysis_result.issue_detected,
                    time_info={
                        **analysis_result.time_info,
                        "halt_latency_seconds": round(halt_latency, 4),
                    },
                )
                break

            self.mcu.send_command("STATUS_OK")
            self.system_status = "RUNNING SAFELY"
            self._publish(
                image_b64=frame_b64,
                analysis=analysis_result.analysis,
                print_status=analysis_result.print_status,
                issue_detected=analysis_result.issue_detected,
                time_info=analysis_result.time_info,
            )

            self._sleep_until_next_cycle(loop_started)

        logger.info("Orchestrator halted")
        self.shutdown()

    def _sleep_until_next_cycle(self, loop_started: float) -> None:
        elapsed = time.perf_counter() - loop_started
        remaining = settings.loop_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def shutdown(self) -> None:
        self.camera.close()
        self.printer.stop()
        self.mcu.close()
        self.dashboard.close()


def main() -> None:
    orchestrator = FailSafeOrchestrator()
    try:
        orchestrator.run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        orchestrator.shutdown()


if __name__ == "__main__":
    main()
