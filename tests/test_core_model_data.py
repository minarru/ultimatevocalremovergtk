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


def _repo_with_mdx(*basenames: str) -> MagicMock:
    repo = MagicMock()
    repo.list_vr_models.return_value = []
    repo.list_mdx_models.return_value = list(basenames)
    repo.list_demucs_models.return_value = []
    repo.mdx_name_select_MAPPER = {}
    repo.mdx_hash_MAPPER = {}
    repo.vr_hash_MAPPER = {}
    repo.model_hash_table = {}
    repo.on_unrecognized_model = None
    repo.mdx_catalogue_display_index.return_value = {}
    repo.vr_catalogue_display_index.return_value = {}
    repo.demucs_catalogue_display_index.return_value = {}
    return repo


class NestedCanonicalModelConfigTests(unittest.TestCase):
    """Canonical settings IDs must not be treated as ensemble member tags."""

    def _capture_config(self):
        from core.model_data import ModelConfig as RealConfig

        captured: dict[str, object] = {}

        def wrapper(*args: typing.Any, **kwargs: typing.Any):
            model = RealConfig(*args, **kwargs)
            captured["process_method"] = model.process_method
            captured["has_model_path"] = hasattr(model, "model_path")
            return model

        return captured, wrapper

    def test_vocal_splitter_canonical_id_does_not_crash(self) -> None:
        from core.model_data import process_determine_vocal_split_model

        settings = Settings.defaults()
        settings.process.vocal_splitter_enabled = True
        settings.process.vocal_splitter = "mdx:KaraokeFusion"
        repo = _repo_with_mdx("KaraokeFusion")
        captured, wrapper = self._capture_config()

        with patch("core.model_data.ModelConfig", side_effect=wrapper), patch(
            "core.model_display.map_basenames_to_display",
            side_effect=lambda names, *args, **kwargs: list(names),
        ), patch("core.apollo.list_apollo_models", return_value=[]):
            process_determine_vocal_split_model(settings, repo)

        self.assertEqual(captured.get("process_method"), MDX_ARCH_TYPE)
        self.assertTrue(captured.get("has_model_path"))

    def test_secondary_canonical_id_does_not_crash(self) -> None:
        from bundled.constants import VOCAL_STEM
        from core.model_data import process_determine_secondary_model

        settings = Settings.defaults()
        settings.mdx.voc_inst_secondary_model = "mdx:KaraokeFusion"
        repo = _repo_with_mdx("KaraokeFusion")
        captured, wrapper = self._capture_config()

        with patch("core.model_data.ModelConfig", side_effect=wrapper), patch(
            "core.model_display.map_basenames_to_display",
            side_effect=lambda names, *args, **kwargs: list(names),
        ), patch("core.apollo.list_apollo_models", return_value=[]):
            process_determine_secondary_model(
                settings, repo, MDX_ARCH_TYPE, VOCAL_STEM
            )

        self.assertEqual(captured.get("process_method"), MDX_ARCH_TYPE)
        self.assertTrue(captured.get("has_model_path"))


class _FocusStub:
    """Minimal stand-in carrying just what ``_apply_stem_focus`` reads."""

    def __init__(self, settings: Settings, primary: str, secondary: str) -> None:
        from bundled.constants import MDX_ARCH_TYPE

        self.settings = settings
        self.is_vocal_split_model = False
        self.primary_stem = primary
        self.secondary_stem = secondary
        self.is_karaoke = False
        self.is_bv_model = False
        self.process_method = MDX_ARCH_TYPE
        self.mdx_stem_count = 2
        self.demucs_stem_count = 0
        self.mdx_model_stems: list[str] = []
        self.mdxnet_stems_selected: list[str] = []
        self.is_mdx_include_stem_complement = False
        self.available_stem_routes: tuple[typing.Any, ...] = ()
        self.selected_stem_routes: tuple[typing.Any, ...] = ()
        self.demucs_source_list: list[str] = []
        self.is_primary_stem_only = False
        self.is_secondary_stem_only = False
        self.mdxnet_stem_select = None
        self.demucs_stems = None

    def apply(self) -> None:
        from core.model_data import _ModelConfigImplementation

        _ModelConfigImplementation._apply_stem_focus(self)  # type: ignore[arg-type]


class StemIdentityAssembleTests(unittest.TestCase):
    def test_vocal_split_model_keeps_its_native_primary_stem(self) -> None:
        """The old assemble rewrote a splitter's primary to ``lead_only``.

        Native yaml/hash spelling must survive; the lead/backing concept is
        derived instead (see tests/test_vocal_split_stems.py).
        """
        from core.model_data import _ModelConfigImplementation
        from core.stems import StemBucket, stem_concept

        stub = _FocusStub(Settings.defaults(), "vocals", "other")
        stub.is_vocal_split_model = True
        _ModelConfigImplementation._apply_stem_focus(stub)  # type: ignore[arg-type]
        self.assertEqual(stub.primary_stem, "vocals")
        self.assertEqual(stub.secondary_stem, "other")
        self.assertEqual(stem_concept(stub, "vocals"), StemBucket.LEAD_VOCALS)

    def test_applying_focus_never_writes_back_into_settings(self) -> None:
        """One Settings assembles many configs (ensemble members, secondaries,
        pre-process), and in the GUI it is the live persisted object that
        read-only callers like estimate_workload also assemble from. Writing
        resolved flags back into it leaked one model's pick onto the next and
        silently rewrote the user's saved Save-stems toggles."""
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.VOCALS.value
        before = (
            settings.process.primary_stem_only,
            settings.process.secondary_stem_only,
            settings.demucs.is_primary_stem_only,
            settings.demucs.is_secondary_stem_only,
        )

        vocals_primary = _FocusStub(settings, "vocals", "other")
        vocals_primary.apply()
        inst_primary = _FocusStub(settings, "other", "vocals")
        inst_primary.apply()

        after = (
            settings.process.primary_stem_only,
            settings.process.secondary_stem_only,
            settings.demucs.is_primary_stem_only,
            settings.demucs.is_secondary_stem_only,
        )
        self.assertEqual(before, after)
        # Each config still resolves the focus onto its own stems.
        self.assertEqual(
            (vocals_primary.is_primary_stem_only, vocals_primary.is_secondary_stem_only),
            (True, False),
        )
        self.assertEqual(
            (inst_primary.is_primary_stem_only, inst_primary.is_secondary_stem_only),
            (False, True),
        )

    def test_focus_naming_no_stem_exports_everything(self) -> None:
        settings = Settings.defaults()
        settings.process.stem_focus = "Bass"
        stub = _FocusStub(settings, "vocals", "other")
        stub.apply()
        self.assertEqual(
            (stub.is_primary_stem_only, stub.is_secondary_stem_only), (False, False)
        )

    def test_multi_stem_mdx_focus_populates_native_subset(self) -> None:
        from bundled.constants import BASS_STEM

        settings = Settings.defaults()
        settings.process.stem_focus = BASS_STEM
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.apply()
        self.assertEqual(stub.mdxnet_stems_selected, ["bass"])
        self.assertEqual(stub.mdxnet_stem_select, "bass")
        self.assertEqual(
            (stub.is_primary_stem_only, stub.is_secondary_stem_only),
            (False, False),
        )

    def test_multi_stem_mdx_include_complement_adds_derived_route(self) -> None:
        from bundled.constants import BASS_STEM

        settings = Settings.defaults()
        settings.process.stem_focus = BASS_STEM
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.is_mdx_include_stem_complement = True
        stub.apply()
        complement = next(
            route
            for route in stub.available_stem_routes
            if route.concept == "raw:no bass"
        )
        self.assertTrue(complement.conditional)
        self.assertIsNone(complement.native)

    def test_multi_stem_mdx_instrumental_focus_uses_vocal_complement(self) -> None:
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.INSTRUMENTAL.value
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.apply()
        self.assertEqual(stub.mdxnet_stems_selected, ["vocals"])
        self.assertEqual(stub.mdxnet_stem_select, "vocals")
        self.assertEqual(
            (stub.is_primary_stem_only, stub.is_secondary_stem_only),
            (False, True),
        )

    def test_demucs_native_focus_replaces_stale_primary(self) -> None:
        from bundled.constants import BASS_STEM, DEMUCS_ARCH_TYPE

        settings = Settings.defaults()
        settings.process.stem_focus = BASS_STEM
        stub = _FocusStub(settings, "Vocals", "Instrumental")
        stub.process_method = DEMUCS_ARCH_TYPE
        stub.mdx_stem_count = 0
        stub.mdx_model_stems = []
        stub.demucs_stem_count = 4
        stub.demucs_source_list = ["Bass", "Drums", "Other", "Vocals"]
        stub.apply()
        self.assertEqual(stub.demucs_stems, BASS_STEM)
        self.assertEqual(stub.primary_stem, BASS_STEM)
        self.assertEqual(
            (stub.is_primary_stem_only, stub.is_secondary_stem_only),
            (True, False),
        )


if __name__ == "__main__":
    unittest.main()
