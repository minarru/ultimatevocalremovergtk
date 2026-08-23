"""Locks for the model-identity cutover. Characterization tests in this
module describe *current* contracts and must pass on the first commit.
Target-behavior tests are added in later tasks in this same file."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from bundled.constants import CHOOSE_MODEL, NO_MODEL
from core.catalogue_coordinator import CatalogueCoordinator
from core.catalogue_types import SourceId
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
from core.remote_catalog_cache import RemoteJsonSource


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


def _coordinator_for_payload(payload: dict[str, Any]) -> CatalogueCoordinator:
    sources = {
        SourceId.UPSTREAM: RemoteJsonSource(
            source_id=SourceId.UPSTREAM, local_loader=lambda: payload
        )
    }
    for source_id in (
        SourceId.POLITREES,
        SourceId.EXTRAS,
        SourceId.MVSEPLESS,
    ):
        sources[source_id] = RemoteJsonSource(
            source_id=source_id, enabled=lambda: False
        )
    return CatalogueCoordinator(sources=sources)


def _snapshot(
    *,
    vr: Any = None,
    mdx: Any = None,
    demucs: Any = None,
    apollo: Any = None,
    meta: Any = None,
    display_vr: Any = None,
    display_mdx: Any = None,
    display_demucs: Any = None,
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
        display_index_vr=dict(display_vr or {}),
        display_index_mdx=dict(display_mdx or {}),
        display_index_demucs=dict(display_demucs or {}),
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

    def test_rejects_basename_with_edge_whitespace(self) -> None:
        for value in ("vr: model", "vr:model "):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_stored_model_id(value)


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

    def test_one_malformed_catalogue_row_does_not_empty_the_index(self) -> None:
        """Catalogue content is fetched from four network sources.

        A single illegal artifact name used to raise out of the whole build,
        emptying every model picker at once.
        """
        from bundled.constants import VR_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.model_inventory import build_identity_index

        good_files = {"good.pth": "http://example.invalid/good.pth"}
        bad_files = {"../escape.pth": "http://example.invalid/escape.pth"}
        entries = {
            "VR: Good": EntryMeta(
                label="VR: Good", display="Good", arch=VR_ARCH_TYPE, files=good_files,
            ),
            "VR: Bad": EntryMeta(
                label="VR: Bad", display="Bad", arch=VR_ARCH_TYPE, files=bad_files,
            ),
        }
        snapshot = _snapshot(
            vr={"VR: Good": good_files, "VR: Bad": bad_files},
            meta={"vr": entries},
        )
        index = build_identity_index(_empty_repo(), snapshot=snapshot)
        ids = [record.id for record in index.records()]
        self.assertIn("vr:good", ids)
        self.assertNotIn("vr:escape", ids)

    def test_one_unrepresentable_installed_filename_does_not_empty_the_index(self) -> None:
        from core.model_inventory import build_identity_index

        repo = _empty_repo(
            _model_artifact_files=lambda family: (
                ["~stray.pth", "real.pth"] if family == "vr" else []
            ),
        )
        index = build_identity_index(repo, snapshot=_snapshot())
        ids = [record.id for record in index.records()]
        self.assertIn("vr:real", ids)
        self.assertNotIn("vr:~stray", ids)

    def test_untargetable_and_nested_installed_filenames_are_omitted(self) -> None:
        from core.model_inventory import build_identity_index

        repo = _empty_repo(
            _model_artifact_files=lambda family: (
                [
                    ".pth", "bad:name.pth", "model .pth",
                    "nested/stray.pth", "valid.pth",
                ]
                if family == "vr"
                else []
            ),
        )

        index = build_identity_index(repo, snapshot=_snapshot())

        self.assertEqual(
            [record.id for record in index.records()],
            ["vr:valid"],
        )
        for record in index.records():
            self.assertEqual(index.lookup(record.id), record)

    def test_malformed_installed_demucs_bag_does_not_empty_the_index(self) -> None:
        import tempfile

        from core.model_inventory import build_identity_index

        cases = (
            ("illegal entrypoint", ["../bad.yaml"], []),
            ("illegal supporting artifact", ["bad.yaml", "../sig-hash.th"], ["sig"]),
        )
        for label, demucs_files, signatures in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                yaml_path = f"{directory}/bag.yaml"
                with open(yaml_path, "w", encoding="utf-8") as handle:
                    json.dump({"models": signatures}, handle)
                repo = _empty_repo(
                    _model_artifact_files=lambda family, rows=demucs_files: (
                        ["good.pth"]
                        if family == "vr"
                        else rows
                        if family == "demucs"
                        else []
                    ),
                    _model_artifact_path=lambda _family, _name: yaml_path,
                )

                index = build_identity_index(
                    repo,
                    snapshot=_snapshot(),
                    bundled_demucs_specs={},
                    registered_demucs={},
                )

                self.assertEqual(
                    [record.id for record in index.records()], ["vr:good"]
                )

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

    def test_missing_trusted_mdx_yaml_keeps_exact_supporting_evidence(self) -> None:
        from core import paths
        from core.model_inventory import build_identity_index

        with tempfile.TemporaryDirectory() as directory:
            checkpoint_path = os.path.join(directory, "recoverable.ckpt")
            hash_directory = os.path.join(directory, "model_data")
            os.makedirs(hash_directory)
            with open(os.path.join(hash_directory, "trusted.json"), "w", encoding="utf-8") as handle:
                json.dump({"config_yaml": "exact-recovery.yaml"}, handle)
            repo = _empty_repo(
                _model_artifact_files=lambda family: (
                    ["recoverable.ckpt"] if family == "mdx" else []
                ),
                _model_artifact_path=lambda _family, _name: checkpoint_path,
                model_hash_table={checkpoint_path: "trusted"},
            )

            with patch.object(paths, "MDX_HASH_DIR", hash_directory):
                record = build_identity_index(repo, snapshot=_snapshot()).lookup(
                    "mdx:recoverable"
                )

        self.assertFalse(record.identity_complete)
        self.assertIsNone(record.mdx)
        self.assertEqual(
            record.artifacts.supporting_filenames, ("exact-recovery.yaml",)
        )

    def test_incomplete_catalogue_match_is_enriched_from_trusted_install(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE
        from core import paths
        from core.catalog_sources import EntryMeta
        from core.model_inventory import build_identity_index

        with tempfile.TemporaryDirectory() as directory:
            checkpoint_path = os.path.join(directory, "catalogued.ckpt")
            hash_directory = os.path.join(directory, "model_data")
            os.makedirs(hash_directory)
            with open(os.path.join(hash_directory, "trusted.json"), "w", encoding="utf-8") as handle:
                json.dump({"config_yaml": "trusted-local.yaml"}, handle)
            selection = "MDX-Net Model: Catalogued"
            files = {"catalogued.ckpt": "http://example.invalid/catalogued.ckpt"}
            entry = EntryMeta(
                label=selection,
                display="Catalogued display",
                arch=MDX_ARCH_TYPE,
                files=files,
                checkpoint="catalogued.ckpt",
            )
            repo = _empty_repo(
                _model_artifact_files=lambda family: (
                    ["catalogued.ckpt"] if family == "mdx" else []
                ),
                _model_artifact_path=lambda _family, _name: checkpoint_path,
                model_hash_table={checkpoint_path: "trusted"},
            )
            snapshot = _snapshot(
                mdx={selection: files}, meta={"mdx": {selection: entry}}
            )

            with patch.object(paths, "MDX_HASH_DIR", hash_directory):
                record = build_identity_index(repo, snapshot=snapshot).lookup(
                    "mdx:catalogued"
                )

        self.assertTrue(record.installed)
        self.assertFalse(record.identity_complete)
        self.assertEqual(record.display, "MDX-Net — Catalogued")
        self.assertEqual(
            record.artifacts.supporting_filenames, ("trusted-local.yaml",)
        )


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
    """Replayable manifests are schema 3; bench remains non-replayable v1."""

    def test_separate_manifest_schema_is_3(self) -> None:
        from cli.execution import MANIFEST_SCHEMA_VERSION

        self.assertEqual(MANIFEST_SCHEMA_VERSION, 3)

    def test_bench_manifest_schema_stays_1(self) -> None:
        import inspect
        from cli import bench

        source = inspect.getsource(bench.cmd_bench)
        self.assertIn('"schema_version": 1', source)


class SentinelLockTests(unittest.TestCase):
    def test_choose_and_no_model_strings_are_stable(self) -> None:
        self.assertEqual(CHOOSE_MODEL, "Choose Model")
        self.assertEqual(NO_MODEL, "No Model Selected")


class IdentityIndexCostTests(unittest.TestCase):
    """The index is built once per repository state, not once per service."""

    def test_mdx_family_is_listed_once_per_build(self) -> None:
        from core.model_inventory import build_identity_index

        calls: list[str] = []

        def artifact_files(family: str) -> list[str]:
            calls.append(family)
            if family != "mdx":
                return []
            return [
                "a.ckpt", "a.yaml", "b.ckpt", "b.yaml", "c.ckpt", "c.yaml",
            ]

        repo = _empty_repo(
            _model_artifact_files=artifact_files,
            _model_artifact_path=lambda family, name: f"/nowhere/{family}/{name}",
        )
        index = build_identity_index(repo, snapshot=_snapshot())

        self.assertEqual(
            sorted(record.id for record in index.records() if record.family == "mdx"),
            ["mdx:a", "mdx:b", "mdx:c"],
        )
        self.assertEqual(
            calls.count("mdx"), 1,
            "the MDX artifact directory must be listed once, not once per checkpoint",
        )

    def test_two_services_over_one_repository_share_the_built_index(self) -> None:
        from unittest.mock import patch

        from core.model_identity import ModelIdentityService
        from core.model_repository import ModelRepository

        builds: list[int] = []
        repo = ModelRepository()

        from core import model_inventory

        real_build = model_inventory.build_identity_index

        def counting_build(*args: Any, **kwargs: Any):
            builds.append(1)
            return real_build(*args, **kwargs)

        with patch.object(model_inventory, "build_identity_index", counting_build):
            first = ModelIdentityService(repo).index
            second = ModelIdentityService(repo).index

        self.assertIs(first, second)
        self.assertEqual(len(builds), 1)

        with patch.object(model_inventory, "build_identity_index", counting_build):
            repo.invalidate_models()
            third = ModelIdentityService(repo).index

        self.assertIsNot(third, first)
        self.assertEqual(len(builds), 2)


class DisplayEnrichmentTests(unittest.TestCase):
    """`ModelRecord.display` is the authoritative friendly label."""

    def _repo(
        self,
        *,
        mdx: Any = (),
        vr: Any = (),
        demucs: Any = (),
        apollo: Any = (),
        **overrides: Any,
    ):
        files = {
            "mdx": list(mdx),
            "vr": list(vr),
            "demucs": list(demucs),
            "apollo": list(apollo),
        }
        return _empty_repo(
            _model_artifact_files=lambda family: files.get(family, []),
            **overrides,
        )

    def _records(self, repo: Any, snapshot: Any) -> dict[str, ModelRecord]:
        from core.model_inventory import build_identity_index

        index = build_identity_index(
            repo,
            snapshot=snapshot,
            bundled_demucs_specs={},
            registered_demucs={},
        )
        return {record.id: record for record in index.records()}

    def test_catalogue_display_wins_over_conflicting_mapper(self) -> None:
        repo, snapshot = _fake_mdx_pair()
        repo.mdx_name_select_MAPPER = {"model.ckpt": "Mapper Label"}
        records = self._records(repo, snapshot)
        self.assertEqual(records["mdx:model"].display, "MDX-Net — Pair")

    def test_registry_override_and_exact_source_precedence_use_shared_projector(self) -> None:
        from core.model_inventory import build_identity_index

        repo, snapshot = _fake_mdx_pair()
        repo._model_artifact_files = lambda family: (
            ["model.ckpt", "config.yaml"] if family == "mdx" else []
        )
        repo.mdx_name_select_MAPPER = {"model.ckpt": "Mapper title"}
        with patch(
            "core.model_registry.ModelRegistryService.presentation",
            return_value={
                "catalogue_label": "Persisted title",
                "display_override": "Trusted title",
            },
        ):
            record = build_identity_index(
                repo,
                snapshot=snapshot,
                bundled_demucs_specs={},
                registered_demucs={},
            ).lookup("mdx:model")

        self.assertEqual(record.display, "Trusted title")
        self.assertEqual(record.id, "mdx:model")
        self.assertEqual(record.backend_name, "model")
        self.assertEqual(record.artifacts.primary_filename, "model.ckpt")

    def test_live_then_persisted_then_mirror_source_precedence(self) -> None:
        from core.model_inventory import build_identity_index

        repo, snapshot = _fake_mdx_pair()
        repo._model_artifact_files = lambda family: (
            ["model.ckpt", "config.yaml"] if family == "mdx" else []
        )
        repo.mdx_name_select_MAPPER = {"model.ckpt": "Mapper title"}
        with patch(
            "core.model_registry.ModelRegistryService.presentation",
            return_value={"catalogue_label": "Persisted title"},
        ):
            live = build_identity_index(
                repo,
                snapshot=snapshot,
                bundled_demucs_specs={},
                registered_demucs={},
            ).lookup("mdx:model")
        self.assertEqual(live.display, "MDX-Net — Pair")

        installed_only = self._repo(
            mdx=["custom.onnx"],
            mdx_name_select_MAPPER={"custom.onnx": "BS Roformer Vocals by viperx"},
        )
        with patch(
            "core.model_registry.ModelRegistryService.presentation",
            return_value={"catalogue_label": "MDX23C Model: Persisted"},
        ):
            persisted = self._records(installed_only, _snapshot())["mdx:custom"]
        self.assertEqual(persisted.display, "MDX23C — Persisted")

        with patch(
            "core.model_registry.ModelRegistryService.presentation", return_value={}
        ):
            mirrored = self._records(installed_only, _snapshot())["mdx:custom"]
        self.assertEqual(
            mirrored.display, "BandSplit Roformer — Vocals · ViperX"
        )

    def test_ambiguous_exact_catalogue_owners_follow_non_live_precedence(self) -> None:
        first = "MDX-Net Model: Live Alpha"
        second = "MDX-Net Model: Live Beta"
        coordinator = _coordinator_for_payload({
            "vr_download_list": {},
            "mdx_download_list": {
                first: "shared.onnx",
                second: "shared.onnx",
            },
            "demucs_download_list": {},
        })
        self.addCleanup(coordinator.close)
        snapshot = coordinator.ensure(allow_network=False)
        self.assertEqual(tuple(snapshot.mdx), (first,))
        self.assertEqual(
            set(snapshot.meta_by_family["mdx"]),
            {first, second},
        )
        cases = (
            (
                {"catalogue_label": "MDX23C Model: Persisted Choice"},
                {"shared.onnx": "BS Roformer Vocals by viperx"},
                "MDX23C — Persisted Choice",
            ),
            (
                {},
                {"shared.onnx": "BS Roformer Vocals by viperx"},
                "BandSplit Roformer — Vocals · ViperX",
            ),
            ({}, {}, "shared"),
        )

        for persisted, mapper, expected in cases:
            with self.subTest(expected=expected), patch(
                "core.model_registry.ModelRegistryService.presentation",
                return_value=persisted,
            ):
                record = self._records(
                    self._repo(
                        mdx=["shared.onnx"],
                        mdx_name_select_MAPPER=mapper,
                    ),
                    snapshot,
                )["mdx:shared"]

            self.assertEqual(record.display, expected)
            self.assertNotIn(
                record.display,
                ("MDX-Net — Live Alpha", "MDX-Net — Live Beta"),
            )

    def test_inventory_projection_never_persists_presentation(self) -> None:
        from core.model_inventory import build_identity_index

        repo = self._repo(mdx=["custom.onnx"])
        with patch(
            "core.model_registry.ModelRegistryService.remember_presentation",
            side_effect=AssertionError("inventory write"),
        ):
            record = build_identity_index(
                repo,
                snapshot=_snapshot(),
                bundled_demucs_specs={},
                registered_demucs={},
            ).lookup("mdx:custom")
        self.assertEqual(record.display, "custom")

    def test_former_vip_installed_model_uses_public_catalogue_display(self) -> None:
        payload = {
            "mdx_download_list": {},
            "mdx_download_vip_list": {
                "MDX-Net Model VIP: UVR-MDX-NET_Main_427": (
                    "UVR-MDX-NET_Main_427.onnx"
                )
            },
            "vr_download_list": {},
            "demucs_download_list": {},
        }
        coordinator = _coordinator_for_payload(payload)
        self.addCleanup(coordinator.close)
        snapshot = coordinator.ensure(allow_network=False)
        repo = self._repo(mdx=["UVR-MDX-NET_Main_427.onnx"])

        record = self._records(repo, snapshot)["mdx:UVR-MDX-NET_Main_427"]

        self.assertEqual(record.display, "MDX-Net — UVR Main 427")
        self.assertEqual(record.backend_name, "UVR-MDX-NET_Main_427")

    def test_catalogue_basename_echo_falls_through_to_mapper(self) -> None:
        repo = self._repo(
            mdx=["model.ckpt"],
            mdx_name_select_MAPPER={"model.ckpt": "Friendly Mapper"},
        )
        snapshot = _snapshot(display_mdx={"model": "model"})
        records = self._records(repo, snapshot)
        self.assertEqual(records["mdx:model"].display, "Friendly Mapper")

    def test_installed_only_mdx_gets_exact_mapper_display(self) -> None:
        repo = self._repo(
            mdx=["Kim_Vocal_1.onnx"],
            mdx_name_select_MAPPER={"Kim_Vocal_1.onnx": "Kim Vocal 1"},
        )
        records = self._records(repo, _snapshot())
        self.assertEqual(records["mdx:Kim_Vocal_1"].display, "Kim Vocal 1")

    def test_installed_only_demucs_gets_exact_mapper_display(self) -> None:
        repo = self._repo(
            demucs=["tasnet.th"],
            demucs_name_select_MAPPER={"tasnet.th": "v1 | tasnet"},
        )
        records = self._records(repo, _snapshot())
        self.assertEqual(records["demucs:tasnet"].display, "v1 — TasNet")

    def test_vr_uses_catalogue_index_and_has_no_mapper_fallback(self) -> None:
        repo = self._repo(
            vr=["1_HP-UVR.pth", "9_HP2-UVR.pth"],
            mdx_name_select_MAPPER={"9_HP2-UVR.pth": "Must Not Apply"},
        )
        snapshot = _snapshot(display_vr={"1_HP-UVR": "VR Arch — 1 HP"})
        records = self._records(repo, snapshot)
        self.assertEqual(records["vr:1_HP-UVR"].display, "HP 1")
        self.assertEqual(records["vr:9_HP2-UVR"].display, "HP2 9")

    def test_apollo_keeps_raw_basename_without_catalogue_display(self) -> None:
        repo = self._repo(apollo=["custom_apollo.ckpt"])
        records = self._records(repo, _snapshot())
        self.assertEqual(records["apollo:custom_apollo"].display, "custom_apollo")

    def test_unknown_custom_model_retains_raw_basename(self) -> None:
        repo = self._repo(mdx=["my_private_model.onnx"])
        records = self._records(repo, _snapshot())
        self.assertEqual(records["mdx:my_private_model"].display, "my_private_model")

    def test_substring_only_mapper_candidate_is_ignored(self) -> None:
        repo = self._repo(
            mdx=["model.onnx"],
            mdx_name_select_MAPPER={"model_v2.ckpt": "Wrong Model"},
        )
        records = self._records(repo, _snapshot())
        self.assertEqual(records["mdx:model"].display, "model")

    def test_local_mapper_overlay_precedence_survives_enrichment(self) -> None:
        repo = self._repo(
            mdx=["model.onnx"],
            mdx_name_select_MAPPER={"model.onnx": "Overlay Wins"},
        )
        records = self._records(repo, _snapshot())
        self.assertEqual(records["mdx:model"].display, "Overlay Wins")

    def test_catalogue_index_outranks_demucs_mapper(self) -> None:
        repo = self._repo(
            demucs=["registered.th"],
            demucs_name_select_MAPPER={"registered.th": "Mapper Label"},
        )
        records = self._records(
            repo, _snapshot(display_demucs={"registered": "Catalogue Label"})
        )
        self.assertEqual(records["demucs:registered"].display, "Catalogue Label")

    def test_table_driven_exact_mappings_agree_and_unknowns_stay_raw(self) -> None:
        cases = (
            ("Kim_Vocal_1.onnx", "Kim Vocal 1", "Kim Vocal 1"),
            ("Kim_Vocal_2.onnx", "Kim Vocal 2", "Kim Vocal 2"),
            (
                "UVR-MDX-NET-Inst_HQ_3.onnx",
                "UVR-MDX-NET Inst HQ 3",
                "UVR-MDX-NET Instrumental High Quality 3",
            ),
            ("totally_unknown_model.onnx", None, "totally_unknown_model"),
        )
        mapper = {name: label for name, label, _ in cases if label}
        repo = self._repo(
            mdx=[name for name, _, _ in cases],
            mdx_name_select_MAPPER=mapper,
        )
        records = self._records(repo, _snapshot())
        for filename, _, expected in cases:
            basename = os.path.splitext(filename)[0]
            with self.subTest(model=basename):
                self.assertEqual(records[f"mdx:{basename}"].display, expected)

    def test_enrichment_changes_only_display(self) -> None:
        from core.model_inventory import _enrich_record_displays

        repo = self._repo(mdx_name_select_MAPPER={"model.onnx": "Friendly"})
        original = ModelRecord(
            id="mdx:model",
            family="mdx",
            basename="model",
            display="model",
            backend_name="model",
            artifacts=ModelArtifacts("model.onnx", ()),
            installed=True,
        )
        enriched = _enrich_record_displays(repo, [original], _snapshot())[0]

        self.assertEqual(enriched.display, "Friendly")
        self.assertEqual(enriched.id, original.id)
        self.assertEqual(enriched.family, original.family)
        self.assertEqual(enriched.basename, original.basename)
        self.assertEqual(enriched.backend_name, original.backend_name)
        self.assertEqual(enriched.artifacts, original.artifacts)
        self.assertEqual(enriched.demucs, original.demucs)
        self.assertEqual(enriched.mdx, original.mdx)
        self.assertEqual(enriched.installed, original.installed)
        self.assertEqual(enriched.identity_complete, original.identity_complete)
        self.assertEqual(enriched.identity_error, original.identity_error)
        self.assertEqual(enriched.catalogue_entry, original.catalogue_entry)

    def test_enrichment_returns_same_object_when_unchanged(self) -> None:
        from core.model_inventory import _enrich_record_displays

        original = ModelRecord(
            id="mdx:model",
            family="mdx",
            basename="model",
            display="model",
            backend_name="model",
            artifacts=ModelArtifacts("model.onnx", ()),
            installed=True,
        )
        result = _enrich_record_displays(self._repo(), [original], _snapshot())
        self.assertIs(result[0], original)


class PresentationBackfillTests(unittest.TestCase):
    def test_backfill_persists_installed_exact_catalogue_evidence(self) -> None:
        from core.model_inventory import backfill_installed_presentations
        from core.model_registry import ModelRegistryService

        repo, snapshot = _fake_mdx_pair()
        repo._model_artifact_files = lambda family: (
            ["model.ckpt", "config.yaml"] if family == "mdx" else []
        )
        snapshot.entry_sources = {"mdx": {"MDX-Net Model: Pair": "upstream"}}
        with tempfile.TemporaryDirectory() as directory, patch(
            "core.model_registry.paths.REGISTERED_MODEL_INDEX",
            os.path.join(directory, "registered.json"),
        ):
            ModelRegistryService.remember_presentation(
                "mdx:model", display_override="Trusted title"
            )
            changed = backfill_installed_presentations(repo, snapshot)
            evidence = ModelRegistryService.presentation("mdx:model")

        self.assertTrue(changed)
        self.assertEqual(evidence["catalogue_label"], "MDX-Net Model: Pair")
        self.assertEqual(evidence["catalogue_source"], "upstream")
        self.assertEqual(evidence["display_override"], "Trusted title")

    def test_mapper_refresh_can_backfill_without_a_catalogue_snapshot(self) -> None:
        from core.model_inventory import backfill_installed_presentations
        from core.model_registry import ModelRegistryService

        repo = _empty_repo(
            _model_artifact_files=lambda family: (
                ["mirror.onnx"] if family == "mdx" else []
            ),
            mdx_name_select_MAPPER={"mirror.onnx": "MDX-Net Model: Mirror"},
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "core.model_registry.paths.REGISTERED_MODEL_INDEX",
            os.path.join(directory, "registered.json"),
        ):
            changed = backfill_installed_presentations(repo, None)
            evidence = ModelRegistryService.presentation("mdx:mirror")

        self.assertTrue(changed)
        self.assertEqual(evidence["catalogue_label"], "MDX-Net Model: Mirror")
        self.assertEqual(evidence["catalogue_source"], "model_name_mapper")

    def test_prededupe_exact_catalogue_evidence_is_backfilled(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.model_inventory import backfill_installed_presentations
        from core.model_registry import ModelRegistryService

        selection = "MDX-Net Model: Exact Alias"
        entry = EntryMeta(
            label=selection,
            display="Exact Alias",
            arch=MDX_ARCH_TYPE,
            files={"alias.onnx": "https://example.invalid/alias.onnx"},
            checkpoint="alias.onnx",
        )
        snapshot = _snapshot(meta={"mdx": {selection: entry}})
        snapshot.entry_sources = {"mdx": {selection: "politrees"}}
        repo = _empty_repo(
            _model_artifact_files=lambda family: (
                ["alias.onnx"] if family == "mdx" else []
            ),
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "core.model_registry.paths.REGISTERED_MODEL_INDEX",
            os.path.join(directory, "registered.json"),
        ):
            changed = backfill_installed_presentations(repo, snapshot)
            evidence = ModelRegistryService.presentation("mdx:alias")

        self.assertTrue(changed)
        self.assertEqual(evidence["catalogue_label"], selection)
        self.assertEqual(evidence["catalogue_source"], "politrees")
