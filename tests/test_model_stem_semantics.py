import unittest

from bundled.constants import INST_STEM, VOCAL_STEM
from core.model_stem_semantics import (
    DUAL_STEM_WEIGHTS,
    INTENT_DRUM_BASS_SEP,
    INTENT_DUAL_VOC_INST,
    INTENT_INSTRUMENTAL,
    INTENT_KARAOKE,
    INTENT_VOCALS,
    VOCALS_OTHER_DISPLAY_OVERRIDES,
    export_intent_from_fields,
    export_intent_from_model,
    infer_is_karaoke_from_hints,
    infer_name_intent_from_label,
    is_vocal_target,
    is_vocals_other_pair,
    recommended_export_note,
    resolve_is_karaoke,
    stem_display_overrides,
)


class _Training:
    def __init__(self, instruments, target=""):
        self.instruments = instruments
        self.target_instrument = target


class _Config:
    def __init__(self, instruments, target=""):
        self.training = _Training(instruments, target)


class _Model:
    def __init__(self, **kwargs):
        self.is_roformer = kwargs.get("is_roformer", False)
        self.is_karaoke = kwargs.get("is_karaoke", False)
        self.primary_stem = kwargs.get("primary_stem", "")
        self.mdx_c_configs = kwargs.get("mdx_c_configs")
        self.mdx_model_stems = kwargs.get("mdx_model_stems", [])
        self.model_basename = kwargs.get("model_basename", "")
        self.model_name = kwargs.get("model_name", "")


class ExportIntentTests(unittest.TestCase):
    def test_mdx_main_is_dual_stem(self):
        intent = export_intent_from_fields(
            primary_stem=VOCAL_STEM,
            weight_basename="uvr_mdxnet_main.onnx",
            catalogue_label="MDX-Net Model: UVR-MDX-NET Main",
        )
        self.assertEqual(intent, INTENT_DUAL_VOC_INST)

    def test_vocals_other_yaml_is_instrumental_when_target_other(self):
        intent = export_intent_from_fields(
            target="other",
            instruments=["other", "vocals"],
            catalogue_label="MelBand Roformer Kim | Inst v1 by Unwa",
        )
        self.assertEqual(intent, INTENT_INSTRUMENTAL)

    def test_drum_bass_pair(self):
        intent = export_intent_from_fields(
            target="No Drum-Bass",
            instruments=["No Drum-Bass", "Drum-Bass"],
        )
        self.assertEqual(intent, INTENT_DRUM_BASS_SEP)

    def test_infer_name_mgm_instrumental(self):
        self.assertEqual(
            infer_name_intent_from_label("VR Arch Single Model v4: MGM_MAIN_v4"),
            INTENT_INSTRUMENTAL,
        )

    def test_infer_name_mdx_net_main_dual(self):
        self.assertEqual(
            infer_name_intent_from_label("MDX-Net Model: UVR-MDX-NET Main"),
            INTENT_DUAL_VOC_INST,
        )


class StemDisplayOverridesTests(unittest.TestCase):
    def test_roformer_vocals_other_overrides(self):
        model = _Model(
            is_roformer=True,
            mdx_c_configs=_Config(["other", "vocals"], "other"),
        )
        overrides = stem_display_overrides(model)
        self.assertEqual(overrides, VOCALS_OTHER_DISPLAY_OVERRIDES)
        self.assertEqual(overrides["other"], INST_STEM)
        self.assertEqual(overrides["vocals"], VOCAL_STEM)

    def test_non_pair_returns_none(self):
        model = _Model(is_roformer=True, mdx_c_configs=_Config(["vocals", "drums"]))
        self.assertIsNone(stem_display_overrides(model))

    def test_four_stem_vocals_other_yaml_returns_none(self):
        model = _Model(
            is_roformer=True,
            mdx_c_configs=_Config(["other", "vocals", "drums", "bass"], "other"),
        )
        self.assertIsNone(stem_display_overrides(model))


class KaraokeDetectionTests(unittest.TestCase):
    def test_infer_karaoke_from_catalogue_label(self):
        self.assertTrue(
            infer_is_karaoke_from_hints(
                model_name="BandSplit Roformer | Karaoke Frazer by becruily",
            )
        )

    def test_infer_karaoke_from_config_yaml(self):
        self.assertTrue(
            infer_is_karaoke_from_hints(
                config_yaml="config_BandSplit-Roformer_Karaoke_Frazer_by-becruily.yaml",
            )
        )

    def test_resolve_karaoke_prefers_hash_metadata(self):
        self.assertTrue(resolve_is_karaoke(model_data={"is_karaoke": True}))

    def test_vocal_target_is_case_insensitive(self):
        self.assertTrue(is_vocal_target("Vocals"))
        self.assertTrue(is_vocal_target("vocals"))


class RecommendedExportNoteTests(unittest.TestCase):
    def test_dual_stem_main_note(self):
        model = _Model(
            primary_stem=VOCAL_STEM,
            model_basename="UVR_MDXNET_Main",
            model_name="MDX-Net Model: UVR-MDX-NET Main",
        )
        note = recommended_export_note(model)
        self.assertIn("first-class", note.lower())

    def test_karaoke_vocal_primary_note(self):
        model = _Model(
            is_karaoke=True,
            primary_stem=VOCAL_STEM,
            model_name="BandSplit Roformer | Karaoke Frazer by becruily",
        )
        note = recommended_export_note(model)
        self.assertIn("Instrumental", note)
        self.assertIn("backing", note.lower())

    def test_karaoke_inferred_from_name_without_flag(self):
        model = _Model(
            primary_stem=VOCAL_STEM,
            model_name="BandSplit Roformer | Karaoke Frazer by becruily",
        )
        self.assertEqual(export_intent_from_model(model), INTENT_KARAOKE)
        self.assertIn("Instrumental", recommended_export_note(model))

    def test_empty_for_plain_vocal_model(self):
        model = _Model(
            primary_stem=VOCAL_STEM,
            mdx_c_configs=_Config(["vocals", "other"], "vocals"),
            is_roformer=True,
        )
        self.assertEqual(recommended_export_note(model), "")


class PairDetectionTests(unittest.TestCase):
    def test_is_vocals_other_pair(self):
        self.assertTrue(is_vocals_other_pair(["other", "vocals"]))
        self.assertFalse(is_vocals_other_pair(["Vocals", "Instrumental"]))


class ExportIntentFromModelTests(unittest.TestCase):
    def test_model_wrapper(self):
        model = _Model(
            primary_stem=INST_STEM,
            model_basename="1_HP-UVR",
            model_name="VR Arch Single Model v5: 1_HP-UVR",
        )
        self.assertEqual(export_intent_from_model(model), INTENT_INSTRUMENTAL)


if __name__ == "__main__":
    unittest.main()
