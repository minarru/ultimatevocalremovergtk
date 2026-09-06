from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import MutableMapping, cast
from unittest.mock import patch

_FIXTURE_DIR = Path(__file__).with_name("fixtures") / "model_manifest"
_CURRENT_MODEL_IDS_FIXTURE = (
    Path(__file__).with_name("fixtures") / "catalogue" / "current_model_ids.txt"
)
_INVERT_CLEAN_ID = "mdx:mbr_invert_clean_becruily"
_RETIRED_BECRUILY_IDS = {
    "mdx:mbr_guitar_becruily",
    "mdx:mbr_inst_becruily",
}
_EXPECTED_DEMUCS_SIGNATURES = {
    "demucs:UVR_Demucs_Model_1": ("instrumental", "vocals"),
    "demucs:demucs": ("drums", "bass", "other", "vocals"),
    "demucs:demucs-e07c671f": ("drums", "bass", "other", "vocals"),
    "demucs:demucs48_hq-28a1282c": ("drums", "bass", "other", "vocals"),
    "demucs:demucs_extra": ("drums", "bass", "other", "vocals"),
    "demucs:demucs_extra-3646af93": ("drums", "bass", "other", "vocals"),
    "demucs:demucs_unittest-09ebc15f": ("drums", "bass", "other", "vocals"),
    "demucs:hdemucs_mmi": ("drums", "bass", "other", "vocals"),
    "demucs:htdemucs": ("drums", "bass", "other", "vocals"),
    "demucs:htdemucs_6s": ("drums", "bass", "other", "vocals", "guitar", "piano"),
    "demucs:htdemucs_ft": ("drums", "bass", "other", "vocals"),
    "demucs:light": ("drums", "bass", "other", "vocals"),
    "demucs:light_extra": ("drums", "bass", "other", "vocals"),
    "demucs:mdx": ("drums", "bass", "other", "vocals"),
    "demucs:mdx_extra": ("drums", "bass", "other", "vocals"),
    "demucs:mdx_extra_q": ("drums", "bass", "other", "vocals"),
    "demucs:mdx_q": ("drums", "bass", "other", "vocals"),
    "demucs:repro_mdx_a": ("drums", "bass", "other", "vocals"),
    "demucs:repro_mdx_a_hybrid_only": ("drums", "bass", "other", "vocals"),
    "demucs:repro_mdx_a_time_only": ("drums", "bass", "other", "vocals"),
    "demucs:tasnet": ("drums", "bass", "other", "vocals"),
    "demucs:tasnet-beb46fac": ("drums", "bass", "other", "vocals"),
    "demucs:tasnet_extra": ("drums", "bass", "other", "vocals"),
    "demucs:tasnet_extra-df3777b2": ("drums", "bass", "other", "vocals"),
}


def _document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "author_aliases": {"alice": "Alice"},
        "roles": {
            "vocal.vocals": {
                "display": "Vocals",
                "filename_tag": "Vocals",
                "family": "vocal",
            }
        },
        "pairs": {},
        "models": {
            "mdx:example": {
                "lifecycle": "current",
                "display_alias": "Example · Alice",
                "display_waivers": {"opaque-token": "Example is reviewed."},
                "stem_semantics": {
                    "native_signature": ["Vocals"],
                    "intent": "vocals",
                    "contexts": {
                        "full_mix": {
                            "logical_primary": "vocal.vocals",
                            "outputs": [
                                {
                                    "native": "Vocals",
                                    "role": "vocal.vocals",
                                }
                            ],
                        }
                    },
                    "review_note": "Exact fixture evidence.",
                },
                "catalogue_evidence": {
                    "source": "fixture",
                    "catalogue_label": "Example by alice",
                    "primary_artifact": "example.ckpt",
                    "metadata_source": "exact_config",
                },
            }
        },
    }


def _legacy_fixture_document() -> dict[str, object]:
    """Test-only migration adapter; production code never imports legacy fixtures."""
    display = json.loads((_FIXTURE_DIR / "legacy_display.json").read_text(encoding="utf-8"))
    stems = json.loads((_FIXTURE_DIR / "legacy_stems.json").read_text(encoding="utf-8"))
    runtime = json.loads((_FIXTURE_DIR / "legacy_runtime.json").read_text(encoding="utf-8"))
    contracts = runtime["contracts"]
    models: dict[str, object] = {}
    for model_id, declaration in stems["models"].items():
        record: dict[str, object] = {
            "lifecycle": "retired" if model_id == "mdx:mbr_guitar_becruily" else "current",
            "stem_semantics": {
                **{key: value for key, value in declaration.items() if key != "evidence"},
                "review_note": declaration["evidence"],
            },
            "catalogue_evidence": {
                "source": "fixture",
                "catalogue_label": model_id,
                "primary_artifact": model_id.removeprefix("mdx:") + ".ckpt",
                "metadata_source": "legacy fixture",
            },
        }
        if model_id in display["model_aliases"]:
            record["display_alias"] = display["model_aliases"][model_id]
        if model_id in display["waivers"]:
            record["display_waivers"] = display["waivers"][model_id]
        if model_id in contracts:
            legacy_contract = contracts[model_id]
            record["config_evidence"] = legacy_contract["config_evidence"]
            record["runtime_contract"] = {
                key: value
                for key, value in legacy_contract.items()
                if key not in {"native_signature", "config_evidence"}
            }
        models[model_id] = record
    for model_id, reason in stems["waivers"].items():
        models[model_id] = {
            "lifecycle": "current",
            "stem_waiver": reason,
            "catalogue_evidence": {
                "source": "fixture",
                "catalogue_label": model_id,
                "primary_artifact": model_id.removeprefix("apollo:") + ".ckpt",
                "metadata_source": "legacy fixture",
            },
        }
    return {
        "schema_version": 1,
        "author_aliases": display["author_aliases"],
        "roles": stems["roles"],
        "pairs": stems["pairs"],
        "models": models,
    }


class ModelManifestTests(unittest.TestCase):
    def test_loads_one_atomic_immutable_registry(self) -> None:
        from core.model_manifest import load_model_manifest_document

        registry = load_model_manifest_document(_document())

        self.assertEqual(registry.presentation["model_aliases"]["mdx:example"], "Example · Alice")
        self.assertEqual(registry.presentation["author_aliases"]["alice"], "Alice")
        self.assertEqual(registry.stems.models["mdx:example"].native_signature, ("Vocals",))
        self.assertEqual(registry.models["mdx:example"].lifecycle, "current")
        with self.assertRaises(TypeError):
            registry.models["mdx:other"] = registry.models["mdx:example"]  # type: ignore[index]

    def test_rejects_unknown_model_field_before_publishing_any_view(self) -> None:
        from core.model_manifest import ModelManifestError, load_model_manifest_document

        document = _document()
        model = document["models"]["mdx:example"]  # type: ignore[index]
        model["surprise"] = True  # type: ignore[index]

        with self.assertRaisesRegex(ModelManifestError, r"models\.mdx:example\.surprise"):
            load_model_manifest_document(document)

    def test_requires_exactly_one_stem_decision(self) -> None:
        from core.model_manifest import ModelManifestError, load_model_manifest_document

        document = _document()
        model = document["models"]["mdx:example"]  # type: ignore[index]
        model["stem_waiver"] = "Not applicable."  # type: ignore[index]

        with self.assertRaisesRegex(ModelManifestError, "exactly one"):
            load_model_manifest_document(document)

    def test_rejects_runtime_contract_for_a_non_mdx_model(self) -> None:
        """A VR model must not acquire an MDX runtime contract by accident."""
        from core.model_manifest import ModelManifestError, load_model_manifest_document

        document = _document()
        models = document["models"]  # type: ignore[index]
        record = models.pop("mdx:example")  # type: ignore[union-attr]
        models["vr:example"] = record  # type: ignore[index]
        record["runtime_contract"] = {  # type: ignore[index]
            "backend": "classic_onnx",
            "primary_native": "Vocals",
            "config_yamls": [],
            "evidence": {
                "artifact_sources": ["bundled/example.onnx"],
                "runtime_metadata_sources": ["models/example.json"],
                "review_note": "Fixture runtime contract.",
            },
            "artifact_evidence": [
                {
                    "uvr_md5": "0" * 32,
                    "hash_record_source": "models/example.json",
                }
            ],
        }

        with self.assertRaisesRegex(
            ModelManifestError, r"models\.vr:example\.runtime_contract.*mdx"
        ):
            load_model_manifest_document(document)

    def test_catalogue_config_name_must_resolve_to_record_config_evidence(self) -> None:
        """A catalogue config hint cannot point outside its model record."""
        from core.model_manifest import ModelManifestError, load_model_manifest_document

        document = _document()
        record = document["models"]["mdx:example"]  # type: ignore[index]
        record["catalogue_evidence"]["config_yaml"] = "example.yaml"  # type: ignore[index]
        record["config_evidence"] = {  # type: ignore[index]
            "other.yaml": {
                "training_instruments": ["Vocals"],
                "target_instrument": "Vocals",
                "content_sha256": "a" * 64,
                "sources": ["cache:fixture"],
            }
        }

        with self.assertRaisesRegex(
            ModelManifestError,
            r"models\.mdx:example\.catalogue_evidence\.config_yaml.*config_evidence",
        ):
            load_model_manifest_document(document)

    def test_rejects_stale_legacy_stem_evidence_before_translation(self) -> None:
        """Unified stem fragments must use review_note, not the legacy evidence key."""
        from core.model_manifest import ModelManifestError, load_model_manifest_document

        document = _document()
        record = document["models"]["mdx:example"]  # type: ignore[index]
        record["stem_semantics"]["evidence"] = "stale legacy evidence"  # type: ignore[index]

        with self.assertRaisesRegex(ModelManifestError, r"stem_semantics\.evidence.*unknown"):
            load_model_manifest_document(document)

    def test_rejects_runtime_native_signature_before_translation(self) -> None:
        """The runtime signature belongs to stem_semantics and cannot be silently replaced."""
        from core.model_manifest import ModelManifestError, load_model_manifest_document

        document = _document()
        record = document["models"]["mdx:example"]  # type: ignore[index]
        record["runtime_contract"] = {
            "backend": "classic_onnx",
            "native_signature": ["Vocals"],
            "primary_native": "Vocals",
            "config_yamls": [],
            "evidence": {
                "artifact_sources": ["bundled/example.onnx"],
                "runtime_metadata_sources": ["models/example.json"],
                "review_note": "Fixture runtime contract.",
            },
            "artifact_evidence": [
                {
                    "uvr_md5": "0" * 32,
                    "hash_record_source": "models/example.json",
                }
            ],
        }

        with self.assertRaisesRegex(
            ModelManifestError, r"runtime_contract\.native_signature.*unknown"
        ):
            load_model_manifest_document(document)

    def test_rejects_runtime_config_evidence_before_translation(self) -> None:
        """Runtime config evidence must be record-local rather than a second mutable copy."""
        from core.model_manifest import ModelManifestError, load_model_manifest_document

        document = _document()
        record = document["models"]["mdx:example"]  # type: ignore[index]
        record["runtime_contract"] = {
            "backend": "classic_onnx",
            "primary_native": "Vocals",
            "config_yamls": [],
            "config_evidence": {},
            "evidence": {
                "artifact_sources": ["bundled/example.onnx"],
                "runtime_metadata_sources": ["models/example.json"],
                "review_note": "Fixture runtime contract.",
            },
            "artifact_evidence": [
                {
                    "uvr_md5": "0" * 32,
                    "hash_record_source": "models/example.json",
                }
            ],
        }

        with self.assertRaisesRegex(
            ModelManifestError, r"runtime_contract\.config_evidence.*unknown"
        ):
            load_model_manifest_document(document)

    def test_config_evidence_is_valid_without_a_runtime_contract(self) -> None:
        """Reviewed config provenance also belongs to non-runtime records."""
        from core.model_manifest import load_model_manifest_document

        document = _document()
        record = document["models"]["mdx:example"]  # type: ignore[index]
        record["config_evidence"] = {  # type: ignore[index]
            "example.yaml": {
                "training_instruments": ["Vocals"],
                "target_instrument": "Vocals",
                "content_sha256": "a" * 64,
                "sources": ["cache:fixture"],
            }
        }

        registry = load_model_manifest_document(document)

        self.assertEqual(
            registry.models["mdx:example"].config_evidence["example.yaml"].target_instrument,
            "Vocals",
        )

    def test_local_config_evidence_must_match_the_checked_in_yaml_bytes(self) -> None:
        """A local source cannot claim a digest or parsed training fields it does not have."""
        from core.model_manifest import ModelManifestError, load_model_manifest_document

        document = _document()
        record = document["models"]["mdx:example"]  # type: ignore[index]
        record["config_evidence"] = {  # type: ignore[index]
            "model_2_stem_full_band_8k.yaml": {
                "training_instruments": ["Vocals"],
                "target_instrument": "Vocals",
                "content_sha256": "a" * 64,
                "sources": [
                    "models/MDX_Net_Models/model_data/mdx_c_configs/model_2_stem_full_band_8k.yaml"
                ],
            }
        }

        with self.assertRaisesRegex(ModelManifestError, r"content_sha256.*local source bytes"):
            load_model_manifest_document(document)

    def test_rejects_case_folded_author_duplicates_and_nested_json_duplicates(self) -> None:
        """JSON parser and document validation both reject ambiguous exact tokens."""
        from core.model_manifest import (
            ModelManifestError,
            load_model_manifest,
            load_model_manifest_document,
        )

        document = _document()
        document["author_aliases"] = {"ViperX": "ViperX", "viperx": "VIPERX"}
        with self.assertRaisesRegex(ModelManifestError, r"author_aliases\.viperx"):
            load_model_manifest_document(document)

        duplicate_nested_key = '''{
          "schema_version": 1,
          "author_aliases": {}, "roles": {}, "pairs": {},
          "models": {"apollo:example": {
            "lifecycle": "current", "stem_waiver": "not applicable",
            "catalogue_evidence": {
              "source": "fixture", "source": "duplicate", "catalogue_label": "example",
              "primary_artifact": "example.ckpt", "metadata_source": "fixture"
            }
          }}
        }'''
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(duplicate_nested_key, encoding="utf-8")
            with self.assertRaisesRegex(ModelManifestError, r"duplicate key 'source'"):
                load_model_manifest(path)

    def test_duplicate_bundled_json_logs_one_critical_failure(self) -> None:
        """Duplicate keys take the bundled failure path before an error reaches callers."""
        import core.model_manifest.loader as loader

        duplicate_root_key = '{"schema_version": 1, "schema_version": 1}'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "model_manifest.json"
            path.write_text(duplicate_root_key, encoding="utf-8")
            with (
                patch.object(loader, "BUNDLED_MODEL_MANIFEST_PATH", path),
                patch.object(loader, "log_event") as log_event,
            ):
                loader.reset_model_manifest_cache_for_tests()
                with self.assertRaisesRegex(
                    loader.ModelManifestError, r"duplicate key 'schema_version'"
                ):
                    loader.load_model_manifest(path)
                with self.assertRaisesRegex(
                    loader.ModelManifestError, r"duplicate key 'schema_version'"
                ):
                    loader.load_model_manifest(path)

            self.assertEqual(log_event.call_count, 1)
            self.assertEqual(log_event.call_args.args, ("model", "model_manifest_invalid"))
            self.assertEqual(log_event.call_args.kwargs["level"], "critical")

    def test_public_values_are_recursively_read_only(self) -> None:
        """Consumers cannot mutate a successfully published registry in place."""
        from core.model_manifest import load_model_manifest_document

        registry = load_model_manifest_document(_legacy_fixture_document())
        contract = registry.runtime.contracts["mdx:MDX23C-8KFFT-InstVoc_HQ"]
        config = registry.models["mdx:MDX23C-8KFFT-InstVoc_HQ"].config_evidence
        mutable_config = cast(MutableMapping[str, object], config)
        mutable_runtime_config = cast(MutableMapping[str, object], contract.config_evidence)

        self.assertIsInstance(contract.config_yamls, tuple)
        with self.assertRaises(TypeError):
            mutable_config["other.yaml"] = config["model_2_stem_full_band_8k.yaml"]
        with self.assertRaises(TypeError):
            mutable_runtime_config["other.yaml"] = contract.config_evidence[
                "model_2_stem_full_band_8k.yaml"
            ]

    def test_path_loader_caches_only_complete_registries_and_can_reset_for_tests(self) -> None:
        """A loader cache must never make a half-validated registry observable."""
        from core.model_manifest import (
            load_model_manifest,
            reset_model_manifest_cache_for_tests,
        )

        with TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(_document()), encoding="utf-8")
            first = load_model_manifest(path)
            self.assertIs(load_model_manifest(path), first)

            changed = _document()
            changed["models"]["mdx:example"]["lifecycle"] = "retired"  # type: ignore[index]
            path.write_text(json.dumps(changed), encoding="utf-8")
            self.assertEqual(load_model_manifest(path).models["mdx:example"].lifecycle, "current")

            reset_model_manifest_cache_for_tests()
            self.assertEqual(load_model_manifest(path).models["mdx:example"].lifecycle, "retired")

    def test_frozen_legacy_fixtures_preserve_all_three_views(self) -> None:
        """The migration fixture holds aliases, reviewed routes, waivers, and contracts."""
        from core.mdx_runtime_contract import load_mdx_runtime_contract_document
        from core.model_manifest import load_model_manifest_document
        from core.model_stem_manifest import load_stem_manifest_document

        display = json.loads((_FIXTURE_DIR / "legacy_display.json").read_text())
        stem_document = json.loads((_FIXTURE_DIR / "legacy_stems.json").read_text())
        stems = load_stem_manifest_document(stem_document)
        runtime_document = json.loads((_FIXTURE_DIR / "legacy_runtime.json").read_text())
        runtime = load_mdx_runtime_contract_document(runtime_document, registry=stems)

        unified = load_model_manifest_document(_legacy_fixture_document())

        self.assertEqual(unified.presentation, display)
        self.assertEqual(unified.stems, stems)
        self.assertEqual(unified.runtime, runtime)
        self.assertEqual(unified.models["mdx:mbr_guitar_becruily"].lifecycle, "retired")
        self.assertIn("apollo:apollo_edm_big_by_essid", unified.stems.waivers)

    def test_obsolete_bundled_authorities_are_absent_from_active_repository_surfaces(
        self,
    ) -> None:
        """Runtime code and every current document name only the unified authority."""
        root = Path(__file__).resolve().parents[1]
        obsolete = (
            "model_display_manifest.json",
            "model_stem_manifest.json",
            "model_runtime_stem_contracts.json",
        )
        for filename in obsolete:
            with self.subTest(authority=filename):
                self.assertFalse((root / "bundled" / filename).exists())

        production_roots = ("bundled", "cli", "core", "engines", "ml", "scripts", "ui")
        active_files = [
            path for directory in production_roots for path in (root / directory).rglob("*.py")
        ]
        historical_roots = tuple(
            root / relative
            for relative in (
                "docs/superpowers/plans",
                "docs/superpowers/specs",
            )
        )
        historical_files = {
            root / "docs/model_display_quality_audit.md",
        }

        def is_allowed_historical_document(path: Path) -> bool:
            return path in historical_files or any(
                path.is_relative_to(directory) for directory in historical_roots
            )

        documentation = [
            root / directory / filename
            for directory in (".", "ui", "cli", "scripts")
            for filename in ("AGENTS.md", "CLAUDE.md")
        ]
        documentation.extend(
            path
            for suffix in ("*.md", "*.tsv")
            for path in (root / "docs").rglob(suffix)
            if not is_allowed_historical_document(path)
        )
        active_files.extend(documentation)
        references = {
            path.relative_to(root).as_posix(): filename
            for path in active_files
            for filename in obsolete
            if filename in path.read_text(encoding="utf-8")
        }
        self.assertEqual(references, {})

    def test_historical_model_designs_link_to_the_unified_superseding_design(self) -> None:
        """Historical contracts remain available but clearly point at their successor."""
        root = Path(__file__).resolve().parents[1]
        successor = "2026-08-27-unified-model-manifest-and-catalogue-evidence-design.md"
        historical = (
            "docs/superpowers/specs/2026-08-22-model-display-projection-refresh-design.md",
            "docs/superpowers/specs/2026-08-24-catalogue-wide-stem-semantics-design.md",
        )
        if not all((root / relative).is_file() for relative in historical):
            self.skipTest("historical design docs live on the dev branch")
        for relative in historical:
            with self.subTest(document=relative):
                text = (root / relative).read_text(encoding="utf-8")
                self.assertIn(successor, text)
                self.assertIn("supersed", text.casefold())

    def test_compatibility_facades_use_the_unified_bundled_path(self) -> None:
        from core.mdx_runtime_contract import BUNDLED_MDX_RUNTIME_CONTRACT_PATH
        from core.model_manifest import BUNDLED_MODEL_MANIFEST_PATH, load_model_manifest
        from core.model_manifest.presentation import presentation_registry
        from core.model_manifest.runtime import mdx_runtime_registry
        from core.model_manifest.stems import stem_semantics_registry
        from core.model_stem_manifest import BUNDLED_MANIFEST_PATH

        self.assertEqual(BUNDLED_MANIFEST_PATH, BUNDLED_MODEL_MANIFEST_PATH)
        self.assertEqual(BUNDLED_MDX_RUNTIME_CONTRACT_PATH, BUNDLED_MODEL_MANIFEST_PATH)
        registry = load_model_manifest()
        from core.mdx_runtime_contract import load_mdx_runtime_contracts
        from core.model_naming import load_model_display_manifest
        from core.model_stem_manifest import load_stem_manifest

        self.assertIs(presentation_registry(), registry.presentation)
        self.assertIs(stem_semantics_registry(), registry.stems)
        self.assertIs(mdx_runtime_registry(), registry.runtime)
        self.assertIs(load_model_display_manifest(), registry.presentation)
        self.assertIs(load_stem_manifest(BUNDLED_MANIFEST_PATH), registry.stems)
        self.assertIs(
            load_mdx_runtime_contracts(BUNDLED_MDX_RUNTIME_CONTRACT_PATH),
            registry.runtime,
        )
        contract = registry.runtime.contracts["mdx:MDX23C-8KFFT-InstVoc_HQ"]
        self.assertIs(
            contract.native_signature,
            registry.stems.models[contract.model_id].native_signature,
        )
        self.assertIs(
            contract.config_evidence,
            registry.models[contract.model_id].config_evidence,
        )

    def test_compatibility_path_loaders_are_thin_unified_facades(self) -> None:
        """Explicit facade paths delegate without maintaining parallel JSON readers."""
        from core.mdx_runtime_contract import load_mdx_runtime_contracts
        from core.model_naming import load_model_display_manifest
        from core.model_stem_manifest import load_stem_manifest

        sentinel = SimpleNamespace(
            presentation=object(),
            stems=object(),
            runtime=object(),
        )
        path = Path("/fixture/unified-model-manifest.json")
        with patch("core.model_manifest.load_model_manifest", return_value=sentinel) as load:
            self.assertIs(load_model_display_manifest(path), sentinel.presentation)
            self.assertIs(load_stem_manifest(path), sentinel.stems)
            self.assertIs(load_mdx_runtime_contracts(path), sentinel.runtime)

        self.assertEqual([call.args for call in load.call_args_list], [(path,), (path,), (path,)])

    def test_invalid_presentation_prevents_stem_and_runtime_views_from_publishing(self) -> None:
        """A malformed presentation domain cannot publish a partial unified manifest."""
        import core.model_manifest.loader as loader

        document = _document()
        document["author_aliases"] = {"Alice": "Alice", "alice": "ALICE"}
        with (
            patch.object(loader, "build_stem_view") as build_stems,
            patch.object(loader, "build_runtime_view") as build_runtime,
        ):
            with self.assertRaisesRegex(loader.ModelManifestError, r"author_aliases\.alice"):
                loader.load_model_manifest_document(document)

        build_stems.assert_not_called()
        build_runtime.assert_not_called()

    def test_invalid_stem_domain_prevents_presentation_from_publishing(self) -> None:
        """A malformed stem domain cannot publish the otherwise valid presentation view."""
        import core.model_manifest.loader as loader

        document = _document()
        record = document["models"]["mdx:example"]  # type: ignore[index]
        record["stem_semantics"]["contexts"] = {}  # type: ignore[index]
        with patch.object(loader, "build_presentation_view") as build_presentation:
            with self.assertRaisesRegex(
                loader.ModelManifestError, r"models\.mdx:example\.contexts"
            ):
                loader.load_model_manifest_document(document)

        build_presentation.assert_not_called()

    def test_display_facade_rejects_duplicate_keys_in_an_explicit_unified_manifest(self) -> None:
        """The presentation adapter must retain duplicate checks outside its own domain."""
        from core.model_naming import load_model_display_manifest

        document = '''{
          "schema_version": 1,
          "author_aliases": {},
          "roles": {
            "vocal.vocals": {
              "display": "Vocals",
              "display": "Duplicated",
              "filename_tag": "Vocals",
              "family": "vocal"
            }
          },
          "pairs": {},
          "models": {}
        }'''
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unified.json"
            path.write_text(document, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"duplicate key 'display'"):
                load_model_display_manifest(path)

    def test_unified_cross_domain_failures_are_fail_closed_at_legacy_boundaries(self) -> None:
        """Any invalid unified domain leaves stem and runtime consumers on their safe shapes."""
        from core.mdx_runtime_contract import load_bundled_mdx_runtime_contracts
        from core.model_manifest import BUNDLED_MODEL_MANIFEST_PATH
        from core.model_stem_manifest import (
            load_bundled_stem_semantics,
            resolve_model_stem_semantics,
        )
        from core.stem_roles import StemReviewStatus

        self.addCleanup(load_bundled_stem_semantics.cache_clear)
        self.addCleanup(load_bundled_mdx_runtime_contracts.cache_clear)
        cases = {
            "presentation": lambda document: document["author_aliases"].update({"viperx": ""}),
            "stems": lambda document: document["models"]["mdx:MDX23C-8KFFT-InstVoc_HQ"][
                "stem_semantics"
            ].update({"contexts": {}}),
            "runtime": lambda document: document["models"]["mdx:MDX23C-8KFFT-InstVoc_HQ"][
                "runtime_contract"
            ].update({"backend": "not-a-backend"}),
        }
        with TemporaryDirectory() as directory:
            for domain, invalidate in cases.items():
                with self.subTest(domain=domain):
                    document = json.loads(BUNDLED_MODEL_MANIFEST_PATH.read_text(encoding="utf-8"))
                    invalidate(document)
                    path = Path(directory) / f"{domain}.json"
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with (
                        patch("core.model_stem_manifest.BUNDLED_MANIFEST_PATH", path),
                        patch("core.mdx_runtime_contract.BUNDLED_MDX_RUNTIME_CONTRACT_PATH", path),
                        patch("core.model_stem_manifest.log_event") as stem_log,
                        patch("core.mdx_runtime_contract.log_event") as runtime_log,
                    ):
                        load_bundled_stem_semantics.cache_clear()
                        load_bundled_mdx_runtime_contracts.cache_clear()
                        stems = load_bundled_stem_semantics()
                        runtime = load_bundled_mdx_runtime_contracts()
                        raw = resolve_model_stem_semantics(
                            "mdx:MDX23C-8KFFT-InstVoc_HQ",
                            native_stems=("Instrumental", "Vocals"),
                        )

                    self.assertEqual(stems.models, {})
                    self.assertEqual(raw.status, StemReviewStatus.RAW)
                    self.assertEqual(runtime.contracts, {})
                    self.assertTrue(runtime.warning.startswith("runtime-contract-unavailable"))
                    stem_log.assert_called_once()
                    runtime_log.assert_called_once()


class CurrentCatalogueManifestTests(unittest.TestCase):
    def test_reviewed_current_snapshot_is_exactly_485_sorted_unique_ids(self) -> None:
        """The expected Download Center membership is an explicit reviewed fixture."""
        from core.model_manifest import load_model_manifest

        expected_ids = _CURRENT_MODEL_IDS_FIXTURE.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(expected_ids), 485)
        self.assertEqual(expected_ids, sorted(expected_ids))
        self.assertEqual(len(set(expected_ids)), 485)

        registry = load_model_manifest()
        current_ids = {
            model_id
            for model_id, record in registry.models.items()
            if record.lifecycle == "current"
        }
        self.assertEqual(current_ids, set(expected_ids))
        self.assertTrue(_RETIRED_BECRUILY_IDS.isdisjoint(expected_ids))

    def test_invert_clean_record_pins_exact_reviewed_source_and_config_evidence(self) -> None:
        from core.model_manifest import load_model_manifest

        registry = load_model_manifest()
        record = registry.models[_INVERT_CLEAN_ID]
        self.assertEqual(record.lifecycle, "current")
        self.assertEqual(
            registry.presentation["model_aliases"][_INVERT_CLEAN_ID],
            "MelBand Roformer — Invert Clean · Becruily",
        )
        evidence = record.catalogue_evidence
        self.assertEqual(
            (
                evidence.source,
                evidence.catalogue_label,
                evidence.primary_artifact,
                evidence.config_yaml,
                evidence.metadata_source,
            ),
            (
                "mvsepless",
                "Mel-Band Roformer Invert Clean by Becruily",
                "mbr_invert_clean_becruily.ckpt",
                "mbr_invert_clean_becruily_config.yaml",
                "remote_yaml:mbr_invert_clean_becruily_config.yaml",
            ),
        )
        config = record.config_evidence["mbr_invert_clean_becruily_config.yaml"]
        self.assertEqual(config.training_instruments, ("Vocals", "Other"))
        self.assertEqual(config.target_instrument, "Vocals")
        self.assertEqual(
            config.content_sha256,
            "d5a9551d1f1d1b2f0ac4b911a62d6deb36bbe3b965dadb6207dbe19ba002b547",
        )
        self.assertEqual(
            config.sources,
            (
                "https://huggingface.co/noblebarkrr/mvsepless_resources/resolve/main/"
                "mel_band_roformer/mbr_invert_clean_becruily_config.yaml?download=true",
            ),
        )

    def test_retired_becruily_records_remain_available_to_installed_projections(self) -> None:
        from core.model_manifest import load_model_manifest
        from core.model_naming import project_model_display

        registry = load_model_manifest()
        expected_displays = {
            "mdx:mbr_guitar_becruily": (
                "MelBand Roformer — Instrumental · Becruily [mbr_guitar_becruily]"
            ),
            "mdx:mbr_inst_becruily": (
                "MelBand Roformer — Instrumental · Becruily [mbr_inst_becruily]"
            ),
        }
        self.assertEqual(
            {
                model_id
                for model_id, record in registry.models.items()
                if record.lifecycle == "retired"
            },
            _RETIRED_BECRUILY_IDS,
        )
        for model_id, expected_display in expected_displays.items():
            with self.subTest(model_id=model_id):
                self.assertIn(model_id, registry.stems.models)
                self.assertEqual(project_model_display(model_id), expected_display)

    def test_all_demucs_signatures_and_vr_bve_record_are_exact_manifest_data(self) -> None:
        from core.model_manifest import load_model_manifest
        from core.stem_roles import StemProcessingContext

        registry = load_model_manifest()
        self.assertEqual(
            {
                model_id: registry.stems.models[model_id].native_signature
                for model_id, record in registry.models.items()
                if model_id.startswith("demucs:") and record.lifecycle == "current"
            },
            _EXPECTED_DEMUCS_SIGNATURES,
        )

        model_id = "vr:UVR-BVE-4B_SN-44100-1"
        record = registry.models[model_id]
        evidence = record.catalogue_evidence
        self.assertEqual(
            (
                record.lifecycle,
                registry.presentation["model_aliases"][model_id],
                evidence.source,
                evidence.catalogue_label,
                evidence.primary_artifact,
                evidence.metadata_source,
            ),
            (
                "current",
                "VR v5 — Karaoke BVE (4 Bands, SN, 44.1 kHz) 1",
                "TRvlvr+Politrees",
                "VR Arch Single Model v5: UVR-BVE-4B_SN-44100-1",
                "UVR-BVE-4B_SN-44100-1.pth",
                "community_models.txt+politrees_vr_hash",
            ),
        )
        declaration = registry.stems.models[model_id]
        self.assertEqual(declaration.native_signature, ("Vocals", "Instrumental"))
        self.assertEqual(declaration.intent, "vocals")
        self.assertEqual(
            {
                context.value: (
                    declaration.contexts[context].logical_primary.value,
                    tuple(
                        (output.native.raw, str(output.role))
                        for output in declaration.contexts[context].outputs
                        if output.native is not None
                    ),
                )
                for context in (
                    StemProcessingContext.FULL_MIX,
                    StemProcessingContext.VOCAL_SPLIT,
                )
            },
            {
                "full_mix": (
                    "vocal.backing",
                    (
                        ("Vocals", "vocal.backing"),
                        ("Instrumental", "mix.instrumental_with_lead_vocals"),
                    ),
                ),
                "vocal_split": (
                    "vocal.backing",
                    (
                        ("Vocals", "vocal.backing"),
                        ("Instrumental", "vocal.lead"),
                    ),
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
