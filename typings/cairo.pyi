from typing import Any

FORMAT_ARGB32: int

class ImageSurface:
    def __init__(self, format: int, width: int, height: int) -> None: ...

class Context:
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
