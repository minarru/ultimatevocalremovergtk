from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type, cast

import torch
from torch import nn
from torch.nn.modules import activation

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
        in_channel: Optional[int],
        hidden_activation: str = "Tanh",
        hidden_activation_kwargs: Optional[Dict[str, Any]] = None,
        complex_mask: bool = True,
    ) -> None:
        super().__init__()
        if hidden_activation_kwargs is None:
            hidden_activation_kwargs = {}
        self.hidden_activation_kwargs = hidden_activation_kwargs
        self.norm = nn.LayerNorm(emb_dim)
        self.hidden = torch.jit.script(
            nn.Sequential(
                nn.Linear(in_features=emb_dim, out_features=mlp_dim),
                activation.__dict__[hidden_activation](
                    **self.hidden_activation_kwargs
                ),
            )
        )

        self.bandwidth = bandwidth
        self.in_channel = in_channel

        self.complex_mask = complex_mask
        self.reim = 2 if complex_mask else 1
        self.glu_mult = 2


class NormMLP(BaseNormMLP):
    def __init__(
        self,
        emb_dim: int,
        mlp_dim: int,
        bandwidth: int,
        in_channel: Optional[int],
        hidden_activation: str = "Tanh",
        hidden_activation_kwargs: Optional[Dict[str, Any]] = None,
        complex_mask: bool = True,
    ) -> None:
        super().__init__(
            emb_dim=emb_dim,
            mlp_dim=mlp_dim,
            bandwidth=bandwidth,
            in_channel=in_channel,
            hidden_activation=hidden_activation,
            hidden_activation_kwargs=hidden_activation_kwargs,
            complex_mask=complex_mask,
        )

        assert in_channel is not None
        self.output = torch.jit.script(
            nn.Sequential(
                nn.Linear(
                    in_features=mlp_dim,
                    out_features=bandwidth * in_channel * self.reim * 2,
                ),
                nn.GLU(dim=-1),
            )
        )

    def reshape_output(self, mb: torch.Tensor) -> torch.Tensor:
        batch, n_time, _ = mb.shape
        in_channel = cast(int, self.in_channel)
        if self.complex_mask:
            mb = mb.reshape(
                batch,
                n_time,
                in_channel,
                self.bandwidth,
                self.reim,
            ).contiguous()
            mb = torch.view_as_complex(mb)
        else:
            mb = mb.reshape(batch, n_time, in_channel, self.bandwidth)

        mb = torch.permute(mb, (0, 2, 3, 1))
        return mb

    def forward(self, qb: torch.Tensor) -> torch.Tensor:
        qb = self.norm(qb)
        qb = self.hidden(qb)
        mb = self.output(qb)
        return self.reshape_output(mb)


class MultAddNormMLP(NormMLP):
    def __init__(
        self,
        emb_dim: int,
        mlp_dim: int,
        bandwidth: int,
        in_channel: Optional[int],
        hidden_activation: str = "Tanh",
        hidden_activation_kwargs: Optional[Dict[str, Any]] = None,
        complex_mask: bool = True,
    ) -> None:
        super().__init__(
            emb_dim,
            mlp_dim,
            bandwidth,
            in_channel,
            hidden_activation,
            hidden_activation_kwargs,
            complex_mask,
        )

        assert in_channel is not None
        self.output2 = torch.jit.script(
            nn.Sequential(
                nn.Linear(
                    in_features=mlp_dim,
                    out_features=bandwidth * in_channel * self.reim * 2,
                ),
                nn.GLU(dim=-1),
            )
        )

    def forward(self, qb: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        qb = self.norm(qb)
        qb = self.hidden(qb)
        mmb = self.output(qb)
        mmb = self.reshape_output(mmb)
        amb = self.output2(qb)
        amb = self.reshape_output(amb)
        return mmb, amb


class MaskEstimationModuleSuperBase(nn.Module):
    pass


class MaskEstimationModuleBase(MaskEstimationModuleSuperBase):
    def __init__(
        self,
        band_specs: List[Tuple[float, float]],
        emb_dim: int,
        mlp_dim: int,
        in_channel: Optional[int],
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
                    in_channel=in_channel,
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


class OverlappingMaskEstimationModule(MaskEstimationModuleBase):
    def __init__(
        self,
        in_channel: Optional[int],
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
        use_freq_weights: bool = True,
    ) -> None:
        check_nonzero_bandwidth(band_specs)
        check_no_gap(band_specs)

        super().__init__(
            band_specs=band_specs,
            emb_dim=emb_dim + cond_dim,
            mlp_dim=mlp_dim,
            in_channel=in_channel,
            hidden_activation=hidden_activation,
            hidden_activation_kwargs=hidden_activation_kwargs,
            complex_mask=complex_mask,
            norm_mlp_cls=norm_mlp_cls,
            norm_mlp_kwargs=norm_mlp_kwargs,
        )

        self.n_freq = n_freq
        self.band_specs = band_specs
        self.in_channel = in_channel

        if freq_weights is not None:
            for i, fw in enumerate(freq_weights):
                self.register_buffer(f"freq_weights/{i}", fw)

            self.use_freq_weights = use_freq_weights
        else:
            self.use_freq_weights = False

        self.cond_dim = cond_dim

    def _prepare_q(
        self,
        q: torch.Tensor,
        cond: Optional[torch.Tensor],
    ) -> torch.Tensor:
        batch, n_bands, n_time, _emb_dim = q.shape

        if cond is not None:
            if cond.ndim == 2:
                cond = cond[:, None, None, :].expand(-1, n_bands, n_time, -1)
            elif cond.ndim == 3:
                assert cond.shape[1] == n_time
            else:
                raise ValueError(f"Invalid cond shape: {cond.shape}")

            q = torch.cat([q, cond], dim=-1)
        elif self.cond_dim > 0:
            ones = torch.ones(
                (batch, n_bands, n_time, self.cond_dim),
                device=q.device,
                dtype=q.dtype,
            )
            q = torch.cat([q, ones], dim=-1)

        return q

    def forward(
        self,
        q: torch.Tensor,
        cond: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        batch, _n_bands, n_time, _emb_dim = q.shape
        q = self._prepare_q(q, cond)

        mask_list = self.compute_masks(q)

        assert self.in_channel is not None
        assert self.n_freq is not None

        masks = torch.zeros(
            (batch, self.in_channel, self.n_freq, n_time),
            device=q.device,
            dtype=mask_list[0].dtype,
        )

        for im, mask in enumerate(mask_list):
            fstart, fend = self.band_specs[im]
            if self.use_freq_weights:
                fw = self.get_buffer(f"freq_weights/{im}")[:, None]
                mask = mask * fw
            masks[:, :, int(fstart) : int(fend), :] += mask

        return masks


class MultAddMaskEstimationModule(OverlappingMaskEstimationModule):
    def __init__(
        self,
        in_channel: int,
        band_specs: List[Tuple[float, float]],
        freq_weights: List[torch.Tensor],
        n_freq: int,
        emb_dim: int,
        mlp_dim: int,
        cond_dim: int = 0,
        hidden_activation: str = "Tanh",
        hidden_activation_kwargs: Optional[Dict[str, Any]] = None,
        complex_mask: bool = True,
        use_freq_weights: bool = True,
    ) -> None:
        super().__init__(
            in_channel=in_channel,
            band_specs=band_specs,
            freq_weights=freq_weights,
            n_freq=n_freq,
            emb_dim=emb_dim,
            mlp_dim=mlp_dim,
            cond_dim=cond_dim,
            hidden_activation=hidden_activation,
            hidden_activation_kwargs=hidden_activation_kwargs,
            complex_mask=complex_mask,
            norm_mlp_cls=MultAddNormMLP,
            use_freq_weights=use_freq_weights,
        )

    def compute_mult_add_masks(
        self,
        q: torch.Tensor,
    ) -> Tuple[List[torch.Tensor], List[torch.Tensor]]:
        mult_masks: List[torch.Tensor] = []
        add_masks: List[torch.Tensor] = []

        for b, nmlp in enumerate(self.norm_mlp):
            qb = q[:, b, :, :]
            mmb, amb = cast(MultAddNormMLP, nmlp)(qb)
            mult_masks.append(mmb)
            add_masks.append(amb)

        return mult_masks, add_masks

    def forward(
        self,
        q: torch.Tensor,
        cond: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        batch, _n_bands, n_time, _emb_dim = q.shape
        q = self._prepare_q(q, cond)

        mult_list, add_list = self.compute_mult_add_masks(q)

        assert self.in_channel is not None
        assert self.n_freq is not None
        in_channel = self.in_channel
        n_freq = self.n_freq

        mult = torch.zeros(
            (batch, in_channel, n_freq, n_time),
            device=q.device,
            dtype=mult_list[0].dtype,
        )
        add = torch.zeros_like(mult)

        for im, (mm, am) in enumerate(zip(mult_list, add_list)):
            fstart, fend = self.band_specs[im]
            if self.use_freq_weights:
                fw = self.get_buffer(f"freq_weights/{im}")[:, None]
                mm = mm * fw
                am = am * fw
            mult[:, :, int(fstart) : int(fend), :] += mm
            add[:, :, int(fstart) : int(fend), :] += am

        return torch.stack([mult, add], dim=-1)


class PatchingMaskEstimationModule(OverlappingMaskEstimationModule):
    def __init__(
        self,
        in_channel: int,
        band_specs: List[Tuple[float, float]],
        freq_weights: List[torch.Tensor],
        n_freq: int,
        emb_dim: int,
        mlp_dim: int,
        hidden_activation: str = "Tanh",
        hidden_activation_kwargs: Optional[Dict[str, Any]] = None,
        complex_mask: bool = True,
        mask_kernel_freq: int = 3,
        mask_kernel_time: int = 3,
        conv_kernel_freq: int = 1,
        conv_kernel_time: int = 1,
        kernel_norm_mlp_version: int = 1,
        use_freq_weights: bool = True,
    ) -> None:
        del conv_kernel_freq, conv_kernel_time, kernel_norm_mlp_version
        super().__init__(
            in_channel=in_channel,
            band_specs=band_specs,
            freq_weights=freq_weights,
            n_freq=n_freq,
            emb_dim=emb_dim,
            mlp_dim=mlp_dim,
            hidden_activation=hidden_activation,
            hidden_activation_kwargs=hidden_activation_kwargs,
            complex_mask=complex_mask,
            use_freq_weights=use_freq_weights,
        )
        self.mask_kernel_freq = mask_kernel_freq
        self.mask_kernel_time = mask_kernel_time

    def forward(
        self,
        q: torch.Tensor,
        cond: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        base = super().forward(q, cond)
        kf = self.mask_kernel_freq
        kt = self.mask_kernel_time
        batch, channels, n_freq, n_time = base.shape
        out = torch.zeros(
            batch,
            channels,
            kf,
            kt,
            n_freq,
            n_time,
            device=base.device,
            dtype=base.dtype,
        )
        half_f = (kf - 1) // 2
        half_t = (kt - 1) // 2
        for i in range(kf):
            for j in range(kt):
                df = half_f - i
                dt = half_t - j
                out[:, :, i, j] = base.roll(shifts=(df, dt), dims=(2, 3))
        return out


class MaskEstimationModule(OverlappingMaskEstimationModule):
    def __init__(
        self,
        band_specs: List[Tuple[float, float]],
        emb_dim: int,
        mlp_dim: int,
        in_channel: Optional[int],
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
            in_channel=in_channel,
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
