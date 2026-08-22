from __future__ import annotations

import os
import unittest
from typing import Literal
import tempfile
import numpy as np
from unittest.mock import Mock, patch

from bundled.constants import DEMUCS_ARCH_TYPE, VR_ARCH_PM, VR_ARCH_TYPE
from core import paths
from core.job_plan import (
    JobResolver,
    JobSpec,
    ValidationLevel,
    active_model_paths,
    compute_model_identity_digest,
)
from core.model_identity import (
    IdentityIndex,
    MdxSpec,
    ModelArtifacts,
    ModelIdentityService,
    ModelRecord,
)
from core.model_repository import ModelRepository
from core.settings import Settings
from core.types import ProcessMethod


class DryResolutionArchitectureTests(unittest.TestCase):
    def test_vr_process_label_is_normalized_to_engine_architecture(self) -> None:
        settings = Settings.defaults()
        repo = Mock()
        resolved = Mock()

        with patch("core.model_repository.ModelConfig", return_value=resolved) as config:
            result = ModelRepository.resolve_model_dry(
                repo, settings, VR_ARCH_PM, "VR model"
            )

        self.assertIs(result, resolved)
        config.assert_called_once_with(
            settings,
            repo,
            "VR model",
            VR_ARCH_TYPE,
            is_dry_check=True,
        )


class ActivePathTests(unittest.TestCase):
    def test_mdx_primary_only_when_secondaries_off(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:UVR-MDX-NET-Inst_HQ_4"
        self.assertEqual(active_model_paths(settings, command="separate"), ("mdx.model",))

    def test_enabled_splitter_is_included(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:UVR-MDX-NET-Inst_HQ_4"
        settings.process.vocal_splitter_enabled = True
        settings.process.vocal_splitter = "vr:UVR-De-Echo-Normal"
        self.assertEqual(
            active_model_paths(settings, command="separate"),
            ("mdx.model", "process.vocal_splitter"),
        )

    def test_four_stem_secondaries_include_all_slots(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.DEMUCS
        settings.demucs.model = "demucs:htdemucs"
        settings.demucs.is_secondary_model_activate = True
        settings.demucs.voc_inst_secondary_model = "mdx:a"
        settings.demucs.other_secondary_model = "mdx:b"
        settings.demucs.bass_secondary_model = "mdx:c"
        settings.demucs.drums_secondary_model = "mdx:d"
        paths = active_model_paths(
            settings, command="separate", source_layout="4_stem"
        )
        self.assertIn("demucs.voc_inst_secondary_model", paths)
        self.assertIn("demucs.drums_secondary_model", paths)

    def test_two_stem_secondaries_include_only_primary_slot(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.DEMUCS
        settings.demucs.model = "demucs:UVR_Demucs_Model_1"
        settings.demucs.is_secondary_model_activate = True
        settings.demucs.voc_inst_secondary_model = "mdx:a"
        settings.demucs.other_secondary_model = "mdx:b"
        paths = active_model_paths(
            settings, command="separate", source_layout="2_stem"
        )
        self.assertEqual(
            [path for path in paths if path.endswith("_secondary_model")],
            ["demucs.voc_inst_secondary_model"],
        )

    def test_enabled_missing_secondary_raises(self) -> None:
        from core.job_plan import JobResolver

        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        settings.mdx.is_secondary_model_activate = True
        settings.mdx.voc_inst_secondary_model = "mdx:missing"
        primary = _record("mdx:primary")
        resolver = JobResolver(Mock())
        resolver.identities.lookup = Mock(
            side_effect=lambda model_id: (
                primary if model_id == primary.id else (_ for _ in ()).throw(ValueError("missing"))
            )
        )
        with self.assertRaises(ValueError):
            resolver._dependency_map(settings, "separate")

    def test_enabled_missing_secondary_raises_during_model_assembly(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE, VOCAL_STEM
        from core.model_config import process_determine_secondary_model
        from core.model_identity import IdentityIndex, ModelIdentityService

        settings = Settings.defaults()
        settings.mdx.is_secondary_model_activate = True
        settings.mdx.voc_inst_secondary_model = "mdx:missing"
        repo = Mock()
        with patch.object(
            ModelIdentityService,
            "_published_index",
            return_value=IdentityIndex({}),
        ):
            with self.assertRaises(ValueError):
                process_determine_secondary_model(
                    settings, repo, MDX_ARCH_TYPE, VOCAL_STEM
                )

    def test_demucs_pre_proc_accepts_vr_and_mdx_families(self) -> None:
        primary = _record("demucs:primary")
        for pre_proc in (_record("vr:pre-proc"), _record("mdx:pre-proc")):
            with self.subTest(family=pre_proc.family):
                settings = Settings.defaults()
                settings.process.method = ProcessMethod.DEMUCS
                settings.demucs.model = primary.id
                settings.demucs.is_pre_proc_model_activate = True
                settings.demucs.pre_proc_model = pre_proc.id
                records = {primary.id: primary, pre_proc.id: pre_proc}
                resolver = JobResolver(Mock())
                resolver.identities.lookup = Mock(side_effect=records.__getitem__)

                self.assertEqual(
                    resolver._dependency_map(settings, "separate"),
                    {
                        "demucs.model": primary,
                        "demucs.pre_proc_model": pre_proc,
                    },
                )

    def test_demucs_pre_proc_rejects_demucs_family(self) -> None:
        primary = _record("demucs:primary")
        pre_proc = _record("demucs:pre-proc")
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.DEMUCS
        settings.demucs.model = primary.id
        settings.demucs.is_pre_proc_model_activate = True
        settings.demucs.pre_proc_model = pre_proc.id
        records = {primary.id: primary, pre_proc.id: pre_proc}
        resolver = JobResolver(Mock())
        resolver.identities.lookup = Mock(side_effect=records.__getitem__)

        with self.assertRaisesRegex(
            ValueError,
            r"demucs\.pre_proc_model .* requires family mdx, vr",
        ):
            resolver._dependency_map(settings, "separate")


class DigestTests(unittest.TestCase):
    def test_display_change_does_not_change_digest(self) -> None:
        a = _record("mdx:foo", display="Old")
        b = _record("mdx:foo", display="New")
        self.assertEqual(
            compute_model_identity_digest({"mdx.model": a}),
            compute_model_identity_digest({"mdx.model": b}),
        )

    def test_backend_change_changes_digest(self) -> None:
        a = _record("mdx:foo")
        b = ModelRecord(
            id="mdx:foo",
            family="mdx",
            basename="foo",
            display="X",
            backend_name="foo.onnx",
            artifacts=ModelArtifacts("foo.onnx"),
            installed=True,
        )
        self.assertNotEqual(
            compute_model_identity_digest({"mdx.model": a}),
            compute_model_identity_digest({"mdx.model": b}),
        )

    def test_artifact_change_changes_digest(self) -> None:
        a = _record("mdx:foo")
        b = ModelRecord(
            id=a.id,
            family=a.family,
            basename=a.basename,
            display=a.display,
            backend_name=a.backend_name,
            artifacts=ModelArtifacts("renamed.onnx", ("config.yaml",)),
            installed=a.installed,
        )
        digest = compute_model_identity_digest({"mdx.model": a})
        self.assertTrue(digest.startswith("sha256:"))
        self.assertNotEqual(
            digest,
            compute_model_identity_digest({"mdx.model": b}),
        )


class ResolvedPlanIdentityTests(unittest.TestCase):
    def test_plan_serializes_dependencies_and_descriptor_identity(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        record = ModelRecord(
            id="mdx:primary",
            family="mdx",
            basename="primary",
            display="Primary",
            backend_name="primary.onnx",
            artifacts=ModelArtifacts("primary.onnx", ("config.yaml",)),
            installed=True,
            mdx=MdxSpec("classic_onnx"),
        )
        resolver = JobResolver(Mock(inventory_generation=3))
        resolver.identities = Mock()
        resolver.identities.lookup.return_value = record
        resolver.identities.resolve.side_effect = AssertionError("fuzzy resolution used")

        with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
            plan = resolver.resolve(
                JobSpec("separate", settings, (handle.name,), "/tmp/out"),
                ValidationLevel.CONFIG,
            )

        payload = plan.to_dict()
        self.assertEqual(payload["model_dependencies"], {"mdx.model": record.id})
        self.assertEqual(payload["model_identity_digest"], plan.model_identity_digest)
        self.assertEqual(plan.models[0].backend_name, record.backend_name)
        self.assertEqual(plan.models[0].artifacts, record.artifacts)
        self.assertEqual(plan.models[0].mdx, record.mdx)
        resolver.identities.resolve.assert_not_called()

    def test_active_identity_change_makes_plan_stale(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        original = _record("mdx:primary")
        changed = ModelRecord(
            id=original.id,
            family=original.family,
            basename=original.basename,
            display=original.display,
            backend_name="changed",
            artifacts=original.artifacts,
            installed=True,
        )
        resolver = JobResolver(Mock(inventory_generation=0))
        resolver.identities = Mock()
        resolver.identities.lookup.return_value = original
        with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
            plan = resolver.resolve(
                JobSpec("separate", settings, (handle.name,), "/tmp/out"),
                ValidationLevel.CONFIG,
            )

        resolver.identities.lookup.return_value = changed
        self.assertFalse(resolver.is_current(plan))


class ApolloSettingsStayCanonicalTests(unittest.TestCase):
    def test_resolver_does_not_write_filename_into_settings(self) -> None:
        from core.audio_plan import AudioJobResolver
        from core.settings import Settings
        from core.job_plan import ValidationLevel

        settings = Settings.defaults()
        settings.audio_tools.apollo_model = "apollo:restorer"
        record = ModelRecord(
            id="apollo:restorer",
            family="apollo",
            basename="restorer",
            display="restorer",
            backend_name="restorer.ckpt",
            artifacts=ModelArtifacts("restorer.ckpt"),
            installed=True,
        )
        resolver = AudioJobResolver(Mock(inventory_generation=0))
        resolver.identities = Mock()
        resolver.identities.resolve.return_value = record
        resolver._resolve_apollo(settings, [], ValidationLevel.CONFIG)
        self.assertEqual(settings.audio_tools.apollo_model, "apollo:restorer")


class SplitterExactIdTests(unittest.TestCase):
    def test_substring_no_longer_matches(self) -> None:
        from core.settings.job_resolution import resolve_splitter_identity
        from core.settings import Settings

        settings = Settings.defaults()
        repo, index = _repo_with_karaoke("vr:UVR-De-Echo-Normal")
        with patch.object(
            ModelIdentityService, "_published_index", return_value=index
        ), patch.object(
            ModelIdentityService,
            "canonical_id_from_member_tag",
            return_value="vr:UVR-De-Echo-Normal",
        ):
            with self.assertRaises(ValueError):
                resolve_splitter_identity("Echo", settings, repo)

    def test_canonical_splitter_id_still_resolves(self) -> None:
        from core.settings.job_resolution import resolve_splitter_identity
        from core.settings import Settings

        settings = Settings.defaults()
        repo, index = _repo_with_karaoke("vr:UVR-De-Echo-Normal")
        with patch.object(
            ModelIdentityService, "_published_index", return_value=index
        ), patch.object(
            ModelIdentityService,
            "canonical_id_from_member_tag",
            return_value="vr:UVR-De-Echo-Normal",
        ):
            self.assertEqual(
                resolve_splitter_identity("vr:UVR-De-Echo-Normal", settings, repo),
                "vr:UVR-De-Echo-Normal",
            )


class DemucsInferenceIdentityTests(unittest.TestCase):
    def test_mismatched_post_inference_layout_raises_actionable_error(self) -> None:
        from core.demucs_registry import validate_demucs_output_layout

        with self.assertRaisesRegex(
            ValueError,
            r"htdemucs_6s.*4_stem.*6_stem source layout",
        ):
            validate_demucs_output_layout(
                expected_count=6,
                actual_count=4,
                model_label="v4 - htdemucs_6s",
            )

    def test_preprocessing_result_layout_is_validated_before_graft_indexing(self) -> None:
        from core.demucs_registry import validate_demucs_inference_layouts

        source = np.zeros((4, 2, 2), dtype=np.float32)
        inst_source = np.zeros((2, 2, 2), dtype=np.float32)

        with self.assertRaisesRegex(
            ValueError,
            r"pre-processing result.*2_stem.*4_stem source layout",
        ):
            validate_demucs_inference_layouts(
                expected_count=4,
                model_label="Friendly Demucs",
                source=source,
                inst_source=inst_source,
            )


class MdxYamlFetchPolicyTests(unittest.TestCase):
    def test_plan_offline_does_not_fetch(self) -> None:
        from core.job_plan import JobResolver

        record = _mdx_record_missing_yaml()
        resolver = JobResolver(_repo_with_mdx_c_missing_yaml())
        resolver.identities = Mock()
        resolver.identities.lookup.return_value = record
        with patch("core.mdx_config_fetch.ensure_mdx_c_config", side_effect=AssertionError("fetch")):
            plan = resolver.resolve(_separate_spec(), allow_network=False)
        # No fetch, and the miss lands in the plan rather than escaping it.
        self.assertIn(
            "model.configuration", [item.code for item in plan.diagnostics]
        )

    def test_plan_online_fetches_once_then_relooks_up(self) -> None:
        from core.job_plan import JobResolver

        fetches: list[str] = []

        def fake_ensure(name: str, **kwargs: object) -> bool:
            fetches.append(name)
            return True

        record = _mdx_record_missing_yaml()
        resolver = JobResolver(_repo_with_mdx_c_missing_yaml())
        resolver.identities = Mock()
        resolver.identities.lookup.return_value = record
        with patch("core.mdx_config_fetch.ensure_mdx_c_config", side_effect=fake_ensure), patch.object(
            resolver, "_assemble", return_value=[Mock(model_status=True)]
        ):
            resolver.resolve(_separate_spec(), ValidationLevel.CONFIG, allow_network=True)
        self.assertEqual(len(fetches), 1)


def _repo_with_karaoke(canonical_id: str) -> tuple[Mock, IdentityIndex]:
    record = _record(canonical_id)
    repo = Mock()
    repo.karaoke_model_list = Mock(return_value=[f"VR Arch: {canonical_id.split(':', 1)[1]}"])
    return repo, IdentityIndex({canonical_id: record})


def _mdx_record_missing_yaml() -> ModelRecord:
    return ModelRecord(
        id="mdx:TestModel",
        family="mdx",
        basename="TestModel",
        display="Test",
        backend_name="TestModel.ckpt",
        artifacts=ModelArtifacts("TestModel.ckpt", ("missing_config.yaml",)),
        installed=True,
        mdx=MdxSpec("mdx23c"),
    )


def _repo_with_mdx_c_missing_yaml() -> Mock:
    return Mock(inventory_generation=0, invalidate_models=Mock())


def _separate_spec() -> JobSpec:
    settings = Settings.defaults()
    settings.process.method = ProcessMethod.MDX
    settings.mdx.model = "mdx:TestModel"
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    return JobSpec("separate", settings, (path,), "/tmp/out")


def _record(model_id: str, *, display: str = "X") -> ModelRecord:
    family, basename = model_id.split(":", 1)
    return ModelRecord(
        id=model_id,
        family=family,
        basename=basename,
        display=display,
        backend_name=basename,
        artifacts=ModelArtifacts(f"{basename}.onnx"),
        installed=True,
    )


class OfflineMdxConfigDiagnosticTests(unittest.TestCase):
    """An unavailable MDX yaml is a plan diagnostic, not an escaping exception.

    ``_ensure_mdx_yaml_configs`` used to be called outside ``resolve``'s
    ``try/except ValueError``, so its offline raise propagated: the GUI and CLI
    both caught it broadly, but ``--dry-run --report json`` returned a bare
    error instead of the plan payload every other planning failure produces.
    """

    def _spec(self, tmp: str) -> JobSpec:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:roformer"
        source = os.path.join(tmp, "input.wav")
        with open(source, "wb") as handle:
            handle.write(b"RIFF")
        return JobSpec("separate", settings, (source,), os.path.join(tmp, "out"))

    def _resolver(self) -> JobResolver:
        record = ModelRecord(
            id="mdx:roformer",
            family="mdx",
            basename="roformer",
            display="Roformer",
            backend_name="roformer",
            artifacts=ModelArtifacts("roformer.ckpt", ("roformer.yaml",)),
            installed=True,
            mdx=MdxSpec("bs_roformer"),
        )
        repo = Mock()
        repo.inventory_generation = 0
        resolver = JobResolver(repo)
        resolver.identities.lookup = Mock(return_value=record)  # type: ignore[method-assign]
        return resolver

    def test_offline_yaml_miss_becomes_a_diagnostic(self) -> None:
        resolver = self._resolver()
        with tempfile.TemporaryDirectory() as tmp:
            spec = self._spec(tmp)
            with patch.object(paths, "MDX_C_CONFIG_PATH", os.path.join(tmp, "configs")):
                plan = resolver.resolve(
                    spec, ValidationLevel.MODEL, allow_network=False
                )

        codes = [item.code for item in plan.diagnostics]
        self.assertIn("model.configuration", codes)
        message = next(
            item.message for item in plan.diagnostics
            if item.code == "model.configuration"
        )
        self.assertIn("not available offline", message)
        # The payload is still a plan: dependencies and the identity digest are
        # built from the pre-fetch map, not emptied by the failure.
        self.assertIn("mdx.model", plan.model_dependencies)
        self.assertTrue(plan.model_identity_digest)


class DemucsSecondarySlotAgreementTests(unittest.TestCase):
    """The runtime must resolve exactly the slots planning declared.

    ``active_model_paths`` widens to the four per-stem Demucs secondary slots
    only for a ``4_stem``/``6_stem`` source layout. ``ModelConfig`` used to
    widen for any Demucs model whenever ``demucs.stems == ALL_STEMS``, so a
    2-source model resolved four slots the plan never validated or digested.
    """

    def _settings(self):
        from bundled.constants import ALL_STEMS

        settings = Settings.defaults()
        settings.process.method = ProcessMethod.DEMUCS
        settings.demucs.model = "demucs:bag"
        settings.demucs.stems = ALL_STEMS
        settings.demucs.is_secondary_model_activate = True
        for slot in ("voc_inst", "other", "bass", "drums"):
            setattr(settings.demucs, f"{slot}_secondary_model", "mdx:helper")
        return settings

    def _record(self, layout: Literal["2_stem", "4_stem", "6_stem"]) -> ModelRecord:
        from core.model_identity import DemucsSpec

        return ModelRecord(
            id="demucs:bag",
            family="demucs",
            basename="bag",
            display="Bag",
            backend_name="bag",
            artifacts=ModelArtifacts("bag.th"),
            installed=True,
            demucs=DemucsSpec("v2" if layout == "2_stem" else "v4", layout),
        )

    def _resolved_slots(
        self, layout: Literal["2_stem", "4_stem", "6_stem"]
    ) -> list[str]:
        from bundled.constants import DEMUCS_ARCH_TYPE
        from core.model_config.config import ModelConfig

        settings = self._settings()
        asked: list[str] = []

        def fake_determine(
            _settings: object, _repo: object, _method: object, stem: object
        ) -> tuple[None, None]:
            asked.append(str(stem))
            return None, None

        with patch(
            "core.model_config.determine.process_determine_secondary_model",
            side_effect=fake_determine,
        ):
            ModelConfig(
                settings, Mock(), "demucs:bag", DEMUCS_ARCH_TYPE,
                is_dry_check=True, identity=self._record(layout),
            )
        return asked

    def _planned_slots(
        self, layout: Literal["2_stem", "4_stem", "6_stem"]
    ) -> set[str]:
        settings = self._settings()
        return {
            path.split(".", 1)[1].removesuffix("_secondary_model")
            for path in active_model_paths(
                settings, command="separate", primary=(self._record(layout),)
            )
            if path.endswith("_secondary_model")
        }

    def test_two_source_layout_resolves_one_slot_like_the_plan(self) -> None:
        from bundled.constants import DEMUCS_4_SOURCE_LIST

        asked = self._resolved_slots("2_stem")
        self.assertNotEqual(asked, list(DEMUCS_4_SOURCE_LIST))
        self.assertEqual(len(asked), 1)
        self.assertEqual(self._planned_slots("2_stem"), {"voc_inst"})

    def test_four_source_layout_resolves_every_slot_like_the_plan(self) -> None:
        from bundled.constants import DEMUCS_4_SOURCE_LIST

        self.assertEqual(self._resolved_slots("4_stem"), list(DEMUCS_4_SOURCE_LIST))
        self.assertEqual(
            self._planned_slots("4_stem"), {"voc_inst", "other", "bass", "drums"}
        )
