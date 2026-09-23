from abc import ABC

import torch
from torch import nn

from .bandsplit import BandSplitModule as BandSplitModule
from .tfmodel import (
    SeqBandModellingModule as SeqBandModellingModule,
)
from .tfmodel import (
    TransformerTimeFreqModule as TransformerTimeFreqModule,
)


class BandsplitCoreBase(nn.Module, ABC):
    band_split: nn.Module
    tf_model: nn.Module
    # ``mask_estim`` is declared by each subclass: MultiMask holds a ModuleDict,
    # SingleMask a plain Module. Declaring it here made that an override clash.

    def __init__(self) -> None:
        super().__init__()

    # Instance method, not a staticmethod: subclasses override it as one, and
    # every call site is ``self.mask(...)`` / ``super().mask(...)``.
    def mask(self, x: torch.Tensor, m: torch.Tensor) -> torch.Tensor:
        return x * m
