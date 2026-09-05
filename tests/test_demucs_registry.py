from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from typing import Any
from unittest.mock import patch

from core.model_identity import DemucsSpec

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_cli(data_dir: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update({
        "UVR_DATA_DIR": data_dir,
        "UVR_DISABLE_POLITREES": "1",
        "UVR_DISABLE_MVSEPLESS": "1",
    })
    return subprocess.run(
        [sys.executable, "-m", "cli", *arguments, "--report", "json"],
        cwd=_PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


class BundledDemucsSpecTests(unittest.TestCase):
    def test_specs_cover_every_official_mapper_stem(self) -> None:
        from core.demucs_registry import load_bundled_demucs_specs, mapper_stems

        specs = load_bundled_demucs_specs()
        self.assertEqual(set(specs), mapper_stems())

    def test_htdemucs_6s_is_six_source_v4(self) -> None:
        from core.demucs_registry import load_bundled_demucs_specs

        spec = load_bundled_demucs_specs()["demucs:htdemucs_6s"]
        self.assertEqual(spec, DemucsSpec("v4", "6_stem"))

    def test_uvr_bag_is_two_source(self) -> None:
        from core.demucs_registry import load_bundled_demucs_specs

        spec = load_bundled_demucs_specs()["demucs:UVR_Demucs_Model_1"]
        self.assertEqual(spec.source_layout, "2_stem")


class DemucsCatalogueSpecTests(unittest.TestCase):
    def test_explicit_version_is_not_overwritten_by_label(self) -> None:
        from types import SimpleNamespace

        from core.model_inventory import _demucs_spec

        entry = SimpleNamespace(
            label="Demucs v4: foo",
            display="v4 — foo",
            demucs_version="v3",
            stems=["drums", "bass", "other", "vocals"],
        )
        self.assertEqual(_demucs_spec(entry), DemucsSpec("v3", "4_stem"))

    def test_explicit_layout_is_not_overwritten_by_stem_count(self) -> None:
        from types import SimpleNamespace

        from core.model_inventory import _demucs_spec

        entry = SimpleNamespace(
            label="Demucs v4: htdemucs_6s",
            display="v4 — htdemucs_6s",
            source_layout="6_stem",
            stems=["drums", "bass", "other", "vocals"],
        )
        self.assertEqual(_demucs_spec(entry), DemucsSpec("v4", "6_stem"))

    def test_colon_label_import_is_accepted(self) -> None:
        from types import SimpleNamespace

        from core.model_inventory import _demucs_spec

        entry = SimpleNamespace(
            label="Demucs v3: mdx",
            display="v3 — mdx",
            stems=["drums", "bass", "other", "vocals"],
        )
        self.assertEqual(_demucs_spec(entry), DemucsSpec("v3", "4_stem"))

    def test_em_dash_display_is_not_imported_for_version(self) -> None:
        from types import SimpleNamespace

        from core.model_inventory import _demucs_spec

        entry = SimpleNamespace(
            label="Demucs v4 — foo",
            display="v4 — foo",
            stems=["drums", "bass", "other", "vocals"],
        )
        self.assertIsNone(_demucs_spec(entry))


class DemucsRegistryDocumentTests(unittest.TestCase):
    def _sample_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "models": {
                "demucs:my_model": {
                    "display_name": "My model",
                    "backend_name": "my_model",
                    "entrypoint": "v3_v4_repo/my_model.yaml",
                    "supporting_artifacts": [
                        "v3_v4_repo/abc12345-checksum.th",
                    ],
                    "primary_hash": "abc123",
                    "demucs_version": "v4",
                    "source_layout": "4_stem",
                }
            },
            "by_primary_hash": {"abc123": "demucs:my_model"},
        }

    def test_load_returns_empty_document_when_registry_is_missing(self) -> None:
        from core.demucs_registry import DemucsRegistry

        with tempfile.TemporaryDirectory() as tmp:
            registry = DemucsRegistry(models_dir=tmp)

            self.assertEqual(
                registry.load(),
                {"schema_version": 1, "models": {}, "by_primary_hash": {}},
            )
            self.assertFalse(os.path.exists(registry.path))
            self.assertEqual(
                registry.lock_path,
                os.path.join(tmp, "model_data", "registered_models.json.lock"),
            )

    def test_save_round_trips_the_registered_models_document(self) -> None:
        from core.demucs_registry import DemucsRegistry

        with tempfile.TemporaryDirectory() as tmp:
            registry = DemucsRegistry(models_dir=tmp)
            payload = self._sample_payload()

            registry.save(payload)

            with open(registry.path, encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertEqual(stored, payload)
            self.assertEqual(registry.load(), payload)

    def test_load_repairs_reverse_hash_index_from_models(self) -> None:
        from core.demucs_registry import DemucsRegistry

        with tempfile.TemporaryDirectory() as tmp:
            registry = DemucsRegistry(models_dir=tmp)
            os.makedirs(os.path.dirname(registry.path), exist_ok=True)
            broken = self._sample_payload()
            broken["by_primary_hash"] = {"stale": "demucs:other_model"}
            with open(registry.path, "w", encoding="utf-8") as handle:
                json.dump(broken, handle)

            loaded = registry.load()

            self.assertEqual(loaded, self._sample_payload())
            with open(registry.path, encoding="utf-8") as handle:
                repaired = json.load(handle)
            self.assertEqual(repaired, self._sample_payload())

    def test_save_rejects_paths_that_escape_the_demucs_model_root(self) -> None:
        from core.demucs_registry import DemucsRegistry

        with tempfile.TemporaryDirectory() as tmp:
            registry = DemucsRegistry(models_dir=tmp)
            payload = self._sample_payload()
            models = payload["models"]
            assert isinstance(models, dict)
            record = models["demucs:my_model"]
            assert isinstance(record, dict)
            record["entrypoint"] = "../outside.yaml"

            with self.assertRaisesRegex(ValueError, "path escapes"):
                registry.save(payload)

            self.assertFalse(os.path.exists(registry.path))

    def test_save_rejects_symlink_paths_that_resolve_outside_the_demucs_root(self) -> None:
        from core.demucs_registry import DemucsRegistry

        with tempfile.TemporaryDirectory() as tmp:
            models_dir = os.path.join(tmp, "Demucs_Models")
            outside_dir = os.path.join(tmp, "outside")
            os.makedirs(outside_dir)
            os.makedirs(os.path.join(models_dir, "model_data"))
            os.symlink(outside_dir, os.path.join(models_dir, "link"))

            registry = DemucsRegistry(models_dir=models_dir)
            payload = self._sample_payload()
            models = payload["models"]
            assert isinstance(models, dict)
            record = models["demucs:my_model"]
            assert isinstance(record, dict)
            record["entrypoint"] = "link/outside.yaml"

            with self.assertRaisesRegex(ValueError, "path escapes"):
                registry.save(payload)

            self.assertFalse(os.path.exists(registry.path))


class DemucsRegistrationTests(unittest.TestCase):
    def test_missing_config_fails_before_creating_destination_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.th")
            with open(source, "wb") as handle:
                handle.write(b"custom checkpoint")
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir, "models", "register", source, "--family", "demucs"
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn("--config is required", payload["error"]["message"])
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "models", "Demucs_Models"))
            )

    def test_invalid_version_fails_before_creating_destination_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.th")
            config = os.path.join(tmp, "config.json")
            with open(source, "wb") as handle:
                handle.write(b"custom checkpoint")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v5", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "invalid Demucs version",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "models", "Demucs_Models"))
            )

    def test_invalid_layout_fails_before_creating_destination_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.th")
            config = os.path.join(tmp, "config.json")
            with open(source, "wb") as handle:
                handle.write(b"custom checkpoint")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "5_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "invalid Demucs source layout",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "models", "Demucs_Models"))
            )

    def test_invalid_extension_fails_before_creating_destination_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.ckpt")
            config = os.path.join(tmp, "config.json")
            with open(source, "wb") as handle:
                handle.write(b"custom checkpoint")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "v3/v4 Demucs entrypoint must be .th or .yaml",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "models", "Demucs_Models"))
            )

    def test_v4_uppercase_weight_extension_is_rejected_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.TH")
            config = os.path.join(tmp, "config.json")
            with open(source, "wb") as handle:
                handle.write(b"custom checkpoint")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "v3/v4 Demucs entrypoint must be .th or .yaml",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "models", "Demucs_Models"))
            )

    def test_v4_uppercase_yaml_extension_is_rejected_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.YAML")
            config = os.path.join(tmp, "config.json")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("models:\n  - abc12345\n")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "v3/v4 Demucs entrypoint must be .th or .yaml",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "models", "Demucs_Models"))
            )

    def test_v4_uppercase_bag_member_extension_is_rejected_before_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            member_data = b"bag member"
            checksum = hashlib.sha256(member_data).hexdigest()[:8]
            source = os.path.join(tmp, "custom.yaml")
            member = os.path.join(tmp, f"abc12345-{checksum}.TH")
            config = os.path.join(tmp, "config.json")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("models:\n  - abc12345\n")
            with open(member, "wb") as handle:
                handle.write(member_data)
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "must match exactly one",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "models", "Demucs_Models"))
            )

    def test_complete_bag_copies_all_members_and_commits_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first_data = b"first Demucs member"
            second_data = b"second Demucs member"
            first_checksum = hashlib.sha256(first_data).hexdigest()[:8]
            second_checksum = hashlib.sha256(second_data).hexdigest()[:8]
            first_name = f"abc12345-{first_checksum}.th"
            second_name = f"def67890-{second_checksum}.th"
            source = os.path.join(tmp, "custom_bag.yaml")
            first_source = os.path.join(tmp, first_name)
            second_source = os.path.join(tmp, second_name)
            config = os.path.join(tmp, "config.json")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("models:\n  - abc12345\n  - def67890\n")
            with open(first_source, "wb") as handle:
                handle.write(first_data)
            with open(second_source, "wb") as handle:
                handle.write(second_data)
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "demucs_version": "v4",
                        "source_layout": "6_stem",
                        "display_name": "Custom bag",
                    },
                    handle,
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            repo_dir = os.path.join(
                data_dir, "models", "Demucs_Models", "v3_v4_repo"
            )
            for name, expected in (
                ("custom_bag.yaml", b"models:\n  - abc12345\n  - def67890\n"),
                (first_name, first_data),
                (second_name, second_data),
            ):
                with open(os.path.join(repo_dir, name), "rb") as handle:
                    self.assertEqual(handle.read(), expected)
            registry_path = os.path.join(
                data_dir,
                "models",
                "Demucs_Models",
                "model_data",
                "registered_models.json",
            )
            with open(registry_path, encoding="utf-8") as handle:
                registry = json.load(handle)
            entry = registry["models"]["demucs:custom_bag"]
            self.assertEqual(entry["display_name"], "Custom bag")
            self.assertEqual(entry["backend_name"], "custom_bag")
            self.assertEqual(entry["entrypoint"], "v3_v4_repo/custom_bag.yaml")
            self.assertEqual(
                entry["supporting_artifacts"],
                [f"v3_v4_repo/{first_name}", f"v3_v4_repo/{second_name}"],
            )
            self.assertEqual(
                registry["by_primary_hash"][entry["primary_hash"]],
                "demucs:custom_bag",
            )

    def test_member_collision_leaves_no_command_created_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            member_data = b"submitted member"
            checksum = hashlib.sha256(member_data).hexdigest()[:8]
            member_name = f"abc12345-{checksum}.th"
            source = os.path.join(tmp, "custom_bag.yaml")
            member_source = os.path.join(tmp, member_name)
            config = os.path.join(tmp, "config.json")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("models:\n  - abc12345\n")
            with open(member_source, "wb") as handle:
                handle.write(member_data)
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")
            repo_dir = os.path.join(
                data_dir, "models", "Demucs_Models", "v3_v4_repo"
            )
            os.makedirs(repo_dir)
            collision = os.path.join(repo_dir, member_name)
            with open(collision, "wb") as handle:
                handle.write(b"different installed member")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "different content", json.loads(result.stdout)["error"]["message"]
            )
            with open(collision, "rb") as handle:
                self.assertEqual(handle.read(), b"different installed member")
            self.assertEqual(os.listdir(repo_dir), [member_name])
            self.assertFalse(
                os.path.exists(
                    os.path.join(
                        data_dir,
                        "models",
                        "Demucs_Models",
                        "model_data",
                        "registered_models.json",
                    )
                )
            )

    def test_registry_write_failure_rolls_back_promoted_artifact(self) -> None:
        from core.demucs_registry import DemucsRegistry, prepare_demucs_registration

        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.th")
            with open(source, "wb") as handle:
                handle.write(b"custom checkpoint")
            models_dir = os.path.join(tmp, "Demucs_Models")
            unit = prepare_demucs_registration(
                source,
                {"demucs_version": "v4", "source_layout": "4_stem"},
                models_dir=models_dir,
            )
            registry = DemucsRegistry(models_dir=models_dir)

            with patch(
                "core.demucs_registry.write_json_atomic",
                side_effect=OSError("simulated registry write failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated registry write failure"):
                    registry.install(unit)

            repo_dir = os.path.join(models_dir, "v3_v4_repo")
            self.assertEqual(os.listdir(repo_dir), [])
            self.assertFalse(os.path.exists(registry.path))

    def test_source_mutation_after_prepare_aborts_without_publishing(self) -> None:
        from core.demucs_registry import DemucsRegistry, prepare_demucs_registration

        with tempfile.TemporaryDirectory() as tmp:
            original = b"validated checkpoint"
            checksum = hashlib.sha256(original).hexdigest()[:8]
            source = os.path.join(tmp, f"abc12345-{checksum}.th")
            with open(source, "wb") as handle:
                handle.write(original)
            models_dir = os.path.join(tmp, "Demucs_Models")
            unit = prepare_demucs_registration(
                source,
                {"demucs_version": "v4", "source_layout": "4_stem"},
                models_dir=models_dir,
            )
            with open(source, "wb") as handle:
                handle.write(b"mutated after checksum validation")
            registry = DemucsRegistry(models_dir=models_dir)

            with self.assertRaisesRegex(ValueError, "changed since validation"):
                registry.install(unit)

            self.assertFalse(os.path.exists(unit.destination_paths[0]))
            self.assertFalse(os.path.exists(registry.path))

    def test_direct_checksum_mutation_during_snapshot_cannot_be_registered(
        self,
    ) -> None:
        from core.demucs_registry import DemucsRegistry, prepare_demucs_registration

        with tempfile.TemporaryDirectory() as tmp:
            original = b"validated direct weight"
            checksum = hashlib.sha256(original).hexdigest()[:8]
            source = os.path.join(tmp, f"abc12345-{checksum}.th")
            with open(source, "wb") as handle:
                handle.write(original)
            models_dir = os.path.join(tmp, "Demucs_Models")
            registry = DemucsRegistry(models_dir=models_dir)
            real_open = open
            source_reads = 0

            def mutate_on_second_source_read(
                file: Any, mode: str = "r", *args: Any, **kwargs: Any
            ) -> Any:
                nonlocal source_reads
                if os.path.abspath(str(file)) == source and mode == "rb":
                    source_reads += 1
                    if source_reads == 2:
                        with real_open(source, "wb") as handle:
                            handle.write(b"mutated invalid direct weight")
                return real_open(file, mode, *args, **kwargs)

            with self.assertRaisesRegex(
                ValueError, "invalid declared checksum|changed since validation"
            ):
                with patch(
                    "builtins.open", side_effect=mutate_on_second_source_read
                ):
                    unit = prepare_demucs_registration(
                        source,
                        {"demucs_version": "v4", "source_layout": "4_stem"},
                        models_dir=models_dir,
                    )
                    registry.install(unit)

            destination = os.path.join(
                models_dir, "v3_v4_repo", os.path.basename(source)
            )
            self.assertFalse(os.path.exists(destination))
            self.assertFalse(os.path.exists(registry.path))

    def test_yaml_membership_mutation_during_snapshot_cannot_be_registered(
        self,
    ) -> None:
        from core.demucs_registry import DemucsRegistry, prepare_demucs_registration

        with tempfile.TemporaryDirectory() as tmp:
            member_data = b"validated YAML member"
            checksum = hashlib.sha256(member_data).hexdigest()[:8]
            member_name = f"abc12345-{checksum}.th"
            source = os.path.join(tmp, "custom.yaml")
            member = os.path.join(tmp, member_name)
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("models:\n  - abc12345\n")
            with open(member, "wb") as handle:
                handle.write(member_data)
            models_dir = os.path.join(tmp, "Demucs_Models")
            registry = DemucsRegistry(models_dir=models_dir)
            real_open = open
            source_reads = 0

            def mutate_on_second_source_read(
                file: Any, mode: str = "r", *args: Any, **kwargs: Any
            ) -> Any:
                nonlocal source_reads
                if os.path.abspath(str(file)) == source and "r" in mode:
                    source_reads += 1
                    if source_reads == 2:
                        with real_open(source, "w", encoding="utf-8") as handle:
                            handle.write("models:\n  - def67890\n")
                return real_open(file, mode, *args, **kwargs)

            with self.assertRaisesRegex(
                ValueError, "membership|must match exactly one|changed since validation"
            ):
                with patch(
                    "builtins.open", side_effect=mutate_on_second_source_read
                ):
                    unit = prepare_demucs_registration(
                        source,
                        {"demucs_version": "v4", "source_layout": "4_stem"},
                        models_dir=models_dir,
                    )
                    registry.install(unit)

            repo_dir = os.path.join(models_dir, "v3_v4_repo")
            self.assertFalse(os.path.exists(os.path.join(repo_dir, "custom.yaml")))
            self.assertFalse(os.path.exists(os.path.join(repo_dir, member_name)))
            self.assertFalse(os.path.exists(registry.path))

    def test_bag_member_checksum_mutation_during_snapshot_cannot_be_registered(
        self,
    ) -> None:
        from core.demucs_registry import DemucsRegistry, prepare_demucs_registration

        with tempfile.TemporaryDirectory() as tmp:
            member_data = b"validated bag weight"
            checksum = hashlib.sha256(member_data).hexdigest()[:8]
            member_name = f"abc12345-{checksum}.th"
            source = os.path.join(tmp, "custom.yaml")
            member = os.path.join(tmp, member_name)
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("models:\n  - abc12345\n")
            with open(member, "wb") as handle:
                handle.write(member_data)
            models_dir = os.path.join(tmp, "Demucs_Models")
            registry = DemucsRegistry(models_dir=models_dir)
            real_open = open
            member_reads = 0

            def mutate_on_second_member_read(
                file: Any, mode: str = "r", *args: Any, **kwargs: Any
            ) -> Any:
                nonlocal member_reads
                if os.path.abspath(str(file)) == member and mode == "rb":
                    member_reads += 1
                    if member_reads == 2:
                        with real_open(member, "wb") as handle:
                            handle.write(b"mutated invalid bag weight")
                return real_open(file, mode, *args, **kwargs)

            with self.assertRaisesRegex(
                ValueError, "invalid declared checksum|changed since validation"
            ):
                with patch(
                    "builtins.open", side_effect=mutate_on_second_member_read
                ):
                    unit = prepare_demucs_registration(
                        source,
                        {"demucs_version": "v4", "source_layout": "4_stem"},
                        models_dir=models_dir,
                    )
                    registry.install(unit)

            repo_dir = os.path.join(models_dir, "v3_v4_repo")
            self.assertFalse(os.path.exists(os.path.join(repo_dir, "custom.yaml")))
            self.assertFalse(os.path.exists(os.path.join(repo_dir, member_name)))
            self.assertFalse(os.path.exists(registry.path))

    def test_projection_failure_cannot_report_failure_after_durable_commit(
        self,
    ) -> None:
        from cli.discovery import cmd_models_register

        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.th")
            config = os.path.join(tmp, "config.json")
            with open(source, "wb") as handle:
                handle.write(b"custom checkpoint")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            models_dir = os.path.join(tmp, "Demucs_Models")
            args = argparse.Namespace(
                checkpoint=source,
                family="demucs",
                config=config,
                report="json",
                quiet=False,
                verbose=False,
                job_id="postcommit",
            )
            output = io.StringIO()

            with (
                patch("core.paths.DEMUCS_MODELS_DIR", models_dir),
                patch(
                    "cli.discovery._registered_demucs_info",
                    side_effect=ValueError("simulated projection failure"),
                ),
                redirect_stdout(output),
            ):
                result = cmd_models_register(args)

            self.assertEqual(result, 0, output.getvalue())
            self.assertTrue(
                os.path.isfile(
                    os.path.join(models_dir, "v3_v4_repo", "custom.th")
                )
            )
            registry_path = os.path.join(
                models_dir, "model_data", "registered_models.json"
            )
            with open(registry_path, encoding="utf-8") as handle:
                document = json.load(handle)
            self.assertIn("demucs:custom", document["models"])
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["items"], [{
                "id": "demucs:custom",
                "family": "demucs",
                "installed": True,
                "registered": True,
            }])

    def test_v2_th_gz_installs_in_legacy_directory_with_compound_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.th.gz")
            config = os.path.join(tmp, "config.json")
            with open(source, "wb") as handle:
                handle.write(b"legacy checkpoint")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v2", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            item = json.loads(result.stdout)["items"][0]
            self.assertEqual(item["id"], "demucs:custom")
            legacy_path = os.path.join(
                data_dir, "models", "Demucs_Models", "custom.th.gz"
            )
            self.assertTrue(os.path.isfile(legacy_path))
            self.assertFalse(
                os.path.exists(
                    os.path.join(
                        data_dir,
                        "models",
                        "Demucs_Models",
                        "v3_v4_repo",
                        "custom.th.gz",
                    )
                )
            )

    def test_v4_weight_backend_name_is_local_repo_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            weight = b"checksummed checkpoint"
            checksum = hashlib.sha256(weight).hexdigest()[:8]
            source = os.path.join(tmp, f"abc12345-{checksum}.th")
            config = os.path.join(tmp, "config.json")
            with open(source, "wb") as handle:
                handle.write(weight)
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "2_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            item = json.loads(result.stdout)["items"][0]
            self.assertEqual(item["id"], f"demucs:abc12345-{checksum}")
            self.assertEqual(item["backend_name"], "abc12345")
            self.assertEqual(item["display"], f"abc12345-{checksum}")

    def test_matching_orphan_destination_is_adopted_without_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.th")
            config = os.path.join(tmp, "config.json")
            with open(source, "wb") as handle:
                handle.write(b"custom checkpoint")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")
            repo_dir = os.path.join(
                data_dir, "models", "Demucs_Models", "v3_v4_repo"
            )
            os.makedirs(repo_dir)
            orphan = os.path.join(repo_dir, "custom.th")
            with open(orphan, "wb") as handle:
                handle.write(b"custom checkpoint")
            inode_before = os.stat(orphan).st_ino

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(os.stat(orphan).st_ino, inode_before)
            registry_path = os.path.join(
                data_dir,
                "models",
                "Demucs_Models",
                "model_data",
                "registered_models.json",
            )
            self.assertTrue(os.path.isfile(registry_path))

    def test_large_orphan_with_same_uvr_tail_but_different_prefix_is_rejected(
        self,
    ) -> None:
        from core.demucs_registry import DemucsRegistry, prepare_demucs_registration

        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.th")
            shared_tail = b"x" * (10000 * 1024)
            with open(source, "wb") as handle:
                handle.write(b"source-prefix")
                handle.write(shared_tail)
            models_dir = os.path.join(tmp, "Demucs_Models")
            unit = prepare_demucs_registration(
                source,
                {"demucs_version": "v4", "source_layout": "4_stem"},
                models_dir=models_dir,
            )
            destination = unit.destination_paths[0]
            os.makedirs(os.path.dirname(destination))
            with open(destination, "wb") as handle:
                handle.write(b"orphan-prefix")
                handle.write(shared_tail)
            registry = DemucsRegistry(models_dir=models_dir)

            with self.assertRaisesRegex(ValueError, "different content"):
                registry.install(unit)

            with open(destination, "rb") as handle:
                self.assertEqual(handle.read(13), b"orphan-prefix")
            self.assertFalse(os.path.exists(registry.path))

    def test_missing_bag_member_fails_before_creating_destination_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.yaml")
            config = os.path.join(tmp, "config.json")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("models:\n  - abc12345\n")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "must match exactly one",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "models", "Demucs_Models"))
            )

    def test_ambiguous_bag_member_fails_before_creating_destination_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.yaml")
            config = os.path.join(tmp, "config.json")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("models:\n  - abc12345\n")
            for content in (b"first", b"second"):
                checksum = hashlib.sha256(content).hexdigest()[:8]
                with open(
                    os.path.join(tmp, f"abc12345-{checksum}.th"), "wb"
                ) as handle:
                    handle.write(content)
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "must match exactly one",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "models", "Demucs_Models"))
            )

    def test_invalid_declared_checksum_fails_before_creating_destination_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "abc12345-deadbeef.th")
            config = os.path.join(tmp, "config.json")
            with open(source, "wb") as handle:
                handle.write(b"not deadbeef")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "invalid declared checksum",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "models", "Demucs_Models"))
            )

    def test_multi_hyphen_weight_fails_before_creating_destination_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "abc12345-dead-beef.th")
            config = os.path.join(tmp, "config.json")
            with open(source, "wb") as handle:
                handle.write(b"checkpoint")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")

            result = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "expected signature.th or signature-checksum.th",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "models", "Demucs_Models"))
            )

    def test_losing_race_does_not_delete_artifact_claimed_by_winner(self) -> None:
        from core.demucs_registry import (
            DemucsRegistrationUnit,
            DemucsRegistry,
            prepare_demucs_registration,
        )

        with tempfile.TemporaryDirectory() as tmp:
            loser_source_dir = os.path.join(tmp, "loser")
            winner_source_dir = os.path.join(tmp, "winner")
            os.makedirs(loser_source_dir)
            os.makedirs(winner_source_dir)
            loser_source = os.path.join(loser_source_dir, "custom.th")
            winner_source = os.path.join(winner_source_dir, "custom.th")
            for source in (loser_source, winner_source):
                with open(source, "wb") as handle:
                    handle.write(b"shared checkpoint")
            models_dir = os.path.join(tmp, "Demucs_Models")
            loser_unit = prepare_demucs_registration(
                loser_source,
                {
                    "demucs_version": "v4",
                    "source_layout": "4_stem",
                    "display_name": "Loser",
                },
                models_dir=models_dir,
            )
            winner_unit = prepare_demucs_registration(
                winner_source,
                {
                    "demucs_version": "v4",
                    "source_layout": "4_stem",
                    "display_name": "Winner",
                },
                models_dir=models_dir,
            )
            commit_barrier = threading.Barrier(2)
            loser_promoted = threading.Event()
            winner_committed = threading.Event()

            class OrderedRegistry(DemucsRegistry):
                def _commit_unit(
                    self, unit: DemucsRegistrationUnit, *, replace: bool
                ) -> dict[str, Any]:
                    if unit.entry["display_name"] == "Loser":
                        loser_promoted.set()
                    commit_barrier.wait(timeout=5)
                    if unit.entry["display_name"] == "Winner":
                        try:
                            return super()._commit_unit(unit, replace=replace)
                        finally:
                            winner_committed.set()
                    if not winner_committed.wait(timeout=5):
                        raise AssertionError("winner did not commit")
                    return super()._commit_unit(unit, replace=replace)

            registry = OrderedRegistry(models_dir=models_dir)
            errors: list[Exception] = []

            def install(unit: DemucsRegistrationUnit) -> None:
                try:
                    registry.install(unit)
                except Exception as exc:
                    errors.append(exc)

            loser = threading.Thread(target=install, args=(loser_unit,))
            winner = threading.Thread(target=install, args=(winner_unit,))
            loser.start()
            self.assertTrue(loser_promoted.wait(timeout=5))
            winner.start()
            loser.join(timeout=5)
            winner.join(timeout=5)

            self.assertFalse(loser.is_alive())
            self.assertFalse(winner.is_alive())
            self.assertEqual(len(errors), 1)
            destination = os.path.join(models_dir, "v3_v4_repo", "custom.th")
            self.assertTrue(os.path.isfile(destination))
            with open(destination, "rb") as handle:
                self.assertEqual(handle.read(), b"shared checkpoint")
            stored = registry.load()
            self.assertEqual(
                stored["models"]["demucs:custom"]["display_name"], "Winner"
            )


class DemucsConfigureTests(unittest.TestCase):
    def test_configure_attaches_metadata_to_incomplete_installed_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            newer_dir = os.path.join(
                data_dir, "models", "Demucs_Models", "v3_v4_repo"
            )
            os.makedirs(newer_dir)
            installed = os.path.join(newer_dir, "custom.th")
            with open(installed, "wb") as handle:
                handle.write(b"custom checkpoint")
            config = os.path.join(tmp, "config.json")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "demucs_version": "v4",
                        "source_layout": "6_stem",
                        "display_name": "Recovered custom",
                    },
                    handle,
                )

            result = _run_cli(
                data_dir,
                "models",
                "configure",
                "demucs:custom",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(os.path.isfile(installed))
            listing = _run_cli(
                data_dir, "models", "list", "--family", "demucs"
            )
            self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
            rows = json.loads(listing.stdout)["items"]
            custom = next(row for row in rows if row["id"] == "demucs:custom")
            self.assertEqual(custom["display"], "Recovered custom")
            self.assertEqual(custom["demucs_version"], "v4")
            self.assertEqual(custom["source_layout"], "6_stem")
            self.assertTrue(custom["identity_complete"])

    def test_version_change_that_would_move_directories_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            newer_dir = os.path.join(
                data_dir, "models", "Demucs_Models", "v3_v4_repo"
            )
            os.makedirs(newer_dir)
            installed = os.path.join(newer_dir, "custom.th")
            with open(installed, "wb") as handle:
                handle.write(b"custom checkpoint")
            config = os.path.join(tmp, "config.json")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v2", "source_layout": "4_stem"}, handle
                )

            result = _run_cli(
                data_dir,
                "models",
                "configure",
                "demucs:custom",
                "--config",
                config,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "configure does not move Demucs artifacts",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertTrue(os.path.isfile(installed))
            self.assertFalse(
                os.path.exists(
                    os.path.join(data_dir, "models", "Demucs_Models", "custom.th")
                )
            )
            self.assertFalse(
                os.path.exists(
                    os.path.join(
                        data_dir,
                        "models",
                        "Demucs_Models",
                        "model_data",
                        "registered_models.json",
                    )
                )
            )

    def test_configure_rejects_non_demucs_metadata_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            newer_dir = os.path.join(
                data_dir, "models", "Demucs_Models", "v3_v4_repo"
            )
            os.makedirs(newer_dir)
            with open(os.path.join(newer_dir, "custom.th"), "wb") as handle:
                handle.write(b"custom checkpoint")
            config = os.path.join(tmp, "config.json")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )

            result = _run_cli(
                data_dir,
                "models",
                "configure",
                "demucs:custom",
                "--config",
                config,
                "--primary-stem",
                "Vocals",
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "Demucs metadata is supplied only through --config",
                json.loads(result.stdout)["error"]["message"],
            )
            self.assertFalse(
                os.path.exists(
                    os.path.join(
                        data_dir,
                        "models",
                        "Demucs_Models",
                        "model_data",
                        "registered_models.json",
                    )
                )
            )
    def test_reset_removes_metadata_but_keeps_artifact_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.th")
            config = os.path.join(tmp, "config.json")
            with open(source, "wb") as handle:
                handle.write(b"custom checkpoint")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")
            registered = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )
            self.assertEqual(
                registered.returncode, 0, registered.stdout + registered.stderr
            )

            reset = _run_cli(
                data_dir, "models", "configure", "demucs:custom", "--reset"
            )

            self.assertEqual(reset.returncode, 0, reset.stdout + reset.stderr)
            installed = os.path.join(
                data_dir,
                "models",
                "Demucs_Models",
                "v3_v4_repo",
                "custom.th",
            )
            self.assertTrue(os.path.isfile(installed))
            registry_path = os.path.join(
                data_dir,
                "models",
                "Demucs_Models",
                "model_data",
                "registered_models.json",
            )
            with open(registry_path, encoding="utf-8") as handle:
                registry = json.load(handle)
            self.assertEqual(registry["models"], {})
            self.assertEqual(registry["by_primary_hash"], {})

            listing = _run_cli(
                data_dir, "models", "list", "--family", "demucs"
            )
            self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
            rows = json.loads(listing.stdout)["items"]
            custom = next(row for row in rows if row["id"] == "demucs:custom")
            self.assertTrue(custom["installed"])
            self.assertFalse(custom["identity_complete"])

    def test_existing_registration_uses_its_exact_entrypoint_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            models_dir = os.path.join(data_dir, "models", "Demucs_Models")
            newer_dir = os.path.join(models_dir, "v3_v4_repo")
            model_data_dir = os.path.join(models_dir, "model_data")
            os.makedirs(newer_dir)
            os.makedirs(model_data_dir)
            for path in (
                os.path.join(models_dir, "custom.th"),
                os.path.join(newer_dir, "custom.th"),
            ):
                with open(path, "wb") as handle:
                    handle.write(b"same named checkpoint")
            registry_path = os.path.join(model_data_dir, "registered_models.json")
            document = {
                "schema_version": 1,
                "models": {
                    "demucs:custom": {
                        "display_name": "Custom",
                        "backend_name": "custom",
                        "entrypoint": "custom.th",
                        "supporting_artifacts": [],
                        "primary_hash": "abc123",
                        "demucs_version": "v1",
                        "source_layout": "4_stem",
                    }
                },
                "by_primary_hash": {"abc123": "demucs:custom"},
            }
            with open(registry_path, "w", encoding="utf-8") as handle:
                json.dump(document, handle)
            config = os.path.join(tmp, "config.json")
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )

            result = _run_cli(
                data_dir,
                "models",
                "configure",
                "demucs:custom",
                "--config",
                config,
                "--replace",
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                "configure does not move Demucs artifacts",
                json.loads(result.stdout)["error"]["message"],
            )
            with open(registry_path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), document)


class DemucsInventoryRegistrationTests(unittest.TestCase):
    def test_inventory_does_not_rewrite_a_stale_registry_reverse_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            models_dir = os.path.join(data_dir, "models", "Demucs_Models")
            newer_dir = os.path.join(models_dir, "v3_v4_repo")
            model_data_dir = os.path.join(models_dir, "model_data")
            os.makedirs(newer_dir)
            os.makedirs(model_data_dir)
            with open(os.path.join(newer_dir, "custom.th"), "wb") as handle:
                handle.write(b"registered checkpoint")
            registry_path = os.path.join(
                model_data_dir, "registered_models.json"
            )
            original_bytes = json.dumps(
                {
                    "schema_version": 1,
                    "models": {
                        "demucs:custom": {
                            "display_name": "Custom",
                            "backend_name": "custom",
                            "entrypoint": "v3_v4_repo/custom.th",
                            "supporting_artifacts": [],
                            "primary_hash": "correct-hash",
                            "demucs_version": "v4",
                            "source_layout": "4_stem",
                        }
                    },
                    "by_primary_hash": {"stale-hash": "demucs:custom"},
                },
                separators=(",", ":"),
            ).encode("utf-8")
            with open(registry_path, "wb") as handle:
                handle.write(original_bytes)

            listing = _run_cli(
                data_dir, "models", "list", "--family", "demucs"
            )

            self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
            with open(registry_path, "rb") as handle:
                self.assertEqual(handle.read(), original_bytes)

    def test_registered_entry_requires_artifact_at_exact_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            models_dir = os.path.join(data_dir, "models", "Demucs_Models")
            newer_dir = os.path.join(models_dir, "v3_v4_repo")
            model_data_dir = os.path.join(models_dir, "model_data")
            os.makedirs(newer_dir)
            os.makedirs(model_data_dir)
            with open(os.path.join(newer_dir, "custom.th"), "wb") as handle:
                handle.write(b"checkpoint in the wrong directory")
            with open(
                os.path.join(model_data_dir, "registered_models.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "schema_version": 1,
                        "models": {
                            "demucs:custom": {
                                "display_name": "Custom",
                                "backend_name": "custom",
                                "entrypoint": "custom.th",
                                "supporting_artifacts": [],
                                "primary_hash": "abc123",
                                "demucs_version": "v1",
                                "source_layout": "4_stem",
                            }
                        },
                        "by_primary_hash": {"abc123": "demucs:custom"},
                    },
                    handle,
                )

            listing = _run_cli(
                data_dir, "models", "list", "--family", "demucs"
            )

            self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
            rows = json.loads(listing.stdout)["items"]
            custom = next(row for row in rows if row["id"] == "demucs:custom")
            self.assertFalse(custom["identity_complete"])
            self.assertIn("custom.th", custom["identity_error"])

    def test_registered_bag_rechecks_yaml_membership_without_hashing_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            member_data = b"registered member"
            checksum = hashlib.sha256(member_data).hexdigest()[:8]
            member_name = f"abc12345-{checksum}.th"
            source = os.path.join(tmp, "custom.yaml")
            config = os.path.join(tmp, "config.json")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("models:\n  - abc12345\n")
            with open(os.path.join(tmp, member_name), "wb") as handle:
                handle.write(member_data)
            with open(config, "w", encoding="utf-8") as handle:
                json.dump(
                    {"demucs_version": "v4", "source_layout": "4_stem"}, handle
                )
            data_dir = os.path.join(tmp, "data")
            registered = _run_cli(
                data_dir,
                "models",
                "register",
                source,
                "--family",
                "demucs",
                "--config",
                config,
            )
            self.assertEqual(
                registered.returncode, 0, registered.stdout + registered.stderr
            )
            installed_yaml = os.path.join(
                data_dir,
                "models",
                "Demucs_Models",
                "v3_v4_repo",
                "custom.yaml",
            )
            with open(installed_yaml, "w", encoding="utf-8") as handle:
                handle.write("models:\n  - different\n")

            listing = _run_cli(
                data_dir, "models", "list", "--family", "demucs"
            )

            self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
            rows = json.loads(listing.stdout)["items"]
            custom = next(row for row in rows if row["id"] == "demucs:custom")
            self.assertFalse(custom["identity_complete"])
            self.assertIn("membership", custom["identity_error"])
