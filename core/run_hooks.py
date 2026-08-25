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

from .audio_io import resolve_wav_type_set
from .debug_log import debug_elapsed
from .ensembler import (
    Ensembler,
    planned_ensemble_stems,
)
from .model_config import ModelConfig
from .run_estimate import combine_progress_local_step
from .run_loop import FileState, _write_captured_stems
from .stems import StemRoute, StemRouteKind, select_stem_routes


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

    def export_and_base(self, runner: Any, state: FileState, model: Any) -> tuple[str, str]:
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

    def extra_process_data(self, runner: Any, state: FileState, model: Any) -> dict:
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

    def __init__(self, ensemble: Ensembler, is_multi_stem: bool) -> None:
        self.ensemble = ensemble
        self.export_path = ensemble.ensemble_folder_name
        self.is_multi_stem = is_multi_stem

    def before_file(self, runner: Any, state: FileState) -> None:
        state.scratch["ensemble_stem_arrays"] = {}
        state.scratch["ensemble_stems"] = {}
        state.scratch["ensemble_contributors"] = {}
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

    def export_and_base(self, runner: Any, state: FileState, model: Any) -> tuple[str, str]:
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

    def extra_process_data(self, runner: Any, state: FileState, model: Any) -> dict:
        return {
            "is_ensemble_master": True,
            "is_4_stem_ensemble": self.is_multi_stem,
            "is_save_all_outputs_ensemble": bool(runner.settings.ensemble.save_all_outputs),
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
        planned = planned_ensemble_stems(model)
        member_id = str(
            getattr(model, "canonical_id", "")
            or getattr(model, "model_and_process_tag", "")
            or id(model)
        )
        for collected in planned.values():
            scratch["ensemble_stems"][collected.group_key] = collected
            scratch["ensemble_contributors"].setdefault(collected.group_key, set()).add(member_id)

        def collect(tag: str, value: Any) -> None:
            collected = planned.get(tag)
            if collected is None:
                return
            scratch["ensemble_stem_arrays"].setdefault(collected.group_key, []).append(value)
            if tag in paths:
                scratch["member_paths"][collected.group_key] = paths[tag]

        if chunked:
            for stem_tag, arr in stems.items():
                collected = planned.get(stem_tag)
                if collected is not None:
                    scratch["member_stem_parts"].setdefault(collected, []).append(arr)
                    if stem_tag in paths:
                        scratch["member_paths"][collected.group_key] = paths[stem_tag]
            return
        for stem_tag, arr in stems.items():
            collect(stem_tag, arr)

    def after_model(self, runner: Any, state: FileState, model: Any) -> None:
        from core.audio_chunking import concat_stems

        scratch = state.scratch
        salvage_arrays: dict = {}
        if state.chunked:
            for collected, parts in scratch["member_stem_parts"].items():
                concat = concat_stems(parts, overlap_samples=state.ov_samples)
                scratch["ensemble_stem_arrays"].setdefault(collected.group_key, []).append(concat)
                salvage_arrays[collected.group_key] = concat
        else:
            for tag, arr in scratch["last_member_stems"].items():
                collected = planned_ensemble_stems(model).get(tag)
                if collected is not None:
                    salvage_arrays[collected.group_key] = arr
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
        if self.is_multi_stem:
            contributors = state.scratch["ensemble_contributors"]
            collected_stems = state.scratch["ensemble_stems"]
            output_stems = [
                collected
                for key, collected in collected_stems.items()
                if len(contributors.get(key, ())) >= 2
            ]
            focus = str(runner.settings.process.stem_focus or "")
            if focus:
                routes = tuple(
                    StemRoute(
                        native=None,
                        role=collected.role,
                        label=collected.filename_tag,
                        filename_tag=collected.filename_tag,
                        kind=StemRouteKind.DERIVED,
                        selected_by_default=True,
                    )
                    for collected in output_stems
                )
                selection = select_stem_routes(routes, focus)
                if selection.routes:
                    allowed = {route.role for route in selection.routes}
                    output_stems = [
                        collected for collected in output_stems if collected.role in allowed
                    ]
            combine_steps = [(collected, {}) for collected in output_stems]
        else:
            pair_stems = list(self.ensemble.pair_stems)
            focus = str(runner.settings.process.stem_focus or "")
            if focus:
                routes = tuple(
                    StemRoute(
                        native=None,
                        role=collected.role,
                        label=collected.filename_tag,
                        filename_tag=collected.filename_tag,
                        kind=StemRouteKind.DERIVED,
                        selected_by_default=True,
                    )
                    for collected in pair_stems
                )
                selection = select_stem_routes(routes, focus)
                if selection.routes:
                    allowed = {route.role for route in selection.routes}
                    pair_stems = [
                        collected for collected in pair_stems if collected.role in allowed
                    ]
            combine_steps = [(collected, {}) for collected in pair_stems]

        combine_total = max(1, len(combine_steps))
        combine_start = state.progress_sink.fraction
        combine_end = state.file_num / max(1, state.total_files)
        for combine_idx, (stem_name, kwargs) in enumerate(combine_steps):
            self.ensemble.ensemble_outputs(
                ensemble_final_base,
                export_path,
                stem_name,
                stem_arrays=ensemble_stem_arrays,
                is_multi_stem=self.is_multi_stem,
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
