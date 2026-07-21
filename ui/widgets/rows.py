"""Small helpers around ``Adw.ComboRow`` / ``Adw.SwitchRow``.

The Tk UI binds dozens of option menus and checkbuttons directly to
``tk.StringVar`` / ``tk.BooleanVar``. These helpers provide the equivalent for
libadwaita rows: build a combo backed by a ``Gtk.StringList`` and read/write the
selected value as the plain string the :class:`~core.settings.SettingsModel`
expects (mirroring how Tk stores every option as a string).
"""

from typing import Iterable, List, Optional, Sequence

from gi.repository import Adw, Gdk, Gtk, Pango

_ICON_LOOKUP_FLAGS = Gtk.IconLookupFlags.FORCE_SYMBOLIC


def image_from_icon_name(icon_name: str, size: int = 16) -> Gtk.Image:
    """Build a ``Gtk.Image`` for a themed symbolic icon.

    ``Gtk.Image.new_from_icon_name`` does not resolve GResource-backed icons in
    GTK 4, so look up via ``Gtk.IconTheme`` and attach the paintable instead.
    """
    image = Gtk.Image()
    display = Gdk.Display.get_default()
    if display is not None:
        theme = Gtk.IconTheme.get_for_display(display)
        if theme.has_icon(icon_name):
            paintable = theme.lookup_icon(
                icon_name,
                None,
                size,
                1,
                Gtk.TextDirection.LTR,
                _ICON_LOOKUP_FLAGS,
            )
            if paintable is not None:
                image.set_from_paintable(paintable)
                return image
    image.set_from_icon_name(icon_name)
    return image


def _apply_icon_name(image: Gtk.Image, icon_name: str, size: int = 16) -> None:
    display = Gdk.Display.get_default()
    if display is not None:
        theme = Gtk.IconTheme.get_for_display(display)
        if theme.has_icon(icon_name):
            paintable = theme.lookup_icon(
                icon_name,
                None,
                size,
                1,
                Gtk.TextDirection.LTR,
                _ICON_LOOKUP_FLAGS,
            )
            if paintable is not None:
                image.set_from_paintable(paintable)
                return
    image.set_from_icon_name(icon_name)


def add_row_icon(row, icon_name: str) -> None:
    """Add a leading symbolic ``icon_name`` prefix to an ``Adw`` row."""
    row.add_prefix(image_from_icon_name(icon_name))


def set_row_icon(row, icon_name: Optional[str]) -> None:
    """Set or clear the leading icon on an ``Adw`` row (updates in place)."""
    image = getattr(row, "_uvr_row_icon", None)
    if not icon_name:
        if image is not None:
            image.unparent()
            row._uvr_row_icon = None
        return
    if image is None:
        image = image_from_icon_name(icon_name)
        row.add_prefix(image)
        row._uvr_row_icon = image
    else:
        _apply_icon_name(image, icon_name)


def make_combo_row(
    title: str,
    values: Iterable,
    subtitle: Optional[str] = None,
    icon_name: Optional[str] = None,
) -> Adw.ComboRow:
    """Build an ``Adw.ComboRow`` whose model is the stringified ``values``."""
    row = Adw.ComboRow(title=title)
    if subtitle:
        row.set_subtitle(subtitle)
    if icon_name:
        add_row_icon(row, icon_name)
    set_combo_values(row, values)
    return row


def use_wrapping_list(row: Adw.ComboRow) -> None:
    """Make an ``Adw.ComboRow`` show full, non-truncated values.

    Two changes, both aimed at long entries such as model names:

    * the *popover* list items wrap (``WORD_CHAR``) instead of ellipsizing, so
      every option is fully readable; and
    * the *selected* value is shown on the row's full-width subtitle line
      (``set_use_subtitle``) rather than the narrow, right-aligned value label
      that truncates long names. A name expression is required because a custom
      list factory is in use.

    Search is also enabled here: model pickers are the long lists where a
    filter box pays off, and the same ``string`` expression used for display
    drives the search matching.
    """
    factory = Gtk.SignalListItemFactory()

    def on_setup(_factory, item):
        label = Gtk.Label(xalign=0.0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        item.set_child(label)

    def on_bind(_factory, item):
        item.get_child().set_label(item.get_item().get_string())

    factory.connect("setup", on_setup)
    factory.connect("bind", on_bind)
    row.set_list_factory(factory)

    row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
    if hasattr(row, "set_enable_search"):
        row.set_enable_search(True)
    # Default PREFIX matching misses mid-name queries like "Vocal" in "Kim Vocal 2".
    if hasattr(row, "set_search_match_mode"):
        row.set_search_match_mode(Gtk.StringFilterMatchMode.SUBSTRING)
    row.set_use_subtitle(True)
    # Allow the value subtitle to wrap onto multiple lines for very long names.
    if hasattr(row, "set_subtitle_lines"):
        row.set_subtitle_lines(0)


def set_combo_values(row: Adw.ComboRow, values: Iterable) -> None:
    """Replace the row's model with ``values`` (coerced to strings)."""
    if hasattr(row, "_uvr_combo_ids"):
        del row._uvr_combo_ids
    model = Gtk.StringList()
    for value in values:
        model.append(str(value))
    row.set_model(model)


def set_combo_tag_values(row: Adw.ComboRow, items: Iterable) -> None:
    """Populate a combo with ``[(stored_id, display_label), ...]`` or plain strings."""
    ids: List[str] = []
    labels: List[str] = []
    for item in items:
        if isinstance(item, tuple):
            stored, display = item
            ids.append(str(stored))
            labels.append(str(display))
        else:
            text = str(item)
            ids.append(text)
            labels.append(text)
    row._uvr_combo_ids = ids
    model = Gtk.StringList()
    for label in labels:
        model.append(label)
    row.set_model(model)


def combo_values(row: Adw.ComboRow) -> List[str]:
    model = row.get_model()
    return [model.get_string(i) for i in range(model.get_n_items())]


def set_combo_value(row: Adw.ComboRow, value) -> bool:
    """Select the item matching ``value``; returns ``True`` when found."""
    target = str(value)
    ids = getattr(row, "_uvr_combo_ids", None)
    model = row.get_model()
    if ids:
        for index, stored in enumerate(ids):
            if stored == target:
                row.set_selected(index)
                return True
    for index in range(model.get_n_items()):
        if model.get_string(index) == target:
            row.set_selected(index)
            return True
    return False


def get_combo_value(row: Adw.ComboRow) -> Optional[str]:
    index = row.get_selected()
    if index == Gtk.INVALID_LIST_POSITION:
        return None
    ids = getattr(row, "_uvr_combo_ids", None)
    if ids:
        return ids[index]
    return row.get_model().get_string(index)


def make_switch_row(
    title: str,
    subtitle: Optional[str] = None,
    icon_name: Optional[str] = None,
) -> Adw.SwitchRow:
    row = Adw.SwitchRow(title=title)
    if subtitle:
        row.set_subtitle(subtitle)
    if icon_name:
        add_row_icon(row, icon_name)
    return row


_SCALE_WIDTH = 120
_VALUE_LABEL_WIDTH = 64


def _snap_to_step(value: float, lower: float, step: float) -> float:
    if step <= 0:
        return value
    steps = round((value - lower) / step)
    return lower + steps * step


def _update_scale_value(row: Adw.ActionRow) -> None:
    """Refresh the value label beside the slider."""
    values = getattr(row, "_uvr_values", None)
    scale = row._uvr_scale
    label = row._uvr_value_label
    if values:
        index = int(round(scale.get_value()))
        index = max(0, min(len(values) - 1, index))
        label.set_label(values[index])
        return
    digits = getattr(row, "_uvr_digits", 0)
    if digits:
        label.set_label(f"{scale.get_value():.{digits}f}")
    else:
        label.set_label(str(int(round(scale.get_value()))))


def _make_scale_row(
    title: str,
    *,
    subtitle: Optional[str] = None,
    icon_name: Optional[str] = None,
) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title)
    if subtitle:
        row.set_subtitle(subtitle)
    if icon_name:
        add_row_icon(row, icon_name)

    suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    suffix.set_halign(Gtk.Align.FILL)
    suffix.set_hexpand(True)
    # Minimum footprint (slider min + value label); the slider flexes to fill
    # any extra width on wide layouts and yields it back to the title when narrow.
    suffix.set_size_request(_SCALE_WIDTH + _VALUE_LABEL_WIDTH, -1)
    suffix.add_css_class("uvr-scale-suffix")

    value_label = Gtk.Label(xalign=1.0)
    value_label.set_width_chars(7)
    value_label.set_max_width_chars(10)
    value_label.set_ellipsize(Pango.EllipsizeMode.END)
    value_label.add_css_class("dim-label")
    suffix.append(value_label)

    scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL)
    scale.set_draw_value(False)
    scale.set_hexpand(True)
    scale.set_halign(Gtk.Align.FILL)
    scale.set_size_request(_SCALE_WIDTH, -1)
    suffix.append(scale)
    row.add_suffix(suffix)
    row._uvr_scale = scale
    row._uvr_value_label = value_label
    row._uvr_values = None
    row._uvr_digits = 0
    row._uvr_store_float = False

    def on_changed(*_args):
        values = row._uvr_values
        if values:
            index = int(round(scale.get_value()))
            index = max(0, min(len(values) - 1, index))
            if index != scale.get_value():
                scale.set_value(index)
        else:
            adj = scale.get_adjustment()
            snapped = _snap_to_step(scale.get_value(), adj.get_lower(), adj.get_step_increment())
            if abs(snapped - scale.get_value()) > 1e-9:
                scale.set_value(snapped)
        _update_scale_value(row)

    scale.connect("value-changed", on_changed)
    return row


def _configure_adjustment(
    adjustment: Gtk.Adjustment,
    *,
    lower: float,
    upper: float,
    step: float = 1,
    value: Optional[float] = None,
) -> None:
    """Reconfigure a ``Gtk.Adjustment`` with valid page-size bounds."""
    if value is None:
        value = adjustment.get_value()
    value = max(lower, min(upper, float(value or lower)))
    page_increment = max(step, (upper - lower) / 10) if upper > lower else step
    adjustment.configure(value, lower, upper, step, page_increment, 0)


def make_discrete_scale_row(
    title: str,
    values: Sequence,
    subtitle: Optional[str] = None,
    icon_name: Optional[str] = None,
) -> Adw.ActionRow:
    """Build a slider that snaps to one of the stringified ``values``."""
    choices = [str(value) for value in values]
    row = _make_scale_row(title, subtitle=subtitle, icon_name=icon_name)
    row._uvr_values = choices
    adjustment = Gtk.Adjustment(
        lower=0,
        upper=max(0, len(choices) - 1),
        step_increment=1,
        page_increment=1,
    )
    row._uvr_scale.set_adjustment(adjustment)
    row._uvr_scale.set_digits(0)
    _update_scale_value(row)
    return row


def make_numeric_scale_row(
    title: str,
    lower: float,
    upper: float,
    *,
    step: float = 1,
    digits: int = 0,
    subtitle: Optional[str] = None,
    icon_name: Optional[str] = None,
) -> Adw.ActionRow:
    """Build a constrained slider for a numeric range."""
    row = _make_scale_row(title, subtitle=subtitle, icon_name=icon_name)
    row._uvr_digits = digits
    adjustment = Gtk.Adjustment(
        lower=lower,
        upper=upper,
        step_increment=step,
        page_increment=max(step, (upper - lower) / 10 if upper > lower else step),
    )
    row._uvr_scale.set_adjustment(adjustment)
    row._uvr_scale.set_digits(digits)
    _update_scale_value(row)
    return row


def set_scale_default_mark(
    row: Adw.ActionRow,
    default,
    *,
    position=Gtk.PositionType.BOTTOM,
    label: Optional[str] = None,
) -> None:
    """Place a tick mark at the scale's default value (index or numeric)."""
    scale = getattr(row, "_uvr_scale", None)
    if scale is None:
        return
    row._uvr_default = default
    row._uvr_default_label = label
    scale.clear_marks()
    if default is None:
        return
    values = getattr(row, "_uvr_values", None)
    if values:
        target = str(default)
        for index, choice in enumerate(values):
            if choice == target:
                scale.add_mark(float(index), position, label)
                return
        return
    try:
        scale.add_mark(float(default), position, label)
    except (TypeError, ValueError):
        return


def refresh_scale_default_mark(row: Adw.ActionRow) -> None:
    """Re-apply ``row._uvr_default`` after a scale is reconfigured."""
    default = getattr(row, "_uvr_default", None)
    if default is not None:
        set_scale_default_mark(
            row,
            default,
            label=getattr(row, "_uvr_default_label", None),
        )


def reconfigure_discrete_scale(row: Adw.ActionRow, values: Sequence) -> None:
    """Replace the allowed values on a discrete scale row."""
    choices = [str(value) for value in values]
    row._uvr_values = choices
    upper = max(0, len(choices) - 1)
    _configure_adjustment(row._uvr_scale.get_adjustment(), lower=0, upper=upper, step=1)
    current = get_scale_row_value(row) or choices[0]
    set_scale_row_value(row, current)
    _update_scale_value(row)
    refresh_scale_default_mark(row)


def reconfigure_numeric_scale(
    row: Adw.ActionRow,
    lower: float,
    upper: float,
    *,
    step: float = 1,
    digits: int = 0,
) -> None:
    """Replace the numeric range on a scale row."""
    row._uvr_values = None
    row._uvr_digits = digits
    _configure_adjustment(row._uvr_scale.get_adjustment(), lower=lower, upper=upper, step=step)
    row._uvr_scale.set_digits(digits)
    _update_scale_value(row)
    refresh_scale_default_mark(row)


def get_scale_row_value(row: Adw.ActionRow) -> Optional[str]:
    """Read the settings string for a scale row."""
    values = getattr(row, "_uvr_values", None)
    scale = row._uvr_scale
    if values:
        index = int(round(scale.get_value()))
        index = max(0, min(len(values) - 1, index))
        return values[index]
    digits = getattr(row, "_uvr_digits", 0)
    value = scale.get_value()
    if digits:
        return f"{value:.{digits}f}"
    return str(int(round(value)))


def get_scale_row_float(row: Adw.ActionRow) -> float:
    """Read the slider's current numeric value."""
    return row._uvr_scale.get_value()


def set_scale_row_value(row: Adw.ActionRow, value) -> bool:
    """Set a scale row from a stored settings value."""
    if value is None:
        return False
    values = getattr(row, "_uvr_values", None)
    scale = row._uvr_scale
    if values:
        target = str(value)
        for index, choice in enumerate(values):
            if choice == target:
                scale.set_value(index)
                _update_scale_value(row)
                return True
        scale.set_value(0)
        _update_scale_value(row)
        return False
    try:
        scale.set_value(float(value))
    except (TypeError, ValueError):
        return False
    _update_scale_value(row)
    return True


def set_scale_row_float(row: Adw.ActionRow, value: float) -> None:
    row._uvr_scale.set_value(value)
    _update_scale_value(row)
