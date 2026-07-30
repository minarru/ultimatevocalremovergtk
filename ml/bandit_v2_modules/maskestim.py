from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type, cast

import torch
from torch import nn
from torch.nn.modules import activation
from torch.utils.checkpoint import checkpoint_sequential

from .utils import (
    band_widths_from_specs,
    check_no_gap,
    check_no_overlap,
    check_nonzero_bandwidth,
)


class BaseNormMLP(nn.Module):
    def __init__(
        self,
        emb_dim: int,
        mlp_dim: int,
        bandwidth: int,
        in_channels: Optional[int],
        hidden_activation: str = "Tanh",
        hidden_activation_kwargs: Optional[Dict[str, Any]] = None,
        complex_mask: bool = True,
    ) -> None:
        super().__init__()
        if hidden_activation_kwargs is None:
            hidden_activation_kwargs = {}
        self.hidden_activation_kwargs = hidden_activation_kwargs
        self.norm = nn.LayerNorm(emb_dim)
        self.hidden = nn.Sequential(
            nn.Linear(in_features=emb_dim, out_features=mlp_dim),
            activation.__dict__[hidden_activation](**self.hidden_activation_kwargs),
        )

        self.bandwidth = bandwidth
        self.in_channels = in_channels

        self.complex_mask = complex_mask
        self.reim = 2 if complex_mask else 1
        self.glu_mult = 2


class NormMLP(BaseNormMLP):
    def __init__(
        self,
        emb_dim: int,
        mlp_dim: int,
        bandwidth: int,
        in_channels: Optional[int],
        hidden_activation: str = "Tanh",
        hidden_activation_kwargs: Optional[Dict[str, Any]] = None,
        complex_mask: bool = True,
    ) -> None:
        super().__init__(
            emb_dim=emb_dim,
            mlp_dim=mlp_dim,
            bandwidth=bandwidth,
            in_channels=in_channels,
            hidden_activation=hidden_activation,
            hidden_activation_kwargs=hidden_activation_kwargs,
            complex_mask=complex_mask,
        )

        assert in_channels is not None
        self.output = nn.Sequential(
            nn.Linear(
                in_features=mlp_dim,
                out_features=bandwidth * in_channels * self.reim * 2,
            ),
            nn.GLU(dim=-1),
        )

        try:
            self.combined = torch.compile(
                nn.Sequential(self.norm, self.hidden, self.output), disable=True
            )
        except Exception:
            self.combined = nn.Sequential(self.norm, self.hidden, self.output)

    def reshape_output(self, mb: torch.Tensor) -> torch.Tensor:
        batch, n_time, _ = mb.shape
        in_channels = cast(int, self.in_channels)
        if self.complex_mask:
            mb = mb.reshape(
                batch, n_time, in_channels, self.bandwidth, self.reim
            ).contiguous()
            mb = torch.view_as_complex(mb)
        else:
            mb = mb.reshape(batch, n_time, in_channels, self.bandwidth)

        mb = torch.permute(mb, (0, 2, 3, 1))
        return mb

    def forward(self, qb: torch.Tensor) -> torch.Tensor:
        mb = checkpoint_sequential(self.combined, 2, qb, use_reentrant=False)
        return self.reshape_output(mb)


class MaskEstimationModuleSuperBase(nn.Module):
    pass


class MaskEstimationModuleBase(MaskEstimationModuleSuperBase):
    def __init__(
        self,
        band_specs: List[Tuple[float, float]],
        emb_dim: int,
        mlp_dim: int,
        in_channels: Optional[int],
        hidden_activation: str = "Tanh",
        hidden_activation_kwargs: Optional[Dict[str, Any]] = None,
        complex_mask: bool = True,
        norm_mlp_cls: Type[nn.Module] = NormMLP,
        norm_mlp_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__()

        self.band_widths = band_widths_from_specs(band_specs)
        self.n_bands = len(band_specs)

        if hidden_activation_kwargs is None:
            hidden_activation_kwargs = {}

        if norm_mlp_kwargs is None:
            norm_mlp_kwargs = {}

        self.norm_mlp = nn.ModuleList(
            [
                norm_mlp_cls(
                    bandwidth=self.band_widths[b],
                    emb_dim=emb_dim,
                    mlp_dim=mlp_dim,
                    in_channels=in_channels,
                    hidden_activation=hidden_activation,
                    hidden_activation_kwargs=hidden_activation_kwargs,
                    complex_mask=complex_mask,
                    **norm_mlp_kwargs,
                )
                for b in range(self.n_bands)
            ]
        )

    def compute_masks(self, q: torch.Tensor) -> List[torch.Tensor]:
        masks: List[torch.Tensor] = []

        for b, nmlp in enumerate(self.norm_mlp):
            qb = q[:, b, :, :]
            mb = nmlp(qb)
            masks.append(mb)

        return masks

    def compute_mask(self, q: torch.Tensor, b: int) -> torch.Tensor:
        qb = q[:, b, :, :]
        return cast(NormMLP, self.norm_mlp[b])(qb)


class OverlappingMaskEstimationModule(MaskEstimationModuleBase):
    def __init__(
        self,
        in_channels: Optional[int],
        band_specs: List[Tuple[float, float]],
        freq_weights: Optional[List[torch.Tensor]],
        n_freq: Optional[int],
        emb_dim: int,
        mlp_dim: int,
        cond_dim: int = 0,
        hidden_activation: str = "Tanh",
        hidden_activation_kwargs: Optional[Dict[str, Any]] = None,
        complex_mask: bool = True,
        norm_mlp_cls: Type[nn.Module] = NormMLP,
        norm_mlp_kwargs: Optional[Dict[str, Any]] = None,
        use_freq_weights: bool = False,
    ) -> None:
        check_nonzero_bandwidth(band_specs)
        check_no_gap(band_specs)

        if cond_dim > 0:
            raise NotImplementedError

        super().__init__(
            band_specs=band_specs,
            emb_dim=emb_dim + cond_dim,
            mlp_dim=mlp_dim,
            in_channels=in_channels,
            hidden_activation=hidden_activation,
            hidden_activation_kwargs=hidden_activation_kwargs,
            complex_mask=complex_mask,
            norm_mlp_cls=norm_mlp_cls,
            norm_mlp_kwargs=norm_mlp_kwargs,
        )

        self.n_freq = n_freq
        self.band_specs = band_specs
        self.in_channels = in_channels

        if freq_weights is not None and use_freq_weights:
            for i, fw in enumerate(freq_weights):
                self.register_buffer(f"freq_weights/{i}", fw)

            self.use_freq_weights = use_freq_weights
        else:
            self.use_freq_weights = False

    def forward(self, q: torch.Tensor) -> torch.Tensor:
        batch, n_bands, n_time, _emb_dim = q.shape

        assert self.in_channels is not None
        assert self.n_freq is not None

        masks = torch.zeros(
            (batch, self.in_channels, self.n_freq, n_time),
            device=q.device,
            dtype=torch.complex64,
        )

        for im in range(n_bands):
            fstart, fend = self.band_specs[im]
            mask = self.compute_mask(q, im)

            if self.use_freq_weights:
                fw = self.get_buffer(f"freq_weights/{im}")[:, None]
                mask = mask * fw
            masks[:, :, int(fstart) : int(fend), :] += mask

        return masks


class MaskEstimationModule(OverlappingMaskEstimationModule):
    def __init__(
        self,
        band_specs: List[Tuple[float, float]],
        emb_dim: int,
        mlp_dim: int,
        in_channels: Optional[int],
        hidden_activation: str = "Tanh",
        hidden_activation_kwargs: Optional[Dict[str, Any]] = None,
        complex_mask: bool = True,
        **kwargs: Any,
    ) -> None:
        del kwargs
        check_nonzero_bandwidth(band_specs)
        check_no_gap(band_specs)
        check_no_overlap(band_specs)
        super().__init__(
            in_channels=in_channels,
            band_specs=band_specs,
            freq_weights=None,
            n_freq=None,
            emb_dim=emb_dim,
            mlp_dim=mlp_dim,
            hidden_activation=hidden_activation,
            hidden_activation_kwargs=hidden_activation_kwargs,
            complex_mask=complex_mask,
        )

    def forward(
        self,
        q: torch.Tensor,
        cond: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        del cond
        masks = self.compute_masks(q)
        return torch.concat(masks, dim=2)
