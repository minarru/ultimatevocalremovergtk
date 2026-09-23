"""Bundled checkpoint identities: validation, dedupe, cache merge, refresh."""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from typing import Any
from unittest.mock import patch

# Load the script path before top-level catalogue imports (one module identity).
# isort: off
from tests import generator_fixtures as _fixtures  # noqa: F401

# isort: on
from catalogue import identities as catalogue_identities

from core import checkpoint_identities
from core.catalog_dedupe import dedupe_download_catalogue
from core.checkpoint_identities import (
    CheckpointIdentities,
    CheckpointIdentitiesError,
    load_checkpoint_identities,
    parse_checkpoint_identities,
)
from core.download_sizes import prefetch_same_size_identity, trusted_content_ids_from_cache

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_HF = "https://huggingface.co/owner/repo/resolve/main/"
_EVIDENCE = {"evidence": "reviewed"}


def _document(**sections: Any) -> dict[str, Any]:
    return {"schema_version": 1, "content_ids": {}, "rehosts": {}, "withdrawn": {}, **sections}


class ParseCheckpointIdentitiesTests(unittest.TestCase):
    def test_valid_document(self) -> None:
        parsed = parse_checkpoint_identities(
            _document(
                content_ids={f"{_HF}a.ckpt": _SHA_A},
                rehosts={f"{_HF}copy.ckpt": {"checkpoint": "orig.ckpt", **_EVIDENCE}},
                withdrawn={f"{_HF}bad.ckpt": {"reason": "wrong bytes", **_EVIDENCE}},
            )
        )
        self.assertEqual(parsed.content_ids[f"{_HF}a.ckpt"], _SHA_A)
        self.assertEqual(parsed.rehosts[f"{_HF}copy.ckpt"], "orig.ckpt")
        self.assertEqual(parsed.withdrawn[f"{_HF}bad.ckpt"], "wrong bytes")

    def test_rejects_malformed_documents(self) -> None:
        cases = {
            "schema": {**_document(), "schema_version": 2},
            "unnormalized url": _document(content_ids={f"{_HF}a.ckpt?download=true": _SHA_A}),
            "not a sha": _document(content_ids={f"{_HF}a.ckpt": "abc"}),
            "no evidence": _document(rehosts={f"{_HF}a.ckpt": {"checkpoint": "o.ckpt"}}),
            "overlap": _document(
                rehosts={f"{_HF}a.ckpt": {"checkpoint": "o.ckpt", **_EVIDENCE}},
                withdrawn={f"{_HF}a.ckpt": {"reason": "x", **_EVIDENCE}},
            ),
        }
        for name, payload in cases.items():
            with self.subTest(name):
                with self.assertRaises(CheckpointIdentitiesError):
                    parse_checkpoint_identities(payload)

    def test_invalid_bundled_file_degrades_to_no_identities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "checkpoint_identities.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"schema_version": 99}')
            with patch.object(checkpoint_identities, "BUNDLED_IDENTITIES_FILE", path):
                checkpoint_identities.clear_checkpoint_identities_cache()
                self.addCleanup(checkpoint_identities.clear_checkpoint_identities_cache)
                self.assertEqual(load_checkpoint_identities(), CheckpointIdentities())

    def test_bundled_table_is_valid_and_covers_the_reviewed_rows(self) -> None:
        identities = load_checkpoint_identities()
        self.assertGreater(len(identities.content_ids), 400)
        self.assertEqual(len(identities.rehosts), 11)
        self.assertEqual(len(identities.withdrawn), 1)


class RehostDedupeTests(unittest.TestCase):
    def _identities(self) -> CheckpointIdentities:
        return parse_checkpoint_identities(
            _document(rehosts={f"{_HF}copy.ckpt": {"checkpoint": "Orig.ckpt", **_EVIDENCE}})
        )

    def test_rehost_collides_with_the_upstream_checkpoint_name(self) -> None:
        catalogue = {
            "Upstream": {"Orig.ckpt": "config.yaml"},
            "Rehost": {"copy.ckpt": f"{_HF}copy.ckpt"},
        }
        with patch(
            "core.checkpoint_identities.load_checkpoint_identities",
            return_value=self._identities(),
        ):
            self.assertEqual(list(dedupe_download_catalogue(catalogue)), ["Upstream"])

    def test_rehost_lists_when_the_upstream_row_is_gone(self) -> None:
        catalogue = {"Rehost": {"copy.ckpt": f"{_HF}copy.ckpt"}}
        with patch(
            "core.checkpoint_identities.load_checkpoint_identities",
            return_value=self._identities(),
        ):
            self.assertEqual(list(dedupe_download_catalogue(catalogue)), ["Rehost"])


class BundledContentIdMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_path = os.path.join(self._tmp.name, "download_size_cache.json")
        patcher = patch("core.download_sizes._cache_path", return_value=self.cache_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        identities = parse_checkpoint_identities(
            _document(content_ids={f"{_HF}a.ckpt": _SHA_A, f"{_HF}b.ckpt": _SHA_A})
        )
        loader = patch(
            "core.checkpoint_identities.load_checkpoint_identities", return_value=identities
        )
        loader.start()
        self.addCleanup(loader.stop)

    def _write_cache(self, payload: dict[str, Any]) -> None:
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_bundled_ids_apply_without_a_warm_cache(self) -> None:
        ids = trusted_content_ids_from_cache([f"{_HF}a.ckpt?download=true", f"{_HF}b.ckpt"])
        self.assertEqual(ids, {f"{_HF}a.ckpt": _SHA_A, f"{_HF}b.ckpt": _SHA_A})

    def test_live_content_id_overrides_the_bundled_one(self) -> None:
        self._write_cache({f"{_HF}a.ckpt": {"size": 1, "content_id": _SHA_B, "fetched_at": 0}})
        self.assertEqual(trusted_content_ids_from_cache([f"{_HF}a.ckpt"])[f"{_HF}a.ckpt"], _SHA_B)

    def test_prefetch_heads_a_new_twin_but_never_a_bundled_url(self) -> None:
        now = time.time()
        new = f"{_HF}new.ckpt"
        self._write_cache(
            {
                f"{_HF}a.ckpt": {"size": 100, "fetched_at": now},
                new: {"size": 100, "fetched_at": now},
            }
        )
        with patch(
            "core.download_sizes._head_remote_meta", return_value=(100, "etag", _SHA_A)
        ) as head:
            prefetch_same_size_identity([f"{_HF}a.ckpt", new])
        self.assertEqual([call.args[0] for call in head.call_args_list], [new])


class _Response(io.BytesIO):
    def __init__(self, payload: object, link: str = "") -> None:
        super().__init__(json.dumps(payload).encode())
        self.headers = {"Link": link} if link else {}


class RefreshIdentityTableTests(unittest.TestCase):
    def _tree_pages(self) -> dict[str, _Response]:
        first = "https://huggingface.co/api/models/owner/repo/tree/main?recursive=true"
        second = f"{first}&cursor=2"
        return {
            first: _Response(
                [{"type": "file", "path": "a.ckpt", "lfs": {"oid": _SHA_A}}],
                link=f'<{second}>; rel="next"',
            ),
            second: _Response(
                [
                    {"type": "file", "path": "dir/b.ckpt", "lfs": {"oid": _SHA_B}},
                    {"type": "file", "path": "config.yaml"},
                ]
            ),
        }

    def test_hf_resolve_parts(self) -> None:
        self.assertEqual(
            catalogue_identities.hf_resolve_parts(f"{_HF}dir/b%20c.ckpt"),
            ("owner/repo", "main", "dir/b c.ckpt"),
        )
        self.assertIsNone(catalogue_identities.hf_resolve_parts("https://github.com/o/r/x.ckpt"))

    def test_refresh_follows_pages_and_keeps_reviewed_sections(self) -> None:
        pages = self._tree_pages()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "checkpoint_identities.json")
            reviewed = {f"{_HF}gone.ckpt": {"checkpoint": "Orig.ckpt", **_EVIDENCE}}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    _document(content_ids={f"{_HF}gone.ckpt": _SHA_B}, rehosts=reviewed),
                    handle,
                )
            urls = [f"{_HF}a.ckpt?download=true", f"{_HF}dir/b.ckpt", f"{_HF}gone.ckpt"]
            with patch.object(catalogue_identities, "_urlopen", side_effect=pages.__getitem__):
                changed, unresolved = catalogue_identities.refresh_identity_table(urls, path=path)
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
        self.assertTrue(changed)
        # The file the tree no longer lists keeps its last known identity.
        self.assertEqual(unresolved, [f"{_HF}gone.ckpt"])
        self.assertEqual(
            document["content_ids"],
            {f"{_HF}a.ckpt": _SHA_A, f"{_HF}dir/b.ckpt": _SHA_B, f"{_HF}gone.ckpt": _SHA_B},
        )
        self.assertEqual(document["rehosts"], reviewed)

    def test_shrink_guard_preserves_previous_file_unless_explicitly_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "checkpoint_identities.json")
            original = json.dumps(_document(content_ids={f"{_HF}a.ckpt": _SHA_A}))
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(original)
            with patch.object(catalogue_identities, "fetch_content_ids", return_value=({}, [])):
                with self.assertRaises(catalogue_identities.IdentityTableShrinkError):
                    catalogue_identities.refresh_identity_table([], path=path)
                with open(path, encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), original)
                changed, unresolved = catalogue_identities.refresh_identity_table(
                    [], path=path, allow_shrink=True
                )
            self.assertTrue(changed)
            self.assertEqual(unresolved, [])
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["content_ids"], {})

    def test_missing_content_ids_reports_only_uncovered_hf_urls(self) -> None:
        identities = parse_checkpoint_identities(_document(content_ids={f"{_HF}a.ckpt": _SHA_A}))
        urls = [f"{_HF}a.ckpt", f"{_HF}new.ckpt", "https://github.com/o/r/x.ckpt"]
        self.assertEqual(
            catalogue_identities.missing_content_ids(urls, identities), [f"{_HF}new.ckpt"]
        )


if __name__ == "__main__":
    unittest.main()
