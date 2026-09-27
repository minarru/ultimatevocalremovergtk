"""Deduplication reports which kept row each dropped duplicate belongs to."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from core.catalog_dedupe import (
    CatalogueDuplicate,
    dedupe_download_catalogue,
    find_catalogue_duplicates,
)
from core.checkpoint_identities import parse_checkpoint_identities

_HF = "https://huggingface.co/owner/repo/resolve/main/"
_SHA = "a" * 64


def _identities(**sections: Any):
    document = {"schema_version": 1, "content_ids": {}, "rehosts": {}, "withdrawn": {}}
    document.update(sections)
    return patch(
        "core.checkpoint_identities.load_checkpoint_identities",
        return_value=parse_checkpoint_identities(document),
    )


class FindCatalogueDuplicatesTests(unittest.TestCase):
    def test_same_content_under_another_filename(self) -> None:
        catalogue = {
            "Kept": {"kept.ckpt": f"{_HF}kept.ckpt"},
            "Copy": {"copy.ckpt": f"{_HF}copy.ckpt"},
        }
        ids = {f"{_HF}kept.ckpt": _SHA, f"{_HF}copy.ckpt": _SHA}
        with _identities():
            kept, duplicates = find_catalogue_duplicates(catalogue, content_ids=ids)
        self.assertEqual(list(kept), ["Kept"])
        self.assertEqual(duplicates, {"Copy": CatalogueDuplicate("Kept", "sha256")})

    def test_reviewed_rehost(self) -> None:
        catalogue = {
            "Upstream": {"Orig.ckpt": "config.yaml"},
            "Rehost": {"copy.ckpt": f"{_HF}copy.ckpt"},
        }
        rehosts = {f"{_HF}copy.ckpt": {"checkpoint": "Orig.ckpt", "evidence": "reviewed"}}
        with _identities(rehosts=rehosts):
            _kept, duplicates = find_catalogue_duplicates(catalogue)
        self.assertEqual(duplicates, {"Rehost": CatalogueDuplicate("Upstream", "rehost")})

    def test_same_url(self) -> None:
        catalogue = {
            "Kept": {"model.ckpt": f"{_HF}model.ckpt"},
            "Mirror": {"model.ckpt": f"{_HF}model.ckpt"},
        }
        with _identities():
            _kept, duplicates = find_catalogue_duplicates(catalogue)
        self.assertEqual(duplicates["Mirror"].kept, "Kept")

    def test_checkpoint_name_differing_only_in_case(self) -> None:
        # Reached through the label check first: the evidence reported is the
        # exact key both rows share, not the check that happened to fire.
        catalogue = {
            "MDX23C Model: MDX23C_D1581": {"MDX23C_D1581.ckpt": "model_2_stem_061321.yaml"},
            "MDX23C D1581": {"mdx23c_d1581.ckpt": f"{_HF}mdx23c_d1581.ckpt"},
        }
        with _identities():
            _kept, duplicates = find_catalogue_duplicates(catalogue)
        self.assertEqual(
            duplicates,
            {"MDX23C D1581": CatalogueDuplicate("MDX23C Model: MDX23C_D1581", "checkpoint")},
        )

    def test_label_only_collision_is_not_a_duplicate(self) -> None:
        catalogue = {
            "Vocals by Someone": {"one.ckpt": f"{_HF}one.ckpt"},
            "Vocals by someone": {"two.ckpt": f"{_HF}two.ckpt"},
        }
        with _identities():
            kept, duplicates = find_catalogue_duplicates(catalogue)
        self.assertEqual(list(kept), ["Vocals by Someone"])
        self.assertEqual(duplicates, {})

    def test_evidence_pointing_at_two_kept_rows_is_ambiguous(self) -> None:
        catalogue = {
            "A": {"a.ckpt": f"{_HF}a.ckpt"},
            "B": {"b.ckpt": f"{_HF}b.ckpt"},
            # Same bytes as A, same filename as B.
            "C": {"b.ckpt": f"{_HF}c.ckpt"},
        }
        ids = {f"{_HF}a.ckpt": _SHA, f"{_HF}c.ckpt": _SHA}
        with _identities():
            _kept, duplicates = find_catalogue_duplicates(catalogue, content_ids=ids)
        self.assertNotIn("C", duplicates)

    def test_withdrawn_rows_are_not_duplicates(self) -> None:
        catalogue = {
            "Kept": {"model.ckpt": f"{_HF}model.ckpt"},
            "Bad": {"model.ckpt": f"{_HF}bad.ckpt"},
        }
        withdrawn = {f"{_HF}bad.ckpt": {"reason": "wrong bytes", "evidence": "reviewed"}}
        with _identities(withdrawn=withdrawn):
            _kept, duplicates = find_catalogue_duplicates(catalogue)
        self.assertEqual(duplicates, {})

    def test_kept_rows_match_dedupe_download_catalogue(self) -> None:
        catalogue = {
            "Kept": {"kept.ckpt": f"{_HF}kept.ckpt"},
            "Copy": {"copy.ckpt": f"{_HF}copy.ckpt"},
            "Mirror": {"kept.ckpt": f"{_HF}kept.ckpt"},
            "Other": {"other.ckpt": f"{_HF}other.ckpt"},
        }
        ids = {f"{_HF}kept.ckpt": _SHA, f"{_HF}copy.ckpt": _SHA}
        with _identities():
            kept, _duplicates = find_catalogue_duplicates(catalogue, content_ids=ids)
            self.assertEqual(kept, dedupe_download_catalogue(catalogue, content_ids=ids))


if __name__ == "__main__":
    unittest.main()
