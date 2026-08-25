"""Validation behavior for the saved-ensemble name form."""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from ui.ensemble.window import EnsemblePage


class _Entry:
    def __init__(self) -> None:
        self.text = ""
        self.changed = None
        self.css: set[str] = set()

    def set_placeholder_text(self, _text: str) -> None:
        pass

    def connect(self, signal: str, callback: Any) -> None:
        if signal == "changed":
            self.changed = callback

    def get_text(self) -> str:
        return self.text

    def set_text(self, text: str) -> None:
        self.text = text
        if self.changed is not None:
            self.changed(self)

    def add_css_class(self, name: str) -> None:
        self.css.add(name)

    def remove_css_class(self, name: str) -> None:
        self.css.discard(name)

    def grab_focus(self) -> None:
        pass


class _Dialog:
    def __init__(self, **_kwargs: Any) -> None:
        self.enabled: dict[str, bool] = {}
        self.body = ""
        self.response = None

    def set_extra_child(self, _child: Any) -> None:
        pass

    def add_response(self, _ident: str, _label: str) -> None:
        pass

    def set_response_appearance(self, *_args: Any) -> None:
        pass

    def set_default_response(self, _response: str) -> None:
        pass

    def set_close_response(self, _response: str) -> None:
        pass

    def set_response_enabled(self, response: str, enabled: bool) -> None:
        self.enabled[response] = enabled

    def set_body(self, body: str) -> None:
        self.body = body

    def connect(self, signal: str, callback: Any) -> None:
        if signal == "response":
            self.response = callback

    def present(self, _window: Any) -> None:
        pass


class EnsembleSaveDialogTests(unittest.TestCase):
    def test_invalid_name_keeps_save_disabled_until_corrected(self) -> None:
        page = object.__new__(EnsemblePage)
        page.window = mock.Mock()
        page._do_save_ensemble = mock.Mock()
        entry = _Entry()
        dialog = _Dialog()

        with (
            mock.patch("ui.ensemble.window.Gtk.Entry", return_value=entry),
            mock.patch("ui.ensemble.window.Adw.AlertDialog", return_value=dialog),
        ):
            page._present_save_dialog(["model-a", "model-b"])

        self.assertFalse(dialog.enabled["save"])
        entry.set_text("../escape")
        self.assertFalse(dialog.enabled["save"])
        self.assertIn("only letters", dialog.body)
        self.assertIn("error", entry.css)

        entry.set_text("My Mix")
        self.assertTrue(dialog.enabled["save"])
        self.assertNotIn("error", entry.css)
        assert dialog.response is not None
        dialog.response(dialog, "save")
        page._do_save_ensemble.assert_called_once_with("My Mix", ["model-a", "model-b"])


if __name__ == "__main__":
    unittest.main()
