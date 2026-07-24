"""Tests for classic MDX hop batching helpers and ORT batch probing."""

from __future__ import annotations

import unittest
from unittest import mock

from engines.mdx_classic_batch import (
    mdx_batch_ranges,
    mdx_hop_starts,
    resolve_mdx_effective_batch,
)


class MdxClassicBatchHelpersTests(unittest.TestCase):
    def test_hop_starts(self) -> None:
        self.assertEqual(mdx_hop_starts(10, 4), [0, 4, 8])
        self.assertEqual(mdx_hop_starts(0, 4), [])
        self.assertEqual(mdx_hop_starts(10, 0), [])

    def test_batch_ranges_groups_hops(self) -> None:
        self.assertEqual(mdx_batch_ranges(5, 2), [(0, 2), (2, 4), (4, 5)])
        self.assertEqual(mdx_batch_ranges(3, 8), [(0, 3)])
        self.assertEqual(mdx_batch_ranges(0, 4), [])
        self.assertEqual(mdx_batch_ranges(4, 0), [(0, 1), (1, 2), (2, 3), (3, 4)])

    def test_effective_batch_dynamic_uses_requested(self) -> None:
        self.assertEqual(resolve_mdx_effective_batch(4, None), 4)
        self.assertEqual(resolve_mdx_effective_batch(0, None), 1)

    def test_effective_batch_fixed_one_forces_one(self) -> None:
        self.assertEqual(resolve_mdx_effective_batch(8, 1), 1)

    def test_effective_batch_fixed_caps_requested(self) -> None:
        self.assertEqual(resolve_mdx_effective_batch(8, 4), 4)
        self.assertEqual(resolve_mdx_effective_batch(2, 4), 2)


class OrtFixedBatchSizeTests(unittest.TestCase):
    def test_fixed_one(self) -> None:
        from engines.amp_runtime import ort_fixed_batch_size

        session = mock.MagicMock()
        session.get_inputs.return_value = [mock.MagicMock(shape=[1, 4, 3072, 256])]
        self.assertEqual(ort_fixed_batch_size(session), 1)

    def test_dynamic_none_dim(self) -> None:
        from engines.amp_runtime import ort_fixed_batch_size

        session = mock.MagicMock()
        session.get_inputs.return_value = [mock.MagicMock(shape=[None, 4, 3072, 256])]
        self.assertIsNone(ort_fixed_batch_size(session))

    def test_dynamic_symbolic_name(self) -> None:
        from engines.amp_runtime import ort_fixed_batch_size

        session = mock.MagicMock()
        session.get_inputs.return_value = [mock.MagicMock(shape=["batch", 4, 3072, 256])]
        self.assertIsNone(ort_fixed_batch_size(session))

    def test_resolve_with_ort_session_fixed_one(self) -> None:
        from engines.amp_runtime import ort_fixed_batch_size

        session = mock.MagicMock()
        session.get_inputs.return_value = [mock.MagicMock(shape=[1, 4, 8, 8])]
        fixed = ort_fixed_batch_size(session)
        self.assertEqual(resolve_mdx_effective_batch(4, fixed), 1)


if __name__ == "__main__":
    unittest.main()
