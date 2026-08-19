"""Pure settings-to-subtitle summaries for collapsible option sections."""

from __future__ import annotations
import typing

import unittest

from bundled.constants import (
    ALL_STEMS,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    NO_MODEL,
)
from core.stems import EnsemblePair
from core.settings import Settings
from ui.option_summaries import (
    OFF,
    ON_NO_MODEL,
    four_stem_secondaries_apply,
    preproc_summary,
    secondary_models_summary,
    vocal_split_summary,
)


class _Settings:
    """Build real typed settings with concise flat-key overrides."""

    def __new__(cls, **values: typing.Any):
        return Settings.from_flat(values)


class FourStemApplicabilityTests(unittest.TestCase):
    def test_demucs_with_all_stems_uses_four_slots(self):
        settings = _Settings(demucs_stems=ALL_STEMS)
        self.assertTrue(four_stem_secondaries_apply(settings, DEMUCS_ARCH_TYPE))

    def test_demucs_without_all_stems_does_not(self):
        settings = _Settings(demucs_stems="Vocals")
        self.assertFalse(four_stem_secondaries_apply(settings, DEMUCS_ARCH_TYPE))

    def test_mdx_alone_never_uses_four_slots(self):
        settings = _Settings(demucs_stems=ALL_STEMS)
        self.assertFalse(four_stem_secondaries_apply(settings, MDX_ARCH_TYPE))

    def test_four_stem_ensemble_applies_to_every_architecture(self):
        settings = _Settings(
            chosen_process_method=ENSEMBLE_MODE,
            ensemble_main_stem=EnsemblePair.FOUR_STEM.value,
        )
        self.assertTrue(four_stem_secondaries_apply(settings, MDX_ARCH_TYPE))
        self.assertTrue(four_stem_secondaries_apply(settings, DEMUCS_ARCH_TYPE))

    def test_multi_stem_ensemble_applies_to_demucs_only(self):
        settings = _Settings(
            chosen_process_method=ENSEMBLE_MODE,
            ensemble_main_stem=EnsemblePair.MULTI_STEM.value,
        )
        self.assertTrue(four_stem_secondaries_apply(settings, DEMUCS_ARCH_TYPE))
        self.assertFalse(four_stem_secondaries_apply(settings, MDX_ARCH_TYPE))

    def test_ensemble_with_a_plain_pair_does_not_use_four_slots(self):
        """All-stems is a non-ensemble rule: core/model_data.py:606 gates it
        on ``not is_ensemble_mode``, so an ordinary 2-stem ensemble must not
        reach the four-slot path even with demucs_stems set to ALL_STEMS."""
        settings = _Settings(
            chosen_process_method=ENSEMBLE_MODE,
            ensemble_main_stem=EnsemblePair.VOCALS_INSTRUMENTAL.value,
            demucs_stems=ALL_STEMS,
        )
        self.assertFalse(four_stem_secondaries_apply(settings, DEMUCS_ARCH_TYPE))


class SecondaryModelsSummaryTests(unittest.TestCase):
    def test_off_when_not_activated(self):
        settings = _Settings(mdx_is_secondary_model_activate=False)
        self.assertEqual(
            secondary_models_summary(settings, "mdx", four_stem=False), OFF
        )

    def test_on_but_unset_reports_no_model(self):
        settings = _Settings(
            mdx_is_secondary_model_activate=True,
            mdx_voc_inst_secondary_model=NO_MODEL,
        )
        self.assertEqual(
            secondary_models_summary(settings, "mdx", four_stem=False), ON_NO_MODEL
        )

    def test_describes_the_configured_pair(self):
        settings = _Settings(
            mdx_is_secondary_model_activate=True,
            mdx_voc_inst_secondary_model="MDX-Net: UVR-MDX-NET Inst HQ 3",
            mdx_voc_inst_secondary_model_scale=0.9,
        )
        summary = secondary_models_summary(settings, "mdx", four_stem=False)
        self.assertIn("UVR-MDX-NET Inst HQ 3", summary)
        self.assertIn("0.90", summary)
        self.assertNotIn("MDX-Net:", summary)

    def test_canonical_id_strips_family_prefix(self):
        settings = _Settings(
            mdx_is_secondary_model_activate=True,
            mdx_voc_inst_secondary_model="mdx:UVR-MDX-NET-Inst_HQ_3",
            mdx_voc_inst_secondary_model_scale=0.9,
        )
        summary = secondary_models_summary(settings, "mdx", four_stem=False)
        self.assertIn("UVR-MDX-NET-Inst_HQ_3", summary)
        self.assertNotIn("mdx:", summary)

    def test_two_stem_ignores_other_bass_drums(self):
        settings = _Settings(
            demucs_is_secondary_model_activate=True,
            demucs_voc_inst_secondary_model=NO_MODEL,
            demucs_bass_secondary_model="VR Arc: 1_HP-UVR",
            demucs_bass_secondary_model_scale=0.5,
        )
        self.assertEqual(
            secondary_models_summary(settings, "demucs", four_stem=False), ON_NO_MODEL
        )

    def test_four_stem_includes_other_bass_drums(self):
        settings = _Settings(
            demucs_is_secondary_model_activate=True,
            demucs_voc_inst_secondary_model=NO_MODEL,
            demucs_bass_secondary_model="VR Arc: 1_HP-UVR",
            demucs_bass_secondary_model_scale=0.5,
        )
        summary = secondary_models_summary(settings, "demucs", four_stem=True)
        self.assertIn("1_HP-UVR", summary)

    def test_multiple_pairs_are_joined(self):
        settings = _Settings(
            demucs_is_secondary_model_activate=True,
            demucs_voc_inst_secondary_model="MDX-Net: A",
            demucs_voc_inst_secondary_model_scale=0.9,
            demucs_bass_secondary_model="VR Arc: B",
            demucs_bass_secondary_model_scale=0.5,
        )
        summary = secondary_models_summary(settings, "demucs", four_stem=True)
        self.assertIn(" · ", summary)


class PreprocSummaryTests(unittest.TestCase):
    def test_off_when_not_activated(self):
        self.assertEqual(
            preproc_summary(_Settings(is_demucs_pre_proc_model_activate=False)), OFF
        )

    def test_on_but_unset_reports_no_model(self):
        settings = _Settings(
            is_demucs_pre_proc_model_activate=True,
            demucs_pre_proc_model=NO_MODEL,
        )
        self.assertEqual(preproc_summary(settings), ON_NO_MODEL)

    def test_names_the_model(self):
        settings = _Settings(
            is_demucs_pre_proc_model_activate=True,
            demucs_pre_proc_model="MDX-Net: UVR-MDX-NET Inst HQ 3",
        )
        self.assertEqual(preproc_summary(settings), "UVR-MDX-NET Inst HQ 3")

    def test_mentions_the_instrumental_mixture(self):
        settings = _Settings(
            is_demucs_pre_proc_model_activate=True,
            demucs_pre_proc_model="MDX-Net: X",
            is_demucs_pre_proc_model_inst_mix=True,
        )
        self.assertIn("instrumental mixture", preproc_summary(settings))


class VocalSplitSummaryTests(unittest.TestCase):
    def test_off_only_when_both_switches_are_off(self):
        settings = _Settings(is_set_vocal_splitter=False, is_deverb_vocals=False)
        self.assertEqual(vocal_split_summary(settings), OFF)

    def test_splitter_alone_names_the_model(self):
        settings = _Settings(
            is_set_vocal_splitter=True,
            set_vocal_splitter="VR Arc: UVR-BVE-4B",
            is_deverb_vocals=False,
        )
        self.assertEqual(vocal_split_summary(settings), "UVR-BVE-4B")

    def test_splitter_on_without_model_reports_no_model(self):
        settings = _Settings(
            is_set_vocal_splitter=True,
            set_vocal_splitter=NO_MODEL,
            is_deverb_vocals=False,
        )
        self.assertEqual(vocal_split_summary(settings), ON_NO_MODEL)

    def test_deverb_alone_is_described_without_a_splitter(self):
        settings = _Settings(
            is_set_vocal_splitter=False,
            is_deverb_vocals=True,
            deverb_vocal_opt="Main Vocals Only",
        )
        self.assertEqual(vocal_split_summary(settings), "deverb: Main Vocals Only")

    def test_both_are_joined(self):
        settings = _Settings(
            is_set_vocal_splitter=True,
            set_vocal_splitter="VR Arc: UVR-BVE-4B",
            is_deverb_vocals=True,
            deverb_vocal_opt="All Vocal Types",
        )
        self.assertEqual(
            vocal_split_summary(settings), "UVR-BVE-4B · deverb: All Vocal Types"
        )

    def test_missing_keys_degrade_to_off(self):
        self.assertEqual(vocal_split_summary(_Settings()), OFF)


if __name__ == "__main__":
    unittest.main()
