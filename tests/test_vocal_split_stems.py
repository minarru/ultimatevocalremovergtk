"""Vocal-splitter stem pairing across community MDX-C yaml shapes."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

from bundled.constants import (
    BV_VOCAL_STEM,
    INST_STEM,
    LEAD_VOCAL_STEM,
    VOCAL_STEM,
)
from core.model_stem_semantics import (
    pick_backing_key,
    pick_instrumental_key,
    pick_vocal_key,
    vocal_inst_from_sources,
    vocal_split_source_roles,
)
from core.stem_pairs import stem_pair_definition
from core.stem_roles import StemRoleId
from core.stems import (
    StemBucket,
    bucket_for_model_stem,
    model_stem_routes,
    routes_for_ensemble_pair,
    run_export_routes,
)
from engines.base import SeperateAttributes
from engines.mdx_c import mdx_vocal_split_chain_sources
from engines.mdx_c_engine import SeperateMDXC
from engines.orchestration import process_chain_model


def _arr(fill: float) -> np.ndarray:
    return np.full((2, 4), fill, dtype=np.float32)


def _split_bucket(stem: str | None, *, is_bv: bool = False) -> StemBucket:
    """The splitter-role concept for a native stem (the old remap's job)."""
    return bucket_for_model_stem(stem or "", stem_count=2, is_bv=is_bv, is_vocal_split=True)


def _semantic_model(
    canonical_id: str,
    native_stems: list[str],
    *,
    backend_primary: str,
    vocal_split: bool,
) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        canonical_id=canonical_id,
        mdx_model_stems=native_stems,
        demucs_source_list=[],
        primary_stem_native=backend_primary,
        primary_stem=backend_primary,
        secondary_stem=native_stems[1],
        target_instrument="",
        is_vocal_split_model=vocal_split,
        is_karaoke=True,
        is_bv_model="BVE" in canonical_id,
        mdx_stem_count=len(native_stems),
        mdxnet_stems_selected=[],
    )


class ReviewedVocalSplitContextTests(unittest.TestCase):
    def _labels(
        self,
        canonical_id: str,
        native_stems: list[str],
        backend_primary: str,
        *,
        vocal_split: bool,
    ) -> list[str]:
        return [
            route.label
            for route in model_stem_routes(
                _semantic_model(
                    canonical_id,
                    native_stems,
                    backend_primary=backend_primary,
                    vocal_split=vocal_split,
                )
            )
        ]

    def test_ordinary_karaoke_changes_only_accompaniment_meaning(self) -> None:
        model_id = "mdx:bs_karaoke_becruily"
        self.assertEqual(
            self._labels(model_id, ["Vocals", "Instrumental"], "Vocals", vocal_split=False),
            ["Lead Vocals", "Instrumental with Backing Vocals"],
        )
        self.assertEqual(
            self._labels(model_id, ["Vocals", "Instrumental"], "Vocals", vocal_split=True),
            ["Lead Vocals", "Backing Vocals"],
        )

    def test_vr_bve_reverses_context_semantics_without_flipping_native(self) -> None:
        model_id = "vr:UVR-BVE-4B_SN-44100-1"
        self.assertEqual(
            self._labels(model_id, ["Vocals", "Instrumental"], "Vocals", vocal_split=False),
            ["Backing Vocals", "Instrumental with Lead Vocals"],
        )
        self.assertEqual(
            self._labels(model_id, ["Vocals", "Instrumental"], "Vocals", vocal_split=True),
            ["Backing Vocals", "Lead Vocals"],
        )

    def test_both_melband_bve_models_keep_ordinary_karaoke_semantics(self) -> None:
        for model_id in (
            "mdx:mbr_bve_gonzaluigi",
            "mdx:model_MelBand-Roformer_BVE_by-Gonza",
        ):
            with self.subTest(model_id=model_id, context="full_mix"):
                self.assertEqual(
                    self._labels(model_id, ["Lead", "Back"], "Lead", vocal_split=False),
                    ["Lead Vocals", "Instrumental with Backing Vocals"],
                )
            with self.subTest(model_id=model_id, context="vocal_split"):
                self.assertEqual(
                    self._labels(model_id, ["Lead", "Back"], "Lead", vocal_split=True),
                    ["Lead Vocals", "Backing Vocals"],
                )

    def test_giantailab_third_route_stays_distinct_from_karaoke_pair(self) -> None:
        model_id = "mdx:bs_karaoke_3stem_giantailab"
        self.assertEqual(
            self._labels(
                model_id,
                ["vocals", "backing_vocal", "instrumental"],
                "vocals",
                vocal_split=False,
            ),
            ["Lead Vocals", "Backing Vocal", "Instrumental with Backing Vocals"],
        )
        self.assertEqual(
            self._labels(
                model_id,
                ["vocals", "backing_vocal", "instrumental"],
                "vocals",
                vocal_split=True,
            ),
            ["Lead Vocals", "Backing Vocal", "Backing Vocals"],
        )

    def test_giantailab_pair_and_multi_mode_keep_exact_role_membership(self) -> None:
        model = _semantic_model(
            "mdx:bs_karaoke_3stem_giantailab",
            ["vocals", "backing_vocal", "instrumental"],
            backend_primary="vocals",
            vocal_split=False,
        )
        routes = model_stem_routes(model)
        karaoke = stem_pair_definition("pair.karaoke")
        assert karaoke is not None

        self.assertEqual(
            [route.role for route in routes_for_ensemble_pair(routes, karaoke)],
            [
                StemRoleId("vocal.lead"),
                StemRoleId("mix.instrumental_with_backing_vocals"),
            ],
        )

        from core.settings import Settings

        model.is_ensemble_mode = True
        model.available_stem_routes = routes
        model.selected_stem_routes = routes_for_ensemble_pair(routes, karaoke)
        model.settings = Settings.defaults()
        model.settings.ensemble.main_stem = "mode.multi_stem"
        self.assertEqual(tuple(run_export_routes(model)), routes)


class VocalSplitRoleBucketTests(unittest.TestCase):
    """The 2x2 splitter table, now owned by ``bucket_for_model_stem``.

    These assertions moved off the deleted ``vocal_split_primary_stem`` /
    ``vocal_split_write_logic_stem`` helpers, which encoded the same table a
    second time. ``lead_only``/``backing_only`` are input aliases only; a run
    resolves to ``LEAD_VOCALS``/``BACKING_VOCALS`` instead.
    """

    def test_title_case_vocals_is_lead(self) -> None:
        self.assertEqual(_split_bucket("Vocals"), StemBucket.LEAD_VOCALS)

    def test_lowercase_vocals_is_lead(self) -> None:
        self.assertEqual(_split_bucket("vocals"), StemBucket.LEAD_VOCALS)

    def test_bv_model_inverts(self) -> None:
        self.assertEqual(_split_bucket("Vocals", is_bv=True), StemBucket.BACKING_VOCALS)
        self.assertEqual(_split_bucket("other", is_bv=True), StemBucket.LEAD_VOCALS)

    def test_other_native_is_backing(self) -> None:
        self.assertEqual(_split_bucket("other"), StemBucket.BACKING_VOCALS)
        self.assertEqual(_split_bucket("Instrumental"), StemBucket.BACKING_VOCALS)

    def test_lead_only_alias_still_reads_as_lead(self) -> None:
        self.assertEqual(_split_bucket(LEAD_VOCAL_STEM), StemBucket.LEAD_VOCALS)
        self.assertEqual(_split_bucket(BV_VOCAL_STEM), StemBucket.BACKING_VOCALS)

    def test_empty_and_unknown_are_unknown_not_backing(self) -> None:
        # The old helper defaulted a missing/unrecognized stem to backing
        # vocals; UNKNOWN makes write_audio skip it instead of mislabelling it.
        for stem in ("", None, "center"):
            with self.subTest(stem=stem):
                self.assertEqual(_split_bucket(stem), StemBucket.UNKNOWN)


class SourcePickerTests(unittest.TestCase):
    def test_title_case_voc_inst(self) -> None:
        sources = {"Vocals": 1, "Instrumental": 2}
        self.assertEqual(pick_vocal_key(sources), "Vocals")
        self.assertEqual(pick_backing_key(sources), "Instrumental")
        self.assertEqual(pick_instrumental_key(sources), "Instrumental")

    def test_lowercase_vocals_other(self) -> None:
        sources = {"vocals": 1, "other": 2}
        self.assertEqual(pick_vocal_key(sources), "vocals")
        self.assertEqual(pick_backing_key(sources), "other")
        self.assertEqual(pick_instrumental_key(sources), "other")

    def test_backing_vocal_preferred_over_instrumental(self) -> None:
        sources = {"vocals": 1, "backing_vocal": 2, "instrumental": 3}
        self.assertEqual(pick_vocal_key(sources), "vocals")
        self.assertEqual(pick_backing_key(sources), "backing_vocal")
        self.assertEqual(pick_instrumental_key(sources), "instrumental")

    def test_four_stem_other_is_not_instrumental_or_backing(self) -> None:
        sources = {"drums": 1, "bass": 2, "other": 3, "vocals": 4}
        self.assertEqual(pick_vocal_key(sources), "vocals")
        self.assertIsNone(pick_backing_key(sources))
        self.assertIsNone(pick_instrumental_key(sources))

    def test_missing_vocals(self) -> None:
        sources = {"center": 1, "wide": 2}
        self.assertIsNone(pick_vocal_key(sources))
        self.assertIsNone(pick_backing_key(sources))

    def test_karaoke_roles_vs_bv_roles(self) -> None:
        sources = {"Vocals": 1, "Instrumental": 2}
        self.assertEqual(
            vocal_split_source_roles(sources, is_bv_model=False),
            ("Vocals", "Instrumental"),
        )
        self.assertEqual(
            vocal_split_source_roles(sources, is_bv_model=True),
            ("Instrumental", "Vocals"),
        )


class ChainSourceMergeTests(unittest.TestCase):
    def test_route_less_aliases_yield_no_chain_handoff(self) -> None:
        voc = _arr(1.0)
        inst = _arr(2.0)
        handoff = mdx_vocal_split_chain_sources(
            {},
            {"vocal": voc, "other": inst},
        )

        self.assertEqual(handoff, {})

    def test_reviewed_routes_publish_only_exact_native_dependencies(self) -> None:
        voc = _arr(1.0)
        inst = _arr(2.0)
        routes = model_stem_routes(
            _semantic_model(
                "mdx:mel_band_roformer_vocals_becruily",
                ["vocals", "other"],
                backend_primary="vocals",
                vocal_split=False,
            )
        )

        merged = mdx_vocal_split_chain_sources(
            {},
            {"VOCALS": voc, "OTHER": inst},
            routes=routes,
        )

        np.testing.assert_array_equal(merged[VOCAL_STEM], voc.T)
        np.testing.assert_array_equal(merged[INST_STEM], inst.T)

        mismatch = mdx_vocal_split_chain_sources(
            {},
            {"vocal": voc, "other": inst},
            routes=routes,
        )
        self.assertNotIn(VOCAL_STEM, mismatch)
        np.testing.assert_array_equal(mismatch[INST_STEM], inst.T)

    def test_unreviewed_routes_fail_closed_for_canonical_spelling(self) -> None:
        voc = _arr(1.0)
        inst = _arr(2.0)
        routes = model_stem_routes(
            _semantic_model(
                "mdx:unknown_custom_model",
                [VOCAL_STEM, INST_STEM],
                backend_primary=VOCAL_STEM,
                vocal_split=False,
            )
        )

        handoff = mdx_vocal_split_chain_sources(
            {},
            {VOCAL_STEM: voc, INST_STEM: inst},
            routes=routes,
        )

        self.assertEqual(handoff, {})

    def test_empty_routes_fail_closed_for_canonical_spelling(self) -> None:
        handoff = mdx_vocal_split_chain_sources(
            {},
            {VOCAL_STEM: _arr(1.0), INST_STEM: _arr(2.0)},
            routes=(),
        )

        self.assertEqual(handoff, {})

    def test_route_less_four_stem_map_yields_no_chain_handoff(self) -> None:
        handoff = mdx_vocal_split_chain_sources(
            {},
            {
                "drums": _arr(0.0),
                "bass": _arr(0.0),
                "other": _arr(3.0),
                "vocals": _arr(1.0),
            },
        )

        self.assertEqual(handoff, {})

    def test_string_placeholder_is_not_an_array(self) -> None:
        vocal, _inst = vocal_inst_from_sources({VOCAL_STEM: "Vocals"})
        self.assertEqual(vocal, "Vocals")
        self.assertFalse(isinstance(vocal, np.ndarray))


class WriteAudioGuardTests(unittest.TestCase):
    def test_empty_stem_name_returns_without_saving(self) -> None:
        sep = SeperateAttributes.__new__(SeperateAttributes)
        sep.is_vocal_split_model = True
        sep.is_bv_model = False
        sep.write_audio("/tmp/x.wav", _arr(1.0).T, 44100, stem_name="")

    def _secondary_writer(self) -> SeperateAttributes:
        """Skip disk writes; still run ``master_vocal_path`` recording."""
        sep = SeperateAttributes.__new__(SeperateAttributes)
        sep.is_vocal_split_model = False
        sep.is_bv_model = False
        sep.is_bv_model_rebalenced = False
        sep.is_inst_only_voc_splitter = False
        sep.is_save_vocal_only = False
        sep.is_sec_bv_rebalance = False
        sep.is_ensemble_mode = False
        sep.is_secondary_model = True
        sep.master_vocal_path = None
        return sep

    def test_yaml_lowercase_vocals_records_master_vocal_path(self) -> None:
        """Community MDX-C yamls (InstVoc Duality, etc.) write ``vocals``.

        Exact ``== VOCAL_STEM`` left ``master_vocal_path`` unset, so the
        vocal-split chain crashed in ``os.path.basename(None)``.
        """
        sep = self._secondary_writer()
        path = "/tmp/song_(Vocals).wav"
        sep.write_audio(path, _arr(1.0).T, 44100, stem_name="vocals")
        self.assertEqual(sep.master_vocal_path, path)

    def test_canonical_vocals_still_records_master_vocal_path(self) -> None:
        sep = self._secondary_writer()
        path = "/tmp/song_(Vocals).wav"
        sep.write_audio(path, _arr(1.0).T, 44100, stem_name=VOCAL_STEM)
        self.assertEqual(sep.master_vocal_path, path)

    def test_raw_route_preserves_vocal_chain_handoff_without_role_promotion(self) -> None:
        from core.stem_roles import StemId, StemLiteral
        from core.stems import StemRoute, StemRouteKind

        sep = self._secondary_writer()
        route = StemRoute(
            native=StemId("VoCaLs"),
            role=StemLiteral("vocals"),
            label="VoCaLs",
            filename_tag="VoCaLs",
            kind=StemRouteKind.NATIVE,
        )
        path = "/tmp/song_(VoCaLs).wav"

        sep.write_audio(
            path,
            _arr(1.0).T,
            44100,
            stem_name=route.label,
            route=route,
        )

        self.assertIsInstance(route.role, StemLiteral)
        self.assertEqual(sep.master_vocal_path, path)

    def test_vr_bve_capture_uses_distinct_reviewed_tags_for_generated_outputs(self) -> None:
        sep = self._vocal_split_writer()
        sep.is_save_inst_vocal_splitter = True
        sep.master_inst_source = _arr(4.0).T
        routes = model_stem_routes(
            _semantic_model(
                "vr:UVR-BVE-4B_SN-44100-1",
                ["Vocals", "Instrumental"],
                backend_primary="Vocals",
                vocal_split=True,
            )
        )

        for index, route in enumerate(routes, start=1):
            sep.write_audio(
                f"/tmp/source-{index}.wav",
                _arr(float(index)).T,
                44100,
                stem_name=route.label,
                route=route,
            )

        self.assertEqual(
            set(sep._ensemble_stem_buffers),
            {
                "Backing_Vocals",
                "Lead_Vocals",
                "Instrumental_with_Backing_Vocals",
                "Instrumental_with_Lead_Vocals",
            },
        )
        self.assertEqual(
            set(sep._ensemble_stem_paths.values()),
            {
                "/tmp/Backing Vocals.wav",
                "/tmp/Lead Vocals.wav",
                "/tmp/Instrumental with Backing Vocals.wav",
                "/tmp/Instrumental with Lead Vocals.wav",
            },
        )

    def test_vr_bve_rebalance_counts_one_executable_recipe_and_completes_progress(self) -> None:
        from types import MethodType

        from engines.stem_writer import export_source_map

        routes = model_stem_routes(
            _semantic_model(
                "vr:UVR-BVE-4B_SN-44100-1",
                ["Vocals", "Instrumental"],
                backend_primary="Vocals",
                vocal_split=True,
            )
        )
        sep = self._vocal_split_writer()
        sep.selected_stem_routes = routes
        sep.available_stem_routes = routes
        sep.is_bv_model_rebalenced = True
        sep.is_save_inst_vocal_splitter = True
        sep.master_vocal_source = _arr(1.0).T
        sep.master_inst_source = _arr(4.0).T
        sep.stem_export_wav_path = lambda stem, *, route=None: f"/tmp/{stem}.wav"
        progress: list[float] = []
        sep.set_progress_bar = progress.append
        sep.begin_save_phase = MethodType(SeperateAttributes.begin_save_phase, sep)
        sep._report_save_progress = MethodType(SeperateAttributes._report_save_progress, sep)

        export_source_map(
            sep,
            {
                "Vocals": _arr(3.0).T,
                "Instrumental": _arr(2.0).T,
            },
            samplerate=44100,
        )

        self.assertEqual(sep._save_stem_total, 1)
        self.assertEqual(sep._save_stem_index, 1)
        self.assertEqual(len(progress), 1)
        self.assertEqual(
            set(sep._ensemble_stem_buffers),
            {
                "Backing_Vocals",
                "Lead_Vocals",
                "Instrumental_with_Backing_Vocals",
                "Instrumental_with_Lead_Vocals",
            },
        )

    def test_instrumental_does_not_record_master_vocal_path(self) -> None:
        sep = self._secondary_writer()
        sep.write_audio("/tmp/song_(Instrumental).wav", _arr(1.0).T, 44100, stem_name=INST_STEM)
        self.assertIsNone(sep.master_vocal_path)

    def _vocal_split_writer(self) -> Any:
        sep = SeperateAttributes.__new__(SeperateAttributes)
        sep.is_vocal_split_model = True
        sep.is_bv_model = False
        sep.is_karaoke = False
        sep.is_bv_model_rebalenced = False
        sep.is_inst_only_voc_splitter = False
        sep.is_save_vocal_only = False
        sep.is_sec_bv_rebalance = False
        sep.is_ensemble_mode = True
        sep.capture_stems_only = True
        sep.is_secondary_model = False
        sep.is_save_inst_vocal_splitter = False
        sep.is_deverb_vocals = False
        sep.deverb_vocal_opt = "ALL"
        sep.is_normalization = False
        sep.is_prevent_export_clipping = False
        sep.amplification_threshold = 0
        sep.save_format = "WAV"
        sep.wav_type_set = "PCM_16"
        sep.audio_file_base_voc_split = lambda name: f"/tmp/{name}.wav"
        sep.write_to_console = lambda *a, **k: None
        sep._report_save_progress = lambda: None
        sep.master_vocal_path = None
        return sep

    def test_vocal_split_yaml_vocals_writes_lead_not_backing(self) -> None:
        sep = self._vocal_split_writer()
        sep.write_audio("/tmp/x.wav", _arr(1.0).T, 44100, stem_name="vocals")
        paths = getattr(sep, "_ensemble_stem_paths", {})
        self.assertIn("/tmp/Lead Vocals.wav", paths.values())
        self.assertNotIn("/tmp/Backing Vocals.wav", paths.values())

    def test_vocal_split_yaml_vocals_is_deverb_eligible(self) -> None:
        from core.stems import StemBucket, stem_concept

        sep = self._vocal_split_writer()
        sep.mdx_stem_count = 2
        self.assertEqual(stem_concept(sep, "vocals"), StemBucket.LEAD_VOCALS)

    def test_deverb_all_does_not_process_splitter_instrumental(self) -> None:
        sep = self._vocal_split_writer()
        sep.capture_stems_only = False
        sep.is_deverb_vocals = True
        sep.is_save_inst_vocal_splitter = True
        sep.master_inst_source = _arr(2.0).T
        sep.device = "cpu"
        sep.DEVERBER_MODEL = "/tmp/deverb.pth"
        sep.settings = MagicMock()
        sep.mp3_bit_set = "320k"
        sep.flac_bit_set = "PCM_16"
        sep.deverb_progress_callback = MagicMock(return_value=None)
        sep.check_run_control = MagicMock()
        with (
            patch(
                "engines.stem_writer.vr_denoiser", return_value=(_arr(0.5).T, _arr(0.5).T)
            ) as deverb,
            patch("engines.stem_writer.sf.write"),
        ):
            sep.write_audio("/tmp/x.wav", _arr(1.0).T, 44100, stem_name="vocals")
        deverb.assert_called_once()


class VocalSplitChainHandoffTests(unittest.TestCase):
    def _sep(self, **kwargs: Any) -> SeperateAttributes:
        sep = SeperateAttributes.__new__(SeperateAttributes)
        sep.vocal_split_model = MagicMock()
        sep.process_data = MagicMock()
        sep.is_ensemble_mode = False
        sep.is_karaoke = False
        sep.is_bv_model = False
        sep.master_vocal_path = "/tmp/song_(Vocals).wav"
        for key, value in kwargs.items():
            setattr(sep, key, value)
        return sep

    def test_reviewed_exact_sources_invoke_chain(self) -> None:
        sep = self._sep()
        routes = model_stem_routes(
            _semantic_model(
                "mdx:mel_band_roformer_vocals_becruily",
                ["vocals", "other"],
                backend_primary="vocals",
                vocal_split=False,
            )
        )
        handoff = mdx_vocal_split_chain_sources(
            {},
            {"VOCALS": _arr(1.0), "OTHER": _arr(2.0)},
            routes=routes,
        )

        with patch("engines.base.process_chain_model") as chain:
            sep._process_vocal_split_chain(handoff)

        chain.assert_called_once()
        kwargs = chain.call_args.kwargs
        self.assertIsInstance(kwargs["master_vocal_source"], np.ndarray)
        self.assertIsInstance(kwargs["master_inst_source"], np.ndarray)

    def test_noncanonical_alias_maps_do_not_invoke_chain(self) -> None:
        sep = self._sep()
        aliases = (
            {"vocals": _arr(1.0).T, "other": _arr(2.0).T},
            {"vocal": _arr(1.0).T, "instrument": _arr(2.0).T},
            {"voc": _arr(1.0).T, "inst": _arr(2.0).T},
        )
        for payload in aliases:
            with self.subTest(payload=tuple(payload)):
                with patch("engines.base.process_chain_model") as chain:
                    sep._process_vocal_split_chain(payload)
                chain.assert_not_called()

    def test_route_less_canonical_raw_sources_do_not_invoke_chain(self) -> None:
        sep = self._sep()
        handoff = mdx_vocal_split_chain_sources(
            {},
            {
                VOCAL_STEM: _arr(1.0),
                INST_STEM: _arr(2.0),
            },
        )

        with patch("engines.base.process_chain_model") as chain:
            sep._process_vocal_split_chain(handoff)

        chain.assert_not_called()

    def test_string_payload_does_not_invoke_chain(self) -> None:
        sep = self._sep()
        with patch("engines.base.process_chain_model") as chain:
            sep._process_vocal_split_chain({VOCAL_STEM: "Vocals"})
        chain.assert_not_called()

    def test_karaoke_primary_skips_chain(self) -> None:
        sep = self._sep(is_karaoke=True)
        with patch("engines.base.process_chain_model") as chain:
            sep._process_vocal_split_chain({VOCAL_STEM: _arr(1.0).T})
        chain.assert_not_called()

    def test_instrumental_only_does_not_trace_vocal_split_phase(self) -> None:
        sep = self._sep(model_basename="bs_leap_xe_inst_unwa", vocal_split_model=None)
        with (
            patch("engines.base.process_chain_model") as chain,
            patch("engines.base.trace_phase") as trace,
        ):
            sep.process_vocal_split_chain({"other": _arr(2.0).T})
        chain.assert_not_called()
        trace.assert_not_called()

    def test_chain_traces_splitter_model_not_primary(self) -> None:
        splitter = MagicMock()
        splitter.model_basename = "UVR-BVE-4B_SN-44100-1"
        splitter.model_display_label = "UVR-BVE-4B_SN-44100-1"
        sep = self._sep(
            model_basename="bs_leap_xe_inst_unwa",
            model_display_label="bs_leap_xe_inst_unwa",
            vocal_split_model=splitter,
        )
        voc = _arr(1.0).T
        with (
            patch("engines.base.process_chain_model") as chain,
            patch("engines.base.trace_phase") as trace,
        ):
            sep.process_vocal_split_chain({VOCAL_STEM: voc})
        chain.assert_called_once()
        trace.assert_called_once_with(
            "separate", "vocal_split_chain", model="UVR-BVE-4B_SN-44100-1"
        )

    def test_missing_vocal_path_still_passes_a_basename(self) -> None:
        sep = self._sep(master_vocal_path=None, audio_file_base="01. Song")
        voc = _arr(1.0).T
        with patch("engines.base.process_chain_model") as chain:
            sep._process_vocal_split_chain({VOCAL_STEM: voc})
        chain.assert_called_once()
        self.assertIsNone(chain.call_args.kwargs["vocal_stem_path"])
        self.assertEqual(chain.call_args.kwargs["vocal_stem_base"], "01. Song")


class ProcessChainModelPathTests(unittest.TestCase):
    def test_none_vocal_path_does_not_raise_basename_typeerror(self) -> None:
        model = MagicMock()
        model.bv_model_rebalance = False
        process_data = MagicMock()
        with (
            patch("engines.separator_factory.build_seperator") as build,
            patch("engines.orchestration._run_seperator", return_value=None),
        ):
            process_chain_model(
                model,
                process_data,
                vocal_stem_path=None,
                master_vocal_source=_arr(1.0).T,
            )
        build.assert_called_once()
        audio, base = build.call_args.kwargs["vocal_stem_path"]
        self.assertIsInstance(audio, np.ndarray)
        self.assertIsInstance(base, str)
        self.assertTrue(base)

    def test_explicit_fallback_base_preserves_dots(self) -> None:
        model = MagicMock()
        model.bv_model_rebalance = False
        process_data = MagicMock()
        with (
            patch("engines.separator_factory.build_seperator") as build,
            patch("engines.orchestration._run_seperator", return_value=None),
        ):
            process_chain_model(
                model,
                process_data,
                vocal_stem_path=None,
                vocal_stem_base="01. Song",
                master_vocal_source=_arr(1.0).T,
            )
        _audio, base = build.call_args.kwargs["vocal_stem_path"]
        self.assertEqual(base, "01. Song")


class _SplitPairFake:
    def __init__(self, *, is_bv: bool = False) -> None:
        self.is_bv_model = is_bv


class MdxcVocalSplitSourceTests(unittest.TestCase):
    def _build(self, sources: dict[str, np.ndarray], *, is_bv: bool = False) -> dict[str, Any]:
        fake = _SplitPairFake(is_bv=is_bv)
        return SeperateMDXC._vocal_split_pair_sources(
            fake,  # type: ignore[arg-type]
            sources,
            _arr(3.0),
        )

    def test_route_less_title_case_pair_preserves_raw_keys(self) -> None:
        self.assertEqual(
            list(self._build({"Vocals": _arr(1.0), "Instrumental": _arr(2.0)})),
            ["Vocals", "Instrumental"],
        )

    def test_explicit_empty_reviewed_routes_do_not_fall_back_to_spelling(self) -> None:
        fake = _SplitPairFake()

        built = SeperateMDXC._vocal_split_pair_sources(
            fake,  # type: ignore[arg-type]
            {"Vocals": _arr(1.0), "Instrumental": _arr(2.0)},
            _arr(3.0),
            routes=(),
        )

        self.assertEqual(built, {})

    def test_route_less_lowercase_pair_preserves_raw_keys(self) -> None:
        self.assertEqual(
            list(self._build({"vocals": _arr(1.0), INST_STEM: _arr(2.0)})),
            ["vocals", INST_STEM],
        )

    def test_native_rate_mix_is_restored_before_splitter_complement(self) -> None:
        from types import SimpleNamespace

        fake = SimpleNamespace(
            mdx_c_configs=SimpleNamespace(
                audio=SimpleNamespace(sample_rate=48000),
                training=SimpleNamespace(target_instrument=None, instruments=["Vocals"]),
            ),
            is_roformer=False,
            primary_model_name="main",
            model_basename="main",
            model_cache_key="main",
            model_display_label="main",
            primary_sources=None,
            audio_file="/tmp/song.wav",
            is_vocal_split_model=True,
            is_secondary_model=False,
            is_pre_proc_model=False,
            primary_stem_native="Vocals",
            is_bv_model=False,
            start_inference_console_write=lambda: None,
            write_to_console=lambda *args, **kwargs: None,
            demix=lambda mix: {"Vocals": np.ones((2, 480), dtype=np.float32)},
        )
        captured: dict[str, Any] = {}

        def build_pair(
            sources: dict[str, Any],
            mix: Any,
            *,
            routes: Any = None,
        ) -> dict[str, Any]:
            captured["source_length"] = sources["Vocals"].shape[1]
            captured["mix_length"] = mix.shape[1]
            captured["routes"] = routes
            return {}

        fake._vocal_split_pair_sources = build_pair
        from engines.stem_writer import ExportPlan

        with (
            patch(
                "engines.mdx_c_engine.prepare_mix", return_value=np.ones((2, 441), dtype=np.float32)
            ),
            patch(
                "engines.mdx_c_engine.librosa.resample",
                side_effect=lambda audio, *, orig_sr, target_sr, axis: np.ones(
                    (2, 480 if target_sr == 48000 else 441), dtype=np.float32
                ),
            ),
        ):
            plan = SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

        self.assertEqual(
            captured,
            {
                "source_length": 441,
                "mix_length": 441,
                "routes": (),
            },
        )
        self.assertIsInstance(plan, ExportPlan)
        self.assertEqual(plan.sources, {})
        self.assertEqual(plan.samplerate, 44100)
        self.assertEqual(plan.split_sources, {})

    def test_reviewed_splitter_plan_preserves_native_source_keys(self) -> None:
        from types import MethodType, SimpleNamespace

        mix = _arr(3.0)
        lead = _arr(1.0)
        backing = _arr(2.0)
        semantic_model = _semantic_model(
            "mdx:bs_karaoke_becruily",
            ["Vocals", "Instrumental"],
            backend_primary="Vocals",
            vocal_split=True,
        )
        routes = model_stem_routes(semantic_model)
        fake = SimpleNamespace(
            mdx_c_configs=SimpleNamespace(
                audio=SimpleNamespace(sample_rate=44100),
                training=SimpleNamespace(
                    target_instrument="Vocals",
                    instruments=["Vocals", "Instrumental"],
                ),
            ),
            is_roformer=True,
            primary_model_name="splitter",
            model_basename="splitter",
            model_cache_key="splitter",
            model_display_label="splitter",
            primary_sources=(mix, {"vocals": lead, "INSTRUMENTAL": backing}),
            load_cached_sources=lambda: None,
            is_vocal_split_model=True,
            is_secondary_model=True,
            is_pre_proc_model=False,
            primary_stem_native="Vocals",
            is_bv_model=False,
            available_stem_routes=routes,
            selected_stem_routes=routes,
            is_ensemble_mode=False,
        )
        fake._vocal_split_pair_sources = MethodType(
            SeperateMDXC._vocal_split_pair_sources,
            fake,
        )

        plan = SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

        self.assertEqual(list(plan.sources), ["Vocals", "Instrumental"])
        np.testing.assert_array_equal(plan.sources["Vocals"], lead.T)
        np.testing.assert_array_equal(plan.sources["Instrumental"], backing.T)

    def test_giantailab_reviewed_plan_discards_non_pair_native_route(self) -> None:
        from types import SimpleNamespace

        routes = model_stem_routes(
            _semantic_model(
                "mdx:bs_karaoke_3stem_giantailab",
                ["vocals", "backing_vocal", "instrumental"],
                backend_primary="vocals",
                vocal_split=True,
            )
        )
        fake = SimpleNamespace(is_bv_model=False, is_vocal_split_model=True)

        built = SeperateMDXC._vocal_split_pair_sources(
            fake,  # type: ignore[arg-type]
            {
                "vocals": _arr(1.0),
                "backing_vocal": _arr(2.0),
                "instrumental": _arr(3.0),
            },
            _arr(6.0),
            routes=routes,
        )

        self.assertEqual(list(built), ["vocals", "instrumental"])

    def test_route_less_three_stem_map_preserves_every_raw_key(self) -> None:
        self.assertEqual(
            list(
                self._build(
                    {
                        "vocals": _arr(1.0),
                        "backing_vocal": _arr(2.0),
                        "instrumental": _arr(9.0),
                    }
                )
            ),
            ["vocals", "backing_vocal", "instrumental"],
        )

    def test_pair_sources_are_channel_last_for_export(self) -> None:
        built = self._build({"Vocals": _arr(1.0), "Instrumental": _arr(2.0)})
        self.assertEqual(built["Vocals"].shape, (4, 2))
        self.assertEqual(built["Instrumental"].shape, (4, 2))


if __name__ == "__main__":
    unittest.main()
