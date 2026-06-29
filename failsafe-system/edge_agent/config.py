import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # App Lab injects VIDEO_DEVICE; CAMERA_DEVICE overrides if set explicitly.
    camera_device: str = os.getenv(
        "CAMERA_DEVICE", os.getenv("VIDEO_DEVICE", "/dev/video0")
    )
    camera_width: int = int(os.getenv("CAMERA_WIDTH", "640"))
    camera_height: int = int(os.getenv("CAMERA_HEIGHT", "480"))

    bambu_broker_host: str = os.getenv("BAMBU_BROKER_HOST", "192.168.1.100")
    bambu_broker_port: int = int(os.getenv("BAMBU_BROKER_PORT", "8883"))
    bambu_serial_number: str = os.getenv("BAMBU_SERIAL_NUMBER", "REPLACE_ME")
    bambu_access_code: str = os.getenv("BAMBU_ACCESS_CODE", "REPLACE_ME")
    bambu_username: str = os.getenv("BAMBU_USERNAME", "bblp")

    cerebras_api_key: str = os.getenv("CEREBRAS_API_KEY", "")
    cerebras_model: str = os.getenv("CEREBRAS_MODEL", "gemma-4-31b")

    web_app_url: str = os.getenv("WEB_APP_URL", "http://127.0.0.1:8080")
    loop_interval_seconds: float = float(os.getenv("LOOP_INTERVAL_SECONDS", "4.0"))

    arduino_router_socket: str = os.getenv(
        "ARDUINO_ROUTER_SOCKET", "/var/run/arduino-router.sock"
    )
    mcu_rpc_method: str = os.getenv("MCU_RPC_METHOD", "status_command")


settings = Settings()
