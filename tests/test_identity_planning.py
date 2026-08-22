from __future__ import annotations

import unittest
import tempfile
from unittest.mock import Mock, patch

from bundled.constants import DEMUCS_ARCH_TYPE, VR_ARCH_PM, VR_ARCH_TYPE
from core.job_plan import (
    JobResolver,
    JobSpec,
    ValidationLevel,
    active_model_paths,
    compute_model_identity_digest,
)
from core.model_identity import MdxSpec, ModelArtifacts, ModelRecord
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
