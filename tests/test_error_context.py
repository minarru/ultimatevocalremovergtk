import os
import tempfile
import unittest
import unittest.mock
import wave

from bundled.constants import DEFAULT_DATA, DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from bundled.error_handling import error_text
from core.error_context import (
    build_separation_context,
    clear_run_error_context,
    format_error_context,
    model_summary_lines,
    non_default_setting_lines,
    probe_audio_file,
    set_run_error_context,
    update_run_error_context,
)
from core.model_data import ModelRepository
from core.settings import Settings
from ui.errorlog import log_error


class ErrorContextTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_run_error_context()

    def test_non_default_setting_lines_only_reports_changes(self) -> None:
        settings = Settings.defaults()
        settings.set("mdx_segment_size", 512)
        lines = non_default_setting_lines(settings)
        self.assertTrue(any("mdx_segment_size=512" in line for line in lines))
        self.assertFalse(any("window_width" in line for line in lines))

    def test_probe_audio_file_reads_wav_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "clip.wav")
            with wave.open(path, "w") as handle:
                handle.setnchannels(2)
                handle.setsampwidth(2)
                handle.setframerate(44100)
                handle.writeframes(b"\x00\x00" * (44100 * 2))
            info = probe_audio_file(path)
        self.assertTrue(info["valid"])
        self.assertEqual(info["sample_rate"], 44100)
        self.assertEqual(info["channels"], 2)
        self.assertAlmostEqual(info["duration_sec"], 1.0, places=2)

    def test_format_error_context_includes_model_and_audio(self) -> None:
        set_run_error_context(
            process="MDX-Net",
            models=["MelBand Roformer | Karaoke Fusion by Gonza"],
            model_lines=[
                "model=MelBand Roformer | Karaoke Fusion by Gonza",
                "engine=Roformer",
                "mdx_segment_size=256",
            ],
            audio={
                "basename": "song.wav",
                "valid": True,
                "sample_rate": 48000,
                "channels": 2,
                "duration_sec": 245.5,
                "frames": 11784000,
                "format": "WAV",
            },
            non_default_settings=["overlap_mdx23=8 (default 2)"],
        )
        text = format_error_context()
        self.assertIn("Run Context:", text)
        self.assertIn("MelBand Roformer", text)
        self.assertIn("native_sample_rate=48000 Hz", text)
        self.assertIn("processing_sample_rate=44100 Hz", text)
        self.assertIn("overlap_mdx23=8", text)

    def test_error_text_includes_context_block(self) -> None:
        context = "Run Context:\n\nProcess: MDX-Net\n"
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            formatted = error_text("MDX-Net", exc, context=context)
        self.assertIn(context, formatted)
        self.assertIn("RuntimeError", formatted)

    def test_log_error_uses_stored_context(self) -> None:
        set_run_error_context(
            process="MDX-Net",
            models=["Test Model"],
            non_default_settings=[f"mdx_segment_size={DEFAULT_DATA['mdx_segment_size']!r} (default)"],
        )
        formatted = log_error("MDX-Net", RuntimeError("boom"))
        self.assertIn("Run Context:", formatted)
        self.assertIn("Test Model", formatted)

    def test_build_separation_context_uses_display_model_name(self) -> None:
        settings = Settings.defaults()
        settings.set("chosen_process_method", MDX_ARCH_TYPE)
        settings.set("mdx_net_model", "model_MelBand-Roformer_Karaoke_Fusion_Standard_by-Gonza.ckpt")
        ctx = build_separation_context(settings, ModelRepository(), ["song.wav"], MDX_ARCH_TYPE)
        self.assertEqual(ctx["process"], MDX_ARCH_TYPE)
        self.assertEqual(ctx["input_files"], ["song.wav"])
        self.assertTrue(ctx["models"])

    def test_model_summary_lines_for_vr_and_demucs(self) -> None:
        """Regression: VR/Demucs branches must not NameError on VR_ARCH_TYPE."""

        class _Fake:
            process_method = VR_ARCH_TYPE
            model_name = "v5: test"
            model_basename = "test"
            repo = object()
            window_size = 512
            aggression_setting = 0.05
            model_samplerate = 44100
            is_secondary_model_activated = False
            demucs_stems = ""
            overlap = 0.0

        with unittest.mock.patch(
            "core.error_context.display_name_for_model",
            return_value="v5: test",
        ):
            vr_lines = model_summary_lines(_Fake())
            self.assertTrue(any("engine=VR" in line for line in vr_lines))

            demucs = _Fake()
            demucs.process_method = DEMUCS_ARCH_TYPE
            demucs.demucs_stems = "All Stems"
            demucs.overlap = 0.25
            demucs_lines = model_summary_lines(demucs)
            self.assertTrue(any("engine=Demucs" in line for line in demucs_lines))


if __name__ == "__main__":
    unittest.main()
