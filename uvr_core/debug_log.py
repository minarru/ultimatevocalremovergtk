"""Opt-in stderr logging for tracing UI/worker timing.

Enable with the ``UVR_DEBUG`` environment variable::

    UVR_DEBUG=1 python -m uvr_gtk
    UVR_DEBUG=ui,dispatch,worker,separate,cleanup python -m uvr_gtk

In fish, prefix with ``env`` (inline ``VAR=val cmd`` is bash-style)::

    env UVR_DEBUG=ui .venv/bin/python -m uvr_gtk

Logs are written to **stderr** and mirrored to a log file (plain text, no ANSI)::

    ~/.cache/uvr/debug.log

Override the file with ``UVR_DEBUG_LOG=/path/to/log``. If the app is already
running, a second launch exits immediately (GApplication single-instance) and
will not print to your terminal — use the log file or quit the existing
instance first.

A startup line is emitted when tracing is active; dialog timing lines appear
after you confirm Stop.

Recognised components: ``ui``, ``dispatch``, ``console``, ``worker``,
``separate``, ``cleanup``, ``model``, ``audio``, ``download``.
``1`` / ``all`` enables every component.

``UVR_DEBUG_VERBOSE=1`` enables chatty logs (every progress tick, scroll
viewport detail). When stderr is a TTY, lines are colorized per component.
Set ``NO_COLOR=1`` or ``UVR_DEBUG_NOCOLOR=1`` to disable ANSI codes.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

_ENABLED: Optional[bool] = None
_VERBOSE: Optional[bool] = None
_FLAGS: set[str] = set()
_LOG_FILE_PATH: Optional[str] = None
_LOG_FILE_ANNOUNCED = False
_RUN_T0: Optional[float] = None
_SEQ: int = 0
_TLS = threading.local()

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
    "model": "\033[96m",  # bright cyan
    "audio": "\033[95m",  # bright magenta
    "download": "\033[94m",  # bright blue
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


def verbose() -> bool:
    global _VERBOSE
    if _VERBOSE is None:
        raw = os.environ.get("UVR_DEBUG_VERBOSE", "").strip().lower()
        _VERBOSE = raw in {"1", "true", "yes", "on"}
    return _VERBOSE


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


def preview_text(text: str, max_len: int = 72) -> str:
    preview = text.replace("\n", "\\n")
    if len(preview) > max_len:
        return preview[: max_len - 3] + "..."
    return preview


def format_ctx(**ctx: object) -> str:
    parts = []
    for key, value in ctx.items():
        if value is None:
            continue
        parts.append(f"{key}={value!r}")
    return " ".join(parts)


def format_line(
    component: str,
    message: str,
    *,
    wall: str,
    millis: int,
    run_delta: str,
    thread: str,
    colorize: bool,
    seq: Optional[int] = None,
) -> str:
    prefix = f"#{seq} " if seq is not None else ""
    meta = _paint(_DIM, f"[UVR {prefix}{wall}.{millis:03d}", colorize=colorize)
    if run_delta:
        meta += _paint(_BOLD + _RUN_DELTA, run_delta, colorize=colorize)
    meta += _paint(_DIM, f" {thread}]", colorize=colorize)

    comp_color = _COMPONENT_COLORS.get(component.lower(), _DEFAULT_COMPONENT)
    tag = _paint(_BOLD + comp_color, f" [{component}]", colorize=colorize)
    body = _paint(comp_color, f" {message}", colorize=colorize)
    return f"{meta}{tag}{body}"


def _log_file_path() -> Optional[str]:
    if _ENABLED is None:
        _parse_env()
    if not _ENABLED:
        return None
    global _LOG_FILE_PATH
    if _LOG_FILE_PATH is not None:
        return _LOG_FILE_PATH
    explicit = os.environ.get("UVR_DEBUG_LOG", "").strip()
    if explicit:
        path = explicit
    else:
        cache = os.environ.get(
            "XDG_CACHE_HOME",
            os.path.join(os.path.expanduser("~"), ".cache"),
        )
        path = os.path.join(cache, "uvr", "debug.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _LOG_FILE_PATH = path
    return path


def announce_log_file() -> None:
    """Print the debug log path once (stderr) when tracing is enabled."""
    global _LOG_FILE_ANNOUNCED
    if _LOG_FILE_ANNOUNCED or not enabled():
        return
    path = _log_file_path()
    if path is None:
        return
    _LOG_FILE_ANNOUNCED = True
    print(f"UVR debug log: {path}", file=sys.stderr, flush=True)


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
    global _RUN_T0, _SEQ
    _RUN_T0 = time.monotonic()
    _SEQ = 0


def clear_run_start() -> None:
    global _RUN_T0
    _RUN_T0 = None


def next_seq() -> int:
    """Return the next per-run correlation sequence number."""
    global _SEQ
    _SEQ += 1
    return _SEQ


def set_correlation_seq(seq: int) -> None:
    _TLS.seq = seq


def correlation_seq() -> Optional[int]:
    return getattr(_TLS, "seq", None)


def debug(component: str, message: str, *, seq: Optional[int] = None) -> None:
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
        seq=seq,
    )
    plain = format_line(
        component,
        message,
        wall=wall,
        millis=millis,
        run_delta=run_delta,
        thread=thread,
        colorize=False,
        seq=seq,
    )
    print(line, file=sys.stderr, flush=True)
    path = _log_file_path()
    if path is not None:
        try:
            with open(path, "a", encoding="utf-8") as log_file:
                log_file.write(plain + "\n")
        except OSError:
            pass


def debug_elapsed(component: str, label: str, started: float, **ctx: object) -> None:
    elapsed = time.perf_counter() - started
    suffix = f" {format_ctx(**ctx)}" if ctx else ""
    debug(component, f"{label} elapsed={elapsed:.3f}s{suffix}")


@contextmanager
def trace_phase(component: str, phase: str, **ctx: object) -> Iterator[None]:
    """Log phase entry, exit elapsed time, and exceptions when debug is enabled."""
    if not enabled(component):
        yield
        return
    started = time.perf_counter()
    suffix = f" {format_ctx(**ctx)}" if ctx else ""
    debug(component, f"phase={phase} start{suffix}")
    try:
        yield
    except Exception as exc:
        debug(component, f"phase={phase} error={type(exc).__name__}: {exc}")
        raise
    else:
        debug_elapsed(component, f"phase={phase} done", started, **ctx)
