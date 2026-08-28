"""Unit tests for the catalogue YAML stem cache (disk + background worker)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from email.message import Message
from typing import Callable
from unittest import mock

from yaml.constructor import ConstructorError

import core.catalogue_stem_cache as csc

_SCHEMA_2_ENTRY_KEYS = {
    "stems",
    "target_instrument",
    "content_sha256",
    "etag",
    "last_modified",
    "fetched_at",
    "checked_at",
    "last_error",
}


class _FakeResponse:
    def __init__(
        self,
        data: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._data = data
        self.status = status
        self.headers = headers or {}

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


def _request_url(request: urllib.request.Request) -> str:
    return request.full_url


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

    def test_parse_accepts_reviewed_python_tuple_but_rejects_unsafe_tags(self) -> None:
        stems, target = csc.parse_stems_from_yaml_bytes(
            b"training:\n  instruments: !!python/tuple [Vocals, Other]\n"
            b"  target_instrument: Vocals\n"
        )
        self.assertEqual(stems, ["Vocals", "Other"])
        self.assertEqual(target, "Vocals")

        with self.assertRaises(ConstructorError):
            csc.parse_stems_from_yaml_bytes(
                b"training: !!python/object/apply:os.system ['echo unsafe']\n"
            )

    def test_parse_rejects_documents_without_nonempty_training_instruments(self) -> None:
        for payload in (b"- Vocals\n", b"training: {}\n", b"training:\n  instruments: []\n"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                csc.parse_stems_from_yaml_bytes(payload)

    def test_remember_and_lookup_round_trip(self) -> None:
        url = "https://example.test/config.yaml?v=1"
        digest = "a" * 64
        csc.remember_stems(
            url,
            ["Vocals", "other"],
            "Vocals",
            content_sha256=digest,
            ok=True,
        )
        hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.stems, ("Vocals", "other"))
        self.assertEqual(hit.target_instrument, "Vocals")
        self.assertEqual(hit.content_sha256, digest)
        self.assertTrue(hit.ok)
        # Query string stripped for cache key.
        hit2 = csc.lookup_stems("https://example.test/config.yaml")
        self.assertIsNotNone(hit2)
        assert hit2 is not None
        self.assertEqual(hit2.stems, ("Vocals", "other"))
        self.assertTrue(os.path.isfile(self.cache_path))
        with open(self.cache_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["schema_version"], 2)
        key = csc.normalize_config_url(url)
        self.assertIn(key, payload["entries"])
        self.assertEqual(set(payload["entries"][key]), _SCHEMA_2_ENTRY_KEYS)

    def test_legacy_cache_is_read_without_rewrite_then_normalized_on_mutation(self) -> None:
        url = "https://example.test/legacy.yaml?source=old"
        original = {
            "fetched_at": 100.0,
            "entries": {
                csc.normalize_config_url(url): {
                    "stems": ["Vocals", "Other"],
                    "target_instrument": "Vocals",
                    "content_sha256": "c" * 64,
                    "fetched_at": time.time(),
                    "ok": True,
                }
            },
        }
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump(original, handle)
        csc._memory_entries = None

        hit = csc.lookup_stems(url)

        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.usable)
        with open(self.cache_path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), original)

        csc.remember_stems("https://example.test/new.yaml", ["Drums"], None, ok=True)
        with open(self.cache_path, encoding="utf-8") as handle:
            normalized = json.load(handle)
        self.assertEqual(normalized["schema_version"], 2)
        self.assertNotIn("ok", normalized["entries"][csc.normalize_config_url(url)])
        self.assertEqual(
            normalized["entries"][csc.normalize_config_url(url)]["checked_at"],
            original["entries"][csc.normalize_config_url(url)]["fetched_at"],
        )

    def test_success_ttl_uses_checked_at_and_cold_failure_uses_failure_ttl(self) -> None:
        now = 10_000_000.0
        success = "https://example.test/success.yaml"
        failure = "https://example.test/failure.yaml"
        csc.remember_stems(success, ["Vocals"], None, ok=True)
        csc.remember_stems(failure, [], None, ok=False, error_kind="network")
        entries = csc._ensure_loaded()
        entries[csc.normalize_config_url(success)]["checked_at"] = (
            now - csc._SUCCESS_TTL_SECONDS + 1
        )
        entries[csc.normalize_config_url(failure)]["checked_at"] = (
            now - csc._FAILURE_TTL_SECONDS + 1
        )
        with mock.patch.object(csc.time, "time", return_value=now):
            self.assertTrue(csc.lookup_stems(success).usable)  # type: ignore[union-attr]
            self.assertFalse(csc.lookup_stems(failure).usable)  # type: ignore[union-attr]
        entries[csc.normalize_config_url(success)]["checked_at"] = (
            now - csc._SUCCESS_TTL_SECONDS - 1
        )
        entries[csc.normalize_config_url(failure)]["checked_at"] = (
            now - csc._FAILURE_TTL_SECONDS - 1
        )
        with mock.patch.object(csc.time, "time", return_value=now):
            expired_success = csc.lookup_stems(success)
            self.assertIsNotNone(expired_success)
            assert expired_success is not None
            self.assertTrue(expired_success.usable)
            self.assertTrue(expired_success.revalidation_due)
            self.assertIsNone(csc.lookup_stems(failure))

    def test_failed_revalidation_preserves_last_known_good_evidence(self) -> None:
        url = "https://example.test/stale.yaml"
        csc.remember_stems(
            url,
            ["Vocals", "Other"],
            "Vocals",
            content_sha256="a" * 64,
            ok=True,
            etag='"v1"',
        )

        csc.remember_stems(url, [], None, ok=False, error_kind="network", error_message="down")

        with mock.patch.object(csc.time, "time", return_value=12.0):
            hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.ok)
        self.assertTrue(hit.stale)
        self.assertEqual(hit.stems, ("Vocals", "Other"))
        self.assertEqual(hit.content_sha256, "a" * 64)
        self.assertEqual(hit.etag, '"v1"')
        self.assertIn("down", hit.warning)

    def test_expired_success_remains_usable_and_becomes_due(self) -> None:
        now = 10_000_000.0
        url = "https://example.test/expired-success.yaml"
        csc.remember_stems(url, ["Vocals", "Instrumental"], "Vocals", ok=True)
        entry = csc._ensure_loaded()[csc.normalize_config_url(url)]
        entry["checked_at"] = now - csc._SUCCESS_TTL_SECONDS - 1

        with mock.patch.object(csc.time, "time", return_value=now):
            hit = csc.lookup_stems(url)

        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.usable)
        self.assertTrue(hit.stale)
        self.assertTrue(hit.revalidation_due)

    def test_retained_lkg_failure_uses_failure_retry_ttl(self) -> None:
        now = 10_000_000.0
        url = "https://example.test/lkg-retry.yaml"
        csc.remember_stems(url, ["Vocals", "Instrumental"], "Vocals", ok=True)
        csc.remember_stems(url, [], None, ok=False, error_kind="network", error_message="down")
        entry = csc._ensure_loaded()[csc.normalize_config_url(url)]

        entry["checked_at"] = now - csc._FAILURE_TTL_SECONDS + 1
        with mock.patch.object(csc.time, "time", return_value=now):
            before_retry = csc.lookup_stems(url)
        self.assertIsNotNone(before_retry)
        assert before_retry is not None
        self.assertTrue(before_retry.usable)
        self.assertFalse(before_retry.revalidation_due)

        entry["checked_at"] = now - csc._FAILURE_TTL_SECONDS - 1
        with mock.patch.object(csc.time, "time", return_value=now):
            after_retry = csc.lookup_stems(url)
        self.assertIsNotNone(after_retry)
        assert after_retry is not None
        self.assertTrue(after_retry.usable)
        self.assertTrue(after_retry.revalidation_due)

    def test_force_revalidation_sends_validators_and_304_keeps_body(self) -> None:
        url = "https://example.test/conditional.yaml"
        csc.remember_stems(
            url,
            ["Vocals"],
            "Vocals",
            content_sha256="b" * 64,
            ok=True,
            etag='"v1"',
            last_modified="Wed, 27 Aug 2026 12:00:00 GMT",
        )
        requests: list[urllib.request.Request] = []

        def fake_urlopen(request: urllib.request.Request) -> _FakeResponse:
            requests.append(request)
            return _FakeResponse(b"", status=304)

        with mock.patch.object(csc, "_urlopen", side_effect=fake_urlopen):
            csc._fetch_and_remember(url, force=True)

        request = requests[0]
        self.assertEqual(request.get_header("If-none-match"), '"v1"')
        self.assertEqual(
            request.get_header("If-modified-since"),
            "Wed, 27 Aug 2026 12:00:00 GMT",
        )
        hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.stems, ("Vocals",))
        self.assertEqual(hit.content_sha256, "b" * 64)
        self.assertFalse(hit.stale)

    def test_http_error_304_advances_checked_at_without_replacing_evidence(self) -> None:
        url = "https://example.test/conditional-http-error.yaml"
        csc.remember_stems(url, ["Vocals"], None, content_sha256="d" * 64, ok=True)
        entry = csc._ensure_loaded()[csc.normalize_config_url(url)]
        entry["fetched_at"] = 10.0
        entry["checked_at"] = 11.0
        response = urllib.error.HTTPError(url, 304, "not modified", Message(), None)
        with (
            mock.patch.object(csc.time, "time", return_value=12.0),
            mock.patch.object(csc, "_urlopen", side_effect=response),
        ):
            self.assertTrue(csc._fetch_and_remember(url, force=True))
        with mock.patch.object(csc.time, "time", return_value=12.0):
            hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.fetched_at, 10.0)
        self.assertEqual(hit.checked_at, 12.0)
        self.assertEqual(hit.content_sha256, "d" * 64)

    def test_http_200_replaces_evidence_only_after_parse_and_digest_checks(self) -> None:
        url = "https://example.test/replace.yaml"
        old_body = b"training:\n  instruments: [Vocals]\n"
        csc.remember_stems(
            url,
            ["Vocals"],
            None,
            content_sha256=hashlib.sha256(old_body).hexdigest(),
            ok=True,
            etag='"old"',
        )
        new_body = b"training:\n  instruments: [Drums, Bass]\n  target_instrument: Drums\n"
        with mock.patch.object(
            csc,
            "_urlopen",
            return_value=_FakeResponse(new_body, headers={"ETag": '"new"'}),
        ):
            csc._fetch_and_remember(url, force=True)
        hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.stems, ("Drums", "Bass"))
        self.assertEqual(hit.target_instrument, "Drums")
        self.assertEqual(hit.content_sha256, hashlib.sha256(new_body).hexdigest())
        self.assertEqual(hit.etag, '"new"')

        with mock.patch.object(csc, "_urlopen", return_value=_FakeResponse(b"training: {}\n")):
            csc._fetch_and_remember(url, force=True)
        self.assertEqual(csc.lookup_stems(url).stems, ("Drums", "Bass"))  # type: ignore[union-attr]

    def test_revalidation_distinguishes_body_and_semantic_drift(self) -> None:
        url = "https://example.test/drift.yaml"
        body = b"training:\n  instruments: [Vocals]\n"
        csc.remember_stems(
            url,
            ["Vocals"],
            None,
            content_sha256=hashlib.sha256(body).hexdigest(),
            ok=True,
        )
        formatting_only = b"# republished\ntraining:\n  instruments: [Vocals]\n"
        with (
            mock.patch.object(csc, "_urlopen", return_value=_FakeResponse(formatting_only)),
            mock.patch.object(csc, "log_event") as log_event,
        ):
            csc._fetch_and_remember(url, force=True)
        same_fields = csc.lookup_stems(url)
        self.assertIsNotNone(same_fields)
        assert same_fields is not None
        self.assertEqual(
            set(csc._ensure_loaded()[csc.normalize_config_url(url)]), _SCHEMA_2_ENTRY_KEYS
        )
        with open(self.cache_path, encoding="utf-8") as handle:
            self.assertEqual(
                set(json.load(handle)["entries"][csc.normalize_config_url(url)]),
                _SCHEMA_2_ENTRY_KEYS,
            )
        self.assertTrue(
            any(
                call.args[1] == "catalogue_stem_evidence_drift" for call in log_event.call_args_list
            )
        )

        semantic = b"training:\n  instruments: [Drums]\n"
        with (
            mock.patch.object(csc, "_urlopen", return_value=_FakeResponse(semantic)),
            mock.patch.object(csc, "log_event") as log_event,
        ):
            csc._fetch_and_remember(url, force=True)
        changed_fields = csc.lookup_stems(url)
        self.assertIsNotNone(changed_fields)
        assert changed_fields is not None
        self.assertEqual(changed_fields.stems, ("Drums",))
        self.assertEqual(
            set(csc._ensure_loaded()[csc.normalize_config_url(url)]), _SCHEMA_2_ENTRY_KEYS
        )
        with open(self.cache_path, encoding="utf-8") as handle:
            self.assertEqual(
                set(json.load(handle)["entries"][csc.normalize_config_url(url)]),
                _SCHEMA_2_ENTRY_KEYS,
            )
        self.assertTrue(
            any(
                call.args[1] == "catalogue_stem_evidence_drift" for call in log_event.call_args_list
            )
        )

    def test_cold_failure_has_no_evidence_and_force_retries_expired_failure(self) -> None:
        url = "https://example.test/cold-failure.yaml"
        csc.remember_stems(url, [], None, ok=False, error_kind="network", error_message="offline")
        hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertFalse(hit.usable)
        self.assertEqual(hit.stems, ())
        self.assertEqual(hit.last_error.kind, "network")  # type: ignore[union-attr]
        self.assertGreater(hit.last_error.at, 0)  # type: ignore[union-attr]
        csc._ensure_loaded()[csc.normalize_config_url(url)]["checked_at"] = 0.0
        with mock.patch.object(
            csc, "_urlopen", return_value=_FakeResponse(b"training:\n  instruments: [Other]\n")
        ):
            csc._fetch_and_remember(url, force=True)
        self.assertEqual(csc.lookup_stems(url).stems, ("Other",))  # type: ignore[union-attr]

    def test_atomic_write_failure_preserves_previous_cache_file(self) -> None:
        first = "https://example.test/first.yaml"
        csc.remember_stems(first, ["Vocals"], None, ok=True)
        with open(self.cache_path, "rb") as handle:
            before = handle.read()
        with mock.patch.object(csc.os, "replace", side_effect=OSError("disk full")):
            csc.remember_stems("https://example.test/second.yaml", ["Drums"], None, ok=True)
        with open(self.cache_path, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_read_only_policy_never_writes_cache(self) -> None:
        from core.access_policy import access_policy

        with access_policy(
            allow_network=True,
            allow_metadata_writes=False,
            allow_cache_writes=False,
        ):
            csc.remember_stems("https://example.test/readonly.yaml", ["Vocals"], None, ok=True)
        self.assertFalse(os.path.exists(self.cache_path))

    def test_queued_read_only_policy_never_migrates_or_writes(self) -> None:
        """The executor must use the enqueuer's ContextVar policy, not defaults."""
        from core import paths
        from core.access_policy import access_policy

        url = "https://example.test/read-only-worker.yaml"
        read_only_path = os.path.join(self._tmp.name, "read-only-worker-cache.json")
        self._path_patch.stop()
        try:
            with (
                mock.patch.object(paths, "CATALOGUE_STEM_CACHE_FILE", read_only_path),
                mock.patch.object(
                    paths,
                    "migrate_cache_file",
                    side_effect=AssertionError("read-only worker migrated cache"),
                ),
                mock.patch.object(
                    csc,
                    "_urlopen",
                    return_value=_FakeResponse(b"training:\n  instruments: [Vocals]\n"),
                ),
            ):
                with access_policy(
                    allow_network=True,
                    allow_metadata_writes=False,
                    allow_cache_writes=False,
                ):
                    csc.enqueue_missing([url])
                    csc.ensure_worker_started()
                    self.assertTrue(
                        _wait_until(
                            lambda: (hit := csc.lookup_stems(url)) is not None and hit.usable
                        ),
                        "read-only queued worker did not retain in-memory evidence",
                    )
            self.assertFalse(os.path.exists(read_only_path))
            self.assertFalse(os.path.exists(f"{read_only_path}.tmp"))
        finally:
            self._path_patch.start()

    def test_force_and_priority_merge_for_both_enqueue_orders(self) -> None:
        url = "https://example.test/merged-duplicate.yaml"
        for first, second in (
            ({"priority": False, "force": True}, {"priority": True, "force": False}),
            ({"priority": True, "force": False}, {"priority": False, "force": True}),
        ):
            with self.subTest(first=first, second=second):
                csc.enqueue_missing([url], priority=first["priority"], force=first["force"])
                csc.enqueue_missing([url], priority=second["priority"], force=second["force"])
                first_item = csc._url_queue.get_nowait()
                items = csc._drain_queued_items(first_item)
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0][0], 0)
                self.assertTrue(items[0][3])
                csc._reset_worker_state_for_tests()

    def test_failed_entry_returned_within_failure_ttl(self) -> None:
        url = "https://example.test/missing.yaml"
        csc.remember_stems(url, [], None, ok=False)
        hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertFalse(hit.ok)
        self.assertEqual(hit.stems, ())
        self.assertIsNone(hit.target_instrument)

    def test_invalid_cached_content_digest_is_not_evidence(self) -> None:
        url = "https://example.test/invalid-digest.yaml"
        csc.remember_stems(
            url,
            ["Vocals", "other"],
            "Vocals",
            content_sha256="A" * 64,
            ok=True,
        )

        hit = csc.lookup_stems(url)

        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.content_sha256, "")

    def test_catalogue_stems_disabled_by_env(self) -> None:
        url = "https://example.test/config.yaml"
        csc.remember_stems(url, ["Vocals"], None, ok=True)
        with mock.patch.dict(os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": "1"}):
            self.assertFalse(csc.catalogue_stems_enabled())
            self.assertIsNone(csc.lookup_stems(url))

    def test_expired_success_entry_retains_lkg_and_is_due(self) -> None:
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
            stale = csc.lookup_stems(stale_url)
            hit = csc.lookup_stems(fresh_url)
        self.assertIsNotNone(stale)
        assert stale is not None
        self.assertTrue(stale.usable)
        self.assertTrue(stale.revalidation_due)
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

        def fake_urlopen(u: urllib.request.Request) -> _FakeResponse:
            opens.append(_request_url(u))
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
        self.assertEqual(hit.content_sha256, hashlib.sha256(yaml_bytes).hexdigest())
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

        def fake_urlopen(u: urllib.request.Request) -> _FakeResponse:
            return _FakeResponse(bodies[_request_url(u)])

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
                        csc.lookup_stems(url_a) is not None and csc.lookup_stems(url_b) is not None
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

        def fake_urlopen(u: urllib.request.Request) -> _FakeResponse:
            nonlocal opens
            order.append(_request_url(u))
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

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(threads_count)]
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

        def fake_urlopen(u: urllib.request.Request) -> _FakeResponse:
            order.append(_request_url(u))
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

        def fake_urlopen(u: urllib.request.Request) -> _FakeResponse:
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

        def fake_urlopen(u: urllib.request.Request) -> _FakeResponse:
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

        def fake_urlopen(u: urllib.request.Request) -> _FakeResponse:
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
