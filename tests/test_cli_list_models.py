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
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cli.discovery import (
    _print_detail, cmd_devices_list, cmd_models_download, cmd_profile_list,
)
from cli.main import main
from core.model_identity import ModelIdentityService, ModelRecord, resolve_model_record
from core.model_catalogue import CatalogEntryId
from core.model_registry import ModelRegistryService


class ModelIdTests(unittest.TestCase):
    def test_qualified_id_is_stable(self) -> None:
        records = [ModelRecord("mdx:model_a", "mdx", "model_a", "Model A")]
        result = resolve_model_record("mdx:model_a", records)
        self.assertEqual(result.id, "mdx:model_a")

    def test_apollo_id_is_supported(self) -> None:
        record = ModelRecord(
            "apollo:restore", "apollo", "restore", "Restore", True,
            "restore.ckpt",
        )
        self.assertEqual(resolve_model_record("restore.ckpt", [record]).id, "apollo:restore")

    def test_family_constraint_rejects_cross_family_match(self) -> None:
        service = ModelIdentityService(object())
        records = (
            ModelRecord("mdx:shared", "mdx", "shared", "Shared"),
            ModelRecord("vr:other", "vr", "other", "Other"),
        )
        with patch.object(service, "records", return_value=records):
            self.assertEqual(service.resolve("shared", family="mdx").id, "mdx:shared")
            with self.assertRaisesRegex(ValueError, "required family"):
                service.resolve("mdx:shared", family="vr")

    def test_allowed_families_reject_ineligible_identity(self) -> None:
        service = ModelIdentityService(object())
        records = (
            ModelRecord("apollo:restore", "apollo", "restore", "Restore"),
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
            ModelRecord("mdx:vocals", "mdx", "vocals", "Vocals"),
            ModelRecord("vr:vocals", "vr", "vocals", "Vocals"),
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

        with patch.object(politrees_catalog, "_cached_links", None), patch.object(
            politrees_catalog, "_read_disk_cache_entry", return_value=None
        ), patch.object(
            politrees_catalog, "_read_disk_cache", return_value=None
        ), patch.object(politrees_catalog, "_urlopen") as network:
            self.assertIsNone(
                politrees_catalog.load_politrees_links(allow_network=False)
            )
        network.assert_not_called()

    def test_offline_context_never_mutates_process_environment(self) -> None:
        from core.offline import catalogue_offline

        with patch.dict(os.environ, {}, clear=True):
            with catalogue_offline(True):
                self.assertNotIn("UVR_DISABLE_POLITREES", os.environ)
                self.assertNotIn("UVR_DISABLE_MVSEPLESS", os.environ)

    def test_legacy_ensemble_tag_resolves_to_canonical_id(self) -> None:
        records = [ModelRecord("mdx:model_a", "mdx", "model_a", "Model A")]
        result = resolve_model_record("MDX-Net: Model A", records)
        self.assertEqual(result.id, "mdx:model_a")


class DiscoveryTests(unittest.TestCase):
    def args(self) -> argparse.Namespace:
        return argparse.Namespace(report="json", quiet=False, verbose=False)

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
        ), patch("core.model_data.ModelRepository"), patch(
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
