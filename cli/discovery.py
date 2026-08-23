"""Model, ensemble, device, settings, profile, and completion commands."""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import os
import shlex
import shutil
import sys
from enum import Enum
from typing import Any, Mapping
from bundled.constants import MDX_ARCH_TYPE, VR_ARCH_TYPE

from core.paths import (
    DEMUCS_MODELS_DIR,
    MDX_MODELS_DIR,
    APOLLO_MODELS_DIR,
    VR_MODELS_DIR,
)
from core.settings import Settings
from core.settings.access import parse_setting_assignment, validate_setting_path

from core.model_identity import (
    FAMILIES,
    iter_model_records,
)
from .model_identity import CliModelLookup
from .profiles import (
    IDENTITY_SETTING_PATHS,
    LoadedProfile,
    MODEL_REFERENCE_SETTING_PATHS,
    list_profiles,
    load_profile,
    profile_path,
    save_profile,
)
from .reporting import add_reporting_args, emit_document, emit_event, fail, report_mode


def _print_rows(args: argparse.Namespace, rows: list[dict[str, Any]]) -> int:
    if report_mode(args) == "human":
        for row in rows:
            print("\t".join(_human_cell(value, key=key) for key, value in row.items()))
    else:
        emit_document(args, {"ok": True, "status": "success", "items": rows})
    return 0


def _print_detail(args: argparse.Namespace, row: dict[str, Any]) -> int:
    """Render one inspection object with stable field labels in human mode."""
    if report_mode(args) != "human":
        return _print_rows(args, [row])
    for label, value in row.items():
        print(f"{label}\t{_human_cell(value)}")
    return 0


def _human_cell(value: Any, *, key: str | None = None) -> str:
    value = _jsonable(value)
    if key in {"primary_stem", "secondary_stem"} and isinstance(value, str) and value:
        from core.stems import canonical_stem_alias

        return canonical_stem_alias(value) or value
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if value is None:
        return ""
    return str(value)


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


def _model_info(record: Any, repo: Any, *, detailed: bool = False) -> dict[str, Any]:
    if record.family == "apollo":
        from core.apollo import ApolloModelData
        from core.paths import APOLLO_MODELS_DIR
        from core.model_registry import ModelRegistryService

        backend_name = record.backend_name
        path = os.path.join(APOLLO_MODELS_DIR, backend_name)
        data = ApolloModelData(
            backend_name, model_hash_table=repo.model_hash_table,
            on_unrecognized=None, is_dry_check=True,
        )
        local = (
            ModelRegistryService(repo).read_local(record.method, data.model_hash)
            if data.model_hash else None
        )
        info = {
            **record.to_dict(), "installed": os.path.isfile(path),
            "configured": bool(data.is_model_status), "path": path,
            "hash": data.model_hash or None, "primary_stem": "Restored",
            "secondary_stem": None,
            "metadata_source": "model-local" if local else "model-catalog",
        }
        if detailed:
            info.update({
                "metadata_sources": [{"provenance": info["metadata_source"]}],
                "architectural_facts": {"config_yaml": getattr(data, "config_yaml", None)},
                "model_native_recommendations": {},
                "local_overrides": local,
            })
        return info
    settings = Settings.defaults()
    section = getattr(settings, record.family)
    section.model = record.id
    settings.process.method = record.method
    try:
        model = repo.resolve_model_dry(settings, record.method, record.id)
    except (AttributeError, KeyError, OSError, ValueError):
        model = None
    info: dict[str, Any] = {
        **record.to_dict(),
        "installed": bool(record.installed),
        "configured": bool(model and model.model_status),
    }
    if model is not None:
        path = str(getattr(model, "model_path", "") or "")
        local_path = str(getattr(model, "model_hash_dir", "") or "")
        info.update({
            "path": path,
            "hash": getattr(model, "model_hash", None),
            "primary_stem": getattr(model, "primary_stem", None),
            "secondary_stem": getattr(model, "secondary_stem", None),
            "metadata_source": (
                "model-local" if local_path and os.path.isfile(local_path)
                else "model-catalog"
            ),
        })
        if detailed:
            facts: dict[str, Any] = {}
            for name in (
                "model_samplerate", "primary_stem_native", "mdx_dim_f_set",
                "mdx_dim_t_set", "mdx_n_fft_scale_set", "mdx_model_stems",
                "demucs_version", "demucs_source_list", "demucs_stem_count",
                "is_mdx_c", "is_roformer", "is_target_instrument",
            ):
                value = getattr(model, name, None)
                if value not in (None, "", [], ()):
                    facts[name] = list(value) if isinstance(value, tuple) else value
            recommendations = {
                name: getattr(model, name)
                for name in ("compensate", "segment", "overlap_mdx", "overlap")
                if getattr(model, name, None) is not None
            }
            local_overrides = None
            if local_path and os.path.isfile(local_path):
                try:
                    with open(local_path, encoding="utf-8") as handle:
                        local_overrides = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    local_overrides = {"unreadable": local_path}
            info.update({
                "metadata_sources": [
                    {"provenance": "model-catalog"},
                    *(
                        [{"provenance": "model-local", "path": local_path}]
                        if local_path and os.path.isfile(local_path) else []
                    ),
                ],
                "architectural_facts": facts,
                "model_native_recommendations": recommendations,
                "local_overrides": local_overrides,
            })
    return info


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
                coordinator.ensure(vip=True, allow_network=False)
            repo = ModelRepository(catalogue=coordinator)
            repo.bind_model_hash_table(
                lambda: persisted_settings.process.model_hash_table
            )
            records = iter_model_records(repo)
            if coordinator is None:
                records = (record for record in records if record.installed)
            rows = []
            for record in records:
                if args.family is not None and record.family != args.family:
                    continue
                if not record.installed:
                    rows.append({**record.to_dict(), "configured": False})
                    continue
                rows.append(_model_info(record, repo))
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
                (
                    (entry.name, entry.is_file())
                    for entry in entries
                ),
                key=lambda item: item[0].casefold(),
            )
    except FileNotFoundError:
        installed = []
    for name, is_file in installed:
        if is_file and name.casefold().endswith(".ckpt"):
            rows.append({
                "artifact": name,
                "family": "demucs",
                "identity_complete": False,
                "identity_error": "unsupported Demucs-root .ckpt artifact",
                "installed": True,
                "supported": False,
            })
    return _print_rows(args, rows)


def _registered_demucs_info(
    model_id: str, entry: Mapping[str, Any], *, models_dir: str
) -> dict[str, Any]:
    """Build registration output from the entry that was durably committed."""
    entrypoint = str(entry["entrypoint"])
    supporting = [
        os.path.basename(str(path)) for path in entry["supporting_artifacts"]
    ]
    return {
        "id": model_id,
        "family": "demucs",
        "basename": model_id.partition(":")[2],
        "display": str(entry["display_name"]),
        "backend_name": str(entry["backend_name"]),
        "primary_artifact": os.path.basename(entrypoint),
        "supporting_artifacts": supporting,
        "installed": True,
        "identity_complete": True,
        "demucs_version": str(entry["demucs_version"]),
        "source_layout": str(entry["source_layout"]),
        "configured": True,
        "registered": True,
        "path": os.path.join(models_dir, entrypoint.replace("/", os.sep)),
        "hash": None,
        "metadata_source": "model-registry",
    }


def cmd_models_register(args: argparse.Namespace) -> int:
    from core.apollo import checkpoint_md5
    from core.mdx_c_registry import compute_checkpoint_hash

    source = os.path.abspath(args.checkpoint)
    if not os.path.isfile(source):
        return fail(args, f"checkpoint not found: {args.checkpoint}", exit_code=2)
    if args.family in {"vr", "mdx", "demucs", "apollo"} and not args.config:
        return fail(args, f"--config is required for unknown {args.family} checkpoints", exit_code=2)
    config: dict[str, Any] | None = None
    if args.config:
        try:
            with open(args.config, encoding="utf-8") as handle:
                config = json.load(handle)
            if not isinstance(config, dict):
                raise ValueError("model config root must be an object")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return fail(args, f"invalid model config: {exc}", exit_code=2, exc=exc)
    if args.family == "demucs" and config is not None:
        from core.demucs_registry import DemucsRegistry, prepare_demucs_registration
        from core.model_repository import ModelRepository

        try:
            unit = prepare_demucs_registration(source, config)
            registry = DemucsRegistry()
            repo = ModelRepository()
            document = registry.install(unit)
        except (OSError, TypeError, ValueError) as exc:
            return fail(args, str(exc), exit_code=2, exc=exc)
        try:
            repo.invalidate_models()
        except Exception:
            # Registration is already durable; cache refresh cannot turn the
            # completed transaction into a reported failure.
            pass
        models = document["models"]
        assert isinstance(models, Mapping)
        entry = models[unit.model_id]
        assert isinstance(entry, Mapping)
        try:
            info = _registered_demucs_info(
                unit.model_id, entry, models_dir=registry.models_dir
            )
        except Exception:
            # The registry install above is already durable. A presentation
            # projection must not turn that completed transaction into a
            # reported registration failure.
            info = {
                "id": unit.model_id,
                "family": "demucs",
                "installed": True,
                "registered": True,
            }
        return _print_rows(args, [info])
    destinations = {
        "vr": VR_MODELS_DIR, "mdx": MDX_MODELS_DIR,
        "demucs": DEMUCS_MODELS_DIR, "apollo": APOLLO_MODELS_DIR,
    }
    destination = os.path.join(destinations[args.family], os.path.basename(source))
    if args.family == "apollo":
        model_hash = checkpoint_md5(source)
    else:
        model_hash = compute_checkpoint_hash(source)
    if not model_hash:
        return fail(args, f"could not fingerprint checkpoint: {source}", exit_code=2)
    from core.model_registry import ModelRegistryService

    existing_id = ModelRegistryService.registered_id(model_hash)
    if existing_id:
        return _print_rows(args, [{
            "id": existing_id, "registered": False,
            "already_registered": True,
        }])
    from core.model_repository import ModelRepository
    if os.path.exists(destination):
        return fail(args, f"model destination already exists: {destination}", exit_code=2)
    hash_file = None
    hash_created = False
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(source, destination)
        if config is not None and args.family in {"vr", "mdx", "apollo"}:
            from bundled.constants import APOLLO_ARCH_TYPE
            from core.model_registry import ModelRegistryService

            method = {
                "vr": VR_ARCH_TYPE, "mdx": MDX_ARCH_TYPE,
                "apollo": APOLLO_ARCH_TYPE,
            }[args.family]
            hash_file = ModelRegistryService().configure(
                args.family, method, model_hash, config,
                model_path=destination, replace=False,
            )
            hash_created = True
        repo = ModelRepository()
        record = CliModelLookup(repo).lookup(
            f"{args.family}:{os.path.splitext(os.path.basename(source))[0]}"
        )
        info = _model_info(record, repo)
        if not info.get("configured"):
            raise ValueError("registered checkpoint could not be configured")
        ModelRegistryService.remember_registered(model_hash, record.id)
    except Exception as exc:  # rollback only artifacts created by this command
        try:
            if os.path.isfile(destination):
                os.remove(destination)
            if hash_created and hash_file and os.path.isfile(hash_file):
                os.remove(hash_file)
        except OSError:
            pass
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{**info, "registered": True}])


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
        rows = [
            dataclasses.asdict(row)
            for row in service.filter(
                family=args.family, query=args.query, purpose=args.purpose,
                supported=args.supported, installed=args.installed,
            )
        ]
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
                    "input": record.id, "status": "failed",
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
    exit_code = 130 if stop_event.is_set() else 3 if failures and successes else 1 if failures else 0
    emit_document(args, {
        "ok": exit_code == 0, "status": "partial" if exit_code == 3 else "failed" if exit_code else "success",
        "command": "models.download", "inputs": outcomes,
        "stopped": stop_event.is_set(),
    })
    return exit_code


def cmd_models_configure(args: argparse.Namespace) -> int:
    from bundled.constants import APOLLO_ARCH_TYPE
    from core.apollo import checkpoint_md5
    from core.model_identity import ModelIdentityService
    from core.model_repository import ModelRepository
    from core.model_registry import ModelRegistryService

    repo = ModelRepository()
    try:
        record = CliModelLookup(repo).lookup(args.model)
        if record.family == "demucs":
            from core import paths
            from core.demucs_registry import (
                DemucsRegistry,
                prepare_demucs_registration,
            )

            non_demucs_metadata = (
                "primary_stem", "vr_params", "nout", "nout_lstm",
                "dim_f", "dim_t", "n_fft", "compensation",
                "config_yaml", "roformer", "karaoke", "backing_vocal",
                "bv_rebalance",
            )
            if args.reset:
                if args.config or any(
                    getattr(args, name, None) is not None
                    for name in non_demucs_metadata
                ):
                    raise ValueError("--reset cannot be combined with metadata values")
                registry = DemucsRegistry()
                removed = registry.reset(record.id)
                if removed:
                    repo.invalidate_models()
                return _print_rows(args, [{"id": record.id, "reset": removed}])
            if not args.config:
                raise ValueError("--config is required for Demucs models")
            if any(
                getattr(args, name, None) is not None
                for name in non_demucs_metadata
            ):
                raise ValueError(
                    "Demucs metadata is supplied only through --config"
                )
            with open(args.config, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise ValueError("model config root must be an object")
            registry = DemucsRegistry()
            registered = registry.load()["models"].get(record.id)
            if isinstance(registered, dict):
                model_path = os.path.join(
                    registry.models_dir,
                    str(registered["entrypoint"]).replace("/", os.sep),
                )
            else:
                model_path = str(
                    repo._model_artifact_path(
                        "demucs", record.artifacts.primary_filename
                    )
                )
            if not os.path.isfile(model_path):
                raise ValueError(f"installed checkpoint is unavailable for {record.id}")
            unit = prepare_demucs_registration(
                model_path, loaded, models_dir=paths.DEMUCS_MODELS_DIR
            )
            if unit.model_id != record.id:
                raise ValueError(
                    f"Demucs entrypoint derives {unit.model_id}, not {record.id}"
                )
            actual_dir = os.path.realpath(os.path.dirname(model_path))
            expected_dir = os.path.realpath(os.path.dirname(unit.destination_paths[0]))
            if actual_dir != expected_dir:
                raise ValueError(
                    "configure does not move Demucs artifacts between legacy and v3/v4 directories"
                )
            registry.configure(unit, replace=args.replace)
            repo.invalidate_models()
            return _print_rows(args, [{
                "id": record.id,
                "configured": True,
                "path": registry.path,
            }])
        if record.family == "apollo":
            from core import paths

            model_path = os.path.join(paths.APOLLO_MODELS_DIR, record.backend_name)
            model_hash = checkpoint_md5(model_path)
            method = APOLLO_ARCH_TYPE
        else:
            info = _model_info(record, repo, detailed=True)
            model_path = str(info.get("path") or "")
            model_hash = str(info.get("hash") or "")
            method = record.arch
        if not model_hash or not os.path.isfile(model_path):
            raise ValueError(f"installed checkpoint is unavailable for {record.id}")
        registry = ModelRegistryService(repo)
        if args.reset:
            if args.config or any(
                getattr(args, name, None) is not None
                for name in ("primary_stem", "vr_params", "nout", "dim_f", "config_yaml")
            ):
                raise ValueError("--reset cannot be combined with metadata values")
            removed = registry.reset_local(method, model_hash)
            return _print_rows(args, [{"id": record.id, "reset": removed}])
        payload: dict[str, Any] = {}
        if args.config:
            with open(args.config, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise ValueError("model config root must be an object")
            payload.update(loaded)
        mappings = {
            "primary_stem": "primary_stem", "vr_params": "vr_model_param",
            "nout": "nout", "nout_lstm": "nout_lstm",
            "dim_f": "mdx_dim_f_set", "dim_t": "mdx_dim_t_set",
            "n_fft": "mdx_n_fft_scale_set", "compensation": "compensate",
            "config_yaml": "config_yaml", "roformer": "is_roformer",
            "karaoke": "is_karaoke", "backing_vocal": "is_bv_model",
            "bv_rebalance": "is_bv_model_rebalance",
        }
        for source, target in mappings.items():
            value = getattr(args, source, None)
            if value is not None:
                payload[target] = value
        path = registry.configure(
            record.family, method, model_hash, payload,
            model_path=model_path, replace=args.replace,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{"id": record.id, "configured": True, "path": path}])


def add_devices_parser(sub: argparse._SubParsersAction) -> None:
    root = sub.add_parser("devices", help="Inspect inference devices")
    children = root.add_subparsers(dest="devices_command", required=True)
    listing = children.add_parser("list")
    add_reporting_args(listing)
    listing.set_defaults(func=cmd_devices_list)


def cmd_devices_list(args: argparse.Namespace) -> int:
    import dataclasses
    from core.device import list_devices

    return _print_rows(args, [dataclasses.asdict(item) for item in list_devices()])


def add_ensembles_parser(sub: argparse._SubParsersAction) -> None:
    root = sub.add_parser("ensembles", help="Inspect ensemble presets")
    children = root.add_subparsers(dest="ensembles_command", required=True)
    listing = children.add_parser("list")
    add_reporting_args(listing)
    listing.set_defaults(func=cmd_ensembles_list)
    show = children.add_parser("show")
    show.add_argument("name")
    add_reporting_args(show)
    show.set_defaults(func=cmd_ensembles_show)
    create = children.add_parser("create", help="Create a saved ensemble")
    create.add_argument("name")
    create.add_argument("--member", action="append", required=True)
    create.add_argument("--main-stem", required=True)
    create.add_argument("--algorithm", required=True)
    create.add_argument("--wav-ensemble", action=argparse.BooleanOptionalAction, default=False)
    create.add_argument("--save-all-outputs", action=argparse.BooleanOptionalAction, default=True)
    create.add_argument("--replace", action="store_true")
    add_reporting_args(create)
    create.set_defaults(func=cmd_ensembles_create)
    delete = children.add_parser("delete", help="Delete a saved user ensemble")
    delete.add_argument("name")
    add_reporting_args(delete)
    delete.set_defaults(func=cmd_ensembles_delete)


def _ensemble_rows() -> list[dict[str, Any]]:
    from core.ensemble_presets import curated_combo_label, list_curated_ensembles, load_curated_ensemble
    from core.ensemble_service import list_saved_ensembles, load_ensemble

    rows = []
    for preset in list_curated_ensembles():
        rows.append({"id": preset, "display": curated_combo_label(preset), "kind": "curated", "data": load_curated_ensemble(preset)})
    for name in list_saved_ensembles():
        rows.append({"id": name, "display": name, "kind": "saved", "data": load_ensemble(name)})
    return rows


def cmd_ensembles_list(args: argparse.Namespace) -> int:
    rows = [{key: value for key, value in row.items() if key != "data"} for row in _ensemble_rows()]
    return _print_rows(args, rows)


def cmd_ensembles_show(args: argparse.Namespace) -> int:
    needle = args.name.lower()
    matches = [row for row in _ensemble_rows() if row["id"].lower() == needle or row["display"].lower() == needle]
    if len(matches) != 1:
        return fail(args, f"unknown or ambiguous ensemble {args.name!r}", exit_code=2)
    row = matches[0]
    data = dict(row.get("data") or {})
    try:
        from core.model_repository import ModelRepository
        repo = ModelRepository()
        lookup = CliModelLookup(repo)
        members = [lookup.lookup(tag).id for tag in data.get("selected_models") or []]
    except (OSError, ValueError):
        members = list(data.get("selected_models") or [])
    detail = {
        "id": row["id"],
        "display": row["display"],
        "kind": row["kind"],
        "description": data.get("description"),
        "members": members,
        "stem_pair": data.get("ensemble_main_stem"),
        "algorithm": data.get("ensemble_type"),
        "wav_ensemble": bool(data.get("is_wav_ensemble", False)),
        "retain_member_outputs": bool(data.get("save_all_outputs", False)),
    }
    return _print_detail(args, detail)


def cmd_ensembles_create(args: argparse.Namespace) -> int:
    from core.ensemble_service import EnsembleService
    from core.model_repository import ModelRepository

    try:
        preset = EnsembleService(ModelRepository()).create(
            args.name,
            members=args.member,
            main_stem=args.main_stem,
            algorithm=args.algorithm,
            wav_ensemble=args.wav_ensemble,
            save_all_outputs=args.save_all_outputs,
            replace=args.replace,
        )
    except (OSError, TypeError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{
        "created": True, "id": preset.id, "display": preset.display,
        "members": list(preset.members), "stem_pair": preset.main_stem.value,
        "algorithm": preset.algorithm,
    }])


def cmd_ensembles_delete(args: argparse.Namespace) -> int:
    from core.ensemble_service import EnsembleService

    try:
        if not EnsembleService.delete(args.name):
            raise ValueError(f"saved ensemble not found: {args.name!r}")
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{"deleted": True, "id": args.name}])


def _setting_paths() -> list[str]:
    settings = Settings.defaults()
    result = []
    for section in ("process", "vr", "mdx", "demucs", "ensemble", "audio_tools", "ui"):
        result.extend(
            f"{section}.{field.name}"
            for field in dataclasses.fields(getattr(settings, section))
        )
    return sorted(result)


def add_settings_parser(sub: argparse._SubParsersAction) -> None:
    root = sub.add_parser("settings", help="Inspect settings and sparse profiles")
    children = root.add_subparsers(dest="settings_command", required=True)
    show = children.add_parser("show")
    show.add_argument("--profile")
    add_reporting_args(show)
    show.set_defaults(func=cmd_settings_show)
    explain = children.add_parser("explain")
    explain.add_argument("path")
    explain.add_argument("--profile")
    add_reporting_args(explain)
    explain.set_defaults(func=cmd_settings_explain)
    validate = children.add_parser("validate")
    validate.add_argument("--profile")
    validate.add_argument("--set", action="append", default=[])
    add_reporting_args(validate)
    validate.set_defaults(func=cmd_settings_validate)
    profiles = children.add_parser("profile")
    profile_sub = profiles.add_subparsers(dest="profile_command", required=True)
    listing = profile_sub.add_parser("list")
    add_reporting_args(listing)
    listing.set_defaults(func=cmd_profile_list)
    pshow = profile_sub.add_parser("show")
    pshow.add_argument("name")
    add_reporting_args(pshow)
    pshow.set_defaults(func=cmd_profile_show)
    create = profile_sub.add_parser("create")
    create.add_argument("name")
    identity = create.add_mutually_exclusive_group()
    identity.add_argument("--model")
    identity.add_argument("--ensemble")
    create.add_argument("--member", action="append", default=[])
    create.add_argument("--set", action="append", default=[])
    create.add_argument("--replace", action="store_true")
    add_reporting_args(create)
    create.set_defaults(func=cmd_profile_create)
    delete = profile_sub.add_parser("delete")
    delete.add_argument("name")
    add_reporting_args(delete)
    delete.set_defaults(func=cmd_profile_delete)


def _jsonable(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def cmd_settings_show(args: argparse.Namespace) -> int:
    try:
        settings, profile = load_profile(args.profile)
        from core.settings.job_resolution import SettingsResolver

        profile_source = "gui" if profile.source == "gui" else profile.source
        settings, sources = SettingsResolver().resolve(
            settings,
            base_provenance={
                path: profile_source for path in profile.settings
            },
        )
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    payload = {
        "profile": profile.to_dict(),
        "settings": settings.to_json_dict(),
        "sources": sources,
    }
    if report_mode(args) == "human":
        print(f"profile\t{profile.name}\t{profile.source}")
        for path in _setting_paths():
            section, name = path.split(".", 1)
            value = getattr(getattr(settings, section), name)
            print(f"{path}\t{_human_cell(value)}\t{sources[path]}")
        return 0
    return _print_rows(args, [payload])


def cmd_settings_explain(args: argparse.Namespace) -> int:
    paths = _setting_paths()
    if args.path not in paths:
        matches = difflib.get_close_matches(args.path, paths, n=5)
        return fail(args, f"unknown setting {args.path!r}; close matches: {', '.join(matches) or 'none'}", exit_code=2)
    settings, profile = load_profile(args.profile)
    from core.settings.job_resolution import SettingsResolver

    settings, sources = SettingsResolver().resolve(
        settings,
        base_provenance={
            path: ("gui" if profile.source == "gui" else profile.source)
            for path in profile.settings
        },
    )
    from core.settings.descriptors import describe_setting

    descriptor = describe_setting(args.path)
    section, field_name = args.path.split(".", 1)
    current = getattr(getattr(settings, section), field_name)
    provenance = sources[args.path]
    row = {
        "path": args.path,
        "type": descriptor.type_name,
        "default": descriptor.default,
        "value": _jsonable(current),
        "supports_auto": descriptor.supports_auto,
        "allowed_values": descriptor.allowed_values,
        "model_specific_behavior": descriptor.model_behavior,
        "provenance": provenance,
    }
    return _print_rows(args, [row])


def cmd_settings_validate(args: argparse.Namespace) -> int:
    try:
        settings, profile = load_profile(args.profile)
        from core.settings.access import apply_settings_overrides
        apply_settings_overrides(settings, [parse_setting_assignment(item) for item in args.set])
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{"valid": True, "profile": profile.name}])


def cmd_profile_list(args: argparse.Namespace) -> int:
    rows = [{"name": "defaults", "source": "built-in"}, {"name": "gui", "source": "gui"}]
    rows.extend({"name": name, "source": "profile"} for name in list_profiles())
    return _print_rows(args, rows)


def cmd_profile_show(args: argparse.Namespace) -> int:
    try:
        _settings, profile = load_profile(args.name)
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [profile.to_dict()])


def cmd_profile_create(args: argparse.Namespace) -> int:
    try:
        values = dict(parse_setting_assignment(item) for item in args.set)
        settings = Settings.defaults()
        for path in values:
            if path in IDENTITY_SETTING_PATHS:
                raise ValueError(
                    f"{path} is identity/state; use --model, --ensemble, or --member"
                )
            validate_setting_path(settings, path)
        if args.model and (args.ensemble or args.member):
            raise ValueError("a profile cannot combine a primary model with ensemble identity")
        if args.ensemble and args.member:
            raise ValueError("choose an ensemble preset or --member values, not both")
        model = args.model
        members = list(args.member)
        reference_paths = MODEL_REFERENCE_SETTING_PATHS.intersection(values)
        if model or members or reference_paths:
            from core.model_repository import ModelRepository
            repo = ModelRepository()
            lookup = CliModelLookup(repo)
            model = lookup.lookup(model).id if model else None
            members = [lookup.lookup(item).id for item in members]
            for setting_path in reference_paths:
                values[setting_path] = lookup.lookup(str(values[setting_path])).id
        if args.ensemble:
            needle = args.ensemble.casefold()
            matches = [
                row for row in _ensemble_rows()
                if str(row["id"]).casefold() == needle
                or str(row["display"]).casefold() == needle
            ]
            if len(matches) != 1:
                raise ValueError(f"unknown or ambiguous ensemble {args.ensemble!r}")
            ensemble = str(matches[0]["id"])
        else:
            ensemble = None
        profile = LoadedProfile(
            name=args.name, source="profile", model=model,
            ensemble=ensemble, members=members, settings=values,
        )
        path = save_profile(profile, replace=args.replace)
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{"created": True, "name": args.name, "path": path}])


def cmd_profile_delete(args: argparse.Namespace) -> int:
    try:
        path = profile_path(args.name)
        if not os.path.isfile(path):
            raise ValueError(f"profile not found: {args.name!r}")
        os.remove(path)
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{"deleted": True, "name": args.name}])


def add_completion_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("completion", help="Generate shell completion")
    parser.add_argument("shell", choices=("bash", "zsh", "fish"))
    parser.set_defaults(func=cmd_completion, report="human", quiet=False, verbose=False)


def cmd_completion(args: argparse.Namespace) -> int:
    from .main import build_parser

    root = build_parser()
    subcommands = next(
        action for action in root._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    commands = " ".join(subcommands.choices)
    dynamic: list[str] = ["defaults", "gui", *_setting_paths(), *list_profiles()]
    try:
        from core.model_repository import ModelRepository
        dynamic.extend(record.id for record in iter_model_records(ModelRepository()))
        dynamic.extend(str(row["id"]) for row in _ensemble_rows())
        from core.gpu import list_gpu_devices
        dynamic.append("cpu")
        dynamic.extend(
            ident if ident in {"mps", "directml"} else f"cuda:{ident}"
            for ident, _label in list_gpu_devices()
        )
    except (ImportError, OSError, ValueError):
        # Completion remains usable from a minimally provisioned install.
        pass
    words = " ".join(shlex.quote(item) for item in [*commands.split(), *sorted(set(dynamic))])
    if args.shell == "bash":
        print(f"complete -W {shlex.quote(words)} uvr")
    elif args.shell == "zsh":
        print(f"#compdef uvr\n_arguments '*:uvr value:({words})'")
    else:
        for command in commands.split():
            print(f"complete -c uvr -n '__fish_use_subcommand' -a {command}")
        for item in sorted(set(dynamic)):
            print(f"complete -c uvr -a {shlex.quote(item)}")
    return 0
