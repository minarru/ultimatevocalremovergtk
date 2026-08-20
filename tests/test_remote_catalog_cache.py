"""Contract tests for the revisioned remote JSON source store."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from io import BytesIO
from unittest import mock

from core.access_policy import AccessPolicy
from core.catalogue_types import RefreshMode, SourceId, semantic_digest
from core.remote_catalog_cache import RemoteJsonSource


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Response(BytesIO):
    def __init__(self, payload: dict, *, status: int = 200, headers: dict | None = None) -> None:
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.status = status
        self.headers = headers or {}

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)


class RemoteJsonSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "catalog.json")
        self.clock = _Clock()
        self.addCleanup(self.tmp.cleanup)

    def _source(self, opener=None, **kwargs) -> RemoteJsonSource:
        return RemoteJsonSource(
            source_id=SourceId.POLITREES,
            url="https://example.test/catalog.json",
            cache_filename="catalog.json",
            cache_path=self.path,
            ttl_seconds=60,
            opener=opener or (lambda _url: _Response({"mdx_download_list": {"A": {"a.ckpt": "u"}}})),
            clock=self.clock,
            **kwargs,
        )

    def test_disabled_before_io(self) -> None:
        opener = mock.Mock()
        source = self._source(opener=opener, enabled=lambda: False)
        source.load(
            mode=RefreshMode.FORCE,
            policy=AccessPolicy(allow_network=True, allow_metadata_writes=True),
        )
        opener.assert_not_called()
        self.assertFalse(os.path.exists(self.path))

    def test_memory_hit_skips_disk_and_network(self) -> None:
        opener = mock.Mock(side_effect=lambda _url: _Response({"vr_download_list": {"V": "v.pth"}}))
        source = self._source(opener=opener)
        policy = AccessPolicy(allow_network=True, allow_metadata_writes=True)
        first = source.load(mode=RefreshMode.FORCE, policy=policy)
        opener.reset_mock()
        second = source.load(
            mode=RefreshMode.STALE_WHILE_REVALIDATE, policy=policy
        )
        opener.assert_not_called()
        self.assertEqual(first.content.semantic_digest, second.content.semantic_digest)

    def test_stale_disk_returns_immediately_and_schedules_refresh(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "fetched_at": self.clock.now - 120,
                    "data": {"mdx_download_list": {"Old": {"o.ckpt": "u"}}},
                },
                handle,
            )
        started = threading.Event()

        def opener(_url):
            started.set()
            return _Response({"mdx_download_list": {"New": {"n.ckpt": "u"}}})

        source = self._source(opener=opener)
        state = source.load(
            mode=RefreshMode.STALE_WHILE_REVALIDATE,
            policy=AccessPolicy(allow_network=True, allow_metadata_writes=True),
        )
        self.assertIn("Old", state.content.payload["mdx_download_list"])
        started.wait(timeout=2)
        self.assertTrue(started.is_set())

    def test_force_is_single_flight(self) -> None:
        calls = {"n": 0}
        release = threading.Event()

        def opener(_url):
            calls["n"] += 1
            release.wait(timeout=2)
            return _Response({"mdx_download_list": {"A": {"a.ckpt": "u"}}})

        source = self._source(opener=opener)
        policy = AccessPolicy(allow_network=True, allow_metadata_writes=True)
        results: list = []

        def run() -> None:
            results.append(source.load(mode=RefreshMode.FORCE, policy=policy))

        threads = [threading.Thread(target=run) for _ in range(3)]
        for thread in threads:
            thread.start()
        time.sleep(0.05)
        release.set()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(len(results), 3)

    def test_failed_force_does_not_extend_freshness(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "fetched_at": 50.0,
                    "data": {"mdx_download_list": {"Old": {"o.ckpt": "u"}}},
                },
                handle,
            )
        source = self._source(opener=mock.Mock(side_effect=OSError("offline")))
        source.load(
            mode=RefreshMode.OFFLINE,
            policy=AccessPolicy(allow_network=False, allow_metadata_writes=False),
        )
        before = source.state.content.fetched_at
        self.clock.now = 1_500.0
        source.load(
            mode=RefreshMode.FORCE,
            policy=AccessPolicy(allow_network=True, allow_metadata_writes=True),
        )
        self.assertEqual(source.state.content.fetched_at, before)
        self.assertIsNotNone(source.state.status.error)

    def test_write_denied_updates_memory_not_disk(self) -> None:
        source = self._source()
        source.load(
            mode=RefreshMode.FORCE,
            policy=AccessPolicy(allow_network=True, allow_metadata_writes=False),
        )
        self.assertIsNotNone(source.state.content)
        self.assertFalse(os.path.exists(self.path))

    def test_ordered_digest_changes_with_insertion_order(self) -> None:
        left = {"mdx_download_list": {"A": {"a.ckpt": "u"}, "B": {"b.ckpt": "u"}}}
        right = {"mdx_download_list": {"B": {"b.ckpt": "u"}, "A": {"a.ckpt": "u"}}}
        self.assertNotEqual(semantic_digest(left), semantic_digest(right))

    def test_identical_payload_keeps_semantic_revision(self) -> None:
        payload = {"mdx_download_list": {"A": {"a.ckpt": "u"}}}
        opener = mock.Mock(side_effect=lambda _url: _Response(payload))
        source = self._source(opener=opener)
        policy = AccessPolicy(allow_network=True, allow_metadata_writes=True)
        first = source.load(mode=RefreshMode.FORCE, policy=policy)
        self.clock.now += 5
        second = source.load(mode=RefreshMode.FORCE, policy=policy)
        self.assertEqual(first.content.semantic_digest, second.content.semantic_digest)

    def test_304_refreshes_status_without_new_body(self) -> None:
        payload = {"mdx_download_list": {"A": {"a.ckpt": "u"}}}
        headers = {"ETag": '"abc"'}
        calls = {"n": 0}

        def opener(target):
            calls["n"] += 1
            if calls["n"] == 1:
                return _Response(payload, headers=headers)
            response = _Response(payload, status=304, headers=headers)
            return response

        source = self._source(opener=opener)
        policy = AccessPolicy(allow_network=True, allow_metadata_writes=True)
        first = source.load(mode=RefreshMode.FORCE, policy=policy)
        digest = first.content.semantic_digest
        self.clock.now += 5
        second = source.load(mode=RefreshMode.FORCE, policy=policy)
        self.assertEqual(second.content.semantic_digest, digest)
        self.assertGreaterEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
