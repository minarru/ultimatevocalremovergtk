"""Ensemble preflight/start must flush Save Stems before snapshotting settings."""

from __future__ import annotations

import typing
import unittest
from unittest.mock import MagicMock, Mock

from bundled.constants import INST_STEM, VOCAL_STEM
from core import Settings
from core.export_naming import OutputNamingContext
from core.job_plan import PlannedInput, ResolvedJob, ValidationLevel, settings_fingerprint
from core.stem_selection import ExclusiveView, StemSelectionState
from core.types import ProcessMethod


def _resolved_job(
    *, command: str, path: str, output: str, settings: Settings,
    model_dependencies: typing.Mapping[str, typing.Any] | None = None,
) -> ResolvedJob:
    planned = PlannedInput(
        path=path,
        naming=OutputNamingContext(
            input_path=path,
            track="song",
            track_base="song",
            export_directory=output,
            extension="wav",
        ),
        outputs=(),
    )
    return ResolvedJob(
        command=command,
        settings=settings,
        inputs=(planned,),
        models=(),
        provenance={},
        diagnostics=(),
        validation_level=ValidationLevel.RUNTIME,
        inventory_generation=0,
        settings_fingerprint=settings_fingerprint(settings),
        device="cpu",
        output=output,
        model_dependencies=model_dependencies or {},
    )


def _minimal_page(*, settings: Settings | None = None) -> typing.Any:
    import ui.ensemble.window as ensemble_window

    page = object.__new__(ensemble_window.EnsemblePage)
    page.settings = settings or Settings.defaults()
    page.save_stems = MagicMock()
    page.vocal_split_row = MagicMock()
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
        page.vocal_split_row.persist_to_settings.assert_called_once_with(page.settings)
        page.save_stems.persist_to_settings.assert_called_once()
        self.assertEqual(spec.command, "ensemble")
        self.assertEqual(spec.inputs, ("/tmp/song.wav",))

    def test_start_flushes_save_stems(self) -> None:
        page = _minimal_page()

        page.start(MagicMock())

        page.save_stems.persist_to_settings.assert_called_once()
        page.vocal_split_row.persist_to_settings.assert_called_once_with(page.settings)
        page._persist_selected_models.assert_called_once()
        page.window.begin_run.assert_called_once_with(page)
        page.context.runner.start.assert_called_once()

    def test_start_uses_planned_inputs_not_widget_paths(self) -> None:
        page = _minimal_page()
        page.input_row.paths = ["/widget/changed.wav"]
        page.output_row.path = "/widget/out"
        dependencies = {"ensemble.selected_models[0]": Mock(id="mdx:a")}
        plan = _resolved_job(
            command="ensemble",
            path="/in/song.wav",
            output="/plan/out",
            settings=page.settings,
            model_dependencies=dependencies,
        )

        page.start(MagicMock(), plan=plan)

        args, kwargs = page.context.runner.start.call_args
        self.assertEqual(list(args[0]), ["/in/song.wav"])
        self.assertEqual(kwargs["planned"], plan.inputs)
        self.assertEqual(kwargs["planned_output_root"], "/plan/out")
        self.assertIs(kwargs["model_dependencies"], dependencies)
        page.save_stems.persist_to_settings.assert_called_once()

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


def _minimal_separation_window() -> typing.Any:
    import ui.window as window_mod

    window = MagicMock()
    window.input_row.paths = ["/widget/changed.wav"]
    window.context.try_save_settings = MagicMock(return_value=None)
    window._start_separation = lambda callbacks, plan=None: (
        window_mod.MainWindow._start_separation(window, callbacks, plan=plan)
    )
    return window


class SeparationPlannedStartTests(unittest.TestCase):
    def test_start_uses_planned_inputs_not_widget_paths(self) -> None:
        from ui.window import _SeparationTarget

        window = _minimal_separation_window()
        dependencies = {"mdx.model": Mock(id="mdx:primary")}
        plan = _resolved_job(
            command="separate",
            path="/in/song.wav",
            output="/plan/out",
            settings=Settings.defaults(),
            model_dependencies=dependencies,
        )
        target = _SeparationTarget(window)

        target.start(MagicMock(), plan=plan)

        args, kwargs = window.context.runner.start.call_args
        self.assertEqual(list(args[0]), ["/in/song.wav"])
        self.assertEqual(kwargs["planned"], plan.inputs)
        self.assertEqual(kwargs["planned_output_root"], "/plan/out")
        self.assertIs(kwargs["model_dependencies"], dependencies)
        window.begin_run.assert_called_once_with(window._separation_target)

    def test_unplanned_start_still_reads_widget_paths(self) -> None:
        from ui.window import _SeparationTarget

        window = _minimal_separation_window()
        target = _SeparationTarget(window)

        target.start(MagicMock())

        args, kwargs = window.context.runner.start.call_args
        self.assertEqual(list(args[0]), ["/widget/changed.wav"])
        self.assertFalse(kwargs.get("planned"))


if __name__ == "__main__":
    unittest.main()
