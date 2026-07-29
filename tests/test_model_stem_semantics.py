import unittest

from bundled.constants import (
    BV_VOCAL_STEM,
    BV_VOCAL_STEM_LABEL,
    INST_STEM,
    INST_WITH_BACKING_VOCALS_STEM,
    INST_WITH_LEAD_VOCALS_STEM,
    LEAD_VOCAL_STEM,
    LEAD_VOCAL_STEM_LABEL,
    VOCAL_STEM,
)
from core.model_stem_semantics import (
    DUAL_STEM_WEIGHTS,
    INTENT_DRUM_BASS_SEP,
    INTENT_DUAL_VOC_INST,
    INTENT_INSTRUMENTAL,
    INTENT_KARAOKE,
    INTENT_MULTI_STEM,
    INTENT_SPECIALTY_STEM,
    INTENT_SPECIAL_FX,
    INTENT_VOCALS,
    VOCALS_OTHER_DISPLAY_OVERRIDES,
    apply_karaoke_quick_export_default,
    export_intent_from_fields,
    export_intent_from_model,
    export_stem_label,
    infer_is_karaoke_from_hints,
    infer_name_intent_from_label,
    is_special_fx_stem,
    is_specialty_instrument_pair,
    is_vocal_target,
    is_vocals_other_pair,
    karaoke_bv_export_labels,
    preferred_quick_export_mode,
    recommended_export_note,
    resolve_is_karaoke,
    shows_voc_inst_quick_export,
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
        self.is_bv_model = kwargs.get("is_bv_model", False)
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
        assert overrides is not None
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

    def test_karaoke_display_overrides(self):
        overrides = stem_display_overrides(_Model(is_karaoke=True))
        assert overrides is not None
        self.assertEqual(overrides[VOCAL_STEM], LEAD_VOCAL_STEM_LABEL)
        self.assertEqual(overrides[INST_STEM], INST_WITH_BACKING_VOCALS_STEM)

    def test_bv_display_overrides(self):
        overrides = stem_display_overrides(_Model(is_bv_model=True))
        assert overrides is not None
        self.assertEqual(overrides[VOCAL_STEM], BV_VOCAL_STEM_LABEL)
        self.assertEqual(overrides[INST_STEM], INST_WITH_LEAD_VOCALS_STEM)


class KaraokeBvExportLabelTests(unittest.TestCase):
    def test_karaoke_map(self):
        labels = karaoke_bv_export_labels(_Model(is_karaoke=True))
        assert labels is not None
        self.assertEqual(labels[VOCAL_STEM], LEAD_VOCAL_STEM_LABEL)
        self.assertEqual(labels[INST_STEM], INST_WITH_BACKING_VOCALS_STEM)

    def test_bv_preferred_over_karaoke(self):
        labels = karaoke_bv_export_labels(_Model(is_karaoke=True, is_bv_model=True))
        assert labels is not None
        self.assertEqual(labels[VOCAL_STEM], BV_VOCAL_STEM_LABEL)
        self.assertEqual(labels[INST_STEM], INST_WITH_LEAD_VOCALS_STEM)

    def test_export_stem_label_karaoke(self):
        model = _Model(is_karaoke=True)
        self.assertEqual(export_stem_label(model, VOCAL_STEM), LEAD_VOCAL_STEM_LABEL)
        self.assertEqual(
            export_stem_label(model, INST_STEM),
            INST_WITH_BACKING_VOCALS_STEM,
        )

    def test_export_stem_label_ensemble_passthrough(self):
        model = _Model(is_karaoke=True)
        self.assertEqual(
            export_stem_label(model, VOCAL_STEM, for_ensemble=True),
            VOCAL_STEM,
        )
        self.assertEqual(
            export_stem_label(model, LEAD_VOCAL_STEM, for_ensemble=True),
            LEAD_VOCAL_STEM,
        )

    def test_export_stem_label_ensemble_canonicalizes_yaml_casing(self):
        model = _Model()
        self.assertEqual(export_stem_label(model, "vocals", for_ensemble=True), VOCAL_STEM)
        self.assertEqual(export_stem_label(model, "drums", for_ensemble=True), "Drums")
        self.assertEqual(export_stem_label(model, "bass", for_ensemble=True), "Bass")
        self.assertEqual(export_stem_label(model, "other", for_ensemble=True), "Other")

    def test_export_stem_label_splitter_codes(self):
        model = _Model()
        self.assertEqual(export_stem_label(model, LEAD_VOCAL_STEM), LEAD_VOCAL_STEM_LABEL)
        self.assertEqual(export_stem_label(model, BV_VOCAL_STEM), BV_VOCAL_STEM_LABEL)


class EnsembleStemCanonicalizationTests(unittest.TestCase):
    def test_folds_known_aliases_only(self):
        from core.model_stem_semantics import canonical_ensemble_stem_tag

        self.assertEqual(canonical_ensemble_stem_tag("vocals"), VOCAL_STEM)
        self.assertEqual(canonical_ensemble_stem_tag("VOCALS"), VOCAL_STEM)
        self.assertEqual(canonical_ensemble_stem_tag("Drums"), "Drums")
        self.assertEqual(canonical_ensemble_stem_tag("drums"), "Drums")
        self.assertEqual(canonical_ensemble_stem_tag("instrumental"), INST_STEM)

    def test_preserves_specialty_and_karaoke_labels(self):
        from core.model_stem_semantics import canonical_ensemble_stem_tag

        self.assertEqual(canonical_ensemble_stem_tag(LEAD_VOCAL_STEM), LEAD_VOCAL_STEM)
        self.assertEqual(canonical_ensemble_stem_tag(LEAD_VOCAL_STEM_LABEL), LEAD_VOCAL_STEM_LABEL)
        self.assertEqual(canonical_ensemble_stem_tag("Speech"), "Speech")
        self.assertEqual(canonical_ensemble_stem_tag("Sfx"), "Sfx")
        self.assertEqual(canonical_ensemble_stem_tag("Music"), "Music")

    def test_does_not_fold_lead_vocals_into_vocals(self):
        from core.model_stem_semantics import canonical_ensemble_stem_tag

        self.assertNotEqual(
            canonical_ensemble_stem_tag(LEAD_VOCAL_STEM_LABEL),
            VOCAL_STEM,
        )


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

    def test_special_fx_note(self):
        model = _Model(
            primary_stem="noreverb",
            mdx_c_configs=_Config(["noreverb", "reverb"], "noreverb"),
        )
        note = recommended_export_note(model)
        self.assertIn("dereverbbed", note.lower())

    def test_specialty_stem_note(self):
        model = _Model(
            mdx_c_configs=_Config(["male", "female"]),
            model_name="BandSplit Roformer | Chorus Male-Female by Sucial",
        )
        note = recommended_export_note(model)
        self.assertIn("Male / Female", note)
        self.assertIn("Specialty", note)


class QuickExportSemanticsTests(unittest.TestCase):
    def test_multi_stem_hides_quick_export(self):
        model = _Model(
            mdx_c_configs=_Config(["vocals", "drums", "bass", "other"]),
            model_name="Demucs 4-stem",
        )
        stems = ["Vocals", "Drums", "Bass", "Other"]
        self.assertFalse(shows_voc_inst_quick_export(model, stems))

    def test_karaoke_shows_quick_export(self):
        model = _Model(
            is_karaoke=True,
            primary_stem=VOCAL_STEM,
            mdx_model_stems=["Vocals", "Instrumental", "Other"],
            model_name="BandSplit Roformer | Karaoke Frazer by becruily",
        )
        self.assertTrue(shows_voc_inst_quick_export(model, model.mdx_model_stems))

    def test_karaoke_prefers_instrumental_quick_export(self):
        model = _Model(
            is_karaoke=True,
            primary_stem=VOCAL_STEM,
            mdx_model_stems=["Vocals", "Instrumental", "Other"],
        )
        self.assertEqual(preferred_quick_export_mode(model), "instrumental")

    def test_apply_karaoke_default_sets_instrumental_flags(self):
        class _Settings(dict):
            def get(self, key, default=None):
                return super().get(key, default)

            def set(self, key, value):
                self[key] = value

        settings = _Settings(
            {
                "mdx_stems": "All Stems",
                "mdx_stems_selected": [],
                "is_primary_stem_only": False,
                "is_secondary_stem_only": False,
            }
        )
        model = _Model(
            is_karaoke=True,
            primary_stem=VOCAL_STEM,
            mdx_model_stems=["Vocals", "Instrumental", "Other"],
        )
        self.assertTrue(
            apply_karaoke_quick_export_default(
                settings,
                model,
                primary_key="is_primary_stem_only",
                secondary_key="is_secondary_stem_only",
            )
        )
        self.assertEqual(settings["mdx_stems_selected"], ["Vocals"])
        self.assertTrue(settings["is_secondary_stem_only"])
        self.assertFalse(settings["is_primary_stem_only"])


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


class SpecialFxIntentTests(unittest.TestCase):
    def test_bleedless_models_are_voc_or_inst_not_special_fx(self):
        cases = {
            "MelBand Roformer Kim | FT v2 Bleedless by Unwa": INTENT_VOCALS,
            "MelBand Roformer | Vocals Bleedless by Aname": INTENT_VOCALS,
            "MelBand Roformer | Instrumental Bleedless v1 by Gabox": INTENT_INSTRUMENTAL,
            "MelBand Roformer | Instrumental Fullness v4 Noise by Gabox": INTENT_DUAL_VOC_INST,
            "MelBand Roformer | Instrumental DeNoise-DeBleed by Gabox": INTENT_INSTRUMENTAL,
            "MelBand Roformer | Bleed Suppressor v1 by Unwa & 97chris": INTENT_INSTRUMENTAL,
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(infer_name_intent_from_label(label), expected)

    def test_subtraction_models_are_special_fx(self):
        cases = {
            "MDX-Net Model: UVR-MDX-NET Crowd HQ 1 By Aufr33": INTENT_SPECIAL_FX,
            "VR Arch Single Model v5: 17_HP-Wind_Inst-UVR": INTENT_SPECIAL_FX,
            "VR Arch Single Model v5: UVR-DeNoise by FoxJoy": INTENT_SPECIAL_FX,
            "MelBand Roformer | DeReverb by anvuew": INTENT_SPECIAL_FX,
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(infer_name_intent_from_label(label), expected)

    def test_crowd_extraction_is_specialty_not_subtraction(self):
        self.assertEqual(
            infer_name_intent_from_label("MelBand Roformer | Crowd by Aufr33 & Viperx"),
            INTENT_SPECIALTY_STEM,
        )

    def test_noreverb_target_is_special_fx_from_fields(self):
        self.assertEqual(
            export_intent_from_fields(target="noreverb", catalogue_label=""),
            INTENT_SPECIAL_FX,
        )
        self.assertTrue(is_special_fx_stem("noreverb"))
        self.assertTrue(is_special_fx_stem("no crowd"))


class SpecialtyStemIntentTests(unittest.TestCase):
    def test_specialty_labels(self):
        cases = {
            "BandSplit Roformer | Chorus Male-Female by Sucial": INTENT_SPECIALTY_STEM,
            "MelBand Roformer | Aspiration by Sucial": INTENT_SPECIALTY_STEM,
            "MDX23C Model: MDX23C Phantom Centre extraction by wesleyr36": INTENT_SPECIALTY_STEM,
            "MelBand Roformer | BVE by Gonza": INTENT_SPECIALTY_STEM,
            "MelBand Roformer | Guitar by becruily": INTENT_SPECIALTY_STEM,
            "MelBand Roformer | Crowd by Aufr33 & Viperx": INTENT_SPECIALTY_STEM,
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(infer_name_intent_from_label(label), expected)

    def test_specialty_from_instruments(self):
        self.assertEqual(
            export_intent_from_fields(instruments=["male", "female"]),
            INTENT_SPECIALTY_STEM,
        )
        self.assertTrue(is_specialty_instrument_pair(["aspiration", "other"]))

    def test_special_fx_backend_focus(self):
        from core.model_stem_semantics import backend_focus_label

        self.assertEqual(
            backend_focus_label("no echo", "", []),
            "special_fx_primary:no echo",
        )
        self.assertEqual(
            backend_focus_label("", "noreverb", ["noreverb", "reverb"]),
            "special_fx_target:noreverb",
        )
        self.assertEqual(
            backend_focus_label("", "", ["male", "female"]),
            "specialty_two_stem",
        )


if __name__ == "__main__":
    unittest.main()
