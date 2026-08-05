"""Durable model hash entries must ignore stale mtime/size."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from core import model_hash_cache as mhc


class ModelHashCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "model.ckpt")
        with open(self.path, "wb") as handle:
            handle.write(b"abc")
        st = os.stat(self.path)
        self.entry = {
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
        table: dict = {}
        mhc.remember(table, self.path, "cafebabe")
        stored = table[self.path]
        self.assertEqual(stored["hash"], "cafebabe")
        st = os.stat(self.path)
        self.assertEqual(stored["mtime_ns"], st.st_mtime_ns)
        self.assertEqual(stored["size"], st.st_size)

    def test_lookup_trusted_returns_hash(self) -> None:
        table = {self.path: dict(self.entry)}
        self.assertEqual(mhc.lookup_trusted(table, self.path), "deadbeef")


if __name__ == "__main__":
    unittest.main()
