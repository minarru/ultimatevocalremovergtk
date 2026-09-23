"""Refresh ``bundled/checkpoint_identities.json`` from Hugging Face.

The table's ``content_ids`` are generated: one Hub tree listing per
repository yields every LFS file's SHA-256 without downloading a byte. The
reviewed ``rehosts`` and ``withdrawn`` sections are carried over untouched.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import quote, unquote, urlsplit

from core.catalog_dedupe import normalize_checkpoint_url
from core.checkpoint_identities import (
    BUNDLED_IDENTITIES_FILE,
    SCHEMA_VERSION,
    CheckpointIdentities,
    clear_checkpoint_identities_cache,
    parse_checkpoint_identities,
)
from core.json_store import write_text_atomic

_HF_HOST = "huggingface.co"
_TREE_API = "https://huggingface.co/api/models/{repo}/tree/{revision}?recursive=true"
_NEXT_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel="?next"?')


def _urlopen(request: str | urllib.request.Request) -> Any:
    from core import mdx_config_fetch

    return mdx_config_fetch._urlopen(request)


def hf_resolve_parts(url: str) -> Optional[Tuple[str, str, str]]:
    """``(repo, revision, path)`` for a Hugging Face ``resolve/`` URL."""
    parts = urlsplit(url)
    if parts.netloc != _HF_HOST:
        return None
    segments = unquote(parts.path).strip("/").split("/")
    if len(segments) < 5 or segments[2] != "resolve":
        return None
    return f"{segments[0]}/{segments[1]}", segments[3], "/".join(segments[4:])


def _fetch_tree(repo: str, revision: str) -> Dict[str, str]:
    """Map every LFS file path in ``repo@revision`` to its SHA-256."""
    url: Optional[str] = _TREE_API.format(repo=repo, revision=quote(revision, safe=""))
    shas: Dict[str, str] = {}
    while url:
        with _urlopen(url) as response:
            entries = json.load(response)
            link = response.headers.get("Link") or ""
        for entry in entries:
            lfs = entry.get("lfs") if isinstance(entry, dict) else None
            if entry.get("type") == "file" and isinstance(lfs, dict) and lfs.get("oid"):
                shas[str(entry["path"])] = str(lfs["oid"])
        match = _NEXT_LINK_RE.search(link)
        url = match.group(1) if match else None
    return shas


def fetch_content_ids(urls: Iterable[str]) -> Tuple[Dict[str, str], List[str]]:
    """Return ``(content_ids, unresolved)`` for the Hugging Face URLs given.

    ``unresolved`` lists Hugging Face URLs whose file the tree did not list
    (a removed file, or a repository the Hub refused to list).
    """
    wanted: Dict[Tuple[str, str], Dict[str, str]] = defaultdict(dict)
    for url in urls:
        key = normalize_checkpoint_url(url)
        parts = hf_resolve_parts(key)
        if parts is not None:
            repo, revision, path = parts
            wanted[(repo, revision)][path] = key
    content_ids: Dict[str, str] = {}
    unresolved: List[str] = []
    for (repo, revision), paths in sorted(wanted.items()):
        try:
            tree = _fetch_tree(repo, revision)
        except Exception:
            unresolved.extend(paths.values())
            continue
        for path, key in paths.items():
            sha = tree.get(path)
            if sha:
                content_ids[key] = sha
            else:
                unresolved.append(key)
    return content_ids, sorted(unresolved)


def missing_content_ids(urls: Iterable[str], identities: CheckpointIdentities) -> List[str]:
    """Hugging Face checkpoint URLs the bundled table does not cover."""
    missing = {
        key
        for key in (normalize_checkpoint_url(url) for url in urls)
        if hf_resolve_parts(key) is not None and key not in identities.content_ids
    }
    return sorted(missing)


def render_identity_document(document: Mapping[str, Any], content_ids: Mapping[str, str]) -> str:
    """Serialize ``document`` with ``content_ids`` replaced, keys sorted."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "content_ids": dict(sorted(content_ids.items())),
        "rehosts": dict(sorted(dict(document.get("rehosts") or {}).items())),
        "withdrawn": dict(sorted(dict(document.get("withdrawn") or {}).items())),
    }
    parse_checkpoint_identities(payload)
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


class IdentityTableShrinkError(RuntimeError):
    """A refresh would drop too many known identities to be trusted."""


#: Same floor as the catalogue publication guard: losing more than a tenth of
#: the known identities is far likelier a failed listing than real removals.
_SHRINK_FLOOR = 0.9


def prepare_identity_table(
    urls: Iterable[str], *, path: str = BUNDLED_IDENTITIES_FILE, allow_shrink: bool = False
) -> Tuple[str, List[str]]:
    """Prepare the table's ``content_ids`` without changing any files.

    Returns ``(text, unresolved)``. A URL the tree could not resolve keeps
    its previous identity rather than silently losing it to one bad listing,
    and a result keeping under 90% of the previous identities raises
    :class:`IdentityTableShrinkError` unless ``allow_shrink``.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            previous_text: Optional[str] = handle.read()
        document: Dict[str, Any] = json.loads(previous_text)
    except FileNotFoundError:
        document, previous_text = {}, None
    url_list = list(urls)
    fetched, unresolved = fetch_content_ids(url_list)
    previous = dict(document.get("content_ids") or {})
    for key in unresolved:
        if key in previous:
            fetched[key] = previous[key]
    if previous and not allow_shrink and len(fetched) < _SHRINK_FLOOR * len(previous):
        raise IdentityTableShrinkError(
            f"{len(fetched)} checkpoint identities against {len(previous)} previously"
        )
    return render_identity_document(document, fetched), unresolved


def refresh_identity_table(
    urls: Iterable[str], *, path: str = BUNDLED_IDENTITIES_FILE, allow_shrink: bool = False
) -> Tuple[bool, List[str]]:
    """Publish a standalone identity refresh; the generator stages it in its bundle."""
    text, unresolved = prepare_identity_table(urls, path=path, allow_shrink=allow_shrink)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            previous_text = handle.read()
    except FileNotFoundError:
        previous_text = None
    if text == previous_text:
        return False, unresolved
    write_text_atomic(path, text)
    clear_checkpoint_identities_cache()
    return True, unresolved
