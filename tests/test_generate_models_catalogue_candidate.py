"""Generator candidate behavior."""

import os
import unittest
from unittest import mock

# Load the script path before top-level catalogue imports (one module identity).
# isort: off
from tests import generator_fixtures as fixtures

from catalogue import audit_types as catalogue_audit_types
from catalogue import cache as catalogue_cache
from catalogue import collect as catalogue
from catalogue import evidence as catalogue_evidence
from catalogue import locations as catalogue_locations
from catalogue import manifest_candidate as catalogue_manifest_candidate
from catalogue import types as catalogue_types





# isort: on

class ManifestCandidateContractTests(unittest.TestCase):
    """The generator changes machine evidence without fabricating review decisions."""

    def test_demucs_bundle_yaml_is_not_published_as_mdx_config_evidence(self) -> None:
        entry = catalogue_types.ModelEntry(
            source="fixture-source",
            family="Demucs",
            catalogue_label="Demucs v4: htdemucs_6s",
            weight_file="5c90dfd2-34c22ccb.th",
            config_yaml="htdemucs_6s.yaml",
            metadata_source="catalogue_demucs_declaration",
        )

        self.assertNotIn(
            "config_yaml",
            catalogue_manifest_candidate._manifest_evidence_document(entry),
        )

    def test_candidate_keeps_richer_exact_provenance_for_the_same_artifact(self) -> None:
        from core.model_manifest import load_model_manifest_document

        document = fixtures._generator_manifest_document()
        evidence = document["models"]["mdx:model"]["catalogue_evidence"]
        evidence.update(
            {
                "source": "fixture-source",
                "catalogue_label": "Fixture Model",
                "primary_artifact": "model.ckpt",
                "metadata_source": "remote_yaml:model.yaml+exact_artifact_hash",
            }
        )
        unified = load_model_manifest_document(document)

        candidate = catalogue_manifest_candidate.build_manifest_candidate(
            [fixtures._generator_manifest_entry()],
            document,
            registry=unified,
        )

        self.assertEqual(
            fixtures._candidate_document(candidate)["models"]["mdx:model"]["catalogue_evidence"][
                "metadata_source"
            ],
            "remote_yaml:model.yaml+exact_artifact_hash",
        )

    def _candidate(
        self,
        entries: list[catalogue_types.ModelEntry],
        *,
        lifecycle: str = "current",
        strict_runtime: bool = False,
    ) -> catalogue_audit_types.ManifestCandidateResult:
        from dataclasses import replace
        from types import SimpleNamespace

        from core.model_manifest import load_model_manifest_document

        document = fixtures._generator_manifest_document(lifecycle=lifecycle)
        registry = load_model_manifest_document(document)
        if strict_runtime:
            registry = replace(
                registry,
                runtime=SimpleNamespace(contracts={"mdx:model": object()}),
            )
        return catalogue_manifest_candidate.build_manifest_candidate(entries, document, registry=registry)

    def test_new_catalogue_id_requires_a_reviewed_record(self) -> None:
        result = self._candidate([fixtures._generator_manifest_entry(weight_file="new.ckpt")])

        self.assertIn("manifest-new-current", {item.code for item in result.diagnostics})
        self.assertFalse(result.structurally_valid)

    def test_missing_current_id_requires_explicit_retirement(self) -> None:
        result = self._candidate([])

        finding = next(
            item for item in result.diagnostics if item.code == "manifest-missing-current"
        )
        self.assertEqual(finding.model_ids, ("mdx:model",))
        self.assertFalse(result.structurally_valid)

    def test_retired_id_cannot_reappear_without_lifecycle_review(self) -> None:
        result = self._candidate([fixtures._generator_manifest_entry()], lifecycle="retired")

        finding = next(
            item for item in result.diagnostics if item.code == "manifest-retired-reappeared"
        )
        self.assertEqual(finding.model_ids, ("mdx:model",))
        self.assertFalse(result.structurally_valid)

    def test_same_semantics_digest_drift_updates_only_machine_evidence(self) -> None:
        result = self._candidate([fixtures._generator_manifest_entry(config_sha256="b" * 64)])

        self.assertTrue(result.structurally_valid)
        self.assertEqual(
            [item.code for item in result.diagnostics],
            ["config-digest-drift"],
        )
        record = fixtures._candidate_document(result)["models"]["mdx:model"]
        self.assertEqual(record["display_alias"], "Reviewed Fixture")
        self.assertEqual(
            record["stem_semantics"]["review_note"],
            "Human-reviewed fixture semantics.",
        )
        self.assertEqual(
            record["config_evidence"]["model.yaml"]["content_sha256"],
            "b" * 64,
        )
        self.assertEqual(
            record["config_evidence"]["model.yaml"]["sources"],
            ["https://new.test/model.yaml"],
        )

    def test_strict_runtime_digest_drift_keeps_the_approved_digest(self) -> None:
        result = self._candidate(
            [fixtures._generator_manifest_entry(config_sha256="b" * 64)],
            strict_runtime=True,
        )

        self.assertFalse(result.structurally_valid)
        self.assertIn(
            "runtime-config-digest-mismatch",
            {item.code for item in result.diagnostics},
        )
        self.assertEqual(
            fixtures._candidate_document(result)["models"]["mdx:model"]["config_evidence"]["model.yaml"][
                "content_sha256"
            ],
            "a" * 64,
        )

    def test_config_signature_or_target_drift_blocks_candidate(self) -> None:
        cases = (
            {"instruments": ["Vocals", "Drums"]},
            {"target_instrument": "Other"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                result = self._candidate([fixtures._generator_manifest_entry(**changes)])
                self.assertIn(
                    "config-semantic-mismatch",
                    {item.code for item in result.diagnostics},
                )
                self.assertFalse(result.structurally_valid)

    def test_missing_config_association_keeps_the_reviewed_evidence(self) -> None:
        result = self._candidate(
            [
                fixtures._generator_manifest_entry(
                    config_yaml="",
                    config_url="",
                    config_sha256="",
                )
            ]
        )

        self.assertFalse(result.structurally_valid)
        self.assertTrue(result.degraded)
        self.assertEqual(
            fixtures._candidate_document(result)["models"]["mdx:model"]["catalogue_evidence"]["config_yaml"],
            "model.yaml",
        )

    def test_missing_exact_config_evidence_is_degraded(self) -> None:
        result = self._candidate([fixtures._generator_manifest_entry(config_sha256="")])

        finding = next(
            item for item in result.diagnostics if item.code == "config-evidence-missing"
        )
        self.assertEqual(finding.model_ids, ("mdx:model",))
        self.assertTrue(result.degraded)

    def test_reconciliation_uses_the_supplied_unified_views_without_reloading(self) -> None:
        from core.model_manifest import load_model_manifest_document

        unified = load_model_manifest_document(fixtures._generator_manifest_document())
        entry = fixtures._generator_manifest_entry()

        with (
            mock.patch(
                "core.mdx_runtime_contract.load_bundled_mdx_runtime_contracts",
                side_effect=AssertionError("runtime registry reloaded"),
            ),
            mock.patch.object(
                catalogue_evidence,
                "reviewed_catalogue_stem_signature",
                side_effect=AssertionError("stem registry reloaded"),
            ),
            mock.patch.object(
                catalogue_evidence,
                "catalogue_stem_evidence_uses_config",
                side_effect=AssertionError("model registry reloaded"),
            ),
        ):
            catalogue_evidence.reconcile_stem_semantics(
                [entry],
                registry=unified.stems,
                contracts=unified.runtime,
                reviewed_non_config_ids=frozenset(),
            )

        self.assertIsNotNone(entry.stem_semantics)

    def test_config_backed_current_id_without_pinned_evidence_detects_wrong_signature(self) -> None:
        from core.model_manifest import load_model_manifest

        unified = load_model_manifest()
        model_id = "mdx:BandSplit_Roformer_4stems_FT_by_SYH99999"
        record = unified.models[model_id]
        self.assertTrue(record.catalogue_evidence.config_yaml)
        self.assertFalse(record.config_evidence)
        entry = catalogue_types.ModelEntry(
            source=record.catalogue_evidence.source,
            family="Roformer",
            catalogue_label=record.catalogue_evidence.catalogue_label,
            weight_file=record.catalogue_evidence.primary_artifact,
            config_yaml=record.catalogue_evidence.config_yaml,
            config_url="https://example.test/current-no-pin.yaml",
            config_sha256="b" * 64,
            instruments=["WRONG_A", "WRONG_B"],
            metadata_source="remote_yaml:current-no-pin.yaml",
        )

        reviewed_non_config_ids = {
            model_id
            for model_id, record in unified.models.items()
            if not record.catalogue_evidence.config_yaml
        }

        catalogue_evidence.reconcile_stem_semantics(
            [entry],
            registry=unified.stems,
            contracts=unified.runtime,
            reviewed_non_config_ids=reviewed_non_config_ids,
        )
        semantics = entry.stem_semantics
        if semantics is None:
            self.fail("reconciliation did not attach exact stem semantics")
        self.assertEqual(semantics.model_id, model_id)
        self.assertEqual(semantics.native_signature, ("WRONG_A", "WRONG_B"))
        self.assertFalse(semantics.reviewed)
        self.assertIn("signature-mismatch", semantics.contexts[0].warning)

    def test_offline_cache_miss_uses_exact_unified_config_evidence(self) -> None:
        import shutil
        import tempfile

        from core.model_manifest import load_model_manifest_document

        document = fixtures._generator_manifest_document()
        document["models"]["mdx:model"]["catalogue_evidence"]["metadata_source"] = (
            "remote_yaml:model.yaml"
        )
        unified = load_model_manifest_document(document)
        cache_dir = os.path.join(tempfile.mkdtemp(prefix="uvr-manifest-evidence-"), "yaml")
        self.addCleanup(shutil.rmtree, os.path.dirname(cache_dir), ignore_errors=True)
        context = catalogue_types.CatalogueContext()

        with (
            mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", cache_dir),
            mock.patch(
                "core.mdx_config_fetch._urlopen",
                side_effect=AssertionError("offline config fetch"),
            ),
        ):
            entry = catalogue._parse_catalogue_entry(
                source="fixture-source",
                family="MDX23C",
                label="Fixture Model",
                payload={
                    "model.ckpt": "https://new.test/model.ckpt",
                    "model.yaml": "https://new.test/model.yaml",
                },
                ctx=context,
                policy=catalogue_cache.OFFLINE_FETCH_POLICY,
                registry=unified.stems,
                manifest_records=unified.models,
            )[0]

        self.assertEqual(entry.config_sha256, "a" * 64)
        self.assertEqual(entry.instruments, ["Vocals", "Other"])
        self.assertEqual(entry.target_instrument, "Vocals")
        self.assertEqual(entry.metadata_source, "remote_yaml:model.yaml")
        self.assertEqual(context.unavailable_yaml_evidence, set())
        self.assertFalse(os.path.exists(cache_dir))

    def test_offline_cache_miss_without_exact_unified_evidence_stays_degraded(self) -> None:
        context = catalogue_types.CatalogueContext()

        entry = catalogue._parse_catalogue_entry(
            source="fixture-source",
            family="MDX23C",
            label="Fixture Model",
            payload={
                "model.ckpt": "https://new.test/model.ckpt",
                "unknown.yaml": "https://new.test/unknown.yaml",
            },
            ctx=context,
            policy=catalogue_cache.OFFLINE_FETCH_POLICY,
            manifest_records={},
        )[0]

        self.assertEqual(entry.config_sha256, "")
        self.assertEqual(context.unavailable_yaml_evidence, {"unknown.yaml"})
