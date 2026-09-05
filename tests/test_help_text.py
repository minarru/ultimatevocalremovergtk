import unittest

from ui.help_text import (
    AGGRESSION_SETTING_HELP,
    AMPLIFICATION_THRESHOLD_HELP,
    BATCH_SIZE_HELP,
    COMPENSATE_HELP,
    CROP_SIZE_HELP,
    ENSEMBLE_LISTBOX_HELP,
    ENSEMBLE_TYPE_HELP,
    IS_DENOISE_HELP,
    IS_DEVERB_VOC_HELP,
    IS_FREQUENCY_MATCH_HELP,
    IS_PREVENT_EXPORT_CLIPPING_HELP,
    IS_SPLIT_MODE_HELP,
    IS_VOC_SPLIT_INST_SAVE_SELECT_HELP,
    IS_VOC_SPLIT_MODEL_SELECT_HELP,
    IS_WAV_ENSEMBLE_HELP,
    MANUAL_ENSEMBLE_ALGORITHM_HINT,
    MODEL_OPTIONS_ROW_HINT,
    MODEL_SAMPLE_MODE_HELP,
    OVERLAP_HELP,
    PHASE_SHIFTS_ALIGN_HELP,
    POST_PROCESS_THREASHOLD_HELP,
    PRE_PROC_MODEL_HELP,
    PROCESS_METHOD_HINT,
    PROGRESS_ETA_HINT,
    SAVE_STEM_ONLY_HELP,
    STEM_ONLY_ALL_HINT,
    VIEW_INPUTS_BUTTON_HINT,
    iter_help_strings,
    validate_help_text,
)


class HelpTextStyleTests(unittest.TestCase):
    def test_all_tooltip_strings_follow_style_guide(self):
        violations: list[str] = []
        for name, text in iter_help_strings():
            violations.extend(validate_help_text(text, name=name))
        self.assertEqual(
            violations,
            [],
            "Help text style violations:\n" + "\n".join(violations),
        )

    def test_behavior_sensitive_tooltips_match_current_controls(self):
        self.assertIn("0 to 50", AGGRESSION_SETTING_HELP)
        self.assertNotIn("-100", AGGRESSION_SETTING_HELP)
        self.assertIn("0.25, 0.50, 0.75, and 0.99", OVERLAP_HELP)
        self.assertIn("Instrumental with Lead Vocals", IS_VOC_SPLIT_INST_SAVE_SELECT_HELP)
        self.assertNotIn("does not work in ensemble", IS_VOC_SPLIT_MODEL_SELECT_HELP)
        self.assertNotIn("does not work in ensemble", IS_DEVERB_VOC_HELP)
        self.assertIn("independently of Normalize output", AMPLIFICATION_THRESHOLD_HELP)
        self.assertIn("Spectral-only algorithms ignore", IS_WAV_ENSEMBLE_HELP)
        self.assertIn("Preferences → Processing", MODEL_SAMPLE_MODE_HELP)
        self.assertIn("time-window alignment", PHASE_SHIFTS_ALIGN_HELP)
        self.assertNotIn("vocal", MODEL_OPTIONS_ROW_HINT.casefold())
        self.assertIn("extra-model", MODEL_OPTIONS_ROW_HINT)
        self.assertIn("current VR inference does not use it", CROP_SIZE_HELP)
        self.assertIn("Lower values affect more", POST_PROCESS_THREASHOLD_HELP)
        self.assertIn("higher values are more selective", POST_PROCESS_THREASHOLD_HELP)
        self.assertIn("Demucs v4 always", IS_SPLIT_MODE_HELP)
        self.assertIn("pitch shift and Spectral inversion", IS_FREQUENCY_MATCH_HELP)
        self.assertIn("otherwise no effect", IS_FREQUENCY_MATCH_HELP)
        self.assertIn("supported vocal outputs", IS_DENOISE_HELP)
        self.assertNotIn("all MDX-Net models", IS_DENOISE_HELP)
        self.assertIn("Also save de-reverberated and reverb-only", IS_DEVERB_VOC_HELP)
        self.assertIn("instrumental output is fed into Demucs", PRE_PROC_MODEL_HELP)
        self.assertIn("Classic MDX-Net only", COMPENSATE_HELP)
        self.assertIn("Roformer models use their YAML batch size", BATCH_SIZE_HELP)
        self.assertIn("Multi-stem exports share one gain", IS_PREVENT_EXPORT_CLIPPING_HELP)
        self.assertIn("spectrogram-based models", PROCESS_METHOD_HINT)
        self.assertNotIn("MDX-Net — hybrid spectrogram", PROCESS_METHOD_HINT)
        self.assertIn("compatible", ENSEMBLE_LISTBOX_HELP)
        self.assertIn("Max Spec", ENSEMBLE_TYPE_HELP)
        self.assertIn("Median Spec", ENSEMBLE_TYPE_HELP)
        self.assertIn("Chunk Min", ENSEMBLE_TYPE_HELP)
        self.assertIn("Primary/Secondary", ENSEMBLE_TYPE_HELP)
        self.assertNotIn("writes one file", SAVE_STEM_ONLY_HELP)
        self.assertNotIn("default", STEM_ONLY_ALL_HINT.casefold())
        self.assertIn("unless waveform mode supports", MANUAL_ENSEMBLE_ALGORITHM_HINT)
        self.assertEqual(VIEW_INPUTS_BUTTON_HINT, "Review and verify inputs")
        self.assertNotIn("holds while saving", PROGRESS_ETA_HINT)
        self.assertIn("fills during inference", PROGRESS_ETA_HINT)
        self.assertIn("Combining i/n", PROGRESS_ETA_HINT)


if __name__ == "__main__":
    unittest.main()
