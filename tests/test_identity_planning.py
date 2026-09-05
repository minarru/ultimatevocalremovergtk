from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock, patch

import numpy as np

from bundled.constants import DEMUCS_ARCH_TYPE, VR_ARCH_PM, VR_ARCH_TYPE
from core import paths
from core.job_plan import (
    JobResolver,
    JobSpec,
    ValidationLevel,
    active_model_paths,
    compute_model_identity_digest,
)
from core.model_config.determine import secondary_slot_for_primary_stem
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
from tests.planning_fixtures import ConfigurationFiles, resolver_with_ports


class DryResolutionArchitectureTests(unittest.TestCase):
    def test_vr_process_label_is_normalized_to_engine_architecture(self) -> None:
        settings = Settings.defaults()
        repo = Mock()
        resolved = Mock()

        with patch("core.model_repository.ModelConfig", return_value=resolved) as config:
            result = ModelRepository.resolve_model_dry(repo, settings, VR_ARCH_PM, "VR model")

        self.assertIs(result, resolved)
        config.assert_called_once_with(
            settings,
            repo,
            "VR model",
            VR_ARCH_TYPE,
            is_dry_check=True,
        )


class ActivePathTests(unittest.TestCase):
    def test_ensemble_unions_native_slots_for_same_family_members(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.selected_models = ["mdx:vocal-member", "mdx:other-member"]
        settings.mdx.is_secondary_model_activate = True
        settings.mdx.voc_inst_secondary_model = "mdx:voc-helper"
        settings.mdx.other_secondary_model = "mdx:other-helper"
        primaries = (
            _record("mdx:vocal-member"),
            _record("mdx:other-member"),
        )

        paths = active_model_paths(
            settings,
            command="ensemble",
            primary=primaries,
            primary_stems={
                "ensemble.selected_models[0]": "Vocals",
                "ensemble.selected_models[1]": "other",
            },
        )

        self.assertEqual(
            [path for path in paths if path.endswith("_secondary_model")],
            ["mdx.voc_inst_secondary_model", "mdx.other_secondary_model"],
        )

    def test_secondary_slot_uses_normalized_native_primary_stem(self) -> None:
        cases = {
            "Vocals": "voc_inst",
            "vocals": "voc_inst",
            "Instrumental": "voc_inst",
            "instrumental": "voc_inst",
            "Other": "other",
            "other": "other",
            "Bass": "bass",
            "bass": "bass",
            "Drums": "drums",
            "drums": "drums",
        }
        for native_stem, expected in cases.items():
            with self.subTest(native_stem=native_stem):
                self.assertEqual(secondary_slot_for_primary_stem(native_stem), expected)

    def test_native_primary_stem_overrides_stale_mdx_settings_slot(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        settings.mdx.stems = "Drums"
        settings.mdx.is_secondary_model_activate = True
        settings.mdx.voc_inst_secondary_model = "mdx:voc-inst-helper"
        settings.mdx.drums_secondary_model = "mdx:drums-helper"

        paths = active_model_paths(
            settings,
            command="separate",
            primary=(_record("mdx:primary"),),
            primary_stems={"mdx": "instrumental"},
        )

        self.assertEqual(
            [path for path in paths if path.endswith("_secondary_model")],
            ["mdx.voc_inst_secondary_model"],
        )

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
        paths = active_model_paths(settings, command="separate", source_layout="4_stem")
        self.assertIn("demucs.voc_inst_secondary_model", paths)
        self.assertIn("demucs.drums_secondary_model", paths)

    def test_two_stem_secondaries_include_only_primary_slot(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.DEMUCS
        settings.demucs.model = "demucs:UVR_Demucs_Model_1"
        settings.demucs.is_secondary_model_activate = True
        settings.demucs.voc_inst_secondary_model = "mdx:a"
        settings.demucs.other_secondary_model = "mdx:b"
        paths = active_model_paths(settings, command="separate", source_layout="2_stem")
        self.assertEqual(
            [path for path in paths if path.endswith("_secondary_model")],
            ["demucs.voc_inst_secondary_model"],
        )

    def test_enabled_missing_secondary_raises(self) -> None:

        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        settings.mdx.is_secondary_model_activate = True
        settings.mdx.voc_inst_secondary_model = "mdx:missing"
        primary = _record("mdx:primary")
        resolver = resolver_with_ports(Mock())
        resolver.identities.lookup = Mock(
            side_effect=lambda model_id: (
                primary if model_id == primary.id else (_ for _ in ()).throw(ValueError("missing"))
            )
        )
        with self.assertRaises(ValueError):
            resolver.dependencies.dependencies(settings, "separate")

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
                process_determine_secondary_model(settings, repo, MDX_ARCH_TYPE, VOCAL_STEM)

    def test_nested_runtime_consumes_the_planned_dependency_record(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE
        from core.model_config import process_determine_secondary_model

        settings = Settings.defaults()
        settings.mdx.is_secondary_model_activate = True
        settings.mdx.drums_secondary_model = "mdx:unplanned-raw-value"
        planned = _record("mdx:planned-drums")
        nested = Mock(model_status=True, model_basename="planned-drums")

        with (
            patch("core.model_config.config.ModelConfig", return_value=nested) as config,
            patch(
                "core.model_identity.ModelIdentityService.lookup",
                side_effect=AssertionError("runtime re-resolved raw settings"),
            ),
        ):
            model, _scale = process_determine_secondary_model(
                settings,
                Mock(),
                MDX_ARCH_TYPE,
                "drums",
                {"mdx.drums_secondary_model": planned},
            )

        self.assertIs(model, nested)
        self.assertEqual(config.call_args.kwargs["identity"].id, planned.id)

    def test_resolver_plans_secondary_from_assembled_native_stem(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        settings.mdx.stems = "Drums"
        settings.mdx.is_secondary_model_activate = True
        settings.mdx.voc_inst_secondary_model = "mdx:voc-inst-helper"
        settings.mdx.drums_secondary_model = "mdx:drums-helper"
        records = {
            "mdx:primary": _record("mdx:primary"),
            "mdx:voc-inst-helper": _record("mdx:voc-inst-helper"),
            "mdx:drums-helper": _record("mdx:drums-helper"),
        }
        resolver = resolver_with_ports(Mock(inventory_generation=0))
        resolver.identities.lookup = Mock(side_effect=records.__getitem__)
        primary_model = Mock(model_status=True, primary_stem="instrumental")
        final_model = Mock(
            model_status=True,
            primary_stem="instrumental",
            compensate=None,
            model_hash_dir="",
        )
        resolver.materializer.assemble = Mock(side_effect=[[primary_model], [final_model]])

        with tempfile.NamedTemporaryFile(suffix=".wav") as source:
            plan = resolver.resolve(
                JobSpec("separate", settings, (source.name,), "/tmp/out"),
                ValidationLevel.MODEL,
            )

        self.assertEqual(
            set(plan.model_dependencies),
            {"mdx.model", "mdx.voc_inst_secondary_model"},
        )
        final_dependencies = resolver.materializer.assemble.call_args_list[1].kwargs["model_dependencies"]
        self.assertEqual(
            final_dependencies["mdx.voc_inst_secondary_model"].id,
            "mdx:voc-inst-helper",
        )
        self.assertEqual(
            plan.model_identity_digest,
            compute_model_identity_digest(plan.model_dependencies),
        )

    def test_config_plan_retains_native_stem_for_staleness_recheck(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        settings.mdx.stems = "Drums"
        settings.mdx.is_secondary_model_activate = True
        settings.mdx.voc_inst_secondary_model = "mdx:voc-inst-helper"
        settings.mdx.drums_secondary_model = "mdx:drums-helper"
        records = {
            "mdx:primary": _record("mdx:primary"),
            "mdx:voc-inst-helper": _record("mdx:voc-inst-helper"),
            "mdx:drums-helper": _record("mdx:drums-helper"),
        }
        resolver = resolver_with_ports(Mock(inventory_generation=0))
        resolver.identities.lookup = Mock(side_effect=records.__getitem__)
        topology_model = SimpleNamespace(
            model_status=True,
            primary_stem="instrumental",
            secondary_stem="Vocals",
            mdx_model_stems=(),
            demucs_source_list=(),
            mdxnet_stems_selected=(),
            model_path="",
            model_hash_dir="",
            vocal_split_model=None,
            is_karaoke=False,
            is_bv_model=False,
        )
        resolver.materializer.assemble = Mock(return_value=[topology_model])

        with tempfile.NamedTemporaryFile(suffix=".wav") as source:
            plan = resolver.resolve(
                JobSpec("separate", settings, (source.name,), "/tmp/out"),
                ValidationLevel.CONFIG,
            )

        self.assertEqual(plan.models[0].primary_stem, "instrumental")
        self.assertTrue(resolver.is_current(plan))

    def test_primary_refresh_reseeds_topology_and_final_dependencies(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        settings.mdx.is_secondary_model_activate = True
        settings.mdx.voc_inst_secondary_model = "mdx:helper"
        old = ModelRecord(
            id="mdx:primary",
            family="mdx",
            basename="primary",
            display="Primary",
            backend_name="old.ckpt",
            artifacts=ModelArtifacts("old.ckpt", ("refresh.yaml",)),
            installed=True,
        )
        new = ModelRecord(
            id="mdx:primary",
            family="mdx",
            basename="primary",
            display="Primary",
            backend_name="new.ckpt",
            artifacts=ModelArtifacts("new.ckpt", ("refresh.yaml",)),
            installed=True,
        )
        helper = _record("mdx:helper")
        records = {old.id: old, helper.id: helper}
        resolver = resolver_with_ports(Mock(inventory_generation=0))
        resolver.identities.lookup = Mock(
            side_effect=lambda model_id: records[model_id]
        )
        probe = Mock(model_status=True, primary_stem="Vocals")
        final = Mock(
            model_status=True,
            primary_stem="Vocals",
            compensate=None,
            model_hash_dir="",
        )
        assembly = Mock(side_effect=[[probe], [final]])
        resolver.materializer.assemble = assembly

        configs = ConfigurationFiles()
        resolver = JobResolver(resolver.repo, identities=resolver.identities,
                               materializer=resolver.materializer, configs=configs)
        resolver.identities.invalidate = lambda: records.update({old.id: new})
        with tempfile.NamedTemporaryFile(suffix=".wav") as source:
            plan = resolver.resolve(
                JobSpec("separate", settings, (source.name,), "/tmp/out"),
                ValidationLevel.MODEL,
            )

        self.assertIs(assembly.call_args_list[0].args[2][0], new)
        self.assertIs(plan.model_dependencies["mdx.model"], new)
        self.assertIs(assembly.call_args_list[1].kwargs["model_dependencies"]["mdx.model"], new)
        self.assertEqual(configs.calls, [("exists", "refresh.yaml"), ("ensure", "refresh.yaml"),
                                        ("exists", "refresh.yaml")])
        self.assertEqual(
            plan.model_identity_digest,
            compute_model_identity_digest(plan.model_dependencies),
        )

    def test_ensemble_resolver_plans_and_assembles_each_native_slot(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        settings.ensemble.selected_models = ["mdx:vocal-member", "mdx:other-member"]
        settings.mdx.is_secondary_model_activate = True
        settings.mdx.voc_inst_secondary_model = "mdx:voc-helper"
        settings.mdx.other_secondary_model = "mdx:other-helper"
        records = {
            model_id: _record(model_id)
            for model_id in (
                "mdx:vocal-member",
                "mdx:other-member",
                "mdx:voc-helper",
                "mdx:other-helper",
            )
        }
        resolver = resolver_with_ports(Mock(inventory_generation=0))
        resolver.identities.lookup = Mock(side_effect=records.__getitem__)

        def model(primary: str) -> SimpleNamespace:
            return SimpleNamespace(
                model_status=True,
                primary_stem=primary,
                secondary_stem=("Instrumental" if primary == "Vocals" else "No Other"),
                mdx_model_stems=(),
                demucs_source_list=(),
                mdxnet_stems_selected=(),
                model_path="",
                model_hash_dir="",
                vocal_split_model=None,
                is_karaoke=False,
                is_bv_model=False,
                compensate=None,
            )

        probe_models = [model("Vocals"), model("other")]
        final_models = [model("Vocals"), model("other")]
        resolver.materializer.assemble = Mock(side_effect=[probe_models, final_models])
        with tempfile.NamedTemporaryFile(suffix=".wav") as source:
            plan = resolver.resolve(
                JobSpec("ensemble", settings, (source.name,), "/tmp/out"),
                ValidationLevel.MODEL,
            )

        self.assertEqual(
            set(plan.model_dependencies),
            {
                "ensemble.selected_models[0]",
                "ensemble.selected_models[1]",
                "mdx.voc_inst_secondary_model",
                "mdx.other_secondary_model",
            },
        )
        final_dependencies = resolver.materializer.assemble.call_args_list[1].kwargs["model_dependencies"]
        self.assertIs(
            final_dependencies["mdx.voc_inst_secondary_model"],
            records["mdx:voc-helper"],
        )
        self.assertIs(
            final_dependencies["mdx.other_secondary_model"],
            records["mdx:other-helper"],
        )
        self.assertTrue(resolver.is_current(plan))

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
                resolver = resolver_with_ports(Mock())
                resolver.identities.lookup = Mock(side_effect=records.__getitem__)

                self.assertEqual(
                    resolver.dependencies.dependencies(settings, "separate"),
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
        resolver = resolver_with_ports(Mock())
        resolver.identities.lookup = Mock(side_effect=records.__getitem__)

        with self.assertRaisesRegex(
            ValueError,
            r"demucs\.pre_proc_model .* requires family mdx, vr",
        ):
            resolver.dependencies.dependencies(settings, "separate")


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
        resolver = resolver_with_ports(Mock(inventory_generation=3))
        resolver.identities.lookup = Mock()
        resolver.identities.lookup.return_value = record

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

    def test_enriched_display_reaches_the_descriptor_and_naming(self) -> None:
        """Identity stays raw; only the label is friendly.

        The descriptor carries the record's display, and export naming reads it
        from there -- no consumer re-derives a label from a filename, and none
        resolves a display back into an id.
        """
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.process.add_model_name = True
        settings.mdx.model = "mdx:melband_roformer_karaoke_becruily"
        record = ModelRecord(
            id="mdx:melband_roformer_karaoke_becruily",
            family="mdx",
            basename="melband_roformer_karaoke_becruily",
            display="MelBand Roformer — Karaoke · becruily",
            backend_name="melband_roformer_karaoke_becruily",
            artifacts=ModelArtifacts(
                "melband_roformer_karaoke_becruily.ckpt",
                ("melband_roformer_karaoke_becruily.yaml",),
            ),
            installed=True,
            mdx=MdxSpec("mel_band_roformer"),
        )
        resolver = resolver_with_ports(Mock(inventory_generation=1))
        resolver.identities.lookup = Mock()
        resolver.identities.lookup.return_value = record

        # An MDX-C spec resolves its yaml; this test is about the label only.
        with (
            tempfile.NamedTemporaryFile(suffix=".wav") as handle,
            patch("core.mdx_config_fetch.ensure_mdx_c_config", return_value=True),
            patch("core.downloads.ensure_mdx_c_config", return_value=True),
        ):
            plan = resolver.resolve(
                JobSpec("separate", settings, (handle.name,), "/tmp/out"),
                ValidationLevel.CONFIG,
            )

        self.assertEqual(plan.models[0].id, "mdx:melband_roformer_karaoke_becruily")
        self.assertEqual(plan.models[0].backend_name, "melband_roformer_karaoke_becruily")
        self.assertEqual(plan.models[0].display, "MelBand Roformer — Karaoke · becruily")
        self.assertEqual(
            plan.inputs[0].naming.model_label,
            "MelBand Roformer — Karaoke · becruily",
        )

    def test_a_display_only_rename_leaves_the_identity_digest_alone(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        raw = ModelRecord(
            id="mdx:primary",
            family="mdx",
            basename="primary",
            display="primary",
            backend_name="primary.onnx",
            artifacts=ModelArtifacts("primary.onnx", ()),
            installed=True,
        )
        friendly = ModelRecord(
            id=raw.id,
            family=raw.family,
            basename=raw.basename,
            display="Friendly Primary",
            backend_name=raw.backend_name,
            artifacts=raw.artifacts,
            installed=True,
        )

        digests = []
        for record in (raw, friendly):
            resolver = resolver_with_ports(Mock(inventory_generation=0))
            resolver.identities.lookup = Mock()
            resolver.identities.lookup.return_value = record
            with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
                plan = resolver.resolve(
                    JobSpec("separate", settings, (handle.name,), "/tmp/out"),
                    ValidationLevel.CONFIG,
                )
            digests.append(plan.model_identity_digest)

        self.assertEqual(digests[0], digests[1])

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
        resolver = resolver_with_ports(Mock(inventory_generation=0))
        resolver.identities.lookup = Mock()
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
        from core.job_plan import ValidationLevel
        from core.settings import Settings

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
        resolver.identities.lookup = Mock()
        resolver.identities.lookup.return_value = record
        resolver._resolve_apollo(settings, [], ValidationLevel.CONFIG)
        self.assertEqual(settings.audio_tools.apollo_model, "apollo:restorer")

    def test_audio_tools_uses_explicit_backend_checkpoint(self) -> None:
        from core.audio_tools import AudioTools

        settings = Settings.defaults()
        settings.audio_tools.apollo_model = "apollo:restorer"
        tool = AudioTools(settings, apollo_backend_name="restorer.ckpt")

        self.assertEqual(tool.apollo_model, "restorer.ckpt")
        self.assertTrue(tool.apollo_model_location.endswith("/restorer.ckpt"))
        self.assertNotIn("apollo:", tool.apollo_model_location)

    def test_apollo_inference_observes_explicit_checkpoint_path(self) -> None:
        import ml.apollo_inference
        from core.audio_tools import AudioTools

        with tempfile.TemporaryDirectory() as output:
            settings = Settings.defaults()
            settings.process.export_path = output
            settings.audio_tools.apollo_model = "apollo:restorer"
            tool = AudioTools(settings, apollo_backend_name="restorer.ckpt")
            backend = SimpleNamespace(torch_device="cpu", backend_name="cpu")
            with (
                patch.object(
                    ml.apollo_inference,
                    "restore_process",
                    return_value=np.zeros((2, 16)),
                ) as restore_process,
                patch("soundfile.write"),
                patch(
                    "core.gpu_backend.resolve_inference_backend",
                    return_value=backend,
                ),
                patch("core.gpu_backend.clear_torch_cache"),
                patch.object(tool, "_save_format"),
            ):
                tool.apollo_process(
                    "/tmp/input.wav",
                    "input",
                    {"model": "params"},
                    {},
                    Mock(),
                )

        checkpoint = restore_process.call_args.args[1]
        self.assertTrue(checkpoint.endswith("/restorer.ckpt"))
        self.assertNotIn("apollo:", checkpoint)


class SplitterExactIdTests(unittest.TestCase):
    def test_substring_no_longer_matches(self) -> None:
        from core.settings import Settings
        from core.settings.job_resolution import resolve_splitter_identity

        settings = Settings.defaults()
        repo, index = _repo_with_karaoke("vr:UVR-De-Echo-Normal")
        with (
            patch.object(ModelIdentityService, "_published_index", return_value=index),
            patch.object(
                ModelIdentityService,
                "canonical_id_from_member_tag",
                return_value="vr:UVR-De-Echo-Normal",
            ),
        ):
            with self.assertRaises(ValueError):
                resolve_splitter_identity("Echo", settings, repo)

    def test_canonical_splitter_id_still_resolves(self) -> None:
        from core.settings import Settings
        from core.settings.job_resolution import resolve_splitter_identity

        settings = Settings.defaults()
        repo, index = _repo_with_karaoke("vr:UVR-De-Echo-Normal")
        with (
            patch.object(ModelIdentityService, "_published_index", return_value=index),
            patch.object(
                ModelIdentityService,
                "canonical_id_from_member_tag",
                return_value="vr:UVR-De-Echo-Normal",
            ),
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

        record = _mdx_record_missing_yaml()
        resolver = resolver_with_ports(_repo_with_mdx_c_missing_yaml())
        resolver.identities.lookup = Mock()
        resolver.identities.lookup.return_value = record
        with patch(
            "core.mdx_config_fetch.ensure_mdx_c_config", side_effect=AssertionError("fetch")
        ):
            plan = resolver.resolve(_separate_spec(), allow_network=False)
        # No fetch, and the miss lands in the plan rather than escaping it.
        self.assertIn("model.configuration", [item.code for item in plan.diagnostics])

    def test_plan_online_fetches_once_then_relooks_up(self) -> None:

        fetches: list[str] = []

        def fake_ensure(name: str, **kwargs: object) -> bool:
            fetches.append(name)
            return True

        record = _mdx_record_missing_yaml()
        resolver = resolver_with_ports(_repo_with_mdx_c_missing_yaml())
        resolver.identities.lookup = Mock()
        resolver.identities.lookup.return_value = record
        with (
            patch("core.mdx_config_fetch.ensure_mdx_c_config", side_effect=fake_ensure),
            patch.object(resolver.materializer, "assemble", return_value=[Mock(model_status=True)]),
        ):
            resolver.resolve(_separate_spec(), ValidationLevel.CONFIG, allow_network=True)
        self.assertEqual(len(fetches), 1)

    def test_online_recovery_requires_complete_identity_after_relookup(self) -> None:

        incomplete = ModelRecord(
            id="mdx:TestModel",
            family="mdx",
            basename="TestModel",
            display="Test",
            backend_name="TestModel.ckpt",
            artifacts=ModelArtifacts("TestModel.ckpt", ("still-unknown.yaml",)),
            installed=True,
            identity_complete=False,
            identity_error="unknown MDX YAML architecture for TestModel.ckpt",
        )
        resolver = resolver_with_ports(_repo_with_mdx_c_missing_yaml())
        resolver.identities.lookup = Mock()
        resolver.identities.lookup.return_value = incomplete
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(paths, "MDX_C_CONFIG_PATH", directory),
            patch("core.mdx_config_fetch.ensure_mdx_c_config", return_value=True),
        ):
            plan = resolver.resolve(_separate_spec(), ValidationLevel.CONFIG, allow_network=True)

        self.assertIn("model.configuration", [item.code for item in plan.diagnostics])

    def test_unrelated_incomplete_identity_does_not_enter_yaml_recovery(self) -> None:

        incomplete = ModelRecord(
            id="mdx:TestModel",
            family="mdx",
            basename="TestModel",
            display="Test",
            backend_name="TestModel.ckpt",
            artifacts=ModelArtifacts("TestModel.ckpt"),
            installed=True,
            identity_complete=False,
            identity_error="identity metadata is incomplete",
        )
        resolver = resolver_with_ports(_repo_with_mdx_c_missing_yaml())
        resolver.identities.lookup = Mock()
        resolver.identities.lookup.return_value = incomplete
        with patch(
            "core.mdx_config_fetch.ensure_mdx_c_config",
            side_effect=AssertionError("unrelated identity entered recovery"),
        ) as ensure:
            plan = resolver.resolve(_separate_spec(), ValidationLevel.CONFIG, allow_network=True)

        ensure.assert_not_called()
        self.assertIn("model.identity", [item.code for item in plan.diagnostics])


class KaraokeSplitterPlanningTests(unittest.TestCase):
    def _plan(self, splitter_id: str, eligible_ids: list[str]):
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        settings.process.vocal_splitter_enabled = True
        settings.process.vocal_splitter = splitter_id
        source = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        source.close()
        self.addCleanup(os.unlink, source.name)
        records = {
            "mdx:primary": _record("mdx:primary"),
            splitter_id: _record(splitter_id),
        }
        repo = Mock(inventory_generation=0)
        repo.karaoke_model_list.return_value = eligible_ids
        resolver = resolver_with_ports(repo)
        resolver.identities.lookup = Mock(side_effect=records.__getitem__)  # type: ignore[method-assign]
        return resolver.resolve(
            JobSpec("separate", settings, (source.name,), "/tmp/out"),
            ValidationLevel.CONFIG,
            allow_network=False,
        )

    def test_exact_non_karaoke_splitter_is_rejected(self) -> None:
        plan = self._plan("vr:not-karaoke", ["vr:eligible"])

        self.assertIn("model.identity", [item.code for item in plan.diagnostics])
        self.assertEqual(
            plan.model_dependencies["process.vocal_splitter"].id,
            "vr:not-karaoke",
        )

    def test_exact_karaoke_splitter_is_accepted(self) -> None:
        plan = self._plan("vr:eligible", ["vr:eligible"])

        self.assertNotIn("model.identity", [item.code for item in plan.diagnostics])
        self.assertEqual(plan.model_dependencies["process.vocal_splitter"].id, "vr:eligible")

    def test_offline_missing_yaml_fails_before_karaoke_pool_dry_check(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        settings.process.vocal_splitter_enabled = True
        settings.process.vocal_splitter = "mdx:splitter"
        source = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        source.close()
        self.addCleanup(os.unlink, source.name)
        splitter = ModelRecord(
            id="mdx:splitter",
            family="mdx",
            basename="splitter",
            display="Splitter",
            backend_name="splitter.ckpt",
            artifacts=ModelArtifacts("splitter.ckpt", ("splitter.yaml",)),
            installed=True,
            mdx=MdxSpec("mdx23c"),
        )
        records = {
            "mdx:primary": _record("mdx:primary"),
            "mdx:splitter": splitter,
        }
        repo = Mock(inventory_generation=0)
        repo.karaoke_model_list.side_effect = AssertionError(
            "karaoke pool probed before missing YAML recovery"
        )
        resolver = resolver_with_ports(repo)
        resolver.identities.lookup = Mock(side_effect=records.__getitem__)  # type: ignore[method-assign]

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(paths, "MDX_C_CONFIG_PATH", directory),
        ):
            plan = resolver.resolve(
                JobSpec("separate", settings, (source.name,), "/tmp/out"),
                ValidationLevel.CONFIG,
                allow_network=False,
            )

        repo.karaoke_model_list.assert_not_called()
        self.assertIn("model.configuration", [item.code for item in plan.diagnostics])


class NestedReferenceExactnessTests(unittest.TestCase):
    def test_runtime_fallback_does_not_trim_splitter_reference(self) -> None:
        from core.model_config.determine import _model_config_for_reference

        settings = Settings.defaults()
        service = Mock()
        service.lookup.side_effect = ValueError("not a canonical model ID")
        with patch("core.model_identity.ModelIdentityService", return_value=service):
            with self.assertRaisesRegex(ValueError, "canonical"):
                _model_config_for_reference(
                    settings, Mock(), " mdx:splitter ", is_vocal_split_model=True
                )

        service.lookup.assert_called_once_with(" mdx:splitter ")


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
        resolver = resolver_with_ports(repo)
        resolver.identities.lookup = Mock(return_value=record)  # type: ignore[method-assign]
        return resolver

    def test_offline_yaml_miss_becomes_a_diagnostic(self) -> None:
        resolver = self._resolver()
        with tempfile.TemporaryDirectory() as tmp:
            spec = self._spec(tmp)
            with patch.object(paths, "MDX_C_CONFIG_PATH", os.path.join(tmp, "configs")):
                plan = resolver.resolve(spec, ValidationLevel.MODEL, allow_network=False)

        codes = [item.code for item in plan.diagnostics]
        self.assertIn("model.configuration", codes)
        message = next(
            item.message for item in plan.diagnostics if item.code == "model.configuration"
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

    def _ensemble_settings(self, pair_id: str) -> Settings:
        settings = self._settings()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.main_stem = pair_id
        settings.ensemble.selected_models = ["demucs:bag", "mdx:peer"]
        return settings

    @staticmethod
    def _assembled_model(primary_stem: str) -> SimpleNamespace:
        return SimpleNamespace(
            model_status=True,
            primary_stem=primary_stem,
            secondary_stem="Instrumental",
            mdx_model_stems=(),
            demucs_source_list=(),
            mdxnet_stems_selected=(),
            model_path="",
            model_hash_dir="",
            vocal_split_model=None,
            is_karaoke=False,
            is_bv_model=False,
            is_ensemble_mode=True,
            compensate=None,
        )

    def _resolved_slots(self, layout: Literal["2_stem", "4_stem", "6_stem"]) -> list[str]:
        from core.model_config.config import ModelConfig

        settings = self._settings()
        asked: list[str] = []

        def fake_determine(
            _settings: object,
            _repo: object,
            _method: object,
            stem: object,
            _dependencies: object = None,
        ) -> tuple[None, None]:
            asked.append(str(stem))
            return None, None

        with patch(
            "core.model_config.determine.process_determine_secondary_model",
            side_effect=fake_determine,
        ):
            ModelConfig(
                settings,
                Mock(),
                "demucs:bag",
                DEMUCS_ARCH_TYPE,
                is_dry_check=True,
                identity=self._record(layout),
            )
        return asked

    def _planned_slots(self, layout: Literal["2_stem", "4_stem", "6_stem"]) -> set[str]:
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

    def test_four_and_six_source_layouts_resolve_every_slot_like_the_plan(self) -> None:
        from bundled.constants import DEMUCS_4_SOURCE_LIST

        for layout in ("4_stem", "6_stem"):
            with self.subTest(layout=layout):
                self.assertEqual(self._resolved_slots(layout), list(DEMUCS_4_SOURCE_LIST))
                self.assertEqual(
                    self._planned_slots(layout),
                    {"voc_inst", "other", "bass", "drums"},
                )

    def test_four_and_multi_stem_ensembles_still_plan_every_slot(self) -> None:
        demucs = self._record("4_stem")
        peer = _record("mdx:peer")
        for pair_id in ("mode.four_stem", "mode.multi_stem"):
            with self.subTest(pair_id=pair_id):
                settings = self._ensemble_settings(pair_id)
                slots = {
                    path.split(".", 1)[1].removesuffix("_secondary_model")
                    for path in active_model_paths(
                        settings,
                        command="ensemble",
                        primary=(demucs, peer),
                    )
                    if path.startswith("demucs.") and path.endswith("_secondary_model")
                }
                self.assertEqual(slots, {"voc_inst", "other", "bass", "drums"})

    def test_four_source_member_in_two_stem_ensemble_uses_only_pair_slot(self) -> None:
        from core.model_config.config import ModelConfig

        settings = self._ensemble_settings("pair.vocals_instrumental")
        demucs = self._record("4_stem")
        peer = _record("mdx:peer")
        helper = _record("mdx:helper")
        records = {
            demucs.id: demucs,
            peer.id: peer,
            helper.id: helper,
        }
        resolver = resolver_with_ports(Mock(inventory_generation=0))
        resolver.identities.lookup = Mock(side_effect=records.__getitem__)
        resolver.materializer.assemble = Mock(
            side_effect=[
                [self._assembled_model("Vocals"), self._assembled_model("Vocals")],
                [self._assembled_model("Vocals"), self._assembled_model("Vocals")],
            ]
        )

        with tempfile.NamedTemporaryFile(suffix=".wav") as source:
            plan = resolver.resolve(
                JobSpec("ensemble", settings, (source.name,), "/tmp/out"),
                ValidationLevel.MODEL,
            )

        expected_dependencies = {
            "ensemble.selected_models[0]": demucs,
            "ensemble.selected_models[1]": peer,
            "demucs.voc_inst_secondary_model": helper,
        }
        self.assertEqual(plan.model_dependencies, expected_dependencies)
        self.assertEqual(
            plan.model_identity_digest,
            compute_model_identity_digest(expected_dependencies),
        )

        asked: list[str] = []

        def fake_determine(
            _settings: object,
            _repo: object,
            _method: object,
            stem: object,
            dependencies: object = None,
        ) -> tuple[None, None]:
            self.assertIs(dependencies, plan.model_dependencies)
            asked.append(str(stem))
            return None, None

        with patch(
            "core.model_config.determine.process_determine_secondary_model",
            side_effect=fake_determine,
        ):
            runtime = ModelConfig(
                settings,
                Mock(),
                demucs.display,
                identity=demucs,
                is_dry_check=True,
                model_dependencies=plan.model_dependencies,
            )

        self.assertEqual(runtime.process_method, DEMUCS_ARCH_TYPE)
        self.assertFalse(runtime.is_demucs_4_stem_secondaries)
        self.assertEqual(asked, ["Vocals"])
