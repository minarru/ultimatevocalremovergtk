#!/usr/bin/env python3
"""Local-only sweep: start a real run for every model installed on this machine.

Not part of CI — weights are gitignored, so this can only run where models
exist. The parent process discovers jobs and runs each one in its own
subprocess, serially. See docs/superpowers/specs/2026-07-31-local-model-sweep-design.md
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KIND_SINGLE = "single"
KIND_ENSEMBLE = "ensemble"
KIND_TOOL = "tool"
KIND_SKIP = "skip"

DEFAULT_TIMEOUT = 300.0
ENSEMBLE_TIMEOUT = 900.0

# Literal values verified against bundled/constants/process.py / core.stems.
MAX_MIN = "Max Spec/Min Spec"
VOCALS_INSTRUMENTAL = "vocals_instrumental"
APOLLO_RESTORE = "Apollo Restore"
ALL_STEMS = "All Stems"


@dataclass(frozen=True)
class SweepJob:
    """One unit of work: exactly one run, executed in its own subprocess."""

    id: str
    kind: str
    method: Optional[str] = None
    model: Optional[str] = None
    overrides: Dict[str, Any] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT
    #: Part of the group `--method composite` selects. Tracked explicitly: the
    #: group is not identifiable from `kind` (two composite jobs are
    #: KIND_SINGLE) nor from the timeout (composite:4-stem uses the per-model
    #: default), so inferring it silently missed jobs.
    composite: bool = False
    detail: str = ""


@dataclass(frozen=True)
class Installed:
    """What is actually present on this machine."""

    mdx: List[str]
    vr: List[str]
    demucs: List[str]
    apollo: List[str]
    ensemble_tags: List[str]
    karaoke_tags: List[str]


def collect_installed(repo: Any, settings: Any) -> Installed:
    """Read the model tree. Impure; ``discover_jobs`` stays testable without it."""
    from bundled.constants import INST_STEM, VOCAL_STEM
    from core.apollo import list_apollo_models

    return Installed(
        mdx=list(repo.list_mdx_models()),
        vr=list(repo.list_vr_models()),
        demucs=list(repo.list_demucs_models()),
        apollo=list(list_apollo_models()),
        ensemble_tags=list(repo.model_list(settings, VOCAL_STEM, INST_STEM)),
        karaoke_tags=list(repo.karaoke_model_list(settings)),
    )


def _wanted(name: str, only: str, skip: frozenset) -> bool:
    if name in skip:
        return False
    return only.lower() in name.lower() if only else True


def discover_jobs(
    installed: Installed,
    *,
    methods: set,
    only: str = "",
    skip: frozenset = frozenset(),
) -> List[SweepJob]:
    """Build the job list from what is installed. Pure: lists in, jobs out."""
    jobs: List[SweepJob] = []

    for method, names in (
        ("mdx", installed.mdx),
        ("vr", installed.vr),
        ("demucs", installed.demucs),
    ):
        if method not in methods:
            continue
        for name in names:
            if not _wanted(name, only, skip):
                continue
            jobs.append(
                SweepJob(id=f"{method}:{name}", kind=KIND_SINGLE, method=method, model=name)
            )

    if "apollo" in methods:
        for name in installed.apollo:
            if not _wanted(name, only, skip):
                continue
            jobs.append(
                SweepJob(
                    id=f"apollo:{name}",
                    kind=KIND_TOOL,
                    overrides={
                        "audio_tools.apollo_model": name,
                        "audio_tools.chosen_audio_tool": APOLLO_RESTORE,
                    },
                )
            )

    if "composite" in methods:
        jobs.extend(_composite_jobs(installed))

    return jobs


def _skip(job_id: str, reason: str, *, composite: bool = False) -> SweepJob:
    return SweepJob(id=job_id, kind=KIND_SKIP, detail=reason, composite=composite)


def _composite_jobs(installed: Installed) -> List[SweepJob]:
    """Multi-pass shapes single-model runs never reach."""
    jobs: List[SweepJob] = []

    # 1. Four-stem export.
    four_stem = next((n for n in installed.demucs if "hdemucs_mmi" in n), None)
    if four_stem is not None:
        jobs.append(
            SweepJob(
                id="composite:4-stem",
                kind=KIND_SINGLE,
                method="demucs",
                model=four_stem,
                overrides={"demucs_stems": ALL_STEMS},
                composite=True,
            )
        )
    else:
        scnet = next((n for n in installed.mdx if "4stems" in n), None)
        if scnet is not None:
            jobs.append(
                SweepJob(
                    id="composite:4-stem",
                    kind=KIND_SINGLE,
                    method="mdx",
                    model=scnet,
                    overrides={"mdx_stems": ALL_STEMS},
                    composite=True,
                )
            )
        else:
            jobs.append(_skip("composite:4-stem", "no 4-stem model installed", composite=True))

    # 2. Two-member ensemble.
    if len(installed.ensemble_tags) >= 2:
        jobs.append(
            SweepJob(
                id="composite:ensemble",
                kind=KIND_ENSEMBLE,
                overrides={
                    "selected_models": installed.ensemble_tags[:2],
                    "ensemble_type": MAX_MIN,
                    "ensemble_main_stem": VOCALS_INSTRUMENTAL,
                    "is_save_all_outputs_ensemble": False,
                },
                timeout=ENSEMBLE_TIMEOUT,
                composite=True,
            )
        )
    else:
        jobs.append(_skip("composite:ensemble", "needs two ensemble-capable models", composite=True))

    # 3. Primary + secondary chain.
    # repo.model_list returns family-prefixed tags ("mdx:Name", "vr:Name").
    # The old predicate matched a raw display name that no longer exists, so
    # this job was skipped on every install while blaming a missing model.
    mdx_tag = next((t for t in installed.ensemble_tags if t.startswith("mdx:")), None)
    if installed.vr and mdx_tag is not None:
        jobs.append(
            SweepJob(
                id="composite:secondary-chain",
                kind=KIND_SINGLE,
                method="vr",
                model=installed.vr[0],
                overrides={
                    "vr_is_secondary_model_activate": True,
                    "vr_voc_inst_secondary_model": mdx_tag,
                    "vr_voc_inst_secondary_model_scale": 0.5,
                },
                timeout=ENSEMBLE_TIMEOUT,
                composite=True,
            )
        )
    else:
        missing = "a VR model" if not installed.vr else "an MDX ensemble tag"
        jobs.append(
            _skip("composite:secondary-chain", f"needs {missing}", composite=True)
        )

    # 4. Vocal splitter chain.
    if installed.mdx and installed.karaoke_tags:
        jobs.append(
            SweepJob(
                id="composite:vocal-splitter",
                kind=KIND_SINGLE,
                method="mdx",
                model=installed.mdx[0],
                overrides={
                    "is_set_vocal_splitter": True,
                    "set_vocal_splitter": installed.karaoke_tags[0],
                    "is_save_inst_set_vocal_splitter": True,
                },
                timeout=ENSEMBLE_TIMEOUT,
                composite=True,
            )
        )
    else:
        jobs.append(_skip("composite:vocal-splitter", "needs an MDX and a karaoke model", composite=True))

    return jobs


PASS = "PASS"
NO_OUTPUT = "NO_OUTPUT"
TIMEOUT = "TIMEOUT"
OOM = "OOM"
OOM_CPU_OK = "OOM(cpu-ok)"
UNRECOGNIZED = "UNRECOGNIZED"


#: Enough for a torch load error's headline plus its first few key mismatches.
_DETAIL_MAX_LINES = 6


def _error_detail(text: Optional[str]) -> str:
    """The useful part of an exception message, bounded.

    Keeping only the first line discarded everything for the errors that most
    need explaining: torch puts "Error(s) in loading state_dict for X:" on line
    one and the actual size mismatches and missing keys on the lines after it.
    """
    lines = [line.strip() for line in (text or "").strip().splitlines()]
    kept = [line for line in lines if line][:_DETAIL_MAX_LINES]
    return "\n".join(kept)


def classify(
    *, exit_code: Optional[int], result: Optional[dict], timed_out: bool
) -> tuple:
    """Turn a child's exit code and result payload into a verdict + detail."""
    from core.oom_markers import is_oom_message

    if timed_out:
        return TIMEOUT, ""
    if result is None:
        return f"CRASH(exit {exit_code})", ""
    protocol_error = result.get("protocol_error")
    if protocol_error:
        return "FAIL(protocol)", str(protocol_error)
    if result.get("unrecognized"):
        return UNRECOGNIZED, "model hash not in the metadata tables"

    error_type = result.get("error_type")
    message = str(result.get("message") or "")
    if error_type:
        detail = _error_detail(message)
        if is_oom_message(message) or error_type == "OutOfMemoryError":
            return OOM, detail
        return f"FAIL({error_type})", detail
    if result.get("stopped"):
        return "FAIL(stopped)", "run stopped before completion"
    if not result.get("outputs"):
        return NO_OUTPUT, "run completed but wrote no audio"
    return PASS, ""


def is_failure(verdict: str, *, strict: bool) -> bool:
    """Whether a verdict should make the sweep exit non-zero."""
    if verdict in (PASS, OOM_CPU_OK) or verdict.startswith("SKIP"):
        return False
    if verdict == UNRECOGNIZED:
        return strict
    return True


def render_row(job_id: str, verdict: str, elapsed_s: float, detail: str) -> str:
    row = f"{job_id:<52.52} {verdict:<34.34} {elapsed_s:>7.1f}s"
    if not detail:
        return row
    body = "\n".join(f"    {line}" for line in detail.splitlines())
    return f"{row}\n{body}"


def apply_timeouts(
    jobs: Sequence[SweepJob],
    *,
    timeout: Optional[float] = None,
    composite_timeout: Optional[float] = None,
) -> List[SweepJob]:
    """Override job timeouts with whatever the CLI asked for.

    Routing is by group membership, not by the timeout a job currently holds:
    composite jobs do not share one default (composite:4-stem runs on the
    per-model default while the rest use ENSEMBLE_TIMEOUT), so keying on the
    value let --composite-timeout silently miss the group's slowest member.

    ``None`` means the flag was not given, leaving each job's own default.
    """
    resolved: List[SweepJob] = []
    for job in jobs:
        chosen = composite_timeout if job.composite else timeout
        wanted = job.timeout if chosen is None else chosen
        resolved.append(
            job if wanted == job.timeout
            else SweepJob(**{**job.__dict__, "timeout": wanted})
        )
    return resolved


def write_manifest(
    path: str, jobs: Sequence[SweepJob], *, run_meta: Optional[Dict[str, Any]] = None
) -> None:
    """Record the resolved job list, so a planned sweep can be reviewed or repeated."""
    from core.json_store import write_json_atomic

    write_json_atomic(
        path,
        {
            "run": run_meta or {},
            "planned": len(jobs),
            "jobs": [dict(job.__dict__) for job in jobs],
        },
    )


def _git_output(*args: str) -> str:
    """stdout of a git command run at the repo root, or "" if it fails."""
    import subprocess

    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_commit() -> str:
    """Short commit, suffixed ``-dirty`` when the tree has uncommitted changes.

    This tree normally carries long-lived local edits, so a bare HEAD would
    attribute the run to code that never actually ran.
    """
    commit = _git_output("rev-parse", "--short", "HEAD")
    if not commit:
        return ""
    return f"{commit}-dirty" if _git_output("status", "--porcelain") else commit


def run_metadata(args: Any, *, methods: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """What produced this report, so a result can be tied back to a build.

    A bare list of verdicts cannot be compared against another run without
    knowing the code, the device and the settings behind it.
    """
    import platform
    import sys as _sys

    try:
        commit = _git_commit()
    except OSError:
        commit = ""

    try:
        # Repo root is on sys.path from module import.
        from __version__ import VERSION
    except ImportError:
        VERSION = ""

    return {
        "version": VERSION,
        "commit": commit,
        "python": _sys.version.split()[0],
        "platform": platform.platform(),
        "cpu": bool(getattr(args, "cpu", False)),
        "cpu_retry": bool(getattr(args, "cpu_retry", True)),
        # The resolved set, not the raw flag: a default sweep runs every group
        # and would otherwise report [], which reads as "nothing selected".
        "methods": sorted(methods if methods is not None else (getattr(args, "method", None) or [])),
        "only": getattr(args, "only", None) or "",
        "skip": getattr(args, "skip", None) or "",
        "timeout_s": float(getattr(args, "timeout", None) or DEFAULT_TIMEOUT),
        "composite_timeout_s": float(
            getattr(args, "composite_timeout", None) or ENSEMBLE_TIMEOUT
        ),
        "strict": bool(getattr(args, "strict", False)),
        "settings": "stock" if getattr(args, "stock_settings", False) else "copied",
    }


def render_summary(verdicts: Sequence[str], *, planned: Optional[int] = None) -> str:
    passed = sum(1 for v in verdicts if v == PASS)
    skipped = sum(1 for v in verdicts if v.startswith("SKIP"))
    oom_ok = sum(1 for v in verdicts if v == OOM_CPU_OK)
    unrecognized = sum(1 for v in verdicts if v == UNRECOGNIZED)
    failed = len(verdicts) - passed - skipped - oom_ok - unrecognized
    parts = [f"{passed} passed", f"{failed} failed"]
    if oom_ok:
        parts.append(f"{oom_ok} OOM(cpu-ok)")
    if unrecognized:
        parts.append(f"{unrecognized} unrecognized")
    if skipped:
        parts.append(f"{skipped} skipped")
    if planned is not None and planned > len(verdicts):
        # --fail-fast stops early; without this the run reads as a smaller sweep.
        parts.append(f"{planned - len(verdicts)} not run")
    return "  ".join(parts)


def make_input_clip(path: str, *, seconds: float = 3.0, rate: int = 44100) -> str:
    """Write a short deterministic stereo clip.

    Not silence: an all-zero input can produce all-zero stems and trip the
    level-matching and clipping paths in ways that say nothing about the model.
    """
    import numpy as np
    import soundfile as sf

    frames = int(rate * seconds)
    t = np.arange(frames, dtype=np.float64) / rate
    rng = np.random.default_rng(0)
    left = (
        0.5 * np.sin(2 * np.pi * 220.0 * t)
        + 0.25 * np.sin(2 * np.pi * 880.0 * t)
        + 0.05 * rng.standard_normal(frames)
    )
    right = (
        0.4 * np.sin(2 * np.pi * 330.0 * t)
        + 0.2 * np.sin(2 * np.pi * 1320.0 * t)
        + 0.05 * rng.standard_normal(frames)
    )
    stereo = np.stack([left, right], axis=1)
    stereo = stereo / max(1e-9, float(np.abs(stereo).max())) * 0.7  # ~-3 dBFS
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    sf.write(path, stereo, rate, subtype="PCM_16")
    return path


def prepare_scratch(
    root: str, *, models_dir: str, settings_src: Optional[str]
) -> tuple:
    """Build an isolated UVR data dir: symlinked models, copied settings.

    Model resolution comes back empty without the ``models`` symlink, and the
    user's own ``settings.json`` must never be written to.
    """
    import json
    import shutil

    os.makedirs(root, exist_ok=True)
    link = os.path.join(root, "models")
    if not os.path.exists(link):
        os.symlink(os.path.abspath(models_dir), link)

    settings_path = os.path.join(root, "settings.json")
    if settings_src and os.path.isfile(settings_src):
        shutil.copyfile(settings_src, settings_path)
    else:
        with open(settings_path, "w") as handle:
            json.dump({}, handle)
    return root, settings_path


def child_env(data_dir: str) -> Dict[str, str]:
    """Environment for a child run: isolated data dir, no warmup, no network."""
    env = dict(os.environ)
    env["UVR_DATA_DIR"] = data_dir
    env["UVR_SKIP_SEPARATE_WARMUP"] = "1"
    env["UVR_DISABLE_POLITREES"] = "1"
    env["UVR_DISABLE_MVSEPLESS"] = "1"
    return env


AUDIO_SUFFIXES = (".wav", ".flac", ".mp3", ".aiff", ".ogg", ".opus")


def collect_outputs(export_dir: str) -> List[List[Any]]:
    """Non-empty audio files written into ``export_dir``."""
    found: List[List[Any]] = []
    for root, _dirs, files in os.walk(export_dir):
        for name in sorted(files):
            if not name.lower().endswith(AUDIO_SUFFIXES):
                continue
            path = os.path.join(root, name)
            size = os.path.getsize(path)
            if size > 0:
                found.append([path, size])
    return found


def run_child(spec_path: str) -> int:
    """Execute exactly one job and write ``result.json`` next to the spec.

    The spec read, ``export_dir`` lookup and directory creation all happen
    inside the guarded region below: a missing/unreadable spec, malformed
    JSON, or a spec missing ``export_dir`` is a clean, diagnosable failure,
    not a crash with no ``result.json`` — the parent must be able to tell
    the two apart.
    """
    import json
    import time
    import traceback

    job_dir = os.path.dirname(os.path.abspath(spec_path))
    result: Dict[str, Any] = {
        "ok": False,
        "error_type": None,
        "message": "",
        "elapsed_s": 0.0,
        "outputs": [],
        "stopped": False,
        "unrecognized": False,
    }
    started = time.perf_counter()
    export_dir = ""
    try:
        with open(spec_path) as handle:
            spec = json.load(handle)

        export_dir = spec["export_dir"]

        from core import ModelRepository, Settings
        from core.blocking_runner import run_blocking
        from core.job_plan import JobResolver, JobSpec, ValidationLevel
        from core.job_runner import JobRunner
        from core.model_identity import ModelIdentityService
        from core.settings.flat_map import FLAT_TO_PATH
        from core.settings.job_resolution import SettingsLayer, SettingsResolver

        kind = spec["kind"]
        profile = Settings.load(spec["settings_path"])
        assignments = []
        for key, value in (spec.get("overrides") or {}).items():
            if "." in key:
                path = key
            else:
                section, field_name = FLAT_TO_PATH[key]
                path = f"{section}.{field_name}"
            assignments.append((path, value))
        settings, provenance = SettingsResolver().resolve(
            profile,
            export_path=export_dir,
            method=spec.get("method"),
            stable_naming=True,
            layers=(SettingsLayer("profile", tuple(assignments)),),
        )
        if spec.get("cpu"):
            settings.process.use_gpu = False
            settings.process.device = "cpu"

        repo = ModelRepository()
        if kind == KIND_SINGLE:
            record = ModelIdentityService(repo).resolve(
                f"{spec['method']}:{spec['model']}"
            )
            from core.types import ProcessMethod

            settings.process.method = ProcessMethod(record.method)
            setattr(getattr(settings, record.family), "model", record.id)
        elif kind == KIND_ENSEMBLE:
            from core.types import ProcessMethod

            settings.process.method = ProcessMethod.ENSEMBLE

        timeout = float(spec.get("timeout") or DEFAULT_TIMEOUT)
        if kind == KIND_TOOL:
            outcome = _run_tool(settings, spec["input_path"], timeout, repo=repo)
        else:
            command = "ensemble" if kind == KIND_ENSEMBLE else "separate"
            plan = JobResolver(repo).resolve(
                JobSpec(
                    command, settings, (spec["input_path"],), export_dir, provenance
                ),
                ValidationLevel.MODEL,
            )
            errors = [item.message for item in plan.diagnostics if item.severity == "error"]
            if errors:
                result["unrecognized"] = any("configuration" in item.code for item in plan.diagnostics)
                raise ValueError(errors[0])
            os.makedirs(export_dir, exist_ok=True)
            runner = JobRunner(plan.settings)
            start_runner = lambda callbacks: runner.start(
                [item.path for item in plan.inputs],
                callbacks,
                planned=plan.inputs,
                planned_output_root=plan.output,
            )
            def write_console(text: str) -> None:
                sys.stdout.write(text)

            outcome = run_blocking(
                runner, start_runner, timeout=timeout,
                on_console=write_console,
            )

        result["stopped"] = bool(outcome.stopped)
        if outcome.error is not None:
            result["error_type"] = type(outcome.error).__name__
            result["message"] = str(outcome.error)
    except BaseException as exc:  # noqa: BLE001 - the point is to report anything
        result["error_type"] = type(exc).__name__
        result["message"] = f"{exc}\n{traceback.format_exc()}"

    result["elapsed_s"] = time.perf_counter() - started
    if export_dir:
        result["outputs"] = collect_outputs(export_dir)
    # ``ok`` must mean exactly what the exit code means: no error, not
    # stopped, and at least one output actually written.
    result["ok"] = (
        result["error_type"] is None
        and not result["stopped"]
        and bool(result["outputs"])
    )
    _write_result(job_dir, result)
    return 0 if result["ok"] else 1


def _write_result(job_dir: str, result: Dict[str, Any]) -> None:
    """Publish the child's result atomically.

    The parent reads this file as soon as the child exits, so a partial write
    from a child killed mid-flush must never be observable.
    """
    from core.json_store import write_json_atomic

    write_json_atomic(os.path.join(job_dir, "result.json"), result)


def _read_result(result_path: str) -> Optional[Dict[str, Any]]:
    """Read a child's result.json, or None when the child never wrote one.

    Malformed JSON becomes a protocol error rather than an exception: a child
    killed mid-write must fail its own job, not abort the whole sweep.
    """
    import json

    if not os.path.isfile(result_path):
        return None
    try:
        with open(result_path) as handle:
            payload = json.load(handle)
    except (ValueError, OSError) as exc:
        return {"protocol_error": f"unreadable result.json: {exc}"}
    if not isinstance(payload, dict):
        return {"protocol_error": f"result.json root is {type(payload).__name__}, not an object"}
    return payload


def _run_tool(settings: Any, input_path: str, timeout: float, *, repo: Any):
    """Run the Apollo restore tool, mirroring the UI's model resolution."""
    from core.apollo import ApolloModelData
    from core.audio_plan import AudioJobResolver, AudioJobSpec
    from core.audio_tools import AudioToolRunner
    from core.blocking_runner import run_blocking
    from core.job_plan import ValidationLevel

    plan = AudioJobResolver(repo).resolve(
        AudioJobSpec(
            APOLLO_RESTORE, settings, settings.process.export_path,
            (input_path,), provenance={"profile": "profile"},
        ),
        ValidationLevel.MODEL,
    )
    errors = [item.message for item in plan.diagnostics if item.severity == "error"]
    if errors:
        raise ValueError(errors[0])
    if plan.model is None:
        raise ValueError("resolved Apollo model is unavailable")
    os.makedirs(plan.output, exist_ok=True)
    model_data = ApolloModelData(
        plan.model.backend_name,
        model_hash_table=repo.model_hash_table,
        on_unrecognized=None,
    )
    if not model_data.is_model_status:
        raise RuntimeError(f"Apollo model not valid: {settings.audio_tools.apollo_model}")

    runner = AudioToolRunner(
        plan.settings, apollo_backend_name=plan.model.backend_name
    )
    def write_console(text: str) -> None:
        sys.stdout.write(text)

    return run_blocking(
        runner,
        lambda callbacks: runner.start(
            APOLLO_RESTORE, [input_path], [], callbacks,
            apollo_params={
                "extracted_params": model_data.extracted_params,
                "config": model_data.config,
            },
        ),
        timeout=timeout,
        on_console=write_console,
    )


def spawn_child(*, spec: Dict[str, Any], job_dir: str, env: Dict[str, str], timeout: float):
    """Run one job in a fresh process. Returns ``(exit_code, result, timed_out)``.

    The child is started as its own process-group leader (``start_new_session
    =True``) so that on a timeout we can kill its whole group, not just the
    immediate process. The child shells out to grandchildren of its own —
    pydub's ffmpeg for FLAC/MP3 export, rubberband via ``ml/pyrb.py`` — and a
    bare ``proc.kill()`` only signals the direct child, leaving those
    grandchildren to run on as orphans holding memory and file handles.
    """
    import signal
    import subprocess

    os.makedirs(job_dir, exist_ok=True)
    spec_path = os.path.join(job_dir, "spec.json")
    from core.json_store import write_json_atomic

    write_json_atomic(spec_path, spec)

    result_path = os.path.join(job_dir, "result.json")
    if os.path.exists(result_path):
        os.remove(result_path)

    argv = [sys.executable, os.path.abspath(__file__), "--run-job", spec_path]
    proc = subprocess.Popen(argv, env=env, start_new_session=True)
    try:
        exit_code = proc.wait(timeout=timeout + 30.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()  # reap the now-dead process so it doesn't linger as a zombie
        return None, None, True

    return exit_code, _read_result(result_path), False


SpawnFn = Callable[..., Tuple[Optional[int], Optional[Dict[str, Any]], bool]]


def run_one(
    job: SweepJob,
    *,
    spawn: SpawnFn,
    job_dir: str,
    settings_path: str,
    input_path: str,
    data_dir: str,
    cpu: bool,
    cpu_retry: bool,
) -> Tuple[str, str, float]:
    """Run one job, retrying once on CPU when the GPU ran out of memory."""
    import time

    if job.kind == KIND_SKIP:
        return f"SKIP({job.detail})", "", 0.0

    def attempt(on_cpu: bool) -> Tuple[str, str, float]:
        spec = {
            "kind": job.kind,
            "method": job.method,
            "model": job.model,
            "overrides": job.overrides,
            "settings_path": settings_path,
            "input_path": input_path,
            "export_dir": os.path.join(job_dir, "cpu" if on_cpu else "gpu", "out"),
            "cpu": on_cpu,
            "timeout": job.timeout,
        }
        started = time.perf_counter()
        exit_code, result, timed_out = spawn(
            spec=spec,
            job_dir=os.path.join(job_dir, "cpu" if on_cpu else "gpu"),
            env=child_env(data_dir),
            timeout=job.timeout,
        )
        verdict, detail = classify(exit_code=exit_code, result=result, timed_out=timed_out)
        return verdict, detail, time.perf_counter() - started

    verdict, detail, elapsed = attempt(cpu)
    if verdict == OOM and cpu_retry and not cpu:
        retry_verdict, retry_detail, retry_elapsed = attempt(True)
        elapsed += retry_elapsed
        if retry_verdict == PASS:
            return OOM_CPU_OK, "out of VRAM at these settings; identical run passed on CPU", elapsed
        return retry_verdict, retry_detail, elapsed
    return verdict, detail, elapsed


def sweep(
    jobs: Sequence[SweepJob],
    *,
    spawn: SpawnFn,
    root: str,
    settings_path: str,
    input_path: str,
    data_dir: str,
    cpu: bool,
    cpu_retry: bool,
    strict: bool,
    fail_fast: bool,
    json_path: Optional[str],
    keep_outputs: bool,
    run_meta: Optional[Dict[str, Any]] = None,
) -> int:
    """Run every job serially. One child alive at a time."""
    import shutil

    rows: List[Dict[str, Any]] = []
    verdicts: List[str] = []
    for index, job in enumerate(jobs, 1):
        print(f"[{index}/{len(jobs)}] {job.id}", flush=True)
        job_dir = os.path.join(root, f"job{index:03d}")
        verdict, detail, elapsed = run_one(
            job,
            spawn=spawn,
            job_dir=job_dir,
            settings_path=settings_path,
            input_path=input_path,
            data_dir=data_dir,
            cpu=cpu,
            cpu_retry=cpu_retry,
        )
        print(render_row(job.id, verdict, elapsed, detail), flush=True)
        rows.append(
            {"id": job.id, "verdict": verdict, "detail": detail, "elapsed_s": elapsed}
        )
        verdicts.append(verdict)
        if not keep_outputs:
            shutil.rmtree(job_dir, ignore_errors=True)
        if fail_fast and is_failure(verdict, strict=strict):
            break

    print("-" * 96)
    print(render_summary(verdicts, planned=len(jobs)))
    if json_path:
        from core.json_store import write_json_atomic

        write_json_atomic(
            json_path,
            {
                "run": run_meta or {},
                "planned": len(jobs),
                "executed": len(rows),
                "results": rows,
            },
        )
        print(f"json={json_path}")
    return 1 if any(is_failure(v, strict=strict) for v in verdicts) else 0


def venv_python() -> Optional[str]:
    """Project venv interpreter, if it exists on disk."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_dir = os.environ.get("UVR_VENV_DIR") or os.path.join(root, ".venv")
    candidate = os.path.join(venv_dir, "bin", "python")
    return candidate if os.path.isfile(candidate) else None


def ensure_sweep_interpreter(*, allow_reexec: bool) -> None:
    """Refuse to keep a system Python that cannot import pip deps.

    ``python scripts/model_sweep.py`` often resolves to distro Python, which
    may have numpy but not ``soundfile``. Children inherit ``sys.executable``,
    so the clip-writer crash is only the first failure. Re-exec into ``.venv``
    when this is a real CLI invocation; in-process tests pass ``argv`` and
    must not be replaced.
    """
    import importlib.util

    if importlib.util.find_spec("soundfile") is not None:
        return
    if not allow_reexec:
        return
    venv = venv_python()
    # Do not realpath(): .venv/bin/python is a symlink to the system
    # interpreter, so realpath would look like we are already there.
    if venv:
        venv_bin = os.path.dirname(os.path.abspath(venv))
        here_bin = os.path.dirname(os.path.abspath(sys.executable))
        if here_bin != venv_bin:
            os.execv(venv, [venv, os.path.abspath(__file__), *sys.argv[1:]])
    print(
        "soundfile is not importable in this interpreter.\n"
        "The sweep needs the project venv (pip deps live there, not on system Python).\n"
        "Run:  ./install_packages.sh\n"
        "      .venv/bin/python scripts/model_sweep.py ...",
        file=sys.stderr,
    )
    raise SystemExit(2)


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Local-only: start a real separation for every model installed on "
            "this machine. Weights are gitignored, so this is not part of CI. "
            "The parent stays torch-free; each job runs in its own subprocess. "
            "If this interpreter cannot import soundfile, the CLI re-execs "
            "into .venv/bin/python."
        ),
        epilog=(
            "Settings and GPU:\n"
            "  Default copies settings.json into an isolated scratch dir. GPU\n"
            "  is used only if that copy has process.use_gpu on. --stock-settings\n"
            "  writes empty JSON so Settings defaults apply (use_gpu is False),\n"
            "  which is a CPU run. --cpu forces CPU either way.\n"
            "\n"
            "composite is not an app process method. It is four multi-pass jobs\n"
            "this sweep adds on top of per-model runs: composite:4-stem,\n"
            "composite:ensemble, composite:secondary-chain, composite:vocal-splitter.\n"
            "Missing weights become SKIP, not a failure. They take\n"
            "--composite-timeout, not --timeout.\n"
            "\n"
            "Examples:\n"
            "  python scripts/model_sweep.py --list\n"
            "  python scripts/model_sweep.py --list --manifest /tmp/jobs.json\n"
            "  python scripts/model_sweep.py --method mdx --cpu --json /tmp/out.json\n"
            "  python scripts/model_sweep.py --method composite --composite-timeout 900\n"
        ),
    )
    parser.add_argument("--run-job", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--method",
        action="append",
        choices=("mdx", "vr", "demucs", "apollo", "composite"),
        help=(
            "Limit to these job groups (repeatable; default: all five). "
            "mdx/vr/demucs/apollo are one real run per installed model. "
            "composite is the four multi-pass jobs listed in the epilog, "
            "not UVR's Ensemble Mode process method."
        ),
    )
    parser.add_argument(
        "--only",
        default="",
        metavar="SUBSTR",
        help="Keep only models whose filename contains this substring.",
    )
    parser.add_argument(
        "--skip",
        default="",
        metavar="NAMES",
        help="Comma-separated model filenames to drop from the plan.",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        help=(
            "Force CPU for every job, even if the copied settings.json has GPU on."
        ),
    )
    parser.add_argument(
        "--no-cpu-retry",
        dest="cpu_retry",
        action="store_false",
        help="Do not retry an OOM GPU job on CPU (retry is on by default).",
    )
    parser.set_defaults(cpu_retry=True)
    parser.add_argument(
        "--stock-settings",
        action="store_true",
        help=(
            "Use Settings defaults instead of copying the user's settings.json. "
            "Defaults have GPU off, so this is a CPU run. Omit this flag to "
            "inherit GPU from the copied settings.json (unless --cpu)."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="SEC",
        help=(
            f"Per-model job timeout in seconds (default {DEFAULT_TIMEOUT:.0f}). "
            "Does not apply to composite jobs; use --composite-timeout."
        ),
    )
    parser.add_argument(
        "--composite-timeout",
        type=float,
        default=None,
        metavar="SEC",
        help=(
            "Timeout in seconds for every job --method composite selects "
            f"(defaults: {DEFAULT_TIMEOUT:.0f} for composite:4-stem, "
            f"{ENSEMBLE_TIMEOUT:.0f} for the other three)."
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        metavar="PATH",
        help=(
            "After the run, write results JSON here (outcomes, not the plan). "
            "To dump the planned jobs without running them, use --list "
            "--manifest PATH."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help=(
            "Print the planned job list and exit without running anything. "
            "Combine with --manifest to also write that plan as JSON."
        ),
    )
    parser.add_argument(
        "--manifest",
        default=None,
        metavar="PATH",
        help=(
            "Write the planned job list as JSON (run metadata + jobs) to this "
            "path. Does not stop the run by itself; pass --list as well to "
            "plan-only."
        ),
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help=(
            "Stop after the first failing job. SKIP and OOM-then-CPU-OK "
            "continue; UNRECOGNIZED only stops if --strict is also set."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat an UNRECOGNIZED outcome as a failure (exit non-zero).",
    )
    parser.add_argument(
        "--keep-outputs",
        action="store_true",
        help=(
            "Keep the scratch directory (copied settings, input clip, per-job "
            "exports) instead of deleting it when the sweep finishes."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    import shutil
    import tempfile

    args = build_parser().parse_args(argv)
    if args.run_job:
        return run_child(args.run_job)
    ensure_sweep_interpreter(allow_reexec=argv is None)

    from core import ModelRepository
    from core import paths as core_paths
    from core.settings import Settings

    repo = ModelRepository()
    repo.reload_mappers()
    settings = Settings.load(core_paths.SETTINGS_DATA_FILE)
    installed = collect_installed(repo, settings)

    methods = set(args.method) if args.method else {"mdx", "vr", "demucs", "apollo", "composite"}
    skip = frozenset(s for s in (args.skip or "").split(",") if s)
    jobs = discover_jobs(installed, methods=methods, only=args.only, skip=skip)
    jobs = apply_timeouts(
        jobs, timeout=args.timeout, composite_timeout=args.composite_timeout
    )
    meta = run_metadata(args, methods=sorted(methods))

    if args.manifest:
        write_manifest(args.manifest, jobs, run_meta=meta)
        print(f"manifest={args.manifest}")

    if args.list:
        for job in jobs:
            print(f"{job.id:<52} {job.kind}")
        print(f"{len(jobs)} jobs")
        return 0

    assert "torch" not in sys.modules, "the sweep parent must stay torch-free"

    root = tempfile.mkdtemp(prefix="uvr-sweep-")
    print(f"scratch={root}")
    try:
        data_dir, settings_path = prepare_scratch(
            os.path.join(root, "data"),
            models_dir=core_paths.MODELS_DIR,
            settings_src=None if args.stock_settings else core_paths.SETTINGS_DATA_FILE,
        )
        input_path = make_input_clip(os.path.join(root, "sweep-input.wav"))

        return sweep(
            jobs,
            spawn=spawn_child,
            root=root,
            settings_path=settings_path,
            input_path=input_path,
            data_dir=data_dir,
            cpu=args.cpu,
            cpu_retry=args.cpu_retry,
            strict=args.strict,
            fail_fast=args.fail_fast,
            json_path=args.json_path,
            keep_outputs=args.keep_outputs,
            run_meta=meta,
        )
    finally:
        # sweep() already drops each job dir unless --keep-outputs; the copied
        # settings, models symlink and input clip live at the top level and are
        # nobody else's to remove.
        if args.keep_outputs:
            print(f"scratch preserved (--keep-outputs): {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
