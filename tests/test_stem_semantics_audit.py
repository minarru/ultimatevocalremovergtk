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
            "scripts.model_probe.iter_catalogue_targets", return_value=iter(targets)
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
            mocked.assert_called_once_with(guessed_only=False, show_progress=True)

        with patch.object(
            stem_semantics_audit, "_iter_entries", return_value=iter([])
        ) as mocked:
            stem_semantics_audit.main(["--quiet"])
            mocked.assert_called_once_with(guessed_only=False, show_progress=False)

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
        with patch("scripts.model_probe.remote_size", return_value=len(tail)), patch(
            "scripts.model_probe.http_range_reader",
            return_value=lambda start, end: tail[start:end],
        ):
            result = stem_semantics_audit._remote_checkpoint_hash("https://example.test/model.ckpt")
        self.assertEqual(result.digest, hashlib.md5(tail).hexdigest())
        self.assertEqual(result.status, "ok")

    def test_hashes_the_whole_file_when_smaller_than_the_tail_span(self) -> None:
        import hashlib

        whole = b"y" * 512
        with patch("scripts.model_probe.remote_size", return_value=len(whole)), patch(
            "scripts.model_probe.http_range_reader",
            return_value=lambda start, end: whole[start:end],
        ):
            result = stem_semantics_audit._remote_checkpoint_hash("https://example.test/small.ckpt")
        self.assertEqual(result.digest, hashlib.md5(whole).hexdigest())
        self.assertEqual(result.status, "ok")

    def test_fetch_failure_is_reported_not_silently_dropped(self) -> None:
        with patch("scripts.model_probe.remote_size", side_effect=OSError("boom")):
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
        ), patch("scripts.model_probe._fetch_config", return_value="/tmp/c.yaml"), patch(
            "scripts.model_probe._cache_dir", return_value="/tmp"
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
            "scripts.model_probe._fetch_config", return_value="/tmp/fake.yaml"
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
            "scripts.model_probe._fetch_config", return_value="/tmp/fake.yaml"
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
