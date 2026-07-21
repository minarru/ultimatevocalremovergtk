"""Tests for prepare_mix decode / layout helpers."""

import unittest
from unittest import mock

import numpy as np

from engines.mix import _as_channel_first, prepare_mix


class PrepareMixTests(unittest.TestCase):
    def test_channel_first_passthrough(self) -> None:
        mix = np.zeros((2, 100), dtype=np.float32)
        out = prepare_mix(mix)
        self.assertEqual(out.shape, (2, 100))
        np.testing.assert_array_equal(out, mix)

    def test_channel_last_transposed(self) -> None:
        mix = np.zeros((100, 2), dtype=np.float32)
        out = prepare_mix(mix)
        self.assertEqual(out.shape, (2, 100))

    def test_mono_duplicated(self) -> None:
        mix = np.linspace(-0.5, 0.5, 50, dtype=np.float32)
        out = prepare_mix(mix)
        self.assertEqual(out.shape, (2, 50))
        np.testing.assert_allclose(out[0], mix)
        np.testing.assert_allclose(out[1], mix)

    def test_as_channel_first_rejects_bad_shape(self) -> None:
        with self.assertRaises(ValueError):
            _as_channel_first(np.zeros((3, 3), dtype=np.float32))

    def test_path_decode_cached_reuse(self) -> None:
        decoded = np.zeros((2, 8), dtype=np.float32)
        with mock.patch("engines.mix.librosa.load", return_value=(decoded, 44100)) as load:
            first = prepare_mix("/tmp/fake.wav")
            second = prepare_mix(first)
        load.assert_called_once()
        np.testing.assert_array_equal(second, first)
        self.assertEqual(second.shape, (2, 8))


if __name__ == "__main__":
    unittest.main()
