from typing import Any, Callable, Optional

class _Object:
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    def __getattr__(self, name: str) -> Any: ...


class _GIType(type):
    def __getattr__(cls, name: str) -> Any: ...


class Gtk(metaclass=_GIType):
    INVALID_LIST_POSITION: int


class Adw(metaclass=_GIType): ...


class Gio(metaclass=_GIType): ...


class GLib(metaclass=_GIType):
    SOURCE_REMOVE: bool
    SOURCE_CONTINUE: bool

    class Error(BaseException):
        message: str

    @staticmethod
    def idle_add(func: Callable[..., Any], *args: Any, **kwargs: Any) -> int: ...

    @staticmethod
    def timeout_add(interval_ms: int, func: Callable[..., Any], *args: Any) -> int: ...

    @staticmethod
    def source_remove(source_id: int) -> None: ...

    @staticmethod
    def markup_escape_text(text: str) -> str: ...


class Gdk(metaclass=_GIType): ...


class Pango(metaclass=_GIType): ...

# Common annotation targets referenced across the GTK layer.
GtkWidget = _Object
AdwWidget = _Object
