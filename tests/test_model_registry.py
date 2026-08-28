"""Durable hash ownership and exact model-presentation evidence."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import warnings
from unittest import mock

from core.model_registry import ModelRegistryService
from core.name_mapper import local_overlay_path


def _write_json(path: str, payload: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _legacy_overlay_archive_path(mapper_path: str) -> str:
    overlay = local_overlay_path(mapper_path)
    return f"{os.path.splitext(overlay)[0]}.legacy.json"


class ModelRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.runtime_dir = os.path.join(self.root, ".uvr-runtime")
        self.registry_path = os.path.join(self.runtime_dir, "registered_models.json")
        self.legacy_path = os.path.join(self.root, "registered_models.json")
        self.mdx_mapper = os.path.join(self.root, "mdx", "model_data", "model_name_mapper.json")
        self.demucs_mapper = os.path.join(
            self.root, "demucs", "model_data", "model_name_mapper.json"
        )
        patches = (
            mock.patch(
                "core.model_registry.paths.REGISTERED_MODEL_INDEX",
                self.registry_path,
            ),
            mock.patch(
                "core.model_registry.paths.LEGACY_REGISTERED_MODEL_INDEX",
                self.legacy_path,
            ),
            mock.patch(
                "core.model_registry.paths.MDX_MODEL_NAME_SELECT",
                self.mdx_mapper,
            ),
            mock.patch(
                "core.model_registry.paths.DEMUCS_MODEL_NAME_SELECT",
                self.demucs_mapper,
            ),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_reads_merge_legacy_and_runtime_without_mutating_either_file(self) -> None:
        legacy = {
            "schema_version": 2,
            "hashes": {"shared": "mdx:legacy", "legacy-only": "vr:legacy"},
            "models": {
                "mdx:model": {
                    "catalogue_label": "Legacy label",
                    "catalogue_source": "legacy-source",
                    "display_override": "Legacy override",
                }
            },
        }
        runtime = {
            "schema_version": 2,
            "hashes": {"shared": "mdx:runtime", "runtime-only": "vr:runtime"},
            "models": {
                "mdx:model": {
                    "catalogue_label": "Runtime label",
                    "display_override": "Runtime override",
                }
            },
        }
        _write_json(self.legacy_path, legacy)
        _write_json(self.registry_path, runtime)
        legacy_bytes = _read_bytes(self.legacy_path)
        runtime_bytes = _read_bytes(self.registry_path)

        self.assertEqual(ModelRegistryService.registered_id("shared"), "mdx:runtime")
        self.assertEqual(ModelRegistryService.registered_id("legacy-only"), "vr:legacy")
        self.assertEqual(
            ModelRegistryService.presentation("mdx:model"),
            {
                "catalogue_label": "Runtime label",
                "catalogue_source": "legacy-source",
                "display_override": "Runtime override",
            },
        )
        self.assertEqual(_read_bytes(self.legacy_path), legacy_bytes)
        self.assertEqual(_read_bytes(self.registry_path), runtime_bytes)

    def test_first_mutation_migrates_and_archives_legacy_registry(self) -> None:
        _write_json(self.legacy_path, {"legacy-hash": "mdx:legacy"})
        legacy_bytes = _read_bytes(self.legacy_path)

        self.assertTrue(ModelRegistryService.remember_registered("new-hash", "vr:new"))

        self.assertEqual(
            _read_json(self.registry_path),
            {
                "schema_version": 2,
                "hashes": {"legacy-hash": "mdx:legacy", "new-hash": "vr:new"},
                "models": {},
            },
        )
        self.assertFalse(os.path.exists(self.legacy_path))
        archive = os.path.join(self.runtime_dir, "registered_models.legacy.json")
        self.assertEqual(_read_bytes(archive), legacy_bytes)

    def test_existing_archive_uses_next_available_number(self) -> None:
        _write_json(self.legacy_path, {"legacy-hash": "mdx:legacy"})
        first_archive = os.path.join(self.runtime_dir, "registered_models.legacy.json")
        _write_json(first_archive, {"older": "mdx:older"})

        ModelRegistryService.remember_registered("new-hash", "vr:new")

        self.assertTrue(os.path.isfile(first_archive))
        numbered = os.path.join(self.runtime_dir, "registered_models.legacy.1.json")
        self.assertEqual(_read_json(numbered), {"legacy-hash": "mdx:legacy"})

    def test_corrupt_legacy_read_warns_and_uses_valid_runtime_registry(self) -> None:
        os.makedirs(os.path.dirname(self.legacy_path), exist_ok=True)
        with open(self.legacy_path, "wb") as handle:
            handle.write(b'{"schema_version": 2, "hashes": ')
        _write_json(
            self.registry_path,
            {
                "schema_version": 2,
                "hashes": {"runtime-hash": "mdx:runtime"},
                "models": {},
            },
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            resolved = ModelRegistryService.registered_id("runtime-hash")

        self.assertEqual(resolved, "mdx:runtime")
        self.assertTrue(any("legacy model registry" in str(item.message) for item in caught))

    def test_corrupt_legacy_blocks_mutation_without_touching_runtime(self) -> None:
        os.makedirs(os.path.dirname(self.legacy_path), exist_ok=True)
        with open(self.legacy_path, "wb") as handle:
            handle.write(b'{"schema_version": 2, "hashes": ')
        _write_json(
            self.registry_path,
            {
                "schema_version": 2,
                "hashes": {"runtime-hash": "mdx:runtime"},
                "models": {},
            },
        )
        runtime_bytes = _read_bytes(self.registry_path)
        legacy_bytes = _read_bytes(self.legacy_path)

        with self.assertRaisesRegex(ValueError, "legacy model registry"):
            ModelRegistryService.remember_registered("new-hash", "vr:new")

        self.assertEqual(_read_bytes(self.registry_path), runtime_bytes)
        self.assertEqual(_read_bytes(self.legacy_path), legacy_bytes)

    def test_failed_runtime_write_keeps_legacy_and_runtime_unarchived(self) -> None:
        _write_json(self.legacy_path, {"legacy-hash": "mdx:legacy"})
        _write_json(
            self.registry_path,
            {"schema_version": 2, "hashes": {"runtime-hash": "mdx:runtime"}, "models": {}},
        )
        runtime_bytes = _read_bytes(self.registry_path)
        legacy_bytes = _read_bytes(self.legacy_path)

        with (
            mock.patch("core.model_registry.write_json_atomic", side_effect=OSError("disk full")),
            self.assertRaisesRegex(OSError, "disk full"),
        ):
            ModelRegistryService.remember_registered("new-hash", "vr:new")

        self.assertEqual(_read_bytes(self.registry_path), runtime_bytes)
        self.assertEqual(_read_bytes(self.legacy_path), legacy_bytes)
        self.assertFalse(
            os.path.exists(os.path.join(self.runtime_dir, "registered_models.legacy.json"))
        )

    def test_archive_failure_warns_and_keeps_published_runtime_registry(self) -> None:
        _write_json(self.legacy_path, {"legacy-hash": "mdx:legacy"})

        with (
            mock.patch("core.model_registry.shutil.move", side_effect=OSError("read only")),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            changed = ModelRegistryService.remember_registered("new-hash", "vr:new")

        self.assertTrue(changed)
        self.assertEqual(
            _read_json(self.registry_path)["hashes"],
            {"legacy-hash": "mdx:legacy", "new-hash": "vr:new"},
        )
        self.assertTrue(os.path.isfile(self.legacy_path))
        self.assertTrue(any("archive failed" in str(item.message) for item in caught))

    def test_noop_retry_finishes_archive_after_previous_archive_failure(self) -> None:
        _write_json(self.legacy_path, {"legacy-hash": "mdx:legacy"})
        with (
            mock.patch("core.model_registry.shutil.move", side_effect=OSError("read only")),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore")
            ModelRegistryService.remember_registered("new-hash", "vr:new")

        changed = ModelRegistryService.remember_registered("new-hash", "vr:new")

        self.assertFalse(changed)
        self.assertFalse(os.path.exists(self.legacy_path))
        self.assertTrue(
            os.path.isfile(os.path.join(self.runtime_dir, "registered_models.legacy.json"))
        )

    def test_flat_schema_reads_without_rewriting(self) -> None:
        _write_json(self.registry_path, {"hash-a": "mdx:alpha"})
        with open(self.registry_path, "rb") as handle:
            original = handle.read()

        self.assertEqual(ModelRegistryService.registered_id("hash-a"), "mdx:alpha")
        self.assertEqual(ModelRegistryService.presentation("mdx:alpha"), {})

        with open(self.registry_path, "rb") as handle:
            self.assertEqual(handle.read(), original)

    def test_hash_mutation_upgrades_flat_schema_and_preserves_ownership(self) -> None:
        _write_json(self.registry_path, {"hash-a": "mdx:alpha"})

        self.assertTrue(ModelRegistryService.remember_registered("hash-b", "vr:beta"))

        self.assertEqual(
            _read_json(self.registry_path),
            {
                "schema_version": 2,
                "hashes": {"hash-a": "mdx:alpha", "hash-b": "vr:beta"},
                "models": {},
            },
        )
        self.assertEqual(ModelRegistryService.registered_id("hash-a"), "mdx:alpha")

    def test_forget_hash_preserves_presentation_entries(self) -> None:
        _write_json(
            self.registry_path,
            {
                "schema_version": 2,
                "hashes": {"hash-a": "mdx:alpha"},
                "models": {
                    "mdx:alpha": {
                        "catalogue_label": "MDX-Net Model: Alpha",
                        "catalogue_source": "upstream",
                    }
                },
            },
        )

        ModelRegistryService.forget_registered("hash-a")

        self.assertEqual(
            _read_json(self.registry_path),
            {
                "schema_version": 2,
                "hashes": {},
                "models": {
                    "mdx:alpha": {
                        "catalogue_label": "MDX-Net Model: Alpha",
                        "catalogue_source": "upstream",
                    }
                },
            },
        )

    def test_presentation_round_trip_omits_empty_fields(self) -> None:
        changed = ModelRegistryService.remember_presentation(
            "mdx:alpha",
            catalogue_label="MDX-Net Model: Alpha",
            catalogue_source="upstream",
            display_override="",
        )

        self.assertTrue(changed)
        self.assertEqual(
            ModelRegistryService.presentation("mdx:alpha"),
            {
                "catalogue_label": "MDX-Net Model: Alpha",
                "catalogue_source": "upstream",
            },
        )
        self.assertEqual(
            _read_json(self.registry_path)["models"]["mdx:alpha"],
            {
                "catalogue_label": "MDX-Net Model: Alpha",
                "catalogue_source": "upstream",
            },
        )

    def test_catalogue_backfill_preserves_explicit_override(self) -> None:
        ModelRegistryService.remember_presentation(
            "mdx:alpha",
            catalogue_label="Old label",
            catalogue_source="old-source",
            display_override="Trusted Alpha",
        )

        changed = ModelRegistryService.remember_presentation(
            "mdx:alpha",
            catalogue_label="New label",
            catalogue_source="new-source",
        )
        self.assertTrue(changed)
        changed = ModelRegistryService.remember_presentation(
            "mdx:alpha",
            catalogue_label="Newest label",
            display_override="",
        )

        self.assertTrue(changed)
        self.assertEqual(
            ModelRegistryService.presentation("mdx:alpha"),
            {
                "catalogue_label": "Newest label",
                "catalogue_source": "new-source",
                "display_override": "Trusted Alpha",
            },
        )

    def test_non_string_presentation_fields_cannot_poison_registry(self) -> None:
        trusted = {
            "schema_version": 2,
            "hashes": {"hash-a": "mdx:alpha"},
            "models": {
                "mdx:alpha": {
                    "catalogue_label": "Alpha",
                    "catalogue_source": "upstream",
                    "display_override": "Trusted Alpha",
                }
            },
        }
        invalid_updates: tuple[dict[str, object], ...] = (
            {"catalogue_label": 42},
            {"catalogue_source": None},
            {"display_override": None},
        )

        for invalid_update in invalid_updates:
            with self.subTest(invalid_update=invalid_update):
                _write_json(self.registry_path, trusted)
                with open(self.registry_path, "rb") as handle:
                    original = handle.read()

                with self.assertRaisesRegex(ValueError, "must be strings"):
                    ModelRegistryService.remember_presentation(
                        "mdx:alpha",
                        **invalid_update,  # type: ignore[arg-type]
                    )

                with open(self.registry_path, "rb") as handle:
                    self.assertEqual(handle.read(), original)
                self.assertEqual(
                    ModelRegistryService.presentation("mdx:alpha"),
                    trusted["models"]["mdx:alpha"],
                )

    def test_presentation_keys_must_be_exact_canonical_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical model ID"):
            ModelRegistryService.presentation("alpha")
        with self.assertRaisesRegex(ValueError, "canonical model ID"):
            ModelRegistryService.remember_presentation("MDX:alpha", catalogue_label="Alpha")
        self.assertFalse(os.path.exists(self.registry_path))

    def test_concurrent_hash_and_presentation_updates_preserve_both_maps(self) -> None:
        barrier = threading.Barrier(12)

        def remember_hash(index: int) -> None:
            barrier.wait()
            ModelRegistryService.remember_registered(f"hash-{index}", f"mdx:model-{index}")

        def remember_presentation(index: int) -> None:
            barrier.wait()
            ModelRegistryService.remember_presentation(
                f"mdx:model-{index}",
                catalogue_label=f"Model {index}",
                catalogue_source="test",
            )

        workers = [threading.Thread(target=remember_hash, args=(index,)) for index in range(6)] + [
            threading.Thread(target=remember_presentation, args=(index,)) for index in range(6)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        payload = _read_json(self.registry_path)
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(len(payload["hashes"]), 6)
        self.assertEqual(len(payload["models"]), 6)
        for index in range(6):
            self.assertEqual(payload["hashes"][f"hash-{index}"], f"mdx:model-{index}")
            self.assertEqual(
                payload["models"][f"mdx:model-{index}"]["catalogue_label"],
                f"Model {index}",
            )

    def test_malformed_registry_is_not_truncated_by_a_mutation(self) -> None:
        os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
        malformed = b'{"schema_version": 2, "hashes": '
        with open(self.registry_path, "wb") as handle:
            handle.write(malformed)

        with self.assertRaises(ValueError):
            ModelRegistryService.remember_registered("hash-a", "mdx:alpha")

        with open(self.registry_path, "rb") as handle:
            self.assertEqual(handle.read(), malformed)

    def test_failed_atomic_presentation_write_keeps_registry_and_overlay(self) -> None:
        _write_json(self.registry_path, {"hash-a": "mdx:alpha"})
        overlay = local_overlay_path(self.mdx_mapper)
        _write_json(overlay, {"alpha.ckpt": "Legacy Alpha"})
        with open(self.registry_path, "rb") as handle:
            original = handle.read()

        with (
            mock.patch("core.json_store.os.replace", side_effect=OSError("disk full")),
            self.assertRaisesRegex(OSError, "disk full"),
        ):
            ModelRegistryService.remember_presentation("mdx:alpha", catalogue_label="Alpha")

        with open(self.registry_path, "rb") as handle:
            self.assertEqual(handle.read(), original)
        self.assertTrue(os.path.isfile(overlay))
        self.assertFalse(os.path.exists(_legacy_overlay_archive_path(self.mdx_mapper)))

    def test_first_presentation_mutation_archives_each_legacy_overlay_once(self) -> None:
        mdx_overlay = local_overlay_path(self.mdx_mapper)
        demucs_overlay = local_overlay_path(self.demucs_mapper)
        _write_json(mdx_overlay, {"alpha.ckpt": "Legacy Alpha"})
        _write_json(demucs_overlay, {"beta.th": "Legacy Beta"})

        ModelRegistryService.remember_presentation("mdx:alpha", catalogue_label="Alpha")

        for mapper, overlay in (
            (self.mdx_mapper, mdx_overlay),
            (self.demucs_mapper, demucs_overlay),
        ):
            archive = _legacy_overlay_archive_path(mapper)
            self.assertFalse(os.path.exists(overlay))
            self.assertTrue(os.path.isfile(archive))
        self.assertEqual(
            _read_json(_legacy_overlay_archive_path(self.mdx_mapper)),
            {"alpha.ckpt": "Legacy Alpha"},
        )

    def test_existing_archive_blocks_move_without_overwriting_either_file(self) -> None:
        overlay = local_overlay_path(self.mdx_mapper)
        archive = _legacy_overlay_archive_path(self.mdx_mapper)
        _write_json(overlay, {"alpha.ckpt": "Current legacy"})
        _write_json(archive, {"alpha.ckpt": "Existing archive"})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ModelRegistryService.remember_presentation("mdx:alpha", catalogue_label="Alpha")

        self.assertEqual(_read_json(overlay), {"alpha.ckpt": "Current legacy"})
        self.assertEqual(_read_json(archive), {"alpha.ckpt": "Existing archive"})
        self.assertTrue(any("archive already exists" in str(item.message) for item in caught))


if __name__ == "__main__":
    unittest.main()
