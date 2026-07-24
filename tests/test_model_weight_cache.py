"""Tests for process-scoped model weight LRU cache."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from engines.model_weight_cache import (
    ModelWeightCache,
    ensure_weight_cache_vram_headroom,
    get_weight_cache,
    model_file_identity,
    vram_headroom_is_low,
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

    def test_model_file_identity_stable(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pth", delete=False) as handle:
            handle.write(b"weights")
            path = handle.name
        try:
            first = model_file_identity(path)
            second = model_file_identity(path)
            self.assertIsNotNone(first)
            self.assertEqual(first, second)
            key = weight_cache_key("vr", path, "cuda:0")
            self.assertEqual(key[1], first)
        finally:
            os.remove(path)

    def test_model_file_identity_empty(self) -> None:
        self.assertIsNone(model_file_identity(""))

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

    def test_park_all_moves_accelerator_module_to_cpu(self) -> None:
        cache = ModelWeightCache()
        key = ("mdx", ("/m", 0, 0), "cuda:0", ())
        module = mock.MagicMock(name="big")
        cache.put(key, module=module)
        self.assertEqual(cache._device_resident_key, key)
        cache.park_all()
        module.cpu.assert_called()
        self.assertIsNone(cache._device_resident_key)
        self.assertIsNotNone(cache.get(key))

    def test_park_except_protects_identity(self) -> None:
        cache = ModelWeightCache()
        keep_id = ("/keep", 1, 1)
        drop_id = ("/drop", 2, 2)
        keep = mock.MagicMock(name="keep")
        drop = mock.MagicMock(name="drop")
        cache.put(("mdx", keep_id, "cuda:0", ()), module=keep)
        cache.put(("mdx", drop_id, "cuda:0", ()), module=drop)
        keep.cpu.reset_mock()
        drop.cpu.reset_mock()
        touched = cache.park_except({keep_id})
        self.assertEqual(touched, 1)
        keep.cpu.assert_not_called()
        drop.cpu.assert_called()
        self.assertIsNotNone(cache.get(("mdx", keep_id, "cuda:0", ())))
        self.assertIsNotNone(cache.get(("mdx", drop_id, "cuda:0", ())))

    def test_clear_except_removes_unprotected(self) -> None:
        cache = ModelWeightCache()
        keep_id = ("/keep", 1, 1)
        drop_id = ("/drop", 2, 2)
        cache.put(("mdx", keep_id, "cuda:0", ()), module=mock.MagicMock())
        cache.put(("mdx", drop_id, "cuda:0", ()), module=mock.MagicMock())
        removed = cache.clear_except({keep_id})
        self.assertEqual(removed, 1)
        self.assertIsNotNone(cache.get(("mdx", keep_id, "cuda:0", ())))
        self.assertIsNone(cache.get(("mdx", drop_id, "cuda:0", ())))

    def test_release_inference_memory_park_weights(self) -> None:
        from core.inference_cleanup import release_inference_memory

        cache = get_weight_cache()
        key = ("mdx", ("/park", 0, 0), "cuda:0", ())
        module = mock.MagicMock(name="parked")
        cache.put(key, module=module)
        module.cpu.reset_mock()
        release_inference_memory(None, park_weights=True)
        module.cpu.assert_called()
        self.assertIsNotNone(cache.get(key))

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

    def test_vram_headroom_thresholds(self) -> None:
        gib = 1024**3
        self.assertTrue(vram_headroom_is_low(1 * gib, 16 * gib))
        self.assertFalse(vram_headroom_is_low(4 * gib, 16 * gib))
        # 10% free on a large card is still "low" by ratio even if > 2 GiB.
        self.assertTrue(vram_headroom_is_low(3 * gib, 32 * gib))

    def test_ensure_vram_headroom_noop_when_plenty_free(self) -> None:
        gib = 1024**3
        with mock.patch(
            "engines.model_weight_cache.cuda_mem_info",
            return_value=(8 * gib, 16 * gib),
        ):
            self.assertEqual(ensure_weight_cache_vram_headroom("cuda:0"), "")

    def test_ensure_parks_other_when_protect_set(self) -> None:
        cache = get_weight_cache()
        keep_id = ("/keep", 1, 1)
        drop_id = ("/drop", 2, 2)
        keep = mock.MagicMock(name="keep")
        drop = mock.MagicMock(name="drop")
        cache.put(("mdx", keep_id, "cuda:0", ()), module=keep)
        cache.put(("mdx", drop_id, "cuda:0", ()), module=drop)
        keep.cpu.reset_mock()
        drop.cpu.reset_mock()
        gib = 1024**3
        with mock.patch(
            "engines.model_weight_cache.cuda_mem_info",
            side_effect=[(1 * gib, 16 * gib), (4 * gib, 16 * gib)],
        ), mock.patch("engines.model_weight_cache._flush_cuda_allocator"):
            action = ensure_weight_cache_vram_headroom(
                "cuda:0", protect_identities={keep_id}
            )
        self.assertEqual(action, "parked_other")
        keep.cpu.assert_not_called()
        drop.cpu.assert_called()
        self.assertIsNotNone(cache.get(("mdx", keep_id, "cuda:0", ())))
        self.assertIsNotNone(cache.get(("mdx", drop_id, "cuda:0", ())))

    def test_ensure_clears_other_when_still_low_after_park(self) -> None:
        cache = get_weight_cache()
        keep_id = ("/keep", 1, 1)
        drop_id = ("/drop", 2, 2)
        cache.put(("mdx", keep_id, "cuda:0", ()), module=mock.MagicMock(name="keep"))
        cache.put(("mdx", drop_id, "cuda:0", ()), module=mock.MagicMock(name="drop"))
        gib = 1024**3
        with mock.patch(
            "engines.model_weight_cache.cuda_mem_info",
            side_effect=[(1 * gib, 16 * gib), (1 * gib, 16 * gib), (4 * gib, 16 * gib)],
        ), mock.patch("engines.model_weight_cache._flush_cuda_allocator"):
            action = ensure_weight_cache_vram_headroom(
                "cuda:0", protect_identities={keep_id}
            )
        self.assertEqual(action, "cleared_other")
        self.assertIsNotNone(cache.get(("mdx", keep_id, "cuda:0", ())))
        self.assertIsNone(cache.get(("mdx", drop_id, "cuda:0", ())))

    def test_ensure_escalates_to_cleared_all(self) -> None:
        cache = get_weight_cache()
        keep_id = ("/keep", 1, 1)
        cache.put(("mdx", keep_id, "cuda:0", ()), module=mock.MagicMock())
        gib = 1024**3
        low = (1 * gib, 16 * gib)
        with mock.patch(
            "engines.model_weight_cache.cuda_mem_info",
            side_effect=[low, low, low, low, low],
        ), mock.patch("engines.model_weight_cache._flush_cuda_allocator"):
            action = ensure_weight_cache_vram_headroom(
                "cuda:0", protect_identities={keep_id}
            )
        self.assertEqual(action, "cleared_all")
        self.assertIsNone(cache.get(("mdx", keep_id, "cuda:0", ())))

    def test_ensure_no_protect_falls_back_to_parked_all(self) -> None:
        cache = get_weight_cache()
        key = ("mdx", ("/a", 0, 0), "cuda:0", ())
        module = mock.MagicMock()
        cache.put(key, module=module)
        gib = 1024**3
        with mock.patch(
            "engines.model_weight_cache.cuda_mem_info",
            side_effect=[(1 * gib, 16 * gib), (4 * gib, 16 * gib)],
        ), mock.patch("engines.model_weight_cache._flush_cuda_allocator"):
            action = ensure_weight_cache_vram_headroom("cuda:0")
        self.assertEqual(action, "parked_all")
        module.cpu.assert_called()
        self.assertIsNotNone(cache.get(key))

    def test_collect_run_model_paths_includes_secondary(self) -> None:
        from core.job_runner import collect_run_model_paths

        primary = mock.MagicMock()
        primary.model_path = "/models/primary.pth"
        primary.secondary_model = mock.MagicMock()
        primary.secondary_model.model_path = "/models/secondary.pth"
        primary.pre_proc_model = mock.MagicMock()
        primary.pre_proc_model.model_path = "/models/pre.pth"
        primary.secondary_model_4_stem = []
        # Nested secondaries should not recurse infinitely: secondary has no children
        primary.secondary_model.secondary_model = None
        primary.secondary_model.pre_proc_model = None
        primary.secondary_model.secondary_model_4_stem = []
        primary.pre_proc_model.secondary_model = None
        primary.pre_proc_model.pre_proc_model = None
        primary.pre_proc_model.secondary_model_4_stem = []

        found = collect_run_model_paths([primary])
        self.assertEqual(
            found,
            {"/models/primary.pth", "/models/secondary.pth", "/models/pre.pth"},
        )


if __name__ == "__main__":
    unittest.main()
