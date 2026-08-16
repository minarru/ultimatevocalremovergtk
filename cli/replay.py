"""Replay a versioned job manifest."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

from .reporting import add_reporting_args, emit_document, fail
from .profiles import IDENTITY_SETTING_PATHS

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("manifest", help="Manifest JSON produced by --manifest")
    parser.add_argument("-o", "--output", help="Override the recorded output directory")
    parser.add_argument(
        "--on-exists", choices=("fail", "overwrite", "rename", "skip"),
        help="Override the recorded collision policy",
    )
    parser.add_argument("--allow-model-change", action="store_true")
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
        if not isinstance(manifest, dict) or manifest.get("schema_version") not in {1, 2}:
            raise ValueError("unsupported manifest schema")
        spec = manifest.get("job_spec") or {}
        command = manifest.get("command")
        if command not in {"separate", "ensemble", "audio"}:
            raise ValueError(f"manifest command {command!r} cannot be replayed")
        inputs = spec.get("inputs") or []
        pairs = spec.get("pairs") or []
        if not inputs and not pairs:
            raise ValueError("manifest contains no inputs")
        output = os.path.abspath(args.output or spec.get("output") or "")
        if not output:
            raise ValueError("manifest contains no output path")
        profile_payload = {
            "schema_version": 1,
            "name": f"manifest-{manifest.get('job_id') or 'replay'}",
            "model": spec.get("model"),
            "ensemble": spec.get("ensemble"),
            "members": [] if spec.get("ensemble") else (spec.get("members") or []),
            "settings": _flat_settings(
                manifest.get("settings") or (manifest.get("plan") or {}).get("settings") or {},
                include_audio_tools=command == "audio",
            ),
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
        if command == "separate" and spec.get("model"):
            child.extend(["--model", spec["model"]])
        elif command == "ensemble":
            if spec.get("ensemble"):
                child.extend(["--ensemble", spec["ensemble"]])
            else:
                for member in spec.get("members") or []:
                    child.extend(["--model", member])
        child.extend(["--on-exists", args.on_exists or spec.get("collision_policy") or "fail", "--report", "json", "--quiet"])
        check_code, checked, _check_stderr = _run([*child, "--dry-run"])
        if check_code:
            return fail(args, "manifest replay validation failed", exit_code=2, extra={"validation": checked})
        expected = _hashes(manifest.get("plan") or {})
        actual = _hashes(checked.get("plan") or {})
        if expected != actual and not args.allow_model_change:
            return fail(
                args,
                "model hashes changed since the manifest was written; pass --allow-model-change",
                exit_code=2,
                extra={"expected": expected, "actual": actual},
            )
        code, result, stderr = _run(child)
        if not result:
            return fail(args, stderr.strip() or "manifest replay produced no result", exit_code=code or 1)
        emit_document(args, {
            "ok": code == 0,
            "status": "success" if code == 0 else "failed",
            "command": "run",
            "replayed_manifest": os.path.abspath(args.manifest),
            "result": result,
        })
        return code
    finally:
        try:
            os.remove(profile_path)
        except OSError:
            pass
