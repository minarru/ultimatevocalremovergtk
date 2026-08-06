"""Unit tests for CUDA OOM segment-size backoff helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.oom_segment import (
    backoff_candidates,
    default_segment,
    effective_segment,
    snap_segment_down,
    supports_segment_backoff,
    yaml_dim_t,
)


class SnapSegmentTests(unittest.TestCase):
    def test_snaps_down_to_step_32(self) -> None:
        self.assertEqual(snap_segment_down(2208), 2208)
        self.assertEqual(snap_segment_down(1105), 1088)
        self.assertEqual(snap_segment_down(33), 32)
        self.assertEqual(snap_segment_down(1), 32)


class BackoffCandidatesTests(unittest.TestCase):
    def test_larger_of_half_and_default_first(self) -> None:
        # half(2208)=1104 snaps down to 1088; default=256 → try 1088 then 256
        self.assertEqual(backoff_candidates(2208, 256), [1088, 256])

    def test_default_larger_than_half_comes_first(self) -> None:
        # half(512)=256, default=384 → 384 then 256
        self.assertEqual(backoff_candidates(512, 384), [384, 256])

    def test_dedupes_when_half_equals_default(self) -> None:
        self.assertEqual(backoff_candidates(512, 256), [256])

    def test_empty_when_already_at_floor(self) -> None:
        self.assertEqual(backoff_candidates(32, 32), [])
        self.assertEqual(backoff_candidates(32, 256), [])

    def test_half_still_offered_when_at_default(self) -> None:
        self.assertEqual(backoff_candidates(256, 256), [128])

    def test_ignores_default_not_below_current(self) -> None:
        self.assertEqual(backoff_candidates(256, 512), [128])


class ModelSegmentTests(unittest.TestCase):
    def test_yaml_dim_t_and_defaults(self) -> None:
        model = SimpleNamespace(
            is_mdx_c_seg_def=True,
            mdx_segment_size=2208,
            mdx_c_configs=SimpleNamespace(inference=SimpleNamespace(dim_t=256)),
        )
        self.assertEqual(yaml_dim_t(model), 256)
        self.assertEqual(default_segment(model), 256)
        self.assertEqual(effective_segment(model), 256)

    def test_effective_uses_explicit_segment(self) -> None:
        model = SimpleNamespace(
            is_mdx_c_seg_def=False,
            mdx_segment_size=2208,
            mdx_c_configs=SimpleNamespace(inference=SimpleNamespace(dim_t=256)),
        )
        self.assertEqual(effective_segment(model), 2208)

    def test_supports_segment_backoff(self) -> None:
        self.assertTrue(supports_segment_backoff(SimpleNamespace(is_mdx_c=True)))
        self.assertTrue(supports_segment_backoff(SimpleNamespace(is_roformer=True)))
        self.assertTrue(
            supports_segment_backoff(SimpleNamespace(process_method="MDX-Net"))
        )
        self.assertFalse(supports_segment_backoff(SimpleNamespace(process_method="VR Architecture")))
        self.assertFalse(supports_segment_backoff(None))


if __name__ == "__main__":
    unittest.main()
