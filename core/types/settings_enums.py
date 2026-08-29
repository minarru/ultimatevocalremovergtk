"""Closed settings vocabularies (``str, Enum``; ``.value`` = UI label)."""

from __future__ import annotations

from enum import Enum


class WavType(str, Enum):
    PCM_U8 = "PCM_U8"
    PCM_16 = "PCM_16"
    PCM_24 = "PCM_24"
    PCM_32 = "PCM_32"
    FLOAT_32 = "32-bit Float"
    FLOAT_64 = "64-bit Float"


class Mp3Bitrate(str, Enum):
    K96 = "96k"
    K128 = "128k"
    K160 = "160k"
    K224 = "224k"
    K256 = "256k"
    K320 = "320k"


class OpusBitrate(str, Enum):
    K64 = "64k"
    K96 = "96k"
    K128 = "128k"
    K160 = "160k"
    K192 = "192k"
    K256 = "256k"


class FlacBitDepth(str, Enum):
    BIT_16 = "16-bit"
    BIT_24 = "24-bit"


class DeverbVocalOpt(str, Enum):
    MAIN_VOCALS_ONLY = "Main Vocals Only"
    LEAD_VOCALS_ONLY = "Lead Vocals Only"
    BACKING_VOCALS_ONLY = "Backing Vocals Only"
    ALL_VOCAL_TYPES = "All Vocal Types"


class MdxDenoiseOption(str, Enum):
    NONE = "None"
    STANDARD = "Standard"
    DENOISE_MODEL = "Denoise Model"


class AlignPhaseOption(str, Enum):
    AUTOMATIC = "Automatic"
    POSITIVE_PHASE = "Positive Phase"
    NEGATIVE_PHASE = "Negative Phase"
    NATIVE_PHASE = "Native Phase"


class PhaseShiftsOpt(str, Enum):
    NONE = "None"
    SHIFTS_VERY_LOW = "Shifts: Very Low"
    SHIFTS_LOW = "Shifts: Low"
    SHIFTS_MEDIUM = "Shifts: Medium"
    SHIFTS_HIGH = "Shifts: High"
    SHIFTS_VERY_HIGH = "Shifts: Very High"
    SHIFTS_MAXIMUM = "Shifts: Maximum"


class TimeWindow(str, Enum):
    NONE = "None"
    V1 = "1"
    V2 = "2"
    V3 = "3"
    V4 = "4"
    V5 = "5"
    V6 = "6"
    V7 = "7"
    SHIFTS_LOW = "Shifts: Low"
    SHIFTS_MEDIUM = "Shifts: Medium"
    SHIFTS_HIGH = "Shifts: High"


class IntroAnalysis(str, Enum):
    DEFAULT = "Default"
    V1 = "1"
    V2 = "2"
    V3 = "3"
    V4 = "4"
    SHIFTS_LOW = "Shifts: Low"
    SHIFTS_MEDIUM = "Shifts: Medium"
    SHIFTS_HIGH = "Shifts: High"


class DbAnalysis(str, Enum):
    NONE = "None"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    VERY_HIGH = "Very High"


class AudioTool(str, Enum):
    MANUAL_ENSEMBLE = "Manual Ensemble"
    TIME_STRETCH = "Time Stretch"
    CHANGE_PITCH = "Change Pitch"
    ALIGN_INPUTS = "Align Inputs"
    MATCHERING = "Matchering"
    APOLLO_RESTORE = "Apollo Restore"


class ManualEnsembleOption(str, Enum):
    MAX_SPEC = "Max Spec"
    MIN_SPEC = "Min Spec"
    AVERAGE = "Average"
    MEDIAN_SPEC = "Median Spec"
    SOFT_SPEC = "Soft Spec"
    MAX_MAG_AVG_PHASE = "Max Mag / Avg Phase"
    HYBRID_SPEC = "Hybrid Spec"
    CHUNK_MIN = "Chunk Min"
    COMBINE_INPUTS = "Combine Inputs"


class ColorScheme(str, Enum):
    AUTO = "auto"
    LIGHT = "light"
    DARK = "dark"


class DiagnosticLevel(str, Enum):
    ERRORS = "errors"
    DEBUG = "debug"
    TRACE = "trace"


__all__ = [
    "AlignPhaseOption",
    "AudioTool",
    "ColorScheme",
    "DiagnosticLevel",
    "DbAnalysis",
    "DeverbVocalOpt",
    "FlacBitDepth",
    "IntroAnalysis",
    "ManualEnsembleOption",
    "MdxDenoiseOption",
    "Mp3Bitrate",
    "OpusBitrate",
    "PhaseShiftsOpt",
    "TimeWindow",
    "WavType",
]
