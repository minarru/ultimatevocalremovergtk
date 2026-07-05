"""Audio Tools GTK surface.

GTK4 / libadwaita port of UVR's Audio Tools mode, embedded as a page in the main
window's tab view. :class:`AudioToolsPage` builds the tool selector, the per-tool
option stack and the shared output options in the responsive two-column layout,
and runs the selected tool through :class:`core.audio_tools.AudioToolRunner`
using the main window's shared console, progress bar and Start/Stop controls. The
dual/batch input editor used by the align/matchering tools lives in
:mod:`ui.audio_tools.dual_batch`.
"""

from .window import AudioToolsPage

__all__ = ["AudioToolsPage"]
