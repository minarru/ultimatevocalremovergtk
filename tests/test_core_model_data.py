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


class AssembleMdxIdentityTests(unittest.TestCase):
    def test_legacy_member_tag_becomes_engine_name(self) -> None:
        """Non-ensemble assemble still feeds the engine basename, not a member tag."""
        from core.model_identity import ModelIdentityService, ModelRecord, canonical_member_tag

        record = ModelRecord(
            "mdx:UVR-MDX-NET-Inst_HQ_4",
            "mdx",
            "UVR-MDX-NET-Inst_HQ_4",
            "UVR-MDX-NET Inst HQ 4",
            engine_name="UVR-MDX-NET-Inst_HQ_4",
        )
        tag = canonical_member_tag(record)
        captured: list[str] = []

        def fake_config(
            _settings: object, _repo: object, model_name: str, *_args: object, **_kwargs: object
        ) -> MagicMock:
            captured.append(model_name)
            model = MagicMock()
            model.model_status = True
            return model

        settings = Settings.defaults()
        with patch.object(ModelIdentityService, "records", return_value=(record,)):
            with patch("core.model_config.config.ModelConfig", side_effect=fake_config):
                assemble_model(settings, MagicMock(), tag, MDX_ARCH_TYPE)
        self.assertEqual(captured, [record.engine_name])
        self.assertNotIn(":", captured[0])

    def test_ensemble_assemble_passes_canonical_ids(self) -> None:
        from core.model_identity import ModelIdentityService, ModelRecord

        records = (
            ModelRecord("mdx:a", "mdx", "a", "A", engine_name="a"),
            ModelRecord("mdx:b", "mdx", "b", "B", engine_name="b"),
        )
        settings = Settings.defaults()
        settings.ensemble.selected_models = ["mdx:a", "mdx:b"]
        captured: list[str] = []

        def fake_config(
            _settings: object, _repo: object, model_name: str, *_args: object, **_kwargs: object
        ) -> MagicMock:
            captured.append(model_name)
            model = MagicMock()
            model.model_status = True
            return model

        with patch.object(ModelIdentityService, "records", return_value=records):
            with patch("core.model_config.config.ModelConfig", side_effect=fake_config):
                assemble_model(settings, MagicMock(), arch_type=ENSEMBLE_MODE)
        self.assertEqual(captured, ["mdx:a", "mdx:b"])


class EnsembleModeIdentityTests(unittest.TestCase):
    def _build(self, token: str, *, records: tuple[object, ...] = ()) -> ModelConfig:
        from core.model_identity import ModelIdentityService

        settings = Settings.defaults()
        repo = MagicMock()
        repo.mdx_name_select_MAPPER = {}
        repo.mdx_hash_MAPPER = {}
        repo.vr_hash_MAPPER = {}
        repo.model_hash_table = {}
        repo.on_unrecognized_model = None
        repo.mdx_catalogue_display_index.return_value = {}
        repo.vr_catalogue_display_index.return_value = {}

        def fake_get_model_hash(self: typing.Any) -> None:
            self.model_hash = None
            self.model_status = False

        with patch.object(ModelIdentityService, "records", return_value=records):
            with patch.object(ModelConfig, "get_model_hash", fake_get_model_hash):
                return ModelConfig(settings, repo, token, is_dry_check=True)

    def test_canonical_id_sets_arch_display_and_member_tag(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE
        from core.model_identity import ModelRecord

        record = ModelRecord("mdx:good", "mdx", "good", "Good", engine_name="good")
        model = self._build("mdx:good", records=(record,))
        self.assertEqual(model.process_method, MDX_ARCH_TYPE)
        self.assertEqual(model.model_name, "Good")
        self.assertEqual(model.model_and_process_tag, record.id)

    def test_legacy_member_tag_still_splits(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE
        from core.model_identity import ModelRecord, canonical_member_tag

        record = ModelRecord("mdx:good", "mdx", "good", "Good", engine_name="good")
        tag = canonical_member_tag(record)
        model = self._build(tag, records=(record,))
        self.assertEqual(model.process_method, MDX_ARCH_TYPE)
        self.assertEqual(model.model_name, "Good")
        self.assertEqual(model.model_and_process_tag, record.id)


class ModelConfigKaraokeConfidenceTests(unittest.TestCase):
    """ModelConfig.is_karaoke_curated must agree with which branch of
    resolve_karaoke_confidence actually set is_karaoke."""

    def _model(self) -> typing.Any:
        from types import SimpleNamespace

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
        model.check_if_karaokee_model = lambda: ModelConfig.check_if_karaokee_model(model)  # type: ignore[arg-type]
        return model

    def test_curated_hash_metadata_sets_curated_true(self) -> None:
        model = self._model()
        model.model_data = {"is_karaoke": True}
        ModelConfig.check_if_karaokee_model(model)
        self.assertTrue(model.is_karaoke)
        self.assertTrue(model.is_karaoke_curated)

    def test_curated_false_metadata_blocks_name_inference(self) -> None:
        model = self._model()
        model.model_data = {"is_karaoke": False}
        model.model_name = "Karaoke-labelled model"
        ModelConfig.apply_karaoke_metadata(model)
        self.assertFalse(model.is_karaoke)
        self.assertTrue(model.is_karaoke_curated)

    def test_legacy_typo_false_metadata_blocks_name_inference(self) -> None:
        model = self._model()
        model.model_data = {"is_karaokee": False}
        model.model_name = "Karaoke-labelled model"
        ModelConfig.apply_karaoke_metadata(model)
        self.assertFalse(model.is_karaoke)
        self.assertTrue(model.is_karaoke_curated)

    def test_guessed_from_name_sets_curated_false(self) -> None:
        model = self._model()
        model.model_name = "BandSplit Roformer | Karaoke Frazer by becruily"
        ModelConfig.apply_karaoke_metadata(model)
        self.assertTrue(model.is_karaoke)
        self.assertFalse(model.is_karaoke_curated)

    def test_no_signal_leaves_both_false(self) -> None:
        model = self._model()
        ModelConfig.apply_karaoke_metadata(model)
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


class ListModelTagsCanonicalTests(unittest.TestCase):
    """list_*_model_tags emit family:basename, sorted by display label."""

    def test_list_mdx_model_tags_are_canonical_ids_sorted_by_display(self) -> None:
        from bundled.constants import ENSEMBLE_PARTITION
        from core.model_repository import ModelRepository
        from core.model_identity import ModelId

        repo = ModelRepository.__new__(ModelRepository)
        with patch.object(repo, "list_mdx_models", return_value=["zzz", "aaa"]), patch(
            "core.model_repository.map_basenames_to_display",
            return_value=["Zebra", "Apple"],
        ):
            tags = repo.list_mdx_model_tags()
        self.assertEqual(tags, ["mdx:aaa", "mdx:zzz"])
        for tag in tags:
            ModelId.parse(tag)
            self.assertNotIn(ENSEMBLE_PARTITION, tag)

    def test_list_vr_and_demucs_tags_use_family_prefix(self) -> None:
        from core.model_repository import ModelRepository
        from core.model_identity import ModelId

        repo = ModelRepository.__new__(ModelRepository)
        with patch.object(repo, "list_vr_models", return_value=["hp"]), patch(
            "core.model_repository.map_basenames_to_display", return_value=["HP"]
        ):
            vr = repo.list_vr_model_tags()
        self.assertEqual(vr, ["vr:hp"])
        ModelId.parse(vr[0])

        with patch.object(repo, "list_demucs_models", return_value=["htdemucs"]), patch(
            "core.model_repository.map_basenames_to_display", return_value=["v4 | htdemucs"]
        ):
            demucs = repo.list_demucs_model_tags()
        self.assertEqual(demucs, ["demucs:htdemucs"])
        ModelId.parse(demucs[0])


class NestedCanonicalModelConfigTests(unittest.TestCase):
    """Canonical settings IDs must not be treated as ensemble member tags."""

    def _capture_config(self):
        from core.model_config import ModelConfig as RealConfig

        captured: dict[str, object] = {}

        def wrapper(*args: typing.Any, **kwargs: typing.Any):
            model = RealConfig(*args, **kwargs)
            captured["process_method"] = model.process_method
            captured["has_model_path"] = hasattr(model, "model_path")
            return model

        return captured, wrapper

    def test_vocal_splitter_canonical_id_does_not_crash(self) -> None:
        from core.model_config import process_determine_vocal_split_model

        settings = Settings.defaults()
        settings.process.vocal_splitter_enabled = True
        settings.process.vocal_splitter = "mdx:KaraokeFusion"
        repo = _repo_with_mdx("KaraokeFusion")
        captured, wrapper = self._capture_config()

        with patch("core.model_config.config.ModelConfig", side_effect=wrapper), patch(
            "core.model_display.map_basenames_to_display",
            side_effect=lambda names, *args, **kwargs: list(names),
        ), patch("core.apollo.list_apollo_models", return_value=[]):
            process_determine_vocal_split_model(settings, repo)

        self.assertEqual(captured.get("process_method"), MDX_ARCH_TYPE)
        self.assertTrue(captured.get("has_model_path"))

    def test_secondary_canonical_id_does_not_crash(self) -> None:
        from bundled.constants import VOCAL_STEM
        from core.model_config import process_determine_secondary_model

        settings = Settings.defaults()
        settings.mdx.voc_inst_secondary_model = "mdx:KaraokeFusion"
        repo = _repo_with_mdx("KaraokeFusion")
        captured, wrapper = self._capture_config()

        with patch("core.model_config.config.ModelConfig", side_effect=wrapper), patch(
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
        self.mdxnet_stem_select = None
        self.demucs_stems = None
        self.is_ensemble_mode = False
        self.is_secondary_model = False
        self.is_pre_proc_model = False

    def apply(self) -> None:
        ModelConfig._apply_stem_focus(self)  # type: ignore[arg-type]


class StemIdentityAssembleTests(unittest.TestCase):
    def test_vocal_split_model_keeps_its_native_primary_stem(self) -> None:
        """The old assemble rewrote a splitter's primary to ``lead_only``.

        Native yaml/hash spelling must survive; the lead/backing concept is
        derived instead (see tests/test_vocal_split_stems.py).
        """
        from core.stems import StemBucket, stem_concept

        stub = _FocusStub(Settings.defaults(), "vocals", "other")
        stub.is_vocal_split_model = True
        ModelConfig._apply_stem_focus(stub)  # type: ignore[arg-type]
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
        before = settings.process.stem_focus

        vocals_primary = _FocusStub(settings, "vocals", "other")
        vocals_primary.apply()
        inst_primary = _FocusStub(settings, "other", "vocals")
        inst_primary.apply()

        self.assertEqual(settings.process.stem_focus, before)
        # Focus resolves onto selected routes; assembled flags/natives stay put.
        self.assertEqual(
            [route.concept for route in vocals_primary.selected_stem_routes],
            [StemBucket.VOCALS.value],
        )
        self.assertEqual(vocals_primary.primary_stem, "vocals")
        self.assertEqual(
            [route.concept for route in inst_primary.selected_stem_routes],
            [StemBucket.VOCALS.value],
        )
        self.assertEqual(inst_primary.primary_stem, "other")

    def test_focus_naming_no_stem_exports_everything(self) -> None:
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = "Bass"
        stub = _FocusStub(settings, "vocals", "other")
        stub.apply()
        self.assertEqual(stub.primary_stem, "vocals")
        self.assertEqual(
            {route.concept for route in stub.selected_stem_routes},
            {StemBucket.VOCALS.value, StemBucket.INSTRUMENTAL.value},
        )

    def test_multi_stem_mdx_focus_populates_native_subset(self) -> None:
        from bundled.constants import BASS_STEM
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = BASS_STEM
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.apply()
        self.assertEqual(stub.mdxnet_stems_selected, [])
        self.assertEqual(stub.primary_stem, "vocals")
        selected = stub.selected_stem_routes
        self.assertEqual(len(selected), 1)
        self.assertIsNotNone(selected[0].native)
        self.assertTrue(selected[0].native.matches("bass"))
        self.assertEqual(selected[0].concept, StemBucket.BASS.value)

    def test_multi_stem_mdx_include_complement_adds_derived_route(self) -> None:
        from bundled.constants import BASS_STEM
        from core.stems import StemBucket

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
            if route.concept == StemBucket.INSTRUMENTAL.value
        )
        self.assertIsNone(complement.native)
        selected = stub.selected_stem_routes
        self.assertEqual(len(selected), 1)
        self.assertIsNotNone(selected[0].native)
        self.assertTrue(selected[0].native.matches("bass"))

    def test_multi_stem_mdx_instrumental_focus_uses_vocal_complement(self) -> None:
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.INSTRUMENTAL.value
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.apply()
        self.assertEqual(stub.mdxnet_stems_selected, [])
        self.assertEqual(stub.primary_stem, "vocals")
        selected = stub.selected_stem_routes
        self.assertEqual(len(selected), 1)
        self.assertIsNone(selected[0].native)
        self.assertEqual(selected[0].concept, StemBucket.INSTRUMENTAL.value)

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
        self.assertEqual(stub.demucs_stems, None)
        self.assertEqual(stub.primary_stem, "Vocals")
        selected = stub.selected_stem_routes
        self.assertEqual(len(selected), 1)
        self.assertIsNotNone(selected[0].native)
        self.assertTrue(selected[0].native.matches(BASS_STEM))

    def test_empty_focus_honors_mdx_subset_sidecar(self) -> None:
        from bundled.constants import BASS_STEM, DRUM_STEM
        from core.stems import StemBucket

        settings = Settings.defaults()
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.mdxnet_stems_selected = [BASS_STEM, DRUM_STEM]
        stub.apply()
        selected = stub.selected_stem_routes
        self.assertEqual(len(selected), 2)
        self.assertIsNotNone(selected[0].native)
        self.assertIsNotNone(selected[1].native)
        self.assertEqual(
            [route.concept for route in selected],
            [StemBucket.BASS.value, StemBucket.DRUMS.value],
        )
        self.assertTrue(selected[0].native.matches("bass"))
        self.assertTrue(selected[1].native.matches("drums"))

    def test_empty_focus_without_sidecar_keeps_defaults(self) -> None:
        from core.stems import StemBucket

        settings = Settings.defaults()
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.mdxnet_stems_selected = []
        stub.apply()
        self.assertEqual(
            {route.concept for route in stub.selected_stem_routes if route.native},
            {
                StemBucket.DRUMS.value,
                StemBucket.BASS.value,
                StemBucket.OTHER.value,
                StemBucket.VOCALS.value,
            },
        )

    def test_focus_wins_over_conflicting_sidecar(self) -> None:
        from bundled.constants import BASS_STEM, DRUM_STEM
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = BASS_STEM
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.mdxnet_stems_selected = [DRUM_STEM]
        stub.apply()
        selected = stub.selected_stem_routes
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].concept, StemBucket.BASS.value)
        self.assertTrue(selected[0].native.matches("bass"))

    def test_demucs_leftover_mdx_sidecar_is_ignored(self) -> None:
        from bundled.constants import BASS_STEM, DEMUCS_ARCH_TYPE, DRUM_STEM
        from core.stems import StemBucket

        settings = Settings.defaults()
        stub = _FocusStub(settings, "Vocals", "Instrumental")
        stub.process_method = DEMUCS_ARCH_TYPE
        stub.mdx_stem_count = 0
        stub.mdx_model_stems = []
        stub.mdxnet_stems_selected = [BASS_STEM, DRUM_STEM]
        stub.demucs_stem_count = 4
        stub.demucs_source_list = ["Bass", "Drums", "Other", "Vocals"]
        stub.apply()
        self.assertEqual(
            {route.concept for route in stub.selected_stem_routes if route.native},
            {
                StemBucket.BASS.value,
                StemBucket.DRUMS.value,
                StemBucket.OTHER.value,
                StemBucket.VOCALS.value,
            },
        )

    def test_empty_focus_mdx_sidecar_filters_native_subset(self) -> None:
        from bundled.constants import BASS_STEM, DRUM_STEM
        from core.stems import StemBucket

        settings = Settings.defaults()
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.mdxnet_stems_selected = [BASS_STEM, DRUM_STEM]
        stub.apply()
        selected = stub.selected_stem_routes
        self.assertEqual(
            {route.concept for route in selected},
            {StemBucket.BASS.value, StemBucket.DRUMS.value},
        )

    def test_positional_sentinel_wins_over_sidecar(self) -> None:
        from bundled.constants import BASS_STEM, DRUM_STEM
        from core.stems import FOCUS_PRIMARY, StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = FOCUS_PRIMARY
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.mdxnet_stems_selected = [BASS_STEM, DRUM_STEM]
        stub.apply()
        selected = stub.selected_stem_routes
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].concept, StemBucket.VOCALS.value)
        self.assertTrue(selected[0].native.matches("vocals"))

    def test_concept_focus_selects_native_bass(self) -> None:
        from bundled.constants import BASS_STEM
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = BASS_STEM
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.apply()
        selected = stub.selected_stem_routes
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].concept, StemBucket.BASS.value)
        self.assertTrue(selected[0].native.matches("bass"))

    def test_ensemble_pair_wins_over_positional_sentinel(self) -> None:
        from core.stems import EnsemblePair, FOCUS_PRIMARY, StemBucket

        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL
        settings.process.stem_focus = FOCUS_PRIMARY
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.is_ensemble_mode = True
        stub.apply()
        self.assertEqual(
            {route.concept for route in stub.selected_stem_routes},
            {StemBucket.VOCALS.value, StemBucket.INSTRUMENTAL.value},
        )

    def test_positional_sentinel_picks_primary_route(self) -> None:
        from core.stems import FOCUS_PRIMARY, StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = FOCUS_PRIMARY
        stub = _FocusStub(settings, "vocals", "other")
        stub.apply()
        selected = stub.selected_stem_routes
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].concept, StemBucket.VOCALS.value)

    def test_positional_sentinel_picks_derived_secondary(self) -> None:
        from core.stems import FOCUS_SECONDARY, StemBucket, StemRouteKind

        settings = Settings.defaults()
        settings.process.stem_focus = FOCUS_SECONDARY
        stub = _FocusStub(settings, "vocals", "Instrumental")
        stub.mdx_model_stems = ["drums", "bass", "other", "vocals"]
        stub.mdx_stem_count = 4
        stub.apply()
        selected = stub.selected_stem_routes
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].concept, StemBucket.INSTRUMENTAL.value)
        self.assertIsNone(selected[0].native)
        self.assertEqual(selected[0].kind, StemRouteKind.DERIVED)


if __name__ == "__main__":
    unittest.main()
