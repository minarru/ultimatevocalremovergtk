"""Ensemble Mode GTK surface.

GTK4 / libadwaita port of UVR's Ensemble Mode, embedded as a page in the main
window's tab view. :class:`EnsemblePage` builds the ensemble option groups in
the shared responsive two-column layout and runs the ensemble (combining outputs
through :class:`core.Ensembler`) using the main window's shared console,
progress bar and Start/Stop controls.
"""

from .window import EnsemblePage

__all__ = ["EnsemblePage"]
