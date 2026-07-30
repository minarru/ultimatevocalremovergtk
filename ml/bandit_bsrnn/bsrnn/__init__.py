from abc import ABC

import torch
from torch import nn

from .bandsplit import BandSplitModule
from .tfmodel import (
    SeqBandModellingModule,
    TransformerTimeFreqModule,
)


class BandsplitCoreBase(nn.Module, ABC):
    band_split: nn.Module
    tf_model: nn.Module
    mask_estim: nn.Module

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def mask(x: torch.Tensor, m: torch.Tensor) -> torch.Tensor:
        return x * m
