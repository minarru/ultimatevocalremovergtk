"""Exact catalogue-row identity shared by runtime and maintenance tooling."""

from __future__ import annotations

from typing import Any


def _manifest_catalogue_id(
    family: str,
    selection: str,
    declared_primary: str,
    files: tuple[str, ...],
) -> str | None:
    """Return a reviewed identity only when its exact artifact is present.

    Demucs bags are the important case: their checkpoint member names are
    content hashes, while the reviewed manifest binds the exact source label
    and declared primary member to the executable model identity.
    """
    try:
        from .model_manifest.loader import load_model_manifest

        records = load_model_manifest().models
    except Exception:
        # Identity must stay fail-closed when the bundled authority is not
        # available; callers retain their raw-label fallback in that state.
        return None
    matches = [
        record.model_id
        for record in records.values()
        if record.model_id.startswith(f"{family}:")
        and record.catalogue_evidence.catalogue_label == selection
        and record.catalogue_evidence.primary_artifact == declared_primary
        and declared_primary in files
    ]
    return matches[0] if len(matches) == 1 else None


def catalogue_model_id(
    family: str,
    selection: str,
    raw: Any,
    meta: Any,
) -> str | None:
    """Derive one exact canonical ID from a validated family-scoped row."""
    from .model_identity import ModelId
    from .model_inventory import (
        _entry_files,
        _project_apollo,
        _project_demucs,
        _project_mdx,
        _project_vr,
        artifact_stem,
        validate_artifact_name,
    )

    projector = {
        "vr": _project_vr,
        "mdx": _project_mdx,
        "demucs": _project_demucs,
        "apollo": _project_apollo,
    }.get(family)
    if projector is None or meta is None:
        return None
    try:
        files = _entry_files(meta, raw, family)
    except ValueError:
        return None

    # All catalogue rows have at most one config declaration. A multi-config
    # row is ambiguous even when a projector could select one by insertion
    # order.
    yamls = [name for name in files if name.casefold().endswith((".yaml", ".yml"))]
    if len(yamls) > 1:
        return None

    declared = str(getattr(meta, "checkpoint", "") or "")
    if not declared:
        return None
    try:
        declared = validate_artifact_name(declared, family=family)
    except ValueError:
        return None
    if declared not in files:
        return None

    # For ordinary rows, any second non-YAML artifact is a second primary
    # claim. Demucs bags are the sole exception: a reviewed manifest record
    # declares which member belongs to the logical model.
    primaries = [name for name in files if not name.casefold().endswith((".yaml", ".yml"))]
    if family != "demucs" and (len(primaries) != 1 or declared != primaries[0]):
        return None

    # Reviewed catalogue evidence owns exceptional source layouts. In
    # particular it prevents a hash-named Demucs bag member from becoming the
    # model's runtime basename. The lookup remains exact on family, label, and
    # declared artifact membership; no display or normalized-label matching is
    # involved.
    manifest_id = _manifest_catalogue_id(family, selection, declared, files)
    if manifest_id is not None:
        return manifest_id

    if family == "demucs" and (len(primaries) != 1 or declared != primaries[0]):
        return None

    try:
        record = projector(selection, meta, files)
    except ValueError:
        record = None
    if record is not None:
        return record.id

    try:
        return ModelId(family, artifact_stem(declared)).value
    except ValueError:
        return None


catalogue_presentation_id = catalogue_model_id

__all__ = ["catalogue_model_id", "catalogue_presentation_id"]
