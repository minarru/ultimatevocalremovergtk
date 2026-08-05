"""About dialog (``Adw.AboutDialog`` / ``Adw.AboutWindow``) for UVR.

A summary of the application reusing UVR's version, developers, license and
links. This dialog also carries the credits, resources, license and changelog
content that previously lived in the standalone Help & Info guide, surfaced
through ``Adw.AboutDialog``'s native sections (credits/acknowledgements, links,
the Legal page and the release notes).

Entry point: :func:`open_about`.
"""
import typing

from gi.repository import Adw, GLib, Gtk

from bundled.constants import DONATE_LINK_BMAC, FORK_ISSUE_URL, LICENSE_TEXT
from core import paths

from . import APP_ID

try:
    from __version__ import UPSTREAM_BASE, VERSION
except Exception:  # pragma: no cover
    VERSION = "v1.0.0"
    UPSTREAM_BASE = "v5.6.0"

CHANGE_LOG = paths.CHANGE_LOG_PATH

# Upstream AI code authors. Formatted as "Name URL" so libadwaita renders the
# trailing URL as a clickable link in the credit section.
_AI_CODE_AUTHORS = [
    "Tsurumeso https://github.com/tsurumeso/vocal-remover",
    "Kuielab & Woosung Choi https://github.com/kuielab",
    "Adefossez & Demucs https://github.com/facebookresearch/demucs",
]

_SPECIAL_THANKS = [
    "DilanBoskan",
    "Audio Separation & CC Karaoke & Friends Discord Communities",
]

# (title, url) - external resources. The official GitHub is the dialog's
# ``website`` already, so it is intentionally not duplicated here.
_RESOURCE_LINKS = [
    ("X-Minus AI", "https://x-minus.pro/ai"),
    ("MVSep", "https://mvsep.com/quality_checker/leaderboard.php"),
    ("FFmpeg", "https://www.wikihow.com/Install-FFmpeg-on-Windows"),
    ("Rubber Band Library", "https://breakfastquay.com/rubberband/"),
    ("Matchering", "https://github.com/sergree/matchering"),
]


def _read_change_log() -> str:
    try:
        with open(CHANGE_LOG, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def _changelog_to_markup(text: str) -> str:
    """Convert the plain-text changelog into the markup subset Adw allows.

    ``Adw.AboutDialog`` release notes only accept ``<p>``/``<ul>``/``<li>``/
    ``<em>``/``<code>`` and reject ``<br>`` and raw ``&``/``<``. Each non-empty
    line is escaped and wrapped in its own paragraph; blank lines are dropped
    (they act as paragraph breaks).
    """
    paragraphs = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        paragraphs.append(f"<p>{GLib.markup_escape_text(stripped)}</p>")
    return "".join(paragraphs)


def _enrich_about(about: typing.Any) -> None:
    """Apply credits/resources/license/changelog to an about dialog/window.

    The same setters exist on both ``Adw.AboutDialog`` and ``Adw.AboutWindow``.
    """
    about.set_support_url(DONATE_LINK_BMAC)
    about.set_designers(["Bas Curtiz"])

    about.add_credit_section("AI Architecture Code", _AI_CODE_AUTHORS)
    about.add_acknowledgement_section("Special Thanks", _SPECIAL_THANKS)

    for title, url in _RESOURCE_LINKS:
        about.add_link(title, url)

    about.set_license_type(Gtk.License.CUSTOM)
    about.set_license(LICENSE_TEXT(VERSION, UPSTREAM_BASE))

    notes = _changelog_to_markup(_read_change_log())
    if notes:
        about.set_release_notes(notes)
        about.set_release_notes_version(VERSION or "")


def open_about(parent_window: typing.Any):
    """Open an About dialog summarising UVR. Wire this to a ``win.about`` action."""
    from .resources import ensure_application_icon, register_gresources

    register_gresources()
    # application_icon=APP_ID below only resolves once this has run.
    ensure_application_icon()

    # Heterogeneous by nature: this bag is splatted into two different
    # constructors below, and dict() would otherwise unify str and list[str]
    # into a union that matches neither signature.
    kwargs: dict[str, typing.Any] = dict(
        application_name="Ultimate Vocal Remover",
        application_icon=APP_ID,
        version=VERSION or "v1.0.0",
        comments="A GUI for vocal/instrumental separation using state-of-the-art AI models.",
        website="https://github.com/minarru/ultimatevocalremovergtk",
        issue_url=FORK_ISSUE_URL,
        developer_name="Anjok07 & Aufr33",
        developers=["Anjok07", "Aufr33", "DilanBoskan"],
        copyright="\u00a9 2022 Ultimate Vocal Remover",
    )

    # Adw.AboutDialog is the modern API (libadwaita 1.5+); fall back to
    # Adw.AboutWindow on older runtimes.
    if hasattr(Adw, "AboutDialog"):
        about = Adw.AboutDialog(**kwargs)
        _enrich_about(about)
        about.present(parent_window)
    else:
        about = Adw.AboutWindow(transient_for=parent_window, **kwargs)
        _enrich_about(about)
        about.present()
    return about
