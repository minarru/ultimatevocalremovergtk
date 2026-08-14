"""Headless command-line front end for Ultimate Vocal Remover GTK.

A presentation layer, exactly like :mod:`ui`: it drives the Tk-free backend in
:mod:`core` and nothing in ``core`` may import it. Unlike :mod:`ui`, this
package pins no GI versions and must stay importable without GTK, torch or
onnxruntime present.
"""
