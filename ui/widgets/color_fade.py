"""Cross-fade a window from its previous frame after a color scheme change."""

from __future__ import annotations

import typing
from typing import Protocol, runtime_checkable

from gi.repository import Adw, Gdk, GLib, Gsk, Gtk

from core.debug_log import log_event

FADE_DURATION_MS = 250
# Restyling a window for a new scheme can stall a frame for longer than the
# whole fade, so a single frame never advances it by more than this.
_MAX_FRAME_STEP_US = 33_000


class ColorFade:
    """Draw the previous frame over ``widget`` and fade it out.

    The owner renders its own contents into a separate ``Gtk.Snapshot`` and
    passes the node to :meth:`draw`. GTK does not keep a toplevel's render
    node, so ``Gtk.WidgetPaintable`` can return an empty image for a window.
    Nothing is captured when animations are disabled.
    """

    def __init__(self, widget: Gtk.Widget):
        self._widget = widget
        self._last_frame: Gsk.RenderNode | None = None
        self._image: Gsk.RenderNode | None = None
        self._alpha = 0.0
        self._elapsed_us = 0
        self._last_frame_us: int | None = None
        self._tick_id = 0
        self._frames = 0
        self._draws = 0

    @property
    def active(self) -> bool:
        return self._image is not None

    def begin(self) -> None:
        widget = self._widget
        mapped = widget.get_mapped()
        animations = Adw.get_enable_animations(widget)
        image = self._with_background(self._last_frame)
        if not mapped or not animations or image is None:
            log_event(
                "ui",
                "color_fade_skipped",
                mapped=mapped,
                animations=animations,
                has_frame=image is not None,
            )
            self._finish()
            return
        self._image = image
        self._alpha = 1.0
        self._elapsed_us = 0
        self._last_frame_us = None
        self._frames = 0
        self._draws = 0
        if not self._tick_id:
            self._tick_id = widget.add_tick_callback(self._on_tick)
        log_event("ui", "color_fade_begin", node=image.get_node_type().value_nick)
        widget.queue_draw()

    def _with_background(self, frame: Gsk.RenderNode | None) -> Gsk.RenderNode | None:
        """Put the widget's CSS background under ``frame``.

        GTK draws a widget's background outside ``do_snapshot``, so the
        recorded frame lacks it; this runs before the new scheme is applied.
        """
        if frame is None:
            return None
        widget = self._widget
        background = Gtk.Snapshot()
        # GTK 4 deprecated StyleContext and the render_* helpers in 4.10 but
        # offers no other way to paint a widget's CSS background; both remain
        # until GTK 5.
        background.render_background(
            widget.get_style_context(), 0, 0, widget.get_width(), widget.get_height()
        )
        node = background.to_node()
        if node is None:
            return frame
        return Gsk.ContainerNode.new([node, frame])

    def draw(self, snapshot: Gtk.Snapshot, contents: Gsk.RenderNode | None) -> None:
        """Append ``contents`` and, during a fade, the previous frame over it."""
        frame = contents
        if self._image is not None and self._alpha > 0.0:
            self._draws += 1
            composite = Gtk.Snapshot()
            if contents is not None:
                composite.append_node(contents)
            composite.push_opacity(self._alpha)
            composite.append_node(self._image)
            composite.pop()
            frame = composite.to_node()
        if frame is not None:
            snapshot.append_node(frame)
        # Keep what is on screen, mid-fade included, so a scheme change during
        # a fade starts from the blend the user sees.
        self._last_frame = frame

    def _on_tick(self, widget: Gtk.Widget, clock: Gdk.FrameClock) -> bool:
        now = clock.get_frame_time()
        if self._last_frame_us is not None:
            self._elapsed_us += min(now - self._last_frame_us, _MAX_FRAME_STEP_US)
        self._last_frame_us = now
        self._frames += 1
        progress = min(1.0, self._elapsed_us / (FADE_DURATION_MS * 1000))
        if progress >= 1.0:
            self._tick_id = 0
            self._finish()
            return GLib.SOURCE_REMOVE
        # Ease out: the old frame leaves quickly, then settles.
        self._alpha = (1.0 - progress) ** 2
        widget.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _finish(self) -> None:
        if self._tick_id:
            self._widget.remove_tick_callback(self._tick_id)
            self._tick_id = 0
        if self._image is not None:
            log_event("ui", "color_fade_end", frames=self._frames, draws=self._draws)
            self._image = None
            self._alpha = 0.0
            self._widget.queue_draw()


@runtime_checkable
class FadesColors(Protocol):
    def begin_color_fade(self) -> None: ...


def begin_color_fades() -> None:
    """Start the color fade on every open window that supports one."""
    toplevels = Gtk.Window.get_toplevels()
    for index in range(toplevels.get_n_items()):
        window = toplevels.get_item(index)
        if isinstance(window, FadesColors):
            window.begin_color_fade()


class FadingWindow(Adw.Window):
    """``Adw.Window`` that cross-fades on a color scheme change.

    Blueprints use it as ``$UvrFadingWindow``; import this module before
    loading them so the type is registered.
    """

    __gtype_name__ = "UvrFadingWindow"

    def __init__(self, **kwargs: typing.Any):
        super().__init__(**kwargs)
        self._color_fade = ColorFade(self)

    def begin_color_fade(self) -> None:
        self._color_fade.begin()

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        frame = Gtk.Snapshot()
        Adw.Window.do_snapshot(self, frame)
        self._color_fade.draw(snapshot, frame.to_node())
