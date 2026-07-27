# Model options sheet rework — design

Date: 2026-07-27
Status: approved (design), pending implementation plan

## Problem

The global model-options sheet (`ui/model_options/sheet.py`) is a hand-built
`Adw.Dialog` with three architecture tabs (VR, MDX-Net, Demucs). Four things
work badly:

1. **Sizing.** The sheet tracks the parent window's width and resizes to match
   it (`_sync_from_parent_width` + a surface `notify::width` handler). A modal
   options sheet has no reason to be as wide as the main window, and the
   machinery is ~45 lines that also drags in `parent_window_width`, which
   contains a live GTK4 bug (see "Out of scope").
2. **Columns.** `build_columns_box()` is homogeneous, so the "Inference" group
   sits beside "Extra models" at equal width regardless of content. Row counts
   are lopsided: **VR has 6 inference rows, Demucs 4, MDX-Net 2**, while the
   right column always holds 3 expanders (4 for Demucs) plus a maintenance row.
   The MDX-Net tab renders two rows next to four.
3. **Applicability signalling.** Non-applicable architectures are marked with a
   dim `Gtk.Label` subtitle per page, and ensemble context with a second dim
   `Gtk.Label` banner. Both are bare labels styled `dim-label` — they read as
   incidental prose, not as state, and they are inconsistent with the real
   `Adw.Banner` used elsewhere in the window.
4. **Disclosure.** The three expanders ("Secondary models", "Pre-process model",
   "Vocal splitter and deverb") are collapsed and titled only. Nothing indicates
   whether a section is on or what it is configured to do without opening it.

## Decisions taken

Gathered before design (recorded here so the plan does not relitigate them):

- Scope is **one rework**, covering layout, clarity, and information
  architecture together.
- Non-applicable architectures **keep their tabs** and stay editable — the sheet
  is also how a user pre-configures an architecture before switching to it.
  Inactive ones must be *obviously* inactive.
- The container stays an **`Adw.Dialog`**. No promotion to a window, no
  `Adw.PreferencesDialog`, **no search**.
- Disclosure is **live state subtitles plus auto-expand of enabled sections**.
- "Change model defaults" gets its **own group at the bottom of each tab**.
- The layout is **single column at every width** (see §2 for the rationale;
  a width-conditional split was considered and rejected).

## Design

### 1. Container and proportions

Keep `Adw.Dialog` → `Adw.ToolbarView` → `Adw.HeaderBar` with the switcher as
the header title widget. Change:

- **Width is capped at 760px and does not track the parent.** Delete
  `_sync_from_parent_width`, `_start_width_tracking`, `_stop_width_tracking`,
  `_last_parent_width`, `_surface_handler`, `_parent_map_handler`, and the
  `present()` call to `configure_dialog_width`. The `closed` handler loses its
  only job and is removed with them.
- **Height follows content**, bounded to 90% of the parent's allocated height.
  Replaces the fixed `_SHEET_WIDE_HEIGHT = 560`. When the parent height is
  unavailable (unrealized, or 0), fall back to the current 560.
- Constants `_SHEET_WIDE_WIDTH`, `_SHEET_WIDE_HEIGHT` and `_NARROW_BREAKPOINT`
  are replaced by `_SHEET_WIDTH = 760`, `_SHEET_FALLBACK_HEIGHT = 560` and
  `_SHEET_MAX_HEIGHT_FRACTION = 0.9`.

Consequence worth stating: the sheet stops calling `parent_window_width`, so it
no longer reaches the `get_default_width()` crash path. That bug still exists
for `ui/errorlog.py` and `ui/download.py` and is **not** fixed here.

### 2. Single-column layout

Each tab page becomes a `Gtk.ScrolledWindow` wrapping an `Adw.Clamp`
(`maximum-size` 700, `tightening-threshold` 600) containing a vertical
`Gtk.Box` of the three groups in order:

```
Inference
Extra models
Model maintenance
```

`build_columns_box` / `set_columns_narrow` are no longer used by this file
(they remain in `ui/widgets/columns.py` for other callers), and
`_sync_narrow_layout`, `_tab_columns` and the `notify::content-width` handler
are deleted.

Rationale for single column at all widths, over a width-conditional split:

- A conditional split engages on wide screens, which is exactly where MDX-Net
  shows 2 rows beside 4 expanders. Gating on width hides the imbalance on small
  screens rather than fixing it.
- The groups are not peers. "Extra models" operates on the primary model's
  output; stacking expresses that order, side-by-side implies independence.
- §4 expands sections dynamically. In two columns, expanding a right-column row
  grows only that column and the page lurches asymmetrically.
- Every other settings surface in the app (Preferences) is single-column
  clamped, as are libadwaita preference pages generally.

Height cost is acceptable: the tallest tab (VR) is roughly 730px with all
expanders collapsed, which fits without scrolling on a maximized window at
1080p and scrolls slightly on a ~900px-tall window. MDX-Net is around 480px.

### 3. Applicability signalling

Replace both `Gtk.Label` mechanisms with real widgets.

**Ensemble context — badge counts.** Each `Adw.ViewStackPage` gets
`set_badge_number(n)` where `n` is that architecture's member count from the
existing `member_arch_counts()`. Zero clears the badge (`set_badge_number(0)`).
Verified available in the installed libadwaita 1.9.2.

**Separation context — a page banner.** Each non-applicable page gets an
`Adw.Banner` at the top of the page (above the scroller, inside the page box)
reading:

> Not used by this run — the active method is MDX-Net

with button label `Switch to VR Architecture`. The applicable page shows no
banner; absence means normal. The banner replaces the per-page `Gtk.Label`
subtitle (`_tab_subtitles`) entirely.

The sheet cannot switch the method itself — it holds only `parent`, `views`,
`views_by_stack` and `settings`, while a correct switch also needs
`_show_method()` and the method combo kept in sync. So `ModelOptionsSheet` and
`open_model_options_sheet` take a new optional callback
`on_switch_method: Callable[[str], None] | None`, receiving the target stack
name. `MainWindow` implements it by setting `method_row`'s value to that view's
title, which fires the existing `_on_method_selected` path
(`ui/window.py:822`) and does the whole job. After invoking the callback the
sheet calls its own `update_context` with the new active method so the banners
and default tab refresh in place; it does **not** close. When the callback is
`None` the banner is shown without a button.

**Ensemble standing explanation.** The dialog-level `_ensemble_banner`
`Gtk.Label` is deleted. Its text ("These settings apply to each member model by
architecture…") moves to the `Inference` group's `description`, where it is
context rather than an alert.

**Empty ensemble.** When ensemble context has no members at all, every page
shows an `Adw.Banner` reading "Select ensemble member models before editing
architecture-specific options." with no button, and pages stay insensitive as
today.

`applicability.py` changes: `applicability_subtitle` is replaced by
`applicability_banner(context, stack_name, *, active_method_key,
selected_models) -> tuple[str, str] | None` returning `(text, button_label)` or
`None` for "no banner". `ensemble_context_banner` is retained but its return
value is consumed as a group description. `member_arch_counts` is unchanged.
`ui/model_options/__init__.py` re-exports `applicability_subtitle`; that export
and `tests/test_model_options_applicability.py` change with it.

### 4. Live state disclosure

A new module `ui/model_options/summaries.py` holds pure functions over a
settings mapping, with no GTK import, so they are unit-testable headlessly:

```python
def secondary_models_summary(settings, prefix: str) -> str
def preproc_summary(settings) -> str
def vocal_split_summary(settings) -> str
```

Each returns a one-line subtitle. Conventions:

- Every activate switch in the section off → `"Off"`.
- On, but the model it needs is unset (`NO_MODEL`) → `"On — no model selected"`.
- On and configured → a compact description, e.g. for secondary models
  `"Vocals/Instrumental: UVR-MDX-NET Inst HQ 3 (0.90)"`, with multiple
  configured stem pairs joined by `" · "`.

`vocal_split_summary` covers **two independent switches** in one expander
(`is_set_vocal_splitter` and `is_deverb_vocals`). It returns `"Off"` only when
both are off; otherwise it joins the enabled halves with `" · "`, e.g.
`"UVR-BVE-4B · deverb: Main vocals"`, or `"deverb: Main vocals"` when only
deverb is on.

`ui/views/base.py` applies them: after building each expander, set its subtitle
from the matching summary, and re-apply on each activate switch's
`notify::active` and on the section's model combos' `notify::selected`. A new
`_sync_expander_summaries()` method does the whole pass; it is called at the end
of `MethodView.load()` (`ui/views/base.py:376`, beside the existing
`_sync_switch_dependents()` call) so a settings reload refreshes subtitles.
Views without a given section (`secondary_prefix` unset, `has_preproc` false)
skip it — the method guards on the expander attribute existing.

**Auto-expand:** when any of a section's activate switches is on, its expander
opens. This happens in `_sync_expander_summaries()` — **expand only, never
auto-collapse**, so a section the user opened by hand is never shut on them.
Because it runs from `load()`, auto-expand applies on sheet open and after a
settings reload, not on every switch toggle.

Keys consumed, per existing schema (`prefix` is `vr` / `mdx` / `demucs`):

| Section | Activate key | Detail keys |
|---|---|---|
| Secondary models | `{prefix}_is_secondary_model_activate` | `{prefix}_{slot}_secondary_model`, `{prefix}_{slot}_secondary_model_scale` for slot in `voc_inst`, `other`, `bass`, `drums` |
| Pre-process model | `is_demucs_pre_proc_model_activate` | `demucs_pre_proc_model`, `is_demucs_pre_proc_model_inst_mix` |
| Vocal splitter and deverb | `is_set_vocal_splitter`, `is_deverb_vocals` | `set_vocal_splitter`, `is_save_inst_set_vocal_splitter`, `deverb_vocal_opt` |

No new settings keys are introduced.

### 5. Model maintenance group

`_build_secondary_section` in `ui/views/base.py` currently appends the
"Change model defaults" `Adw.ActionRow` to `secondary_group`. Move it into a
new `self.maintenance_group = Adw.PreferencesGroup(title="Model maintenance")`,
appended to `self.groups` after `secondary_group`. The sheet reparents all three
groups per tab. The row keeps its existing `CLEAR_CACHE_HELP` hint and
`_on_change_defaults` handler.

The group stays per-architecture — it edits that architecture's stored model
parameters — but stops presenting as a fourth "extra model".

## Files

| File | Change |
|---|---|
| `ui/model_options/sheet.py` | shell rework; net smaller |
| `ui/model_options/summaries.py` | **new** — pure state summarisers |
| `ui/model_options/applicability.py` | `applicability_banner` replaces `applicability_subtitle`; badge counts consumed by the sheet |
| `ui/views/base.py` | `maintenance_group`; expander subtitles + auto-expand; expose expanders |
| `tests/test_model_options_summaries.py` | **new** — headless summariser tests |
| `tests/test_model_options_applicability.py` | update for `applicability_banner` |
| `tests/` (sheet) | badge numbers, banner presence/absence, single-column structure |

## Testing

- **Headless (no display):** every function in `summaries.py`, and
  `applicability_banner` across the three contexts × three stacks × empty and
  populated member lists. These are the bulk of the coverage.
- **GTK-guarded** (`@unittest.skipUnless(DISPLAY or WAYLAND_DISPLAY)`, with
  `gi.require_version` in `setUpClass`): sheet constructs; each tab page has
  exactly one clamped column; badge numbers match `member_arch_counts`; the
  non-applicable page carries a banner and the applicable one does not;
  an enabled section's expander is expanded after a context update.
- The existing suite (694 tests) must stay green.

## Error handling

- Parent height unavailable → fall back to `_SHEET_FALLBACK_HEIGHT`; no
  exception, no tracking handler to leak.
- A settings key missing from the mapping → summariser reads it via
  `settings.get(key, default)` and degrades to `"Off"` / `"On — no model
  selected"` rather than raising. `SettingsModel` backfills missing keys from
  defaults on load, so this is defence in depth.
- `Adw.ViewStackPage.set_badge_number` is guarded with `hasattr` in the same
  style as the existing `Adw.InlineViewSwitcher` fallback, so an older
  libadwaita degrades to no badges rather than crashing.

## Out of scope

- **`ui/dialogs/utils.py:80` calls `parent.get_default_width()`**, which does
  not exist on `Gtk.Window` in GTK4 (`get_default_size` does). It raises
  `AttributeError` whenever `parent.get_width() <= 1`. This rework removes the
  sheet's two call sites, but `ui/errorlog.py:135` and `ui/download.py:409,490`
  still reach it. Needs its own fix.
- The fixed-width 360px log panel (item 6 of the earlier UI audit), explicitly
  excluded by the user.
- Search within the sheet.
- Any change to what the settings mean or how engines consume them.
