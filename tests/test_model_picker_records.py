"""Installed-record membership for the non-primary GUI model pickers."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from bundled.constants import NO_MODEL
from core.model_identity import ModelArtifacts, ModelRecord
from tests.private_gtk import require_private_gtk


def setUpModule() -> None:
    require_private_gtk()


def _record(
    model_id: str,
    display: str,
    *,
    installed: bool = True,
    identity_complete: bool = True,
    identity_error: str | None = None,
) -> ModelRecord:
    family, basename = model_id.split(":", 1)
    return ModelRecord(
        id=model_id,
        family=family,
        basename=basename,
        display=display,
        backend_name=basename,
        artifacts=ModelArtifacts(primary_filename=basename),
        installed=installed,
        identity_complete=identity_complete,
        identity_error=identity_error,
    )


class VocalSplitPickerTests(unittest.TestCase):
    def _populate(
        self,
        records: list[ModelRecord],
        eligible: list[str],
        *,
        stored: object = NO_MODEL,
    ) -> tuple[list[object], list[object]]:
        from ui.widgets.vocal_split_row import VocalSplitRow

        row: Any = VocalSplitRow.__new__(VocalSplitRow)
        row._repo = SimpleNamespace(karaoke_model_list=lambda _settings: eligible)
        row._settings = object()
        row._stored_splitter = stored
        row._syncing = False
        row.splitter_row = object()
        values: list[object] = []
        selections: list[object] = []
        with (
            mock.patch(
                "core.model_identity.ModelIdentityService.records",
                return_value=tuple(records),
            ),
            mock.patch(
                "ui.widgets.vocal_split_row.set_combo_tag_values",
                side_effect=lambda _combo, items: values.extend(items),
            ),
            mock.patch(
                "ui.widgets.vocal_split_row.set_combo_value",
                side_effect=lambda _combo, value: selections.append(value),
            ),
        ):
            VocalSplitRow._populate_models_now(row)
        return values, selections

    def test_duplicate_displays_remain_distinct_installed_ids(self) -> None:
        records = [
            _record("vr:first", "Karaoke Voice"),
            _record("vr:second", "Karaoke Voice"),
            _record("vr:catalogue", "Catalogue only", installed=False),
        ]

        values, _selections = self._populate(
            records,
            ["vr:first", "vr:catalogue", "vr:second"],
        )

        self.assertEqual(
            values,
            [
                NO_MODEL,
                ("vr:first", "Karaoke Voice"),
                ("vr:second", "Karaoke Voice"),
            ],
        )

    def test_absent_stored_text_is_not_added_as_a_selectable_row(self) -> None:
        values, selections = self._populate(
            [_record("vr:installed", "Installed")],
            ["vr:installed"],
            stored="VR Arc: deleted model",
        )

        self.assertEqual(values, [NO_MODEL, ("vr:installed", "Installed")])
        self.assertEqual(selections, [NO_MODEL])

    def test_unhashable_stored_value_is_visual_no_selection(self) -> None:
        try:
            values, selections = self._populate(
                [_record("vr:installed", "Installed")],
                ["vr:installed"],
                stored=["VR Arc: deleted model"],
            )
        except TypeError as exc:
            self.fail(f"preserved non-string splitter value crashed the picker: {exc}")

        self.assertEqual(values, [NO_MODEL, ("vr:installed", "Installed")])
        self.assertEqual(selections, [NO_MODEL])


class VocalSplitRefreshTests(unittest.TestCase):
    def test_refresh_preserves_exact_id_and_never_selects_a_new_arrival(self) -> None:
        from core.settings import Settings
        from ui.widgets.rows import get_combo_value
        from ui.widgets.vocal_split_row import VocalSplitRow

        eligible = ["vr:kept"]
        records = [_record("vr:kept", "Kept karaoke")]
        repo = SimpleNamespace(karaoke_model_list=lambda _settings: list(eligible))
        settings = Settings.defaults()
        settings.process.vocal_splitter = "vr:kept"
        settings.process.vocal_splitter_enabled = True

        with mock.patch(
            "core.model_identity.ModelIdentityService.records",
            side_effect=lambda: tuple(records),
        ):
            row = VocalSplitRow(repo, lambda: None)
            row.apply_from_settings(settings)
            row._populator._populate_now()

            records.append(_record("vr:new", "New karaoke"))
            eligible.append("vr:new")
            row.refresh_models()

        self.assertEqual(get_combo_value(row.splitter_row), "vr:kept")
        self.assertEqual(row._splitter_ids, {"vr:kept", "vr:new"})
        self.assertFalse(row._splitter_write_gated)

    def test_refresh_removed_id_stays_blocked_until_an_explicit_repick(self) -> None:
        from core.settings import Settings
        from ui.widgets.rows import get_combo_value
        from ui.widgets.vocal_split_row import VocalSplitRow

        eligible = ["vr:removed"]
        records = [_record("vr:removed", "Removed karaoke")]
        repo = SimpleNamespace(karaoke_model_list=lambda _settings: list(eligible))
        settings = Settings.defaults()
        settings.process.vocal_splitter = "vr:removed"
        settings.process.vocal_splitter_enabled = True

        with mock.patch(
            "core.model_identity.ModelIdentityService.records",
            side_effect=lambda: tuple(records),
        ):
            row = VocalSplitRow(repo, lambda: None)
            row.apply_from_settings(settings)
            row._populator._populate_now()
            eligible.clear()
            row.refresh_models()
            row.persist_to_settings(settings)
            row.apply_from_settings(settings)

        self.assertEqual(get_combo_value(row.splitter_row), NO_MODEL)
        self.assertTrue(row.repick_required)
        self.assertEqual(
            row.blocked_reason(),
            "Choose a vocal splitter model again after the model refresh",
        )
        self.assertTrue(row.splitter_warning_row.get_visible())
        self.assertIn("Pick a model", row.splitter_warning_row.get_subtitle() or "")
        self.assertEqual(settings.process.vocal_splitter, "vr:removed")
        self.assertTrue(settings.process.vocal_splitter_enabled)


class PickerVerboseLoggingTests(unittest.TestCase):
    def test_combo_population_logs_exact_display_and_basename_only_when_verbose(self) -> None:
        from core import debug_log, glib_log
        from ui.widgets import rows

        class FakeStringList:
            def __init__(self) -> None:
                self.values: list[str] = []

            def append(self, value: str) -> None:
                self.values.append(value)

        class FakeComboRow:
            def __init__(self) -> None:
                self.model: FakeStringList | None = None

            def get_title(self) -> str:
                return "Primary model"

            def set_model(self, model: FakeStringList) -> None:
                self.model = model

        emitted: list[str] = []
        old_domains = debug_log._DOMAINS
        old_normalized = debug_log._GMD_NORMALIZED
        try:
            debug_log._DOMAINS = None
            debug_log._GMD_NORMALIZED = False
            glib_log.set_emit_hook(lambda _domain, message, _level: emitted.append(message))
            with (
                mock.patch.dict(
                    os.environ,
                    {"G_MESSAGES_DEBUG": "uvr-model"},
                    clear=False,
                ),
                mock.patch.object(rows.Gtk, "StringList", FakeStringList),
                mock.patch.object(rows, "stash"),
            ):
                os.environ.pop("UVR_VERBOSE", None)
                rows.set_combo_tag_values(
                    cast(Any, FakeComboRow()),
                    [("vr:1_HP-UVR", "HP 1")],
                )
                self.assertEqual(emitted, [])

                os.environ["UVR_VERBOSE"] = "1"
                rows.set_combo_tag_values(
                    cast(Any, FakeComboRow()),
                    [("Choose Model", "Choose Model")],
                )
                self.assertEqual(emitted, [])

                rows.set_combo_tag_values(
                    cast(Any, FakeComboRow()),
                    [
                        ("Choose Model", "Choose Model"),
                        ("vr:1_HP-UVR", "HP 1"),
                        ("mdx:raw_name", "raw_name"),
                    ],
                )
        finally:
            os.environ.pop("UVR_VERBOSE", None)
            debug_log._DOMAINS = old_domains
            debug_log._GMD_NORMALIZED = old_normalized
            glib_log.set_emit_hook(None)

        self.assertEqual(
            emitted,
            [
                "picker surface='Primary model' entries=2 basename_displays=1",
                "picker surface='Primary model' id='vr:1_HP-UVR' "
                "basename='1_HP-UVR' display='HP 1' display_is_basename=False",
                "picker surface='Primary model' id='mdx:raw_name' "
                "basename='raw_name' display='raw_name' display_is_basename=True",
            ],
        )


class _FakeRow:
    def __init__(self, title: str = "", subtitle: str = "", **_kwargs: object) -> None:
        self.title = title
        self.subtitle = subtitle
        self._listbox: _FakeListBox | None = None

    def set_title(self, value: str) -> None:
        self.title = value

    def set_subtitle(self, value: str) -> None:
        self.subtitle = value

    def add_prefix(self, _child: object) -> None:
        pass

    def set_activatable_widget(self, _child: object) -> None:
        pass

    def get_next_sibling(self) -> _FakeRow | None:
        if self._listbox is None:
            return None
        index = self._listbox.children.index(self)
        if index + 1 >= len(self._listbox.children):
            return None
        return self._listbox.children[index + 1]


class _FakeCheck:
    def __init__(self, **_kwargs: object) -> None:
        self.active = False

    def set_active(self, value: bool) -> None:
        self.active = value

    def get_active(self) -> bool:
        return self.active

    def connect(self, *_args: object) -> None:
        pass


class _FakeListBox:
    def __init__(self) -> None:
        self.children: list[_FakeRow] = []

    def get_first_child(self) -> _FakeRow | None:
        return self.children[0] if self.children else None

    def append(self, row: _FakeRow) -> None:
        row._listbox = self
        self.children.append(row)

    def remove(self, row: _FakeRow) -> None:
        self.children.remove(row)
        row._listbox = None

    def invalidate_filter(self) -> None:
        pass


class EnsemblePickerTests(unittest.TestCase):
    def test_rebuild_passes_current_pair_id_to_repository(self) -> None:
        """The repository boundary receives persisted semantic IDs, not UI adapters."""
        from ui.ensemble import window as ensemble_window

        requested: list[object] = []
        page: Any = ensemble_window.EnsemblePage.__new__(ensemble_window.EnsemblePage)
        page.models_listbox = _FakeListBox()
        page.context = SimpleNamespace(
            repo=SimpleNamespace(
                ensemble_model_list=lambda _settings, pair: requested.append(pair) or []
            )
        )
        page.settings = SimpleNamespace(
            ensemble=SimpleNamespace(main_stem="pair.vocals_instrumental", selected_models=[])
        )
        page._ensemble_pair = lambda: "pair.vocals_instrumental"
        page._persist_selected_models = lambda: None
        page._update_models_dialog_status = lambda: None
        page._update_models_summary = lambda: None

        with (
            mock.patch("core.model_identity.ModelIdentityService.records", return_value=()),
            mock.patch.object(ensemble_window.Adw, "ActionRow", _FakeRow),
            mock.patch.object(ensemble_window, "stash"),
        ):
            page._rebuild_model_list([])

        self.assertEqual(requested, ["pair.vocals_instrumental"])

    def test_rows_are_installed_ids_with_family_disambiguation_and_verbose_trace(self) -> None:
        from core import debug_log, glib_log
        from ui.ensemble import window as ensemble_window

        records = [
            _record("vr:shared", "Shared display"),
            _record("mdx:shared", "Shared display"),
            _record("mdx:catalogue", "Catalogue only", installed=False),
        ]
        repo = SimpleNamespace(
            ensemble_model_list=lambda _settings, _pair: [
                "mdx:catalogue",
                "mdx:shared",
                "vr:shared",
            ]
        )
        page: Any = ensemble_window.EnsemblePage.__new__(ensemble_window.EnsemblePage)
        page.models_listbox = _FakeListBox()
        page.context = SimpleNamespace(repo=repo)
        page.settings = SimpleNamespace()
        page._ensemble_pair = lambda: "pair.vocals_instrumental"
        page._persist_selected_models = lambda: None
        page._update_models_dialog_status = lambda: None
        page._update_models_summary = lambda: None

        emitted: list[str] = []
        old_domains = debug_log._DOMAINS
        old_normalized = debug_log._GMD_NORMALIZED
        try:
            debug_log._DOMAINS = None
            debug_log._GMD_NORMALIZED = False
            glib_log.set_emit_hook(lambda _domain, message, _level: emitted.append(message))
            with (
                mock.patch.dict(
                    os.environ,
                    {"G_MESSAGES_DEBUG": "uvr-model", "UVR_VERBOSE": "1"},
                    clear=False,
                ),
                mock.patch(
                    "core.model_identity.ModelIdentityService.records",
                    return_value=tuple(records),
                ),
                mock.patch.object(ensemble_window.Adw, "ActionRow", _FakeRow),
                mock.patch.object(ensemble_window.Gtk, "CheckButton", _FakeCheck),
                mock.patch.object(ensemble_window, "stash"),
            ):
                page._rebuild_model_list([])
        finally:
            debug_log._DOMAINS = old_domains
            debug_log._GMD_NORMALIZED = old_normalized
            glib_log.set_emit_hook(None)

        self.assertEqual(
            [(row.title, row.subtitle) for row in page.models_listbox.children],
            [
                ("Shared display", "MDX-Net"),
                ("Shared display", "VR Arc"),
            ],
        )
        self.assertEqual(list(page._model_checks), ["mdx:shared", "vr:shared"])
        self.assertIn(
            "picker surface='Ensemble members (pair.vocals_instrumental)' "
            "entries=2 basename_displays=0",
            emitted,
        )
        self.assertIn(
            "picker surface='Ensemble members (pair.vocals_instrumental)' "
            "id='mdx:shared' basename='shared' display='Shared display' "
            "display_is_basename=False",
            emitted,
        )

    def test_flush_drops_illegal_members_and_keeps_checked_members(self) -> None:
        from ui.ensemble.window import EnsemblePage

        page: Any = EnsemblePage.__new__(EnsemblePage)
        page.settings = SimpleNamespace(
            ensemble=SimpleNamespace(selected_models=["MDX-Net: legacy display"])
        )
        page._models_write_gated = True
        page._model_checks = {"mdx:installed": _FakeCheck(active=True)}
        page._selected_model_tags = lambda: ["mdx:installed"]
        page._loading = True
        page._update_models_dialog_status = lambda: None
        page._update_models_summary = lambda: None
        page._rebuild_stem_only_toggles = lambda: None

        EnsemblePage._persist_selected_models(page)

        self.assertEqual(
            page.settings.ensemble.selected_models,
            ["mdx:installed"],
        )

        page._on_model_toggled(_FakeCheck())

        self.assertFalse(page._models_write_gated)
        self.assertEqual(
            page.settings.ensemble.selected_models,
            ["mdx:installed"],
        )

    def test_rebuild_handles_an_unhashable_preserved_member(self) -> None:
        from ui.ensemble import window as ensemble_window

        page: Any = ensemble_window.EnsemblePage.__new__(ensemble_window.EnsemblePage)
        page.models_listbox = _FakeListBox()
        page.context = SimpleNamespace(
            repo=SimpleNamespace(ensemble_model_list=lambda _settings, _pair: ["mdx:installed"])
        )
        page.settings = SimpleNamespace(
            ensemble=SimpleNamespace(selected_models=[["invalid member"]])
        )
        page._ensemble_pair = lambda: "pair.vocals_instrumental"
        page._update_models_dialog_status = lambda: None
        page._update_models_summary = lambda: None
        record = _record("mdx:installed", "Installed")

        try:
            with (
                mock.patch(
                    "core.model_identity.ModelIdentityService.records",
                    return_value=(record,),
                ),
                mock.patch.object(ensemble_window.Adw, "ActionRow", _FakeRow),
                mock.patch.object(ensemble_window.Gtk, "CheckButton", _FakeCheck),
                mock.patch.object(ensemble_window, "stash"),
            ):
                page._rebuild_model_list(page.settings.ensemble.selected_models)
        except TypeError as exc:
            self.fail(f"preserved non-string ensemble member crashed the picker: {exc}")

        self.assertTrue(page._models_write_gated)
        self.assertEqual(page.settings.ensemble.selected_models, [])

    def test_repeated_activation_does_not_restore_dropped_gated_members(self) -> None:
        from core.settings import Settings
        from ui.ensemble import window as ensemble_window

        stored = ["mdx:installed", "mdx:uninstalled"]
        settings = Settings()
        settings.ensemble.selected_models = list(stored)
        page: Any = ensemble_window.EnsemblePage.__new__(ensemble_window.EnsemblePage)
        page.models_listbox = _FakeListBox()
        page.context = SimpleNamespace(
            repo=SimpleNamespace(ensemble_model_list=lambda _settings, _pair: ["mdx:installed"])
        )
        page.settings = settings
        page._ensemble_pair = lambda: "pair.vocals_instrumental"
        page._update_models_dialog_status = lambda: None
        page._update_models_summary = lambda: None
        page._sync_shared_from_settings = lambda: None
        record = _record("mdx:installed", "Installed")

        with (
            mock.patch(
                "core.model_identity.ModelIdentityService.records",
                return_value=(record,),
            ),
            mock.patch.object(ensemble_window.Adw, "ActionRow", _FakeRow),
            mock.patch.object(ensemble_window.Gtk, "CheckButton", _FakeCheck),
            mock.patch.object(ensemble_window, "stash"),
        ):
            page._rebuild_model_list(list(stored))
            page.on_activated()
            page.on_activated()

        self.assertFalse(page._models_write_gated)
        self.assertEqual(page.settings.ensemble.selected_models, ["mdx:installed"])
        self.assertEqual(page._selected_model_tags(), ["mdx:installed"])
        self.assertEqual(len(page.models_listbox.children), 1)

    def test_reopening_models_dialog_does_not_restore_dropped_gated_members(self) -> None:
        from core.settings import Settings
        from ui.ensemble import window as ensemble_window

        stored = ["mdx:installed", "MDX-Net: legacy display"]
        settings = Settings()
        settings.ensemble.selected_models = list(stored)
        page: Any = ensemble_window.EnsemblePage.__new__(ensemble_window.EnsemblePage)
        page.models_listbox = _FakeListBox()
        page.context = SimpleNamespace(
            repo=SimpleNamespace(ensemble_model_list=lambda _settings, _pair: ["mdx:installed"])
        )
        page.settings = settings
        page._ensemble_pair = lambda: "pair.vocals_instrumental"
        page._update_models_dialog_status = lambda: None
        page._update_models_summary = lambda: None
        page.models_dialog = object()
        page.window = object()
        record = _record("mdx:installed", "Installed")

        with (
            mock.patch(
                "core.model_identity.ModelIdentityService.records",
                return_value=(record,),
            ),
            mock.patch.object(ensemble_window.Adw, "ActionRow", _FakeRow),
            mock.patch.object(ensemble_window.Gtk, "CheckButton", _FakeCheck),
            mock.patch.object(ensemble_window, "stash"),
            mock.patch.object(ensemble_window, "present_modal_dialog"),
        ):
            page._rebuild_model_list(list(stored))
            page._open_models_dialog()
            page._open_models_dialog()

        self.assertFalse(page._models_write_gated)
        self.assertEqual(page.settings.ensemble.selected_models, ["mdx:installed"])
        self.assertEqual(page._selected_model_tags(), ["mdx:installed"])

    def test_pair_ineligible_member_is_dropped_at_persist_boundary(self) -> None:
        from core.settings import Settings
        from ui.ensemble import window as ensemble_window

        stored = ["mdx:first", "mdx:second", "mdx:ineligible"]
        settings = Settings()
        settings.ensemble.selected_models = list(stored)
        page: Any = ensemble_window.EnsemblePage.__new__(ensemble_window.EnsemblePage)
        page.models_listbox = _FakeListBox()
        page.context = SimpleNamespace(
            repo=SimpleNamespace(
                ensemble_model_list=lambda _settings, _pair: [
                    "mdx:first",
                    "mdx:second",
                ]
            )
        )
        page.settings = settings
        page._ensemble_pair = lambda: "pair.vocals_instrumental"
        page._update_models_dialog_status = lambda: None
        page._update_models_summary = lambda: None
        records = tuple(_record(model_id, model_id) for model_id in stored)

        with (
            mock.patch(
                "core.model_identity.ModelIdentityService.records",
                return_value=records,
            ),
            mock.patch.object(ensemble_window.Adw, "ActionRow", _FakeRow),
            mock.patch.object(ensemble_window.Gtk, "CheckButton", _FakeCheck),
            mock.patch.object(ensemble_window, "stash"),
        ):
            page._rebuild_model_list(list(stored))
            page._rebuild_model_list(list(settings.ensemble.selected_models))

        self.assertFalse(page._models_write_gated)
        self.assertEqual(settings.ensemble.selected_models, ["mdx:first", "mdx:second"])
        warnings = page._ensemble_member_warnings
        self.assertEqual(warnings, ())

    def test_refresh_lists_a_newly_installed_gated_member_without_selecting_it(self) -> None:
        """A repository refresh may reveal an ID, but only a click selects it."""
        from core.settings import Settings
        from ui.ensemble import window as ensemble_window

        missing_id = "mdx:later"
        settings = Settings()
        settings.ensemble.selected_models = ["mdx:installed", missing_id]
        eligible = ["mdx:installed"]
        records = [_record("mdx:installed", "Installed")]
        page: Any = ensemble_window.EnsemblePage.__new__(ensemble_window.EnsemblePage)
        page.models_listbox = _FakeListBox()
        page.context = SimpleNamespace(
            repo=SimpleNamespace(ensemble_model_list=lambda _settings, _pair: list(eligible))
        )
        page.settings = settings
        page._ensemble_pair = lambda: "pair.vocals_instrumental"
        page._update_models_dialog_status = lambda: None
        page._update_models_summary = lambda: None

        with (
            mock.patch(
                "core.model_identity.ModelIdentityService.records",
                side_effect=lambda: tuple(records),
            ),
            mock.patch.object(ensemble_window.Adw, "ActionRow", _FakeRow),
            mock.patch.object(ensemble_window.Gtk, "CheckButton", _FakeCheck),
            mock.patch.object(ensemble_window, "stash"),
        ):
            page._rebuild_model_list(list(settings.ensemble.selected_models))
            self.assertTrue(page._models_write_gated)

            records.append(_record(missing_id, "Arrived Later"))
            eligible.append(missing_id)
            page._rebuild_model_list(list(settings.ensemble.selected_models))

        self.assertIn(missing_id, page._model_checks)
        self.assertFalse(page._model_checks[missing_id].get_active())
        self.assertFalse(page._models_write_gated)
        self.assertEqual(settings.ensemble.selected_models, ["mdx:installed"])


class _FakeControl:
    def __init__(self, *, active: bool = False) -> None:
        self.active = active
        self.sensitive = True

    def get_active(self) -> bool:
        return self.active

    def set_sensitive(self, value: bool) -> None:
        self.sensitive = value


class VocalSplitPickerGateTests(unittest.TestCase):
    def _gated_row(self, stored: str) -> tuple[Any, Any]:
        from core.settings import Settings
        from ui.widgets.vocal_split_row import VocalSplitRow

        settings = Settings()
        settings.process.vocal_splitter = stored
        row: Any = VocalSplitRow.__new__(VocalSplitRow)
        row._syncing = False
        row._settings = settings
        row._stored_splitter = stored
        row._splitter_write_gated = True
        row._populator = SimpleNamespace(ready=True)
        row.split_switch = _FakeControl(active=True)
        row.splitter_row = _FakeControl()
        row.save_inst_switch = _FakeControl()
        row.deverb_switch = _FakeControl()
        row.deverb_row = _FakeControl()
        row.refresh_summary = lambda: None
        row._on_changed = lambda: None
        return row, settings

    def test_every_non_picker_signal_flushes_each_gated_stored_value(self) -> None:
        from ui.widgets import vocal_split_row

        for stored in ("VR Arc: legacy display", "vr:uninstalled"):
            for emitter_name in (
                "split_switch",
                "save_inst_switch",
                "deverb_switch",
                "deverb_row",
            ):
                with self.subTest(stored=stored, emitter=emitter_name):
                    row, settings = self._gated_row(stored)
                    emitter = getattr(row, emitter_name)
                    emitter.active = True
                    with mock.patch.object(
                        vocal_split_row,
                        "get_combo_value",
                        side_effect=lambda control, splitter=row.splitter_row: (
                            NO_MODEL if control is splitter else "Main Vocals Only"
                        ),
                    ):
                        row._on_row_changed(emitter)

                    self.assertTrue(row._splitter_write_gated)
                    self.assertEqual(row._stored_splitter, stored)
                    self.assertEqual(settings.process.vocal_splitter, stored)
                    self.assertTrue(settings.process.vocal_splitter_enabled)

    def test_picker_signal_replaces_the_gated_stored_value(self) -> None:
        from ui.widgets import vocal_split_row

        row, settings = self._gated_row("vr:uninstalled")
        with mock.patch.object(
            vocal_split_row,
            "get_combo_value",
            side_effect=lambda control: (
                "vr:installed" if control is row.splitter_row else "Main Vocals Only"
            ),
        ):
            row._on_row_changed(row.splitter_row)

        self.assertFalse(row._splitter_write_gated)
        self.assertEqual(row._stored_splitter, "vr:installed")
        self.assertEqual(settings.process.vocal_splitter, "vr:installed")


class _FakeBanner:
    def __init__(self) -> None:
        self.revealed = False
        self.title = ""

    def set_revealed(self, value: bool) -> None:
        self.revealed = value

    def set_title(self, value: str) -> None:
        self.title = value


class DemucsIdentityBannerTests(unittest.TestCase):
    def test_incomplete_selected_record_reveals_its_identity_error(self) -> None:
        from ui.views.demucs import DemucsView

        record = _record(
            "demucs:loose-th",
            "Loose TH",
            identity_complete=False,
            identity_error="unknown Demucs version or source layout for loose.th",
        )
        view: Any = DemucsView.__new__(DemucsView)
        view.context = SimpleNamespace(repo=object())
        view.identity_banner = _FakeBanner()
        view.selected_model = lambda: record.id

        with mock.patch(
            "core.model_identity.ModelIdentityService.records",
            return_value=(record,),
        ):
            DemucsView._on_model_resolved(view, None)

        self.assertTrue(view.identity_banner.revealed)
        self.assertIn("unknown Demucs version or source layout", view.identity_banner.title)

    def test_banner_hides_once_the_selected_identity_is_complete(self) -> None:
        from ui.views.demucs import DemucsView

        record = _record("demucs:configured", "Configured")
        view: Any = DemucsView.__new__(DemucsView)
        view.context = SimpleNamespace(repo=object())
        view.identity_banner = _FakeBanner()
        view.identity_banner.revealed = True
        view.selected_model = lambda: record.id

        with mock.patch(
            "core.model_identity.ModelIdentityService.records",
            return_value=(record,),
        ):
            DemucsView._on_model_resolved(view, None)

        self.assertFalse(view.identity_banner.revealed)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class DemucsIdentityBannerGtkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.model-picker-banner")
        cls._app.register()

    def test_method_view_constructs_a_persistent_adw_banner(self) -> None:
        from gi.repository import Adw

        from core.model_repository import ModelRepository
        from core.settings import Settings
        from ui.views.demucs import DemucsView

        context = SimpleNamespace(settings=Settings.defaults(), repo=ModelRepository())
        view: Any = DemucsView(context, lambda: None)

        self.assertIsInstance(view.identity_banner, Adw.Banner)
        self.assertFalse(view.identity_banner.get_revealed())


if __name__ == "__main__":
    unittest.main()


class EnsembleRefreshLifecycleTests(unittest.TestCase):
    """`EnsemblePage.refresh_models` must repaint an open dialog.

    Marking dirty and waiting for `on_activated` is right for a page nobody is
    looking at -- rebuilding resolves `ensemble_model_list`, which hashes
    checkpoints. But when the member dialog is already mapped, the user is
    staring at the stale list, so it has to rebuild now.
    """

    def _page(self, *, mapped: bool) -> Any:
        from ui.ensemble.window import EnsemblePage

        page: Any = EnsemblePage.__new__(EnsemblePage)
        page.vocal_split_row = mock.MagicMock()
        page._models_dirty = False
        page._models_write_gated = False
        page._rebuilds = []
        page._rebuild_model_list = lambda members: page._rebuilds.append(list(members))
        page._model_members_for_rebuild = lambda: ["mdx:a", "mdx:b"]
        page.models_dialog = mock.MagicMock()
        page.models_dialog.get_mapped.return_value = mapped
        return page

    def test_rebuilds_immediately_when_the_dialog_is_mapped(self) -> None:
        from ui.ensemble.window import EnsemblePage

        page = self._page(mapped=True)

        EnsemblePage.refresh_models(page)

        self.assertEqual(page._rebuilds, [["mdx:a", "mdx:b"]])
        page.vocal_split_row.refresh_models.assert_called_once_with()

    def test_clears_the_dirty_flag_after_rebuilding(self) -> None:
        from ui.ensemble.window import EnsemblePage

        page = self._page(mapped=True)
        page._models_dirty = True

        EnsemblePage.refresh_models(page)

        self.assertFalse(page._models_dirty)

    def test_marks_dirty_without_rebuilding_when_inactive(self) -> None:
        from ui.ensemble.window import EnsemblePage

        page = self._page(mapped=False)

        EnsemblePage.refresh_models(page)

        self.assertEqual(page._rebuilds, [])
        self.assertTrue(page._models_dirty)
        page.vocal_split_row.refresh_models.assert_called_once_with()

    def test_a_partially_built_page_does_not_raise(self) -> None:
        """A refresh can arrive before the dialog exists."""
        from ui.ensemble.window import EnsemblePage

        page = self._page(mapped=False)
        del page.models_dialog

        EnsemblePage.refresh_models(page)

        self.assertTrue(page._models_dirty)
        self.assertEqual(page._rebuilds, [])

    def test_write_gated_members_survive_an_immediate_rebuild(self) -> None:
        """The gate feeds stored members, not the live checklist."""
        from ui.ensemble.window import EnsemblePage

        page = self._page(mapped=True)
        page._models_write_gated = True
        page.settings = SimpleNamespace(
            ensemble=SimpleNamespace(selected_models=["MDX-Net: legacy display"])
        )
        page._model_checks = [object()]
        page._selected_model_tags = lambda: ["mdx:installed"]
        page._model_members_for_rebuild = lambda: EnsemblePage._model_members_for_rebuild(page)

        EnsemblePage.refresh_models(page)

        self.assertEqual(page._rebuilds, [["MDX-Net: legacy display"]])
        self.assertTrue(page._models_write_gated)


class EnsemblePairRefreshTests(unittest.TestCase):
    def _page(self, pair_id: str, eligible: dict[str, list[str]]) -> Any:
        from core.settings import Settings
        from ui.ensemble.window import EnsemblePage

        page: Any = EnsemblePage.__new__(EnsemblePage)
        page.settings = Settings.defaults()
        page.settings.ensemble.main_stem = pair_id
        page.context = SimpleNamespace(
            repo=SimpleNamespace(
                ensemble_model_list=lambda _settings, requested: eligible.get(requested, [])
            )
        )
        page.main_stem_row = object()
        page._loading = False
        page._pair_repick_warning = ""
        page._update_ensemble_banner = mock.Mock()
        return page

    def test_refresh_preserves_a_still_eligible_exact_pair_id(self) -> None:
        from ui.ensemble import window as ensemble_window

        eligible = {"pair.center_side": ["mdx:center", "mdx:side"]}
        page = self._page("pair.center_side", eligible)
        selected: list[str] = []

        with (
            mock.patch.object(ensemble_window, "set_combo_tag_values"),
            mock.patch.object(
                ensemble_window,
                "set_combo_value",
                side_effect=lambda _row, value: selected.append(value),
            ),
        ):
            page._refresh_pair_choices()

        self.assertEqual(page.settings.ensemble.main_stem, "pair.center_side")
        self.assertEqual(selected, ["pair.center_side"])
        self.assertEqual(page._pair_repick_warning, "")

    def test_refresh_removed_pair_resets_to_choose_with_repick_warning(self) -> None:
        from ui.ensemble import window as ensemble_window

        page = self._page(
            "pair.center_side",
            {"pair.center_side": ["mdx:only-one"]},
        )
        selected: list[str] = []

        with (
            mock.patch.object(ensemble_window, "set_combo_tag_values"),
            mock.patch.object(
                ensemble_window,
                "set_combo_value",
                side_effect=lambda _row, value: selected.append(value),
            ),
        ):
            page._refresh_pair_choices()

        self.assertEqual(page.settings.ensemble.main_stem, "")
        self.assertEqual(selected, [""])
        self.assertIn("Choose a stem pair again", page._pair_repick_warning)

    def test_refresh_unknown_removed_pair_id_requires_explicit_repick(self) -> None:
        from ui.ensemble import window as ensemble_window

        page = self._page("pair.removed_from_registry", {})
        selected: list[str] = []

        with (
            mock.patch.object(ensemble_window, "set_combo_tag_values"),
            mock.patch.object(
                ensemble_window,
                "set_combo_value",
                side_effect=lambda _row, value: selected.append(value),
            ),
        ):
            page._refresh_pair_choices()

        self.assertEqual(page.settings.ensemble.main_stem, "")
        self.assertEqual(selected, [""])
        self.assertIn("pair.removed_from_registry", page._pair_repick_warning)
        self.assertIn("Choose a stem pair again", page._pair_repick_warning)

        selected.clear()
        with (
            mock.patch.object(ensemble_window, "set_combo_tag_values"),
            mock.patch.object(
                ensemble_window,
                "set_combo_value",
                side_effect=lambda _row, value: selected.append(value),
            ),
        ):
            page._refresh_pair_choices()

        self.assertEqual(selected, [""])
        self.assertIn("pair.removed_from_registry", page._pair_repick_warning)

    def test_newly_eligible_pair_becomes_visible_without_selection(self) -> None:
        from ui.ensemble import window as ensemble_window

        page = self._page(
            "",
            {"pair.karaoke": ["mdx:lead", "vr:accompaniment"]},
        )
        rendered: list[list[tuple[str, str]]] = []
        selected: list[str] = []

        with (
            mock.patch.object(
                ensemble_window,
                "set_combo_tag_values",
                side_effect=lambda _row, values: rendered.append(list(values)),
            ),
            mock.patch.object(
                ensemble_window,
                "set_combo_value",
                side_effect=lambda _row, value: selected.append(value),
            ),
        ):
            page._refresh_pair_choices()

        self.assertIn(
            ("pair.karaoke", "Instrumental with Backing Vocals/Lead Vocals"),
            rendered[0],
        )
        self.assertEqual(page.settings.ensemble.main_stem, "")
        self.assertEqual(selected, [""])
