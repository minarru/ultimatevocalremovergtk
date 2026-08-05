"""karaoke_model_list must not rebuild dry ModelConfigs on a warm cache hit."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from bundled.constants import ENSEMBLE_PARTITION, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.model_data import ModelConfig, ModelRepository
from core.settings import Settings


class KaraokeModelCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["UVR_DATA_DIR"] = self._tmp.name
        self.addCleanup(lambda: os.environ.pop("UVR_DATA_DIR", None))
        self.settings = Settings()
        self.repo = ModelRepository()
        self.repo.invalidate_stem_check()

    def test_second_call_reuses_cached_tags(self) -> None:
        tags = (
            f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}Fake VR",
            f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Fake MDX",
        )
        builds: list[str] = []

        def fake_tags(self) -> list[str]:
            return list(tags)

        real_init = ModelConfig.__init__

        def counting_init(self, settings, repo, model_name, **kwargs):
            builds.append(str(model_name))
            real_init(self, settings, repo, model_name, **kwargs)
            self.model_status = True
            self.is_karaoke = str(model_name).endswith("Fake VR")
            self.is_bv_model = False
            self.model_and_process_tag = str(model_name)

        with mock.patch.object(ModelRepository, "default_change_model_tags", fake_tags):
            with mock.patch.object(ModelConfig, "__init__", counting_init):
                first = self.repo.karaoke_model_list(self.settings)
                second = self.repo.karaoke_model_list(self.settings)

        self.assertEqual(first, second)
        self.assertEqual(first, [tags[0]])
        self.assertEqual(len(builds), 2, "warm hit must not construct ModelConfigs again")

    def test_invalidate_stem_check_clears_karaoke_cache(self) -> None:
        tags = (f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}Fake VR",)
        builds: list[str] = []

        def fake_tags(self) -> list[str]:
            return list(tags)

        real_init = ModelConfig.__init__

        def counting_init(self, settings, repo, model_name, **kwargs):
            builds.append(str(model_name))
            real_init(self, settings, repo, model_name, **kwargs)
            self.model_status = True
            self.is_karaoke = True
            self.is_bv_model = False
            self.model_and_process_tag = str(model_name)

        with mock.patch.object(ModelRepository, "default_change_model_tags", fake_tags):
            with mock.patch.object(ModelConfig, "__init__", counting_init):
                self.repo.karaoke_model_list(self.settings)
                self.repo.invalidate_stem_check()
                self.repo.karaoke_model_list(self.settings)

        self.assertEqual(len(builds), 2)


if __name__ == "__main__":
    unittest.main()
