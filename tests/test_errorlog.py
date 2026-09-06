import os
import unittest

from bundled.error_handling import FFMPEG_MISSING_ERROR, error_dialouge, error_text
from ui.errorlog import (
    _ERROR_DIALOG_WIDTH,
    _ERROR_SUMMARY_MAX_HEIGHT,
    _ERROR_SUMMARY_MIN_HEIGHT,
    _error_dialog_width,
    _friendly_error_message,
    _summary_viewport_height,
    get_error_log,
    log_error,
    set_error_log,
)


class ErrorLogTests(unittest.TestCase):
    def setUp(self) -> None:
        set_error_log("")

    def test_log_error_stores_formatted_text(self) -> None:
        from core.error_context import clear_run_error_context

        clear_run_error_context()
        exc = KeyError("'All Stems'")
        formatted = log_error("MDX-Net", exc)
        self.assertIn("MDX-Net", formatted)
        self.assertIn("All Stems", formatted)
        self.assertEqual(get_error_log(), formatted)

    def test_error_dialouge_includes_exception_name(self) -> None:
        body = error_dialouge(ValueError("bad segment size"))
        self.assertIn("ValueError", body)

    def test_error_text_includes_traceback_block(self) -> None:
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            formatted = error_text("VR", exc)
        self.assertIn("Traceback Error", formatted)
        self.assertIn("RuntimeError", formatted)

    def test_friendly_error_message_omits_generic_contact_only_text(self) -> None:
        self.assertIsNone(_friendly_error_message(RuntimeError("boom")))

    def test_friendly_error_message_keeps_mapped_guidance(self) -> None:
        message = _friendly_error_message(MemoryError("CUDA out of memory"))
        self.assertIsNotNone(message)
        self.assertIn("GPU memory", message or "")

    def test_ffmpeg_missing_error_matches_current_platform_path_separator(self) -> None:
        # Traceback paths use os.sep for the running platform (Linux/macOS use
        # "/"); a hardcoded backslash here would never match outside Windows.
        traceback_line = (
            f'  File "{os.path.join("/usr/lib/audioread", "__init__.py")}", '
            "line 116, in audio_open\n"
        )
        self.assertIn(FFMPEG_MISSING_ERROR, traceback_line)

    def test_ffmpeg_missing_error_surfaces_friendly_message(self) -> None:
        exc = RuntimeError(
            f'  File "{os.path.join("audioread", "__init__.py")}", line 116, in audio_open'
        )
        message = _friendly_error_message(exc)
        self.assertIsNotNone(message)
        self.assertIn("FFmpeg", message or "")

    def test_error_dialog_width_is_readable_but_capped(self) -> None:
        class _WideWindow:
            def get_width(self) -> int:
                return 1400

            def get_default_size(self) -> tuple[int, int]:
                return (1400, 900)

        self.assertEqual(_error_dialog_width(_WideWindow()), _ERROR_DIALOG_WIDTH)
        self.assertGreaterEqual(_ERROR_DIALOG_WIDTH, 560)

    def test_error_dialog_width_shrinks_on_narrow_parent(self) -> None:
        class _NarrowWindow:
            def get_width(self) -> int:
                return 480

            def get_default_size(self) -> tuple[int, int]:
                return (480, 640)

        self.assertEqual(_error_dialog_width(_NarrowWindow()), 416)

    def test_summary_viewport_height_fits_short_errors(self) -> None:
        height = _summary_viewport_height("RuntimeError: boom", width_px=520)
        self.assertGreaterEqual(height, _ERROR_SUMMARY_MIN_HEIGHT)
        self.assertLess(height, 120)

    def test_summary_viewport_height_caps_long_errors(self) -> None:
        long_text = "RuntimeError: " + ("x" * 4000)
        height = _summary_viewport_height(long_text, width_px=520)
        self.assertEqual(height, _ERROR_SUMMARY_MAX_HEIGHT)

    def test_typical_runtime_error_stays_under_scroll_cap(self) -> None:
        summary = (
            "RuntimeError: PytorchStreamReader failed reading zip archive: "
            "failed finding central directory. This is an internal miniz error. "
            "If you are seeing this error, there is a high likelihood that your "
            "checkpoint file is corrupted."
        )
        height = _summary_viewport_height(summary, width_px=520)
        self.assertLessEqual(height, _ERROR_SUMMARY_MAX_HEIGHT)


class ErrorLogViewLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')
        from gi.repository import Gtk

        Gtk.init()
        from tests.private_gtk import require_private_gtk

        require_private_gtk()

    def test_direct_console_entry_initializes_adwaita_in_fresh_process(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import gi; gi.require_version('Gtk', '4.0'); "
                "gi.require_version('Adw', '1'); from gi.repository import Gtk; "
                "Gtk.init(); from ui import errorlog; "
                "errorlog.set_error_log('fresh process report'); "
                "window = errorlog.open_error_log(None); "
                "buffer = errorlog._ERROR_LOG_BUFFER; "
                "assert buffer is not None; "
                "assert buffer.get_text(buffer.get_start_iter(), "
                "buffer.get_end_iter(), True) == 'fresh process report'; "
                "window.close()",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_worker_update_close_and_reopen_dispose_queued_sink(self) -> None:
        import gc
        import threading
        import time
        import weakref

        from gi.repository import GLib, Gtk

        from core.error_log import append_error_log
        from ui import errorlog

        def buffer_text(buffer: Gtk.TextBuffer) -> str:
            return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

        set_error_log('seed')
        parent = Gtk.Window()
        window = errorlog.open_error_log(parent)
        self.addCleanup(parent.close)
        self.addCleanup(
            lambda: errorlog._ERROR_LOG_WINDOW.close() if errorlog._ERROR_LOG_WINDOW else None
        )
        old_buffer = errorlog._ERROR_LOG_BUFFER
        assert old_buffer is not None
        old_buffer_ref = weakref.ref(old_buffer)
        old_sink = weakref.ref(errorlog._ERROR_LOG_SINK)
        worker = threading.Thread(target=append_error_log, args=('worker',))
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        deadline = time.monotonic() + 5
        context = GLib.MainContext.default()
        while 'worker' not in buffer_text(old_buffer) and time.monotonic() < deadline:
            context.iteration(False)
        self.assertIn('worker', buffer_text(old_buffer))
        # Schedule, then close before main-loop delivery. Old idles cannot own widgets.
        append_error_log('queued')
        window.close()
        self.assertIsNone(errorlog._ERROR_LOG_SINK)
        gc.collect()
        self.assertIsNone(old_sink())
        reopened = errorlog.open_error_log(parent)
        self.assertIsNot(reopened, window)
        new_buffer = errorlog._ERROR_LOG_BUFFER
        assert new_buffer is not None
        self.assertEqual(buffer_text(new_buffer), get_error_log())
        while context.pending():
            context.iteration(False)
        self.assertNotIn('queued', buffer_text(old_buffer))
        self.assertIn('queued', buffer_text(new_buffer))
        reopened.close()
        del old_buffer, window
        gc.collect()
        self.assertIsNone(old_buffer_ref())


if __name__ == "__main__":
    unittest.main()
