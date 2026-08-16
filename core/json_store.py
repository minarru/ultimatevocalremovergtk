"""Path-safe atomic JSON persistence shared by profiles and registries."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from collections.abc import Iterator
from typing import Any


_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def _path_lock(path: str) -> threading.RLock:
    normalized = os.path.abspath(path)
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(normalized, threading.RLock())


@contextmanager
def locked_json_path(path: str) -> Iterator[None]:
    """Serialize a read/backup/write transaction for one JSON path."""
    with _path_lock(path):
        yield


def safe_json_path(directory: str, name: str, *, suffix: str = ".json") -> str:
    clean = str(name or "").strip()
    if not clean or clean in {".", ".."} or os.path.basename(clean) != clean:
        raise ValueError(f"invalid name {name!r}")
    root = os.path.abspath(directory)
    path = os.path.abspath(os.path.join(root, f"{clean}{suffix}"))
    if os.path.commonpath((root, path)) != root:
        raise ValueError("path escapes storage directory")
    return path


def content_digest(path: str) -> str:
    """SHA-256 of the file bytes; empty string if the path does not exist."""
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except FileNotFoundError:
        return ""


def read_json_object(path: str) -> dict[str, Any]:
    with _path_lock(path), open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def write_json_atomic(path: str, payload: dict[str, Any]) -> None:
    with _path_lock(path):
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def write_json_if_unchanged(
    path: str, payload: dict[str, Any], expected_digest: str,
) -> bool:
    """Under the path lock, write only if content_digest(path) == expected_digest.

    Return False (and do not write) on mismatch. Missing file matches digest ''.
    """
    with _path_lock(path):
        if content_digest(path) != expected_digest:
            return False
        write_json_atomic(path, payload)
        return True


def backup_once(path: str, *, suffix: str = ".pre-canonical-id.bak") -> str:
    with _path_lock(path):
        backup = f"{path}{suffix}"
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
    return backup
