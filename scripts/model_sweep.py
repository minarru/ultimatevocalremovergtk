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

# Literal values verified against bundled/constants/process.py.
MAX_MIN = "Max Spec/Min Spec"
VOCAL_PAIR = "Vocals/Instrumental"
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
    from core.apollo import list_apollo_models
    from bundled.constants import INST_STEM, VOCAL_STEM

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


def _skip(job_id: str, reason: str) -> SweepJob:
    return SweepJob(id=job_id, kind=KIND_SKIP, detail=reason)


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
                )
            )
        else:
            jobs.append(_skip("composite:4-stem", "no 4-stem model installed"))

    # 2. Two-member ensemble.
    if len(installed.ensemble_tags) >= 2:
        jobs.append(
            SweepJob(
                id="composite:ensemble",
                kind=KIND_ENSEMBLE,
                overrides={
                    "selected_models": installed.ensemble_tags[:2],
                    "ensemble_type": MAX_MIN,
                    "ensemble_main_stem": VOCAL_PAIR,
                    "is_save_all_outputs_ensemble": False,
                },
                timeout=ENSEMBLE_TIMEOUT,
            )
        )
    else:
        jobs.append(_skip("composite:ensemble", "needs two ensemble-capable models"))

    # 3. Primary + secondary chain.
    mdx_tag = next((t for t in installed.ensemble_tags if t.startswith("MDX-Net")), None)
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
            )
        )
    else:
        jobs.append(_skip("composite:secondary-chain", "needs a VR and an MDX model"))

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
            )
        )
    else:
        jobs.append(_skip("composite:vocal-splitter", "needs an MDX and a karaoke model"))

    return jobs


PASS = "PASS"
NO_OUTPUT = "NO_OUTPUT"
TIMEOUT = "TIMEOUT"
OOM = "OOM"
OOM_CPU_OK = "OOM(cpu-ok)"
UNRECOGNIZED = "UNRECOGNIZED"


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def classify(
    *, exit_code: Optional[int], result: Optional[dict], timed_out: bool
) -> tuple:
    """Turn a child's exit code and result payload into a verdict + detail."""
    from core.oom_markers import is_oom_message

    if timed_out:
        return TIMEOUT, ""
    if result is None:
        return f"CRASH(exit {exit_code})", ""
    if result.get("unrecognized"):
        return UNRECOGNIZED, "model hash not in the metadata tables"

    error_type = result.get("error_type")
    message = str(result.get("message") or "")
    if error_type:
        detail = _first_line(message)
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
    return f"{row}\n    {detail}" if detail else row


def render_summary(verdicts: Sequence[str]) -> str:
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
    return env


AUDIO_SUFFIXES = (".wav", ".flac", ".mp3", ".aiff", ".ogg", ".opus")


def apply_overrides(settings: Any, overrides: Dict[str, Any]) -> None:
    """Apply job overrides. Dotted keys are nested paths; bare keys are flat keys.

    ``set_flat`` silently no-ops on an unmapped key, which would make a job
    quietly test the wrong configuration — so unmapped keys raise here instead.
    """
    from core.settings.access import set_flat, set_path
    from core.settings.flat_map import FLAT_TO_PATH

    for key, value in overrides.items():
        if "." in key:
            set_path(settings, key, value)
            continue
        if key not in FLAT_TO_PATH:
            raise KeyError(f"flat key {key!r} is not in FLAT_TO_PATH; add the mapping first")
        set_flat(settings, key, value)


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


def _model_is_recognized(settings: Any, method: Optional[str], model: Optional[str]) -> bool:
    """Whether the weight resolves to known metadata (MD5 → model_data)."""
    if not model or method is None:
        return True
    from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
    from core import ModelConfig, ModelRepository

    arch = {"mdx": MDX_ARCH_TYPE, "vr": VR_ARCH_TYPE, "demucs": DEMUCS_ARCH_TYPE}[method]
    repo = ModelRepository()
    config = ModelConfig(settings, repo, model, arch, is_dry_check=True)
    return bool(config.model_status)


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
        os.makedirs(export_dir, exist_ok=True)

        from bundled.constants import ENSEMBLE_MODE
        from core.headless_run import build_settings, run_ensemble_sync, run_separation_sync
        from core.types import ProcessMethod

        kind = spec["kind"]
        settings = build_settings(
            settings_path=spec["settings_path"],
            export_path=export_dir,
            method=spec.get("method"),
            model=spec.get("model"),
            use_gpu=False if spec.get("cpu") else None,
            stable_names=True,
            allow_ensemble=(kind == KIND_ENSEMBLE),
        )
        if kind == KIND_ENSEMBLE:
            settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        apply_overrides(settings, spec.get("overrides") or {})

        if kind == KIND_SINGLE and not _model_is_recognized(
            settings, spec.get("method"), spec.get("model")
        ):
            result["unrecognized"] = True
            result["elapsed_s"] = time.perf_counter() - started
            _write_result(job_dir, result)
            return 0

        timeout = float(spec.get("timeout") or DEFAULT_TIMEOUT)
        if kind == KIND_TOOL:
            outcome_error, stopped = _run_tool(settings, spec["input_path"], timeout)
        elif kind == KIND_ENSEMBLE:
            outcome = run_ensemble_sync(
                settings, [spec["input_path"]], print_console=True, join_timeout=timeout
            )
            outcome_error, stopped = outcome.error, outcome.stopped
        else:
            outcome = run_separation_sync(
                settings, [spec["input_path"]], print_console=True, join_timeout=timeout
            )
            outcome_error, stopped = outcome.error, outcome.stopped

        result["stopped"] = bool(stopped)
        if outcome_error is not None:
            result["error_type"] = type(outcome_error).__name__
            result["message"] = str(outcome_error)
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
    import json

    with open(os.path.join(job_dir, "result.json"), "w") as handle:
        json.dump(result, handle)


def _run_tool(settings: Any, input_path: str, timeout: float) -> tuple:
    """Run the Apollo restore tool, mirroring the UI's model resolution."""
    import threading

    from core import ModelRepository
    from core.apollo import ApolloModelData
    from core.audio_tools import AudioToolRunner
    from core.job_runner import JobCallbacks

    repo = ModelRepository()
    model_data = ApolloModelData(
        settings.audio_tools.apollo_model,
        model_hash_table=repo.model_hash_table,
        on_unrecognized=None,
    )
    if not model_data.is_model_status:
        raise RuntimeError(f"Apollo model not valid: {settings.audio_tools.apollo_model}")

    done = threading.Event()
    error_box: List[BaseException] = []
    stopped_box: List[bool] = []

    def _on_console(text: str) -> None:
        sys.stdout.write(text)

    def _on_stopped() -> None:
        stopped_box.append(True)
        done.set()

    def _on_error(exc: BaseException) -> None:
        error_box.append(exc)
        done.set()

    callbacks = JobCallbacks(
        on_console=_on_console,
        on_complete=done.set,
        on_stopped=_on_stopped,
        on_error=_on_error,
    )
    runner = AudioToolRunner(settings)
    runner.start(
        APOLLO_RESTORE,
        [input_path],
        [],
        callbacks,
        apollo_params={
            "extracted_params": model_data.extracted_params,
            "config": model_data.config,
        },
    )
    if not done.wait(timeout=timeout):
        # A bare stop() only sets a flag (core/audio_tools.py); it never
        # calls KThread.terminate(). Without force=True the non-daemon
        # worker thread keeps running after this raises, and the child
        # can't exit on its own — the parent would have to SIGKILL it.
        runner.stop(force=True)
        raise TimeoutError(f"audio tool exceeded {timeout:.0f}s")
    return (error_box[0] if error_box else None), bool(stopped_box)


def spawn_child(*, spec: Dict[str, Any], job_dir: str, env: Dict[str, str], timeout: float):
    """Run one job in a fresh process. Returns ``(exit_code, result, timed_out)``."""
    import json
    import subprocess

    os.makedirs(job_dir, exist_ok=True)
    spec_path = os.path.join(job_dir, "spec.json")
    with open(spec_path, "w") as handle:
        json.dump(spec, handle)

    result_path = os.path.join(job_dir, "result.json")
    if os.path.exists(result_path):
        os.remove(result_path)

    argv = [sys.executable, os.path.abspath(__file__), "--run-job", spec_path]
    timed_out = False
    try:
        completed = subprocess.run(argv, env=env, timeout=timeout + 30.0)
        exit_code = completed.returncode
    except subprocess.TimeoutExpired:
        return None, None, True

    result = None
    if os.path.isfile(result_path):
        with open(result_path) as handle:
            result = json.load(handle)
    return exit_code, result, timed_out


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
) -> int:
    """Run every job serially. One child alive at a time."""
    import json
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
    print(render_summary(verdicts))
    if json_path:
        with open(json_path, "w") as handle:
            json.dump({"results": rows}, handle, indent=2)
        print(f"json={json_path}")
    return 1 if any(is_failure(v, strict=strict) for v in verdicts) else 0


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Start a real run for every model installed on this machine."
    )
    parser.add_argument("--run-job", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--method",
        action="append",
        choices=("mdx", "vr", "demucs", "apollo", "composite"),
        help="Limit to these job groups (repeatable; default: all)",
    )
    parser.add_argument("--only", default="", help="Substring filter on model filename")
    parser.add_argument("--skip", default="", help="Comma-separated model filenames to skip")
    parser.add_argument("--cpu", action="store_true", help="Force CPU for every job")
    parser.add_argument(
        "--no-cpu-retry",
        dest="cpu_retry",
        action="store_false",
        help="Do not retry an OOM job on CPU",
    )
    parser.set_defaults(cpu_retry=True)
    parser.add_argument(
        "--stock-settings",
        action="store_true",
        help="Use default settings instead of a copy of the user's settings.json",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--list", action="store_true", help="Print the job list and exit")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--strict", action="store_true", help="Treat UNRECOGNIZED as a failure"
    )
    parser.add_argument("--keep-outputs", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    import tempfile

    args = build_parser().parse_args(argv)
    if args.run_job:
        return run_child(args.run_job)

    from core import ModelRepository
    from core.settings import Settings
    from core import paths as core_paths

    repo = ModelRepository()
    repo.reload_mappers()
    settings = Settings.load(core_paths.SETTINGS_DATA_FILE)
    installed = collect_installed(repo, settings)

    methods = set(args.method) if args.method else {"mdx", "vr", "demucs", "apollo", "composite"}
    skip = frozenset(s for s in (args.skip or "").split(",") if s)
    jobs = discover_jobs(installed, methods=methods, only=args.only, skip=skip)
    jobs = [
        job if job.timeout != DEFAULT_TIMEOUT else SweepJob(**{**job.__dict__, "timeout": args.timeout})
        for job in jobs
    ]

    if args.list:
        for job in jobs:
            print(f"{job.id:<52} {job.kind}")
        print(f"{len(jobs)} jobs")
        return 0

    assert "torch" not in sys.modules, "the sweep parent must stay torch-free"

    root = tempfile.mkdtemp(prefix="uvr-sweep-")
    print(f"scratch={root}")
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
    )


if __name__ == "__main__":
    raise SystemExit(main())
