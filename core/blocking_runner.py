"""Presentation-neutral synchronous execution for callback-based runners."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, Protocol

from .job_callbacks import JobCallbacks


class BlockingRunner(Protocol):
    def is_running(self) -> bool: ...
    def stop(self, *, force: bool = False) -> None: ...


@dataclass(frozen=True)
class RunResult:
    elapsed_s: float
    completed: bool = False
    stopped: bool = False
    interrupted: bool = False
    error: BaseException | None = None
    console: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.completed and not self.stopped and self.error is None

    def with_interrupted(self, interrupted: bool = True) -> "RunResult":
        return replace(
            self,
            interrupted=interrupted,
            stopped=self.stopped or (interrupted and not self.completed),
        )


def run_blocking(
    runner: BlockingRunner,
    start: Callable[[JobCallbacks], None],
    *,
    timeout: float | None = None,
    on_progress: Callable[..., None] | None = None,
    on_console: Callable[[str], None] | None = None,
) -> RunResult:
    """Start ``runner`` and block without owning signals or output streams."""
    done = threading.Event()
    console: list[str] = []
    errors: list[BaseException] = []
    state = {"completed": False, "stopped": False}

    def console_callback(value: str) -> None:
        console.append(value)
        if on_console is not None:
            on_console(value)

    def complete_callback() -> None:
        state["completed"] = True
        done.set()

    def stopped_callback() -> None:
        state["stopped"] = True
        done.set()

    def error_callback(exc: BaseException) -> None:
        errors.append(exc)
        done.set()

    callbacks = JobCallbacks(
        on_progress=on_progress,
        on_console=console_callback,
        on_complete=complete_callback,
        on_stopped=stopped_callback,
        on_error=error_callback,
    )
    started = time.perf_counter()
    try:
        try:
            start(callbacks)
            while not done.wait(timeout=0.25):
                if not runner.is_running():
                    break
                if timeout is not None and time.perf_counter() - started > timeout:
                    runner.stop(force=True)
                    state["stopped"] = True
                    errors.append(TimeoutError(f"processing exceeded {timeout:.0f}s"))
                    break
        except BaseException as exc:  # runner failures are returned, not presented here
            errors.append(exc)
    finally:
        thread = getattr(runner, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        try:
            release = getattr(runner, "release_inference_memory", None)
            if callable(release):
                release(clear_weight_cache=False)
        except Exception:
            pass
    return RunResult(
        elapsed_s=time.perf_counter() - started,
        completed=state["completed"],
        stopped=state["stopped"],
        error=errors[0] if errors else None,
        console=tuple(console),
    )


__all__ = ["BlockingRunner", "RunResult", "run_blocking"]
