"""Set user-provided strings on ``Adw`` rows as plain text (not Pango markup)."""


def set_row_title(row, text: str) -> None:
    """Set a row title without interpreting ``&``, ``<``, etc. as markup."""
    if hasattr(row, "set_use_markup"):
        row.set_use_markup(False)
    row.set_title(text or "")


def set_row_subtitle(row, text: str) -> None:
    """Set a row subtitle without interpreting ``&``, ``<``, etc. as markup."""
    if hasattr(row, "set_use_markup"):
        row.set_use_markup(False)
    row.set_subtitle(text or "")
