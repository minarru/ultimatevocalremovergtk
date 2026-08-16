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
            self.assertEqual(json.loads(open(path, encoding="utf-8").read())["a"], 2)

    def test_write_proceeds_when_digest_matches(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "p.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"a": 1}\n')
            digest = content_digest(path)
            self.assertTrue(write_json_if_unchanged(path, {"a": 3}, digest))
            self.assertEqual(json.loads(open(path, encoding="utf-8").read())["a"], 3)

    def test_missing_file_matches_empty_digest(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "missing.json")
            self.assertEqual(content_digest(path), "")
            self.assertTrue(write_json_if_unchanged(path, {"ok": True}, ""))
            self.assertTrue(os.path.isfile(path))
