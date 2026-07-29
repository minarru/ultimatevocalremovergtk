import unittest

from core.model_config import ModelConfig


class ApplyKaraokeMetadataTests(unittest.TestCase):
    def test_mdx_c_hash_karaoke_flag(self):
        model = ModelConfig.__new__(ModelConfig)
        model.model_data = {"is_karaoke": True, "config_yaml": "config_mel_band_roformer_karaoke.yaml"}
        model.model_name = "MelBand Roformer | Karaoke by Gabox"
        model.model_basename = "mel_band_roformer_karaoke_gabox"
        model.is_karaoke = False
        model.is_bv_model = False
        model.bv_model_rebalance = None
        model.apply_karaoke_metadata("config_mel_band_roformer_karaoke.yaml")
        self.assertTrue(model.is_karaoke)

    def test_mdx_c_name_hint_without_hash_flag(self):
        model = ModelConfig.__new__(ModelConfig)
        model.model_data = {"config_yaml": "config_BandSplit-Roformer_Karaoke_Frazer_by-becruily.yaml"}
        model.model_name = "BandSplit Roformer | Karaoke Frazer by becruily"
        model.model_basename = "model_BandSplit-Roformer_Karaoke_Frazer_by-becruily"
        model.is_karaoke = False
        model.is_bv_model = False
        model.bv_model_rebalance = None
        model.apply_karaoke_metadata(
            "config_BandSplit-Roformer_Karaoke_Frazer_by-becruily.yaml"
        )
        self.assertTrue(model.is_karaoke)

    def test_non_karaoke_vocal_roformer_stays_false(self):
        model = ModelConfig.__new__(ModelConfig)
        model.model_data = {"config_yaml": "model_bs_roformer_ep_317_sdr_12.9755.yaml"}
        model.model_name = "Roformer Model: BS-Roformer-Viperx-1297"
        model.model_basename = "model_bs_roformer_ep_317_sdr_12.9755"
        model.is_karaoke = False
        model.is_bv_model = False
        model.bv_model_rebalance = None
        model.apply_karaoke_metadata("model_bs_roformer_ep_317_sdr_12.9755.yaml")
        self.assertFalse(model.is_karaoke)

    def test_works_before_model_basename_is_assigned(self):
        model = ModelConfig.__new__(ModelConfig)
        model.model_data = {"config_yaml": "config_BandSplit-Roformer_Karaoke_Frazer_by-becruily.yaml"}
        model.model_name = "BandSplit Roformer | Karaoke Frazer by becruily"
        model.model_path = "/models/MDX_Net_Models/model_BandSplit-Roformer_Karaoke_Frazer_by-becruily.ckpt"
        model.is_karaoke = False
        model.is_bv_model = False
        model.bv_model_rebalance = None
        model.apply_karaoke_metadata(
            "config_BandSplit-Roformer_Karaoke_Frazer_by-becruily.yaml"
        )
        self.assertTrue(model.is_karaoke)


if __name__ == "__main__":
    unittest.main()
