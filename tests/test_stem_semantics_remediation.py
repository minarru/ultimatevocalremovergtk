"""Audio-level regressions for reviewed stem recipe execution."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from core.model_config.config import ModelConfig
from core.model_stem_manifest import load_bundled_stem_semantics
from core.settings import Settings
from core.stem_roles import StemReviewStatus
from core.stems import FOCUS_PRIMARY, FOCUS_SECONDARY
from engines.mdx import SeperateMDX

DECISION_FIXTURE = Path(__file__).with_name("fixtures") / "stem_manifest_decisions.json"
TASK5_PROMOTION_IDS = frozenset(
    {
        "mdx:Kim_Inst",
        "mdx:Kim_Vocal_1",
        "mdx:Kim_Vocal_2",
        "mdx:MDX23C-8KFFT-InstVoc_HQ",
        "mdx:MDX23C-8KFFT-InstVoc_HQ_2",
        "mdx:Reverb_HQ_By_FoxJoy",
        "mdx:UVR-MDX-NET_Crowd_HQ_1",
        "mdx:UVR_MDXNET_1_9703",
        "mdx:UVR_MDXNET_2_9682",
        "mdx:UVR_MDXNET_3_9662",
        "mdx:UVR_MDXNET_9482",
        "mdx:UVR_MDXNET_KARA",
        "mdx:kuielab_a_bass",
        "mdx:kuielab_a_drums",
        "mdx:kuielab_a_other",
        "mdx:kuielab_a_vocals",
        "mdx:kuielab_b_bass",
        "mdx:kuielab_b_drums",
        "mdx:kuielab_b_other",
        "mdx:kuielab_b_vocals",
        "mdx:melband_roformer_inst_v1",
        "mdx:melband_roformer_inst_v2",
        "mdx:melband_roformer_instvoc_duality_v1",
        "mdx:melband_roformer_instvox_duality_v2",
        "mdx:model_bs_roformer_ep_317_sdr_12.9755",
        "mdx:model_bs_roformer_ep_368_sdr_12.9628",
        "mdx:model_bs_roformer_ep_937_sdr_10.5309",
        "mdx:model_mel_band_roformer_ep_3005_sdr_11.4360",
    }
)
EXPECTED_FINAL_KARAOKE_IDS = (
    "mdx:UVR_MDXNET_KARA",
    "mdx:UVR_MDXNET_KARA_2",
    "mdx:bs_karaoke_3stem_giantailab",
    "mdx:bs_karaoke_anvuew",
    "mdx:bs_karaoke_becruily",
    "mdx:bs_karaoke_gabox",
    "mdx:bs_karaoke_inv_gabox",
    "mdx:bs_pope_karaoke_974_lambda",
    "mdx:mbr_bve_gonzaluigi",
    "mdx:mbr_karaoke1_gabox",
    "mdx:mbr_karaoke25022025_gabox",
    "mdx:mbr_karaoke28022025_gabox",
    "mdx:mbr_karaoke2_gabox",
    "mdx:mbr_karaoke_fusion2_aggr_gonzaluigi",
    "mdx:mbr_karaoke_fusion_aggr_gonzaluigi",
    "mdx:mbr_karaoke_fusion_gonzaluigi",
    "mdx:mbr_karaoke_fusion_total_aggr_gonzaluigi",
    "mdx:mbr_karaoke_small_gabox_aufr33",
    "mdx:mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956",
    "mdx:mel_band_roformer_karaoke_gabox",
    "mdx:melband_roformer_karaoke_becruily",
    "mdx:model_BandSplit-Roformer_Karaoke_Frazer_by-becruily",
    "mdx:model_MelBand-Roformer_BVE_by-Gonza",
    "mdx:model_MelBand-Roformer_Karaoke_Fusion_Aggressive_by-Gonza",
    "mdx:model_MelBand-Roformer_Karaoke_Fusion_Aggressive_v2_by-Gonza",
    "mdx:model_MelBand-Roformer_Karaoke_Fusion_Standard_by-Gonza",
    "mdx:model_MelBand-Roformer_Karaoke_Fusion_Total_by-Gonza",
    "mdx:model_MelBand-Roformer_Karaoke_by-Gabox",
    "vr:5_HP-Karaoke-UVR",
    "vr:6_HP-Karaoke-UVR",
)


def _normalized_manifest_model(model: dict[str, object]) -> dict[str, object]:
    raw_contexts = model["contexts"]
    assert isinstance(raw_contexts, dict)
    contexts: dict[str, object] = {}
    for context_id in sorted(raw_contexts):
        raw_context = raw_contexts[context_id]
        assert isinstance(raw_context, dict)
        context: dict[str, object] = {"logical_primary": raw_context["logical_primary"]}
        if "logical_secondary" in raw_context:
            context["logical_secondary"] = raw_context["logical_secondary"]
        raw_outputs = raw_context["outputs"]
        assert isinstance(raw_outputs, list)
        outputs: list[dict[str, object]] = []
        for raw_output in raw_outputs:
            assert isinstance(raw_output, dict)
            native = raw_output["native"]
            output: dict[str, object] = {
                "native": native,
                "role": raw_output["role"],
                "production": raw_output.get(
                    "production", "native" if native is not None else "derived"
                ),
            }
            if "complement_of" in raw_output:
                output["complement_of"] = raw_output["complement_of"]
            if "derived_from" in raw_output:
                output["derived_from"] = raw_output["derived_from"]
            output["selected_by_default"] = raw_output.get("selected_by_default", True)
            outputs.append(output)
        context["outputs"] = outputs
        contexts[context_id] = context
    return {"intent": model["intent"], "contexts": contexts}


class ReviewedDecisionLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(DECISION_FIXTURE.read_text(encoding="utf-8"))
        cls.manifest = json.loads(
            Path("bundled/model_stem_manifest.json").read_text(encoding="utf-8")
        )

    def test_fixture_is_the_complete_sorted_final_decision_oracle(self) -> None:
        fixture = self.fixture
        models = fixture["models"]
        self.assertEqual(fixture["schema_version"], 1)
        self.assertEqual(fixture["catalogue_model_count"], 485)
        self.assertEqual(fixture["declared_model_count"], 483)
        self.assertEqual(fixture["declared_context_count"], 514)
        self.assertEqual(len(models), 483)
        self.assertEqual(sum(len(model["contexts"]) for model in models.values()), 514)
        self.assertEqual(list(models), sorted(models))
        intent_counts: dict[str, int] = {}
        for model_id, model in models.items():
            with self.subTest(model_id=model_id):
                intent = model["intent"]
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
                self.assertEqual(list(model["contexts"]), sorted(model["contexts"]))
                for context in model["contexts"].values():
                    roles = [output["role"] for output in context["outputs"]]
                    self.assertEqual(roles.count(context["logical_primary"]), 1)
                    secondary = context.get("logical_secondary")
                    if secondary is not None:
                        self.assertNotEqual(secondary, context["logical_primary"])
                        self.assertEqual(roles.count(secondary), 1)
        self.assertEqual(
            intent_counts,
            {
                "drum_bass_sep": 1,
                "dual_voc_inst": 16,
                "instrumental": 107,
                "karaoke": 30,
                "multi_stem": 72,
                "special_fx": 29,
                "specialty_stem": 110,
                "vocals": 118,
            },
        )

        expected_waivers = [
            "apollo:apollo_edm_big_by_essid",
            "apollo:apollo_edm_by_essid",
        ]
        self.assertEqual(fixture["waivers"], expected_waivers)
        karaoke_ids = fixture["karaoke_model_ids"]
        self.assertEqual(len(karaoke_ids), 30)
        self.assertEqual(karaoke_ids, sorted(karaoke_ids))
        self.assertEqual(karaoke_ids, list(EXPECTED_FINAL_KARAOKE_IDS))
        self.assertEqual(
            set(karaoke_ids),
            {model_id for model_id, model in models.items() if model["intent"] == "karaoke"},
        )
        self.assertIn("mdx:mbr_bve_gonzaluigi", karaoke_ids)
        self.assertIn("mdx:model_MelBand-Roformer_BVE_by-Gonza", karaoke_ids)
        self.assertNotIn("vr:UVR-BVE-4B_SN-44100-1", karaoke_ids)

    def test_task5_manifest_matches_every_shared_ordered_decision(self) -> None:
        expected_models = self.fixture["models"]
        actual_models = self.manifest["models"]
        self.assertEqual(len(actual_models), 483)
        self.assertEqual(
            self.manifest["waivers"],
            {model_id: self.manifest["waivers"][model_id] for model_id in self.fixture["waivers"]},
        )
        self.assertEqual(
            sum(len(model["contexts"]) for model in actual_models.values()),
            514,
        )
        self.assertEqual(set(actual_models), set(expected_models))
        for model_id in sorted(actual_models):
            with self.subTest(model_id=model_id):
                self.assertEqual(
                    _normalized_manifest_model(actual_models[model_id]),
                    expected_models[model_id],
                )

        actual_karaoke_ids = {
            model_id for model_id, model in actual_models.items() if model["intent"] == "karaoke"
        }
        self.assertEqual(actual_karaoke_ids, set(self.fixture["karaoke_model_ids"]))

    def test_reviewed_roles_are_exact_and_used_by_the_final_oracle(self) -> None:
        expected_roles = {
            "vocal.bass": ("Bass Vocals", "Bass_Vocals", None),
            "instrument.hi_hat": ("Hi-Hat", "Hi_Hat", None),
            "instrument.hi_hat.removed": (
                "Hi-Hat Removed",
                "Hi_Hat_Removed",
                "instrument.hi_hat",
            ),
            "instrument.orchestra": ("Orchestra", "Orchestra", None),
            "instrument.orchestra.removed": (
                "Orchestra Removed",
                "Orchestra_Removed",
                "instrument.orchestra",
            ),
            "instrument.woodwinds": ("Woodwinds", "Woodwinds", None),
            "instrument.woodwinds.removed": (
                "Woodwinds Removed",
                "Woodwinds_Removed",
                "instrument.woodwinds",
            ),
            "instrument.guitar.lead": ("Lead Guitar", "Lead_Guitar", None),
            "instrument.guitar.rhythm": ("Rhythm Guitar", "Rhythm_Guitar", None),
            "instrument.drum_bass": ("Drum/Bass", "Drum_Bass", None),
            "instrument.drum_bass.removed": (
                "Drum/Bass Removed",
                "Drum_Bass_Removed",
                "instrument.drum_bass",
            ),
            "effect.reverb_echo": ("Reverb/Echo", "Reverb_Echo", None),
            "effect.reverb_echo.removed": (
                "Reverb/Echo Removed",
                "Reverb_Echo_Removed",
                "effect.reverb_echo",
            ),
            "cinematic.sfx": ("SFX", "SFX", None),
            "residual.other.removed": (
                "Residual Removed",
                "Residual_Removed",
                "residual.other",
            ),
        }
        roles = self.manifest["roles"]
        for role_id, (display, filename_tag, removed_of) in expected_roles.items():
            with self.subTest(role_id=role_id):
                definition = roles.get(role_id)
                self.assertIsNotNone(definition)
                assert definition is not None
                self.assertEqual(definition["display"], display)
                self.assertEqual(definition["filename_tag"], filename_tag)
                self.assertEqual(definition.get("removed_of"), removed_of)

        obsolete = {
            "instrument.hh",
            "instrument.hh.removed",
            "instrument.orch",
            "instrument.orch.removed",
            "instrument.woodwind",
            "instrument.woodwind.removed",
            "instrument.rhythm",
            "residual.back",
            "residual.backing_vocal",
            "residual.lead",
            "residual.others",
        }
        self.assertFalse(obsolete.intersection(roles))
        used_roles = {
            output["role"]
            for model in self.fixture["models"].values()
            for context in model["contexts"].values()
            for output in context["outputs"]
        }
        self.assertEqual(set(roles) - used_roles, set())

    def test_giantailab_is_the_only_default_false_logical_primary(self) -> None:
        default_false_primaries: list[tuple[str, str, str]] = []
        for model_id, model in self.fixture["models"].items():
            for context_id, context in model["contexts"].items():
                for output in context["outputs"]:
                    if (
                        output["role"] == context["logical_primary"]
                        and not output["selected_by_default"]
                    ):
                        default_false_primaries.append((model_id, context_id, output["role"]))
        self.assertEqual(
            default_false_primaries,
            [
                (
                    "mdx:bs_karaoke_3stem_giantailab",
                    "full_mix",
                    "mix.instrumental_with_backing_vocals",
                )
            ],
        )


def _classic_fake(
    *,
    canonical_id: str,
    signature: tuple[str, str],
    backend_primary: str,
    focus: str,
) -> SimpleNamespace:
    mix = np.array(
        [[20.0, 21.0, 22.0, 23.0], [30.0, 31.0, 32.0, 33.0]],
        dtype=np.float32,
    )
    source = np.array(
        [[2.0, 3.0, 4.0, 5.0], [7.0, 8.0, 9.0, 10.0]],
        dtype=np.float32,
    )
    secondary = next(native for native in signature if native != backend_primary)
    settings = Settings.defaults()
    settings.process.stem_focus = focus
    return SimpleNamespace(
        settings=settings,
        canonical_id=canonical_id,
        stem_semantics=None,
        mdx_model_stems=list(signature),
        mdxnet_stems_selected=[],
        demucs_source_list=[],
        mdx_stem_count=2,
        demucs_stem_count=0,
        target_instrument="",
        primary_stem_native=backend_primary,
        primary_model_name="classic-fixture",
        model_cache_key="classic-fixture",
        primary_sources=(mix, source),
        load_cached_sources=lambda: None,
        primary_stem=backend_primary,
        secondary_stem=secondary,
        secondary_source=None,
        primary_source=None,
        secondary_source_primary=None,
        secondary_source_secondary=None,
        is_match_frequency_pitch=False,
        is_secondary_model_activated=False,
        secondary_model=None,
        is_invert_spec=False,
        process_secondary_stem=lambda stem, secondary=None: stem,
        is_vocal_split_model=False,
        is_secondary_model=False,
        is_pre_proc_model=False,
        is_inst_only_voc_splitter=False,
        is_sec_bv_rebalance=False,
        is_ensemble_mode=False,
        is_karaoke=False,
        is_bv_model=False,
        primary_mix=mix,
        primary_demix=source,
    )


class ClassicMdxReviewedRoutingTests(unittest.TestCase):
    CASES = (
        (
            "default",
            "mdx:UVR_MDXNET_Main",
            ("Instrumental", "Vocals"),
            "Vocals",
            "",
            ("Vocals", "Instrumental"),
        ),
        (
            "primary-only",
            "mdx:UVR_MDXNET_Main",
            ("Instrumental", "Vocals"),
            "Vocals",
            FOCUS_PRIMARY,
            ("Vocals",),
        ),
        (
            "inverse-only",
            "mdx:UVR_MDXNET_Main",
            ("Instrumental", "Vocals"),
            "Vocals",
            FOCUS_SECONDARY,
            ("Instrumental",),
        ),
        (
            "karaoke",
            "mdx:UVR_MDXNET_KARA_2",
            ("Instrumental", "Vocals"),
            "Instrumental",
            "",
            ("Vocals", "Instrumental"),
        ),
        (
            "reverb",
            "mdx:Reverb_HQ_By_FoxJoy",
            ("Reverb", "No Reverb"),
            "Reverb",
            "",
            ("No Reverb", "Reverb"),
        ),
        (
            "crowd",
            "mdx:UVR-MDX-NET_Crowd_HQ_1",
            ("No Crowd", "Crowd"),
            "No Crowd",
            "",
            ("No Crowd", "Crowd"),
        ),
        (
            "kuielab-a-bass",
            "mdx:kuielab_a_bass",
            ("Bass", "No Bass"),
            "Bass",
            "",
            ("Bass", "No Bass"),
        ),
        (
            "kuielab-b-bass",
            "mdx:kuielab_b_bass",
            ("Bass", "No Bass"),
            "Bass",
            "",
            ("Bass", "No Bass"),
        ),
        (
            "kuielab-a-drums",
            "mdx:kuielab_a_drums",
            ("Drums", "No Drums"),
            "Drums",
            "",
            ("Drums", "No Drums"),
        ),
        (
            "kuielab-b-drums",
            "mdx:kuielab_b_drums",
            ("Drums", "No Drums"),
            "Drums",
            "",
            ("Drums", "No Drums"),
        ),
        (
            "kuielab-a-other",
            "mdx:kuielab_a_other",
            ("Other", "No Other"),
            "Other",
            "",
            ("Other", "No Other"),
        ),
        (
            "kuielab-b-other",
            "mdx:kuielab_b_other",
            ("Other", "No Other"),
            "Other",
            "",
            ("Other", "No Other"),
        ),
        (
            "kuielab-a-vocals",
            "mdx:kuielab_a_vocals",
            ("Vocals", "Instrumental"),
            "Vocals",
            "",
            ("Vocals", "Instrumental"),
        ),
        (
            "kuielab-b-vocals",
            "mdx:kuielab_b_vocals",
            ("Vocals", "Instrumental"),
            "Vocals",
            "",
            ("Vocals", "Instrumental"),
        ),
    )

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_bundled_stem_semantics()

    def test_classic_focus_resolves_reviewed_routes_to_exact_engine_keys(self) -> None:
        for name, model_id, signature, backend_primary, focus, selected_natives in self.CASES:
            with self.subTest(case=name):
                fake = _classic_fake(
                    canonical_id=model_id,
                    signature=signature,
                    backend_primary=backend_primary,
                    focus=focus,
                )

                with (
                    mock.patch(
                        "core.stems.load_bundled_stem_semantics",
                        return_value=self.registry,
                    ),
                ):
                    ModelConfig._apply_stem_focus(fake)  # type: ignore[arg-type]

                self.assertEqual(fake.stem_semantics.status, StemReviewStatus.REVIEWED)
                selected = tuple(fake.selected_stem_routes)
                self.assertEqual(
                    {route.native.raw for route in selected if route.native is not None},
                    set(selected_natives),
                )
                if name in {"default", "primary-only", "inverse-only"}:
                    self.assertEqual(fake.stem_semantics.model_id, "mdx:UVR_MDXNET_Main")
                    self.assertEqual(
                        fake.stem_semantics.evidence,
                        "catalogue_id=mdx:UVR_MDXNET_Main; source=TRvlvr+Politrees; "
                        "metadata_source=community_models.txt; "
                        "native_signature=instrumental|vocals; backend_primary=Vocals; "
                        "backend_target=vocals; reviewed_contexts=full_mix",
                    )
                    self.assertEqual(fake.primary_stem, "Vocals")
                    self.assertEqual(
                        {
                            output.native.raw: output.backend_primary
                            for output in fake.stem_semantics.outputs
                            if output.native is not None
                        },
                        {"Instrumental": False, "Vocals": True},
                    )

                plan = SeperateMDX.seperate(fake)  # type: ignore[arg-type]

                engine_secondary = next(native for native in signature if native != backend_primary)
                expected_keys = tuple(
                    native
                    for native in (engine_secondary, backend_primary)
                    if native in selected_natives
                )
                self.assertEqual(tuple(plan.sources), expected_keys)
                semantic_only_keys = {
                    route.concept
                    for route in selected
                    if route.native is not None and route.concept != route.native.raw
                }
                self.assertFalse(semantic_only_keys.intersection(plan.sources))
                presentation_only_keys = {
                    value
                    for route in selected
                    if route.native is not None
                    for value in (route.label, route.filename_tag)
                    if value != route.native.raw
                }
                self.assertFalse(presentation_only_keys.intersection(plan.sources))
                if engine_secondary in selected_natives:
                    np.testing.assert_array_equal(
                        plan.sources[engine_secondary],
                        (fake.primary_mix - fake.primary_demix).T,
                    )
                if backend_primary in selected_natives:
                    np.testing.assert_array_equal(
                        plan.sources[backend_primary],
                        fake.primary_demix.T,
                    )


if __name__ == "__main__":
    unittest.main()
