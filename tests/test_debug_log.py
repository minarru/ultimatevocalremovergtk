import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from core import debug_log, glib_log


@contextmanager
def _capture_fds() -> Iterator[list[str]]:
    """Capture OS-level stdout/stderr (GLib writes to fds, not sys.stderr)."""
    out_r, out_w = os.pipe()
    err_r, err_w = os.pipe()
    saved_out = os.dup(1)
    saved_err = os.dup(2)
    captured = ["", ""]
    try:
        os.dup2(out_w, 1)
        os.dup2(err_w, 2)
        os.close(out_w)
        os.close(err_w)
        yield captured
    finally:
        # Restore first so reads below don't block forever on open writers.
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        with os.fdopen(out_r, "r", encoding="utf-8", errors="replace") as out_f:
            captured[0] = out_f.read()
        with os.fdopen(err_r, "r", encoding="utf-8", errors="replace") as err_f:
            captured[1] = err_f.read()


class DebugLogTests(unittest.TestCase):
    def setUp(self) -> None:
        debug_log._DOMAINS = None
        debug_log._GMD_NORMALIZED = False
        debug_log._LOG_FILE_PATH = None
        debug_log._LOG_FILE_ANNOUNCED = False
        debug_log._RUN_T0 = None
        debug_log._SEQ = 0
        glib_log.set_emit_hook(None)
        self._old_gmd = os.environ.pop("G_MESSAGES_DEBUG", None)
        self._old_log = os.environ.pop("UVR_LOG_FILE", None)
        self._old_verbose = os.environ.pop("UVR_VERBOSE", None)

    def tearDown(self) -> None:
        debug_log._DOMAINS = None
        debug_log._GMD_NORMALIZED = False
        debug_log._LOG_FILE_PATH = None
        debug_log._LOG_FILE_ANNOUNCED = False
        debug_log._RUN_T0 = None
        debug_log._SEQ = 0
        glib_log.set_emit_hook(None)
        if self._old_gmd is not None:
            os.environ["G_MESSAGES_DEBUG"] = self._old_gmd
        else:
            os.environ.pop("G_MESSAGES_DEBUG", None)
        if self._old_log is not None:
            os.environ["UVR_LOG_FILE"] = self._old_log
        else:
            os.environ.pop("UVR_LOG_FILE", None)
        if self._old_verbose is not None:
            os.environ["UVR_VERBOSE"] = self._old_verbose
        else:
            os.environ.pop("UVR_VERBOSE", None)

    def test_disabled_by_default(self) -> None:
        self.assertFalse(debug_log.enabled("ui"))

    def test_uvr_enables_all_components(self) -> None:
        os.environ["G_MESSAGES_DEBUG"] = "uvr"
        self.assertTrue(debug_log.enabled("ui"))
        self.assertTrue(debug_log.enabled("worker"))
        self.assertTrue(debug_log.enabled("model"))

    def test_all_enables_everything(self) -> None:
        os.environ["G_MESSAGES_DEBUG"] = "all"
        self.assertTrue(debug_log.enabled("worker"))

    def test_component_filter_shorthand(self) -> None:
        os.environ["G_MESSAGES_DEBUG"] = "ui,dispatch,trace"
        self.assertTrue(debug_log.enabled("ui"))
        self.assertTrue(debug_log.enabled("dispatch"))
        self.assertTrue(debug_log.enabled("trace"))
        self.assertFalse(debug_log.enabled("worker"))

    def test_component_filter_domain_names(self) -> None:
        os.environ["G_MESSAGES_DEBUG"] = "uvr-ui,uvr-worker"
        self.assertTrue(debug_log.enabled("ui"))
        self.assertTrue(debug_log.enabled("worker"))
        self.assertFalse(debug_log.enabled("model"))

    def test_uvr_ui_does_not_enable_worker(self) -> None:
        os.environ["G_MESSAGES_DEBUG"] = "uvr-ui"
        self.assertTrue(debug_log.enabled("ui"))
        self.assertFalse(debug_log.enabled("worker"))

    def test_verbose_follows_trace_domain(self) -> None:
        self.assertFalse(debug_log.verbose())
        os.environ["G_MESSAGES_DEBUG"] = "uvr-trace"
        debug_log._DOMAINS = None
        self.assertTrue(debug_log.verbose())
        os.environ["G_MESSAGES_DEBUG"] = "uvr-ui"
        debug_log._DOMAINS = None
        self.assertFalse(debug_log.verbose())

    def test_uvr_verbose_env_enables_verbose(self) -> None:
        self.assertFalse(debug_log.verbose())
        os.environ["UVR_VERBOSE"] = "1"
        self.assertTrue(debug_log.verbose())
        os.environ["UVR_VERBOSE"] = "true"
        self.assertTrue(debug_log.verbose())

    def test_uvr_console_shorthand_no_longer_enables_verbose(self) -> None:
        os.environ["G_MESSAGES_DEBUG"] = "uvr-console"
        debug_log._DOMAINS = None
        self.assertFalse(debug_log.verbose())

    def test_preview_text_truncates(self) -> None:
        self.assertTrue(debug_log.preview_text("a\nb" * 40).endswith("..."))
        self.assertEqual(debug_log.preview_text("short"), "short")

    def test_next_seq_resets_on_mark_run_start(self) -> None:
        debug_log.mark_run_start()
        self.assertEqual(debug_log.next_seq(), 1)
        self.assertEqual(debug_log.next_seq(), 2)
        debug_log.mark_run_start()
        self.assertEqual(debug_log.next_seq(), 1)

    def test_trace_phase_noop_when_disabled(self) -> None:
        with debug_log.trace_phase("separate", "demix", model="test"):
            pass

    def test_trace_phase_logs_when_enabled(self) -> None:
        emitted: list[tuple[str, str]] = []

        def _hook(domain: str, message: str, _level: int) -> None:
            emitted.append((domain, message))

        glib_log.set_emit_hook(_hook)
        os.environ["G_MESSAGES_DEBUG"] = "uvr-separate"

        with debug_log.trace_phase("separate", "demix", model="m1"):
            pass

        messages = [msg for _domain, msg in emitted]
        self.assertTrue(any("phase=demix start" in msg for msg in messages))
        self.assertTrue(any("phase=demix done" in msg for msg in messages))

    def test_debug_mirrors_to_log_file(self) -> None:
        emitted: list[str] = []

        def _hook(_domain: str, message: str, _level: int) -> None:
            emitted.append(message)

        glib_log.set_emit_hook(_hook)
        os.environ["G_MESSAGES_DEBUG"] = "uvr-ui"
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            os.environ["UVR_LOG_FILE"] = str(log_path)

            debug_log.debug("ui", "mirror test")

            self.assertEqual(emitted, ["mirror test"])
            self.assertEqual(
                log_path.read_text(encoding="utf-8"),
                "uvr-ui: mirror test\n",
            )

    def test_emit_integration_glib(self) -> None:
        os.environ["G_MESSAGES_DEBUG"] = "uvr"
        debug_log._DOMAINS = None
        debug_log._GMD_NORMALIZED = False
        glib_log.init()
        with _capture_fds() as captured:
            debug_log.debug("ui", "integration test")
        combined = captured[0] + captured[1]
        self.assertIn("uvr-ui-DEBUG", combined)
        self.assertIn("integration test", combined)


if __name__ == "__main__":
    unittest.main()
