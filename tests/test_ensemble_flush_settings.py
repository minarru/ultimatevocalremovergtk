"""Ensemble preflight/start must flush Save Stems before snapshotting settings."""

from __future__ import annotations

import typing
import unittest
from unittest.mock import MagicMock, Mock

from bundled.constants import INST_STEM, VOCAL_STEM
from core import Settings
from core.stem_selection import ExclusiveView, StemSelectionState
from core.types import ProcessMethod


def _minimal_page(*, settings: Settings | None = None) -> typing.Any:
    import ui.ensemble.window as ensemble_window

    page = object.__new__(ensemble_window.EnsemblePage)
    page.settings = settings or Settings.defaults()
    page.save_stems = MagicMock()
    page._persist_selected_models = MagicMock()
    page.input_row = MagicMock()
    page.input_row.paths = ["/tmp/song.wav"]
    page.output_row = MagicMock()
    page.output_row.path = "/tmp/out"
    page.window = MagicMock()
    page.context = MagicMock()
    page.context.try_save_settings = MagicMock(return_value=None)
    page.context.runner = MagicMock()
    page._toast = MagicMock()
    page._ensemble_pair = MagicMock(return_value=Mock(value="Vocals/Instrumental"))
    page._selected_model_tags = MagicMock(return_value=["mdx:a", "mdx:b"])
    return page


class EnsembleFlushSettingsTests(unittest.TestCase):
    def test_build_job_spec_flushes_save_stems(self) -> None:
        page = _minimal_page()

        spec = page.build_job_spec()

        self.assertEqual(page.settings.process.method, ProcessMethod.ENSEMBLE)
        page._persist_selected_models.assert_called_once()
        page.save_stems.persist_to_settings.assert_called_once()
        self.assertEqual(spec.command, "ensemble")
        self.assertEqual(spec.inputs, ("/tmp/song.wav",))

    def test_start_flushes_save_stems(self) -> None:
        page = _minimal_page()

        page.start(MagicMock())

        page.save_stems.persist_to_settings.assert_called_once()
        page._persist_selected_models.assert_called_once()
        page.window.begin_run.assert_called_once_with(page)
        page.context.runner.start.assert_called_once()

    def test_flush_preserves_stem_focus_from_widget(self) -> None:
        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem=INST_STEM,
            secondary_stem=VOCAL_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )

        class SaveStemsStub:
            def persist_to_settings(self) -> None:
                state.write(settings, ExclusiveView(choice=INST_STEM))

        page = _minimal_page(settings=settings)
        page.save_stems = SaveStemsStub()

        page._flush_run_settings()

        self.assertEqual(settings.process.stem_focus, INST_STEM)
        self.assertEqual(settings.process.method, ProcessMethod.ENSEMBLE)


if __name__ == "__main__":
    unittest.main()
