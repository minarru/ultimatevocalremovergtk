import os
import sys
import tempfile
import threading
import unittest
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest import mock

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
        debug_log._LOG_FILE_DISABLED = False
        debug_log._LOG_FILE_ANNOUNCED = False
        debug_log._RUN_T0 = None
        debug_log._SEQ = 0
        debug_log._CONFIGURED_LEVEL = "errors"
        debug_log._INCLUDE_SENSITIVE = False
        debug_log._LEVEL_OVERRIDE = None
        debug_log._SENSITIVE_OVERRIDE = None
        debug_log._MAX_LOG_BYTES = 2 * 1024 * 1024
        debug_log._LOG_FILE_COUNT = 5
        glib_log.set_emit_hook(None)
        self._old_gmd = os.environ.pop("G_MESSAGES_DEBUG", None)
        self._old_log = os.environ.pop("UVR_LOG_FILE", None)
        self._old_verbose = os.environ.pop("UVR_VERBOSE", None)
        self._old_level = os.environ.pop("UVR_LOG_LEVEL", None)
        self._old_sensitive = os.environ.pop("UVR_DEBUG_SENSITIVE", None)

    def tearDown(self) -> None:
        debug_log._DOMAINS = None
        debug_log._GMD_NORMALIZED = False
        debug_log._LOG_FILE_PATH = None
        debug_log._LOG_FILE_DISABLED = False
        debug_log._LOG_FILE_ANNOUNCED = False
        debug_log._RUN_T0 = None
        debug_log._SEQ = 0
        debug_log._CONFIGURED_LEVEL = "errors"
        debug_log._INCLUDE_SENSITIVE = False
        debug_log._LEVEL_OVERRIDE = None
        debug_log._SENSITIVE_OVERRIDE = None
        debug_log._MAX_LOG_BYTES = 2 * 1024 * 1024
        debug_log._LOG_FILE_COUNT = 5
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
        if self._old_level is not None:
            os.environ["UVR_LOG_LEVEL"] = self._old_level
        else:
            os.environ.pop("UVR_LOG_LEVEL", None)
        if self._old_sensitive is not None:
            os.environ["UVR_DEBUG_SENSITIVE"] = self._old_sensitive
        else:
            os.environ.pop("UVR_DEBUG_SENSITIVE", None)

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

    def test_error_domain_does_not_enable_unrelated_debug_components(self) -> None:
        os.environ["G_MESSAGES_DEBUG"] = "uvr-error"

        self.assertTrue(debug_log.enabled("error"))
        self.assertFalse(debug_log.enabled("ui"))

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
            mirrored = log_path.read_text(encoding="utf-8")
            self.assertIn("level=DEBUG", mirrored)
            self.assertIn("component=ui", mirrored)
            self.assertIn("session=", mirrored)
            self.assertIn("message='mirror test'", mirrored)

    def test_configured_debug_level_emits_structured_operation_event(self) -> None:
        emitted: list[str] = []

        def _hook(_domain: str, message: str, _level: int) -> None:
            emitted.append(message)

        glib_log.set_emit_hook(_hook)
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="debug", log_file=str(log_path))

            debug_log.log_event(
                "worker",
                "job_started",
                operation_id="job-7",
                model="mdx:test",
            )

            self.assertEqual(len(emitted), 1)
            line = log_path.read_text(encoding="utf-8")
            self.assertIn("level=DEBUG", line)
            self.assertIn("component=worker", line)
            self.assertIn("session=", line)
            self.assertIn("operation=job-7", line)
            self.assertIn("event=job_started", line)
            self.assertIn("model='mdx:test'", line)

    def test_debug_level_suppresses_trace_until_trace_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="debug", log_file=str(log_path))
            debug_log.log_event("dispatch", "tick", level="trace", fraction=0.5)
            self.assertFalse(log_path.exists())

            debug_log.configure(level="trace", log_file=str(log_path))
            debug_log.log_event("dispatch", "tick", level="trace", fraction=0.5)
            self.assertIn("level=TRACE", log_path.read_text(encoding="utf-8"))

    def test_error_level_is_recorded_at_default_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="errors", log_file=str(log_path))

            debug_log.log_event(
                "audio",
                "write_failed",
                level="error",
                error="RuntimeError: boom",
            )

            line = log_path.read_text(encoding="utf-8")
            self.assertIn("level=ERROR", line)
            self.assertIn("event=write_failed", line)
            self.assertIn("error='RuntimeError: boom'", line)

    def test_warning_level_requires_debug_or_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="errors", log_file=str(log_path))

            debug_log.log_event(
                "settings",
                "recoverable_warning",
                level="warning",
                error="using defaults",
            )
            self.assertFalse(log_path.exists())

            debug_log.configure(level="debug", log_file=str(log_path))
            debug_log.log_event(
                "settings",
                "recoverable_warning",
                level="warning",
                error="using defaults",
            )
            self.assertIn(
                "event=recoverable_warning",
                log_path.read_text(encoding="utf-8"),
            )

    def test_bootstrap_records_settings_load_failures_before_settings_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "bootstrap.log"
            os.environ["UVR_LOG_FILE"] = str(log_path)

            debug_log.configure_bootstrap()
            debug_log.log_event(
                "settings",
                "settings_load_failed",
                level="error",
                error="corrupt",
            )

            diagnostic = log_path.read_text(encoding="utf-8")
            self.assertIn("event=settings_load_failed", diagnostic)
            self.assertEqual(debug_log.current_level(), "errors")

    def test_explicit_policy_overrides_environment_and_persisted_settings(self) -> None:
        from core.settings import Settings
        from core.types.settings_enums import DiagnosticLevel

        settings = Settings.defaults()
        settings.diagnostics.level = DiagnosticLevel.DEBUG
        settings.diagnostics.include_sensitive = False
        os.environ["UVR_LOG_LEVEL"] = "trace"
        os.environ["UVR_DEBUG_SENSITIVE"] = "1"

        debug_log.configure_from_settings(
            settings,
            level="errors",
            include_sensitive_details=False,
            log_file="",
        )

        self.assertEqual(debug_log.current_level(), "errors")
        self.assertFalse(debug_log.include_sensitive())

    def test_live_policy_update_preserves_active_log_destination_and_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "cli-override.log"
            debug_log.configure(
                level="debug",
                include_sensitive=False,
                log_file=str(log_path),
                max_bytes=321,
                file_count=2,
            )

            debug_log.update_policy(level="trace", include_sensitive=True)
            debug_log.log_event("ui", "policy_updated")

            self.assertEqual(debug_log.current_level(), "trace")
            self.assertTrue(debug_log.include_sensitive())
            self.assertEqual(debug_log._MAX_LOG_BYTES, 321)
            self.assertEqual(debug_log._LOG_FILE_COUNT, 2)
            self.assertIn(
                "event=policy_updated",
                log_path.read_text(encoding="utf-8"),
            )

    def test_live_policy_update_preserves_environment_overrides(self) -> None:
        from core.settings import Settings

        os.environ["UVR_LOG_LEVEL"] = "trace"
        os.environ["UVR_DEBUG_SENSITIVE"] = "1"
        debug_log.configure_from_settings(Settings.defaults(), log_file="")

        debug_log.update_policy(level="errors", include_sensitive=False)

        self.assertEqual(debug_log.current_level(), "trace")
        self.assertTrue(debug_log.include_sensitive())

    def test_sensitive_values_are_redacted_and_url_secrets_never_emit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hidden_path = Path(tmp) / "hidden.log"
            debug_log.configure(
                level="debug",
                include_sensitive=False,
                log_file=str(hidden_path),
            )
            debug_log.log_event(
                "download",
                "request",
                path="/home/alice/Music/private.wav",
                url="https://user:password@example.com/private/model?token=secret",
                authorization="Bearer never-log-this",
            )
            hidden = hidden_path.read_text(encoding="utf-8")
            self.assertNotIn("alice", hidden)
            self.assertNotIn("password", hidden)
            self.assertNotIn("secret", hidden)
            self.assertNotIn("never-log-this", hidden)
            self.assertIn("path='<path>'", hidden)
            self.assertIn("url='<url>'", hidden)
            self.assertIn("authorization='<redacted>'", hidden)

            visible_path = Path(tmp) / "visible.log"
            debug_log.configure(
                level="debug",
                include_sensitive=True,
                log_file=str(visible_path),
            )
            debug_log.log_event(
                "download",
                "request",
                path="/home/alice/Music/private.wav",
                url="https://user:password@example.com/private/model?token=secret",
            )
            visible = visible_path.read_text(encoding="utf-8")
            self.assertIn("/home/alice/Music/private.wav", visible)
            self.assertIn("https://example.com/private/model", visible)
            self.assertNotIn("user:password", visible)
            self.assertNotIn("token=secret", visible)

    def test_secrets_embedded_in_exception_text_are_always_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(
                level="errors",
                include_sensitive=True,
                log_file=str(log_path),
            )

            debug_log.log_event(
                "download",
                "request_failed",
                level="error",
                error=(
                    "Authorization: Bearer top-secret; "
                    "password=hunter2 api_key='private-key'"
                ),
            )

            diagnostic = log_path.read_text(encoding="utf-8")
            self.assertNotIn("top-secret", diagnostic)
            self.assertNotIn("hunter2", diagnostic)
            self.assertNotIn("private-key", diagnostic)
            self.assertIn("<redacted>", diagnostic)
            self.assertIn(diagnostic.rstrip()[-1], {"'", '"'})

    def test_common_credential_forms_are_redacted_from_errors_and_tracebacks(self) -> None:
        credential_text = (
            "Authorization: Basic dXNlcjpwYXNz "
            "access_token=abc123 client_secret=hunter2 "
            "Bearer standalone-secret"
        )
        for include_sensitive in (False, True):
            with self.subTest(include_sensitive=include_sensitive), tempfile.TemporaryDirectory() as tmp:
                log_path = Path(tmp) / "uvr.log"
                debug_log.configure(
                    level="errors",
                    include_sensitive=include_sensitive,
                    log_file=str(log_path),
                )

                debug_log.log_event(
                    "error",
                    "unhandled_exception",
                    level="error",
                    error=credential_text,
                    traceback=f"RuntimeError: {credential_text}",
                )

                diagnostic = log_path.read_text(encoding="utf-8")
                for secret in (
                    "dXNlcjpwYXNz",
                    "abc123",
                    "hunter2",
                    "standalone-secret",
                ):
                    self.assertNotIn(secret, diagnostic)

    def test_cookie_and_header_dumps_are_fully_redacted(self) -> None:
        credential_text = (
            "Cookie: session=abc; csrf=xyz\n"
            "headers={X-Custom: private-value, X-Trace: also-private}"
        )
        for include_sensitive in (False, True):
            with self.subTest(include_sensitive=include_sensitive), tempfile.TemporaryDirectory() as tmp:
                log_path = Path(tmp) / "uvr.log"
                debug_log.configure(
                    level="errors",
                    include_sensitive=include_sensitive,
                    log_file=str(log_path),
                )

                debug_log.log_event(
                    "error",
                    "request_failed",
                    level="error",
                    error=credential_text,
                    traceback=credential_text,
                )

                diagnostic = log_path.read_text(encoding="utf-8")
                for secret in (
                    "session=abc",
                    "csrf=xyz",
                    "private-value",
                    "also-private",
                ):
                    self.assertNotIn(secret, diagnostic)
                self.assertIn("Cookie: <redacted>", diagnostic)
                self.assertIn("headers=<redacted>", diagnostic)

    def test_quoted_mapping_header_dumps_are_redacted_idempotently(self) -> None:
        credential_texts = (
            "{'Cookie': 'session=abc', 'headers': {'X-Private': 'secret'}}",
            '{"Cookie": "session=xyz", "headers": {"X-Private": "hidden"}}',
            "{'headers': {'nested': {'first': 'hidden-one'}, "
            "'X-Private': 'hidden-two'}}",
            "{'headers': HeaderDump('constructor-one', 'constructor-two')}",
        )
        for include_sensitive in (False, True):
            with self.subTest(include_sensitive=include_sensitive), tempfile.TemporaryDirectory() as tmp:
                log_path = Path(tmp) / "uvr.log"
                debug_log.configure(
                    level="errors",
                    include_sensitive=include_sensitive,
                    log_file=str(log_path),
                )

                for credential_text in credential_texts:
                    sanitized = debug_log.redact_text(credential_text)
                    self.assertEqual(debug_log.redact_text(sanitized), sanitized)
                    debug_log.log_event(
                        "error",
                        "request_failed",
                        level="error",
                        error=credential_text,
                    )

                diagnostic = log_path.read_text(encoding="utf-8")
                for secret in (
                    "session=abc",
                    "secret",
                    "session=xyz",
                    "hidden",
                    "hidden-one",
                    "hidden-two",
                    "constructor-one",
                    "constructor-two",
                ):
                    self.assertNotIn(secret, diagnostic)

    def test_arbitrary_values_cannot_inject_lines_or_break_the_caller(self) -> None:
        class MultilineRepr:
            def __repr__(self) -> str:
                return "first line\nlevel=TRACE forged=true"

        class RaisingRepr:
            def __repr__(self) -> str:
                raise RuntimeError("repr failed")

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="errors", log_file=str(log_path))

            debug_log.log_event(
                "error",
                "untrusted_value",
                level="error",
                value=MultilineRepr(),
            )
            debug_log.log_event(
                "error",
                "unprintable_value",
                level="error",
                value=RaisingRepr(),
            )

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn(r"first line\nlevel=TRACE forged=true", lines[0])
            self.assertIn("event=unprintable_value", lines[1])
            self.assertIn("<unavailable>", lines[1])

    def test_relative_paths_are_hidden_unless_sensitive_details_are_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hidden_path = Path(tmp) / "hidden.log"
            debug_log.configure(level="errors", log_file=str(hidden_path))
            debug_log.log_event(
                "audio",
                "write_failed",
                level="error",
                error="could not open private/session/song.wav",
            )
            self.assertNotIn(
                "private/session/song.wav",
                hidden_path.read_text(encoding="utf-8"),
            )

            visible_path = Path(tmp) / "visible.log"
            debug_log.configure(
                level="errors",
                include_sensitive=True,
                log_file=str(visible_path),
            )
            debug_log.log_event(
                "audio",
                "write_failed",
                level="error",
                error="could not open private/session/song.wav",
            )
            self.assertIn(
                "private/session/song.wav",
                visible_path.read_text(encoding="utf-8"),
            )

    def test_cli_option_alternatives_are_not_mistaken_for_paths(self) -> None:
        self.assertEqual(
            debug_log.redact_text("required: inputs, -o/--output"),
            "required: inputs, -o/--output",
        )

    def test_non_path_slash_syntax_is_not_redacted(self) -> None:
        text = "ratio=1/2 algorithm=Max Spec/Min Spec device cpu/cuda"
        self.assertEqual(debug_log.redact_text(text), text)

    def test_contextual_extensionless_relative_paths_are_redacted(self) -> None:
        text = (
            "could not open 'models/checkpoints'; output directory outputs/stems; "
            "No such file or directory: 'private/cache'; "
            "could not open 'my models/checkpoints'; "
            'output directory "my outputs/stems"'
        )
        self.assertEqual(
            debug_log.redact_text(text),
            "could not open <path>; output directory <path>; "
            "No such file or directory: <path>; could not open <path>; "
            "output directory <path>",
        )

    def test_context_words_do_not_turn_known_slash_syntax_into_paths(self) -> None:
        text = (
            "output ratio=1/2 model cpu/cuda model cpu/cuda/mps "
            "output devices=cpu/cuda/mps output ratio=1/2/3"
        )
        self.assertEqual(debug_log.redact_text(text), text)

    def test_structured_values_cannot_inject_additional_log_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="errors", log_file=str(log_path))

            debug_log.log_event(
                "error",
                "failure",
                level="error",
                operation_id="job-1\nlevel=TRACE",
                error="first line\nsecond line\rthird line",
            )

            diagnostic = log_path.read_text(encoding="utf-8")
            self.assertEqual(len(diagnostic.splitlines()), 1)
            self.assertIn(r"job-1\nlevel=TRACE", diagnostic)
            self.assertIn(r"first line\\nsecond line\\rthird line", diagnostic)

    def test_rotating_file_keeps_configured_number_of_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(
                level="debug",
                log_file=str(log_path),
                max_bytes=180,
                file_count=3,
            )

            for index in range(20):
                debug_log.log_event("worker", "item", index=index, detail="x" * 40)

            self.assertTrue(log_path.exists())
            self.assertTrue(Path(f"{log_path}.1").exists())
            self.assertTrue(Path(f"{log_path}.2").exists())
            self.assertFalse(Path(f"{log_path}.3").exists())

    def test_diagnostic_files_are_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(
                level="debug",
                include_sensitive=True,
                log_file=str(log_path),
            )

            debug_log.log_event("ui", "private_details", path="/private/song.wav")

            self.assertEqual(log_path.stat().st_mode & 0o077, 0)

    def test_concurrent_writers_keep_one_complete_event_per_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="debug", log_file=str(log_path))

            def write_events(worker: int) -> None:
                for item in range(20):
                    debug_log.log_event(
                        "worker",
                        "concurrent_event",
                        worker=worker,
                        item=item,
                    )

            workers = [
                threading.Thread(target=write_events, args=(index,))
                for index in range(8)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=2)

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 160)
            self.assertTrue(all("event=concurrent_event" in line for line in lines))

    def test_file_write_failures_never_break_the_caller(self) -> None:
        debug_log.configure(level="errors", log_file="/unwritable/uvr.log")

        with mock.patch("core.debug_log.os.makedirs", side_effect=OSError("full")):
            debug_log.log_event(
                "error",
                "diagnostic_write_failed",
                level="error",
            )

    def test_runtime_hooks_capture_warnings_only_in_debug_and_exceptions_always(self) -> None:
        original_showwarning = warnings.showwarning
        original_excepthook = sys.excepthook
        original_thread_hook = threading.excepthook
        self.addCleanup(setattr, warnings, "showwarning", original_showwarning)
        self.addCleanup(setattr, sys, "excepthook", original_excepthook)
        self.addCleanup(setattr, threading, "excepthook", original_thread_hook)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            debug_log, "_ORIGINAL_SHOWWARNING"
        ), mock.patch.object(debug_log, "_ORIGINAL_EXCEPTHOOK"):
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="debug", log_file=str(log_path))
            debug_log.install_runtime_hooks()
            with warnings.catch_warnings():
                warnings.simplefilter("always")
                warnings.warn("diagnostic warning", RuntimeWarning, stacklevel=2)
            self.assertIn("event=python_warning", log_path.read_text(encoding="utf-8"))

            errors_path = Path(tmp) / "errors.log"
            debug_log.configure(level="errors", log_file=str(errors_path))
            sys.excepthook(RuntimeError, RuntimeError("uncaught boom"), None)
            text = errors_path.read_text(encoding="utf-8")
            self.assertIn("event=unhandled_exception", text)
            self.assertIn("uncaught boom", text)

    def test_gui_main_applies_persisted_diagnostics_before_running_app(self) -> None:
        from core.settings import Settings
        from core.types.settings_enums import DiagnosticLevel
        from ui import application

        settings = Settings.defaults()
        settings.diagnostics.level = DiagnosticLevel.TRACE
        settings.diagnostics.include_sensitive = True
        fake_app = mock.Mock()
        fake_app.run.return_value = 0
        fake_app._did_activate = True

        with mock.patch.object(application.Settings, "load", return_value=settings), mock.patch(
            "core.debug_log.configure_from_settings"
        ) as configure_from_settings, mock.patch(
            "core.debug_log.install_runtime_hooks"
        ) as install_runtime_hooks, mock.patch(
            "core.debug_log.log_event"
        ) as log_event, mock.patch.object(
            application, "UVRApplication", return_value=fake_app
        ), mock.patch(
            "ui.shutdown.finalize_process_exit"
        ):
            self.assertEqual(application.main(["uvr"]), 0)

        configure_from_settings.assert_called_once_with(settings)
        install_runtime_hooks.assert_called_once_with()
        names = [call.args[1] for call in log_event.call_args_list]
        self.assertEqual(names, ["application_started", "application_exited"])

    def test_gui_runtime_hooks_install_before_failure_prone_startup_work(self) -> None:
        from ui import application

        order: list[str] = []
        with mock.patch(
            "core.debug_log.configure_bootstrap",
            side_effect=lambda: order.append("bootstrap"),
        ), mock.patch(
            "core.debug_log.install_runtime_hooks",
            side_effect=lambda: order.append("hooks"),
        ), mock.patch(
            "core.torch_checkpoint.ensure_demucs_import_aliases",
            side_effect=lambda: (
                order.append("aliases"),
                (_ for _ in ()).throw(RuntimeError("alias setup failed")),
            )[1],
        ):
            with self.assertRaisesRegex(RuntimeError, "alias setup failed"):
                application.main(["uvr"])

        self.assertEqual(order, ["bootstrap", "hooks", "aliases"])

    def test_ui_error_log_records_error_at_default_threshold(self) -> None:
        from core.error_log import log_error

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="errors", log_file=str(log_path))

            log_error("Separation", RuntimeError("write failed"), context="saving")

            diagnostic = log_path.read_text(encoding="utf-8")
            self.assertIn("event=ui_error", diagnostic)
            self.assertIn("error_type='RuntimeError'", diagnostic)
            self.assertIn("write failed", diagnostic)

    def test_emit_integration_glib(self) -> None:
        os.environ["G_MESSAGES_DEBUG"] = "uvr"
        debug_log._DOMAINS = None
        debug_log._GMD_NORMALIZED = False
        glib_log.init()
        with _capture_fds() as captured:
            debug_log.debug("ui", "integration test")
        combined = captured[0] + captured[1]
        if not combined.strip():
            # GLib may route through journald / a custom writer (common on CI).
            self.skipTest("GLib did not write debug lines to stdout/stderr")
        self.assertIn("uvr-ui-DEBUG", combined)
        self.assertIn("integration test", combined)


if __name__ == "__main__":
    unittest.main()
