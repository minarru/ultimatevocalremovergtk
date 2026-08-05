"""SCNet music source separation (ported from MSST / UVR community configs)."""

from ml.scnet_src.scnet import SCNet
from ml.scnet_src.scnet_masked import SCNetMasked
from ml.scnet_src.separation import SeparationNet

__all__ = ["SCNet", "SCNetMasked", "SeparationNet"]
