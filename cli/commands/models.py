"""Models command operations."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Mapping

from core.model_identity import (
    FAMILIES,
    iter_model_records,
)
from core.paths import (
    DEMUCS_MODELS_DIR,
)
from core.settings import Settings

from ..model_identity import CliModelLookup
from ..reporting import add_reporting_args, fail
from .formatting import _print_detail, _print_rows
from .model_catalogue import cmd_models_catalog, cmd_models_download
from .model_metadata import _model_info, _stem_semantics_fields
from .model_registration import cmd_models_configure, cmd_models_register


def _catalogue_projection_fields(record: Any, repo: Any) -> dict[str, Any]:
    """Read one all-known row's published evidence without resolving its config."""
    from core.model_catalogue import catalogue_evidence_fields

    entry = getattr(record, "catalogue_entry", None)
    family = getattr(entry, "family", None)
    selection = getattr(entry, "selection", None)
    snapshot = getattr(getattr(repo, "catalogue", None), "latest_snapshot", None)
    by_family = getattr(snapshot, "meta_by_family", None)
    meta = None
    if isinstance(by_family, Mapping) and isinstance(family, str) and isinstance(selection, str):
        values = by_family.get(family)
        if isinstance(values, Mapping):
            meta = values.get(selection)

    fields: dict[str, Any] = catalogue_evidence_fields(meta)
    projection = getattr(meta, "stem_semantics", None)
    if projection is not None:
        fields.update(projection.as_dict())
        fields["canonical_roles"] = list(projection.canonical_roles)
        if projection.evidence:
            fields["stem_semantics_evidence"] = projection.evidence
    return fields


def _list_model_info(record: Any) -> dict[str, Any]:
    """Build a non-invasive list row from the published identity record.

    ``models list`` is discovery, not inspection: dry model resolution can
    fetch or parse an MDX-C config.  A model's detailed runtime configuration
    remains available through ``models show``; list reports only its published
    identity and the raw semantic fallback until a catalogue projection exists.
    """
    return {
        **record.to_dict(),
        "configured": bool(record.installed and record.identity_complete),
        **_stem_semantics_fields(None),
    }


def _emit_catalogue_evidence_warning(record: Any, fields: Mapping[str, Any]) -> None:
    """Keep per-row evidence diagnostics out of the result document."""
    warning = fields.get("catalogue_evidence_warning")
    if not isinstance(warning, str) or not warning:
        return
    from core.debug_log import log_event

    model_id = str(getattr(record, "id", "unknown"))
    log_event(
        "cli",
        "catalogue_evidence_warning",
        level="warning",
        model_id=model_id,
        warning=warning,
    )
    print(f"warning: catalogue evidence {model_id}: {warning}", file=sys.stderr)


def add_models_parser(sub: argparse._SubParsersAction) -> None:
    root = sub.add_parser("models", help="Inspect and register models")
    children = root.add_subparsers(dest="models_command", required=True)
    listing = children.add_parser("list", help="List installed models")
    listing.add_argument("--family", choices=FAMILIES)
    listing.add_argument(
        "--all-known",
        action="store_true",
        help="Include catalogue-only records that are not installed",
    )
    add_reporting_args(listing)
    listing.set_defaults(func=cmd_models_list)
    show = children.add_parser("show", help="Show model metadata")
    show.add_argument("model")
    add_reporting_args(show)
    show.set_defaults(func=cmd_models_show)
    validate = children.add_parser("validate", help="Verify model checkpoints and configuration")
    validate.add_argument("model", nargs="?")
    validate.add_argument(
        "--offline",
        action="store_true",
        help="Do not fetch missing MDX-C YAML configs during validation",
    )
    add_reporting_args(validate)
    validate.set_defaults(func=cmd_models_validate, validating=True)
    register = children.add_parser("register", help="Register an unknown checkpoint")
    register.add_argument("checkpoint")
    register.add_argument("--family", choices=FAMILIES, required=True)
    register.add_argument("--config")
    add_reporting_args(register)
    register.set_defaults(func=cmd_models_register)
    catalog = children.add_parser("catalog", help="Search the downloadable model catalogue")
    catalog.add_argument("--family", choices=FAMILIES)
    catalog.add_argument("--query", default="")
    catalog.add_argument("--purpose", default="all")
    catalog.add_argument("--supported", action=argparse.BooleanOptionalAction, default=None)
    catalog.add_argument("--installed", action=argparse.BooleanOptionalAction, default=None)
    catalog.add_argument("--offline", action="store_true")
    add_reporting_args(catalog)
    catalog.set_defaults(func=cmd_models_catalog)
    download = children.add_parser("download", help="Download explicit catalogue entries")
    download.add_argument("entries", nargs="+")
    download.add_argument("--offline", action="store_true")
    add_reporting_args(download)
    download.set_defaults(func=cmd_models_download)
    configure = children.add_parser("configure", help="Write or reset local model metadata")
    configure.add_argument("model")
    configure.add_argument("--config")
    configure.add_argument("--replace", action="store_true")
    configure.add_argument("--reset", action="store_true")
    configure.add_argument("--primary-stem")
    configure.add_argument("--vr-params")
    configure.add_argument("--nout", type=int)
    configure.add_argument("--nout-lstm", type=int)
    configure.add_argument("--dim-f", type=int)
    configure.add_argument("--dim-t", type=int)
    configure.add_argument("--n-fft", type=int)
    configure.add_argument("--compensation", type=float)
    configure.add_argument("--config-yaml")
    configure.add_argument("--roformer", action=argparse.BooleanOptionalAction, default=None)
    configure.add_argument("--karaoke", action=argparse.BooleanOptionalAction, default=None)
    configure.add_argument("--backing-vocal", action=argparse.BooleanOptionalAction, default=None)
    configure.add_argument("--bv-rebalance", type=float)
    add_reporting_args(configure)
    configure.set_defaults(func=cmd_models_configure)


def cmd_models_list(args: argparse.Namespace) -> int:
    from core.access_policy import access_policy
    from core.model_repository import ModelRepository

    coordinator = None
    try:
        with access_policy(allow_network=False, allow_metadata_writes=False):
            persisted_settings = Settings.load()
            if getattr(args, "all_known", False):
                from core.catalogue_coordinator import CatalogueCoordinator

                coordinator = CatalogueCoordinator()
                coordinator.ensure(allow_network=False)
            repo = ModelRepository(catalogue=coordinator)
            repo.bind_model_hash_table(lambda: persisted_settings.process.model_hash_table)
            records = iter_model_records(repo)
            if coordinator is None:
                records = (record for record in records if record.installed)
            rows = []
            for record in records:
                if args.family is not None and record.family != args.family:
                    continue
                item = _list_model_info(record)
                if getattr(args, "all_known", False):
                    catalogue_fields = _catalogue_projection_fields(record, repo)
                    if "stem_semantics_status" in catalogue_fields:
                        item.update(
                            {
                                key: value
                                for key, value in catalogue_fields.items()
                                if key != "catalogue_evidence_warning"
                            }
                        )
                    item.update(
                        {
                            key: value
                            for key, value in catalogue_fields.items()
                            if key.startswith("catalogue_evidence_")
                        }
                    )
                    _emit_catalogue_evidence_warning(record, catalogue_fields)
                rows.append(item)
            return _print_rows(args, rows)
    finally:
        if coordinator is not None:
            coordinator.close()


def cmd_models_show(args: argparse.Namespace) -> int:
    from core.access_policy import access_policy
    from core.model_repository import ModelRepository

    allow_network = not getattr(args, "offline", False)
    try:
        repo = ModelRepository()
        record = CliModelLookup(repo).lookup(args.model)
        with access_policy(
            allow_network=allow_network,
            allow_metadata_writes=allow_network,
        ):
            info = _model_info(record, repo, detailed=True)
        if not info.get("configured"):
            raise ValueError(f"model configuration is unavailable for {record.id}")
        path = str(info.get("path") or "")
        if not os.path.isfile(path):
            raise ValueError(f"checkpoint is missing for {record.id}")
        if record.family == "apollo":
            from core.apollo import checkpoint_md5

            info["verified_hash"] = checkpoint_md5(path)
        else:
            from core.mdx_c_registry import compute_checkpoint_hash

            info["verified_hash"] = compute_checkpoint_hash(path)
        if info.get("hash") and info["verified_hash"] != info["hash"]:
            raise ValueError(
                f"model hash changed for {record.id}; expected {info['hash']}, "
                f"got {info['verified_hash']}"
            )
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_detail(args, info)


def cmd_models_validate(args: argparse.Namespace) -> int:
    if args.model is not None:
        return cmd_models_show(args)
    rows = []
    try:
        with os.scandir(DEMUCS_MODELS_DIR) as entries:
            installed = sorted(
                ((entry.name, entry.is_file()) for entry in entries),
                key=lambda item: item[0].casefold(),
            )
    except FileNotFoundError:
        installed = []
    for name, is_file in installed:
        if is_file and name.casefold().endswith(".ckpt"):
            rows.append(
                {
                    "artifact": name,
                    "family": "demucs",
                    "identity_complete": False,
                    "identity_error": "unsupported Demucs-root .ckpt artifact",
                    "installed": True,
                    "supported": False,
                }
            )
    return _print_rows(args, rows)
