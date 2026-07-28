# Model options sheet rework — design

Date: 2026-07-27
Status: approved (design), pending implementation plan

## Problem

The global model-options sheet (`ui/model_options/sheet.py`) is a hand-built
`Adw.Dialog` with three architecture tabs (VR, MDX-Net, Demucs). Five things
work badly:

1. **Sizing.** The sheet tracks the parent window's width and resizes to match
   it (`_sync_from_parent_width` + a surface `notify::width` handler). A modal
   options sheet has no reason to be as wide as the main window, and the
   machinery is ~45 lines that also drags in `parent_window_width`, which
   contains a live GTK4 bug (see "Out of scope").
2. **Columns.** `build_columns_box()` is homogeneous, so "Inference" sits beside
   "Extra models" at equal width regardless of content, at a 900px-wide dialog
   — two 440px columns with a canyon between them. Row counts are lopsided:
   **VR has 6 inference rows, Demucs 4, MDX-Net 2**, while the right column
   holds 3 expanders (4 for Demucs).
3. **Misplaced global settings.** The "Vocal splitter and deverb" expander is
   built unconditionally for every view (`ui/views/base.py:717-734`) but edits
   **unprefixed global keys** — `is_set_vocal_splitter`, `set_vocal_splitter`,
   `is_save_inst_set_vocal_splitter`, `is_deverb_vocals`, `deverb_vocal_opt`.
   It is therefore rendered three times over one set of values: changing it on
   the VR tab silently changes the MDX-Net and Demucs tabs. The code
   acknowledges this ("shared global options, surfaced per method") without
   resolving it.
4. **Applicability signalling.** Non-applicable architectures are marked with a
   dim `Gtk.Label` subtitle per page, and ensemble context with a second dim
   `Gtk.Label` banner. Both are bare labels styled `dim-label` — they read as
   incidental prose, not as state, and they are inconsistent with the real
   `Adw.Banner` used elsewhere in the window.
5. **Disclosure.** The expanders are collapsed and titled only. Nothing
   indicates whether a section is on, or what it is configured to do, without
   opening it. Secondary models in particular always shows four stem-pair slots
   (`voc_inst`, `other`, `bass`, `drums`) even when the primary model produces
   two stems and three of them are meaningless.

## Decisions taken

Gathered before design; the plan does not relitigate them.

- Scope is **one rework**, covering layout, clarity, and information
  architecture together.
- Non-applicable architectures **keep their tabs** and stay editable — the sheet
  is also how a user pre-configures an architecture before switching to it.
  Inactive ones must be *obviously* inactive.
- The container stays an **`Adw.Dialog`**. No promotion to a window, no
  `Adw.PreferencesDialog`, **no search**.
- Disclosure is **live state subtitles plus auto-expand of enabled sections**.
- "Change model defaults" gets its **own group at the bottom of each tab**.
- **Vocal splitter + deverb moves to the main view**, into the "Processing"
  option-row group.
- **Secondary models hides its non-applicable stem slots** whenever the run
  cannot reach the engine's four-source path.
- The sheet keeps **two columns**, fixed rather than removed (see §2).

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
  unavailable (unrealized, or 0), fall back to 560.
- Constants `_SHEET_WIDE_WIDTH`, `_SHEET_WIDE_HEIGHT` are replaced by
  `_SHEET_WIDTH = 760`, `_SHEET_FALLBACK_HEIGHT = 560` and
  `_SHEET_MAX_HEIGHT_FRACTION = 0.9`.

Consequence worth stating: the sheet stops calling `parent_window_width`, so it
no longer reaches the `get_default_width()` crash path. That bug still exists
for `ui/errorlog.py` and `ui/download.py` and is **not** fixed here.

### 2. Two non-homogeneous columns

The defect was never "two columns" — it was a *homogeneous* split at a *900px*
dialog. At the 760 cap with columns sized to their content, the layout is:

```
col_start            col_end
  Inference            Extra models
                       Model maintenance
```

`build_columns_box()` is replaced by a non-homogeneous equivalent for this
surface: `Gtk.Box(HORIZONTAL, spacing=18)` with both children `hexpand=True`
but `homogeneous=False`, so each column takes its natural width. Below ~700px
of content width the columns stack vertically (retaining the existing
`set_columns_narrow`-style behaviour, driven off `notify::content-width`).

`_NARROW_BREAKPOINT` becomes `_STACK_BREAKPOINT = 700`, matched to the sheet's
own width rather than the main window's 880sp.

**Why not single column.** The main window defaults to **1040×720**
(`ui/window.py:189-190`), leaving ~578px of dialog content height after the
header bar and insets. Single column would put VR at ~765px and Demucs at
~710px — both scrolling on open with nothing enabled, which is worse than the
status quo. Two columns fit every tab (see §7).

**Why not all-expanded-and-rearranged.** Fully expanding every section roughly
doubles content height (VR ~1480px, Demucs ~1600px). An `Adw.Dialog` cannot
exceed its parent, so 578px is a hard ceiling; no arrangement closes a 2.5×
gap, and three columns at a 760 cap gives ~240px each, too narrow for combo
rows carrying long model names. Reflowing groups between columns on expand
would also make them jump mid-interaction, and GTK has no masonry layout.
Collapsed-by-default is the mechanism that makes the sheet fit at all.

### 3. Vocal splitter and deverb moves to the main view

Remove the `voc_split_expander` construction from `_build_secondary_section`
in `ui/views/base.py` entirely. Add it instead to the **"Processing"
`Adw.PreferencesGroup`** on the two surfaces that run separations:

- `MainWindow._build_shared_group` (`ui/window.py:601`) — the Separation page
- `EnsembleWindow`'s equivalent (`ui/ensemble/window.py:366`)

Audio Tools does not run separations and does not get it.

Both surfaces edit the same global keys. This is the existing, correct pattern:
`OutputFormatRow` already appears in all three Processing groups editing the
same global `save_format`.

**Form.** One `Adw.ExpanderRow` titled "Vocal splitter and deverb", carrying
the live subtitle from §5, containing the five existing rows in their current
order:

| Row | Key | Type |
|---|---|---|
| Enable vocal split mode | `is_set_vocal_splitter` | switch |
| Vocal splitter model | `set_vocal_splitter` | model combo (karaoke list) |
| Save split vocal instrumentals | `is_save_inst_set_vocal_splitter` | switch |
| Deverb vocals | `is_deverb_vocals` | switch |
| Deverb vocal type | `deverb_vocal_opt` | combo (`DEVERB_MAPPER` keys) |

Collapsed it costs one row (~60px) on the main page — the scarcest real estate
in the app — and expands to five only on demand. The existing
`_bind_switch_dependents` dimming (splitter switch → model + save-inst rows;
deverb switch → deverb type row) is preserved.

**Where it is built.** Not as a factory over `MethodView`'s helpers. Those
helpers (`add_option_switch`, `add_option_combo`, `_add_model_combo`) register
each row in per-view registries — `_option_rows`, `_switch_rows`,
`_model_combos` — which `MethodView.load()` and `.save()` iterate for
persistence. Reusing them outside a view means reimplementing that machinery.

Instead the section becomes a **self-contained widget owning its own binding**,
following the pattern `OutputFormatRow` already established for exactly this
situation (a shared row living in several windows):

```python
# ui/widgets/vocal_split_row.py
class VocalSplitRow(Adw.ExpanderRow):
    def __init__(self, repo, on_changed): ...
    def apply_from_settings(self, settings) -> None: ...
    def persist_to_settings(self, settings) -> None: ...
```

Both windows already call `format_row.apply_from_settings(...)` and
`.persist_to_settings(...)` in their load and flush paths, so `VocalSplitRow`
drops into the same call sites with no new plumbing shape to learn. The model
combo is populated lazily on first expansion (`notify::expanded` → populate),
as it is today.

### 4. Secondary models hides non-applicable stem slots

`_SECONDARY_SLOTS` (`ui/views/base.py:76`) defines four slots: `voc_inst`,
`other`, `bass`, `drums`. Show `voc_inst` always; show the other three only when
the run can actually reach the engine's four-source path.

**The rule is a property of the run, not of the selected model.** An earlier
draft of this spec said "hide unless the resolved primary model produces four
stems", derived from `update_stem_labels()`'s `self._resolved_model`. Tracing
the engine showed that to be wrong. `core/model_data.py:609-610` gates the
four-slot branch on:

```python
if is_valid_ensemble or self.is_4_stem_ensemble or is_multi_stem_ensemble_demucs:
```

which unfolds (`:604-607`) to three cases — a Demucs model with
`demucs_stems == ALL_STEMS` outside ensemble mode; **any** member of a 4-stem
ensemble, VR and MDX-Net included; and a Demucs member of a multi-stem
ensemble. The model-stem-count rule would have wrongly hidden the slots on the
VR and MDX-Net tabs during a 4-stem ensemble, where they are live.

So the check is a pure function over settings plus the tab's architecture:

```python
def four_stem_secondaries_apply(settings, process_method: str) -> bool
```

mirroring the engine condition exactly, and living in `ui/option_summaries.py`
(§5) so it is unit-testable without a display. `_sync_secondary_slot_visibility()`
sets `visible` on the six rows (3 combos + 3 scales) for `other`/`bass`/`drums`
from its result, and is called from `update_stem_labels()`
(`ui/views/base.py:267`) — the existing refresh point, which already runs on
load, on model change, and after stem-group changes.

Hiding rather than dimming: dimming saves no height, and the height is the
point. This is a deliberate departure from the `_bind_switch_dependents`
dimming convention, justified because whether a run has four sources is a
*structural* fact, not a toggle the user is expected to flip.

Values for hidden slots are untouched — they persist in settings and reappear
when a four-source run is configured. No settings are cleared.

Effect: the expanded section drops from ~600px (9 rows) to ~240px (3 rows) in
the common two-source case.

**Applicability in ensemble runs — verified, do not re-question.** Secondary
models apply to ensemble members. `is_secondary_model_activated` is read from
the per-architecture key for any non-secondary model with no ensemble gate
(`core/model_data.py:456,490,573`), and there is dedicated ensemble handling
downstream: the `is_4_stem_ensemble` branch (`:610`), the
`ensemble_primary_stem` substitution (`:623`), and the `is_valid_ensemble`
guard (`:606`). So the section stays in the per-architecture tabs, and §6's
badge count is exactly the set of members a secondary configured there affects.

Likewise the vocal splitter applies to ensemble runs — `_vocal_splitter_active`
is a flat global check with no ensemble gate (`core/run_estimate.py:126-128`)
and `vocal_splitter_model_data` runs for every non-secondary model
(`core/model_data.py:654`). This confirms §3's placement in the Ensemble
Processing group.

### 5. Live state disclosure

A new module `ui/option_summaries.py` holds pure functions over a settings
mapping, with no GTK import, so they are unit-testable headlessly. It sits at
the `ui/` root rather than under `ui/model_options/` because both
`ui/views/base.py` and `ui/widgets/vocal_split_row.py` consume it, and a
widget importing from `model_options` would invert the dependency:

```python
def four_stem_secondaries_apply(settings, process_method: str) -> bool
def secondary_models_summary(settings, prefix: str, *, four_stem: bool) -> str
def preproc_summary(settings) -> str
def vocal_split_summary(settings) -> str
```

`four_stem_secondaries_apply` is §4's visibility rule. It lives here rather than
in `applicability.py` because it is consumed by `ui/views/base.py`, which must
not depend on `ui/model_options/`.

Each returns a one-line subtitle. Conventions:

- Every activate switch in the section off → `"Off"`.
- On, but the model it needs is unset (`NO_MODEL`) → `"On — no model selected"`.
- On and configured → a compact description, e.g. for secondary models
  `"Vocals/Instrumental: UVR-MDX-NET Inst HQ 3 (0.90)"`, with multiple
  configured stem pairs joined by `" · "`.

`secondary_models_summary` takes `four_stem` so it describes only the slots
that are actually visible (§4), keeping subtitle and body consistent.

`vocal_split_summary` covers **two independent switches**
(`is_set_vocal_splitter` and `is_deverb_vocals`). It returns `"Off"` only when
both are off; otherwise it joins the enabled halves with `" · "`, e.g.
`"UVR-BVE-4B · deverb: Main vocals"`, or `"deverb: Main vocals"` when only
deverb is on.

**Application.** In `ui/views/base.py`, after building each expander, set its
subtitle from the matching summary and re-apply on each activate switch's
`notify::active` and each model combo's `notify::selected`. A new
`_sync_expander_summaries()` does the whole pass; it is called at the end of
`MethodView.load()` (`ui/views/base.py:376`, beside the existing
`_sync_switch_dependents()` call) and from `update_stem_labels()` (so the
secondary subtitle follows slot visibility). Views without a given section
(`secondary_prefix` unset, `has_preproc` false) skip it — the method guards on
the expander attribute existing. `VocalSplitRow` applies the same pattern
internally, refreshing its own subtitle from `apply_from_settings` and from its
two switches' `notify::active`.

**Auto-expand:** when any of a section's activate switches is on, its expander
opens. This happens in `_sync_expander_summaries()` — **expand only, never
auto-collapse**, so a section the user opened by hand is never shut on them.
Because it runs from `load()`, auto-expand applies on sheet open and after a
settings reload, not on every switch toggle. The main-view vocal-split row
follows the same rule, expanding on window load when enabled.

Keys consumed, per existing schema (`prefix` is `vr` / `mdx` / `demucs`):

| Section | Activate key | Detail keys |
|---|---|---|
| Secondary models | `{prefix}_is_secondary_model_activate` | `{prefix}_{slot}_secondary_model`, `{prefix}_{slot}_secondary_model_scale` for slot in `voc_inst`, `other`, `bass`, `drums` |
| Pre-process model | `is_demucs_pre_proc_model_activate` | `demucs_pre_proc_model`, `is_demucs_pre_proc_model_inst_mix` |
| Vocal splitter and deverb | `is_set_vocal_splitter`, `is_deverb_vocals` | `set_vocal_splitter`, `is_save_inst_set_vocal_splitter`, `deverb_vocal_opt` |

No new settings keys are introduced.

### 6. Applicability signalling

Replace both `Gtk.Label` mechanisms with real widgets.

**Ensemble context — badge counts.** Each `Adw.ViewStackPage` gets
`set_badge_number(n)` where `n` is that architecture's member count from the
existing `member_arch_counts()`. Zero clears the badge (`set_badge_number(0)`).
Verified available in the installed libadwaita 1.9.2, and guarded with
`hasattr` in the same style as the existing `Adw.InlineViewSwitcher` fallback.

**Separation context — a page banner.** Each non-applicable page gets an
`Adw.Banner` at the top of the page (above the scroller, inside the page box):

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

### 7. Model maintenance group

`_build_secondary_section` in `ui/views/base.py` currently appends the
"Change model defaults" `Adw.ActionRow` to `secondary_group`. Move it into a
new `self.maintenance_group = Adw.PreferencesGroup(title="Model maintenance")`,
appended to `self.groups` after `secondary_group`. The sheet reparents all three
groups per tab, `maintenance_group` into `col_end` below `secondary_group`. The
row keeps its existing `CLEAR_CACHE_HELP` hint and `_on_change_defaults`
handler.

The group stays per-architecture — it edits that architecture's stored model
parameters — but stops presenting as a fourth "extra model".

### 8. Resulting fit

Against ~578px of content height at the default 1040×720 window:

| Tab | col_start | col_end | Max | Fits |
|---|---|---|---|---|
| VR | Inference 420 | Extra 100 + Maint 100 = 200 | 420 | yes |
| Demucs | Inference 300 | Extra 160 + Maint 100 = 260 | 300 | yes |
| MDX-Net | Inference 180 | Extra 100 + Maint 100 = 200 | 200 | yes |

With Secondary models expanded on a two-source run (§4), the right column grows
to ~380px — still within budget. A 4-stem model expands it to ~740px and
scrolls, which is acceptable: at that point the user is deliberately working
inside one section.

Moving the vocal splitter out (§3) also removes the MDX-Net imbalance as a side
effect — 180 vs 200 instead of 180 vs 320.

Main page cost: one collapsed row (~60px) added to the Processing group on the
Separation and Ensemble pages.

## Files

| File | Change |
|---|---|
| `ui/model_options/sheet.py` | shell rework; net smaller |
| `ui/option_summaries.py` | **new** — pure state summarisers, no GTK |
| `ui/widgets/vocal_split_row.py` | **new** — `VocalSplitRow`, modelled on `OutputFormatRow` |
| `ui/model_options/applicability.py` | `applicability_banner` replaces `applicability_subtitle` |
| `ui/model_options/__init__.py` | export update |
| `ui/views/base.py` | vocal-split section removed; `maintenance_group`; stem-slot visibility; expander subtitles + auto-expand |
| `ui/window.py` | `VocalSplitRow` in Processing group; `on_switch_method` callback |
| `ui/ensemble/window.py` | `VocalSplitRow` in Processing group |
| `tests/test_option_summaries.py` | **new** — headless summariser tests |
| `tests/test_secondary_slot_visibility.py` | **new** — four-source vs two-source slot rules |
| `tests/test_model_options_applicability.py` | update for `applicability_banner` |
| `tests/` (sheet) | badge numbers, banner presence/absence, two-column structure |

## Testing

- **Headless (no display):** every function in `option_summaries.py`;
  `applicability_banner` across the three contexts × three stacks × empty and
  populated member lists; `four_stem_secondaries_apply` across all three engine
  cases (Demucs with all stems, 4-stem ensemble on every architecture,
  multi-stem ensemble on Demucs only) plus the negatives. These are the bulk of
  the coverage.
- **GTK-guarded** (`@unittest.skipUnless(DISPLAY or WAYLAND_DISPLAY)`, with
  `gi.require_version` in `setUpClass`): sheet constructs; each tab page has two
  non-homogeneous columns that stack below the breakpoint; badge numbers match
  `member_arch_counts`; the non-applicable page carries a banner and the
  applicable one does not; an enabled section's expander is expanded after a
  context update; the vocal-split row appears in the Processing group on the
  Separation and Ensemble pages and **not** in Audio Tools.
- **Regression:** editing the vocal splitter on the Separation page and
  reopening Ensemble shows the same values (they are one global setting) — the
  behaviour that used to require three synchronised copies.
- The existing suite (694 tests) must stay green.

## Error handling

- Parent height unavailable → fall back to `_SHEET_FALLBACK_HEIGHT`; no
  exception, no tracking handler to leak.
- A settings key missing from the mapping → summariser reads it via
  `settings.get(key, default)` and degrades to `"Off"` / `"On — no model
  selected"` rather than raising. `SettingsModel` backfills missing keys from
  defaults on load, so this is defence in depth.
- §4's visibility rule never touches the resolved model, so a hash miss or an
  unchosen model cannot break it: `four_stem_secondaries_apply` reads only
  `chosen_process_method`, `ensemble_main_stem` and `demucs_stems`, each with a
  default, and returns `False` when none of the three engine cases match —
  showing the `voc_inst` slot alone.
- `Adw.ViewStackPage.set_badge_number` guarded with `hasattr`, so an older
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
