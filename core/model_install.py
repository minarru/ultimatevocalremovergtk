"""One owner for publishing a downloaded model.

Registration, usability verification and repository publication used to be
spread across `DownloadManager.download`, the queue worker and the CLI batch
loop. Each could invalidate independently, so a model could reach the pickers
before every declared artifact had landed, and a multi-model batch produced one
late refresh instead of one per model as it became usable.

This module is the single entry point both frontends call after a transfer.
It is frontend-neutral: no GTK, no CLI reporting, no network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = ["ModelInstallResult", "finalize_downloaded_model"]


@dataclass(frozen=True)
class ModelInstallResult:
    """Outcome of finalizing one logical model.

    ``ready`` -- every declared artifact is present and the model projects an
    installed, identity-complete record.
    ``published`` -- this call owned the repository invalidation.
    ``metadata_changed`` -- registration or ownership indexing wrote something.
    ``detail`` -- actionable text when the item is not ready.
    """

    ready: bool
    published: bool
    metadata_changed: bool = False
    detail: str = ""


def _missing_targets(jobs: Sequence[tuple[str, str]]) -> list[str]:
    return [
        os.path.basename(path)
        for _url, path in jobs
        if not os.path.isfile(path)
    ]


def _register_family(family: str, jobs: Sequence[tuple[str, str]]) -> bool:
    """Run family registration. Helpers report metadata change; none invalidate."""
    changed = False
    job_list = list(jobs)
    if family == "mdx":
        from .mdx_c_registry import register_mdx_c_from_download_jobs

        if register_mdx_c_from_download_jobs(job_list):
            changed = True
    elif family == "apollo":
        from .apollo_registry import register_apollo_from_download_jobs

        if register_apollo_from_download_jobs(job_list):
            changed = True

    from .model_registry import ModelRegistryService

    if ModelRegistryService.index_downloaded(family, job_list):
        changed = True
    return changed


def _candidate_record(repo: Any, family: str, selection: str) -> Any | None:
    """Project a fresh, uncached inventory and find this catalogue entry.

    Deliberately bypasses the published/cached index: this is a precondition
    check that must not write caches, bump generation, notify, fetch or hash.
    """
    from .model_identity import ModelIdentityService
    from .model_inventory import build_identity_index

    snapshot = ModelIdentityService(repo)._snapshot()
    if snapshot is None:
        return None
    index = build_identity_index(repo, snapshot=snapshot)
    for record in index.records():
        entry = record.catalogue_entry
        if entry is not None and entry.family == family and entry.selection == selection:
            return record
    return None


def _catalogue_source(repo: Any, family: str, selection: str) -> str:
    coordinator = getattr(repo, "catalogue", None)
    snapshot = getattr(coordinator, "_latest", None)
    by_family = getattr(snapshot, "entry_sources", None)
    if isinstance(by_family, Mapping):
        sources = by_family.get(family)
        if isinstance(sources, Mapping):
            source = str(sources.get(selection) or "").strip()
            if source:
                return source
    return "catalogue"


def finalize_downloaded_model(
    *,
    repo: Any,
    family: str,
    selection: str,
    jobs: Sequence[tuple[str, str]],
    transfer_result: str,
) -> ModelInstallResult:
    """Register, verify and publish one downloaded logical model.

    Publishes at most one full invalidation, and only once the model is
    actually usable. An unchanged ``exists`` transfer with intact metadata is
    ready but publishes nothing: there is no change to repaint.
    """
    from .debug_log import debug

    if transfer_result not in ("complete", "exists"):
        return ModelInstallResult(
            ready=False,
            published=False,
            detail=f"transfer did not complete ({transfer_result})",
        )

    missing = _missing_targets(jobs)
    if missing:
        return ModelInstallResult(
            ready=False,
            published=False,
            detail=f"missing downloaded artifacts: {', '.join(missing)}",
        )

    metadata_changed = _register_family(family, jobs)

    if getattr(repo, "catalogue", None) is None:
        return ModelInstallResult(
            ready=False,
            published=False,
            metadata_changed=metadata_changed,
            detail="no catalogue snapshot is available to verify the download",
        )

    record = _candidate_record(repo, family, selection)
    if record is None:
        return ModelInstallResult(
            ready=False,
            published=False,
            metadata_changed=metadata_changed,
            detail=(
                f"no catalogue record for {family}:{selection} after download"
            ),
        )
    if not record.installed:
        return ModelInstallResult(
            ready=False,
            published=False,
            metadata_changed=metadata_changed,
            detail=f"{record.id} did not project as installed after download",
        )
    if not record.identity_complete:
        return ModelInstallResult(
            ready=False,
            published=False,
            metadata_changed=metadata_changed,
            detail=(
                record.identity_error
                or f"{record.id} is installed but not identity-complete"
            ),
        )

    from .model_registry import ModelRegistryService

    try:
        presentation_changed = ModelRegistryService.remember_presentation(
            record.id,
            catalogue_label=selection,
            catalogue_source=_catalogue_source(repo, family, selection),
        )
    except (OSError, ValueError) as exc:
        return ModelInstallResult(
            ready=False,
            published=False,
            metadata_changed=metadata_changed,
            detail=(
                f"could not persist presentation evidence for {record.id}; "
                f"retry the download finalization: {type(exc).__name__}: {exc}"
            ),
        )

    metadata_changed = metadata_changed or presentation_changed
    changed = transfer_result == "complete" or metadata_changed
    if changed:
        debug("model", f"publish {record.id} after download")
        repo.invalidate_models()
    return ModelInstallResult(
        ready=True,
        published=bool(changed),
        metadata_changed=metadata_changed,
    )
