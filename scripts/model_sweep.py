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
from typing import Any, Dict, List, Optional, Sequence

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
