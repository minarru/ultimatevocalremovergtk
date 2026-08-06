"""Local-overlay name mappers: upstream file stays a pure mirror."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

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
