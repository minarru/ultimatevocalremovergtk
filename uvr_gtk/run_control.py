"""Shared Start/Stop dispatch and run lifecycle for the main window.

:class:`RunController` owns progress, console output, notifications and the
pinned running target so :class:`uvr_gtk.window.MainWindow` can stay focused on
layout and settings. Ensemble and Audio Tools pages call
:meth:`RunController.begin_run` / :meth:`RunController.fail_to_start` through thin
delegates on the window.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any, Optional

from gi.repository import Adw, Gio, GLib, Gtk

from data.constants import STOP_PROCESS_CONFIRM, STOP_PROCESSING

from uvr_core.debug_log import (
    clear_run_start,
    debug,
    mark_run_start,
    next_seq,
    preview_text,
    set_correlation_seq,
    verbose,
)
from uvr_core.separate_import import engines_imported, warm_status

from . import APP_ID
from .dispatch import gtk_job_callbacks, reset_progress_log

if TYPE_CHECKING:
    from .window import MainWindow

_OPEN_FOLDER_LABEL = "Open Folder"
_OPEN_FOLDER_ERROR = "Couldn't open the output folder: {message}"
_NOTIFY_COMPLETE_TITLE = "{label} complete"
_NOTIFY_COMPLETE_BODY = "Saved to {folder}"
_NOTIFY_COMPLETE_BODY_PLAIN = "Processing finished"
_NOTIFY_FAILED_TITLE = "{label} failed"
_NOTIFY_FAILED_BODY = "Open the app to see the error log"
_NOTIFY_ICONS = {
    "uvr-complete": "emblem-ok-symbolic",
    "uvr-failed": "dialog-error-symbolic",
}
_PROGRESS_STARTING = "Starting…"
_PROGRESS_DONE = "Done"
_PROGRESS_EPSILON = 0.001


class RunController:
    """Run lifecycle shared by Separation, Ensemble and Audio Tools."""

    def __init__(self, window: MainWindow):
        self._window = window
        self._running_target: Any = None
        self._run_output_dir = ""
        self._run_label = "Processing"
        self._run_started_at = 0.0
        self._stop_confirm_dialog: Optional[Adw.AlertDialog] = None
        self._cleanup_target: Any = None
        self._cleanup_attempts = 0

    @property
    def running_target(self) -> Any:
        return self._running_target

    def handle_start(self, target) -> None:
        """Validate readiness, then hand off to the active run target."""
        try:
            reason = target.start_blocked_reason()
        except Exception:  # noqa: BLE001 - readiness check must never break the UI
            reason = None
        if reason is not None:
            debug("ui", f"handle_start blocked reason={reason!r}")
            self._window._toast(reason)
            return

        callbacks = gtk_job_callbacks(
            on_progress=self._on_progress,
            on_console=self._window.console.append,
            on_complete=self._on_complete,
            on_stopped=self._on_stopped,
            on_error=self._on_error,
        )
        debug("ui", f"handle_start -> {type(target).__name__}.start()")
        target.start(callbacks)

    def begin_run(self, target) -> None:
        """Shared bookkeeping when any run target starts its worker."""
        mark_run_start()
        reset_progress_log()
        debug("ui", f"begin_run target={type(target).__name__} engines_imported={engines_imported()} warm={warm_status()}")
        self._running_target = target
        self._run_output_dir = self._window.settings.get("export_path") or ""
        self._run_label = self._run_label_for(target)
        self._run_started_at = time.monotonic()
        self._window.console.clear()
        self._window.log_panel.set_progress_fraction(0.0)
        self._window.log_panel.set_progress_text(_PROGRESS_STARTING)
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
        if target is not None and hasattr(target, "pause"):
            target.pause()

        def on_response(_dlg, response: str) -> None:
            self._stop_confirm_dialog = None
            if response == "stop":
                self._confirm_stop()
            elif target is not None and hasattr(target, "unpause"):
                target.unpause()

        self._stop_confirm_dialog = dialog
        dialog.connect("response", on_response)
        dialog.present(self._window)

    def _confirm_stop(self) -> None:
        target = self._running_target
        if target is None:
            return
        debug("ui", f"stop confirmed target={type(target).__name__}")
        self._window.console.append(f"\n{STOP_PROCESSING}\n")
        target.stop()
        self._finish_run_ui(stopped=True, defer_cleanup=True)
        self._schedule_inference_cleanup(target)

    def _schedule_inference_cleanup(self, target: Any) -> None:
        debug("cleanup", f"cleanup poll scheduled target={type(target).__name__}")
        self._cleanup_target = target
        self._cleanup_attempts = 0
        GLib.timeout_add(50, self._poll_inference_cleanup)

    def _worker_is_running(self, target: Any) -> bool:
        window = self._window
        page = getattr(window, "_audio_tools_page", None)
        if target is page:
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
            self._release_inference_memory(force_if_alive=False)
            self._cleanup_target = None
            return False
        if self._cleanup_attempts >= 80:
            debug("cleanup", f"poll attempt={self._cleanup_attempts} timeout force=True")
            self._release_inference_memory(force_if_alive=True)
            self._cleanup_target = None
            return False
        if verbose():
            debug("cleanup", f"poll attempt={self._cleanup_attempts} worker_alive=True")
        return True

    def _finish_run_ui(self, *, stopped: bool = False, defer_cleanup: bool = False) -> None:
        debug("ui", f"finish_run_ui stopped={stopped} defer_cleanup={defer_cleanup}")
        if stopped and not defer_cleanup:
            self._release_inference_memory(wait_for_stop=0.5)
        self._window._stop_pulse()
        self._set_running(False)
        self._running_target = None
        self._window.log_panel.set_progress_fraction(0.0)
        self._window.log_panel.set_progress_text("Stopped" if stopped else "")
        clear_run_start()

    def _on_stopped(self) -> None:
        debug("ui", "on_stopped cooperative worker stop")
        self._cleanup_target = None
        self._finish_run_ui(stopped=True)

    def _on_complete(self) -> None:
        debug("ui", f"on_complete output_dir={os.path.basename(self._run_output_dir or '') or '(none)'}")
        self._release_inference_memory(wait_for_stop=0.5)
        self._window._stop_pulse()
        self._set_running(False)
        self._window.log_panel.set_progress_fraction(1.0)
        self._window.log_panel.set_progress_text(_PROGRESS_DONE)
        self._running_target = None
        clear_run_start()
        output_dir = self._run_output_dir
        self._show_complete_toast(output_dir)
        self._send_completion_notification(output_dir)

    def _on_error(self, exc: BaseException) -> None:
        debug("ui", f"on_error error={type(exc).__name__}: {exc}")
        self._release_inference_memory()
        self._window._stop_pulse()
        self._set_running(False)
        self._window.log_panel.set_progress_text("")
        message = f"Process failed: {exc}"
        self._window.console.append(f"\n{message}\n")
        self._report_error(message, exc)
        self._send_failure_notification()
        self._running_target = None
        clear_run_start()

    def _show_complete_toast(self, output_dir: str) -> None:
        toast = Adw.Toast.new("Process complete.")
        if output_dir and os.path.isdir(output_dir):
            toast.set_button_label(_OPEN_FOLDER_LABEL)
            toast.connect("button-clicked", self._on_open_output_folder, output_dir)
        self._window.toast_overlay.add_toast(toast)

    def _on_open_output_folder(self, _toast: Adw.Toast, output_dir: str) -> None:
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(output_dir))
        launcher.launch(self._window, None, self._on_output_folder_launched)

    def _on_output_folder_launched(self, launcher: Gtk.FileLauncher, result) -> None:
        try:
            launcher.launch_finish(result)
        except GLib.Error as exc:
            self._window._toast(_OPEN_FOLDER_ERROR.format(message=exc.message))

    def _send_completion_notification(self, output_dir: str) -> None:
        title = _NOTIFY_COMPLETE_TITLE.format(label=self._run_label)
        if output_dir:
            body = _NOTIFY_COMPLETE_BODY.format(
                folder=os.path.basename(os.path.normpath(output_dir))
            )
        else:
            body = _NOTIFY_COMPLETE_BODY_PLAIN
        self._send_notification("uvr-complete", title, body)

    def _send_failure_notification(self) -> None:
        title = _NOTIFY_FAILED_TITLE.format(label=self._run_label)
        self._send_notification("uvr-failed", title, _NOTIFY_FAILED_BODY)

    def _send_notification(self, ident: str, title: str, body: str) -> None:
        try:
            app = self._window.get_application()
            if app is None:
                return
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            icon_name = _NOTIFY_ICONS.get(ident, APP_ID)
            try:
                notification.set_icon(Gio.ThemedIcon.new(icon_name))
            except Exception:  # noqa: BLE001 - icon is best-effort
                pass
            app.send_notification(ident, notification)
        except Exception:  # noqa: BLE001 - notifications must never break a run
            pass

    def _on_progress(self, fraction: float) -> None:
        if fraction > _PROGRESS_EPSILON:
            self._window._stop_pulse()
            self._window.log_panel.set_progress_fraction(fraction)
            self._window.log_panel.set_progress_text(self._progress_text(fraction))

    def _progress_text(self, fraction: float) -> str:
        percent = int(round(fraction * 100))
        elapsed = max(0.0, time.monotonic() - self._run_started_at)
        parts = [f"{percent}%", f"{_format_mmss(elapsed)} elapsed"]
        if fraction > 0.01 and fraction < 1.0:
            remaining = elapsed * (1.0 - fraction) / fraction
            parts.append(f"~{_format_mmss(remaining)} left")
        return " · ".join(parts)

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
            on_copied=lambda: window._toast("Report copied to clipboard"),
        )

    def _set_running(self, running: bool) -> None:
        self._window.start_button.set_sensitive(not running)
        self._window.stop_button.set_sensitive(running)

    def _release_inference_memory(
        self,
        *,
        wait_for_stop: float = 0.0,
        force_if_alive: bool = False,
    ) -> None:
        debug(
            "cleanup",
            f"release_inference_memory wait_for_stop={wait_for_stop} force_if_alive={force_if_alive}",
        )
        window = self._window
        window.context.runner.release_inference_memory(
            wait_for_stop=wait_for_stop,
            force_if_alive=force_if_alive,
        )
        page = getattr(window, "_audio_tools_page", None)
        if page is not None:
            page.runner.release_inference_memory(
                wait_for_stop=wait_for_stop,
                force_if_alive=force_if_alive,
            )


def _format_mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"
