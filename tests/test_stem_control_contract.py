"""Characterize persisted stem choices through resolution, planning and writing.

Known compatibility limits are assertions, not expected failures: native subsets
are runtime-supported but job projection ignores their sidecars; reviewed Include
complement creates an unused array; arbitrary native/derived unions have no
settings encoding. Do not use these gaps to broaden the direct control modes.
"""

from __future__ import annotations

import itertools
import unittest
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import numpy as np

from bundled.constants import secondary_stem
from core.job_plan_types import ModelDescriptor
from core.job_projection import select_output_routes
from core.job_route_observations import collect_output_route_evidence
from core.settings import Settings
from core.stem_selection import DemucsView, ExclusiveView, SubsetView
from core.stems import (
    FOCUS_PRIMARY,
    FOCUS_SECONDARY,
    StemRoute,
    StemSelectionStatus,
    model_stem_routes,
    persisted_stem_focus,
    select_stem_routes,
)
from engines.demucs_export import DemucsExportRequest, DemucsNativeResult, plan_demucs_export
from engines.mdx_c_engine import SeperateMDXC
from engines.stem_writer import ExportPlan, export_source_map
from tests.stem_control_cases import (
    KARAOKE_THREE,
    NATIVE_FIFTY_THREE,
    NATIVE_FIVE,
    NATIVE_FOUR,
    NATIVE_THREE,
    PAIR_MODELS,
    manifest_case,
    manifest_routes,
    resolved_demucs_model,
    resolved_mdx_model,
    route_ids,
    selection_state,
)
from tests.test_mdx_export_routing import _derived, _mdxc_fake, _native


def projected_routes(model: Any) -> tuple[StemRoute, ...]:
    family, basename = model.canonical_id.split(":", 1)
    descriptors = (
        ModelDescriptor(
            model.canonical_id,
            family,
            basename,
            basename,
            primary_stem=model.primary_stem,
            secondary_stem=model.secondary_stem,
            routes=model.available_stem_routes,
        ),
    )
    evidence = collect_output_route_evidence(model.settings, descriptors, command="separate")
    return select_output_routes(
        model.settings, descriptors, command="separate", evidence=evidence
    ).routes


def mdxc_plan(model: Any, *, combine: bool = False, invert: bool = False) -> ExportPlan:
    sources = {
        stem: np.full((2, 8), index + 1.0) for index, stem in enumerate(model.mdx_model_stems)
    }
    fake: Any = _mdxc_fake(
        sources=sources,
        mix=np.full((2, 8), 100.0),
        available_routes=model.available_stem_routes,
        selected_routes=model.selected_stem_routes,
        primary_stem=model.primary_stem,
        secondary_stem=model.secondary_stem,
        invert_spec=invert,
    )
    fake.mdx_c_configs.training.instruments = list(sources)
    fake.mdxnet_stem_select = model.settings.mdx.stems
    fake.is_mdx_include_stem_complement = model.settings.mdx.is_mdx_include_stem_complement
    fake.is_mdx_combine_stems = combine
    # The numerical inversion kernel is covered by its existing tests. Here the
    # deterministic transform proves this flag preserves identities and writes.
    with patch("ml.spec_utils.invert_stem", side_effect=lambda mix, src: (mix - src).T):
        return SeperateMDXC.seperate(fake)


def scheduled_routes(model: Any, plan: ExportPlan) -> tuple[StemRoute, ...]:
    writer = SimpleNamespace(
        selected_stem_routes=model.selected_stem_routes,
        available_stem_routes=model.available_stem_routes,
        is_vocal_split_model=False,
        is_ensemble_mode=False,
        begin_save_phase=Mock(),
        stem_export_wav_path=lambda name, **kwargs: f"/unused/{name}.wav",
        write_audio=Mock(),
    )
    export_source_map(writer, plan.sources, plan.samplerate, extra_sources=plan.extra_sources)
    return tuple(call.kwargs["route"] for call in writer.write_audio.call_args_list)


class ManifestStemControlContractTests(unittest.TestCase):
    def test_karaoke_all_defaults_exclude_optional_combined_output(self) -> None:
        outputs = manifest_case(KARAOKE_THREE)["outputs"]
        self.assertEqual(len(outputs), 4)
        self.assertEqual(
            [o["role"] for o in outputs if o["selected_by_default"]],
            ["vocal.lead", "vocal.backing", "mix.instrumental"],
        )
        self.assertEqual(outputs[-1]["role"], "mix.instrumental_with_backing_vocals")
        self.assertFalse(outputs[-1]["selected_by_default"])

    def test_exceptional_inventories_match_oracle_without_label_identity(self) -> None:
        for model_id in (
            *PAIR_MODELS,
            KARAOKE_THREE,
            NATIVE_THREE,
            NATIVE_FOUR,
            NATIVE_FIVE,
            NATIVE_FIFTY_THREE,
            "demucs:htdemucs",
            "demucs:htdemucs_6s",
        ):
            with self.subTest(model=model_id):
                outputs = manifest_case(model_id)["outputs"]
                routes = manifest_routes(model_id)
                expected = {
                    (o["native"], o["role"], o["production"], o["selected_by_default"])
                    for o in outputs
                }
                actual = {
                    (
                        r.native.raw if r.native else None,
                        r.concept,
                        r.kind.value,
                        r.selected_by_default,
                    )
                    for r in routes
                }
                self.assertEqual(actual, expected)
                self.assertEqual(len(set(route_ids(routes))), len(routes))
                self.assertEqual(
                    route_ids(routes),
                    route_ids(
                        tuple(
                            replace(r, label="Same display", filename_tag="Same file")
                            for r in routes
                        )
                    ),
                )

    def test_every_exceptional_pair_side_round_trips_exact_focus(self) -> None:
        for model_id in PAIR_MODELS:
            state = selection_state(model_id)
            for route in (*state.routes, None):
                with self.subTest(model=model_id, route=route):
                    settings = Settings.defaults()
                    view = ExclusiveView(route.concept if route else "all")
                    state.write(settings, view)
                    self.assertEqual(state.read(settings), view)
                    model = resolved_mdx_model(model_id, settings)
                    expected = (route,) if route else state.routes
                    self.assertEqual(route_ids(model.selected_stem_routes), route_ids(expected))
                    self.assertEqual(route_ids(projected_routes(model)), route_ids(expected))

    def test_imported_positional_karaoke_focus_is_logical_not_native_order(self) -> None:
        state = selection_state("mdx:bs_karaoke_anvuew")
        for focus, role in (
            (FOCUS_PRIMARY, "mix.instrumental_with_backing_vocals"),
            (FOCUS_SECONDARY, "vocal.lead"),
        ):
            with self.subTest(focus=focus):
                settings = Settings.defaults()
                settings.process.stem_focus = focus
                self.assertEqual(state.read(settings), ExclusiveView(role))
                model = resolved_mdx_model("mdx:bs_karaoke_anvuew", settings)
                self.assertEqual([r.concept for r in model.selected_stem_routes], [role])
                self.assertEqual(projected_routes(model), model.selected_stem_routes)


class NativeStemControlContractTests(unittest.TestCase):
    def check_selection(self, model_id: str, indices: tuple[int, ...]) -> None:
        state = selection_state(model_id)
        natives = tuple(r for r in state.routes if r.native is not None)
        expected = tuple(natives[index] for index in indices)
        settings = Settings.defaults()
        state.write(settings, SubsetView("custom", {r.concept for r in expected}, False))
        readback = state.read(settings)
        self.assertIsInstance(readback, SubsetView)
        assert isinstance(readback, SubsetView)
        if len(expected) == len(natives):
            self.assertTrue(readback.custom_all)
        else:
            self.assertEqual(readback.selected, {r.concept for r in expected})
        model = resolved_mdx_model(model_id, settings)
        if model_id == KARAOKE_THREE and indices == (1, 2):
            # Existing fuzzy native-sidecar lookup maps backing_vocal to the
            # earlier lead route. The controller must reject this combination.
            expected = (natives[0], natives[2])
        self.assertEqual(route_ids(model.selected_stem_routes), route_ids(expected))
        plan = mdxc_plan(model)
        self.assertEqual(route_ids(scheduled_routes(model, plan)), route_ids(expected))
        for audio in plan.sources.values():
            self.assertEqual(audio.shape, (8, 2))
        if 1 < len(expected) < len(natives):
            # Existing plan projection ignores the native sidecar. The new
            # controls must preserve runtime subsets without claiming parity.
            self.assertEqual(settings.process.stem_focus, "")
            defaults = tuple(r for r in model.available_stem_routes if r.selected_by_default)
            self.assertEqual(projected_routes(model), defaults)
            self.assertNotEqual(projected_routes(model), model.selected_stem_routes)
        else:
            self.assertEqual(projected_routes(model), model.selected_stem_routes)

    def test_every_native_singleton_pair_and_defaults_for_small_inventories(self) -> None:
        for model_id in (KARAOKE_THREE, NATIVE_THREE, NATIVE_FOUR, NATIVE_FIVE):
            count = sum(r.native is not None for r in manifest_routes(model_id))
            subsets = [
                *(itertools.combinations(range(count), 1)),
                *(itertools.combinations(range(count), 2)),
                tuple(range(count)),
            ]
            for indices in subsets:
                with self.subTest(model=model_id, indices=indices):
                    self.check_selection(model_id, indices)

    def test_fifty_three_defaults_edges_and_sparse_selection_keep_native_keys(self) -> None:
        self.assertEqual(len(manifest_routes(NATIVE_FIFTY_THREE)), 53)
        for indices in (tuple(range(53)), (0,), (52,), (0, 7, 24, 52)):
            with self.subTest(indices=indices):
                self.check_selection(NATIVE_FIFTY_THREE, indices)

    def test_optional_derived_singleton_exclusive_encoding_reaches_planner_and_writer(self) -> None:
        state = selection_state(KARAOKE_THREE)
        derived = next(r for r in state.routes if r.native is None)
        settings = Settings.defaults()
        state.write(settings, ExclusiveView(derived.concept))
        self.assertEqual(settings.process.stem_focus, persisted_stem_focus(derived))
        self.assertEqual(settings.mdx.stems_selected, [])
        model = resolved_mdx_model(KARAOKE_THREE, settings)
        self.assertEqual(model.selected_stem_routes, (derived,))
        self.assertEqual(projected_routes(model), (derived,))
        for combine, invert in itertools.product((False, True), repeat=2):
            with self.subTest(combine=combine, invert=invert):
                plan = mdxc_plan(model, combine=combine, invert=invert)
                self.assertEqual(scheduled_routes(model, plan), (derived,))
                # The reviewed sum recipe is backing + instrumental, regardless
                # of the generic complement recipe switches.
                signature = model.mdx_model_stems
                value = signature.index("backing_vocal") + signature.index("instrumental") + 2
                np.testing.assert_array_equal(plan.sources[derived.concept], np.full((8, 2), value))

    def test_legacy_subset_read_requires_exact_derived_override_in_controller(self) -> None:
        state = selection_state(KARAOKE_THREE)
        derived = next(r for r in state.routes if r.native is None)
        settings = Settings.defaults()
        state.write(settings, ExclusiveView(derived.concept))
        view = state.read(settings)
        # Existing state.read uses the empty native sidecar and displays All.
        # The new controller must inspect exact derived focus before this call.
        self.assertIsInstance(view, SubsetView)
        assert isinstance(view, SubsetView)
        self.assertTrue(view.custom_all)
        self.assertEqual(settings.process.stem_focus, derived.concept)
        self.assertEqual(
            resolved_mdx_model(KARAOKE_THREE, settings).selected_stem_routes, (derived,)
        )

    def test_native_plus_derived_subset_has_no_existing_sidecar_encoding(self) -> None:
        state = selection_state(KARAOKE_THREE)
        derived = next(r for r in state.routes if r.native is None)
        for native in (r for r in state.routes if r.native is not None):
            with self.subTest(native=native.concept):
                settings = Settings.defaults()
                state.write(
                    settings, SubsetView("custom", {native.concept, derived.concept}, False)
                )
                assert native.native is not None
                self.assertEqual(settings.mdx.stems_selected, [native.native.raw])
                model = resolved_mdx_model(KARAOKE_THREE, settings)
                self.assertEqual(model.selected_stem_routes, (native,))

    def test_include_complement_materializes_but_does_not_schedule_unselected_output(self) -> None:
        for model_id in (KARAOKE_THREE, NATIVE_THREE, NATIVE_FOUR, NATIVE_FIVE):
            state = selection_state(model_id)
            natives = tuple(r for r in state.routes if r.native is not None)
            for size, include, combine, invert in itertools.product(
                (1, 2), (False, True), (False, True), (False, True)
            ):
                with self.subTest(
                    model=model_id, size=size, include=include, combine=combine, invert=invert
                ):
                    settings = Settings.defaults()
                    settings.mdx.is_mdx_include_stem_complement = include
                    expected = natives[:size]
                    state.write(
                        settings, SubsetView("custom", {r.concept for r in expected}, False)
                    )
                    model = resolved_mdx_model(model_id, settings)
                    plan = mdxc_plan(model, combine=combine, invert=invert)
                    self.assertEqual(scheduled_routes(model, plan), expected)
                    native_keys = {r.native.raw for r in expected if r.native is not None}
                    extras = set(plan.sources) - native_keys
                    expected_extra = (
                        {secondary_stem(next(iter(native_keys)))}
                        if include and size == 1
                        else set()
                    )
                    self.assertEqual(extras, expected_extra)


class DemucsStemControlContractTests(unittest.TestCase):
    def test_full_constructor_native_focus_and_unsupported_remainder_matrix(self) -> None:
        for model_id in ("demucs:htdemucs", "demucs:htdemucs_6s"):
            state = selection_state(model_id)
            cases = (
                (DemucsView("quick_all", "all", False), "", None),
                (DemucsView("instrument.bass", "Bass", True), "instrument.bass", "instrument.bass"),
                (
                    DemucsView("instrument.bass", "raw:no bass", True),
                    "instrument.bass.removed",
                    None,
                ),
                (DemucsView("instrument.bass", "all", True), "", None),
                (DemucsView("focus_vocals", "all", False), "vocal.vocals", "vocal.vocals"),
                (DemucsView("focus_instrumental", "all", False), "mix.instrumental", None),
            )
            for view, persisted, single_role in cases:
                with self.subTest(model=model_id, view=view):
                    settings = Settings.defaults()
                    state.write(settings, view)
                    self.assertEqual(settings.process.stem_focus, persisted)
                    restored = state.read(settings)
                    self.assertIsInstance(restored, DemucsView)
                    assert isinstance(restored, DemucsView)
                    self.assertEqual(restored.active, view.active)
                    model = resolved_demucs_model(model_id, settings)
                    self.assertEqual(model.process_method, "Demucs")
                    self.assertEqual(model.demucs_stems, settings.demucs.stems)
                    if view.active == "instrument.bass":
                        self.assertEqual(model.primary_stem, "bass")
                        self.assertEqual(model.secondary_stem, "No bass")
                    available = model.available_stem_routes
                    expected = (
                        tuple(r for r in available if r.concept == single_role)
                        if single_role
                        else available
                    )
                    # Canonical declarations have no remainder route. The
                    # unsupported focus/both encodings fall back to all natives.
                    self.assertEqual(model.selected_stem_routes, expected)
                    self.assertEqual(projected_routes(model), expected)
                    mapping = model.demucs_source_map
                    source = np.stack([np.full((2, 8), i + 1.0) for i in range(len(mapping))])
                    plan = plan_demucs_export(
                        DemucsExportRequest(
                            native=DemucsNativeResult(source, np.full((2, 8), 100.0), mapping),
                            routes=expected,
                            write_all_sources=single_role is None,
                            blend=lambda src, secondary=None: src,
                            blended_sources={
                                name: source[index].T for name, index in mapping.items()
                            },
                            primary_stem=model.primary_stem or "",
                            secondary_stem=model.secondary_stem or "",
                            exports_primary=single_role is not None,
                        )
                    )
                    self.assertEqual(scheduled_routes(model, plan), expected)

    def test_legacy_preprocess_sidecar_requires_focused_secondary_and_preprocessor(self) -> None:
        source = np.stack([np.full((2, 8), i + 1.0) for i in range(4)])
        request = DemucsExportRequest(
            native=DemucsNativeResult(
                source,
                np.full((2, 8), 20.0),
                {"Bass": 0, "Drums": 1, "Other": 2, "Vocals": 3},
                inst_mix=np.full((2, 8), 12.0),
            ),
            routes=(_native("bass"), _derived("No Bass")),
            write_all_sources=False,
            blend=lambda src, secondary=None: src,
            primary_stem="Bass",
            secondary_stem="No Bass",
            exports_primary=True,
        )
        for write_secondary, include, has_preprocessor, ensemble in itertools.product(
            (False, True), repeat=4
        ):
            with self.subTest(
                secondary=write_secondary,
                include=include,
                preprocessor=has_preprocessor,
                ensemble=ensemble,
            ):
                plan = plan_demucs_export(
                    replace(
                        request,
                        write_secondary=write_secondary,
                        is_demucs_pre_proc_model_inst_mix=include,
                        has_pre_proc_model=has_preprocessor,
                        is_4_stem_ensemble=ensemble,
                    )
                )
                enabled = write_secondary and include and has_preprocessor and not ensemble
                self.assertEqual(
                    tuple(plan.extra_sources), ("No Bass Instrumental",) if enabled else ()
                )
                if enabled:
                    np.testing.assert_array_equal(
                        plan.extra_sources["No Bass Instrumental"], np.full((8, 2), 11.0)
                    )


class RawAndAdditionalOutputContractTests(unittest.TestCase):
    def test_raw_focus_is_bound_to_model_signature_and_unknown_focus_defaults(self) -> None:
        model = SimpleNamespace(
            canonical_id="mdx:contract-unknown",
            mdx_model_stems=["Alpha", "Beta"],
            primary_stem="Alpha",
            secondary_stem="Beta",
            is_vocal_split_model=False,
        )
        routes = model_stem_routes(model)
        focus = persisted_stem_focus(routes[0])
        self.assertTrue(routes[0].selection_scope)
        self.assertEqual(select_stem_routes(routes, focus).routes, routes[:1])
        for change in (
            {"canonical_id": "mdx:another-unknown"},
            {"mdx_model_stems": ["Alpha", "Gamma"]},
        ):
            changed = SimpleNamespace(**{**vars(model), **change})
            selection = select_stem_routes(model_stem_routes(changed), focus)
            self.assertEqual(selection.status, StemSelectionStatus.UNMATCHED)
        self.assertEqual(
            select_stem_routes(routes, "nonexistent.role").status, StemSelectionStatus.UNMATCHED
        )
        self.assertEqual(select_stem_routes(routes, "").routes, routes)

    def test_duplicate_native_signature_remains_raw_not_semantically_inferred(self) -> None:
        from core.model_stem_manifest import resolve_model_stem_semantics
        from core.stem_roles import StemRoleId
        from core.stems import _semantic_routes

        semantics = resolve_model_stem_semantics(
            NATIVE_THREE, native_stems=("speech", "speech", "effects"), backend_primary="speech"
        )
        routes = _semantic_routes(semantics)
        self.assertTrue(routes)
        self.assertTrue(all(not isinstance(r.role, StemRoleId) for r in routes))

    def test_splitter_schedules_only_lead_backing_and_not_dependency_instrumental(self) -> None:
        from engines.mdx_c_export import vocal_split_pair_sources
        from engines.stem_writer import vocal_split_pair_routes

        routes = manifest_routes(KARAOKE_THREE, "vocal_split")
        pair = vocal_split_pair_routes(routes)
        self.assertEqual({r.concept for r in pair}, {"vocal.lead", "vocal.backing"})
        sources = {r.native.raw: np.full((2, 8), i + 1.0) for i, r in enumerate(routes) if r.native}
        plan = vocal_split_pair_sources(sources, np.full((2, 8), 10.0), routes=routes)
        self.assertEqual(set(plan), {"vocals", "backing_vocal"})
        self.assertNotIn("instrumental", plan)

    def test_deverb_runs_only_for_matching_vocal_nonensemble_output(self) -> None:
        from engines.stem_writer import _save_with_message

        sep = SimpleNamespace(
            is_deverb_vocals=True,
            deverb_vocal_opt="ALL",
            write_to_console=Mock(),
        )
        for bucket, nonensemble, enabled in (
            ("Vocals", True, True),
            ("Bass", True, False),
            ("Vocals", False, False),
        ):
            with self.subTest(bucket=bucket, nonensemble=nonensemble):
                from core.stems import StemBucket

                with (
                    patch("engines.stem_writer.stem_concept", return_value=StemBucket(bucket)),
                    patch("engines.stem_writer._deverb_vocals") as deverb,
                    patch("engines.stem_writer._save_audio_file") as save,
                ):
                    _save_with_message(
                        sep,
                        "/unused/out.wav",
                        bucket,
                        np.zeros((8, 2)),
                        samplerate=44100,
                        buffer_stem_name=None,
                        is_not_ensemble=nonensemble,
                    )
                    self.assertEqual(deverb.call_count, int(enabled))
                    self.assertEqual(save.call_count, 1)

    def test_deverb_writes_two_additional_files_after_the_applicability_gate(self) -> None:
        from engines.stem_writer import _deverb_vocals

        sep = SimpleNamespace(
            write_to_console=Mock(),
            device="cpu",
            DEVERBER_MODEL="unused",
            settings=Settings.defaults(),
            deverb_progress_callback=Mock(),
            check_run_control=Mock(),
        )
        audio = np.zeros((8, 2))
        with (
            patch("engines.stem_writer.vr_denoiser", return_value=(audio, audio)),
            patch("engines.stem_writer._save_audio_file") as save,
        ):
            _deverb_vocals(
                sep,
                "/unused/Vocals.wav",
                audio,
                samplerate=44100,
                buffer_stem_name=None,
                is_not_ensemble=True,
            )
        self.assertEqual(
            [c.args[1] for c in save.call_args_list],
            ["/unused/Vocals_deverbed.wav", "/unused/Vocals_reverb_only.wav"],
        )


if __name__ == "__main__":
    unittest.main()
