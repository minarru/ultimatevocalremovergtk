"""Tests for process-scoped model weight LRU cache."""

import unittest
from unittest import mock

from engines.model_weight_cache import (
    ModelWeightCache,
    get_weight_cache,
    weight_cache_key,
)


class WeightCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        get_weight_cache().clear()

    def tearDown(self) -> None:
        get_weight_cache().clear()

    def test_key_includes_kind_and_device(self) -> None:
        key = weight_cache_key("vr", "/tmp/missing.pth", "cpu", 123)
        self.assertEqual(key[0], "vr")
        self.assertEqual(key[2], "cpu")

    def test_put_get_roundtrip(self) -> None:
        cache = ModelWeightCache(max_entries=2)
        key = ("vr", ("/x", 0, 0), "cpu", ())
        module = mock.MagicMock()
        cache.put(key, module=module)
        hit = cache.get(key)
        self.assertIsNotNone(hit)
        self.assertIs(hit.module, module)

    def test_lru_evicts_oldest(self) -> None:
        cache = ModelWeightCache(max_entries=2)
        a = mock.MagicMock(name="a")
        b = mock.MagicMock(name="b")
        c = mock.MagicMock(name="c")
        cache.put(("a", 1), module=a)
        cache.put(("b", 2), module=b)
        cache.put(("c", 3), module=c)
        self.assertIsNone(cache.get(("a", 1)))
        self.assertIsNotNone(cache.get(("b", 2)))
        self.assertIsNotNone(cache.get(("c", 3)))
        a.cpu.assert_called()

    def test_stash_separator_preserves_module(self) -> None:
        cache = get_weight_cache()
        key = weight_cache_key("vr", "/tmp/model.pth", "cpu", 1)
        module = mock.MagicMock(name="net")
        separator = mock.MagicMock()
        separator._weight_cache_key = key
        separator.model_run = module
        separator._ort_session = None
        separator._inference_model = None
        separator.demucs = None
        self.assertTrue(cache.stash_separator(separator))
        self.assertIsNone(separator.model_run)
        hit = cache.get(key)
        self.assertIsNotNone(hit)
        self.assertIs(hit.module, module)


if __name__ == "__main__":
    unittest.main()
