"""The typed-settings accessors and OOM matcher must import without GTK/torch."""

import subprocess
import sys
import unittest

from core.oom_markers import is_oom_message
from core.settings import Settings
from core.settings.access import get_flat, get_path, set_flat, set_path


class SettingsAccessTests(unittest.TestCase):
    def test_set_path_coerces_value(self) -> None:
        settings = Settings()
        set_path(settings, "mdx.segment_size", "512")
        self.assertEqual(settings.mdx.segment_size, 512)

    def test_get_path_returns_default_for_missing(self) -> None:
        settings = Settings()
        self.assertEqual(get_path(settings, "mdx.nope", "fallback"), "fallback")

    def test_flat_bridge_round_trips(self) -> None:
        settings = Settings()
        set_flat(settings, "is_gpu_conversion", True)
        self.assertTrue(settings.process.use_gpu)
        self.assertTrue(get_flat(settings, "is_gpu_conversion"))

    def test_set_flat_ignores_unmapped_key(self) -> None:
        settings = Settings()
        before = settings.process.use_gpu
        set_flat(settings, "not_a_real_key", 1)  # documented no-op
        self.assertEqual(settings.process.use_gpu, before)

    def test_ui_bridge_still_exports_the_same_objects(self) -> None:
        import ui.settings_bind as bridge

        self.assertIs(bridge.set_flat, set_flat)
        self.assertIs(bridge.get_path, get_path)


class ImportWeightTests(unittest.TestCase):
    def test_helpers_import_without_torch(self) -> None:
        code = (
            "import sys;"
            "import core.oom_markers, core.settings.access;"
            "print('torch' in sys.modules)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        self.assertEqual(out.stdout.strip(), "False")


class OomMarkerTests(unittest.TestCase):
    def test_matches_cuda_message(self) -> None:
        self.assertTrue(is_oom_message("CUDA out of memory. Tried to allocate 2 GiB"))

    def test_matches_ort_message(self) -> None:
        self.assertTrue(is_oom_message("Failed to allocate memory for requested buffer"))

    def test_rejects_unrelated_message(self) -> None:
        self.assertFalse(is_oom_message("shape mismatch in layer 3"))

    def test_engines_module_still_re_exports(self) -> None:
        from engines.mdx_classic_batch import is_oom_message as engines_matcher

        self.assertIs(engines_matcher, is_oom_message)


if __name__ == "__main__":
    unittest.main()
