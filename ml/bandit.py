"""Bandit cinematic source separation models.

Two trees are kept on purpose:

* ``bandit_v2_modules`` — YAML ``Bandit`` (v2) configs
* ``bandit_bsrnn`` — ``MultiMaskMultiSourceBandSplitRNNSimple`` / musical BSRNN

They share ideas but diverge in wrappers, band specs, and checkpoints; do not
collapse them into one NN package. Dead unused modules (e.g. FiLM) are removed
instead of a risky full merge.
"""

from __future__ import annotations

from ml.bandit_bsrnn.bsrnn.wrapper import (
    MultiMaskMultiSourceBandSplitRNNSimple as MultiMaskMultiSourceBandSplitRNN,
)
from ml.bandit_v2_modules.bandit import Bandit

__all__ = ["Bandit", "MultiMaskMultiSourceBandSplitRNN"]
