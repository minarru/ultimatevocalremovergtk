"""One logical model publishes exactly once, and only when it is usable.

Publication used to be spread across three owners: `DownloadManager.download`
registered MDX-C/Apollo metadata and invalidated, the queue marked items ready
independently, and the CLI invalidated again after the whole batch. A model
could therefore reach the pickers before every declared artifact had landed,
and a two-model batch produced one late refresh instead of two timely ones.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

from core.model_install import ModelInstallResult, finalize_downloaded_model


def _snapshot(
    *,
    vr: Any = None,
    mdx: Any = None,
    apollo: Any = None,
    demucs: Any = None,
    meta: Any = None,
    entry_sources: Any = None,
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
        display_index_vr={},
        display_index_mdx={},
        display_index_demucs={},
        entry_sources=entry_sources or {},
    )


class _Repo:
    """A repository stub with the exact surface the finalizer touches."""

    def __init__(self, snapshot: Any, files: dict[str, list[str]] | None = None):
        self._files = files or {}
        self.catalogue: Any = SimpleNamespace(_latest=snapshot)
        self._inventory_lock = None
        self.invalidations = 0
        self.presentation_invalidations = 0
        self.mdx_name_select_MAPPER: dict = {}
        self.demucs_name_select_MAPPER: dict = {}
        self.inventory_generation = 0
        self.catalogue_revision = "rev"
        self.naming_revision = 0

    def _model_artifact_files(self, family: str) -> list[str]:
        return list(self._files.get(family, []))

    def list_vr_models(self) -> list[str]:
        return []

    def list_mdx_models(self) -> list[str]:
        return []

    def list_demucs_models(self) -> list[str]:
        return []

    def invalidate_models(self) -> None:
        self.invalidations += 1

    def invalidate_model_presentation(self, **_kwargs: Any) -> None:
        self.presentation_invalidations += 1


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        # `core.paths` resolves DATA_DIR at import, so setting UVR_DATA_DIR here
        # would be too late and ownership writes would land in the real data dir
        # (the repo root, in the portable dev layout). Patch the path itself.
        index_patch = mock.patch(
            "core.model_registry.paths.REGISTERED_MODEL_INDEX",
            os.path.join(self.root, "registered_models.json"),
        )
        index_patch.start()
        self.addCleanup(index_patch.stop)

    def _file(self, name: str) -> str:
        path = os.path.join(self.root, name)
        with open(path, "wb") as handle:
            handle.write(b"weights")
        return path

    def _path(self, name: str) -> str:
        return os.path.join(self.root, name)


class TransferGateTests(_Base):
    def test_stopped_transfer_is_not_ready_and_publishes_nothing(self) -> None:
        repo = _Repo(_snapshot())
        result = finalize_downloaded_model(
            repo=repo,
            family="mdx",
            selection="Anything",
            jobs=[("http://x/a.onnx", self._file("a.onnx"))],
            transfer_result="stopped",
        )

        self.assertFalse(result.ready)
        self.assertFalse(result.published)
        self.assertEqual(repo.invalidations, 0)
        self.assertTrue(result.detail)

    def test_a_missing_target_blocks_publication(self) -> None:
        """A multi-file item is one logical model: partial is not usable."""
        selectable = "MDX-Net Model: Pair"
        files = {"model.ckpt": "u1", "config.yaml": "u2"}
        repo = _Repo(_snapshot(mdx={selectable: files}))

        result = finalize_downloaded_model(
            repo=repo,
            family="mdx",
            selection=selectable,
            jobs=[
                ("u1", self._file("model.ckpt")),
                ("u2", self._path("config.yaml")),  # never landed
            ],
            transfer_result="complete",
        )

        self.assertFalse(result.ready)
        self.assertFalse(result.published)
        self.assertEqual(repo.invalidations, 0)
        self.assertIn("config.yaml", result.detail)

    def test_no_catalogue_snapshot_is_reported_not_guessed(self) -> None:
        repo = _Repo(None)
        repo.catalogue = None

        result = finalize_downloaded_model(
            repo=repo,
            family="mdx",
            selection="Anything",
            jobs=[("u", self._file("a.onnx"))],
            transfer_result="complete",
        )

        self.assertFalse(result.ready)
        self.assertEqual(repo.invalidations, 0)
        self.assertTrue(result.detail)


class SingleFilePublicationTests(_Base):
    def _run(self, *, transfer_result: str = "complete", family: str = "mdx"):
        from bundled.constants import MDX_ARCH_TYPE, VR_ARCH_TYPE
        from core.catalog_sources import EntryMeta

        selectable = "MDX-Net Model: Solo" if family == "mdx" else "VR Model: Solo"
        arch = MDX_ARCH_TYPE if family == "mdx" else VR_ARCH_TYPE
        name = "solo.onnx" if family == "mdx" else "solo.pth"
        files = {name: "u1"}
        entry = EntryMeta(
            label=selectable, display="Solo", arch=arch, files=files, checkpoint=name
        )
        snapshot = _snapshot(**{family: {selectable: files}}, meta={family: {selectable: entry}})
        repo = _Repo(snapshot, files={family: [name]})
        result = finalize_downloaded_model(
            repo=repo,
            family=family,
            selection=selectable,
            jobs=[("u1", self._file(name))],
            transfer_result=transfer_result,
        )
        return repo, result

    def test_completed_mdx_onnx_publishes_once(self) -> None:
        repo, result = self._run()

        self.assertTrue(result.ready)
        self.assertTrue(result.published)
        self.assertEqual(repo.invalidations, 1)

    def test_completed_vr_publishes_once(self) -> None:
        repo, result = self._run(family="vr")

        self.assertTrue(result.ready)
        self.assertTrue(result.published)
        self.assertEqual(repo.invalidations, 1)

    def test_exists_with_repaired_ownership_publishes_once(self) -> None:
        """First sight of an already-present model still indexes ownership."""
        repo, result = self._run(transfer_result="exists")

        self.assertTrue(result.ready)
        self.assertTrue(result.metadata_changed)
        self.assertTrue(result.published)
        self.assertEqual(repo.invalidations, 1)

    def test_unchanged_exists_is_ready_but_does_not_publish(self) -> None:
        """Second pass: metadata is already complete, so nothing repaints."""
        self._run(transfer_result="exists")  # indexes ownership
        repo, result = self._run(transfer_result="exists")

        self.assertTrue(result.ready)
        self.assertFalse(result.metadata_changed)
        self.assertFalse(result.published)
        self.assertEqual(repo.invalidations, 0)

    def test_repeated_finalization_is_idempotent(self) -> None:
        self._run(transfer_result="complete")
        repo, second = self._run(transfer_result="exists")
        _repo, third = self._run(transfer_result="exists")

        self.assertTrue(second.ready)
        self.assertFalse(second.published)
        self.assertTrue(third.ready)
        self.assertFalse(third.published)
        self.assertEqual(repo.invalidations, 0)

    def test_presentation_is_persisted_before_the_only_publication(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.model_registry import ModelRegistryService

        selection = "MDX-Net Model: Durable"
        files = {"durable.onnx": "u1"}
        entry = EntryMeta(
            label=selection,
            display="Durable",
            arch=MDX_ARCH_TYPE,
            files=files,
            checkpoint="durable.onnx",
        )
        snapshot = _snapshot(
            mdx={selection: files},
            meta={"mdx": {selection: entry}},
            entry_sources={"mdx": {selection: "upstream"}},
        )
        repo = _Repo(snapshot, files={"mdx": ["durable.onnx"]})
        order: list[str] = []
        original = ModelRegistryService.remember_presentation

        def remember(*args: Any, **kwargs: Any) -> bool:
            order.append("persist")
            return original(*args, **kwargs)

        repo.invalidate_models = lambda: order.append("invalidate")
        with mock.patch.object(
            ModelRegistryService, "remember_presentation", side_effect=remember
        ):
            result = finalize_downloaded_model(
                repo=repo,
                family="mdx",
                selection=selection,
                jobs=[("u1", self._file("durable.onnx"))],
                transfer_result="complete",
            )

        self.assertTrue(result.ready)
        self.assertEqual(order, ["persist", "invalidate"])
        self.assertEqual(
            ModelRegistryService.presentation("mdx:durable"),
            {"catalogue_label": selection, "catalogue_source": "upstream"},
        )

    def test_failed_presentation_write_is_retryable_from_exists(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.model_registry import ModelRegistryService

        selection = "MDX-Net Model: Retry"
        files = {"retry.onnx": "u1"}
        entry = EntryMeta(
            label=selection,
            display="Retry",
            arch=MDX_ARCH_TYPE,
            files=files,
            checkpoint="retry.onnx",
        )
        snapshot = _snapshot(
            mdx={selection: files},
            meta={"mdx": {selection: entry}},
            entry_sources={"mdx": {selection: "upstream"}},
        )
        repo = _Repo(snapshot, files={"mdx": ["retry.onnx"]})
        job = ("u1", self._file("retry.onnx"))
        with mock.patch.object(
            ModelRegistryService,
            "remember_presentation",
            side_effect=OSError("registry is read-only"),
        ):
            first = finalize_downloaded_model(
                repo=repo,
                family="mdx",
                selection=selection,
                jobs=[job],
                transfer_result="complete",
            )

        self.assertFalse(first.ready)
        self.assertFalse(first.published)
        self.assertEqual(repo.invalidations, 0)
        self.assertIn("presentation", first.detail)

        second = finalize_downloaded_model(
            repo=repo,
            family="mdx",
            selection=selection,
            jobs=[job],
            transfer_result="exists",
        )
        self.assertTrue(second.ready)
        self.assertTrue(second.published)
        self.assertEqual(repo.invalidations, 1)


class IncompleteIdentityTests(_Base):
    def test_a_candidate_that_is_not_identity_complete_does_not_publish(self) -> None:
        """Registration ran but the model still cannot execute."""
        from bundled.constants import MDX_ARCH_TYPE
        from core.catalog_sources import EntryMeta

        selectable = "MDX-Net Model: Pair"
        files = {"model.ckpt": "u1", "config.yaml": "u2"}
        entry = EntryMeta(
            label=selectable,
            display="Pair",
            arch=MDX_ARCH_TYPE,
            files=files,
            checkpoint="model.ckpt",
        )
        snapshot = _snapshot(mdx={selectable: files}, meta={"mdx": {selectable: entry}})
        # The checkpoint is present but its yaml is not installed, so the
        # projected record cannot be identity-complete.
        repo = _Repo(snapshot, files={"mdx": ["model.ckpt"]})

        result = finalize_downloaded_model(
            repo=repo,
            family="mdx",
            selection=selectable,
            jobs=[("u1", self._file("model.ckpt")), ("u2", self._file("config.yaml"))],
            transfer_result="complete",
        )

        self.assertFalse(result.published)
        self.assertEqual(repo.invalidations, 0)
        self.assertTrue(result.detail)

    def test_an_unknown_selection_is_reported(self) -> None:
        repo = _Repo(_snapshot())

        result = finalize_downloaded_model(
            repo=repo,
            family="mdx",
            selection="Not In Catalogue",
            jobs=[("u", self._file("x.onnx"))],
            transfer_result="complete",
        )

        self.assertFalse(result.ready)
        self.assertEqual(repo.invalidations, 0)
        self.assertIn("Not In Catalogue", result.detail)


class RegistrationTests(_Base):
    def test_mdx_c_registration_runs_and_reports_metadata_change(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE
        from core.catalog_sources import EntryMeta

        # A real MDX-C entry carries its architecture in the artifact names,
        # which is what makes the projected record identity-complete.
        selectable = "Roformer Model: Pair"
        ckpt, config = "mel_band_roformer_pair.ckpt", "mel_band_roformer_pair.yaml"
        files = {ckpt: "u1", config: "u2"}
        entry = EntryMeta(
            label=selectable,
            display="Pair",
            arch=MDX_ARCH_TYPE,
            files=files,
            checkpoint=ckpt,
        )
        snapshot = _snapshot(mdx={selectable: files}, meta={"mdx": {selectable: entry}})
        repo = _Repo(snapshot, files={"mdx": [ckpt, config]})
        jobs = [("u1", self._file(ckpt)), ("u2", self._file(config))]

        with mock.patch(
            "core.mdx_c_registry.register_mdx_c_from_download_jobs", return_value=True
        ) as register:
            result = finalize_downloaded_model(
                repo=repo,
                family="mdx",
                selection=selectable,
                jobs=jobs,
                transfer_result="exists",
            )

        register.assert_called_once_with(jobs)
        self.assertTrue(result.metadata_changed)
        # `exists` plus repaired metadata still publishes exactly once.
        self.assertTrue(result.published)
        self.assertEqual(repo.invalidations, 1)

    def test_apollo_registration_runs_for_apollo_items(self) -> None:
        repo = _Repo(_snapshot())
        jobs = [("u", self._file("apollo.ckpt"))]

        with mock.patch(
            "core.apollo_registry.register_apollo_from_download_jobs", return_value=False
        ) as register, mock.patch(
            "core.mdx_c_registry.register_mdx_c_from_download_jobs", return_value=False
        ):
            finalize_downloaded_model(
                repo=repo,
                family="apollo",
                selection="Apollo: Thing",
                jobs=jobs,
                transfer_result="complete",
            )

        register.assert_called_once_with(jobs)

    def test_registration_helpers_do_not_invalidate_themselves(self) -> None:
        """The finalizer owns the single invalidation for the whole item."""
        repo = _Repo(_snapshot())

        with mock.patch(
            "core.mdx_c_registry.register_mdx_c_from_download_jobs", return_value=True
        ), mock.patch(
            "core.apollo_registry.register_apollo_from_download_jobs", return_value=True
        ):
            finalize_downloaded_model(
                repo=repo,
                family="mdx",
                selection="Unknown",
                jobs=[("u", self._file("m.onnx"))],
                transfer_result="complete",
            )

        # Unknown selection: not ready, so nothing published despite metadata.
        self.assertEqual(repo.invalidations, 0)


class PairedMdxCIntegrationTests(_Base):
    """Ported from `test_download_registers_paired_mdx_c_jobs`.

    A real checkpoint plus a real MDX-C config yaml: registration runs, the
    fresh candidate is installed and identity-complete, and the model publishes
    exactly once.
    """

    def test_paired_mdx_c_download_registers_and_publishes_once(self) -> None:
        import shutil

        from bundled.constants import MDX_ARCH_TYPE
        from core import paths
        from core.catalog_sources import EntryMeta

        hash_dir = os.path.join(self.root, "model_data")
        config_dir = os.path.join(hash_dir, "mdx_c_configs")
        models_dir = os.path.join(self.root, "models")
        os.makedirs(config_dir)
        os.makedirs(models_dir)

        checkpoint = os.path.join(models_dir, "scnet_download_model.ckpt")
        with open(checkpoint, "wb") as handle:
            handle.write(b"download registration checkpoint")
        yaml_name = "config_musdb18_scnet.yaml"
        shutil.copyfile(
            os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name),
            os.path.join(config_dir, yaml_name),
        )

        ckpt_name = os.path.basename(checkpoint)
        files = {ckpt_name: "u1", yaml_name: "u2"}
        entry = EntryMeta(
            label="MDX23C Model: SCNet",
            display="SCNet",
            arch=MDX_ARCH_TYPE,
            files=files,
            checkpoint=ckpt_name,
        )
        snapshot = _snapshot(
            mdx={"MDX23C Model: SCNet": files},
            meta={"mdx": {"MDX23C Model: SCNet": entry}},
        )
        repo = _Repo(snapshot, files={"mdx": [ckpt_name, yaml_name]})
        jobs = [("u1", checkpoint), ("u2", os.path.join(config_dir, yaml_name))]

        originals = (paths.MDX_HASH_DIR, paths.MDX_C_CONFIG_PATH, paths.MDX_MODELS_DIR)
        paths.MDX_HASH_DIR = hash_dir
        paths.MDX_C_CONFIG_PATH = config_dir
        paths.MDX_MODELS_DIR = models_dir
        try:
            result = finalize_downloaded_model(
                repo=repo,
                family="mdx",
                selection="MDX23C Model: SCNet",
                jobs=jobs,
                transfer_result="exists",
            )
        finally:
            paths.MDX_HASH_DIR, paths.MDX_C_CONFIG_PATH, paths.MDX_MODELS_DIR = originals

        self.assertTrue(result.ready)
        self.assertTrue(result.published)
        self.assertEqual(repo.invalidations, 1)


class OwnershipIndexTests(_Base):
    def test_remember_registered_is_idempotent(self) -> None:
        from core.model_registry import ModelRegistryService

        first = ModelRegistryService.remember_registered("abc", "mdx:thing")
        second = ModelRegistryService.remember_registered("abc", "mdx:thing")

        self.assertTrue(first)
        self.assertFalse(second)

    def test_remember_registered_reports_a_repair(self) -> None:
        from core.model_registry import ModelRegistryService

        ModelRegistryService.remember_registered("abc", "mdx:thing")
        repaired = ModelRegistryService.remember_registered("abc", "mdx:other")

        self.assertTrue(repaired)

    def test_index_downloaded_reports_whether_it_changed_metadata(self) -> None:
        from core.model_registry import ModelRegistryService

        checkpoint = self._file("indexed.onnx")
        jobs = [("u", checkpoint)]

        with mock.patch(
            "core.mdx_c_registry.compute_checkpoint_hash", return_value="hash-1"
        ):
            first = ModelRegistryService.index_downloaded("mdx", jobs)
            second = ModelRegistryService.index_downloaded("mdx", jobs)

        self.assertTrue(first)
        self.assertFalse(second)


class ResultContractTests(unittest.TestCase):
    def test_result_is_immutable(self) -> None:
        result = ModelInstallResult(ready=True, published=False)

        with self.assertRaises(Exception):
            result.ready = False  # type: ignore[misc]

    def test_defaults(self) -> None:
        result = ModelInstallResult(ready=True, published=True)

        self.assertFalse(result.metadata_changed)
        self.assertEqual(result.detail, "")


if __name__ == "__main__":
    unittest.main()
