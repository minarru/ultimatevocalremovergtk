from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

import torch
import torch.nn as nn

NormFactory: TypeAlias = Callable[[int], nn.Module]


class TFC(nn.Module):
    def __init__(self, c: int, l: int, k: int, norm: NormFactory) -> None:
        super(TFC, self).__init__()

        self.H = nn.ModuleList()
        for i in range(l):
            self.H.append(
                nn.Sequential(
                    nn.Conv2d(in_channels=c, out_channels=c, kernel_size=k, stride=1, padding=k // 2),
                    norm(c),
                    nn.ReLU(),
                )
            )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for h in self.H:
            x = h(x)
        return x


class DenseTFC(nn.Module):
    def __init__(self, c: int, l: int, k: int, norm: NormFactory) -> None:
        super(DenseTFC, self).__init__()

        self.conv = nn.ModuleList()
        for i in range(l):
            self.conv.append(
                nn.Sequential(
                    nn.Conv2d(in_channels=c, out_channels=c, kernel_size=k, stride=1, padding=k // 2),
                    norm(c),
                    nn.ReLU(),
                )
            )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for layer in self.conv[:-1]:
            x = torch.cat([layer(x), x], 1)
        return self.conv[-1](x)


class TFC_TDF(nn.Module):
    def __init__(
        self,
        c: int,
        l: int,
        f: int,
        k: int,
        bn: int | None,
        dense: bool = False,
        bias: bool = True,
        norm: NormFactory = nn.BatchNorm2d,
    ) -> None:

        super(TFC_TDF, self).__init__()

        self.use_tdf = bn is not None

        self.tfc = DenseTFC(c, l, k, norm) if dense else TFC(c, l, k, norm)

        if self.use_tdf:
            assert bn is not None
            if bn == 0:
                self.tdf = nn.Sequential(
                    nn.Linear(f, f, bias=bias),
                    norm(c),
                    nn.ReLU()
                )
            else:
                self.tdf = nn.Sequential(
                    nn.Linear(f, f // bn, bias=bias),
                    norm(c),
                    nn.ReLU(),
                    nn.Linear(f // bn, f, bias=bias),
                    norm(c),
                    nn.ReLU()
                )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.tfc(x)
        return x + self.tdf(x) if self.use_tdf else x
