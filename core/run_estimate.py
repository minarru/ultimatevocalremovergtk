"""Pre-run workload hints and live separation ETA tracking."""

from __future__ import annotations
import typing

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Tuple

from bundled.constants import (
    ALL_STEMS,
    CHOOSE_STEM_PAIR,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    FOUR_STEM_ENSEMBLE,
    MDX_ARCH_TYPE,
    MULTI_STEM_ENSEMBLE,
    NO_MODEL,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)

if TYPE_CHECKING:
    from .settings import Settings

_MODEL_KEY_BY_METHOD = {
    VR_ARCH_PM: "vr_model",
    VR_ARCH_TYPE: "vr_model",
    MDX_ARCH_TYPE: "mdx_net_model",
    DEMUCS_ARCH_TYPE: "demucs_model",
}

_SECONDARY_ACTIVATE_KEY = {
    VR_ARCH_PM: "vr_is_secondary_model_activate",
    VR_ARCH_TYPE: "vr_is_secondary_model_activate",
    MDX_ARCH_TYPE: "mdx_is_secondary_model_activate",
    DEMUCS_ARCH_TYPE: "demucs_is_secondary_model_activate",
}

# Engine progress mapping (see engines/base.py).
_LOAD_END = 0.10
_SAVE_START = 0.92
_INFER_SPAN = _SAVE_START - _LOAD_END

# Per-model local step ranges passed through JobCallbacks.progress.
_LOCAL_LOAD_END = 0.10
_LOCAL_SAVE_START = 0.90
_LOCAL_COMBINE_START = 0.97
_LOCAL_SAVE_END = 0.96

# Live ETA tuning.
_MIN_INFER_FRAC_FOR_ETA = 0.08
_MIN_INFER_ELAPSED_FOR_ETA = 20.0
_ETA_EMA_ALPHA = 0.35
_MAX_SAMPLES = 8
_SAMPLE_WINDOW_SEC = 15.0


class RunCostTier(str, Enum):
    FASTEST = "Fastest"
    TYPICAL = "Typical"
    SLOWER = "Slower"


@dataclass(frozen=True)
class WorkloadEstimate:
    inference_passes: int
    output_count: int
    uses_gpu: bool
    sample_mode: bool
    sample_seconds: int
    export_tier: RunCostTier
    run_tier: Optional[RunCostTier] = None
    hints: Tuple[str, ...] = ()

    def format_summary(self) -> str:
        """Structural workload line (passes, outputs, device, tier) — no cost factors."""
        if self.inference_passes <= 0 or self.output_count <= 0:
            return ""
        parts = [
            f"{self.inference_passes} pass" + ("es" if self.inference_passes != 1 else ""),
            f"{self.output_count} output" + ("s" if self.output_count != 1 else ""),
            "GPU" if self.uses_gpu else "CPU",
        ]
        if self.sample_mode:
            parts.append(f"Sample {self.sample_seconds}s")
        tier = self._tier_label()
        if tier:
            parts.append(tier)
        return " · ".join(parts)

    def format_cost_factors(self) -> str:
        """Readable incremental cost factors for tooltips, or empty."""
        if not self.hints:
            return ""
        return " · ".join(self.hints)

    def _tier_label(self) -> str:
        if self.run_tier and self.run_tier != self.export_tier:
            return f"{self.export_tier.value} export · {self.run_tier.value} run"
        return self.export_tier.value


def _pitch_change_active(settings: Settings) -> bool:
    try:
        return float(settings.process.semitone_shift or 0) != 0.0
    except (TypeError, ValueError):
        return False


def _mdx_overlap_value(settings: Settings) -> int:
    try:
        return int(float(settings.mdx.overlap_mdx23 or 0))
    except (TypeError, ValueError):
        return 0


def _demucs_shifts_value(settings: Settings) -> int:
    try:
        return int(settings.demucs.shifts or 0)
    except (TypeError, ValueError):
        return 0


def _denoise_active(settings: Settings) -> bool:
    denoise = settings.mdx.denoise_option
    return denoise not in (None, "", "None", "none")


def _vocal_splitter_active(settings: Settings) -> bool:
    return bool(settings.process.vocal_splitter_enabled) and (
        settings.process.vocal_splitter not in (None, NO_MODEL, "")
    )


def cost_factor_hints(settings: typing.Any, method_key: str) -> Tuple[str, ...]:
    """Return readable labels for settings that add cost beyond pass/output counts.

    Pre-process is omitted (already counted as +2 passes). Ensemble uses the
    union of global VR / MDX / Demucs heavy settings.
    """
    hints: List[str] = []
    include_vr = method_key in (VR_ARCH_TYPE, VR_ARCH_PM, ENSEMBLE_MODE)
    include_mdx = method_key in (MDX_ARCH_TYPE, ENSEMBLE_MODE)
    include_demucs = method_key in (DEMUCS_ARCH_TYPE, ENSEMBLE_MODE)

    if include_vr and settings.vr.is_tta:
        hints.append("TTA")
    if include_mdx:
        overlap = _mdx_overlap_value(settings)
        if overlap >= 8:
            hints.append(f"Overlap {overlap}")
        if settings.mdx.is_match_frequency_pitch and _pitch_change_active(settings):
            hints.append("Match frequency")
        if _denoise_active(settings):
            hints.append("Denoise")
    if include_demucs:
        shifts = _demucs_shifts_value(settings)
        if shifts > 1:
            hints.append(f"Shifts {shifts}")
    return tuple(hints)


# Back-compat alias for older imports/tests.
slow_setting_hints = cost_factor_hints


def classify_export_tier(output_count: int) -> RunCostTier:
    if output_count <= 1:
        return RunCostTier.FASTEST
    if output_count == 2:
        return RunCostTier.TYPICAL
    return RunCostTier.SLOWER


def classify_run_tier(run_units: int) -> Optional[RunCostTier]:
    """Classify run heaviness from cost units (passes + heavy-setting extras)."""
    if run_units <= 1:
        return None
    if run_units == 2:
        return RunCostTier.TYPICAL
    return RunCostTier.SLOWER


def compute_run_cost_units(settings: typing.Any, method_key: str, inference_passes: int) -> int:
    """Score relative run cost from passes plus heavy settings multipliers."""
    units = max(0, int(inference_passes))
    include_vr = method_key in (VR_ARCH_TYPE, VR_ARCH_PM, ENSEMBLE_MODE)
    include_mdx = method_key in (MDX_ARCH_TYPE, ENSEMBLE_MODE)
    include_demucs = method_key in (DEMUCS_ARCH_TYPE, ENSEMBLE_MODE)

    if include_vr and settings.vr.is_tta:
        units += inference_passes
    if include_demucs:
        shifts = _demucs_shifts_value(settings)
        if shifts > 1:
            units += shifts - 1
    if include_mdx:
        units += max(0, _mdx_overlap_value(settings) - 7) // 8
        if _denoise_active(settings):
            units += 1
    return units


def count_inference_passes_from_models(models: Sequence[Any]) -> int:
    """Canonical inference-pass count for an assembled model list (JobRunner + UI)."""
    if not models:
        return 0
    true_model_4_stem_count = sum(
        getattr(m, "demucs_4_stem_added_count", 0)
        if getattr(m, "process_method", None) == DEMUCS_ARCH_TYPE
        else 0
        for m in models
    )
    true_model_pre_proc_model_count = sum(
        2 if getattr(m, "pre_proc_model_activated", False) else 0 for m in models
    )
    base = sum(2 if getattr(m, "is_secondary_model_activated", False) else 1 for m in models)
    voc_split = (
        1
        if any(getattr(m, "is_vocal_split_model_activated", False) for m in models)
        else 0
    )
    return base + true_model_4_stem_count + true_model_pre_proc_model_count + voc_split


def count_inference_passes(
    settings: typing.Any,
    *,
    method_key: str,
    repo: typing.Any=None,
    model_name: Optional[str] = None,
) -> int:
    """Return expected inference passes for the current method settings."""
    if method_key == ENSEMBLE_MODE:
        if repo is not None:
            from .model_config import assemble_model

            try:
                models = assemble_model(settings, repo, arch_type=ENSEMBLE_MODE)
                if models:
                    return count_inference_passes_from_models(models)
            except (ValueError, NotImplementedError):
                pass
        selected = settings.ensemble.selected_models or []
        return max(1, len(selected))

    if repo is not None and model_name and model_name not in (None, NO_MODEL, ""):
        from .model_config import assemble_model

        try:
            models = assemble_model(settings, repo, model_name, method_key)
            valid = [m for m in models if getattr(m, "model_status", False)]
            if valid:
                return count_inference_passes_from_models(valid)
        except (ValueError, NotImplementedError):
            pass

    # Fallback may over-count unresolved secondaries / pre-proc / voc-split.
    return _count_inference_passes_light(settings, method_key)


def _count_inference_passes_light(settings: typing.Any, method_key: str) -> int:
    passes = 1
    secondary_active = {
        VR_ARCH_PM: settings.vr.is_secondary_model_activate,
        VR_ARCH_TYPE: settings.vr.is_secondary_model_activate,
        MDX_ARCH_TYPE: settings.mdx.is_secondary_model_activate,
        DEMUCS_ARCH_TYPE: settings.demucs.is_secondary_model_activate,
    }.get(method_key, False)
    if secondary_active:
        passes += 1
    if _vocal_splitter_active(settings):
        passes += 1
    if (
        method_key == DEMUCS_ARCH_TYPE
        and settings.demucs.is_pre_proc_model_activate
    ):
        passes += 2
    return passes


def _multi_stem_base_outputs(settings: typing.Any, repo: typing.Any=None) -> int:
    """Stem file count for Multi-stem Ensemble (at least 4)."""
    if repo is None:
        return 4
    from .model_config import assemble_model

    try:
        models = assemble_model(settings, repo, arch_type=ENSEMBLE_MODE)
    except (ValueError, NotImplementedError):
        return 4
    for model in models:
        for attr in ("mdx_stem_count", "demucs_stem_count"):
            count = int(getattr(model, attr, 0) or 0)
            if count >= 4:
                return count
        stems = getattr(model, "mdx_model_stems", None) or []
        if len(stems) >= 4:
            return len(stems)
    return 4


def ensemble_export_summary(settings: typing.Any, repo: typing.Any=None) -> str:
    """Short export line for ensemble modes without dual-stem Save stems toggles."""
    main = settings.ensemble.main_stem
    if main == FOUR_STEM_ENSEMBLE:
        label = "4 stem outputs"
    elif main == MULTI_STEM_ENSEMBLE:
        count = _multi_stem_base_outputs(settings, repo)
        label = f"{count} stem outputs"
    else:
        return ""
    if settings.ensemble.save_all_outputs:
        members = len(settings.ensemble.selected_models or [])
        if members:
            label = f"{label} + {members} member file" + ("s" if members != 1 else "")
    return label


def count_expected_outputs(
    save_stems: typing.Any=None,
    *,
    settings: typing.Any=None,
    method_key: Optional[str] = None,
    repo: typing.Any=None,
    output_count: Optional[int] = None,
) -> int:
    """Expected on-disk files for the current Save stems / ensemble configuration."""
    if output_count is not None:
        return max(0, int(output_count))

    base = 0
    if method_key == ENSEMBLE_MODE and settings is not None:
        main = settings.ensemble.main_stem
        if main == FOUR_STEM_ENSEMBLE:
            base = 4
        elif main == MULTI_STEM_ENSEMBLE:
            base = _multi_stem_base_outputs(settings, repo)
        elif save_stems is not None and getattr(save_stems, "mode", None) != "hidden":
            base = int(save_stems.expected_output_count())
        if settings.ensemble.save_all_outputs:
            base += len(settings.ensemble.selected_models or [])
        return base

    if save_stems is not None:
        base = int(save_stems.expected_output_count())
    if (
        settings is not None
        and _vocal_splitter_active(settings)
        and settings.process.save_inst_vocal_splitter
    ):
        base += 2
    return base


def estimate_workload(
    settings: typing.Any,
    *,
    method_key: str,
    save_stems: typing.Any=None,
    repo: typing.Any=None,
    model_name: Optional[str] = None,
    has_model: bool = True,
    output_count: Optional[int] = None,
) -> Optional[WorkloadEstimate]:
    if not has_model:
        return None
    if (
        output_count is None
        and save_stems is not None
        and getattr(save_stems, "mode", None) == "hidden"
        and method_key != ENSEMBLE_MODE
    ):
        return None
    counted = count_expected_outputs(
        save_stems,
        settings=settings,
        method_key=method_key,
        repo=repo,
        output_count=output_count,
    )
    if counted <= 0:
        return None
    inference_passes = count_inference_passes(
        settings,
        method_key=method_key,
        repo=repo,
        model_name=model_name,
    )
    if inference_passes <= 0:
        inference_passes = 1
    run_units = compute_run_cost_units(settings, method_key, inference_passes)
    return WorkloadEstimate(
        inference_passes=inference_passes,
        output_count=counted,
        uses_gpu=bool(settings.process.use_gpu),
        sample_mode=bool(settings.process.sample_mode),
        sample_seconds=int(settings.process.sample_mode_duration or 30),
        export_tier=classify_export_tier(counted),
        run_tier=classify_run_tier(run_units),
        hints=cost_factor_hints(settings, method_key),
    )


def format_workload_line(estimate: Optional[WorkloadEstimate]) -> str:
    if estimate is None:
        return ""
    return estimate.format_summary()


def format_workload_tooltip_section(
    estimate: Optional[WorkloadEstimate],
    *,
    base_hint: str,
) -> str:
    """Append cost factors to ``base_hint`` when the estimate has any."""
    base = (base_hint or "").rstrip()
    if estimate is None:
        return base
    factors = estimate.format_cost_factors()
    if not factors:
        return base
    if not base:
        return f"Cost factors: {factors}"
    return f"{base}\n\nCost factors: {factors}"


def compose_stem_group_tooltip(
    export_hint: str,
    estimate: Optional[WorkloadEstimate],
    *,
    workload_hint: str,
) -> str:
    """Combine stem-export help with the relative workload tooltip section."""
    export = (export_hint or "").rstrip()
    workload = format_workload_tooltip_section(estimate, base_hint=workload_hint)
    if not export:
        return workload
    if not workload:
        return export
    return f"{export}\n\n{workload}"


def save_progress_local_step(index: int, total: int) -> float:
    """Local step for per-stem save substeps."""
    total = max(1, total)
    return _LOCAL_SAVE_START + (_LOCAL_SAVE_END - _LOCAL_SAVE_START) * (index / total)


def combine_progress_local_step(index: int, total: int) -> float:
    """Local step for ensemble combine substeps (maps to the Combining phase)."""
    total = max(1, total)
    return _LOCAL_COMBINE_START + (1.0 - _LOCAL_COMBINE_START) * ((index + 1) / total)


def _format_mmss(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


def _infer_fraction(fraction: float) -> float:
    if fraction < _LOAD_END:
        return 0.0
    if fraction >= _SAVE_START:
        return 1.0
    return (fraction - _LOAD_END) / _INFER_SPAN


_LOCAL_INFER_SPAN = _LOCAL_SAVE_START - _LOCAL_LOAD_END


def _local_infer_progress(local_step: Optional[float]) -> float:
    if local_step is None:
        return 0.0
    return max(0.0, min(1.0, (local_step - _LOCAL_LOAD_END) / _LOCAL_INFER_SPAN))


@dataclass
class ProgressEtaTracker:
    """Phase-aware live ETA for separation progress callbacks.

    Load / save / combine are indeterminate for the bar. The determinate bar and
    ETA only track inference; the inference clock pauses outside that phase.
    """

    _samples: List[Tuple[float, float]] = field(default_factory=list)
    _smoothed_remaining: Optional[float] = None
    _local_step: Optional[float] = None
    _pass_index: Optional[int] = None
    _pass_total: Optional[int] = None
    _detail: Optional[str] = None
    _combine_index: Optional[int] = None
    _combine_total: Optional[int] = None
    _held_display: float = 0.0
    _pass_durations: List[float] = field(default_factory=list)
    _combine_durations: List[float] = field(default_factory=list)
    _current_pass_infer_acc: float = 0.0
    _infer_slice_started: Optional[float] = None
    _combine_step_started: Optional[float] = None
    _last_combine_index: Optional[int] = None
    _infer_elapsed_total: float = 0.0

    def reset(self) -> None:
        self._samples.clear()
        self._smoothed_remaining = None
        self._local_step = None
        self._pass_index = None
        self._pass_total = None
        self._detail = None
        self._combine_index = None
        self._combine_total = None
        self._held_display = 0.0
        self._pass_durations.clear()
        self._combine_durations.clear()
        self._current_pass_infer_acc = 0.0
        self._infer_slice_started = None
        self._combine_step_started = None
        self._last_combine_index = None
        self._infer_elapsed_total = 0.0

    @property
    def held_display(self) -> float:
        return self._held_display

    def update(
        self,
        fraction: float,
        now: float,
        *,
        local_step: Optional[float] = None,
        pass_index: Optional[int] = None,
        pass_total: Optional[int] = None,
        detail: Optional[str] = None,
        combine_index: Optional[int] = None,
        combine_total: Optional[int] = None,
    ) -> None:
        fraction = max(0.0, min(1.0, fraction))
        if detail is not None:
            self._detail = detail or None
        if pass_total is not None and pass_total > 0:
            self._pass_total = int(pass_total)
        if combine_total is not None and combine_total > 0:
            self._combine_total = int(combine_total)
        if combine_index is not None:
            self._note_combine_index(int(combine_index), now)
        if pass_index is not None and pass_index > 0:
            new_index = int(pass_index)
            if self._pass_index is not None and new_index != self._pass_index:
                self._finish_pass(now)
            self._pass_index = new_index
        if local_step is not None:
            self._local_step = max(0.0, min(1.0, local_step))

        if fraction >= 1.0:
            self._pause_infer_clock(now)
            self._held_display = 1.0
            return

        phase = self.phase(fraction)
        if phase == "inference":
            self._resume_infer_clock(now)
        else:
            self._pause_infer_clock(now)

        if phase == "combining":
            if self._combine_step_started is None:
                self._combine_step_started = now
        elif self._combine_step_started is not None and self._last_combine_index is not None:
            # Left combining without a step bump (run finished).
            self._combine_step_started = None

        if phase != "inference":
            return

        display = self.inference_display_fraction(fraction)
        if display is not None:
            self._held_display = max(self._held_display, display)
        infer_frac = display if display is not None else _infer_fraction(fraction)
        if infer_frac <= 0.0:
            return
        self._samples.append((infer_frac, now))
        cutoff = now - _SAMPLE_WINDOW_SEC
        self._samples = [(f, t) for f, t in self._samples if t >= cutoff]
        if len(self._samples) > _MAX_SAMPLES:
            self._samples = self._samples[-_MAX_SAMPLES:]

    def _note_combine_index(self, combine_index: int, now: float) -> None:
        if (
            self._last_combine_index is not None
            and combine_index != self._last_combine_index
            and self._combine_step_started is not None
        ):
            self._combine_durations.append(max(0.05, now - self._combine_step_started))
            self._combine_step_started = now
        elif self._combine_step_started is None:
            self._combine_step_started = now
        self._last_combine_index = combine_index
        self._combine_index = combine_index

    def _resume_infer_clock(self, now: float) -> None:
        if self._infer_slice_started is None:
            self._infer_slice_started = now

    def _pause_infer_clock(self, now: float) -> None:
        if self._infer_slice_started is None:
            return
        dt = max(0.0, now - self._infer_slice_started)
        self._current_pass_infer_acc += dt
        self._infer_elapsed_total += dt
        self._infer_slice_started = None

    def _finish_pass(self, now: float) -> None:
        self._pause_infer_clock(now)
        if self._current_pass_infer_acc >= 0.05:
            self._pass_durations.append(self._current_pass_infer_acc)
        self._current_pass_infer_acc = 0.0
        self._samples.clear()
        self._smoothed_remaining = None

    def phase(self, fraction: float) -> str:
        """Return loading / inference / saving / combining for the latest step."""
        local = self._local_step
        if local is not None:
            if local >= _LOCAL_COMBINE_START:
                return "combining"
            if local >= _LOCAL_SAVE_START:
                return "saving"
            if local < _LOCAL_LOAD_END:
                return "loading"
            return "inference"
        if fraction < _LOAD_END:
            return "loading"
        if fraction >= _SAVE_START:
            return "saving"
        return "inference"

    def is_indeterminate(self, fraction: float) -> bool:
        """True for load / save / combine (bar freezes or pulses)."""
        if fraction >= 1.0:
            return False
        return self.phase(fraction) != "inference"

    def _avg_pass_duration(self) -> Optional[float]:
        if not self._pass_durations:
            return None
        return sum(self._pass_durations) / len(self._pass_durations)

    def inference_display_fraction(self, fraction: float) -> Optional[float]:
        """Inference-only bar position in ``[0, 1]``, or ``None`` when indeterminate."""
        fraction = max(0.0, min(1.0, fraction))
        if fraction >= 1.0:
            return 1.0
        if self.is_indeterminate(fraction):
            return None
        local_infer = _local_infer_progress(self._local_step)
        total = self._pass_total or 1
        index = self._pass_index or 1
        index = max(1, min(index, total))
        equal = (index - 1 + local_infer) / total

        avg = self._avg_pass_duration()
        if avg is None or avg <= 0:
            return max(0.0, min(1.0, equal))
        completed = sum(self._pass_durations)
        remaining_after = max(0, total - index)
        done = completed + local_infer * avg
        total_work = completed + avg + avg * remaining_after
        if total_work <= 0:
            return max(0.0, min(1.0, equal))
        return max(0.0, min(1.0, done / total_work))

    def _infer_elapsed(self, now: float) -> float:
        total = self._infer_elapsed_total
        if self._infer_slice_started is not None:
            total += max(0.0, now - self._infer_slice_started)
        return total

    def _raw_remaining(self, fraction: float, now: float) -> Optional[float]:
        phase = self.phase(fraction)
        if phase == "combining":
            return self._combine_remaining(now)
        if phase != "inference":
            return None

        local_infer = _local_infer_progress(self._local_step)
        total = self._pass_total or 1
        index = self._pass_index or 1
        elapsed_infer = self._infer_elapsed(now)
        if (
            local_infer < _MIN_INFER_FRAC_FOR_ETA
            and elapsed_infer < _MIN_INFER_ELAPSED_FOR_ETA
            and not self._pass_durations
        ):
            return None

        avg = self._avg_pass_duration()
        remaining_after = max(0, total - index) * (avg or 0.0)
        current_left: Optional[float] = None

        if len(self._samples) >= 2:
            first_frac, first_t = self._samples[0]
            last_frac, last_t = self._samples[-1]
            delta_frac = last_frac - first_frac
            delta_t = last_t - first_t
            if delta_frac > 0.001 and delta_t > 0.0:
                # samples are overall inference fraction; convert to current-pass rate
                display = self.inference_display_fraction(fraction) or 0.0
                rate = delta_frac / delta_t
                if rate > 0:
                    current_left = max(0.0, (1.0 - display) / rate)

        if current_left is None and avg is not None:
            current_left = max(0.0, (1.0 - local_infer) * avg)
        elif current_left is None and local_infer >= 0.05 and elapsed_infer > 0:
            # Single-pass fallback using inference-only elapsed.
            current_left = max(0.0, elapsed_infer / local_infer - elapsed_infer)

        if current_left is None:
            return None
        # When using overall display rate, remaining_after is already included.
        if len(self._samples) >= 2 and avg is not None:
            return current_left
        return current_left + remaining_after

    def _combine_remaining(self, now: float) -> Optional[float]:
        if not self._combine_total or not self._combine_index:
            return None
        left_steps = max(0, self._combine_total - self._combine_index)
        if self._combine_durations:
            avg = sum(self._combine_durations) / len(self._combine_durations)
            current = 0.0
            if self._combine_step_started is not None:
                current = max(0.0, avg - (now - self._combine_step_started))
            return max(0.0, current + avg * left_steps)
        # Rough prior: a few percent of inference time per remaining combine step.
        per_step = max(1.0, 0.04 * max(self._infer_elapsed_total, 30.0))
        return per_step * max(1, left_steps + 1)

    def _smooth_remaining(self, raw: Optional[float]) -> Optional[float]:
        if raw is None:
            return None
        if self._smoothed_remaining is None:
            self._smoothed_remaining = raw
        else:
            self._smoothed_remaining = (
                _ETA_EMA_ALPHA * raw + (1.0 - _ETA_EMA_ALPHA) * self._smoothed_remaining
            )
        return self._smoothed_remaining

    def format_text(self, fraction: float, elapsed: float, *, now: Optional[float] = None) -> str:
        fraction = max(0.0, min(1.0, fraction))
        clock = now if now is not None else elapsed
        phase = self.phase(fraction)
        elapsed_part = f"{_format_mmss(elapsed)} elapsed"

        if fraction >= 1.0:
            return " · ".join(["100%", elapsed_part])

        def _with_detail(label: str) -> str:
            parts = [elapsed_part, label]
            if self._detail:
                parts.append(self._detail)
            return " · ".join(parts)

        if phase == "loading":
            return _with_detail("Loading model")
        if phase == "saving":
            return _with_detail("Saving stems")
        if phase == "combining":
            if self._combine_index and self._combine_total:
                label = f"Combining ensemble ({self._combine_index}/{self._combine_total})"
            else:
                label = "Combining ensemble"
            parts = [elapsed_part, label]
            raw = self._raw_remaining(fraction, clock)
            smoothed = self._smooth_remaining(raw)
            if smoothed is not None:
                parts.append(f"~{_format_mmss(smoothed)} left")
            return " · ".join(parts)

        display = self.inference_display_fraction(fraction)
        if display is None:
            display = self._held_display
        percent = int(round(display * 100))
        parts = [f"{percent}%", elapsed_part]
        if self._detail:
            parts.append(self._detail)
        raw = self._raw_remaining(fraction, clock)
        smoothed = self._smooth_remaining(raw)
        if smoothed is not None:
            parts.append(f"~{_format_mmss(smoothed)} left")
        else:
            parts.append("Calculating estimate…")
        return " · ".join(parts)
