"""Transactional local model metadata shared by registration and GUI editing."""

from __future__ import annotations

import os
import shutil
import warnings
from typing import Any, Mapping

from bundled.constants import APOLLO_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE

from . import paths
from .json_store import locked_json_path, read_json_object, write_json_atomic

_SCHEMA_VERSION = 2
_PRESENTATION_FIELDS = (
    "catalogue_label",
    "catalogue_source",
    "display_override",
)


def _presentation_input(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"model presentation fields must be strings: {field}")
    return value


def _empty_registry() -> dict[str, Any]:
    return {"schema_version": _SCHEMA_VERSION, "hashes": {}, "models": {}}


def _normalize_hashes(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("registered model hashes must be an object")
    hashes: dict[str, str] = {}
    for model_hash, canonical_id in value.items():
        if (
            not isinstance(model_hash, str)
            or not model_hash
            or not isinstance(canonical_id, str)
            or not canonical_id
        ):
            raise ValueError("registered model hashes must map non-empty strings")
        hashes[model_hash] = canonical_id
    return hashes


def _normalize_models(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, Mapping):
        raise ValueError("registered model presentation must be an object")
    from .model_identity import parse_stored_model_id

    models: dict[str, dict[str, str]] = {}
    for canonical_id, raw_entry in value.items():
        exact_id = str(parse_stored_model_id(str(canonical_id)))
        if not isinstance(raw_entry, Mapping):
            raise ValueError(f"presentation entry for {exact_id} must be an object")
        unknown = set(raw_entry).difference(_PRESENTATION_FIELDS)
        if unknown:
            raise ValueError(
                f"presentation entry for {exact_id} has unknown fields: "
                f"{', '.join(sorted(str(key) for key in unknown))}"
            )
        entry: dict[str, str] = {}
        for field in _PRESENTATION_FIELDS:
            raw_value = raw_entry.get(field)
            if raw_value in (None, ""):
                continue
            if not isinstance(raw_value, str):
                raise ValueError(f"presentation field {field} must be a string")
            entry[field] = raw_value
        models[exact_id] = entry
    return models


def _normalize_registry(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize schema 1 or 2 in memory without writing either form."""
    if "schema_version" not in payload:
        return {
            "schema_version": _SCHEMA_VERSION,
            "hashes": _normalize_hashes(payload),
            "models": {},
        }
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(f"unsupported registered model schema {payload.get('schema_version')!r}")
    if set(payload).difference(("schema_version", "hashes", "models")):
        raise ValueError("registered model registry has unknown top-level fields")
    return {
        "schema_version": _SCHEMA_VERSION,
        "hashes": _normalize_hashes(payload.get("hashes")),
        "models": _normalize_models(payload.get("models")),
    }


def _same_path(first: str, second: str) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(
        os.path.abspath(second)
    )


def _merge_registries(
    base: Mapping[str, Any], overlay: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge two normalized registries with field-level overlay precedence."""
    merged = _empty_registry()
    merged["hashes"] = {**base["hashes"], **overlay["hashes"]}
    model_ids = set(base["models"]) | set(overlay["models"])
    merged["models"] = {
        model_id: {
            **base["models"].get(model_id, {}),
            **overlay["models"].get(model_id, {}),
        }
        for model_id in model_ids
    }
    return merged


def _read_optional_registry(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    return _normalize_registry(read_json_object(path))


def _read_effective_registry(*, for_mutation: bool) -> dict[str, Any]:
    runtime_path = paths.REGISTERED_MODEL_INDEX
    legacy_path = paths.LEGACY_REGISTERED_MODEL_INDEX
    try:
        runtime = _read_optional_registry(runtime_path)
    except (OSError, ValueError) as exc:
        if for_mutation:
            raise
        warnings.warn(
            f"Could not read runtime model registry {runtime_path!r}: {exc}",
            RuntimeWarning,
            stacklevel=3,
        )
        runtime = None

    legacy = None
    if not _same_path(runtime_path, legacy_path):
        try:
            legacy = _read_optional_registry(legacy_path)
        except (OSError, ValueError) as exc:
            if for_mutation:
                raise ValueError(
                    f"legacy model registry {legacy_path!r} is invalid: {exc}"
                ) from exc
            warnings.warn(
                f"Could not read legacy model registry {legacy_path!r}: {exc}",
                RuntimeWarning,
                stacklevel=3,
            )

    return _merge_registries(legacy or _empty_registry(), runtime or _empty_registry())


def _write_runtime_registry(registry: dict[str, Any]) -> None:
    path = paths.REGISTERED_MODEL_INDEX
    write_json_atomic(path, registry)
    persisted = _normalize_registry(read_json_object(path))
    if persisted != registry:
        raise OSError(f"model registry verification failed after writing {path!r}")


def _next_legacy_archive_path() -> str:
    directory = os.path.dirname(os.path.abspath(paths.REGISTERED_MODEL_INDEX))
    candidate = os.path.join(directory, "registered_models.legacy.json")
    index = 0
    while os.path.exists(candidate):
        index += 1
        candidate = os.path.join(directory, f"registered_models.legacy.{index}.json")
    return candidate


def _archive_legacy_registry() -> None:
    legacy_path = paths.LEGACY_REGISTERED_MODEL_INDEX
    if _same_path(legacy_path, paths.REGISTERED_MODEL_INDEX) or not os.path.isfile(
        legacy_path
    ):
        return
    archive = _next_legacy_archive_path()
    try:
        os.makedirs(os.path.dirname(archive), exist_ok=True)
        shutil.move(legacy_path, archive)
    except OSError as exc:
        warnings.warn(
            f"Model registry migrated but legacy archive failed for {legacy_path!r}: {exc}",
            RuntimeWarning,
            stacklevel=3,
        )


def _persist_mutation(registry: dict[str, Any], *, changed: bool) -> bool:
    legacy_path = paths.LEGACY_REGISTERED_MODEL_INDEX
    migration_pending = not _same_path(
        legacy_path, paths.REGISTERED_MODEL_INDEX
    ) and os.path.isfile(legacy_path)
    if changed or migration_pending:
        _write_runtime_registry(registry)
        _archive_legacy_registry()
    return changed


def _archive_legacy_presentation_mappers() -> None:
    from .name_mapper import archive_legacy_local_overlay

    for mapper_path in (
        paths.MDX_MODEL_NAME_SELECT,
        paths.DEMUCS_MODEL_NAME_SELECT,
    ):
        archive_legacy_local_overlay(mapper_path)


class ModelRegistryService:
    def __init__(self, repo: Any | None = None):
        self.repo = repo

    @staticmethod
    def metadata_path(process_method: str, model_hash: str) -> str:
        directory = {
            VR_ARCH_TYPE: paths.VR_HASH_DIR,
            MDX_ARCH_TYPE: paths.MDX_HASH_DIR,
            APOLLO_ARCH_TYPE: paths.APOLLO_HASH_DIR,
        }.get(process_method)
        if directory is None or not model_hash:
            raise ValueError("local metadata is supported only for hashed VR, MDX, and Apollo models")
        return os.path.join(directory, f"{model_hash}.json")

    def read_local(self, process_method: str, model_hash: str) -> dict[str, Any] | None:
        path = self.metadata_path(process_method, model_hash)
        if not os.path.isfile(path):
            return None
        try:
            return read_json_object(path)
        except (OSError, ValueError):
            return None

    @staticmethod
    def registered_id(model_hash: str) -> str | None:
        if not model_hash:
            return None
        with locked_json_path(paths.REGISTERED_MODEL_INDEX):
            registry = _read_effective_registry(for_mutation=False)
            value = registry["hashes"].get(model_hash)
        return str(value) if value else None

    @staticmethod
    def presentation(canonical_id: str) -> dict[str, str]:
        """Return exact persisted presentation evidence for ``canonical_id``."""
        from .model_identity import parse_stored_model_id

        exact_id = str(parse_stored_model_id(canonical_id))
        with locked_json_path(paths.REGISTERED_MODEL_INDEX):
            registry = _read_effective_registry(for_mutation=False)
            return dict(registry["models"].get(exact_id, {}))

    @staticmethod
    def remember_registered(model_hash: str, canonical_id: str) -> bool:
        """Record hash -> canonical id ownership.

        Returns whether this call changed the index. Callers that ignore the
        return stay source-compatible; the download finalizer uses it to tell a
        genuine repair apart from a re-run over an already-indexed model, so an
        unchanged ``exists`` transfer does not republish.
        """
        if not model_hash or not canonical_id:
            raise ValueError("registered models require a hash and canonical ID")
        with locked_json_path(paths.REGISTERED_MODEL_INDEX):
            registry = _read_effective_registry(for_mutation=True)
            hashes = registry["hashes"]
            if hashes.get(model_hash) == canonical_id:
                return _persist_mutation(registry, changed=False)
            hashes[model_hash] = canonical_id
            return _persist_mutation(registry, changed=True)

    @staticmethod
    def forget_registered(model_hash: str) -> None:
        with locked_json_path(paths.REGISTERED_MODEL_INDEX):
            registry = _read_effective_registry(for_mutation=True)
            hashes = registry["hashes"]
            if model_hash in hashes:
                del hashes[model_hash]
                _persist_mutation(registry, changed=True)
            else:
                _persist_mutation(registry, changed=False)

    @staticmethod
    def remember_presentation(
        canonical_id: str,
        *,
        catalogue_label: str = "",
        catalogue_source: str = "",
        display_override: str = "",
    ) -> bool:
        """Merge exact presentation evidence into the durable schema-2 registry.

        Empty optional values do not create fields or erase existing evidence.
        In particular, a catalogue-label backfill cannot clear a trusted
        ``display_override`` recorded earlier.
        """
        from .model_identity import parse_stored_model_id

        exact_id = str(parse_stored_model_id(canonical_id))
        fields = (
            ("catalogue_label", _presentation_input("catalogue_label", catalogue_label)),
            (
                "catalogue_source",
                _presentation_input("catalogue_source", catalogue_source),
            ),
            (
                "display_override",
                _presentation_input("display_override", display_override),
            ),
        )
        updates = {
            field: value
            for field, value in fields
            if value != ""
        }
        if not updates:
            return False
        with locked_json_path(paths.REGISTERED_MODEL_INDEX):
            registry = _read_effective_registry(for_mutation=True)
            models = registry["models"]
            current = dict(models.get(exact_id, {}))
            updated = {**current, **updates}
            if updated == current:
                return _persist_mutation(registry, changed=False)
            models[exact_id] = updated
            changed = _persist_mutation(registry, changed=True)
            _archive_legacy_presentation_mappers()
            return changed

    @classmethod
    def index_downloaded(
        cls, family: str, jobs: list[tuple[str, str]] | tuple[tuple[str, str], ...]
    ) -> bool:
        """Record hashes downloaded through a catalogue without scanning inventory.

        Returns whether any ownership entry was added or repaired.
        """
        changed = False
        extensions = {
            "vr": (".pth",), "mdx": (".onnx", ".ckpt"),
            "apollo": (".ckpt", ".bin"),
        }.get(family, ())
        for _url, checkpoint in jobs:
            if not str(checkpoint).casefold().endswith(extensions):
                continue
            if not os.path.isfile(checkpoint):
                continue
            if family == "apollo":
                from .apollo import checkpoint_md5

                model_hash = checkpoint_md5(checkpoint)
            else:
                from .mdx_c_registry import compute_checkpoint_hash

                model_hash = str(compute_checkpoint_hash(checkpoint) or "")
            if model_hash:
                from .model_identity import ModelId

                if cls.remember_registered(
                    model_hash,
                    str(ModelId(family, os.path.splitext(os.path.basename(checkpoint))[0])),
                ):
                    changed = True
        return changed
    def write_local(
        self, process_method: str, model_hash: str, payload: dict[str, Any],
        *, replace: bool = True,
    ) -> str:
        if not payload:
            raise ValueError("model metadata must be a non-empty object")
        path = self.metadata_path(process_method, model_hash)
        if os.path.exists(path) and not replace:
            raise ValueError(f"local metadata already exists for hash {model_hash}")
        write_json_atomic(path, payload)
        if self.repo is not None:
            self.repo.invalidate_models()
        return path

    @staticmethod
    def validate_payload(
        family: str, payload: dict[str, Any], *, model_path: str = ""
    ) -> dict[str, Any]:
        if not payload:
            raise ValueError("model metadata must be a non-empty object")
        result = dict(payload)
        if family == "vr":
            parameter = str(result.get("vr_model_param") or "")
            if not parameter:
                raise ValueError("VR metadata requires vr_model_param")
            parameter_name = parameter if parameter.endswith(".json") else f"{parameter}.json"
            if os.path.basename(parameter_name) != parameter_name or not os.path.isfile(
                os.path.join(paths.VR_PARAM_DIR, parameter_name)
            ):
                raise ValueError(f"VR parameter file was not found: {parameter}")
            if not result.get("primary_stem"):
                raise ValueError("VR metadata requires primary_stem")
            for key in ("nout", "nout_lstm"):
                if key in result and int(result[key]) <= 0:
                    raise ValueError(f"{key} must be positive")
        elif family == "mdx":
            is_mdx_c = str(model_path).casefold().endswith(".ckpt") or "config_yaml" in result
            if is_mdx_c:
                config = str(result.get("config_yaml") or "")
                if not config.endswith((".yaml", ".yml")):
                    raise ValueError("MDX-C metadata requires a YAML config")
                from .mdx_c_registry import infer_mdx_c_architecture

                if os.path.basename(config) != config or not infer_mdx_c_architecture(config)[0]:
                    raise ValueError(f"MDX-C configuration is invalid or missing: {config}")
            else:
                for key in ("mdx_dim_f_set", "mdx_dim_t_set", "mdx_n_fft_scale_set"):
                    if int(result.get(key) or 0) <= 0:
                        raise ValueError(f"classic MDX metadata requires positive {key}")
                result["compensate"] = float(result.get("compensate", 1.035))
                if not result.get("primary_stem"):
                    raise ValueError("classic MDX metadata requires primary_stem")
        elif family == "apollo":
            config = str(result.get("config_yaml") or "")
            if not config.endswith((".yaml", ".yml")):
                raise ValueError("Apollo metadata requires config_yaml")
            config_path = os.path.join(paths.APOLLO_CONFIG_PATH, os.path.basename(config))
            if os.path.basename(config) != config or not os.path.isfile(config_path):
                raise ValueError(f"Apollo configuration was not found: {config}")
            try:
                from .apollo import ApolloModelData

                extracted, _raw = ApolloModelData.extract_model_params(config_path)
            except (OSError, TypeError, ValueError) as exc:
                raise ValueError(f"Apollo configuration is invalid: {config}") from exc
            if not extracted:
                raise ValueError(f"Apollo configuration is invalid: {config}")
        else:
            raise ValueError(f"local metadata is not supported for {family} models")
        return result

    def configure(
        self, family: str, process_method: str, model_hash: str,
        payload: dict[str, Any], *, model_path: str = "", replace: bool = False,
    ) -> str:
        validated = self.validate_payload(family, payload, model_path=model_path)
        return self.write_local(process_method, model_hash, validated, replace=replace)

    def reset_local(self, process_method: str, model_hash: str) -> bool:
        path = self.metadata_path(process_method, model_hash)
        if not os.path.isfile(path):
            return False
        os.remove(path)
        if self.repo is not None:
            self.repo.invalidate_models()
        return True
