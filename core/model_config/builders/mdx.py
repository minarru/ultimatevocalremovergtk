from __future__ import annotations

from typing import TYPE_CHECKING

from bundled.constants import (
    INST_STEM,
    VOCAL_STEM,
    secondary_stem,
)

from ... import paths
from .inputs import ModelBuildInputs

if TYPE_CHECKING:
    from ..config import ModelConfig
import hashlib
import os

from ...mdx_config_fetch import ensure_mdx_c_config
from ...model_data import (
    _mdx_c_primary_for_select,
    _mdx_c_secondary_for_pair,
    _mdx_c_training,
    load_mdx_c_config,
)


def build_mdx_options(model: ModelConfig, inputs: ModelBuildInputs) -> None:
    repo = inputs.repo
    is_secondary_model = inputs.is_secondary_model
    mdx = inputs.settings.mdx

    model.is_secondary_model_activated = (
        mdx.is_secondary_model_activate if not is_secondary_model else False
    )
    model.margin = int(mdx.margin)
    model.chunks = 0
    model.mdx_segment_size = int(mdx.segment_size)
    model.get_mdx_model_path()
    model.get_model_hash()
    if model.model_hash:
        model.model_hash_dir = os.path.join(paths.MDX_HASH_DIR, f"{model.model_hash}.json")
        if model.is_change_def:
            model.model_data = model.change_model_data()
        else:
            model.model_data = model.get_model_data(paths.MDX_HASH_DIR, repo.mdx_hash_MAPPER)
        if model.model_data:
            if "is_roformer" in model.model_data:
                model.is_roformer = model.model_data["is_roformer"]
            if "model_type" in model.model_data:
                model.model_type = str(model.model_data["model_type"])
            if "config_yaml" in model.model_data:
                model.is_mdx_c = True
                config_name = str(model.model_data["config_yaml"])
                model.mdx_config_yaml = os.path.basename(config_name)
                config_path = os.path.join(paths.MDX_C_CONFIG_PATH, config_name)
                if not os.path.isfile(config_path):
                    ensure_mdx_c_config(config_name)
                if os.path.isfile(config_path):
                    try:
                        from ml_collections import ConfigDict

                        with open(config_path, "rb") as config_file:
                            model.mdx_config_sha256 = hashlib.sha256(config_file.read()).hexdigest()
                        config = ConfigDict(load_mdx_c_config(config_path))
                    except ImportError:
                        # yaml / ml_collections are part of the (lazy) ML
                        # stack; without them an MDX-C model can't be
                        # configured, so treat it as unavailable here.
                        config = None
                    except Exception as exc:
                        from ...debug_log import debug

                        debug(
                            "model",
                            f"mdx_c_config load failed file={os.path.basename(config_path)} "
                            f"error={type(exc).__name__}: {exc}",
                        )
                        config = None
                    if config is None:
                        model.model_status = False
                    else:
                        model.mdx_c_configs = config
                        training = _mdx_c_training(model.mdx_c_configs)
                        target_instrument = (
                            getattr(training, "target_instrument", None)
                            if training is not None
                            else None
                        )
                        if target_instrument:
                            model.is_target_instrument = True
                            target = target_instrument
                            model.mdx_model_stems = [target]
                            # Odd yaml: target ``other`` is a clean
                            # instrumental extractor; complement is the
                            # acapella (all vocals), not ``No other``.
                            if str(target).casefold() == "other":
                                model.primary_stem_native = str(target)
                                model.primary_stem = INST_STEM
                                model.secondary_stem = VOCAL_STEM
                            else:
                                model.primary_stem = target
                                model.primary_stem_native = str(target)
                                model.secondary_stem = secondary_stem(str(model.primary_stem or ""))
                            if (
                                model.is_roformer
                                and model.is_ensemble_mode
                                and target in (VOCAL_STEM, INST_STEM)
                            ):
                                model.mdxnet_stem_select = model.ensemble_primary_stem
                        elif training is not None:
                            instruments = getattr(training, "instruments", None) or []
                            model.mdx_model_stems = list(instruments)
                            model.mdx_stem_count = len(model.mdx_model_stems)
                            if model.mdx_stem_count == 2:
                                model.primary_stem = model.mdx_model_stems[0]
                            else:
                                # ``mdx.stems`` is a global UI choice (often
                                # Instrumental/Vocals). 4-stem models only
                                # expose drums/bass/other/vocals — keep the
                                # selection when it exists, otherwise fall
                                # back so export never KeyErrors.
                                model.primary_stem = _mdx_c_primary_for_select(
                                    model.mdx_model_stems,
                                    model.mdxnet_stem_select,
                                )
                            model.primary_stem_native = str(model.primary_stem or "")
                            if model.is_ensemble_mode:
                                model.mdxnet_stem_select = model.ensemble_primary_stem
                            model.secondary_stem = secondary_stem(str(model.primary_stem or ""))
                            if model.mdx_stem_count == 2:
                                model.secondary_stem = _mdx_c_secondary_for_pair(
                                    model.mdx_model_stems,
                                    model.primary_stem,
                                    model.secondary_stem,
                                )
                        else:
                            model.secondary_stem = secondary_stem(str(model.primary_stem or ""))
                else:
                    model.model_status = False
            else:
                model.compensate = (
                    model.model_data["compensate"]
                    if mdx.compensate is None
                    else float(mdx.compensate)
                )
                model.mdx_dim_f_set = model.model_data["mdx_dim_f_set"]
                model.mdx_dim_t_set = model.model_data["mdx_dim_t_set"]
                model.mdx_n_fft_scale_set = model.model_data["mdx_n_fft_scale_set"]
                model.primary_stem = model.model_data["primary_stem"]
                model.primary_stem_native = model.model_data["primary_stem"]
                model.secondary_stem = secondary_stem(str(model.primary_stem or ""))
        else:
            model.model_status = False
