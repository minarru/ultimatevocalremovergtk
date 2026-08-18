from __future__ import annotations

import json
import os
import tempfile
import unittest
import copy
import threading
from unittest.mock import Mock, patch

from bundled.constants import CHOOSE_MODEL, MDX_ARCH_TYPE, NO_MODEL
from core.identity_migration import IdentityMigrator, migrate_identity_storage
from core.input_discovery import InputDiscoveryPolicy, InputDiscoveryService
from core.job_plan import JobResolver, JobSpec, ValidationLevel
from core.model_identity import ModelIdentityService
from core.settings import Settings
from core.types import ProcessMethod


class _Repo:
    inventory_generation = 4
    mdx_name_select_MAPPER: dict[str, str] = {}
    demucs_name_select_MAPPER: dict[str, str] = {}

    def list_vr_models(self) -> list[str]:
        return []

    def list_mdx_models(self) -> list[str]:
        return []

    def list_demucs_models(self) -> list[str]:
        return []

    def vr_catalogue_display_index(self) -> dict[str, str]:
        return {}

    def mdx_catalogue_display_index(self) -> dict[str, str]:
        return {"model_a": "Model A"}

    def demucs_catalogue_display_index(self) -> dict[str, str]:
        return {}


class IdentityServiceTests(unittest.TestCase):
    def test_catalog_known_identity_migrates_without_checkpoint(self) -> None:
        migrator = IdentityMigrator(_Repo())
        self.assertEqual(migrator.canonical("Model A", family="mdx"), "mdx:model_a")

    def test_legacy_arch_member_tag_does_not_double_prefix(self) -> None:
        migrator = IdentityMigrator(_Repo())
        self.assertEqual(
            migrator.canonical("MDX-Net: Model A", family="mdx"),
            "mdx:model_a",
        )

    def test_unknown_references_clear_to_existing_sentinels(self) -> None:
        settings = Settings.defaults()
        settings.mdx.model = "Unknown Model"
        settings.process.vocal_splitter = "MDX-Net: Unknown Splitter"
        converted, cleared = IdentityMigrator(_Repo()).migrate_settings(settings)
        self.assertEqual(converted, 0)
        self.assertEqual(cleared, 2)
        self.assertEqual(settings.mdx.model, CHOOSE_MODEL)
        self.assertEqual(settings.process.vocal_splitter, NO_MODEL)

    def test_ambiguous_secondary_is_left_unchanged(self) -> None:
        from core.identity_migration import IdentityMigrator
        from bundled.constants import NO_MODEL

        settings = Settings.defaults()
        settings.mdx.voc_inst_secondary_model = "Kim"
        migrator = IdentityMigrator(_Repo())
        with patch(
            "core.identity_migration.resolve_model_record",
            side_effect=ValueError("ambiguous model 'Kim'; matches: mdx:a, vr:a"),
        ):
            migrator.migrate_settings(settings)
        self.assertEqual(settings.mdx.voc_inst_secondary_model, "Kim")
        self.assertNotEqual(settings.mdx.voc_inst_secondary_model, NO_MODEL)

    def test_ambiguous_secondary_is_recorded_on_conflicts_and_failures(self) -> None:
        settings = Settings.defaults()
        settings.identity_schema_version = 0
        settings.mdx.voc_inst_secondary_model = "Kim"
        with tempfile.TemporaryDirectory() as root, patch(
            "core.identity_migration.resolve_model_record",
            side_effect=ValueError("ambiguous model 'Kim'; matches: mdx:a, vr:a"),
        ):
            result = migrate_identity_storage(
                settings,
                _Repo(),
                profile_directory=os.path.join(root, "profiles"),
                ensemble_directory=os.path.join(root, "ensembles"),
            )
        self.assertEqual(settings.mdx.voc_inst_secondary_model, "Kim")
        self.assertTrue(result.conflicts)
        self.assertTrue(any("ambiguous" in item for item in result.conflicts))
        for item in result.conflicts:
            self.assertIn(item, result.failures)

    def test_storage_migration_is_atomic_versioned_and_backed_up(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            settings_path = os.path.join(root, "settings.json")
            profiles = os.path.join(root, "profiles")
            ensembles = os.path.join(root, "ensembles")
            os.makedirs(profiles)
            os.makedirs(ensembles)
            settings = Settings.defaults()
            settings.identity_schema_version = 0
            settings.path = settings_path
            settings.mdx.model = "Model A"
            settings.save()
            ensemble_path = os.path.join(ensembles, "mix.json")
            with open(ensemble_path, "w", encoding="utf-8") as handle:
                json.dump({"selected_models": ["MDX-Net: Model A"]}, handle)
            snapshot = copy.deepcopy(settings)
            result = migrate_identity_storage(
                snapshot, _Repo(), profile_directory=profiles,
                ensemble_directory=ensembles,
            )
            self.assertEqual(settings.mdx.model, "Model A")
            self.assertEqual(snapshot.mdx.model, "mdx:model_a")
            self.assertEqual(result.files_changed, 1)
            self.assertFalse(os.path.isfile(settings_path + ".pre-canonical-id.bak"))
            self.assertTrue(os.path.isfile(ensemble_path + ".pre-canonical-id.bak"))
            with open(ensemble_path, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["selected_models"], ["mdx:model_a"])
            self.assertEqual(saved["identity_schema_version"], 2)

            from ui.context import AppContext

            context = AppContext.__new__(AppContext)
            context.settings = settings
            context.save_settings = Mock()
            applied, conflicts, error = context.apply_identity_migration(result)
            self.assertGreaterEqual(applied, 2)
            self.assertEqual(conflicts, 0)
            self.assertIsNone(error)
            self.assertEqual(settings.mdx.model, "mdx:model_a")
            self.assertEqual(settings.identity_schema_version, 2)
            self.assertTrue(os.path.isfile(settings_path + ".pre-canonical-id.bak"))

    def test_live_edit_wins_over_migration_patch_and_version_retries(self) -> None:
        from core.identity_migration import (
            IdentityMigrationResult, IdentitySettingChange,
        )
        from ui.context import AppContext

        settings = Settings.defaults()
        settings.identity_schema_version = 0
        settings.mdx.model = "User changed this"
        context = AppContext.__new__(AppContext)
        context.settings = settings
        context.save_settings = Mock()
        result = IdentityMigrationResult(settings_changes=(
            IdentitySettingChange("mdx.model", "Model A", "mdx:model_a"),
            IdentitySettingChange("identity_schema_version", 0, 2),
        ))
        applied, conflicts, error = context.apply_identity_migration(result)
        self.assertEqual(applied, 0)
        self.assertEqual(conflicts, 1)
        self.assertIsNone(error)
        self.assertEqual(settings.mdx.model, "User changed this")
        self.assertEqual(settings.identity_schema_version, 0)
        context.save_settings.assert_not_called()

    def test_migration_skips_file_edited_after_read(self) -> None:
        from core import json_store

        with tempfile.TemporaryDirectory() as root:
            ensembles = os.path.join(root, "ensembles")
            os.makedirs(ensembles)
            ensemble_path = os.path.join(ensembles, "mix.json")
            live = {"selected_models": ["User live edit"]}
            with open(ensemble_path, "w", encoding="utf-8") as handle:
                json.dump({"selected_models": ["MDX-Net: Model A"]}, handle)

            real_read = json_store.read_json_object

            def read_then_live_edit(path: str) -> dict:
                payload = real_read(path)
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(live, handle)
                return payload

            settings = Settings.defaults()
            settings.identity_schema_version = 0
            with patch(
                "core.identity_migration.read_json_object",
                side_effect=read_then_live_edit,
            ):
                result = migrate_identity_storage(
                    settings,
                    _Repo(),
                    profile_directory=os.path.join(root, "profiles"),
                    ensemble_directory=ensembles,
                )
            with open(ensemble_path, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved, live)
            self.assertEqual(result.files_changed, 0)
            self.assertFalse(os.path.isfile(ensemble_path + ".pre-canonical-id.bak"))
            self.assertTrue(
                any("changed" in item.casefold() for item in result.conflicts)
            )

    def test_migration_write_reject_leaves_no_backup(self) -> None:
        """write_json_if_unchanged False must not leave a .pre-canonical-id.bak."""
        from core.json_store import write_json_if_unchanged as real_write

        with tempfile.TemporaryDirectory() as root:
            ensembles = os.path.join(root, "ensembles")
            os.makedirs(ensembles)
            ensemble_path = os.path.join(ensembles, "mix.json")
            with open(ensemble_path, "w", encoding="utf-8") as handle:
                json.dump({"selected_models": ["MDX-Net: Model A"]}, handle)

            def write_after_hijack(
                path: str,
                payload: dict,
                expected_digest: str,
                *,
                backup_suffix: str | None = None,
            ) -> bool:
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump({"selected_models": ["hijacked"]}, handle)
                return real_write(
                    path, payload, expected_digest, backup_suffix=backup_suffix,
                )

            settings = Settings.defaults()
            settings.identity_schema_version = 0
            with patch(
                "core.identity_migration.write_json_if_unchanged",
                side_effect=write_after_hijack,
            ):
                result = migrate_identity_storage(
                    settings,
                    _Repo(),
                    profile_directory=os.path.join(root, "profiles"),
                    ensemble_directory=ensembles,
                )
            self.assertEqual(result.files_changed, 0)
            self.assertFalse(os.path.isfile(ensemble_path + ".pre-canonical-id.bak"))
            self.assertTrue(
                any("changed" in item.casefold() for item in result.conflicts)
            )
            with open(ensemble_path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["selected_models"], ["hijacked"])

    def test_repository_initialization_is_singleton_under_concurrency(self) -> None:
        from ui.context import AppContext

        context = AppContext.__new__(AppContext)
        context.settings = Settings.defaults()
        context._repo = None
        context._repo_lock = threading.Lock()
        context._get_dialog_parent = None
        context._unrecognized_hook_installed = False
        created: list[object] = []

        def make_repo() -> object:
            repo = Mock()
            created.append(repo)
            return repo

        barrier = threading.Barrier(8)
        results: list[object] = []

        def access() -> None:
            barrier.wait()
            results.append(context.repo)

        from unittest.mock import patch

        with patch("ui.context.ModelRepository", side_effect=make_repo), patch(
            "core.model_hash_cache.flatten_trusted", return_value={}
        ):
            workers = [threading.Thread(target=access) for _index in range(8)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
        self.assertEqual(len(created), 1)
        self.assertTrue(all(result is created[0] for result in results))


class SharedPolicyTests(unittest.TestCase):
    def test_permissive_and_strict_input_policies_share_discovery(self) -> None:
        service = InputDiscoveryService()
        with tempfile.TemporaryDirectory() as root:
            good = os.path.join(root, "good.wav")
            open(good, "wb").close()
            missing = os.path.join(root, "missing.wav")
            permissive = service.discover(
                [good, missing], InputDiscoveryPolicy(strict=False)
            )
            self.assertEqual(permissive.paths, (os.path.realpath(good),))
            self.assertEqual(permissive.missing, (missing,))
            with self.assertRaisesRegex(ValueError, "not found"):
                service.discover([good, missing], InputDiscoveryPolicy(strict=True))


class JobPlanTests(unittest.TestCase):
    def test_config_plan_is_immutable_and_does_not_create_output(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "song.wav")
            open(source, "wb").close()
            output = os.path.join(root, "out")
            settings = Settings.defaults()
            settings.process.method = ProcessMethod.MDX
            settings.mdx.model = "mdx:model_a"
            plan = JobResolver(_Repo()).resolve(
                JobSpec("separate", settings, (source,), output, {"mdx.model": "gui"}),
                ValidationLevel.CONFIG,
            )
            self.assertTrue(plan.ok)
            self.assertFalse(os.path.exists(output))
            self.assertEqual(plan.inventory_generation, 4)
            self.assertEqual(plan.models[0].id, "mdx:model_a")
            self.assertEqual(len(plan.inputs[0].outputs), 2)
            with self.assertRaises(Exception):
                plan.command = "ensemble"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
