from __future__ import annotations

import json
import os
import tempfile
import unittest

from core.json_store import content_digest, write_json_if_unchanged


class JsonDigestTests(unittest.TestCase):
    def test_write_skipped_when_digest_changes(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "p.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"a": 1}\n')
            digest = content_digest(path)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"a": 2}\n')
            self.assertFalse(write_json_if_unchanged(path, {"a": 3}, digest))
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.loads(handle.read())["a"], 2)

    def test_write_proceeds_when_digest_matches(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "p.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"a": 1}\n')
            digest = content_digest(path)
            self.assertTrue(write_json_if_unchanged(path, {"a": 3}, digest))
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.loads(handle.read())["a"], 3)

    def test_missing_file_matches_empty_digest(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "missing.json")
            self.assertEqual(content_digest(path), "")
            self.assertTrue(write_json_if_unchanged(path, {"ok": True}, ""))
            self.assertTrue(os.path.isfile(path))


class WriteTextAtomicTests(unittest.TestCase):
    """Generated documents must never be left truncated by a failed write."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-text-atomic-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_writes_the_text(self) -> None:
        from core.json_store import write_text_atomic

        path = os.path.join(self.tmp, "doc.md")
        write_text_atomic(path, "# Title\nbody\n")
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "# Title\nbody\n")

    def test_creates_missing_parent_directories(self) -> None:
        from core.json_store import write_text_atomic

        path = os.path.join(self.tmp, "nested", "deep", "doc.md")
        write_text_atomic(path, "x")
        self.assertTrue(os.path.isfile(path))

    def test_leaves_no_temporary_file_behind(self) -> None:
        from core.json_store import write_text_atomic

        path = os.path.join(self.tmp, "doc.md")
        write_text_atomic(path, "x")
        self.assertEqual(os.listdir(self.tmp), ["doc.md"])

    def test_a_failed_write_leaves_the_previous_content_intact(self) -> None:
        """The whole point: a crash mid-write must not truncate the document."""
        from unittest import mock

        from core.json_store import write_text_atomic

        path = os.path.join(self.tmp, "doc.md")
        write_text_atomic(path, "good content\n")
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_text_atomic(path, "replacement that never lands")
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "good content\n")
        self.assertEqual(os.listdir(self.tmp), ["doc.md"])
