"""Replay a versioned job manifest."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

from core.model_identity import parse_stored_model_id

from .reporting import add_reporting_args, emit_document, fail
from .profiles import IDENTITY_SETTING_PATHS

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
            if path not in IDENTITY_SETTING_PATHS and not isinstance(value, dict):
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
