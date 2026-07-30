from __future__ import annotations

from packaging import version

import torch
from torch import Tensor, einsum, nn
import torch.nn.functional as F

from einops import rearrange, reduce

# helpers

def exists(val: object) -> bool:
    return val is not None

# main class

class Attend(nn.Module):
    def __init__(
        self,
        dropout: float = 0.,
        flash: bool = False
    ) -> None:
        super().__init__()
        self.dropout = dropout
        self.attn_dropout = nn.Dropout(dropout)

        self.flash = flash
        assert not (flash and version.parse(torch.__version__) < version.parse('2.0.0')), 'in order to use flash attention, you must be using pytorch 2.0 or above'

    def flash_attn(self, q: Tensor, k: Tensor, v: Tensor) -> Tensor:
        # Let PyTorch pick the SDPA backend.
        #
        # Upstream pinned the backend set per GPU (flash-only on A100, flash
        # disabled elsewhere), which was a 2023 workaround. It is now actively
        # harmful: pinning flash-only means fp32 inputs — i.e. autocast off —
        # find no eligible kernel and raise "No available kernel", and the
        # pinning API (torch.backends.cuda.sdp_kernel) is deprecated and slated
        # for removal. Benchmarked on Ada (sm_89) across Roformer attention
        # shapes in fp16 and fp32, the unpinned heuristic matched or beat every
        # pinned combination — up to 1.26x on long fp16 chunks.
        return F.scaled_dot_product_attention(
            q, k, v,
            dropout_p = self.dropout if self.training else 0.
        )

    def forward(self, q: Tensor, k: Tensor, v: Tensor) -> Tensor:
        """
        einstein notation
        b - batch
        h - heads
        n, i, j - sequence length (base sequence length, source, target)
        d - feature dimension
        """

        q_len, k_len, device = q.shape[-2], k.shape[-2], q.device

        scale = q.shape[-1] ** -0.5

        if self.flash:
            return self.flash_attn(q, k, v)

        # similarity

        sim = einsum(f"b h i d, b h j d -> b h i j", q, k) * scale

        # attention

        attn = sim.softmax(dim=-1)
        attn = self.attn_dropout(attn)

        # aggregate values

        out = einsum(f"b h i j, b h j d -> b h i d", attn, v)

        return out
