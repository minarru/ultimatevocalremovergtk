from __future__ import annotations

import argparse
import io
import json
import signal
import threading
import unittest
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from cli.discovery import (
    _print_detail, cmd_devices_list, cmd_models_download, cmd_profile_list,
)
from cli.main import main
from core.model_identity import (
    DemucsSpec,
    IdentityIndex,
    MdxSpec,
    ModelArtifacts,
    ModelIdentityService,
    ModelRecord,
    resolve_model_record,
)
from core.model_catalogue import CatalogEntryId
from core.model_registry import ModelRegistryService


class ModelIdTests(unittest.TestCase):
    def test_qualified_id_is_stable(self) -> None:
        records = [ModelRecord(
            id='mdx:model_a',
            family='mdx',
            basename='model_a',
            display='Model A',
            backend_name='model_a',
            artifacts=ModelArtifacts('model_a.ckpt'),
            installed=True,
        )]
        result = resolve_model_record("mdx:model_a", records)
        self.assertEqual(result.id, "mdx:model_a")

    def test_apollo_id_is_supported(self) -> None:
        record = ModelRecord(
            id='apollo:restore',
            family='apollo',
            basename='restore',
            display='Restore',
            backend_name='restore.ckpt',
            artifacts=ModelArtifacts('restore.ckpt'),
            installed=True,
        )
        self.assertEqual(resolve_model_record("restore.ckpt", [record]).id, "apollo:restore")

    def test_family_constraint_rejects_cross_family_match(self) -> None:
        service = ModelIdentityService(object())
        records = (
            ModelRecord(
                id='mdx:shared',
                family='mdx',
                basename='shared',
                display='Shared',
                backend_name='shared',
                artifacts=ModelArtifacts('shared.ckpt'),
                installed=True,
            ),
            ModelRecord(
                id='vr:other',
                family='vr',
                basename='other',
                display='Other',
                backend_name='other',
                artifacts=ModelArtifacts('other.ckpt'),
                installed=True,
            ),
        )
        with patch.object(service, "records", return_value=records):
            self.assertEqual(service.resolve("shared", family="mdx").id, "mdx:shared")
            with self.assertRaisesRegex(ValueError, "required family"):
                service.resolve("mdx:shared", family="vr")

    def test_family_does_not_prefix_legacy_arch_member_tag(self) -> None:
        """Leftover ``Arch: Display`` tags still resolve; family= must not make ``mdx:MDX-Net:…``."""
        from core.model_identity import canonical_member_tag

        record = ModelRecord(
            id='mdx:UVR-MDX-NET-Inst_HQ_4',
            family='mdx',
            basename='UVR-MDX-NET-Inst_HQ_4',
            display='MDX-Net — UVR-MDX-NET Inst HQ 4',
            backend_name='UVR-MDX-NET-Inst_HQ_4',
            artifacts=ModelArtifacts('UVR-MDX-NET-Inst_HQ_4.ckpt'),
            installed=True,
        )
        tag = canonical_member_tag(record)
        self.assertEqual(tag, "MDX-Net: MDX-Net — UVR-MDX-NET Inst HQ 4")
        service = ModelIdentityService(object())
        with patch.object(service, "records", return_value=(record,)):
            self.assertEqual(
                service.resolve(tag, family="mdx", fuzzy=False).id, record.id
            )

    def test_allowed_families_reject_ineligible_identity(self) -> None:
        service = ModelIdentityService(object())
        records = (
            ModelRecord(
                id='apollo:restore',
                family='apollo',
                basename='restore',
                display='Restore',
                backend_name='restore',
                artifacts=ModelArtifacts('restore.ckpt'),
                installed=True,
            ),
        )
        with patch.object(service, "records", return_value=records):
            with self.assertRaisesRegex(ValueError, "not eligible"):
                service.resolve("apollo:restore", allowed_families={"mdx", "vr"})


class AdministrationCoreTests(unittest.TestCase):
    def test_catalogue_entry_ids_round_trip_without_becoming_model_ids(self) -> None:
        entry = CatalogEntryId("mdx", "MDX Model: A/B")
        self.assertEqual(CatalogEntryId.parse(str(entry)), entry)
        self.assertTrue(str(entry).startswith("catalog:mdx:"))

    def test_family_metadata_validation(self) -> None:
        vr = ModelRegistryService.validate_payload(
            "vr", {"primary_stem": "Vocals", "vr_model_param": "4band_v3"}
        )
        self.assertEqual(vr["primary_stem"], "Vocals")
        with self.assertRaisesRegex(ValueError, "config_yaml"):
            ModelRegistryService.validate_payload("apollo", {"primary_stem": "Restored"})

    def test_ambiguous_unqualified_name_lists_ids(self) -> None:
        records = [
            ModelRecord(
                id='mdx:vocals',
                family='mdx',
                basename='vocals',
                display='Vocals',
                backend_name='vocals',
                artifacts=ModelArtifacts('vocals.ckpt'),
                installed=True,
            ),
            ModelRecord(
                id='vr:vocals',
                family='vr',
                basename='vocals',
                display='Vocals',
                backend_name='vocals',
                artifacts=ModelArtifacts('vocals.ckpt'),
                installed=True,
            ),
        ]
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            resolve_model_record("vocals", records)

    def test_registered_hash_index_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as root, patch(
            "core.model_registry.paths.REGISTERED_MODEL_INDEX",
            os.path.join(root, "registered.json"),
        ):
            ModelRegistryService.remember_registered("abc", "mdx:model")
            self.assertEqual(ModelRegistryService.registered_id("abc"), "mdx:model")
            ModelRegistryService.forget_registered("abc")
            self.assertIsNone(ModelRegistryService.registered_id("abc"))

    def test_registered_hash_index_updates_are_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as root, patch(
            "core.model_registry.paths.REGISTERED_MODEL_INDEX",
            os.path.join(root, "registered.json"),
        ):
            barrier = threading.Barrier(8)

            def remember(index: int) -> None:
                barrier.wait()
                ModelRegistryService.remember_registered(
                    f"hash-{index}", f"mdx:model-{index}"
                )

            workers = [threading.Thread(target=remember, args=(index,)) for index in range(8)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            for index in range(8):
                self.assertEqual(
                    ModelRegistryService.registered_id(f"hash-{index}"),
                    f"mdx:model-{index}",
                )

    def test_registration_hashes_only_the_submitted_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            checkpoint = os.path.join(root, "new.onnx")
            config = os.path.join(root, "model.json")
            open(checkpoint, "wb").close()
            with open(config, "w", encoding="utf-8") as handle:
                json.dump({"primary_stem": "Vocals"}, handle)
            out = io.StringIO()
            with patch(
                "core.mdx_c_registry.compute_checkpoint_hash", return_value="known-hash"
            ) as fingerprint, patch.object(
                ModelRegistryService, "registered_id", return_value="mdx:existing"
            ), redirect_stdout(out):
                code = main([
                    "models", "register", checkpoint, "--family", "mdx",
                    "--config", config, "--report", "json",
                ])
            self.assertEqual(code, 0)
            fingerprint.assert_called_once_with(os.path.abspath(checkpoint))
            self.assertEqual(
                json.loads(out.getvalue())["items"][0]["id"], "mdx:existing"
            )

    def test_cached_politrees_access_never_calls_network(self) -> None:
        from core import politrees_catalog

        politrees_catalog.clear_politrees_cache()
        with patch.object(
            politrees_catalog, "_politrees_cache_path", return_value="/tmp/does-not-exist-uvr-politrees.json"
        ), patch.object(politrees_catalog, "_urlopen") as network:
            self.assertIsNone(
                politrees_catalog.load_politrees_links(allow_network=False)
            )
        network.assert_not_called()

    def test_catalogue_offline_is_removed(self) -> None:
        import importlib.util

        self.assertIsNone(importlib.util.find_spec("core.offline"))

    def test_legacy_ensemble_tag_resolves_to_canonical_id(self) -> None:
        records = [ModelRecord(
            id='mdx:model_a',
            family='mdx',
            basename='model_a',
            display='Model A',
            backend_name='model_a',
            artifacts=ModelArtifacts('model_a.ckpt'),
            installed=True,
        )]
        result = resolve_model_record("MDX-Net: Model A", records)
        self.assertEqual(result.id, "mdx:model_a")


class DiscoveryTests(unittest.TestCase):
    def args(self) -> argparse.Namespace:
        return argparse.Namespace(report="json", quiet=False, verbose=False)

    def test_models_show_configures_installed_demucs_canonical_id(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(
            os.environ,
            {"UVR_DISABLE_POLITREES": "1", "UVR_DISABLE_MVSEPLESS": "1"},
            clear=False,
        ), redirect_stdout(out), redirect_stderr(err):
            code = main([
                "models", "show", "demucs:hdemucs_mmi", "--report", "json",
            ])

        self.assertEqual(code, 0, err.getvalue())
        item = json.loads(out.getvalue())["items"][0]
        self.assertEqual(item["id"], "demucs:hdemucs_mmi")
        self.assertTrue(item["configured"])
        self.assertEqual(item["architectural_facts"]["demucs_stem_count"], 4)

    def test_devices_have_auto_selection(self) -> None:
        out = io.StringIO()
        with patch("core.gpu.list_gpu_devices", return_value=[("0", "GPU")]), redirect_stdout(out):
            self.assertEqual(cmd_devices_list(self.args()), 0)
        items = json.loads(out.getvalue())["items"]
        self.assertTrue(any(item["selected_by_auto"] for item in items))

    def test_profile_list_contains_virtual_profiles(self) -> None:
        out = io.StringIO()
        with patch("cli.discovery.list_profiles", return_value=["fast"]), redirect_stdout(out):
            self.assertEqual(cmd_profile_list(self.args()), 0)
        names = [item["name"] for item in json.loads(out.getvalue())["items"]]
        self.assertEqual(names, ["defaults", "gui", "fast"])

    def test_settings_human_output_is_scalar_and_provenance_aware(self) -> None:
        out = io.StringIO()
        with patch.dict(os.environ, {"UVR_AUTOCAST": "0"}, clear=False), redirect_stdout(out):
            self.assertEqual(main(["settings", "show"]), 0)
        rows = out.getvalue().splitlines()
        autocast = next(row for row in rows if row.startswith("process.autocast\t"))
        self.assertEqual(autocast, "process.autocast\tFalse\tenvironment")
        self.assertFalse(any("ProcessMethod." in row or "{'" in row for row in rows))
        self.assertTrue(all(len(row.split("\t")) == 3 for row in rows))

    def test_human_inspection_details_include_labels_and_stable_json(self) -> None:
        args = argparse.Namespace(report="human")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(_print_detail(args, {
                "id": "mdx:model", "facts": {"stems": ["Vocals", "Other"]},
            }), 0)
        self.assertEqual(out.getvalue().splitlines(), [
            "id\tmdx:model",
            'facts\t{"stems":["Vocals","Other"]}',
        ])

    def test_download_second_interrupt_keeps_failed_unit_in_report(self) -> None:
        handlers: dict[int, object] = {}
        record = SimpleNamespace(
            id="catalog:mdx:test", family="mdx", supported=True
        )
        manager = Mock()

        def install(signum: int, handler: object) -> None:
            if callable(handler):
                handlers[signum] = handler

        def download(*_args: object, **_kwargs: object) -> str:
            handler = handlers[signal.SIGINT]
            assert callable(handler)
            handler(signal.SIGINT, None)
            handler(signal.SIGINT, None)
            return "complete"

        manager.download.side_effect = download
        service = Mock()
        service.manager = manager
        service.refresh.return_value = True
        service.resolve.return_value = record
        service.jobs.return_value = ((record, (("url", "/tmp/model.onnx"),)),)
        args = argparse.Namespace(
            entries=[record.id], offline=False, report="json", quiet=True,
            verbose=False, job_id="download-test",
        )
        out, err = io.StringIO(), io.StringIO()
        with patch(
            "core.model_catalogue.ModelCatalogueService", return_value=service
        ), patch("core.model_repository.ModelRepository"), patch(
            "signal.signal", side_effect=install
        ), patch(
            "signal.getsignal", return_value=object()
        ), redirect_stdout(out), redirect_stderr(err):
            code = cmd_models_download(args)
        payload = json.loads(out.getvalue())
        self.assertEqual(code, 130)
        self.assertTrue(payload["stopped"])
        self.assertEqual(payload["inputs"][0]["status"], "failed")
        self.assertEqual(payload["inputs"][0]["error"], "interrupted")


class ModelsListInstalledDefaultTests(unittest.TestCase):
    def test_parser_has_all_known_flag(self) -> None:
        from cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["models", "list", "--all-known"])
        self.assertTrue(args.all_known)

    def test_default_list_skips_uninstalled_aliases(self) -> None:
        from cli.discovery import cmd_models_list

        installed = ModelRecord(
            id='mdx:on_disk',
            family='mdx',
            basename='on_disk',
            display='On Disk',
            backend_name='on_disk',
            artifacts=ModelArtifacts('on_disk.ckpt'),
            installed=True,
        )
        alias = ModelRecord(
            id='mdx:alias',
            family='mdx',
            basename='alias',
            display='Alias',
            backend_name='alias',
            artifacts=ModelArtifacts('alias.ckpt'),
            installed=False,
        )
        args = argparse.Namespace(family=None, all_known=False, report="json", quiet=True, verbose=False, job_id="list")
        out = io.StringIO()
        with patch("cli.discovery.iter_model_records", return_value=(installed, alias)), patch(
            "core.model_repository.ModelRepository"
        ), patch("cli.discovery._model_info", side_effect=lambda record, repo: record.to_dict()), redirect_stdout(out):
            code = cmd_models_list(args)
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        ids = [item["id"] for item in payload["items"]]
        self.assertEqual(ids, ["mdx:on_disk"])

    def test_all_known_reports_every_record_from_the_published_index(self) -> None:
        from cli.discovery import cmd_models_list

        records = (
            ModelRecord(
                id="mdx:model",
                family="mdx",
                basename="model",
                display="Model",
                backend_name="model",
                artifacts=ModelArtifacts("model.ckpt", ("model.yaml",)),
                installed=False,
                mdx=MdxSpec("mdx23c"),
            ),
            ModelRecord(
                id="demucs:bag",
                family="demucs",
                basename="bag",
                display="Bag",
                backend_name="bag",
                artifacts=ModelArtifacts("bag.yaml", ("member.th",)),
                installed=False,
                identity_complete=False,
                identity_error="missing Demucs identity metadata",
                demucs=DemucsSpec("v4", "4_stem"),
            ),
        )
        args = argparse.Namespace(
            family=None, all_known=True, report="json", quiet=True,
            verbose=False, job_id="all-known",
        )
        out = io.StringIO()
        with patch(
            "core.model_identity.ModelIdentityService._published_index",
            return_value=IdentityIndex({record.id: record for record in records}),
        ), redirect_stdout(out):
            code = cmd_models_list(args)

        self.assertEqual(code, 0)
        items = json.loads(out.getvalue())["items"]
        self.assertEqual([item["id"] for item in items], ["mdx:model", "demucs:bag"])
        self.assertEqual(items[0]["primary_artifact"], "model.ckpt")
        self.assertEqual(items[0]["supporting_artifacts"], ["model.yaml"])
        self.assertEqual(items[0]["mdx_kind"], "mdx23c")
        self.assertEqual(items[1]["demucs_version"], "v4")
        self.assertEqual(items[1]["source_layout"], "4_stem")
        self.assertEqual(items[1]["identity_error"], "missing Demucs identity metadata")
        for item in items:
            self.assertIn("backend_name", item)
            self.assertIn("identity_complete", item)
            self.assertNotIn("engine_name", item)


class StrictCliModelIdTests(unittest.TestCase):
    canonical_error = (
        "expected canonical model ID family:basename; run 'uvr models list' "
        "for installed IDs or 'uvr models catalog' for downloadable models"
    )

    def setUp(self) -> None:
        self.record = ModelRecord(
            id="mdx:model",
            family="mdx",
            basename="model",
            display="Model",
            backend_name="model",
            artifacts=ModelArtifacts("model.ckpt"),
            installed=True,
            mdx=MdxSpec("mdx23c"),
        )
        self.index = IdentityIndex({self.record.id: self.record})

    def _run(self, argv: list[str]) -> tuple[int, dict[str, Any]]:
        out = io.StringIO()
        with patch(
            "core.model_identity.ModelIdentityService._published_index",
            return_value=self.index,
        ), redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main([*argv, "--report", "json"])
        return code, json.loads(out.getvalue())

    def test_models_show_rejects_a_bare_basename(self) -> None:
        code, payload = self._run(["models", "show", "model"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["message"], self.canonical_error)

    def test_models_configure_rejects_a_bare_basename(self) -> None:
        code, payload = self._run(["models", "configure", "model", "--reset"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["message"], self.canonical_error)

    def test_models_validate_rejects_a_bare_basename(self) -> None:
        code, payload = self._run(["models", "validate", "model"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["message"], self.canonical_error)

    def test_separate_rejects_a_bare_basename_before_planning(self) -> None:
        from cli.profiles import LoadedProfile
        from core.settings import Settings

        out = io.StringIO()
        with patch(
            "cli.job._base_resolve",
            return_value=(Settings.defaults(), LoadedProfile("defaults", "built-in"), ["song.wav"], "/tmp/out"),
        ), patch(
            "core.model_identity.ModelIdentityService._published_index",
            return_value=self.index,
        ), redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main([
                "separate", "song.wav", "-o", "/tmp/out", "--model", "model",
                "--dry-run", "--report", "json",
            ])
        payload = json.loads(out.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["message"], self.canonical_error)


class SharedCliModelLookupTests(unittest.TestCase):
    def test_shared_lookup_rejects_noncanonical_text_with_discovery_hint(self) -> None:
        from cli.model_identity import CliModelLookup

        lookup = CliModelLookup(Mock())
        with self.assertRaises(ValueError) as caught:
            lookup.lookup("model")
        self.assertEqual(
            str(caught.exception),
            "expected canonical model ID family:basename; run 'uvr models list' "
            "for installed IDs or 'uvr models catalog' for downloadable models",
        )

    def test_shared_lookup_applies_exact_family_check_after_index_lookup(self) -> None:
        from cli.model_identity import CliModelLookup

        record = ModelRecord(
            id="mdx:model",
            family="mdx",
            basename="model",
            display="Model",
            backend_name="model",
            artifacts=ModelArtifacts("model.ckpt"),
            installed=True,
        )
        index = IdentityIndex({record.id: record})
        with patch(
            "cli.model_identity.ModelIdentityService._published_index",
            return_value=index,
        ):
            lookup = CliModelLookup(Mock())
            self.assertEqual(lookup.lookup("mdx:model", family="mdx"), record)
            with self.assertRaisesRegex(
                ValueError,
                "model 'mdx:model' does not belong to required family vr",
            ):
                lookup.lookup("mdx:model", family="vr")


class ModelsValidateInventoryTests(unittest.TestCase):
    def test_untargeted_validate_reports_demucs_root_ckpt(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            checkpoint = os.path.join(root, "unsupported.ckpt")
            Path(checkpoint).write_bytes(b"")
            out = io.StringIO()
            with patch("cli.discovery.DEMUCS_MODELS_DIR", root), redirect_stdout(out):
                code = main(["models", "validate", "--report", "json"])

        self.assertEqual(code, 0)
        items = json.loads(out.getvalue())["items"]
        self.assertEqual(items, [{
            "artifact": "unsupported.ckpt",
            "family": "demucs",
            "identity_complete": False,
            "identity_error": "unsupported Demucs-root .ckpt artifact",
            "installed": True,
            "supported": False,
        }])


class ModelsCatalogSizeBatchTests(unittest.TestCase):
    def test_online_catalog_prefetches_sizes_once(self) -> None:
        from cli.discovery import cmd_models_catalog

        service = Mock()
        service.refresh.return_value = True
        service.filter.return_value = ()
        service.manager = Mock()
        service.manager.catalogue_checkpoint_urls.return_value = [
            "https://a/x.ckpt",
            "https://b/y.ckpt",
        ]
        service.manager._last_refresh_report = None
        args = argparse.Namespace(
            family=None, query="", purpose="all", supported=None, installed=None,
            offline=False, report="json", quiet=True, verbose=False, job_id="catalog",
        )
        out = io.StringIO()
        with patch("core.model_catalogue.ModelCatalogueService", return_value=service), patch(
            "core.catalogue_coordinator.CatalogueCoordinator"
        ), patch(
            "core.download_sizes.prefetch_remote_sizes", return_value={}
        ) as prefetch, redirect_stdout(out):
            code = cmd_models_catalog(args)
        self.assertEqual(code, 0)
        prefetch.assert_called_once()

    def test_offline_catalog_skips_size_prefetch(self) -> None:
        from cli.discovery import cmd_models_catalog

        service = Mock()
        service.refresh.return_value = True
        service.filter.return_value = ()
        service.manager = Mock()
        service.manager._last_refresh_report = None
        args = argparse.Namespace(
            family=None, query="", purpose="all", supported=None, installed=None,
            offline=True, report="json", quiet=True, verbose=False, job_id="catalog",
        )
        out = io.StringIO()
        with patch("core.model_catalogue.ModelCatalogueService", return_value=service), patch(
            "core.catalogue_coordinator.CatalogueCoordinator"
        ), patch(
            "core.download_sizes.prefetch_remote_sizes"
        ) as prefetch, redirect_stdout(out):
            code = cmd_models_catalog(args)
        self.assertEqual(code, 0)
        prefetch.assert_not_called()
