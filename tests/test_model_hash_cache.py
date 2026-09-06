"""Durable model hash entries must ignore stale mtime/size."""

from __future__ import annotations

import os
import tempfile
import unittest

from core import model_hash_cache as mhc
from tests.model_config_fixtures import model_config_shell


class ModelHashCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "model.ckpt")
        with open(self.path, "wb") as handle:
            handle.write(b"abc")
        st = os.stat(self.path)
        self.entry: mhc.HashEntry = {
            "hash": "deadbeef",
            "mtime_ns": st.st_mtime_ns,
            "size": st.st_size,
        }

    def test_flatten_trusted_keeps_matching_entry(self) -> None:
        table = {self.path: dict(self.entry)}
        self.assertEqual(mhc.flatten_trusted(table), {self.path: "deadbeef"})

    def test_flatten_trusted_drops_stale_mtime(self) -> None:
        stale = dict(self.entry)
        stale["mtime_ns"] = self.entry["mtime_ns"] - 1
        table = {self.path: stale}
        self.assertEqual(mhc.flatten_trusted(table), {})

    def test_legacy_string_is_not_trusted_until_remembered(self) -> None:
        table = {self.path: "deadbeef"}
        self.assertEqual(mhc.flatten_trusted(table), {})

    def test_remember_writes_stat_fields(self) -> None:
        table: dict[str, mhc.HashEntry] = {}
        mhc.remember(table, self.path, "cafebabe")
        stored = table[self.path]
        self.assertEqual(stored["hash"], "cafebabe")
        st = os.stat(self.path)
        self.assertEqual(stored["mtime_ns"], st.st_mtime_ns)
        self.assertEqual(stored["size"], st.st_size)

    def test_lookup_trusted_returns_hash(self) -> None:
        table = {self.path: dict(self.entry)}
        self.assertEqual(mhc.lookup_trusted(table, self.path), "deadbeef")

    def test_malformed_mtime_ns_is_untrusted(self) -> None:
        bad = dict(self.entry)
        bad["mtime_ns"] = "bad"
        table = {self.path: bad}
        self.assertIsNone(mhc.lookup_trusted(table, self.path))
        self.assertEqual(mhc.flatten_trusted(table), {})

    def test_malformed_size_is_untrusted(self) -> None:
        bad = dict(self.entry)
        bad["size"] = "bad"
        table = {self.path: bad}
        self.assertIsNone(mhc.lookup_trusted(table, self.path))
        self.assertEqual(mhc.flatten_trusted(table), {})

    def test_overflow_mtime_ns_is_untrusted(self) -> None:
        bad = dict(self.entry)
        bad["mtime_ns"] = float("inf")
        table = {self.path: bad}
        self.assertIsNone(mhc.lookup_trusted(table, self.path))
        self.assertEqual(mhc.flatten_trusted(table), {})

    def test_lookup_trusted_uses_injected_stat(self) -> None:
        table = {self.path: dict(self.entry)}
        st = os.stat(self.path)

        def fake_stat(path: str) -> os.stat_result:
            self.assertEqual(path, self.path)
            return st

        self.assertEqual(
            mhc.lookup_trusted(table, self.path, stat=fake_stat),
            "deadbeef",
        )

    def test_lookup_trusted_returns_none_on_oserror(self) -> None:
        table = {self.path: dict(self.entry)}

        def raising_stat(path: str) -> os.stat_result:
            raise OSError("missing")

        self.assertIsNone(mhc.lookup_trusted(table, self.path, stat=raising_stat))

    def test_remember_is_a_noop_on_oserror(self) -> None:
        table: dict[str, mhc.HashEntry] = {}

        def raising_stat(path: str) -> os.stat_result:
            raise OSError("vanished mid-hash")

        mhc.remember(table, self.path, "cafebabe", stat=raising_stat)
        self.assertEqual(table, {})

    def test_snapshot_table_returns_independent_copy(self) -> None:
        table = {self.path: dict(self.entry)}
        snapshot = mhc.snapshot_table(table)
        self.assertEqual(snapshot, table)
        snapshot["extra"] = "value"
        self.assertNotIn("extra", table)

    def test_concurrent_remember_during_snapshot_does_not_raise(self) -> None:
        import threading

        table: dict[str, mhc.HashEntry] = {}
        stop = threading.Event()
        errors: list[BaseException] = []

        def writer() -> None:
            i = 0
            while not stop.is_set():
                try:
                    mhc.remember(table, f"{self.path}.{i}", "hash")
                except BaseException as exc:  # pragma: no cover - failure path
                    errors.append(exc)
                    return
                i += 1

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            for _ in range(200):
                mhc.snapshot_table(table)
        finally:
            stop.set()
            thread.join(timeout=5)

        self.assertEqual(errors, [])


class ModelHashWireTests(unittest.TestCase):
    def test_get_model_hash_remembers_into_settings(self) -> None:
        from unittest import mock

        from core.model_repository import ModelRepository
        from core.settings import Settings

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "w.ckpt")
        with open(path, "wb") as handle:
            handle.write(b"payload")

        settings = Settings()
        repo = ModelRepository()
        repo.model_hash_table = {}

        cfg = model_config_shell()
        cfg.settings = settings
        cfg.repo = repo
        cfg.model_path = path
        cfg.model_status = True
        cfg.model_hash = None
        cfg.is_dry_check = True

        with mock.patch(
            "core.model_config.config.compute_checkpoint_hash", return_value="abc123"
        ):
            cfg.get_model_hash()

        self.assertEqual(repo.model_hash_table[path], "abc123")
        self.assertEqual(settings.process.model_hash_table[path]["hash"], "abc123")

    def test_replaced_checkpoint_ignores_the_in_memory_hash(self) -> None:
        """A checkpoint swapped at the same path must re-hash, not reuse.

        ``lookup_trusted`` collapses "absent" and "stale" into ``None``. When it
        correctly reports a replaced file, ``get_model_hash`` used to fall
        through to the unguarded in-memory dict and return the previous md5 --
        resolving the new checkpoint to the *old* model's params.
        """
        from unittest import mock

        from core import model_hash_cache as mhc
        from core.model_repository import ModelRepository
        from core.settings import Settings

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "w.ckpt")
        with open(path, "wb") as handle:
            handle.write(b"first payload")

        settings = Settings()
        repo = ModelRepository()
        mhc.remember(settings.process.model_hash_table, path, "OLDHASH")
        repo.model_hash_table = {path: "OLDHASH"}

        # Different length, so the size guard trips regardless of mtime_ns
        # granularity on this filesystem.
        with open(path, "wb") as handle:
            handle.write(b"a completely different, longer payload")

        cfg = model_config_shell()
        cfg.settings = settings
        cfg.repo = repo
        cfg.model_path = path
        cfg.model_status = True
        cfg.model_hash = None
        cfg.is_dry_check = True

        with mock.patch(
            "core.model_config.config.compute_checkpoint_hash", return_value="NEWHASH"
        ):
            cfg.get_model_hash()

        self.assertEqual(cfg.model_hash, "NEWHASH")
        self.assertEqual(repo.model_hash_table[path], "NEWHASH")

    def test_absent_persistent_entry_still_uses_the_in_memory_hash(self) -> None:
        """Eviction must be scoped to *stale* entries.

        Treating "no persistent entry" as stale would disable the in-memory
        cache wholesale and reintroduce an md5 per dry check.
        """
        from unittest import mock

        from core.model_repository import ModelRepository
        from core.settings import Settings

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "w.ckpt")
        with open(path, "wb") as handle:
            handle.write(b"payload")

        settings = Settings()
        repo = ModelRepository()
        repo.model_hash_table = {path: "MEMONLY"}

        cfg = model_config_shell()
        cfg.settings = settings
        cfg.repo = repo
        cfg.model_path = path
        cfg.model_status = True
        cfg.model_hash = None
        cfg.is_dry_check = True

        with mock.patch(
            "core.model_config.config.compute_checkpoint_hash",
            side_effect=AssertionError("must not re-hash an unchanged file"),
        ):
            cfg.get_model_hash()

        self.assertEqual(cfg.model_hash, "MEMONLY")

    def test_appcontext_seeds_trusted_hashes(self) -> None:
        from ui.context import AppContext

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "w.ckpt")
        with open(path, "wb") as handle:
            handle.write(b"payload")
        st = os.stat(path)

        ctx = AppContext()
        ctx.settings.process.model_hash_table = {
            path: {"hash": "seeded", "mtime_ns": st.st_mtime_ns, "size": st.st_size}
        }
        ctx._repo = None

        self.assertEqual(ctx.repo.model_hash_table.get(path), "seeded")


class ModelHashPersistTests(unittest.TestCase):
    def test_settings_round_trip_keeps_entry_shape(self) -> None:
        from core.settings import Settings

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "settings.json")
        checkpoint = os.path.join(tmp.name, "model.ckpt")
        with open(checkpoint, "wb") as handle:
            handle.write(b"x")
        st = os.stat(checkpoint)

        settings = Settings()
        settings.path = path
        settings.process.model_hash_table = {
            checkpoint: {
                "hash": "zz",
                "mtime_ns": st.st_mtime_ns,
                "size": st.st_size,
            }
        }
        settings.save(path)

        loaded = Settings.load(path)
        self.assertEqual(loaded.process.model_hash_table[checkpoint]["hash"], "zz")

    def test_to_json_dict_survives_concurrent_remember(self) -> None:
        """Regression for RuntimeError: dictionary changed size during
        iteration, when a worker thread calls get_model_hash -> remember
        while the main thread serializes settings for save()."""
        import threading

        from core import model_hash_cache as mhc
        from core.settings import Settings

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        checkpoint = os.path.join(tmp.name, "model.ckpt")
        with open(checkpoint, "wb") as handle:
            handle.write(b"x")

        settings = Settings()
        stop = threading.Event()
        errors: list[BaseException] = []

        def writer() -> None:
            i = 0
            while not stop.is_set():
                try:
                    mhc.remember(
                        settings.process.model_hash_table, f"{checkpoint}.{i}", "h"
                    )
                except BaseException as exc:  # pragma: no cover - failure path
                    errors.append(exc)
                    return
                i += 1

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            for _ in range(200):
                settings.to_json_dict()
        finally:
            stop.set()
            thread.join(timeout=5)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
