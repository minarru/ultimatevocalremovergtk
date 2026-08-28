"""Validated bundled and user-supplied Demucs identity metadata."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import deque
from dataclasses import dataclass
from hashlib import md5, sha256
from typing import Any, Mapping

import yaml

from bundled.constants import (
    DEMUCS_2_SOURCE_MAPPER,
    DEMUCS_4_SOURCE_MAPPER,
    DEMUCS_6_SOURCE_MAPPER,
)

from . import paths
from .json_store import locked_json_path, read_json_object, write_json_atomic
from .model_identity import DemucsSpec, parse_stored_model_id


_DEMUCS_REGISTRY_SCHEMA_VERSION = 1
_DEMUCS_VERSIONS = frozenset({"v1", "v2", "v3", "v4"})
_DEMUCS_LAYOUTS = frozenset({"2_stem", "4_stem", "6_stem"})

_SOURCE_LAYOUTS: dict[int, tuple[str, dict[str, int]]] = {
    2: ("2_stem", DEMUCS_2_SOURCE_MAPPER),
    4: ("4_stem", DEMUCS_4_SOURCE_MAPPER),
    6: ("6_stem", DEMUCS_6_SOURCE_MAPPER),
}


def _read_json(path: str) -> Mapping[str, Any]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _bundled_path(filename: str) -> str:
    return os.path.join(
        paths.BUNDLED_MODELS_DIR, "Demucs_Models", "model_data", filename
    )


def _registered_models_path(models_dir: str) -> str:
    return os.path.join(models_dir, "model_data", "registered_models.json")


def _empty_registry_document() -> dict[str, Any]:
    return {
        "schema_version": _DEMUCS_REGISTRY_SCHEMA_VERSION,
        "models": {},
        "by_primary_hash": {},
    }


def validate_demucs_registration_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate user-supplied custom Demucs identity metadata."""
    demucs_version = config.get("demucs_version")
    if demucs_version not in _DEMUCS_VERSIONS:
        raise ValueError("invalid Demucs version; expected v1, v2, v3, or v4")
    source_layout = config.get("source_layout")
    if source_layout not in _DEMUCS_LAYOUTS:
        raise ValueError(
            "invalid Demucs source layout; expected 2_stem, 4_stem, or 6_stem"
        )
    display_name = config.get("display_name")
    if display_name is not None and (
        not isinstance(display_name, str) or not display_name.strip()
    ):
        raise ValueError("Demucs display_name must be a non-empty string")
    if any(key in config for key in ("id", "model_id", "backend_name")):
        raise ValueError("Demucs ID and backend name derive from the entrypoint")
    return {
        "demucs_version": demucs_version,
        "source_layout": source_layout,
        **(
            {"display_name": display_name.strip()}
            if isinstance(display_name, str)
            else {}
        ),
    }


def validate_demucs_entrypoint(source: str, demucs_version: str) -> None:
    """Reject checkpoint formats unsupported by the declared Demucs generation."""
    filename = os.path.basename(source)
    if demucs_version in {"v1", "v2"}:
        if not filename.casefold().endswith((".th", ".th.gz")):
            raise ValueError("v1/v2 Demucs entrypoint must be .th or .th.gz")
        return
    if not filename.endswith((".th", ".yaml")):
        raise ValueError("v3/v4 Demucs entrypoint must be .th or .yaml")


def _demucs_artifact_stem(filename: str) -> str:
    name = os.path.basename(filename)
    if name.casefold().endswith(".th.gz"):
        return name[:-6]
    return os.path.splitext(name)[0]


@dataclass(frozen=True)
class _ArtifactSnapshot:
    content_fingerprint: str
    checkpoint_fingerprint: str
    content: bytes | None = None


def _capture_artifact(path: str, *, include_content: bool = False) -> _ArtifactSnapshot:
    """Capture transaction and UVR fingerprints from one byte stream."""
    checkpoint_window = 10000 * 1024
    content_digest = sha256()
    checkpoint_chunks: deque[bytes] = deque()
    checkpoint_size = 0
    captured_chunks: list[bytes] | None = [] if include_content else None
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            content_digest.update(chunk)
            if captured_chunks is not None:
                captured_chunks.append(chunk)
            checkpoint_chunks.append(chunk)
            checkpoint_size += len(chunk)
            while checkpoint_size > checkpoint_window:
                overflow = checkpoint_size - checkpoint_window
                first = checkpoint_chunks[0]
                if len(first) <= overflow:
                    checkpoint_chunks.popleft()
                    checkpoint_size -= len(first)
                else:
                    checkpoint_chunks[0] = first[overflow:]
                    checkpoint_size -= overflow
    return _ArtifactSnapshot(
        content_fingerprint=content_digest.hexdigest(),
        checkpoint_fingerprint=md5(b"".join(checkpoint_chunks)).hexdigest(),
        content=(
            b"".join(captured_chunks)
            if captured_chunks is not None
            else None
        ),
    )


def _content_fingerprint(path: str) -> str:
    """Return a complete-file digest for registration transaction equality."""
    digest = sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _v3_v4_weight_signature(path: str, content_fingerprint: str) -> str:
    filename = os.path.basename(path)
    if not filename.endswith(".th"):
        raise ValueError(f"v3/v4 Demucs weight must be .th: {filename}")
    stem = filename[:-3]
    parts = stem.split("-")
    if len(parts) > 2 or not parts[0] or (len(parts) == 2 and not parts[1]):
        raise ValueError(
            f"invalid v3/v4 Demucs weight name {filename!r}; expected signature.th "
            "or signature-checksum.th"
        )
    signature = parts[0]
    if len(parts) == 2:
        checksum = parts[1]
        if content_fingerprint[: len(checksum)] != checksum:
            raise ValueError(f"invalid declared checksum for {filename}")
    return signature


def _yaml_bag_members(
    source: str, content: bytes
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        document = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid Demucs YAML bag: {exc}") from exc
    if not isinstance(document, Mapping):
        raise ValueError("Demucs YAML bag root must be an object")
    raw_models = document.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ValueError("Demucs YAML bag must contain a non-empty models list")

    directory = os.path.dirname(source)
    members: list[str] = []
    for raw_signature in raw_models:
        if not isinstance(raw_signature, str) or not raw_signature:
            raise ValueError("Demucs YAML bag signatures must be non-empty strings")
        prefix = f"{raw_signature}-"
        matches = [
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.startswith(prefix)
            and name.endswith(".th")
            and os.path.isfile(os.path.join(directory, name))
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Demucs YAML signature {raw_signature!r} must match exactly one "
                "adjacent signature-checksum.th weight"
            )
        members.append(matches[0])
    return tuple(members), tuple(str(signature) for signature in raw_models)


@dataclass(frozen=True)
class DemucsRegistrationUnit:
    model_id: str
    entry: dict[str, Any]
    source_paths: tuple[str, ...]
    destination_paths: tuple[str, ...]
    content_fingerprints: tuple[str, ...]
    bag_signatures: tuple[str, ...]


def prepare_demucs_registration(
    source: str,
    config: Mapping[str, Any],
    *,
    models_dir: str | None = None,
) -> DemucsRegistrationUnit:
    """Validate one custom Demucs artifact unit without changing the filesystem."""
    source = os.path.abspath(source)
    normalized = validate_demucs_registration_config(config)
    version = str(normalized["demucs_version"])
    validate_demucs_entrypoint(source, version)

    basename = _demucs_artifact_stem(source)
    from .model_identity import ModelId

    model_id = ModelId("demucs", basename).value
    source_snapshot = _capture_artifact(
        source, include_content=source.endswith(".yaml")
    )
    if source.endswith(".yaml"):
        assert source_snapshot.content is not None
        support, bag_signatures = _yaml_bag_members(
            source, source_snapshot.content
        )
        support_snapshots = tuple(_capture_artifact(path) for path in support)
        for signature, path, snapshot in zip(
            bag_signatures, support, support_snapshots, strict=True
        ):
            if (
                _v3_v4_weight_signature(
                    path, snapshot.content_fingerprint
                )
                != signature
            ):
                raise ValueError(
                    f"Demucs YAML member does not match signature {signature!r}"
                )
    else:
        support = ()
        bag_signatures = ()
        support_snapshots = ()
    backend_name = (
        basename
        if source.endswith(".yaml") or version in {"v1", "v2"}
        else _v3_v4_weight_signature(
            source, source_snapshot.content_fingerprint
        )
    )

    root = os.path.abspath(models_dir or paths.DEMUCS_MODELS_DIR)
    destination_dir = (
        root if version in {"v1", "v2"} else os.path.join(root, "v3_v4_repo")
    )
    source_paths = (source, *support)
    snapshots = (source_snapshot, *support_snapshots)
    content_fingerprints = tuple(
        snapshot.content_fingerprint for snapshot in snapshots
    )
    destination_paths = tuple(
        os.path.join(destination_dir, os.path.basename(path)) for path in source_paths
    )
    relative_paths = tuple(
        _normalize_demucs_registry_relative_path(root, path)
        for path in destination_paths
    )
    entry = {
        "display_name": str(normalized.get("display_name") or basename),
        "backend_name": backend_name,
        "entrypoint": relative_paths[0],
        "supporting_artifacts": list(relative_paths[1:]),
        "primary_hash": source_snapshot.checkpoint_fingerprint,
        "demucs_version": version,
        "source_layout": str(normalized["source_layout"]),
    }
    return DemucsRegistrationUnit(
        model_id=model_id,
        entry=entry,
        source_paths=source_paths,
        destination_paths=destination_paths,
        content_fingerprints=content_fingerprints,
        bag_signatures=bag_signatures,
    )


def _normalize_demucs_registry_relative_path(models_dir: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Demucs registry paths must be non-empty")
    rooted = os.path.realpath(models_dir)
    lexical_candidate = os.path.join(models_dir, text.replace("\\", os.sep))
    candidate = os.path.realpath(lexical_candidate)
    if os.path.commonpath((rooted, candidate)) != rooted:
        raise ValueError("path escapes Demucs model root")
    relative = os.path.relpath(candidate, rooted)
    if relative in {"", "."}:
        raise ValueError("Demucs registry paths must reference a file")
    return relative.replace(os.sep, "/")


def _normalize_demucs_registry_model(
    models_dir: str, model_id: str, raw: Mapping[str, Any]
) -> dict[str, Any]:
    parsed = parse_stored_model_id(model_id)
    if parsed.family != "demucs":
        raise ValueError(f"invalid Demucs registry ID {model_id!r}")

    display_name = str(raw.get("display_name") or "").strip()
    backend_name = str(raw.get("backend_name") or "").strip()
    primary_hash = str(raw.get("primary_hash") or "").strip()
    demucs_version = str(raw.get("demucs_version") or "").strip()
    source_layout = str(raw.get("source_layout") or "").strip()
    if not display_name:
        raise ValueError(f"{parsed.value} is missing display_name")
    if not backend_name:
        raise ValueError(f"{parsed.value} is missing backend_name")
    if not primary_hash:
        raise ValueError(f"{parsed.value} is missing primary_hash")
    if demucs_version not in _DEMUCS_VERSIONS:
        raise ValueError(f"invalid Demucs version for {parsed.value}")
    if source_layout not in _DEMUCS_LAYOUTS:
        raise ValueError(f"invalid Demucs source layout for {parsed.value}")

    supporting_raw = raw.get("supporting_artifacts", ())
    if not isinstance(supporting_raw, list):
        raise ValueError(f"{parsed.value} supporting_artifacts must be a list")

    return {
        "display_name": display_name,
        "backend_name": backend_name,
        "entrypoint": _normalize_demucs_registry_relative_path(
            models_dir, raw.get("entrypoint")
        ),
        "supporting_artifacts": [
            _normalize_demucs_registry_relative_path(models_dir, path)
            for path in supporting_raw
        ],
        "primary_hash": primary_hash,
        "demucs_version": demucs_version,
        "source_layout": source_layout,
    }


def _normalize_demucs_registry_document(
    payload: Mapping[str, Any] | None, *, models_dir: str
) -> dict[str, Any]:
    if payload is None:
        return _empty_registry_document()
    if int(payload.get("schema_version") or 0) != _DEMUCS_REGISTRY_SCHEMA_VERSION:
        raise ValueError("unsupported Demucs registry schema")
    raw_models = payload.get("models")
    if not isinstance(raw_models, Mapping):
        raise ValueError("Demucs registry is missing models")

    models: dict[str, dict[str, Any]] = {}
    by_primary_hash: dict[str, str] = {}
    for model_id, raw in raw_models.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"invalid Demucs registry entry {model_id!r}")
        normalized = _normalize_demucs_registry_model(models_dir, str(model_id), raw)
        canonical_id = parse_stored_model_id(str(model_id)).value
        primary_hash = str(normalized["primary_hash"])
        existing = by_primary_hash.get(primary_hash)
        if existing is not None and existing != canonical_id:
            raise ValueError(
                f"duplicate Demucs primary_hash {primary_hash!r} for {existing!r} and {canonical_id!r}"
            )
        models[canonical_id] = normalized
        by_primary_hash[primary_hash] = canonical_id

    return {
        "schema_version": _DEMUCS_REGISTRY_SCHEMA_VERSION,
        "models": models,
        "by_primary_hash": by_primary_hash,
    }


def mapper_stems() -> set[str]:
    """Return canonical IDs represented by the bundled official name mapper."""
    from .model_inventory import artifact_stem

    mapper = _read_json(_bundled_path("model_name_mapper.json"))
    return {f"demucs:{artifact_stem(str(filename))}" for filename in mapper}


def load_bundled_demucs_specs() -> dict[str, DemucsSpec]:
    """Load and validate official Demucs version/source-layout declarations."""
    payload = _read_json(_bundled_path("model_specs.json"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported bundled Demucs spec schema")
    raw_models = payload.get("models")
    if not isinstance(raw_models, Mapping):
        raise ValueError("bundled Demucs specs are missing models")

    result: dict[str, DemucsSpec] = {}
    for model_id, raw in raw_models.items():
        parsed = parse_stored_model_id(str(model_id))
        if parsed.family != "demucs" or not isinstance(raw, Mapping):
            raise ValueError(f"invalid bundled Demucs spec {model_id!r}")
        version = raw.get("version")
        layout = raw.get("source_layout")
        if version not in {"v1", "v2", "v3", "v4"}:
            raise ValueError(f"invalid Demucs version for {model_id}")
        if layout not in {"2_stem", "4_stem", "6_stem"}:
            raise ValueError(f"invalid Demucs source layout for {model_id}")
        result[parsed.value] = DemucsSpec(version, layout)  # type: ignore[arg-type]

    expected = mapper_stems()
    if set(result) != expected:
        missing = sorted(expected - set(result))
        extra = sorted(set(result) - expected)
        raise ValueError(f"bundled Demucs spec drift: missing={missing}, extra={extra}")
    return result


def demucs_source_layout_name(source_count: int) -> str | None:
    """Return the canonical layout label for a Demucs source count."""
    spec = _SOURCE_LAYOUTS.get(int(source_count))
    return None if spec is None else spec[0]


def validate_demucs_output_layout(
    *, expected_count: int, actual_count: int, model_label: str
) -> dict[str, int]:
    """Return the native source map for ``actual_count`` or raise on layout drift."""
    expected_layout = demucs_source_layout_name(expected_count)
    actual = _SOURCE_LAYOUTS.get(int(actual_count))
    if expected_layout is None:
        raise ValueError(f"unsupported declared Demucs source layout: {expected_count}")
    if actual is None:
        raise ValueError(
            f"{model_label} produced {actual_count} sources; expected {expected_layout} source layout"
        )
    actual_layout, source_map = actual
    if actual_layout != expected_layout:
        raise ValueError(
            f"{model_label} produced {actual_layout}; expected {expected_layout} source layout"
        )
    return source_map


def validate_demucs_inference_layouts(
    *,
    expected_count: int,
    model_label: str,
    source: Any,
    inst_source: Any | None = None,
) -> dict[str, int]:
    """Validate main and optional pre-processing Demucs outputs before grafting."""
    source_map = validate_demucs_output_layout(
        expected_count=expected_count,
        actual_count=len(source),
        model_label=model_label,
    )
    if inst_source is not None:
        validate_demucs_output_layout(
            expected_count=expected_count,
            actual_count=len(inst_source),
            model_label=f"{model_label} pre-processing result",
        )
    return source_map


class DemucsRegistry:
    def __init__(self, *, models_dir: str | None = None):
        self.models_dir = os.path.abspath(models_dir or paths.DEMUCS_MODELS_DIR)
        self.path = _registered_models_path(self.models_dir)
        self.lock_path = f"{self.path}.lock"

    def _load_unlocked(self) -> dict[str, Any]:
        try:
            payload = read_json_object(self.path)
        except FileNotFoundError:
            return _empty_registry_document()
        return _normalize_demucs_registry_document(
            payload, models_dir=self.models_dir
        )

    def load(self) -> dict[str, Any]:
        with locked_json_path(self.lock_path):
            normalized = self._load_unlocked()
            try:
                payload = read_json_object(self.path)
            except FileNotFoundError:
                return normalized
            if normalized != payload:
                write_json_atomic(self.path, normalized)
            return normalized

    def load_read_only(self) -> dict[str, Any]:
        """Return a locked, validated view without normalizing the file on disk."""
        with locked_json_path(self.lock_path):
            return self._load_unlocked()

    def save(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _normalize_demucs_registry_document(
            payload, models_dir=self.models_dir
        )
        with locked_json_path(self.lock_path):
            write_json_atomic(self.path, normalized)
        return normalized

    @staticmethod
    def _assert_artifact_matches(
        expected_fingerprint: str, destination: str
    ) -> None:
        if not os.path.isfile(destination):
            raise ValueError(f"Demucs artifact is missing: {destination}")
        if _content_fingerprint(destination) != expected_fingerprint:
            raise ValueError(
                f"model destination already exists with different content: {destination}"
            )

    @staticmethod
    def _assert_unit_snapshot(unit: DemucsRegistrationUnit) -> None:
        if not (
            len(unit.source_paths)
            == len(unit.destination_paths)
            == len(unit.content_fingerprints)
        ):
            raise ValueError("invalid Demucs registration snapshot")
        expected_member_count = len(unit.source_paths) - 1
        entrypoint = str(unit.entry.get("entrypoint", ""))
        if entrypoint.endswith(".yaml"):
            if len(unit.bag_signatures) != expected_member_count:
                raise ValueError("invalid Demucs YAML member snapshot")
            for signature, source in zip(
                unit.bag_signatures, unit.source_paths[1:], strict=True
            ):
                member = os.path.basename(source)
                if not member.startswith(f"{signature}-") or not member.endswith(
                    ".th"
                ):
                    raise ValueError("invalid Demucs YAML member snapshot")
        elif unit.bag_signatures:
            raise ValueError("direct Demucs weights cannot have YAML members")

    @classmethod
    def _assert_sources_unchanged(cls, unit: DemucsRegistrationUnit) -> None:
        cls._assert_unit_snapshot(unit)
        for source, expected in zip(
            unit.source_paths, unit.content_fingerprints, strict=True
        ):
            if _content_fingerprint(source) != expected:
                raise ValueError(
                    f"Demucs artifact changed since validation: {source}"
                )

    def _assert_registry_available(
        self,
        document: Mapping[str, Any],
        unit: DemucsRegistrationUnit,
        *,
        replace: bool,
    ) -> None:
        models = document.get("models")
        if not isinstance(models, Mapping):
            raise ValueError("Demucs registry is missing models")
        existing = models.get(unit.model_id)
        if existing is not None and not replace:
            raise ValueError(f"Demucs model ID is already registered: {unit.model_id}")
        by_primary_hash = document.get("by_primary_hash")
        if not isinstance(by_primary_hash, Mapping):
            raise ValueError("Demucs registry is missing by_primary_hash")
        claimed_id = by_primary_hash.get(unit.entry["primary_hash"])
        if claimed_id is not None and claimed_id != unit.model_id:
            raise ValueError(
                f"Demucs primary hash is already registered as {claimed_id}"
            )

        claimed_paths: dict[str, str] = {}
        for model_id, raw in models.items():
            if model_id == unit.model_id or not isinstance(raw, Mapping):
                continue
            for path in (raw.get("entrypoint"), *(raw.get("supporting_artifacts") or ())):
                claimed_paths[str(path)] = str(model_id)
        for path in (
            unit.entry["entrypoint"],
            *unit.entry["supporting_artifacts"],
        ):
            claimed_id = claimed_paths.get(str(path))
            if claimed_id is not None:
                raise ValueError(
                    f"Demucs artifact {path!r} is already claimed by {claimed_id}"
                )

    def _commit_unit(
        self, unit: DemucsRegistrationUnit, *, replace: bool
    ) -> dict[str, Any]:
        with locked_json_path(self.lock_path):
            document = self._load_unlocked()
            self._assert_registry_available(document, unit, replace=replace)
            self._assert_unit_snapshot(unit)
            for expected, destination in zip(
                unit.content_fingerprints, unit.destination_paths, strict=True
            ):
                self._assert_artifact_matches(expected, destination)
            models = document["models"]
            assert isinstance(models, dict)
            models[unit.model_id] = unit.entry
            normalized = _normalize_demucs_registry_document(
                document, models_dir=self.models_dir
            )
            write_json_atomic(self.path, normalized)
            return normalized

    def _rollback_created_paths(self, created_paths: list[str]) -> None:
        """Remove this command's artifacts unless a concurrent commit claimed them."""
        if not created_paths:
            return
        with locked_json_path(self.lock_path):
            try:
                document = self._load_unlocked()
            except (OSError, TypeError, ValueError):
                return
            models = document.get("models")
            if not isinstance(models, Mapping):
                return
            claimed = {
                str(path)
                for raw in models.values()
                if isinstance(raw, Mapping)
                for path in (
                    raw.get("entrypoint"),
                    *(raw.get("supporting_artifacts") or ()),
                )
            }
            for destination in created_paths:
                relative = _normalize_demucs_registry_relative_path(
                    self.models_dir, destination
                )
                if relative in claimed:
                    continue
                try:
                    os.remove(destination)
                except OSError:
                    pass

    def install(self, unit: DemucsRegistrationUnit) -> dict[str, Any]:
        """Install all artifacts, then durably publish their registry entry."""
        self._assert_sources_unchanged(unit)
        document = self.load_read_only()
        self._assert_registry_available(document, unit, replace=False)
        missing_destinations: list[tuple[str, str, str]] = []
        for source, destination, expected in zip(
            unit.source_paths,
            unit.destination_paths,
            unit.content_fingerprints,
            strict=True,
        ):
            if os.path.exists(destination):
                self._assert_artifact_matches(expected, destination)
            else:
                missing_destinations.append((source, destination, expected))

        temporary_paths: list[tuple[str, str]] = []
        created_paths: list[str] = []
        try:
            for source, destination, expected in missing_destinations:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                descriptor, temporary = tempfile.mkstemp(
                    prefix=f".{os.path.basename(destination)}.",
                    suffix=".uvr-register.tmp",
                    dir=os.path.dirname(destination),
                )
                os.close(descriptor)
                try:
                    shutil.copy2(source, temporary)
                except Exception:
                    try:
                        os.remove(temporary)
                    except OSError:
                        pass
                    raise
                if _content_fingerprint(temporary) != expected:
                    os.remove(temporary)
                    raise ValueError(
                        f"Demucs artifact changed since validation: {source}"
                    )
                temporary_paths.append((temporary, destination))

            for temporary, destination in temporary_paths:
                try:
                    os.link(temporary, destination)
                    created_paths.append(destination)
                except FileExistsError:
                    source_index = unit.destination_paths.index(destination)
                    self._assert_artifact_matches(
                        unit.content_fingerprints[source_index], destination
                    )
                os.remove(temporary)

            return self._commit_unit(unit, replace=False)
        except Exception:
            for temporary, _destination in temporary_paths:
                try:
                    os.remove(temporary)
                except OSError:
                    pass
            self._rollback_created_paths(created_paths)
            raise

    def configure(
        self, unit: DemucsRegistrationUnit, *, replace: bool
    ) -> dict[str, Any]:
        """Attach or update metadata for artifacts already installed in place."""
        return self._commit_unit(unit, replace=replace)

    def reset(self, model_id: str) -> bool:
        """Remove local metadata while leaving installed artifacts untouched."""
        canonical_id = parse_stored_model_id(model_id).value
        with locked_json_path(self.lock_path):
            document = self._load_unlocked()
            models = document["models"]
            assert isinstance(models, dict)
            removed = models.pop(canonical_id, None) is not None
            if removed:
                normalized = _normalize_demucs_registry_document(
                    document, models_dir=self.models_dir
                )
                write_json_atomic(self.path, normalized)
            return removed


__all__ = [
    "DemucsRegistrationUnit",
    "DemucsRegistry",
    "prepare_demucs_registration",
    "validate_demucs_inference_layouts",
    "demucs_source_layout_name",
    "load_bundled_demucs_specs",
    "mapper_stems",
    "validate_demucs_entrypoint",
    "validate_demucs_registration_config",
    "validate_demucs_output_layout",
]
