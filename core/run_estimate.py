"""Pre-run workload hints and live separation ETA tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Sequence, Tuple

from bundled.constants import (
    ALL_STEMS,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    NO_MODEL,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)

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


def _pitch_change_active(settings) -> bool:
    try:
        return float(settings.get("semitone_shift") or 0) != 0.0
    except (TypeError, ValueError):
        return False


def cost_factor_hints(settings, method_key: str) -> Tuple[str, ...]:
    """Return readable labels for settings that add cost beyond pass/output counts."""
    hints: List[str] = []
    if method_key in (VR_ARCH_TYPE, VR_ARCH_PM):
        if settings.get("is_tta"):
            hints.append("TTA")
    elif method_key == MDX_ARCH_TYPE:
        try:
            overlap = int(float(settings.get("overlap_mdx23") or 0))
        except (TypeError, ValueError):
            overlap = 0
        if overlap >= 8:
            hints.append(f"Overlap {overlap}")
        if settings.get("is_match_frequency_pitch") and _pitch_change_active(settings):
            hints.append("Match frequency")
        denoise = settings.get("denoise_option")
        if denoise not in (None, "", "None", "none"):
            hints.append("Denoise")
    elif method_key == DEMUCS_ARCH_TYPE:
        try:
            shifts = int(settings.get("shifts") or 0)
        except (TypeError, ValueError):
            shifts = 0
        if shifts > 1:
            hints.append(f"Shifts {shifts}")
        if settings.get("is_demucs_pre_proc_model_activate"):
            hints.append("Pre-process")
    return tuple(hints)


# Back-compat alias for older imports/tests.
slow_setting_hints = cost_factor_hints


def classify_export_tier(output_count: int) -> RunCostTier:
    if output_count <= 1:
        return RunCostTier.FASTEST
    if output_count == 2:
        return RunCostTier.TYPICAL
    return RunCostTier.SLOWER


def classify_run_tier(inference_passes: int) -> Optional[RunCostTier]:
    if inference_passes <= 1:
        return None
    if inference_passes == 2:
        return RunCostTier.TYPICAL
    return RunCostTier.SLOWER


def count_inference_passes_from_models(models: Sequence[Any]) -> int:
    """Mirror JobRunner._count_true_models for an assembled model list."""
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
    settings,
    *,
    method_key: str,
    repo=None,
    model_name: Optional[str] = None,
) -> int:
    """Return expected inference passes for the current method settings."""
    if method_key == ENSEMBLE_MODE:
        selected = settings.get("selected_models") or []
        return max(1, len(selected))

    if repo is not None and model_name and model_name not in (None, NO_MODEL, ""):
        from .model_data import assemble_model_data

        try:
            models = assemble_model_data(settings, repo, model_name, method_key)
            valid = [m for m in models if getattr(m, "model_status", False)]
            if valid:
                return count_inference_passes_from_models(valid)
        except (ValueError, NotImplementedError):
            pass

    return _count_inference_passes_light(settings, method_key)


def _count_inference_passes_light(settings, method_key: str) -> int:
    passes = 1
    secondary_key = _SECONDARY_ACTIVATE_KEY.get(method_key)
    if secondary_key and settings.get(secondary_key):
        passes += 1
    if settings.get("is_set_vocal_splitter") and settings.get("set_vocal_splitter") not in (
        None,
        NO_MODEL,
        "",
    ):
        passes += 1
    if method_key == DEMUCS_ARCH_TYPE and settings.get("is_demucs_pre_proc_model_activate"):
        passes += 2
    return passes


def count_expected_outputs(save_stems) -> int:
    """Read SaveStemsSection UI state (see ui.widgets.stem_only)."""
    return int(save_stems.expected_output_count())


def estimate_workload(
    settings,
    *,
    method_key: str,
    save_stems,
    repo=None,
    model_name: Optional[str] = None,
    has_model: bool = True,
) -> Optional[WorkloadEstimate]:
    if not has_model or save_stems.mode == "hidden":
        return None
    output_count = count_expected_outputs(save_stems)
    if output_count <= 0:
        return None
    inference_passes = count_inference_passes(
        settings,
        method_key=method_key,
        repo=repo,
        model_name=model_name,
    )
    if inference_passes <= 0:
        inference_passes = 1
    return WorkloadEstimate(
        inference_passes=inference_passes,
        output_count=output_count,
        uses_gpu=bool(settings.get("is_gpu_conversion")),
        sample_mode=bool(settings.get("model_sample_mode")),
        sample_seconds=int(settings.get("model_sample_mode_duration", 30) or 30),
        export_tier=classify_export_tier(output_count),
        run_tier=classify_run_tier(inference_passes),
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


@dataclass
class ProgressEtaTracker:
    """Phase-aware live ETA for separation progress callbacks."""

    _inference_started_at: Optional[float] = None
    _samples: List[Tuple[float, float]] = field(default_factory=list)
    _smoothed_remaining: Optional[float] = None
    _local_step: Optional[float] = None

    def reset(self) -> None:
        self._inference_started_at = None
        self._samples.clear()
        self._smoothed_remaining = None
        self._local_step = None

    def update(self, fraction: float, now: float, *, local_step: Optional[float] = None) -> None:
        fraction = max(0.0, min(1.0, fraction))
        if local_step is not None:
            self._local_step = max(0.0, min(1.0, local_step))
        if fraction >= _LOAD_END and self._inference_started_at is None:
            if self._phase(fraction) == "inference":
                self._inference_started_at = now
        if self._phase(fraction) != "inference":
            return
        infer_frac = _infer_fraction(fraction)
        if infer_frac <= 0.0:
            return
        self._samples.append((infer_frac, now))
        cutoff = now - _SAMPLE_WINDOW_SEC
        self._samples = [(f, t) for f, t in self._samples if t >= cutoff]
        if len(self._samples) > _MAX_SAMPLES:
            self._samples = self._samples[-_MAX_SAMPLES:]

    def _phase(self, fraction: float) -> str:
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

    def _raw_remaining(self, fraction: float, now: float) -> Optional[float]:
        if self._inference_started_at is None:
            return None
        infer_frac = _infer_fraction(fraction)
        if infer_frac <= 0.0:
            return None
        elapsed_infer = now - self._inference_started_at
        if infer_frac < _MIN_INFER_FRAC_FOR_ETA and elapsed_infer < _MIN_INFER_ELAPSED_FOR_ETA:
            return None
        if len(self._samples) >= 2:
            first_frac, first_t = self._samples[0]
            last_frac, last_t = self._samples[-1]
            delta_frac = last_frac - first_frac
            delta_t = last_t - first_t
            if delta_frac > 0.001 and delta_t > 0.0:
                rate = delta_frac / delta_t
                remaining = (1.0 - infer_frac) / rate
                return max(0.0, remaining)
        if infer_frac >= 0.05:
            total_est = elapsed_infer / infer_frac
            return max(0.0, total_est - elapsed_infer)
        return None

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
        percent = int(round(fraction * 100))
        parts = [f"{percent}%", f"{_format_mmss(elapsed)} elapsed"]
        if fraction >= 1.0:
            return " · ".join(parts)

        clock = now if now is not None else elapsed
        phase = self._phase(fraction)
        if phase == "loading":
            parts.append("Loading model")
        elif phase in ("saving", "combining"):
            parts.append("Combining" if phase == "combining" else "Saving")
        else:
            raw = self._raw_remaining(fraction, clock)
            smoothed = self._smooth_remaining(raw)
            if smoothed is not None and fraction < 1.0:
                parts.append(f"~{_format_mmss(smoothed)} left")
            else:
                parts.append("Calculating estimate…")
        return " · ".join(parts)
