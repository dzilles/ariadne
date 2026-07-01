"""Runtime tracking for active agent runs."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RunState:
    id: str
    agent_name: str
    message: str
    status: str = "running"
    cancel_requested: bool = False
    started_at: datetime = field(default_factory=datetime.now)


class RunAlreadyActiveError(RuntimeError):
    """Raised when a new run is requested while another run is active."""


class RunCancelledError(RuntimeError):
    """Raised when a cooperative cancellation point is reached."""


_lock = threading.RLock()
_active_run: Optional[RunState] = None


def start_run(agent_name: str, message: str) -> RunState:
    """Start a new run, rejecting concurrent runs."""
    global _active_run
    with _lock:
        if _active_run and _active_run.status == "running":
            raise RunAlreadyActiveError(
                f"{_active_run.agent_name} is still running."
            )
        _active_run = RunState(
            id=uuid.uuid4().hex,
            agent_name=agent_name,
            message=message,
        )
        return _active_run


def finish_run(run_id: str) -> None:
    """Mark the active run as finished if it still matches."""
    global _active_run
    with _lock:
        if _active_run and _active_run.id == run_id:
            _active_run.status = "finished"
            _active_run = None


def fail_run(run_id: str) -> None:
    """Mark the active run as failed if it still matches."""
    global _active_run
    with _lock:
        if _active_run and _active_run.id == run_id:
            _active_run.status = "failed"
            _active_run = None


def request_cancel() -> Optional[RunState]:
    """Request cancellation for the active run."""
    with _lock:
        if _active_run and _active_run.status == "running":
            _active_run.cancel_requested = True
            return _active_run
        return None


def get_active_run() -> Optional[RunState]:
    """Return the active run, if any."""
    with _lock:
        return _active_run


def is_cancel_requested() -> bool:
    """Return True when the active run should stop at the next tool boundary."""
    with _lock:
        return bool(
            _active_run
            and _active_run.status == "running"
            and _active_run.cancel_requested
        )


def raise_if_cancelled() -> None:
    """Raise when cancellation has been requested."""
    if is_cancel_requested():
        raise RunCancelledError("Run cancellation requested by user.")
