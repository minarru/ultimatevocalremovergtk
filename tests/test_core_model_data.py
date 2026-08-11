import typing
import unittest
from unittest.mock import MagicMock, patch

from bundled.constants import DEFAULT, ENSEMBLE_MODE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.model_config import ModelConfig, assemble_model
from core.settings import Settings


class OverlapMdxDefaultTests(unittest.TestCase):
    def test_default_overlap_mdx_is_float(self):
        settings = Settings.from_flat({"overlap_mdx": DEFAULT})
        repo = MagicMock()
        repo.vr_hash_MAPPER = {}
        repo.model_hash_table = {}
        repo.on_unrecognized_model = None

        def fake_get_model_hash(self: typing.Any):
            self.model_hash = None
            self.model_status = False

        with patch.object(ModelConfig, "get_model_hash", fake_get_model_hash):
            model = ModelConfig(settings, repo, "missing.pth", VR_ARCH_TYPE, is_dry_check=True)
        self.assertEqual(model.overlap_mdx, 0.25)
        self.assertIsInstance(model.overlap_mdx, float)


class AssembleEnsembleTests(unittest.TestCase):
    def test_filters_invalid_members(self):
        settings = Settings.from_flat(
            {
                "selected_models": [
                    f"{VR_ARCH_TYPE}: good",
                    f"{VR_ARCH_TYPE}: bad",
                ]
            }
        )
        repo = MagicMock()
        repo.on_unrecognized_model = None

        good = MagicMock()
        good.model_status = True
        bad = MagicMock()
        bad.model_status = False

        with patch("core.model_config.config.ModelConfig", side_effect=[good, bad]):
            with self.assertRaises(ValueError):
                assemble_model(settings, repo, arch_type=ENSEMBLE_MODE)

    def test_returns_valid_members(self):
        settings = Settings.from_flat(
            {
                "selected_models": [
                    f"{VR_ARCH_TYPE}: a",
                    f"{VR_ARCH_TYPE}: b",
                ]
            }
        )
        repo = MagicMock()
        repo.on_unrecognized_model = None

        first = MagicMock()
        first.model_status = True
        second = MagicMock()
        second.model_status = True

        with patch("core.model_config.config.ModelConfig", side_effect=[first, second]):
            models = assemble_model(settings, repo, arch_type=ENSEMBLE_MODE)
        self.assertEqual(models, [first, second])


class ModelConfigKaraokeConfidenceTests(unittest.TestCase):
    """ModelConfig.is_karaoke_curated must agree with which branch of
    resolve_karaoke_confidence actually set is_karaoke."""

    def _model(self) -> typing.Any:
        from types import SimpleNamespace
        from core.model_data import _ModelConfigImplementation

        # Minimal stand-in with just the attributes check_if_karaokee_model
        # and apply_karaoke_metadata read/write.
        model = SimpleNamespace(
            model_data=None,
            is_karaoke=False,
            is_karaoke_curated=False,
            is_bv_model=False,
            bv_model_rebalance=0,
            model_name="",
            model_basename=None,
            model_path=None,
        )
        # Bind the check_if_karaokee_model method so apply_karaoke_metadata can call it
        model.check_if_karaokee_model = lambda: _ModelConfigImplementation.check_if_karaokee_model(model)  # type: ignore[arg-type]
        return model

    def test_curated_hash_metadata_sets_curated_true(self) -> None:
        from core.model_data import _ModelConfigImplementation

        model = self._model()
        model.model_data = {"is_karaoke": True}
        _ModelConfigImplementation.check_if_karaokee_model(model)
        self.assertTrue(model.is_karaoke)
        self.assertTrue(model.is_karaoke_curated)

    def test_curated_false_metadata_blocks_name_inference(self) -> None:
        from core.model_data import _ModelConfigImplementation

        model = self._model()
        model.model_data = {"is_karaoke": False}
        model.model_name = "Karaoke-labelled model"
        _ModelConfigImplementation.apply_karaoke_metadata(model)
        self.assertFalse(model.is_karaoke)
        self.assertTrue(model.is_karaoke_curated)

    def test_legacy_typo_false_metadata_blocks_name_inference(self) -> None:
        from core.model_data import _ModelConfigImplementation

        model = self._model()
        model.model_data = {"is_karaokee": False}
        model.model_name = "Karaoke-labelled model"
        _ModelConfigImplementation.apply_karaoke_metadata(model)
        self.assertFalse(model.is_karaoke)
        self.assertTrue(model.is_karaoke_curated)

    def test_guessed_from_name_sets_curated_false(self) -> None:
        from core.model_data import _ModelConfigImplementation

        model = self._model()
        model.model_name = "BandSplit Roformer | Karaoke Frazer by becruily"
        _ModelConfigImplementation.apply_karaoke_metadata(model)
        self.assertTrue(model.is_karaoke)
        self.assertFalse(model.is_karaoke_curated)

    def test_no_signal_leaves_both_false(self) -> None:
        from core.model_data import _ModelConfigImplementation

        model = self._model()
        _ModelConfigImplementation.apply_karaoke_metadata(model)
        self.assertFalse(model.is_karaoke)
        self.assertFalse(model.is_karaoke_curated)


if __name__ == "__main__":
    unittest.main()
