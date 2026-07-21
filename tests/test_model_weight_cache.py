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

    def test_mdx_pitch_reference_sr(self) -> None:
        from engines.mdx import _mdx_pitch_reference_sr

        self.assertEqual(_mdx_pitch_reference_sr(), 44100)

    def test_put_get_roundtrip(self) -> None:
        cache = ModelWeightCache(max_entries=4)
        key = ("vr", ("/x", 0, 0), "cpu", ())
        module = mock.MagicMock()
        cache.put(key, module=module)
        module.cpu.assert_called()
        hit = cache.get(key)
        self.assertIsNotNone(hit)
        self.assertIs(hit.module, module)

    def test_put_keeps_accelerator_resident(self) -> None:
        cache = ModelWeightCache(max_entries=4)
        key = ("vr", ("/x", 0, 0), "cuda:0", ())
        module = mock.MagicMock()
        cache.put(key, module=module)
        module.cpu.assert_not_called()
        self.assertEqual(cache._device_resident_key, key)

    def test_put_parks_previous_accelerator_resident(self) -> None:
        cache = ModelWeightCache(max_entries=4)
        a = mock.MagicMock(name="a")
        b = mock.MagicMock(name="b")
        key_a = ("vr", ("/a", 0, 0), "cuda:0", ())
        key_b = ("vr", ("/b", 0, 0), "cuda:0", ())
        cache.put(key_a, module=a)
        a.cpu.assert_not_called()
        cache.put(key_b, module=b)
        a.cpu.assert_called()
        b.cpu.assert_not_called()
        self.assertEqual(cache._device_resident_key, key_b)

    def test_materialize_and_park(self) -> None:
        from engines.model_weight_cache import materialize_module, park_module

        module = mock.MagicMock()
        module.to.return_value = module
        out = materialize_module(module, "cuda:0")
        self.assertIs(out, module)
        module.to.assert_called_with("cuda:0")
        module.eval.assert_called()
        park_module(module)
        module.cpu.assert_called()

    def test_stash_keeps_accelerator_module_resident(self) -> None:
        cache = get_weight_cache()
        key = weight_cache_key("vr", "/tmp/model.pth", "cuda:0", 1)
        module = mock.MagicMock(name="net")
        separator = mock.MagicMock()
        separator._weight_cache_key = key
        separator.model_run = module
        separator._ort_session = None
        separator._inference_model = None
        separator.demucs = None
        self.assertTrue(cache.stash_separator(separator))
        module.cpu.assert_not_called()
        self.assertEqual(cache._device_resident_key, key)

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

    def test_default_max_entries_is_four(self) -> None:
        cache = ModelWeightCache()
        self.assertEqual(cache.max_entries, 4)

    def test_release_inference_memory_keeps_weight_cache(self) -> None:
        from core.inference_cleanup import release_inference_memory

        cache = get_weight_cache()
        key = ("vr", ("/keep", 0, 0), "cpu", ())
        module = mock.MagicMock(name="keep")
        cache.put(key, module=module)
        release_inference_memory(None, clear_weight_cache=False)
        self.assertIsNotNone(cache.get(key))
        release_inference_memory(None, clear_weight_cache=True)
        self.assertIsNone(cache.get(key))

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
