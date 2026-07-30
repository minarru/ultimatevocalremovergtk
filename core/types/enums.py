"""String enums mirroring bundled constant labels."""

from enum import Enum


class Stem(str, Enum):
    VOCALS = "Vocals"
    INSTRUMENTAL = "Instrumental"
    OTHER = "Other"
    BASS = "Bass"
    DRUMS = "Drums"
    GUITAR = "Guitar"
    PIANO = "Piano"
    ALL = "All Stems"


class ProcessMethod(str, Enum):
    VR = "VR Architecture"
    VR_ARCH = "VR Arc"
    MDX = "MDX-Net"
    DEMUCS = "Demucs"
    ENSEMBLE = "Ensemble Mode"
    APOLLO = "Apollo"


class EnsembleAlgorithm(str, Enum):
    MAX_SPEC = "Max Spec"
    MIN_SPEC = "Min Spec"
    AVERAGE = "Average"
    MEDIAN_SPEC = "Median Spec"
    SOFT_SPEC = "Soft Spec"
    MAX_MAG_AVG_PHASE = "Max Mag / Avg Phase"
    HYBRID_SPEC = "Hybrid Spec"
    CHUNK_MIN = "Chunk Min"


class SaveFormat(str, Enum):
    WAV = "WAV"
    FLAC = "FLAC"
    MP3 = "MP3"
