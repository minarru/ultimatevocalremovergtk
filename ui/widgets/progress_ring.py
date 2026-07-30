"""Circular progress ring with finish morph (Nautilus ProgressPaintable)."""

from __future__ import annotations
import typing

from typing import TYPE_CHECKING, Optional

from gi.repository import Adw, Gdk, Gtk

from ui.widgets.download_queue_icons import (
    ICON_CHIP_CANCELLED,
    ICON_CHIP_FAILED,
    ICON_CHIP_PARTIAL,
    ICON_CHIP_SUCCESS,
)

if TYPE_CHECKING:
    from ui.widgets.download_queue_indicator import ChipRingState

# Bundled symbolic icons are authored at 16px; chip ring renders at 18px.
RING_ICON_SIZE = 16
RING_SIZE = 18
DISPLAY_PIXEL_SIZE = RING_SIZE
_RING_SCALE = RING_SIZE / RING_ICON_SIZE
RING_STROKE_WIDTH = 2.0 * _RING_SCALE
RING_ARC_RADIUS = 7.0 * _RING_SCALE

MORPH_OUTCOMES = {
    "success": ICON_CHIP_SUCCESS,
    "cancelled": ICON_CHIP_CANCELLED,
    "partial": ICON_CHIP_PARTIAL,
    "failed": ICON_CHIP_FAILED,
}


class ProgressRing(Gtk.Overlay):
    """18px symbolic ring that crossfades into a terminal icon when finished."""

    def __init__(self) -> None:
        super().__init__()
        self._progress = 0.0
        self._check_progress = 0.0
        self._icon_name = ICON_CHIP_SUCCESS
        self._outcome = "active"
        self._done_animation: Optional[Adw.TimedAnimation] = None

        self._draw_area = Gtk.DrawingArea()
        self._draw_area.set_content_width(RING_SIZE)
        self._draw_area.set_content_height(RING_SIZE)
        self._draw_area.set_draw_func(self._on_draw, None)

        self.set_size_request(RING_SIZE, RING_SIZE)
        self.add_css_class("uvr-progress-ring")

        self._icon = Gtk.Image()
        self._icon.set_pixel_size(DISPLAY_PIXEL_SIZE)
        self._icon.set_halign(Gtk.Align.CENTER)
        self._icon.set_valign(Gtk.Align.CENTER)
        self._icon.set_opacity(0.0)

        self.set_child(self._draw_area)
        self.add_overlay(self._icon)
        self._set_icon_name(ICON_CHIP_SUCCESS)

    def _set_icon_name(self, icon_name: str) -> None:
        """Load the symbolic icon (always call Gtk, not only when the name changes)."""
        self._icon_name = icon_name
        self._icon.set_from_icon_name(icon_name)

    def update_from_state(self, state: ChipRingState) -> None:
        was_morph = self._outcome in MORPH_OUTCOMES
        previous_outcome = self._outcome
        self._outcome = state.outcome
        self._progress = max(0.0, min(1.0, state.progress))

        if state.outcome in MORPH_OUTCOMES:
            icon_name = MORPH_OUTCOMES[state.outcome]
            self._set_icon_name(icon_name)
            if not was_morph or previous_outcome != state.outcome:
                self._clear_animation()
                self._animate_done()
            elif self._done_animation is None and self._check_progress < 1.0:
                self._set_check_progress(1.0)
        else:
            self._set_icon_name(ICON_CHIP_SUCCESS)
            self._check_progress = 0.0
            self._icon.set_opacity(0.0)
            self._draw_area.set_opacity(1.0)
            self._clear_animation()

        self._draw_area.queue_draw()

    def _clear_animation(self) -> None:
        anim = self._done_animation
        self._done_animation = None
        if anim is not None:
            try:
                anim.pause()
            except (AttributeError, TypeError):
                pass

    def _on_anim_value(self, value: float, _user_data: typing.Any=None) -> None:
        if value is None:
            return
        self._set_check_progress(float(value))

    def _set_check_progress(self, value: float) -> None:
        progress = max(0.0, min(1.0, float(value)))
        self._check_progress = progress
        self._draw_area.set_opacity(max(0.0, 1.0 - progress))
        self._icon.set_opacity(progress)
        self._draw_area.queue_draw()

    def _on_animation_done(self, _animation: Adw.TimedAnimation) -> None:
        if self._done_animation is not _animation:
            return
        self._clear_animation()
        self._set_check_progress(1.0)

    def _animate_done(self) -> None:
        if self._done_animation is not None:
            return
        self._set_check_progress(0.0)
        target = Adw.CallbackAnimationTarget.new(self._on_anim_value)
        animation = Adw.TimedAnimation.new(self, 0.0, 1.0, 500, target)
        animation.set_easing(Adw.Easing.EASE_IN_OUT_CUBIC)
        animation.connect("done", self._on_animation_done)
        self._done_animation = animation
        animation.play()

    def _on_draw(
        self,
        _area: Gtk.DrawingArea,
        cr: typing.Any,
        width: float,
        height: float,
        _user_data: typing.Any,
    ) -> None:
        if (self._check_progress or 0.0) >= 1.0:
            return

        style = self._draw_area.get_style_context()
        colors = style.get_color()

        arc_end = self._progress * 3.141592653589793 * 2.0 - 3.141592653589793 / 2.0
        line_width = RING_STROKE_WIDTH
        radius = RING_ARC_RADIUS

        cr.save()
        cr.translate(width / 2.0, height / 2.0)
        cr.set_line_width(line_width)
        cr.set_source_rgba(colors.red, colors.green, colors.blue, colors.alpha)
        cr.arc(0, 0, radius, -3.141592653589793 / 2.0, arc_end)
        cr.stroke()

        dim = Gdk.RGBA()
        dim.red = colors.red
        dim.green = colors.green
        dim.blue = colors.blue
        dim.alpha = colors.alpha * 0.25
        cr.set_source_rgba(dim.red, dim.green, dim.blue, dim.alpha)
        cr.arc(0, 0, radius, arc_end, 3.0 * 3.141592653589793 / 2.0)
        cr.stroke()
        cr.restore()
