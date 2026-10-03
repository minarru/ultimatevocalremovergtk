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

    def test_algorithm_values_fit_beside_their_descriptions(self) -> None:
        """A one-line description must leave the combo room for its value.

        The row's height is settled while the description fits on one line,
        so a long description squeezes the selected value instead of wrapping.
        """
        import time

        from gi.repository import GLib, Gtk

        from bundled.constants import ENSEMBLE_ALGORITHMS
        from tests.gtk_layout_helpers import resize_window
        from ui.widgets.rows import set_combo_value

        page = self._page()
        window = page.window
        self.addCleanup(window.set_visible, False)
        resize_window(window, 1280, 900)
        window.content_stack.set_visible_child_name("ensemble")
        row = page.secondary_algo_row
        row.set_visible(True)

        def find(widget: Any, kind: type) -> Any:
            if isinstance(widget, kind):
                return widget
            child = widget.get_first_child()
            while child is not None:
                found = find(child, kind)
                if found is not None:
                    return found
                child = child.get_next_sibling()
            return None

        def settle() -> None:
            context = GLib.MainContext.default()
            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline:
                context.iteration(False)
                time.sleep(0.005)

        for algorithm in ENSEMBLE_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                set_combo_value(row, algorithm)
                page._apply_algorithm_row_presentation()
                settle()
                value = find(find(row, Gtk.ListView), Gtk.Label)
                self.assertGreater(row.get_width(), 0)
                natural = value.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
                self.assertGreaterEqual(value.get_width(), natural, value.get_label())


#: Each tool's settings holder group in ``audio-tools-page.blp`` (Matchering has none).
_AUDIO_TOOL_HOLDERS = {
    "Manual Ensemble": "manual_ensemble_group",
    "Time Stretch": "time_stretch_group",
    "Change Pitch": "pitch_group",
    "Align Inputs": "align_group",
    "Apollo Restore": "apollo_group",
}


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class AudioToolsLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.page-layout-audio-tools")
        cls._app.register()

    def _window(self) -> Any:
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return window

    def _select(self, page: Any, tool: str) -> None:
        from ui.widgets.rows import set_combo_value

        set_combo_value(page.tool_row, tool)
        self.assertEqual(page._current_tool(), tool)

    def test_every_tool_follows_the_column_rule(self) -> None:
        from gi.repository import Adw

        from bundled.constants import APOLLO_RESTORE
        from ui.audio_tools.window import AUDIO_TOOL_ORDER

        page = self._window()._audio_tools_page
        self.assertFalse(hasattr(page, "testing_row"))
        self.assertIs(page.apollo_gpu_row, page.gpu_row)
        self.assertIs(page.inputs_row, page.input_row)
        for tool in AUDIO_TOOL_ORDER:
            with self.subTest(tool=tool):
                self._select(page, tool)
                self.assertEqual(column_titles(page._col_start), ["Input", "Tool"])
                self.assertEqual(column_titles(page._col_end), ["Output", "Processing"])
                self.assertEqual(_order(page.tool_group), [page.tool_row, *page._tool_rows[tool]])
                holder = _AUDIO_TOOL_HOLDERS.get(tool)
                description = (
                    page._layout_object(holder, Adw.PreferencesGroup).get_description()
                    if holder
                    else None
                )
                self.assertEqual(page.tool_row.get_subtitle() or "", description or "")
                self.assertEqual(
                    _order(page._page_groups.output_group), [page.format_row, page.output_row]
                )
                self.assertEqual(
                    _order(page._page_groups.processing_group),
                    [page.gpu_row, page.normalize_row, page.amplification_row],
                )
                self.assertEqual(page.gpu_row.get_visible(), tool == APOLLO_RESTORE)

    def test_matchering_shows_only_the_picker(self) -> None:
        from bundled.constants import MATCH_INPUTS

        page = self._window()._audio_tools_page
        self._select(page, MATCH_INPUTS)
        self.assertEqual(page._tool_rows[MATCH_INPUTS], ())
        self.assertEqual(_order(page.tool_group), [page.tool_row])

    def test_tool_switch_keeps_rows_and_expander(self) -> None:
        from gi.repository import Adw

        from bundled.constants import ALIGN_INPUTS, APOLLO_RESTORE

        page = self._window()._audio_tools_page
        self._select(page, ALIGN_INPUTS)
        expander = page._layout_object("align_advanced_row", Adw.ExpanderRow)
        self.assertIn(expander, page._tool_rows[ALIGN_INPUTS])
        expander.set_expanded(True)
        self._select(page, APOLLO_RESTORE)
        self.assertFalse(contains(page.tool_group, expander))
        self._select(page, ALIGN_INPUTS)
        self.assertEqual(_order(page.tool_group), [page.tool_row, *page._tool_rows[ALIGN_INPUTS]])
        self.assertTrue(expander.get_expanded())
        self.assertTrue(contains(expander, page.spec_match_row))

    def test_dual_tools_show_pairs_row(self) -> None:
        from bundled.constants import MANUAL_ENSEMBLE
        from core.audio_tools import DUAL_INPUT_TOOLS

        page = self._window()._audio_tools_page
        input_group = page._page_groups.input_group
        self.assertEqual(_order(input_group), [page.input_row, page.dual_inputs_row])
        for tool in DUAL_INPUT_TOOLS:
            with self.subTest(tool=tool):
                self._select(page, tool)
                self.assertTrue(page.dual_inputs_row.get_visible())
                self.assertFalse(page.input_row.get_visible())
                self.assertTrue(input_group.get_description())
        self._select(page, MANUAL_ENSEMBLE)
        self.assertFalse(page.dual_inputs_row.get_visible())
        self.assertTrue(page.input_row.get_visible())
        self.assertIn(input_group.get_description(), ("", None))

    def test_inputs_edit_after_tool_switch_persists(self) -> None:
        import tempfile

        from bundled.constants import APOLLO_RESTORE, TIME_STRETCH

        window = self._window()
        page = window._audio_tools_page
        window.content_stack.set_visible_child_name("audio_tools")
        self._select(page, APOLLO_RESTORE)
        self._select(page, TIME_STRETCH)
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            page.input_row.set_paths([audio.name])
            self.assertEqual(window.settings.process.input_paths, [audio.name])


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class NarrowLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.page-layout-narrow")
        cls._app.register()

    def test_narrow_layout_keeps_rule_order(self) -> None:
        from gi.repository import Gtk

        from ui.widgets.columns import set_columns_narrow
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        pages = {
            "separation": window,
            "ensemble": window._ensemble_page,
            "audio tools": window._audio_tools_page,
        }
        for name, page in pages.items():
            with self.subTest(page=name):
                box = window._columns_box if page is window else page.columns_box
                set_columns_narrow(box, True)
                self.assertEqual(box.get_orientation(), Gtk.Orientation.VERTICAL)
                order = column_titles(page._col_start) + column_titles(page._col_end)
                self.assertEqual(order[0], "Input")
                self.assertEqual(order[-2:], ["Output", "Processing"])


if __name__ == "__main__":
    unittest.main()
