"""File-pass hooks live in core.run_hooks, not job_runner."""

from __future__ import annotations

import typing
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.ensembler import CollectedStem
from core.stem_roles import StemRoleId
from core.stems import StemId, StemRoute, StemRouteKind

_REPO = Path(__file__).resolve().parents[1]

VOCALS = StemRoleId("vocal.vocals")
INST = StemRoleId("mix.instrumental")
CENTER = StemRoleId("spatial.center")
SIDE = StemRoleId("spatial.side")


def _native(role: StemRoleId, key: str) -> StemRoute:
    return StemRoute(StemId(key), role, key, key, StemRouteKind.NATIVE)


def _complement(role: StemRoleId, of_role: StemRoleId) -> StemRoute:
    return StemRoute(
        None,
        role,
        str(role),
        str(role),
        StemRouteKind.DERIVED,
        complement_of=of_role,
    )


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


class _RecordingEnsembler:
    """Records combine / write / residual / ensemble_outputs without touching audio."""

    def __init__(self, pair_stems: tuple[CollectedStem, ...], primary_algorithm: str) -> None:
        self.ensemble_folder_name = "/tmp/uvr-run-hooks"
        self.append_ensemble_label = None
        self.pair_stems = pair_stems
        self.primary_algorithm = primary_algorithm
        self.combined = object()
        self.residual = object()
        self.combine_calls: list[tuple[object, dict[str, object]]] = []
        self.write_calls: list[tuple[str, object, object]] = []
        self.residual_calls: list[tuple[object, object, bool]] = []
        self.ensemble_output_calls: list[object] = []

    def combine_stem_waveforms(self, stem: object, **kwargs: object) -> object:
        self.combine_calls.append((stem, kwargs))
        return self.combined

    def write_stem_waveform(self, audio_file_base: str, stem: object, wave: object) -> str:
        self.write_calls.append((audio_file_base, stem, wave))
        return "written"

    def mix_residual(self, mix: object, stem: object, *, invert_spec: bool = False) -> object:
        self.residual_calls.append((mix, stem, invert_spec))
        return self.residual

    def ensemble_outputs(
        self,
        _base: str,
        _path: str,
        stem: object,
        **_kwargs: object,
    ) -> None:
        self.ensemble_output_calls.append(stem)


def _voc_inst_pair() -> tuple[CollectedStem, CollectedStem]:
    return (
        CollectedStem(VOCALS, "Vocals"),
        CollectedStem(INST, "Instrumental"),
    )


def _voc_primary_routes() -> dict[str, tuple[StemRoute, ...]]:
    member = (_native(VOCALS, "vocals"), _complement(INST, VOCALS))
    return {"mdx:a": member, "mdx:b": member}


def _run_recorded_after_file(
    ensemble: _RecordingEnsembler,
    *,
    derive: bool,
    is_multi_stem: bool,
    focus: str = "",
    member_routes: dict[str, tuple[StemRoute, ...]] | None = None,
    invert_spec: bool = False,
    decoded_mix: object | None = None,
    stem_arrays: dict | None = None,
    stem_paths: dict | None = None,
    pair_stems: tuple[CollectedStem, ...] | None = None,
) -> _RecordingEnsembler:
    from core.run_hooks import _EnsembleRunHooks
    from core.settings import Settings

    settings = Settings.defaults()
    settings.ensemble.derive_complement_from_mix = derive
    settings.process.stem_focus = focus
    settings.mdx.is_invert_spec = invert_spec
    stems = pair_stems if pair_stems is not None else ensemble.pair_stems
    contributors = {stem.group_key: {"member-a", "member-b"} for stem in stems}
    collected = {stem.group_key: stem for stem in stems}
    arrays = {} if stem_arrays is None else stem_arrays
    paths = {} if stem_paths is None else stem_paths
    scratch: dict[str, object] = {
        "ensemble_stem_arrays": arrays,
        "ensemble_stem_paths": paths,
        "ensemble_final_base": "Song",
        "ensemble_contributors": contributors,
        "ensemble_stems": collected,
    }
    if member_routes is not None:
        scratch["ensemble_member_routes"] = member_routes
    state = SimpleNamespace(
        scratch=scratch,
        decoded_mix=decoded_mix,
        callbacks=SimpleNamespace(
            console=lambda *_args, **_kwargs: None,
            progress=lambda *_args, **_kwargs: None,
        ),
        base_text="",
        progress_sink=SimpleNamespace(fraction=0.0),
        file_num=1,
        total_files=1,
    )
    runner = SimpleNamespace(settings=settings, true_model_count=2)
    _EnsembleRunHooks(typing.cast(typing.Any, ensemble), is_multi_stem=is_multi_stem).after_file(
        runner, typing.cast(typing.Any, state)
    )
    return ensemble


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
        vocals, instrumental = _voc_inst_pair()
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


class PairConsistentHookTests(unittest.TestCase):
    def test_after_chunk_stores_export_routes_even_when_chunked(self) -> None:
        from core.run_hooks import _EnsembleRunHooks

        routes = (_native(VOCALS, "vocals"), _complement(INST, VOCALS))
        model = SimpleNamespace(
            canonical_id="mdx:voc-a",
            selected_stem_routes=routes,
            available_stem_routes=(),
            is_vocal_split_model=False,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_inst_only_voc_splitter=False,
            is_sec_bv_rebalance=False,
            is_ensemble_mode=False,
        )
        vocals, instrumental = _voc_inst_pair()
        ensemble = _RecordingEnsembler((vocals, instrumental), "Max Spec")
        for chunked in (True, False):
            with self.subTest(chunked=chunked):
                state = SimpleNamespace(
                    scratch={
                        "ensemble_stems": {},
                        "ensemble_contributors": {},
                        "ensemble_stem_arrays": {},
                        "ensemble_stem_paths": {},
                        "member_paths": {},
                        "member_stem_parts": {},
                    }
                )
                _EnsembleRunHooks(
                    typing.cast(typing.Any, ensemble), is_multi_stem=False
                ).after_chunk(
                    SimpleNamespace(),
                    typing.cast(typing.Any, state),
                    model,
                    stems={},
                    paths={},
                    chunked=chunked,
                )
                self.assertEqual(
                    state.scratch.get("ensemble_member_routes", {}).get("mdx:voc-a"),
                    routes,
                )

    def test_flag_off_still_calls_ensemble_outputs_for_both_pair_stems(self) -> None:
        vocals, instrumental = _voc_inst_pair()
        mix = object()
        recorded = _run_recorded_after_file(
            _RecordingEnsembler((vocals, instrumental), "Max Spec"),
            derive=False,
            is_multi_stem=False,
            member_routes=_voc_primary_routes(),
            decoded_mix=mix,
        )
        self.assertEqual(recorded.ensemble_output_calls, [vocals, instrumental])
        self.assertEqual(recorded.combine_calls, [])
        self.assertEqual(recorded.write_calls, [])
        self.assertEqual(recorded.residual_calls, [])

    def test_voc_primary_combines_vocals_and_writes_mix_residual_instrumental(self) -> None:
        vocals, instrumental = _voc_inst_pair()
        mix = object()
        arrays = {vocals.group_key: [object(), object()]}
        paths = {vocals.group_key: ["/tmp/a.wav", "/tmp/b.wav"]}
        recorded = _run_recorded_after_file(
            _RecordingEnsembler((vocals, instrumental), "Max Spec"),
            derive=True,
            is_multi_stem=False,
            member_routes=_voc_primary_routes(),
            invert_spec=True,
            decoded_mix=mix,
            stem_arrays=arrays,
            stem_paths=paths,
        )
        self.assertEqual(len(recorded.combine_calls), 1)
        combined_stem, kwargs = recorded.combine_calls[0]
        self.assertEqual(combined_stem, vocals)
        self.assertEqual(kwargs["algorithm"], "Max Spec")
        self.assertIs(kwargs["stem_arrays"], arrays)
        self.assertIs(kwargs["stem_paths"], paths)
        self.assertEqual(
            recorded.write_calls,
            [
                ("Song", vocals, recorded.combined),
                ("Song", instrumental, recorded.residual),
            ],
        )
        self.assertEqual(recorded.residual_calls, [(mix, recorded.combined, True)])
        self.assertEqual(recorded.ensemble_output_calls, [])

    def test_flag_on_four_stem_still_calls_ensemble_outputs_per_native(self) -> None:
        vocals, instrumental = _voc_inst_pair()
        recorded = _run_recorded_after_file(
            _RecordingEnsembler((vocals, instrumental), "Max Spec"),
            derive=True,
            is_multi_stem=True,
            member_routes=_voc_primary_routes(),
            decoded_mix=object(),
        )
        self.assertEqual(recorded.ensemble_output_calls, [vocals, instrumental])
        self.assertEqual(recorded.combine_calls, [])
        self.assertEqual(recorded.write_calls, [])
        self.assertEqual(recorded.residual_calls, [])

    def test_leftover_focus_combines_vocals_and_writes_only_instrumental(self) -> None:
        vocals, instrumental = _voc_inst_pair()
        mix = object()
        recorded = _run_recorded_after_file(
            _RecordingEnsembler((vocals, instrumental), "Max Spec"),
            derive=True,
            is_multi_stem=False,
            focus="mix.instrumental",
            member_routes=_voc_primary_routes(),
            decoded_mix=mix,
        )
        self.assertEqual(len(recorded.combine_calls), 1)
        self.assertEqual(recorded.combine_calls[0][0], vocals)
        self.assertEqual(recorded.write_calls, [("Song", instrumental, recorded.residual)])
        self.assertEqual(recorded.residual_calls, [(mix, recorded.combined, False)])
        self.assertEqual(recorded.ensemble_output_calls, [])

    def test_dual_native_routes_call_ensemble_outputs_for_center_and_side(self) -> None:
        center = CollectedStem(CENTER, "Center")
        side = CollectedStem(SIDE, "Side")
        member = (_native(CENTER, "mid"), _native(SIDE, "side"))
        recorded = _run_recorded_after_file(
            _RecordingEnsembler((center, side), "Max Spec"),
            derive=True,
            is_multi_stem=False,
            member_routes={"mdx:a": member, "mdx:b": member},
            decoded_mix=object(),
            pair_stems=(center, side),
        )
        self.assertEqual(recorded.ensemble_output_calls, [center, side])
        self.assertEqual(recorded.combine_calls, [])
        self.assertEqual(recorded.write_calls, [])
        self.assertEqual(recorded.residual_calls, [])
