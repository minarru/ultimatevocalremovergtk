###
# Author: Kai Li
# Date: 2021-06-17 23:08:32
# LastEditors: Please set LastEditors
# LastEditTime: 2022-05-26 18:06:22
###
from __future__ import annotations

from os import PathLike
from typing import Any

import torch
import torch.nn as nn
from core.torch_checkpoint import load_torch_checkpoint

#from huggingface_hub import PyTorchModelHubMixin


def _unsqueeze_to_3d(x: torch.Tensor) -> torch.Tensor:
    """Normalize shape of `x` to [batch, n_chan, time]."""
    if x.ndim == 1:
        return x.reshape(1, 1, -1)
    elif x.ndim == 2:
        return x.unsqueeze(1)
    else:
        return x


def pad_to_appropriate_length(x: torch.Tensor, lcm: int) -> torch.Tensor:
    values_to_pad = int(x.shape[-1]) % lcm
    if values_to_pad:
        appropriate_shape = x.shape
        padded_x = torch.zeros(
            list(appropriate_shape[:-1])
            + [appropriate_shape[-1] + lcm - values_to_pad],
            dtype=torch.float32,
        ).to(x.device)
        padded_x[..., : x.shape[-1]] = x
        return padded_x
    return x


class BaseModel(nn.Module):
    def __init__(self, sample_rate: int, in_chan: int = 1) -> None:
        super().__init__()
        self._sample_rate = sample_rate
        self._in_chan = in_chan

    def forward(self, *args: Any, **kwargs: Any) -> torch.Tensor:
        raise NotImplementedError

    def sample_rate(self,) -> int:
        return self._sample_rate

    @staticmethod
    def load_state_dict_in_audio(model: nn.Module, pretrained_dict: dict[str, torch.Tensor]) -> nn.Module:
        model_dict = model.state_dict()
        update_dict: dict[str, torch.Tensor] = {}
        prefix = "audio_model."
        for k, v in pretrained_dict.items():
            if not k.startswith(prefix):
                continue
            key = k[len(prefix) :]
            # Skip training-only extras / deeper layers so a near-match
            # checkpoint cannot introduce unexpected keys into state_dict.
            if key in model_dict:
                update_dict[key] = v
        model_dict.update(update_dict)
        model.load_state_dict(model_dict)
        return model

    @staticmethod
    def from_pretrain(
        pretrained_model_conf_or_path: str | PathLike[str], *args: Any, **kwargs: Any
    ) -> BaseModel:
        from . import get

        conf = load_torch_checkpoint(
            pretrained_model_conf_or_path, map_location="cpu"
        )  # Attempt to find the model and instantiate it.

        if not isinstance(conf, dict):
            raise TypeError(
                f"Apollo checkpoint must be a dict, got {type(conf).__name__}"
            )

        state_dict = conf.get("state_dict")
        if not isinstance(state_dict, dict):
            raise KeyError("state_dict")

        model_name = conf.get("model_name")
        if model_name:
            # UVR / look2hear serialized envelope: bare weights + class name.
            model_class = get(model_name)
            model = model_class(*args, **kwargs)
            model.load_state_dict(state_dict)
            return model

        # PyTorch Lightning training checkpoint (epoch/global_step/…). Weights
        # are stored under ``audio_model.*``; build Apollo from yaml params.
        model = get("Apollo")(*args, **kwargs)
        loaded = BaseModel.load_state_dict_in_audio(model, state_dict)
        assert isinstance(loaded, BaseModel)
        return loaded

    def serialize(self) -> dict[str, Any]:
        import pytorch_lightning as pl  # Not used in torch.hub

        model_conf = dict(
            model_name=self.__class__.__name__,
            state_dict=self.get_state_dict(),
            model_args=self.get_model_args(),
        )
        # Additional infos
        infos = dict()
        infos["software_versions"] = dict(
            torch_version=torch.__version__,
            pytorch_lightning_version=getattr(pl, "__version__", "unknown"),
        )
        model_conf["infos"] = infos
        return model_conf

    def get_state_dict(self) -> dict[str, torch.Tensor]:
        """In case the state dict needs to be modified before sharing the model."""
        return self.state_dict()

    def get_model_args(self) -> dict[str, Any]:
        """Should return args to re-instantiate the class."""
        raise NotImplementedError
