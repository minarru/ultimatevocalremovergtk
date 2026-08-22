"""Logical model inventory projected from catalogue and installed artifacts."""

from __future__ import annotations

import os
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
    text = str(name).replace("\\", "/")
    path = PurePosixPath(text)
    if (
        not text
        or text.startswith("/")
        or path.is_absolute()
        or PureWindowsPath(str(name)).is_absolute()
    ):
        raise ValueError(f"invalid {family} artifact path {name!r}")
    if any(part in {"", ".", ".."} for part in text.split("/")):
        raise ValueError(f"invalid {family} artifact path {name!r}")
    normalized = path.as_posix()
    if normalized.startswith("../"):
        raise ValueError(f"invalid {family} artifact path {name!r}")
    return normalized


def _entry_files(entry: Any, raw: Any, family: str) -> tuple[str, ...]:
    source = getattr(entry, "files", None)
    if not isinstance(source, Mapping):
        source = raw if isinstance(raw, Mapping) else {str(raw): ""}
    names: list[str] = []
    for item in source:
        try:
            names.append(validate_artifact_name(str(item), family=family))
        except ValueError:
            continue
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
    return ModelRecord(
        id=f"{family}:{basename}",
        family=family,
        basename=basename,
        display=display,
        backend_name=backend_name,
        artifacts=ModelArtifacts(primary, tuple(supporting)),
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


def _demucs_spec(entry: Any) -> DemucsSpec | None:
    text = f"{getattr(entry, 'label', '')} {getattr(entry, 'display', '')}".casefold()
    version = next((value for value in ("v1", "v2", "v3", "v4") if value in text), None)
    stems = tuple(getattr(entry, "stems", ()) or ())
    layout = {2: "2_stem", 4: "4_stem", 6: "6_stem"}.get(len(stems))
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
            record = projector(
                str(selection), entry, _entry_files(entry, raw, family)
            )
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


def _installed_record(repo: Any, family: str, filename: str) -> ModelRecord | None:
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
        yaml_name = next(
            (
                name for name in _installed_files(repo, family)
                if name.casefold().endswith(_YAML_SUFFIXES)
                and artifact_stem(name) == basename
            ),
            None,
        )
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
        return _record(
            family, basename, basename, filename, filename, installed=True
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
        (record.family, record.artifacts.primary_filename): index
        for index, record in enumerate(result)
    }
    supporting = {
        (record.family, name)
        for record in result
        for name in record.artifacts.supporting_filenames
    }
    for family in ("vr", "mdx", "demucs", "apollo"):
        files = _installed_files(repo, family)
        demucs_bags, demucs_members = (
            _installed_demucs_bags(repo, files) if family == "demucs" else ({}, set())
        )
        for filename in files:
            key = (family, filename)
            if key in supporting or filename in demucs_members:
                continue
            existing = by_primary.get(key)
            if existing is not None:
                result[existing] = replace(result[existing], installed=True)
                continue
            if filename in demucs_bags:
                basename = artifact_stem(filename)
                result.append(_record(
                    "demucs", basename, basename, basename, filename,
                    demucs_bags[filename], installed=True, complete=False,
                    error=f"unknown Demucs version or source layout for {filename}",
                ))
                continue
            record = _installed_record(repo, family, filename)
            if record is not None:
                result.append(record)
    return result


def _apply_bundled_demucs(
    records: list[ModelRecord],
    bundled: Mapping[str, DemucsSpec],
    registered: Mapping[str, Any],
) -> list[ModelRecord]:
    result: list[ModelRecord] = []
    for record in records:
        if record.family != "demucs":
            result.append(record)
            continue
        spec = bundled.get(record.basename)
        custom = registered.get(record.basename)
        if spec is None and isinstance(custom, DemucsSpec):
            spec = custom
        if spec is None:
            result.append(record)
        else:
            result.append(replace(
                record, demucs=spec, identity_complete=True, identity_error=None
            ))
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
    records = _catalogue_records(snapshot) if snapshot is not None else []
    records = _merge_installed(repo, records)
    records = _apply_bundled_demucs(
        records, bundled_demucs_specs or {}, registered_demucs or {}
    )
    return IdentityIndex(_detect_collisions(records))
