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

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["selected_models"], ["MDX-Net: Model A"])
        self.assertTrue(any("selected_models[0]" in item for item in loaded.validation_warnings))


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
        return {
            "schema_version": 3,
            "job_id": "recorded-job",
            "command": "separate",
            "model_dependencies": {"mdx.model": "mdx:primary"},
            "model_identity_digest": cls._RECORDED_DIGEST,
            "settings": {},
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
                to_dict=lambda: {"command": "audio", "model": None},
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
                to_dict=lambda: {"command": "audio", "model": None},
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
        resolver.identities.resolve.return_value = record
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
