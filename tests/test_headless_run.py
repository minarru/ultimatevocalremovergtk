"""Unit tests for headless run helpers (no GPU / no real separation)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from bundled.constants import (
    ALL_STEMS,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    VOCAL_STEM,
    VR_ARCH_PM,
)
from core.bench_metrics import (
    array_diff_stats,
    compare_stem_dirs,
    parse_env_assignment,
    sanitize_env_label,
)
from core.headless_run import (
    apply_stems_override,
    build_settings,
    parse_cli_stems,
    resolve_cli_model_arg,
    resolve_method,
    settings_summary,
)
from core.settings import Settings


class ResolveCliModelArgTests(unittest.TestCase):
    def test_strips_extension_and_maps_installed_basename(self) -> None:
        repo = mock.MagicMock()
        repo.list_mdx_models.return_value = [
            "model_BandSplit-Roformer_Karaoke_Frazer_by-becruily"
        ]
        with mock.patch(
            "core.model_display.map_basenames_to_display",
            return_value=["BandSplit Roformer | Karaoke Frazer by becruily"],
        ), mock.patch(
            "core.model_display.display_name_for_model",
            return_value="BandSplit Roformer | Karaoke Frazer by becruily",
        ):
            out = resolve_cli_model_arg(
                MDX_ARCH_TYPE,
                "/models/MDX_Net_Models/model_BandSplit-Roformer_Karaoke_Frazer_by-becruily.ckpt",
                repo=repo,
            )
        self.assertEqual(out, "BandSplit Roformer | Karaoke Frazer by becruily")

    def test_fuzzy_unique_substring(self) -> None:
        repo = mock.MagicMock()
        repo.list_mdx_models.return_value = [
            "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956",
            "model_BandSplit-Roformer_Karaoke_Frazer_by-becruily",
        ]
        with mock.patch(
            "core.model_display.map_basenames_to_display",
            return_value=[
                "MelBand Roformer | Karaoke aufr33",
                "BandSplit Roformer | Karaoke Frazer by becruily",
            ],
        ):
            out = resolve_cli_model_arg(
                MDX_ARCH_TYPE, "karaoke_frazer.ckpt", repo=repo
            )
        self.assertEqual(out, "BandSplit Roformer | Karaoke Frazer by becruily")

    def test_ambiguous_substring_raises(self) -> None:
        repo = mock.MagicMock()
        repo.list_mdx_models.return_value = [
            "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956",
            "model_BandSplit-Roformer_Karaoke_Frazer_by-becruily",
        ]
        with mock.patch(
            "core.model_display.map_basenames_to_display",
            return_value=[
                "MelBand Roformer | Karaoke aufr33",
                "BandSplit Roformer | Karaoke Frazer by becruily",
            ],
        ):
            with self.assertRaises(ValueError) as ctx:
                resolve_cli_model_arg(MDX_ARCH_TYPE, "karaoke", repo=repo)
        self.assertIn("ambiguous", str(ctx.exception))

    def test_keeps_display_name(self) -> None:
        repo = mock.MagicMock()
        repo.list_demucs_models.return_value = ["hdemucs_mmi"]
        with mock.patch(
            "core.model_display.map_basenames_to_display",
            return_value=["v4 | hdemucs_mmi"],
        ):
            out = resolve_cli_model_arg(DEMUCS_ARCH_TYPE, "v4 | hdemucs_mmi", repo=repo)
        self.assertEqual(out, "v4 | hdemucs_mmi")

    def test_demucs_bag_member_th_maps_to_parent(self) -> None:
        repo = mock.MagicMock()
        repo.list_demucs_models.return_value = ["hdemucs_mmi"]
        with mock.patch(
            "core.demucs_models.demucs_bag_owner_basename",
            return_value="hdemucs_mmi",
        ), mock.patch(
            "core.model_display.display_name_for_model",
            return_value="v4 | hdemucs_mmi",
        ):
            out = resolve_cli_model_arg(
                DEMUCS_ARCH_TYPE, "75fc33f5-1941ce65.th", repo=repo
            )
        self.assertEqual(out, "v4 | hdemucs_mmi")

    def test_build_settings_accepts_filename(self) -> None:
        repo = mock.MagicMock()
        repo.list_vr_models.return_value = ["5_HP-Karaoke-UVR"]
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = os.path.join(tmp, "settings.json")
            Settings.defaults().save(settings_path)
            with mock.patch(
                "core.model_display.map_basenames_to_display",
                return_value=["v5: 5_HP-Karaoke-UVR"],
            ), mock.patch(
                "core.model_display.display_name_for_model",
                return_value="v5: 5_HP-Karaoke-UVR",
            ):
                settings = build_settings(
                    settings_path=settings_path,
                    export_path="/tmp/out",
                    method="vr",
                    model="5_HP-Karaoke-UVR.pth",
                    repo=repo,
                )
        self.assertEqual(settings.get("vr_model"), "v5: 5_HP-Karaoke-UVR")


class ApplyStemsOverrideTests(unittest.TestCase):
    def test_parse_aliases(self) -> None:
        self.assertEqual(parse_cli_stems("both"), {"both"})
        self.assertEqual(parse_cli_stems("all"), {"both"})
        self.assertEqual(parse_cli_stems("vocals,instrumental"), {"vocals", "instrumental"})
        self.assertEqual(parse_cli_stems("inst"), {"instrumental"})

    def test_both_clears_exclusive_flags(self) -> None:
        settings = Settings.defaults()
        settings.set("is_primary_stem_only", True)
        settings.set("is_secondary_stem_only", True)
        settings.set("mdx_stems_selected", [VOCAL_STEM])
        label = apply_stems_override(settings, "both")
        self.assertEqual(label, "both")
        self.assertFalse(settings.get("is_primary_stem_only"))
        self.assertFalse(settings.get("is_secondary_stem_only"))
        self.assertFalse(settings.get("is_primary_stem_only_Demucs"))
        self.assertFalse(settings.get("is_secondary_stem_only_Demucs"))
        self.assertEqual(settings.get("demucs_stems"), ALL_STEMS)
        self.assertEqual(settings.get("mdx_stems"), ALL_STEMS)
        self.assertEqual(settings.get("mdx_stems_selected"), [])

    def test_instrumental_matches_gui_quick_mode(self) -> None:
        settings = Settings.defaults()
        apply_stems_override(settings, "instrumental")
        self.assertFalse(settings.get("is_primary_stem_only"))
        self.assertTrue(settings.get("is_secondary_stem_only"))
        self.assertEqual(settings.get("mdx_stems_selected"), [VOCAL_STEM])

    def test_build_settings_stems(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = os.path.join(tmp, "settings.json")
            Settings.defaults().save(settings_path)
            settings = build_settings(
                settings_path=settings_path,
                export_path="/tmp/out",
                method="mdx",
                stems="vocals",
                stable_names=True,
            )
        self.assertTrue(settings.get("is_primary_stem_only"))
        self.assertFalse(settings.get("is_secondary_stem_only"))

    def test_unknown_token_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_cli_stems("lead")


class ResolveMethodTests(unittest.TestCase):
    def test_aliases(self) -> None:
        self.assertEqual(resolve_method("mdx"), MDX_ARCH_TYPE)
        self.assertEqual(resolve_method("demucs"), DEMUCS_ARCH_TYPE)
        self.assertEqual(resolve_method("vr"), VR_ARCH_PM)

    def test_unknown(self) -> None:
        with self.assertRaises(ValueError):
            resolve_method("ensemble")


class BuildSettingsTests(unittest.TestCase):
    def test_overrides_and_stable_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = os.path.join(tmp, "settings.json")
            base = Settings.defaults()
            base.path = settings_path
            base.set("chosen_process_method", MDX_ARCH_TYPE)
            base.set("mdx_net_model", "Old Model")
            base.set("is_create_model_folder", True)
            base.set("is_testing_audio", True)
            base.save()

            repo = mock.MagicMock()
            repo.list_demucs_models.return_value = ["htdemucs"]
            with mock.patch(
                "core.model_display.map_basenames_to_display",
                return_value=["v4 | htdemucs"],
            ), mock.patch(
                "core.model_display.display_name_for_model",
                return_value="v4 | htdemucs",
            ):
                settings = build_settings(
                    settings_path=settings_path,
                    export_path="/tmp/out",
                    method="demucs",
                    model="htdemucs",
                    use_gpu=False,
                    stable_names=True,
                    repo=repo,
                )
            self.assertEqual(settings.get("chosen_process_method"), DEMUCS_ARCH_TYPE)
            self.assertEqual(settings.get("demucs_model"), "v4 | htdemucs")
            self.assertEqual(settings.get("export_path"), "/tmp/out")
            self.assertFalse(settings.get("is_gpu_conversion"))
            self.assertFalse(settings.get("is_create_model_folder"))
            self.assertFalse(settings.get("is_testing_audio"))
            self.assertFalse(settings.get("is_add_model_name"))
            # Must not persist overrides.
            reloaded = Settings.load(settings_path)
            self.assertEqual(reloaded.get("mdx_net_model"), "Old Model")

    def test_rejects_ensemble(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = os.path.join(tmp, "settings.json")
            base = Settings.defaults()
            base.path = settings_path
            base.set("chosen_process_method", ENSEMBLE_MODE)
            base.save()
            with self.assertRaises(ValueError):
                build_settings(settings_path=settings_path, export_path="/tmp/out")


class BenchMetricsTests(unittest.TestCase):
    def test_array_diff_identical(self) -> None:
        a = np.zeros((100, 2), dtype=np.float32)
        peak, rms, samples, channels = array_diff_stats(a, a.copy())
        self.assertEqual(peak, 0.0)
        self.assertEqual(rms, 0.0)
        self.assertEqual(samples, 100)
        self.assertEqual(channels, 2)

    def test_array_diff_nonzero(self) -> None:
        a = np.zeros((50, 2), dtype=np.float64)
        b = np.ones((50, 2), dtype=np.float64)
        peak, rms, *_ = array_diff_stats(a, b)
        self.assertAlmostEqual(peak, 1.0)
        self.assertAlmostEqual(rms, 1.0)

    def test_parse_and_label(self) -> None:
        self.assertEqual(parse_env_assignment("UVR_AUTOCAST=1"), ("UVR_AUTOCAST", "1"))
        self.assertIn("UVR_AUTOCAST_0", sanitize_env_label(["UVR_AUTOCAST=0"]))

    def test_compare_stem_dirs(self) -> None:
        import soundfile as sf

        with tempfile.TemporaryDirectory() as tmp:
            dir_a = os.path.join(tmp, "a")
            dir_b = os.path.join(tmp, "b")
            os.makedirs(dir_a)
            os.makedirs(dir_b)
            audio = np.zeros((32, 2), dtype=np.float32)
            sf.write(os.path.join(dir_a, "track (Vocals).wav"), audio, 44100)
            sf.write(os.path.join(dir_b, "track (Vocals).wav"), audio + 0.5, 44100)
            sf.write(os.path.join(dir_a, "only_a.wav"), audio, 44100)
            report = compare_stem_dirs(dir_a, dir_b)
            self.assertEqual(len(report.pairs), 1)
            self.assertEqual(report.only_a, ["only_a.wav"])
            self.assertGreater(report.max_rms_diff, 0.0)


class SettingsSummaryTests(unittest.TestCase):
    def test_summary_keys(self) -> None:
        settings = Settings.defaults()
        settings.set("chosen_process_method", MDX_ARCH_TYPE)
        settings.set("mdx_net_model", "Model X")
        summary = settings_summary(settings)
        self.assertEqual(summary["model"], "Model X")
        self.assertEqual(summary["model_key"], "mdx_net_model")


if __name__ == "__main__":
    unittest.main()
