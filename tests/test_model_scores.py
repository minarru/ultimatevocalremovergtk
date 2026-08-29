"""Tests for SDR parsing and purpose/sort helpers."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import unittest.mock

from bundled.constants import (
    APOLLO_ARCH_TYPE,
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)
from core import model_scores
from core.model_scores import (
    ARCH_FILTER_ALL,
    NETWORK_BANDIT,
    NETWORK_BS_ROFORMER,
    NETWORK_CLASSIC_MDX,
    NETWORK_FILTER_OPTIONS,
    NETWORK_MDX23C,
    NETWORK_MEL_BAND,
    NETWORK_SCNET,
    PURPOSE_FX,
    PURPOSE_INSTRUMENTAL,
    PURPOSE_KARAOKE,
    PURPOSE_REMOVAL,
    PURPOSE_RESTORE,
    PURPOSE_SPECIALTY,
    PURPOSE_STEMS,
    PURPOSE_VOCALS,
    catalogue_network_id,
    download_center_hint_for_method,
    family_arch_for_network_filter,
    filter_labels_by_purpose,
    format_sdr_subtitle,
    network_filter_hides_headers,
    network_filter_matches,
    parse_sdr_score,
    purpose_for_label,
    purpose_pages_for_label,
    sort_labels_by_sdr,
)
from core.model_stem_semantics import (
    INTENT_DUAL_VOC_INST,
    INTENT_MULTI_STEM,
    INTENT_SPECIAL_FX,
    INTENT_SPECIALTY_STEM,
)
from ui.download_center import catalogue_matches


class ParseSdrScoreTests(unittest.TestCase):
    def test_float_sdr_in_filename(self) -> None:
        self.assertAlmostEqual(
            float(parse_sdr_score("model_bs_roformer_ep_317_sdr_12.9755.ckpt") or 0.0),
            12.9755,
            places=4,
        )

    def test_int_coded_sdr_in_label(self) -> None:
        self.assertAlmostEqual(
            float(parse_sdr_score("MelBand Roformer | SDR 1143 by Viperx") or 0.0),
            11.43,
        )

    def test_viperx_abbreviation(self) -> None:
        self.assertAlmostEqual(float(parse_sdr_score("BS-Roformer-Viperx-1297") or 0.0), 12.97)

    def test_missing_score_returns_none(self) -> None:
        self.assertIsNone(parse_sdr_score("UVR-MDX-NET-Inst_HQ_5.onnx"))

    def test_best_of_multiple_texts(self) -> None:
        self.assertAlmostEqual(
            float(
                parse_sdr_score("friendly name", "model_sdr_10.2.ckpt", "other_sdr_11.5.ckpt")
                or 0.0
            ),
            11.5,
        )


class PurposeAndSortTests(unittest.TestCase):
    def test_purpose_buckets(self) -> None:
        self.assertEqual(purpose_for_label("Roformer Model: Karaoke by Gabox"), PURPOSE_KARAOKE)
        self.assertEqual(
            purpose_for_label("MelBand Roformer | Instrumental by becruily"),
            PURPOSE_INSTRUMENTAL,
        )
        self.assertEqual(
            purpose_for_label("BandSplit Roformer | Resurrection Vocals by Unwa"),
            PURPOSE_VOCALS,
        )
        self.assertEqual(purpose_for_label("SCnet: 4-stem model"), PURPOSE_SPECIALTY)
        self.assertEqual(purpose_for_label("De-Echo Normal"), PURPOSE_REMOVAL)

    def test_filter_labels_by_purpose(self) -> None:
        labels = [
            "Roformer Model: Karaoke by Gabox",
            "MelBand Roformer | Instrumental by becruily",
            "BandSplit Roformer | Resurrection Vocals by Unwa",
        ]
        karaoke = filter_labels_by_purpose(labels, PURPOSE_KARAOKE)
        self.assertEqual(karaoke, ["Roformer Model: Karaoke by Gabox"])

    def test_curated_intent_overrides_name_guess(self) -> None:
        label = "Mel-Band Roformer General by Someone"
        self.assertEqual(
            model_scores.purpose_for_label(label, intent="vocals"),
            PURPOSE_VOCALS,
        )
        self.assertEqual(
            filter_labels_by_purpose([label], PURPOSE_VOCALS, intents={label: "vocals"}),
            [label],
        )

    def test_sort_labels_by_sdr(self) -> None:
        labels = ["alpha", "BS-Roformer-Viperx-1297", "BS-Roformer-Viperx-1143"]
        ordered = sort_labels_by_sdr(labels)
        self.assertEqual(ordered[0], "BS-Roformer-Viperx-1297")
        self.assertEqual(ordered[1], "BS-Roformer-Viperx-1143")
        self.assertEqual(ordered[2], "alpha")

    def test_format_sdr_subtitle(self) -> None:
        self.assertEqual(format_sdr_subtitle(12.97, "180 MB"), "13.0 SDR · 180 MB")
        self.assertEqual(format_sdr_subtitle(None, "180 MB"), "180 MB")
        self.assertEqual(format_sdr_subtitle(11.43), "11.4 SDR")

    def test_catalogue_matches_purpose(self) -> None:
        names = [
            "Roformer Model: Karaoke by Gabox",
            "MelBand Roformer | Instrumental by becruily",
        ]
        matches = catalogue_matches(names, "", purpose=PURPOSE_KARAOKE)
        self.assertEqual(matches, ["Roformer Model: Karaoke by Gabox"])

    def test_catalogue_matches_uses_curated_intent(self) -> None:
        label = "Mel-Band Roformer General by Someone"
        matches = catalogue_matches([label], "", purpose=PURPOSE_VOCALS, intents={label: "vocals"})
        self.assertEqual(matches, [label])

    def test_dual_intent_lists_on_vocals_and_instrumental_pages(self) -> None:
        label = "MelBand Roformer | InstVoc HQ"
        pages = purpose_pages_for_label(label, intent=INTENT_DUAL_VOC_INST)
        self.assertEqual(pages, frozenset({PURPOSE_VOCALS, PURPOSE_INSTRUMENTAL}))
        self.assertEqual(
            filter_labels_by_purpose(
                [label], PURPOSE_VOCALS, intents={label: INTENT_DUAL_VOC_INST}
            ),
            [label],
        )
        self.assertEqual(
            filter_labels_by_purpose(
                [label], PURPOSE_INSTRUMENTAL, intents={label: INTENT_DUAL_VOC_INST}
            ),
            [label],
        )

    def test_musical_stems_stay_on_the_stems_page(self) -> None:
        self.assertEqual(
            purpose_pages_for_label("SCnet: 4-stem model"),
            frozenset({PURPOSE_STEMS}),
        )
        self.assertEqual(
            purpose_pages_for_label(
                "Demucs v4 Hybrid",
                intent=INTENT_MULTI_STEM,
                primary_role="vocal.vocals",
                output_roles=(
                    "vocal.vocals",
                    "instrument.drums",
                    "instrument.bass",
                    "residual.other",
                ),
            ),
            frozenset({PURPOSE_STEMS}),
        )
        self.assertEqual(
            purpose_pages_for_label(
                "BandSplit Roformer | Male-Female by aufr33",
                intent=INTENT_SPECIALTY_STEM,
                primary_role="vocal.male",
                output_roles=("vocal.male", "vocal.female"),
            ),
            frozenset({PURPOSE_STEMS}),
        )
        self.assertEqual(
            purpose_pages_for_label(
                "MDX23C Phantom Centre",
                intent=INTENT_SPECIALTY_STEM,
                primary_role="spatial.center",
            ),
            frozenset({PURPOSE_STEMS}),
        )

    def test_cleanup_and_aspiration_land_on_removal_not_restore(self) -> None:
        self.assertEqual(
            purpose_pages_for_label("De-Echo Normal", intent=INTENT_SPECIAL_FX),
            frozenset({PURPOSE_REMOVAL}),
        )
        self.assertEqual(
            purpose_pages_for_label(
                "MelBand Roformer | Aspiration by Sucial",
                intent=INTENT_SPECIALTY_STEM,
                primary_role="vocal.aspiration",
                output_roles=("vocal.aspiration", "vocal.aspiration.removed"),
            ),
            frozenset({PURPOSE_REMOVAL}),
        )
        self.assertEqual(
            purpose_pages_for_label(
                "Mel-Band Roformer Musicless by Jasper",
                intent=INTENT_SPECIALTY_STEM,
                primary_role="mix.music.removed",
            ),
            frozenset({PURPOSE_REMOVAL}),
        )
        self.assertEqual(
            purpose_pages_for_label(
                "MelBand Roformer — DeNoiser Children 16 kHz",
                intent=INTENT_SPECIAL_FX,
                primary_role="cinematic.speech",
            ),
            frozenset({PURPOSE_REMOVAL}),
        )
        self.assertEqual(
            purpose_pages_for_label("Apollo Universal", arch=APOLLO_ARCH_TYPE),
            frozenset({PURPOSE_RESTORE}),
        )

    def test_cinematic_models_land_on_fx(self) -> None:
        self.assertEqual(
            purpose_pages_for_label(
                "MelBand Roformer | Crowd by Aufr33 & Viperx",
                intent=INTENT_SPECIALTY_STEM,
                primary_role="cinematic.crowd",
            ),
            frozenset({PURPOSE_FX}),
        )
        self.assertEqual(
            purpose_pages_for_label(
                "MDX-Net — UVR Crowd HQ 1",
                intent=INTENT_SPECIALTY_STEM,
                primary_role="cinematic.crowd.removed",
            ),
            frozenset({PURPOSE_FX}),
        )
        self.assertEqual(
            purpose_pages_for_label(
                "Mel-Band Roformer Explosions by jazzpear",
                intent=INTENT_SPECIALTY_STEM,
                primary_role="cinematic.explosions",
            ),
            frozenset({PURPOSE_FX}),
        )
        self.assertEqual(
            purpose_pages_for_label(
                "MDX23C SFX by Jasper",
                intent=INTENT_SPECIALTY_STEM,
                primary_role="cinematic.foreground_sfx",
            ),
            frozenset({PURPOSE_FX}),
        )
        self.assertEqual(
            purpose_pages_for_label(
                "Bandit Plus by ZFTurbo",
                intent=INTENT_MULTI_STEM,
                primary_role="cinematic.speech",
                output_roles=("cinematic.speech", "mix.music", "cinematic.sfx"),
            ),
            frozenset({PURPOSE_FX}),
        )
        self.assertEqual(
            filter_labels_by_purpose(
                ["De-Echo Normal"],
                PURPOSE_RESTORE,
                intents={"De-Echo Normal": INTENT_SPECIAL_FX},
            ),
            [],
        )

    def test_vocal_only_stays_off_the_instrumental_page(self) -> None:
        label = "BandSplit Roformer | Resurrection Vocals by Unwa"
        self.assertEqual(
            purpose_pages_for_label(label),
            frozenset({PURPOSE_VOCALS}),
        )
        self.assertEqual(
            filter_labels_by_purpose([label], PURPOSE_INSTRUMENTAL),
            [],
        )
        self.assertEqual(
            catalogue_matches([label], "", purpose=PURPOSE_INSTRUMENTAL),
            [],
        )


_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "model_scores_sample.json")


def _sample() -> dict:
    with open(_FIXTURE, "r", encoding="utf-8") as handle:
        return json.load(handle)


class _IsolatedScoreCache(unittest.TestCase):
    """Redirect the disk cache into a temp dir.

    ``load_model_scores`` writes whatever it fetched to the cache, so without
    this a test that patches the fetch poisons the user's real
    ``~/.cache/uvr/model_scores.json`` with the three-entry fixture — and every
    later run reads the fixture instead of the 115-entry snapshot.
    """

    def setUp(self) -> None:
        model_scores.clear_model_scores_cache()
        self.addCleanup(model_scores.clear_model_scores_cache)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        cache_path = os.path.join(self._tmp.name, "model_scores.json")
        patcher = unittest.mock.patch.object(model_scores, "_cache_path", return_value=cache_path)
        patcher.start()
        self.addCleanup(patcher.stop)


class ModelScoreAggregationTests(_IsolatedScoreCache):
    def _loaded(self) -> dict:
        with unittest.mock.patch.object(
            model_scores, "_fetch_model_scores", return_value=_sample()
        ):
            return model_scores.load_model_scores(force=True)

    def test_mean_sdr_per_stem(self) -> None:
        scores = self._loaded()
        entry = scores["model_bs_roformer_ep_317_sdr_12.9755.ckpt"]
        self.assertAlmostEqual(entry["vocals"], 11.5)
        self.assertAlmostEqual(entry["instrumental"], 16.25)

    def test_speed_metric_is_not_a_stem(self) -> None:
        scores = self._loaded()
        entry = scores["model_bs_roformer_ep_317_sdr_12.9755.ckpt"]
        self.assertNotIn("seconds_per_minute_m3", entry)

    def test_zero_track_model_is_unscored_not_an_error(self) -> None:
        scores = self._loaded()
        self.assertEqual(scores.get("uvr-denoise-lite.pth", {}), {})

    def test_lookup_matches_demucs_yaml_key(self) -> None:
        scores = self._loaded()
        found = model_scores.sdr_for_files(
            ["955717e8-8726e21a.th", "htdemucs_ft.yaml"], scores=scores
        )
        self.assertAlmostEqual(found["drums"], 10.0)

    def test_lookup_is_case_insensitive(self) -> None:
        scores = self._loaded()
        found = model_scores.sdr_for_files(["HTDEMUCS_FT.YAML"], scores=scores)
        self.assertAlmostEqual(found["bass"], 12.0)

    def test_lookup_miss_returns_empty(self) -> None:
        scores = self._loaded()
        self.assertEqual(model_scores.sdr_for_files(["nope.ckpt"], scores=scores), {})


class PrimarySdrTests(unittest.TestCase):
    def test_target_stem_wins(self) -> None:
        result = model_scores.primary_sdr({"vocals": 11.5, "instrumental": 16.25}, "vocals")
        self.assertEqual(result, ("vocals", 11.5))

    def test_falls_back_to_highest_when_no_target(self) -> None:
        result = model_scores.primary_sdr({"vocals": 11.5, "instrumental": 16.25}, None)
        self.assertEqual(result, ("instrumental", 16.25))

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(model_scores.primary_sdr({}, "vocals"))


class SdrStemResolutionTests(unittest.TestCase):
    """Score keys are lowercase; model targets are whatever the yaml said."""

    def test_two_stem_other_target_reads_instrumental_score(self) -> None:
        # mbr_inst2_unwa declares target 'other', meaning instrumental.
        scores = {"vocals": 9.0, "instrumental": 16.0}
        result = model_scores.primary_sdr(scores, "other", stem_count=2)
        self.assertEqual(result, ("instrumental", 16.0))

    def test_four_stem_other_target_reads_other_score(self) -> None:
        scores = {"vocals": 9.0, "drums": 10.0, "bass": 12.0, "other": 8.0}
        result = model_scores.primary_sdr(scores, "other", stem_count=4)
        self.assertEqual(result, ("other", 8.0))

    def test_case_mismatch_still_resolves(self) -> None:
        scores = {"vocals": 11.5, "instrumental": 16.25}
        self.assertEqual(model_scores.primary_sdr(scores, "Vocals", stem_count=2), ("vocals", 11.5))

    def test_unknown_target_falls_back_to_highest(self) -> None:
        scores = {"vocals": 11.5, "instrumental": 16.25}
        self.assertEqual(
            model_scores.primary_sdr(scores, "Similarity", stem_count=1),
            ("instrumental", 16.25),
        )


class SdrSubtitleTests(unittest.TestCase):
    def test_stem_is_named(self) -> None:
        self.assertEqual(
            model_scores.format_sdr_subtitle(11.43, "1.2 GB", stem="vocals"),
            "vocals 11.4 SDR · 1.2 GB",
        )

    def test_falls_back_to_extra_when_unscored(self) -> None:
        self.assertEqual(
            model_scores.format_sdr_subtitle(None, "890 MB", extra="vocals, other"),
            "vocals, other · 890 MB",
        )

    def test_size_only(self) -> None:
        self.assertEqual(model_scores.format_sdr_subtitle(None, "890 MB"), "890 MB")

    def test_bare_sdr_without_stem_still_renders(self) -> None:
        self.assertEqual(model_scores.format_sdr_subtitle(11.43, ""), "11.4 SDR")

    def test_format_sdr_subtitle_includes_extra_alongside_sdr(self) -> None:
        from core.model_scores import format_sdr_subtitle

        self.assertEqual(
            format_sdr_subtitle(11.43, "1.2 GB", stem="vocals", extra="Vocals, Instrumental"),
            "vocals 11.4 SDR · Vocals, Instrumental · 1.2 GB",
        )


class CatalogueNetworkFilterTests(unittest.TestCase):
    def test_onnx_checkpoint_is_classic_mdx(self) -> None:
        self.assertEqual(
            catalogue_network_id(
                family_arch=MDX_ARCH_TYPE,
                files=("UVR-MDX-NET-Inst_HQ_5.onnx",),
                label="MDX-Net Model: UVR-MDX-NET Inst HQ 5",
            ),
            NETWORK_CLASSIC_MDX,
        )

    def test_melband_label_without_hyphen_is_mel_band(self) -> None:
        self.assertEqual(
            catalogue_network_id(
                family_arch=MDX_ARCH_TYPE,
                files=("melband_roformer_inst_v1.ckpt", "config.yaml"),
                label="MelBand Roformer | InstVoc HQ",
            ),
            NETWORK_MEL_BAND,
        )

    def test_mdx23c_filename(self) -> None:
        self.assertEqual(
            catalogue_network_id(
                family_arch=MDX_ARCH_TYPE,
                files=("MDX23C-8KFFT-InstVoc_HQ.ckpt", "model_2_stem_full_band_8k.yaml"),
            ),
            NETWORK_MDX23C,
        )

    def test_scnet_masked_collapses_to_scnet(self) -> None:
        self.assertEqual(
            catalogue_network_id(
                family_arch=MDX_ARCH_TYPE,
                files=("scnet_masked_4stem.ckpt", "config.yaml"),
            ),
            NETWORK_SCNET,
        )

    def test_bandit_v2_collapses_to_bandit(self) -> None:
        self.assertEqual(
            catalogue_network_id(
                family_arch=MDX_ARCH_TYPE,
                files=("bandit_v2_cinema.ckpt",),
            ),
            NETWORK_BANDIT,
        )

    def test_unclassified_mdx_keeps_mdx_net_id(self) -> None:
        self.assertEqual(
            catalogue_network_id(
                family_arch=MDX_ARCH_TYPE,
                files=("mystery.ckpt", "config.yaml"),
                label="Custom checkpoint",
            ),
            MDX_ARCH_TYPE,
        )

    def test_vr_family_is_unchanged(self) -> None:
        self.assertEqual(
            catalogue_network_id(family_arch=VR_ARCH_TYPE, files=("1_HP-UVR.pth",)),
            VR_ARCH_TYPE,
        )

    def test_mdx_net_filter_matches_every_mdx_kind(self) -> None:
        for network in (
            NETWORK_CLASSIC_MDX,
            NETWORK_MDX23C,
            NETWORK_MEL_BAND,
            NETWORK_BS_ROFORMER,
            NETWORK_SCNET,
            NETWORK_BANDIT,
            MDX_ARCH_TYPE,
        ):
            with self.subTest(network=network):
                self.assertTrue(
                    network_filter_matches(
                        MDX_ARCH_TYPE,
                        family_arch=MDX_ARCH_TYPE,
                        network=network,
                    )
                )

    def test_mel_band_filter_excludes_classic_mdx(self) -> None:
        self.assertFalse(
            network_filter_matches(
                NETWORK_MEL_BAND,
                family_arch=MDX_ARCH_TYPE,
                network=NETWORK_CLASSIC_MDX,
            )
        )
        self.assertTrue(
            network_filter_matches(
                NETWORK_MEL_BAND,
                family_arch=MDX_ARCH_TYPE,
                network=NETWORK_MEL_BAND,
            )
        )

    def test_subtype_filter_does_not_match_vr(self) -> None:
        self.assertFalse(
            network_filter_matches(
                NETWORK_MEL_BAND,
                family_arch=VR_ARCH_TYPE,
                network=VR_ARCH_TYPE,
            )
        )

    def test_mdx_subtypes_map_to_mdx_folder(self) -> None:
        self.assertEqual(family_arch_for_network_filter(NETWORK_MEL_BAND), MDX_ARCH_TYPE)
        self.assertEqual(family_arch_for_network_filter(MDX_ARCH_TYPE), MDX_ARCH_TYPE)
        self.assertEqual(family_arch_for_network_filter(VR_ARCH_TYPE), VR_ARCH_TYPE)

    def test_mdx_net_and_any_keep_section_headers(self) -> None:
        self.assertFalse(network_filter_hides_headers(ARCH_FILTER_ALL))
        self.assertFalse(network_filter_hides_headers(MDX_ARCH_TYPE))
        self.assertTrue(network_filter_hides_headers(NETWORK_MEL_BAND))
        self.assertTrue(network_filter_hides_headers(VR_ARCH_TYPE))

    def test_dropdown_lists_mdx_subtypes_after_mdx_net(self) -> None:
        labels = [label for _value, label in NETWORK_FILTER_OPTIONS]
        self.assertEqual(
            labels,
            [
                "Any network",
                "VR Arch",
                "MDX-Net",
                "Classic MDX",
                "MDX23C",
                "Mel-Band Roformer",
                "BS-Roformer",
                "SCNet",
                "Bandit",
                "Demucs",
                "Apollo",
            ],
        )


class DownloadCenterHintTests(unittest.TestCase):
    def test_vr_opens_vocals_with_vr_network(self) -> None:
        expected = (PURPOSE_VOCALS, VR_ARCH_TYPE)
        self.assertEqual(download_center_hint_for_method(VR_ARCH_PM), expected)
        self.assertEqual(download_center_hint_for_method(VR_ARCH_TYPE), expected)

    def test_mdx_opens_vocals_with_mdx_network(self) -> None:
        self.assertEqual(
            download_center_hint_for_method(MDX_ARCH_TYPE),
            (PURPOSE_VOCALS, MDX_ARCH_TYPE),
        )

    def test_demucs_opens_stems_with_demucs_network(self) -> None:
        self.assertEqual(
            download_center_hint_for_method(DEMUCS_ARCH_TYPE),
            (PURPOSE_STEMS, DEMUCS_ARCH_TYPE),
        )

    def test_apollo_opens_restore_with_apollo_network(self) -> None:
        self.assertEqual(
            download_center_hint_for_method(APOLLO_ARCH_TYPE),
            (PURPOSE_RESTORE, APOLLO_ARCH_TYPE),
        )

    def test_unknown_method_stays_on_vocals_any_network(self) -> None:
        self.assertEqual(
            download_center_hint_for_method("Ensemble Mode"),
            (PURPOSE_VOCALS, ARCH_FILTER_ALL),
        )


class ModelScoresDisabledTests(_IsolatedScoreCache):
    def test_kill_switch_returns_empty(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"UVR_DISABLE_MODEL_SCORES": "1"}):
            self.assertEqual(model_scores.load_model_scores(force=True), {})


if __name__ == "__main__":
    unittest.main()
