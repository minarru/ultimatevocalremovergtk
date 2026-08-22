"""Single- and ensemble-mode file-pass hooks for :func:`run_models_on_files`.

:class:`~core.job_runner.JobRunner` stays the thread/lifecycle owner and
supplies these hooks to the shared loop. This module must not import
``JobRunner`` (runtime cycle). :mod:`core.run_loop` must not import this
module.
"""

from __future__ import annotations

import os
import time
from typing import Any, List

from bundled.constants import PRIMARY_STEM, SECONDARY_STEM

from .audio_io import resolve_wav_type_set
from .debug_log import debug_elapsed
from .ensembler import (
    Ensembler,
    _ensemble_stem_bucket,
    _extract_stems,
    _filter_final_ensemble_stems,
)
from .model_config import ModelConfig
from .run_estimate import combine_progress_local_step
from .run_loop import FileState, _write_captured_stems
from .stems import coerce_ensemble_pair, exclusive_flags_for_pair


def _model_output_label(model: ModelConfig) -> str:
    """Return the user-facing model label for export paths and test mode."""
    return (
        str(getattr(model, "model_display_label", "") or "")
        or str(getattr(model, "model_name", "") or "")
        or str(getattr(model, "model_basename", "") or "")
    )


class _SingleRunHooks:
    """Single-method naming, stem concat, and export for :func:`run_models_on_files`."""

    process_kind = "separation"

    def __init__(self, export_path: str, amp_threshold: float) -> None:
        self.export_path = export_path
        self.amp_threshold = amp_threshold

    def before_file(self, runner: Any, state: FileState) -> None:
        return

    def export_and_base(
        self, runner: Any, state: FileState, model: Any
    ) -> tuple[str, str]:
        model_label = _model_output_label(model)
        naming = runner._naming_for_file(
            state.audio_file,
            export_path=self.export_path,
            file_index=state.file_num,
            file_total=state.total_files,
            model_label=model_label,
        )
        if naming.export_directory != self.export_path:
            os.makedirs(naming.export_directory, exist_ok=True)
        state.scratch["stem_parts"] = {}
        state.scratch["stem_paths"] = {}
        return naming.track_base, naming.export_directory

    def extra_process_data(
        self, runner: Any, state: FileState, model: Any
    ) -> dict:
        return {"is_ensemble_master": False, "is_4_stem_ensemble": False}

    def after_chunk(
        self,
        runner: Any,
        state: FileState,
        model: Any,
        stems: dict,
        paths: dict,
        chunked: bool,
    ) -> None:
        if not chunked:
            return
        parts = state.scratch["stem_parts"]
        stored_paths = state.scratch["stem_paths"]
        for stem_tag, arr in stems.items():
            parts.setdefault(stem_tag, []).append(arr)
            if stem_tag in paths:
                stored_paths[stem_tag] = paths[stem_tag]

    def after_model(self, runner: Any, state: FileState, model: Any) -> None:
        from core.audio_chunking import concat_stems

        parts = state.scratch.get("stem_parts") or {}
        if not (state.chunked and parts):
            return
        final_stems = {
            stem: concat_stems(chunk_parts, overlap_samples=state.ov_samples)
            for stem, chunk_parts in parts.items()
        }
        _write_captured_stems(
            final_stems,
            state.scratch["stem_paths"],
            is_normalization=bool(runner.settings.process.normalization),
            amplification_threshold=self.amp_threshold,
            wav_type_set=resolve_wav_type_set(runner.settings),
            save_format_name=runner.settings.process.save_format.value,
            mp3_bit_set=runner.settings.process.mp3_bitrate,
            flac_bit_set=runner.settings.process.flac_bit_depth,
        )

    def after_file(self, runner: Any, state: FileState) -> None:
        return


class _EnsembleRunHooks:
    """Ensemble member naming, salvage, and combine for :func:`run_models_on_files`."""

    process_kind = "ensemble"

    def __init__(self, ensemble: Ensembler, is_4_stem: bool) -> None:
        self.ensemble = ensemble
        self.export_path = ensemble.ensemble_folder_name
        self.is_4_stem = is_4_stem

    def before_file(self, runner: Any, state: FileState) -> None:
        state.scratch["ensemble_stem_arrays"] = {}
        runner._ensemble_salvage_members = []
        final_naming = runner._naming_for_file(
            state.audio_file,
            export_path=self.export_path,
            file_index=state.file_num,
            file_total=state.total_files,
            ensemble_label=self.ensemble.append_ensemble_label,
            force_ensemble_label=True,
        )
        state.scratch["ensemble_final_base"] = final_naming.track_base

    def export_and_base(
        self, runner: Any, state: FileState, model: Any
    ) -> tuple[str, str]:
        model_label = _model_output_label(model)
        state.callbacks.console(
            f"Ensemble Mode - {model_label} - "
            f"Model {state.progress_ctx['model_num']}/{state.model_count}\n"
        )
        member_naming = runner._ensemble_member_naming_for_file(
            state.audio_file,
            export_path=self.export_path,
            file_index=state.file_num,
            file_total=state.total_files,
            model_label=model_label,
        )
        state.scratch["member_stem_parts"] = {}
        state.scratch["member_paths"] = {}
        state.scratch["last_member_stems"] = {}
        state.scratch["audio_file_base"] = member_naming.track_base
        state.scratch["model_label"] = model_label
        return member_naming.track_base, self.export_path

    def extra_process_data(
        self, runner: Any, state: FileState, model: Any
    ) -> dict:
        return {
            "is_ensemble_master": True,
            "is_4_stem_ensemble": self.is_4_stem,
            "is_save_all_outputs_ensemble": bool(
                runner.settings.ensemble.save_all_outputs
            ),
        }

    def after_chunk(
        self,
        runner: Any,
        state: FileState,
        model: Any,
        stems: dict,
        paths: dict,
        chunked: bool,
    ) -> None:
        scratch = state.scratch
        scratch["last_member_stems"] = stems
        if chunked:
            for stem_tag, arr in stems.items():
                bucket = _ensemble_stem_bucket(stem_tag)
                scratch["member_stem_parts"].setdefault(bucket, []).append(arr)
                if stem_tag in paths:
                    scratch["member_paths"][bucket] = paths[stem_tag]
            return
        for stem_tag, arr in stems.items():
            bucket = _ensemble_stem_bucket(stem_tag)
            scratch["ensemble_stem_arrays"].setdefault(bucket, []).append(arr)
            if stem_tag in paths:
                scratch["member_paths"][bucket] = paths[stem_tag]

    def after_model(self, runner: Any, state: FileState, model: Any) -> None:
        from core.audio_chunking import concat_stems

        scratch = state.scratch
        salvage_arrays: dict = {}
        if state.chunked:
            for stem_tag, parts in scratch["member_stem_parts"].items():
                concat = concat_stems(parts, overlap_samples=state.ov_samples)
                scratch["ensemble_stem_arrays"].setdefault(
                    _ensemble_stem_bucket(stem_tag), []
                ).append(concat)
                salvage_arrays[_ensemble_stem_bucket(stem_tag)] = concat
        else:
            for stem_tag, arr in scratch["last_member_stems"].items():
                salvage_arrays[_ensemble_stem_bucket(stem_tag)] = arr
        runner._ensemble_salvage_members.append(
            {
                "arrays": salvage_arrays,
                "paths": scratch["member_paths"],
                "audio_file_base": scratch["audio_file_base"],
                "model_label": scratch["model_label"],
            }
        )
        state.callbacks.console("\n")

    def after_file(self, runner: Any, state: FileState) -> None:
        callbacks = state.callbacks
        callbacks.console(state.base_text + "Ensembling outputs...\n")
        combine_started = time.perf_counter()
        ensemble_stem_arrays = state.scratch["ensemble_stem_arrays"]
        ensemble_final_base = state.scratch["ensemble_final_base"]
        export_path = self.export_path
        combine_steps: List[tuple] = []
        if self.is_4_stem:
            stem_names = [
                name
                for name, arrs in ensemble_stem_arrays.items()
                if len(arrs) > 1
            ]
            if not stem_names:
                stem_names = _extract_stems(ensemble_final_base, export_path)
            stem_names = _filter_final_ensemble_stems(
                stem_names, str(runner.settings.process.stem_focus or "")
            )
            combine_steps = [
                (output_stem, {"is_4_stem": True}) for output_stem in stem_names
            ]
        else:
            focus_flags = exclusive_flags_for_pair(
                str(runner.settings.process.stem_focus or ""),
                coerce_ensemble_pair(runner.settings.ensemble.main_stem),
            )
            primary_only, secondary_only = focus_flags or (False, False)
            if not secondary_only:
                combine_steps.append((PRIMARY_STEM, {}))
            if not primary_only:
                combine_steps.append((SECONDARY_STEM, {}))
                combine_steps.append((SECONDARY_STEM, {"is_inst_mix": True}))

        combine_total = max(1, len(combine_steps))
        combine_start = state.progress_sink.fraction
        combine_end = state.file_num / max(1, state.total_files)
        for combine_idx, (stem_name, kwargs) in enumerate(combine_steps):
            self.ensemble.ensemble_outputs(
                ensemble_final_base,
                export_path,
                stem_name,
                stem_arrays=ensemble_stem_arrays,
                **kwargs,
            )
            span = max(combine_end - combine_start, 0.0)
            fraction = combine_start + span * ((combine_idx + 1) / combine_total)
            local_step = combine_progress_local_step(combine_idx, combine_total)
            state.progress_sink.fraction = fraction
            total_count = max(1, runner.true_model_count * state.total_files)
            callbacks.progress(
                fraction,
                local_step=local_step,
                pass_index=total_count,
                pass_total=total_count,
                combine_index=combine_idx + 1,
                combine_total=combine_total,
                detail=f"Combining {combine_idx + 1}/{combine_total}",
            )

        debug_elapsed("worker", "ensemble combine", combine_started)
        callbacks.console("Done\n")
