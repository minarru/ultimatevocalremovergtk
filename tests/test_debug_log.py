import os

import pytest

from uvr_core import debug_log


@pytest.fixture(autouse=True)
def _reset_debug_env():
    debug_log._ENABLED = None
    debug_log._FLAGS = set()
    debug_log._RUN_T0 = None
    old = os.environ.pop("UVR_DEBUG", None)
    yield
    debug_log._ENABLED = None
    debug_log._FLAGS = set()
    debug_log._RUN_T0 = None
    if old is not None:
        os.environ["UVR_DEBUG"] = old
    else:
        os.environ.pop("UVR_DEBUG", None)


def test_disabled_by_default():
    assert not debug_log.enabled("ui")


def test_all_flag():
    os.environ["UVR_DEBUG"] = "1"
    assert debug_log.enabled("ui")
    assert debug_log.enabled("worker")


def test_component_filter():
    os.environ["UVR_DEBUG"] = "ui,dispatch"
    assert debug_log.enabled("ui")
    assert debug_log.enabled("dispatch")
    assert not debug_log.enabled("worker")


def test_format_line_plain():
    line = debug_log.format_line(
        "worker",
        "console emit 'test'",
        wall="16:02:48",
        millis=729,
        run_delta=" run+0.042s",
        thread="KThread-1",
        colorize=False,
    )
    assert line == "[UVR 16:02:48.729 run+0.042s KThread-1] [worker] console emit 'test'"
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
    assert "console emit 'test'" in line
