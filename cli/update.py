"""Read-only release checks."""

from __future__ import annotations

import argparse

from core.version_info import release_update_status

from .reporting import add_reporting_args, emit_document, report_mode


def add_update_parser(sub: argparse._SubParsersAction) -> None:
    root = sub.add_parser("update", help="Inspect application updates")
    children = root.add_subparsers(dest="update_command", required=True)
    check = children.add_parser("check", help="Check the release channel")
    add_reporting_args(check)
    check.set_defaults(func=cmd_update_check)


def cmd_update_check(args: argparse.Namespace) -> int:
    status = release_update_status(force_refresh=True)
    if report_mode(args) == "human":
        current = status.get("version") or "unknown"
        latest = status.get("latest") or "unknown"
        print(f"current: {current}")
        print(f"latest: {latest}")
        print("status: current" if status.get("is_current") else "status: update available")
        print(f"release: {status.get('update_link') or ''}")
        if status.get("upgrade_instructions"):
            print(f"upgrade: {status['upgrade_instructions']}")
    else:
        emit_document(args, {"ok": True, "status": "success", "update": status})
    return 0


__all__ = ["add_update_parser", "cmd_update_check"]
