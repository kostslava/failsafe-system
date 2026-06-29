import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_EDGE_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(_EDGE_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_EDGE_AGENT_DIR))

STATIC_DIR = Path(__file__).resolve().parent / "static"


class DashboardState(BaseModel):
    system_status: str = "INITIALIZING"
    image_base64: str | None = None
    snapshot_at: str | None = None
    analyzing: bool = False
    print_progress: float = 0.0
    analysis: str = ""
    print_status: str = "nominal"
    issue_detected: bool = False
    time_info: dict[str, Any] = Field(default_factory=dict)
    ai_logs: list[str] = Field(default_factory=list)
    updated_at: str = ""


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in self.active:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)

        for websocket in stale:
            self.disconnect(websocket)


app = FastAPI(title="Vision-Loop FailSafe Dashboard")
manager = ConnectionManager()
latest_state = DashboardState().model_dump()


@app.on_event("startup")
async def startup_live_camera() -> None:
    try:
        from live_camera import start_live_camera

        start_live_camera()
    except Exception as exc:
        logger.warning("Live camera startup deferred: %s", exc)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    return latest_state


@app.post("/api/state")
async def update_state(state: DashboardState) -> dict[str, str]:
    global latest_state
    latest_state = state.model_dump()
    await manager.broadcast(latest_state)
    return {"status": "ok"}


@app.post("/api/reset")
async def reset_monitoring() -> dict[str, str]:
    from runtime import get_orchestrator

    orchestrator = get_orchestrator()
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not running")
    if not orchestrator.request_reset():
        raise HTTPException(status_code=409, detail="Monitoring is not halted")
    return {"status": "ok"}


async def _mjpeg_generator():
    boundary = b"frame"
    from live_camera import get_live_camera

    camera = get_live_camera()
    while True:
        jpeg = camera.get_jpeg()
        if jpeg:
            yield (
                b"--"
                + boundary
                + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(jpeg)).encode()
                + b"\r\n\r\n"
                + jpeg
                + b"\r\n"
            )
        await asyncio.sleep(1 / 12)


@app.get("/stream.mjpg")
async def live_stream() -> StreamingResponse:
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        await websocket.send_json(latest_state)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as exc:
        logger.debug("WebSocket closed: %s", exc)
        manager.disconnect(websocket)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=False)
