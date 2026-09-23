"""Checked-in checkpoint identities for cross-source catalogue dedupe.

Content dedupe used to depend only on each user's download-size cache, which
fills a few dozen HEAD probes at a time: the Download Center drifted as it
warmed, and two catalogue regenerations could disagree about membership.
``bundled/checkpoint_identities.json`` makes the known answer reproducible:

* ``content_ids`` — normalized checkpoint URL → SHA-256, generated from the
  Hugging Face tree API by ``scripts/generate_models_catalogue.py --refresh``.
  A live content id in the size cache still wins, so a file replaced at the
  same URL is not deduped against its old bytes.
* ``rehosts`` — reviewed rows that copy an upstream checkpoint. Upstream rows
  carry no URL, so these collide on the upstream checkpoint *name* instead.
* ``withdrawn`` — reviewed rows whose checkpoint is not the model their label
  names. They never list, so the correctly labelled row wins.

Rehosts and withdrawn rows are hidden only from the listing: metadata is
built before dedupe, so an installed copy still resolves.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Mapping

from .catalog_dedupe import normalize_checkpoint_url
from .debug_log import debug

SCHEMA_VERSION = 1

BUNDLED_IDENTITIES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "bundled",
    "checkpoint_identities.json",
)


@dataclass(frozen=True)
class CheckpointIdentities:
    content_ids: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    rehosts: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    withdrawn: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


class CheckpointIdentitiesError(ValueError):
    pass


def _url_keyed(section: object, name: str) -> dict[str, Any]:
    if not isinstance(section, dict):
        raise CheckpointIdentitiesError(f"{name} must be an object")
    out: dict[str, Any] = {}
    for url, value in section.items():
        key = normalize_checkpoint_url(str(url))
        if not key.startswith("https://"):
            raise CheckpointIdentitiesError(f"{name}: {url!r} is not an https URL")
        if key != url:
            raise CheckpointIdentitiesError(f"{name}: {url!r} is not normalized")
        out[key] = value
    return out


def _reviewed_text(value: object, field_name: str, where: str) -> str:
    if not isinstance(value, dict):
        raise CheckpointIdentitiesError(f"{where} must be an object")
    text = value.get(field_name)
    if not isinstance(text, str) or not text.strip():
        raise CheckpointIdentitiesError(f"{where}.{field_name} must be a non-empty string")
    if not isinstance(value.get("evidence"), str) or not value["evidence"].strip():
        raise CheckpointIdentitiesError(f"{where}.evidence must be a non-empty string")
    return text


def parse_checkpoint_identities(payload: object) -> CheckpointIdentities:
    """Validate a decoded identity document."""
    if not isinstance(payload, dict):
        raise CheckpointIdentitiesError("document must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CheckpointIdentitiesError(f"schema_version must be {SCHEMA_VERSION}")
    content_ids = _url_keyed(payload.get("content_ids", {}), "content_ids")
    for url, sha in content_ids.items():
        if (
            not isinstance(sha, str)
            or len(sha) != 64
            or not all(c in "0123456789abcdef" for c in sha)
        ):
            raise CheckpointIdentitiesError(f"content_ids: {url!r} is not a SHA-256")
    rehosts = {
        url: _reviewed_text(value, "checkpoint", f"rehosts[{url!r}]")
        for url, value in _url_keyed(payload.get("rehosts", {}), "rehosts").items()
    }
    withdrawn = {
        url: _reviewed_text(value, "reason", f"withdrawn[{url!r}]")
        for url, value in _url_keyed(payload.get("withdrawn", {}), "withdrawn").items()
    }
    overlap = set(rehosts) & set(withdrawn)
    if overlap:
        raise CheckpointIdentitiesError(f"rows both rehosted and withdrawn: {sorted(overlap)}")
    return CheckpointIdentities(
        content_ids=MappingProxyType(content_ids),
        rehosts=MappingProxyType(rehosts),
        withdrawn=MappingProxyType(withdrawn),
    )


@lru_cache(maxsize=1)
def load_checkpoint_identities() -> CheckpointIdentities:
    """Return the bundled identities, or none when the file is missing or invalid.

    An unusable file degrades to the old cache-only dedupe rather than
    breaking catalogue loading.
    """
    try:
        with open(BUNDLED_IDENTITIES_FILE, "r", encoding="utf-8") as handle:
            return parse_checkpoint_identities(json.load(handle))
    except (OSError, ValueError) as error:
        debug("download", f"checkpoint identities unavailable: {error}")
        return CheckpointIdentities()


def clear_checkpoint_identities_cache() -> None:
    load_checkpoint_identities.cache_clear()
