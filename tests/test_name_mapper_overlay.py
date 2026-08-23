"""Local-overlay name mappers: upstream file stays a pure mirror."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import warnings
from unittest import mock

from core import name_mapper


def _write(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _read(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class NameMapperOverlayTests(unittest.TestCase):
    def test_overlay_path_is_sibling_of_mapper(self) -> None:
        mapper = os.path.join("a", "b", "model_name_mapper.json")
        self.assertEqual(
            name_mapper.local_overlay_path(mapper),
            os.path.join("a", "b", "model_name_mapper_local.json"),
        )

    def test_load_merges_overlay_over_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mapper = os.path.join(tmp, "model_name_mapper.json")
            _write(mapper, {"a.ckpt": "Upstream A", "b.ckpt": "Upstream B"})
            _write(
                name_mapper.local_overlay_path(mapper),
                {"b.ckpt": "Fork B", "c.ckpt": "Fork C"},
            )
            merged = name_mapper.load_name_mapper(mapper)
        # Fork intent wins on conflict; that is the point of an explicit overlay.
        self.assertEqual(
            merged,
            {"a.ckpt": "Upstream A", "b.ckpt": "Fork B", "c.ckpt": "Fork C"},
        )

    def test_presentation_loader_ignores_legacy_local_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mapper = os.path.join(tmp, "model_name_mapper.json")
            _write(mapper, {"a.ckpt": "Upstream A", "b.ckpt": "Upstream B"})
            _write(
                name_mapper.local_overlay_path(mapper),
                {"b.ckpt": "Legacy B", "c.ckpt": "Legacy C"},
            )

            loaded = name_mapper.load_presentation_name_mapper(mapper)

        self.assertEqual(loaded, {"a.ckpt": "Upstream A", "b.ckpt": "Upstream B"})

    def test_repository_presentation_snapshot_ignores_legacy_overlays(self) -> None:
        from core.model_repository import ModelRepository

        with tempfile.TemporaryDirectory() as tmp:
            mdx_mapper = os.path.join(tmp, "mdx", "model_name_mapper.json")
            demucs_mapper = os.path.join(tmp, "demucs", "model_name_mapper.json")
            _write(mdx_mapper, {"a.ckpt": "Upstream A"})
            _write(demucs_mapper, {"b.th": "Upstream B"})
            _write(name_mapper.local_overlay_path(mdx_mapper), {"a.ckpt": "Legacy A"})
            _write(name_mapper.local_overlay_path(demucs_mapper), {"b.th": "Legacy B"})
            repo = ModelRepository.__new__(ModelRepository)
            repo._naming_revision = 0

            with (
                mock.patch("core.model_repository.paths.MDX_MODEL_NAME_SELECT", mdx_mapper),
                mock.patch("core.model_repository.paths.DEMUCS_MODEL_NAME_SELECT", demucs_mapper),
            ):
                ModelRepository._reload_name_mappers(repo)

        self.assertEqual(repo.mdx_name_select_MAPPER, {"a.ckpt": "Upstream A"})
        self.assertEqual(repo.demucs_name_select_MAPPER, {"b.th": "Upstream B"})
        self.assertEqual(repo._naming_revision, 1)

    def test_archival_preserves_overlay_replaced_after_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mapper = os.path.join(tmp, "model_name_mapper.json")
            source = name_mapper.local_overlay_path(mapper)
            archive = name_mapper.legacy_overlay_archive_path(mapper)
            _write(source, {"model.ckpt": "Original"})
            real_link = os.link

            def link_then_replace(link_source: str, link_archive: str) -> None:
                real_link(link_source, link_archive)
                replacement = f"{link_source}.replacement"
                _write(replacement, {"model.ckpt": "Concurrent replacement"})
                os.replace(replacement, link_source)

            with warnings.catch_warnings(record=True) as caught, mock.patch.object(
                name_mapper.os, "link", side_effect=link_then_replace
            ):
                warnings.simplefilter("always")
                changed = name_mapper.archive_legacy_local_overlay(mapper)

            self.assertFalse(changed)
            self.assertEqual(_read(source), {"model.ckpt": "Concurrent replacement"})
            self.assertEqual(_read(archive), {"model.ckpt": "Original"})
            self.assertTrue(
                any("changed during archival" in str(item.message) for item in caught)
            )

    def test_load_without_overlay_returns_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mapper = os.path.join(tmp, "model_name_mapper.json")
            _write(mapper, {"a.ckpt": "Upstream A"})
            self.assertEqual(
                name_mapper.load_name_mapper(mapper), {"a.ckpt": "Upstream A"}
            )

    def test_add_local_name_writes_overlay_not_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mapper = os.path.join(tmp, "model_name_mapper.json")
            _write(mapper, {"a.ckpt": "Upstream A"})
            name_mapper.add_local_name(mapper, "new.ckpt", "My Model")

            self.assertEqual(_read(mapper), {"a.ckpt": "Upstream A"})
            self.assertEqual(
                _read(name_mapper.local_overlay_path(mapper)), {"new.ckpt": "My Model"}
            )

    def test_migration_moves_local_only_keys_into_overlay(self) -> None:
        """Existing installs carry fork keys inside the mirror; rescue them once."""
        with tempfile.TemporaryDirectory() as tmp:
            mapper = os.path.join(tmp, "model_name_mapper.json")
            _write(mapper, {"a.ckpt": "Old A", "local_only.ckpt": "Local Only"})
            remote = {"a.ckpt": "Upstream A"}

            name_mapper.migrate_local_only_keys(mapper, remote)

            self.assertEqual(
                _read(name_mapper.local_overlay_path(mapper)),
                {"local_only.ckpt": "Local Only"},
            )

    def test_migration_ignores_keys_upstream_still_ships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mapper = os.path.join(tmp, "model_name_mapper.json")
            _write(mapper, {"a.ckpt": "Old A"})
            name_mapper.migrate_local_only_keys(mapper, {"a.ckpt": "Upstream A"})
            # The overlay is written even when empty — it is the migration
            # marker — but must not pin upstream's own value.
            self.assertEqual(_read(name_mapper.local_overlay_path(mapper)), {})

    def test_migration_runs_only_once(self) -> None:
        """A second pass must not capture upstream deletions into the overlay."""
        with tempfile.TemporaryDirectory() as tmp:
            mapper = os.path.join(tmp, "model_name_mapper.json")
            _write(mapper, {"a.ckpt": "Upstream A", "fork.ckpt": "Fork"})
            name_mapper.migrate_local_only_keys(mapper, {"a.ckpt": "Upstream A"})
            self.assertEqual(
                _read(name_mapper.local_overlay_path(mapper)), {"fork.ckpt": "Fork"}
            )

            # Upstream later drops a.ckpt; the mirror still holds it at this point.
            self.assertFalse(name_mapper.migrate_local_only_keys(mapper, {}))
            self.assertEqual(
                _read(name_mapper.local_overlay_path(mapper)),
                {"fork.ckpt": "Fork"},
                "re-running migration reinstated the union-file bug",
            )

    def test_upstream_deletion_propagates(self) -> None:
        """The regression the overlay exists to fix.

        Under the old ``{**local, **remote}`` write-back, a key upstream removed
        survived locally forever because the merge target was also the merge
        input. With a pure mirror it disappears.
        """
        from unittest import mock

        from core import downloads as downloads_mod

        with tempfile.TemporaryDirectory() as tmp:
            mapper = os.path.join(tmp, "model_name_mapper.json")
            _write(mapper, {"keep.ckpt": "Keep", "dropped.ckpt": "Mis-mapping"})
            _write(name_mapper.local_overlay_path(mapper), {"fork.ckpt": "Fork Only"})

            class _Resp:
                def __init__(self, data: dict) -> None:
                    import io

                    self._buf = io.StringIO(json.dumps(data))

                def __enter__(self):
                    return self._buf

                def __exit__(self, *args: object) -> None:
                    return None

            # Upstream no longer ships dropped.ckpt.
            remote = {"keep.ckpt": "Keep"}
            urls = [("https://example.test/mdx_name.json", mapper)]

            with mock.patch.object(downloads_mod, "_MODEL_DATA_URLS", urls), (
                mock.patch.object(downloads_mod, "_NAME_MAPPER_DESTS", frozenset({mapper}))
            ), mock.patch.object(
                downloads_mod, "_urlopen", side_effect=[_Resp(remote)]
            ):
                downloads_mod.DownloadManager.update_model_settings(
                    downloads_mod.DownloadManager.__new__(downloads_mod.DownloadManager)
                )

            self.assertEqual(_read(mapper), remote, "mirror must match upstream exactly")
            merged = name_mapper.load_name_mapper(mapper)
            self.assertNotIn("dropped.ckpt", merged, "upstream deletion did not propagate")
            self.assertEqual(merged["fork.ckpt"], "Fork Only", "fork key was lost")


if __name__ == "__main__":
    unittest.main()
