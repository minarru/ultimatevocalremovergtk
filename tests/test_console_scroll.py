"""An unmapped ConsoleView must not spin the GTK main loop.

ui/widgets/console.py:_do_scroll used to re-add itself with GLib.idle_add when
the view was not mapped. An idle source that is always ready means the main
loop never blocks, pinning a core and starving the worker->UI callbacks that
ui/dispatch.py schedules at the same priority.
"""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class ConsoleScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.console-scroll")
        cls._app.register()

    def _drain(self, iterations: int = 200) -> None:
        """Pump the default main context without blocking."""
        from gi.repository import GLib

        ctx = GLib.MainContext.default()
        for _ in range(iterations):
            if not ctx.iteration(False):
                break

    def test_unmapped_append_does_not_spin_idle(self) -> None:
        from ui.widgets.console import ConsoleView

        console = ConsoleView()
        self.assertFalse(console.get_mapped(), "fixture expects an unmapped view")

        calls = {"n": 0}
        original = console._do_scroll

        def counted() -> bool:
            calls["n"] += 1
            return original()

        console._do_scroll = counted  # type: ignore[method-assign]
        console.append("worker output line\n")
        self._drain()

        # With the bug this reaches the full drain count; the fix parks on
        # the "map" signal instead, so the idle runs at most once.
        self.assertLessEqual(
            calls["n"], 2, f"idle source re-armed {calls['n']} times while unmapped"
        )

    def test_unmapped_scroll_is_rearmed_on_map(self) -> None:
        from ui.widgets.console import ConsoleView

        console = ConsoleView()
        console.append("line\n")
        self._drain()
        self.assertIsNotNone(
            console._map_handler_id, "expected a pending map handler while unmapped"
        )


if __name__ == "__main__":
    unittest.main()
