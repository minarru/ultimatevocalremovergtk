"""Opt-in GLib debug logging for tracing UI/worker timing.

Enable with ``G_MESSAGES_DEBUG`` (standard GNOME debug switch)::

    G_MESSAGES_DEBUG=uvr python -m ui
    G_MESSAGES_DEBUG=uvr-ui,uvr-worker python -m ui

In fish, prefix with ``env`` (inline ``VAR=val cmd`` is bash-style)::

    env G_MESSAGES_DEBUG=uvr-ui python -m ui

Optional plain-text mirror (independent of ``G_MESSAGES_DEBUG``)::

    UVR_LOG_FILE=/path/to/log python -m ui

Recognised components map to GLib domains ``uvr-{component}``:

``ui``, ``dispatch``, ``trace``, ``worker``, ``separate``, ``cleanup``,
``model``, ``audio``, ``download``, ``error``, ``settings``.

Parsing rules for ``G_MESSAGES_DEBUG``:

- ``all`` — every component
- ``uvr`` — all ``uvr-*`` components (UVR-specific convenience)
- ``uvr-ui uvr-worker`` — selective domains (GLib uses spaces; commas are accepted)
- ``ui`` — shorthand for ``uvr-ui`` (same for other component names)

High-frequency internals (every progress tick, worker pause polls, per-console
chunk emit) use :func:`verbose`, enabled by ``uvr-trace`` or ``UVR_VERBOSE=1``.

Suggested profiles::

    # General app debugging
    G_MESSAGES_DEBUG=uvr-ui,uvr-settings,uvr-error

    # Separation run debugging
    G_MESSAGES_DEBUG=uvr-ui,uvr-worker,uvr-dispatch,uvr-separate,uvr-model,uvr-error

    # High-frequency internals (or UVR_VERBOSE=1)
    G_MESSAGES_DEBUG=uvr-trace

    # Full internal trace
    G_MESSAGES_DEBUG=uvr

If the app is already running, a second launch exits immediately
(GApplication single-instance) and will not print to your terminal — use
``journalctl --user -f`` or ``UVR_LOG_FILE`` + ``tail -f``.

UVR shorthands in ``G_MESSAGES_DEBUG`` are expanded to GLib domain names
before GTK loads; set the variable before launch (``run_uvr.sh`` does this
automatically).

Application code should use :func:`debug` for opt-in tracing. Standard-library
``logging.getLogger`` is not wired to ``G_MESSAGES_DEBUG``; use :func:`debug`
instead of ``logger.debug`` in UVR modules.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

from . import glib_log

_COMPONENTS = frozenset(
    {
        "ui",
        "dispatch",
        "trace",
        "worker",
        "separate",
        "cleanup",
        "model",
        "audio",
        "download",
        "error",
        "settings",
    }
)

_DOMAINS: Optional[set[str]] = None
_LOG_FILE_PATH: Optional[str] = None
_LOG_FILE_ANNOUNCED = False
_RUN_T0: Optional[float] = None
_SEQ: int = 0
_TLS = threading.local()
_GMD_NORMALIZED = False


def _log_domain(component: str) -> str:
    return f"uvr-{component.lower()}"


def _all_uvr_domains() -> tuple[str, ...]:
    domains = tuple(_log_domain(component) for component in sorted(_COMPONENTS))
    return domains + ("uvr",)


def normalize_g_messages_debug_env() -> None:
    """Expand UVR shorthands in ``G_MESSAGES_DEBUG`` for GLib's domain filter."""
    global _GMD_NORMALIZED, _DOMAINS
    if _GMD_NORMALIZED:
        return
    _GMD_NORMALIZED = True
    _DOMAINS = None

    raw = os.environ.get("G_MESSAGES_DEBUG", "").strip()
    if not raw:
        return

    expanded: list[str] = []
    for token in raw.replace(" ", ",").split(","):
        token = token.strip()
        if not token:
            continue
        lower = token.lower()
        if lower == "all":
            expanded.append("all")
        elif lower == "uvr":
            expanded.extend(_all_uvr_domains())
        elif lower in _COMPONENTS:
            expanded.append(_log_domain(lower))
        else:
            expanded.append(token)

    seen: set[str] = set()
    unique: list[str] = []
    for domain in expanded:
        if domain not in seen:
            seen.add(domain)
            unique.append(domain)
    os.environ["G_MESSAGES_DEBUG"] = " ".join(unique)


def _parse_g_messages_debug() -> set[str]:
    normalize_g_messages_debug_env()
    raw = os.environ.get("G_MESSAGES_DEBUG", "").strip()
    if not raw:
        return set()
    parts = set()
    for token in raw.replace(" ", ",").split(","):
        token = token.strip().lower()
        if token:
            parts.add(token)
    return parts


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


def _domains() -> set[str]:
    global _DOMAINS
    if _DOMAINS is None:
        _DOMAINS = _parse_g_messages_debug()
    return _DOMAINS


def verbose() -> bool:
    flag = os.environ.get("UVR_VERBOSE", "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    return enabled("trace")


def _log_file_path() -> Optional[str]:
    explicit = os.environ.get("UVR_LOG_FILE", "").strip()
    if not explicit:
        return None
    global _LOG_FILE_PATH
    if _LOG_FILE_PATH is not None:
        return _LOG_FILE_PATH
    parent = os.path.dirname(explicit)
    if parent:
        os.makedirs(parent, exist_ok=True)
    _LOG_FILE_PATH = explicit
    return explicit


def announce_log_file() -> None:
    """Emit one MESSAGE when ``UVR_LOG_FILE`` is configured."""
    global _LOG_FILE_ANNOUNCED
    if _LOG_FILE_ANNOUNCED:
        return
    path = _log_file_path()
    if path is None:
        return
    _LOG_FILE_ANNOUNCED = True
    glib_log.emit("uvr", f"debug log file: {path}", level="message")


def enabled(component: str = "") -> bool:
    domains = _domains()
    if not domains:
        return False
    if "all" in domains:
        return True
    if "uvr" in domains:
        return True
    if not component:
        return bool(domains & ({"uvr", "all"} | {_log_domain(c) for c in _COMPONENTS}))
    comp = component.lower()
    if comp in domains:
        return True
    return _log_domain(comp) in domains


def mark_run_start() -> None:
    """Reset the per-run correlation sequence (call when processing starts)."""
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


def _mirror_file(message: str) -> None:
    path = _log_file_path()
    if path is None:
        return
    try:
        with open(path, "a", encoding="utf-8") as log_file:
            log_file.write(message + "\n")
    except OSError:
        pass


def debug(component: str, message: str, *, seq: Optional[int] = None) -> None:
    if not enabled(component):
        return
    if seq is not None:
        message = f"#{seq} {message}"
    domain = _log_domain(component)
    glib_log.emit(domain, message)
    _mirror_file(f"{domain}: {message}")


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
