"""Structured, privacy-aware diagnostics shared by the GTK and CLI frontends.

The application always keeps a small rotating error log. Preferences and CLI
flags can raise the level to Debug or Trace; the legacy GLib-domain switches
below remain supported for focused development sessions.

Enable with ``G_MESSAGES_DEBUG`` (standard GNOME debug switch)::

    G_MESSAGES_DEBUG=uvr python -m ui
    G_MESSAGES_DEBUG=uvr-ui,uvr-worker python -m ui

In fish, prefix with ``env`` (inline ``VAR=val cmd`` is bash-style)::

    env G_MESSAGES_DEBUG=uvr-ui python -m ui

Override the rotating cache log destination::

    UVR_LOG_FILE=/path/to/log python -m ui

Recognised components map to GLib domains ``uvr-{component}``:

``ui``, ``cli``, ``dispatch``, ``trace``, ``worker``, ``separate``,
``cleanup``, ``model``, ``audio``, ``download``, ``ensemble``, ``cache``,
``error``, ``settings``.

Parsing rules for ``G_MESSAGES_DEBUG``:

- ``all`` — every component
- ``uvr`` — all ``uvr-*`` components (UVR-specific convenience)
- ``uvr-ui uvr-worker`` — selective domains (GLib uses spaces; commas are accepted)
- ``ui`` — shorthand for ``uvr-ui`` (same for other component names)

High-frequency internals (sampled progress, worker pause polls, per-console chunk
emit) use :func:`verbose`, enabled by ``uvr-trace`` or ``UVR_VERBOSE=1``.

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

Application code should use :func:`log_event` for named lifecycle boundaries;
:func:`debug` remains the compatibility helper for existing free-form events.
Standard-library ``logging.getLogger`` is not wired into this pipeline.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
import traceback as traceback_module
import uuid
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from types import TracebackType
from typing import Iterator, Optional, TextIO
from urllib.parse import urlsplit, urlunsplit

from . import glib_log

_COMPONENTS = frozenset(
    {
        "cache",
        "cli",
        "ui",
        "dispatch",
        "trace",
        "worker",
        "separate",
        "cleanup",
        "model",
        "audio",
        "download",
        "ensemble",
        "error",
        "settings",
    }
)

_DOMAINS: Optional[set[str]] = None
_LOG_FILE_PATH: Optional[str] = None
_LOG_FILE_DISABLED = False
_LOG_FILE_ANNOUNCED = False
_RUN_T0: Optional[float] = None
_SEQ: int = 0
_TLS = threading.local()
_GMD_NORMALIZED = False
_CONFIGURED_LEVEL = "errors"
_INCLUDE_SENSITIVE = False
_LEVEL_OVERRIDE: Optional[str] = None
_SENSITIVE_OVERRIDE: Optional[bool] = None
_MAX_LOG_BYTES = 2 * 1024 * 1024
_LOG_FILE_COUNT = 5
_SESSION_ID = uuid.uuid4().hex[:12]
_WRITE_LOCK = threading.RLock()
_RUNTIME_HOOKS_INSTALLED = False
_ORIGINAL_SHOWWARNING = warnings.showwarning
_ORIGINAL_EXCEPTHOOK = sys.excepthook
_ORIGINAL_THREAD_EXCEPTHOOK = threading.excepthook

_LEVEL_RANK = {"trace": 10, "debug": 20, "warning": 30, "error": 40}
_HARD_REDACT_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "credentials",
        "headers",
        "password",
        "secret",
        "token",
    }
)
_OMIT_VALUE_KEYS = frozenset(
    {"array", "audio", "samples", "tensor", "waveform", "weights"}
)
_URL_RE = re.compile(r"https?://[^\s'\"]+", re.IGNORECASE)
_UNIX_PATH_RE = re.compile(r"(?<![\w:])/(?:[^\s'\"]+/)*[^\s'\"]+")
_WINDOWS_PATH_RE = re.compile(r"(?<!\w)[A-Za-z]:\\(?:[^\s'\"]+\\)*[^\s'\"]+")
_RELATIVE_PATH_RE = re.compile(
    r"(?<![\w:-])(?!-)(?:"
    r"(?:~|\.\.?)/(?:[^\s'\"/]+/)*[^\s'\"]+|"
    r"(?:[^\s'\"/]+/){2,}[^\s'\"]+|"
    r"(?:[^\s'\"/]+/)+[^\s'\"/]+\.[A-Za-z0-9]{1,12}"
    r")"
)
_RELATIVE_WINDOWS_PATH_RE = re.compile(
    r"(?<![\w:])(?:[^\s'\"\\]+\\)+[^\s'\"\\]+\.[A-Za-z0-9]{1,12}"
)
_CONTEXTUAL_RELATIVE_PATH_RE = re.compile(
    r"(?P<prefix>\b(?:open|read|write|load|save|path|file|folder|directory|dir|"
    r"input|output|cache|model)\b"
    r"(?:\s+(?:path|file|folder|directory|dir))?\s*(?:[:=]\s*|\s+))"
    r"(?:"
    r"(?P<quote>[\"'])(?P<quoted_path>(?!-)[^\r\n/]+/[^\r\n]+?)(?P=quote)|"
    r"(?P<path>(?!-)(?:[^\s'\"/;,\[\](){}]+/)+"
    r"[^\s'\"/;,\[\](){}]+)"
    r")",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?P<key>access[-_]?token|refresh[-_]?token|client[-_]?secret|"
    r"api[-_ ]?key|authorization|credentials?|password|secret|token)"
    r"\b[\"']?(?P<separator>\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|(?:(?:bearer|basic)\s+)?[^\\\s,;'\";}\]]+)",
    re.IGNORECASE,
)
_AUTH_SCHEME_RE = re.compile(
    r"\b(?P<scheme>bearer|basic)\s+[^\s,;'\";}\]]+",
    re.IGNORECASE,
)
_QUOTED_MAPPING_SECRET_KEY_RE = re.compile(
    r"(?P<quote>[\"'])(?P<key>set-cookie|cookie|request[-_ ]?headers?|"
    r"response[-_ ]?headers?|headers?)(?P=quote)"
    r"(?P<separator>\s*:\s*)",
    re.IGNORECASE,
)
_COOKIE_HEADER_RE = re.compile(
    r"\b(?P<key>set-cookie|cookie)(?P<separator>\s*:\s*)"
    r"[^\r\n]*?(?=\\[nr]|\r?$|$)",
    re.IGNORECASE | re.MULTILINE,
)
_COOKIE_ASSIGNMENT_RE = re.compile(
    r"\b(?P<key>cookie)(?P<separator>\s*=\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\\\s,;'\";}\]]+)",
    re.IGNORECASE,
)
_HEADER_DUMP_RE = re.compile(
    r"\b(?P<key>request[-_ ]?headers?|response[-_ ]?headers?|headers?)"
    r"(?P<separator>\s*[:=]\s*)"
    r"(?:\{[^}\r\n]*\}|\[[^\]\r\n]*\]|\([^\)\r\n]*\)|[^\r\n]*?(?=\\[nr]|\r?$|$))",
    re.IGNORECASE | re.MULTILINE,
)


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
        parts.append(f"{key}={_safe_field_repr(key, value)}")
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
    return _CONFIGURED_LEVEL == "trace" or _domain_enabled("trace")


def current_level() -> str:
    return _CONFIGURED_LEVEL


def include_sensitive() -> bool:
    return _INCLUDE_SENSITIVE


def session_id() -> str:
    return _SESSION_ID


def new_operation_id(prefix: str = "operation") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def set_operation_id(operation_id: Optional[str]) -> None:
    _TLS.operation_id = operation_id


def current_operation_id() -> Optional[str]:
    return getattr(_TLS, "operation_id", None)


def _default_log_file() -> str:
    from .paths import CACHE_DIR

    return os.path.join(CACHE_DIR, "logs", "uvr.log")


def configure(
    *,
    level: str = "errors",
    include_sensitive: bool = False,
    log_file: Optional[str] = None,
    max_bytes: int = 2 * 1024 * 1024,
    file_count: int = 5,
) -> None:
    """Apply process-wide diagnostic policy without requiring a restart.

    ``log_file=None`` selects the built-in cache log. An empty string disables
    the file mirror, which is useful for embedded callers and tests.
    """
    normalized = _normalize_level(level)
    global _CONFIGURED_LEVEL, _INCLUDE_SENSITIVE
    global _LEVEL_OVERRIDE, _SENSITIVE_OVERRIDE
    global _LOG_FILE_PATH, _LOG_FILE_DISABLED, _LOG_FILE_ANNOUNCED
    global _MAX_LOG_BYTES, _LOG_FILE_COUNT
    _CONFIGURED_LEVEL = normalized
    _INCLUDE_SENSITIVE = bool(include_sensitive)
    _LEVEL_OVERRIDE = None
    _SENSITIVE_OVERRIDE = None
    _LOG_FILE_DISABLED = log_file == ""
    _LOG_FILE_PATH = None if _LOG_FILE_DISABLED else (log_file or _default_log_file())
    _LOG_FILE_ANNOUNCED = False
    _MAX_LOG_BYTES = max(1, int(max_bytes))
    _LOG_FILE_COUNT = max(1, int(file_count))


def update_policy(*, level: str, include_sensitive: bool) -> None:
    """Apply live level/privacy changes without replacing the log sink.

    Preferences can be changed while a GUI launched by the CLI is running.
    Keeping the active destination and rotation values preserves any
    ``--log-file`` or embedding override for the rest of that process.
    """
    global _CONFIGURED_LEVEL, _INCLUDE_SENSITIVE
    _CONFIGURED_LEVEL = _LEVEL_OVERRIDE or _normalize_level(level)
    _INCLUDE_SENSITIVE = (
        _SENSITIVE_OVERRIDE
        if _SENSITIVE_OVERRIDE is not None
        else bool(include_sensitive)
    )


def _normalize_level(level: object) -> str:
    normalized = str(getattr(level, "value", level) or "errors").strip().lower()
    return normalized if normalized in {"errors", "debug", "trace"} else "errors"


def _remember_policy_overrides(
    *,
    level: Optional[str],
    include_sensitive_details: Optional[bool],
) -> None:
    global _LEVEL_OVERRIDE, _SENSITIVE_OVERRIDE
    _LEVEL_OVERRIDE = _normalize_level(level) if level is not None else None
    _SENSITIVE_OVERRIDE = (
        bool(include_sensitive_details)
        if include_sensitive_details is not None
        else None
    )


def configure_bootstrap() -> None:
    """Enable safe diagnostics before persisted settings can be loaded."""
    env_level = os.environ.get("UVR_LOG_LEVEL", "").strip().lower()
    if os.environ.get("UVR_VERBOSE", "").strip().lower() in {"1", "true", "yes"}:
        env_level = "trace"
    env_sensitive = os.environ.get("UVR_DEBUG_SENSITIVE", "").strip().lower()
    level_override = env_level or None
    sensitive_override = (
        env_sensitive in {"1", "true", "yes"} if env_sensitive else None
    )
    configure(
        level=level_override or "errors",
        include_sensitive=bool(sensitive_override),
        log_file=os.environ.get("UVR_LOG_FILE") or None,
    )
    _remember_policy_overrides(
        level=level_override,
        include_sensitive_details=sensitive_override,
    )


def configure_from_settings(
    settings: object,
    *,
    level: Optional[str] = None,
    include_sensitive_details: Optional[bool] = None,
    log_file: Optional[str] = None,
) -> None:
    """Resolve persisted diagnostics with environment/CLI overrides."""
    diagnostics = getattr(settings, "diagnostics", None)
    stored_level = getattr(diagnostics, "level", "errors")
    stored_sensitive = bool(getattr(diagnostics, "include_sensitive", False))
    env_level = os.environ.get("UVR_LOG_LEVEL", "").strip().lower()
    if os.environ.get("UVR_VERBOSE", "").strip().lower() in {"1", "true", "yes"}:
        env_level = "trace"
    level_override = level if level is not None else (env_level or None)
    resolved_level = level_override or str(getattr(stored_level, "value", stored_level))
    env_sensitive = os.environ.get("UVR_DEBUG_SENSITIVE", "").strip().lower()
    if include_sensitive_details is not None:
        sensitive_override = include_sensitive_details
        resolved_sensitive = include_sensitive_details
    elif env_sensitive:
        sensitive_override = env_sensitive in {"1", "true", "yes"}
        resolved_sensitive = sensitive_override
    else:
        sensitive_override = None
        resolved_sensitive = stored_sensitive
    resolved_log_file = log_file
    if resolved_log_file is None:
        resolved_log_file = os.environ.get("UVR_LOG_FILE") or None
    configure(
        level=resolved_level,
        include_sensitive=resolved_sensitive,
        log_file=resolved_log_file,
    )
    _remember_policy_overrides(
        level=level_override,
        include_sensitive_details=sensitive_override,
    )


def _log_file_path() -> Optional[str]:
    if _LOG_FILE_DISABLED:
        return None
    explicit = os.environ.get("UVR_LOG_FILE", "").strip()
    global _LOG_FILE_PATH
    if _LOG_FILE_PATH is not None:
        return _LOG_FILE_PATH
    if not explicit:
        return None
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
    shown = path if _INCLUDE_SENSITIVE else "<path>"
    glib_log.emit("uvr", f"diagnostic log file: {shown}", level="message")


def enabled(component: str = "") -> bool:
    comp = component.lower()
    if comp == "trace":
        return verbose()
    if _CONFIGURED_LEVEL in {"debug", "trace"}:
        return True
    return _domain_enabled(component)


def _domain_enabled(component: str = "") -> bool:
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
    payload = (message + "\n").encode("utf-8", errors="replace")
    try:
        with _WRITE_LOCK:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            try:
                current_size = os.path.getsize(path)
            except OSError:
                current_size = 0
            if current_size and current_size + len(payload) > _MAX_LOG_BYTES:
                _rotate_log_files(path)
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            try:
                os.fchmod(descriptor, 0o600)
            except OSError:
                pass
            with os.fdopen(descriptor, "ab") as log_file:
                log_file.write(payload)
    except OSError:
        pass


def _rotate_log_files(path: str) -> None:
    if _LOG_FILE_COUNT <= 1:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    for index in range(_LOG_FILE_COUNT - 1, 0, -1):
        source = path if index == 1 else f"{path}.{index - 1}"
        target = f"{path}.{index}"
        if not os.path.exists(source):
            continue
        try:
            os.replace(source, target)
        except OSError:
            pass


def _sanitize_url(value: str, *, reveal_path: bool) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "<url>"
    if not reveal_path:
        return "<url>"
    hostname = parsed.hostname or ""
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        port = ""
    return urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path, "", ""))


def _mapping_value_end(text: str, start: int) -> int:
    """Find the end of a simple quoted-mapping value without evaluating it."""
    if start >= len(text):
        return start

    opener = text[start]
    if opener in "\"'":
        escaped = False
        for index in range(start + 1, len(text)):
            character = text[index]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == opener:
                return index + 1
            elif character in "\r\n":
                return index
        return len(text)

    closers = {"{": "}", "[": "]", "(": ")"}
    stack: list[str] = []
    quote = ""
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in "\"'":
            quote = character
        elif character in closers:
            stack.append(closers[character])
        elif stack and character == stack[-1]:
            stack.pop()
            if not stack:
                return index + 1
        elif not stack and character in ",}]\r\n":
            return index
    return len(text)


def _redact_quoted_mapping_secrets(text: str) -> str:
    result: list[str] = []
    cursor = 0
    while match := _QUOTED_MAPPING_SECRET_KEY_RE.search(text, cursor):
        result.append(text[cursor : match.end()])
        value_end = _mapping_value_end(text, match.end())
        result.append("<redacted>")
        cursor = max(value_end, match.end())
    result.append(text[cursor:])
    return "".join(result)


def _redact_contextual_relative_path(match: re.Match[str]) -> str:
    value = match.group("quoted_path") or match.group("path")
    if _is_known_non_path_slash_token(value):
        return match.group(0)
    return f"{match.group('prefix')}<path>"


def _is_known_non_path_slash_token(value: str) -> bool:
    assignment, separator, alternatives = value.casefold().partition("=")
    if not separator:
        alternatives = assignment
        assignment = ""
    parts = tuple(alternatives.split("/"))
    device_names = {"cpu", "cuda", "mps", "rocm"}
    if assignment in {"", "device", "devices"} and len(parts) > 1:
        if all(part in device_names for part in parts):
            return True
    if assignment in {"ratio", "ratios"} and len(parts) > 1:
        return all(re.fullmatch(r"\d+(?:\.\d+)?", part) for part in parts)
    return False


def _redact_general_relative_path(match: re.Match[str]) -> str:
    value = match.group(0)
    if _is_known_non_path_slash_token(value):
        return value
    return "<path>"


def redact_text(value: str, *, reveal_sensitive: Optional[bool] = None) -> str:
    reveal = _INCLUDE_SENSITIVE if reveal_sensitive is None else reveal_sensitive

    def sanitize_plain(text: str) -> str:
        text = _redact_quoted_mapping_secrets(text)
        text = _COOKIE_HEADER_RE.sub(
            lambda match: (
                f"{match.group('key')}{match.group('separator')}<redacted>"
            ),
            text,
        )
        text = _COOKIE_ASSIGNMENT_RE.sub(
            lambda match: (
                f"{match.group('key')}{match.group('separator')}<redacted>"
            ),
            text,
        )
        text = _HEADER_DUMP_RE.sub(
            lambda match: (
                f"{match.group('key')}{match.group('separator')}<redacted>"
            ),
            text,
        )
        text = _SECRET_ASSIGNMENT_RE.sub(
            lambda match: (
                f"{match.group('key')}{match.group('separator')}<redacted>"
            ),
            text,
        )
        text = _AUTH_SCHEME_RE.sub(
            lambda match: f"{match.group('scheme')} <redacted>",
            text,
        )
        if reveal:
            return text
        text = _UNIX_PATH_RE.sub("<path>", text)
        text = _WINDOWS_PATH_RE.sub("<path>", text)
        text = _CONTEXTUAL_RELATIVE_PATH_RE.sub(
            _redact_contextual_relative_path,
            text,
        )
        text = _RELATIVE_PATH_RE.sub(_redact_general_relative_path, text)
        return _RELATIVE_WINDOWS_PATH_RE.sub("<path>", text)

    result: list[str] = []
    cursor = 0
    for match in _URL_RE.finditer(value):
        result.append(sanitize_plain(value[cursor : match.start()]))
        result.append(_sanitize_url(match.group(0), reveal_path=reveal))
        cursor = match.end()
    result.append(sanitize_plain(value[cursor:]))
    return "".join(result)


def _single_line(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")


def _safe_value(key: str, value: object) -> object:
    lowered = key.casefold()
    if any(marker in lowered for marker in _HARD_REDACT_KEYS):
        return "<redacted>"
    if any(marker in lowered for marker in _OMIT_VALUE_KEYS):
        return "<omitted>"
    if isinstance(value, str):
        if "url" in lowered:
            safe = _sanitize_url(value, reveal_path=_INCLUDE_SENSITIVE)
            return _single_line(safe)
        if any(marker in lowered for marker in ("path", "file", "directory", "input", "output")):
            safe = value if _INCLUDE_SENSITIVE else "<path>"
            return _single_line(safe)
        return _single_line(redact_text(value))
    if isinstance(value, (list, tuple)):
        return type(value)(_safe_value(key, item) for item in value)
    if isinstance(value, dict):
        return {str(item_key): _safe_value(str(item_key), item) for item_key, item in value.items()}
    module = type(value).__module__.partition(".")[0]
    if module in {"numpy", "torch"}:
        shape = getattr(value, "shape", None)
        return f"<{type(value).__name__} shape={shape!r}>"
    return value


def _safe_field_repr(key: str, value: object) -> str:
    """Return a privacy-filtered, single-line representation that cannot raise."""
    try:
        rendered = repr(_safe_value(key, value))
    except Exception:  # diagnostics must never break the caller
        rendered = repr("<unavailable>")
    try:
        rendered = redact_text(rendered)
    except Exception:  # retain fail-open behavior for hostile reprs
        rendered = repr("<unavailable>")
    return rendered.replace("\r", "\\r").replace("\n", "\\n")


def _structured_line(
    component: str,
    event: str,
    level: str,
    *,
    operation_id: Optional[str] = None,
    **fields: object,
) -> str:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    parts = [
        f"timestamp={timestamp}",
        f"level={level.upper()}",
        f"component={component.lower()}",
        f"session={_SESSION_ID}",
    ]
    active_operation = operation_id or getattr(_TLS, "operation_id", None)
    if active_operation:
        parts.append(f"operation={_single_line(redact_text(str(active_operation)))}")
    parts.append(f"event={event}")
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_safe_field_repr(key, value)}")
    return " ".join(parts).replace("\r", "\\r").replace("\n", "\\n")


def _should_emit(level: str, component: str) -> bool:
    normalized = level.lower()
    if normalized == "error":
        return True
    if normalized == "warning":
        return _CONFIGURED_LEVEL in {"debug", "trace"} or _domain_enabled(component)
    if normalized == "trace":
        return verbose()
    return enabled(component)


def log_event(
    component: str,
    event: str,
    *,
    level: str = "debug",
    operation_id: Optional[str] = None,
    **fields: object,
) -> None:
    """Emit one structured diagnostic event when its threshold is active."""
    normalized = level.lower()
    if normalized not in _LEVEL_RANK or not _should_emit(normalized, component):
        return
    body_parts = [f"event={event}"]
    if operation_id:
        body_parts.append(
            f"operation={_single_line(redact_text(str(operation_id)))}"
        )
    try:
        formatted = format_ctx(**fields)
        if formatted:
            body_parts.append(formatted)
        glib_level = "warning" if normalized in {"warning", "error"} else "debug"
        try:
            glib_log.emit(
                _log_domain(component),
                " ".join(body_parts).replace("\r", "\\r").replace("\n", "\\n"),
                level=glib_level,
            )
        except Exception:
            pass
        _mirror_file(
            _structured_line(
                component,
                event,
                normalized,
                operation_id=operation_id,
                **fields,
            )
        )
    except Exception:
        pass


@contextmanager
def operation(operation_id: str) -> Iterator[None]:
    previous = getattr(_TLS, "operation_id", None)
    _TLS.operation_id = operation_id
    try:
        yield
    finally:
        _TLS.operation_id = previous


def install_runtime_hooks() -> None:
    """Capture Python warnings in Debug/Trace and uncaught exceptions always."""
    global _RUNTIME_HOOKS_INSTALLED
    if warnings.showwarning is not _diagnostic_showwarning:
        warnings.showwarning = _diagnostic_showwarning
    if sys.excepthook is not _diagnostic_excepthook:
        sys.excepthook = _diagnostic_excepthook
    if threading.excepthook is not _diagnostic_thread_excepthook:
        threading.excepthook = _diagnostic_thread_excepthook
    _RUNTIME_HOOKS_INSTALLED = True


def _diagnostic_showwarning(
    message: Warning | str,
    category: type[Warning],
    filename: str,
    lineno: int,
    file: Optional[TextIO] = None,
    line: Optional[str] = None,
) -> None:
    if _CONFIGURED_LEVEL in {"debug", "trace"}:
        log_event(
            "error",
            "python_warning",
            level="warning",
            warning_type=category.__name__,
            warning=str(message),
            source_path=filename,
            line_number=lineno,
        )
    _ORIGINAL_SHOWWARNING(message, category, filename, lineno, file=file, line=line)


def _diagnostic_excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: Optional[TracebackType],
) -> None:
    log_event(
        "error",
        "unhandled_exception",
        level="error",
        error_type=exc_type.__name__,
        error=str(exc_value),
        traceback="".join(
            traceback_module.format_exception(exc_type, exc_value, exc_traceback)
        ),
    )
    _ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_traceback)


def _diagnostic_thread_excepthook(args: threading.ExceptHookArgs) -> None:
    thread = getattr(args, "thread", None)
    log_event(
        "error",
        "unhandled_thread_exception",
        level="error",
        error_type=getattr(args.exc_type, "__name__", str(args.exc_type)),
        error=str(args.exc_value),
        thread=getattr(thread, "name", None),
        traceback="".join(
            traceback_module.format_exception(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            )
        ),
    )
    _ORIGINAL_THREAD_EXCEPTHOOK(args)


def debug(component: str, message: str, *, seq: Optional[int] = None) -> None:
    if not enabled(component):
        return
    if seq is not None:
        message = f"#{seq} {message}"
    domain = _log_domain(component)
    safe_message = redact_text(message)
    glib_log.emit(domain, safe_message)
    _mirror_file(
        _structured_line(
            component,
            "message",
            "debug",
            message=safe_message,
        )
    )


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
