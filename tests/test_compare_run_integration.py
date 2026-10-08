"""Run controller collects finished inputs and offers the compare dialog."""

from __future__ import annotations

import unittest
from typing import Any, cast
from unittest import mock

from core.job_plan import PlannedOutput
from core.listening import REFERENCE_LABEL, ComparisonSet, Track
from ui.playback.session import ListeningSession


def _cset(src: str, *outs: str) -> ComparisonSet:
    return ComparisonSet(
        src, (Track(REFERENCE_LABEL, src, None, True), *(Track(o, o) for o in outs))
    )


class ListeningSessionTests(unittest.TestCase):
    def test_add_clear_and_order(self) -> None:
        session = ListeningSession()
        self.assertFalse(session)
        session.add(_cset("/a", "/a1"))
        session.add(_cset("/b", "/b1"))
        self.assertEqual([s.source for s in session.sets()], ["/a", "/b"])
        self.assertEqual(len(session), 2)
        session.clear()
        self.assertFalse(session)

    def test_same_source_replaces_in_place(self) -> None:
        session = ListeningSession()
        session.add(_cset("/a", "/a1"))
        session.add(_cset("/b", "/b1"))
        session.add(_cset("/a", "/a2"))
        self.assertEqual([s.tracks[-1].path for s in session.sets()], ["/a2", "/b1"])


class DispatchInputFinishedTests(unittest.TestCase):
    def test_input_finished_is_marshalled_with_all_arguments(self) -> None:
        from ui.dispatch import gtk_job_callbacks

        received: list[tuple[Any, ...]] = []
        scheduled: list[Any] = []
        with mock.patch(
            "ui.dispatch.GLib.idle_add", side_effect=lambda f, *a: scheduled.append((f, a))
        ):
            callbacks = gtk_job_callbacks(on_input_finished=lambda *a: received.append(a))
            callbacks.input_finished(("/in/a.wav",), ("/out/a.wav",), None, reference="/c.wav")
            self.assertEqual(received, [])
            for func, args in scheduled:
                func(*args)
        self.assertEqual(received, [(("/in/a.wav",), ("/out/a.wav",), None, "/c.wav")])


def _controller() -> tuple[Any, mock.Mock]:
    from core.settings import Settings
    from ui.run_control import RunController
    from ui.run_error_context import RunErrorContext
    from ui.run_host import GtkRunHost
    from ui.run_progress import RunProgressPresenter

    window = mock.Mock()
    window.settings = Settings.defaults()
    window.context.runner.settings = Settings.defaults()
    controller = RunController(GtkRunHost(cast(Any, window)))
    controller.progress = RunProgressPresenter()
    controller._snapshot_error_context = mock.Mock(return_value=RunErrorContext("test"))
    controller._run_label_for = mock.Mock(return_value="Separation")
    controller._set_running = mock.Mock()
    controller._restore_runner_settings = mock.Mock()
    controller._send_completion_notification = mock.Mock()
    controller._schedule_release_inference_memory = mock.Mock()
    return controller, window


def _begin(controller: Any) -> None:
    with (
        mock.patch("ui.run_control.mark_run_start"),
        mock.patch("ui.run_control.reset_progress_log"),
        mock.patch("core.error_context.clear_run_error_context"),
        mock.patch("core.error_context.set_run_error_context"),
    ):
        controller.begin_run(mock.Mock())


class RunControllerCompareTests(unittest.TestCase):
    def test_input_finished_builds_labelled_sets_from_the_plan(self) -> None:
        controller, _ = _controller()
        controller._run_planned_outputs = {
            "/in/song.wav": (PlannedOutput("/out/song (Vocals).wav", "Vocals"),)
        }
        _begin(controller)
        controller._on_input_finished(("/in/song.wav",), ("/out/song (Vocals).wav",), None, None)
        (cset,) = controller.listening.sets()
        self.assertEqual([t.label for t in cset.tracks], [REFERENCE_LABEL, "Vocals"])

    def test_input_without_outputs_is_ignored(self) -> None:
        controller, _ = _controller()
        _begin(controller)
        controller._on_input_finished(("/in/song.wav",), (), None, None)
        self.assertFalse(controller.listening)

    def test_begin_run_closes_open_dialog_and_clears_session(self) -> None:
        controller, window = _controller()
        controller.listening.add(_cset("/a", "/a1"))
        dialog = mock.Mock()
        controller._compare_dialog = dialog
        _begin(controller)
        dialog.close.assert_called_once()
        self.assertIsNone(controller._compare_dialog)
        self.assertFalse(controller.listening)
        window.set_compare_available.assert_called_with(False)

    def test_complete_toast_offers_compare_when_ready(self) -> None:
        controller, window = _controller()
        _begin(controller)
        controller.listening.add(_cset("/a", "/a1"))
        with mock.patch("ui.run_control.playback_unavailable_reason", return_value=None):
            controller._on_complete()
        toast = window.toast_overlay.add_toast.call_args.args[0]
        self.assertEqual(toast.get_button_label(), "Compare")
        window.set_compare_available.assert_called_with(True)

    def test_complete_toast_keeps_open_folder_without_gstreamer(self) -> None:
        controller, window = _controller()
        _begin(controller)
        controller.listening.add(_cset("/a", "/a1"))
        controller._run_output_dir = "/"
        with mock.patch("ui.run_control.playback_unavailable_reason", return_value="missing"):
            controller._on_complete()
        toast = window.toast_overlay.add_toast.call_args.args[0]
        self.assertEqual(toast.get_button_label(), "Open Folder")
        window.set_compare_available.assert_called_with(False)

    def test_stopped_run_with_finished_inputs_offers_compare(self) -> None:
        controller, window = _controller()
        _begin(controller)
        controller.listening.add(_cset("/a", "/a1"))
        window.context.runner.last_oom_exported = False
        controller._host.exported_after_oom = mock.Mock(return_value=False)
        controller._finish_run_ui = mock.Mock()
        with mock.patch("ui.run_control.playback_unavailable_reason", return_value=None):
            controller._on_stopped()
        toast = window.toast_overlay.add_toast.call_args.args[0]
        self.assertEqual(toast.get_button_label(), "Compare")

    def test_failed_run_keeps_finished_inputs_comparable(self) -> None:
        controller, window = _controller()
        _begin(controller)
        controller.listening.add(_cset("/a", "/a1"))
        controller._report_error = mock.Mock()
        controller._send_failure_notification = mock.Mock()
        with mock.patch("ui.run_control.playback_unavailable_reason", return_value=None):
            controller._on_error(RuntimeError("input 2 failed"))
        window.set_compare_available.assert_called_with(True)

    def test_open_compare_presents_one_dialog(self) -> None:
        controller, _ = _controller()
        controller.listening.add(_cset("/a", "/a1"))
        controller._host.settings.ui.listening_in_window = True
        with (
            mock.patch("ui.run_control.playback_unavailable_reason", return_value=None),
            mock.patch("ui.playback.engine.PlaybackEngine") as engine_cls,
            mock.patch("ui.playback.dialog.CompareDialog") as dialog_cls,
        ):
            controller.open_compare()
            controller.open_compare()
        dialog_cls.assert_called_once()
        self.assertIs(dialog_cls.call_args.args[1], engine_cls.return_value)
        dialog_cls.return_value.present.assert_called()
        loader = dialog_cls.call_args.kwargs["waveforms"]
        self.assertIs(loader.cache, controller.listening.peak_cache)
        self.assertIs(dialog_cls.call_args.kwargs["open_in_window"], True)


if __name__ == "__main__":
    unittest.main()
