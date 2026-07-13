"""Legacy shim — use :mod:`ml.bandit_spectral` instead."""

from ml.bandit_spectral import SpectralComponent as _SpectralComponent

__all__ = ["_SpectralComponent"]
