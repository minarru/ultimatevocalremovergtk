"""File-pass hooks live in core.run_hooks, not job_runner."""

from __future__ import annotations

import typing
import unittest
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[1]


def _run_final_ensemble_combine(
    stems: tuple[object, ...],
    focus: str,
    *,
    is_multi_stem: bool,
) -> list[object]:
    from core.run_hooks import _EnsembleRunHooks
    from core.settings import Settings

    combined: list[object] = []

    def ensemble_outputs(
        _base: str,
        _path: str,
        stem: object,
        **_kwargs: object,
    ) -> None:
        combined.append(stem)

    ensemble = SimpleNamespace(
        ensemble_folder_name="/tmp/uvr-run-hooks",
        append_ensemble_label=None,
        pair_stems=stems,
        ensemble_outputs=ensemble_outputs,
    )
    settings = Settings.defaults()
    settings.process.stem_focus = focus
    runner = SimpleNamespace(settings=settings, true_model_count=2)
    contributors = {
        typing.cast(typing.Any, stem).group_key: {"member-a", "member-b"} for stem in stems
    }
    collected = {typing.cast(typing.Any, stem).group_key: stem for stem in stems}
    state = SimpleNamespace(
        scratch={
            "ensemble_stem_arrays": {},
            "ensemble_final_base": "Song",
            "ensemble_contributors": contributors,
            "ensemble_stems": collected,
        },
        callbacks=SimpleNamespace(
            console=lambda *_args, **_kwargs: None,
            progress=lambda *_args, **_kwargs: None,
        ),
        base_text="",
        progress_sink=SimpleNamespace(fraction=0.0),
        file_num=1,
        total_files=1,
    )

    _EnsembleRunHooks(
        typing.cast(typing.Any, ensemble),
        is_multi_stem=is_multi_stem,
    ).after_file(runner, typing.cast(typing.Any, state))
    return combined


class RunHooksHomeTests(unittest.TestCase):
    def test_job_runner_source_does_not_define_hook_classes(self) -> None:
        source = (_REPO / "core" / "job_runner.py").read_text(encoding="utf-8")
        self.assertNotIn("class _SingleRunHooks", source)
        self.assertNotIn("class _EnsembleRunHooks", source)

    def test_hook_classes_importable_from_own_module(self) -> None:
        from core.run_hooks import _EnsembleRunHooks, _SingleRunHooks

        self.assertTrue(callable(_SingleRunHooks))
        self.assertTrue(callable(_EnsembleRunHooks))

    def test_job_runner_module_has_no_hook_attributes(self) -> None:
        import core.job_runner as job_runner

        self.assertFalse(hasattr(job_runner, "_SingleRunHooks"))
        self.assertFalse(hasattr(job_runner, "_EnsembleRunHooks"))
        self.assertFalse(hasattr(job_runner, "_model_output_label"))

    def test_model_output_label_prefers_carried_display_label(self) -> None:
        from core.run_hooks import _model_output_label

        model = typing.cast(
            typing.Any,
            SimpleNamespace(
                model_display_label="Friendly Demucs",
                model_name="demucs:raw-id",
                model_basename="raw-id",
                process_method="Demucs",
                repo=None,
            ),
        )

        self.assertEqual(_model_output_label(model), "Friendly Demucs")


class FinalEnsembleFocusTests(unittest.TestCase):
    def test_scoped_raw_focus_selects_exact_multi_and_pair_output(self) -> None:
        from core.ensembler import CollectedStem
        from core.stem_roles import StemLiteral

        scoped_a = CollectedStem(StemLiteral("Center"), "Center A", "member-a")
        scoped_b = CollectedStem(StemLiteral("Center"), "Center B", "member-b")

        for is_multi_stem in (True, False):
            with self.subTest(is_multi_stem=is_multi_stem):
                self.assertEqual(
                    _run_final_ensemble_combine(
                        (scoped_a, scoped_b),
                        "raw:center#scope=member-a",
                        is_multi_stem=is_multi_stem,
                    ),
                    [scoped_a],
                )

    def test_unmatched_scoped_raw_focus_never_widens_to_all_outputs(self) -> None:
        from core.ensembler import CollectedStem
        from core.stem_roles import StemLiteral

        stems = (
            CollectedStem(StemLiteral("Center"), "Center A", "member-a"),
            CollectedStem(StemLiteral("Center"), "Center B", "member-b"),
        )

        for is_multi_stem in (True, False):
            with self.subTest(is_multi_stem=is_multi_stem):
                self.assertEqual(
                    _run_final_ensemble_combine(
                        stems,
                        "raw:center#scope=missing",
                        is_multi_stem=is_multi_stem,
                    ),
                    [],
                )

    def test_ambiguous_scoped_raw_pair_focus_fails_closed(self) -> None:
        from core.ensembler import CollectedStem
        from core.stem_roles import StemLiteral

        stems = (
            CollectedStem(StemLiteral("Center"), "Center A", "shared"),
            CollectedStem(StemLiteral("Center"), "Center B", "shared"),
        )

        self.assertEqual(
            _run_final_ensemble_combine(
                stems,
                "raw:center#scope=shared",
                is_multi_stem=False,
            ),
            [],
        )

    def test_semantic_and_positional_final_focus_behavior_is_unchanged(self) -> None:
        from core.ensembler import CollectedStem
        from core.stem_roles import StemRoleId

        vocals = CollectedStem(StemRoleId("vocal.vocals"), "Vocals")
        instrumental = CollectedStem(StemRoleId("mix.instrumental"), "Instrumental")
        stems = (vocals, instrumental)

        for is_multi_stem in (True, False):
            with self.subTest(is_multi_stem=is_multi_stem, focus="semantic"):
                self.assertEqual(
                    _run_final_ensemble_combine(
                        stems,
                        "vocal.vocals",
                        is_multi_stem=is_multi_stem,
                    ),
                    [vocals],
                )
            with self.subTest(is_multi_stem=is_multi_stem, focus="positional"):
                self.assertEqual(
                    _run_final_ensemble_combine(
                        stems,
                        "primary",
                        is_multi_stem=is_multi_stem,
                    ),
                    [vocals, instrumental],
                )
