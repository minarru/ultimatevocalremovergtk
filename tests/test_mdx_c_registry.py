"""Tests for MDX-C catalogue auto-registration."""
import typing

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core import paths
from core.mdx_c_registry import (
    build_checkpoint_display_index,
    build_checkpoint_yaml_index,
    compute_checkpoint_hash,
    display_name_for_basename,
    load_mdx_catalog_index,
    pair_checkpoint_yaml_jobs,
    params_from_config_yaml,
    register_mdx_c_checkpoint,
    register_mdx_c_from_download_jobs,
    register_mdx_display_name,
    resolve_mdx_model_basename,
    sanitize_catalogue_label,
    try_register_from_catalog,
    yaml_for_checkpoint,
)
from core.model_config import ModelConfig


class SanitizeCatalogueLabelTests(unittest.TestCase):
    def test_strips_roformer_prefix(self) -> None:
        label = "Roformer Model: BandSplit Roformer | Karaoke Frazer by becruily"
        self.assertEqual(
            sanitize_catalogue_label(label),
            "BandSplit Roformer | Karaoke Frazer by becruily",
        )

    def test_strips_trailing_ckpt_suffix(self) -> None:
        self.assertEqual(
            sanitize_catalogue_label("MelBand Total by Gonza.ckpt"),
            "MelBand Total by Gonza",
        )


class BuildCheckpointDisplayIndexTests(unittest.TestCase):
    def test_maps_selectable_label_to_checkpoint(self) -> None:
        catalogues = [
            {
                "Roformer Model: Test Model": {
                    "test_model.ckpt": "https://example.com/test_model.ckpt",
                }
            }
        ]
        index = build_checkpoint_display_index(catalogues)
        self.assertEqual(index["test_model"], "Test Model")


class DisplayNameResolutionTests(unittest.TestCase):
    def test_display_name_prefers_catalogue(self) -> None:
        mapper = {"known.ckpt": "Known Display"}
        self.assertEqual(
            display_name_for_basename("known", mapper, catalogue_index={"known": "Catalogue"}),
            "Catalogue",
        )

    def test_display_name_falls_back_to_mapper(self) -> None:
        mapper = {"known.ckpt": "Known Display"}
        self.assertEqual(
            display_name_for_basename("known", mapper, catalogue_index={}),
            "Known Display",
        )

    def test_resolve_basename_from_catalogue_display(self) -> None:
        catalogue = {"internal_model": "Friendly Label"}
        self.assertEqual(
            resolve_mdx_model_basename("Friendly Label", {}, catalogue_index=catalogue),
            "internal_model",
        )


class BuildCheckpointYamlIndexTests(unittest.TestCase):
    def test_politrees_shape(self) -> None:
        catalogues = [
            {
                "Roformer": {
                    "community.ckpt": "https://example.com/community.ckpt",
                    "community.yaml": "https://example.com/community.yaml",
                }
            }
        ]
        index = build_checkpoint_yaml_index(catalogues)
        self.assertEqual(index["community.ckpt"], "community.yaml")

    def test_trvlvr_shape(self) -> None:
        catalogues = [
            {
                "MDX23C": {
                    "model.ckpt": "model.yaml",
                }
            }
        ]
        index = build_checkpoint_yaml_index(catalogues)
        self.assertEqual(index["model.ckpt"], "model.yaml")


class ParamsFromConfigYamlTests(unittest.TestCase):
    def test_scnet_yaml(self) -> None:
        params = params_from_config_yaml("config_musdb18_scnet.yaml")
        self.assertIsNotNone(params)
        assert params is not None
        self.assertEqual(params["config_yaml"], "config_musdb18_scnet.yaml")
        self.assertTrue(params["is_roformer"])
        self.assertEqual(params["model_type"], "SCNet")


class RegisterMdxDisplayNameTests(unittest.TestCase):
    def test_writes_mapper_entry_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            models_dir = os.path.join(tmp, "models")
            mapper_path = os.path.join(tmp, "model_data", "model_name_mapper.json")
            os.makedirs(models_dir)
            checkpoint = os.path.join(models_dir, "catalog_model.ckpt")
            with open(checkpoint, "wb") as handle:
                handle.write(b"catalogue display name test")

            original_models_dir = paths.MDX_MODELS_DIR
            original_mapper = paths.MDX_MODEL_NAME_SELECT
            try:
                paths.MDX_MODELS_DIR = models_dir
                paths.MDX_MODEL_NAME_SELECT = mapper_path
                from core.name_mapper import load_name_mapper, local_overlay_path

                self.assertTrue(register_mdx_display_name(checkpoint, "Friendly Name"))
                # Locally-registered names go to the overlay, never the mirror.
                self.assertFalse(os.path.exists(mapper_path))
                with open(local_overlay_path(mapper_path), "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                self.assertEqual(payload["catalog_model.ckpt"], "Friendly Name")
                self.assertEqual(
                    load_name_mapper(mapper_path)["catalog_model.ckpt"], "Friendly Name"
                )
                self.assertFalse(register_mdx_display_name(checkpoint, "Other Name"))
            finally:
                paths.MDX_MODELS_DIR = original_models_dir
                paths.MDX_MODEL_NAME_SELECT = original_mapper


class RegisterMdxCCheckpointTests(unittest.TestCase):
    def test_writes_hash_json_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hash_dir = os.path.join(tmp, "model_data")
            config_dir = os.path.join(hash_dir, "mdx_c_configs")
            os.makedirs(config_dir)
            checkpoint = os.path.join(tmp, "models", "test_model.ckpt")
            os.makedirs(os.path.dirname(checkpoint))
            with open(checkpoint, "wb") as handle:
                handle.write(b"test checkpoint bytes for hashing")

            yaml_name = "config_musdb18_scnet.yaml"
            shutil.copyfile(
                os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name), os.path.join(config_dir, yaml_name)
            )

            original_hash_dir = paths.MDX_HASH_DIR
            original_config_dir = paths.MDX_C_CONFIG_PATH
            try:
                paths.MDX_HASH_DIR = hash_dir
                paths.MDX_C_CONFIG_PATH = config_dir
                first = register_mdx_c_checkpoint(checkpoint, yaml_name)
                self.assertIsNotNone(first)
                model_hash = compute_checkpoint_hash(checkpoint)
                assert model_hash is not None
                json_path = os.path.join(hash_dir, f"{model_hash}.json")
                self.assertTrue(os.path.isfile(json_path))

                with open(json_path, "w", encoding="utf-8") as handle:
                    json.dump({"config_yaml": yaml_name, "is_roformer": False}, handle)

                second = register_mdx_c_checkpoint(checkpoint, yaml_name)
                self.assertIsNotNone(second)
                assert second is not None
                self.assertFalse(second["is_roformer"])
            finally:
                paths.MDX_HASH_DIR = original_hash_dir
                paths.MDX_C_CONFIG_PATH = original_config_dir

    def test_metadata_write_gate_returns_params_without_writing(self) -> None:
        """Planning under a no-write policy resolves params but leaves no JSON."""
        from core.access_policy import access_policy

        with tempfile.TemporaryDirectory() as tmp:
            hash_dir = os.path.join(tmp, "model_data")
            config_dir = os.path.join(hash_dir, "mdx_c_configs")
            os.makedirs(config_dir)
            checkpoint = os.path.join(tmp, "models", "test_model.ckpt")
            os.makedirs(os.path.dirname(checkpoint))
            with open(checkpoint, "wb") as handle:
                handle.write(b"test checkpoint bytes for hashing")

            yaml_name = "config_musdb18_scnet.yaml"
            shutil.copyfile(
                os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name),
                os.path.join(config_dir, yaml_name),
            )

            original_hash_dir = paths.MDX_HASH_DIR
            original_config_dir = paths.MDX_C_CONFIG_PATH
            try:
                paths.MDX_HASH_DIR = hash_dir
                paths.MDX_C_CONFIG_PATH = config_dir
                with access_policy(
                    allow_network=False, allow_metadata_writes=False
                ):
                    params = register_mdx_c_checkpoint(checkpoint, yaml_name)
                self.assertIsNotNone(params)
                model_hash = compute_checkpoint_hash(checkpoint)
                assert model_hash is not None
                self.assertFalse(
                    os.path.exists(os.path.join(hash_dir, f"{model_hash}.json"))
                )
            finally:
                paths.MDX_HASH_DIR = original_hash_dir
                paths.MDX_C_CONFIG_PATH = original_config_dir


class TryRegisterFromCatalogTests(unittest.TestCase):
    def test_resolves_from_custom_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hash_dir = os.path.join(tmp, "model_data")
            config_dir = os.path.join(hash_dir, "mdx_c_configs")
            os.makedirs(config_dir)
            checkpoint = os.path.join(tmp, "models", "catalog_model.ckpt")
            os.makedirs(os.path.dirname(checkpoint))
            with open(checkpoint, "wb") as handle:
                handle.write(b"catalog model checkpoint")

            yaml_name = "config_musdb18_scnet.yaml"
            shutil.copyfile(
                os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name), os.path.join(config_dir, yaml_name)
            )

            original_hash_dir = paths.MDX_HASH_DIR
            original_config_dir = paths.MDX_C_CONFIG_PATH
            try:
                paths.MDX_HASH_DIR = hash_dir
                paths.MDX_C_CONFIG_PATH = config_dir
                index = {"catalog_model.ckpt": yaml_name}
                params = try_register_from_catalog(checkpoint, index=index)
                self.assertIsNotNone(params)
                assert params is not None
                self.assertEqual(params["config_yaml"], yaml_name)
            finally:
                paths.MDX_HASH_DIR = original_hash_dir
                paths.MDX_C_CONFIG_PATH = original_config_dir


class PairCheckpointYamlJobsTests(unittest.TestCase):
    def test_pairs_ckpt_and_yaml_jobs(self) -> None:
        jobs = [
            ("https://example.com/model.ckpt", os.path.join(paths.MDX_MODELS_DIR, "model.ckpt")),
            (
                "https://example.com/model.yaml",
                os.path.join(paths.MDX_C_CONFIG_PATH, "model.yaml"),
            ),
        ]
        with patch("core.mdx_c_registry.os.path.isfile", return_value=True):
            pairs = pair_checkpoint_yaml_jobs(jobs)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][1], "model.yaml")


class RegisterFromDownloadJobsTests(unittest.TestCase):
    def test_registers_existing_download_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hash_dir = os.path.join(tmp, "model_data")
            config_dir = os.path.join(hash_dir, "mdx_c_configs")
            models_dir = os.path.join(tmp, "models")
            os.makedirs(config_dir)
            os.makedirs(models_dir)

            checkpoint = os.path.join(models_dir, "batch_model.ckpt")
            yaml_name = "config_musdb18_scnet.yaml"
            with open(checkpoint, "wb") as handle:
                handle.write(b"batch download checkpoint")
            shutil.copyfile(
                os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name), os.path.join(config_dir, yaml_name)
            )

            jobs = [
                ("https://example.com/batch_model.ckpt", checkpoint),
                ("https://example.com/model.yaml", os.path.join(config_dir, yaml_name)),
            ]

            original_hash_dir = paths.MDX_HASH_DIR
            original_config_dir = paths.MDX_C_CONFIG_PATH
            original_models_dir = paths.MDX_MODELS_DIR
            try:
                paths.MDX_HASH_DIR = hash_dir
                paths.MDX_C_CONFIG_PATH = config_dir
                paths.MDX_MODELS_DIR = models_dir
                self.assertTrue(register_mdx_c_from_download_jobs(jobs))
                model_hash = compute_checkpoint_hash(checkpoint)
                assert model_hash is not None
                self.assertTrue(os.path.isfile(os.path.join(hash_dir, f"{model_hash}.json")))
            finally:
                paths.MDX_HASH_DIR = original_hash_dir
                paths.MDX_C_CONFIG_PATH = original_config_dir
                paths.MDX_MODELS_DIR = original_models_dir


class ModelDataCatalogFallbackTests(unittest.TestCase):
    def test_get_model_data_uses_catalog_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hash_dir = os.path.join(tmp, "model_data")
            config_dir = os.path.join(hash_dir, "mdx_c_configs")
            models_dir = os.path.join(tmp, "models")
            os.makedirs(config_dir)
            os.makedirs(models_dir)

            checkpoint = os.path.join(models_dir, "fallback_model.ckpt")
            yaml_name = "config_musdb18_scnet.yaml"
            with open(checkpoint, "wb") as handle:
                handle.write(b"fallback catalogue checkpoint")
            shutil.copyfile(
                os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name), os.path.join(config_dir, yaml_name)
            )

            model_data = ModelConfig.__new__(ModelConfig)
            model_data.model_hash = compute_checkpoint_hash(checkpoint)
            model_data.process_method = "MDX-Net"
            model_data.is_mdx_ckpt = True
            model_data.model_path = checkpoint
            model_data.is_dry_check = True
            model_data.repo = None

            with patch("core.model_config.config.try_register_from_catalog") as mock_try:
                mock_try.return_value = {
                    "config_yaml": yaml_name,
                    "is_roformer": True,
                    "model_type": "SCNet",
                }
                result = model_data.get_model_data(hash_dir, {})
                mock_try.assert_called_once()
                assert isinstance(result, dict)
                self.assertEqual(result["config_yaml"], yaml_name)


class LoadMdxCatalogIndexTests(unittest.TestCase):
    def test_yaml_for_checkpoint_uses_index(self) -> None:
        index = {"known.ckpt": "known.yaml"}
        self.assertEqual(yaml_for_checkpoint("known.ckpt", index=index), "known.yaml")
        self.assertIsNone(yaml_for_checkpoint("missing.ckpt", index=index))

    @patch("core.mdx_c_registry._load_manual_download_cache")
    def test_load_index_from_manual_cache(self, mock_cache: typing.Any) -> None:
        mock_cache.return_value = {
            "roformer_download_list": {
                "Test": {
                    "sample.ckpt": "https://example.com/sample.ckpt",
                    "sample.yaml": "https://example.com/sample.yaml",
                }
            }
        }
        with patch(
            "core.catalog_sources._supplemental_sources", return_value=({}, {}, {}, {})
        ), patch("core.politrees_catalog.load_politrees_links", return_value=None):
            index = load_mdx_catalog_index()
        self.assertEqual(index["sample.ckpt"], "sample.yaml")

    def test_fallback_index_includes_extras_via_merge(self) -> None:
        extras = {
            "Extras Model": {
                "extra.ckpt": "https://ex/extra.ckpt",
                "extra.yaml": "https://ex/extra.yaml",
            }
        }
        with patch(
            "core.mdx_c_registry._load_manual_download_cache", return_value={}
        ), patch(
            "core.catalog_sources._supplemental_sources",
            return_value=({}, extras, {}, {}),
        ), patch("core.politrees_catalog.load_politrees_links", return_value=None):
            index = load_mdx_catalog_index()
        self.assertEqual(index["extra.ckpt"], "extra.yaml")


if __name__ == "__main__":
    unittest.main()
