"""Replay a versioned job manifest."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

from core.job_plan import EMPTY_MODEL_IDENTITY_DIGEST, active_model_paths
from core.model_identity import (
    DemucsSpec,
    ModelArtifacts,
    ModelRecord,
    parse_stored_model_id,
)
from core.settings import Settings

from .profiles import IDENTITY_SETTING_PATHS, MODEL_REFERENCE_SETTING_PATHS
from .reporting import add_reporting_args, emit_document, fail

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MANIFEST_SCHEMA_VERSION = 3
_SEPARATION_FAMILIES = frozenset({"vr", "mdx", "demucs"})
_SECONDARY_FIELDS = frozenset({
    "voc_inst_secondary_model",
    "other_secondary_model",
    "bass_secondary_model",
    "drums_secondary_model",
})


def add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("manifest", help="Manifest JSON produced by --manifest")
    parser.add_argument("-o", "--output", help="Override the recorded output directory")
    parser.add_argument(
        "--on-exists", choices=("fail", "overwrite", "rename", "skip"),
        help="Override the recorded collision policy",
    )
    parser.add_argument("--allow-model-change", action="store_true")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not fetch missing MDX-C YAML configs during planning",
    )
    add_reporting_args(parser)


def _flat_settings(
    settings: dict[str, Any], *, include_audio_tools: bool = False
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for section, fields in settings.items():
        excluded = {"schema_version", "identity_schema_version", "ui"}
        if not include_audio_tools:
            excluded.add("audio_tools")
        if section in excluded or not isinstance(fields, dict):
            continue
        for name, value in fields.items():
            path = f"{section}.{name}"
            if (
                path not in IDENTITY_SETTING_PATHS
                and path not in MODEL_REFERENCE_SETTING_PATHS
                and not isinstance(value, dict)
            ):
                values[path] = value
    return values


def _hashes(plan: dict[str, Any]) -> dict[str, str]:
    audio_model = plan.get("model")
    if isinstance(audio_model, dict) and audio_model.get("id"):
        return {str(audio_model["id"]): str(audio_model.get("checkpoint_hash") or "")}
    if plan.get("models"):
        return {
            str(model.get("id")): str(model.get("checkpoint_hash") or "")
            for model in plan["models"] if model.get("id")
        }
    identity = plan.get("identity") or {}
    if identity.get("id"):
        return {str(identity["id"]): str(identity.get("hash") or "")}
    return {
        str(member.get("id")): str(member.get("hash") or "")
        for member in identity.get("members") or []
    }


def _is_identity_digest(value: str) -> bool:
    prefix = "sha256:"
    suffix = value.removeprefix(prefix)
    return (
        value.startswith(prefix)
        and len(suffix) == 64
        and all(character in "0123456789abcdef" for character in suffix)
    )


def _ensemble_member_index(path: str) -> int | None:
    prefix = "ensemble.selected_models["
    if not path.startswith(prefix) or not path.endswith("]"):
        return None
    token = path[len(prefix):-1]
    if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
        return None
    return int(token)


def _allowed_dependency_families(path: str, command: str) -> frozenset[str]:
    if command == "audio":
        if path == "audio_tools.apollo_model":
            return frozenset({"apollo"})
        raise ValueError(f"invalid audio model dependency path {path!r}")

    if command == "separate" and path in {
        "vr.model", "mdx.model", "demucs.model",
    }:
        return frozenset({path.partition(".")[0]})
    if command == "ensemble" and _ensemble_member_index(path) is not None:
        return _SEPARATION_FAMILIES
    if path == "process.vocal_splitter" or path == "demucs.pre_proc_model":
        return frozenset({"vr", "mdx"})
    section, separator, field = path.partition(".")
    if separator and section in _SEPARATION_FAMILIES and field in _SECONDARY_FIELDS:
        return _SEPARATION_FAMILIES
    raise ValueError(f"invalid {command} model dependency path {path!r}")


def _validated_identity_contract(
    manifest: dict[str, Any], command: str
) -> tuple[dict[str, str], str]:
    if "model_dependencies" not in manifest:
        raise ValueError("schema 3 manifest requires model_dependencies")
    raw_dependencies = manifest["model_dependencies"]
    if not isinstance(raw_dependencies, dict):
        raise ValueError("schema 3 manifest model_dependencies must be an object")
    if "model_identity_digest" not in manifest:
        raise ValueError("schema 3 manifest requires model_identity_digest")
    digest = manifest["model_identity_digest"]
    if not isinstance(digest, str) or not _is_identity_digest(digest):
        raise ValueError(
            "schema 3 manifest model_identity_digest must be a sha256: digest"
        )
    if not raw_dependencies and digest != EMPTY_MODEL_IDENTITY_DIGEST:
        raise ValueError(
            "an empty model dependency map requires the canonical empty "
            "model identity digest"
        )

    dependencies: dict[str, str] = {}
    for raw_path, raw_model_id in sorted(raw_dependencies.items()):
        if not isinstance(raw_path, str) or not isinstance(raw_model_id, str):
            raise ValueError(
                "schema 3 manifest model_dependencies must map string paths "
                "to canonical model IDs"
            )
        allowed = _allowed_dependency_families(raw_path, command)
        try:
            parsed = parse_stored_model_id(raw_model_id)
        except ValueError as exc:
            raise ValueError(
                f"{raw_path} must contain a canonical model ID: {exc}"
            ) from exc
        if parsed.family not in allowed:
            expected = ", ".join(sorted(allowed))
            raise ValueError(
                f"{raw_path} references {raw_model_id!r}, but requires family {expected}"
            )
        dependencies[raw_path] = parsed.value
    return dependencies, digest


def _profile_identity(
    command: str, dependencies: dict[str, str]
) -> tuple[str | None, list[str], dict[str, str]]:
    model: str | None = None
    members: list[tuple[int, str]] = []
    settings: dict[str, str] = {}
    for path, model_id in dependencies.items():
        if command == "separate" and path in {
            "vr.model", "mdx.model", "demucs.model",
        }:
            if model is not None:
                raise ValueError("separate manifest has multiple primary model dependencies")
            model = model_id
        elif command == "ensemble" and (index := _ensemble_member_index(path)) is not None:
            members.append((index, model_id))
        elif command == "audio" and path == "audio_tools.apollo_model":
            model = model_id
        else:
            settings[path] = model_id
    return model, [model_id for _index, model_id in sorted(members)], settings


def _validate_command_dependency_topology(
    command: str, spec: dict[str, Any], dependencies: dict[str, str]
) -> None:
    if command == "separate":
        primaries = dependencies.keys() & {
            "vr.model", "mdx.model", "demucs.model",
        }
        if len(primaries) != 1:
            raise ValueError(
                "a separate manifest requires exactly one primary model dependency"
            )
        return

    if command == "ensemble":
        indices = sorted(
            index
            for path in dependencies
            if (index := _ensemble_member_index(path)) is not None
        )
        if len(indices) < 2:
            raise ValueError(
                "an ensemble manifest requires at least two model dependencies"
            )
        if indices != list(range(len(indices))):
            raise ValueError(
                "ensemble model dependencies must use contiguous indices starting at 0"
            )
        return

    apollo_path = "audio_tools.apollo_model"
    if spec.get("tool") == "restore":
        if set(dependencies) != {apollo_path}:
            raise ValueError(
                "Apollo restore requires exactly one Apollo model dependency"
            )
    elif dependencies:
        raise ValueError("model-free audio tools must not have model dependencies")


def _primary_dependency_records(
    command: str, dependencies: dict[str, str], plan: dict[str, Any]
) -> tuple[ModelRecord, ...]:
    descriptor_by_id = {
        str(descriptor.get("id")): descriptor
        for descriptor in plan.get("models") or []
        if isinstance(descriptor, dict) and descriptor.get("id")
    }
    primary_items: list[tuple[int, str]] = []
    for path, model_id in dependencies.items():
        if command == "separate" and path in {
            "vr.model", "mdx.model", "demucs.model",
        }:
            primary_items.append((0, model_id))
        elif command == "ensemble" and (index := _ensemble_member_index(path)) is not None:
            primary_items.append((index, model_id))

    records: list[ModelRecord] = []
    for _index, model_id in sorted(primary_items):
        parsed = parse_stored_model_id(model_id)
        descriptor = descriptor_by_id.get(model_id) or {}
        raw_demucs = descriptor.get("demucs")
        demucs = None
        if isinstance(raw_demucs, dict):
            version = raw_demucs.get("version")
            layout = raw_demucs.get("source_layout")
            if version in {"v1", "v2", "v3", "v4"} and layout in {
                "2_stem", "4_stem", "6_stem",
            }:
                demucs = DemucsSpec(version, layout)
        records.append(ModelRecord(
            id=model_id,
            family=parsed.family,
            basename=parsed.basename,
            display=model_id,
            backend_name=parsed.basename,
            artifacts=ModelArtifacts(parsed.basename),
            installed=True,
            demucs=demucs,
        ))
    return tuple(records)


def _validate_active_dependency_paths(
    manifest: dict[str, Any], command: str, dependencies: dict[str, str]
) -> None:
    if command == "audio":
        return
    raw_settings = manifest.get("settings") or (manifest.get("plan") or {}).get(
        "settings"
    )
    if not isinstance(raw_settings, dict):
        raise ValueError("schema 3 manifest settings must be an object")
    settings = Settings.from_json_dict(raw_settings)
    records = _primary_dependency_records(
        command, dependencies, manifest.get("plan") or {}
    )
    if command == "separate":
        primary = records[0]
        getattr(settings, primary.family).model = primary.id
    else:
        settings.ensemble.selected_models = [record.id for record in records]
    descriptor_by_id = {
        str(descriptor.get("id")): descriptor
        for descriptor in (manifest.get("plan") or {}).get("models") or []
        if isinstance(descriptor, dict) and descriptor.get("id")
    }
    if command == "separate":
        primary_paths = [f"{records[0].family}.model"]
    else:
        indexed_primary_paths: list[tuple[int, str]] = []
        for path in dependencies:
            index = _ensemble_member_index(path)
            if index is not None:
                indexed_primary_paths.append((index, path))
        primary_paths = [
            path for _index, path in sorted(indexed_primary_paths)
        ]
    primary_stems = {
        path: str(descriptor_by_id[record.id]["primary_stem"])
        for path, record in zip(primary_paths, records, strict=True)
        if record.id in descriptor_by_id
        and descriptor_by_id[record.id].get("primary_stem")
    }
    expected = set(active_model_paths(
        settings,
        command=command,
        primary=records,
        primary_stems=primary_stems,
    ))
    actual = set(dependencies)
    if expected == actual:
        return
    details: list[str] = []
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        details.append("missing " + ", ".join(missing))
    if extra:
        details.append("extra " + ", ".join(extra))
    raise ValueError(
        "manifest model dependencies do not match active settings: "
        + "; ".join(details)
    )


def _model_changes(
    recorded_dependencies: dict[str, str],
    current_dependencies: dict[str, str],
    recorded_digest: str,
    current_digest: str,
    recorded_hashes: dict[str, str],
    current_hashes: dict[str, str],
) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    if recorded_dependencies != current_dependencies:
        changes["model_dependencies"] = {
            "recorded": recorded_dependencies,
            "current": current_dependencies,
        }
    if recorded_hashes != current_hashes:
        changes["checkpoint_hashes"] = {
            "recorded": recorded_hashes,
            "current": current_hashes,
        }
    if recorded_digest != current_digest:
        changes["model_identity_digest"] = {
            "recorded": recorded_digest,
            "current": current_digest,
        }
    return changes


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [_REPO_ROOT, *[part for part in existing.split(os.pathsep) if part]]
    )
    return env


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    proc = subprocess.run(
        argv, env=_child_env(), capture_output=True, text=True, check=False
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {}
    return proc.returncode, payload, proc.stderr


def cmd_run(args: argparse.Namespace) -> int:
    try:
        with open(args.manifest, encoding="utf-8") as handle:
            manifest = json.load(handle)
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")
        schema = manifest.get("schema_version")
        if schema != _MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"manifest schema {schema!r} is incompatible; expected schema "
                f"{_MANIFEST_SCHEMA_VERSION}"
            )
        spec = manifest.get("job_spec") or {}
        command = manifest.get("command")
        if command not in {"separate", "ensemble", "audio"}:
            raise ValueError(f"manifest command {command!r} cannot be replayed")
        dependencies, recorded_digest = _validated_identity_contract(
            manifest, command
        )
        _validate_command_dependency_topology(command, spec, dependencies)
        _validate_active_dependency_paths(manifest, command, dependencies)
        profile_model, profile_members, dependency_settings = _profile_identity(
            command, dependencies
        )
        inputs = spec.get("inputs") or []
        pairs = spec.get("pairs") or []
        if not inputs and not pairs:
            raise ValueError("manifest contains no inputs")
        output = os.path.abspath(args.output or spec.get("output") or "")
        if not output:
            raise ValueError("manifest contains no output path")
        profile_settings = _flat_settings(
            manifest.get("settings") or (manifest.get("plan") or {}).get("settings") or {},
            include_audio_tools=command == "audio",
        )
        profile_settings.update(dependency_settings)
        profile_payload = {
            "schema_version": 1,
            "name": f"manifest-{manifest.get('job_id') or 'replay'}",
            "model": profile_model,
            "ensemble": None,
            "members": profile_members,
            "settings": profile_settings,
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)

    handle = tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False)
    profile_path = handle.name
    try:
        json.dump(profile_payload, handle)
        handle.close()
        if command == "audio":
            tool = str(spec.get("tool") or "")
            child = [sys.executable, "-m", "cli", "audio", tool]
            if pairs:
                for left, right in pairs:
                    child.extend(["--pair", left, right])
            else:
                child.extend(inputs)
            child.extend(["-o", output, "--profile", profile_path, "--accept-inherited"])
            if spec.get("name") and tool == "ensemble":
                child.extend(["--name", spec["name"]])
        else:
            child = [sys.executable, "-m", "cli", command, *inputs, "-o", output, "--profile", profile_path, "--accept-inherited"]
        if command == "separate" and profile_model:
            child.extend(["--model", profile_model])
        elif command == "ensemble":
            for member in profile_members:
                child.extend(["--model", member])
        child.extend(["--on-exists", args.on_exists or spec.get("collision_policy") or "fail", "--report", "json", "--quiet"])
        if getattr(args, "offline", False):
            child.append("--offline")
        check_code, checked, _check_stderr = _run([*child, "--dry-run"])
        if check_code:
            return fail(args, "manifest replay validation failed", exit_code=2, extra={"validation": checked})
        current_plan = checked.get("plan") or {}
        try:
            current_dependencies, current_digest = _validated_identity_contract(
                current_plan, command
            )
        except ValueError as exc:
            return fail(
                args,
                f"manifest replay validation returned an invalid identity contract: {exc}",
                exit_code=2,
                exc=exc,
                extra={"validation": checked},
            )
        recorded_hashes = _hashes(manifest.get("plan") or {})
        current_hashes = _hashes(current_plan)
        changes = _model_changes(
            dependencies,
            current_dependencies,
            recorded_digest,
            current_digest,
            recorded_hashes,
            current_hashes,
        )
        if dependencies != current_dependencies:
            return fail(
                args,
                "model dependencies changed during replay validation",
                exit_code=2,
                extra={"model_changes": changes},
            )
        if changes and not args.allow_model_change:
            digest_changed = "model_identity_digest" in changes
            hashes_changed = "checkpoint_hashes" in changes
            if digest_changed and hashes_changed:
                message = "model checkpoint hashes and identity digest changed"
            elif digest_changed:
                message = "model identity digest changed"
            else:
                message = "model checkpoint hashes changed"
            return fail(
                args,
                f"{message} since the manifest was written; pass --allow-model-change",
                exit_code=2,
                extra={"model_changes": changes},
            )
        code, result, stderr = _run(child)
        if not result:
            return fail(args, stderr.strip() or "manifest replay produced no result", exit_code=code or 1)
        response = {
            "ok": code == 0,
            "status": "success" if code == 0 else "failed",
            "command": "run",
            "replayed_manifest": os.path.abspath(args.manifest),
            "result": result,
        }
        if changes:
            response["model_changes"] = changes
        emit_document(args, response)
        return code
    finally:
        try:
            os.remove(profile_path)
        except OSError:
            pass
