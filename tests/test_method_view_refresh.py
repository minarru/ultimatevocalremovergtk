"""An expander that is already open must repopulate on refresh.

`refresh_models` only cleared the latches; repopulation hung entirely off
`notify::expanded`, and GObject emits that only when the property actually
changes. So an expander the user had already opened when a download landed kept
showing the old model list until it was collapsed and reopened.
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

from bundled.constants import CHOOSE_MODEL, DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE
from core.model_identity import ModelArtifacts, ModelRecord
from ui.views.base import MethodView
from ui.widgets.lazy_populate import LazyPopulator


class _Expander:
    """Stands in for an Adw.ExpanderRow; only get_expanded() is consulted."""

    def __init__(self, expanded: bool) -> None:
        self._expanded = expanded

    def get_expanded(self) -> bool:
        return self._expanded


def _view(*, secondary: bool | None = None, preproc: bool | None = None) -> Any:
    # Bare instance: MethodView.__init__ builds real GTK rows. Typed Any so the
    # expander stubs below can stand in for Adw.ExpanderRow.
    view: Any = MethodView.__new__(MethodView)
    view._model_combos = []
    view._populating_models = False
    view.populates = 0
    if secondary is not None:
        view.secondary_expander = _Expander(secondary)
    if preproc is not None:
        view.preproc_expander = _Expander(preproc)

    def populate() -> None:
        view.populates += 1

    view._populator = LazyPopulator(
        is_expanded=lambda: MethodView._model_combo_section_open(view),
        populate=populate,
    )
    return view


class SectionOpenTests(unittest.TestCase):
    def test_either_expander_counts_as_open(self) -> None:
        """One latch covers both, so opening one populates the other's combos."""
        self.assertTrue(MethodView._model_combo_section_open(_view(secondary=True)))
        self.assertTrue(
            MethodView._model_combo_section_open(_view(secondary=False, preproc=True))
        )

    def test_all_collapsed_is_closed(self) -> None:
        view = _view(secondary=False, preproc=False)
        self.assertFalse(MethodView._model_combo_section_open(view))

    def test_view_without_expanders_is_closed(self) -> None:
        """VR/MDX views have no pre-process expander; some have neither."""
        self.assertFalse(MethodView._model_combo_section_open(_view()))


class RefreshModelsTests(unittest.TestCase):
    def _refreshable_view(self, **kwargs: Any) -> Any:
        view = _view(**kwargs)
        view._loading = False
        view.populate_models = mock.MagicMock()
        view.update_stem_labels = mock.MagicMock()
        return view

    def test_refresh_repopulates_an_open_expander(self) -> None:
        view = self._refreshable_view(secondary=True)
        view._populator.ensure()
        self.assertEqual(view.populates, 1)

        with mock.patch(
            "ui.widgets.lazy_populate.idle_on_main", side_effect=lambda fn, *a, **k: fn()
        ):
            MethodView.refresh_models(view)

        view.populate_models.assert_called_once_with()
        self.assertEqual(view.populates, 2, "an open expander must re-resolve")

    def test_refresh_defers_the_repopulate_to_idle(self) -> None:
        """It runs as the download toast paints; keep it off the main loop."""
        view = self._refreshable_view(secondary=True)
        view._populator.ensure()
        scheduled: list[Any] = []

        with mock.patch(
            "ui.widgets.lazy_populate.idle_on_main",
            side_effect=lambda fn, *a, **k: scheduled.append(fn),
        ):
            MethodView.refresh_models(view)

        self.assertEqual(len(scheduled), 1)
        self.assertEqual(view.populates, 1, "not inline")
        scheduled[0]()
        self.assertEqual(view.populates, 2)

    def test_refresh_leaves_a_collapsed_expander_unpopulated(self) -> None:
        """Laziness pin: populating resolves model lists, which hashes
        checkpoints. A section nobody can see must not pay for it."""
        view = self._refreshable_view(secondary=False)
        view._model_combos = [
            {"row": object(), "key": "k", "provider": list, "ready": True}
        ]

        MethodView.refresh_models(view)

        self.assertEqual(view.populates, 0)
        self.assertFalse(view._populator.ready)
        self.assertFalse(view._model_combos[0]["ready"])

    def test_change_defaults_repopulates_an_open_expander(self) -> None:
        view = self._refreshable_view(secondary=True)
        view._populator.ensure()
        view.context = mock.MagicMock()
        view._window_root = mock.MagicMock(return_value=None)

        with mock.patch(
            "ui.dialogs.model_params.show_change_defaults_dialog"
        ), mock.patch(
            "ui.widgets.lazy_populate.idle_on_main", side_effect=lambda fn, *a, **k: fn()
        ):
            MethodView._on_change_defaults(view, object())

        self.assertEqual(view.populates, 2)


def _record(
    model_id: str,
    display: str,
    *,
    installed: bool = True,
    identity_complete: bool = True,
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
    )


class InstalledRecordPickerTests(unittest.TestCase):
    """The primary method picker is a projection of identity records."""

    def _populate(
        self,
        records: list[ModelRecord],
        *,
        arch: str = MDX_ARCH_TYPE,
        stored: object = CHOOSE_MODEL,
        legacy_basenames: list[str] | None = None,
    ) -> tuple[list[object], list[object], mock.Mock]:
        view: Any = MethodView.__new__(MethodView)
        view.context = SimpleNamespace(repo=object())
        view.settings = object()
        view.model_key = "mdx_net_model"
        view.method_key = arch
        view.resolution_method_key = ""
        view.model_row = object()
        # The base view shows a banner when it gates a stored value it cannot
        # select; the real widget needs GTK, so record the calls instead.
        self.banner = mock.Mock()
        view.stored_model_banner = self.banner
        basenames = legacy_basenames or [record.basename for record in records]
        view.list_models = mock.Mock(return_value=basenames)

        values: list[object] = []
        selections: list[object] = []
        write = mock.Mock()
        legacy_displays = [record.display for record in records]
        if len(legacy_displays) < len(basenames):
            legacy_displays.extend(basenames[len(legacy_displays) :])

        with mock.patch(
            "core.model_identity.ModelIdentityService.records",
            return_value=tuple(records),
        ), mock.patch(
            "ui.views.base.map_basenames_to_display",
            return_value=legacy_displays,
        ), mock.patch(
            "ui.views.base.get_flat", return_value=stored
        ), mock.patch(
            "ui.views.base.set_combo_tag_values",
            side_effect=lambda _row, items: values.extend(items),
        ), mock.patch(
            "ui.views.base.set_combo_value",
            side_effect=lambda _row, value: selections.append(value),
        ), mock.patch("ui.views.base.set_flat", write):
            MethodView.populate_models(view)
        return values, selections, write


    def test_relabelled_record_repaints_without_touching_the_selection(self) -> None:
        """A friendlier catalogue label must not move the user's choice.

        The picker is a projection of `ModelRecord.display`, so a presentation
        refresh changes the visible label while the stored canonical id stays
        selected and unwritten.
        """
        raw, _selections, _write = self._populate(
            [_record("mdx:kim_vocal_1", "kim_vocal_1")],
            stored="mdx:kim_vocal_1",
        )
        friendly, selections, write = self._populate(
            [_record("mdx:kim_vocal_1", "Kim Vocal 1")],
            stored="mdx:kim_vocal_1",
        )

        self.assertIn(("mdx:kim_vocal_1", "kim_vocal_1"), raw)
        self.assertIn(("mdx:kim_vocal_1", "Kim Vocal 1"), friendly)
        self.assertEqual(selections, ["mdx:kim_vocal_1"])
        write.assert_not_called()

    def test_relabel_that_reorders_the_list_keeps_the_selection(self) -> None:
        """Sort is by display, so a rename can reorder the combo."""
        before, _sel_before, _w = self._populate(
            [
                _record("mdx:alpha", "Alpha"),
                _record("mdx:beta", "Beta"),
            ],
            stored="mdx:beta",
        )
        after, selections, write = self._populate(
            [
                _record("mdx:alpha", "Zulu"),
                _record("mdx:beta", "Beta"),
            ],
            stored="mdx:beta",
        )

        def ids(items: list[object]) -> list[object]:
            return [item[0] for item in items if isinstance(item, tuple)]

        self.assertNotEqual(ids(before), ids(after))
        self.assertEqual(selections, ["mdx:beta"])
        write.assert_not_called()

    def test_duplicate_displays_keep_two_distinct_ids(self) -> None:
        values, _selections, _write = self._populate(
            [
                _record("mdx:first-checkpoint", "Community Vocals"),
                _record("mdx:second-checkpoint", "Community Vocals"),
            ]
        )

        self.assertEqual(
            values,
            [
                CHOOSE_MODEL,
                ("mdx:first-checkpoint", "Community Vocals"),
                ("mdx:second-checkpoint", "Community Vocals"),
            ],
        )

    def test_picker_uses_sdr_order_then_display_and_id_tiebreaks(self) -> None:
        values, _selections, _write = self._populate(
            [
                _record("mdx:z-unscored", "Zulu"),
                _record("mdx:b_sdr_1143", "Beta"),
                _record("mdx:z_sdr_1297", "Zulu score"),
                _record("mdx:a_sdr_1143", "Beta"),
            ]
        )

        self.assertEqual(
            values,
            [
                CHOOSE_MODEL,
                ("mdx:z_sdr_1297", "Zulu score"),
                ("mdx:a_sdr_1143", "Beta"),
                ("mdx:b_sdr_1143", "Beta"),
                ("mdx:z-unscored", "Zulu"),
            ],
        )

    def test_illegal_display_text_is_visual_no_selection_without_a_write(self) -> None:
        _values, selections, write = self._populate(
            [_record("demucs:htdemucs", "v4 — htdemucs")],
            arch=DEMUCS_ARCH_TYPE,
            stored="v4 — htdemucs",
        )

        self.assertEqual(selections, [CHOOSE_MODEL])
        write.assert_not_called()

    def test_gated_stored_value_is_explained_by_a_banner(self) -> None:
        """"Choose Model" alone cannot be told apart from a preserved value."""
        _values, selections, write = self._populate(
            [_record("demucs:htdemucs", "v4 — htdemucs")],
            arch=DEMUCS_ARCH_TYPE,
            stored="v4 — htdemucs",
        )

        self.assertEqual(selections, [CHOOSE_MODEL])
        write.assert_not_called()
        self.banner.set_revealed.assert_called_once_with(True)
        title = self.banner.set_title.call_args.args[0]
        self.assertIn("v4 — htdemucs", title)
        self.assertIn("canonical model ID", title)

    def test_uninstalled_canonical_value_is_explained_by_a_banner(self) -> None:
        _values, selections, _write = self._populate(
            [_record("mdx:installed", "Installed")],
            stored="mdx:elsewhere",
        )

        self.assertEqual(selections, [CHOOSE_MODEL])
        self.banner.set_revealed.assert_called_once_with(True)
        self.assertIn("not installed", self.banner.set_title.call_args.args[0])

    def test_selectable_stored_value_hides_the_banner(self) -> None:
        _values, selections, _write = self._populate(
            [_record("mdx:installed", "Installed")],
            stored="mdx:installed",
        )

        self.assertEqual(selections, ["mdx:installed"])
        self.banner.set_revealed.assert_called_once_with(False)
        self.banner.set_title.assert_not_called()

    def test_unhashable_stored_value_is_visual_no_selection_without_a_write(self) -> None:
        try:
            _values, selections, write = self._populate(
                [_record("demucs:htdemucs", "v4 — htdemucs")],
                arch=DEMUCS_ARCH_TYPE,
                stored=["v4 — htdemucs"],
            )
        except TypeError as exc:
            self.fail(f"preserved non-string model value crashed the picker: {exc}")

        self.assertEqual(selections, [CHOOSE_MODEL])
        write.assert_not_called()

    def test_only_installed_family_records_are_members(self) -> None:
        values, _selections, _write = self._populate(
            [
                _record("demucs:loose-th", "Loose TH", identity_complete=False),
                _record("demucs:catalogue-only", "Catalogue only", installed=False),
                _record("mdx:other-family", "Other family"),
            ],
            arch=DEMUCS_ARCH_TYPE,
            legacy_basenames=["loose-th", "catalogue-only", "other-family", "msst.ckpt"],
        )

        self.assertEqual(values, [CHOOSE_MODEL, ("demucs:loose-th", "Loose TH")])

    def test_save_does_not_overwrite_a_write_gated_stored_value(self) -> None:
        view: Any = MethodView.__new__(MethodView)
        view.settings = object()
        view.model_key = "demucs_model"
        view._model_write_gated = True
        view.selected_model = mock.Mock(return_value=CHOOSE_MODEL)
        view._persist_stem_only = mock.Mock()
        view.save_options = mock.Mock()
        view._save_scales = mock.Mock()
        view._save_switches = mock.Mock()
        view._save_spins = mock.Mock()

        with mock.patch("ui.views.base.set_flat") as write:
            MethodView.save(view)

        write.assert_not_called()

    def test_unsupported_demucs_checkpoint_does_not_count_as_an_available_model(self) -> None:
        view: Any = MethodView.__new__(MethodView)
        view.context = SimpleNamespace(repo=object())
        view.method_key = DEMUCS_ARCH_TYPE
        view.resolution_method_key = ""
        view.list_models = mock.Mock(return_value=["unsupported-msst.ckpt"])

        with mock.patch(
            "core.model_identity.ModelIdentityService.records", return_value=()
        ):
            available = MethodView.has_any_models(view)

        self.assertFalse(available)

    def test_extra_model_picker_intersects_eligible_ids_with_installed_records(self) -> None:
        records = [
            _record("mdx:first", "Same display"),
            _record("mdx:second", "Same display"),
            _record("mdx:catalogue", "Catalogue only", installed=False),
        ]
        view: Any = MethodView.__new__(MethodView)
        view.context = SimpleNamespace(repo=object())
        view.settings = object()
        view._model_combos = [
            {
                "row": object(),
                "key": "mdx_voc_inst_secondary_model",
                "provider": lambda: [
                    "mdx:catalogue",
                    "mdx:second",
                    "mdx:first",
                ],
                "ready": False,
            }
        ]
        values: list[object] = []

        with mock.patch(
            "core.model_identity.ModelIdentityService.records",
            return_value=tuple(records),
        ), mock.patch(
            "ui.views.base.get_flat", return_value="No Model Selected"
        ), mock.patch(
            "ui.views.base.set_combo_tag_values",
            side_effect=lambda _row, items: values.extend(items),
        ), mock.patch("ui.views.base.set_combo_value"):
            MethodView._populate_model_combos_now(view)

        self.assertEqual(
            values,
            [
                "No Model Selected",
                ("mdx:first", "Same display"),
                ("mdx:second", "Same display"),
            ],
        )


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SecondaryPickerWarningGtkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.secondary-warning")
        cls._app.register()

    def test_illegal_secondary_stays_verbatim_until_valid_repick(self) -> None:
        from gi.repository import Adw

        from bundled.constants import NO_MODEL
        from core.settings import Settings
        from ui.widgets.rows import get_combo_value, make_combo_row, set_combo_value

        illegal = "mdx:missing-secondary"
        settings = Settings.defaults()
        settings.mdx.voc_inst_secondary_model = illegal
        record = _record("mdx:secondary", "Friendly secondary")
        missing = _record("mdx:missing-secondary", "Now available")
        records = [record]
        eligible = [record.id]

        view: Any = MethodView.__new__(MethodView)
        view.context = SimpleNamespace(repo=object())
        view.settings = settings
        view._loading = False
        view._populating_models = False
        view._touch_settings = mock.Mock()
        combo = make_combo_row("Vocals / Instrumental", [NO_MODEL])
        warning = Adw.ActionRow(title="Saved model unavailable", visible=False)
        entry = {
            "row": combo,
            "warning_row": warning,
            "key": "mdx_voc_inst_secondary_model",
            "provider": lambda: list(eligible),
            "ready": False,
        }
        view._model_combos = [entry]

        with mock.patch(
            "core.model_identity.ModelIdentityService.records",
            side_effect=lambda: tuple(records),
        ):
            MethodView._populate_model_combos_now(view)

            self.assertEqual(settings.mdx.voc_inst_secondary_model, illegal)
            self.assertEqual(get_combo_value(combo), NO_MODEL)
            self.assertTrue(warning.get_visible())
            self.assertIn(illegal, warning.get_subtitle() or "")

            # Installing the exact missing identity is an inventory refresh,
            # not a user choice. The gate must remain sticky.
            records.append(missing)
            eligible.append(missing.id)
            MethodView._populate_model_combos_now(view)

        self.assertEqual(settings.mdx.voc_inst_secondary_model, illegal)
        self.assertEqual(get_combo_value(combo), NO_MODEL)
        self.assertTrue(warning.get_visible())
        self.assertIn(illegal, warning.get_subtitle() or "")

        set_combo_value(combo, missing.id)
        MethodView._on_model_combo(view, entry["key"], combo)

        self.assertEqual(settings.mdx.voc_inst_secondary_model, missing.id)
        self.assertFalse(warning.get_visible())

    def test_external_settings_change_replaces_stale_secondary_gate(self) -> None:
        from gi.repository import Adw

        from bundled.constants import NO_MODEL
        from core.settings import Settings
        from ui.widgets.rows import get_combo_value, make_combo_row

        original = "mdx:missing-original"
        replacement = _record("mdx:replacement", "Replacement")
        settings = Settings.defaults()
        settings.mdx.voc_inst_secondary_model = original
        view: Any = MethodView.__new__(MethodView)
        view.context = SimpleNamespace(repo=object())
        view.settings = settings
        view._loading = False
        view._populating_models = False
        view._touch_settings = mock.Mock()
        combo = make_combo_row("Vocals / Instrumental", [NO_MODEL])
        warning = Adw.ActionRow(title="Saved model unavailable", visible=False)
        entry = {
            "row": combo,
            "warning_row": warning,
            "key": "mdx_voc_inst_secondary_model",
            "provider": lambda: [replacement.id],
            "ready": False,
        }
        view._model_combos = [entry]

        with mock.patch(
            "core.model_identity.ModelIdentityService.records",
            return_value=(replacement,),
        ):
            MethodView._populate_model_combos_now(view)
            self.assertTrue(warning.get_visible())

            new_invalid = "mdx:missing-replacement"
            settings.mdx.voc_inst_secondary_model = new_invalid
            MethodView._populate_model_combos_now(view)
            self.assertEqual(get_combo_value(combo), NO_MODEL)
            self.assertIn(new_invalid, warning.get_subtitle() or "")
            self.assertNotIn(original, warning.get_subtitle() or "")

            settings.mdx.voc_inst_secondary_model = replacement.id
            MethodView._populate_model_combos_now(view)

        self.assertEqual(get_combo_value(combo), replacement.id)
        self.assertFalse(warning.get_visible())
        self.assertFalse(entry["write_gated"])

if __name__ == "__main__":
    unittest.main()
