import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from orchestrator import FailSafeOrchestrator

_orchestrator: Optional["FailSafeOrchestrator"] = None
_lock = threading.Lock()


def set_orchestrator(orchestrator: "FailSafeOrchestrator") -> None:
    global _orchestrator
    with _lock:
        _orchestrator = orchestrator


def get_orchestrator() -> Optional["FailSafeOrchestrator"]:
    with _lock:
        return _orchestrator
