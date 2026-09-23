"""VR Architecture method view."""

import typing

from gi.repository import Adw

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
    layout_name = "vr_method"

    def list_models(self):
        return self.context.repo.list_vr_models()

    def build_options(self, group: typing.Any):
        self.add_option_scale(
            group,
            "window_size",
            None,
            values=VR_WINDOW,
            hint=WINDOW_SIZE_HELP,
            row=self._layout_object("window_size_row", Adw.ActionRow),
        )
        self.add_option_scale(
            group,
            "aggression_setting",
            None,
            lower=0,
            upper=max(VR_AGGRESSION),
            step=1,
            hint=AGGRESSION_SETTING_HELP,
            row=self._layout_object("aggression_setting_row", Adw.ActionRow),
        )

    def build_advanced(self, group: typing.Any):
        self.add_option_scale(
            group,
            "batch_size",
            None,
            values=BATCH_SIZE,
            hint=BATCH_SIZE_HELP,
            row=self._layout_object("batch_size_row", Adw.ActionRow),
        )
        self.add_option_scale(
            group,
            "crop_size",
            None,
            values=VR_CROP,
            hint=CROP_SIZE_HELP,
            row=self._layout_object("crop_size_row", Adw.ActionRow),
        )
        self.add_option_scale(
            group,
            "post_process_threshold",
            None,
            values=POST_PROCESSES_THREASHOLD_VALUES,
            hint=POST_PROCESS_THREASHOLD_HELP,
            row=self._layout_object("post_process_threshold_row", Adw.ActionRow),
        )
        self.add_option_switch(
            group,
            "is_tta",
            None,
            hint=IS_TTA_HELP,
            row=self._layout_object("is_tta_row", Adw.SwitchRow),
        )
        self.add_option_switch(
            group,
            "is_post_process",
            None,
            hint=IS_POST_PROCESS_HELP,
            row=self._layout_object("is_post_process_row", Adw.SwitchRow),
        )
        self.add_option_switch(
            group,
            "is_high_end_process",
            None,
            hint=IS_HIGH_END_PROCESS_HELP,
            row=self._layout_object("is_high_end_process_row", Adw.SwitchRow),
        )
