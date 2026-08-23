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

    def _record(
        self,
        model_id: str = "apollo:restorer",
        display: str = "Apollo Universal Restorer",
        backend_name: str = "restorer.ckpt",
    ):
        from core.model_identity import ModelArtifacts, ModelRecord

        return ModelRecord(
            id=model_id,
            family="apollo",
            basename=model_id.partition(":")[2],
            display=display,
            backend_name=backend_name,
            artifacts=ModelArtifacts(backend_name),
            installed=True,
        )

    def _page(self, stored: str):
        from bundled.constants import APOLLO_RESTORE
        from core.model_repository import ModelRepository
        from core.settings import Settings
        from ui.audio_tools.window import AudioToolsPage

        settings = Settings.defaults()
        settings.audio_tools.apollo_model = stored
        settings.set("chosen_audio_tool", APOLLO_RESTORE)

        class _Context:
            def __init__(self) -> None:
                self.settings = settings
                self.repo = ModelRepository()

        page = AudioToolsPage(_StubWindow(), _Context())
        from ui.widgets.rows import set_combo_value

        set_combo_value(page.tool_row, APOLLO_RESTORE)
        return page, settings

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

    def test_illegal_value_warning_survives_refresh_until_valid_repick(self) -> None:
        from bundled.constants import CHOOSE_MODEL
        from core.model_identity import ModelIdentityService
        from ui.widgets.rows import combo_values, get_combo_value

        illegal = "Apollo: Apollo Universal Restorer"
        record = self._record()
        with mock.patch.object(
            ModelIdentityService, "records", return_value=(record,)
        ), mock.patch("core.apollo.list_apollo_models", return_value=["restorer.ckpt"]):
            page, settings = self._page(illegal)
            page._refresh_apollo_models()
            page._refresh_apollo_models()

            self.assertEqual(settings.audio_tools.apollo_model, illegal)
            self.assertEqual(get_combo_value(page.apollo_model_row), CHOOSE_MODEL)
            self.assertTrue(page._audio_banner.get_revealed())
            self.assertIn(illegal, page._audio_banner.get_title())

            displayed = combo_values(page.apollo_model_row)
            page.apollo_model_row.set_selected(
                displayed.index("Apollo Universal Restorer")
            )

        self.assertEqual(settings.audio_tools.apollo_model, record.id)
        self.assertFalse(page._audio_banner.get_revealed())

    def test_installed_refresh_does_not_clear_a_presented_missing_gate(self) -> None:
        from bundled.constants import CHOOSE_MODEL
        from core.model_identity import ModelIdentityService
        from ui.widgets.rows import combo_values, get_combo_value

        missing = self._record(
            "apollo:later", "Apollo Later", "later.ckpt"
        )
        records = [self._record()]
        filenames = ["restorer.ckpt"]
        with mock.patch.object(
            ModelIdentityService,
            "records",
            side_effect=lambda: tuple(records),
        ), mock.patch(
            "core.apollo.list_apollo_models",
            side_effect=lambda: list(filenames),
        ):
            page, settings = self._page(missing.id)
            page._refresh_apollo_models()
            self.assertTrue(page._audio_banner.get_revealed())

            records.append(missing)
            filenames.append(missing.backend_name)
            page._refresh_apollo_models()

            self.assertEqual(settings.audio_tools.apollo_model, missing.id)
            self.assertEqual(get_combo_value(page.apollo_model_row), CHOOSE_MODEL)
            self.assertTrue(page._audio_banner.get_revealed())
            self.assertIn(missing.id, page._audio_banner.get_title())

            displayed = combo_values(page.apollo_model_row)
            page.apollo_model_row.set_selected(displayed.index(missing.display))

        self.assertEqual(settings.audio_tools.apollo_model, missing.id)
        self.assertFalse(page._audio_banner.get_revealed())

    def test_external_settings_change_replaces_stale_apollo_gate(self) -> None:
        from bundled.constants import CHOOSE_MODEL
        from core.model_identity import ModelIdentityService
        from ui.widgets.rows import get_combo_value

        original = "apollo:missing-original"
        replacement = self._record()
        with mock.patch.object(
            ModelIdentityService, "records", return_value=(replacement,)
        ), mock.patch(
            "core.apollo.list_apollo_models",
            return_value=[replacement.backend_name],
        ):
            page, settings = self._page(original)
            page._refresh_apollo_models()
            self.assertTrue(page._audio_banner.get_revealed())

            new_invalid = "apollo:missing-replacement"
            settings.audio_tools.apollo_model = new_invalid
            page._refresh_apollo_models()
            self.assertEqual(get_combo_value(page.apollo_model_row), CHOOSE_MODEL)
            self.assertIn(new_invalid, page._audio_banner.get_title())
            self.assertNotIn(original, page._audio_banner.get_title())

            settings.audio_tools.apollo_model = replacement.id
            page._refresh_apollo_models()

        self.assertEqual(get_combo_value(page.apollo_model_row), replacement.id)
        self.assertFalse(page._audio_banner.get_revealed())
        self.assertFalse(page._apollo_write_gated)

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
