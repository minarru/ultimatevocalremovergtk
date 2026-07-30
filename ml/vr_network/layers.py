from __future__ import annotations

from collections.abc import Sequence

import torch
from torch import Tensor, nn
import torch.nn.functional as F

from ml import spec_utils

ActivFactory = type[nn.Module]
PadDilation = int | tuple[int, int]


class Conv2DBNActiv(nn.Module):

    def __init__(
        self,
        nin: int,
        nout: int,
        ksize: int = 3,
        stride: int = 1,
        pad: PadDilation = 1,
        dilation: PadDilation = 1,
        activ: ActivFactory = nn.ReLU,
    ) -> None:
        super(Conv2DBNActiv, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(
                nin, nout,
                kernel_size=ksize,
                stride=stride,
                padding=pad,
                dilation=dilation,
                bias=False),
            nn.BatchNorm2d(nout),
            activ()
        )

    def __call__(self, x: Tensor) -> Tensor:
        return self.conv(x)

class SeperableConv2DBNActiv(nn.Module):

    def __init__(
        self,
        nin: int,
        nout: int,
        ksize: int = 3,
        stride: int = 1,
        pad: PadDilation = 1,
        dilation: PadDilation = 1,
        activ: ActivFactory = nn.ReLU,
    ) -> None:
        super(SeperableConv2DBNActiv, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(
                nin, nin,
                kernel_size=ksize,
                stride=stride,
                padding=pad,
                dilation=dilation,
                groups=nin,
                bias=False),
            nn.Conv2d(
                nin, nout,
                kernel_size=1,
                bias=False),
            nn.BatchNorm2d(nout),
            activ()
        )

    def __call__(self, x: Tensor) -> Tensor:
        return self.conv(x)


class Encoder(nn.Module):

    def __init__(
        self,
        nin: int,
        nout: int,
        ksize: int = 3,
        stride: int = 1,
        pad: int = 1,
        activ: ActivFactory = nn.LeakyReLU,
    ) -> None:
        super(Encoder, self).__init__()
        self.conv1 = Conv2DBNActiv(nin, nout, ksize, 1, pad, activ=activ)
        self.conv2 = Conv2DBNActiv(nout, nout, ksize, stride, pad, activ=activ)

    def __call__(self, x: Tensor) -> tuple[Tensor, Tensor]:
        skip = self.conv1(x)
        h = self.conv2(skip)

        return h, skip


class Decoder(nn.Module):

    def __init__(
        self,
        nin: int,
        nout: int,
        ksize: int = 3,
        stride: int = 1,
        pad: int = 1,
        activ: ActivFactory = nn.ReLU,
        dropout: bool = False,
    ) -> None:
        super(Decoder, self).__init__()
        self.conv = Conv2DBNActiv(nin, nout, ksize, 1, pad, activ=activ)
        self.dropout = nn.Dropout2d(0.1) if dropout else None

    def __call__(self, x: Tensor, skip: Tensor | None = None) -> Tensor:
        x = F.interpolate(x, scale_factor=2, mode='bilinear', align_corners=True)
        if skip is not None:
            skip = spec_utils.crop_center(skip, x)
            x = torch.cat([x, skip], dim=1)
        h = self.conv(x)

        if self.dropout is not None:
            h = self.dropout(h)

        return h


class ASPPModule(nn.Module):

    def __init__(
        self,
        nn_architecture: int,
        nin: int,
        nout: int,
        dilations: Sequence[int] = (4, 8, 16),
        activ: ActivFactory = nn.ReLU,
    ) -> None:
        super(ASPPModule, self).__init__()
        self.conv1 = nn.Sequential(
            nn.AdaptiveAvgPool2d((1, None)),
            Conv2DBNActiv(nin, nin, 1, 1, 0, activ=activ)
        )
        
        self.nn_architecture = nn_architecture
        self.six_layer = [129605]
        self.seven_layer = [537238, 537227, 33966]
        
        extra_conv = SeperableConv2DBNActiv(
            nin, nin, 3, 1, dilations[2], dilations[2], activ=activ)
        
        self.conv2 = Conv2DBNActiv(nin, nin, 1, 1, 0, activ=activ)
        self.conv3 = SeperableConv2DBNActiv(
            nin, nin, 3, 1, dilations[0], dilations[0], activ=activ)
        self.conv4 = SeperableConv2DBNActiv(
            nin, nin, 3, 1, dilations[1], dilations[1], activ=activ)
        self.conv5 = SeperableConv2DBNActiv(
            nin, nin, 3, 1, dilations[2], dilations[2], activ=activ)
        
        if self.nn_architecture in self.six_layer:
            self.conv6 = extra_conv
            nin_x = 6
        elif self.nn_architecture in self.seven_layer:
            self.conv6 = extra_conv
            self.conv7 = extra_conv
            nin_x = 7
        else:
            nin_x = 5
            
        self.bottleneck = nn.Sequential(
            Conv2DBNActiv(nin * nin_x, nout, 1, 1, 0, activ=activ),
            nn.Dropout2d(0.1)
        )

    def forward(self, x: Tensor) -> Tensor:
        _, _, h, w = x.size()
        feat1 = F.interpolate(self.conv1(x), size=(h, w), mode='bilinear', align_corners=True)
        feat2 = self.conv2(x)
        feat3 = self.conv3(x)
        feat4 = self.conv4(x)
        feat5 = self.conv5(x)
        
        if self.nn_architecture in self.six_layer:
            feat6 = self.conv6(x)
            out = torch.cat((feat1, feat2, feat3, feat4, feat5, feat6), dim=1)
        elif self.nn_architecture in self.seven_layer:
            feat6 = self.conv6(x)
            feat7 = self.conv7(x)
            out = torch.cat((feat1, feat2, feat3, feat4, feat5, feat6, feat7), dim=1)
        else:
            out = torch.cat((feat1, feat2, feat3, feat4, feat5), dim=1)
            
        bottle = self.bottleneck(out)
        return bottle
