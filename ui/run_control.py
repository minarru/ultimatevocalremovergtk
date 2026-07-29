"""Shared Start/Stop dispatch and run lifecycle for the main window.

:class:`RunController` owns progress, console output, notifications and the
pinned running target so :class:`ui.window.MainWindow` can stay focused on
layout and settings. Ensemble and Audio Tools pages call
:meth:`RunController.begin_run` / :meth:`RunController.fail_to_start` through thin
delegates on the window.
"""

from __future__ import annotations

import os
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from gi.repository import Adw, Gio, GLib, Gtk

from bundled.constants import (
    QUIT_WHILE_PROCESSING_CONFIRM,
    STOP_PROCESS_CONFIRM,
    STOP_PROCESSING,
)

from core.debug_log import (
    clear_run_start,
    debug,
    mark_run_start,
    next_seq,
    preview_text,
    set_correlation_seq,
    verbose,
)
from core.run_estimate import ProgressEtaTracker
from core.separate_import import engines_imported, warm_status

from .dispatch import gtk_job_callbacks, idle_on_main, reset_progress_log
from .files import open_folder_in_file_manager
from .notifications import (
    NOTIFY_PROCESS_COMPLETE,
    NOTIFY_PROCESS_FAILED,
    send_desktop_notification,
)

if TYPE_CHECKING:
    from .window import MainWindow

_OPEN_FOLDER_LABEL = "Open Folder"
_NOTIFY_COMPLETE_TITLE = "{label} complete"
_NOTIFY_COMPLETE_BODY = "Saved to {folder}"
_NOTIFY_COMPLETE_BODY_PLAIN = "Processing finished"
_NOTIFY_FAILED_TITLE = "{label} failed"
_NOTIFY_FAILED_BODY = "Open the app to see the error log"
_PROGRESS_STARTING = "Starting…"
_PROGRESS_IMPORTING = "Importing engines…"
_PROGRESS_LOADING_ENGINES = "Loading engines…"
_PROGRESS_DONE = "Done"
_PROGRESS_EPSILON = 0.001
_PROGRESS_UI_MIN_INTERVAL = 0.1  # ~10 Hz UI updates during inference
_EXIT_CLEANUP_TIMEOUT_MS = 10_000


def _starting_progress_text() -> str:
    if engines_imported():
        return _PROGRESS_STARTING
    if warm_status() == "in_progress":
        return _PROGRESS_IMPORTING
    return _PROGRESS_LOADING_ENGINES


def target_blocked_reason(target) -> Optional[str]:
    """Return a target readiness reason without allowing UI validation to fail."""
    if target is None:
        return "Choose a processing mode"
    try:
        return target.start_blocked_reason()
    except Exception:  # noqa: BLE001 - readiness must never break the UI
        return None


class RunController:
    """Run lifecycle shared by Separation, Ensemble and Audio Tools."""

    def __init__(self, window: MainWindow):
        self._window = window
        self._running_target: Any = None
        self._run_output_dir = ""
        self._run_label = "Processing"
        self._run_started_at = 0.0
        self._eta_tracker = ProgressEtaTracker()
        self._last_progress_ui_at = 0.0
        self._last_progress_phase: Optional[str] = None
        self._last_progress_pass: Optional[int] = None
        self._last_progress_combine: Optional[int] = None
        self._stop_confirm_dialog: Optional[Adw.AlertDialog] = None
        self._shutdown_dialog: Optional[Adw.AlertDialog] = None
        self._cleanup_target: Any = None
        self._cleanup_attempts = 0
        self._shutdown_target: Any = None
        self._shutdown_attempts = 0
        self._on_close_complete: Optional[Callable[[bool], None]] = None
        self._close_deferred = False
        self._exit_cleanup_pending = False
        self._exit_cleanup_timeout_id: Optional[int] = None
        self._exit_app: Optional[Adw.Application] = None
        self._run_ui_suspended = False

    @property
    def running_target(self) -> Any:
        return self._running_target

    def is_running(self) -> bool:
        return self._running_target is not None and self._window.stop_button.get_sensitive()

    def handle_close_request(self, on_complete: Callable[[bool], None]) -> bool:
        """Handle the main window close gesture.

        Returns ``True`` to defer close (dialog shown or shutdown in progress),
        ``False`` when the window may close immediately.
        """
        self._on_close_complete = on_complete
        if self._shutdown_dialog is not None:
            return True
        if self._stop_confirm_dialog is not None:
            dialog = self._stop_confirm_dialog
            self._stop_confirm_dialog = None
            self._run_ui_suspended = False
            target = self._running_target
            if target is not None and hasattr(target, "unpause"):
                target.unpause()
            if self.is_running():
                self._window._start_pulse()
            # Close the dialog itself, not just our reference to it — otherwise
            # its "response"/"closed" handlers stay live and can later fire
            # against state already mutated by the shutdown-confirm flow below.
            dialog.force_close()
        if self.is_running():
            self._close_deferred = True
            self._present_shutdown_confirm()
            return True
        on_complete = self._on_close_complete
        self._on_close_complete = None
        if on_complete is not None:
            on_complete(False)
        self._stop_all_workers(force=True)
        self._begin_exit_cleanup()
        return False

    def handle_start(self, target) -> None:
        """Validate readiness, then hand off to the active run target."""
        reason = target_blocked_reason(target)
        if reason is not None:
            debug("ui", f"handle_start blocked reason={reason!r}")
            self._window.toast(reason)
            return

        callbacks = gtk_job_callbacks(
            on_progress=self._on_progress,
            on_console=self._append_console,
            on_complete=self._on_complete,
            on_stopped=self._on_stopped,
            on_error=self._on_error,
        )
        debug("ui", f"handle_start -> {type(target).__name__}.start()")
        target.start(callbacks)

    def begin_run(self, target) -> None:
        """Shared bookkeeping when any run target starts its worker."""
        from core.error_context import clear_run_error_context, set_run_error_context

        mark_run_start()
        reset_progress_log()
        clear_run_error_context()
        set_run_error_context(**self._snapshot_error_context(target))
        debug("ui", f"begin_run target={type(target).__name__} engines_imported={engines_imported()} warm={warm_status()}")
        self._running_target = target
        self._run_output_dir = self._window.settings.process.export_path or ""
        self._run_label = self._run_label_for(target)
        self._window.log_panel.set_run_label(self._run_label)
        self._run_started_at = time.monotonic()
        self._eta_tracker.reset()
        self._last_progress_ui_at = 0.0
        self._last_progress_phase = None
        self._last_progress_pass = None
        self._last_progress_combine = None
        self._window.console.clear()
        self._window.log_panel.set_progress_fraction(0.0)
        self._window.log_panel.set_progress_text(_starting_progress_text())
        self._window._start_pulse()
        self._set_running(True)
        self._window._reveal_log_panel(True)
        self._window.log_panel.prepare_for_run()
        debug("ui", "begin_run UI ready (log revealed, prepare_for_run done)")

    def fail_to_start(self, message: str, exc: BaseException) -> None:
        """Recover the UI when a run target could not launch its worker."""
        debug("ui", f"fail_to_start error={type(exc).__name__}: {exc}")
        clear_run_start()
        self._window._stop_pulse()
        self._set_running(False)
        self._window.console.append(f"\n{message}\n")
        self._report_error(message, exc)
        self._running_target = None

    def handle_start_action(self) -> None:
        if self._window.start_button.get_sensitive():
            self.handle_start(self._window._run_target)

    def handle_stop_action(self) -> None:
        if self._window.stop_button.get_sensitive():
            self.handle_stop()

    def handle_stop(self) -> None:
        if not self._window.stop_button.get_sensitive():
            return
        if self._stop_confirm_dialog is not None:
            return
        debug("ui", "handle_stop presenting confirm dialog")
        self._present_stop_confirm()

    def _run_label_for(self, target) -> str:
        window = self._window
        if target is window._separation_target:
            return "Separation"
        if target is window._ensemble_page:
            return "Ensemble"
        if target is window._audio_tools_page:
            return "Audio tools"
        return "Processing"

    def _present_stop_confirm(self) -> None:
        heading, body = STOP_PROCESS_CONFIRM
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("stop", "Stop")
        dialog.set_response_appearance("stop", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        target = self._running_target
        self._suspend_run_ui_for_dialog()

        pending: dict[str, Any] = {"run": None}

        def on_closed(_dialog: Adw.AlertDialog) -> None:
            run = pending["run"]
            pending["run"] = None
            if run is not None:
                self._defer_dialog_action(run, label="stop-closed")

        def on_response(_dlg, response: str) -> None:
            self._stop_confirm_dialog = None
            if response == "stop":
                captured = self._running_target or target
                pending["run"] = lambda: self._confirm_stop(captured)
                if captured is not None and hasattr(captured, "stop"):
                    captured.stop()
                self._defer_dialog_action(pending["run"], label="stop")
                pending["run"] = None
            else:
                if target is not None and hasattr(target, "unpause"):
                    resume = lambda: self._resume_after_dialog_cancel(target)
                else:
                    resume = self._resume_run_ui_after_dialog
                pending["run"] = resume
                self._defer_dialog_action(resume, label="stop-cancel")
                pending["run"] = None

        dialog.connect("closed", on_closed)
        dialog.connect("response", on_response)
        self._stop_confirm_dialog = dialog
        dialog.present(self._window)

    def _present_shutdown_confirm(self) -> None:
        heading, body = QUIT_WHILE_PROCESSING_CONFIRM
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("quit", "Stop and Quit")
        dialog.set_response_appearance("quit", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        target = self._running_target
        self._suspend_run_ui_for_dialog()

        pending: dict[str, Any] = {"run": None}

        def on_closed(_dialog: Adw.AlertDialog) -> None:
            run = pending["run"]
            pending["run"] = None
            if run is not None:
                self._defer_dialog_action(run, label="shutdown-closed")

        def on_response(_dlg, response: str) -> None:
            self._shutdown_dialog = None
            if response == "quit":
                captured = self._running_target or target
                pending["run"] = lambda: self._confirm_shutdown_stop(captured)
                if captured is not None and hasattr(captured, "stop"):
                    captured.stop()
                self._defer_dialog_action(pending["run"], label="shutdown")
                pending["run"] = None
            else:
                self._close_deferred = False
                self._on_close_complete = None
                if target is not None and hasattr(target, "unpause"):
                    resume = lambda: self._resume_after_dialog_cancel(target)
                else:
                    resume = self._resume_run_ui_after_dialog
                pending["run"] = resume
                self._defer_dialog_action(resume, label="shutdown-cancel")
                pending["run"] = None

        dialog.connect("closed", on_closed)
        dialog.connect("response", on_response)
        self._shutdown_dialog = dialog
        dialog.present(self._window)

    def _defer_dialog_action(self, callback: Callable[[], None], *, label: str = "") -> None:
        """Run a dialog follow-up on the next main-loop tick (never block on ``closed``)."""

        def run() -> bool:
            started = time.monotonic()
            debug("ui", f"dialog action label={label or 'dialog'}")
            callback()
            work_ms = (time.monotonic() - started) * 1000.0
            if label:
                debug("ui", f"dialog action label={label} work={work_ms:.1f}ms")
            return GLib.SOURCE_REMOVE

        GLib.idle_add(run)

    def _suspend_run_ui_for_dialog(self) -> None:
        """Pause run-driven widget updates while a confirm dialog is on screen."""
        self._run_ui_suspended = True
        self._window._stop_pulse()
        target = self._running_target
        if target is not None and hasattr(target, "pause"):
            target.pause()

    def _resume_run_ui_after_dialog(self) -> None:
        debug("ui", f"resume_run_ui after dialog dismissed running={self.is_running()}")
        self._run_ui_suspended = False
        if self.is_running():
            self._window._start_pulse()

    def _resume_after_dialog_cancel(self, target: Any) -> None:
        if target is not None and hasattr(target, "unpause"):
            target.unpause()
        self._resume_run_ui_after_dialog()

    def _append_console(self, text: str) -> None:
        if self._run_ui_suspended:
            return
        self._window.console.append(text)

    def _confirm_shutdown_stop(self, target: Any) -> None:
        debug("ui", f"shutdown stop confirmed target={type(target).__name__ if target else None}")
        self._run_ui_suspended = False
        self._window._stop_pulse()
        self._set_running(False)
        self._running_target = None
        self._cleanup_target = None
        clear_run_start()
        if target is not None:
            if hasattr(target, "unpause"):
                target.unpause()
            self._window.console.append(f"\n{STOP_PROCESSING}\n")
            target.stop()
        self._schedule_shutdown_poll(target)

    def _schedule_shutdown_poll(self, target: Any) -> None:
        debug("cleanup", f"shutdown poll scheduled target={type(target).__name__ if target else None}")
        self._shutdown_target = target
        self._shutdown_attempts = 0
        GLib.timeout_add(50, self._poll_shutdown)

    def _poll_shutdown(self) -> bool:
        target = self._shutdown_target
        if target is None:
            self._complete_shutdown(deferred=self._close_deferred)
            return False
        self._shutdown_attempts += 1
        alive = self._worker_is_running(target)
        if not alive:
            debug("cleanup", f"shutdown poll attempt={self._shutdown_attempts} worker_alive=False")
            self._shutdown_target = None
            self._complete_shutdown(deferred=self._close_deferred)
            return False
        if self._shutdown_attempts >= 80:
            debug("cleanup", f"shutdown poll attempt={self._shutdown_attempts} timeout force=True")
            self._shutdown_target = None
            self._complete_shutdown(deferred=self._close_deferred)
            return False
        if verbose():
            debug("cleanup", f"shutdown poll attempt={self._shutdown_attempts} worker_alive=True")
        return True

    def _complete_shutdown(self, *, deferred: bool) -> None:
        debug("ui", f"complete_shutdown deferred={deferred}")
        self._cleanup_target = None
        self._shutdown_target = None
        self._window._stop_pulse()
        self._stop_all_workers(force=True)
        on_complete = self._on_close_complete
        self._on_close_complete = None
        self._close_deferred = False
        if on_complete is not None:
            on_complete(deferred)
        self._begin_exit_cleanup()
        if deferred:
            self._window.destroy()

    def _confirm_stop(self, target: Any) -> None:
        if target is None:
            return
        debug("ui", f"stop confirmed target={type(target).__name__}")
        self._run_ui_suspended = False
        if hasattr(target, "unpause"):
            target.unpause()
        self._finish_run_ui(stopped=True, defer_cleanup=True)
        self._window.console.append(f"\n{STOP_PROCESSING}\n")
        target.stop()
        self._schedule_inference_cleanup(target)

    def _schedule_inference_cleanup(self, target: Any) -> None:
        debug("cleanup", f"cleanup poll scheduled target={type(target).__name__}")
        self._cleanup_target = target
        self._cleanup_attempts = 0
        GLib.timeout_add(50, self._poll_inference_cleanup)

    def _worker_is_running(self, target: Any) -> bool:
        window = self._window
        page = getattr(window, "_audio_tools_page", None)
        if page is not None and target is page:
            return page.runner.is_running()
        return window.context.runner.is_running()

    def _poll_inference_cleanup(self) -> bool:
        target = self._cleanup_target
        if target is None:
            return False
        self._cleanup_attempts += 1
        alive = self._worker_is_running(target)
        if not alive:
            debug("cleanup", f"poll attempt={self._cleanup_attempts} worker_alive=False releasing")
            self._cleanup_target = None
            self._schedule_release_inference_memory(force_if_alive=False)
            return False
        if self._cleanup_attempts >= 80:
            debug("cleanup", f"poll attempt={self._cleanup_attempts} timeout force=True")
            self._cleanup_target = None
            self._schedule_release_inference_memory(force_if_alive=True)
            return False
        if verbose():
            debug("cleanup", f"poll attempt={self._cleanup_attempts} worker_alive=True")
        return True

    def _finish_run_ui(self, *, stopped: bool = False, defer_cleanup: bool = False) -> None:
        debug("ui", f"finish_run_ui stopped={stopped} defer_cleanup={defer_cleanup}")
        if stopped and not defer_cleanup:
            self._schedule_release_inference_memory(wait_for_stop=0.5)
        self._window._stop_pulse()
        self._set_running(False)
        self._running_target = None
        self._window.log_panel.clear_progress()
        clear_run_start()

    def _on_stopped(self) -> None:
        from core.error_context import clear_run_error_context

        debug("ui", "on_stopped cooperative worker stop")
        clear_run_error_context()
        self._cleanup_target = None
        self._finish_run_ui(stopped=True)

    def _on_complete(self) -> None:
        from core.error_context import clear_run_error_context

        debug("ui", f"on_complete output_dir={os.path.basename(self._run_output_dir or '') or '(none)'}")
        clear_run_error_context()
        self._window._stop_pulse()
        self._set_running(False)
        self._window.log_panel.set_progress_fraction(1.0)
        self._window.log_panel.set_progress_text(_PROGRESS_DONE)
        self._window.log_panel.mark_run_complete()
        self._running_target = None
        clear_run_start()
        output_dir = self._run_output_dir
        self._show_complete_toast(output_dir)
        self._send_completion_notification(output_dir)
        self._schedule_release_inference_memory(wait_for_stop=0.5)

    def _on_error(self, exc: BaseException) -> None:
        debug("ui", f"on_error error={type(exc).__name__}: {exc}")
        self._window._stop_pulse()
        self._set_running(False)
        self._window.log_panel.set_progress_text("Failed")
        message = f"Process failed: {exc}"
        self._window.console.append(f"\n{message}\n")
        self._report_error(message, exc)
        self._send_failure_notification()
        self._running_target = None
        clear_run_start()
        # Worker already parks on failure; park again here in case UI cleanup
        # races ahead of the worker finally/except path.
        self._schedule_release_inference_memory(park_weights=True)

    def _show_complete_toast(self, output_dir: str) -> None:
        toast = Adw.Toast.new("Process complete.")
        if output_dir and os.path.isdir(output_dir):
            toast.set_button_label(_OPEN_FOLDER_LABEL)
            toast.connect("button-clicked", self._on_open_output_folder, output_dir)
        self._window.toast_overlay.add_toast(toast)

    def _on_open_output_folder(self, _toast: Adw.Toast, output_dir: str) -> None:
        open_folder_in_file_manager(
            self._window,
            output_dir,
            on_error=self._window.toast,
        )

    def _send_completion_notification(self, output_dir: str) -> None:
        title = _NOTIFY_COMPLETE_TITLE.format(label=self._run_label)
        if output_dir:
            body = _NOTIFY_COMPLETE_BODY.format(
                folder=os.path.basename(os.path.normpath(output_dir))
            )
        else:
            body = _NOTIFY_COMPLETE_BODY_PLAIN
        open_folder = output_dir if output_dir and os.path.isdir(output_dir) else None
        send_desktop_notification(
            self._window.get_application(),
            self._window.settings,
            setting_key=NOTIFY_PROCESS_COMPLETE,
            ident="uvr-complete",
            title=title,
            body=body,
            output_dir=open_folder,
        )

    def _send_failure_notification(self) -> None:
        title = _NOTIFY_FAILED_TITLE.format(label=self._run_label)
        send_desktop_notification(
            self._window.get_application(),
            self._window.settings,
            setting_key=NOTIFY_PROCESS_FAILED,
            ident="uvr-failed",
            title=title,
            body=_NOTIFY_FAILED_BODY,
        )

    def _on_progress(
        self,
        fraction: float,
        local_step: Optional[float] = None,
        pass_index: Optional[int] = None,
        pass_total: Optional[int] = None,
        detail: Optional[str] = None,
        combine_index: Optional[int] = None,
        combine_total: Optional[int] = None,
        **_extra,
    ) -> None:
        if self._run_ui_suspended:
            return
        now = time.monotonic()
        self._eta_tracker.update(
            fraction,
            now,
            local_step=local_step,
            pass_index=pass_index,
            pass_total=pass_total,
            detail=detail,
            combine_index=combine_index,
            combine_total=combine_total,
        )
        phase = self._eta_tracker.phase(fraction)
        force_ui = (
            fraction >= 1.0 - _PROGRESS_EPSILON
            or phase != self._last_progress_phase
            or pass_index != self._last_progress_pass
            or combine_index != self._last_progress_combine
        )
        if (
            not force_ui
            and (now - self._last_progress_ui_at) < _PROGRESS_UI_MIN_INTERVAL
        ):
            return
        self._last_progress_ui_at = now
        self._last_progress_phase = phase
        self._last_progress_pass = pass_index
        self._last_progress_combine = combine_index

        elapsed = max(0.0, now - self._run_started_at)
        self._window.log_panel.set_progress_text(
            self._eta_tracker.format_text(fraction, elapsed, now=now)
        )

        if fraction >= 1.0 - _PROGRESS_EPSILON:
            self._window._stop_pulse()
            self._window.log_panel.set_progress_fraction(1.0)
            return
        if fraction <= _PROGRESS_EPSILON and self._eta_tracker.held_display <= 0:
            self._window._start_pulse()
            return

        # Mid-run load/save/combine: keep the last inference fill and show phase
        # text (GTK pulse would wipe the determinate bar). Pulse only before any
        # inference progress exists.
        if self._eta_tracker.is_indeterminate(fraction):
            held = self._eta_tracker.held_display
            if held > _PROGRESS_EPSILON:
                self._window._stop_pulse()
                self._window.log_panel.set_progress_fraction(held)
            else:
                self._window._start_pulse()
            return

        display = self._eta_tracker.inference_display_fraction(fraction)
        if display is None:
            held = self._eta_tracker.held_display
            if held > _PROGRESS_EPSILON:
                self._window._stop_pulse()
                self._window.log_panel.set_progress_fraction(held)
            else:
                self._window._start_pulse()
            return
        self._window._stop_pulse()
        self._window.log_panel.set_progress_fraction(display)

    def _progress_text(self, fraction: float, local_step: Optional[float] = None, **kwargs) -> str:
        now = time.monotonic()
        elapsed = max(0.0, now - self._run_started_at)
        self._eta_tracker.update(fraction, now, local_step=local_step, **kwargs)
        return self._eta_tracker.format_text(fraction, elapsed, now=now)

    def _report_error(self, message: str, exc: BaseException) -> None:
        from .errorlog import log_error, present_error_dialog

        window = self._window
        target = self._running_target or window._run_target
        key = (
            target.error_key if target is not None else window._active_view().method_key
        )
        formatted = log_error(key, exc)
        label = self._run_label_for(target) if target is not None else "Process"
        present_error_dialog(
            window,
            heading=f"{label} failed",
            exception=exc,
            formatted_log=formatted,
            on_copied=lambda: window.toast("Report copied to clipboard"),
        )

    def _snapshot_error_context(self, target) -> dict:
        from core.error_context import (
            build_audio_tools_context,
            build_ensemble_context,
            build_separation_context,
        )

        window = self._window
        settings = window.settings
        repo = window.context.repo
        tab = window.content_stack.get_visible_child_name()

        if tab == "ensemble":
            page = getattr(window, "_ensemble_page", None)
            paths = list(page.input_row.paths) if page is not None else []
            return build_ensemble_context(settings, paths)
        if tab == "audio_tools":
            from bundled.constants import (
                APOLLO_RESTORE,
                CHANGE_PITCH,
                MANUAL_ENSEMBLE,
                TIME_STRETCH,
            )
            from core.audio_tools import DUAL_INPUT_TOOLS

            page = getattr(window, "_audio_tools_page", None)
            tool = page._current_tool() if page is not None else "Audio Tools"
            paths: list[str] = []
            if page is not None:
                if tool in DUAL_INPUT_TOOLS:
                    paths = [os.path.basename(left) for left, _right in page._dual_pairs]
                else:
                    paths = list(page.inputs_row.paths)
            return build_audio_tools_context(settings, tool, paths)

        method_key = window._active_view().method_key
        return build_separation_context(
            settings,
            repo,
            list(window.input_row.paths),
            method_key,
        )

    def _set_running(self, running: bool) -> None:
        # Update Stop first: ``is_running()`` is ``_running_target and stop
        # sensitive``. On unlock, ``_sync_model_options_action`` must see
        # ``is_running() is False`` or Model options stays disabled.
        self._window.stop_button.set_sensitive(running)
        self._set_options_sensitive(not running)
        self._set_edit_actions_sensitive(not running)
        if running:
            self._window.start_button.set_sensitive(False)
        else:
            self.refresh_start_readiness()

    def _set_options_sensitive(self, sensitive: bool) -> None:
        """Lock editable option surfaces while leaving tabs and logs usable."""
        for page in getattr(self._window, "_options_pages", ()):
            page.set_sensitive(sensitive)

    def _set_edit_actions_sensitive(self, sensitive: bool) -> None:
        for name in ("settings", "view_inputs", "model_options", "download"):
            action = self._window.lookup_action(name)
            if action is not None:
                action.set_enabled(sensitive)
        if sensitive:
            self._window._sync_model_options_action()
            deferred = getattr(self._window, "_deferred_model_refresh", None)
            if deferred is not None:
                self._window._apply_model_refresh(source=deferred)

    def refresh_start_readiness(self) -> Optional[str]:
        """Synchronize Start sensitivity, tooltip and accessibility description."""
        if self._running_target is not None and self._window.stop_button.get_sensitive():
            return None
        target = getattr(self._window, "_run_target", None)
        reason = target_blocked_reason(target)
        button = self._window.start_button
        button.set_sensitive(reason is None)
        description = reason or "Start processing"
        button.set_tooltip_text(description)
        button.update_property(
            [Gtk.AccessibleProperty.DESCRIPTION],
            [description],
        )
        return reason

    def _stop_all_workers(self, *, force: bool = False) -> None:
        debug("ui", f"stop_all_workers force={force}")
        self._window.context.stop_all_workers(force=force)
        page = getattr(self._window, "_audio_tools_page", None)
        if page is not None:
            runner = getattr(page, "_runner", None)
            if runner is not None:
                runner.stop(force=force)

    def _begin_exit_cleanup(self) -> None:
        if self._exit_cleanup_pending:
            return
        self._exit_cleanup_pending = True
        app = self._window.get_application()
        self._exit_app = app
        if app is not None:
            app.hold()
        else:
            debug("ui", "exit cleanup begin: window has no application ref")
        if self._exit_cleanup_timeout_id is not None:
            GLib.source_remove(self._exit_cleanup_timeout_id)
        self._exit_cleanup_timeout_id = GLib.timeout_add(
            _EXIT_CLEANUP_TIMEOUT_MS,
            self._on_exit_cleanup_timeout,
        )
        self._schedule_release_inference_memory(
            force_if_alive=True,
            clear_weight_cache=True,
            on_done=self._finish_exit_cleanup,
        )

    def _on_exit_cleanup_timeout(self) -> bool:
        self._exit_cleanup_timeout_id = None
        if not self._exit_cleanup_pending:
            return False
        debug("cleanup", "exit cleanup timed out; forcing worker stop and quit")
        self._stop_all_workers(force=True)
        self._finish_exit_cleanup()
        return False

    def _finish_exit_cleanup(self) -> None:
        if not self._exit_cleanup_pending:
            return
        self._exit_cleanup_pending = False
        if self._exit_cleanup_timeout_id is not None:
            GLib.source_remove(self._exit_cleanup_timeout_id)
            self._exit_cleanup_timeout_id = None
        app = self._exit_app or self._window.get_application()
        self._exit_app = None
        if app is not None:
            debug("ui", "exit cleanup finish: release and quit")
            app.release()
            app.quit()
        else:
            debug("ui", "exit cleanup finish: no application ref; forcing process exit")
            from .shutdown import finalize_process_exit

            finalize_process_exit(0)

    def _schedule_release_inference_memory(
        self,
        *,
        wait_for_stop: float = 0.0,
        force_if_alive: bool = False,
        clear_weight_cache: bool = False,
        park_weights: bool = False,
        on_done: Optional[Callable[[], None]] = None,
    ) -> None:
        debug(
            "cleanup",
            "schedule_release_inference_memory "
            f"wait_for_stop={wait_for_stop} force_if_alive={force_if_alive} "
            f"clear_weight_cache={clear_weight_cache} park_weights={park_weights}",
        )

        def worker() -> None:
            try:
                self._release_inference_memory(
                    wait_for_stop=wait_for_stop,
                    force_if_alive=force_if_alive,
                    clear_weight_cache=clear_weight_cache,
                    park_weights=park_weights,
                )
            finally:
                if on_done is not None:
                    idle_on_main(on_done)

        threading.Thread(
            target=worker,
            name="uvr-inference-cleanup",
            daemon=True,
        ).start()

    def _release_inference_memory(
        self,
        *,
        wait_for_stop: float = 0.0,
        force_if_alive: bool = False,
        clear_weight_cache: bool = False,
        park_weights: bool = False,
    ) -> None:
        debug(
            "cleanup",
            f"release_inference_memory wait_for_stop={wait_for_stop} "
            f"force_if_alive={force_if_alive} clear_weight_cache={clear_weight_cache} "
            f"park_weights={park_weights}",
        )
        window = self._window
        window.context.runner.release_inference_memory(
            wait_for_stop=wait_for_stop,
            force_if_alive=force_if_alive,
            clear_weight_cache=clear_weight_cache,
            park_weights=park_weights,
        )
        page = getattr(window, "_audio_tools_page", None)
        if page is not None:
            page.runner.release_inference_memory(
                wait_for_stop=wait_for_stop,
                force_if_alive=force_if_alive,
                clear_weight_cache=clear_weight_cache,
                park_weights=park_weights,
            )


def _format_mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"
