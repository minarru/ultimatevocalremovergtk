"""Tests for MDX-C architecture dispatch helpers."""

import unittest
from typing import Any

ConfigDict: Any
try:
    from ml_collections import ConfigDict
except ImportError:
    ConfigDict = None

from engines.mdx_c import build_mdx_c_model, _mdx_c_hop_length


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
        model = build_mdx_c_model(config)
        self.assertEqual(model.__class__.__name__, "SCNet")
        self.assertEqual(_mdx_c_hop_length(config), 1024)

    def _scnet_model_dict(self) -> dict:
        return {
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
            "num_dplayer": 2,
            "expand": 1,
            "audio_channels": 2,
        }

    def _scnet_config(self, **model_overrides: object) -> Any:
        model = self._scnet_model_dict()
        model.update(model_overrides)
        return ConfigDict(
            {
                "model": model,
                "audio": {"sample_rate": 44100},
                "training": {"instruments": ["Drums", "Bass", "Other", "Vocals"]},
                "inference": {"batch_size": 1, "dim_t": 256},
            }
        )

    def test_scnet_tran_factory(self) -> None:
        # Rotary dim kept equal to dim_head (both 8): SCNetTran's rotary
        # embedding is applied per-head, so a larger rotary dim than the head
        # dim it rotates is inconsistent.
        config = self._scnet_config(
            tran_rotary_embedding_dim=8,
            tran_depth=1,
            tran_heads=2,
            tran_dim_head=8,
            tran_attn_dropout=0.0,
            tran_ff_dropout=0.0,
            tran_flash_attn=False,
        )
        model = build_mdx_c_model(config)
        self.assertEqual(model.__class__.__name__, "SCNetTran")

    def test_scnet_masked_from_hint(self) -> None:
        config = self._scnet_config()
        model = build_mdx_c_model(config, model_type_hint="scnet_masked")
        self.assertEqual(model.__class__.__name__, "SCNetMasked")

    def test_scnet_masked_from_keys(self) -> None:
        config = self._scnet_config()
        model = build_mdx_c_model(
            config,
            state_dict_keys=["pos_embed_f", "mask_layer.0.weight", "encoder.0.SDlayer.convs.0.weight"],
        )
        self.assertEqual(model.__class__.__name__, "SCNetMasked")

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
        model = build_mdx_c_model(config)
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
        model = build_mdx_c_model(config)
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

    def test_bs_roformer_ignores_training_only_yaml_keys(self) -> None:
        from ml.bs_roformer import DEFAULT_FREQS_PER_BANDS

        config = ConfigDict(
            {
                "model": {
                    "dim": 64,
                    "depth": 1,
                    "freqs_per_bands": DEFAULT_FREQS_PER_BANDS,
                    "skip_connection": False,
                    "use_torch_checkpoint": False,
                },
                "audio": {"sample_rate": 44100, "hop_length": 512},
                "training": {"instruments": ["Vocals"]},
                "inference": {"batch_size": 1, "dim_t": 256},
            }
        )
        model = build_mdx_c_model(config)
        self.assertEqual(model.__class__.__name__, "BSRoformer")

    def test_bs_roformer_without_declared_bands_still_dispatches_as_bs_roformer(
        self,
    ) -> None:
        """"BS Roformer SW" (shared-weight, multi-stem) yamls omit
        freqs_per_bands entirely and rely on BSRoformer's own
        DEFAULT_FREQS_PER_BANDS. Missing the fallback here used to fall
        through every architecture check and land on TFC_TDF_net, which
        crashes reading model.norm -- a field only MDX23C configs declare."""
        config = ConfigDict(
            {
                "model": {
                    "dim": 32,
                    "depth": 1,
                    "stereo": True,
                    "num_stems": 2,
                    "time_transformer_depth": 1,
                    "freq_transformer_depth": 1,
                    "use_shared_bias": True,
                },
                "audio": {"sample_rate": 44100, "hop_length": 512},
                "training": {"instruments": ["Vocals", "Instrumental"]},
                "inference": {"batch_size": 1, "dim_t": 256},
            }
        )
        model = build_mdx_c_model(config)
        self.assertEqual(model.__class__.__name__, "BSRoformer")

    def test_bs_roformer_use_pope_dispatches_and_builds(self) -> None:
        """``use_pope`` (community "BS PolarFormer" checkpoints) is a yaml
        key that already matches BSRoformer's own constructor arg name, so
        it flows through filter_init_kwargs without any checkpoint-key
        detection -- unlike hyperace/value_residual above."""
        from ml.bs_roformer import DEFAULT_FREQS_PER_BANDS

        config = ConfigDict(
            {
                "model": {
                    "dim": 32,
                    "depth": 1,
                    "stereo": True,
                    "num_stems": 1,
                    "time_transformer_depth": 1,
                    "freq_transformer_depth": 1,
                    "freqs_per_bands": DEFAULT_FREQS_PER_BANDS,
                    "use_pope": True,
                },
                "audio": {"sample_rate": 44100, "hop_length": 512},
                "training": {"instruments": ["Vocals", "Instrumental"]},
                "inference": {"batch_size": 1, "dim_t": 256},
            }
        )
        model = build_mdx_c_model(config)
        self.assertEqual(model.__class__.__name__, "BSRoformer")
        state_dict_keys = model.state_dict().keys()
        self.assertTrue(any(k.endswith("pope_embed.bias") for k in state_dict_keys))
        self.assertFalse(any("rotary_embed" in k for k in state_dict_keys))

    def test_bs_roformer_use_pope_shares_one_embedding_per_axis(self) -> None:
        """The real checkpoints this ports (e.g. bs_pope_vocals_zfturbo) carry
        identical pope_embed weights at every layer for a given axis (time or
        freq) and different weights between axes -- i.e. one shared PoPE
        module per axis, not one per layer. Verified by loading a real
        checkpoint's state dict; this test locks in the same sharing via
        object identity so a future refactor can't silently instantiate a
        fresh PoPE per layer instead of reusing the module."""
        from ml.bs_roformer import BSRoformer, DEFAULT_FREQS_PER_BANDS

        model = BSRoformer(
            dim=32,
            depth=3,
            stereo=True,
            num_stems=1,
            time_transformer_depth=1,
            freq_transformer_depth=1,
            freqs_per_bands=DEFAULT_FREQS_PER_BANDS,
            use_pope=True,
        )
        pope_embed_ids = {
            name: id(module)
            for name, module in model.named_modules()
            if name.endswith("pope_embed")
        }
        time_pope_embeds = {v for k, v in pope_embed_ids.items() if ".0.layers.0.0." in k}
        freq_pope_embeds = {v for k, v in pope_embed_ids.items() if ".1.layers.0.0." in k}
        self.assertEqual(len(time_pope_embeds), 1)
        self.assertEqual(len(freq_pope_embeds), 1)
        self.assertNotEqual(time_pope_embeds, freq_pope_embeds)

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

    def test_melband_accepts_integer_dropout_from_yaml(self) -> None:
        # Shipped Roformer yamls write ``attn_dropout: 0`` / ``ff_dropout: 0``,
        # which yaml parses as int, not float.
        config = ConfigDict(
            {
                "model": {
                    "dim": 64,
                    "depth": 1,
                    "num_bands": 60,
                    "dim_head": 32,
                    "heads": 4,
                    "attn_dropout": 0,
                    "ff_dropout": 0,
                    "multi_stft_resolution_loss_weight": 1,
                },
                "audio": {"hop_length": 441},
                "training": {"instruments": ["Vocals"], "target_instrument": "Vocals"},
                "inference": {"batch_size": 1, "dim_t": 256},
            }
        )
        model = build_mdx_c_model(config)
        self.assertEqual(model.__class__.__name__, "MelBandRoformer")

    def test_bs_roformer_accepts_integer_dropout_from_yaml(self) -> None:
        from ml.bs_roformer import DEFAULT_FREQS_PER_BANDS

        config = ConfigDict(
            {
                "model": {
                    "dim": 64,
                    "depth": 1,
                    "freqs_per_bands": DEFAULT_FREQS_PER_BANDS,
                    "dim_head": 32,
                    "heads": 4,
                    "attn_dropout": 0,
                    "ff_dropout": 0,
                    "multi_stft_resolution_loss_weight": 1,
                },
                "audio": {"sample_rate": 44100, "hop_length": 512},
                "training": {"instruments": ["Vocals"]},
                "inference": {"batch_size": 1, "dim_t": 256},
            }
        )
        model = build_mdx_c_model(config)
        self.assertEqual(model.__class__.__name__, "BSRoformer")

    def test_melband_hop_length_prefers_stft_hop_length(self) -> None:
        config = ConfigDict(
            {
                "model": {
                    "num_bands": 60,
                    "stft_hop_length": 441,
                },
                "audio": {"hop_length": 411},
                "inference": {"dim_t": 1101},
            }
        )
        self.assertEqual(_mdx_c_hop_length(config), 441)
        self.assertEqual(_mdx_c_hop_length(config) * (config.inference.dim_t - 1), 485100)

    def test_melband_inference_build_matches_input_length(self) -> None:
        import torch

        config = ConfigDict(
            {
                "model": {
                    "dim": 64,
                    "depth": 1,
                    "stereo": True,
                    "num_stems": 1,
                    "num_bands": 60,
                    "dim_head": 32,
                    "heads": 4,
                    "stft_n_fft": 2048,
                    "stft_hop_length": 441,
                    "stft_win_length": 2048,
                    "sample_rate": 44100,
                },
                "audio": {"hop_length": 411},
                "training": {"instruments": ["Vocals"], "target_instrument": "Vocals"},
                "inference": {"batch_size": 1, "dim_t": 1101},
            }
        )
        model = build_mdx_c_model(config)
        self.assertTrue(model.match_input_audio_length)
        length = _mdx_c_hop_length(config) * (config.inference.dim_t - 1)
        audio = torch.randn(1, 2, length)
        with torch.inference_mode():
            output = model(audio)
        self.assertEqual(output.shape[-1], length)


if __name__ == "__main__":
    unittest.main()
