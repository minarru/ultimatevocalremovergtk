"""Apollo checkpoint hashes go through the persistent stat-guarded table."""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any
from unittest import mock

from core import apollo, paths
from core import model_hash_cache as mhc
from core.model_repository import ModelRepository

NAME = "restore.ckpt"


class ApolloModelHashTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.models_dir = os.path.join(tmp.name, "models")
        self.hash_dir = os.path.join(tmp.name, "hashes")
        os.makedirs(self.models_dir)
        os.makedirs(self.hash_dir)
        for name, value in (
            ("APOLLO_MODELS_DIR", self.models_dir),
            ("APOLLO_HASH_DIR", self.hash_dir),
            ("APOLLO_CONFIG_PATH", os.path.join(tmp.name, "configs")),
        ):
            patcher = mock.patch.object(paths, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.path = os.path.join(self.models_dir, NAME)
        self._write(b"first")

    def _write(self, payload: bytes) -> None:
        with open(self.path, "wb") as handle:
            handle.write(payload)

    def _data(self, memory: dict[str, str], persistent: dict[str, Any] | None):
        return apollo.ApolloModelData(
            NAME,
            model_hash_table=memory,
            persistent_hash_table=persistent,
            is_dry_check=True,
        )

    def test_computed_hash_is_remembered_with_stat_fields(self) -> None:
        memory: dict[str, str] = {}
        persistent: dict[str, Any] = {}

        data = self._data(memory, persistent)

        expected = apollo.checkpoint_md5(self.path)
        self.assertEqual(data.model_hash, expected)
        self.assertEqual(memory, {self.path: expected})
        self.assertEqual(mhc.lookup_trusted(persistent, self.path), expected)

    def test_trusted_persistent_entry_skips_hashing(self) -> None:
        memory: dict[str, str] = {}
        persistent: dict[str, Any] = {}
        mhc.remember(persistent, self.path, "trusted")

        with mock.patch.object(apollo, "checkpoint_md5") as md5:
            data = self._data(memory, persistent)

        md5.assert_not_called()
        self.assertEqual(data.model_hash, "trusted")
        self.assertEqual(memory, {self.path: "trusted"})

    def test_replaced_checkpoint_ignores_the_in_memory_hash(self) -> None:
        memory: dict[str, str] = {}
        persistent: dict[str, Any] = {}
        old = self._data(memory, persistent).model_hash

        self._write(b"a different, longer checkpoint")
        data = self._data(memory, persistent)

        new = apollo.checkpoint_md5(self.path)
        self.assertNotEqual(old, new)
        self.assertEqual(data.model_hash, new)
        self.assertEqual(memory[self.path], new)
        self.assertEqual(mhc.lookup_trusted(persistent, self.path), new)

    def test_without_persistent_table_keeps_in_memory_behaviour(self) -> None:
        memory = {self.path: "cached"}

        data = self._data(memory, None)

        self.assertEqual(data.model_hash, "cached")

    def test_missing_checkpoint_is_not_remembered(self) -> None:
        os.remove(self.path)
        persistent: dict[str, Any] = {}

        data = self._data({}, persistent)

        self.assertIsNone(data.model_hash)
        self.assertFalse(data.model_status)
        self.assertEqual(persistent, {})


class RepositoryPersistentTableTests(unittest.TestCase):
    def test_unbound_repository_has_no_persistent_table(self) -> None:
        self.assertIsNone(ModelRepository().persistent_model_hash_table())

    def test_bound_repository_returns_the_live_table(self) -> None:
        table: dict[str, Any] = {}
        repo = ModelRepository()
        repo.bind_model_hash_table(lambda: table)

        self.assertIs(repo.persistent_model_hash_table(), table)


if __name__ == "__main__":
    unittest.main()
