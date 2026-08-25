import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import ensemble_service, paths


class SavedEnsemblePersistenceTests(unittest.TestCase):
    def test_names_are_canonicalized_and_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(paths, "ENSEMBLE_CACHE_DIR", tmp):
            path = ensemble_service.save_ensemble(" My Mix ", "pair.karaoke", "max", ["a", "b"])
            self.assertEqual(os.path.basename(path), "My_Mix.json")
            self.assertEqual(ensemble_service.list_saved_ensembles(), ["My_Mix"])
            loaded = ensemble_service.load_ensemble("My Mix")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["schema_version"], 2)
            self.assertEqual(loaded["ensemble_main_stem"], "pair.karaoke")
            self.assertEqual(loaded["selected_models"], ["a", "b"])
            self.assertTrue(ensemble_service.delete_ensemble("My Mix"))
            self.assertEqual(ensemble_service.list_saved_ensembles(), [])

    def test_invalid_names_cannot_escape_cache(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(paths, "ENSEMBLE_CACHE_DIR", os.path.join(tmp, "ensembles")),
        ):
            for name in ("../outside", os.path.join(tmp, "outside"), "bad.json", ""):
                with self.assertRaises(ValueError):
                    ensemble_service.save_ensemble(name, "pair.karaoke", "max", [])
            self.assertFalse(os.path.exists(os.path.join(tmp, "outside.json")))

    def test_listing_ignores_unsafe_legacy_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(paths, "ENSEMBLE_CACHE_DIR", tmp):
            with open(os.path.join(tmp, "Good_Name.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with open(os.path.join(tmp, "bad.name.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            self.assertEqual(ensemble_service.list_saved_ensembles(), ["Good_Name"])

    def test_legacy_document_clears_pair_but_preserves_members_and_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(paths, "ENSEMBLE_CACHE_DIR", tmp):
            with open(os.path.join(tmp, "Legacy.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "ensemble_main_stem": "vocals_instrumental",
                        "ensemble_type": "Max Spec",
                        "selected_models": ["mdx:first", "mdx:second"],
                        "is_wav_ensemble": True,
                        "save_all_outputs": False,
                    },
                    handle,
                )
            loaded = ensemble_service.load_ensemble("Legacy")
            assert loaded is not None
            self.assertEqual(loaded["ensemble_main_stem"], "")
            self.assertEqual(loaded["selected_models"], ["mdx:first", "mdx:second"])
            self.assertEqual(loaded["ensemble_type"], "Max Spec")
            self.assertTrue(loaded["is_wav_ensemble"])
            self.assertFalse(loaded["save_all_outputs"])
            self.assertEqual(len(loaded.validation_warnings), 1)
            self.assertIn("ensemble_main_stem", loaded.validation_warnings[0])

    def test_legacy_document_stays_blocked_until_pair_is_repicked_and_resaved(self) -> None:
        from core.settings import Settings
        from ui.ensemble.window import EnsemblePage

        with tempfile.TemporaryDirectory() as tmp, patch.object(paths, "ENSEMBLE_CACHE_DIR", tmp):
            with open(os.path.join(tmp, "Legacy.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "ensemble_type": "Max Spec",
                        "selected_models": ["mdx:first", "mdx:second"],
                        "is_wav_ensemble": True,
                        "save_all_outputs": False,
                    },
                    handle,
                )
            legacy = ensemble_service.load_ensemble("Legacy")
            assert legacy is not None
            settings = Settings.defaults()
            settings.ensemble.main_stem = legacy["ensemble_main_stem"]
            settings.ensemble.selected_models = list(legacy["selected_models"])
            page = EnsemblePage.__new__(EnsemblePage)
            page.settings = settings
            page._effective_selected_models = lambda: settings.ensemble.selected_models
            self.assertIsNotNone(page._config_blocked_reason())

            settings.ensemble.main_stem = "pair.karaoke"
            self.assertIsNone(page._config_blocked_reason())
            still_legacy = ensemble_service.load_ensemble("Legacy")
            assert still_legacy is not None
            self.assertEqual(still_legacy["ensemble_main_stem"], "")

            ensemble_service.save_ensemble(
                "Legacy",
                settings.ensemble.main_stem,
                legacy["ensemble_type"],
                legacy["selected_models"],
                wav_ensemble=legacy["is_wav_ensemble"],
                save_all_outputs=legacy["save_all_outputs"],
            )
            resaved = ensemble_service.load_ensemble("Legacy")
            assert resaved is not None
            self.assertEqual(resaved["schema_version"], 2)
            self.assertEqual(resaved["ensemble_main_stem"], "pair.karaoke")
            self.assertEqual(resaved["selected_models"], ["mdx:first", "mdx:second"])
            self.assertEqual(resaved["ensemble_type"], "Max Spec")
            self.assertTrue(resaved["is_wav_ensemble"])
            self.assertFalse(resaved["save_all_outputs"])


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SavedEnsembleWarningGtkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.saved-warning")
        cls._app.register()

    def test_reader_warning_is_visible_after_saved_preset_selection(self) -> None:
        from gi.repository import Adw

        from bundled.constants import CHOOSE_ENSEMBLE_OPTION
        from core.ensemble_service import ResolvedEnsemblePreset
        from core.settings import Settings
        from core.stem_pairs import ensemble_pair_choices
        from ui.ensemble.window import EnsemblePage
        from ui.widgets.rows import (
            get_combo_value,
            make_combo_row,
            set_combo_tag_values,
            set_combo_value,
        )

        warning = "ensemble.selected_models[0]: preserved 'MDX-Net: legacy'"
        preset = ResolvedEnsemblePreset(
            id="Broken",
            display="Broken",
            kind="saved",
            main_stem="pair.vocals_instrumental",
            algorithm="Max Spec/Min Spec",
            members=("MDX-Net: legacy",),
            validation_warnings=(warning,),
        )
        settings = Settings.defaults()
        page = EnsemblePage.__new__(EnsemblePage)
        page._loading = False
        page.settings = settings
        page.context = SimpleNamespace(repo=object())
        page.window = SimpleNamespace(_refresh_start_readiness=lambda: None)
        page.saved_row = make_combo_row("Saved ensemble", [CHOOSE_ENSEMBLE_OPTION, "Broken"])
        set_combo_value(page.saved_row, "Broken")
        page.main_stem_row = make_combo_row("Main stem", [])
        set_combo_tag_values(page.main_stem_row, ensemble_pair_choices())
        page._ensemble_banner = Adw.Banner(revealed=False)
        page._config_blocked_reason = lambda: None
        page._refresh_ensemble_type_values = lambda: None
        page._rebuild_stem_only_toggles = lambda: None
        page._rebuild_model_list = lambda preselected: None
        page._persist_selected_models = lambda: None
        page._toast = lambda message: None

        with patch("core.ensemble_service.EnsembleService.apply", return_value=preset):
            EnsemblePage._on_saved_selected(page)

        self.assertTrue(page._ensemble_banner.get_revealed())
        self.assertIn("MDX-Net: legacy", page._ensemble_banner.get_title())
        self.assertEqual(get_combo_value(page.main_stem_row), "pair.vocals_instrumental")

    def test_valid_member_repick_clears_gated_preset_warning(self) -> None:
        from gi.repository import Adw

        from bundled.constants import CHOOSE_ENSEMBLE_OPTION
        from core.settings import Settings
        from ui.ensemble.window import EnsemblePage
        from ui.widgets.rows import make_combo_row

        settings = Settings.defaults()
        settings.ensemble.selected_models = ["mdx:first", "mdx:missing"]
        page = EnsemblePage.__new__(EnsemblePage)
        page.settings = settings
        page._loading = True
        page._models_write_gated = True
        page._ensemble_validation_warnings = (
            "ensemble.selected_models[1]: unknown model 'mdx:missing'",
        )
        page._ensemble_member_warnings = (
            "ensemble.selected_models[1]: model 'mdx:missing' is not installed",
        )
        page._ensemble_banner = Adw.Banner(revealed=True)
        page._config_blocked_reason = lambda: None
        page.window = SimpleNamespace(_refresh_start_readiness=lambda: None)
        page.saved_row = make_combo_row("Saved ensemble", [CHOOSE_ENSEMBLE_OPTION, "Broken"])
        page._selected_model_tags = lambda: ["mdx:first", "mdx:second"]
        page._update_models_dialog_status = lambda: None
        page._update_models_summary = lambda: EnsemblePage._update_ensemble_banner(page)
        page._rebuild_stem_only_toggles = lambda: None

        EnsemblePage._on_model_toggled(page, object())  # type: ignore[arg-type]

        self.assertEqual(settings.ensemble.selected_models, ["mdx:first", "mdx:second"])
        self.assertEqual(page._ensemble_validation_warnings, ())
        self.assertEqual(page._ensemble_member_warnings, ())
        self.assertFalse(page._ensemble_banner.get_revealed())


if __name__ == "__main__":
    unittest.main()
