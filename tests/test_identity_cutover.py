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


if __name__ == "__main__":
    unittest.main()
