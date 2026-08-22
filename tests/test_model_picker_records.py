"""Installed-record membership for the non-primary GUI model pickers."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

from bundled.constants import NO_MODEL
from core.model_identity import ModelArtifacts, ModelRecord


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
        with mock.patch(
            "core.model_identity.ModelIdentityService.records",
            return_value=tuple(records),
        ), mock.patch(
            "ui.widgets.vocal_split_row.set_combo_tag_values",
            side_effect=lambda _combo, items: values.extend(items),
        ), mock.patch(
            "ui.widgets.vocal_split_row.set_combo_value",
            side_effect=lambda _combo, value: selections.append(value),
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


class _FakeRow:
    def __init__(self, title: str = "", subtitle: str = "", **_kwargs: object) -> None:
        self.title = title
        self.subtitle = subtitle

    def set_title(self, value: str) -> None:
        self.title = value

    def set_subtitle(self, value: str) -> None:
        self.subtitle = value

    def add_prefix(self, _child: object) -> None:
        pass

    def set_activatable_widget(self, _child: object) -> None:
        pass


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

    def get_first_child(self) -> None:
        return None

    def append(self, row: _FakeRow) -> None:
        self.children.append(row)

    def invalidate_filter(self) -> None:
        pass


class EnsemblePickerTests(unittest.TestCase):
    def test_rows_are_installed_ids_with_family_disambiguation(self) -> None:
        from core.stems import EnsemblePair
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
        page._ensemble_pair = lambda: EnsemblePair.VOCALS_INSTRUMENTAL
        page._persist_selected_models = lambda: None
        page._update_models_dialog_status = lambda: None
        page._update_models_summary = lambda: None

        with mock.patch(
            "core.model_identity.ModelIdentityService.records",
            return_value=tuple(records),
        ), mock.patch.object(ensemble_window.Adw, "ActionRow", _FakeRow), mock.patch.object(
            ensemble_window.Gtk, "CheckButton", _FakeCheck
        ), mock.patch.object(ensemble_window, "stash"):
            page._rebuild_model_list([])

        self.assertEqual(
            [(row.title, row.subtitle) for row in page.models_listbox.children],
            [
                ("Shared display", "MDX-Net"),
                ("Shared display", "VR Arc"),
            ],
        )
        self.assertEqual(list(page._model_checks), ["mdx:shared", "vr:shared"])

    def test_write_gate_preserves_illegal_members_until_a_user_edit(self) -> None:
        from ui.ensemble.window import EnsemblePage

        page: Any = EnsemblePage.__new__(EnsemblePage)
        page.settings = SimpleNamespace(
            ensemble=SimpleNamespace(selected_models=["MDX-Net: legacy display"])
        )
        page._models_write_gated = True
        page._selected_model_tags = lambda: []

        EnsemblePage._persist_selected_models(page)

        self.assertEqual(
            page.settings.ensemble.selected_models,
            ["MDX-Net: legacy display"],
        )

    def test_rebuild_handles_an_unhashable_preserved_member(self) -> None:
        from core.stems import EnsemblePair
        from ui.ensemble import window as ensemble_window

        page: Any = ensemble_window.EnsemblePage.__new__(ensemble_window.EnsemblePage)
        page.models_listbox = _FakeListBox()
        page.context = SimpleNamespace(
            repo=SimpleNamespace(
                ensemble_model_list=lambda _settings, _pair: ["mdx:installed"]
            )
        )
        page.settings = SimpleNamespace(
            ensemble=SimpleNamespace(selected_models=[["invalid member"]])
        )
        page._ensemble_pair = lambda: EnsemblePair.VOCALS_INSTRUMENTAL
        page._update_models_dialog_status = lambda: None
        page._update_models_summary = lambda: None
        record = _record("mdx:installed", "Installed")

        try:
            with mock.patch(
                "core.model_identity.ModelIdentityService.records",
                return_value=(record,),
            ), mock.patch.object(
                ensemble_window.Adw, "ActionRow", _FakeRow
            ), mock.patch.object(
                ensemble_window.Gtk, "CheckButton", _FakeCheck
            ), mock.patch.object(ensemble_window, "stash"):
                page._rebuild_model_list(page.settings.ensemble.selected_models)
        except TypeError as exc:
            self.fail(f"preserved non-string ensemble member crashed the picker: {exc}")

        self.assertTrue(page._models_write_gated)
        self.assertEqual(
            page.settings.ensemble.selected_models,
            [["invalid member"]],
        )


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
