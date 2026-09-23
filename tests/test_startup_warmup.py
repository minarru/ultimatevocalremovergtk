"""First-frame startup work is ordered after the initial GTK paint."""

from __future__ import annotations

import os
import sys
import time
import unittest
from typing import TYPE_CHECKING, Any
from unittest import mock
from unittest.mock import Mock

if TYPE_CHECKING:
    from ui.startup import FirstFrameScheduler


def _require_gtk_versions() -> None:
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("GLib", "2.0")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")


def _gtk_available() -> bool:
    try:
        _require_gtk_versions()
    except (ImportError, ValueError):
        return False
    return True


_GTK_AVAILABLE = _gtk_available()


class _GtkRequiredTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        _require_gtk_versions()


class _FakeFrameClock:
    def __init__(self) -> None:
        self.connected: list[tuple[str, object, int]] = []
        self.disconnected: list[int] = []
        self.requested_phases: list[Any] = []
        self._next_handler = 40

    def connect(self, signal: str, callback: object) -> int:
        self._next_handler += 1
        handler_id = self._next_handler
        self.connected.append((signal, callback, handler_id))
        return handler_id

    def request_phase(self, phase: Any) -> None:
        self.requested_phases.append(phase)

    def disconnect(self, handler_id: int) -> None:
        self.disconnected.append(handler_id)

    def emit_after_paint(self) -> None:
        for signal, callback, _handler_id in tuple(self.connected):
            if signal == "after-paint":
                callback(self)  # type: ignore[operator]


class _FakeWidget:
    def __init__(self, frame_clock: _FakeFrameClock | None) -> None:
        self.frame_clock = frame_clock

    def get_frame_clock(self) -> Any:
        return self.frame_clock


class _FakeIdle:
    def __init__(self) -> None:
        self.callbacks: dict[int, object] = {}
        self.removed: list[int] = []
        self._next_source = 90

    def add(self, callback: object) -> int:
        self._next_source += 1
        source_id = self._next_source
        self.callbacks[source_id] = callback
        return source_id

    def remove(self, source_id: int) -> None:
        self.removed.append(source_id)

    def run(self, source_id: int) -> object:
        callback = self.callbacks[source_id]
        return callback()  # type: ignore[operator]


@unittest.skipUnless(_GTK_AVAILABLE, "GTK libraries unavailable")
class FirstFrameWarmupTests(_GtkRequiredTestCase):
    def _scheduler(self) -> tuple["FirstFrameScheduler", _FakeFrameClock, _FakeIdle]:
        from ui.startup import FirstFrameScheduler

        clock = _FakeFrameClock()
        idle = _FakeIdle()
        scheduler = FirstFrameScheduler(idle_add=idle.add, source_remove=idle.remove)
        return scheduler, clock, idle

    def test_callback_waits_for_after_paint_then_idle(self) -> None:
        scheduler, clock, idle = self._scheduler()
        callback = Mock()

        self.assertTrue(scheduler.schedule(_FakeWidget(clock), callback))
        callback.assert_not_called()
        self.assertEqual([entry[0] for entry in clock.connected], ["after-paint"])
        from gi.repository import Gdk

        self.assertEqual(clock.requested_phases, [Gdk.FrameClockPhase.PAINT])

        clock.emit_after_paint()
        callback.assert_not_called()
        self.assertEqual(len(idle.callbacks), 1)
        source_id = next(iter(idle.callbacks))
        idle.run(source_id)

        callback.assert_called_once_with()

    def test_schedule_is_idempotent_before_and_after_first_frame(self) -> None:
        scheduler, clock, idle = self._scheduler()
        callback = Mock()
        widget = _FakeWidget(clock)

        self.assertTrue(scheduler.schedule(widget, callback))
        self.assertFalse(scheduler.schedule(widget, callback))
        clock.emit_after_paint()
        self.assertFalse(scheduler.schedule(widget, callback))
        source_id = next(iter(idle.callbacks))
        idle.run(source_id)
        self.assertFalse(scheduler.schedule(widget, callback))
        callback.assert_called_once_with()
        self.assertEqual(len(clock.connected), 1)
        self.assertEqual(len(clock.requested_phases), 1)

    def test_cancel_before_after_paint_disconnects_frame_handler(self) -> None:
        scheduler, clock, idle = self._scheduler()
        callback = Mock()

        self.assertTrue(scheduler.schedule(_FakeWidget(clock), callback))
        handler_id = clock.connected[0][2]
        scheduler.cancel()
        clock.emit_after_paint()

        self.assertEqual(clock.disconnected, [handler_id])
        self.assertEqual(idle.callbacks, {})
        callback.assert_not_called()

    def test_cancel_after_paint_removes_idle_and_blocks_callback(self) -> None:
        scheduler, clock, idle = self._scheduler()
        callback = Mock()

        self.assertTrue(scheduler.schedule(_FakeWidget(clock), callback))
        clock.emit_after_paint()
        source_id = next(iter(idle.callbacks))
        scheduler.cancel()
        idle.run(source_id)

        self.assertEqual(idle.removed, [source_id])
        callback.assert_not_called()

    def test_schedule_without_frame_clock_does_not_queue_startup_work(self) -> None:
        scheduler, _clock, idle = self._scheduler()
        callback = Mock()

        self.assertFalse(scheduler.schedule(_FakeWidget(None), callback))
        self.assertEqual(idle.callbacks, {})
        callback.assert_not_called()


@unittest.skipUnless(
    _GTK_AVAILABLE and bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    "GTK needs a display",
)
class FirstFrameGtkIntegrationTests(_GtkRequiredTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        from tests.private_gtk import require_private_gtk

        require_private_gtk()

    def test_window_map_runs_warmup_after_a_real_frame(self) -> None:
        from gi.repository import GLib, Gtk

        from ui.startup import FirstFrameScheduler

        window = Gtk.Window()
        window.set_default_size(120, 80)
        window.set_child(Gtk.Label(label="frame"))
        self.addCleanup(window.close)
        scheduler = FirstFrameScheduler()
        self.addCleanup(scheduler.cancel)
        mapped: list[bool] = []
        phases: list[str] = []
        warm: list[bool] = []

        def on_map(_window: Gtk.Window) -> None:
            mapped.append(True)
            clock = window.get_frame_clock()
            assert clock is not None
            clock.connect("paint", lambda _clock: phases.append("paint"))
            clock.connect("after-paint", lambda _clock: phases.append("after-paint"))
            self.assertTrue(scheduler.schedule(window, lambda: warm.append(True)))

        window.connect("map", on_map)
        window.present()
        deadline = time.monotonic() + 3.0
        context = GLib.MainContext.default()
        while not warm and time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            time.sleep(0.005)

        self.assertEqual(mapped, [True])
        self.assertEqual(
            warm,
            [True],
            f"mapped={window.get_mapped()} size={window.get_width()}x{window.get_height()} "
            f"phases={phases} frame_handler={scheduler._after_paint_id} "
            f"idle={scheduler._idle_id} idle_add={scheduler._idle_add!r}",
        )

    def test_quiescent_mapped_window_requests_a_new_paint_before_warmup(self) -> None:
        from gi.repository import GLib, Gtk

        from ui.startup import FirstFrameScheduler

        window = Gtk.Window()
        window.set_default_size(120, 80)
        window.set_child(Gtk.Label(label="static"))
        self.addCleanup(window.close)
        scheduler = FirstFrameScheduler()
        self.addCleanup(scheduler.cancel)
        window.present()
        clock = window.get_frame_clock()
        assert clock is not None
        phases: list[str] = []
        clock.connect("paint", lambda _clock: phases.append("paint"))
        clock.connect("after-paint", lambda _clock: phases.append("after-paint"))
        context = GLib.MainContext.default()
        # Model a caller arriving after a static window has stopped producing
        # frames. Stable frame count is the precondition, not extra warmup time.
        deadline = time.monotonic() + 3.0
        last_counter = clock.get_frame_counter()
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            counter = clock.get_frame_counter()
            if counter != last_counter:
                last_counter, stable_since = counter, time.monotonic()
            if "paint" in phases and time.monotonic() - stable_since >= 0.1:
                break
            time.sleep(0.005)
        self.assertIn("paint", phases)
        self.assertGreaterEqual(time.monotonic() - stable_since, 0.1)
        phases.clear()
        self.assertTrue(scheduler.schedule(window, lambda: phases.append("warm")))
        deadline = time.monotonic() + 3.0
        while "warm" not in phases and time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            time.sleep(0.005)
        self.assertEqual(phases, ["paint", "after-paint", "warm"])


@unittest.skipUnless(_GTK_AVAILABLE, "GTK libraries unavailable")
class MainWindowWarmupLifecycleTests(_GtkRequiredTestCase):
    def test_window_schedules_existing_warmup_callback(self) -> None:
        from ui.window import MainWindow

        window: Any = MainWindow.__new__(MainWindow)
        scheduler = Mock()
        window._engine_warmup = scheduler

        MainWindow._schedule_engine_warmup(window)

        scheduler.schedule.assert_called_once_with(window, mock.ANY)
        callback = scheduler.schedule.call_args.args[1]
        with mock.patch("core.separate_import.warm_import_separate_engines") as warmup:
            callback()
        warmup.assert_called_once_with()

    def test_vetoed_close_keeps_pending_warmup(self) -> None:
        from ui.window import MainWindow

        window: Any = MainWindow.__new__(MainWindow)
        scheduler = Mock()
        controller = Mock()
        controller.handle_close_request.return_value = True
        window._engine_warmup = scheduler
        window._run_controller = controller

        self.assertTrue(MainWindow._on_close_request(window))
        scheduler.cancel.assert_not_called()

    def test_accepted_close_cancels_pending_warmup(self) -> None:
        from types import SimpleNamespace

        from ui.window import MainWindow

        window: Any = MainWindow.__new__(MainWindow)
        scheduler = Mock()
        window._engine_warmup = scheduler
        window._unsubscribe_model_events = Mock()
        window._flush_settings = Mock()
        window._save_geometry = Mock()
        window._handle_settings_error = Mock()
        window.context = SimpleNamespace(try_save_settings=Mock(return_value=None))
        window._download_ui = None

        MainWindow._finalize_close(window, False)

        scheduler.cancel.assert_called_once_with()


@unittest.skipUnless(_GTK_AVAILABLE, "GTK libraries unavailable")
class ApplicationStartupImportTests(_GtkRequiredTestCase):
    def test_application_shutdown_cancels_pending_warmup(self) -> None:
        from gi.repository import Adw

        from ui.application import UVRApplication

        app: Any = UVRApplication.__new__(UVRApplication)
        window = Mock()
        app._main_window = window
        with mock.patch.object(Adw.Application, "do_shutdown") as parent_shutdown:
            UVRApplication.do_shutdown(app)

        window.cancel_startup_work.assert_called_once_with()
        parent_shutdown.assert_called_once_with(app)

    def test_main_runs_without_checkpoint_alias_initialization(self) -> None:
        from core.settings import Settings
        from ui import application

        fake_app = Mock()
        fake_app.run.return_value = 0
        fake_app._did_activate = True
        with (
            mock.patch.dict(sys.modules, {"core.torch_checkpoint": None}),
            mock.patch.object(application, "UVRApplication", return_value=fake_app),
            mock.patch.object(application.Settings, "load", return_value=Settings.defaults()),
            mock.patch("core.debug_log.configure_from_settings"),
            mock.patch("core.debug_log.install_runtime_hooks"),
            mock.patch("core.debug_log.log_event"),
            mock.patch("core.debug_log.announce_log_file"),
            mock.patch("ui.shutdown.finalize_process_exit"),
        ):
            self.assertEqual(application.main(["uvr"]), 0)


if __name__ == "__main__":
    unittest.main()
