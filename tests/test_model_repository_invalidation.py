"""One entry point for "the models on disk changed".

Before this there were four spellings of it across `core/` and `ui/`, each
clearing a different subset, and one of them (`update_model_settings`) was
provably incomplete.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any
from unittest import mock

from bundled.constants import ENSEMBLE_PARTITION, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core import model_display
from core.model_config import ModelConfig
from core.model_repository import ModelRepository
from core.settings import Settings
from tests.model_config_fixtures import model_config_shell


class InvalidateModelsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["UVR_DATA_DIR"] = self._tmp.name
        self.addCleanup(lambda: os.environ.pop("UVR_DATA_DIR", None))
        self.settings = Settings()
        self.repo = ModelRepository()

    def test_clears_every_derived_cache(self) -> None:
        self.repo._stem_check_cache = ((("tag",), str(self.settings.mdx.stems)), [])
        self.repo._karaoke_cache = (("tag",), ["tag"])
        self.repo.model_hash_table["/some/model.ckpt"] = "abc123"
        generation_before = model_display._display_generation
        inventory_before = self.repo.inventory_generation
        naming_before = self.repo.naming_revision

        self.repo.invalidate_models()

        self.assertIsNone(self.repo._stem_check_cache)
        self.assertIsNone(self.repo._karaoke_cache)
        self.assertEqual(self.repo.model_hash_table, {})
        self.assertEqual(model_display._display_generation, generation_before)
        self.assertGreater(self.repo.inventory_generation, inventory_before)
        self.assertGreater(self.repo.naming_revision, naming_before)

    def test_reloads_the_mappers(self) -> None:
        """`invalidate_stem_check` alone leaves the mappers stale on disk."""
        self.repo.mdx_hash_MAPPER = {"stale": {}}
        with mock.patch.object(ModelRepository, "reload_mappers") as reload_mappers:
            self.repo.invalidate_models()
        reload_mappers.assert_called_once_with()

    def test_clearing_the_hash_table_does_not_rehash_an_unchanged_file(self) -> None:
        """The persistent stat-guarded table refills the in-memory one.

        Clearing therefore costs an os.stat per checkpoint, not an md5 -- which
        is what makes it safe to fold into the common invalidation path.
        """
        from core import model_hash_cache as mhc

        path = os.path.join(self._tmp.name, "model.ckpt")
        with open(path, "wb") as handle:
            handle.write(b"payload")
        mhc.remember(self.settings.process.model_hash_table, path, "KNOWN")

        self.repo.invalidate_models()

        cfg = model_config_shell()
        cfg.settings = self.settings
        cfg.repo = self.repo
        cfg.model_path = path
        cfg.model_status = True
        cfg.model_hash = None
        cfg.is_dry_check = True

        with mock.patch(
            "core.model_config.config.compute_checkpoint_hash",
            side_effect=AssertionError("invalidate_models must not force a re-hash"),
        ):
            cfg.get_model_hash()

        self.assertEqual(cfg.model_hash, "KNOWN")


class StemCheckKeyTests(unittest.TestCase):
    """The dry-check cache key must track the one setting that reaches a filter."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["UVR_DATA_DIR"] = self._tmp.name
        self.addCleanup(lambda: os.environ.pop("UVR_DATA_DIR", None))
        self.settings = Settings()
        self.repo = ModelRepository()
        self.repo.invalidate_stem_check()

    def _counting_stem_check(self, builds: list[str]) -> Any:
        real_init = ModelConfig.__init__

        def counting_init(
            cfg: ModelConfig,
            settings: Settings,
            repo: ModelRepository,
            model_name: str,
            **kwargs: Any,
        ) -> None:
            builds.append(str(model_name))
            real_init(cfg, settings, repo, model_name, **kwargs)
            cfg.model_status = True
            cfg.model_and_process_tag = str(model_name)

        return counting_init

    def test_rebuilds_when_the_mdx_stem_selection_changes(self) -> None:
        tags = (f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Fake MDX",)
        builds: list[str] = []

        def fake_tags(_self: ModelRepository) -> list[str]:
            return list(tags)

        with mock.patch.object(ModelRepository, "all_model_tags", fake_tags):
            with mock.patch.object(
                ModelConfig, "__init__", self._counting_stem_check(builds)
            ):
                self.repo.stem_check(self.settings)
                self.settings.mdx.stems = "Vocals"
                self.repo.stem_check(self.settings)

        self.assertEqual(
            len(builds), 2, "mdx.stems feeds a dry-check filter; it must bust the cache"
        )

    def test_warm_hit_on_an_unchanged_selection(self) -> None:
        tags = (f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}Fake VR",)
        builds: list[str] = []

        def fake_tags(_self: ModelRepository) -> list[str]:
            return list(tags)

        with mock.patch.object(ModelRepository, "all_model_tags", fake_tags):
            with mock.patch.object(
                ModelConfig, "__init__", self._counting_stem_check(builds)
            ):
                self.repo.stem_check(self.settings)
                self.repo.stem_check(self.settings)

        self.assertEqual(len(builds), 1, "unchanged settings must stay a warm hit")


if __name__ == "__main__":
    unittest.main()
