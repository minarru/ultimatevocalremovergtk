"""Nested secondary / vocal-split / Demucs pre-process ModelConfig factories.

Tk-free ports of ``MainWindow.process_determine_*``. Kept beside
:class:`~core.model_config.ModelConfig` so the repository module does not own
per-run chain construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional

from bundled.constants import (
    BASS_STEM,
    CHOOSE_MODEL,
    DEMUCS_ARCH_TYPE,
    DRUM_STEM,
    INST_STEM,
    MDX_ARCH_TYPE,
    NO_BASS_STEM,
    NO_DRUM_STEM,
    NO_MODEL,
    NO_OTHER_STEM,
    OTHER_STEM,
    VOCAL_STEM,
    VR_ARCH_TYPE,
)

from ..settings import Settings

if TYPE_CHECKING:
    from ..model_identity import ModelRecord
    from ..model_repository import ModelRepository

_SECONDARY_PREFIX_BY_METHOD = {
    VR_ARCH_TYPE: "vr",
    MDX_ARCH_TYPE: "mdx",
    DEMUCS_ARCH_TYPE: "demucs",
}


def secondary_slot_for_primary_stem(main_model_primary_stem: str) -> Optional[str]:
    """Return the nested slot for a normalized native primary-stem label."""
    return {
        str(VOCAL_STEM).strip().casefold(): "voc_inst",
        str(INST_STEM).strip().casefold(): "voc_inst",
        str(OTHER_STEM).strip().casefold(): "other",
        str(NO_OTHER_STEM).strip().casefold(): "other",
        str(DRUM_STEM).strip().casefold(): "drums",
        str(NO_DRUM_STEM).strip().casefold(): "drums",
        str(BASS_STEM).strip().casefold(): "bass",
        str(NO_BASS_STEM).strip().casefold(): "bass",
    }.get(str(main_model_primary_stem or "").strip().casefold())


# Kept as a private spelling for callers outside the active topology path.
_secondary_slot_for_stem = secondary_slot_for_primary_stem


def _model_config_for_reference(
    settings: Settings,
    repo: "ModelRepository",
    reference: str,
    **kwargs: Any,
):
    """Build a nested ModelConfig from a settings model reference.

    Canonical IDs (``mdx:...``) are not ensemble member tags. Passing them to
    :class:`ModelConfig` with the default ``ENSEMBLE_MODE`` leaves ``model_path``
    unset and crashes when reading ``model_basename``.
    """
    from .config import ModelConfig
    from ..model_identity import ModelIdentityService

    raw = str(reference or "")
    if not raw or raw in {CHOOSE_MODEL, NO_MODEL}:
        return None
    record = ModelIdentityService(repo).lookup(raw)
    return ModelConfig(
        settings,
        repo,
        record.display,
        record.arch,
        identity=record,
        **kwargs,
    )


def _model_config_for_record(
    settings: Settings,
    repo: "ModelRepository",
    record: "ModelRecord",
    *,
    model_dependencies: Mapping[str, "ModelRecord"] | None = None,
    **kwargs: Any,
):
    from .config import ModelConfig

    return ModelConfig(
        settings,
        repo,
        record.display,
        record.arch,
        identity=record,
        model_dependencies=model_dependencies,
        **kwargs,
    )


def process_determine_secondary_model(
    settings: Settings,
    repo: "ModelRepository",
    process_method: str,
    main_model_primary_stem: str,
    model_dependencies: Mapping[str, "ModelRecord"] | None = None,
):
    """Tk-free port of ``MainWindow.process_determine_secondary_model``."""
    prefix = _SECONDARY_PREFIX_BY_METHOD.get(process_method)
    if prefix is None:
        return None, None

    slot = secondary_slot_for_primary_stem(main_model_primary_stem)
    section = getattr(settings, prefix)
    dependency_path = f"{prefix}.{slot}_secondary_model" if slot else None
    secondary_model_name = (
        getattr(section, f"{slot}_secondary_model") if slot else NO_MODEL
    )
    secondary_model_scale = (
        getattr(section, f"{slot}_secondary_model_scale") if slot else None
    )
    if secondary_model_scale:
        secondary_model_scale = float(secondary_model_scale)

    secondary_model = None
    record = (
        model_dependencies.get(dependency_path)
        if model_dependencies is not None and dependency_path is not None
        else None
    )
    if record is not None:
        secondary_model = _model_config_for_record(
            settings, repo, record,
            model_dependencies=model_dependencies,
            is_secondary_model=True,
            primary_model_primary_stem=main_model_primary_stem,
        )
    elif model_dependencies is None and secondary_model_name and secondary_model_name != NO_MODEL:
        secondary_model = _model_config_for_reference(
            settings, repo, secondary_model_name,
            is_secondary_model=True,
            primary_model_primary_stem=main_model_primary_stem,
        )
    if secondary_model is not None and not secondary_model.model_status:
        secondary_model = None

    return secondary_model, secondary_model_scale


def process_determine_demucs_pre_proc_model(
    settings: Settings,
    repo: "ModelRepository",
    primary_stem: Any = None,
    model_dependencies: Mapping[str, "ModelRecord"] | None = None,
):
    """Tk-free port of ``MainWindow.process_determine_demucs_pre_proc_model``."""
    pre_proc_name = settings.demucs.pre_proc_model
    if pre_proc_name != NO_MODEL and settings.demucs.is_pre_proc_model_activate:
        record = (
            model_dependencies.get("demucs.pre_proc_model")
            if model_dependencies is not None else None
        )
        pre_proc_model = (
            _model_config_for_record(
                settings, repo, record,
                model_dependencies=model_dependencies,
                primary_model_primary_stem=primary_stem,
                is_pre_proc_model=True,
            )
            if record is not None else (
                _model_config_for_reference(
                    settings, repo, pre_proc_name,
                    primary_model_primary_stem=primary_stem,
                    is_pre_proc_model=True,
                )
                if model_dependencies is None else None
            )
        )
        if pre_proc_model is not None and pre_proc_model.model_status:
            return pre_proc_model
    return None


def process_determine_vocal_split_model(
    settings: Settings,
    repo: "ModelRepository",
    model_dependencies: Mapping[str, "ModelRecord"] | None = None,
):
    """Tk-free port of ``MainWindow.process_determine_vocal_split_model``."""
    split_name = settings.process.vocal_splitter
    if split_name != NO_MODEL and settings.process.vocal_splitter_enabled:
        record = (
            model_dependencies.get("process.vocal_splitter")
            if model_dependencies is not None else None
        )
        vocal_splitter_model = (
            _model_config_for_record(
                settings, repo, record,
                model_dependencies=model_dependencies,
                is_vocal_split_model=True,
            )
            if record is not None else (
                _model_config_for_reference(
                    settings, repo, split_name, is_vocal_split_model=True
                )
                if model_dependencies is None else None
            )
        )
        if vocal_splitter_model is not None and vocal_splitter_model.model_status:
            return vocal_splitter_model
    return None
