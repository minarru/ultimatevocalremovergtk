import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from core.job_plan import PlannedInput, ResolvedJob, ValidationLevel, settings_fingerprint
from core.settings import Settings
from ui.run_control import RunController, _format_mmss, _starting_progress_text


def _resolved_job(
    *,
    command: str = "separate",
    path: str = "/in/song.wav",
    output: str = "/out",
    settings: Settings | None = None,
) -> ResolvedJob:
    from core.export_naming import OutputNamingContext

    settings = settings or Settings.defaults()
    planned = PlannedInput(
        path=path,
        naming=OutputNamingContext(
            input_path=path,
            track="song",
            track_base="song",
            export_directory=output,
            extension="wav",
        ),
        outputs=(),
    )
    return ResolvedJob(
        command=command,
        settings=settings,
        inputs=(planned,),
        models=(),
        provenance={},
        diagnostics=(),
        validation_level=ValidationLevel.RUNTIME,
        inventory_generation=0,
        settings_fingerprint=settings_fingerprint(settings),
        device="cpu",
        output=output,
    )


class FormatMmssTests(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_format_mmss(0), "0:00")

    def test_under_one_minute(self):
        self.assertEqual(_format_mmss(42.9), "0:42")

    def test_over_one_minute(self):
        self.assertEqual(_format_mmss(125), "2:05")


class EnsembleErrorContextSnapshotTests(unittest.TestCase):
    def test_live_snapshot_uses_repository_display_labels(self) -> None:
        from core.model_identity import ModelArtifacts, ModelRecord

        settings = Settings.defaults()
        settings.ensemble.selected_models = ["mdx:first", "vr:second"]
        records = {
            "mdx:first": ModelRecord(
                "mdx:first", "mdx", "first", "Friendly First", "first",
                ModelArtifacts("first.onnx"), True,
            ),
            "vr:second": ModelRecord(
                "vr:second", "vr", "second", "Friendly Second", "second",
                ModelArtifacts("second.pth"), True,
            ),
        }
        repo = object()
        window = SimpleNamespace(
            settings=settings,
            context=SimpleNamespace(repo=repo),
            content_stack=SimpleNamespace(
                get_visible_child_name=lambda: "ensemble"
            ),
            _ensemble_page=SimpleNamespace(
                input_row=SimpleNamespace(paths=["/tmp/song.wav"])
            ),
        )
        controller = cast(Any, RunController.__new__(RunController))
        controller._window = window

        with mock.patch(
            "core.error_context.ModelIdentityService.lookup",
            autospec=True,
            side_effect=lambda _service, model_id: records[model_id],
        ):
            context = controller._snapshot_error_context(object())

        self.assertEqual(context["models"], ["Friendly First", "Friendly Second"])
        self.assertEqual(settings.ensemble.selected_models, ["mdx:first", "vr:second"])


class SetRunningUnlockTests(unittest.TestCase):
    def test_unlock_keeps_model_options_enabled(self) -> None:
        """Regression: unlock must clear Stop before syncing Model options.

        ``is_running()`` is ``_running_target and stop_button.sensitive``. If
        sync runs while Stop is still sensitive, Model options is disabled
        again after a completed separation.
        """
        stop_sensitive = {"value": True}
        stop_button = mock.Mock()
        stop_button.get_sensitive.side_effect = lambda: stop_sensitive["value"]
        stop_button.set_sensitive.side_effect = lambda value: stop_sensitive.__setitem__(
            "value", bool(value)
        )

        model_options = mock.Mock()
        actions = {
            "settings": mock.Mock(),
            "view_inputs": mock.Mock(),
            "model_options": model_options,
        }

        window = mock.Mock()
        window.stop_button = stop_button
        window.start_button = mock.Mock()
        window._options_pages = []
        window.lookup_action.side_effect = lambda name: actions.get(name)

        controller = RunController.__new__(RunController)
        controller._window = window
        controller._running_target = object()

        def sync_model_options_action() -> None:
            model_options.set_enabled(not controller.is_running())

        window._sync_model_options_action = sync_model_options_action

        controller._set_running(False)

        self.assertFalse(controller.is_running())
        model_options.set_enabled.assert_called_with(True)


class HandleCloseRequestTests(unittest.TestCase):
    def test_closing_window_force_closes_stale_stop_confirm_dialog(self) -> None:
        """Regression: a Stop-confirm dialog left open when the window closes
        must be force-closed, not just have its Python reference dropped —
        otherwise its response/closed handlers stay live against state the
        shutdown-confirm flow (presented right after) goes on to mutate.
        """
        stop_button = mock.Mock()
        stop_button.get_sensitive.return_value = True
        window = mock.Mock()
        window.stop_button = stop_button

        controller = RunController.__new__(RunController)
        controller._window = window
        target = mock.Mock()
        controller._running_target = target
        controller._on_close_complete = None
        controller._shutdown_dialog = None
        stale_dialog = mock.Mock()
        controller._stop_confirm_dialog = stale_dialog
        controller._run_ui_suspended = True
        controller._close_deferred = False
        controller._present_shutdown_confirm = mock.Mock()

        result = controller.handle_close_request(lambda _keep_open: None)

        self.assertTrue(result)
        stale_dialog.force_close.assert_called_once()
        self.assertIsNone(controller._stop_confirm_dialog)
        target.unpause.assert_called_once()
        controller._present_shutdown_confirm.assert_called_once()

    def test_active_downloads_alone_require_shutdown_confirmation(self) -> None:
        stop_button = mock.Mock()
        stop_button.get_sensitive.return_value = False
        context = mock.Mock()
        context.active_download_count.return_value = 2
        window = mock.Mock(stop_button=stop_button, context=context)

        controller = RunController.__new__(RunController)
        controller._window = window
        controller._running_target = None
        controller._on_close_complete = None
        controller._shutdown_dialog = None
        controller._stop_confirm_dialog = None
        controller._close_deferred = False
        controller._present_shutdown_confirm = mock.Mock()

        result = controller.handle_close_request(lambda _deferred: None)

        self.assertTrue(result)
        self.assertTrue(controller._close_deferred)
        controller._present_shutdown_confirm.assert_called_once_with()

    def test_shutdown_poll_waits_for_download_cleanup(self) -> None:
        context = mock.Mock()
        context.active_download_count.side_effect = [1, 0]
        window = mock.Mock(context=context)

        controller = RunController.__new__(RunController)
        controller._window = window
        controller._shutdown_target = None
        controller._shutdown_attempts = 0
        controller._close_deferred = True
        controller._complete_shutdown = mock.Mock()

        self.assertTrue(controller._poll_shutdown())
        self.assertFalse(controller._poll_shutdown())
        controller._complete_shutdown.assert_called_once_with(deferred=True)


class ApplicationQuitTests(unittest.TestCase):
    def test_quit_action_closes_main_window_through_its_guard(self) -> None:
        from ui.application import UVRApplication

        window = mock.Mock()
        app = mock.Mock(_main_window=window)

        UVRApplication._on_quit_requested(app)

        window.close.assert_called_once_with()
        app.quit.assert_not_called()


class OnProgressBarTests(unittest.TestCase):
    def _controller(self) -> tuple[RunController, mock.Mock]:
        from core.run_estimate import ProgressEtaTracker

        window = mock.Mock()
        window.log_panel = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._run_ui_suspended = False
        controller._eta_tracker = ProgressEtaTracker()
        controller._last_progress_ui_at = 0.0
        controller._last_progress_phase = None
        controller._last_progress_pass = None
        controller._last_progress_combine = None
        controller._run_started_at = 0.0
        return controller, window

    def test_save_ticks_move_the_bar(self) -> None:
        controller, window = self._controller()
        controller._on_progress(0.4, local_step=0.50, pass_index=1, pass_total=1)
        first = window.log_panel.set_progress_fraction.call_args[0][0]
        controller._last_progress_ui_at = 0.0
        controller._on_progress(0.93, local_step=0.93, pass_index=1, pass_total=1)
        second = window.log_panel.set_progress_fraction.call_args[0][0]
        self.assertGreater(second, first)
        self.assertAlmostEqual(second, 0.93)

    def test_load_without_fill_pulses(self) -> None:
        controller, window = self._controller()
        controller._on_progress(0.05, local_step=0.05, pass_index=1, pass_total=1)
        window._start_pulse.assert_called()
        window.log_panel.set_progress_fraction.assert_not_called()


class AudioPreflightTests(unittest.TestCase):
    def test_audio_plan_skips_confirmation_but_still_uses_acceptance_recheck(self) -> None:
        from bundled.constants import TIME_STRETCH
        from core.audio_plan import ResolvedAudioJob
        from core.job_plan import ValidationLevel
        from core.settings import Settings

        settings = Settings.defaults()
        plan = ResolvedAudioJob(
            TIME_STRETCH, settings, "/tmp/out", (), {}, (),
            ValidationLevel.RUNTIME, 0, "fingerprint", "cpu",
        )
        window = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._set_preflight_busy = mock.Mock()
        controller._accept_plan = mock.Mock()
        controller._present_plan_confirmation = mock.Mock()
        target = object()

        controller._finish_preflight(target, "fingerprint", plan, None)

        controller._accept_plan.assert_called_once_with(target, "fingerprint", plan)
        controller._present_plan_confirmation.assert_not_called()

    def test_audio_page_uses_resolved_apollo_backend_at_start(self) -> None:
        from bundled.constants import APOLLO_RESTORE
        from core.audio_plan import ResolvedAudioJob
        from core.job_plan import ModelDescriptor, ValidationLevel
        from core.model_identity import ModelArtifacts
        from ui.audio_tools.window import AudioToolsPage

        settings = Settings.defaults()
        settings.audio_tools.apollo_model = "apollo:restorer"
        plan = ResolvedAudioJob(
            APOLLO_RESTORE,
            settings,
            "/tmp/out",
            (),
            {},
            (),
            ValidationLevel.RUNTIME,
            0,
            "fingerprint",
            "cpu",
            ModelDescriptor(
                id="apollo:restorer",
                family="apollo",
                basename="restorer",
                display="Restorer",
                backend_name="restorer.ckpt",
                artifacts=ModelArtifacts("restorer.ckpt"),
            ),
        )
        runner = mock.Mock(apollo_backend_name=None)
        page = SimpleNamespace(
            _current_tool=mock.Mock(return_value=APOLLO_RESTORE),
            _dual_pairs=[],
            inputs_row=SimpleNamespace(paths=["/tmp/song.wav"]),
            _resolve_apollo_model=mock.Mock(return_value={"ok": True}),
            runner=runner,
            window=mock.Mock(),
            context=mock.Mock(try_save_settings=mock.Mock(return_value=None)),
            _toast=mock.Mock(),
        )
        callbacks = mock.Mock()

        AudioToolsPage.start(cast(Any, page), callbacks, plan)

        page._resolve_apollo_model.assert_called_once_with("restorer.ckpt")
        self.assertEqual(runner.apollo_backend_name, "restorer.ckpt")
        runner.start.assert_called_once_with(
            APOLLO_RESTORE,
            ["/tmp/song.wav"],
            [],
            callbacks,
            apollo_params={"ok": True},
        )


class StartTargetSettingsCopyTests(unittest.TestCase):
    def test_start_target_does_not_mutate_window_settings(self) -> None:
        from core.settings import Settings

        window_settings = Settings.defaults()
        self.assertIsNone(window_settings.mdx.compensate)

        plan_settings = Settings.defaults()
        plan_settings.mdx.compensate = 1.055
        plan = mock.Mock(settings=plan_settings)

        runner = mock.Mock()
        runner.settings = window_settings
        context = mock.Mock()
        context._runner = runner
        context.runner = runner

        window = mock.Mock()
        window.settings = window_settings
        window.context = context

        target = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._callbacks = mock.Mock(return_value=object())

        controller._start_target(target, plan)

        self.assertIsNone(window.settings.mdx.compensate)
        self.assertEqual(window.context.runner.settings.mdx.compensate, 1.055)
        target.start.assert_called_once()
        self.assertNotIn("plan", target.start.call_args.kwargs)

    def test_start_target_forwards_resolved_job_plan(self) -> None:
        from core.settings import Settings

        plan = _resolved_job()
        runner = mock.Mock()
        runner.settings = Settings.defaults()
        window = mock.Mock()
        window.settings = Settings.defaults()
        window.context.runner = runner
        window.context._runner = runner
        target = mock.Mock()
        callbacks = object()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._callbacks = mock.Mock(return_value=callbacks)

        controller._start_target(target, plan)

        target.start.assert_called_once_with(callbacks, plan=plan)

    def test_start_target_forwards_audio_plan_backend_contract(self) -> None:
        from bundled.constants import TIME_STRETCH
        from core.audio_plan import ResolvedAudioJob
        from core.job_plan import ValidationLevel
        from core.settings import Settings

        settings = Settings.defaults()
        plan = ResolvedAudioJob(
            TIME_STRETCH, settings, "/tmp/out", (), {}, (),
            ValidationLevel.RUNTIME, 0, "fingerprint", "cpu",
        )
        runner = mock.Mock()
        runner.settings = Settings.defaults()
        window = mock.Mock()
        window.settings = Settings.defaults()
        window.context.runner = runner
        window.context._runner = runner
        target = mock.Mock()
        callbacks = object()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._callbacks = mock.Mock(return_value=callbacks)

        controller._start_target(target, plan)

        target.start.assert_called_once_with(callbacks, plan=plan)

    def test_start_target_applies_plan_to_audio_tools_page_runner(self) -> None:
        from core.settings import Settings

        window_settings = Settings.defaults()
        plan_settings = Settings.defaults()
        plan_settings.mdx.compensate = 1.055
        plan = mock.Mock(settings=plan_settings)

        context_runner = mock.Mock()
        context_runner.settings = window_settings
        context = mock.Mock()
        context._runner = context_runner
        context.runner = context_runner

        page_runner = mock.Mock()
        page_runner.settings = window_settings
        target = mock.Mock()
        target._runner = page_runner

        window = mock.Mock()
        window.settings = window_settings
        window.context = context
        window._audio_tools_page = target

        controller = RunController.__new__(RunController)
        controller._window = window
        controller._callbacks = mock.Mock(return_value=object())

        controller._start_target(target, plan)

        self.assertIsNone(window.settings.mdx.compensate)
        self.assertEqual(page_runner.settings.mdx.compensate, 1.055)
        self.assertIsNot(page_runner.settings, plan.settings)

        controller._restore_runner_settings()
        self.assertIs(page_runner.settings, window_settings)
        self.assertIs(context_runner.settings, window_settings)


class PlanRecheckTests(unittest.TestCase):
    def test_finished_recheck_starts_only_when_settings_and_models_are_current(self) -> None:
        from core.job_plan import settings_fingerprint
        from core.settings import Settings

        settings = Settings.defaults()
        target = mock.Mock()
        target.build_job_spec.return_value = mock.Mock(settings=settings)
        window = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._set_preflight_busy = mock.Mock()
        controller._start_target = mock.Mock()
        controller._begin_preflight = mock.Mock()
        plan = object()

        controller._finish_plan_recheck(
            target, settings_fingerprint(settings), plan, True, None
        )

        controller._set_preflight_busy.assert_called_once_with(False)
        controller._start_target.assert_called_once_with(target, plan)
        controller._begin_preflight.assert_not_called()

    def test_stale_recheck_returns_to_preflight(self) -> None:
        from core.job_plan import settings_fingerprint
        from core.settings import Settings

        settings = Settings.defaults()
        target = mock.Mock()
        target.build_job_spec.return_value = mock.Mock(settings=settings)
        window = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._set_preflight_busy = mock.Mock()
        controller._start_target = mock.Mock()
        controller._begin_preflight = mock.Mock()

        controller._finish_plan_recheck(
            target, settings_fingerprint(settings), object(), False, None
        )

        controller._start_target.assert_not_called()
        controller._begin_preflight.assert_called_once_with(target)

    def test_accept_plan_rejects_stale_input_paths(self) -> None:
        from core.job_plan import JobSpec, settings_fingerprint
        from core.settings import Settings

        settings = Settings.defaults()
        plan = _resolved_job(path="/in/old.wav", output="/out", settings=settings)
        target = mock.Mock()
        target.build_job_spec.return_value = JobSpec(
            "separate", settings, ("/in/new.wav",), "/out"
        )
        window = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._set_preflight_busy = mock.Mock()
        controller._begin_preflight = mock.Mock()
        with mock.patch("threading.Thread") as thread:
            controller._accept_plan(target, settings_fingerprint(settings), plan)

        window.toast.assert_called()
        controller._begin_preflight.assert_called_once_with(target)
        thread.assert_not_called()
        controller._set_preflight_busy.assert_not_called()

    def test_accept_plan_rejects_stale_output(self) -> None:
        from core.job_plan import JobSpec, settings_fingerprint
        from core.settings import Settings

        settings = Settings.defaults()
        plan = _resolved_job(path="/in/song.wav", output="/old", settings=settings)
        target = mock.Mock()
        target.build_job_spec.return_value = JobSpec(
            "separate", settings, ("/in/song.wav",), "/new"
        )
        window = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._set_preflight_busy = mock.Mock()
        controller._begin_preflight = mock.Mock()
        with mock.patch("threading.Thread") as thread:
            controller._accept_plan(target, settings_fingerprint(settings), plan)

        controller._begin_preflight.assert_called_once_with(target)
        thread.assert_not_called()

    def test_finish_recheck_rejects_stale_input_paths(self) -> None:
        from core.job_plan import JobSpec, settings_fingerprint
        from core.settings import Settings

        settings = Settings.defaults()
        plan = _resolved_job(path="/in/old.wav", output="/out", settings=settings)
        target = mock.Mock()
        target.build_job_spec.return_value = JobSpec(
            "separate", settings, ("/in/new.wav",), "/out"
        )
        window = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._set_preflight_busy = mock.Mock()
        controller._start_target = mock.Mock()
        controller._begin_preflight = mock.Mock()

        controller._finish_plan_recheck(
            target, settings_fingerprint(settings), plan, True, None
        )

        controller._start_target.assert_not_called()
        controller._begin_preflight.assert_called_once_with(target)


class BeginRunOutputTests(unittest.TestCase):
    def test_start_target_clears_operation_when_target_aborts_before_begin_run(self) -> None:
        from core import debug_log

        window = mock.Mock()
        window.settings = Settings.defaults()
        window.context.runner.settings = Settings.defaults()
        target = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._operation_id = None
        controller._operation_started_at = 0.0
        controller._running_target = None
        controller._callbacks = mock.Mock(return_value=mock.Mock())

        with mock.patch(
            "ui.run_control.new_operation_id", return_value="ui-run-aborted"
        ):
            controller._start_target(target)

        self.assertIsNone(controller._operation_id)
        self.assertIsNone(debug_log.current_operation_id())

    def test_start_target_handles_pre_begin_exception_and_clears_operation(self) -> None:
        from core import debug_log

        window = mock.Mock()
        window.settings = Settings.defaults()
        window.context.runner.settings = Settings.defaults()
        target = mock.Mock()
        target.start.side_effect = RuntimeError("pre-begin failure")
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._operation_id = None
        controller._operation_started_at = 0.0
        controller._running_target = None
        controller._callbacks = mock.Mock(return_value=mock.Mock())
        controller.fail_to_start = mock.Mock(
            side_effect=lambda _message, _exc: controller._finish_operation(
                "run_start_failed", level="error"
            )
        )

        with mock.patch(
            "ui.run_control.new_operation_id", return_value="ui-run-failed"
        ):
            controller._start_target(target)

        controller.fail_to_start.assert_called_once()
        self.assertIsNone(controller._operation_id)
        self.assertIsNone(debug_log.current_operation_id())

    def test_preflight_operation_is_reused_when_run_begins(self) -> None:
        from core import debug_log
        from core.run_estimate import ProgressEtaTracker
        from core.settings import Settings

        window = mock.Mock()
        window.settings = Settings.defaults()
        window.context.runner.settings = Settings.defaults()
        window.log_panel = mock.Mock()
        window.console = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._operation_id = "ui-run-preflight"
        controller._operation_started_at = 10.0
        controller._eta_tracker = ProgressEtaTracker()
        controller._snapshot_error_context = mock.Mock(return_value={})
        controller._run_label_for = mock.Mock(return_value="Separation")
        controller._set_running = mock.Mock()
        debug_log.set_operation_id("ui-run-preflight")
        self.addCleanup(debug_log.set_operation_id, None)

        with mock.patch("ui.run_control.mark_run_start"), \
             mock.patch("ui.run_control.reset_progress_log"), \
             mock.patch("ui.run_control.new_operation_id") as new_operation_id, \
             mock.patch("core.error_context.clear_run_error_context"), \
             mock.patch("core.error_context.set_run_error_context"):
            controller.begin_run(object())

        new_operation_id.assert_not_called()
        self.assertEqual(controller._operation_id, "ui-run-preflight")
        self.assertEqual(debug_log.current_operation_id(), "ui-run-preflight")

    def test_preflight_worker_inherits_ui_operation_id(self) -> None:
        from core import debug_log
        from core.settings import Settings

        observed: list[str | None] = []
        settings = Settings.defaults()
        spec = mock.Mock(settings=settings)
        plan = mock.Mock(diagnostics=[])
        target = mock.Mock()
        target.build_job_spec.return_value = spec
        window = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._operation_id = None
        controller._operation_started_at = 0.0
        controller._preflight_in_progress = False
        controller._plan_dialog = None
        controller._set_preflight_busy = mock.Mock()
        controller._finish_preflight = mock.Mock()

        class ImmediateThread:
            def __init__(
                self,
                *,
                target: Any,
                **_kwargs: Any,
            ) -> None:
                self._target = target

            def start(self) -> None:
                self._target()

        resolver = mock.Mock()

        def resolve(_spec: object, _level: object) -> object:
            observed.append(debug_log.current_operation_id())
            debug_log.log_event("settings", "plan_resolved")
            return plan

        resolver.resolve.side_effect = resolve
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="debug", log_file=str(log_path))
            self.addCleanup(debug_log.configure, level="errors", log_file="")
            with mock.patch("ui.run_control.target_blocked_reason", return_value=None), \
                 mock.patch("ui.run_control.new_operation_id", return_value="ui-run-preflight"), \
                 mock.patch("ui.run_control.threading.Thread", ImmediateThread), \
                 mock.patch("core.job_plan.JobResolver", return_value=resolver), \
                 mock.patch("ui.run_control.idle_on_main", side_effect=lambda func, *args: func(*args)):
                controller.handle_start(target)

            debug_log.log_event("worker", "worker_started")
            debug_log.log_event("audio", "export_completed")
            controller._finish_operation("run_completed")
            correlated = [
                line
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if any(
                    event in line
                    for event in (
                        "event=plan_resolved",
                        "event=worker_started",
                        "event=export_completed",
                        "event=run_completed",
                    )
                )
            ]

        self.assertEqual(observed, ["ui-run-preflight"])
        self.assertEqual(len(correlated), 4)
        self.assertTrue(
            all("operation=ui-run-preflight" in line for line in correlated)
        )
        self.assertIsNone(controller._operation_id)
        self.assertIsNone(debug_log.current_operation_id())

    def test_begin_run_uses_runner_export_path(self) -> None:
        from core.run_estimate import ProgressEtaTracker
        from core.settings import Settings

        window_settings = Settings.defaults()
        window_settings.process.export_path = "/widget/out"
        runner_settings = Settings.defaults()
        runner_settings.process.export_path = "/plan/out"
        runner = mock.Mock()
        runner.settings = runner_settings

        window = mock.Mock()
        window.settings = window_settings
        window.context.runner = runner
        window.log_panel = mock.Mock()
        window.console = mock.Mock()

        controller = RunController.__new__(RunController)
        controller._window = window
        controller._eta_tracker = ProgressEtaTracker()
        controller._snapshot_error_context = mock.Mock(return_value={})
        controller._run_label_for = mock.Mock(return_value="Separation")
        controller._set_running = mock.Mock()

        with mock.patch("ui.run_control.mark_run_start"), \
             mock.patch("ui.run_control.reset_progress_log"), \
             mock.patch("core.error_context.clear_run_error_context"), \
             mock.patch("core.error_context.set_run_error_context"):
            controller.begin_run(object())

        self.assertEqual(controller._run_output_dir, "/plan/out")

    def test_begin_run_creates_operation_context_and_completion_clears_it(self) -> None:
        from core import debug_log
        from core.run_estimate import ProgressEtaTracker
        from core.settings import Settings

        window = mock.Mock()
        window.settings = Settings.defaults()
        window.context.runner.settings = Settings.defaults()
        window.log_panel = mock.Mock()
        window.console = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._eta_tracker = ProgressEtaTracker()
        controller._snapshot_error_context = mock.Mock(return_value={})
        controller._run_label_for = mock.Mock(return_value="Separation")
        controller._set_running = mock.Mock()
        controller._restore_runner_settings = mock.Mock()
        controller._show_complete_toast = mock.Mock()
        controller._send_completion_notification = mock.Mock()
        controller._schedule_release_inference_memory = mock.Mock()

        with mock.patch("ui.run_control.mark_run_start"), \
             mock.patch("ui.run_control.reset_progress_log"), \
             mock.patch("ui.run_control.new_operation_id", return_value="ui-run-7"), \
             mock.patch("core.error_context.clear_run_error_context"), \
             mock.patch("core.error_context.set_run_error_context"):
            controller.begin_run(object())
            self.assertEqual(debug_log.current_operation_id(), "ui-run-7")
            controller._on_complete()

        self.assertIsNone(debug_log.current_operation_id())

    def test_fail_to_start_restores_runner_settings(self) -> None:
        window = mock.Mock()
        window.console = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._set_running = mock.Mock()
        controller._report_error = mock.Mock()
        controller._restore_runner_settings = mock.Mock()
        controller._running_target = object()

        controller.fail_to_start("Unable to start", RuntimeError("boom"))

        controller._restore_runner_settings.assert_called_once()
        self.assertIsNone(controller._running_target)


class StartingProgressTextTests(unittest.TestCase):
    def test_starting_progress_text_uses_warmup_state(self) -> None:
        with mock.patch("ui.run_control.engines_imported", return_value=True):
            self.assertEqual(_starting_progress_text(), "Starting…")
        with mock.patch("ui.run_control.engines_imported", return_value=False):
            with mock.patch("ui.run_control.warm_status", return_value="in_progress"):
                self.assertEqual(_starting_progress_text(), "Importing engines…")
            with mock.patch("ui.run_control.warm_status", return_value="not_started"):
                self.assertEqual(_starting_progress_text(), "Loading engines…")


if __name__ == "__main__":
    unittest.main()


class ActiveModelLabelTests(unittest.TestCase):
    """The label the run surfaces is the identity display, not a second mapper.

    `ModelConfig.model_display_label` is assigned from `identity.display`, and
    `_model_output_label` is what export paths and the floating log read. No UI
    code re-derives a label during a run.
    """

    def test_run_label_prefers_the_identity_display(self) -> None:
        from core.run_hooks import _model_output_label

        model = SimpleNamespace(
            model_display_label="MelBand Roformer — Karaoke · becruily",
            model_name="melband_roformer_karaoke_becruily",
            model_basename="melband_roformer_karaoke_becruily",
        )

        self.assertEqual(
            _model_output_label(cast(Any, model)),
            "MelBand Roformer — Karaoke · becruily",
        )

    def test_unknown_custom_model_falls_back_to_its_basename(self) -> None:
        from core.run_hooks import _model_output_label

        model = SimpleNamespace(
            model_display_label="",
            model_name="",
            model_basename="my_private_model",
        )

        self.assertEqual(_model_output_label(cast(Any, model)), "my_private_model")

    def test_model_config_takes_its_label_from_the_identity_record(self) -> None:
        """Locks the assignment in core/model_config/config.py."""
        import inspect

        from core.model_config import config as config_mod

        source = inspect.getsource(config_mod)
        self.assertIn("self.model_display_label = (", source)
        self.assertIn("identity.display if identity is not None else model_name", source)
