"""Literal evidence and ordered context-assessment contracts."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from typing import cast

from core.model_stem_manifest import _ModelStemContext, _ModelStemDeclaration

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))


class EvidenceBoundaryTests(unittest.TestCase):
    def test_exact_yaml_evidence_keeps_native_order_and_provenance(self) -> None:
        from catalogue.config_evidence import parse_yaml_evidence

        value = parse_yaml_evidence(
            b'training:\n  instruments: [other, vocals]\n  target_instrument: vocals\nmodel:\n  num_bands: 32\n',
            yaml_name="model.yaml",
            metadata_source="remote_yaml:model.yaml",
        )
        self.assertEqual(value.instruments, ["other", "vocals"])
        self.assertEqual(value.target_instrument, "vocals")
        self.assertEqual(value.architecture, "Mel-Band Roformer")
        self.assertEqual(value.metadata_source, "remote_yaml:model.yaml")
        self.assertEqual(
            value.content_sha256, "03827bb3d948d66e647d97ec1d8534890526031ea0cc52503f3c7b52d48a09de"
        )

    def test_missing_resolution_retains_declared_projection_and_ordered_findings(self) -> None:
        from catalogue.audit_rules import assess_context

        from core.stem_roles import StemProcessingContext

        context = SimpleNamespace(outputs=(), logical_primary="vocal.lead", logical_secondary=None)
        declaration = SimpleNamespace(intent="karaoke", native_signature=("vocals",))
        result = assess_context(
            "mdx:fixture",
            cast(_ModelStemDeclaration, declaration),
            StemProcessingContext.FULL_MIX,
            cast(_ModelStemContext, context),
            None,
        )
        self.assertEqual(
            [item.code for item in result.diagnostics],
            [
                "context-logical-primary",
                "context-logical-secondary-required",
                "context-native-signature",
                "context-resolution-error",
            ],
        )
        self.assertEqual(
            [(item.expected, item.actual) for item in result.diagnostics],
            [
                (("vocal.lead",), ()),
                (("vocal.lead",), ()),
                (("vocals",), ()),
                ((), ()),
            ],
        )
        self.assertEqual(result.projection.model_id, "mdx:fixture")
        self.assertEqual(result.projection.declared_roles, frozenset())
        self.assertIsNone(result.projection.semantics)
        self.assertFalse(result.full_mix_reviewed)

    def test_invalid_context_contributes_no_projection(self) -> None:
        from catalogue.audit_rules import assess_model_contexts

        declaration = SimpleNamespace(contexts={"invalid": object()})
        result = assess_model_contexts("mdx:fixture", cast(_ModelStemDeclaration, declaration), {})
        self.assertEqual(
            [item.code for item in result.diagnostics], ["missing-full-mix", "context-invalid"]
        )
        self.assertEqual(result.projections, ())
        self.assertFalse(result.fully_reviewed)

    def test_reviewed_status_is_independent_of_other_context_findings(self) -> None:
        from catalogue.audit_rules import assess_model_contexts

        from core.model_stem_manifest import _ModelStemContext, _ModelStemDeclaration
        from core.stem_roles import (
            ModelStemSemantics,
            StemProcessingContext,
            StemReviewStatus,
            StemRoleId,
        )

        context = StemProcessingContext.FULL_MIX
        declaration = _ModelStemDeclaration(
            (),
            "unknown",
            {
                context: _ModelStemContext(StemRoleId("vocal.lead"), ()),
            },
            "fixture",
        )
        resolved = ModelStemSemantics(
            "mdx:fixture", context, "unknown", (), StemReviewStatus.REVIEWED, "fixture"
        )
        result = assess_model_contexts("mdx:fixture", declaration, {context: resolved})
        self.assertEqual([item.code for item in result.diagnostics], ["context-logical-primary"])
        self.assertTrue(result.fully_reviewed)
        self.assertEqual(len(result.projections), 1)
        self.assertIs(result.projections[0].semantics, resolved)

    def test_public_facades_keep_type_and_function_identity(self) -> None:
        from catalogue import (
            audit_types,
            cache,
            collect,
            confidence,
            evidence,
            manifest_candidate,
            stem_audit,
            types,
        )

        for old, new in (
            (collect.ModelEntry, types.ModelEntry),
            (collect.FetchPolicy, cache.FetchPolicy),
            (collect.reconcile_stem_semantics, evidence.reconcile_stem_semantics),
            (stem_audit.StemAuditResult, audit_types.StemAuditResult),
            (stem_audit.build_manifest_candidate, manifest_candidate.build_manifest_candidate),
            (stem_audit.run_stem_confidence_audit, confidence.run_stem_confidence_audit),
        ):
            self.assertIs(old, new)
        instruments = ["other", "vocals"]
        entry = types.ModelEntry(
            "fixture", "MDX-Net", "fixture", "fixture.ckpt", instruments=instruments
        )
        self.assertIs(entry.instruments, instruments)
