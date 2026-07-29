"""VR Architecture method view."""
import typing

from bundled.constants import (
    AGGRESSION_SETTING_HELP,
    BATCH_SIZE,
    BATCH_SIZE_HELP,
    CROP_SIZE_HELP,
    IS_HIGH_END_PROCESS_HELP,
    IS_POST_PROCESS_HELP,
    IS_TTA_HELP,
    POST_PROCESS_THREASHOLD_HELP,
    POST_PROCESSES_THREASHOLD_VALUES,
    VR_AGGRESSION,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
    VR_CROP,
    VR_WINDOW,
    WINDOW_SIZE_HELP,
)

from .base import MethodView, register_method_view


@register_method_view
class VRView(MethodView):
    method_key = VR_ARCH_PM
    resolution_method_key = VR_ARCH_TYPE
    model_key = "vr_model"
    stack_name = "vr"
    title = "VR Architecture"
    secondary_prefix = "vr"

    def list_models(self):
        return self.context.repo.list_vr_models()

    def build_options(self, group: typing.Any):
        self.add_option_scale(group, "window_size", "Window size", values=VR_WINDOW, hint=WINDOW_SIZE_HELP)
        self.add_option_scale(
            group,
            "aggression_setting",
            "Aggression setting",
            lower=0,
            upper=max(VR_AGGRESSION),
            step=1,
            hint=AGGRESSION_SETTING_HELP,
        )

    def build_advanced(self, group: typing.Any):
        self.add_advanced_scale("batch_size", "Batch size", values=BATCH_SIZE, hint=BATCH_SIZE_HELP)
        self.add_advanced_scale("crop_size", "Crop size", values=VR_CROP, hint=CROP_SIZE_HELP)
        self.add_advanced_scale(
            "post_process_threshold",
            "Post-process threshold",
            values=POST_PROCESSES_THREASHOLD_VALUES,
            hint=POST_PROCESS_THREASHOLD_HELP,
        )
        self.add_advanced_switch("is_tta", "Enable TTA", hint=IS_TTA_HELP)
        self.add_advanced_switch("is_post_process", "Post-process", hint=IS_POST_PROCESS_HELP)
        self.add_advanced_switch("is_high_end_process", "High-end process", hint=IS_HIGH_END_PROCESS_HELP)
