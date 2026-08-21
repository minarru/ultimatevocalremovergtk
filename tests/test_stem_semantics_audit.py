"""CLI tests for the stem-semantics audit script. No network -- catalogue
walking and config fetching are patched; only the script's own logic
(sorting, table rendering, JSON output shape) is under test."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from typing import Any, Optional
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location(
    "stem_semantics_audit",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "stem_semantics_audit.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
stem_semantics_audit = importlib.util.module_from_spec(_SPEC)
sys.modules["stem_semantics_audit"] = stem_semantics_audit
_SPEC.loader.exec_module(stem_semantics_audit)


def _entry(entry_id: str, *, curated: bool, karaoke: bool = True) -> "stem_semantics_audit.StemSemanticsEntry":
    return stem_semantics_audit.StemSemanticsEntry(
        entry_id=entry_id,
        label=entry_id,
        stems=["vocals", "other"],
        is_karaoke=karaoke,
        is_karaoke_curated=curated,
        is_bv=False,
        buckets=["Vocals", "Instrumental"],
    )


class RenderTableTests(unittest.TestCase):
    def test_includes_confidence_and_buckets(self) -> None:
        table = stem_semantics_audit.render_table([_entry("a", curated=True)])
        self.assertIn("a", table)
        self.assertIn("curated", table)
        self.assertIn("Vocals", table)

    def test_marks_errors(self) -> None:
        entry = stem_semantics_audit.StemSemanticsEntry(
            entry_id="bad", label="bad", error="config unreadable"
        )
        table = stem_semantics_audit.render_table([entry])
        self.assertIn("ERROR", table)
        self.assertIn("config unreadable", table)


class IterEntriesProgressTests(unittest.TestCase):
    def test_reports_each_target_to_stderr(self) -> None:
        from types import SimpleNamespace

        targets = [
            SimpleNamespace(entry_id="first", label="First Model"),
            SimpleNamespace(entry_id="second", label="Second Model"),
        ]
        with patch(
            "scripts.model_tool_support.iter_catalogue_targets", return_value=iter(targets)
        ), patch.object(
            stem_semantics_audit, "_curated_hash_table", return_value={}
        ), patch.object(
            stem_semantics_audit,
            "_entry_for_target",
            side_effect=[_entry("first", curated=False), _entry("second", curated=True)],
        ), redirect_stderr(io.StringIO()) as stderr:
            entries = list(stem_semantics_audit._iter_entries(show_progress=True))

        self.assertEqual([entry.entry_id for entry in entries], ["first", "second"])
        progress = stderr.getvalue()
        self.assertIn("[1/2] first: First Model", progress)
        self.assertIn("[2/2] second: Second Model", progress)


class MainCliTests(unittest.TestCase):
    def test_json_output_is_written_to_the_given_path(self) -> None:
        entries = [_entry("guessed", curated=False), _entry("curated", curated=True)]
        with patch.object(stem_semantics_audit, "_iter_entries", return_value=iter(entries)):
            with tempfile.TemporaryDirectory() as tmp:
                json_path = os.path.join(tmp, "out.json")
                exit_code = stem_semantics_audit.main(["--json", json_path])
                self.assertEqual(exit_code, 0)
                with open(json_path) as f:
                    data = json.load(f)
                self.assertEqual(len(data), 2)
                self.assertIn("is_karaoke_curated", data[0])

    def test_guessed_confidence_sorted_first(self) -> None:
        entries = [_entry("curated", curated=True), _entry("guessed", curated=False)]
        with patch.object(stem_semantics_audit, "_iter_entries", return_value=iter(entries)):
            with tempfile.TemporaryDirectory() as tmp:
                json_path = os.path.join(tmp, "out.json")
                stem_semantics_audit.main(["--json", json_path])
                with open(json_path) as f:
                    data = json.load(f)
                self.assertEqual(data[0]["entry_id"], "guessed")
                self.assertEqual(data[1]["entry_id"], "curated")

    def test_progress_is_enabled_by_default_and_quiet_can_disable_it(self) -> None:
        with patch.object(
            stem_semantics_audit, "_iter_entries", return_value=iter([])
        ) as mocked:
            stem_semantics_audit.main([])
            # Assert the flag under test, not the whole signature: pinning every
            # kwarg makes this fail whenever an unrelated option is added.
            self.assertTrue(mocked.call_args.kwargs["show_progress"])

        with patch.object(
            stem_semantics_audit, "_iter_entries", return_value=iter([])
        ) as mocked:
            stem_semantics_audit.main(["--quiet"])
            self.assertFalse(mocked.call_args.kwargs["show_progress"])

    def test_keyboard_interrupt_exits_130_without_writing_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "out.json")
            with patch.object(
                stem_semantics_audit,
                "_iter_entries",
                side_effect=KeyboardInterrupt,
            ), redirect_stderr(io.StringIO()) as stderr:
                exit_code = stem_semantics_audit.main(["--json", json_path])
            self.assertEqual(exit_code, 130)
            self.assertFalse(os.path.exists(json_path))
            self.assertIn("interrupted", stderr.getvalue().lower())

    def test_json_replacement_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "out.json")
            with open(json_path, "w") as handle:
                handle.write("old")
            stem_semantics_audit._write_json(
                json_path, [_entry("new", curated=True)]
            )
            with open(json_path) as handle:
                data = json.load(handle)
            self.assertEqual(data[0]["entry_id"], "new")
            self.assertFalse(os.path.exists(f"{json_path}.part"))


class RemoteCheckpointHashTests(unittest.TestCase):
    """_remote_checkpoint_hash must never touch real network -- these patch
    scripts.model_probe's range-fetch helpers at their source."""

    def test_hashes_the_tail_of_a_remote_file(self) -> None:
        import hashlib

        tail = b"x" * (10000 * 1024)
        with patch("scripts.model_tool_support.remote_size", return_value=len(tail)), patch(
            "scripts.model_tool_support.http_range_reader",
            return_value=lambda start, end: tail[start:end],
        ):
            result = stem_semantics_audit._remote_checkpoint_hash("https://example.test/model.ckpt")
        self.assertEqual(result.digest, hashlib.md5(tail).hexdigest())
        self.assertEqual(result.status, "ok")

    def test_hashes_the_whole_file_when_smaller_than_the_tail_span(self) -> None:
        import hashlib

        whole = b"y" * 512
        with patch("scripts.model_tool_support.remote_size", return_value=len(whole)), patch(
            "scripts.model_tool_support.http_range_reader",
            return_value=lambda start, end: whole[start:end],
        ):
            result = stem_semantics_audit._remote_checkpoint_hash("https://example.test/small.ckpt")
        self.assertEqual(result.digest, hashlib.md5(whole).hexdigest())
        self.assertEqual(result.status, "ok")

    def test_fetch_failure_is_reported_not_silently_dropped(self) -> None:
        with patch("scripts.model_tool_support.remote_size", side_effect=OSError("boom")):
            result = stem_semantics_audit._remote_checkpoint_hash("https://example.test/model.ckpt")
        self.assertEqual(result.digest, "")
        self.assertEqual(result.status, "fetch_failed")
        self.assertIn("boom", result.error)

    def test_missing_url_is_distinct_from_a_failed_fetch(self) -> None:
        result = stem_semantics_audit._remote_checkpoint_hash("")
        self.assertEqual(result.digest, "")
        self.assertEqual(result.status, "no_url")


class HashStatusTests(unittest.TestCase):
    """A guess made without evidence must not look like a guess made against it."""

    class _Target:
        entry_id = "e1"
        label = "Some Model"
        config_url = "https://example.test/c.yaml"
        checkpoint_url = "https://example.test/m.ckpt"
        is_bv_model = False

    def _entry(self, lookup: Any, curated_table: Optional[dict] = None):
        with patch.object(
            stem_semantics_audit, "_remote_checkpoint_hash", return_value=lookup
        ), patch("scripts.model_tool_support.fetch_config", return_value="/tmp/c.yaml"), patch(
            "scripts.model_tool_support.cache_dir", return_value="/tmp"
        ), patch(
            "core.model_data.load_mdx_c_config",
            return_value={"training": {"instruments": ["vocals", "other"]}},
        ):
            return stem_semantics_audit._entry_for_target(
                self._Target(), curated_table or {}
            )

    def test_fetched_hash_absent_from_curated_metadata_is_unmatched(self) -> None:
        entry = self._entry(stem_semantics_audit.HashLookup(digest="abc", status="ok"))
        self.assertEqual(entry.hash_status, "unmatched")

    def test_fetched_hash_present_in_curated_metadata_is_matched(self) -> None:
        entry = self._entry(
            stem_semantics_audit.HashLookup(digest="abc", status="ok"),
            curated_table={"abc": {"is_karaoke": True}},
        )
        self.assertEqual(entry.hash_status, "matched")

    def test_failed_fetch_is_not_reported_as_unmatched(self) -> None:
        entry = self._entry(
            stem_semantics_audit.HashLookup(status="fetch_failed", error="timed out")
        )
        self.assertEqual(entry.hash_status, "fetch_failed")
        self.assertIn("timed out", entry.hash_error)

    def test_missing_checkpoint_url_is_its_own_status(self) -> None:
        entry = self._entry(stem_semantics_audit.HashLookup(status="no_url"))
        self.assertEqual(entry.hash_status, "no_url")

    def test_table_shows_hash_status_so_evidence_is_visible(self) -> None:
        entry = stem_semantics_audit.StemSemanticsEntry(
            entry_id="e1", label="M", stems=["vocals"], hash_status="fetch_failed"
        )
        self.assertIn("fetch_failed", stem_semantics_audit.render_table([entry]))


class HashCacheTests(unittest.TestCase):
    """Repeated audits must not re-fetch ~10MB per entry."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-hashcache-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, "hashes.json")

    def test_a_successful_lookup_is_served_from_cache(self) -> None:
        cache = stem_semantics_audit.HashCache(self.path)
        cache.put("https://x/m.ckpt", stem_semantics_audit.HashLookup(digest="abc", status="ok"))
        cache.save()

        reloaded = stem_semantics_audit.HashCache(self.path)
        hit = reloaded.get("https://x/m.ckpt")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.digest, "abc")
        self.assertEqual(hit.status, "ok")

    def test_a_failed_fetch_is_not_cached(self) -> None:
        """One bad network day must not poison every later report."""
        cache = stem_semantics_audit.HashCache(self.path)
        cache.put(
            "https://x/m.ckpt",
            stem_semantics_audit.HashLookup(status="fetch_failed", error="timeout"),
        )
        cache.save()
        self.assertIsNone(stem_semantics_audit.HashCache(self.path).get("https://x/m.ckpt"))

    def test_different_urls_do_not_share_an_entry(self) -> None:
        cache = stem_semantics_audit.HashCache(self.path)
        cache.put("https://a/m.ckpt", stem_semantics_audit.HashLookup(digest="aaa", status="ok"))
        cache.put("https://b/m.ckpt", stem_semantics_audit.HashLookup(digest="bbb", status="ok"))
        cache.save()
        reloaded = stem_semantics_audit.HashCache(self.path)
        a = reloaded.get("https://a/m.ckpt")
        b = reloaded.get("https://b/m.ckpt")
        assert a is not None and b is not None
        self.assertEqual((a.digest, b.digest), ("aaa", "bbb"))

    def test_a_corrupt_cache_file_is_ignored_not_fatal(self) -> None:
        with open(self.path, "w") as handle:
            handle.write("{not json")
        self.assertIsNone(stem_semantics_audit.HashCache(self.path).get("https://x/m.ckpt"))

    def test_records_carry_the_fetch_time(self) -> None:
        cache = stem_semantics_audit.HashCache(self.path)
        cache.put("https://x/m.ckpt", stem_semantics_audit.HashLookup(digest="abc", status="ok"))
        cache.save()
        with open(self.path) as handle:
            payload = json.load(handle)
        record = next(iter(payload.values()))
        self.assertIn("fetched_at", record)
        self.assertGreater(record["fetched_at"], 0)

    def test_the_hash_helper_consults_the_cache_before_fetching(self) -> None:
        from unittest import mock

        cache = stem_semantics_audit.HashCache(self.path)
        cache.put("https://x/m.ckpt", stem_semantics_audit.HashLookup(digest="abc", status="ok"))
        with mock.patch(
            "scripts.model_tool_support.checkpoint_tail_hash",
            side_effect=AssertionError("fetched despite a cache hit"),
        ):
            result = stem_semantics_audit._remote_checkpoint_hash("https://x/m.ckpt", cache=cache)
        self.assertEqual(result.digest, "abc")

    def test_a_miss_fetches_and_populates_the_cache(self) -> None:
        from unittest import mock

        cache = stem_semantics_audit.HashCache(self.path)
        with mock.patch(
            "scripts.model_tool_support.checkpoint_tail_hash", return_value="def"
        ):
            result = stem_semantics_audit._remote_checkpoint_hash("https://y/m.ckpt", cache=cache)
        self.assertEqual(result.digest, "def")
        hit = cache.get("https://y/m.ckpt")
        assert hit is not None
        self.assertEqual(hit.digest, "def")


class SummaryCountsTests(unittest.TestCase):
    def _entry(self, **kwargs: Any):
        base = dict(entry_id="e", label="L")
        base.update(kwargs)
        return stem_semantics_audit.StemSemanticsEntry(**base)

    def test_counts_confidence_and_hash_status(self) -> None:
        entries = [
            self._entry(is_karaoke_curated=True, hash_status="matched"),
            self._entry(is_karaoke_curated=False, hash_status="unmatched"),
            self._entry(is_karaoke_curated=False, hash_status="fetch_failed"),
            self._entry(is_karaoke_curated=False, hash_status="no_url"),
            self._entry(error="bad config"),
        ]
        text = stem_semantics_audit.render_summary(entries)
        self.assertIn("5 entries", text)
        self.assertIn("1 curated", text)
        self.assertIn("1 fetch_failed", text)
        self.assertIn("1 no_url", text)
        self.assertIn("1 config error", text)

    def test_summary_is_printed_after_the_table(self) -> None:
        entries = [self._entry(is_karaoke_curated=True, hash_status="matched")]
        self.assertIn("1 entries", stem_semantics_audit.render_summary(entries))


class SelectionTests(unittest.TestCase):
    """--only and --limit make a targeted review possible."""

    class _T:
        def __init__(self, entry_id: str, label: str) -> None:
            self.entry_id = entry_id
            self.label = label
            self.config_url = "https://x/c.yaml"
            self.checkpoint_url = "https://x/m.ckpt"
            self.is_bv_model = False

    def _targets(self):
        return [
            self._T("mel_karaoke", "MelBand Karaoke"),
            self._T("bs_vocals", "BS Vocals"),
            self._T("scnet_4stem", "SCNet 4-stem"),
        ]

    def test_select_targets_filters_by_substring(self) -> None:
        picked = stem_semantics_audit.select_targets(self._targets(), only="karaoke")
        self.assertEqual([t.entry_id for t in picked], ["mel_karaoke"])

    def test_select_targets_matches_the_label_too(self) -> None:
        picked = stem_semantics_audit.select_targets(self._targets(), only="SCNet")
        self.assertEqual([t.entry_id for t in picked], ["scnet_4stem"])

    def test_select_targets_is_case_insensitive(self) -> None:
        picked = stem_semantics_audit.select_targets(self._targets(), only="KARAOKE")
        self.assertEqual([t.entry_id for t in picked], ["mel_karaoke"])

    def test_limit_truncates(self) -> None:
        picked = stem_semantics_audit.select_targets(self._targets(), limit=2)
        self.assertEqual(len(picked), 2)

    def test_only_and_limit_compose(self) -> None:
        picked = stem_semantics_audit.select_targets(
            self._targets(), only="e", limit=1
        )
        self.assertEqual(len(picked), 1)

    def test_no_selection_returns_everything(self) -> None:
        self.assertEqual(len(stem_semantics_audit.select_targets(self._targets())), 3)

    def test_flags_exist(self) -> None:
        args = stem_semantics_audit.build_parser().parse_args(
            ["--only", "kara", "--limit", "5", "--no-cache"]
        )
        self.assertEqual(args.only, "kara")
        self.assertEqual(args.limit, 5)
        self.assertTrue(args.no_cache)

    def test_cache_is_on_by_default(self) -> None:
        self.assertFalse(stem_semantics_audit.build_parser().parse_args([]).no_cache)


class CuratedHashTableTests(unittest.TestCase):
    def test_merges_vr_and_mdx_hash_tables(self) -> None:
        def fake_load(path: str) -> dict:
            if "VR_Models" in path:
                return {"vrhash": {"is_karaoke": True}}
            return {"mdxhash": {"is_karaoke": False}}

        with patch("core.model_data.load_model_hash_data", side_effect=fake_load):
            table = stem_semantics_audit._curated_hash_table()
        self.assertEqual(table["vrhash"], {"is_karaoke": True})
        self.assertEqual(table["mdxhash"], {"is_karaoke": False})

    def test_missing_table_file_does_not_crash(self) -> None:
        with patch("core.model_data.load_model_hash_data", side_effect=FileNotFoundError):
            table = stem_semantics_audit._curated_hash_table()
        self.assertEqual(table, {})


class EntryForTargetCuratedLookupTests(unittest.TestCase):
    """_entry_for_target must resolve curated status through the checkpoint
    hash, not the mvsepless catalogue entry -- that's the bug this fix
    addresses."""

    def _target(self, *, label: str) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(
            entry_id="e1",
            label=label,
            config_url="https://example.test/c.yaml",
            checkpoint_url="https://example.test/w.ckpt",
        )

    def test_matched_checkpoint_hash_reports_curated(self) -> None:
        target = self._target(label="Some Model")
        with patch(
            "scripts.model_tool_support.fetch_config", return_value="/tmp/fake.yaml"
        ), patch(
            "core.model_data.load_mdx_c_config",
            return_value={"training": {"instruments": ["vocals", "other"]}},
        ), patch.object(
            stem_semantics_audit,
            "_remote_checkpoint_hash",
            return_value=stem_semantics_audit.HashLookup(digest="curatedhash", status="ok"),
        ):
            entry = stem_semantics_audit._entry_for_target(
                target, curated_table={"curatedhash": {"is_karaoke": True}}
            )
        self.assertTrue(entry.is_karaoke)
        self.assertTrue(entry.is_karaoke_curated)

    def test_unmatched_checkpoint_hash_falls_back_to_name_guess(self) -> None:
        target = self._target(label="Karaoke Extractor")
        with patch(
            "scripts.model_tool_support.fetch_config", return_value="/tmp/fake.yaml"
        ), patch(
            "core.model_data.load_mdx_c_config",
            return_value={"training": {"instruments": ["vocals", "other"]}},
        ), patch.object(
            stem_semantics_audit,
            "_remote_checkpoint_hash",
            return_value=stem_semantics_audit.HashLookup(digest="unknownhash", status="ok"),
        ):
            entry = stem_semantics_audit._entry_for_target(target, curated_table={})
        self.assertTrue(entry.is_karaoke)
        self.assertFalse(entry.is_karaoke_curated)


if __name__ == "__main__":
    unittest.main()
