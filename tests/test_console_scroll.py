"""An unmapped ConsoleView must not spin the GTK main loop.

ui/widgets/console.py:_do_scroll used to re-add itself with GLib.idle_add when
the view was not mapped. An idle source that is always ready means the main
loop never blocks, pinning a core and starving the worker->UI callbacks that
ui/dispatch.py schedules at the same priority.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock


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

    def test_two_unmapped_appends_share_one_map_handler(self) -> None:
        from ui.widgets.console import ConsoleView

        console = ConsoleView()
        self.assertFalse(console.get_mapped())
        console.append("line one\n")
        self._drain()
        first_handler = console._map_handler_id
        self.assertIsNotNone(first_handler)

        idles_before = {"n": 0}
        from gi.repository import GLib
        from typing import Any, Callable

        orig_idle = GLib.idle_add

        def counting_idle(func: Callable[..., Any], *args: Any, **kwargs: Any) -> int:
            idles_before["n"] += 1
            return orig_idle(func, *args, **kwargs)

        with mock.patch.object(GLib, "idle_add", side_effect=counting_idle):
            console.append("line two\n")
            self._drain()

        self.assertEqual(
            console._map_handler_id,
            first_handler,
            "second append while unmapped must reuse the pending map handler",
        )
        self.assertEqual(
            idles_before["n"],
            0,
            "second append must not schedule another idle once parked on map",
        )

    def test_done_marker_skipped_without_an_open_line(self) -> None:
        from bundled.constants import DONE
        from ui.widgets.console import ConsoleView

        console = ConsoleView()
        console.append("Running inference...\n")
        console.append(DONE)
        self.assertNotIn(DONE.strip(), console.get_text())

    def test_done_marker_appended_to_an_open_line(self) -> None:
        from bundled.constants import DONE
        from ui.widgets.console import ConsoleView

        console = ConsoleView()
        console.append("Running inference...")
        console.append(DONE)
        self.assertIn(DONE.strip(), console.get_text())

    def test_done_check_does_not_copy_the_buffer(self) -> None:
        from bundled.constants import DONE
        from gi.repository import Gtk
        from ui.widgets.console import ConsoleView

        console = ConsoleView()
        for i in range(500):
            console.append(f"line {i}\n")

        # Spy on Gtk.TextBuffer.get_text to measure copy sizes, not just method name.
        # This catches if _ends_with_newline() later regresses to copying the
        # whole buffer via any API path.
        orig_get_text = Gtk.TextBuffer.get_text
        spans: list[int] = []

        def spy_get_text(buf: Gtk.TextBuffer, start: Gtk.TextIter, end: Gtk.TextIter, include_hidden: bool) -> str:
            spans.append(end.get_offset() - start.get_offset())
            return orig_get_text(buf, start, end, include_hidden)

        try:
            Gtk.TextBuffer.get_text = spy_get_text  # type: ignore[method-assign]
            # Clear spans accumulated during setup; measure only the DONE call.
            spans.clear()
            console.append(DONE)
            max_span = max(spans) if spans else 0
            self.assertLessEqual(
                max_span, 1,
                f"append() copied {max_span} chars for the DONE check; expected <= 1"
            )
        finally:
            Gtk.TextBuffer.get_text = orig_get_text  # type: ignore[method-assign]


if __name__ == "__main__":
    unittest.main()
