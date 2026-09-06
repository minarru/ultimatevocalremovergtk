"""Model catalogue command operations."""

from __future__ import annotations

import argparse
import dataclasses
import sys
from typing import Any

from ..reporting import emit_document, emit_event, fail, report_mode
from .formatting import _print_rows


def cmd_models_catalog(args: argparse.Namespace) -> int:
    from core.catalogue_coordinator import CatalogueCoordinator
    from core.downloads import DownloadManager
    from core.model_catalogue import ModelCatalogueService

    coordinator = CatalogueCoordinator()
    try:
        service = ModelCatalogueService(DownloadManager(coordinator=coordinator))
        usable = service.refresh(offline=args.offline)
        if not usable:
            return fail(args, "could not refresh the model catalogue", exit_code=1, kind="runtime")
        if not args.offline:
            _emit_catalogue_status(args, getattr(service.manager, "_last_refresh_report", None))
            from core.download_sizes import prefetch_remote_sizes

            prefetch_remote_sizes(service.manager.catalogue_checkpoint_urls())
            service._records = None
        rows = []
        for row in service.filter(
            family=args.family,
            query=args.query,
            purpose=args.purpose,
            supported=args.supported,
            installed=args.installed,
        ):
            item = dataclasses.asdict(row)
            if not item.get("catalogue_evidence_warning"):
                item.pop("catalogue_evidence_warning", None)
            from core.model_catalogue import catalogue_entry_meta

            meta = catalogue_entry_meta(service.manager, row.family, row.selection)
            projection = getattr(meta, "stem_semantics", None)
            if projection is not None:
                item.update(projection.as_dict())
                item["canonical_roles"] = list(projection.canonical_roles)
                item["stem_semantics_evidence"] = projection.evidence
                item["catalogue_guessed_intent"] = getattr(meta, "guessed_intent", None)
            rows.append(item)
        return _print_rows(args, rows)
    finally:
        coordinator.close()


def _emit_catalogue_status(args: argparse.Namespace, report: Any) -> None:
    from core.catalogue_types import RefreshReport

    if not isinstance(report, RefreshReport):
        return
    if report.upstream_live and not report.failed:
        return
    payload = report.as_dict()
    emit_event(args, "catalogue_status", **payload)
    if report_mode(args) == "human":
        bits = []
        if not payload.get("upstream_live"):
            bits.append("saved catalogue")
        if payload.get("partial") or payload.get("failed"):
            bits.append("partial refresh")
        if payload.get("stale"):
            bits.append("stale sources")
        detail = ", ".join(bits) or "mixed-age snapshot"
        print(f"warning: using {detail}", file=sys.stderr)


def cmd_models_download(args: argparse.Namespace) -> int:
    from core.catalogue_coordinator import CatalogueCoordinator

    coordinator = CatalogueCoordinator()
    try:
        return _cmd_models_download_body(args, coordinator)
    finally:
        coordinator.close()


def _cmd_models_download_body(args: argparse.Namespace, coordinator: Any) -> int:
    import signal
    import threading

    from core.downloads import DownloadManager
    from core.model_catalogue import ModelCatalogueService
    from core.model_repository import ModelRepository

    service = ModelCatalogueService(DownloadManager(coordinator=coordinator))
    try:
        usable = service.refresh(offline=args.offline)
        if not usable:
            return fail(args, "could not refresh the model catalogue", exit_code=1, kind="runtime")
        if not args.offline:
            _emit_catalogue_status(args, getattr(service.manager, "_last_refresh_report", None))
        records = [service.resolve(value) for value in args.entries]
        resolved = service.jobs(records)
        unsupported = [record.id for record, _jobs in resolved if not record.supported]
        if unsupported:
            raise ValueError(f"unsupported catalogue entry: {unsupported[0]}")
        if any(not jobs for _record, jobs in resolved):
            raise ValueError("one or more catalogue entries have no downloadable files")
    except ValueError as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)

    stop_event = threading.Event()
    interrupts = {"count": 0}

    def request_stop(*_unused: Any) -> None:
        interrupts["count"] += 1
        stop_event.set()
        if interrupts["count"] > 1:
            raise KeyboardInterrupt

    previous = signal.getsignal(signal.SIGINT)
    try:
        signal.signal(signal.SIGINT, request_stop)
    except (OSError, ValueError):
        previous = None
    outcomes: list[dict[str, Any]] = []
    # Same coordinator the manager meshed: the finalizer verifies each download
    # against the already-published snapshot rather than fetching its own.
    repo = ModelRepository(catalogue=coordinator)
    # Ahead of the loop on purpose. Run after publication it would be a second
    # full invalidation for models that already published themselves.
    service.manager.update_model_settings(repo)
    try:
        for record, jobs in resolved:
            emit_event(args, "started", command="models.download", input=record.id)
            try:
                result = service.manager.download(
                    list(jobs),
                    on_progress=lambda fraction, model=record.id: emit_event(
                        args, "progress", fraction=fraction, input=model
                    ),
                    on_info=(None if args.quiet else lambda text: print(text, file=sys.stderr)),
                    stop_event=stop_event,
                )
                status = "success" if result in {"complete", "exists"} else "failed"
                item = {"input": record.id, "status": status, "result": result}
                if stop_event.is_set():
                    item.update(status="failed", error="interrupted")
                if item["status"] == "success":
                    from core.model_install import finalize_downloaded_model

                    outcome = finalize_downloaded_model(
                        repo=repo,
                        family=record.family,
                        selection=record.selection,
                        jobs=list(jobs),
                        transfer_result=result,
                    )
                    if not outcome.ready:
                        item.update(status="failed", error=outcome.detail)
            except KeyboardInterrupt:
                stop_event.set()
                item = {
                    "input": record.id,
                    "status": "failed",
                    "error": "interrupted",
                }
            except (OSError, ValueError) as exc:
                item = {"input": record.id, "status": "failed", "error": str(exc)}
            outcomes.append(item)
            emit_event(args, "input_finished", **item)
            if stop_event.is_set():
                break
    finally:
        if previous is not None:
            try:
                signal.signal(signal.SIGINT, previous)
            except (OSError, TypeError, ValueError):
                pass
    failures = sum(row["status"] == "failed" for row in outcomes)
    successes = sum(row["status"] == "success" for row in outcomes)
    exit_code = (
        130 if stop_event.is_set() else 3 if failures and successes else 1 if failures else 0
    )
    emit_document(
        args,
        {
            "ok": exit_code == 0,
            "status": "partial" if exit_code == 3 else "failed" if exit_code else "success",
            "command": "models.download",
            "inputs": outcomes,
            "stopped": stop_event.is_set(),
        },
    )
    return exit_code
