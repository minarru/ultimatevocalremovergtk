"""Activate switches dim the rows they gate."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SwitchDependentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.switch-dependents")
        cls._app.register()

    def _view(self):
        from ui.views.base import MethodView

        view = MethodView.__new__(MethodView)
        return view

    def test_dependents_follow_the_switch(self):
        from gi.repository import Adw

        from ui.views.base import MethodView

        view = self._view()
        switch = Adw.SwitchRow(title="Activate secondary model")
        dependent = Adw.ActionRow(title="Vocals/Instrumental")

        MethodView._bind_switch_dependents(view, switch, [dependent])

        switch.set_active(False)
        self.assertFalse(dependent.get_sensitive())
        switch.set_active(True)
        self.assertTrue(dependent.get_sensitive())

    def test_initial_state_is_applied_immediately(self):
        from gi.repository import Adw

        from ui.views.base import MethodView

        view = self._view()
        switch = Adw.SwitchRow(title="Enable vocal split mode")
        switch.set_active(False)
        dependent = Adw.ActionRow(title="Vocal splitter model")
        dependent.set_sensitive(True)

        MethodView._bind_switch_dependents(view, switch, [dependent])

        self.assertFalse(dependent.get_sensitive())


if __name__ == "__main__":
    unittest.main()
