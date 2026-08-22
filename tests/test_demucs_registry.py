from __future__ import annotations

import json
import os
import tempfile
import unittest

from core.model_identity import DemucsSpec


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

        from bundled.constants import DEMUCS_ARCH_TYPE
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
