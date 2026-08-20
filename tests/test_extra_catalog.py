"""Tests for the fork-curated catalogue additions and Apollo download wiring."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from bundled.constants import (
    APOLLO_ARCH_TYPE,
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    NO_NEW_MODELS,
    VR_ARCH_TYPE,
)
from core import extra_catalog, paths
from core.downloads import DownloadManager


class ExtraCatalogFileTests(unittest.TestCase):
    def setUp(self) -> None:
        extra_catalog.clear_extra_catalog_cache()

    def tearDown(self) -> None:
        extra_catalog.clear_extra_catalog_cache()

    def test_bundled_file_parses_and_drops_comment_block(self) -> None:
        data = extra_catalog.load_extra_models()
        self.assertTrue(data)
        self.assertNotIn("_comment", data)

    def test_every_entry_has_absolute_urls(self) -> None:
        data = extra_catalog.load_extra_models()
        for list_name, entries in data.items():
            for label, files in entries.items():
                self.assertIsInstance(files, dict, f"{list_name}/{label}")
                self.assertTrue(files, f"{list_name}/{label} is empty")
                for filename, url in files.items():
                    self.assertTrue(
                        str(url).startswith("https://"),
                        f"{list_name}/{label}/{filename} is not an absolute https URL",
                    )

    def test_mdx_family_entries_pair_checkpoint_with_config(self) -> None:
        data = extra_catalog.load_extra_models()
        for key in ("scnet_download_list", "roformer_download_list"):
            for label, files in data.get(key, {}).items():
                yamls = [n for n in files if n.endswith(".yaml")]
                ckpts = [n for n in files if not n.endswith(".yaml")]
                self.assertEqual(len(yamls), 1, f"{label} needs exactly one config")
                self.assertEqual(len(ckpts), 1, f"{label} needs exactly one checkpoint")

    def test_checkpoint_filenames_are_unique_across_lists(self) -> None:
        """Two entries writing the same filename would collide on disk."""
        data = extra_catalog.load_extra_models()
        seen: dict[str, str] = {}
        for key in ("scnet_download_list", "roformer_download_list"):
            for label, files in data.get(key, {}).items():
                for name in files:
                    if name.endswith(".yaml"):
                        continue
                    self.assertNotIn(name, seen, f"{name} duplicated: {seen.get(name)} / {label}")
                    seen[name] = label

    def test_configs_differing_upstream_get_distinct_local_names(self) -> None:
        """HyperACE v2 inst/voc differ (target_instrument), so must not share a name."""
        roformer = extra_catalog.load_extra_models().get("roformer_download_list", {})
        configs = {}
        for _label, files in roformer.items():
            for name, url in files.items():
                if name.endswith(".yaml"):
                    configs.setdefault(name, set()).add(url)
        for name, urls in configs.items():
            self.assertEqual(len(urls), 1, f"{name} maps to more than one upstream config")

    def test_disable_env_var_yields_empty_catalogue(self) -> None:
        with mock.patch.dict(os.environ, {"UVR_DISABLE_EXTRA_MODELS": "1"}):
            extra_catalog.clear_extra_catalog_cache()
            self.assertEqual(extra_catalog.load_extra_models(), {})


class ExtraCatalogMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        extra_catalog.clear_extra_catalog_cache()

    def test_upstream_labels_are_never_overwritten(self) -> None:
        extra = {"scnet_download_list": {"Shared Label": {"mine.ckpt": "https://x/mine.ckpt"}}}
        mdx = {"Shared Label": {"upstream.ckpt": "https://up/upstream.ckpt"}}
        _vr, merged, _demucs = extra_catalog.merge_extra_catalogues({}, mdx, {}, extra=extra)
        self.assertEqual(merged["Shared Label"], {"upstream.ckpt": "https://up/upstream.ckpt"})

    def test_new_labels_are_added(self) -> None:
        extra = {"roformer_download_list": {"New One": {"n.ckpt": "https://x/n.ckpt"}}}
        _vr, merged, _demucs = extra_catalog.merge_extra_catalogues({}, {}, {}, extra=extra)
        self.assertIn("New One", merged)

    def test_apollo_list_is_separate_from_mdx(self) -> None:
        extra = {"apollo_download_list": {"A": {"a.ckpt": "https://x/a.ckpt"}}}
        _vr, merged, _demucs = extra_catalog.merge_extra_catalogues({}, {}, {}, extra=extra)
        self.assertNotIn("A", merged)
        self.assertIn("A", extra_catalog.apollo_download_list(extra=extra))


class ApolloDownloadWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        extra_catalog.clear_extra_catalog_cache()
        from core.catalog_sources import invalidate_catalogue_merge

        invalidate_catalogue_merge()
        self.manager = DownloadManager()
        # Curated extras are bundled locally. Keep both remote catalogues
        # offline: ``merged_catalogues`` still loads mvsepless unless told not to.
        self.manager._merge_politrees_supplement(allow_network=False)

    def test_apollo_catalogue_is_populated_without_network(self) -> None:
        self.assertTrue(self.manager.apollo_download_list)

    def test_resolve_routes_checkpoint_and_config_to_apollo_dirs(self) -> None:
        label = next(iter(self.manager.apollo_download_list))
        jobs = self.manager.resolve(label, APOLLO_ARCH_TYPE)
        self.assertEqual(len(jobs), 2)
        dests = [path for _url, path in jobs]
        ckpts = [p for p in dests if p.endswith((".ckpt", ".bin"))]
        yamls = [p for p in dests if p.endswith(".yaml")]
        self.assertEqual(len(ckpts), 1)
        self.assertEqual(len(yamls), 1)
        self.assertEqual(os.path.dirname(ckpts[0]), paths.APOLLO_MODELS_DIR)
        self.assertEqual(os.path.dirname(yamls[0]), paths.APOLLO_CONFIG_PATH)

    def test_resolve_rejects_unknown_selection(self) -> None:
        self.assertEqual(self.manager.resolve("nope", APOLLO_ARCH_TYPE), [])
        self.assertEqual(self.manager.resolve(NO_NEW_MODELS, APOLLO_ARCH_TYPE), [])

    def test_available_downloads_includes_apollo_bucket(self) -> None:
        available = self.manager.available_downloads()
        self.assertIn(APOLLO_ARCH_TYPE, available)

    def test_model_directory_maps_apollo(self) -> None:
        self.assertEqual(
            self.manager.model_directory(APOLLO_ARCH_TYPE), paths.APOLLO_MODELS_DIR
        )
        # Existing arch types must keep their directories.
        self.assertEqual(self.manager.model_directory(VR_ARCH_TYPE), paths.VR_MODELS_DIR)
        self.assertEqual(self.manager.model_directory(MDX_ARCH_TYPE), paths.MDX_MODELS_DIR)
        self.assertEqual(
            self.manager.model_directory(DEMUCS_ARCH_TYPE), paths.DEMUCS_MODELS_DIR
        )

    def test_curated_separation_entries_resolve_through_mdx_path(self) -> None:
        expected = {
            "SCnet: 4-stems Huge SCNet v1.2 by Aname",
            "Roformer Model: BandSplit Roformer | HyperACE v2 Vocals by Unwa",
        }
        for label in expected:
            self.assertIn(label, self.manager.mdx_download_list)
            jobs = self.manager.resolve(label, MDX_ARCH_TYPE)
            dests = [p for _u, p in jobs]
            self.assertTrue(any(p.startswith(paths.MDX_MODELS_DIR) for p in dests))
            self.assertTrue(any(p.startswith(paths.MDX_C_CONFIG_PATH) for p in dests))


class ApolloRegistryTests(unittest.TestCase):
    def test_registers_hash_json_pointing_at_downloaded_config(self) -> None:
        from core import apollo, apollo_registry

        with tempfile.TemporaryDirectory() as tmp:
            models_dir = os.path.join(tmp, "Apollo_Models")
            config_dir = os.path.join(models_dir, "model_configs")
            hash_dir = os.path.join(models_dir, "model_data")
            os.makedirs(config_dir)
            os.makedirs(hash_dir)

            ckpt = os.path.join(models_dir, "some_apollo.ckpt")
            with open(ckpt, "wb") as handle:
                handle.write(b"apollo-weights")
            yaml_path = os.path.join(config_dir, "some_apollo.yaml")
            with open(yaml_path, "w", encoding="utf-8") as handle:
                handle.write("model:\n  sr: 44100\n")

            jobs = [("https://x/some_apollo.ckpt", ckpt), ("https://x/some_apollo.yaml", yaml_path)]

            with mock.patch.object(paths, "APOLLO_MODELS_DIR", models_dir), mock.patch.object(
                paths, "APOLLO_CONFIG_PATH", config_dir
            ), mock.patch.object(paths, "APOLLO_HASH_DIR", hash_dir):
                self.assertTrue(apollo_registry.register_apollo_from_download_jobs(jobs))
                digest = apollo.checkpoint_md5(ckpt)
                written = os.path.join(hash_dir, f"{digest}.json")
                self.assertTrue(os.path.isfile(written))
                with open(written, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle), {"config_yaml": "some_apollo.yaml"})

    def test_config_yaml_is_not_mistaken_for_a_checkpoint(self) -> None:
        """APOLLO_CONFIG_PATH nests inside APOLLO_MODELS_DIR, so the pairing
        helper must exclude configs from the checkpoint side."""
        from core import apollo_registry

        with tempfile.TemporaryDirectory() as tmp:
            models_dir = os.path.join(tmp, "Apollo_Models")
            config_dir = os.path.join(models_dir, "model_configs")
            os.makedirs(config_dir)
            yaml_path = os.path.join(config_dir, "only_config.yaml")
            with open(yaml_path, "w", encoding="utf-8") as handle:
                handle.write("model: {}\n")

            jobs = [("https://x/only_config.yaml", yaml_path)]
            with mock.patch.object(paths, "APOLLO_MODELS_DIR", models_dir), mock.patch.object(
                paths, "APOLLO_CONFIG_PATH", config_dir
            ):
                self.assertEqual(apollo_registry.pair_apollo_jobs(jobs), [])

    def test_registered_model_is_recognised_without_prompting(self) -> None:
        """End-to-end: a downloaded pair must resolve through ApolloModelData
        with no ``on_unrecognized`` callback, and yield the four build params.

        The yaml body mirrors the real upstream Apollo configs (params live
        under a top-level ``model:`` key alongside hydra ``_target_`` noise).
        """
        from core import apollo, apollo_registry

        config_body = (
            "exp:\n  dir: ./exps\n"
            "model:\n"
            "  _target_: look2hear.models.apollo.Apollo\n"
            "  sr: 44100\n"
            "  win: 20\n"
            "  feature_dim: 256\n"
            "  layer: 6\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            models_dir = os.path.join(tmp, "Apollo_Models")
            config_dir = os.path.join(models_dir, "model_configs")
            hash_dir = os.path.join(models_dir, "model_data")
            os.makedirs(config_dir)
            os.makedirs(hash_dir)

            ckpt = os.path.join(models_dir, "apollo_big.ckpt")
            with open(ckpt, "wb") as handle:
                handle.write(b"weights" * 512)
            yaml_path = os.path.join(config_dir, "apollo_big.yaml")
            with open(yaml_path, "w", encoding="utf-8") as handle:
                handle.write(config_body)

            jobs = [("https://x/apollo_big.ckpt", ckpt), ("https://x/apollo_big.yaml", yaml_path)]

            with mock.patch.object(paths, "APOLLO_MODELS_DIR", models_dir), mock.patch.object(
                paths, "APOLLO_CONFIG_PATH", config_dir
            ), mock.patch.object(paths, "APOLLO_HASH_DIR", hash_dir):
                apollo_registry.register_apollo_from_download_jobs(jobs)

                self.assertEqual(apollo.list_apollo_models(), ["apollo_big.ckpt"])
                data = apollo.ApolloModelData("apollo_big.ckpt")
                self.assertTrue(data.is_model_status)
                self.assertEqual(
                    data.extracted_params,
                    {"sr": 44100, "win": 20, "feature_dim": 256, "layer": 6},
                )

    def test_checkpoint_md5_matches_apollo_model_data(self) -> None:
        """The registry digest and ApolloModelData's must agree exactly."""
        import hashlib

        from core import apollo

        with tempfile.TemporaryDirectory() as tmp:
            ckpt = os.path.join(tmp, "m.ckpt")
            payload = b"x" * 4096
            with open(ckpt, "wb") as handle:
                handle.write(payload)
            # Small file: the tail seek fails, so the whole file is hashed.
            self.assertEqual(apollo.checkpoint_md5(ckpt), hashlib.md5(payload).hexdigest())


if __name__ == "__main__":
    unittest.main()
