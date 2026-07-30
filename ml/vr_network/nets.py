from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import torch
from torch import Tensor, nn
import torch.nn.functional as F

from . import layers

ModelCapacityTuple = tuple[int, ...]
ModelCapacityData = list[ModelCapacityTuple]


class BaseASPPNet(nn.Module):

    def __init__(
        self,
        nn_architecture: int,
        nin: int,
        ch: int,
        dilations: Sequence[int] = (4, 8, 16),
    ) -> None:
        super(BaseASPPNet, self).__init__()
        self.nn_architecture = nn_architecture
        self.enc1 = layers.Encoder(nin, ch, 3, 2, 1)
        self.enc2 = layers.Encoder(ch, ch * 2, 3, 2, 1)
        self.enc3 = layers.Encoder(ch * 2, ch * 4, 3, 2, 1)
        self.enc4 = layers.Encoder(ch * 4, ch * 8, 3, 2, 1)
        
        if self.nn_architecture == 129605:
            self.enc5 = layers.Encoder(ch * 8, ch * 16, 3, 2, 1)
            self.aspp = layers.ASPPModule(nn_architecture, ch * 16, ch * 32, dilations)
            self.dec5 = layers.Decoder(ch * (16 + 32), ch * 16, 3, 1, 1)
        else:
            self.aspp = layers.ASPPModule(nn_architecture, ch * 8, ch * 16, dilations)
            
        self.dec4 = layers.Decoder(ch * (8 + 16), ch * 8, 3, 1, 1)
        self.dec3 = layers.Decoder(ch * (4 + 8), ch * 4, 3, 1, 1)
        self.dec2 = layers.Decoder(ch * (2 + 4), ch * 2, 3, 1, 1)
        self.dec1 = layers.Decoder(ch * (1 + 2), ch, 3, 1, 1)

    def __call__(self, x: Tensor) -> Tensor:
        h, e1 = self.enc1(x)
        h, e2 = self.enc2(h)
        h, e3 = self.enc3(h)
        h, e4 = self.enc4(h)
        
        if self.nn_architecture == 129605:
            h, e5 = self.enc5(h)
            h = self.aspp(h)
            h = self.dec5(h, e5)
        else:
            h = self.aspp(h)
            
        h = self.dec4(h, e4)
        h = self.dec3(h, e3)
        h = self.dec2(h, e2)
        h = self.dec1(h, e1)

        return h

def determine_model_capacity(n_fft_bins: int, nn_architecture: int) -> CascadedASPPNet:
    
    sp_model_arch = [31191, 33966, 129605]
    hp_model_arch = [123821, 123812]
    hp2_model_arch = [537238, 537227]
    
    if nn_architecture in sp_model_arch:
        model_capacity_data = [
            (2, 16),
            (2, 16),
            (18, 8, 1, 1, 0),
            (8, 16),
            (34, 16, 1, 1, 0),
            (16, 32),
            (32, 2, 1),
            (16, 2, 1),
            (16, 2, 1),
        ]
    
    if nn_architecture in hp_model_arch:
        model_capacity_data = [
            (2, 32),
            (2, 32),
            (34, 16, 1, 1, 0),
            (16, 32),
            (66, 32, 1, 1, 0),
            (32, 64),
            (64, 2, 1),
            (32, 2, 1),
            (32, 2, 1),
        ]
       
    if nn_architecture in hp2_model_arch: 
        model_capacity_data = [
            (2, 64),
            (2, 64),
            (66, 32, 1, 1, 0),
            (32, 64),
            (130, 64, 1, 1, 0),
            (64, 128),
            (128, 2, 1),
            (64, 2, 1),
            (64, 2, 1),
        ]

    cascaded = CascadedASPPNet
    model = cascaded(n_fft_bins, model_capacity_data, nn_architecture)
    
    return model

class CascadedASPPNet(nn.Module):

    def __init__(
        self,
        n_fft: int,
        model_capacity_data: ModelCapacityData,
        nn_architecture: int,
    ) -> None:
        super(CascadedASPPNet, self).__init__()
        stg1_low = model_capacity_data[0]
        stg1_high = model_capacity_data[1]
        stg2_bridge = model_capacity_data[2]
        stg2_full = model_capacity_data[3]
        stg3_bridge = model_capacity_data[4]
        stg3_full = model_capacity_data[5]
        out_cfg = model_capacity_data[6]
        aux1_cfg = model_capacity_data[7]
        aux2_cfg = model_capacity_data[8]

        self.stg1_low_band_net = BaseASPPNet(nn_architecture, stg1_low[0], stg1_low[1])
        self.stg1_high_band_net = BaseASPPNet(nn_architecture, stg1_high[0], stg1_high[1])

        self.stg2_bridge = layers.Conv2DBNActiv(
            stg2_bridge[0], stg2_bridge[1], stg2_bridge[2], stg2_bridge[3], stg2_bridge[4],
        )
        self.stg2_full_band_net = BaseASPPNet(nn_architecture, stg2_full[0], stg2_full[1])

        self.stg3_bridge = layers.Conv2DBNActiv(
            stg3_bridge[0], stg3_bridge[1], stg3_bridge[2], stg3_bridge[3], stg3_bridge[4],
        )
        self.stg3_full_band_net = BaseASPPNet(nn_architecture, stg3_full[0], stg3_full[1])

        self.out = nn.Conv2d(out_cfg[0], out_cfg[1], out_cfg[2], bias=False)
        self.aux1_out = nn.Conv2d(aux1_cfg[0], aux1_cfg[1], aux1_cfg[2], bias=False)
        self.aux2_out = nn.Conv2d(aux2_cfg[0], aux2_cfg[1], aux2_cfg[2], bias=False)

        self.max_bin = n_fft // 2
        self.output_bin = n_fft // 2 + 1

        self.offset = 128

    def forward(self, x: Tensor) -> Tensor | tuple[Tensor, Tensor, Tensor]:
        mix = x.detach()
        x = x.clone()

        x = x[:, :, :self.max_bin]

        bandw = x.size()[2] // 2
        aux1 = torch.cat([
            self.stg1_low_band_net(x[:, :, :bandw]),
            self.stg1_high_band_net(x[:, :, bandw:])
        ], dim=2)

        h = torch.cat([x, aux1], dim=1)
        aux2 = self.stg2_full_band_net(self.stg2_bridge(h))

        h = torch.cat([x, aux1, aux2], dim=1)
        h = self.stg3_full_band_net(self.stg3_bridge(h))

        mask = torch.sigmoid(self.out(h))
        mask = F.pad(
            input=mask,
            pad=(0, 0, 0, self.output_bin - mask.size()[2]),
            mode='replicate')
 
        if self.training:
            aux1 = torch.sigmoid(self.aux1_out(aux1))
            aux1 = F.pad(
                input=aux1,
                pad=(0, 0, 0, self.output_bin - aux1.size()[2]),
                mode='replicate')
            aux2 = torch.sigmoid(self.aux2_out(aux2))
            aux2 = F.pad(
                input=aux2,
                pad=(0, 0, 0, self.output_bin - aux2.size()[2]),
                mode='replicate')
            return mask * mix, aux1 * mix, aux2 * mix
        else:
            return mask# * mix

    def predict_mask(self, x: Tensor) -> Tensor:
        mask = cast(Tensor, self.forward(x))

        if self.offset > 0:
            end = -self.offset
            mask = cast(Tensor, mask)[:, :, :, self.offset:end]

        return mask
