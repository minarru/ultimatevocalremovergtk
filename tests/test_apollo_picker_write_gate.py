"""The Apollo picker must never rewrite a stored model value.

Every method picker got a write gate at the identity cutover: a stored value
that is not one of the picker's installed canonical IDs shows as no selection
and stays on disk exactly as written, until the user re-picks. The Apollo
picker instead resolved the stored text and wrote the result back on every
window load and refresh, which silently converted legacy values.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock


class _StubWindow:
    def toast(self, _message: str) -> None:
        pass

    def _refresh_start_readiness(self) -> None:
        pass


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class ApolloPickerWriteGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.apollo-picker-gate")
        cls._app.register()

    def _record(self):
        from core.model_identity import ModelArtifacts, ModelRecord

        return ModelRecord(
            id="apollo:restorer",
            family="apollo",
            basename="restorer",
            display="Apollo Universal Restorer",
            backend_name="restorer.ckpt",
            artifacts=ModelArtifacts("restorer.ckpt"),
            installed=True,
        )

    def _page(self, stored: str):
        from core.model_repository import ModelRepository
        from core.settings import Settings
        from ui.audio_tools.window import AudioToolsPage

        settings = Settings.defaults()
        settings.audio_tools.apollo_model = stored

        class _Context:
            def __init__(self) -> None:
                self.settings = settings
                self.repo = ModelRepository()

        return AudioToolsPage(_StubWindow(), _Context()), settings

    def test_legacy_display_value_is_left_alone_and_shows_no_selection(self) -> None:
        from bundled.constants import CHOOSE_MODEL
        from core.model_identity import ModelIdentityService
        from ui.widgets.rows import get_combo_value

        record = self._record()
        with mock.patch.object(
            ModelIdentityService, "records", return_value=(record,)
        ), mock.patch("core.apollo.list_apollo_models", return_value=["restorer.ckpt"]):
            page, settings = self._page("Apollo: Apollo Universal Restorer")
            page._refresh_apollo_models()

        self.assertEqual(
            settings.audio_tools.apollo_model, "Apollo: Apollo Universal Restorer"
        )
        self.assertEqual(get_combo_value(page.apollo_model_row), CHOOSE_MODEL)

    def test_bare_basename_value_is_left_alone_too(self) -> None:
        from bundled.constants import CHOOSE_MODEL
        from core.model_identity import ModelIdentityService
        from ui.widgets.rows import get_combo_value

        record = self._record()
        with mock.patch.object(
            ModelIdentityService, "records", return_value=(record,)
        ), mock.patch("core.apollo.list_apollo_models", return_value=["restorer.ckpt"]):
            page, settings = self._page("restorer")
            page._refresh_apollo_models()

        self.assertEqual(settings.audio_tools.apollo_model, "restorer")
        self.assertEqual(get_combo_value(page.apollo_model_row), CHOOSE_MODEL)

    def test_canonical_installed_value_selects_and_is_unchanged(self) -> None:
        from core.model_identity import ModelIdentityService
        from ui.widgets.rows import get_combo_value

        record = self._record()
        with mock.patch.object(
            ModelIdentityService, "records", return_value=(record,)
        ), mock.patch("core.apollo.list_apollo_models", return_value=["restorer.ckpt"]):
            page, settings = self._page(record.id)
            page._refresh_apollo_models()

        self.assertEqual(settings.audio_tools.apollo_model, record.id)
        self.assertEqual(get_combo_value(page.apollo_model_row), record.id)


if __name__ == "__main__":  # pragma: no cover - manual runs
    unittest.main()
