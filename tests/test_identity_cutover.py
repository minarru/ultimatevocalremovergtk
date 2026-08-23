from __future__ import annotations

import unittest
from typing import Any

from core.job_plan import JobResolver, JobSpec, ValidationLevel
from core.model_identity import IdentityIndex, ModelArtifacts, ModelRecord
from core.settings import Settings
from core.settings.defaults import default_settings_dict
from core.types import ProcessMethod


class KeepTextCutoverTests(unittest.TestCase):
    def test_display_in_settings_is_preserved(self) -> None:
        payload = default_settings_dict()
        payload["mdx"]["model"] = "MDX-Net — UVR-MDX-NET Inst HQ 4"
        settings = Settings.from_json_dict(payload)
        self.assertEqual(settings.mdx.model, "MDX-Net — UVR-MDX-NET Inst HQ 4")
        self.assertNotIn("identity_schema_version", settings.to_json_dict())

    def test_sparse_cli_profile_is_not_inflated(self) -> None:
        import json
        import tempfile
        from unittest.mock import patch
        from cli.profiles import load_profile, PROFILE_SCHEMA_VERSION
        from core.settings import Settings

        payload = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "name": "sparse",
            "model": "mdx:UVR-MDX-NET-Inst_HQ_4",
            "members": [],
            "settings": {"process.vocal_splitter": "vr:UVR-De-Echo-Normal"},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = handle.name
        real = Settings.from_json_dict

        def wrapped(data: Any) -> Settings:
            if isinstance(data, dict) and data.get("model") == payload["model"]:
                raise AssertionError("sparse profile fed to Settings.from_json_dict")
            return real(data)

        with patch.object(Settings, "from_json_dict", side_effect=wrapped):
            _settings, loaded = load_profile(path)
        self.assertEqual(loaded.model, "mdx:UVR-MDX-NET-Inst_HQ_4")
        self.assertEqual(
            loaded.settings["process.vocal_splitter"], "vr:UVR-De-Echo-Normal"
        )

    def test_sparse_cli_profile_keeps_illegal_text_with_transient_warnings(self) -> None:
        import json
        import tempfile
        from cli.profiles import PROFILE_SCHEMA_VERSION, load_profile

        payload = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "name": "illegal",
            "model": None,
            "members": ["Demucs: htdemucs"],
            "settings": {"process.vocal_splitter": "VR: Splitter"},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = handle.name

        _settings, loaded = load_profile(path)

        self.assertIsNone(loaded.model)
        self.assertEqual(loaded.members, ["Demucs: htdemucs"])
        self.assertEqual(loaded.settings["process.vocal_splitter"], "VR: Splitter")
        self.assertEqual(len(loaded.validation_warnings), 2)
        self.assertNotIn("validation_warnings", loaded.to_dict())

    def test_sparse_cli_profile_keeps_illegal_primary_text(self) -> None:
        import json
        import tempfile
        from cli.profiles import PROFILE_SCHEMA_VERSION, load_profile

        payload = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "name": "illegal-primary",
            "model": "MDX-Net: Model A",
            "members": [],
            "settings": {},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = handle.name

        _settings, loaded = load_profile(path)

        self.assertEqual(loaded.model, "MDX-Net: Model A")
        self.assertEqual(len(loaded.validation_warnings), 1)

    def test_sparse_cli_profile_validates_apollo_in_its_native_shape(self) -> None:
        import json
        import tempfile
        from unittest.mock import patch
        from cli.profiles import PROFILE_SCHEMA_VERSION, load_profile

        payload = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "name": "illegal-apollo",
            "model": None,
            "members": [],
            "settings": {"audio_tools.apollo_model": "Apollo: Restoration Model"},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = handle.name
        real = Settings.from_json_dict

        def wrapped(data: Any) -> Settings:
            if isinstance(data, dict) and "settings" in data:
                raise AssertionError("sparse profile fed to Settings.from_json_dict")
            return real(data)

        with patch.object(Settings, "from_json_dict", side_effect=wrapped):
            settings, loaded = load_profile(path)

        self.assertEqual(
            loaded.settings["audio_tools.apollo_model"],
            "Apollo: Restoration Model",
        )
        self.assertEqual(settings.audio_tools.apollo_model, "Apollo: Restoration Model")
        self.assertTrue(
            any("audio_tools.apollo_model" in item for item in loaded.validation_warnings)
        )
        self.assertTrue(
            any("audio_tools.apollo_model" in item for item in settings.validation_warnings)
        )
        self.assertNotIn("validation_warnings", loaded.to_dict())
        self.assertNotIn("validation_warnings", settings.to_json_dict())

    def test_repository_validation_preserves_unknown_canonical_text(self) -> None:
        settings = Settings.defaults()
        settings.mdx.model = "mdx:not-installed"

        warnings = settings.validate_model_references(IdentityIndex({}))

        self.assertEqual(settings.mdx.model, "mdx:not-installed")
        self.assertTrue(any("unknown model" in item for item in warnings))

    def test_non_string_model_value_is_preserved_with_a_warning(self) -> None:
        payload = default_settings_dict()
        payload["mdx"]["model"] = ["not", "a", "string"]

        settings = Settings.from_json_dict(payload)

        self.assertEqual(settings.mdx.model, ["not", "a", "string"])
        self.assertTrue(any("mdx.model" in item for item in settings.validation_warnings))

    def test_legacy_flat_settings_keep_illegal_model_text_with_a_warning(self) -> None:
        settings = Settings.from_flat({"mdx_net_model": "MDX-Net: Model A"})

        self.assertEqual(settings.mdx.model, "MDX-Net: Model A")
        self.assertTrue(any("mdx.model" in item for item in settings.validation_warnings))

    def test_repository_validation_checks_installation_completeness_and_family(self) -> None:
        settings = Settings.defaults()
        settings.mdx.model = "vr:wrong-family"
        settings.demucs.model = "demucs:incomplete"
        settings.ensemble.selected_models = ["mdx:missing-artifact"]
        records = {
            "vr:wrong-family": ModelRecord(
                id="vr:wrong-family",
                family="vr",
                basename="wrong-family",
                display="Wrong family",
                backend_name="wrong-family",
                artifacts=ModelArtifacts("wrong-family.pth"),
                installed=True,
            ),
            "demucs:incomplete": ModelRecord(
                id="demucs:incomplete",
                family="demucs",
                basename="incomplete",
                display="Incomplete",
                backend_name="incomplete",
                artifacts=ModelArtifacts("incomplete.th"),
                installed=True,
                identity_complete=False,
                identity_error="demucs_version is unknown",
            ),
            "mdx:missing-artifact": ModelRecord(
                id="mdx:missing-artifact",
                family="mdx",
                basename="missing-artifact",
                display="Missing artifact",
                backend_name="missing-artifact",
                artifacts=ModelArtifacts("missing-artifact.onnx"),
                installed=False,
            ),
        }

        warnings = settings.validate_model_references(IdentityIndex(records))

        self.assertTrue(any("mdx.model" in item and "family mdx" in item for item in warnings))
        self.assertTrue(any("demucs_version is unknown" in item for item in warnings))
        self.assertTrue(any("not installed" in item for item in warnings))

    def test_stage_two_planning_rejects_an_uninstalled_record(self) -> None:
        record = ModelRecord(
            id="mdx:catalog-only",
            family="mdx",
            basename="catalog-only",
            display="Catalog only",
            backend_name="catalog-only",
            artifacts=ModelArtifacts("catalog-only.onnx"),
            installed=False,
        )

        plan = self._config_plan(record)

        self.assertTrue(
            any("not installed" in item.message for item in plan.diagnostics)
        )

    def test_stage_two_planning_rejects_an_incomplete_identity(self) -> None:
        record = ModelRecord(
            id="mdx:incomplete",
            family="mdx",
            basename="incomplete",
            display="Incomplete",
            backend_name="incomplete",
            artifacts=ModelArtifacts("incomplete.ckpt"),
            installed=True,
            identity_complete=False,
            identity_error="mdx_kind is unknown",
        )

        plan = self._config_plan(record)

        self.assertTrue(
            any("mdx_kind is unknown" in item.message for item in plan.diagnostics)
        )

    def _config_plan(self, record: ModelRecord) -> Any:
        import os
        import tempfile

        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = record.id
        resolver = JobResolver(object())
        resolver.identities = IdentityIndex({record.id: record})  # type: ignore[assignment]
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "song.wav")
            open(source, "wb").close()
            return resolver.resolve(
                JobSpec("separate", settings, (source,), root, {}),
                ValidationLevel.CONFIG,
            )

    def test_saved_ensemble_reader_keeps_illegal_member_and_writer_omits_version(self) -> None:
        import json
        import os
        import tempfile
        from unittest.mock import patch
        from core import ensemble_service, paths

        with tempfile.TemporaryDirectory() as root, patch.object(
            paths, "ENSEMBLE_CACHE_DIR", root
        ):
            saved_path = ensemble_service.save_ensemble(
                "canonical", "vocals_instrumental", "Max Spec", ["mdx:model-a"]
            )
            with open(saved_path, encoding="utf-8") as handle:
                self.assertNotIn("identity_schema_version", json.load(handle))

            illegal_path = os.path.join(root, "illegal.json")
            with open(illegal_path, "w", encoding="utf-8") as handle:
                json.dump({"selected_models": ["MDX-Net: Model A"]}, handle)
            loaded = ensemble_service.load_ensemble("illegal")
            preset = ensemble_service.EnsembleService(object()).resolve("illegal")

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["selected_models"], ["MDX-Net: Model A"])
        self.assertTrue(any("selected_models[0]" in item for item in loaded.validation_warnings))
        self.assertEqual(preset.validation_warnings, tuple(loaded.validation_warnings))

    def test_saved_ensemble_keeps_nonstring_member_through_resolve_and_apply(self) -> None:
        import json
        import os
        import tempfile
        from unittest.mock import patch
        from core import ensemble_service, paths

        member = {"legacy": ["model", 17]}
        with tempfile.TemporaryDirectory() as root, patch.object(
            paths, "ENSEMBLE_CACHE_DIR", root
        ):
            with open(os.path.join(root, "nonstring.json"), "w", encoding="utf-8") as handle:
                json.dump({"selected_models": [member]}, handle)
            loaded = ensemble_service.load_ensemble("nonstring")
            service = ensemble_service.EnsembleService(object())
            preset = service.resolve("nonstring")
            settings = Settings.defaults()
            applied = service.apply(settings, "nonstring")

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["selected_models"], [member])
        self.assertIsInstance(preset.members[0], dict)
        self.assertEqual(preset.members[0], member)
        self.assertEqual(settings.ensemble.selected_models, [member])
        self.assertIsInstance(settings.ensemble.selected_models[0], dict)
        self.assertEqual(applied.validation_warnings, tuple(loaded.validation_warnings))
        self.assertTrue(any("selected_models[0]" in item for item in applied.validation_warnings))

    def test_saved_ensemble_exact_missing_member_adds_field_warning(self) -> None:
        import tempfile
        from unittest.mock import patch

        from core import ensemble_service, paths

        def record(model_id: str) -> ModelRecord:
            family, basename = model_id.split(":", 1)
            return ModelRecord(
                id=model_id,
                family=family,
                basename=basename,
                display=basename,
                backend_name=basename,
                artifacts=ModelArtifacts(f"{basename}.onnx"),
                installed=True,
            )

        first = record("mdx:first")
        second = record("mdx:second")
        missing = "mdx:missing"
        index = IdentityIndex({first.id: first, second.id: second})

        class ExactResolver:
            def resolve(self, value: str) -> ModelRecord:
                return index.lookup(value)

        with tempfile.TemporaryDirectory() as root, patch.object(
            paths, "ENSEMBLE_CACHE_DIR", root
        ):
            ensemble_service.save_ensemble(
                "missing-member",
                "vocals_instrumental",
                "Max Spec/Min Spec",
                [first.id, second.id, missing],
            )
            service = ensemble_service.EnsembleService(object())
            service.identities = ExactResolver()  # type: ignore[assignment]
            preset = service.resolve("missing-member")

        self.assertEqual(preset.members, (first.id, second.id, missing))
        matching = [
            warning for warning in preset.validation_warnings
            if "selected_models[2]" in warning
        ]
        self.assertEqual(len(matching), 1, preset.validation_warnings)
        self.assertIn(missing, matching[0])


class ReplayManifestContractTests(unittest.TestCase):
    _EMPTY_DIGEST = (
        "sha256:44136fa355b3678a1146ad16f7e8649e"
        "94fb4fc21fe77e8310c060f61caaff8a"
    )
    _RECORDED_DIGEST = "sha256:" + "1" * 64
    _CURRENT_DIGEST = "sha256:" + "2" * 64

    @staticmethod
    def _args(path: str, *, allow_model_change: bool = False) -> Any:
        import argparse

        return argparse.Namespace(
            manifest=path,
            output=None,
            on_exists=None,
            allow_model_change=allow_model_change,
            offline=False,
            report="json",
            quiet=True,
            verbose=False,
            job_id="replay-test",
        )

    @classmethod
    def _manifest(cls) -> dict[str, Any]:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:primary"
        return {
            "schema_version": 3,
            "job_id": "recorded-job",
            "command": "separate",
            "model_dependencies": {"mdx.model": "mdx:primary"},
            "model_identity_digest": cls._RECORDED_DIGEST,
            "settings": settings.to_json_dict(),
            "plan": {
                "models": [{"id": "mdx:primary", "checkpoint_hash": "old-hash"}],
            },
            "job_spec": {
                "inputs": ["/recorded/song.wav"],
                "output": "/recorded/out",
                # Replay must use the validated dependency ID, not this legacy text.
                "model": "MDX-Net: Primary",
                "collision_policy": "fail",
            },
        }

    @classmethod
    def _ensemble_manifest(
        cls, indices: tuple[int, ...] = (0, 1)
    ) -> dict[str, Any]:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        members = [f"mdx:member-{index}" for index in indices]
        settings.ensemble.selected_models = members
        return {
            "schema_version": 3,
            "job_id": "recorded-ensemble",
            "command": "ensemble",
            "model_dependencies": {
                f"ensemble.selected_models[{index}]": model_id
                for index, model_id in zip(indices, members)
            },
            "model_identity_digest": cls._RECORDED_DIGEST,
            "settings": settings.to_json_dict(),
            "plan": {
                "models": [
                    {"id": model_id, "checkpoint_hash": f"hash-{index}"}
                    for index, model_id in zip(indices, members)
                ],
            },
            "job_spec": {
                "inputs": ["/recorded/song.wav"],
                "output": "/recorded/out",
                "members": members,
                "collision_policy": "fail",
            },
        }

    @classmethod
    def _audio_manifest(
        cls,
        tool: str,
        dependencies: dict[str, str],
        digest: str,
    ) -> dict[str, Any]:
        settings = Settings.defaults()
        if "audio_tools.apollo_model" in dependencies:
            settings.audio_tools.apollo_model = dependencies[
                "audio_tools.apollo_model"
            ]
        return {
            "schema_version": 3,
            "job_id": "recorded-audio",
            "command": "audio",
            "model_dependencies": dependencies,
            "model_identity_digest": digest,
            "settings": settings.to_json_dict(),
            "plan": {"model": None},
            "job_spec": {
                "tool": tool,
                "inputs": ["/recorded/song.wav"],
                "output": "/recorded/out",
                "collision_policy": "fail",
            },
        }

    def _invoke_without_child(
        self, manifest: dict[str, Any], *, allow_model_change: bool = False
    ) -> tuple[int, dict[str, Any]]:
        import io
        import json
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout
        from unittest.mock import patch

        from cli.replay import cmd_run

        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(manifest, handle)
            handle.flush()
            stdout = io.StringIO()
            with patch(
                "cli.replay._run",
                side_effect=AssertionError("replay child must not run"),
            ), redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                code = cmd_run(
                    self._args(handle.name, allow_model_change=allow_model_change)
                )
        return code, json.loads(stdout.getvalue())

    def _invoke_with_successful_child(
        self,
        manifest: dict[str, Any],
        *,
        allow_model_change: bool = False,
    ) -> tuple[int, dict[str, Any], int, list[dict[str, Any]]]:
        import io
        import json
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout
        from unittest.mock import patch

        from cli.replay import cmd_run

        calls = 0
        profiles: list[dict[str, Any]] = []
        checked_plan = dict(manifest.get("plan") or {})
        checked_plan["model_dependencies"] = dict(
            manifest["model_dependencies"]
        )
        checked_plan["model_identity_digest"] = manifest[
            "model_identity_digest"
        ]

        def run_child(argv: list[str]) -> tuple[int, dict[str, Any], str]:
            nonlocal calls
            calls += 1
            profile_index = argv.index("--profile") + 1
            with open(argv[profile_index], encoding="utf-8") as profile_handle:
                profiles.append(json.load(profile_handle))
            if "--dry-run" in argv:
                return 0, {"plan": checked_plan}, ""
            return 0, {"ok": True, "status": "success"}, ""

        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(manifest, handle)
            handle.flush()
            stdout = io.StringIO()
            with patch("cli.replay._run", side_effect=run_child), redirect_stdout(
                stdout
            ), redirect_stderr(io.StringIO()):
                code = cmd_run(
                    self._args(
                        handle.name, allow_model_change=allow_model_change
                    )
                )
        return code, json.loads(stdout.getvalue()), calls, profiles

    def test_override_cannot_admit_noncanonical_empty_digest(self) -> None:
        manifest = self._audio_manifest("stretch", {}, self._CURRENT_DIGEST)

        code, payload, calls, _profiles = self._invoke_with_successful_child(
            manifest, allow_model_change=True
        )

        self.assertEqual(code, 2)
        self.assertEqual(calls, 0)
        self.assertIn("empty", payload["error"]["message"])
        self.assertIn("identity digest", payload["error"]["message"])

    def test_command_dependency_topology_is_validated_before_child(self) -> None:
        separate = self._manifest()
        separate["model_dependencies"] = {}
        separate["model_identity_digest"] = self._EMPTY_DIGEST

        ensemble_short = self._ensemble_manifest((0,))
        ensemble_gapped = self._ensemble_manifest((0, 2))
        restore_empty = self._audio_manifest(
            "restore", {}, self._EMPTY_DIGEST
        )
        model_free_apollo = self._audio_manifest(
            "stretch",
            {"audio_tools.apollo_model": "apollo:restorer"},
            self._RECORDED_DIGEST,
        )
        cases = (
            ("separate-primary", separate, "one primary"),
            ("ensemble-short", ensemble_short, "at least two"),
            ("ensemble-gapped", ensemble_gapped, "contiguous"),
            ("restore-model", restore_empty, "Apollo"),
            ("model-free-audio", model_free_apollo, "model-free"),
        )
        for name, manifest, message in cases:
            with self.subTest(name=name):
                code, payload, calls, _profiles = (
                    self._invoke_with_successful_child(manifest)
                )

                self.assertEqual(code, 2)
                self.assertEqual(calls, 0)
                self.assertIn(message, payload["error"]["message"])

    def test_missing_active_dependency_is_rejected_before_child(self) -> None:
        separate = self._manifest()
        separate["settings"]["process"]["vocal_splitter_enabled"] = True
        separate["settings"]["process"]["vocal_splitter"] = "vr:splitter"

        ensemble = self._ensemble_manifest()
        ensemble["settings"]["process"]["vocal_splitter_enabled"] = True
        ensemble["settings"]["process"]["vocal_splitter"] = "vr:splitter"

        for command, manifest in (("separate", separate), ("ensemble", ensemble)):
            with self.subTest(command=command):
                code, payload, calls, _profiles = (
                    self._invoke_with_successful_child(manifest)
                )

                self.assertEqual(code, 2)
                self.assertEqual(calls, 0)
                self.assertIn("process.vocal_splitter", payload["error"]["message"])

    def test_extra_inactive_dependency_is_rejected_before_child(self) -> None:
        manifest = self._manifest()
        manifest["model_dependencies"]["process.vocal_splitter"] = "vr:splitter"

        code, payload, calls, _profiles = self._invoke_with_successful_child(
            manifest
        )

        self.assertEqual(code, 2)
        self.assertEqual(calls, 0)
        self.assertIn("process.vocal_splitter", payload["error"]["message"])

    def test_replay_topology_uses_recorded_native_primary_stem(self) -> None:
        from cli.replay import _validate_active_dependency_paths

        manifest = self._manifest()
        manifest["settings"]["mdx"]["stems"] = "Drums"
        manifest["settings"]["mdx"]["is_secondary_model_activate"] = True
        manifest["settings"]["mdx"]["voc_inst_secondary_model"] = (
            "mdx:voc-inst-helper"
        )
        manifest["settings"]["mdx"]["drums_secondary_model"] = (
            "mdx:drums-helper"
        )
        manifest["plan"]["models"][0]["primary_stem"] = "instrumental"
        dependencies = {
            "mdx.model": "mdx:primary",
            "mdx.voc_inst_secondary_model": "mdx:voc-inst-helper",
        }

        _validate_active_dependency_paths(manifest, "separate", dependencies)

        del manifest["plan"]["models"][0]["primary_stem"]
        with self.assertRaisesRegex(ValueError, "missing mdx.drums_secondary_model"):
            _validate_active_dependency_paths(manifest, "separate", dependencies)

    def test_ensemble_replay_unions_same_family_native_slots(self) -> None:
        from cli.replay import _validate_active_dependency_paths

        manifest = self._ensemble_manifest()
        manifest["settings"]["mdx"]["is_secondary_model_activate"] = True
        manifest["settings"]["mdx"]["voc_inst_secondary_model"] = "mdx:voc-helper"
        manifest["settings"]["mdx"]["other_secondary_model"] = "mdx:other-helper"
        manifest["plan"]["models"][0]["primary_stem"] = "Vocals"
        manifest["plan"]["models"][1]["primary_stem"] = "other"
        dependencies = dict(manifest["model_dependencies"])
        dependencies.update({
            "mdx.voc_inst_secondary_model": "mdx:voc-helper",
            "mdx.other_secondary_model": "mdx:other-helper",
        })

        _validate_active_dependency_paths(manifest, "ensemble", dependencies)

        del dependencies["mdx.other_secondary_model"]
        with self.assertRaisesRegex(ValueError, "missing mdx.other_secondary_model"):
            _validate_active_dependency_paths(manifest, "ensemble", dependencies)

    def test_sparse_profiles_copy_identities_only_from_dependency_map(self) -> None:
        separate = self._manifest()
        separate["settings"]["process"]["vocal_splitter"] = "vr:stale-splitter"
        separate["settings"]["mdx"]["voc_inst_secondary_model"] = (
            "vr:stale-secondary"
        )
        separate["settings"]["demucs"]["pre_proc_model"] = "mdx:stale-pre"

        ensemble = self._ensemble_manifest()
        ensemble["settings"]["process"]["vocal_splitter"] = "vr:stale-splitter"
        ensemble["settings"]["mdx"]["voc_inst_secondary_model"] = (
            "vr:stale-secondary"
        )

        audio = self._audio_manifest(
            "restore",
            {"audio_tools.apollo_model": "apollo:restorer"},
            self._RECORDED_DIGEST,
        )
        audio["settings"]["audio_tools"]["apollo_model"] = "apollo:stale"

        cases = (
            (
                "separate",
                separate,
                {
                    "process.vocal_splitter",
                    "mdx.voc_inst_secondary_model",
                    "demucs.pre_proc_model",
                },
            ),
            (
                "ensemble",
                ensemble,
                {
                    "process.vocal_splitter",
                    "mdx.voc_inst_secondary_model",
                },
            ),
            ("apollo", audio, {"audio_tools.apollo_model"}),
        )
        for name, manifest, forbidden in cases:
            with self.subTest(name=name):
                code, _payload, calls, profiles = (
                    self._invoke_with_successful_child(manifest)
                )

                self.assertEqual(code, 0)
                self.assertEqual(calls, 2)
                self.assertTrue(profiles)
                self.assertTrue(forbidden.isdisjoint(profiles[0]["settings"]))
                if name == "separate":
                    self.assertEqual(profiles[0]["model"], "mdx:primary")
                elif name == "ensemble":
                    self.assertEqual(
                        profiles[0]["members"],
                        ["mdx:member-0", "mdx:member-1"],
                    )
                else:
                    self.assertEqual(profiles[0]["model"], "apollo:restorer")

    def test_separation_writer_emits_schema_3_identity_contract(self) -> None:
        import argparse
        import json
        import os
        import tempfile

        from cli.execution import BatchOutcome, write_manifest
        from cli.job import ResolvedJob
        from cli.profiles import LoadedProfile

        settings = Settings.defaults()
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "manifest.json")
            job = ResolvedJob(
                command="separate",
                settings=settings,
                profile=LoadedProfile("defaults", "built-in"),
                inputs=["/recorded/song.wav"],
                output=root,
                plan={
                    "model_dependencies": {"mdx.model": "mdx:primary"},
                    "model_identity_digest": self._RECORDED_DIGEST,
                },
            )
            write_manifest(
                argparse.Namespace(
                    manifest_out=path,
                    manifest=False,
                    job_id="writer-test",
                    on_exists="fail",
                ),
                job,
                BatchOutcome("success", 0.25),
            )
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)

        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(
            payload["model_dependencies"], {"mdx.model": "mdx:primary"}
        )
        self.assertEqual(payload["model_identity_digest"], self._RECORDED_DIGEST)

    def test_audio_writer_emits_empty_identity_contract_without_a_model(self) -> None:
        import argparse
        import json
        import os
        import tempfile
        from types import SimpleNamespace

        from cli.audio import _write_audio_manifest
        from cli.execution import BatchOutcome

        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "manifest.json")
            plan = SimpleNamespace(
                output=root,
                units=(SimpleNamespace(inputs=("/recorded/song.wav",)),),
                model=None,
                to_dict=lambda: {
                    "command": "audio",
                    "model": None,
                    "model_dependencies": {},
                    "model_identity_digest": self._EMPTY_DIGEST,
                },
            )
            _write_audio_manifest(
                argparse.Namespace(
                    manifest_out=path,
                    manifest=False,
                    job_id="audio-writer-test",
                    audio_command="stretch",
                    original_argv=[],
                    on_exists="fail",
                ),
                plan,
                BatchOutcome("success", 0.25),
            )
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)

        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(payload["model_dependencies"], {})
        self.assertEqual(payload["model_identity_digest"], self._EMPTY_DIGEST)

    def test_audio_writer_emits_apollo_dependency_and_semantic_digest(self) -> None:
        import argparse
        import json
        import os
        import tempfile
        from types import SimpleNamespace

        from cli.audio import _write_audio_manifest
        from cli.execution import BatchOutcome
        from core.job_plan import ModelDescriptor
        from core.model_identity import ModelArtifacts

        model = ModelDescriptor(
            id="apollo:restorer",
            family="apollo",
            basename="restorer",
            display="Restorer",
            backend_name="restorer.ckpt",
            artifacts=ModelArtifacts("restorer.ckpt"),
        )
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "manifest.json")
            plan = SimpleNamespace(
                output=root,
                units=(SimpleNamespace(inputs=("/recorded/song.wav",)),),
                model=model,
                to_dict=lambda: {
                    "command": "audio",
                    "model": None,
                    "model_dependencies": {
                        "audio_tools.apollo_model": "apollo:restorer"
                    },
                    "model_identity_digest": (
                        "sha256:6237d0e7483c76dc8c0cb6860acfd195"
                        "b817e4ce1b92b7c5159ff58d6047fcd2"
                    ),
                },
            )
            _write_audio_manifest(
                argparse.Namespace(
                    manifest_out=path,
                    manifest=False,
                    job_id="audio-writer-test",
                    audio_command="restore",
                    original_argv=[],
                    on_exists="fail",
                ),
                plan,
                BatchOutcome("success", 0.25),
            )
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)

        self.assertEqual(
            payload["model_dependencies"],
            {"audio_tools.apollo_model": "apollo:restorer"},
        )
        self.assertEqual(
            payload["model_identity_digest"],
            "sha256:6237d0e7483c76dc8c0cb6860acfd195"
            "b817e4ce1b92b7c5159ff58d6047fcd2",
        )

    def test_apollo_plan_carries_artifacts_used_by_manifest_digest(self) -> None:
        from unittest.mock import Mock

        from core.audio_plan import AudioJobResolver
        from core.job_plan import ValidationLevel

        artifacts = ModelArtifacts("restorer.ckpt", ("restorer.yaml",))
        record = ModelRecord(
            id="apollo:restorer",
            family="apollo",
            basename="restorer",
            display="Restorer",
            backend_name="restorer.ckpt",
            artifacts=artifacts,
            installed=True,
        )
        resolver = AudioJobResolver(Mock())
        resolver.identities = Mock()
        resolver.identities.lookup.return_value = record
        settings = Settings.defaults()
        settings.audio_tools.apollo_model = record.id

        descriptor = resolver._resolve_apollo(
            settings, [], ValidationLevel.CONFIG
        )

        self.assertIsNotNone(descriptor)
        assert descriptor is not None
        self.assertEqual(descriptor.artifacts, artifacts)

    def test_schema_1_is_a_compatibility_error_even_with_override(self) -> None:
        manifest = self._manifest()
        manifest["schema_version"] = 1

        code, payload = self._invoke_without_child(
            manifest, allow_model_change=True
        )

        self.assertEqual(code, 2)
        self.assertIn("schema 1", payload["error"]["message"])
        self.assertIn("schema 3", payload["error"]["message"])

    def test_schema_3_requires_dependency_map_and_digest(self) -> None:
        for field in ("model_dependencies", "model_identity_digest"):
            with self.subTest(field=field):
                manifest = self._manifest()
                del manifest[field]

                code, payload = self._invoke_without_child(manifest)

                self.assertEqual(code, 2)
                self.assertIn(field, payload["error"]["message"])

    def test_schema_3_rejects_malformed_identity_fields(self) -> None:
        cases = (
            ("model_dependencies", [], "must be an object"),
            ("model_identity_digest", "sha256:not-a-digest", "sha256: digest"),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                manifest = self._manifest()
                manifest[field] = value

                code, payload = self._invoke_without_child(manifest)

                self.assertEqual(code, 2)
                self.assertIn(message, payload["error"]["message"])

    def test_dependency_path_is_rejected_before_child_resolution(self) -> None:
        manifest = self._manifest()
        manifest["model_dependencies"] = {"mdx.not_a_model_slot": "mdx:primary"}

        code, payload = self._invoke_without_child(manifest)

        self.assertEqual(code, 2)
        self.assertIn("mdx.not_a_model_slot", payload["error"]["message"])
        self.assertIn("dependency path", payload["error"]["message"])

    def test_dependency_family_is_rejected_even_with_override(self) -> None:
        manifest = self._manifest()
        manifest["model_dependencies"] = {"mdx.model": "vr:wrong-family"}

        code, payload = self._invoke_without_child(
            manifest, allow_model_change=True
        )

        self.assertEqual(code, 2)
        self.assertIn("mdx.model", payload["error"]["message"])
        self.assertIn("family mdx", payload["error"]["message"])

    def test_illegal_dependency_id_is_rejected_even_with_override(self) -> None:
        manifest = self._manifest()
        manifest["model_dependencies"] = {"mdx.model": "MDX-Net: Primary"}

        code, payload = self._invoke_without_child(
            manifest, allow_model_change=True
        )

        self.assertEqual(code, 2)
        self.assertIn("canonical model ID", payload["error"]["message"])

    def test_semantic_digest_drift_requires_override(self) -> None:
        import io
        import json
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout
        from unittest.mock import patch

        from cli.replay import cmd_run

        manifest = self._manifest()
        checked = {
            "plan": {
                "model_dependencies": {"mdx.model": "mdx:primary"},
                "model_identity_digest": self._CURRENT_DIGEST,
                "models": [
                    {"id": "mdx:primary", "checkpoint_hash": "old-hash"}
                ],
            }
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(manifest, handle)
            handle.flush()
            stdout = io.StringIO()
            with patch("cli.replay._run", return_value=(0, checked, "")), redirect_stdout(
                stdout
            ), redirect_stderr(io.StringIO()):
                code = cmd_run(self._args(handle.name))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 2)
        self.assertIn("identity digest changed", payload["error"]["message"])
        self.assertEqual(
            payload["model_changes"]["model_identity_digest"],
            {"recorded": self._RECORDED_DIGEST, "current": self._CURRENT_DIGEST},
        )

    def test_malformed_current_identity_contract_is_a_structured_error(self) -> None:
        import io
        import json
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout
        from unittest.mock import patch

        from cli.replay import cmd_run

        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(self._manifest(), handle)
            handle.flush()
            stdout = io.StringIO()
            with patch(
                "cli.replay._run", return_value=(0, {"plan": {}}, "")
            ), redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                code = cmd_run(self._args(handle.name))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 2)
        self.assertIn("model_dependencies", payload["error"]["message"])

    def test_override_cannot_accept_a_missing_current_dependency(self) -> None:
        import io
        import json
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout
        from unittest.mock import patch

        from cli.replay import cmd_run

        checked = {
            "plan": {
                "model_dependencies": {},
                "model_identity_digest": self._EMPTY_DIGEST,
                "models": [],
            }
        }
        calls = 0

        def run_child(_argv: list[str]) -> tuple[int, dict[str, Any], str]:
            nonlocal calls
            calls += 1
            return 0, checked, ""

        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(self._manifest(), handle)
            handle.flush()
            stdout = io.StringIO()
            with patch("cli.replay._run", side_effect=run_child), redirect_stdout(
                stdout
            ), redirect_stderr(io.StringIO()):
                code = cmd_run(
                    self._args(handle.name, allow_model_change=True)
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(calls, 1)
        self.assertIn("dependencies changed", payload["error"]["message"])

    def test_override_reports_hash_and_digest_drift_and_replays_exact_id(self) -> None:
        import io
        import json
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout
        from unittest.mock import patch

        from cli.replay import cmd_run

        manifest = self._manifest()
        checked = {
            "plan": {
                "model_dependencies": {"mdx.model": "mdx:primary"},
                "model_identity_digest": self._CURRENT_DIGEST,
                "models": [
                    {"id": "mdx:primary", "checkpoint_hash": "new-hash"}
                ],
            }
        }
        captured_profile: dict[str, Any] = {}
        calls = 0

        def run_child(argv: list[str]) -> tuple[int, dict[str, Any], str]:
            nonlocal calls
            calls += 1
            profile_index = argv.index("--profile") + 1
            with open(argv[profile_index], encoding="utf-8") as profile_handle:
                captured_profile.update(json.load(profile_handle))
            if "--dry-run" in argv:
                return 0, checked, ""
            return 0, {"ok": True, "status": "success"}, ""

        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(manifest, handle)
            handle.flush()
            stdout = io.StringIO()
            with patch("cli.replay._run", side_effect=run_child), redirect_stdout(
                stdout
            ), redirect_stderr(io.StringIO()):
                code = cmd_run(
                    self._args(handle.name, allow_model_change=True)
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(calls, 2)
        self.assertEqual(captured_profile["model"], "mdx:primary")
        self.assertEqual(
            payload["model_changes"],
            {
                "checkpoint_hashes": {
                    "recorded": {"mdx:primary": "old-hash"},
                    "current": {"mdx:primary": "new-hash"},
                },
                "model_identity_digest": {
                    "recorded": self._RECORDED_DIGEST,
                    "current": self._CURRENT_DIGEST,
                },
            },
        )


if __name__ == "__main__":
    unittest.main()


class ValidationWarningSurfacingTests(unittest.TestCase):
    """Stage-2 validation ran nowhere and its warnings were never printed.

    A preserved illegal or uninstalled stored value is invisible by design --
    no writer replaces it -- so without a surfaced warning the CLI silently
    ignores it and the GUI shows an unexplained "Choose Model".
    """

    def test_warn_validation_prints_a_stderr_block_with_the_lookup_hint(self) -> None:
        import argparse
        import io
        from contextlib import redirect_stderr

        from cli.reporting import warn_validation

        args = argparse.Namespace(report="human", quiet=False)
        err = io.StringIO()
        with redirect_stderr(err):
            warn_validation(args, ["mdx.model: preserved 'MDX-Net: Kim Vocal 2'"])
        text = err.getvalue()
        self.assertIn("mdx.model", text)
        self.assertIn("uvr models list", text)

    def test_warn_validation_is_silent_when_quiet_or_empty(self) -> None:
        import argparse
        import io
        from contextlib import redirect_stderr

        from cli.reporting import warn_validation

        err = io.StringIO()
        with redirect_stderr(err):
            warn_validation(argparse.Namespace(report="human", quiet=True), ["x"])
            warn_validation(argparse.Namespace(report="human", quiet=False), [])
            warn_validation(argparse.Namespace(report="human", quiet=False), None)
        self.assertEqual(err.getvalue(), "")

    def test_stored_identity_warnings_runs_stage_two_against_the_index(self) -> None:
        from unittest import mock
        from unittest.mock import patch

        from cli.job import stored_identity_warnings
        from cli.profiles import LoadedProfile
        from core.model_identity import (
            IdentityIndex,
            ModelArtifacts,
            ModelIdentityService,
            ModelRecord,
        )

        record = ModelRecord(
            id="mdx:known",
            family="mdx",
            basename="known",
            display="Known",
            backend_name="known",
            artifacts=ModelArtifacts("known.onnx"),
            installed=False,
        )
        settings = Settings.defaults()
        settings.mdx.model = "mdx:known"
        profile = LoadedProfile(
            name="p", source="profile",
            validation_warnings=["mdx.model: syntax note"],
        )
        index = IdentityIndex({record.id: record})
        with patch.object(
            ModelIdentityService, "_published_index", return_value=index
        ):
            warnings = stored_identity_warnings(settings, mock.Mock(), profile)

        self.assertIn("mdx.model: syntax note", warnings)
        self.assertTrue(
            any("is not installed" in item for item in warnings), warnings
        )

    def test_stage_two_does_not_repeat_a_stage_one_syntax_complaint(self) -> None:
        from unittest import mock
        from unittest.mock import patch

        from cli.job import stored_identity_warnings
        from cli.profiles import LoadedProfile
        from core.model_identity import IdentityIndex, ModelIdentityService

        settings = Settings.defaults()
        settings.mdx.voc_inst_secondary_model = "MDX-Net: Kim Vocal 2"
        profile = LoadedProfile(
            name="p", source="profile",
            validation_warnings=[
                "mdx.voc_inst_secondary_model: expected canonical model ID "
                "family:basename or a permitted sentinel; preserved "
                "'MDX-Net: Kim Vocal 2'; run 'uvr models list' to find IDs"
            ],
        )
        with patch.object(
            ModelIdentityService, "_published_index", return_value=IdentityIndex({})
        ):
            warnings = stored_identity_warnings(settings, mock.Mock(), profile)

        matching = [
            item for item in warnings
            if item.startswith("mdx.voc_inst_secondary_model:")
        ]
        self.assertEqual(len(matching), 1, warnings)

    def test_stored_identity_warnings_survive_an_unavailable_index(self) -> None:
        from unittest import mock
        from unittest.mock import patch

        from cli.job import stored_identity_warnings
        from cli.profiles import LoadedProfile
        from core.model_identity import ModelIdentityService

        profile = LoadedProfile(
            name="p", source="profile", validation_warnings=["mdx.model: syntax note"],
        )
        with patch.object(
            ModelIdentityService, "_published_index", side_effect=OSError("no models")
        ):
            warnings = stored_identity_warnings(Settings.defaults(), mock.Mock(), profile)

        self.assertEqual(warnings, ["mdx.model: syntax note"])
