"""Devices command operations."""

from __future__ import annotations

import argparse

from ..reporting import add_reporting_args
from .formatting import _print_rows


def add_devices_parser(sub: argparse._SubParsersAction) -> None:
    root = sub.add_parser("devices", help="Inspect inference devices")
    children = root.add_subparsers(dest="devices_command", required=True)
    listing = children.add_parser("list")
    add_reporting_args(listing)
    listing.set_defaults(func=cmd_devices_list)


def cmd_devices_list(args: argparse.Namespace) -> int:
    import dataclasses

    from core.device import list_devices

    return _print_rows(args, [dataclasses.asdict(item) for item in list_devices()])
