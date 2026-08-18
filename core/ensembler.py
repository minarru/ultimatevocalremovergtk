"""Ensemble output combination, independent of job-thread lifecycle.

:class:`Ensembler` is a Tk-free port of ``UVR.py``'s combiner: it reads
:class:`~core.settings.Settings`, writes member stems into a scratch or
export folder, then combines them per stem. Construction is torch-free;
``spec_utils`` is imported only inside :meth:`Ensembler.ensemble_outputs`.

Member files are collected by filename — ``{base} {model} ({stem}).wav`` —
so export naming and this module must change together.
"""

from __future__ import annotations

import os
import re
import time
import typing
from collections import Counter
from typing import List, Sequence

from bundled.constants import INST_STEM, MAX_SPEC, PRIMARY_STEM

from . import paths
from .audio_io import resolve_wav_type_set
from .debug_log import debug
from .export_naming import format_stem_basename, sanitize_filename_component
from .settings import Settings
from .stems import StemBucket, canonical_ensemble_stem_tag, coerce_ensemble_pair, filename_tag


def _ensemble_stem_bucket(stem_tag: str) -> str:
    """Canonical key for multi-stem ensemble combine buckets.

    Member maps are already keyed by :func:`export_stem_label` in ensemble
    mode; this is a no-op for those tags and only folds leftover casing.
    """
    return canonical_ensemble_stem_tag(stem_tag)


def _filter_final_ensemble_stems(
    stem_names: Sequence[str], focus: str
) -> list[str]:
    """Apply one focus to final four/multi-stem outputs only."""
    if not str(focus or "").strip():
        return list(stem_names)
    from core.stems import (
        StemLiteral,
        derived_stem_route,
        focus_bucket,
        select_stem_routes,
    )

    routes = []
    for name in stem_names:
        bucket = focus_bucket(str(name))
        concept = bucket if bucket is not StemBucket.UNKNOWN else StemLiteral(str(name))
        routes.append(
            derived_stem_route(
                concept,
                label=str(name),
                tag=_ensemble_stem_bucket(str(name)),
                selected_by_default=True,
            )
        )
    selection = select_stem_routes(routes, focus)
    if not selection.routes:
        return list(stem_names)
    allowed = {route.filename_tag.casefold() for route in selection.routes}
    return [
        name for name in stem_names
        if _ensemble_stem_bucket(str(name)).casefold() in allowed
    ]


def _capture_separator_stem_arrays(seperator: typing.Any) -> dict:
    """Copy stem waveforms buffered by an ensemble member before release.

    Stem tags are passed through :func:`canonical_ensemble_stem_tag` so yaml
    lowercase labels and Demucs Title Case share one combine bucket.
    """
    buffers = getattr(seperator, "_ensemble_stem_buffers", None) or {}
    if not buffers:
        return {}
    import numpy as np

    captured: dict = {}
    for name, arr in buffers.items():
        key = canonical_ensemble_stem_tag(name)
        if key in captured and key != name:
            debug(
                "worker",
                f"ensemble stem tag collision merging {name!r} into {key!r}",
            )
        captured[key] = np.array(arr, copy=True)
    return captured


def _capture_separator_stem_paths(seperator: typing.Any) -> dict:
    """Copy deferred stem export paths buffered alongside stem arrays."""
    paths = getattr(seperator, "_ensemble_stem_paths", None) or {}
    return {
        canonical_ensemble_stem_tag(name): path for name, path in paths.items()
    }


def _extract_stems(audio_file_base: str, export_path: str) -> List[str]:
    """Tk-free copy of ``UVR.extract_stems``.

    Finds the stem tags (the ``(...)`` suffix) shared by more than one of the
    per-member output files, i.e. the stems that actually have something to
    ensemble for a 4-/multi-stem run. Tags are canonicalized so ``vocals`` and
    ``Vocals`` count toward the same stem.
    """
    if not os.path.isdir(export_path):
        return []
    filenames = [name for name in os.listdir(export_path) if name.startswith(audio_file_base)]
    pattern = r"\(([^()]+)\)(?=[^()]*\.wav)"
    stem_list = []
    for filename in filenames:
        match = re.search(pattern, filename)
        if match:
            stem_list.append(canonical_ensemble_stem_tag(match.group(1)))
    counter = Counter(stem_list)
    return list({item for item in stem_list if counter[item] > 1})


class Ensembler:
    """Tk-free port of ``UVR.py``'s ``Ensembler`` (output combination only).

    Reads its configuration from :class:`~core.settings.Settings` rather than Tk
    root window, and lazily imports the heavy ``spec_utils`` / ``separate``
    helpers only when actually combining audio, keeping construction torch-free.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.is_save_all_outputs_ensemble = settings.ensemble.save_all_outputs

        from core.export_naming import ensemble_name_for_export

        chosen_ensemble_name = ensemble_name_for_export(settings.ensemble.chosen_ensemble)
        from core.ensemble_algorithms import parse_ensemble_type

        ensemble_type_value = settings.ensemble.type
        primary_algorithm, secondary_algorithm = parse_ensemble_type(ensemble_type_value)
        pair = coerce_ensemble_pair(settings.ensemble.main_stem)
        primary_bucket, secondary_bucket = pair.buckets()
        primary_ui, secondary_ui = pair.stem_halves()
        # Combine/search tags must match export_stem_label buckets (e.g.
        # Lead_Vocals), not UI pair halves (Lead Vocals).
        self.ensemble_primary_stem = (
            filename_tag(primary_bucket)
            if primary_bucket is not StemBucket.UNKNOWN
            else canonical_ensemble_stem_tag(primary_ui)
        )
        self.ensemble_secondary_stem = (
            filename_tag(secondary_bucket)
            if secondary_bucket is not StemBucket.UNKNOWN
            else canonical_ensemble_stem_tag(secondary_ui)
        )
        time_stamp = round(time.time())

        self.main_export_path = settings.process.export_path
        self.append_ensemble_label = (
            chosen_ensemble_name if settings.ensemble.append_ensemble_name else None
        )
        ensemble_folder_root = self.main_export_path if self.is_save_all_outputs_ensemble else paths.ENSEMBLE_TEMP_PATH
        folder_label = sanitize_filename_component(chosen_ensemble_name.replace(" ", "_")) or "Ensembled"
        self.ensemble_folder_name = os.path.join(ensemble_folder_root, f"{folder_label}_Outputs_{time_stamp}")
        # Dual-stem: Primary/Secondary pair. 4-stem uses the full token in ensemble_outputs.
        self.primary_algorithm = primary_algorithm
        self.secondary_algorithm = secondary_algorithm
        self.is_normalization = settings.process.normalization
        try:
            self.amplification_threshold = float(
                settings.process.amplification_threshold or 0.0
            )
        except (TypeError, ValueError):
            self.amplification_threshold = 0.0
        self.is_wav_ensemble = settings.ensemble.wav_ensemble
        self.wav_type_set = resolve_wav_type_set(settings)
        self.mp3_bit_set = settings.process.mp3_bitrate
        self.flac_bit_set = settings.process.flac_bit_depth
        self.save_format = settings.process.save_format.value
        os.makedirs(self.ensemble_folder_name, exist_ok=True)

    def ensemble_outputs(
        self,
        audio_file_base: typing.Any,
        export_path: typing.Any,
        stem: typing.Any,
        is_4_stem: typing.Any=False,
        is_inst_mix: typing.Any=False,
        stem_arrays: typing.Any=None,
    ):
        """Combine the per-member outputs for ``stem`` with the chosen algorithm.

        Prefer in-memory member waveforms from ``stem_arrays`` when present
        (ensemble scratch path); otherwise fall back to disk ``.wav`` members.
        """
        debug("worker", f"ensemble_outputs stem={stem!r} is_4_stem={is_4_stem} is_inst_mix={is_inst_mix}")
        from ml import spec_utils
        from engines.separate import save_format as _save_format

        if is_4_stem:
            # Single-token algorithm (no slash); never use an empty secondary partition.
            raw_type = self.settings.ensemble.type
            algorithm = raw_type.partition("/")[0].strip() or MAX_SPEC
            stem_tag = canonical_ensemble_stem_tag(stem)
        elif is_inst_mix:
            algorithm = self.secondary_algorithm
            stem_tag = f"{self.ensemble_secondary_stem} {INST_STEM}"
        else:
            algorithm = self.primary_algorithm if stem == PRIMARY_STEM else self.secondary_algorithm
            stem_tag = (
                canonical_ensemble_stem_tag(self.ensemble_primary_stem)
                if stem == PRIMARY_STEM
                else canonical_ensemble_stem_tag(self.ensemble_secondary_stem)
            )

        array_inputs = list((stem_arrays or {}).get(stem_tag, []))
        if not array_inputs and stem_arrays:
            # Belt-and-suspenders for mixed casing left in older in-memory maps.
            for key, values in stem_arrays.items():
                if canonical_ensemble_stem_tag(key) == stem_tag:
                    array_inputs.extend(values)
        stem_suffix = f" ({sanitize_filename_component(stem_tag)}).wav"
        # Member files are ``{final_base} {model} ({stem}).wav``; match by track prefix.
        match_prefix = audio_file_base
        if self.append_ensemble_label and match_prefix.endswith(f" {self.append_ensemble_label}"):
            match_prefix = match_prefix[: -(len(self.append_ensemble_label) + 1)]
        stem_outputs = self.get_files_to_ensemble(
            folder=export_path, prefix=match_prefix, suffix=stem_suffix
        )
        if len(stem_outputs) <= 1:
            # Disk fallback: member files may still use yaml lowercase tags.
            stem_outputs = self.get_files_to_ensemble_for_stem(
                folder=export_path, prefix=match_prefix, stem_tag=stem_tag
            )
        audio_file_output = format_stem_basename(audio_file_base, stem_tag)
        stem_save_path = os.path.join(f"{self.main_export_path}", f"{audio_file_output}.wav")

        if len(array_inputs) > 1:
            spec_utils.ensemble_inputs(
                array_inputs,
                algorithm,
                self.is_normalization,
                self.wav_type_set,
                stem_save_path,
                is_wave=self.is_wav_ensemble,
                is_array=True,
                min_peak=self.amplification_threshold,
            )
            _save_format(stem_save_path, self.save_format, self.mp3_bit_set, self.flac_bit_set)
        elif len(stem_outputs) > 1:
            spec_utils.ensemble_inputs(
                stem_outputs,
                algorithm,
                self.is_normalization,
                self.wav_type_set,
                stem_save_path,
                is_wave=self.is_wav_ensemble,
                min_peak=self.amplification_threshold,
            )
            _save_format(stem_save_path, self.save_format, self.mp3_bit_set, self.flac_bit_set)

        if self.is_save_all_outputs_ensemble:
            for stem_output in stem_outputs:
                _save_format(stem_output, self.save_format, self.mp3_bit_set, self.flac_bit_set)
        else:
            for stem_output in stem_outputs:
                try:
                    os.remove(stem_output)
                except OSError:
                    pass

    def get_files_to_ensemble(self, folder: typing.Any="", prefix: typing.Any="", suffix: typing.Any=""):
        """Grab all the per-member output files to be ensembled for one stem."""
        if not os.path.isdir(folder):
            return []
        return [
            os.path.join(folder, name)
            for name in os.listdir(folder)
            if name.startswith(prefix) and name.endswith(suffix)
        ]

    def get_files_to_ensemble_for_stem(self, folder: typing.Any="", prefix: typing.Any="", stem_tag: typing.Any=""):
        """Like :meth:`get_files_to_ensemble`, but match stem tags case-insensitively.

        Used when member files were written with yaml lowercase ``(vocals)``
        while the combine step looks for canonical ``(Vocals)``.
        """
        if not os.path.isdir(folder) or not stem_tag:
            return []
        wanted = canonical_ensemble_stem_tag(stem_tag).casefold()
        pattern = re.compile(r"\(([^()]+)\)\.(?:wav|flac|mp3)$", re.IGNORECASE)
        matches = []
        for name in os.listdir(folder):
            if not name.startswith(prefix):
                continue
            match = pattern.search(name)
            if not match:
                continue
            if canonical_ensemble_stem_tag(match.group(1)).casefold() == wanted:
                matches.append(os.path.join(folder, name))
        return matches


__all__ = ["Ensembler"]
