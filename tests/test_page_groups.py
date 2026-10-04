"""build_page_groups: the Input/Output/Processing groups every run page shares."""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

from tests.test_row_slot import _order


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class PageGroupsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        Adw.init()

    def _build(self, *, processing: Any = None, **overrides: Any) -> Any:
        from ui.widgets.page_groups import PageGroupCallbacks, build_page_groups

        values: dict[str, Any] = {
            "on_inputs_changed": mock.Mock(),
            "on_output_changed": mock.Mock(),
            "on_format_changed": mock.Mock(),
            "toast": mock.Mock(),
            "hint": mock.Mock(),
            "accept_any_getter": lambda: False,
            "initial_folder_getter": lambda: None,
        }
        values.update(overrides)
        callbacks = PageGroupCallbacks(**values)
        if processing is None:
            return build_page_groups(callbacks)
        return build_page_groups(callbacks, processing=processing)

    def test_titles(self) -> None:
        groups = self._build()
        self.assertEqual(groups.input_group.get_title(), "Input")
        self.assertEqual(groups.output_group.get_title(), "Output")
        self.assertEqual(groups.processing_group.get_title(), "Processing")

    def test_default_order(self) -> None:
        groups = self._build()
        self.assertEqual(_order(groups.input_group), [groups.input_row])
        self.assertEqual(_order(groups.output_group), [groups.format_row, groups.output_row])
        self.assertEqual(
            _order(groups.processing_group),
            [groups.gpu_row, groups.autocast_row, groups.sample_row],
        )

    def test_extra_input_and_processing_rows_follow(self) -> None:
        from gi.repository import Adw

        groups = self._build()
        extra_in = Adw.ActionRow(title="in")
        extra_proc = Adw.ActionRow(title="proc")
        groups.add_input_row(extra_in)
        groups.add_processing(extra_proc)
        self.assertEqual(_order(groups.input_group), [groups.input_row, extra_in])
        self.assertEqual(
            _order(groups.processing_group),
            [groups.gpu_row, groups.autocast_row, groups.sample_row, extra_proc],
        )

    def test_output_order_with_lead_and_tail(self) -> None:
        from gi.repository import Adw

        groups = self._build()
        a, b, c = (Adw.ActionRow(title=t) for t in "ABC")
        groups.set_output_lead([a, b])
        groups.add_output_tail(c)
        self.assertEqual(
            _order(groups.output_group),
            [a, b, groups.format_row, groups.output_row, c],
        )

    def test_processing_subset(self) -> None:
        groups = self._build(processing=("gpu",))
        self.assertIsNone(groups.autocast_row)
        self.assertIsNone(groups.sample_row)
        self.assertEqual(_order(groups.processing_group), [groups.gpu_row])

    def test_bindings_cover_supplied_rows(self) -> None:
        bindings = self._build().bindings()
        for name in (
            "use_gpu",
            "autocast",
            "sample_mode",
            "export_path",
            "input_paths",
            "save_format",
        ):
            self.assertIsNotNone(getattr(bindings, name), name)
        self.assertIsNone(bindings.vocal_splitter_enabled)

        subset = self._build(processing=("gpu",)).bindings()
        self.assertIsNotNone(subset.use_gpu)
        self.assertIsNone(subset.autocast)
        self.assertIsNone(subset.sample_mode)

    def test_apply_pushes_settings(self) -> None:
        from core.settings import Settings

        settings = Settings()
        settings.process.export_path = "/tmp/out"
        settings.process.use_gpu = True
        settings.process.sample_mode = True
        groups = self._build()
        groups.apply(settings)
        self.assertEqual(groups.output_row.path, "/tmp/out")
        assert groups.gpu_row is not None and groups.sample_row is not None
        self.assertTrue(groups.gpu_row.get_active())
        self.assertTrue(groups.sample_row.get_active())

    def test_switch_callbacks_take_no_arguments(self) -> None:
        callback = mock.Mock()
        groups = self._build(on_gpu_changed=callback)
        assert groups.gpu_row is not None
        groups.gpu_row.set_active(True)
        callback.assert_called_once_with()

    def test_sample_row_label(self) -> None:
        from ui.shared_settings import SAMPLE_MODE_TITLE, sample_mode_subtitle

        groups = self._build(sample_duration=45)
        assert groups.sample_row is not None
        self.assertEqual(groups.sample_row.get_title(), SAMPLE_MODE_TITLE)
        self.assertEqual(groups.sample_row.get_subtitle(), sample_mode_subtitle(45))

    def test_hints_attached(self) -> None:
        from ui.help_text import (
            INPUT_FOLDER_ENTRY_HELP,
            IS_AUTOCAST_HELP,
            IS_GPU_CONVERSION_HELP,
            MODEL_SAMPLE_MODE_HELP,
            OUTPUT_FOLDER_ENTRY_HELP,
        )

        hint = mock.Mock()
        groups = self._build(hint=hint)
        hint.assert_has_calls(
            [
                mock.call(groups.input_row, INPUT_FOLDER_ENTRY_HELP),
                mock.call(groups.output_row, OUTPUT_FOLDER_ENTRY_HELP),
                mock.call(groups.gpu_row, IS_GPU_CONVERSION_HELP),
                mock.call(groups.autocast_row, IS_AUTOCAST_HELP),
                mock.call(groups.sample_row, MODEL_SAMPLE_MODE_HELP),
            ],
            any_order=True,
        )
        self.assertEqual(hint.call_count, 5)

    def test_view_inputs_button(self) -> None:
        groups = self._build()
        self.assertEqual(groups.view_inputs_button.get_action_name(), "win.view_inputs")

        callback = mock.Mock()
        groups = self._build(view_inputs_action=None, on_view_inputs=callback)
        self.assertIsNone(groups.view_inputs_button.get_action_name())
        groups.view_inputs_button.emit("clicked")
        callback.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
