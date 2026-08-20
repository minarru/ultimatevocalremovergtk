"""Sentinel proving the live-network guard is armed inside swallowed fetches."""

from __future__ import annotations

import os
import unittest

from tests.net_guard import BlockedNetworkAccess


class NetGuardArmedTests(unittest.TestCase):
    def test_blocked_access_is_not_exception(self) -> None:
        self.assertFalse(issubclass(BlockedNetworkAccess, Exception))
        self.assertTrue(issubclass(BlockedNetworkAccess, BaseException))

    def test_guard_escapes_politrees_except_exception(self) -> None:
        import core.politrees_catalog as pc

        os.environ["UVR_DISABLE_POLITREES"] = "0"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_POLITREES", None))
        pc.clear_politrees_cache()
        with self.assertRaises(BlockedNetworkAccess):
            pc.load_politrees_links(force=True)

    def test_guard_message_includes_armed_sentinel(self) -> None:
        exc = BlockedNetworkAccess("probe")
        self.assertIn("UVR_NET_GUARD_ARMED=1", str(_blocked_message()))


def _blocked_message() -> str:
    from tests import net_guard

    return str(net_guard._blocked(("example.test", 443)))


if __name__ == "__main__":
    unittest.main()
