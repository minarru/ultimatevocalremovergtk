from __future__ import annotations

import os
import tempfile
import threading
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import Mock, patch

from core.input_discovery import InputDiscoveryPolicy, InputDiscoveryService
from core.job_plan import JobResolver, JobSpec, ValidationLevel
from core.settings import Settings
from core.settings.defaults import default_settings_dict
from core.types import ProcessMethod


class _Repo:
    inventory_generation = 4
    mdx_name_select_MAPPER: dict[str, str] = {}
    demucs_name_select_MAPPER: dict[str, str] = {}

    def list_vr_models(self) -> list[str]:
        return []

    def list_mdx_models(self) -> list[str]:
        return ["model_a"]

    def list_demucs_models(self) -> list[str]:
        return []

    def vr_catalogue_display_index(self) -> dict[str, str]:
        return {}

    def mdx_catalogue_display_index(self) -> dict[str, str]:
        return {"model_a": "Model A"}

    def demucs_catalogue_display_index(self) -> dict[str, str]:
        return {}


class IdentityServiceTests(unittest.TestCase):
    def test_illegal_stored_text_is_preserved_with_a_warning(self) -> None:
        payload = default_settings_dict()
        payload["mdx"]["model"] = "MDX-Net: Model A"

        settings = Settings.from_json_dict(payload)

        self.assertEqual(settings.mdx.model, "MDX-Net: Model A")
        self.assertTrue(any("mdx.model" in item for item in settings.validation_warnings))

    def test_obsolete_identity_version_is_ignored_on_read(self) -> None:
        payload = default_settings_dict()
        payload["identity_schema_version"] = 1

        settings = Settings.from_json_dict(payload)

        self.assertFalse(hasattr(settings, "identity_schema_version"))
        self.assertNotIn("identity_schema_version", settings.to_json_dict())

    def test_repository_initialization_is_singleton_under_concurrency(self) -> None:
        from ui.context import AppContext

        context = AppContext.__new__(AppContext)
        context.settings = Settings.defaults()
        context._repo = None
        context._repo_lock = threading.Lock()
        context._catalogue = Mock()
        context._catalogue_lock = threading.Lock()
        context._get_dialog_parent = None
        context._unrecognized_hook_installed = False
        created: list[object] = []

        def make_repo(*_args: object, **_kwargs: object) -> object:
            repo = Mock()
            created.append(repo)
            return repo

        barrier = threading.Barrier(8)
        results: list[object] = []

        def access() -> None:
            barrier.wait()
            results.append(context.repo)


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
            with self.assertRaises(FrozenInstanceError):
                plan.command = "ensemble"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
