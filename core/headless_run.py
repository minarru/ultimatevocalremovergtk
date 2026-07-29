"""Headless separation helpers (no GTK).

Used by ``python -m core.cli`` to drive :class:`JobRunner` synchronously with
the same settings schema as the GUI.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from bundled.constants import (
    ALL_STEMS,
    BASS_STEM,
    DEMUCS_ARCH_TYPE,
    DRUM_STEM,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    OTHER_STEM,
    VOCAL_STEM,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)

from .job_runner import JobCallbacks, JobRunner
from .paths import SETTINGS_DATA_FILE
from .settings import Settings

METHOD_ALIASES = {
    "mdx": MDX_ARCH_TYPE,
    "mdx-net": MDX_ARCH_TYPE,
    "demucs": DEMUCS_ARCH_TYPE,
    "vr": VR_ARCH_PM,
    "vr-architecture": VR_ARCH_PM,
}

_MODEL_KEY_BY_METHOD = {
    VR_ARCH_PM: "vr_model",
    MDX_ARCH_TYPE: "mdx_net_model",
    DEMUCS_ARCH_TYPE: "demucs_model",
}
_MODEL_SECTION_BY_METHOD = {
    VR_ARCH_PM: "vr",
    MDX_ARCH_TYPE: "mdx",
    DEMUCS_ARCH_TYPE: "demucs",
}

# Settings method → architecture key used by model_display / ModelData.
_ARCH_FOR_METHOD = {
    VR_ARCH_PM: VR_ARCH_TYPE,
    MDX_ARCH_TYPE: MDX_ARCH_TYPE,
    DEMUCS_ARCH_TYPE: DEMUCS_ARCH_TYPE,
}

_MODEL_FILE_EXTS = (".onnx", ".ckpt", ".pth", ".th", ".yaml", ".gz")

# CLI --stems tokens → canonical labels.
_STEM_TOKEN_ALIASES = {
    "both": "both",
    "all": "both",
    "primary": "primary",
    "secondary": "secondary",
    "vocals": "vocals",
    "vocal": "vocals",
    "instrumental": "instrumental",
    "inst": "instrumental",
    "bass": "bass",
    "drums": "drums",
    "drum": "drums",
    "other": "other",
}

_DEMUCS_FOCUS_BY_TOKEN = {
    "vocals": VOCAL_STEM,
    "instrumental": VOCAL_STEM,  # UI: derive instrumental from vocals focus
    "bass": BASS_STEM,
    "drums": DRUM_STEM,
    "other": OTHER_STEM,
}


@dataclass
class HeadlessResult:
    """Outcome of a synchronous headless separation run."""

    ok: bool
    elapsed_s: float
    export_path: str
    error: Optional[BaseException] = None
    stopped: bool = False
    console: list[str] = field(default_factory=list)


def resolve_method(method: Optional[str]) -> Optional[str]:
    """Map a CLI method alias to the settings ``chosen_process_method`` value."""
    if method is None:
        return None
    key = method.strip().lower()
    if key in METHOD_ALIASES:
        return METHOD_ALIASES[key]
    # Allow passing the exact settings string.
    for value in (MDX_ARCH_TYPE, DEMUCS_ARCH_TYPE, VR_ARCH_PM):
        if key == value.lower():
            return value
    raise ValueError(
        f"unknown method {method!r}; expected one of: mdx, demucs, vr "
        f"(or exact settings values)"
    )


def _stem_from_model_arg(model_arg: str) -> str:
    """Strip directories and known weight extensions from a CLI ``--model`` value."""
    name = os.path.basename(str(model_arg).strip())
    root, ext = os.path.splitext(name)
    if ext.lower() in _MODEL_FILE_EXTS:
        return root
    return name


def _normalize_model_query(text: str) -> str:
    """Collapse a model name to lowercase alphanumerics for fuzzy CLI matching."""
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def _resolve_among_installed(
    *,
    raw: str,
    stem: str,
    arch: str,
    installed: Sequence[str],
    repository: Any,
) -> str:
    """Map a CLI model token to a unique installed display label."""
    from .model_display import display_name_for_model, map_basenames_to_display

    displays = list(map_basenames_to_display(list(installed), arch, repository))
    by_display = {disp: disp for disp in displays}
    if raw in by_display:
        return raw
    if stem in by_display:
        return stem

    installed_by_lower = {name.lower(): name for name in installed}
    if stem in installed:
        return display_name_for_model(arch, stem, repository)
    if stem.lower() in installed_by_lower:
        return display_name_for_model(arch, installed_by_lower[stem.lower()], repository)

    query = _normalize_model_query(stem)
    if not query:
        raise ValueError(f"unknown --model {raw!r}")

    matches: list[str] = []
    for basename, display in zip(installed, displays):
        keys = (
            _normalize_model_query(basename),
            _normalize_model_query(display),
        )
        if any(query == key or (query in key) for key in keys if key):
            matches.append(display)

    unique = list(dict.fromkeys(matches))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        preview = ", ".join(repr(name) for name in unique[:6])
        more = "" if len(unique) <= 6 else f", … (+{len(unique) - 6} more)"
        raise ValueError(
            f"ambiguous --model {raw!r}; matches: {preview}{more}. "
            f"Pass a fuller basename or the GUI display name."
        )
    raise ValueError(
        f"unknown --model {raw!r} for method {arch!r}. "
        f"Pass an installed weight basename/filename or GUI display name."
    )


def resolve_cli_model_arg(method: str, model_arg: str, repo: Optional[Any] = None) -> str:
    """Normalize a CLI ``--model`` to the label :class:`ModelData` expects.

    Accepts:
    - GUI display names (unchanged when already known)
    - On-disk basenames (``model_BandSplit-Roformer_Karaoke_Frazer_by-becruily``)
    - Filenames with extension (``….ckpt``)
    - Short unique substrings of those names (``karaoke_frazer``)
    - Absolute/relative paths to a weight file

    Filenames are mapped to catalogue/GUI display labels when possible so Demucs
    version tags and MDX name mappers keep working. Does not change UI storage.
    """
    from .model_data import ModelRepository

    raw = str(model_arg).strip()
    if not raw:
        raise ValueError("--model value is empty")

    stem = _stem_from_model_arg(raw)
    arch = _ARCH_FOR_METHOD.get(method)
    if arch is None:
        return stem

    repository = repo or ModelRepository()

    if arch == MDX_ARCH_TYPE:
        return _resolve_among_installed(
            raw=raw,
            stem=stem,
            arch=arch,
            installed=repository.list_mdx_models(),
            repository=repository,
        )
    if arch == VR_ARCH_TYPE:
        return _resolve_among_installed(
            raw=raw,
            stem=stem,
            arch=arch,
            installed=repository.list_vr_models(),
            repository=repository,
        )
    if arch == DEMUCS_ARCH_TYPE:
        from .demucs_models import demucs_bag_owner_basename
        from .model_display import display_name_for_model

        # Bag-member .th weights are hidden from list_demucs_models(); map them
        # to the parent yaml the GUI actually selects.
        owner = demucs_bag_owner_basename(stem)
        if owner:
            return display_name_for_model(arch, owner, repository)
        return _resolve_among_installed(
            raw=raw,
            stem=stem,
            arch=arch,
            installed=repository.list_demucs_models(),
            repository=repository,
        )
    return stem


def parse_cli_stems(stems_arg: str) -> set[str]:
    """Parse ``--stems`` into a set of canonical tokens (``both``, ``vocals``, …)."""
    raw = str(stems_arg or "").strip()
    if not raw:
        raise ValueError("--stems value is empty")
    tokens: set[str] = set()
    for part in raw.replace(";", ",").split(","):
        key = part.strip().lower()
        if not key:
            continue
        canon = _STEM_TOKEN_ALIASES.get(key)
        if canon is None:
            known = ", ".join(sorted(set(_STEM_TOKEN_ALIASES)))
            raise ValueError(f"unknown --stems token {part.strip()!r}; expected one of: {known}")
        tokens.add(canon)
    if not tokens:
        raise ValueError("--stems value is empty")
    return tokens


def _set_exclusive_stem_flags(
    settings: Settings,
    *,
    primary_only: bool,
    secondary_only: bool,
) -> None:
    settings.process.primary_stem_only = primary_only
    settings.process.secondary_stem_only = secondary_only
    settings.demucs.is_primary_stem_only = primary_only
    settings.demucs.is_secondary_stem_only = secondary_only


def apply_stems_override(settings: Settings, stems_arg: str) -> str:
    """Apply a CLI ``--stems`` override to settings (does not persist).

    Mirrors the GUI Save-stems quick modes for dual-stem and Demucs focus.
    Returns a short label describing what will be saved.
    """
    tokens = parse_cli_stems(stems_arg)

    if "both" in tokens or tokens >= {"vocals", "instrumental"}:
        _set_exclusive_stem_flags(settings, primary_only=False, secondary_only=False)
        settings.demucs.stems = ALL_STEMS
        settings.mdx.stems = ALL_STEMS
        settings.mdx.stems_selected = []
        return "both"

    if len(tokens) != 1:
        raise ValueError(
            f"ambiguous --stems {stems_arg!r}; use both, primary, secondary, "
            f"vocals, instrumental, or a single Demucs stem (bass/drums/other)"
        )

    choice = next(iter(tokens))
    if choice == "primary":
        _set_exclusive_stem_flags(settings, primary_only=True, secondary_only=False)
        settings.mdx.stems = ALL_STEMS
        settings.mdx.stems_selected = []
        return "primary"

    if choice == "secondary":
        _set_exclusive_stem_flags(settings, primary_only=False, secondary_only=True)
        settings.mdx.stems = ALL_STEMS
        settings.mdx.stems_selected = []
        return "secondary"

    if choice == "vocals":
        # Same as UI "Vocals only" / Demucs focus vocals.
        _set_exclusive_stem_flags(settings, primary_only=True, secondary_only=False)
        settings.demucs.stems = VOCAL_STEM
        settings.mdx.stems = VOCAL_STEM
        settings.mdx.stems_selected = [VOCAL_STEM]
        return "vocals"

    if choice == "instrumental":
        # Same as UI "Instrumental only" (derived / secondary).
        _set_exclusive_stem_flags(settings, primary_only=False, secondary_only=True)
        settings.demucs.stems = VOCAL_STEM
        settings.mdx.stems = VOCAL_STEM
        settings.mdx.stems_selected = [VOCAL_STEM]
        return "instrumental"

    focus = _DEMUCS_FOCUS_BY_TOKEN.get(choice)
    if focus is None:
        raise ValueError(f"unsupported --stems token {choice!r}")
    _set_exclusive_stem_flags(settings, primary_only=True, secondary_only=False)
    settings.demucs.stems = focus
    settings.mdx.stems = ALL_STEMS
    settings.mdx.stems_selected = []
    return choice


def build_settings(
    *,
    settings_path: Optional[str] = None,
    export_path: Optional[str] = None,
    method: Optional[str] = None,
    model: Optional[str] = None,
    stems: Optional[str] = None,
    use_gpu: Optional[bool] = None,
    stable_names: bool = True,
    repo: Optional[Any] = None,
    long_chunk_seconds: Optional[float] = None,
    long_chunk_overlap: Optional[float] = None,
) -> Settings:
    """Load settings and apply CLI overrides (does not persist)."""
    path = settings_path or SETTINGS_DATA_FILE
    settings = Settings.load(path)

    if export_path is not None:
        settings.process.export_path = export_path

    resolved_method = resolve_method(method) if method else None
    if resolved_method is not None:
        settings.process.method = resolved_method

    chosen = settings.process.method
    if chosen == ENSEMBLE_MODE:
        raise ValueError(
            "ensemble mode is not supported by the headless CLI (v1); "
            "pass --method mdx|demucs|vr"
        )

    if model is not None:
        method_for_model = resolved_method or chosen
        model_section = _MODEL_SECTION_BY_METHOD.get(method_for_model)
        if model_section is None:
            raise ValueError(
                f"cannot set --model for process method {method_for_model!r}"
            )
        getattr(settings, model_section).model = resolve_cli_model_arg(
            method_for_model, model, repo=repo
        )

    if stems is not None:
        apply_stems_override(settings, stems)

    if use_gpu is not None:
        settings.process.use_gpu = bool(use_gpu)

    if stable_names:
        # Stable basenames make stem pairing for bench-ab reliable.
        settings.process.create_model_folder = False
        settings.process.testing_audio = False
        settings.process.add_model_name = False

    if long_chunk_seconds is not None:
        settings.process.long_file_chunk_seconds = float(long_chunk_seconds)
    if long_chunk_overlap is not None:
        settings.process.long_file_chunk_overlap_seconds = float(long_chunk_overlap)

    return settings


def run_separation_sync(
    settings: Settings,
    input_paths: Sequence[str],
    *,
    print_console: bool = True,
    join_timeout: Optional[float] = None,
) -> HeadlessResult:
    """Start :class:`JobRunner` and block until complete / error / stop."""
    if not input_paths:
        raise ValueError("at least one input path is required")

    chosen = settings.process.method
    if chosen == ENSEMBLE_MODE:
        raise ValueError("ensemble mode is not supported by the headless CLI (v1)")

    export_path = str(settings.process.export_path or "")
    if not export_path:
        raise ValueError("export_path is empty; pass -o/--output")

    console_lines: list[str] = []
    error_box: list[BaseException] = []
    done = threading.Event()
    outcome = {"stopped": False}

    def on_console(text: str) -> None:
        console_lines.append(text)
        if print_console:
            sys.stdout.write(text if text.endswith("\n") else text + "\n")
            sys.stdout.flush()

    def on_complete() -> None:
        done.set()

    def on_stopped() -> None:
        outcome["stopped"] = True
        done.set()

    def on_error(exc: BaseException) -> None:
        error_box.append(exc)
        done.set()

    callbacks = JobCallbacks(
        on_console=on_console,
        on_complete=on_complete,
        on_stopped=on_stopped,
        on_error=on_error,
    )

    runner = JobRunner(settings)
    started = time.perf_counter()
    try:
        runner.start(list(input_paths), callbacks)
        while not done.wait(timeout=0.25):
            if not runner.is_running() and not done.is_set():
                # Worker exited without signaling (unexpected).
                done.set()
                break
            if join_timeout is not None and (time.perf_counter() - started) > join_timeout:
                runner.stop(force=True)
                raise TimeoutError(f"separation exceeded {join_timeout:.0f}s")
    except KeyboardInterrupt:
        runner.stop(force=True)
        done.wait(timeout=5.0)
        raise
    finally:
        # Wait for the worker thread to finish cleanup.
        thread = getattr(runner, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout if join_timeout else None)
        try:
            runner.release_inference_memory(clear_weight_cache=False)
        except Exception:
            # Best-effort: never mask the original start/run failure (e.g. missing deps).
            pass

    elapsed = time.perf_counter() - started
    err = error_box[0] if error_box else None
    ok = err is None and not outcome["stopped"]
    return HeadlessResult(
        ok=ok,
        elapsed_s=elapsed,
        export_path=export_path,
        error=err,
        stopped=bool(outcome["stopped"]),
        console=console_lines,
    )


def settings_summary(settings: Settings) -> dict[str, Any]:
    """Small dict of the knobs most relevant to headless runs."""
    method = settings.process.method
    model_key = _MODEL_KEY_BY_METHOD.get(method, "")
    model_section = _MODEL_SECTION_BY_METHOD.get(method)
    return {
        "chosen_process_method": method,
        "model_key": model_key,
        "model": getattr(settings, model_section).model if model_section else None,
        "export_path": settings.process.export_path,
        "is_gpu_conversion": settings.process.use_gpu,
        "save_format": settings.process.save_format,
        "is_primary_stem_only": settings.process.primary_stem_only,
        "is_secondary_stem_only": settings.process.secondary_stem_only,
        "demucs_stems": settings.demucs.stems,
        "mdx_stems": settings.mdx.stems,
        "mdx_stems_selected": settings.mdx.stems_selected,
        "long_file_chunk_seconds": settings.process.long_file_chunk_seconds,
        "long_file_chunk_overlap_seconds": (
            settings.process.long_file_chunk_overlap_seconds
        ),
    }
