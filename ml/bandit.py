"""Bandit cinematic source separation models."""

from ml.bandit_bsrnn.bsrnn.wrapper import (
    MultiMaskMultiSourceBandSplitRNNSimple as MultiMaskMultiSourceBandSplitRNN,
)
from ml.bandit_v2_modules.bandit import Bandit

__all__ = ["Bandit", "MultiMaskMultiSourceBandSplitRNN"]
