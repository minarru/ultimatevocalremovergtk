"""Model registration command operations."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from typing import Any, Mapping

from bundled.constants import MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.paths import (
    APOLLO_MODELS_DIR,
    DEMUCS_MODELS_DIR,
    MDX_MODELS_DIR,
    VR_MODELS_DIR,
)

from ..model_identity import CliModelLookup
from ..reporting import fail
from .formatting import _print_rows
from .model_metadata import _model_info


def _registered_demucs_info(
    model_id: str, entry: Mapping[str, Any], *, models_dir: str
) -> dict[str, Any]:
    """Build registration output from the entry that was durably committed."""
    entrypoint = str(entry["entrypoint"])
    supporting = [os.path.basename(str(path)) for path in entry["supporting_artifacts"]]
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
        return fail(
            args, f"--config is required for unknown {args.family} checkpoints", exit_code=2
        )
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
            info = _registered_demucs_info(unit.model_id, entry, models_dir=registry.models_dir)
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
        "vr": VR_MODELS_DIR,
        "mdx": MDX_MODELS_DIR,
        "demucs": DEMUCS_MODELS_DIR,
        "apollo": APOLLO_MODELS_DIR,
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
        return _print_rows(
            args,
            [
                {
                    "id": existing_id,
                    "registered": False,
                    "already_registered": True,
                }
            ],
        )
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
                "vr": VR_ARCH_TYPE,
                "mdx": MDX_ARCH_TYPE,
                "apollo": APOLLO_ARCH_TYPE,
            }[args.family]
            hash_file = ModelRegistryService().configure(
                args.family,
                method,
                model_hash,
                config,
                model_path=destination,
                replace=False,
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


def cmd_models_configure(args: argparse.Namespace) -> int:
    from bundled.constants import APOLLO_ARCH_TYPE
    from core.apollo import checkpoint_md5
    from core.model_registry import ModelRegistryService
    from core.model_repository import ModelRepository

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
                "primary_stem",
                "vr_params",
                "nout",
                "nout_lstm",
                "dim_f",
                "dim_t",
                "n_fft",
                "compensation",
                "config_yaml",
                "roformer",
                "karaoke",
                "backing_vocal",
                "bv_rebalance",
            )
            if args.reset:
                if args.config or any(
                    getattr(args, name, None) is not None for name in non_demucs_metadata
                ):
                    raise ValueError("--reset cannot be combined with metadata values")
                registry = DemucsRegistry()
                removed = registry.reset(record.id)
                if removed:
                    repo.invalidate_models()
                return _print_rows(args, [{"id": record.id, "reset": removed}])
            if not args.config:
                raise ValueError("--config is required for Demucs models")
            if any(getattr(args, name, None) is not None for name in non_demucs_metadata):
                raise ValueError("Demucs metadata is supplied only through --config")
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
                    repo._model_artifact_path("demucs", record.artifacts.primary_filename)
                )
            if not os.path.isfile(model_path):
                raise ValueError(f"installed checkpoint is unavailable for {record.id}")
            unit = prepare_demucs_registration(
                model_path, loaded, models_dir=paths.DEMUCS_MODELS_DIR
            )
            if unit.model_id != record.id:
                raise ValueError(f"Demucs entrypoint derives {unit.model_id}, not {record.id}")
            actual_dir = os.path.realpath(os.path.dirname(model_path))
            expected_dir = os.path.realpath(os.path.dirname(unit.destination_paths[0]))
            if actual_dir != expected_dir:
                raise ValueError(
                    "configure does not move Demucs artifacts between legacy and v3/v4 directories"
                )
            registry.configure(unit, replace=args.replace)
            repo.invalidate_models()
            return _print_rows(
                args,
                [
                    {
                        "id": record.id,
                        "configured": True,
                        "path": registry.path,
                    }
                ],
            )
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
            "primary_stem": "primary_stem",
            "vr_params": "vr_model_param",
            "nout": "nout",
            "nout_lstm": "nout_lstm",
            "dim_f": "mdx_dim_f_set",
            "dim_t": "mdx_dim_t_set",
            "n_fft": "mdx_n_fft_scale_set",
            "compensation": "compensate",
            "config_yaml": "config_yaml",
            "roformer": "is_roformer",
            "karaoke": "is_karaoke",
            "backing_vocal": "is_bv_model",
            "bv_rebalance": "is_bv_model_rebalance",
        }
        for source, target in mappings.items():
            value = getattr(args, source, None)
            if value is not None:
                payload[target] = value
        path = registry.configure(
            record.family,
            method,
            model_hash,
            payload,
            model_path=model_path,
            replace=args.replace,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{"id": record.id, "configured": True, "path": path}])
