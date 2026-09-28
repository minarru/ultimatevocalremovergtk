"""Lockstep multi-track playback on one GStreamer pipeline.

Every track is decoded continuously into one ``audiomixer``; only the selected
branch has volume 1.0, so switching is instant and sample-aligned. Tracks are
screened with ``GstPbutils.Discoverer`` first: a branch that fails mid-stream
would stall the mixer, so unreadable files never join the pipeline.

This is the only module that imports GStreamer, and it does so lazily.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Callable, Protocol, Sequence

from gi.repository import GLib

from core.debug_log import log_event

if TYPE_CHECKING:
    from gi.repository import Gst

    from core.listening import Track

_REQUIRED_FACTORIES = (
    "uridecodebin",
    "audioconvert",
    "audioresample",
    "capsfilter",
    "volume",
    "audiomixer",
    "autoaudiosink",
)
_POSITION_INTERVAL_MS = 100
_DEFAULT_RATE = 44100
_SECOND = 1_000_000_000


@functools.cache
def playback_unavailable_reason() -> str | None:
    """``None`` when playback works, else a short user-facing reason (cached)."""
    try:
        import gi

        gi.require_version("Gst", "1.0")
        gi.require_version("GstPbutils", "1.0")
        from gi.repository import Gst, GstPbutils  # noqa: F401
    except (ImportError, ValueError) as exc:
        reason = f"GStreamer is not installed ({exc})"
        log_event("playback", "unavailable", reason=reason)
        return reason
    ok, _argv = Gst.init_check(None)
    if not ok:
        reason = "GStreamer failed to initialise"
        log_event("playback", "unavailable", reason=reason)
        return reason
    missing = [name for name in _REQUIRED_FACTORIES if Gst.ElementFactory.find(name) is None]
    if missing:
        reason = "Missing GStreamer plugins: " + ", ".join(missing)
        log_event("playback", "unavailable", reason=reason)
        return reason
    return None


class PlaybackControls(Protocol):
    on_position: Callable[[float], None]
    on_duration: Callable[[float], None]
    on_state: Callable[[bool], None]
    on_track_error: Callable[[int, str], None]
    on_error: Callable[[str], None]

    @property
    def playing(self) -> bool: ...
    @property
    def duration(self) -> float: ...
    @property
    def position(self) -> float: ...
    @property
    def selected(self) -> int: ...
    @property
    def loaded(self) -> bool: ...
    def load(
        self, tracks: Sequence[Track], *, selected: int = 0, position: float = 0.0
    ) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def toggle(self) -> None: ...
    def seek(self, seconds: float) -> None: ...
    def select(self, index: int) -> None: ...
    def unload(self) -> None: ...


def _noop(*_args: object) -> None:
    return None


class PlaybackEngine:
    """One pipeline per loaded :class:`~core.listening.ComparisonSet`."""

    def __init__(
        self,
        *,
        sink_factory: Callable[[], Gst.Element] | None = None,
        discover_timeout: float = 3.0,
    ) -> None:
        self.on_position: Callable[[float], None] = _noop
        self.on_duration: Callable[[float], None] = _noop
        self.on_state: Callable[[bool], None] = _noop
        self.on_track_error: Callable[[int, str], None] = _noop
        self.on_error: Callable[[str], None] = _noop
        self._sink_factory = sink_factory
        self._discover_timeout = discover_timeout
        self._pipeline: Gst.Pipeline | None = None
        self._bus: Gst.Bus | None = None
        self._volumes: dict[int, Gst.Element] = {}
        self._selected = 0
        self._playing = False
        self._at_end = False
        self._prerolled = False
        self._pending_seek: float | None = None
        self._duration = 0.0
        self._timer: int | None = None

    # -- state ---------------------------------------------------------------

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def selected(self) -> int:
        return self._selected

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    @property
    def position(self) -> float:
        if self._pipeline is None:
            return 0.0
        from gi.repository import Gst

        ok, value = self._pipeline.query_position(Gst.Format.TIME)
        return value / _SECOND if ok and value >= 0 else 0.0

    def _volumes_for_test(self) -> dict[int, float]:
        return {i: float(v.get_property("volume")) for i, v in self._volumes.items()}

    # -- loading -------------------------------------------------------------

    def load(self, tracks: Sequence[Track], *, selected: int = 0, position: float = 0.0) -> None:
        self.unload()
        # Initialises GStreamer (cached) — callers must not have to do it first.
        reason = playback_unavailable_reason()
        if reason is not None:
            self._fail(reason)
            return
        from gi.repository import Gst, GstPbutils

        discoverer = GstPbutils.Discoverer.new(int(self._discover_timeout * _SECOND))
        playable: list[tuple[int, str]] = []
        rates: list[int] = []
        for index, track in enumerate(tracks):
            try:
                uri = Gst.filename_to_uri(track.path)
                if uri is None:
                    raise GLib.Error("Invalid file path")
                info = discoverer.discover_uri(uri)
            except GLib.Error as exc:
                self._track_failed(index, exc.message)
                continue
            streams = info.get_audio_streams()
            if not streams:
                self._track_failed(index, "No audio stream")
                continue
            rates.append(streams[0].get_sample_rate())
            playable.append((index, uri))
        if not playable:
            self._fail("No playable tracks")
            return

        pipeline = Gst.Pipeline.new("uvr-compare")
        mixer = Gst.ElementFactory.make("audiomixer")
        out_convert = Gst.ElementFactory.make("audioconvert")
        sink = (
            self._sink_factory()
            if self._sink_factory is not None
            else Gst.ElementFactory.make("autoaudiosink")
        )
        if mixer is None or out_convert is None or sink is None:
            self._fail("Missing GStreamer elements")
            return
        # The mixer fixes its format from the first branch to negotiate, so pin one
        # shared format up front; each branch converts into it before mixing.
        rate = max((r for r in rates if r > 0), default=_DEFAULT_RATE)
        mix_caps = Gst.Caps.from_string(
            f"audio/x-raw,format=F32LE,layout=interleaved,rate={rate},channels=2"
        )
        for element in (mixer, out_convert, sink):
            pipeline.add(element)
        mixer.link(out_convert)
        out_convert.link(sink)

        for index, uri in playable:
            decode = Gst.ElementFactory.make("uridecodebin")
            convert = Gst.ElementFactory.make("audioconvert")
            resample = Gst.ElementFactory.make("audioresample")
            volume = Gst.ElementFactory.make("volume")
            caps = Gst.ElementFactory.make("capsfilter")
            if (
                decode is None
                or convert is None
                or resample is None
                or volume is None
                or caps is None
            ):
                self._fail("Missing GStreamer elements")
                return
            decode.set_property("uri", uri)
            caps.set_property("caps", mix_caps)
            for element in (decode, convert, resample, caps, volume):
                pipeline.add(element)
            convert.link(resample)
            resample.link(caps)
            caps.link(volume)
            volume.link(mixer)
            decode.connect("pad-added", self._on_pad_added, convert)
            self._volumes[index] = volume

        self._pipeline = pipeline
        self._selected = selected if selected in self._volumes else min(self._volumes)
        self._apply_volumes()
        self._pending_seek = position if position > 0 else None
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)
        self._bus = bus
        pipeline.set_state(Gst.State.PAUSED)
        log_event("playback", "load", tracks=len(tracks), playable=len(playable))

    @staticmethod
    def _on_pad_added(_decode: Gst.Element, pad: Gst.Pad, convert: Gst.Element) -> None:
        caps = pad.get_current_caps() or pad.query_caps(None)
        if not caps.to_string().startswith("audio/"):
            return
        sink_pad = convert.get_static_pad("sink")
        if sink_pad is not None and not sink_pad.is_linked():
            pad.link(sink_pad)

    # -- transport -----------------------------------------------------------

    def play(self) -> None:
        if self._pipeline is None:
            return
        from gi.repository import Gst

        if self._at_end:
            self._at_end = False
            self.seek(0.0)
        self._pipeline.set_state(Gst.State.PLAYING)
        self._set_playing(True)

    def pause(self) -> None:
        if self._pipeline is None:
            return
        from gi.repository import Gst

        self._pipeline.set_state(Gst.State.PAUSED)
        self._set_playing(False)
        self.on_position(self.position)

    def toggle(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def seek(self, seconds: float) -> None:
        if self._pipeline is None:
            return
        target = max(0.0, seconds)
        if self._duration > 0:
            target = min(target, self._duration)
        if not self._prerolled:
            self._pending_seek = target
            return
        from gi.repository import Gst

        self._at_end = False
        self._pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
            int(target * _SECOND),
        )
        self.on_position(target)

    def select(self, index: int) -> None:
        if index not in self._volumes:
            return
        self._selected = index
        self._apply_volumes()

    def unload(self) -> None:
        self._stop_timer()
        pipeline, self._pipeline = self._pipeline, None
        if self._bus is not None:
            self._bus.remove_signal_watch()
            self._bus = None
        if pipeline is not None:
            from gi.repository import Gst

            pipeline.set_state(Gst.State.NULL)
        self._volumes = {}
        self._prerolled = False
        self._pending_seek = None
        self._duration = 0.0
        self._at_end = False
        if self._playing:
            self._playing = False
            self.on_state(False)

    # -- internals -----------------------------------------------------------

    def _apply_volumes(self) -> None:
        for index, volume in self._volumes.items():
            volume.set_property("volume", 1.0 if index == self._selected else 0.0)

    def _set_playing(self, playing: bool) -> None:
        if playing == self._playing:
            return
        self._playing = playing
        if playing:
            self._start_timer()
        else:
            self._stop_timer()
        self.on_state(playing)

    def _start_timer(self) -> None:
        if self._timer is None:
            self._timer = GLib.timeout_add(_POSITION_INTERVAL_MS, self._tick)

    def _stop_timer(self) -> None:
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self) -> bool:
        if self._pipeline is None:
            self._timer = None
            return GLib.SOURCE_REMOVE
        self.on_position(self.position)
        return GLib.SOURCE_CONTINUE

    def _track_failed(self, index: int, message: str) -> None:
        log_event("playback", "track_error", index=index, error=message)
        self.on_track_error(index, message)

    def _fail(self, message: str) -> None:
        log_event("playback", "error", level="error", error=message)
        self.unload()
        self.on_error(message)

    def _on_message(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        from gi.repository import Gst

        if self._pipeline is None:
            return
        kind = message.type
        if kind == Gst.MessageType.ASYNC_DONE and not self._prerolled:
            self._prerolled = True
            ok, value = self._pipeline.query_duration(Gst.Format.TIME)
            self._duration = value / _SECOND if ok and value > 0 else 0.0
            self.on_duration(self._duration)
            if self._pending_seek is not None:
                pending, self._pending_seek = self._pending_seek, None
                self.seek(pending)
        elif kind == Gst.MessageType.EOS:
            self._pipeline.set_state(Gst.State.PAUSED)
            self._at_end = True
            self._set_playing(False)
            self.on_position(self._duration)
        elif kind == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            self._fail(error.message or "Playback failed")


__all__ = ["PlaybackControls", "PlaybackEngine", "playback_unavailable_reason"]
