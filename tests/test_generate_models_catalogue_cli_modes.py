"""Generator cli modes behavior."""

import os
import unittest
from typing import Any, Mapping

# Load the script path before top-level catalogue imports (one module identity).
# isort: off
from tests import generator_fixtures as fixtures

import generate_models_catalogue as cli
from catalogue import collect as catalogue
from catalogue import confidence as catalogue_confidence
from catalogue import render
from catalogue import types as catalogue_types
from catalogue.audit_types import (
    CatalogueEvidenceCounts,
    NativeToRoleAmbiguity,
    RoleToNativeVariant,
    StemAuditDiagnostic,
    StemAuditResult,
    StemRelationshipEvidence,
    StemSemanticReferenceRow,
)

from core.stem_roles import (
    StemProcessingContext,
)




# isort: on

from tests.diagnostic_fixtures import expected_stderr_line


class ReferenceTsvOptInTests(unittest.TestCase):
    """The TSV is a deliberate output, not a side effect of running the command."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-tsv-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.tsv = os.path.join(self.tmp, "model_intent_reference.tsv")
        self.out = os.path.join(self.tmp, "models-catalogue.md")
        self.display = os.path.join(self.tmp, "model_display_reference.tsv")
        self.stem = os.path.join(self.tmp, "model_stem_semantics_reference.tsv")

    def _community(self):
        return {
            "model.ckpt": catalogue_types.CommunityRef(
                filename="model.ckpt",
                arch="Roformer",
                primary_stem="Vocals",
                stems_text="vocals, other",
                friendly_name="Some Model",
                intent="vocals",
            )
        }

    def _run(self, argv: list, *, entries: int = 1) -> int:
        import contextlib
        from unittest import mock

        class _Snapshot:
            vr = {f"Model {i}": f"m{i}.pth" for i in range(entries)}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        ctx = catalogue_types.CatalogueContext(community_by_file=self._community())
        with contextlib.ExitStack() as stack:
            stack.enter_context(fixtures._legacy_publication_manifest_fixture())
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", self.tsv))
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", self.out))
            stack.enter_context(mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", self.display))
            stack.enter_context(
                mock.patch.object(cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", self.stem)
            )
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=fixtures._clean_stem_audit
                )
            )
            stack.enter_context(
                mock.patch.object(catalogue, "_build_catalogue_context", lambda **k: ctx)
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue,
                    "_snapshot_and_payloads",
                    lambda **k: (_Snapshot(), ({}, {}, {}, {})),
                )
            )
            for flag in ("--write-tsv", "--write-display-reference"):
                if flag in argv:
                    stack.enter_context(expected_stderr_line(self, f"Warning: {flag} is deprecated and has no effect; all generated references are always synchronized."))
            return cli.main(argv)

    def test_a_default_run_writes_the_tsv(self) -> None:
        self.assertEqual(self._run([]), 0)
        self.assertTrue(os.path.isfile(self.out))
        self.assertTrue(os.path.isfile(self.tsv))

    def test_write_tsv_writes_it(self) -> None:
        self.assertEqual(self._run(["--write-tsv"]), 0)
        self.assertTrue(os.path.isfile(self.tsv))
        with open(self.tsv, encoding="utf-8") as handle:
            self.assertIn("model.ckpt", handle.read())

    def test_a_refused_run_does_not_write_the_tsv(self) -> None:
        """A run that refuses to publish must not mutate the other artifact either."""
        with open(self.out, "w", encoding="utf-8") as handle:
            handle.write("## Summary\n\n- Total catalogue entries: **400**\n")
        self.assertEqual(self._run(["--write-tsv"], entries=1), 2)
        self.assertFalse(os.path.exists(self.tsv), "refused run still wrote the TSV")

    def test_write_tsv_flag_is_exposed_on_the_cli(self) -> None:
        self.assertTrue(cli._parse_args(["--write-tsv"]).write_tsv)
        self.assertFalse(cli._parse_args([]).write_tsv)


class DisplayReferenceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-display-reference-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "models-catalogue.md")
        self.reference = os.path.join(self.tmp, "model_display_reference.tsv")
        self.intent = os.path.join(self.tmp, "model_intent_reference.tsv")
        self.stem = os.path.join(self.tmp, "model_stem_semantics_reference.tsv")

    def _run(
        self,
        argv: list[str],
        *,
        vr: Mapping[str, object] | None = None,
        mdx: Mapping[str, object] | None = None,
    ) -> int:
        import contextlib
        from unittest import mock

        class _Snapshot:
            def __init__(self) -> None:
                self.vr: dict[str, object] = dict(
                    {"VR Arch Single Model v5: 1_HP-UVR": "1_HP-UVR.pth"} if vr is None else vr
                )
                self.mdx: dict[str, object] = dict({} if mdx is None else mdx)
                self.demucs: dict[str, object] = {}
                self.apollo: dict[str, object] = {}
                self.meta: dict[str, object] = {}
                self.unsupported: dict[str, object] = {}
                self.report = None

        snapshot = _Snapshot()

        with contextlib.ExitStack() as stack:
            stack.enter_context(fixtures._legacy_publication_manifest_fixture())
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", self.out))
            stack.enter_context(
                mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", self.reference)
            )
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", self.intent))
            stack.enter_context(
                mock.patch.object(cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", self.stem)
            )
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=fixtures._clean_stem_audit
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue,
                    "_build_catalogue_context",
                    lambda **_kwargs: catalogue_types.CatalogueContext(),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue,
                    "_snapshot_and_payloads",
                    lambda **_kwargs: (snapshot, ({}, {}, {}, {})),
                )
            )
            for flag in ("--write-tsv", "--write-display-reference"):
                if flag in argv:
                    stack.enter_context(expected_stderr_line(self, f"Warning: {flag} is deprecated and has no effect; all generated references are always synchronized."))
            return cli.main(argv)

    def test_flag_writes_the_complete_reference(self) -> None:
        self.assertEqual(self._run(["--write-display-reference"]), 0)
        with open(self.reference, encoding="utf-8") as handle:
            rendered = handle.read()
        self.assertIn("catalogue_generation", rendered)
        self.assertIn("1_HP-UVR.pth", rendered)

    def test_check_detects_reference_drift_without_writing(self) -> None:
        self.assertEqual(self._run(["--write-display-reference"]), 0)
        with open(self.reference, "a", encoding="utf-8") as handle:
            handle.write("drift\n")
        with open(self.reference, "rb") as handle:
            before = handle.read()

        self.assertEqual(self._run(["--check", "--write-display-reference"]), 1)
        with open(self.reference, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_check_rejects_matching_reference_with_unreviewed_flags(self) -> None:
        import contextlib
        import io

        mdx = {"MDX-Net Model: private_model": "private_model.onnx"}
        self.assertEqual(
            self._run(["--write-display-reference"], vr={}, mdx=mdx),
            0,
        )
        with open(self.reference, "rb") as handle:
            before = handle.read()
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            result = self._run(["--check", "--write-display-reference"], vr={}, mdx=mdx)

        self.assertEqual(result, 1)
        self.assertIn("unreviewed presentation flag", stderr.getvalue().lower())
        with open(self.reference, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_check_rejects_matching_case_insensitive_display_collision(self) -> None:
        import contextlib
        import io

        mdx = {
            "MDX-Net Model: Shared": "first.onnx",
            "MDX-Net: shared": "second.onnx",
        }
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            result = self._run(["--write-display-reference"], vr={}, mdx=mdx)

        self.assertEqual(result, 1)
        self.assertIn("case-insensitive display collision", stderr.getvalue().lower())
        self.assertFalse(os.path.exists(self.reference))

    def test_default_run_writes_the_reference(self) -> None:
        self.assertEqual(self._run([]), 0)
        self.assertTrue(os.path.exists(self.reference))

    def test_summary_with_flag_remains_read_only(self) -> None:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self._run(["--summary", "--write-display-reference"]), 1)
        self.assertFalse(os.path.exists(self.reference))

    def test_refused_run_does_not_write_the_reference(self) -> None:
        with open(self.out, "w", encoding="utf-8") as handle:
            handle.write("## Summary\n\n- Total catalogue entries: **400**\n")

        self.assertEqual(self._run(["--write-display-reference"]), 2)
        self.assertFalse(os.path.exists(self.reference))

    def test_flag_is_opt_in(self) -> None:
        self.assertTrue(cli._parse_args(["--write-display-reference"]).write_display_reference)
        self.assertFalse(cli._parse_args([]).write_display_reference)

    def test_stem_semantics_reference_flag_is_opt_in(self) -> None:
        self.assertTrue(
            cli._parse_args(["--write-stem-semantics-reference"]).write_stem_semantics_reference
        )
        self.assertFalse(cli._parse_args([]).write_stem_semantics_reference)


class CheckModeTests(unittest.TestCase):
    """--check reports drift without touching the tree."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-check-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "models-catalogue.md")
        self.tsv = os.path.join(self.tmp, "model_intent_reference.tsv")
        self.display = os.path.join(self.tmp, "model_display_reference.tsv")
        self.stem = os.path.join(self.tmp, "model_stem_semantics_reference.tsv")

    def _run(self, argv: list) -> int:
        import contextlib
        from unittest import mock

        class _Snapshot:
            vr = {f"Model {i}": f"m{i}.pth" for i in range(3)}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        ctx = catalogue_types.CatalogueContext(
            community_by_file={
                "model.ckpt": catalogue_types.CommunityRef(
                    filename="model.ckpt",
                    arch="Roformer",
                    primary_stem="Vocals",
                    stems_text="vocals, other",
                    friendly_name="Some Model",
                    intent="vocals",
                )
            }
        )
        with contextlib.ExitStack() as stack:
            stack.enter_context(fixtures._legacy_publication_manifest_fixture())
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", self.out))
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", self.tsv))
            stack.enter_context(mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", self.display))
            stack.enter_context(
                mock.patch.object(cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", self.stem)
            )
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=fixtures._clean_stem_audit
                )
            )
            stack.enter_context(
                mock.patch.object(catalogue, "_build_catalogue_context", lambda **k: ctx)
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue,
                    "_snapshot_and_payloads",
                    lambda **k: (_Snapshot(), ({}, {}, {}, {})),
                )
            )
            for flag in ("--write-tsv", "--write-display-reference"):
                if flag in argv:
                    stack.enter_context(expected_stderr_line(self, f"Warning: {flag} is deprecated and has no effect; all generated references are always synchronized."))
            return cli.main(argv)

    def test_check_on_an_up_to_date_document_exits_zero(self) -> None:
        self.assertEqual(self._run([]), 0)
        with open(self.out, "rb") as handle:
            before = handle.read()
        mtime = os.path.getmtime(self.out)
        self.assertEqual(self._run(["--check"]), 0)
        with open(self.out, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual(os.path.getmtime(self.out), mtime, "--check rewrote the file")

    def test_check_reports_drift_without_writing(self) -> None:
        self.assertEqual(self._run([]), 0)
        with open(self.out, "a", encoding="utf-8") as handle:
            handle.write("\ndrifted\n")
        with open(self.out, "rb") as handle:
            drifted = handle.read()
        self.assertEqual(self._run(["--check"]), 1)
        with open(self.out, "rb") as handle:
            self.assertEqual(handle.read(), drifted, "--check wrote anyway")

    def test_check_on_a_missing_document_is_drift(self) -> None:
        self.assertEqual(self._run(["--check"]), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_check_also_covers_the_tsv_when_requested(self) -> None:
        self.assertEqual(self._run(["--write-tsv"]), 0)
        self.assertEqual(self._run(["--check", "--write-tsv"]), 0)
        os.unlink(self.tsv)
        self.assertEqual(self._run(["--check", "--write-tsv"]), 1)
        self.assertFalse(os.path.exists(self.tsv))

    def test_check_and_write_are_mutually_exclusive(self) -> None:
        import io
        from contextlib import redirect_stderr
        output = io.StringIO()
        with redirect_stderr(output), self.assertRaises(SystemExit):
            cli._parse_args(["--check", "--write"])
        self.assertIn("usage:", output.getvalue())
        self.assertIn('not allowed with argument', output.getvalue())

    def test_write_is_the_default(self) -> None:
        self.assertFalse(cli._parse_args([]).check)


class SummaryModeTests(unittest.TestCase):
    """--summary answers the maintainer's likely question without 7,000 lines."""

    def _entries(self):
        flagged = catalogue_types.ModelEntry(
            source="TRvlvr",
            family="Roformer",
            catalogue_label="Bad Model",
            weight_file="bad.ckpt",
            name_intent="vocals",
            metadata_source="bundled_yaml:x.yaml",
        )
        flagged.flags = ["NAME says vocal but backend is instrumental-focused"]
        unknown = catalogue_types.ModelEntry(
            source="extras",
            family="MDX23C",
            catalogue_label="Mystery",
            weight_file="m.ckpt",
            name_intent="unknown",
        )
        fine = catalogue_types.ModelEntry(
            source="TRvlvr",
            family="VR Architecture",
            catalogue_label="Good Model",
            weight_file="g.pth",
            name_intent="vocals",
            metadata_source="bundled_yaml:y.yaml",
        )
        return [flagged, unknown, fine]

    def test_reports_counts(self) -> None:
        text = render.render_summary_report(self._entries(), unsupported_count=4)
        self.assertIn("**3**", text)
        self.assertIn("4", text)

    def test_lists_flagged_entries(self) -> None:
        text = render.render_summary_report(self._entries(), unsupported_count=0)
        self.assertIn("Bad Model", text)
        self.assertIn("backend is instrumental-focused", text)

    def test_lists_unknown_intent_entries(self) -> None:
        text = render.render_summary_report(self._entries(), unsupported_count=0)
        self.assertIn("Mystery", text)

    def test_omits_the_clean_entries(self) -> None:
        """The point is the exception list, not the full inventory."""
        text = render.render_summary_report(self._entries(), unsupported_count=0)
        self.assertNotIn("Good Model", text)

    def test_is_much_shorter_than_the_full_render(self) -> None:
        entries = self._entries()
        full = render._render(entries, unsupported_count=0)
        summary = render.render_summary_report(entries, unsupported_count=0)
        self.assertLess(len(summary), len(full))

    def test_semantic_summary_uses_structured_audit_counts_and_sections(self) -> None:
        ambiguity_evidence = (
            StemRelationshipEvidence(
                model_id="mdx:broken",
                context=StemProcessingContext.FULL_MIX,
                native="Vocals",
                role_id="vocal.vocals",
            ),
            StemRelationshipEvidence(
                model_id="mdx:alternate",
                context=StemProcessingContext.VOCAL_SPLIT,
                native="vocals",
                role_id="vocal.backing",
            ),
        )
        variant_evidence = (
            ambiguity_evidence[0],
            StemRelationshipEvidence(
                model_id="mdx:lead",
                context=StemProcessingContext.FULL_MIX,
                native="Lead Vocal",
                role_id="vocal.vocals",
            ),
        )
        audit = StemAuditResult(
            catalogue_model_ids=("mdx:broken", "mdx:waived", "mdx:raw"),
            reviewed_model_ids=("mdx:broken",),
            waived_model_ids=("mdx:waived",),
            raw_model_ids=("mdx:raw",),
            evidence_counts=CatalogueEvidenceCounts(0, 0, 0, ()),
            diagnostics=(
                StemAuditDiagnostic(
                    code="native-signature",
                    model_ids=("mdx:broken",),
                    message="reviewed declaration does not match runtime-native source keys",
                    expected=("Vocals",),
                    actual=("Instrumental",),
                ),
                StemAuditDiagnostic(
                    code="context-duplicate-role",
                    model_ids=("mdx:broken",),
                    context=StemProcessingContext.FULL_MIX,
                    message="processing context maps more than one output to the same role",
                    actual=("vocal.vocals", "vocal.vocals"),
                ),
                StemAuditDiagnostic(
                    code="context-native-signature",
                    model_ids=("mdx:broken",),
                    context=StemProcessingContext.FULL_MIX,
                    message="context native outputs do not match the declaration signature",
                    expected=("Vocals",),
                    actual=("Instrumental",),
                ),
                StemAuditDiagnostic(
                    code="pair-incomplete",
                    model_ids=("mdx:broken",),
                    message="pair is incomplete",
                ),
                StemAuditDiagnostic(
                    code="role-display-collision",
                    model_ids=("mdx:broken",),
                    message="roles share a display",
                ),
                StemAuditDiagnostic(
                    code="reference-drift",
                    model_ids=("mdx:broken",),
                    message="checked-in reference differs",
                    expected=("expected-digest",),
                    actual=("actual-digest",),
                    structural=False,
                ),
            ),
            native_to_role_ambiguities=(
                NativeToRoleAmbiguity(
                    normalized_native="vocals",
                    native_spellings=("Vocals", "vocals"),
                    role_ids=("vocal.backing", "vocal.vocals"),
                    model_ids=("mdx:alternate", "mdx:broken"),
                    evidence=ambiguity_evidence,
                ),
            ),
            role_to_native_variants=(
                RoleToNativeVariant(
                    role_id="vocal.vocals",
                    normalized_natives=("lead vocal", "vocals"),
                    native_spellings=("Lead Vocal", "Vocals"),
                    model_ids=("mdx:broken", "mdx:lead"),
                    evidence=variant_evidence,
                ),
            ),
        )

        text = render.render_summary_report(self._entries(), unsupported_count=0, stem_audit=audit)

        self.assertIn("Reviewed catalogue models: **1**", text)
        self.assertIn("Waived catalogue models: **1**", text)
        self.assertIn("Raw catalogue models: **1**", text)
        self.assertIn("Structural stem findings: **5**", text)
        self.assertIn("Accidental semantic collisions: **1**", text)
        self.assertIn("Native-to-role ambiguity groups: **1**", text)
        self.assertIn("Role-to-native variant groups: **1**", text)
        for heading in (
            "## Signature and context findings",
            "## Native-to-role ambiguities",
            "## Role-to-native variants",
            "## Invalid pairs",
            "## Collisions",
            "## Reference drift",
        ):
            self.assertIn(heading, text)
        self.assertIn("`native-signature`", text)
        self.assertIn("`mdx:broken`", text)
        self.assertIn("full_mix", text)
        self.assertIn("expected: `Vocals`", text)
        self.assertIn("actual: `Instrumental`", text)
        self.assertIn("normalized native `vocals`", text)
        self.assertIn("role `vocal.vocals`", text)
        self.assertIn("`mdx:alternate` (vocal_split)", text)
        self.assertIn("`Lead Vocal`", text)
        self.assertNotIn("Nothing flagged", text)
        self.assertNotIn("No stem semantic audit findings.", text)

    def test_semantic_summary_counts_distinct_reviewed_contexts_and_karaoke_models(self) -> None:
        def row(
            model_id: str,
            context: StemProcessingContext,
            *,
            intent: str,
            role_id: str,
            review_status: str = "reviewed",
        ) -> StemSemanticReferenceRow:
            family, _separator, basename = model_id.partition(":")
            return StemSemanticReferenceRow(
                runtime_family=family,
                runtime_basename=basename,
                catalogue_source="fixture",
                catalogue_label=model_id,
                execution_arch="MDX",
                model_id=model_id,
                model_display=model_id,
                native_signature=("Vocals", "Instrumental"),
                processing_context=context,
                native_stem="Vocals",
                production="native",
                backend_primary="Vocals",
                backend_target="",
                logical_primary=True,
                logical_secondary=False,
                role_id=role_id,
                canonical_name="Vocals",
                filename_tag="Vocals",
                pair_id="",
                intent=intent,
                intent_source="reviewed_manifest",
                review_status=review_status,
                evidence_or_waiver="fixture",
                selected_by_default=True,
            )

        rows = (
            row(
                "mdx:karaoke",
                StemProcessingContext.FULL_MIX,
                intent="karaoke",
                role_id="mix.instrumental_with_backing_vocals",
            ),
            row(
                "mdx:karaoke",
                StemProcessingContext.FULL_MIX,
                intent="karaoke",
                role_id="vocal.lead",
            ),
            row(
                "mdx:karaoke",
                StemProcessingContext.VOCAL_SPLIT,
                intent="karaoke",
                role_id="vocal.backing",
            ),
            row(
                "mdx:other",
                StemProcessingContext.FULL_MIX,
                intent="vocals",
                role_id="vocal.vocals",
            ),
            row(
                "apollo:waived",
                StemProcessingContext.FULL_MIX,
                intent="unknown",
                role_id="",
                review_status="waived",
            ),
        )
        audit = StemAuditResult(
            catalogue_model_ids=("mdx:karaoke", "mdx:other", "apollo:waived"),
            reviewed_model_ids=("mdx:karaoke", "mdx:other"),
            waived_model_ids=("apollo:waived",),
            raw_model_ids=(),
            evidence_counts=CatalogueEvidenceCounts(0, 0, 0, ()),
            diagnostics=(),
            reference_rows=rows,
        )

        text = render.render_summary_report(self._entries(), unsupported_count=0, stem_audit=audit)

        self.assertIn("Reviewed contexts: **3**", text)
        self.assertIn("Reviewed karaoke declarations: **1**", text)

    def test_summary_does_not_overwrite_the_document(self) -> None:
        """A summary is an ad-hoc query, not a replacement for the catalogue."""
        import contextlib
        import io
        import tempfile
        from unittest import mock

        class _Snapshot:
            vr = {"M": "m.pth"}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "models-catalogue.md")
            with open(out, "w", encoding="utf-8") as handle:
                handle.write("THE REAL CATALOGUE\n- Total catalogue entries: **400**\n")
            stdout = io.StringIO()
            with (
                mock.patch.object(cli, "OUTPUT_PATH", out),
                mock.patch.object(
                    catalogue, "_build_catalogue_context", lambda **k: catalogue_types.CatalogueContext()
                ),
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads", lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                ),
                contextlib.redirect_stdout(stdout),
            ):
                rc = cli.main(["--summary"])

            self.assertEqual(rc, 2)
            with open(out, encoding="utf-8") as handle:
                self.assertIn("THE REAL CATALOGUE", handle.read())
            self.assertFalse(os.path.exists(catalogue._ir_path_for(out)))
        self.assertIn("Counts", stdout.getvalue())

    def test_summary_flag_exists(self) -> None:
        self.assertTrue(cli._parse_args(["--summary"]).summary)
        self.assertFalse(cli._parse_args([]).summary)


class CollectEntriesIsTheRealPathTests(unittest.TestCase):
    """A second entry path exercised only by tests is how main and tests drift."""

    def test_main_collects_through_collect_entries(self) -> None:
        from unittest import mock

        class _Snapshot:
            vr = {"M": "m.pth"}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(cli, "OUTPUT_PATH", os.path.join(tmp, "c.md")),
                mock.patch.object(cli, "REFERENCE_TSV_PATH", os.path.join(tmp, "intent.tsv")),
                mock.patch.object(
                    cli, "DISPLAY_REFERENCE_TSV_PATH", os.path.join(tmp, "display.tsv")
                ),
                mock.patch.object(
                    cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", os.path.join(tmp, "stem.tsv")
                ),
                mock.patch.object(
                    cli.stem_audit,
                    "audit_catalogue_stems",
                    side_effect=fixtures._clean_stem_audit,
                ),
                mock.patch.object(
                    catalogue, "_build_catalogue_context", lambda **k: catalogue_types.CatalogueContext()
                ),
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads", lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                ),
                mock.patch.object(
                    catalogue, "collect_entries", wraps=catalogue.collect_entries
                ) as collect,
            ):
                cli.main([])
        self.assertEqual(collect.call_count, 1, "main did not go through collect_entries")


class SummaryHonestyTests(unittest.TestCase):
    """A summary of a failed fetch must not read as a clean bill of health."""

    def _dead_report(self):
        from core.catalogue_types import RefreshMode, RefreshReport

        return RefreshReport(mode=RefreshMode.OFFLINE, usable=False)

    def test_an_unusable_snapshot_is_called_out(self) -> None:
        text = render.render_summary_report([], unsupported_count=0, report=self._dead_report())
        self.assertNotIn("Nothing flagged", text)
        self.assertIn("unusable", text.lower())

    def test_an_empty_catalogue_is_called_out_even_without_a_report(self) -> None:
        text = render.render_summary_report([], unsupported_count=0, report=None)
        self.assertNotIn("Nothing flagged", text)
        self.assertIn("no entries", text.lower())

    def test_a_healthy_empty_of_problems_run_still_reads_clean(self) -> None:
        entry = catalogue_types.ModelEntry(
            source="TRvlvr",
            family="VR Architecture",
            catalogue_label="Good",
            weight_file="g.pth",
            name_intent="vocals",
            metadata_source="bundled_yaml:y.yaml",
        )
        text = render.render_summary_report([entry], unsupported_count=0)
        self.assertIn("Nothing flagged", text)


class StemConfidenceAuditModeTests(unittest.TestCase):
    """The remote confidence review is isolated from catalogue publication."""

    def test_audit_mode_exposes_the_legacy_review_filters(self) -> None:
        args = cli._parse_args(
            [
                "--audit-stem-confidence",
                "--guessed-only",
                "--only",
                "karaoke",
                "--limit",
                "3",
                "--json",
                "/tmp/confidence.json",
                "--quiet",
                "--no-cache",
            ]
        )

        self.assertTrue(args.audit_stem_confidence)
        self.assertTrue(args.guessed_only)
        self.assertEqual(args.only, "karaoke")
        self.assertEqual(args.limit, 3)
        self.assertEqual(args.json_path, "/tmp/confidence.json")
        self.assertTrue(args.quiet)
        self.assertTrue(args.no_hash_cache)

    def test_audit_only_filters_are_rejected_outside_audit_mode(self) -> None:
        import io
        from contextlib import redirect_stderr
        output = io.StringIO()
        with redirect_stderr(output), self.assertRaises(SystemExit):
            cli._parse_args(["--guessed-only"])
        self.assertIn("usage:", output.getvalue())
        self.assertIn('require --audit-stem-confidence', output.getvalue())

    def test_offline_rejects_hash_cache_bypass(self) -> None:
        import io
        from contextlib import redirect_stderr
        output = io.StringIO()
        with redirect_stderr(output), self.assertRaises(SystemExit):
            cli._parse_args(["--audit-stem-confidence", "--offline", "--no-cache"])
        self.assertIn("usage:", output.getvalue())
        self.assertIn('--offline', output.getvalue())

    def test_audit_mode_does_not_collect_or_publish_catalogue_artifacts(self) -> None:
        import contextlib
        import io
        from unittest import mock

        with (
            mock.patch.object(
                catalogue_confidence,
                "run_stem_confidence_audit",
                return_value=0,
            ) as audit,
            mock.patch.object(
                catalogue,
                "_build_catalogue_context",
                side_effect=AssertionError("publication collection must not run"),
            ),
            mock.patch.object(
                cli,
                "load_stem_manifest",
                side_effect=AssertionError("confidence audit must not load publication manifest"),
                create=True,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli.main(["--audit-stem-confidence", "--quiet"]), 0)

        self.assertTrue(audit.called)

    def test_offline_refresh_reuses_warm_source_config_and_hash_caches(self) -> None:
        import contextlib
        import io
        import tempfile
        from types import SimpleNamespace
        from unittest import mock

        target = SimpleNamespace(
            entry_id="warm",
            label="Warm model",
            config_url="https://example.test/warm.yaml",
            checkpoint_url="https://example.test/warm.ckpt",
            is_bv_model=False,
        )
        source = SimpleNamespace(
            state=SimpleNamespace(content=SimpleNamespace(payload={"warm": {}}))
        )
        source_calls: list[Any] = []
        source.load = lambda **kwargs: source_calls.append(kwargs["mode"])
        coordinator = SimpleNamespace(source=lambda _source_id: source, close=lambda: None)
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "hashes.json")
            cache = catalogue_confidence.HashCache(cache_path)
            cache.put(
                target.checkpoint_url,
                catalogue_confidence.HashLookup(digest="known", status="ok"),
            )
            cache.save()
            with (
                mock.patch(
                    "core.catalogue_coordinator.CatalogueCoordinator",
                    return_value=coordinator,
                ),
                mock.patch(
                    "scripts.model_tool_support.iter_catalogue_targets",
                    return_value=iter([target]),
                ),
                mock.patch.object(
                    catalogue_confidence, "default_hash_cache_path", return_value=cache_path
                ),
                mock.patch.object(
                    catalogue_confidence, "_curated_hash_table", return_value={"known": {}}
                ),
                mock.patch("catalogue.confidence.os.path.isfile", return_value=True),
                mock.patch(
                    "core.model_data.load_mdx_c_config",
                    return_value={"training": {"instruments": ["vocals", "other"]}},
                ) as config_load,
                mock.patch(
                    "catalogue.cache.fetch_yaml_bytes",
                    side_effect=AssertionError("offline config fetch"),
                ),
                mock.patch(
                    "scripts.model_tool_support.checkpoint_tail_hash",
                    side_effect=AssertionError("offline checkpoint fetch"),
                ),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(
                    cli.main(["--audit-stem-confidence", "--offline", "--refresh", "--quiet"]),
                    0,
                )

        config_load.assert_called_once()
        self.assertEqual([mode.value for mode in source_calls], ["offline"])
