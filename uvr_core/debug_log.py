"""Opt-in stderr logging for tracing UI/worker timing.

Enable with the ``UVR_DEBUG`` environment variable::

    UVR_DEBUG=1 python __main__.py
    UVR_DEBUG=ui,dispatch,worker,separate python __main__.py

Recognised components: ``ui``, ``dispatch``, ``console``, ``worker``,
``separate``, ``cleanup``. ``1`` / ``all`` enables every component.

When stderr is a TTY, lines are colorized per component. Set ``NO_COLOR=1`` or
``UVR_DEBUG_NOCOLOR=1`` to disable ANSI codes. Set ``UVR_DEBUG_COLOR=1`` to
force color even when stderr is not a TTY.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Optional

_ENABLED: Optional[bool] = None
_FLAGS: set[str] = set()
_RUN_T0: Optional[float] = None

_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RUN_DELTA = "\033[93m"  # bright yellow
_COMPONENT_COLORS = {
    "ui": "\033[36m",  # cyan
    "dispatch": "\033[33m",  # yellow
    "console": "\033[32m",  # green
    "worker": "\033[35m",  # magenta
    "separate": "\033[34m",  # blue
    "cleanup": "\033[31m",  # red
}
_DEFAULT_COMPONENT = "\033[37m"  # white


def _parse_env() -> None:
    global _ENABLED, _FLAGS
    raw = os.environ.get("UVR_DEBUG", "").strip().lower()
    if not raw or raw in {"0", "false", "no", "off"}:
        _ENABLED = False
        _FLAGS = set()
        return
    _ENABLED = True
    if raw in {"1", "true", "yes", "on", "all"}:
        _FLAGS = {"all"}
        return
    _FLAGS = {part.strip() for part in raw.split(",") if part.strip()}
    if "all" in _FLAGS:
        _FLAGS = {"all"}


def _use_color() -> bool:
    if os.environ.get("NO_COLOR") or os.environ.get("UVR_DEBUG_NOCOLOR") == "1":
        return False
    if os.environ.get("UVR_DEBUG_COLOR") == "1":
        return True
    try:
        return sys.stderr.isatty()
    except Exception:  # noqa: BLE001 - best-effort TTY detection
        return False


def _paint(code: str, text: str, *, colorize: bool) -> str:
    if not colorize:
        return text
    return f"{code}{text}{_RESET}"


def format_line(
    component: str,
    message: str,
    *,
    wall: str,
    millis: int,
    run_delta: str,
    thread: str,
    colorize: bool,
) -> str:
    meta = _paint(_DIM, f"[UVR {wall}.{millis:03d}", colorize=colorize)
    if run_delta:
        meta += _paint(_BOLD + _RUN_DELTA, run_delta, colorize=colorize)
    meta += _paint(_DIM, f" {thread}]", colorize=colorize)

    comp_color = _COMPONENT_COLORS.get(component.lower(), _DEFAULT_COMPONENT)
    tag = _paint(_BOLD + comp_color, f" [{component}]", colorize=colorize)
    body = _paint(comp_color, f" {message}", colorize=colorize)
    return f"{meta}{tag}{body}"


def enabled(component: str = "") -> bool:
    if _ENABLED is None:
        _parse_env()
    if not _ENABLED:
        return False
    if not component or "all" in _FLAGS:
        return True
    return component.lower() in _FLAGS


def mark_run_start() -> None:
    """Reset the per-run monotonic clock (call when the user starts processing)."""
    global _RUN_T0
    _RUN_T0 = time.monotonic()


def clear_run_start() -> None:
    global _RUN_T0
    _RUN_T0 = None


def debug(component: str, message: str) -> None:
    if not enabled(component):
        return
    now = time.monotonic()
    wall = time.strftime("%H:%M:%S")
    millis = int(time.time() * 1000) % 1000
    thread = threading.current_thread().name
    run_delta = ""
    if _RUN_T0 is not None:
        run_delta = f" run+{now - _RUN_T0:.3f}s"
    line = format_line(
        component,
        message,
        wall=wall,
        millis=millis,
        run_delta=run_delta,
        thread=thread,
        colorize=_use_color(),
    )
    print(line, file=sys.stderr, flush=True)
