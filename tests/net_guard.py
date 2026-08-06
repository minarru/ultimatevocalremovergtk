"""Fail the suite on live outbound network instead of silently depending on it.

CI runs ``unittest discover`` bare — no ``UVR_DISABLE_*`` flags — so any test
that reaches a catalogue source, a config fetch or a size HEAD does real HTTP.
Those calls all have offline fallbacks, so the tests still pass; they just make
CI slow, flaky and dependent on third-party uptime, and nothing catches a newly
added one.

The guard blocks **outbound TCP to non-loopback addresses only**. AF_UNIX is
untouched, so GTK/DBus connections still work, and loopback stays open for any
test that spins up a local server.

Set ``UVR_TESTS_ALLOW_NETWORK=1`` to disable the guard for a debugging run.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import traceback
from typing import Any, Tuple

_installed = False
_real_socket_connect = socket.socket.connect
_real_create_connection = socket.create_connection


class BlockedNetworkAccess(AssertionError):
    """Raised when a test attempts live outbound network access."""


def _is_loopback(host: object) -> bool:
    if not isinstance(host, str) or not host:
        return False
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _should_block(address: object) -> bool:
    if not isinstance(address, tuple) or len(address) < 2:
        # AF_UNIX and friends pass a str/bytes path — never blocked.
        return False
    return not _is_loopback(address[0])


def _origin() -> str:
    """Best-effort 'which test did this' for the error message."""
    for frame in reversed(traceback.extract_stack()):
        if f"{os.sep}tests{os.sep}" in frame.filename and "net_guard" not in frame.filename:
            return f"{os.path.basename(frame.filename)}:{frame.lineno} in {frame.name}"
    return "<unknown test>"


def _blocked(address: object) -> BlockedNetworkAccess:
    return BlockedNetworkAccess(
        f"live network access to {address!r} from {_origin()}.\n"
        "Tests must not do real HTTP. Patch the importing module's own name "
        "(e.g. core.politrees_catalog._urlopen), not core.mdx_config_fetch._urlopen "
        "— modules bind these helpers by value. Set UVR_TESTS_ALLOW_NETWORK=1 to "
        "bypass this guard while debugging."
    )


def _guarded_connect(self: socket.socket, address: Any) -> None:
    if _should_block(address):
        raise _blocked(address)
    return _real_socket_connect(self, address)


def _guarded_create_connection(
    address: Tuple[str, int], *args: Any, **kwargs: Any
) -> socket.socket:
    if _should_block(address):
        raise _blocked(address)
    return _real_create_connection(address, *args, **kwargs)


def install() -> None:
    global _installed
    if _installed or os.environ.get("UVR_TESTS_ALLOW_NETWORK") == "1":
        return
    _installed = True
    socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
    socket.create_connection = _guarded_create_connection
