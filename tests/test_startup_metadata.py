"""Startup metadata must avoid redundant work without weakening invalidation."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from core import model_data
from core.model_identity import IdentityIndex, ModelIdentityService


class IdentityPublicationTests(unittest.TestCase):
    def test_build_uses_snapshot_read_after_cache_key(self):
        repo = SimpleNamespace(
            inventory_generation=0,
            catalogue_revision="old",
            naming_revision=0,
            _inventory_lock=threading.RLock(),
            catalogue=None,
        )
        service = ModelIdentityService(repo)
        old, new = object(), object()

        def snapshot():
            if repo.catalogue_revision == "old":
                # Simulate publication after the snapshot was captured.
                repo.catalogue_revision = "new"
                return old
            return new

        with (
            patch.object(service, "_snapshot", side_effect=snapshot),
            patch(
                "core.model_inventory.build_identity_index", return_value=IdentityIndex({})
            ) as build,
        ):
            self.assertIsInstance(service.index, IdentityIndex)
        build.assert_called_once_with(repo, snapshot=new)

    def test_cached_index_is_invalidated_by_each_revision(self):
        for field, value in (
            ("inventory_generation", 1),
            ("catalogue_revision", "next"),
            ("naming_revision", 1),
        ):
            with self.subTest(field=field):
                repo = SimpleNamespace(
                    inventory_generation=0,
                    catalogue_revision="published",
                    naming_revision=0,
                    _inventory_lock=threading.RLock(),
                    catalogue=None,
                )
                service = ModelIdentityService(repo)
                old, new = IdentityIndex({}), IdentityIndex({})
                with patch("core.model_inventory.build_identity_index", side_effect=[old, new]):
                    self.assertIs(service.index, old)
                    setattr(repo, field, value)
                    self.assertIs(service.index, new)
                    self.assertIs(service.index, new)

    def test_initial_publication_builds_once_and_reuses_index(self):
        repo = SimpleNamespace(
            inventory_generation=0,
            catalogue_revision="",
            naming_revision=0,
            _inventory_lock=threading.RLock(),
        )
        snapshot = object()

        def ensure(**kwargs: object):
            repo.catalogue_revision = "published"
            repo.catalogue.latest_snapshot = snapshot
            return snapshot

        repo.catalogue = SimpleNamespace(latest_snapshot=None, ensure=ensure)
        service = ModelIdentityService(repo)
        index = IdentityIndex({})
        with patch("core.model_inventory.build_identity_index", return_value=index) as build:
            self.assertIs(service.index, index)
            self.assertIs(service.index, index)
        build.assert_called_once_with(repo, snapshot=snapshot)

    def test_change_during_build_still_retries(self):
        repo = SimpleNamespace(
            inventory_generation=0,
            catalogue_revision="published",
            naming_revision=0,
            _inventory_lock=threading.RLock(),
            catalogue=None,
        )
        stale, fresh = IdentityIndex({}), IdentityIndex({})

        def build(*args: object, **kwargs: object):
            if repo.inventory_generation == 0:
                repo.inventory_generation += 1
                return stale
            return fresh

        service = ModelIdentityService(repo)
        with patch("core.model_inventory.build_identity_index", side_effect=build) as builder:
            self.assertIs(service.index, fresh)
            self.assertIs(service.index, fresh)
        self.assertEqual(builder.call_count, 2)


class StartupYamlTests(unittest.TestCase):
    def test_prefers_c_safe_loader_when_available(self):
        if not hasattr(yaml, "CSafeLoader"):
            self.skipTest("PyYAML was built without libyaml")
        with patch.object(model_data, "_MDX_C_YAML_LOADER", None):
            self.assertTrue(issubclass(model_data._mdx_c_yaml_loader(), yaml.CSafeLoader))

    def test_backends_preserve_extensions_and_safe_tag_boundary(self):
        for backend in (yaml.SafeLoader, getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
            with (
                self.subTest(backend=backend.__name__),
                patch.object(yaml, "CSafeLoader", backend, create=True),
                patch.object(model_data, "_MDX_C_YAML_LOADER", None),
            ):
                parsed = model_data.load_mdx_c_config_data(
                    b"stems: !!python/tuple [Vocals, Instrumental]\nrate: 1e-3\n"
                    b"base: &base [1, 2]\ncopy: *base\n"
                )
                self.assertEqual(parsed["stems"], ("Vocals", "Instrumental"))
                self.assertEqual(parsed["rate"], 0.001)
                self.assertEqual(parsed["base"], parsed["copy"])
                with self.assertRaises(yaml.constructor.ConstructorError):
                    model_data.load_mdx_c_config_data("bad: !!python/object/apply:builtins.list []")
                with self.assertRaises(yaml.YAMLError):
                    model_data.load_mdx_c_config_data("bad: [unfinished")

    def test_python_fallback_without_c_extension(self):
        with patch.object(model_data, "_MDX_C_YAML_LOADER", None):
            original = getattr(yaml, "CSafeLoader", None)
            if original is not None:
                del yaml.CSafeLoader
            try:
                self.assertEqual(model_data.load_mdx_c_config_data("value: 1e-3"), {"value": 0.001})
            finally:
                if original is not None:
                    yaml.CSafeLoader = original
