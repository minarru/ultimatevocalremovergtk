"""Build browser records for GTK adapter fixtures that manually construct rows."""

from dataclasses import replace
from typing import Any

from ui.catalogue_browser import BrowserRow
from ui.widget_state import fetch, stash


def seed_browser_row(window: Any, row: Any, arch: str | None = None):
    arch = str(arch or fetch(row, '_uvr_arch', '') or '')
    name = fetch(row, '_uvr_model_name', '') or fetch(row, '_uvr_sort_name', '')
    stash(row, '_uvr_arch', arch)
    stash(row, '_uvr_model_name', name)
    reason = (
        fetch(row, '_uvr_unsupported_reason', '') if fetch(row, '_uvr_unsupported', False) else None
    )
    data = BrowserRow(
        (arch, name),
        fetch(row, '_uvr_display_name', '') or fetch(row, '_uvr_sort_name', ''),
        fetch(row, '_uvr_network', '') or arch,
        reason=reason,
        sdr=fetch(row, '_uvr_sdr', None),
    )
    if hasattr(window, 'manager'):
        projected = window._project_browser_row(arch, name, reason)
        data = replace(
            data,
            intent=projected.intent,
            primary_role=projected.primary_role,
            output_roles=projected.output_roles,
        )
    window.browser.rows[data.key] = data
    return data


def seed_browser_sources(window: Any):
    rows = [
        window._project_browser_row(arch, name)
        for arch, names in window.browser.available.items()
        for name in names
    ]
    rows.extend(
        window._project_browser_row(arch, name, reason)
        for arch, pairs in window.browser.unsupported.items()
        for name, reason in pairs
    )
    window.browser.replace_rows(rows)
