"""Unit tests for the catalogue YAML stem cache (disk + background worker)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from typing import Callable
from unittest import mock

import core.catalogue_stem_cache as csc


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            out, self._data = self._data, b""
            return out
        out, self._data = self._data[:n], self._data[n:]
        return out

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class CatalogueStemCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self._tmp.name, "catalogue_stem_cache.json")
        self._path_patch = mock.patch.object(csc, "_cache_path", return_value=self.cache_path)
        self._path_patch.start()
        self._display_patch = mock.patch("core.model_display.clear_display_cache")
        self._display_patch.start()
        csc.clear_catalogue_stem_cache()
        reset = getattr(csc, "_reset_worker_state_for_tests", None)
        if reset is not None:
            reset()

    def tearDown(self) -> None:
        reset = getattr(csc, "_reset_worker_state_for_tests", None)
        if reset is not None:
            reset()
        csc.clear_catalogue_stem_cache()
        self._display_patch.stop()
        self._path_patch.stop()
        self._tmp.cleanup()

    def test_parse_stems_from_yaml_bytes(self) -> None:
        yaml_bytes = b"""
training:
  instruments:
    - Vocals
    - other
  target_instrument: Vocals
"""
        stems, target = csc.parse_stems_from_yaml_bytes(yaml_bytes)
        self.assertEqual(stems, ["Vocals", "other"])
        self.assertEqual(target, "Vocals")

    def test_remember_and_lookup_round_trip(self) -> None:
        url = "https://example.test/config.yaml?v=1"
        csc.remember_stems(url, ["Vocals", "other"], "Vocals", ok=True)
        hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.stems, ("Vocals", "other"))
        self.assertEqual(hit.target_instrument, "Vocals")
        self.assertTrue(hit.ok)
        # Query string stripped for cache key.
        hit2 = csc.lookup_stems("https://example.test/config.yaml")
        self.assertIsNotNone(hit2)
        assert hit2 is not None
        self.assertEqual(hit2.stems, ("Vocals", "other"))
        self.assertTrue(os.path.isfile(self.cache_path))
        with open(self.cache_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        key = csc.normalize_config_url(url)
        self.assertIn(key, payload["entries"])

    def test_failed_entry_returned_within_failure_ttl(self) -> None:
        url = "https://example.test/missing.yaml"
        csc.remember_stems(url, [], None, ok=False)
        hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertFalse(hit.ok)
        self.assertEqual(hit.stems, ())
        self.assertIsNone(hit.target_instrument)

    def test_catalogue_stems_disabled_by_env(self) -> None:
        url = "https://example.test/config.yaml"
        csc.remember_stems(url, ["Vocals"], None, ok=True)
        with mock.patch.dict(os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": "1"}):
            self.assertFalse(csc.catalogue_stems_enabled())
            self.assertIsNone(csc.lookup_stems(url))

    def test_expired_success_entry_returns_none(self) -> None:
        stale_url = "https://example.test/old.yaml"
        fresh_url = "https://example.test/fresh.yaml"
        stale_key = csc.normalize_config_url(stale_url)
        fresh_key = csc.normalize_config_url(fresh_url)
        stale_at = 1_000_000.0
        now = stale_at + csc._SUCCESS_TTL_SECONDS + 1
        payload = {
            "fetched_at": now,
            "entries": {
                stale_key: {
                    "stems": ["Vocals"],
                    "target_instrument": None,
                    "fetched_at": stale_at,
                    "ok": True,
                },
                fresh_key: {
                    "stems": ["other"],
                    "target_instrument": None,
                    "fetched_at": now - 3600,
                    "ok": True,
                },
            },
        }
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        csc._memory_entries = None
        with mock.patch.object(csc.time, "time", return_value=now):
            self.assertIsNone(csc.lookup_stems(stale_url))
            hit = csc.lookup_stems(fresh_url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.stems, ("other",))
        self.assertTrue(hit.ok)

    def test_enqueue_dedupes_and_worker_remembers(self) -> None:
        url = "https://example.test/dedupe.yaml?v=9"
        yaml_bytes = b"""
training:
  instruments:
    - Vocals
    - other
  target_instrument: Vocals
"""
        opens: list[str] = []
        done = threading.Event()

        def fake_urlopen(u: str) -> _FakeResponse:
            opens.append(u)
            return _FakeResponse(yaml_bytes)

        def on_notify() -> None:
            done.set()

        csc.subscribe(on_notify)
        with mock.patch.object(csc, "_urlopen", side_effect=fake_urlopen):
            csc.enqueue_missing([url, url])
            csc.ensure_worker_started()
            self.assertTrue(done.wait(timeout=2.0), "worker did not notify")
            self.assertTrue(
                _wait_until(lambda: csc.lookup_stems(url) is not None),
                "worker did not remember stems in time",
            )
        hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.stems, ("Vocals", "other"))
        self.assertEqual(hit.target_instrument, "Vocals")
        self.assertTrue(hit.ok)
        self.assertEqual(len(opens), 1)
        self.assertEqual(opens[0], csc.normalize_config_url(url))

    def test_notify_fires_once_per_batch(self) -> None:
        url_a = "https://example.test/batch-a.yaml"
        url_b = "https://example.test/batch-b.yaml"
        bodies = {
            url_a: b"training:\n  instruments: [Vocals]\n",
            url_b: b"training:\n  instruments: [drums]\n",
        }
        calls: list[int] = []
        notified = threading.Event()

        def on_notify() -> None:
            calls.append(1)
            notified.set()

        def fake_urlopen(u: str) -> _FakeResponse:
            return _FakeResponse(bodies[u])

        csc.subscribe(on_notify)
        with mock.patch.object(csc, "_urlopen", side_effect=fake_urlopen):
            csc.enqueue_missing([url_a, url_b])
            csc.ensure_worker_started()
            self.assertTrue(
                notified.wait(timeout=2.0),
                "subscriber was not notified",
            )
            self.assertTrue(
                _wait_until(
                    lambda: (
                        csc.lookup_stems(url_a) is not None
                        and csc.lookup_stems(url_b) is not None
                    )
                ),
                "worker did not finish both URLs",
            )
            # Brief settle window: must stay a single batch notify, not per-URL.
            time.sleep(0.05)
        self.assertEqual(len(calls), 1)

    def test_priority_url_fetched_before_bulk(self) -> None:
        bulk = "https://example.test/bulk.yaml"
        prio = "https://example.test/prio.yaml"
        body = b"training:\n  instruments: [Vocals]\n"
        order: list[str] = []
        done = threading.Event()
        opens = 0

        def fake_urlopen(u: str) -> _FakeResponse:
            nonlocal opens
            order.append(u)
            opens += 1
            if opens >= 2:
                done.set()
            return _FakeResponse(body)

        # One worker: both URLs would otherwise land in the same chunk and run
        # concurrently, making the assertion depend on thread scheduling rather
        # than on the priority queue.
        with mock.patch.object(csc, "_FETCH_WORKERS", 1):
            with mock.patch.object(csc, "_urlopen", side_effect=fake_urlopen):
                csc.enqueue_missing([bulk], priority=False)
                csc.enqueue_missing([prio], priority=True)
                csc.ensure_worker_started()
                self.assertTrue(done.wait(timeout=2.0), "worker did not finish both")
                self.assertTrue(
                    _wait_until(
                        lambda: (
                            csc.lookup_stems(bulk) is not None
                            and csc.lookup_stems(prio) is not None
                        )
                    )
                )
        self.assertEqual(order[0], prio)
        self.assertEqual(order[1], bulk)

    def test_remember_stems_is_thread_safe(self) -> None:
        """Concurrent writers must not corrupt the shared entry dict or its file.

        ``_FETCH_WORKERS`` > 1 means the pool calls this from several threads;
        an unguarded read-modify-write raises "dictionary changed size during
        iteration" out of json.dump, which _fetch_and_remember then miscodes as
        a failed fetch.
        """
        errors: list[BaseException] = []
        per_thread = 60
        threads_count = 4
        # Seed enough entries that each json.dump spends real time iterating
        # the shared dict — that iteration is the window the race lands in.
        seeded = 3000
        entries = csc._ensure_loaded()
        for i in range(seeded):
            entries[f"https://example.test/seed-{i}.yaml"] = {
                "stems": ["Vocals"],
                "target_instrument": None,
                "fetched_at": time.time(),
                "ok": True,
            }

        def writer(n: int) -> None:
            try:
                for i in range(per_thread):
                    csc.remember_stems(
                        f"https://example.test/t{n}-{i}.yaml", ["Vocals"], None, ok=True
                    )
            except BaseException as exc:  # noqa: BLE001 - recorded for assertion
                errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=(n,)) for n in range(threads_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10.0)

        self.assertEqual([repr(e) for e in errors], [])
        for n in range(threads_count):
            for i in range(per_thread):
                self.assertIsNotNone(
                    csc.lookup_stems(f"https://example.test/t{n}-{i}.yaml"),
                    f"entry t{n}-{i} missing from memory cache",
                )
        with open(self.cache_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(
            len(payload["entries"]),
            seeded + threads_count * per_thread,
            "on-disk cache lost entries to interleaved writes",
        )

    def test_priority_promotes_already_queued_url(self) -> None:
        """A bulk-queued URL re-enqueued with priority must jump the queue.

        The Download Center bulk-enqueues the whole catalogue on open, then
        re-enqueues visible rows as filters change. Without promotion every
        later call is a no-op and prioritization never takes effect.
        """
        bulk = [f"https://example.test/bulk-{i}.yaml" for i in range(4)]
        promoted = bulk[3]
        body = b"training:\n  instruments: [Vocals]\n"
        order: list[str] = []
        done = threading.Event()

        def fake_urlopen(u: str) -> _FakeResponse:
            order.append(u)
            if len(order) >= len(bulk):
                done.set()
            return _FakeResponse(body)

        with mock.patch.object(csc, "_FETCH_WORKERS", 1):
            with mock.patch.object(csc, "_urlopen", side_effect=fake_urlopen):
                csc.enqueue_missing(bulk, priority=False)
                csc.enqueue_missing([promoted], priority=True)
                csc.ensure_worker_started()
                self.assertTrue(done.wait(timeout=3.0), "worker did not finish")
        self.assertEqual(order[0], promoted)
        self.assertEqual(sorted(order), sorted(bulk), "a URL was fetched twice")

    def test_notify_fires_per_chunk_not_only_at_drain(self) -> None:
        """Subscribers hear about finished chunks while work remains.

        Notifying only after the queue drains means the first stem subtitle
        appears only once the last YAML in the catalogue has been fetched,
        which cancels out prioritizing visible rows.
        """
        urls = [f"https://example.test/chunk-{i}.yaml" for i in range(4)]
        body = b"training:\n  instruments: [Vocals]\n"
        calls: list[int] = []

        def on_notify() -> None:
            calls.append(1)

        def fake_urlopen(u: str) -> _FakeResponse:
            return _FakeResponse(body)

        csc.subscribe(on_notify)
        with mock.patch.object(csc, "_urlopen", side_effect=fake_urlopen):
            csc.enqueue_missing(urls)
            csc.ensure_worker_started()
            self.assertTrue(
                _wait_until(
                    lambda: all(csc.lookup_stems(u) is not None for u in urls),
                    timeout=3.0,
                ),
                "worker did not finish all URLs",
            )
            time.sleep(0.05)
        # 4 URLs at _FETCH_WORKERS=2 is two chunks, so two notifies.
        self.assertEqual(len(calls), 2)

    def test_batch_reuses_one_thread_pool(self) -> None:
        """Thread creation must not scale with the number of URLs.

        A fresh executor per chunk spawned ~N threads to fetch N URLs; one pool
        per batch caps it at _FETCH_WORKERS.
        """
        urls = [f"https://example.test/pool-{i}.yaml" for i in range(8)]
        body = b"training:\n  instruments: [Vocals]\n"
        names: set[str] = set()
        lock = threading.Lock()

        def fake_urlopen(u: str) -> _FakeResponse:
            with lock:
                names.add(threading.current_thread().name)
            return _FakeResponse(body)

        with mock.patch.object(csc, "_urlopen", side_effect=fake_urlopen):
            csc.enqueue_missing(urls)
            csc.ensure_worker_started()
            self.assertTrue(
                _wait_until(
                    lambda: all(csc.lookup_stems(u) is not None for u in urls),
                    timeout=3.0,
                ),
                "worker did not finish all URLs",
            )
        self.assertLessEqual(
            len(names), csc._FETCH_WORKERS, f"spawned {len(names)} threads for {len(urls)} URLs"
        )

    def test_worker_concurrency_at_most_two(self) -> None:
        urls = [f"https://example.test/conc-{i}.yaml" for i in range(6)]
        body = b"training:\n  instruments: [Vocals]\n"
        lock = threading.Lock()
        active = 0
        max_seen = 0
        done = threading.Event()
        finished = 0

        def fake_urlopen(u: str) -> _FakeResponse:
            nonlocal active, max_seen, finished
            with lock:
                active += 1
                max_seen = max(max_seen, active)
            time.sleep(0.04)
            with lock:
                active -= 1
                finished += 1
                if finished >= len(urls):
                    done.set()
            return _FakeResponse(body)

        with mock.patch.object(csc, "_urlopen", side_effect=fake_urlopen):
            csc.enqueue_missing(urls)
            csc.ensure_worker_started()
            self.assertTrue(done.wait(timeout=3.0), "worker did not finish")
        self.assertLessEqual(max_seen, 2)
        self.assertGreaterEqual(max_seen, 2)

    def test_changed_config_url_does_not_inherit_stems(self) -> None:
        csc.remember_stems("https://example.test/old.yaml", ["Vocals"], "Vocals", ok=True)
        self.assertIsNone(csc.lookup_stems("https://example.test/new.yaml"))

    def test_offline_policy_does_not_start_worker(self) -> None:
        from core.access_policy import access_policy

        with access_policy(allow_network=False, allow_metadata_writes=False):
            with mock.patch("threading.Thread.start", side_effect=AssertionError("thread")):
                csc.ensure_worker_started()


if __name__ == "__main__":
    unittest.main()
