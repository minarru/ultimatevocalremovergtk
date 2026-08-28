import typing
import unittest
from types import SimpleNamespace

from gi.repository import GLib

from bundled.constants import (
    ALL_STEMS,
    BASS_STEM,
    DRUM_STEM,
    INST_STEM,
    PRIMARY_STEM,
    SECONDARY_STEM,
    VOCAL_STEM,
)
from core.settings import Settings
from core.stem_roles import StemId, StemLiteral, StemRoleId
from core.stem_selection import (
    _FOCUS_VOCALS,
    _QUICK_ALL,
    _QUICK_INSTRUMENTAL,
    _QUICK_VOCALS,
    _TOGGLE_ALL,
    _stem_focus_tag,
)
from core.stems import StemRoute, model_stem_routes
from tests.private_gtk import require_private_gtk
from ui.widget_state import fetch
from ui.widgets.stem_only import (
    _LEAD_VOCAL_PAIR_LABELS,
    SaveStemsSection,
    build_stem_only_options,
    canonical_stem_name,
    get_combo_value,
    roformer_lead_vocal_label_overrides,
    set_combo_value,
    stem_display_label,
)


def setUpModule() -> None:
    require_private_gtk()


class _Settings(Settings):
    def __init__(self, data: typing.Any = None):
        super().__init__()
        self.update(data or {})

    def __getitem__(self, key: typing.Any):
        return self.get(key)

    def __setitem__(self, key: typing.Any, value: typing.Any):
        self.set(key, value)


def _reviewed_target_routes(model_id: str, native: str) -> tuple[StemRoute, ...]:
    return model_stem_routes(
        SimpleNamespace(
            canonical_id=model_id,
            mdx_model_stems=[native],
            demucs_source_list=[],
            primary_stem=native,
            primary_stem_native=native,
            target_instrument=native,
            is_vocal_split_model=False,
        )
    )


class StemDisplayLabelTests(unittest.TestCase):
    def test_lowercase_aliases_normalize(self):
        self.assertEqual(canonical_stem_name("other"), "Other")
        self.assertEqual(canonical_stem_name("vocals"), "Vocals")
        self.assertEqual(canonical_stem_name("drums"), "Drums")

    def test_complement_stems_use_friendly_labels(self):
        self.assertEqual(stem_display_label("other"), "Other")
        self.assertEqual(stem_display_label("No other"), "Mix minus Other")
        self.assertEqual(stem_display_label("No Vocals"), "Instrumental")
        self.assertEqual(stem_display_label("No vocals"), "Instrumental")

    def test_build_stem_only_options_use_display_labels(self):
        options = build_stem_only_options(
            primary_stem="other",
            secondary_stem="No other",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        labels = [option.display_label for option in options if option.settings_key]
        self.assertEqual(labels, ["Other", "Mix minus Other"])

    def test_roformer_other_pair_uses_vocals_instrumental_labels(self):
        overrides = dict(_LEAD_VOCAL_PAIR_LABELS)
        self.assertEqual(stem_display_label("other", overrides=overrides), INST_STEM)
        self.assertEqual(stem_display_label("No other", overrides=overrides), VOCAL_STEM)
        options = build_stem_only_options(
            primary_stem="other",
            secondary_stem="No other",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            stem_label_overrides=overrides,
        )
        labels = [option.display_label for option in options if option.settings_key]
        self.assertEqual(labels, [VOCAL_STEM, INST_STEM])

    def test_roformer_vocals_other_overrides_only_for_two_stem_models(self):
        class _Training:
            instruments = ["other", "vocals"]

        class _Config:
            training = _Training()

        class _Model:
            is_roformer = True
            mdx_c_configs = _Config()

        self.assertEqual(roformer_lead_vocal_label_overrides(_Model()), _LEAD_VOCAL_PAIR_LABELS)
        self.assertIsNone(roformer_lead_vocal_label_overrides(None))

    def test_gains_shared_table_aliases_not_previously_recognized(self) -> None:
        self.assertEqual(canonical_stem_name("voc"), VOCAL_STEM)
        self.assertEqual(canonical_stem_name("instrument"), INST_STEM)

    def test_specialty_names_still_resolve_locally(self) -> None:
        self.assertEqual(canonical_stem_name("speech"), "Speech")
        self.assertEqual(canonical_stem_name("sfx"), "Sfx")
        self.assertEqual(canonical_stem_name("music"), "Music")
        self.assertEqual(canonical_stem_name("effects"), "Effects")

    def test_vocals_other_overrides_skipped_for_multi_stem_models(self):
        class _Training:
            instruments = ["other", "vocals", "drums", "bass"]

        class _Config:
            training = _Training()

        class _Model:
            is_roformer = True
            mdx_c_configs = _Config()

        self.assertIsNone(roformer_lead_vocal_label_overrides(_Model()))


class BuildStemOnlyOptionsTests(unittest.TestCase):
    def test_reviewed_routes_supply_role_ids_labels_and_logical_primary_order(self):
        routes = (
            StemRoute(
                StemId("other"),
                StemRoleId("mix.instrumental_with_backing_vocals"),
                label="Instrumental with Backing Vocals",
                logical_primary=False,
            ),
            StemRoute(
                StemId("vocals"),
                StemRoleId("vocal.lead"),
                label="Lead Vocals",
                logical_primary=True,
            ),
        )
        options = build_stem_only_options(
            primary_stem="other",
            secondary_stem="vocals",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            routes=routes,
        )

        self.assertEqual(
            [(option.name, option.display_label, option.settings_key) for option in options[1:]],
            [
                ("vocal.lead", "Lead Vocals", "is_primary_stem_only"),
                (
                    "mix.instrumental_with_backing_vocals",
                    "Instrumental with Backing Vocals",
                    "is_secondary_stem_only",
                ),
            ],
        )

    def test_raw_routes_keep_raw_labels_and_scoped_ids(self):
        routes = (
            StemRoute(
                StemId("Mystery Lead"),
                StemLiteral("Mystery Lead"),
                label="Mystery Lead",
                logical_primary=True,
                selection_scope="fixture-scope",
            ),
            StemRoute(
                StemId("Mystery Back"),
                StemLiteral("Mystery Back"),
                label="Mystery Back",
                selection_scope="fixture-scope",
            ),
        )
        options = build_stem_only_options(
            primary_stem="Mystery Lead",
            secondary_stem="Mystery Back",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            routes=routes,
        )

        self.assertEqual(
            [option.display_label for option in options[1:]],
            ["Mystery Lead", "Mystery Back"],
        )
        self.assertTrue(options[1].name.startswith("raw:mystery lead#scope="))

    def test_all_stems_is_first_option(self):
        options = build_stem_only_options(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.assertEqual(options[0].name, _TOGGLE_ALL)
        self.assertIsNone(options[0].settings_key)

    def test_named_stems_use_settings_keys(self):
        options = build_stem_only_options(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        keys = {option.settings_key for option in options if option.settings_key}
        self.assertEqual(keys, {"is_primary_stem_only", "is_secondary_stem_only"})

    def test_fallback_primary_secondary_labels(self):
        options = build_stem_only_options(
            primary_stem=None,
            secondary_stem=None,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        labels = [option.display_label for option in options]
        self.assertIn(PRIMARY_STEM, labels)
        self.assertIn(SECONDARY_STEM, labels)


class SaveStemsSectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = _Settings(
            {
                "mdx_stems_selected": [],
                "mdx_stems": ALL_STEMS,
                "demucs_stems": ALL_STEMS,
            }
        )
        self.section = SaveStemsSection(settings=self.settings)

    def _drain_main_context(self) -> None:
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def test_hidden_without_model(self):
        self.section.configure_hidden(has_model=False)
        self.assertEqual(self.section.export_summary(), "Choose a model to configure stem export")
        self.assertFalse(self.section._section_visible)
        self.assertFalse(self.section._exclusive_row.get_visible())

    def test_refresh_marks_a_removed_exact_role_for_explicit_repick(self):
        self.settings.process.stem_focus = "vocal.lead"
        self.section.configure_exclusive(
            primary_stem="vocals",
            secondary_stem="other",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
            routes=(
                StemRoute(
                    StemId("vocals"),
                    StemRoleId("vocal.vocals"),
                    label="Vocals",
                    logical_primary=True,
                ),
                StemRoute(
                    StemId("other"),
                    StemRoleId("mix.instrumental"),
                    label="Instrumental",
                ),
            ),
        )

        self.assertTrue(self.section.require_refresh_repick("vocal.lead"))
        self.assertTrue(self.section.repick_required)
        self.assertTrue(self.section.selection_warning_row.get_visible())
        self.assertEqual(get_combo_value(self.section._exclusive_row), "choose")
        self.section._on_exclusive_changed()
        self.assertTrue(self.section.repick_required)
        self.assertTrue(self.section.selection_warning_row.get_visible())
        set_combo_value(self.section._exclusive_row, "vocal.vocals")
        self.section._on_exclusive_changed()
        self.assertFalse(self.section.repick_required)
        self._drain_main_context()
        self.assertEqual(
            fetch(self.section._exclusive_row, "_uvr_combo_ids"),
            [_TOGGLE_ALL, "vocal.vocals", "mix.instrumental"],
        )
        self.assertFalse(set_combo_value(self.section._exclusive_row, "choose"))
        self.section._on_exclusive_changed()
        self.section.persist_to_settings()
        self.assertEqual(get_combo_value(self.section._exclusive_row), "vocal.vocals")
        self.assertEqual(self.settings.process.stem_focus, "vocal.vocals")

    def test_refresh_preserves_a_still_valid_exact_role(self) -> None:
        self.settings.process.stem_focus = "vocal.lead"
        self.section.configure_exclusive(
            primary_stem="nativeLead",
            secondary_stem="nativeBacking",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
            routes=(
                StemRoute(
                    StemId("nativeLead"),
                    StemRoleId("vocal.lead"),
                    label="Lead Vocals",
                    logical_primary=True,
                ),
                StemRoute(
                    StemId("nativeBacking"),
                    StemRoleId("vocal.backing"),
                    label="Backing Vocals",
                ),
            ),
        )
        self.section.sync_from_settings()

        self.assertFalse(self.section.require_refresh_repick("vocal.lead"))
        self.assertFalse(self.section.repick_required)
        self.assertEqual(get_combo_value(self.section._exclusive_row), "vocal.lead")

    def test_subset_removed_role_selects_choose_until_explicit_repick(self) -> None:
        self.section.configure_subset(
            stems=["vocals", "other", "bass"],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            routes=(
                StemRoute(
                    StemId("vocals"),
                    StemRoleId("vocal.vocals"),
                    label="Vocals",
                    logical_primary=True,
                ),
                StemRoute(
                    StemId("other"),
                    StemRoleId("mix.instrumental"),
                    label="Instrumental",
                ),
                StemRoute(
                    StemId("bass"),
                    StemRoleId("instrument.bass"),
                    label="Bass",
                ),
            ),
        )

        self.assertTrue(self.section.require_refresh_repick("vocal.lead"))
        self.assertEqual(get_combo_value(self.section._quick_row), "choose")
        self.assertTrue(self.section.selection_warning_row.get_visible())
        self.section._on_quick_export_changed()
        self.assertTrue(self.section.repick_required)
        self.assertTrue(self.section.selection_warning_row.get_visible())
        set_combo_value(self.section._quick_row, _QUICK_VOCALS)
        self.section._on_quick_export_changed()
        self.assertFalse(self.section.repick_required)
        self._drain_main_context()
        self.assertEqual(
            fetch(self.section._quick_row, "_uvr_combo_ids"),
            [_QUICK_ALL, _QUICK_INSTRUMENTAL, _QUICK_VOCALS],
        )
        self.assertFalse(set_combo_value(self.section._quick_row, "choose"))
        self.section._on_quick_export_changed()
        self.section.persist_to_settings()
        self.assertEqual(self.section._subset_mode, _QUICK_VOCALS)
        self.assertEqual(self.settings.process.stem_focus, "vocal.vocals")

    def test_subset_removed_role_without_quick_export_offers_only_choose(self) -> None:
        self.section.configure_subset(
            stems=["vocals", "other", "bass"],
            show_quick_export=False,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            routes=(
                StemRoute(
                    StemId("vocals"),
                    StemRoleId("vocal.vocals"),
                    label="Vocals",
                    logical_primary=True,
                ),
                StemRoute(
                    StemId("other"),
                    StemRoleId("mix.instrumental"),
                    label="Instrumental",
                ),
                StemRoute(
                    StemId("bass"),
                    StemRoleId("instrument.bass"),
                    label="Bass",
                ),
            ),
        )

        self.assertTrue(self.section.require_refresh_repick("vocal.lead"))
        self.assertEqual(fetch(self.section._quick_row, "_uvr_combo_ids"), ["choose"])
        self.assertNotIn(
            _QUICK_INSTRUMENTAL,
            fetch(self.section._quick_row, "_uvr_combo_ids"),
        )
        self.assertNotIn(
            _QUICK_VOCALS,
            fetch(self.section._quick_row, "_uvr_combo_ids"),
        )
        self.section._on_quick_export_changed()
        self.assertTrue(self.section.repick_required)
        self.section._custom_dialog.present()
        self._drain_main_context()
        self.section._on_custom_stems_save()
        self.assertFalse(self.section.repick_required)
        self._drain_main_context()
        self.assertFalse(self.section._quick_row.get_visible())
        self.assertEqual(fetch(self.section._quick_row, "_uvr_combo_ids"), [])
        self.section.persist_to_settings()
        self.assertNotEqual(self.settings.process.stem_focus, "choose")

    def test_demucs_removed_role_selects_choose_until_explicit_repick(self) -> None:
        routes = (
            StemRoute(
                StemId("vocals"),
                StemRoleId("vocal.vocals"),
                label="Vocals",
                logical_primary=True,
            ),
            StemRoute(
                StemId("bass"),
                StemRoleId("instrument.bass"),
                label="Bass",
            ),
        )
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, "vocals", "bass"],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            routes=routes,
        )

        self.assertTrue(self.section.require_refresh_repick("vocal.lead"))
        self.assertEqual(get_combo_value(self.section._demucs_focus_row), "choose")
        self.assertTrue(self.section.selection_warning_row.get_visible())
        self.section._on_demucs_focus_changed()
        self.assertTrue(self.section.repick_required)
        self.section._on_demucs_export_changed()
        self.assertTrue(self.section.repick_required)
        set_combo_value(self.section._demucs_focus_row, "vocal.vocals")
        self.section._on_demucs_focus_changed()
        self.assertFalse(self.section.repick_required)
        self._drain_main_context()
        self.assertEqual(
            fetch(self.section._demucs_focus_row, "_uvr_combo_ids"),
            [_QUICK_ALL, "vocal.vocals", "instrument.bass"],
        )
        self.assertFalse(set_combo_value(self.section._demucs_focus_row, "choose"))
        self.section._on_demucs_focus_changed()
        self.section.persist_to_settings()
        self.assertEqual(get_combo_value(self.section._demucs_focus_row), "vocal.vocals")
        self.assertEqual(self.settings.demucs.stems, "vocals")
        self.assertNotEqual(self.settings.process.stem_focus, "choose")

    def test_exclusive_sync_persist_round_trip(self):
        self.settings.process.stem_focus = "vocal.vocals"
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertIn("Vocals", self.section.export_summary())
        self.section.persist_to_settings()
        self.assertEqual(self.settings.process.stem_focus, "vocal.vocals")

    def test_stem_focus_survives_switching_to_a_model_where_it_is_secondary(self) -> None:
        """The bug this whole feature exists to fix: picking "Instrumental
        Only" on a vocals-primary model, then switching to a model where
        the instrumental happens to be the *secondary* stem, must still
        export the instrumental -- not silently flip to vocals."""
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        set_combo_value(self.section._exclusive_row, INST_STEM)
        self.section.persist_to_settings()
        self.assertEqual(self.settings.process.stem_focus, "mix.instrumental")

        # Switch to a model where Instrumental is now primary, Vocals secondary.
        self.section.configure_exclusive(
            primary_stem=INST_STEM,
            secondary_stem=VOCAL_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertEqual(self.settings.process.stem_focus, "mix.instrumental")
        self.assertIn("Instrumental", self.section.export_summary())

    def test_stem_focus_falls_back_to_all_for_an_unrelated_model(self) -> None:
        self.settings.process.stem_focus = INST_STEM
        self.section.configure_exclusive(
            primary_stem="noreverb",
            secondary_stem="reverb",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        # The preference stays parked, not discarded, for a future relevant model.
        self.assertEqual(self.settings.process.stem_focus, INST_STEM)

    def test_empty_stem_focus_exports_all(self) -> None:
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertIn("Exporting all outputs", self.section.export_summary())

    def test_persist_writes_stem_focus_from_the_chosen_stem(self) -> None:
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        set_combo_value(self.section._exclusive_row, VOCAL_STEM)
        self.section.persist_to_settings()
        self.assertEqual(self.settings.process.stem_focus, "vocal.vocals")

    def test_persist_all_clears_stem_focus(self) -> None:
        self.settings.process.stem_focus = VOCAL_STEM
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        set_combo_value(self.section._exclusive_row, _TOGGLE_ALL)
        self.section.persist_to_settings()
        self.assertEqual(self.settings.process.stem_focus, "")

    def test_subset_quick_instrumental_persist(self):
        self.settings.process.stem_focus = "mix.instrumental"
        self.settings["mdx_stems_selected"] = [VOCAL_STEM]
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertEqual(self.section._subset_mode, _QUICK_INSTRUMENTAL)
        self.assertFalse(self.section._subset._chips[VOCAL_STEM].get_active())
        self.assertFalse(self.section._subset.is_all_active())
        self.section.persist_to_settings()
        self.assertEqual(self.settings["mdx_stems_selected"], [VOCAL_STEM])
        self.assertEqual(self.settings.process.stem_focus, "mix.instrumental")

    def test_subset_quick_vocals_highlights_vocal_chip(self):
        self.settings.process.stem_focus = "vocal.vocals"
        self.settings["mdx_stems_selected"] = [VOCAL_STEM]
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertEqual(self.section._subset_mode, _QUICK_VOCALS)
        self.assertTrue(self.section._subset._chips[VOCAL_STEM].get_active())

    def test_subset_rows_use_reviewed_route_ids_and_labels(self) -> None:
        routes = (
            StemRoute(
                StemId("nativeLead"),
                StemRoleId("vocal.lead"),
                label="Lead Vocals",
                logical_primary=True,
            ),
            StemRoute(
                StemId("nativeBacking"),
                StemRoleId("vocal.backing"),
                label="Backing Vocals",
            ),
        )
        self.section.configure_subset(
            stems=["nativeLead", "nativeBacking"],
            show_quick_export=False,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
            routes=routes,
        )

        self.assertEqual(self.section._subset_token_id("nativeLead"), "vocal.lead")
        self.assertEqual(self.section._subset_label("nativeLead"), "Lead Vocals")
        self.section._subset_mode = "custom"
        self.section._set_custom_selection({"vocal.lead"})
        self.assertEqual(self.section.export_summary(), "Exporting Lead Vocals")

    def test_subset_quick_instrumental_ui_clears_chips(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section._quick_export.set_active(_QUICK_INSTRUMENTAL)
        self.section._on_quick_export_changed()
        self.assertFalse(self.section._subset._chips[VOCAL_STEM].get_active())
        self.assertFalse(self.section._subset.is_all_active())

    def test_subset_custom_single_stem_persist(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section._subset_mode = "custom"
        self.section._subset.rebuild([VOCAL_STEM, BASS_STEM, DRUM_STEM])
        self.section._subset.set_selection(
            {BASS_STEM}, full_stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM]
        )
        self.section.persist_to_settings()
        self.assertEqual(self.settings["mdx_stems_selected"], [BASS_STEM])
        self.assertEqual(self.settings["mdx_stems"], BASS_STEM)

    def test_subset_all_stems_persist(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section._subset_mode = _QUICK_ALL
        self.section.persist_to_settings()
        self.assertEqual(self.settings["mdx_stems"], ALL_STEMS)
        self.assertEqual(self.settings["mdx_stems_selected"], [])

    def test_demucs_all_stems_hides_export_filter(self):
        self.settings["demucs_stems"] = ALL_STEMS
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, "focus_instrumental", "focus_vocals", BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertFalse(self.section._demucs_export_block.get_visible())

    def test_demucs_bass_focus_defaults_primary_only(self):
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            has_model=True,
        )
        self.section._demucs_focus.set_active_name(BASS_STEM)
        self.section._on_demucs_focus_changed()
        self.section.persist_to_settings()
        self.assertEqual(self.settings["demucs_stems"], BASS_STEM)
        self.assertEqual(self.settings.process.stem_focus, "instrument.bass")

    def test_subset_hides_quick_export_when_disabled(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            show_quick_export=False,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.assertFalse(self.section._quick_block.get_visible())
        self.assertTrue(self.section._subset_block.get_visible())

    def test_mode_switch_hides_rows(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.assertTrue(self.section._subset_block.get_visible())
        self.assertFalse(self.section._exclusive_block.get_visible())
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.assertFalse(self.section._subset_block.get_visible())
        self.assertTrue(self.section._exclusive_block.get_visible())

    def test_configure_exclusive_accepts_and_stores_confidence_kwargs(self) -> None:
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
            is_karaoke=True,
            is_karaoke_curated=True,
            is_bv=False,
            stem_count=2,
        )
        self.assertTrue(self.section._exclusive_is_karaoke)
        self.assertTrue(self.section._exclusive_is_karaoke_curated)
        self.assertFalse(self.section._exclusive_is_bv)
        self.assertEqual(self.section._exclusive_stem_count, 2)

    def test_configure_exclusive_confidence_kwargs_default_safely(self) -> None:
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.assertFalse(self.section._exclusive_is_karaoke)
        self.assertFalse(self.section._exclusive_is_karaoke_curated)
        self.assertFalse(self.section._exclusive_is_bv)
        self.assertEqual(self.section._exclusive_stem_count, 2)

    def test_unrecognized_stem_focus_does_not_flip_on_resync_of_the_same_model(self) -> None:
        """Regression: two different unrecognized stems on the same model
        (e.g. a DeReverb pair) must not collide on the shared
        StemBucket.UNKNOWN anchor -- picking "reverb only" and then
        re-resolving the SAME model (e.g. tab reactivation) must not
        silently flip the pick to "noreverb only"."""
        routes = _reviewed_target_routes("mdx:bs_dereverb_2250_anvuew", "noreverb")
        self.section.configure_exclusive(
            primary_stem="noreverb",
            secondary_stem="reverb",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
            routes=routes,
        )
        self.section.sync_from_settings()
        set_combo_value(self.section._exclusive_row, "effect.reverb.removed")
        self.section.persist_to_settings()
        self.assertEqual(self.settings.process.stem_focus, "effect.reverb.removed")

        self.section.configure_exclusive(
            primary_stem="noreverb",
            secondary_stem="reverb",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
            routes=routes,
        )
        self.section.sync_from_settings()
        self.assertEqual(self.settings.process.stem_focus, "effect.reverb.removed")
        self.assertIn("reverb", self.section.export_summary().casefold())

    def test_two_different_unrecognized_stem_models_do_not_collide(self) -> None:
        """Before the fix, every unrecognized stem bucketed to the same
        StemBucket.UNKNOWN, so a focus set on one DeReverb-style model
        would false-match an unrelated DeEcho-style model."""
        routes = _reviewed_target_routes("mdx:bs_dereverb_2250_anvuew", "noreverb")
        self.section.configure_exclusive(
            primary_stem="noreverb",
            secondary_stem="reverb",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
            routes=routes,
        )
        self.section.sync_from_settings()
        set_combo_value(self.section._exclusive_row, "effect.reverb.removed")
        self.section.persist_to_settings()

        self.section.configure_exclusive(
            primary_stem="noecho",
            secondary_stem="echo",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertEqual(self.settings.process.stem_focus, "effect.reverb.removed")
        self.assertIn("Exporting all outputs", self.section.export_summary())

    def test_subset_reviewed_vocals_focus_matches_vocals_quick(self) -> None:
        self.settings.process.stem_focus = "vocal.vocals"
        self.settings["mdx_stems_selected"] = ["vocals"]
        self.section.configure_subset(
            stems=["vocals", "other"],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertEqual(self.section._subset_mode, _QUICK_VOCALS)

    def test_exclusive_lowercase_focus_matches_yaml_vocals(self) -> None:
        self.settings.process.stem_focus = "vocal.vocals"
        self.section.configure_exclusive(
            primary_stem="other",
            secondary_stem="vocals",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertIn("Vocals", self.section.export_summary())

    def test_ensemble_karaoke_vocals_focus_selects_lead(self) -> None:
        from bundled.constants import INST_WITH_BACKING_VOCALS_STEM, LEAD_VOCAL_STEM_LABEL

        self.settings.process.stem_focus = "vocal.lead"
        self.section.configure_exclusive(
            primary_stem=LEAD_VOCAL_STEM_LABEL,
            secondary_stem=INST_WITH_BACKING_VOCALS_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
            routes=(
                StemRoute(
                    None,
                    StemRoleId("vocal.lead"),
                    label=LEAD_VOCAL_STEM_LABEL,
                    filename_tag="Lead Vocals",
                    logical_primary=True,
                ),
                StemRoute(
                    None,
                    StemRoleId("mix.instrumental_with_backing_vocals"),
                    label=INST_WITH_BACKING_VOCALS_STEM,
                    filename_tag="Instrumental with Backing Vocals",
                ),
            ),
        )
        self.section.sync_from_settings()
        self.assertIn("Lead Vocal", self.section.export_summary())

    def test_ensemble_other_pair_instrumental_focus_does_not_select_other(self) -> None:
        from bundled.constants import NO_OTHER_STEM, OTHER_STEM
        from core.stems import StemBucket

        self.settings.process.stem_focus = StemBucket.INSTRUMENTAL.value
        self.section.configure_exclusive(
            primary_stem=OTHER_STEM,
            secondary_stem=NO_OTHER_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertIn("Exporting all outputs", self.section.export_summary())

    def test_demucs_reviewed_vocals_focus_matches_vocals_chip(self) -> None:
        self.settings["demucs_stems"] = "vocals"
        self.settings.process.stem_focus = "vocal.vocals"
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, "focus_instrumental", "focus_vocals", BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertEqual(self.section._demucs_active_name(), _FOCUS_VOCALS)

    def test_demucs_native_pick_replaces_stale_focus(self) -> None:
        self.settings.process.stem_focus = VOCAL_STEM
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, BASS_STEM, DRUM_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            has_model=True,
        )
        set_combo_value(self.section._demucs_focus_row, BASS_STEM)
        self.section._update_demucs_export_visibility(from_settings=False)
        set_combo_value(
            self.section._demucs_export_row,
            BASS_STEM,
        )
        self.section.persist_to_settings()
        self.assertEqual(self.settings.process.stem_focus, "instrument.bass")

    def test_demucs_complement_pick_persists_complement_identity(self) -> None:
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            has_model=True,
        )
        set_combo_value(self.section._demucs_focus_row, BASS_STEM)
        self.section._update_demucs_export_visibility(from_settings=False)
        set_combo_value(
            self.section._demucs_export_row,
            "raw:no bass",
        )
        self.section.persist_to_settings()
        self.assertEqual(self.settings.process.stem_focus, "instrument.bass.removed")

    def test_demucs_all_clears_stale_focus(self) -> None:
        self.settings.process.stem_focus = VOCAL_STEM
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            has_model=True,
        )
        set_combo_value(self.section._demucs_focus_row, _QUICK_ALL)
        self.section.persist_to_settings()
        self.assertEqual(self.settings.process.stem_focus, "")


class StemFocusTagTests(unittest.TestCase):
    def test_recognized_stem_returns_bucket_tag(self) -> None:
        self.assertEqual(
            _stem_focus_tag(
                "vocals", stem_count=2, is_karaoke=False, is_karaoke_curated=False, is_bv=False
            ),
            VOCAL_STEM,
        )

    def test_unrecognized_stem_returns_a_raw_name_tag(self) -> None:
        self.assertEqual(
            _stem_focus_tag(
                "reverb", stem_count=2, is_karaoke=False, is_karaoke_curated=False, is_bv=False
            ),
            "raw:reverb",
        )

    def test_different_unrecognized_stems_get_different_tags(self) -> None:
        tag_a = _stem_focus_tag(
            "reverb", stem_count=2, is_karaoke=False, is_karaoke_curated=False, is_bv=False
        )
        tag_b = _stem_focus_tag(
            "echo", stem_count=2, is_karaoke=False, is_karaoke_curated=False, is_bv=False
        )
        self.assertNotEqual(tag_a, tag_b)


if __name__ == "__main__":
    unittest.main()
