#!/usr/bin/env python3
"""Shared support for the model diagnostic scripts.

Checkpoint and catalogue plumbing used by both :mod:`scripts.model_probe` and
:mod:`scripts.stem_semantics_audit`. It lives here rather than inside one of
those CLIs so neither has to import the other's private helpers: this is the
factual, low-level layer -- remote byte ranges, checkpoint headers and tail
hashes, catalogue target resolution and cache identity -- with no opinion
about verdicts, reporting or separation.

Deliberately diagnostic-only. The application downloads whole checkpoints and
has no need to read a remote header, so none of this belongs in ``core``.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pickle
import struct
import sys
import zipfile
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def add_repo_to_path() -> None:
    """Make ``core`` / ``engines`` / ``ml`` importable when run as a script."""
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)


#: How much of a checkpoint's tail the UVR fingerprint covers.
_HASH_TAIL_BYTES = 10000 * 1024


#: ``read(start, end) -> bytes`` over a local file or an HTTP range request.
RangeReader = Callable[[int, int], bytes]

_SAFETENSORS_LEN_BYTES = 8

#: Enough to cover a zip end-of-central-directory record plus the directory of
#: a checkpoint with a few thousand tensors.
_ZIP_TAIL_BYTES = 256 * 1024

#: Keys a training checkpoint wraps its weights in.
_STATE_DICT_WRAPPERS = ("state_dict", "model_state_dict", "model", "weights")


def safetensors_header_span(head: bytes) -> Tuple[int, int]:
    """Return ``(start, end)`` byte offsets of a ``.safetensors`` JSON header.

    The first 8 bytes are a little-endian u64 header length, so this needs only
    that prefix to say which range to fetch next.
    """
    if len(head) < _SAFETENSORS_LEN_BYTES:
        raise ValueError("need at least 8 bytes to read a safetensors header length")
    (length,) = struct.unpack("<Q", head[:_SAFETENSORS_LEN_BYTES])
    return _SAFETENSORS_LEN_BYTES, _SAFETENSORS_LEN_BYTES + int(length)


def parse_safetensors_header(blob: bytes) -> List[str]:
    """Return the tensor names declared in a ``.safetensors`` header."""
    start, end = safetensors_header_span(blob)
    raw = blob[start:end]
    if len(raw) < end - start:
        raise ValueError("safetensors header truncated")
    try:
        header = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"safetensors header is not JSON: {exc}") from exc
    if not isinstance(header, dict):
        raise ValueError("safetensors header is not a JSON object")
    return [key for key in header if key != "__metadata__"]


class _AttrDict(dict):
    """A dict that tolerates attribute assignment.

    ``Module.state_dict()`` hangs ``_metadata`` off the OrderedDict instance, so
    the pickle carries a BUILD opcode that sets ``__dict__`` — which a plain
    ``dict`` rejects. Every real checkpoint hits this.
    """


class _StubUnpickler(pickle.Unpickler):
    """Rebuild a checkpoint's key structure without importing or executing anything.

    ``find_class`` never resolves a real symbol and ``persistent_load`` never
    touches storage, so the pickle's dict keys survive while every value
    collapses to an inert placeholder. That is all a key diff needs.
    """

    def find_class(self, module: str, name: str) -> Any:  # noqa: D102
        if (module, name) == ("collections", "OrderedDict"):
            return _AttrDict
        return lambda *args, **kwargs: None

    def persistent_load(self, pid: Any) -> Any:  # noqa: D102
        return None


def parse_torch_pickle_keys(data: bytes) -> List[str]:
    """Return the ``state_dict`` keys held in a torch ``data.pkl`` payload."""
    try:
        obj = _StubUnpickler(io.BytesIO(data)).load()
    except Exception as exc:  # noqa: BLE001 - any malformed pickle is a probe failure
        raise ValueError(f"could not read checkpoint pickle: {exc}") from exc
    return _keys_of_state_dict(obj)


def _keys_of_state_dict(obj: Any) -> List[str]:
    """Pull the weight keys out of a checkpoint object, unwrapping if needed."""
    if not isinstance(obj, dict):
        raise ValueError(f"checkpoint root is {type(obj).__name__}, not a dict")
    for wrapper in _STATE_DICT_WRAPPERS:
        inner = obj.get(wrapper)
        if isinstance(inner, dict) and inner:
            return [str(key) for key in inner]
    return [str(key) for key in obj]


def _data_pkl_name(archive: zipfile.ZipFile) -> str:
    """Name of the ``data.pkl`` member holding the checkpoint's key structure."""
    names = [name for name in archive.namelist() if name.endswith("data.pkl")]
    if not names:
        raise ValueError("zip has no data.pkl entry")
    return names[0]


class _TailFile(io.RawIOBase):
    """Seekable file-like view that pulls byte ranges on demand."""

    def __init__(self, read: RangeReader, size: int) -> None:
        self._read = read
        self._size = size
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        else:
            self._pos = self._size + offset
        return self._pos

    def tell(self) -> int:
        return self._pos

    def read(self, n: Optional[int] = -1) -> bytes:
        # ``None`` and a negative size both mean "to EOF" per RawIOBase.
        end = self._size if n is None or n < 0 else min(self._size, self._pos + n)
        if end <= self._pos:
            return b""
        chunk = self._read(self._pos, end)
        self._pos += len(chunk)
        return chunk


def torch_checkpoint_keys(read: RangeReader, size: int) -> List[str]:
    """Return a torch checkpoint's ``state_dict`` keys, reading only its header.

    ``read`` is a range reader over the checkpoint; zipfile seeks to the central
    directory and the ``data.pkl`` entry, so the tensor payload is never fetched.
    """
    try:
        with zipfile.ZipFile(_TailFile(read, size)) as archive:
            return parse_torch_pickle_keys(archive.read(_data_pkl_name(archive)))
    except zipfile.BadZipFile as exc:
        raise ValueError(
            f"not a zip archive (legacy torch pickle format?): {exc}"
        ) from exc


@dataclass
class CatalogueTarget:
    """A catalogue entry resolved to the URLs and metadata the probe needs."""

    entry_id: str
    label: str
    model_type: str = ""
    config_url: str = ""
    checkpoint_url: str = ""
    reason: str = ""
    is_bv_model: bool = False

    @property
    def config_name(self) -> str:
        from urllib.parse import unquote, urlparse

        return os.path.basename(unquote(urlparse(self.config_url).path))


def _default_mvsepless_catalogue(*, allow_network: bool = True) -> Dict[str, Any]:
    """Raw mvsepless ``models.json`` via the same coordinator Download Center uses."""
    add_repo_to_path()
    from core.catalogue_coordinator import CatalogueCoordinator
    from core.catalogue_types import SourceId

    coordinator = CatalogueCoordinator()
    try:
        coordinator.ensure(vip=False, allow_network=allow_network)
        content = coordinator.source(SourceId.MVSEPLESS).state.content
        if content is None:
            return {}
        return dict(content.payload)
    finally:
        coordinator.close()


def resolve_target(entry_id: str, catalogue: Optional[Dict[str, Any]] = None) -> CatalogueTarget:
    """Look up ``entry_id`` in the mvsepless catalogue.

    ``catalogue`` is injectable so callers (and tests) can work offline.
    """
    add_repo_to_path()

    if catalogue is None:
        catalogue = _default_mvsepless_catalogue()

    entry = catalogue.get(entry_id)
    if not isinstance(entry, dict):
        raise KeyError(f"no catalogue entry {entry_id!r}")

    return _target_from_entry(entry_id, entry)


def _target_from_entry(entry_id: str, entry: Dict[str, Any]) -> CatalogueTarget:
    from core.mvsepless_catalog import classify_entry, entry_label

    _supported, reason = classify_entry(entry_id, entry)
    return CatalogueTarget(
        entry_id=entry_id,
        label=entry_label(entry_id, entry),
        model_type=str(entry.get("model_type") or ""),
        config_url=str(entry.get("config_url") or ""),
        checkpoint_url=str(entry.get("checkpoint_url") or ""),
        reason=reason,
        is_bv_model=bool(entry.get("is_bv_model")),
    )


def iter_catalogue_targets(
    catalogue: Optional[Dict[str, Any]] = None, *, unsupported_only: bool = True
) -> Iterator[CatalogueTarget]:
    """Yield a :class:`CatalogueTarget` per mvsepless catalogue entry.

    Defaults to the entries ``classify_entry`` marks unsupported — the actual
    triage workload this script exists for. ``catalogue`` is injectable so
    callers (and tests) can work offline, same as :func:`resolve_target`.
    """
    add_repo_to_path()
    from core.mvsepless_catalog import classify_entry

    if catalogue is None:
        catalogue = _default_mvsepless_catalogue()

    for entry_id, entry in catalogue.items():
        if not isinstance(entry, dict):
            continue
        if unsupported_only:
            supported, _reason = classify_entry(entry_id, entry)
            if supported:
                continue
        yield _target_from_entry(entry_id, entry)


def _default_opener(request: Any) -> Any:
    from core.mdx_config_fetch import _urlopen

    return _urlopen(request)


def _request(url: str, headers: Dict[str, str]) -> Any:
    import urllib.request

    return urllib.request.Request(url, headers=headers)


class RangeError(RuntimeError):
    """A range request returned something other than the bytes that were asked for.

    Worth its own type because the failure is silent otherwise: a server that
    ignores ``Range`` streams the entire checkpoint, and a short or misaligned
    body gets hashed as though it were the requested span.
    """


def _parse_content_range(value: str) -> Tuple[int, int, Optional[int]]:
    """``bytes 100-139/1000`` -> ``(100, 139, 1000)``. ``*`` total becomes None."""
    unit, _, spec = value.strip().partition(" ")
    if unit.lower() != "bytes":
        raise RangeError(f"unsupported Content-Range unit: {value!r}")
    span, _, total_text = spec.partition("/")
    first, _, last = span.partition("-")
    try:
        start, end = int(first), int(last)
    except ValueError:
        raise RangeError(f"unparsable Content-Range: {value!r}") from None
    total = int(total_text) if total_text.strip().isdigit() else None
    return start, end, total


def _response_status(response: Any) -> Optional[int]:
    status: Any = getattr(response, "status", None)
    if status is None:
        getcode = getattr(response, "getcode", None)
        status = getcode() if callable(getcode) else None
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def http_range_reader(url: str, *, opener: Optional[Callable[[Any], Any]] = None) -> RangeReader:
    """A :data:`RangeReader` backed by validated HTTP range requests.

    ``start``/``end`` are half-open like every other reader here; HTTP ranges
    are inclusive, hence the ``end - 1``.

    The response is checked rather than trusted: it must be a 206 whose
    ``Content-Range`` matches the span requested, carrying exactly that many
    bytes. Anything else raises :class:`RangeError` instead of being returned
    as though it were the requested bytes. A server may legitimately clamp the
    final range to the last byte of the file, which is accepted.
    """
    fetch = opener or _default_opener

    def read(start: int, end: int) -> bytes:
        request = _request(url, {"Range": f"bytes={start}-{end - 1}"})
        with fetch(request) as response:
            status = _response_status(response)
            if status != 206:
                raise RangeError(
                    f"{url}: expected 206 Partial Content, got {status} "
                    f"(the server may be ignoring Range)"
                )
            header = (response.headers or {}).get("Content-Range") or ""
            if not header:
                raise RangeError(f"{url}: 206 response carried no Content-Range")
            data = response.read()

        got_start, got_end, total = _parse_content_range(header)
        if got_start != start:
            raise RangeError(
                f"{url}: asked for bytes {start}-{end - 1}, server sent {got_start}-{got_end}"
            )
        at_eof = total is not None and got_end == total - 1
        if got_end != end - 1 and not at_eof:
            raise RangeError(
                f"{url}: asked for bytes {start}-{end - 1}, server sent {got_start}-{got_end}"
            )
        expected = got_end - got_start + 1
        if len(data) != expected:
            raise RangeError(
                f"{url}: Content-Range promised {expected} bytes, body carried {len(data)}"
            )
        return data

    return read


def remote_size(url: str, *, opener: Optional[Callable[[Any], Any]] = None) -> int:
    """Total size of a remote file, learned from a one-byte range request.

    A range request rather than HEAD: redirect-heavy hosts answer it more
    reliably, and ``Content-Range`` carries the total either way.
    """
    fetch = opener or _default_opener
    request = _request(url, {"Range": "bytes=0-0"})
    with fetch(request) as response:
        content_range = response.headers.get("Content-Range") or ""
    total = content_range.rpartition("/")[2].strip()
    if not total.isdigit():
        raise ValueError(f"server did not report a size for {url}")
    return int(total)


def remote_checkpoint_keys(url: str) -> List[str]:
    """Fetch only a remote checkpoint's header and return its ``state_dict`` keys."""
    read = http_range_reader(url)
    if url.endswith(".safetensors"):
        span = safetensors_header_span(read(0, _SAFETENSORS_LEN_BYTES))
        return parse_safetensors_header(read(0, span[1]))
    return torch_checkpoint_keys(read, remote_size(url))


def _checkpoint_keys_cache_path(dest_dir: str) -> str:
    return os.path.join(dest_dir, "checkpoint_keys.json")


def _read_checkpoint_keys_cache(dest_dir: str) -> Dict[str, List[str]]:
    try:
        with open(_checkpoint_keys_cache_path(dest_dir), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _write_checkpoint_keys_cache(dest_dir: str, payload: Dict[str, List[str]]) -> None:
    add_repo_to_path()
    from core.json_store import write_json_atomic

    try:
        write_json_atomic(_checkpoint_keys_cache_path(dest_dir), payload)
    except OSError:
        pass


def cached_remote_checkpoint_keys(url: str, dest_dir: str) -> List[str]:
    """``remote_checkpoint_keys``, skipping the range-fetch on a repeat URL.

    Checkpoint headers are presumed immutable once fetched — same assumption
    ``_fetch_config`` makes for config yamls — so this caches with no TTL,
    keyed by URL, in one JSON file under ``dest_dir``.
    """
    cache = _read_checkpoint_keys_cache(dest_dir)
    cached = cache.get(url)
    if cached is not None:
        return cached
    keys = remote_checkpoint_keys(url)
    cache[url] = keys
    _write_checkpoint_keys_cache(dest_dir, cache)
    return keys


def local_checkpoint_keys(path: str) -> List[str]:
    """``state_dict`` keys of a checkpoint on disk, reading only its header."""

    def read(start: int, end: int) -> bytes:
        with open(path, "rb") as handle:
            handle.seek(start)
            return handle.read(end - start)

    if path.endswith(".safetensors"):
        span = safetensors_header_span(read(0, _SAFETENSORS_LEN_BYTES))
        return parse_safetensors_header(read(0, span[1]))
    return torch_checkpoint_keys(read, os.path.getsize(path))


def cache_name(url: str, filename: str) -> str:
    """Cache filename keyed by URL, not by basename alone.

    Two models can both ship a ``config.yaml``; keying on the basename made
    the second one silently read the first one's bytes. The readable stem is
    kept so the cache directory stays browsable.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    stem, ext = os.path.splitext(filename)
    return f"{stem}-{digest}{ext}"


def fetch_config(url: str, dest_dir: str) -> str:
    """Download a yaml config (a few KB) into ``dest_dir`` and return the path."""
    from urllib.parse import unquote, urlparse

    from core.mdx_config_fetch import _urlopen

    name = os.path.basename(unquote(urlparse(url).path)) or "config.yaml"
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, cache_name(url, name))
    if os.path.isfile(dest):
        return dest
    tmp_dest = f"{dest}.part"
    try:
        with _urlopen(url) as response:
            data = response.read()
        with open(tmp_dest, "wb") as handle:
            handle.write(data)
        os.replace(tmp_dest, dest)
    finally:
        try:
            os.unlink(tmp_dest)
        except FileNotFoundError:
            pass
    return dest


def cache_dir() -> str:
    add_repo_to_path()
    from core import paths

    return os.path.join(paths.CACHE_DIR, "model_tools")




def checkpoint_tail_hash(url: str, *, opener: Optional[Callable[[Any], Any]] = None) -> str:
    """UVR-style MD5 fingerprint of a remote checkpoint, range-fetched.

    Mirrors ``core.mdx_c_registry.compute_checkpoint_hash``'s local-file logic
    -- hash the last :data:`_HASH_TAIL_BYTES`, or the whole file when smaller --
    but reads over HTTP so auditing a catalogue does not require downloading
    full checkpoints. Raises on any fetch or range problem; callers decide
    whether one unreachable checkpoint should end their run.
    """
    size = remote_size(url, opener=opener)
    read = http_range_reader(url, opener=opener)
    start = max(0, size - _HASH_TAIL_BYTES)
    return hashlib.md5(read(start, size)).hexdigest()
