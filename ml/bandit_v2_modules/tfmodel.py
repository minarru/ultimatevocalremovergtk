from __future__ import annotations

import warnings
from typing import cast

import torch
from torch import nn
from torch.nn.modules import rnn
from torch.utils.checkpoint import checkpoint_sequential


class TimeFrequencyModellingModule(nn.Module):
    def __init__(self) -> None:
        super().__init__()


class ResidualRNN(nn.Module):
    def __init__(
        self,
        emb_dim: int,
        rnn_dim: int,
        bidirectional: bool = True,
        rnn_type: str = "LSTM",
        use_batch_trick: bool = True,
        use_layer_norm: bool = True,
    ) -> None:
        super().__init__()

        assert use_layer_norm
        assert use_batch_trick

        self.use_layer_norm = use_layer_norm
        self.norm = nn.LayerNorm(emb_dim)
        self.rnn = rnn.__dict__[rnn_type](
            input_size=emb_dim,
            hidden_size=rnn_dim,
            num_layers=1,
            batch_first=True,
            bidirectional=bidirectional,
        )

        self.fc = nn.Linear(
            in_features=rnn_dim * (2 if bidirectional else 1), out_features=emb_dim
        )

        self.use_batch_trick = use_batch_trick
        if not self.use_batch_trick:
            warnings.warn("NOT USING BATCH TRICK IS EXTREMELY SLOW!!", stacklevel=2)

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        z0 = torch.clone(z)
        z = self.norm(z)

        batch, n_uncrossed, n_across, emb_dim = z.shape
        z = torch.reshape(z, (batch * n_uncrossed, n_across, emb_dim))
        z = self.rnn(z)[0]
        z = torch.reshape(z, (batch, n_uncrossed, n_across, -1))

        z = self.fc(z)
        return z + z0


class Transpose(nn.Module):
    def __init__(self, dim0: int, dim1: int) -> None:
        super().__init__()
        self.dim0 = dim0
        self.dim1 = dim1

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return z.transpose(self.dim0, self.dim1)


class SeqBandModellingModule(TimeFrequencyModellingModule):
    seqband: nn.ModuleList | nn.Sequential

    def __init__(
        self,
        n_modules: int = 12,
        emb_dim: int = 128,
        rnn_dim: int = 256,
        bidirectional: bool = True,
        rnn_type: str = "LSTM",
        parallel_mode: bool = False,
    ) -> None:
        super().__init__()

        self.n_modules = n_modules

        if parallel_mode:
            self.seqband = nn.ModuleList([])
            for _ in range(n_modules):
                self.seqband.append(
                    nn.ModuleList(
                        [
                            ResidualRNN(
                                emb_dim=emb_dim,
                                rnn_dim=rnn_dim,
                                bidirectional=bidirectional,
                                rnn_type=rnn_type,
                            ),
                            ResidualRNN(
                                emb_dim=emb_dim,
                                rnn_dim=rnn_dim,
                                bidirectional=bidirectional,
                                rnn_type=rnn_type,
                            ),
                        ]
                    )
                )
        else:
            seqband: list[nn.Module] = []
            for _ in range(2 * n_modules):
                seqband += [
                    ResidualRNN(
                        emb_dim=emb_dim,
                        rnn_dim=rnn_dim,
                        bidirectional=bidirectional,
                        rnn_type=rnn_type,
                    ),
                    Transpose(1, 2),
                ]

            self.seqband = nn.Sequential(*seqband)

        self.parallel_mode = parallel_mode

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        if self.parallel_mode:
            seqband = cast(nn.ModuleList, self.seqband)
            for sbm_pair in seqband:
                pair = cast(nn.ModuleList, sbm_pair)
                sbm_t = cast(ResidualRNN, pair[0])
                sbm_f = cast(ResidualRNN, pair[1])
                zt = sbm_t(z)
                zf = sbm_f(z.transpose(1, 2))
                z = zt + zf.transpose(1, 2)
        else:
            z = checkpoint_sequential(
                cast(nn.Sequential, self.seqband),
                self.n_modules,
                z,
                use_reentrant=False,
            )

        return z
