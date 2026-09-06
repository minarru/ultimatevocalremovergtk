"""Generator guards behavior."""

import json
import os
import unittest
from typing import Optional

# Load the script path before top-level catalogue imports (one module identity).
# isort: off
from tests import generator_fixtures as fixtures

import generate_models_catalogue as cli
from catalogue import collect as catalogue
from catalogue import types as catalogue_types





# isort: on

class PublicationGuardTests(unittest.TestCase):
    """A degraded snapshot must not replace a good catalogue document."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-guard-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "models-catalogue.md")

    def _report(self, *, usable: bool = True, failed: tuple = ()):
        from core.catalogue_types import RefreshMode, RefreshReport

        return RefreshReport(mode=RefreshMode.OFFLINE, usable=usable, failed=failed)

    def test_previous_entry_count_is_read_from_an_existing_document(self) -> None:
        with open(self.out, "w", encoding="utf-8") as handle:
            handle.write("## Summary\n\n- Total catalogue entries: **412**\n")
        self.assertEqual(cli._previous_entry_count(self.out), 412)

    def test_missing_document_has_no_previous_count(self) -> None:
        self.assertIsNone(cli._previous_entry_count(self.out))

    def test_unusable_snapshot_is_refused(self) -> None:
        verdict = cli._publication_verdict(
            entries=[], report=self._report(usable=False), previous_count=None
        )
        self.assertFalse(verdict.ok)
        self.assertIn("unusable", verdict.reason.lower())

    def test_a_large_drop_is_refused_even_when_no_source_reported_failure(self) -> None:
        """The real cold-cache case: offline sources are not refreshed, not failed.

        A run against an empty supplemental cache produced 88 entries where the
        published document had 474, with report.usable True and report.failed
        empty -- so failure state cannot be the trigger. The count is.
        """
        verdict = cli._publication_verdict(
            entries=[object()] * 88, report=self._report(), previous_count=474
        )
        self.assertFalse(verdict.ok)
        self.assertIn("474", verdict.reason)

    def test_a_small_drop_still_publishes(self) -> None:
        """Ordinary regeneration jitter must not need an override flag."""
        verdict = cli._publication_verdict(
            entries=[object()] * 398, report=self._report(), previous_count=400
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_failed_sources_are_named_in_the_refusal(self) -> None:
        from core.catalogue_types import SourceId

        verdict = cli._publication_verdict(
            entries=[object()] * 10,
            report=self._report(failed=((SourceId.UPSTREAM, "boom"),)),
            previous_count=400,
        )
        self.assertFalse(verdict.ok)
        self.assertIn("upstream", verdict.reason)

    def test_a_healthy_snapshot_publishes(self) -> None:
        verdict = cli._publication_verdict(
            entries=[object()] * 400, report=self._report(), previous_count=400
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_allow_degraded_overrides_a_refusal(self) -> None:
        verdict = cli._publication_verdict(
            entries=[],
            report=self._report(usable=False),
            previous_count=400,
            allow_degraded=True,
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_allow_degraded_flag_is_exposed_on_the_cli(self) -> None:
        self.assertTrue(cli._parse_args(["--allow-degraded"]).allow_degraded)
        self.assertFalse(cli._parse_args([]).allow_degraded)


class IntermediateRepresentationTests(unittest.TestCase):
    """A stable machine-readable form that Markdown and TSV render from."""

    def _entry(self, label: str = "Some Model"):
        return catalogue_types.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label=label,
            weight_file="m.ckpt",
            instruments=["vocals", "other"],
            stem_count=2,
            name_intent="vocals",
            metadata_source="catalogue_meta",
        )

    def test_carries_a_schema_version(self) -> None:
        ir = catalogue.build_ir([self._entry()], report=None, unsupported_count=0)
        self.assertEqual(ir["schema_version"], catalogue.IR_SCHEMA_VERSION)

    def test_round_trips_through_json(self) -> None:
        ir = catalogue.build_ir([self._entry()], report=None, unsupported_count=3)
        restored = json.loads(json.dumps(ir))
        self.assertEqual(restored["unsupported_omitted"], 3)
        self.assertEqual(restored["entries"][0]["catalogue_label"], "Some Model")
        self.assertEqual(restored["entries"][0]["instruments"], ["vocals", "other"])

    def test_entry_count_is_recorded_for_the_publication_guard(self) -> None:
        ir = catalogue.build_ir(
            [self._entry("a"), self._entry("b")], report=None, unsupported_count=0
        )
        self.assertEqual(ir["entry_count"], 2)

    def test_provenance_is_included_when_a_report_exists(self) -> None:
        from core.catalogue_types import RefreshMode, RefreshReport, SourceId

        report = RefreshReport(
            mode=RefreshMode.OFFLINE, usable=True, failed=((SourceId.POLITREES, "boom"),)
        )
        ir = catalogue.build_ir([self._entry()], report=report, unsupported_count=0)
        self.assertEqual(ir["provenance"]["mode"], "offline")
        self.assertTrue(ir["provenance"]["failed"])

    def test_no_report_still_produces_valid_ir(self) -> None:
        ir = catalogue.build_ir([self._entry()], report=None, unsupported_count=0)
        self.assertEqual(ir["provenance"], {})

    def test_previous_entry_count_prefers_the_sidecar(self) -> None:
        """More reliable than re-parsing a rendered summary line."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "models-catalogue.md")
            with open(doc, "w", encoding="utf-8") as handle:
                handle.write("- Total catalogue entries: **7**\n")
            sidecar = catalogue._ir_path_for(doc)
            with open(sidecar, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema_version": 1,
                        "entry_count": 412,
                        # Must prove it describes this document; see
                        # SidecarTrustTests for the stale case.
                        "document_sha256": catalogue._document_digest(doc),
                    },
                    handle,
                )
            self.assertEqual(cli._previous_entry_count(doc), 412)

    def test_previous_entry_count_falls_back_to_the_document(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "models-catalogue.md")
            with open(doc, "w", encoding="utf-8") as handle:
                handle.write("- Total catalogue entries: **7**\n")
            self.assertEqual(cli._previous_entry_count(doc), 7)

    def test_a_corrupt_sidecar_falls_back_rather_than_failing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "models-catalogue.md")
            with open(doc, "w", encoding="utf-8") as handle:
                handle.write("- Total catalogue entries: **7**\n")
            with open(catalogue._ir_path_for(doc), "w", encoding="utf-8") as handle:
                handle.write("{not json")
            self.assertEqual(cli._previous_entry_count(doc), 7)


class SidecarTrustTests(unittest.TestCase):
    """The sidecar may only speak for the document it was written with."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-sidecar-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.doc = os.path.join(self.tmp, "models-catalogue.md")

    def _write_doc(self, count: int) -> None:
        with open(self.doc, "w", encoding="utf-8") as handle:
            handle.write(f"- Total catalogue entries: **{count}**\n")

    def _write_sidecar(self, count: int, *, digest: Optional[str] = None) -> None:
        payload: dict = {"schema_version": 1, "entry_count": count}
        if digest is not None:
            payload["document_sha256"] = digest
        with open(catalogue._ir_path_for(self.doc), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_a_sidecar_written_with_this_document_is_trusted(self) -> None:
        self._write_doc(474)
        self._write_sidecar(474, digest=catalogue._document_digest(self.doc))
        self.assertEqual(cli._previous_entry_count(self.doc), 474)

    def test_a_stale_sidecar_cannot_lower_the_guard_floor(self) -> None:
        """The exact hazard: a degraded run's sidecar outliving its document."""
        self._write_doc(474)
        self._write_sidecar(88, digest="sha-of-some-other-document")
        self.assertEqual(cli._previous_entry_count(self.doc), 474)

    def test_a_sidecar_with_no_digest_is_not_trusted(self) -> None:
        """Written before the cross-check existed; the document is authoritative."""
        self._write_doc(474)
        self._write_sidecar(88)
        self.assertEqual(cli._previous_entry_count(self.doc), 474)

    def test_the_sidecar_is_used_when_the_document_has_no_count(self) -> None:
        with open(self.doc, "w", encoding="utf-8") as handle:
            handle.write("a document with no summary line\n")
        self._write_sidecar(412, digest=catalogue._document_digest(self.doc))
        self.assertEqual(cli._previous_entry_count(self.doc), 412)

    def test_a_published_run_writes_a_matching_digest(self) -> None:
        import contextlib
        from unittest import mock

        class _Snapshot:
            vr = {"M": "m.pth"}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        with contextlib.ExitStack() as stack:
            stack.enter_context(fixtures._legacy_publication_manifest_fixture())
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", self.doc))
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "REFERENCE_TSV_PATH",
                    os.path.join(self.tmp, "model_intent_reference.tsv"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "DISPLAY_REFERENCE_TSV_PATH",
                    os.path.join(self.tmp, "model_display_reference.tsv"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "STEM_SEMANTICS_REFERENCE_TSV_PATH",
                    os.path.join(self.tmp, "model_stem_semantics_reference.tsv"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=fixtures._clean_stem_audit
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_build_catalogue_context", lambda **k: catalogue_types.CatalogueContext()
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads", lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                )
            )
            self.assertEqual(cli.main([]), 0)

        with open(catalogue._ir_path_for(self.doc), encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["document_sha256"], catalogue._document_digest(self.doc))
