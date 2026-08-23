"""Logical model inventory projected from catalogue and installed artifacts."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping, cast

import yaml

from .model_identity import (
    CatalogueRef,
    DemucsSpec,
    IdentityIndex,
    MdxSpec,
    ModelArtifacts,
    ModelId,
    ModelRecord,
)

_ARTIFACT_SUFFIXES = (
    ".th.gz",
    ".ckpt",
    ".onnx",
    ".pth",
    ".yaml",
    ".yml",
    ".th",
    ".bin",
    ".gz",
)
_CHECKPOINT_SUFFIXES = (".ckpt", ".onnx")
_YAML_SUFFIXES = (".yaml", ".yml")
_MDX_KIND_HINTS = (
    ("mel_band_roformer", ("mel_band_roformer", "melband_roformer")),
    ("bs_roformer", ("bs_roformer", "bandsplit_roformer", "band_split_roformer")),
    ("scnet_masked", ("scnet_masked",)),
    ("scnet_tran", ("scnet_tran",)),
    ("scnet", ("scnet",)),
    ("bandit_v2", ("bandit_v2",)),
    ("bandit", ("bandit",)),
    ("mdx23c", ("mdx23c",)),
)
_CASE_INSENSITIVE_FS = os.path.normcase("A") == os.path.normcase("a")


def _artifact_key(family: str, filename: str) -> tuple[str, str]:
    name = os.path.normcase(filename) if _CASE_INSENSITIVE_FS else filename
    return (family, name)


def artifact_stem(filename: str) -> str:
    """Strip one recognized model-artifact suffix, including compound ones."""
    name = os.path.basename(str(filename))
    folded = name.casefold()
    for suffix in _ARTIFACT_SUFFIXES:
        if folded.endswith(suffix):
            return name[: -len(suffix)]
    return name


def validate_artifact_name(name: str, *, family: str) -> str:
    """Validate and normalize a model-root-relative artifact name."""
    text = str(name or "").replace("\\", "/").strip()
    path = PurePosixPath(text)
    if (
        not text
        or text.startswith("/")
        or text.startswith("~")
        or path.is_absolute()
        or PureWindowsPath(str(name)).is_absolute()
    ):
        raise ValueError(f"illegal artifact path {name!r}")
    if any(part in {"", ".", ".."} for part in text.split("/")):
        raise ValueError(f"illegal artifact path {name!r}")
    normalized = path.as_posix()
    if normalized.startswith("../"):
        raise ValueError(f"illegal artifact path {name!r}")
    if len(path.parts) != 1:
        raise ValueError(f"unsupported {family} artifact layout {name!r}")
    return normalized


def _entry_files(entry: Any, raw: Any, family: str) -> tuple[str, ...]:
    source = getattr(entry, "files", None)
    if not isinstance(source, Mapping):
        source = raw if isinstance(raw, Mapping) else {str(raw): ""}
    names: list[str] = []
    for item in source:
        names.append(validate_artifact_name(str(item), family=family))
    return tuple(names)


def _record(
    family: str,
    basename: str,
    display: str,
    backend_name: str,
    primary: str,
    supporting: Iterable[str] = (),
    *,
    installed: bool = False,
    selection: str | None = None,
    complete: bool = True,
    error: str | None = None,
    demucs: DemucsSpec | None = None,
    mdx: MdxSpec | None = None,
) -> ModelRecord:
    primary = validate_artifact_name(primary, family=family)
    supporting = tuple(
        validate_artifact_name(name, family=family) for name in supporting
    )
    model_id = ModelId(family, basename)
    return ModelRecord(
        id=model_id.value,
        family=family,
        basename=basename,
        display=display,
        backend_name=backend_name,
        artifacts=ModelArtifacts(primary, supporting),
        installed=installed,
        catalogue_entry=CatalogueRef(family, selection) if selection else None,
        identity_complete=complete,
        identity_error=error,
        demucs=demucs,
        mdx=mdx,
    )


def _project_vr(selection: str, entry: Any, files: tuple[str, ...]) -> ModelRecord | None:
    primaries = [name for name in files if name.casefold().endswith(".pth")]
    if len(primaries) != 1:
        return None
    primary = primaries[0]
    basename = artifact_stem(primary)
    return _record(
        "vr", basename, str(getattr(entry, "display", basename)), basename, primary,
        (name for name in files if name != primary), selection=selection,
    )


def _mdx_kind(files: Iterable[str], yaml_path: str | None = None) -> MdxSpec | None:
    names = tuple(files)
    if any(name.casefold().endswith(".onnx") for name in names):
        return MdxSpec("classic_onnx")
    tokens = " ".join(names).casefold().replace("-", "_")
    if yaml_path:
        try:
            with open(yaml_path, encoding="utf-8") as handle:
                document = yaml.safe_load(handle)
            if isinstance(document, Mapping):
                tokens += " " + str(document.get("model_type") or "").casefold()
        except (OSError, yaml.YAMLError):
            pass
    for kind, hints in _MDX_KIND_HINTS:
        if any(hint in tokens for hint in hints):
            return MdxSpec(kind)  # type: ignore[arg-type]
    return None


def _project_mdx(selection: str, entry: Any, files: tuple[str, ...]) -> ModelRecord | None:
    checkpoints = [name for name in files if name.casefold().endswith(_CHECKPOINT_SUFFIXES)]
    yamls = [name for name in files if name.casefold().endswith(_YAML_SUFFIXES)]
    if not checkpoints:
        return None
    declared = str(getattr(entry, "checkpoint", "") or "")
    primary = declared if declared in checkpoints else checkpoints[0]
    ambiguous = len(checkpoints) != 1 or len(yamls) > 1
    kind = _mdx_kind(files)
    complete = not ambiguous and (primary.casefold().endswith(".onnx") or kind is not None)
    error = None
    if ambiguous:
        error = f"ambiguous MDX artifacts: {', '.join((*checkpoints, *yamls))}"
    elif kind is None:
        error = f"unknown MDX YAML architecture for {primary}"
    basename = artifact_stem(primary)
    return _record(
        "mdx", basename, str(getattr(entry, "display", basename)), basename, primary,
        yamls, selection=selection, complete=complete, error=error, mdx=kind,
    )


def _demucs_version_from_label(entry: Any) -> str | None:
    for value in (getattr(entry, "label", ""), getattr(entry, "display", "")):
        match = re.fullmatch(
            r"(?:Demucs )?v([1-4])(?:\s*:\s*|\s*\|\s*)(.+)", str(value)
        )
        if match:
            return f"v{match.group(1)}"
    return None


def _demucs_layout_from_stems(entry: Any) -> str | None:
    stems = tuple(getattr(entry, "stems", ()) or ())
    return {2: "2_stem", 4: "4_stem", 6: "6_stem"}.get(len(stems))


def _demucs_spec(entry: Any) -> DemucsSpec | None:
    version = getattr(entry, "demucs_version", None)
    if version not in {"v1", "v2", "v3", "v4"}:
        version = _demucs_version_from_label(entry)

    layout = getattr(entry, "source_layout", None)
    if layout not in {"2_stem", "4_stem", "6_stem"}:
        layout = _demucs_layout_from_stems(entry)

    if version is None or layout is None:
        return None
    return DemucsSpec(version, layout)  # type: ignore[arg-type]


def _project_demucs(
    selection: str, entry: Any, files: tuple[str, ...]
) -> ModelRecord | None:
    yamls = [name for name in files if name.casefold().endswith(_YAML_SUFFIXES)]
    if len(yamls) > 1:
        return None
    if yamls:
        primary = yamls[0]
        supporting = tuple(name for name in files if name != primary)
    else:
        weights = [
            name for name in files
            if name.casefold().endswith((".th", ".th.gz"))
        ]
        if len(weights) != 1:
            return None
        primary = weights[0]
        supporting = ()
    basename = artifact_stem(primary)
    spec = _demucs_spec(entry)
    return _record(
        "demucs", basename, str(getattr(entry, "display", basename)), basename,
        primary, supporting, selection=selection, complete=spec is not None,
        error=None if spec else f"unknown Demucs version or source layout for {primary}",
        demucs=spec,
    )


def _project_apollo(
    selection: str, entry: Any, files: tuple[str, ...]
) -> ModelRecord | None:
    checkpoints = [
        name for name in files if name.casefold().endswith((".ckpt", ".bin"))
    ]
    if len(checkpoints) != 1:
        return None
    primary = checkpoints[0]
    basename = artifact_stem(primary)
    return _record(
        "apollo", basename, str(getattr(entry, "display", basename)), primary,
        primary, (name for name in files if name != primary), selection=selection,
    )


def _catalogue_records(snapshot: Any) -> list[ModelRecord]:
    records: list[ModelRecord] = []
    meta_by_family = getattr(snapshot, "meta_by_family", {}) or {}
    projectors = {
        "vr": _project_vr,
        "mdx": _project_mdx,
        "demucs": _project_demucs,
        "apollo": _project_apollo,
    }
    for family, projector in projectors.items():
        catalogue = getattr(snapshot, family, {}) or {}
        metadata = meta_by_family.get(family, {}) if isinstance(meta_by_family, Mapping) else {}
        for selection, raw in catalogue.items():
            entry = metadata.get(selection)
            if entry is None:
                continue
            # Catalogue content comes from four network sources. An illegal
            # artifact name in any single row must drop that row, not raise out
            # of ``build_identity_index`` and empty every model picker.
            try:
                record = projector(
                    str(selection), entry, _entry_files(entry, raw, family)
                )
            except ValueError as exc:
                from .debug_log import debug

                debug(
                    "model",
                    f"catalogue row rejected family={family} "
                    f"selection={selection!r}: {exc}",
                )
                continue
            if record is not None:
                records.append(record)
    return records


def _installed_files(repo: Any, family: str) -> tuple[str, ...]:
    provider = getattr(repo, "_model_artifact_files", None)
    if not callable(provider):
        return ()
    values = provider(family)
    if not isinstance(values, Iterable):
        return ()
    return tuple(str(name) for name in values)


def _mdx_installed_yaml(files: tuple[str, ...], checkpoint_filename: str) -> str | None:
    """Pick the yaml that belongs to one installed MDX checkpoint.

    ``files`` is the caller's already-listed MDX artifact set: this used to
    re-list the directory for every installed ``.ckpt``, making one index build
    O(n) directory listings in the MDX family alone.
    """
    yamls = [name for name in files if name.casefold().endswith(_YAML_SUFFIXES)]
    checkpoints = [name for name in files if name.casefold().endswith(".ckpt")]
    if len(yamls) == 1 and len(checkpoints) == 1:
        return yamls[0]
    basename = artifact_stem(checkpoint_filename)
    for name in yamls:
        if artifact_stem(name) == basename:
            return name
    return None


def _trusted_local_metadata(
    repo: Any,
    family: str,
    checkpoint_filename: str,
    hash_directory: str,
) -> Mapping[str, Any] | None:
    """Read hash-keyed metadata for a checkpoint already trusted by its owner."""
    import json

    path_provider = getattr(repo, "_model_artifact_path", None)
    if not callable(path_provider):
        return None
    checkpoint_path = str(path_provider(family, checkpoint_filename))
    hash_table = getattr(repo, "model_hash_table", None) or {}
    model_hash = hash_table.get(checkpoint_path)
    if not isinstance(model_hash, str) or not model_hash:
        return None
    json_path = os.path.join(hash_directory, f"{model_hash}.json")
    if not os.path.isfile(json_path):
        return None
    try:
        with open(json_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return payload


def _mdx_spec_from_architecture(architecture: str, yaml_name: str) -> MdxSpec | None:
    kinds = {
        "MDX23C": "mdx23c",
        "Mel-Band Roformer": "mel_band_roformer",
        "BS Roformer": "bs_roformer",
        "SCNet": "scnet",
        "SCNet Masked": "scnet_masked",
        "SCNet Tran": "scnet_tran",
        "Bandit": "bandit_v2" if "bandit_v2" in yaml_name.casefold() else "bandit",
    }
    kind = kinds.get(architecture)
    return MdxSpec(kind) if kind is not None else None  # type: ignore[arg-type]


def _trusted_mdx_config(
    repo: Any, checkpoint_filename: str
) -> tuple[str, MdxSpec | None] | None:
    """Return exact trusted YAML evidence, even before the YAML is available."""
    from . import paths
    from .mdx_c_registry import infer_mdx_c_architecture

    payload = _trusted_local_metadata(
        repo, "mdx", checkpoint_filename, paths.MDX_HASH_DIR
    )
    if payload is None:
        return None
    config = payload.get("config_yaml")
    if not isinstance(config, str) or not config.casefold().endswith(_YAML_SUFFIXES):
        return None
    try:
        yaml_name = validate_artifact_name(config, family="mdx")
    except ValueError:
        return None
    architecture, _is_roformer = infer_mdx_c_architecture(yaml_name)
    spec = _mdx_spec_from_architecture(architecture, yaml_name)
    return yaml_name, spec


def _apollo_config_name(repo: Any, checkpoint_filename: str) -> str | None:
    from . import paths

    payload = _trusted_local_metadata(
        repo, "apollo", checkpoint_filename, paths.APOLLO_HASH_DIR
    )
    if payload is None:
        return None
    config = payload.get("config_yaml")
    return str(config) if config else None


def _installed_record(
    repo: Any, family: str, filename: str, files: tuple[str, ...] = ()
) -> ModelRecord | None:
    folded = filename.casefold()
    basename = artifact_stem(filename)
    if family == "vr" and folded.endswith(".pth"):
        return _record(family, basename, basename, basename, filename, installed=True)
    if family == "mdx" and folded.endswith(".onnx"):
        return _record(
            family, basename, basename, basename, filename, installed=True,
            mdx=MdxSpec("classic_onnx"),
        )
    if family == "mdx" and folded.endswith(".ckpt"):
        path_provider = getattr(repo, "_model_artifact_path", None)
        trusted_config = _trusted_mdx_config(repo, filename)
        if trusted_config is not None:
            yaml_name, kind = trusted_config
        else:
            yaml_name = _mdx_installed_yaml(files, filename)
            yaml_path = cast(
                str | None,
                path_provider(family, yaml_name)
                if yaml_name and callable(path_provider)
                else None,
            )
            kind = _mdx_kind((filename, yaml_name or ""), yaml_path)
        return _record(
            family, basename, basename, basename, filename,
            (yaml_name,) if yaml_name else (), installed=True,
            complete=kind is not None,
            error=None if kind else f"unknown MDX YAML architecture for {filename}",
            mdx=kind,
        )
    if family == "demucs" and folded.endswith((".th", ".th.gz", ".yaml", ".yml")):
        spec = None
        return _record(
            family, basename, basename, basename, filename, installed=True,
            complete=False, error=f"unknown Demucs version or source layout for {filename}",
            demucs=spec,
        )
    if family == "apollo" and folded.endswith((".ckpt", ".bin")):
        config_name = _apollo_config_name(repo, filename)
        supporting = (config_name,) if config_name else ()
        return _record(
            family, basename, basename, filename, filename, supporting,
            installed=True,
        )
    return None


def _installed_demucs_bags(
    repo: Any, files: tuple[str, ...]
) -> tuple[dict[str, tuple[str, ...]], set[str]]:
    bags: dict[str, tuple[str, ...]] = {}
    members: set[str] = set()
    path_provider = getattr(repo, "_model_artifact_path", None)
    if not callable(path_provider):
        return bags, members
    for yaml_name in files:
        if not yaml_name.casefold().endswith(_YAML_SUFFIXES):
            continue
        try:
            with open(str(path_provider("demucs", yaml_name)), encoding="utf-8") as handle:
                document = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(document, Mapping):
            continue
        signatures = tuple(str(item) for item in (document.get("models") or ()) if item)
        owned = tuple(
            name
            for name in files
            if name.casefold().endswith((".th", ".th.gz"))
            and any(artifact_stem(name).startswith(f"{signature}-") for signature in signatures)
        )
        bags[yaml_name] = owned
        members.update(owned)
    return bags, members


def _merge_installed(repo: Any, records: list[ModelRecord]) -> list[ModelRecord]:
    result = list(records)
    by_primary = {
        _artifact_key(record.family, record.artifacts.primary_filename): index
        for index, record in enumerate(result)
    }
    supporting = {
        _artifact_key(record.family, name)
        for record in result
        for name in record.artifacts.supporting_filenames
    }
    for family in ("vr", "mdx", "demucs", "apollo"):
        files = _installed_files(repo, family)
        demucs_bags, demucs_members = (
            _installed_demucs_bags(repo, files) if family == "demucs" else ({}, set())
        )
        for filename in files:
            key = _artifact_key(family, filename)
            if key in supporting or filename in demucs_members:
                continue
            existing = by_primary.get(key)
            if existing is not None:
                catalogue_record = result[existing]
                if family == "mdx" and not catalogue_record.identity_complete:
                    local_record = _installed_record(repo, family, filename, files)
                    if local_record is not None:
                        local_supporting = (
                            local_record.artifacts.supporting_filenames
                            or catalogue_record.artifacts.supporting_filenames
                        )
                        mdx = local_record.mdx or catalogue_record.mdx
                        complete = (
                            catalogue_record.identity_complete
                            or local_record.identity_complete
                        )
                        result[existing] = replace(
                            catalogue_record,
                            artifacts=replace(
                                catalogue_record.artifacts,
                                supporting_filenames=local_supporting,
                            ),
                            installed=True,
                            identity_complete=complete,
                            identity_error=(
                                None
                                if complete
                                else local_record.identity_error
                                or catalogue_record.identity_error
                            ),
                            mdx=mdx,
                        )
                    else:
                        result[existing] = replace(
                            catalogue_record, installed=True
                        )
                else:
                    result[existing] = replace(
                        catalogue_record, installed=True
                    )
                continue
            try:
                if filename in demucs_bags:
                    basename = artifact_stem(filename)
                    record = _record(
                        "demucs", basename, basename, basename, filename,
                        demucs_bags[filename], installed=True, complete=False,
                        error=f"unknown Demucs version or source layout for {filename}",
                    )
                else:
                    record = _installed_record(repo, family, filename, files)
            except ValueError as exc:
                # Same rule as the catalogue rows: one unrepresentable filename
                # on disk (a leading ``~``, say) drops that model, it does not
                # empty the index for every other one.
                from .debug_log import debug

                debug(
                    "model",
                    f"installed artifact rejected family={family} "
                    f"file={filename!r}: {exc}",
                )
                continue
            if record is not None:
                result.append(record)
    return result


def _apply_bundled_demucs(
    records: list[ModelRecord],
    bundled: Mapping[str, DemucsSpec],
) -> list[ModelRecord]:
    result: list[ModelRecord] = []
    for record in records:
        if record.family != "demucs":
            result.append(record)
            continue
        spec = bundled.get(record.id) or record.demucs
        if spec is None:
            result.append(record)
        else:
            result.append(replace(
                record, demucs=spec, identity_complete=True, identity_error=None
            ))
    return result


def _registered_demucs_bag_membership_error(
    entrypoint_path: str, supporting_paths: tuple[str, ...]
) -> str | None:
    if not entrypoint_path.casefold().endswith(".yaml"):
        return None
    try:
        with open(entrypoint_path, encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError):
        return "registered Demucs bag membership is unreadable"
    if not isinstance(document, Mapping):
        return "registered Demucs bag membership root is invalid"
    raw_models = document.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        return "registered Demucs bag membership list is empty or invalid"

    directory = os.path.dirname(entrypoint_path)
    recorded = {os.path.realpath(path) for path in supporting_paths}
    referenced: set[str] = set()
    try:
        adjacent = os.listdir(directory)
    except OSError:
        return "registered Demucs bag membership directory is unavailable"
    for signature in raw_models:
        if not isinstance(signature, str) or not signature:
            return "registered Demucs bag membership contains an invalid signature"
        matches = [
            os.path.realpath(os.path.join(directory, name))
            for name in adjacent
            if name.startswith(f"{signature}-")
            and name.casefold().endswith(".th")
            and os.path.isfile(os.path.join(directory, name))
        ]
        if len(matches) != 1 or matches[0] not in recorded:
            return f"registered Demucs bag membership mismatch for {signature}"
        referenced.add(matches[0])
    if referenced != recorded:
        return "registered Demucs bag membership has unreferenced artifacts"
    return None


def _apply_registered_demucs(
    records: list[ModelRecord],
    registered: Mapping[str, Any],
) -> list[ModelRecord]:
    from . import paths

    result: list[ModelRecord] = []
    for record in records:
        raw = registered.get(record.id) if record.family == "demucs" else None
        if not isinstance(raw, Mapping):
            result.append(record)
            continue
        entrypoint_path = str(raw.get("entrypoint") or "")
        supporting_paths = tuple(
            str(path) for path in (raw.get("supporting_artifacts") or ())
        )
        entrypoint = os.path.basename(entrypoint_path)
        supporting = tuple(
            os.path.basename(path) for path in supporting_paths
        )
        absolute_paths = tuple(
            os.path.join(
                paths.DEMUCS_MODELS_DIR, relative.replace("/", os.sep)
            )
            for relative in (entrypoint_path, *supporting_paths)
        )
        missing = [
            relative
            for relative, absolute in zip(
                (entrypoint_path, *supporting_paths), absolute_paths, strict=True
            )
            if not os.path.isfile(absolute)
        ]
        membership_error = (
            _registered_demucs_bag_membership_error(
                absolute_paths[0], absolute_paths[1:]
            )
            if not missing else None
        )
        spec = DemucsSpec(
            str(raw.get("demucs_version")),  # type: ignore[arg-type]
            str(raw.get("source_layout")),  # type: ignore[arg-type]
        )
        result.append(replace(
            record,
            display=str(raw.get("display_name") or record.display),
            backend_name=str(raw.get("backend_name") or record.backend_name),
            artifacts=ModelArtifacts(entrypoint, supporting),
            demucs=spec,
            identity_complete=not missing and membership_error is None,
            identity_error=(
                f"missing registered Demucs artifacts: {', '.join(missing)}"
                if missing else membership_error
            ),
        ))
    return result


#: Presentation-only sources, by family. VR has a catalogue display index but
#: no legacy name mapper; Apollo has neither and keeps whatever display its
#: catalogue or registration record already carried.
_DISPLAY_INDEX_ATTR = {
    "vr": "display_index_vr",
    "mdx": "display_index_mdx",
    "demucs": "display_index_demucs",
}

_NAME_MAPPER_ATTR = {
    "mdx": "mdx_name_select_MAPPER",
    "demucs": "demucs_name_select_MAPPER",
}


def _record_display(
    repo: Any, record: ModelRecord, snapshot: Any | None
) -> str | None:
    """Resolve one record's friendly label from exact evidence only.

    Returns ``None`` when the record already carries its authoritative label, so
    the caller never has to compare presentation text: comparing ``display`` is
    the inversion that lets a catalogue rename move an existing selection, and
    ``tests/test_no_runtime_display_inversion.py`` forbids it outright.
    """
    from .model_display import lookup_mapper_display_exact

    current = str(record.display or "").strip()
    if current and current != record.basename:
        return None

    attribute = _DISPLAY_INDEX_ATTR.get(record.family)
    if attribute and snapshot is not None:
        index = getattr(snapshot, attribute, None)
        if isinstance(index, Mapping):
            candidate = str(index.get(record.basename) or "").strip()
            # A catalogue that only echoes the basename is not a friendly label.
            if candidate and candidate != record.basename:
                return candidate

    mapper_attribute = _NAME_MAPPER_ATTR.get(record.family)
    if mapper_attribute:
        mapper = getattr(repo, mapper_attribute, None)
        if isinstance(mapper, Mapping):
            mapped = lookup_mapper_display_exact(record.basename, mapper)
            candidate = str(mapped or "").strip()
            if candidate:
                return candidate

    # Nothing friendly is known. The raw basename is the label, so only rebuild
    # the record when it is not already carrying it.
    return None if current == record.basename else record.basename


def _enrich_record_displays(
    repo: Any, records: list[ModelRecord], snapshot: Any | None
) -> list[ModelRecord]:
    """Give every record its authoritative display label, presentation only.

    Runs once after all catalogue/installed/Demucs merges so that
    ``ModelRecord.display`` is the single friendly label every consumer reads.
    Only ``.display`` may change here: identity, artifacts and execution specs
    are already final, and the identity digest excludes display.
    """
    result: list[ModelRecord] = []
    for record in records:
        display = _record_display(repo, record, snapshot)
        result.append(
            record if display is None else replace(record, display=display)
        )
    return result


def _detect_collisions(records: list[ModelRecord]) -> dict[str, ModelRecord]:
    grouped: dict[str, list[ModelRecord]] = {}
    for record in records:
        grouped.setdefault(record.id, []).append(record)
    result: dict[str, ModelRecord] = {}
    for model_id, matches in grouped.items():
        primaries = {item.artifacts.primary_filename for item in matches}
        if len(primaries) > 1:
            names = ", ".join(sorted(primaries))
            result[model_id] = replace(
                matches[0], identity_complete=False,
                identity_error=f"identity collision between {names}",
                installed=any(item.installed for item in matches),
            )
            continue
        merged = matches[0]
        if any(item.installed for item in matches) and not merged.installed:
            merged = replace(merged, installed=True)
        result[model_id] = merged
    return result


def build_identity_index(
    repo: Any,
    *,
    snapshot: Any | None,
    bundled_demucs_specs: Mapping[str, DemucsSpec] | None = None,
    registered_demucs: Mapping[str, Any] | None = None,
) -> IdentityIndex:
    """Build the logical inventory without network access or checkpoint hashing."""
    if bundled_demucs_specs is None:
        from .demucs_registry import load_bundled_demucs_specs

        bundled_demucs_specs = load_bundled_demucs_specs()
    if registered_demucs is None:
        from .demucs_registry import DemucsRegistry

        registered_demucs = cast(
            Mapping[str, Any], DemucsRegistry().load_read_only()["models"]
        )
    records = _catalogue_records(snapshot) if snapshot is not None else []
    records = _merge_installed(repo, records)
    records = _apply_bundled_demucs(records, bundled_demucs_specs)
    records = _apply_registered_demucs(records, registered_demucs)
    records = _enrich_record_displays(repo, records, snapshot)
    return IdentityIndex(_detect_collisions(records))
