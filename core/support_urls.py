"""Fork support URLs (issue tracker pre-fill, etc.)."""

from __future__ import annotations

import platform
import urllib.parse

from bundled.constants import FORK_ISSUE_URL

try:
    from __version__ import UPSTREAM_BASE, VERSION
except Exception:  # pragma: no cover
    VERSION = ""
    UPSTREAM_BASE = ""

_MAX_ISSUE_URL_LEN = 6000
_TRUNCATED_SUFFIX = "\n… (truncated)"


def _issue_body(*, log_text: str) -> str:
    system = platform.system()
    release = platform.release()
    python_version = platform.python_version()
    log_block = log_text.strip() or "(empty)"
    return (
        "## Environment\n"
        f"- GTK version: {VERSION or 'unknown'}\n"
        f"- Upstream base: {UPSTREAM_BASE or 'unknown'}\n"
        f"- OS: {system} {release}\n"
        f"- Python: {python_version}\n"
        "\n"
        "## Steps to reproduce\n"
        "1.\n"
        "\n"
        "## Expected / actual\n"
        "\n"
        "\n"
        "## Error log\n"
        "```\n"
        f"{log_block}\n"
        "```\n"
    )


def fork_issue_url(*, log_text: str, title: str = "UVR GTK bug report") -> str:
    """Build a Codeberg new-issue URL with environment context and error log."""
    clipped = log_text
    while True:
        body = _issue_body(log_text=clipped)
        url = f"{FORK_ISSUE_URL}?{urllib.parse.urlencode({'title': title, 'body': body})}"
        if len(url) <= _MAX_ISSUE_URL_LEN:
            return url
        if not clipped:
            return url
        if len(clipped) > len(_TRUNCATED_SUFFIX) + 1:
            clipped = clipped[: max(0, len(clipped) - 512)].rstrip()
            if clipped and not clipped.endswith(_TRUNCATED_SUFFIX):
                clipped += _TRUNCATED_SUFFIX
        else:
            clipped = _TRUNCATED_SUFFIX.strip()
