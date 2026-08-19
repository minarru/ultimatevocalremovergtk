"""Worker-thread callbacks for separation and audio-tool jobs.

:class:`JobRunner` and :class:`AudioToolRunner` invoke these from a ``KThread``.
GTK marshals them onto the main loop via :mod:`ui.dispatch`.
"""

from __future__ import annotations

import threading
import typing
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .debug_log import debug, next_seq, preview_text, set_correlation_seq, verbose
from .oom_choice import OOM_CHOICE_AUTO, OOM_CHOICE_STOP, OomChoiceRequest
from .run_control import check_stopped


@dataclass
class JobCallbacks:
    """Callbacks invoked from the worker thread.

    ``on_progress`` receives a float in ``[0.0, 1.0]`` plus optional keyword
    metadata (``local_step``, ``pass_index``, ``pass_total``, ``detail``,
    ``combine_index``, ``combine_total``). ``on_console`` receives text chunks;
    ``on_complete`` fires once on success; ``on_error`` receives the raised
    exception. ``on_oom_choice`` receives an :class:`OomChoiceRequest` on the
    main loop; the worker blocks until ``request.respond`` is called. The GTK
    layer marshals each of these onto the main loop.
    """

    on_progress: Optional[Callable[..., None]] = None
    on_console: Optional[Callable[[str], None]] = None
    on_complete: Optional[Callable[[], None]] = None
    on_stopped: Optional[Callable[[], None]] = None
    on_error: Optional[Callable[[BaseException], None]] = None
    on_oom_choice: Optional[Callable[[OomChoiceRequest], None]] = None
    on_input_start: Optional[Callable[[tuple[str, ...]], None]] = None
    on_input_finished: Optional[
        Callable[[tuple[str, ...], tuple[str, ...], BaseException | None], None]
    ] = None

    def progress(
        self,
        fraction: float,
        *,
        local_step: Optional[float] = None,
        pass_index: Optional[int] = None,
        pass_total: Optional[int] = None,
        detail: Optional[str] = None,
        combine_index: Optional[int] = None,
        combine_total: Optional[int] = None,
    ) -> None:
        if not self.on_progress:
            return
        clamped = max(0.0, min(1.0, fraction))
        self.on_progress(
            clamped,
            local_step=local_step,
            pass_index=pass_index,
            pass_total=pass_total,
            detail=detail,
            combine_index=combine_index,
            combine_total=combine_total,
        )

    def input_started(self, paths: typing.Sequence[str]) -> None:
        if self.on_input_start:
            self.on_input_start(tuple(paths))

    def input_finished(
        self, paths: typing.Sequence[str], generated: typing.Sequence[str] = (),
        error: BaseException | None = None,
    ) -> None:
        if self.on_input_finished:
            self.on_input_finished(tuple(paths), tuple(generated), error)

    def console(self, text: str) -> None:
        seq = next_seq()
        set_correlation_seq(seq)
        if verbose():
            debug("worker", f"console emit {preview_text(text)!r}", seq=seq)
        if self.on_console:
            self.on_console(text)

    def complete(self) -> None:
        debug("worker", "complete")
        if self.on_complete:
            self.on_complete()

    def stopped(self) -> None:
        debug("worker", "stopped")
        if self.on_stopped:
            self.on_stopped()

    def error(self, exc: BaseException) -> None:
        debug("worker", f"error {type(exc).__name__}: {exc}")
        if self.on_error:
            self.on_error(exc)

    def request_oom_choice(
        self,
        request: OomChoiceRequest,
        runner: Any,
    ) -> str:
        """Ask the UI for an OOM recovery choice, or return ``auto`` if unbound."""
        if not self.on_oom_choice:
            return OOM_CHOICE_AUTO

        done = threading.Event()
        box: dict[str, str] = {"choice": OOM_CHOICE_STOP}

        def reply(choice: str) -> None:
            box["choice"] = str(choice or OOM_CHOICE_STOP)
            done.set()

        request.reply = reply
        debug(
            "worker",
            "oom choice requested "
            f"kind={request.process_kind!r} export={request.can_export} "
            f"retry={request.can_retry}",
        )
        self.on_oom_choice(request)
        while not done.wait(timeout=0.05):
            check_stopped(runner)
        choice = box["choice"]
        debug("worker", f"oom choice={choice!r}")
        return choice
