"""Locks for the model-identity cutover. Characterization tests in this
module describe *current* contracts and must pass on the first commit.
Target-behavior tests are added in later tasks in this same file."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from bundled.constants import CHOOSE_MODEL, NO_MODEL
from core.model_catalogue import CatalogEntryId, ModelCatalogueRecord, ModelCatalogueService
from core.model_identity import (
    CatalogueRef,
    DemucsSpec,
    IdentityIndex,
    MdxSpec,
    ModelArtifacts,
    ModelId,
    ModelRecord,
    parse_stored_model_id,
)


def _empty_repo(**overrides: Any):
    values = {
        "list_vr_models": lambda: [],
        "list_mdx_models": lambda: [],
        "list_demucs_models": lambda: [],
        "inventory_generation": 0,
        "catalogue_revision": "x",
        "naming_revision": 0,
        "mdx_name_select_MAPPER": {},
        "demucs_name_select_MAPPER": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _snapshot(
    *,
    vr: Any = None,
    mdx: Any = None,
    demucs: Any = None,
    apollo: Any = None,
    meta: Any = None,
):
    families = {
        "vr": vr or {},
        "mdx": mdx or {},
        "demucs": demucs or {},
        "apollo": apollo or {},
    }
    return SimpleNamespace(
        **families,
        meta_by_family={
            family: dict((meta or {}).get(family, {})) for family in families
        },
        unsupported={},
    )


def _fake_mdx_pair():
    from bundled.constants import MDX_ARCH_TYPE
    from core.catalog_sources import EntryMeta

    selectable = "MDX-Net Model: Pair"
    files = {
        "model.ckpt": "http://example.invalid/model.ckpt",
        "config.yaml": "http://example.invalid/config.yaml",
    }
    entry = EntryMeta(
        label=selectable,
        display="MDX-Net — Pair",
        arch=MDX_ARCH_TYPE,
        files=files,
        checkpoint="model.ckpt",
    )
    return _empty_repo(), _snapshot(
        mdx={selectable: files}, meta={"mdx": {selectable: entry}}
    )


def _fake_demucs_bag():
    from bundled.constants import DEMUCS_ARCH_TYPE
    from core.catalog_sources import EntryMeta

    selectable = "Demucs v4: htdemucs_ft"
    files = {
        "htdemucs_ft.yaml": "http://example.invalid/htdemucs_ft.yaml",
        "f7e0c4bc-ba3fe64a.th": "http://example.invalid/f7e0c4bc-ba3fe64a.th",
        "d12395a8-e57c48e6.th": "http://example.invalid/d12395a8-e57c48e6.th",
    }
    entry = EntryMeta(
        label=selectable,
        display="v4 — htdemucs_ft",
        arch=DEMUCS_ARCH_TYPE,
        files=files,
        checkpoint="htdemucs_ft.yaml",
    )
    return _empty_repo(), _snapshot(
        demucs={selectable: files}, meta={"demucs": {selectable: entry}}
    )


def _fake_demucs_root_ckpt():
    return _empty_repo(list_demucs_models=lambda: ["mystery"]), _snapshot()


def _fake_mdx_extension_collision():
    return _empty_repo(
        _model_artifact_files=lambda family: (
            ["foo.onnx", "foo.ckpt"] if family == "mdx" else []
        ),
    ), _snapshot()


class StrictIdParseTests(unittest.TestCase):
    def test_parses_canonical_id(self) -> None:
        parsed = parse_stored_model_id("mdx:UVR-MDX-NET-Inst_HQ_4")
        self.assertEqual(parsed.family, "mdx")
        self.assertEqual(parsed.basename, "UVR-MDX-NET-Inst_HQ_4")

    def test_rejects_display_and_arch_prefix(self) -> None:
        for value in (
            "MDX-Net — UVR-MDX-NET Inst HQ 4",
            "MDX-Net: UVR-MDX-NET Inst HQ 4",
            "UVR-MDX-NET-Inst_HQ_4",
            "mdx:",
            "roformer:foo",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_stored_model_id(value)

    def test_does_not_casefold_basename(self) -> None:
        parsed = parse_stored_model_id("mdx:Some_Model")
        self.assertEqual(parsed.basename, "Some_Model")


class IdentityIndexLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        record = ModelRecord(
            id="mdx:Some_Model",
            family="mdx",
            basename="Some_Model",
            display="MDX-Net — Some Model",
            backend_name="Some_Model",
            artifacts=ModelArtifacts("Some_Model.onnx"),
            installed=True,
        )
        self.index = IdentityIndex({record.id: record})

    def test_exact_id_hits(self) -> None:
        self.assertEqual(self.index.lookup("mdx:Some_Model").basename, "Some_Model")

    def test_casefold_id_does_not_hit(self) -> None:
        with self.assertRaises(ValueError):
            self.index.lookup("mdx:some_model")

    def test_display_does_not_hit(self) -> None:
        with self.assertRaises(ValueError):
            self.index.lookup("MDX-Net — Some Model")


class ArtifactStemTests(unittest.TestCase):
    def test_strips_compound_th_gz(self) -> None:
        from core.model_inventory import artifact_stem

        self.assertEqual(artifact_stem("tasnet.th.gz"), "tasnet")
        self.assertEqual(artifact_stem("tasnet.th"), "tasnet")
        self.assertEqual(artifact_stem("model.ckpt"), "model")


class InventoryCardinalityTests(unittest.TestCase):
    def test_mdx_checkpoint_plus_yaml_is_one_record(self) -> None:
        from core.model_inventory import build_identity_index

        repo, snapshot = _fake_mdx_pair()
        index = build_identity_index(repo, snapshot=snapshot)
        ids = [record.id for record in index.records() if record.family == "mdx"]
        self.assertEqual(ids, ["mdx:model"])
        record = index.lookup("mdx:model")
        self.assertEqual(record.artifacts.primary_filename, "model.ckpt")
        self.assertEqual(record.artifacts.supporting_filenames, ("config.yaml",))

    def test_demucs_bag_plus_members_is_one_record(self) -> None:
        from core.model_inventory import build_identity_index

        repo, snapshot = _fake_demucs_bag()
        index = build_identity_index(repo, snapshot=snapshot)
        demucs = [record for record in index.records() if record.family == "demucs"]
        self.assertEqual([record.id for record in demucs], ["demucs:htdemucs_ft"])
        self.assertTrue(demucs[0].artifacts.supporting_filenames)

    def test_bundled_demucs_spec_enriches_installed_bag(self) -> None:
        from core.model_inventory import build_identity_index

        repo = _empty_repo(
            _model_artifact_files=lambda family: (
                ["htdemucs_6s.yaml"] if family == "demucs" else []
            ),
        )
        record = build_identity_index(repo, snapshot=_snapshot()).lookup(
            "demucs:htdemucs_6s"
        )
        self.assertEqual(record.demucs, DemucsSpec("v4", "6_stem"))
        self.assertTrue(record.identity_complete)

    def test_yaml_shaped_id_is_not_a_record(self) -> None:
        from core.model_inventory import build_identity_index

        repo, snapshot = _fake_mdx_pair()
        index = build_identity_index(repo, snapshot=snapshot)
        with self.assertRaises(ValueError):
            index.lookup("mdx:config")

    def test_demucs_root_ckpt_is_not_a_record(self) -> None:
        from core.model_inventory import build_identity_index

        repo, snapshot = _fake_demucs_root_ckpt()
        index = build_identity_index(repo, snapshot=snapshot)
        ids = [record.id for record in index.records()]
        self.assertNotIn("demucs:mystery", ids)

    def test_builder_does_not_touch_the_network(self) -> None:
        from core.model_inventory import build_identity_index

        repo, snapshot = _fake_mdx_pair()
        with patch(
            "core.mdx_config_fetch.ensure_mdx_c_config",
            side_effect=AssertionError("fetch"),
        ):
            build_identity_index(repo, snapshot=snapshot)

    def test_installed_mdx_pair_with_different_stems(self) -> None:
        import tempfile

        from core.model_inventory import build_identity_index

        with tempfile.TemporaryDirectory() as directory:
            yaml_path = f"{directory}/config.yaml"
            with open(yaml_path, "w", encoding="utf-8") as handle:
                handle.write("model_type: mdx23c\n")
            repo = _empty_repo(
                _model_artifact_files=lambda family: (
                    ["model.ckpt", "config.yaml"] if family == "mdx" else []
                ),
                _model_artifact_path=lambda family, name: (
                    yaml_path if name == "config.yaml" else f"{directory}/{name}"
                ),
            )
            index = build_identity_index(repo, snapshot=_snapshot())
            record = index.lookup("mdx:model")
            self.assertTrue(record.installed)
            self.assertEqual(record.artifacts.primary_filename, "model.ckpt")
            self.assertEqual(record.artifacts.supporting_filenames, ("config.yaml",))
            self.assertEqual(record.mdx, MdxSpec("mdx23c"))
            self.assertTrue(record.identity_complete)


class CollisionAndSafetyTests(unittest.TestCase):
    def test_onnx_and_ckpt_same_basename_are_unavailable(self) -> None:
        from core.model_inventory import build_identity_index

        repo, snapshot = _fake_mdx_extension_collision()
        index = build_identity_index(repo, snapshot=snapshot)
        with self.assertRaises(ValueError):
            index.lookup("mdx:foo")
        runnable = [
            record
            for record in index.records()
            if record.id == "mdx:foo" and record.identity_complete
        ]
        self.assertEqual(runnable, [])

    def test_rejects_parent_directory_artifact_name(self) -> None:
        from core.model_inventory import validate_artifact_name

        with self.assertRaises(ValueError):
            validate_artifact_name("../escape.pth", family="vr")

    def test_stale_generation_discards_the_index(self) -> None:
        import threading

        from core.model_identity import ModelIdentityService
        from core.model_inventory import build_identity_index

        builds: list[int] = []

        class Repo:
            inventory_generation = 1
            catalogue_revision = "a"
            naming_revision = 0
            _inventory_lock = threading.RLock()

            def list_vr_models(self):
                return []

            def list_mdx_models(self):
                return []

            def list_demucs_models(self):
                return []

        repo = Repo()
        service = ModelIdentityService(repo)

        def racing_build(*args: Any, **kwargs: Any):
            builds.append(repo.inventory_generation)
            if len(builds) == 1:
                repo.inventory_generation = 2
            return build_identity_index(*args, **kwargs)

        with patch("core.model_inventory.build_identity_index", side_effect=racing_build):
            service.records()
        self.assertGreaterEqual(len(builds), 2)


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


class MetaByFamilyTests(unittest.TestCase):
    def test_snapshot_has_family_split_meta(self) -> None:
        import typing

        from core.catalogue_coordinator import CatalogueSnapshot

        hints = typing.get_type_hints(CatalogueSnapshot)
        self.assertIn("meta_by_family", hints)

    def test_same_selectable_in_two_families_does_not_overwrite(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE, VR_ARCH_TYPE
        from core.catalogue_coordinator import build_meta_by_family

        vr = {"Shared Label": {"a.pth": "http://example.invalid/a.pth"}}
        mdx = {"Shared Label": {"b.onnx": "http://example.invalid/b.onnx"}}
        result = build_meta_by_family(vr, mdx, {}, {}, extra_meta={})
        self.assertEqual(result["vr"]["Shared Label"].arch, VR_ARCH_TYPE)
        self.assertEqual(result["mdx"]["Shared Label"].arch, MDX_ARCH_TYPE)


class DisplayIndexPrimaryOnlyTests(unittest.TestCase):
    def test_yaml_stem_is_not_an_index_key(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.catalogue_coordinator import _basename_index

        meta = {
            "MDX-Net Model: Pair": EntryMeta(
                label="MDX-Net Model: Pair",
                display="MDX-Net — Pair",
                arch=MDX_ARCH_TYPE,
                files={
                    "model.ckpt": "http://x/model.ckpt",
                    "config.yaml": "http://x/config.yaml",
                },
                checkpoint="model.ckpt",
            )
        }
        index = _basename_index(meta, MDX_ARCH_TYPE)
        self.assertEqual(set(index), {"model"})
        self.assertNotIn("config", index)

    def test_demucs_bag_member_stem_is_not_an_index_key(self) -> None:
        from bundled.constants import DEMUCS_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.catalogue_coordinator import _basename_index

        meta = {
            "Demucs v4: htdemucs_ft": EntryMeta(
                label="Demucs v4: htdemucs_ft",
                display="v4 — htdemucs_ft",
                arch=DEMUCS_ARCH_TYPE,
                files={
                    "f7e0c4bc-ba3fe64a.th": "http://x/f7e0c4bc-ba3fe64a.th",
                    "d12395a8-e57c48e6.th": "http://x/d12395a8-e57c48e6.th",
                    "htdemucs_ft.yaml": "http://x/htdemucs_ft.yaml",
                },
                checkpoint="f7e0c4bc-ba3fe64a.th",
            )
        }
        index = _basename_index(meta, DEMUCS_ARCH_TYPE)
        self.assertEqual(set(index), {"htdemucs_ft"})
        self.assertNotIn("f7e0c4bc-ba3fe64a", index)
        self.assertNotIn("d12395a8-e57c48e6", index)


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
