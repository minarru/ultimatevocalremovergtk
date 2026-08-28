"""Versioned human, JSON, and JSONL reporting for the public CLI."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any, Callable, Optional, TextIO

REPORT_SCHEMA_VERSION = 1
REPORT_CHOICES = ("human", "json", "jsonl")


def add_reporting_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("Reporting")
    group.add_argument(
        "--report",
        choices=REPORT_CHOICES,
        default="human",
        help="Result format (default: human)",
    )
    group.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress and engine logs; retain errors and the result",
    )
    group.add_argument(
        "--verbose",
        action="store_true",
        help="Show the effective plan before processing",
    )
    diagnostics = group.add_mutually_exclusive_group()
    diagnostics.add_argument(
        "--debug",
        action="store_true",
        help="Record structured debug diagnostics (does not change plan output)",
    )
    diagnostics.add_argument(
        "--trace",
        action="store_true",
        help="Record high-frequency structured trace diagnostics",
    )
    group.add_argument(
        "--debug-sensitive",
        action="store_true",
        help="Include local paths and URL paths; credentials and queries stay redacted",
    )
    group.add_argument(
        "--log-file",
        metavar="PATH",
        help="Write diagnostics to PATH instead of the rotating cache log",
    )


def ensure_job_id(args: Any) -> str:
    value = getattr(args, "job_id", None)
    if not value:
        value = str(uuid.uuid4())
        args.job_id = value
    return str(value)


def report_mode(args: Any) -> str:
    return str(getattr(args, "report", "human"))


def base_payload(args: Any, **values: Any) -> dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "job_id": ensure_job_id(args),
        **values,
    }


def emit_document(args: Any, payload: dict[str, Any]) -> None:
    """Emit one final result in the selected format."""
    mode = report_mode(args)
    document = base_payload(args, **payload)
    if mode == "json":
        print(json.dumps(document, indent=2, sort_keys=True))
    elif mode == "jsonl":
        print(json.dumps({"event": "finished", **document}, sort_keys=True))
    else:
        _emit_human_result(document)


def emit_event(args: Any, event: str, **values: Any) -> None:
    if report_mode(args) != "jsonl":
        return
    print(
        json.dumps(base_payload(args, event=event, **values), sort_keys=True),
        flush=True,
    )


def _emit_human_result(payload: dict[str, Any]) -> None:
    print(f"status={payload.get('status') or 'success'}")
    if "elapsed_s" in payload:
        print(f"elapsed_s={float(payload['elapsed_s']):.3f}")
    if payload.get("export_path"):
        print(f"export_path={payload['export_path']}")
    results = payload.get("inputs")
    if isinstance(results, list):
        if len(results) > 1:
            succeeded = sum(item.get("status") == "success" for item in results)
            failed = sum(item.get("status") == "failed" for item in results)
            skipped = sum(item.get("status") == "skipped" for item in results)
            print(
                f"inputs={len(results)} succeeded={succeeded} "
                f"failed={failed} skipped={skipped}"
            )
        for item in results:
            if item.get("status") == "failed":
                print(f"error[{item.get('input')}]={item.get('error')}", file=sys.stderr)


def make_progress_printer(
    args: Any = None,
    stream: Optional[TextIO] = None,
) -> Optional[Callable[..., None]]:
    """Return an ``on_progress`` callback, or ``None`` when not on a TTY.

    Progress goes to stderr so ``--json`` stdout stays parseable. The callback
    runs on the JobRunner worker thread; it only touches a stream, never a
    widget.
    """
    # A stream as the first positional parameter remains useful to core-facing
    # callers; public CLI code passes the Namespace.
    if args is not None and not hasattr(args, "report") and hasattr(args, "write"):
        stream = args
        args = None
    if getattr(args, "quiet", False):
        return None
    if report_mode(args) == "jsonl":
        def jsonl_progress(fraction: float, **meta: Any) -> None:
            emit_event(
                args,
                "progress",
                fraction=max(0.0, min(1.0, float(fraction))),
                **meta,
            )

        return jsonl_progress
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


def finish_progress(args: Any = None, stream: Optional[TextIO] = None) -> None:
    """Close out the in-place progress line with a newline."""
    if args is not None and not hasattr(args, "report") and hasattr(args, "write"):
        stream = args
        args = None
    if report_mode(args) != "human":
        return
    out = stream if stream is not None else sys.stderr
    if getattr(out, "isatty", lambda: False)():
        out.write("\n")
        out.flush()


def warn_validation(args: Any, warnings: Any) -> None:
    """Print stored-identity validation warnings to stderr.

    An illegal or uninstalled stored model reference is preserved verbatim by
    every writer, so nothing else tells the user it is there. Warnings never
    change the exit code -- a value that is actually used still fails planning.
    """
    items = [str(item) for item in (warnings or ()) if str(item).strip()]
    if not items or getattr(args, "quiet", False):
        return
    print("warning: stored model references need attention:", file=sys.stderr)
    for item in items:
        print(f"  {item}", file=sys.stderr)
    if not all("uvr models" in item for item in items):
        print(
            "  run 'uvr models list' or 'uvr models catalog' for canonical "
            "family:basename IDs",
            file=sys.stderr,
        )


def fail(
    args: Any,
    message: str,
    *,
    exit_code: int,
    exc: Optional[BaseException] = None,
    extra: Optional[dict[str, Any]] = None,
    kind: str = "configuration",
) -> int:
    """Report one failure without contaminating machine-readable stdout."""
    from core.debug_log import log_event

    log_event(
        "cli",
        "command_failed",
        level="error",
        operation_id=ensure_job_id(args),
        kind=kind,
        exit_code=exit_code,
        error_type=type(exc).__name__ if exc is not None else None,
        error=message,
    )
    print(f"error: {message}", file=sys.stderr)
    if report_mode(args) != "human":
        error: dict[str, Any] = {"kind": kind, "message": message}
        if exc is not None:
            error["type"] = type(exc).__name__
        payload: dict[str, Any] = {
            "ok": False,
            "status": "failed",
            "error": error,
        }
        if extra:
            payload.update(extra)
        if exit_code == 130:
            payload.setdefault("stopped", True)
        emit_document(args, payload)
    return exit_code
