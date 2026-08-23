import os
import tempfile
import unittest
import unittest.mock
import wave

from bundled.constants import DEFAULT_DATA, DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from bundled.error_handling import error_text
from core.error_context import (
    build_ensemble_context,
    build_separation_context,
    clear_run_error_context,
    format_error_context,
    model_summary_lines,
    non_default_setting_lines,
    probe_audio_file,
    set_run_error_context,
    update_run_error_context,
)
from core.model_repository import ModelRepository
from core.model_identity import ModelArtifacts, ModelRecord
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

    @unittest.mock.patch("core.error_context.ModelIdentityService")
    def test_build_separation_context_prefers_installed_record_display(
        self, service: unittest.mock.Mock
    ) -> None:
        service.return_value.display_label.return_value = "Inst HQ 3"
        settings = Settings.defaults()
        settings.set("chosen_process_method", MDX_ARCH_TYPE)
        settings.set("mdx_net_model", "mdx:UVR-MDX-NET-Inst_HQ_3")

        ctx = build_separation_context(
            settings, ModelRepository(), ["song.wav"], MDX_ARCH_TYPE
        )

        self.assertEqual(ctx["models"], ["Inst HQ 3"])

    def test_ensemble_error_log_uses_displays_without_mutating_exact_ids(
        self,
    ) -> None:
        settings = Settings.defaults()
        settings.ensemble.selected_models = ["mdx:first", "vr:second"]
        records = {
            "mdx:first": ModelRecord(
                id="mdx:first",
                family="mdx",
                basename="first",
                display="Friendly First",
                backend_name="first",
                artifacts=ModelArtifacts("first.onnx"),
                installed=True,
            ),
            "vr:second": ModelRecord(
                id="vr:second",
                family="vr",
                basename="second",
                display="Friendly Second",
                backend_name="second",
                artifacts=ModelArtifacts("second.pth"),
                installed=True,
            ),
        }

        with unittest.mock.patch(
            "core.error_context.ModelIdentityService.lookup",
            autospec=True,
            side_effect=lambda _service, model_id: records[model_id],
        ):
            ctx = build_ensemble_context(settings, ["song.wav"], repo=object())
            set_run_error_context(**ctx)
            text = format_error_context()

        self.assertIn("Friendly First", text)
        self.assertIn("Friendly Second", text)
        self.assertNotIn("mdx:first", text)
        self.assertNotIn("vr:second", text)
        self.assertEqual(settings.ensemble.selected_models, ["mdx:first", "vr:second"])

    def test_ensemble_error_log_keeps_exact_id_when_display_lookup_fails(
        self,
    ) -> None:
        settings = Settings.defaults()
        settings.ensemble.selected_models = ["mdx:missing"]

        with unittest.mock.patch(
            "core.error_context.ModelIdentityService.lookup",
            autospec=True,
            side_effect=ValueError("not installed"),
        ):
            ctx = build_ensemble_context(settings, ["song.wav"], repo=object())

        self.assertEqual(ctx["models"], ["mdx:missing"])
        self.assertEqual(settings.ensemble.selected_models, ["mdx:missing"])

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

    def test_model_summary_prefers_the_carried_identity_display(self) -> None:
        model = unittest.mock.Mock()
        model.model_display_label = "BandSplit PolarFormer — Karaoke · Lambda001"
        model.process_method = MDX_ARCH_TYPE
        model.model_name = "raw-checkpoint"
        model.model_basename = "raw-checkpoint"
        model.repo = object()
        model.is_roformer = True
        model.mdx_segment_size = 256
        model.is_mdx_c_seg_def = False
        model.overlap_mdx23 = 8
        model.is_secondary_model_activated = False

        with unittest.mock.patch(
            "core.error_context.display_name_for_model", return_value="stale mapper label"
        ):
            lines = model_summary_lines(model)

        self.assertEqual(lines[0], f"model={model.model_display_label}")


if __name__ == "__main__":
    unittest.main()
