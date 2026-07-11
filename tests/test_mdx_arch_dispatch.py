"""Tests for MDX-C architecture dispatch helpers."""

import unittest

try:
    from ml_collections import ConfigDict
except ImportError:
    ConfigDict = None

from engines.mdx import _build_mdx_c_model, _mdx_c_hop_length


@unittest.skipIf(ConfigDict is None, "ml_collections not installed")
class MdxArchDispatchTests(unittest.TestCase):
    def test_scnet_factory(self) -> None:
        config = ConfigDict(
            {
                "model": {
                    "sources": ["drums", "bass", "other", "vocals"],
                    "hop_size": 1024,
                    "nfft": 4096,
                    "win_size": 4096,
                    "normalized": True,
                    "dims": [4, 32, 64, 128],
                    "band_SR": [0.175, 0.392, 0.433],
                    "band_stride": [1, 4, 16],
                    "band_kernel": [3, 4, 16],
                    "conv_depths": [3, 2, 1],
                    "compress": 4,
                    "conv_kernel": 3,
                    "num_dplayer": 6,
                    "expand": 1,
                    "audio_channels": 2,
                },
                "audio": {"sample_rate": 44100},
                "training": {"instruments": ["Drums", "Bass", "Other", "Vocals"]},
                "inference": {"batch_size": 2, "dim_t": 256},
            }
        )
        model = _build_mdx_c_model(config)
        self.assertEqual(model.__class__.__name__, "SCNet")
        self.assertEqual(_mdx_c_hop_length(config), 1024)

    def test_bandit_v2_factory(self) -> None:
        config = ConfigDict(
            {
                "cls": "Bandit",
                "kwargs": {
                    "in_channels": 1,
                    "stems": ["speech", "music", "sfx"],
                    "band_type": "musical",
                    "n_bands": 64,
                    "hop_length": 512,
                    "n_fft": 2048,
                },
                "audio": {"sample_rate": 48000},
                "training": {"instruments": ["Speech", "Music", "Sfx"]},
                "inference": {"batch_size": 2, "dim_t": 256},
            }
        )
        model = _build_mdx_c_model(config)
        self.assertEqual(model.__class__.__name__, "Bandit")
        self.assertEqual(_mdx_c_hop_length(config), 512)

    def test_bandit_plus_factory(self) -> None:
        config = ConfigDict(
            {
                "model": {
                    "in_channel": 1,
                    "stems": ["speech", "music", "effects"],
                    "band_specs": "musical",
                    "n_bands": 64,
                    "fs": 44100,
                    "hop_length": 512,
                    "n_fft": 2048,
                },
                "audio": {"sample_rate": 44100},
                "training": {"instruments": ["Speech", "Music", "Effects"]},
                "inference": {"batch_size": 1, "dim_t": 256},
            }
        )
        model = _build_mdx_c_model(config)
        self.assertEqual(model.__class__.__name__, "MultiMaskMultiSourceBandSplitRNNSimple")

    def test_bs_roformer_accepts_mlp_expansion_factor(self) -> None:
        from ml.bs_roformer import BSRoformer, DEFAULT_FREQS_PER_BANDS

        model = BSRoformer(
            dim=256,
            depth=1,
            freqs_per_bands=DEFAULT_FREQS_PER_BANDS,
            mlp_expansion_factor=4,
        )
        self.assertEqual(model.__class__.__name__, "BSRoformer")

    def test_bs_roformer_preserves_input_length(self) -> None:
        import torch

        from ml.bs_roformer import BSRoformer, DEFAULT_FREQS_PER_BANDS

        model = BSRoformer(
            dim=64,
            depth=1,
            stereo=True,
            freqs_per_bands=DEFAULT_FREQS_PER_BANDS,
            stft_hop_length=512,
        )
        model.eval()
        length = 882000
        audio = torch.randn(1, 2, length)
        with torch.inference_mode():
            output = model(audio)
        self.assertEqual(output.shape[-1], length)


if __name__ == "__main__":
    unittest.main()
