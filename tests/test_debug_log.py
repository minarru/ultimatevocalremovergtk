import os
from contextlib import contextmanager

import pytest

from core import debug_log, glib_log


@pytest.fixture(autouse=True)
def _reset_debug_env():
    debug_log._DOMAINS = None
    debug_log._GMD_NORMALIZED = False
    debug_log._LOG_FILE_PATH = None
    debug_log._LOG_FILE_ANNOUNCED = False
    debug_log._RUN_T0 = None
    debug_log._SEQ = 0
    glib_log.set_emit_hook(None)
    old_gmd = os.environ.pop("G_MESSAGES_DEBUG", None)
    old_log = os.environ.pop("UVR_LOG_FILE", None)
    yield
    debug_log._DOMAINS = None
    debug_log._GMD_NORMALIZED = False
    debug_log._LOG_FILE_PATH = None
    debug_log._LOG_FILE_ANNOUNCED = False
    debug_log._RUN_T0 = None
    debug_log._SEQ = 0
    glib_log.set_emit_hook(None)
    if old_gmd is not None:
        os.environ["G_MESSAGES_DEBUG"] = old_gmd
    else:
        os.environ.pop("G_MESSAGES_DEBUG", None)
    if old_log is not None:
        os.environ["UVR_LOG_FILE"] = old_log
    else:
        os.environ.pop("UVR_LOG_FILE", None)


def test_disabled_by_default():
    assert not debug_log.enabled("ui")


def test_uvr_enables_all_components():
    os.environ["G_MESSAGES_DEBUG"] = "uvr"
    assert debug_log.enabled("ui")
    assert debug_log.enabled("worker")
    assert debug_log.enabled("model")


def test_all_enables_everything():
    os.environ["G_MESSAGES_DEBUG"] = "all"
    assert debug_log.enabled("worker")


def test_component_filter_shorthand():
    os.environ["G_MESSAGES_DEBUG"] = "ui,dispatch"
    assert debug_log.enabled("ui")
    assert debug_log.enabled("dispatch")
    assert not debug_log.enabled("worker")


def test_component_filter_domain_names():
    os.environ["G_MESSAGES_DEBUG"] = "uvr-ui,uvr-worker"
    assert debug_log.enabled("ui")
    assert debug_log.enabled("worker")
    assert not debug_log.enabled("model")


def test_uvr_ui_does_not_enable_worker():
    os.environ["G_MESSAGES_DEBUG"] = "uvr-ui"
    assert debug_log.enabled("ui")
    assert not debug_log.enabled("worker")


def test_verbose_follows_console_domain():
    assert not debug_log.verbose()
    os.environ["G_MESSAGES_DEBUG"] = "uvr-console"
    debug_log._DOMAINS = None
    assert debug_log.verbose()
    os.environ["G_MESSAGES_DEBUG"] = "uvr-ui"
    debug_log._DOMAINS = None
    assert not debug_log.verbose()


def test_preview_text_truncates():
    assert debug_log.preview_text("a\nb" * 40).endswith("...")
    assert debug_log.preview_text("short") == "short"


def test_next_seq_resets_on_mark_run_start():
    debug_log.mark_run_start()
    assert debug_log.next_seq() == 1
    assert debug_log.next_seq() == 2
    debug_log.mark_run_start()
    assert debug_log.next_seq() == 1


def test_trace_phase_noop_when_disabled():
    with debug_log.trace_phase("separate", "demix", model="test"):
        pass


def test_trace_phase_logs_when_enabled():
    emitted: list[tuple[str, str]] = []

    def _hook(domain: str, message: str, _level: int) -> None:
        emitted.append((domain, message))

    glib_log.set_emit_hook(_hook)
    os.environ["G_MESSAGES_DEBUG"] = "uvr-separate"

    with debug_log.trace_phase("separate", "demix", model="m1"):
        pass

    messages = [msg for _domain, msg in emitted]
    assert any("phase=demix start" in msg for msg in messages)
    assert any("phase=demix done" in msg for msg in messages)


def test_debug_mirrors_to_log_file(tmp_path):
    emitted: list[str] = []

    def _hook(_domain: str, message: str, _level: int) -> None:
        emitted.append(message)

    glib_log.set_emit_hook(_hook)
    os.environ["G_MESSAGES_DEBUG"] = "uvr-ui"
    log_path = tmp_path / "uvr.log"
    os.environ["UVR_LOG_FILE"] = str(log_path)

    debug_log.debug("ui", "mirror test")

    assert emitted == ["mirror test"]
    assert log_path.read_text(encoding="utf-8") == "uvr-ui: mirror test\n"


def test_emit_integration_glib(capfd):
    os.environ["G_MESSAGES_DEBUG"] = "uvr"
    debug_log._DOMAINS = None
    debug_log._GMD_NORMALIZED = False
    glib_log.init()
    debug_log.debug("ui", "integration test")
    out, err = capfd.readouterr()
    combined = out + err
    assert "uvr-ui-DEBUG" in combined
    assert "integration test" in combined
