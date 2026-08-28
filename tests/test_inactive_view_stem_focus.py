"""Inactive method views must not clobber ``process.stem_focus`` on flush.

See also :meth:`ui.views.base.MethodView.save` (``include_stem_only`` contract)
and ``tests.test_ensemble_flush_settings`` (ensemble preflight flush).
"""

from __future__ import annotations

import typing
import unittest
from unittest.mock import MagicMock, patch

from core import Settings
from core.stem_selection import (
    _QUICK_ALL,
    _TOGGLE_ALL,
    DemucsView,
    ExclusiveView,
    StemSelectionState,
)


class InactiveViewStemFocusTests(unittest.TestCase):
    def test_separation_readiness_blocks_a_refresh_repick(self) -> None:
        from ui.window import MainWindow

        window = MainWindow.__new__(MainWindow)
        window.input_row = MagicMock()
        window.input_row.blocked_reason.return_value = None
        window.output_row = MagicMock()
        window.output_row.blocked_reason.return_value = None
        window.context = MagicMock()
        view = MagicMock()
        view.has_model.return_value = True
        view.save_stems.repick_required = True
        window._active_view = lambda: view

        self.assertEqual(
            MainWindow._separation_blocked_reason(window),
            "Choose a stem again after the model refresh",
        )

    def test_separation_readiness_blocks_a_splitter_refresh_repick(self) -> None:
        from ui.window import MainWindow

        window = MainWindow.__new__(MainWindow)
        window.input_row = MagicMock()
        window.input_row.blocked_reason.return_value = None
        window.output_row = MagicMock()
        window.output_row.blocked_reason.return_value = None
        window.context = MagicMock()
        window.vocal_split_row = MagicMock()
        window.vocal_split_row.blocked_reason.return_value = (
            "Choose a vocal splitter model again after the model refresh"
        )
        view = MagicMock()
        view.has_model.return_value = True
        view.save_stems.repick_required = False
        window._active_view = lambda: view

        self.assertEqual(
            MainWindow._separation_blocked_reason(window),
            "Choose a vocal splitter model again after the model refresh",
        )

    def test_demucs_quick_all_clears_stem_focus_when_written(self) -> None:
        """Documents why inactive Demucs must not persist during ``_flush_settings``."""
        settings = Settings.defaults()
        settings.process.stem_focus = "Instrumental"

        state = StemSelectionState()
        state.configure_demucs(
            focus_stems=["quick_all", "focus_instrumental", "focus_vocals"],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            demucs_stem_count=4,
        )
        state.write(
            settings,
            DemucsView(
                active=_QUICK_ALL,
                export_choice=_TOGGLE_ALL,
                export_filter_visible=False,
            ),
        )
        self.assertEqual(settings.process.stem_focus, "")

    def test_mdx_exclusive_persist_survives_without_demucs_flush(self) -> None:
        settings = Settings.defaults()
        mdx = StemSelectionState()
        mdx.configure_exclusive(
            primary_stem="Instrumental",
            secondary_stem="Vocals",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        mdx.write(settings, ExclusiveView(choice="Instrumental"))
        self.assertEqual(settings.process.stem_focus, "mix.instrumental")

        demucs = StemSelectionState()
        demucs.configure_demucs(
            focus_stems=["quick_all"],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            demucs_stem_count=4,
        )
        # Inactive Demucs must not run ``write`` during flush; if it did, focus
        # would be cleared (see test_demucs_quick_all_clears_stem_focus_when_written).
        self.assertEqual(settings.process.stem_focus, "mix.instrumental")

    def test_demucs_save_options_does_not_persist_stems(self) -> None:
        from ui.views.demucs import DemucsView as DemucsMethodView

        view: typing.Any = DemucsMethodView.__new__(DemucsMethodView)
        view._option_rows = {}
        view._loading = False
        view.save_stems = MagicMock()
        view.save_stems.mode = "demucs"

        DemucsMethodView.save_options(view)

        view.save_stems.persist_to_settings.assert_not_called()

    def test_mdx_save_options_does_not_persist_stems(self) -> None:
        from ui.views.mdx import MDXView

        view: typing.Any = MDXView.__new__(MDXView)
        view._option_rows = {}
        view._loading = False
        view.save_stems = MagicMock()
        view.save_stems.mode = "subset"
        view.segment_row = MagicMock()
        view.overlap_row = MagicMock()
        view._persist_segment_value = MagicMock()
        view._overlap_key = MagicMock(return_value="overlap_mdx23")
        view.settings = Settings.defaults()

        with patch("ui.views.mdx.get_scale_row_value", return_value=None):
            MDXView.save_options(view)

        view.save_stems.persist_to_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
