"""Operation identities shared by worker progress and its consumers."""

from __future__ import annotations

from enum import StrEnum


class ProcessingPhase(StrEnum):
    PREPARING_SAMPLES = "preparing_samples"
    READING_AUDIO = "reading_audio"
    LOADING_MODEL = "loading_model"
    LOADING_SECONDARY = "loading_secondary"
    LOADING_PREPROCESS = "loading_preprocess"
    LOADING_SPLITTER = "loading_splitter"
    SEPARATING = "separating"
    SEPARATING_SECONDARY = "separating_secondary"
    PREPROCESSING = "preprocessing"
    SPLITTING_VOCALS = "splitting_vocals"
    DENOISING = "denoising"
    DEVERBING = "deverbing"
    BUFFERING = "buffering"
    SAVING = "saving"
    COMBINING = "combining"
    JOINING = "joining"
    CHANGING_PITCH = "changing_pitch"
    STRETCHING_TIME = "stretching_time"
    ALIGNING = "aligning"
    MATCHING = "matching"
    RESTORING = "restoring"
    CACHED = "cached"
    FINISHING = "finishing"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def timing_category(self) -> str:
        """Preserve the ETA clock's load / inference / save / combine boundaries."""
        if self in _LOADING_PHASES:
            return "loading"
        if self in (
            self.SAVING,
            self.BUFFERING,
            self.DEVERBING,
            self.JOINING,
            self.FINISHING,
            self.CACHED,
        ):
            return "saving"
        if self is self.COMBINING:
            return "combining"
        return "inference"


_LOADING_PHASES = {
    ProcessingPhase.PREPARING_SAMPLES,
    ProcessingPhase.READING_AUDIO,
    ProcessingPhase.LOADING_MODEL,
    ProcessingPhase.LOADING_SECONDARY,
    ProcessingPhase.LOADING_PREPROCESS,
    ProcessingPhase.LOADING_SPLITTER,
}
_LABELS = {
    ProcessingPhase.PREPARING_SAMPLES: "Preparing sample clips",
    ProcessingPhase.READING_AUDIO: "Reading audio",
    ProcessingPhase.LOADING_MODEL: "Loading model",
    ProcessingPhase.LOADING_SECONDARY: "Loading secondary model",
    ProcessingPhase.LOADING_PREPROCESS: "Loading pre-process model",
    ProcessingPhase.LOADING_SPLITTER: "Loading vocal splitter",
    ProcessingPhase.SEPARATING: "Separating audio",
    ProcessingPhase.SEPARATING_SECONDARY: "Running secondary model",
    ProcessingPhase.PREPROCESSING: "Pre-processing audio",
    ProcessingPhase.SPLITTING_VOCALS: "Splitting vocals",
    ProcessingPhase.DENOISING: "Denoising audio",
    ProcessingPhase.DEVERBING: "Removing reverb",
    ProcessingPhase.BUFFERING: "Collecting outputs",
    ProcessingPhase.SAVING: "Saving outputs",
    ProcessingPhase.COMBINING: "Combining outputs",
    ProcessingPhase.JOINING: "Joining chunks",
    ProcessingPhase.CHANGING_PITCH: "Changing pitch",
    ProcessingPhase.STRETCHING_TIME: "Stretching time",
    ProcessingPhase.ALIGNING: "Aligning audio",
    ProcessingPhase.MATCHING: "Matching audio",
    ProcessingPhase.RESTORING: "Restoring audio",
    ProcessingPhase.CACHED: "Using cached outputs",
    ProcessingPhase.FINISHING: "Finishing",
}
