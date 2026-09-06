"""GPU cache cleanup after inference."""
from bundled.constants import is_macos
from core.gpu_backend import clear_torch_cache


def clear_gpu_cache(backend_name: str | None = None):
    if backend_name is None:
        for name in ("mps", "cuda", "directml"):
            clear_torch_cache(is_macos=is_macos, backend_name=name)
    else:
        clear_torch_cache(is_macos=is_macos, backend_name=backend_name)
