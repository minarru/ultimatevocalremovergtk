"""Pure presentation of an already-resolved processing plan."""

import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from core.job_plan_types import ResolvedJob
from core.sample_mode import fitted_sample_start, sample_length, sample_start, seconds_text
from core.settings import Settings


def _shown_start(starts: Mapping[str, float], path: str, duration: float) -> float:
    """The start the run will use, once a known file length pulls a late start back."""
    start = sample_start(starts, path)
    if start <= 0:
        return start
    from core.audio_probe import audio_duration_seconds

    return fitted_sample_start(start, duration, audio_duration_seconds(path))


def _clock(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def _sample_lengths(plan: ResolvedJob) -> list[float]:
    process = plan.settings.process
    default = process.sample_mode_duration
    return [sample_length(process.sample_lengths, item.path, default) for item in plan.inputs]


def _sample_summary(plan: ResolvedJob) -> tuple[str, str | None]:
    """The Sample row and, when inputs have different ranges, a per-input line."""
    process = plan.settings.process
    if not process.sample_mode:
        return "Full tracks", None
    lengths = _sample_lengths(plan)
    starts = [
        _shown_start(process.sample_starts, item.path, length)
        for item, length in zip(plan.inputs, lengths, strict=True)
    ]
    if len(set(lengths)) <= 1:
        duration = seconds_text(lengths[0] if lengths else process.sample_mode_duration)
        if not any(starts):
            return f"First {duration} s", None
        if len(set(starts)) == 1:
            return f"{duration} s from {_clock(starts[0])}", None
        detail = ", ".join(
            f"{os.path.basename(item.path)} {_clock(start)}"
            for item, start in zip(plan.inputs, starts, strict=True)
        )
        return f"{duration} s, custom ranges", f"Sample starts: {detail}"
    detail = ", ".join(
        f"{os.path.basename(item.path)} {seconds_text(length)} s from {_clock(start)}"
        for item, start, length in zip(plan.inputs, starts, lengths, strict=True)
    )
    return "Custom ranges", f"Sample ranges: {detail}"


def _files(count: int) -> str:
    return f"{count} {'file' if count == 1 else 'files'}"


def _format(settings: Settings) -> str:
    process = settings.process
    format_name = process.save_format.value
    quality = {
        "WAV": process.wav_type.value.replace("PCM_", "").replace("U8", "8") + "-bit"
        if process.wav_type.value.startswith("PCM_")
        else process.wav_type.value.replace("FLOAT", "32-bit float"),
        "FLAC": process.flac_bit_depth.value,
        "MP3": process.mp3_bitrate.value.replace("k", " kbps"),
        "OPUS": process.opus_bitrate.value.replace("k", " kbps"),
    }.get(format_name, "")
    return " · ".join(value for value in (format_name, quality) if value)


# Explicit review fields: adding an application preference must never silently
# add it to the user-facing plan or clipboard export.
_BACKEND_FIELDS = {
    "vr": "aggression_setting window_size batch_size crop_size is_tta is_output_image "
    "is_post_process is_high_end_process post_process_threshold",
    "mdx": "segment_size overlap_mdx overlap_mdx23 is_chunk_mdxnet "
    "is_mdx23_combine_stems is_mdx_include_stem_complement chunks margin compensate "
    "is_denoise denoise_option phase_option phase_shifts is_save_align "
    "is_match_frequency_pitch is_match_silence is_spec_match is_mdx_c_seg_def "
    "is_invert_spec is_mixer_mode batch_size",
    "demucs": "segment overlap shifts is_split_mode is_demucs_combine_stems",
}


def _fields(section: object, names: str) -> dict[str, Any]:
    return {name: getattr(section, name) for name in names.split()}


def _technical_plan(plan: ResolvedJob) -> dict[str, Any]:
    """Review projection, deliberately separate from the replay/settings dump."""
    process = plan.settings.process
    processing = _fields(
        process,
        "autocast normalization match_mix_level prevent_export_clipping "
        "amplification_threshold semitone_shift sample_mode long_file_chunk_seconds "
        "vocal_splitter_enabled",
    )
    if process.sample_mode:
        processing["sample_mode_duration"] = process.sample_mode_duration
        starts = {item.path: sample_start(process.sample_starts, item.path) for item in plan.inputs}
        processing["sample_starts"] = {path: start for path, start in starts.items() if start > 0}
        lengths = {
            item.path: process.sample_lengths[os.path.abspath(item.path)]
            for item in plan.inputs
            if os.path.abspath(item.path) in process.sample_lengths
        }
        if lengths:
            processing["sample_lengths"] = lengths
    if process.long_file_chunk_seconds:
        processing["long_file_chunk_overlap_seconds"] = process.long_file_chunk_overlap_seconds
    if process.vocal_splitter_enabled:
        processing.update(
            _fields(process, "save_inst_vocal_splitter voc_split_save_opt deverb_vocals")
        )
        if process.deverb_vocals:
            processing["deverb_vocal_opt"] = process.deverb_vocal_opt
    families = {model.family for model in plan.models}
    families.update(record.family for record in plan.model_dependencies.values())
    for family in sorted(families & _BACKEND_FIELDS.keys()):
        processing[family] = _fields(getattr(plan.settings, family), _BACKEND_FIELDS[family])
    dependencies = {}
    for path, record in sorted(plan.model_dependencies.items()):
        entry: dict[str, Any] = {"id": record.id, "display": record.display}
        section_name, _, field = path.partition(".")
        if field.endswith("_secondary_model") and section_name in _BACKEND_FIELDS:
            entry["scale"] = getattr(getattr(plan.settings, section_name), field + "_scale")
        if path == "demucs.pre_proc_model":
            entry["instrumental_mix"] = plan.settings.demucs.is_pre_proc_model_inst_mix
        dependencies[path] = entry
    details = {
        "command": plan.command,
        "device": plan.device,
        "models": [
            {
                "id": model.id,
                "display": model.display,
                "family": model.family,
                "checkpoint": model.checkpoint,
            }
            for model in plan.models
        ],
        "dependencies": dependencies,
        "inputs": [
            {"path": item.path, "outputs": [asdict(output) for output in item.outputs]}
            for item in plan.inputs
        ],
        "output": {
            "directory": plan.output or process.export_path,
            "format": _format(plan.settings),
        },
        "processing": processing,
        "warnings": [
            diagnostic.message
            for diagnostic in plan.diagnostics
            if diagnostic.severity == "warning"
        ],
    }
    if plan.command == "ensemble":
        details["ensemble"] = _fields(
            plan.settings.ensemble,
            "type save_all_outputs append_ensemble_name wav_ensemble cleanup_temps derive_complement_from_mix",
        )
    return details


@dataclass(frozen=True)
class PlanReviewPresentation:
    heading: str
    file_summary: str
    stems: tuple[str, ...]
    conditional_stems: tuple[str, ...]
    format: str
    destination: str
    additional: str
    device: str
    sample: str
    processing: str
    warnings: tuple[str, ...]
    technical: str


def review_presentation(plan: ResolvedJob) -> PlanReviewPresentation:
    outputs = tuple(output for item in plan.inputs for output in item.outputs)
    conditional = sum(output.conditional for output in outputs)
    guaranteed = len(outputs) - conditional
    file_summary = f"{guaranteed} planned {'file' if guaranteed == 1 else 'files'}"
    if conditional:
        file_summary += (
            f" · up to {conditional} conditional {'file' if conditional == 1 else 'files'}"
        )
    stems = tuple(dict.fromkeys(output.stem for output in outputs if not output.conditional))
    optional = tuple(dict.fromkeys(output.stem for output in outputs if output.conditional))
    process = plan.settings.process
    additional = []
    if optional:
        additional.append("When produced: " + ", ".join(optional))
    if plan.command == "ensemble":
        if plan.settings.ensemble.save_all_outputs:
            additional.append(
                "Individual model outputs will also be saved; not included in the planned file count."
            )
        if process.vocal_splitter_enabled:
            additional.append(
                "Vocal splitting is enabled; any additional files are not included in the planned file count."
            )
    device = {
        "cpu": "CPU",
        "cuda": "NVIDIA GPU (CUDA)",
        "mps": "Apple GPU (Metal)",
        "auto": "Automatic device",
        "directml": "GPU (DirectML)",
    }.get(plan.device, plan.device)
    if plan.device.startswith("cuda:"):
        device = "NVIDIA GPU · " + plan.device
    elif plan.device.startswith("directml:"):
        device = "GPU · " + plan.device
    sample, sample_detail = _sample_summary(plan)
    if sample_detail is not None:
        additional.append(sample_detail)
    warnings = list(dict.fromkeys(d.message for d in plan.diagnostics if d.severity == "warning"))
    if process.sample_mode:
        lengths = set(_sample_lengths(plan))
        if len(lengths) <= 1:
            seconds = seconds_text(lengths.pop() if lengths else process.sample_mode_duration)
            warnings.append(f"Only a {seconds}-second sample of each input will be processed.")
        else:
            warnings.append("Only a sample of each input will be processed.")
    return PlanReviewPresentation(
        heading=f"{'Ensemble' if plan.command == 'ensemble' else 'Separate'} {_files(len(plan.inputs))}",
        file_summary=file_summary,
        stems=stems,
        conditional_stems=optional,
        format=_format(plan.settings),
        destination=plan.output or process.export_path,
        additional="\n".join(additional),
        device=device,
        sample=sample,
        processing=f"{device} · {sample}",
        warnings=tuple(warnings),
        technical=file_summary
        + "\n\n"
        + json.dumps(_technical_plan(plan), indent=2, ensure_ascii=False, default=str),
    )
