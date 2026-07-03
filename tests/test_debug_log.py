import os
from contextlib import contextmanager

import pytest

from uvr_core import debug_log


@pytest.fixture(autouse=True)
def _reset_debug_env():
    debug_log._ENABLED = None
    debug_log._VERBOSE = None
    debug_log._FLAGS = set()
    debug_log._RUN_T0 = None
    debug_log._SEQ = 0
    old = os.environ.pop("UVR_DEBUG", None)
    old_verbose = os.environ.pop("UVR_DEBUG_VERBOSE", None)
    yield
    debug_log._ENABLED = None
    debug_log._VERBOSE = None
    debug_log._FLAGS = set()
    debug_log._RUN_T0 = None
    debug_log._SEQ = 0
    if old is not None:
        os.environ["UVR_DEBUG"] = old
    else:
        os.environ.pop("UVR_DEBUG", None)
    if old_verbose is not None:
        os.environ["UVR_DEBUG_VERBOSE"] = old_verbose
    else:
        os.environ.pop("UVR_DEBUG_VERBOSE", None)


def test_disabled_by_default():
    assert not debug_log.enabled("ui")


def test_all_flag():
    os.environ["UVR_DEBUG"] = "1"
    assert debug_log.enabled("ui")
    assert debug_log.enabled("worker")
    assert debug_log.enabled("model")


def test_component_filter():
    os.environ["UVR_DEBUG"] = "ui,dispatch"
    assert debug_log.enabled("ui")
    assert debug_log.enabled("dispatch")
    assert not debug_log.enabled("worker")


def test_verbose_flag():
    assert not debug_log.verbose()
    os.environ["UVR_DEBUG_VERBOSE"] = "1"
    debug_log._VERBOSE = None
    assert debug_log.verbose()


def test_preview_text_truncates():
    assert debug_log.preview_text("a\nb" * 40).endswith("...")
    assert debug_log.preview_text("short") == "short"


def test_format_line_plain():
    line = debug_log.format_line(
        "worker",
        "console emit 'test'",
        wall="16:02:48",
        millis=729,
        run_delta=" run+0.042s",
        thread="KThread-1",
        colorize=False,
        seq=7,
    )
    assert line == "[UVR #7 16:02:48.729 run+0.042s KThread-1] [worker] console emit 'test'"
    assert "\033[" not in line


def test_format_line_colored():
    line = debug_log.format_line(
        "worker",
        "console emit 'test'",
        wall="16:02:48",
        millis=729,
        run_delta=" run+0.042s",
        thread="KThread-1",
        colorize=True,
    )
    assert "\033[" in line
    assert "[worker]" in line


def test_next_seq_resets_on_mark_run_start():
    debug_log.mark_run_start()
    assert debug_log.next_seq() == 1
    assert debug_log.next_seq() == 2
    debug_log.mark_run_start()
    assert debug_log.next_seq() == 1


def test_trace_phase_noop_when_disabled():
    with debug_log.trace_phase("separate", "demix", model="test"):
        pass


def test_trace_phase_logs_when_enabled(capsys):
    os.environ["UVR_DEBUG"] = "separate"

    @contextmanager
    def _noop():
        yield

    with debug_log.trace_phase("separate", "demix", model="m1"):
        pass

    err = capsys.readouterr().err
    assert "phase=demix start" in err
    assert "phase=demix done" in err
