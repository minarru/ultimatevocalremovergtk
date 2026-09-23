from __future__ import annotations

from typing import TYPE_CHECKING

from bundled.constants import (
    WOOD_INST_MODEL_HASH,
    WOOD_INST_PARAMS,
    secondary_stem,
)

from ... import paths
from .inputs import ModelBuildInputs

if TYPE_CHECKING:
    from ..config import ModelConfig
import os


def build_vr_options(model: ModelConfig, inputs: ModelBuildInputs) -> None:
    repo = inputs.repo
    is_secondary_model = inputs.is_secondary_model
    vr = inputs.settings.vr

    model.is_secondary_model_activated = (
        vr.is_secondary_model_activate if not is_secondary_model else False
    )
    model.aggression_setting = float(int(vr.aggression_setting) / 100)
    model.is_tta = vr.is_tta
    model.is_post_process = vr.is_post_process
    model.window_size = int(vr.window_size)
    model.batch_size = 1 if vr.batch_size is None else int(vr.batch_size)
    model.crop_size = int(vr.crop_size)
    model.is_high_end_process = "mirroring" if vr.is_high_end_process else "None"
    model.post_process_threshold = float(vr.post_process_threshold)
    model.model_capacity = 32, 128
    model.get_vr_model_path()
    model.get_model_hash()
    if model.model_hash:
        model.model_hash_dir = os.path.join(paths.VR_HASH_DIR, f"{model.model_hash}.json")
        if model.is_change_def:
            model.model_data = model.change_model_data()
        else:
            model.model_data = (
                model.get_model_data(paths.VR_HASH_DIR, repo.vr_hash_MAPPER)
                if model.model_hash != WOOD_INST_MODEL_HASH
                else WOOD_INST_PARAMS
            )
        if model.model_data:
            from ml.vr_network.model_param_init import ModelParameters

            vr_model_param = os.path.join(
                paths.VR_PARAM_DIR, "{}.json".format(model.model_data["vr_model_param"])
            )
            model.primary_stem = model.model_data["primary_stem"]
            model.secondary_stem = secondary_stem(str(model.primary_stem or ""))
            model.vr_model_param = ModelParameters(vr_model_param)
            model.model_samplerate = model.vr_model_param.param["sr"]
            model.primary_stem_native = model.primary_stem
            if "nout" in model.model_data.keys() and "nout_lstm" in model.model_data.keys():
                model.model_capacity = model.model_data["nout"], model.model_data["nout_lstm"]
                model.is_vr_51_model = True
            model.check_if_karaokee_model()
        else:
            model.model_status = False
