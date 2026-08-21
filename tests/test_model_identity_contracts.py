"""Locks for the model-identity cutover. Characterization tests in this
module describe *current* contracts and must pass on the first commit.
Target-behavior tests are added in later tasks in this same file."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from bundled.constants import CHOOSE_MODEL, NO_MODEL
from core.model_catalogue import CatalogEntryId, ModelCatalogueRecord, ModelCatalogueService
from core.model_identity import (
    CatalogueRef,
    DemucsSpec,
    MdxSpec,
    ModelArtifacts,
    ModelRecord,
)


class DownloadMatchingLockTests(unittest.TestCase):
    """models download stays catalogue-facing: exact row id, exact
    selectable/display, then one unique substring. Ambiguity fails."""

    def setUp(self) -> None:
        self.service = ModelCatalogueService.__new__(ModelCatalogueService)
        self.hq4_id = CatalogEntryId("mdx", "MDX-Net Model: UVR-MDX-NET Inst HQ 4")
        self.row = ModelCatalogueRecord(
            id=self.hq4_id.value,
            family="mdx",
            selection=self.hq4_id.selection,
            display="MDX-Net — UVR-MDX-NET Inst HQ 4",
            purpose="all",
            supported=True,
            installed=False,
        )
        self.service.records = lambda: (self.row,)  # type: ignore[method-assign]

    def test_exact_catalog_entry_id_resolves(self) -> None:
        got = self.service.resolve(self.hq4_id.value)
        self.assertEqual(got.id, self.hq4_id.value)

    def test_exact_selectable_resolves(self) -> None:
        got = self.service.resolve("MDX-Net Model: UVR-MDX-NET Inst HQ 4")
        self.assertEqual(got.selection, self.hq4_id.selection)

    def test_exact_display_resolves(self) -> None:
        got = self.service.resolve("MDX-Net — UVR-MDX-NET Inst HQ 4")
        self.assertEqual(got.selection, self.hq4_id.selection)

    def test_unique_substring_resolves(self) -> None:
        got = self.service.resolve("Inst HQ 4")
        self.assertEqual(got.selection, self.hq4_id.selection)

    def test_ambiguous_substring_lists_candidate_ids(self) -> None:
        other_id = CatalogEntryId("mdx", "MDX-Net Model: UVR-MDX-NET Inst HQ 5")
        other = ModelCatalogueRecord(
            id=other_id.value,
            family="mdx",
            selection=other_id.selection,
            display="MDX-Net — UVR-MDX-NET Inst HQ 5",
            purpose="all",
            supported=True,
            installed=False,
        )
        self.service.records = lambda: (self.row, other)  # type: ignore[method-assign]
        with self.assertRaises(ValueError) as ctx:
            self.service.resolve("Inst HQ")
        message = str(ctx.exception)
        self.assertIn(self.hq4_id.value, message)
        self.assertIn(other_id.value, message)


class ModelRecordContractTests(unittest.TestCase):
    def test_to_dict_reports_backend_name_not_engine_name(self) -> None:
        record = ModelRecord(
            id="demucs:htdemucs_6s",
            family="demucs",
            basename="htdemucs_6s",
            display="v4 — htdemucs_6s",
            backend_name="htdemucs_6s",
            artifacts=ModelArtifacts(
                primary_filename="htdemucs_6s.yaml",
                supporting_filenames=("abc12345-deadbeef.th",),
            ),
            installed=True,
            catalogue_entry=CatalogueRef("demucs", "Demucs v4: htdemucs_6s"),
            demucs=DemucsSpec("v4", "6_stem"),
        )
        payload = record.to_dict()
        self.assertEqual(payload["backend_name"], "htdemucs_6s")
        self.assertEqual(payload["primary_artifact"], "htdemucs_6s.yaml")
        self.assertEqual(payload["supporting_artifacts"], ["abc12345-deadbeef.th"])
        self.assertEqual(payload["demucs_version"], "v4")
        self.assertEqual(payload["source_layout"], "6_stem")
        self.assertNotIn("engine_name", payload)

    def test_mdx_kind_is_serialized(self) -> None:
        record = ModelRecord(
            id="mdx:UVR-MDX-NET-Inst_HQ_4",
            family="mdx",
            basename="UVR-MDX-NET-Inst_HQ_4",
            display="MDX-Net — UVR-MDX-NET Inst HQ 4",
            backend_name="UVR-MDX-NET-Inst_HQ_4",
            artifacts=ModelArtifacts("UVR-MDX-NET-Inst_HQ_4.onnx"),
            installed=True,
            mdx=MdxSpec("classic_onnx"),
        )
        self.assertEqual(record.to_dict()["mdx_kind"], "classic_onnx")


class ManifestSchemaSnapshotTests(unittest.TestCase):
    """Replayable manifests are schema 1 (separate/ensemble) and 2 (audio).
    Bench is schema 1 and is not replayable. Task 18 bumps replayable
    manifests to schema 3."""

    def test_separate_manifest_schema_is_1(self) -> None:
        from cli.execution import MANIFEST_SCHEMA_VERSION

        self.assertEqual(MANIFEST_SCHEMA_VERSION, 1)

    def test_replay_currently_accepts_schema_1_and_2(self) -> None:
        import inspect
        from cli import replay

        source = inspect.getsource(replay.cmd_run)
        self.assertIn("{1, 2}", source)

    def test_bench_manifest_schema_stays_1(self) -> None:
        import inspect
        from cli import bench

        source = inspect.getsource(bench.cmd_bench)
        self.assertIn('"schema_version": 1', source)


class SentinelLockTests(unittest.TestCase):
    def test_choose_and_no_model_strings_are_stable(self) -> None:
        self.assertEqual(CHOOSE_MODEL, "Choose Model")
        self.assertEqual(NO_MODEL, "No Model Selected")
