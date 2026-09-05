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
import typing
from typing import TYPE_CHECKING, Any, Callable, Optional

from gi.repository import Adw, GLib

from bundled.constants import (
    QUIT_WHILE_PROCESSING_CONFIRM,
    STOP_PROCESS_CONFIRM,
    STOP_PROCESSING,
)
from core.debug_log import (
    clear_run_start,
    debug,
    log_event,
    mark_run_start,
    new_operation_id,
    operation,
    set_operation_id,
)
from core.separate_import import engines_imported, warm_status

from .dispatch import gtk_job_callbacks, idle_on_main, reset_progress_log
from .files import open_folder_in_file_manager
from .notifications import (
    NOTIFY_PROCESS_COMPLETE,
    NOTIFY_PROCESS_FAILED,
    send_desktop_notification,
)
from .protocols import RunHost, RunReadiness, RunTarget
from .run_error_context import RunErrorContext
from .run_lifecycle import RunShutdownCoordinator
from .run_progress import RunProgressPresenter

if TYPE_CHECKING:
    from core.job_callbacks import JobCallbacks
    from core.settings import Settings

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


def target_blocked_reason(target: RunReadiness | None) -> Optional[str]:
    """Return a target readiness reason without allowing UI validation to fail."""
    if target is None:
        return "Choose a processing mode"
    try:
        return target.start_blocked_reason()
    except Exception:  # readiness must never break the UI
        return None


class RunController:
    """Run lifecycle shared by Separation, Ensemble and Audio Tools."""

    def __init__(self, host: RunHost):
        self._host = host
        self._running_target: RunTarget | None = None
        self._run_output_dir = ""
        self._run_label = "Processing"
        self._run_started_at = 0.0
        self._operation_id: Optional[str] = None
        self._operation_started_at = 0.0
        self.progress = RunProgressPresenter()
        self._stop_confirm_dialog: Optional[Adw.AlertDialog] = None
        self._shutdown_dialog: Optional[Adw.AlertDialog] = None
        self._oom_dialog: Optional[Adw.AlertDialog] = None
        self._on_close_complete: Optional[Callable[[bool], None]] = None
        self._close_deferred = False
        self.shutdown = RunShutdownCoordinator(
            host,
            GLib,
            self._schedule_release_inference_memory,
            lambda: self._complete_shutdown(deferred=self._close_deferred),
        )
        self._run_ui_suspended = False
        self._preflight_in_progress = False
        self._plan_dialog: Optional[Adw.AlertDialog] = None
        self._preflight_start_label: Optional[str] = None

    @property
    def running_target(self) -> RunTarget | None:
        return self._running_target

    def is_running(self) -> bool:
        return self._running_target is not None and self._host.stop_enabled()

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
            if target is not None:
                target.unpause()
            if self.is_running():
                self._host.set_pulse(True)
            # Close the dialog itself, not just our reference to it — otherwise
            # its "response"/"closed" handlers stay live and can later fire
            # against state already mutated by the shutdown-confirm flow below.
            dialog.force_close()
        if self.is_running() or self._active_download_count():
            self._close_deferred = True
            self._present_shutdown_confirm()
            return True
        on_complete = self._on_close_complete
        self._on_close_complete = None
        if on_complete is not None:
            on_complete(False)
        self._stop_all_workers(force=True)
        self.shutdown.begin_exit_cleanup()
        return False

    def handle_start(self, target: RunTarget | None) -> None:
        """Validate readiness, then hand off to the active run target."""
        reason = target_blocked_reason(target)
        if reason is not None:
            debug("ui", f"handle_start blocked reason={reason!r}")
            self._host.toast(reason)
            return

        assert target is not None  # None is rejected by the readiness reason above.
        if self._preflight_in_progress or self._plan_dialog is not None:
            return
        self._ensure_operation()
        self._begin_preflight(target)

    def _callbacks(self) -> JobCallbacks:
        return gtk_job_callbacks(
            on_progress=self._on_progress,
            on_console=self._append_console,
            on_complete=self._on_complete,
            on_stopped=self._on_stopped,
            on_error=self._on_error,
            on_oom_choice=self._on_oom_choice,
        )

    def _start_target(self, target: RunTarget, plan: typing.Any=None) -> None:
        from core.audio_plan import ResolvedAudioJob
        from core.job_plan import ResolvedJob

        operation_id = self._ensure_operation()
        if plan is not None:
            import copy
            plan_settings = copy.deepcopy(plan.settings)
            self._host.bind_run_settings(plan_settings)
            self._apply_page_runner_settings(target, plan_settings)
        else:
            self._host.bind_run_settings(self._host.settings)
        callbacks = self._callbacks()
        debug("ui", f"handle_start -> {type(target).__name__}.start()")
        try:
            if isinstance(plan, (ResolvedJob, ResolvedAudioJob)):
                target.start(callbacks, plan=plan)
            else:
                target.start(callbacks)
        except Exception as exc:  # surface launch failures in the UI
            self.fail_to_start(
                f"Unable to start {type(target).__name__}: {exc}",
                exc,
            )
            return
        if (
            getattr(self, "_operation_id", None) == operation_id
            and getattr(self, "_running_target", None) is None
        ):
            self._finish_operation(
                "run_cancelled",
                reason="target_not_launched",
            )

    def _apply_page_runner_settings(self, target: RunTarget, settings: Settings) -> None:
        target.bind_run_settings(settings)

    def _restore_runner_settings(self) -> None:
        self._host.restore_runner_settings()

    def _set_preflight_busy(self, busy: bool) -> None:
        self._preflight_in_progress = busy
        if busy:
            self._preflight_start_label = self._host.start_label()
            self._host.set_start_label("Preparing…")
            self._host.enable_start(False)
        else:
            self._host.set_start_label(self._preflight_start_label or "Start")
            self._preflight_start_label = None
            self._host.refresh_readiness()

    def _begin_preflight(self, target: RunTarget) -> None:
        from core.job_plan import settings_fingerprint

        try:
            spec = target.build_job_spec()
        except Exception as exc:  # presented through normal UI
            self._host.toast(f"Could not prepare processing plan: {exc}")
            self._finish_operation(
                "run_preflight_failed",
                level="error",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return
        operation_id = self._ensure_operation()
        focus = str(getattr(spec.settings.process, "stem_focus", "") or "")
        debug(
            "ui",
            f"preflight stem_focus={focus!r} method={getattr(spec.settings.process.method, 'value', spec.settings.process.method)!r}",
        )
        fingerprint = settings_fingerprint(spec.settings)
        self._set_preflight_busy(True)

        def worker() -> None:
            from core.audio_plan import AudioJobResolver, AudioJobSpec
            from core.job_plan import JobResolver, ValidationLevel

            with operation(operation_id):
                try:
                    if isinstance(spec, AudioJobSpec):
                        plan = AudioJobResolver(self._host.repo).resolve(
                            spec, ValidationLevel.RUNTIME
                        )
                    else:
                        plan = JobResolver(self._host.repo).resolve(
                            spec, ValidationLevel.RUNTIME
                        )
                    error: BaseException | None = None
                except Exception as exc:  # marshalled to GTK
                    plan, error = None, exc
            idle_on_main(
                self._finish_preflight, target, fingerprint, plan, error
            )

        threading.Thread(
            target=worker, name="uvr-job-preflight", daemon=True
        ).start()

    def _finish_preflight(
        self, target: RunTarget, fingerprint: str, plan: typing.Any,
        error: BaseException | None,
    ) -> None:
        self._set_preflight_busy(False)
        if error is not None:
            self._host.toast(f"Could not prepare processing plan: {error}")
            self._finish_operation(
                "run_preflight_failed",
                level="error",
                error_type=type(error).__name__,
                error=str(error),
            )
            return
        errors = [item.message for item in plan.diagnostics if item.severity == "error"]
        if errors:
            self._host.toast(errors[0])
            self._finish_operation(
                "run_preflight_rejected",
                reason=errors[0],
            )
            return
        from core.audio_plan import ResolvedAudioJob

        if isinstance(plan, ResolvedAudioJob):
            self._accept_plan(target, fingerprint, plan)
            return
        if not self._host.settings.ui.confirm_processing_plan:
            self._accept_plan(target, fingerprint, plan)
            return
        self._present_plan_confirmation(target, fingerprint, plan)

    def _present_plan_confirmation(
        self, target: RunTarget, fingerprint: str, plan: typing.Any
    ) -> None:
        from core.job_plan import format_effective_plan

        dialog = Adw.AlertDialog(
            heading="Review processing plan",
            body=format_effective_plan(plan),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("start", "Start Processing")
        dialog.set_response_appearance("start", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def response(_dialog: typing.Any, choice: str) -> None:
            self._plan_dialog = None
            if choice == "start":
                self._accept_plan(target, fingerprint, plan)
            else:
                self._host.refresh_readiness()
                self._finish_operation(
                    "run_cancelled",
                    reason="plan_confirmation",
                )

        dialog.connect("response", response)
        self._plan_dialog = dialog
        dialog.present(self._host.dialog_parent)

    def _accept_plan(
        self, target: RunTarget, fingerprint: str, plan: typing.Any
    ) -> None:
        from core.job_plan import settings_fingerprint

        try:
            current = target.build_job_spec()
        except Exception as exc:
            self._host.toast(f"Could not recheck processing plan: {exc}")
            self._finish_operation(
                "run_preflight_failed",
                level="error",
                stage="acceptance",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return
        if settings_fingerprint(current.settings) != fingerprint:
            self._host.toast("Processing settings or models changed; reviewing the updated plan")
            self._begin_preflight(target)
            return
        if not _resolved_job_matches_spec(plan, current):
            self._host.toast(
                "Input files or output folder changed; reviewing the updated plan"
            )
            self._begin_preflight(target)
            return
        self._set_preflight_busy(True)
        operation_id = self._ensure_operation()

        def worker() -> None:
            from core.audio_plan import AudioJobResolver, ResolvedAudioJob
            from core.job_plan import JobResolver

            with operation(operation_id):
                try:
                    is_current = (
                        AudioJobResolver(self._host.repo).is_current(plan)
                        if isinstance(plan, ResolvedAudioJob)
                        else JobResolver(self._host.repo).is_current(plan)
                    )
                    error: BaseException | None = None
                except Exception as exc:  # marshalled to GTK
                    is_current, error = False, exc
            idle_on_main(
                self._finish_plan_recheck,
                target, fingerprint, plan, is_current, error,
            )

        threading.Thread(
            target=worker, name="uvr-plan-recheck", daemon=True
        ).start()

    def _finish_plan_recheck(
        self, target: RunTarget, fingerprint: str, plan: typing.Any,
        is_current: bool, error: BaseException | None,
    ) -> None:
        from core.job_plan import settings_fingerprint

        self._set_preflight_busy(False)
        if error is not None:
            self._host.toast(f"Could not recheck processing plan: {error}")
            self._finish_operation(
                "run_preflight_failed",
                level="error",
                stage="recheck",
                error_type=type(error).__name__,
                error=str(error),
            )
            return
        try:
            current = target.build_job_spec()
            settings_unchanged = (
                settings_fingerprint(current.settings) == fingerprint
            )
        except Exception as exc:
            self._host.toast(f"Could not recheck processing plan: {exc}")
            self._finish_operation(
                "run_preflight_failed",
                level="error",
                stage="final_recheck",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return
        if not is_current or not settings_unchanged:
            self._host.toast(
                "Processing settings or models changed; reviewing the updated plan"
            )
            self._begin_preflight(target)
            return
        if not _resolved_job_matches_spec(plan, current):
            self._host.toast(
                "Input files or output folder changed; reviewing the updated plan"
            )
            self._begin_preflight(target)
            return
        self._start_target(target, plan)

    def begin_run(self, target: RunTarget) -> None:
        """Shared bookkeeping when any run target starts its worker."""
        from core.error_context import clear_run_error_context, set_run_error_context

        self._ensure_operation()
        mark_run_start()
        reset_progress_log()
        clear_run_error_context()
        set_run_error_context(**self._snapshot_error_context(target).fields())
        log_event(
            "ui",
            "run_started",
            target=type(target).__name__,
            engines_imported=engines_imported(),
            warm_status=warm_status(),
        )
        self._running_target = target
        self._run_output_dir = self._host.run_output_dir()
        self._run_label = self._run_label_for(target)
        self._host.set_run_label(self._run_label)
        self._run_started_at = time.monotonic()
        self.progress.reset(self._run_started_at)
        self._host.clear_console()
        self._host.set_progress_fraction(0.0)
        self._host.set_progress_text(_starting_progress_text())
        self._host.set_pulse(True)
        self._set_running(True)
        self._host.reveal_log()
        self._host.prepare_log()
        debug("ui", "begin_run UI ready (log revealed, prepare_for_run done)")

    def _ensure_operation(self) -> str:
        operation_id = getattr(self, "_operation_id", None)
        if operation_id is None:
            operation_id = new_operation_id("ui-run")
            self._operation_id = operation_id
            self._operation_started_at = time.monotonic()
        set_operation_id(operation_id)
        return operation_id

    def fail_to_start(self, message: str, exc: BaseException) -> None:
        """Recover the UI when a run target could not launch its worker."""
        self._finish_operation(
            "run_start_failed",
            level="error",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        clear_run_start()
        self._host.set_pulse(False)
        self._set_running(False)
        self._host.append_console(f"\n{message}\n")
        self._report_error(message, exc)
        self._running_target = None
        self._restore_runner_settings()

    def _finish_operation(
        self,
        event: str,
        *,
        level: str = "debug",
        **fields: object,
    ) -> None:
        operation_id = getattr(self, "_operation_id", None)
        if operation_id is None:
            return
        started_at = getattr(self, "_operation_started_at", 0.0) or getattr(
            self, "_run_started_at", 0.0
        )
        elapsed = max(0.0, time.monotonic() - started_at)
        log_event(
            "ui",
            event,
            level=level,
            operation_id=operation_id,
            elapsed_seconds=round(elapsed, 3),
            **fields,
        )
        self._operation_id = None
        self._operation_started_at = 0.0
        set_operation_id(None)

    def handle_start_action(self) -> None:
        if self._host.start_enabled():
            self.handle_start(self._host.target)

    def handle_stop_action(self) -> None:
        if self._host.stop_enabled():
            self.handle_stop()

    def handle_stop(self) -> None:
        if not self._host.stop_enabled():
            return
        if self._stop_confirm_dialog is not None:
            return
        debug("ui", "handle_stop presenting confirm dialog")
        self._present_stop_confirm()

    def _run_label_for(self, target: RunTarget) -> str:
        return target.run_label

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

        def on_response(_dlg: typing.Any, response: str) -> None:
            self._stop_confirm_dialog = None
            if response == "stop":
                captured = self._running_target or target
                pending["run"] = lambda: self._confirm_stop(captured)
                if captured is not None:
                    captured.stop()
                self._defer_dialog_action(pending["run"], label="stop")
                pending["run"] = None
            else:
                if target is not None:
                    def resume() -> None:
                        return self._resume_after_dialog_cancel(target)
                else:
                    resume = self._resume_run_ui_after_dialog
                pending["run"] = resume
                self._defer_dialog_action(resume, label="stop-cancel")
                pending["run"] = None

        dialog.connect("closed", on_closed)
        dialog.connect("response", on_response)
        self._stop_confirm_dialog = dialog
        dialog.present(self._host.dialog_parent)

    def _present_shutdown_confirm(self) -> None:
        download_count = self._active_download_count()
        if self.is_running() and download_count:
            heading = "Stop processing and downloads?"
            body = (
                "Processing and model downloads are still running. "
                "Stopping now may leave the current output incomplete; partial "
                "model downloads will be removed."
            )
        elif download_count:
            heading = "Cancel model downloads and quit?"
            noun = "download is" if download_count == 1 else "downloads are"
            body = (
                f"{download_count} model {noun} still active. Partial downloads "
                "will be removed before the application quits."
            )
        else:
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

        def on_response(_dlg: typing.Any, response: str) -> None:
            self._shutdown_dialog = None
            if response == "quit":
                captured = self._running_target or target
                pending["run"] = lambda: self._confirm_shutdown_stop(captured)
                if captured is not None:
                    captured.stop()
                self._host.stop_context_workers(force=False)
                self._defer_dialog_action(pending["run"], label="shutdown")
                pending["run"] = None
            else:
                self._close_deferred = False
                self._on_close_complete = None
                if target is not None:
                    def resume() -> None:
                        return self._resume_after_dialog_cancel(target)
                else:
                    resume = self._resume_run_ui_after_dialog
                pending["run"] = resume
                self._defer_dialog_action(resume, label="shutdown-cancel")
                pending["run"] = None

        dialog.connect("closed", on_closed)
        dialog.connect("response", on_response)
        self._shutdown_dialog = dialog
        dialog.present(self._host.dialog_parent)

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
        self._host.set_pulse(False)
        target = self._running_target
        if target is not None:
            target.pause()

    def _resume_run_ui_after_dialog(self) -> None:
        debug("ui", f"resume_run_ui after dialog dismissed running={self.is_running()}")
        self._run_ui_suspended = False
        if self.is_running():
            self._host.set_pulse(True)

    def _resume_after_dialog_cancel(self, target: RunTarget | None) -> None:
        if target is not None:
            target.unpause()
        self._resume_run_ui_after_dialog()

    def _append_console(self, text: str) -> None:
        if self._run_ui_suspended:
            return
        self._host.append_console(text)

    def _confirm_shutdown_stop(self, target: RunTarget | None) -> None:
        debug("ui", f"shutdown stop confirmed target={type(target).__name__ if target else None}")
        self._run_ui_suspended = False
        self._host.set_pulse(False)
        self._set_running(False)
        self._running_target = None
        self.shutdown.cleanup_target = None
        clear_run_start()
        self._finish_operation("run_stopped", reason="shutdown")
        if target is not None:
            target.unpause()
            self._host.append_console(f"\n{STOP_PROCESSING}\n")
            target.stop()
        self.shutdown.schedule_shutdown_poll(target)

    def _complete_shutdown(self, *, deferred: bool) -> None:
        debug("ui", f"complete_shutdown deferred={deferred}")
        self.shutdown.cleanup_target = None
        self.shutdown.shutdown_target = None
        self._host.set_pulse(False)
        self._stop_all_workers(force=True)
        on_complete = self._on_close_complete
        self._on_close_complete = None
        self._close_deferred = False
        if on_complete is not None:
            on_complete(deferred)
        self.shutdown.begin_exit_cleanup()
        if deferred:
            self._host.destroy()

    def _confirm_stop(self, target: RunTarget | None) -> None:
        if target is None:
            return
        debug("ui", f"stop confirmed target={type(target).__name__}")
        self._run_ui_suspended = False
        target.unpause()
        self._finish_run_ui(stopped=True, defer_cleanup=True)
        self._host.append_console(f"\n{STOP_PROCESSING}\n")
        target.stop()
        self.shutdown.schedule_inference_cleanup(target)

    def _finish_run_ui(self, *, stopped: bool = False, defer_cleanup: bool = False) -> None:
        debug("ui", f"finish_run_ui stopped={stopped} defer_cleanup={defer_cleanup}")
        if stopped and not defer_cleanup:
            self._schedule_release_inference_memory(wait_for_stop=0.5)
        self._host.set_pulse(False)
        self._set_running(False)
        self._running_target = None
        self._host.clear_progress()
        clear_run_start()
        if stopped:
            self._finish_operation("run_stopped", reason="user")

    def _on_oom_choice(self, request: typing.Any) -> None:
        """Present the mid-run OOM dialog; ``request.respond`` unblocks the worker."""
        from core.oom_choice import OOM_CHOICE_STOP

        from .oom_dialog import present_oom_choice_dialog

        if self._oom_dialog is not None:
            debug("ui", "oom dialog already open — forcing stop")
            request.respond(OOM_CHOICE_STOP)
            return

        debug(
            "ui",
            "present oom dialog "
            f"kind={getattr(request, 'process_kind', '')!r} "
            f"export={getattr(request, 'can_export', False)} "
            f"retry={getattr(request, 'can_retry', False)}",
        )
        self._run_ui_suspended = True
        self._host.set_pulse(False)

        def on_choice(choice: str) -> None:
            self._oom_dialog = None
            self._run_ui_suspended = False
            if self.is_running():
                self._host.set_pulse(True)
            label = {
                "export": "Export completed outputs",
                "stop": "Stop",
                "retry": "Retry with smaller segment",
            }.get(choice, choice)
            self._host.append_console(f"\nGPU OOM recovery: {label}\n")
            request.respond(choice)

        self._oom_dialog = present_oom_choice_dialog(
            self._host.dialog_parent,
            request,
            on_choice=on_choice,
        )

    def _on_stopped(self) -> None:
        from core.error_context import clear_run_error_context

        debug("ui", "on_stopped cooperative worker stop")
        clear_run_error_context()
        self.shutdown.cleanup_target = None
        exported = self._host.exported_after_oom()
        self._finish_run_ui(stopped=True)
        self._restore_runner_settings()
        if exported:
            toast = Adw.Toast.new("Exported completed ensemble outputs.")
            output_dir = self._run_output_dir
            if output_dir and os.path.isdir(output_dir):
                toast.set_button_label(_OPEN_FOLDER_LABEL)
                toast.connect("button-clicked", self._on_open_output_folder, output_dir)
            self._host.add_toast(toast)

    def _on_complete(self) -> None:
        from core.error_context import clear_run_error_context

        clear_run_error_context()
        self._host.set_pulse(False)
        self._set_running(False)
        self._host.set_progress_fraction(1.0)
        self._host.set_progress_text(_PROGRESS_DONE)
        self._host.mark_run_complete()
        self._running_target = None
        clear_run_start()
        self._restore_runner_settings()
        output_dir = self._run_output_dir
        self._show_complete_toast(output_dir)
        self._send_completion_notification(output_dir)
        self._schedule_release_inference_memory(wait_for_stop=0.5)
        self._finish_operation("run_completed", output_path=output_dir)

    def _on_error(self, exc: BaseException) -> None:
        self._finish_operation(
            "run_failed",
            level="error",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        self._host.set_pulse(False)
        self._set_running(False)
        self._host.set_progress_text("Failed")
        message = f"Process failed: {exc}"
        self._host.append_console(f"\n{message}\n")
        self._report_error(message, exc)
        self._send_failure_notification()
        self._running_target = None
        clear_run_start()
        self._restore_runner_settings()
        # Worker already parks on failure; park again here in case UI cleanup
        # races ahead of the worker finally/except path.
        self._schedule_release_inference_memory(park_weights=True)

    def _show_complete_toast(self, output_dir: str) -> None:
        toast = Adw.Toast.new("Process complete.")
        if output_dir and os.path.isdir(output_dir):
            toast.set_button_label(_OPEN_FOLDER_LABEL)
            toast.connect("button-clicked", self._on_open_output_folder, output_dir)
        self._host.add_toast(toast)

    def _on_open_output_folder(self, _toast: Adw.Toast, output_dir: str) -> None:
        open_folder_in_file_manager(
            self._host.dialog_parent,
            output_dir,
            on_error=self._host.toast,
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
            self._host.get_application(),
            self._host.settings,
            setting_key=NOTIFY_PROCESS_COMPLETE,
            ident="uvr-complete",
            title=title,
            body=body,
            output_dir=open_folder,
        )

    def _send_failure_notification(self) -> None:
        title = _NOTIFY_FAILED_TITLE.format(label=self._run_label)
        send_desktop_notification(
            self._host.get_application(),
            self._host.settings,
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
        **_extra: typing.Any,
    ) -> None:
        presentation = self.progress.update(
            fraction, time.monotonic(), suspended=self._run_ui_suspended,
            local_step=local_step, pass_index=pass_index, pass_total=pass_total,
            detail=detail, combine_index=combine_index, combine_total=combine_total,
        )
        if presentation is None:
            return
        self._host.set_progress_text(presentation.text)
        if presentation.pulse == "start":
            self._host.set_pulse(True)
        else:
            self._host.set_pulse(False)
        if presentation.fraction is not None:
            self._host.set_progress_fraction(presentation.fraction)

    def _report_error(self, message: str, exc: BaseException) -> None:
        from .errorlog import log_error, present_error_dialog

        target = self._running_target or self._host.target
        key = (
            target.error_key if target is not None else self._host.fallback_error_key
        )
        formatted = log_error(key, exc)
        label = self._run_label_for(target) if target is not None else "Process"
        present_error_dialog(
            self._host.dialog_parent,
            heading=f"{label} failed",
            exception=exc,
            formatted_log=formatted,
            on_copied=lambda: self._host.toast("Report copied to clipboard"),
        )

    def _snapshot_error_context(self, target: RunTarget) -> RunErrorContext:
        # Preserve capture from the visible page/shared settings at begin_run.
        return self._host.context_target.snapshot_error_context()

    def _set_running(self, running: bool) -> None:
        # Update Stop first: ``is_running()`` is ``_running_target and stop
        # sensitive``. On unlock, ``_sync_model_options_action`` must see
        # ``is_running() is False`` or Model options stays disabled.
        self._host.enable_stop(running)
        self._set_options_sensitive(not running)
        self._set_edit_actions_sensitive(not running)
        if running:
            self._host.enable_start(False)
        else:
            self.refresh_start_readiness()

    def _set_options_sensitive(self, sensitive: bool) -> None:
        self._host.set_options_sensitive(sensitive)

    def _set_edit_actions_sensitive(self, sensitive: bool) -> None:
        self._host.set_edit_actions_sensitive(sensitive)

    def _active_download_count(self) -> int:
        return self._host.active_download_count()

    def refresh_start_readiness(self) -> Optional[str]:
        """Synchronize Start sensitivity, tooltip and accessibility description."""
        if self._running_target is not None and self._host.stop_enabled():
            return None
        target = self._host.target
        reason = target_blocked_reason(target)
        self._host.enable_start(reason is None)
        description = reason or "Start processing"
        self._host.describe_start(description)
        return reason

    def _stop_all_workers(self, *, force: bool = False) -> None:
        debug("ui", f"stop_all_workers force={force}")
        self._host.stop_all_workers(force=force)

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
        self._host.release_inference_memory(
            wait_for_stop=wait_for_stop, force_if_alive=force_if_alive,
            clear_weight_cache=clear_weight_cache, park_weights=park_weights,
        )


def _resolved_job_matches_spec(plan: typing.Any, spec: typing.Any) -> bool:
    """True when a core ResolvedJob still matches the live JobSpec I/O contract."""
    from core.job_plan import ResolvedJob

    if not isinstance(plan, ResolvedJob):
        return True
    if getattr(spec, "command", None) != plan.command:
        return False
    planned_paths = tuple(os.path.normpath(item.path) for item in plan.inputs)
    spec_paths = tuple(
        os.path.normpath(path) for path in getattr(spec, "inputs", ())
    )
    if planned_paths != spec_paths:
        return False
    return os.path.normpath(plan.output or "") == os.path.normpath(
        getattr(spec, "output", "") or ""
    )


def _format_mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"
