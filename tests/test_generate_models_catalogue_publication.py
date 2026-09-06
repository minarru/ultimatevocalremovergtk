"""Generator publication behavior."""

import json
import os
import unicodedata
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

# Load the script path before top-level catalogue imports (one module identity).
# isort: off
from tests import generator_fixtures as fixtures

import generate_models_catalogue as cli
from catalogue import audit_reference as catalogue_audit_reference
from catalogue import audit_types as catalogue_audit_types
from catalogue import cache as catalogue_cache
from catalogue import collect as catalogue
from catalogue import locations as catalogue_locations
from catalogue import manifest_candidate as catalogue_manifest_candidate
from catalogue import render
from catalogue import types as catalogue_types
from catalogue.audit_types import (
    CatalogueEvidenceCounts,
    NativeToRoleAmbiguity,
    StemAuditDiagnostic,
    StemAuditResult,
)





# isort: on

class UnifiedPublicationCliTests(unittest.TestCase):
    """The generator publishes and compares one complete snapshot bundle."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-unified-publication-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.output = os.path.join(self.tmp, "models-catalogue.md")
        self.intent = os.path.join(self.tmp, "model_intent_reference.tsv")
        self.display = os.path.join(self.tmp, "model_display_reference.tsv")
        self.stem = os.path.join(self.tmp, "model_stem_semantics_reference.tsv")
        self.manifest = Path(self.tmp) / "model_manifest.json"
        self.ir = catalogue._ir_path_for(self.output)
        with open(self.manifest, "w", encoding="utf-8") as handle:
            json.dump(fixtures._generator_manifest_document(), handle, indent=2, sort_keys=True)
            handle.write("\n")
        self.context = catalogue_types.CatalogueContext(
            community_by_file={
                "model.ckpt": catalogue_types.CommunityRef(
                    filename="model.ckpt",
                    arch="Roformer",
                    primary_stem="Vocals",
                    stems_text="vocals, other",
                    friendly_name="Fixture model",
                    intent="vocals",
                )
            },
        )
        self.entry = catalogue_types.ModelEntry(
            source="fixture",
            family="MDX23C",
            catalogue_label="Fixture Model",
            weight_file="model.ckpt",
            config_yaml="model.yaml",
            config_url="https://new.test/model.yaml",
            config_sha256="a" * 64,
            instruments=["Vocals", "Other"],
            target_instrument="Vocals",
            primary_stem="Vocals",
            stem_count=2,
            name_intent="vocals",
            metadata_source="remote_yaml:model.yaml",
        )
        self.entries = [self.entry]
        self.collect_call_count = 0

    def _audit(self, *args: object, **kwargs: object) -> StemAuditResult:
        return StemAuditResult(
            catalogue_model_ids=("mdx:model",),
            reviewed_model_ids=("mdx:model",),
            waived_model_ids=(),
            raw_model_ids=(),
            evidence_counts=CatalogueEvidenceCounts(148, 123, 92, ()),
            diagnostics=(),
        )

    def _run(
        self,
        argv: list[str],
        *,
        context: catalogue_types.CatalogueContext | None = None,
        audit: object | None = None,
    ) -> int:
        from unittest import mock

        class _Snapshot:
            unsupported: dict[str, object] = {}
            report = None

        from catalogue import stem_audit

        def collect_once(
            *_args: object, **_kwargs: object
        ) -> tuple[object, list[catalogue_types.ModelEntry]]:
            self.collect_call_count += 1
            return _Snapshot(), self.entries

        audit_side_effect = self._audit if audit is None else audit
        if isinstance(audit_side_effect, StemAuditResult):
            audit_result = audit_side_effect

            def return_audit(*_args: object, **_kwargs: object) -> StemAuditResult:
                return audit_result

            audit_side_effect = return_audit

        with (
            mock.patch.object(cli, "OUTPUT_PATH", self.output),
            mock.patch.object(cli, "REFERENCE_TSV_PATH", self.intent),
            mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", self.display),
            mock.patch.object(cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", self.stem),
            mock.patch.object(cli, "BUNDLED_MANIFEST_PATH", self.manifest),
            mock.patch.object(
                catalogue,
                "_build_catalogue_context",
                return_value=context or self.context,
            ),
            mock.patch.object(
                catalogue,
                "collect_entries",
                side_effect=collect_once,
            ),
            mock.patch.object(
                stem_audit,
                "audit_catalogue_stems",
                side_effect=audit_side_effect,
            ),
        ):
            return cli.main(argv)

    def test_one_collection_snapshot_feeds_validation_and_all_renderers(self) -> None:
        from unittest import mock


        audited: list[object] = []
        candidates: list[catalogue_audit_types.ManifestCandidateResult] = []

        def audit_entries(entries: object, *_args: object, **_kwargs: object) -> StemAuditResult:
            audited.append(entries)
            return self._audit()

        real_build_candidate = catalogue_manifest_candidate.build_manifest_candidate

        def build_candidate(
            *args: object, **kwargs: object
        ) -> catalogue_audit_types.ManifestCandidateResult:
            candidate = real_build_candidate(*args, **kwargs)  # type: ignore[arg-type]
            candidates.append(candidate)
            return candidate

        with (
            mock.patch.object(
                catalogue_manifest_candidate,
                "build_manifest_candidate",
                side_effect=build_candidate,
            ) as manifest_candidate,
            mock.patch.object(render, "_render", wraps=render._render) as catalogue_renderer,
            mock.patch.object(
                render,
                "presentation_reference_audit",
                wraps=render.presentation_reference_audit,
            ) as display_renderer,
            mock.patch.object(cli, "build_ir", wraps=cli.build_ir) as ir_renderer,
        ):
            self.assertEqual(self._run([], audit=audit_entries), 0)

        self.assertEqual(self.collect_call_count, 1)
        self.assertIs(manifest_candidate.call_args.args[0], self.entries)
        self.assertEqual(audited, [self.entries])
        self.assertIs(catalogue_renderer.call_args.args[0], self.entries)
        self.assertIs(display_renderer.call_args.args[0], self.entries)
        self.assertIs(ir_renderer.call_args.args[0], self.entries)
        candidate_presentation = candidates[0].presentation
        self.assertIsNotNone(candidate_presentation)
        self.assertIs(
            catalogue_renderer.call_args.kwargs["presentation"],
            candidate_presentation,
        )
        self.assertIs(
            display_renderer.call_args.kwargs["presentation"],
            candidate_presentation,
        )

    def test_cold_offline_check_accepts_incidental_yaml_for_reviewed_non_config_model(
        self,
    ) -> None:
        """An incidental config name is not required evidence for an exact non-config ID."""
        import contextlib
        import shutil
        from unittest import mock

        document = fixtures._generator_manifest_document()
        record = cast(dict[str, dict[str, object]], document["models"])["mdx:model"]
        del record["config_evidence"]
        self.manifest.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        yaml_cache = os.path.join(self.tmp, "cold-yaml-cache")

        class _Snapshot:
            vr: dict[str, object] = {}
            mdx = {
                "Fixture Model": {
                    "model.ckpt": "https://example.invalid/model.ckpt",
                    "incidental.yaml": "https://example.invalid/incidental.yaml",
                }
            }
            demucs: dict[str, object] = {}
            apollo: dict[str, object] = {}
            meta: dict[str, object] = {}
            unsupported: dict[str, object] = {}
            report = None

        upstream = {"mdx_download_list": _Snapshot.mdx}
        real_collect_entries = catalogue.collect_entries

        def collect_expected_snapshot(
            *args: object, **kwargs: object
        ) -> tuple[object, list[catalogue_types.ModelEntry]]:
            snapshot, entries = real_collect_entries(*args, **kwargs)  # type: ignore[arg-type]
            # Bootstrap the expected artifact set with the desired reviewed-
            # non-config gate, then exercise the unmodified real path below.
            self.context.unavailable_yaml_evidence.clear()
            return snapshot, entries

        common_patches = (
            mock.patch.object(cli, "OUTPUT_PATH", self.output),
            mock.patch.object(cli, "REFERENCE_TSV_PATH", self.intent),
            mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", self.display),
            mock.patch.object(cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", self.stem),
            mock.patch.object(cli, "BUNDLED_MANIFEST_PATH", self.manifest),
            mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", yaml_cache),
            mock.patch.object(catalogue, "_build_catalogue_context", return_value=self.context),
            mock.patch.object(
                catalogue,
                "_snapshot_and_payloads",
                return_value=(_Snapshot(), (upstream, {}, {}, {})),
            ),
            mock.patch(
                "core.mdx_config_fetch._urlopen",
                side_effect=AssertionError("offline generator requested the network"),
            ),
            mock.patch.object(cli.stem_audit, "audit_catalogue_stems", side_effect=self._audit),
        )
        with contextlib.ExitStack() as stack:
            for patcher in common_patches:
                stack.enter_context(patcher)
            stack.enter_context(
                mock.patch.object(
                    catalogue, "collect_entries", side_effect=collect_expected_snapshot
                )
            )
            self.assertEqual(cli.main(["--offline"]), 0)

        self.assertFalse(os.path.exists(yaml_cache))
        shutil.rmtree(yaml_cache, ignore_errors=True)
        self.context.unavailable_yaml_evidence.clear()
        paths = (self.manifest, self.output, self.ir, self.intent, self.display, self.stem)
        before = {Path(path): Path(path).read_bytes() for path in paths}

        with contextlib.ExitStack() as stack:
            for patcher in common_patches:
                stack.enter_context(patcher)
            stack.enter_context(
                mock.patch(
                    "core.json_store.write_json_atomic",
                    side_effect=AssertionError("check attempted a manifest write"),
                )
            )
            stack.enter_context(
                mock.patch(
                    "core.json_store.write_text_atomic",
                    side_effect=AssertionError("check attempted an artifact write"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue.os,
                    "replace",
                    side_effect=AssertionError("check attempted a cache write"),
                )
            )
            self.assertEqual(cli.main(["--check", "--offline"]), 0)

        self.assertEqual(self.context.unavailable_yaml_evidence, set())
        self.assertFalse(os.path.exists(yaml_cache))
        self.assertEqual(
            {Path(path): Path(path).read_bytes() for path in paths},
            before,
        )

    def test_candidate_presentation_alias_and_waiver_render_without_global_state(self) -> None:
        """Markdown and TSV use the exact presentation view loaded from the fixture path."""
        from unittest import mock

        document = fixtures._generator_manifest_document()
        record = cast(dict[str, dict[str, object]], document["models"])["mdx:model"]
        record["display_alias"] = "Candidate_Only_Alias"
        record["display_waivers"] = {
            "underscore": "Candidate-only fixture alias is deliberately underscored."
        }
        self.manifest.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        class _ForbiddenGlobalPresentation(dict[str, object]):
            def __getitem__(self, key: str) -> object:
                raise AssertionError(f"renderer consulted global presentation section {key!r}")

            def get(self, key: str, default: object = None) -> object:
                raise AssertionError(f"renderer consulted global presentation section {key!r}")

        with (
            mock.patch(
                "core.model_naming._DISPLAY_MANIFEST",
                _ForbiddenGlobalPresentation(),
            ),
            mock.patch.object(
                render,
                "load_model_display_manifest",
                side_effect=AssertionError("renderer reloaded global presentation state"),
            ),
        ):
            self.assertEqual(self._run([]), 0)

        markdown = Path(self.output).read_text(encoding="utf-8")
        display_rows = Path(self.display).read_text(encoding="utf-8").splitlines()
        headers = display_rows[0].split("\t")
        row = dict(zip(headers, display_rows[1].split("\t"), strict=True))
        self.assertIn("### Candidate_Only_Alias", markdown)
        self.assertEqual(row["current_display"], "Candidate_Only_Alias")
        self.assertEqual(row["presentation_flags"], "underscore")
        self.assertEqual(
            row["waiver_reasons"],
            "underscore: Candidate-only fixture alias is deliberately underscored.",
        )
        self.assertEqual(row["review_status"], "reviewed")

    def test_default_write_synchronizes_every_generated_artifact(self) -> None:
        """Removing a default renderer must leave a missing checked-in output."""
        self.assertEqual(self._run([]), 0)

        for path in (self.output, self.ir, self.intent, self.display, self.stem, self.manifest):
            with self.subTest(path=path):
                self.assertTrue(os.path.isfile(path))
        with open(self.ir, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["entry_count"], 1)
        with open(self.manifest, encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(
            manifest["models"]["mdx:model"]["catalogue_evidence"]["source"],
            "fixture",
        )

    def test_check_compares_the_unified_manifest_without_repairing_it(self) -> None:
        self.assertEqual(self._run([]), 0)
        with open(self.manifest, encoding="utf-8") as handle:
            stale = json.load(handle)
        stale["models"]["mdx:model"]["catalogue_evidence"]["source"] = "stale"
        with open(self.manifest, "w", encoding="utf-8") as handle:
            json.dump(stale, handle, indent=2, sort_keys=True)
            handle.write("\n")
        with open(self.manifest, "rb") as handle:
            before = handle.read()

        self.assertEqual(self._run(["--check"]), 1)
        with open(self.manifest, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_check_compares_every_generated_artifact_without_repairing_it(self) -> None:
        """A stale reference cannot escape --check because its flag was omitted."""
        self.assertEqual(self._run([]), 0)
        with open(self.intent, "a", encoding="utf-8") as handle:
            handle.write("stale\n")
        with open(self.intent, "rb") as handle:
            before = handle.read()

        self.assertEqual(self._run(["--check"]), 1)
        with open(self.intent, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_structural_audit_failure_blocks_every_replacement(self) -> None:
        """Publishing any subset after invalidating manifest structure is unsafe."""
        invalid = StemAuditResult(
            catalogue_model_ids=("mdx:model",),
            reviewed_model_ids=(),
            waived_model_ids=(),
            raw_model_ids=("mdx:model",),
            evidence_counts=CatalogueEvidenceCounts(0, 0, 0, ()),
            diagnostics=(
                StemAuditDiagnostic(
                    code="catalogue-unreviewed",
                    model_ids=("mdx:model",),
                    message="fixture has no reviewed declaration",
                ),
            ),
        )
        sentinels = {
            self.output: b"markdown sentinel\n",
            self.intent: b"intent sentinel\n",
            self.display: b"display sentinel\n",
            self.stem: b"stem sentinel\n",
            self.ir: b"ir sentinel\n",
        }
        for path, contents in sentinels.items():
            with open(path, "wb") as handle:
                handle.write(contents)

        self.assertEqual(self._run([], audit=invalid), 1)
        for path, contents in sentinels.items():
            with self.subTest(path=path), open(path, "rb") as handle:
                self.assertEqual(handle.read(), contents)

    def test_missing_required_supplemental_evidence_is_degraded(self) -> None:
        """Unavailable evidence cannot replace a complete reference set."""
        incomplete = catalogue_types.CatalogueContext(
            unavailable_supplemental_evidence=("community models.txt reference",)
        )
        before = self.manifest.read_bytes()

        for argv in ([], ["--allow-degraded"]):
            with self.subTest(argv=argv):
                self.assertEqual(self._run(argv, context=incomplete), 2)
        self.assertFalse(os.path.exists(self.output))
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_display_collision_blocks_every_replacement(self) -> None:
        collision = render.PresentationReferenceAudit(
            text="header\n",
            unreviewed=(),
            collisions=(("Same", ("mdx:model", "mdx:other")),),
        )
        sentinels = {path: Path(path).read_bytes() for path in (self.manifest,)}

        with mock.patch.object(render, "presentation_reference_audit", return_value=collision):
            self.assertEqual(self._run([]), 1)

        for path, contents in sentinels.items():
            with self.subTest(path=path), open(path, "rb") as handle:
                self.assertEqual(handle.read(), contents)

    def test_failed_late_atomic_writer_rolls_back_the_whole_bundle(self) -> None:
        self.assertEqual(self._run([]), 0)
        paths = (self.manifest, self.output, self.ir, self.intent, self.display, self.stem)
        before = {path: Path(path).read_bytes() for path in paths}
        real_writer = __import__(
            "core.json_store", fromlist=["write_text_atomic"]
        ).write_text_atomic

        def fail_display(path: str, text: str) -> None:
            if path == self.display:
                raise OSError("late fixture replacement failure")
            real_writer(path, text)

        self.entry.source = "changed-source"
        with mock.patch("core.json_store.write_text_atomic", side_effect=fail_display):
            with self.assertRaisesRegex(OSError, "late fixture replacement failure"):
                self._run([])

        for path in paths:
            with self.subTest(path=path), open(path, "rb") as handle:
                self.assertEqual(handle.read(), before[path])

    def test_unserializable_rendered_json_fails_before_the_first_replacement(self) -> None:
        self.assertEqual(self._run([]), 0)
        paths = (self.manifest, self.output, self.ir, self.intent, self.display, self.stem)
        before = {path: Path(path).read_bytes() for path in paths}

        with (
            mock.patch.object(cli, "build_ir", return_value={"invalid": object()}),
            mock.patch("core.json_store.write_json_atomic") as write_json,
            mock.patch("core.json_store.write_text_atomic") as write_text,
        ):
            with self.assertRaises(TypeError):
                self._run([])

        write_json.assert_not_called()
        write_text.assert_not_called()
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(Path(path).read_bytes(), before[path])

    def test_summary_reports_manifest_lifecycle_evidence_and_drift_counts(self) -> None:
        import contextlib
        import io

        from core.model_manifest import load_model_manifest_document

        document = fixtures._generator_manifest_document()
        registry = load_model_manifest_document(document)
        manifest_audit = catalogue_manifest_candidate.build_manifest_candidate(
            [fixtures._generator_manifest_entry(config_sha256="b" * 64)],
            document,
            registry=registry,
        )
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            print(
                render.render_summary_report(
                    [self.entry],
                    manifest_audit=manifest_audit,
                )
            )

        text = output.getvalue()
        self.assertIn("Current manifest models: **1**", text)
        self.assertIn("Retired manifest models: **0**", text)
        self.assertIn("Evidence ready: **1**", text)
        self.assertIn("Same-semantics config digest drift: **1**", text)
        self.assertIn("Semantic config mismatches: **0**", text)
        self.assertIn("Lifecycle drift: **0**", text)
        self.assertIn("Manifest reference drift: **1**", text)

    def test_summary_reports_semantic_findings_without_publishing(self) -> None:
        """A summary must consume the audit result instead of recollecting semantics."""
        import contextlib
        import io

        finding = StemAuditResult(
            catalogue_model_ids=("mdx:model",),
            reviewed_model_ids=(),
            waived_model_ids=(),
            raw_model_ids=("mdx:model",),
            evidence_counts=CatalogueEvidenceCounts(0, 0, 0, ()),
            diagnostics=(
                StemAuditDiagnostic(
                    code="reference-drift",
                    model_ids=("mdx:model",),
                    message="fixture reference differs",
                    structural=False,
                ),
            ),
        )
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self._run(["--summary"], audit=finding), 1)

        self.assertIn("## Reference drift", stdout.getvalue())
        self.assertFalse(os.path.exists(self.output))

    def test_summary_reports_disk_drift_separately_and_changes_no_bytes(self) -> None:
        self.assertEqual(self._run([]), 0)
        with open(self.stem, "a", encoding="utf-8") as handle:
            handle.write("stale row\n")
        paths = (self.output, self.ir, self.intent, self.display, self.stem, self.manifest)
        before = {}
        for path in paths:
            with open(path, "rb") as handle:
                before[path] = handle.read()

        self.assertEqual(self._run(["--summary"]), 1)

        for path in paths:
            with self.subTest(path=path), open(path, "rb") as handle:
                self.assertEqual(handle.read(), before[path])

    def test_candidate_row_parity_failure_blocks_write_check_and_summary(self) -> None:
        from unittest import mock

        for argv in ([], ["--check"], ["--summary"]):
            with (
                self.subTest(argv=argv),
                mock.patch.object(
                    render,
                    "stem_semantics_reference_tsv",
                    return_value="not the structured rows\n",
                ),
            ):
                self.assertEqual(self._run(argv), 1)
            self.assertFalse(os.path.exists(self.output))

    def test_help_pins_all_four_exit_codes_and_summary_semantics(self) -> None:
        import contextlib
        import io

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            cli._parse_args(["--help"])

        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("0  clean snapshot", help_text)
        self.assertIn("1  generated drift or semantic findings", help_text)
        self.assertIn("2  degraded or unusable evidence", help_text)
        self.assertIn("130  interrupted opt-in remote confidence audit", help_text)
        self.assertNotIn("--summary completed", help_text)

    def test_legacy_reference_flags_are_deprecated_no_ops(self) -> None:
        """Compatibility flags must not split the generated artifact bundle."""
        import contextlib
        import io

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(
                self._run(
                    [
                        "--write-tsv",
                        "--write-display-reference",
                        "--write-stem-semantics-reference",
                    ]
                ),
                0,
            )
        self.assertEqual(stderr.getvalue().lower().count("deprecated"), 3)
        self.assertTrue(os.path.isfile(self.stem))

    def test_validated_registry_is_loaded_once_and_renderer_consumes_audit_rows(self) -> None:
        """The renderer cannot reload or independently resolve manifest semantics."""
        from unittest import mock

        from core.model_manifest import load_model_manifest_document

        with open(self.manifest, encoding="utf-8") as handle:
            document = json.load(handle)
        registry = load_model_manifest_document(document)
        seen: list[object] = []
        rendered_rows: list[object] = []

        def render_stems(rows: object) -> str:
            rendered_rows.append(rows)
            return catalogue_audit_reference.reference_rows_tsv(rows)  # type: ignore[arg-type]

        def audit_stems(*_args: object, **kwargs: object) -> StemAuditResult:
            seen.append(kwargs.get("registry"))
            return self._audit()

        with (
            mock.patch.object(
                cli,
                "load_model_manifest_document",
                wraps=load_model_manifest_document,
            ) as loader,
            mock.patch.object(
                render,
                "stem_semantics_reference_tsv",
                side_effect=render_stems,
            ),
        ):
            self.assertEqual(self._run([], audit=audit_stems), 0)

        loader.assert_called_once()
        self.assertEqual(seen, [registry.stems])
        self.assertEqual(rendered_rows, [()])

    def test_missing_politrees_hash_files_do_not_degrade_a_complete_offline_bundle(self) -> None:
        """Unused hash supplements cannot turn five matching artifacts into exit 2."""
        from unittest import mock

        community_cache = os.path.join(self.tmp, "community-cache")
        unused_hash_cache = os.path.join(self.tmp, "absent-politrees-hashes")
        yaml_cache = os.path.join(self.tmp, "yaml-cache")
        yaml_url = "https://example.invalid/model.yaml"
        os.makedirs(community_cache)
        with open(
            catalogue_cache._cache_path(
                community_cache,
                catalogue._COMMUNITY_MODELS_URL,
                "models.txt",
            ),
            "wb",
        ) as handle:
            handle.write(b"model.ckpt  MDX23C  vocals*, other  Fixture model\n")
        os.makedirs(yaml_cache)
        yaml_bytes = b"training:\n  instruments: [Vocals, Other]\n  target_instrument: Vocals\n"
        with open(
            catalogue_cache._cache_path(yaml_cache, yaml_url, "model.yaml"),
            "wb",
        ) as handle:
            handle.write(yaml_bytes)
        self.entry.config_yaml = "model.yaml"
        self.entry.config_url = yaml_url
        self.entry.config_sha256 = __import__("hashlib").sha256(yaml_bytes).hexdigest()
        self.entry.instruments = ["Vocals", "Other"]
        self.entry.target_instrument = "Vocals"
        self.entry.metadata_source = "remote_yaml:model.yaml"
        network_calls: list[str] = []

        def record_network(target: object) -> None:
            network_calls.append(str(getattr(target, "full_url", target)))
            raise AssertionError("offline generator requested the network")

        with (
            mock.patch.object(catalogue_locations, "COMMUNITY_CACHE_DIR", community_cache),
            mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", yaml_cache),
            mock.patch("core.mdx_config_fetch._urlopen", side_effect=record_network),
        ):
            context = catalogue._build_catalogue_context(policy=catalogue_cache.OFFLINE_FETCH_POLICY)

        self.assertEqual(network_calls, [])
        self.assertFalse(os.path.exists(unused_hash_cache))
        self.assertEqual(context.unavailable_supplemental_evidence, ())
        self.assertEqual(set(context.community_by_file), {"model.ckpt"})
        informational = StemAuditResult(
            catalogue_model_ids=("mdx:model",),
            reviewed_model_ids=("mdx:model",),
            waived_model_ids=(),
            raw_model_ids=(),
            evidence_counts=CatalogueEvidenceCounts(148, 123, 92, ()),
            diagnostics=(),
            native_to_role_ambiguities=(
                NativeToRoleAmbiguity(
                    normalized_native="vocals",
                    native_spellings=("Vocals", "vocals"),
                    role_ids=("vocal.lead", "vocal.vocals"),
                    model_ids=("mdx:model",),
                    evidence=(),
                ),
            ),
            role_to_native_variants=(),
        )
        self.assertTrue(informational.ok)
        self.assertTrue(informational.structurally_valid)

        self.assertEqual(self._run([], context=context, audit=informational), 0)
        self.assertEqual(self._run(["--check"], context=context, audit=informational), 0)
        for path in (self.output, self.ir, self.intent, self.display, self.stem):
            with self.subTest(path=path):
                self.assertTrue(os.path.isfile(path))


class MalformedManifestCliTests(unittest.TestCase):
    """Normal modes reject a bad manifest before collection or rendering."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-malformed-stem-manifest-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.output = os.path.join(self.tmp, "models-catalogue.md")
        self.intent = os.path.join(self.tmp, "model_intent_reference.tsv")
        self.display = os.path.join(self.tmp, "model_display_reference.tsv")
        self.stem = os.path.join(self.tmp, "model_stem_semantics_reference.tsv")
        self.ir = catalogue._ir_path_for(self.output)
        self.manifest = os.path.join(self.tmp, "bad-manifest.json")
        with open(self.manifest, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 0}, handle)
        self.sentinels = {
            self.output: b"catalogue sentinel\n",
            self.ir: b"ir sentinel\n",
            self.intent: b"intent sentinel\n",
            self.display: b"display sentinel\n",
            self.stem: b"stem sentinel\n",
        }
        for path, data in self.sentinels.items():
            with open(path, "wb") as handle:
                handle.write(data)

    def _assert_manifest_invalid(self, argv: list[str]) -> None:
        import contextlib
        import io
        from pathlib import Path
        from unittest import mock

        stderr = io.StringIO()
        blocked = AssertionError("manifest validation must precede this boundary")
        with (
            mock.patch.object(cli, "OUTPUT_PATH", self.output),
            mock.patch.object(cli, "REFERENCE_TSV_PATH", self.intent),
            mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", self.display),
            mock.patch.object(cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", self.stem),
            mock.patch.object(
                cli,
                "BUNDLED_MANIFEST_PATH",
                Path(self.manifest),
                create=True,
            ),
            mock.patch.object(
                catalogue,
                "_build_catalogue_context",
                side_effect=blocked,
            ) as context_builder,
            mock.patch.object(catalogue, "collect_entries", side_effect=blocked) as collector,
            mock.patch.object(render, "_render", side_effect=blocked) as catalogue_renderer,
            mock.patch.object(
                render,
                "presentation_reference_audit",
                side_effect=blocked,
            ) as display_renderer,
            mock.patch.object(
                render,
                "stem_semantics_reference_tsv",
                side_effect=blocked,
            ) as stem_renderer,
            mock.patch.object(
                render,
                "render_summary_report",
                side_effect=blocked,
            ) as summary_renderer,
            contextlib.redirect_stderr(stderr),
        ):
            rc = cli.main(argv)

        self.assertEqual(rc, 1)
        lines = stderr.getvalue().splitlines()
        self.assertEqual(len(lines), 1, stderr.getvalue())
        self.assertIn("manifest-invalid", lines[0])
        self.assertNotIn("Traceback", stderr.getvalue())
        for boundary in (
            context_builder,
            collector,
            catalogue_renderer,
            display_renderer,
            stem_renderer,
            summary_renderer,
        ):
            boundary.assert_not_called()
        for path, data in self.sentinels.items():
            with self.subTest(path=path), open(path, "rb") as handle:
                self.assertEqual(handle.read(), data)

    def test_write_rejects_malformed_manifest_before_side_effects(self) -> None:
        self._assert_manifest_invalid([])

    def test_check_rejects_malformed_manifest_before_side_effects(self) -> None:
        self._assert_manifest_invalid(["--check"])

    def test_summary_rejects_malformed_manifest_before_side_effects(self) -> None:
        self._assert_manifest_invalid(["--summary"])


class ReviewedRepositoryPublicationTests(unittest.TestCase):
    def test_generated_bundle_has_the_reviewed_task_10_end_state(self) -> None:
        """The checked-in publication must retain every reviewed count and zero gate."""
        root = Path(fixtures.ROOT)
        manifest = json.loads((root / "bundled/model_manifest.json").read_text())
        current = {
            model_id: record
            for model_id, record in manifest["models"].items()
            if record["lifecycle"] == "current"
        }
        declarations = {
            model_id: record["stem_semantics"]
            for model_id, record in current.items()
            if "stem_semantics" in record
        }
        waivers = {
            model_id: record["stem_waiver"]
            for model_id, record in current.items()
            if "stem_waiver" in record
        }
        self.assertEqual(len(current), 485)
        self.assertEqual(len(declarations), 483)
        self.assertEqual(
            set(waivers),
            {
                "apollo:apollo_edm_big_by_essid",
                "apollo:apollo_edm_by_essid",
            },
        )
        self.assertEqual(
            sum(len(declaration["contexts"]) for declaration in declarations.values()),
            514,
        )

        stem_lines = (root / "docs/model_stem_semantics_reference.tsv").read_text().splitlines()
        stem_headers = stem_lines[0].split("\t")
        stem_rows = [
            dict(zip(stem_headers, line.split("\t"), strict=True)) for line in stem_lines[1:]
        ]
        self.assertEqual(len(stem_rows), 1_237)
        self.assertEqual(
            {row["model_id"] for row in stem_rows if row["review_status"] == "raw"},
            set(),
        )

        display_lines = (root / "docs/model_display_reference.tsv").read_text().splitlines()
        display_headers = display_lines[0].split("\t")
        display_rows = [
            dict(zip(display_headers, line.split("\t"), strict=True)) for line in display_lines[1:]
        ]
        self.assertEqual(len(display_rows), 485)
        self.assertEqual(
            {row["canonical_id"] for row in display_rows if row["review_status"] == "unreviewed"},
            set(),
        )
        normalized: dict[str, list[str]] = {}
        for row in display_rows:
            key = unicodedata.normalize("NFKC", row["current_display"]).casefold()
            normalized.setdefault(key, []).append(row["canonical_id"])
        self.assertEqual(
            {key: ids for key, ids in normalized.items() if len(ids) > 1},
            {},
        )

        catalogue_text = (root / "docs/models-catalogue.md").read_text()
        self.assertIn("- Snapshot mode: `force`", catalogue_text)
        self.assertIn("- Source stale: none", catalogue_text)
        self.assertIn("- Source failed: none", catalogue_text)
        self.assertIn("- Source upstream live: True", catalogue_text)
        refreshed_line = next(
            line for line in catalogue_text.splitlines() if line.startswith("- Source refreshed:")
        )
        self.assertEqual(
            {source.strip() for source in refreshed_line.partition(":")[2].split(",")},
            {"extras", "upstream", "politrees", "mvsepless"},
        )
