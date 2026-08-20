"""Tests for download size formatting and job estimates."""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import core.download_sizes as download_sizes
from core.download_sizes import (
    _CACHE_TTL_SECONDS,
    _IDENTITY_HEAD_CAP,
    content_ids_from_cache,
    describe_download_size,
    format_download_size,
    prefetch_remote_sizes,
    prefetch_same_size_identity,
)


class FormatDownloadSizeTests(unittest.TestCase):
    def test_bytes(self) -> None:
        self.assertEqual(format_download_size(512), "512 B")

    def test_megabytes(self) -> None:
        self.assertEqual(format_download_size(245 * 1024 * 1024), "245 MB")

    def test_gigabytes(self) -> None:
        self.assertEqual(format_download_size(int(1.2 * 1024**3)), "1.2 GB")

    def test_unknown(self) -> None:
        self.assertEqual(format_download_size(None), "unknown")


class DescribeDownloadSizeTests(unittest.TestCase):
    def test_single_known_file(self) -> None:
        with patch("core.download_sizes.fetch_remote_size", return_value=100 * 1024 * 1024):
            with tempfile.TemporaryDirectory() as tmp:
                jobs = [("https://example.com/model.onnx", os.path.join(tmp, "model.onnx"))]
                self.assertEqual(describe_download_size(jobs), "100 MB")

    def test_already_downloaded(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        try:
            jobs = [("https://example.com/model.onnx", path)]
            self.assertEqual(describe_download_size(jobs), "Already downloaded")
        finally:
            os.remove(path)

    def test_unknown_sizes(self) -> None:
        with patch("core.download_sizes.fetch_remote_size", return_value=None):
            with tempfile.TemporaryDirectory() as tmp:
                jobs = [("https://example.com/a.onnx", os.path.join(tmp, "a.onnx"))]
                self.assertEqual(describe_download_size(jobs), "Size unknown")

    def test_multi_file_shows_aggregate_size_only(self) -> None:
        with patch("core.download_sizes.fetch_remote_size", return_value=50 * 1024 * 1024):
            with tempfile.TemporaryDirectory() as tmp:
                jobs = [
                    ("https://example.com/a.ckpt", os.path.join(tmp, "a.ckpt")),
                    ("https://example.com/b.yaml", os.path.join(tmp, "b.yaml")),
                ]
                self.assertEqual(describe_download_size(jobs), "100 MB")


class PrefetchRemoteSizesTests(unittest.TestCase):
    def test_skips_fresh_cache_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            url = "https://example.com/model.onnx"
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump({url: {"size": 1024, "fetched_at": time.time()}}, handle)
            with patch("core.download_sizes._cache_path", return_value=cache_path):
                with patch("core.download_sizes._head_remote_meta") as head:
                    stats = prefetch_remote_sizes([url])
            self.assertEqual(stats, {"total": 1, "fresh": 1, "fetched": 0, "failed": 0})
            head.assert_not_called()

    def test_refetches_expired_cache_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            url = "https://example.com/model.onnx"
            stale_at = time.time() - _CACHE_TTL_SECONDS - 60
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump({url: {"size": 1024, "fetched_at": stale_at}}, handle)
            with patch("core.download_sizes._cache_path", return_value=cache_path):
                with patch(
                    "core.download_sizes._head_remote_meta",
                    return_value=(2048, None),
                ) as head:
                    stats = prefetch_remote_sizes([url])
            self.assertEqual(stats, {"total": 1, "fresh": 0, "fetched": 1, "failed": 0})
            head.assert_called_once_with(url)
            with open(cache_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload[url]["size"], 2048)

    def test_stores_etag_from_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            url = "https://example.com/model.ckpt"
            with patch("core.download_sizes._cache_path", return_value=cache_path):
                with patch(
                    "core.download_sizes._head_remote_meta",
                    return_value=(2048, "etag-abc"),
                ):
                    stats = prefetch_remote_sizes([url])
            self.assertEqual(stats["fetched"], 1)
            with open(cache_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload[url]["etag"], "etag-abc")

    def test_fresh_size_without_etag_not_refetched_by_prefetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            url = "https://example.com/model.ckpt"
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump({url: {"size": 1024, "fetched_at": time.time()}}, handle)
            with patch("core.download_sizes._cache_path", return_value=cache_path):
                with patch("core.download_sizes._head_remote_meta") as head:
                    stats = prefetch_remote_sizes([url])
            self.assertEqual(stats, {"total": 1, "fresh": 1, "fetched": 0, "failed": 0})
            head.assert_not_called()

    def test_content_ids_from_cache_require_trusted_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            url = "https://example.com/a.ckpt?download=true"
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "https://example.com/a.ckpt": {
                            "size": 10,
                            "etag": "e1",
                            "content_id": "hf-oid",
                            "fetched_at": time.time(),
                        }
                    },
                    handle,
                )
            with patch("core.download_sizes._cache_path", return_value=cache_path):
                ids = content_ids_from_cache([url])
            self.assertEqual(ids.get("https://example.com/a.ckpt"), "hf-oid")

    def test_ordinary_etag_is_not_a_content_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            url = "https://example.com/a.ckpt"
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {url: {"size": 10, "etag": "weak-or-ordinary", "fetched_at": time.time()}},
                    handle,
                )
            with patch("core.download_sizes._cache_path", return_value=cache_path):
                self.assertEqual(content_ids_from_cache([url]), {})

    def test_same_size_identity_heads_only_cohort_missing_etag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            a = "https://example.com/a.ckpt"
            b = "https://example.com/b.ckpt"
            c = "https://example.com/unique.ckpt"
            now = time.time()
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        a: {"size": 100, "fetched_at": now},
                        b: {"size": 100, "fetched_at": now},
                        c: {"size": 200, "fetched_at": now},
                    },
                    handle,
                )
            with patch("core.download_sizes._cache_path", return_value=cache_path):
                with patch(
                    "core.download_sizes._head_remote_meta",
                    side_effect=[(100, "etag-a", "oid-a"), (100, "etag-a", "oid-a")],
                ) as head:
                    stats = prefetch_same_size_identity([a, b, c])
                self.assertEqual(stats["fetched"], 2)
                self.assertEqual(head.call_count, 2)
                ids = content_ids_from_cache([a, b, c])
                self.assertEqual(ids[a], "oid-a")
                self.assertEqual(ids[b], "oid-a")

    def test_prefetch_fetches_multiple_stale_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            urls = [f"https://example.com/{i}.ckpt" for i in range(5)]
            with patch("core.download_sizes._cache_path", return_value=cache_path):
                with patch(
                    "core.download_sizes._head_remote_meta",
                    return_value=(1024, "e"),
                ) as head:
                    with patch.dict(os.environ, {"UVR_SIZE_HEAD_WORKERS": "4"}):
                        stats = prefetch_remote_sizes(urls)
            self.assertEqual(stats["fetched"], 5)
            self.assertEqual(head.call_count, 5)

    def test_prefetch_stops_submitting_once_shutdown_requested(self) -> None:
        """Interpreter exit must not wait on the whole queue of pending HEADs.

        ThreadPoolExecutor's atexit hook joins its workers *after* the queue
        drains, so submitting every stale URL up front makes quitting the app
        block on hundreds of 20s-timeout requests. Submitting in bounded waves
        and checking the shutdown flag between them caps that wait at one wave.
        """
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            urls = [f"https://example.com/{i}.ckpt" for i in range(20)]
            calls: list[str] = []

            def fake_head(url: str):
                calls.append(url)
                download_sizes.request_shutdown()
                return (1024, "e")

            try:
                with patch("core.download_sizes._cache_path", return_value=cache_path):
                    with patch(
                        "core.download_sizes._head_remote_meta", side_effect=fake_head
                    ):
                        with patch.dict(os.environ, {"UVR_SIZE_HEAD_WORKERS": "2"}):
                            prefetch_remote_sizes(urls)
            finally:
                download_sizes._shutdown.clear()

        self.assertLessEqual(
            len(calls), 2, f"kept submitting after shutdown: {len(calls)} HEADs"
        )

    def test_identity_pass_stops_submitting_once_shutdown_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            now = time.time()
            payload = {
                f"https://example.com/{i}.ckpt": {"size": 100, "fetched_at": now}
                for i in range(20)
            }
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            calls: list[str] = []

            def fake_head(url: str):
                calls.append(url)
                download_sizes.request_shutdown()
                return (100, "etag")

            try:
                with patch("core.download_sizes._cache_path", return_value=cache_path):
                    with patch(
                        "core.download_sizes._head_remote_meta", side_effect=fake_head
                    ):
                        with patch.dict(os.environ, {"UVR_SIZE_HEAD_WORKERS": "2"}):
                            prefetch_same_size_identity(list(payload))
            finally:
                download_sizes._shutdown.clear()

        self.assertLessEqual(
            len(calls), 2, f"kept submitting after shutdown: {len(calls)} HEADs"
        )

    def test_identity_pass_targets_oldest_entries_first(self) -> None:
        """The capped window must follow staleness, not URL order.

        Sorting by URL always picks the same alphabetically-first slice, so a
        host that never returns an ETag keeps those URLs in the candidate
        cohort forever and permanently blocks everything after them.
        """
        total = _IDENTITY_HEAD_CAP + 10
        now = time.time()
        # Alphabetically-first URLs are the *freshest*, so URL order and
        # staleness order disagree.
        payload = {
            f"https://example.com/{i:03d}.ckpt": {"size": 100, "fetched_at": now - i}
            for i in range(total)
        }
        oldest = {
            f"https://example.com/{i:03d}.ckpt" for i in range(total - _IDENTITY_HEAD_CAP, total)
        }
        calls: list[str] = []

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            with patch("core.download_sizes._cache_path", return_value=cache_path):
                with patch(
                    "core.download_sizes._head_remote_meta",
                    side_effect=lambda url: (calls.append(url), (100, None))[1],
                ):
                    prefetch_same_size_identity(list(payload))

        self.assertEqual(set(calls), oldest)

    def test_identity_pass_rotates_across_calls(self) -> None:
        """A URL that yields no etag must not block the tail on the next pass."""
        total = _IDENTITY_HEAD_CAP + 10
        now = time.time()
        payload = {
            f"https://example.com/{i:03d}.ckpt": {"size": 100, "fetched_at": now - i}
            for i in range(total)
        }
        first: list[str] = []
        second: list[str] = []

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            with patch("core.download_sizes._cache_path", return_value=cache_path):
                # Neither pass yields an etag, so every URL stays a candidate.
                with patch(
                    "core.download_sizes._head_remote_meta",
                    side_effect=lambda url: (first.append(url), (100, None))[1],
                ):
                    prefetch_same_size_identity(list(payload))
                with patch(
                    "core.download_sizes._head_remote_meta",
                    side_effect=lambda url: (second.append(url), (100, None))[1],
                ):
                    prefetch_same_size_identity(list(payload))

        never_tried = set(payload) - set(first)
        self.assertEqual(len(never_tried), 10)
        self.assertTrue(
            never_tried.issubset(set(second)),
            "second pass repeated the first window instead of rotating",
        )

    def test_identity_pass_caps_heads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            now = time.time()
            payload = {
                f"https://example.com/{i}.ckpt": {"size": 100, "fetched_at": now}
                for i in range(_IDENTITY_HEAD_CAP + 10)
            }
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            with patch("core.download_sizes._cache_path", return_value=cache_path):
                with patch(
                    "core.download_sizes._head_remote_meta",
                    return_value=(100, "etag"),
                ) as head:
                    stats = prefetch_same_size_identity(list(payload))
            self.assertEqual(stats["total"], _IDENTITY_HEAD_CAP)
            self.assertEqual(head.call_count, _IDENTITY_HEAD_CAP)


class RequestUrlSizeCoalesceTests(unittest.TestCase):
    def test_duplicate_urls_share_one_fetch(self) -> None:
        import threading

        from core.download_sizes import request_url_size

        started = threading.Event()
        release = threading.Event()
        calls = {"n": 0}

        def fetch(url: str) -> int:
            calls["n"] += 1
            started.set()
            release.wait(timeout=2)
            return 123

        seen: list[int | None] = []
        with patch("core.download_sizes.fetch_remote_size", side_effect=fetch), patch(
            "core.download_sizes._cache_get", return_value=None
        ):
            request_url_size("https://example.com/a.ckpt", lambda _u, size: seen.append(size))
            self.assertTrue(started.wait(timeout=2))
            request_url_size("https://example.com/a.ckpt", lambda _u, size: seen.append(size))
            release.set()
            deadline = time.time() + 2
            while len(seen) < 2 and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(seen, [123, 123])


if __name__ == "__main__":
    unittest.main()
