"""Console reporting for the headless CLI: progress line, --quiet, --json."""

from __future__ import annotations

import argparse
import sys
from typing import Any, Callable, Optional, TextIO


def add_reporting_args(parser: argparse.ArgumentParser) -> None:
    """Attach --quiet and --json to a subcommand parser."""
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress engine console output; errors and the summary still print",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable result object on stdout",
    )


def make_progress_printer(
    stream: Optional[TextIO] = None,
) -> Optional[Callable[..., None]]:
    """Return an ``on_progress`` callback, or ``None`` when not on a TTY.

    Progress goes to stderr so ``--json`` stdout stays parseable. The callback
    runs on the JobRunner worker thread; it only touches a stream, never a
    widget.
    """
    out = stream if stream is not None else sys.stderr
    if not getattr(out, "isatty", lambda: False)():
        return None

    def on_progress(fraction: float, **meta: Any) -> None:
        pct = max(0.0, min(1.0, float(fraction))) * 100.0
        detail = str(meta.get("detail") or "")
        pass_index = meta.get("pass_index")
        pass_total = meta.get("pass_total")
        if pass_index is not None and pass_total:
            detail = f"pass {pass_index}/{pass_total} {detail}".strip()
        combine_index = meta.get("combine_index")
        combine_total = meta.get("combine_total")
        if combine_index is not None and combine_total:
            detail = f"combine {combine_index}/{combine_total} {detail}".strip()
        out.write(f"\r{pct:5.1f}%  {detail[:60]:<60}")
        out.flush()

    return on_progress


def finish_progress(stream: Optional[TextIO] = None) -> None:
    """Close out the in-place progress line with a newline."""
    out = stream if stream is not None else sys.stderr
    if getattr(out, "isatty", lambda: False)():
        out.write("\n")
        out.flush()


def emit_json(payload: dict[str, Any]) -> None:
    """Write one JSON document to stdout. The only function allowed to print there under ``--json``."""
    import json

    print(json.dumps(payload, indent=2))


def fail(
    args: argparse.Namespace,
    message: str,
    *,
    exit_code: int,
    exc: Optional[BaseException] = None,
) -> int:
    """Print a human error on stderr; under ``--json`` also emit one failure document."""
    print(f"error: {message}", file=sys.stderr)
    if getattr(args, "json", False):
        error: dict[str, Any] = {"message": message}
        if exc is not None:
            error["type"] = type(exc).__name__
        emit_json({"ok": False, "error": error})
    return exit_code
