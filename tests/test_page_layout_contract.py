"""Every run page uses one column layout.

Left column: Input, then the page's own section. Right column: Output, then
Processing. These tests pin that contract for each page and check that rows
moving between groups keep their settings behaviour.
"""

from __future__ import annotations

import os
import unittest
from typing import Any

from tests.test_row_slot import _order


def column_titles(column: Any) -> list[str]:
    """Titles of ``column``'s direct children, in display order."""
    titles: list[str] = []
    child = column.get_first_child()
    while child is not None:
        titles.append(child.get_title() if hasattr(child, "get_title") else "")
        child = child.get_next_sibling()
    return titles


def contains(group: Any, row: Any) -> bool:
    """Whether ``row`` sits somewhere inside ``group``."""
    return bool(row.is_ancestor(group))


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SeparationLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.page-layout-separation")
        cls._app.register()

    def _window(self) -> Any:
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return window

    def _switch(self, window: Any, method_key: str) -> Any:
        from ui.widgets.rows import set_combo_value

        view = window._views_by_method[method_key]
        set_combo_value(window.method_row, view.title)
        self.assertIs(window._current_view, view)
        return view

    def test_every_method_follows_the_column_rule(self) -> None:
        window = self._window()
        for index in range(window.method_row.get_model().get_n_items()):
            with self.subTest(method=index):
                window.method_row.set_selected(index)
                view = window._current_view
                self.assertEqual(column_titles(window._col_start), ["Input", "Model"])
                self.assertEqual(column_titles(window._col_end), ["Output", "Processing"])
                self.assertTrue(contains(view.group, window.vocal_split_row))
                self.assertTrue(contains(window._page_groups.output_group, window.format_row))
                self.assertTrue(contains(window._page_groups.output_group, window.output_row))

    def test_output_rows_after_repeated_switching(self) -> None:
        from gi.repository import Adw

        from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_PM

        window = self._window()
        output_group = window._page_groups.output_group
        for method_key in (VR_ARCH_PM, MDX_ARCH_TYPE, DEMUCS_ARCH_TYPE, VR_ARCH_PM):
            with self.subTest(method=method_key):
                active = self._switch(window, method_key)
                self.assertEqual(
                    _order(output_group),
                    [*active.output_stems.rows, window.format_row, window.output_row],
                )
                for view in window._views:
                    if view is active:
                        continue
                    for row in view.output_stems.rows:
                        holder = row.get_ancestor(Adw.PreferencesGroup)
                        self.assertTrue(holder is None or holder.get_root() is not window)
                        self.assertIsNot(row.get_root(), window)

    def test_output_tooltip_follows_active_view(self) -> None:
        from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_PM

        window = self._window()
        output_group = window._page_groups.output_group
        previous = None
        for method_key in (MDX_ARCH_TYPE, VR_ARCH_PM, DEMUCS_ARCH_TYPE):
            with self.subTest(method=method_key):
                view = self._switch(window, method_key)
                if previous is not None:
                    self.assertIsNone(previous.on_output_tooltip)
                hook = view.on_output_tooltip
                self.assertIsNotNone(hook)
                seen: list[str] = []

                def spy(text: str, hook: Any = hook, seen: list[str] = seen) -> None:
                    seen.append(text)
                    hook(text)

                view.on_output_tooltip = spy
                view._update_stem_group_metadata(refresh_workload=False)
                view.on_output_tooltip = hook
                self.assertTrue(seen)
                self.assertEqual(output_group.get_tooltip_text(), seen[-1] or None)
                self.assertEqual(
                    output_group.get_tooltip_text(), view.stem_group.get_tooltip_text()
                )
                previous = view

    def test_format_edit_after_switch_persists(self) -> None:
        from bundled.constants import FLAC, WAV
        from core.types.enums import SaveFormat

        window = self._window()
        self.assertEqual(window.content_stack.get_visible_child_name(), "separation")
        window.settings.process.save_format = SaveFormat(WAV)
        window._sync_shared_from_settings()
        target = next(view for view in window._views if view is not window._current_view)
        self._switch(window, target.method_key)
        window.format_row.set_save_format(FLAC)
        window._flush_settings()
        self.assertEqual(window.settings.process.save_format, FLAC)

    def test_vocal_splitter_survives_switching(self) -> None:
        from ui.widgets.rows import get_combo_value

        stored = "mdx:Layout Contract Fixture Splitter"
        window = self._window()
        window.settings.process.vocal_splitter = stored
        window._sync_shared_from_settings()
        row = window.vocal_split_row
        self.assertEqual(get_combo_value(row.splitter_row), stored)
        for _ in range(2):
            target = next(view for view in window._views if view is not window._current_view)
            self._switch(window, target.method_key)
            self.assertTrue(contains(target.group, row))
        self.assertEqual(get_combo_value(row.splitter_row), stored)
        self.assertEqual(window.settings.process.vocal_splitter, stored)
        window._flush_settings()
        self.assertEqual(window.settings.process.vocal_splitter, stored)


def expander_rows(expander: Any) -> list[Any]:
    """Rows inside an ``Adw.ExpanderRow``'s revealer, in display order."""
    from gi.repository import Gtk

    def find_revealer(widget: Any) -> Any:
        if isinstance(widget, Gtk.Revealer):
            return widget
        child = widget.get_first_child()
        while child is not None:
            found = find_revealer(child)
            if found is not None:
                return found
            child = child.get_next_sibling()
        return None

    revealer = find_revealer(expander)
    return [] if revealer is None else _order(revealer)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class EnsembleLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.page-layout-ensemble")
        cls._app.register()

    def _page(self) -> Any:
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return window._ensemble_page

    def test_columns_follow_the_rule(self) -> None:
        page = self._page()
        self.assertEqual(column_titles(page._col_start), ["Input", "Ensemble", "Combination"])
        self.assertEqual(column_titles(page._col_end), ["Output", "Processing"])

    def test_ensemble_group_hosts_member_options_and_vocal_splitter(self) -> None:
        page = self._page()
        group = page.ensemble_group
        self.assertTrue(contains(group, page.member_options_row))
        self.assertTrue(contains(group, page.vocal_split_row))
        self.assertEqual(
            _order(group)[-3:],
            [page.models_trigger_row, page.member_options_row, page.vocal_split_row],
        )

    def test_output_group_order(self) -> None:
        page = self._page()
        self.assertIs(page.stems_group, page._page_groups.output_group)
        self.assertEqual(
            _order(page.stems_group),
            [*page.output_stems.rows, page.format_row, page.output_row, page.save_all_row],
        )

    def test_processing_hosts_the_advanced_expander(self) -> None:
        from gi.repository import Adw

        page = self._page()
        processing = page._page_groups.processing_group
        advanced = page._layout_object("advanced_row", Adw.ExpanderRow)
        self.assertEqual(
            _order(processing),
            [page.gpu_row, page.autocast_row, page.sample_row, advanced],
        )
        self.assertEqual(expander_rows(advanced), [page.append_name_row, page.wav_ensemble_row])

    def test_combination_group_has_no_summary_description(self) -> None:
        from gi.repository import Adw

        page = self._page()
        page._update_models_summary()
        page._refresh_ensemble_type_values()
        group = page._layout_object("combination_group", Adw.PreferencesGroup)
        self.assertIn(group.get_description(), ("", None))


if __name__ == "__main__":
    unittest.main()
