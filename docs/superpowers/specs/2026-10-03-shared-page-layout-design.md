# Shared page layout — design

**Status:** approved in brainstorming, awaiting spec review
**Date:** 2026-10-03
**Branch:** `dev` (implementation on a feature branch off `dev`)

## Goal

Give the three run pages (Separation, Ensemble, Audio Tools) one layout, so
that a control the pages share sits in the same column and group on every
page, and the two columns are closer to balanced.

Success means:

- Every page reads **Input → page-specific section** in the left column and
  **Output → Processing** in the right column, with those exact group titles.
- The shared Input, Output and Processing groups are built by one builder, not
  three copies.
- Column balance (left minus right content height at 1280 px) lands near the
  targets below, and no shared-settings behaviour changes.

## Background

A UI review on 2026-10-03 measured the pages at 1280 px:

| Page | Left − right today |
|---|---|
| Separation VR / MDX | −151 px |
| Separation Demucs | −206 px |
| Ensemble | +80 px |
| Audio Tools, Manual Ensemble | +135 px |
| Audio Tools, Align Inputs | +379 px |

It also found the shared controls placed differently on each page:

| | Separation | Ensemble | Audio Tools |
|---|---|---|---|
| Input group title | Input | Files | Files |
| Output folder | Output (right) | Files (left) | Files (left) |
| Format | Output | Output | Processing |
| Model options | Model group | Processing → Advanced | — |
| Vocal splitter | Processing | Processing | — |
| Timestamp toggle | Preferences | Preferences | On the page |

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Vocal splitter placement | With the model, in the left column, on Separation and Ensemble |
| Audio Tools timestamp row | Removed; Preferences → Output remains its home, as on the other pages |
| Audio Tools Limit peaks / Amplification | Stay on Audio Tools, in Processing |
| Implementation approach | Shared group builders (one builder for Input / Output / Processing) |
| Ensemble Advanced group | Kept in Processing, slimmed to Ensemble waveforms and Append ensemble name |

### Out of scope

Unifying the model pickers, dialog conventions, the remaining dot-formatted
numbers (SDR scores, secondary-model weight), and the control-type
inconsistencies (sliders vs spin rows) from the same review. Each is a
separate piece of work.

## Layout

Rule: **left** = Input, then the page's own section. **Right** = Output, then
Processing.

| Page | Left | Right |
|---|---|---|
| Separation | Input · Model (model row, method sliders, Model options, Vocal splitter) | Output (output toggle, Save stems, Format, Output folder) · Processing (GPU, FP16 autocast, Sample mode) |
| Ensemble | Input · Ensemble (Configuration, Output mode, Member models, Member model options, Vocal splitter) · Combination | Output (output toggle, Save stems, Format, Output folder, Keep individual model outputs) · Processing (GPU, FP16 autocast, Sample mode, Advanced) |
| Audio Tools | Input (files, or input pairs for dual tools) · Tool (tool picker, then the active tool's settings) | Output (Format, Output folder) · Processing (GPU for Apollo, Limit peaks above full scale, Amplification threshold) |

Changes from today:

- **Separation:** Vocal splitter moves from Processing to the Model group.
- **Ensemble:** "Files" becomes "Input"; Output folder moves to Output;
  Vocal splitter moves to the Ensemble group; Member model options moves out
  of Advanced to sit under Member models (mirroring Separation's Model
  options); the Combination group's summary description is removed (it
  repeated the rows below it and the run card's status).
- **Audio Tools:** "Files" becomes "Input"; Format and Output folder form a new
  Output group; the tool picker and the active tool's settings become one
  "Tool" group; the timestamp row is removed. The GPU row loses its
  page-specific "Use CUDA when available" subtitle.

Balance targets (estimates, ±30 px):

| Page | Target |
|---|---|
| Separation VR / MDX | ≈ −40 px |
| Separation Demucs | ≈ −95 px |
| Ensemble | ≈ +110 px |
| Audio Tools, Manual Ensemble | ≈ +5 px |
| Audio Tools, Align Inputs | ≈ +250 px (inherent: most settings) |

The narrow layout (single column below the 880 sp breakpoint) keeps the same
order: Input, page section, Output, Processing.

## Architecture

### Shared group builder

New files: `resources/ui/page-groups.blp` and `ui/widgets/page_groups.py`.

```python
@dataclass(frozen=True)
class PageGroupCallbacks:
    on_inputs_changed: Callable[[], None]
    on_output_changed: Callable[[], None]
    on_format_changed: Callable[[FormatEdit], None]
    on_view_inputs: Callable[[], None]
    toast: Callable[[str], None]
    hint: Callable[[Gtk.Widget, str], None]
    accept_any_getter: Callable[[], bool]
    initial_folder_getter: Callable[[], str | None]
    on_gpu_changed: Callable[[], None] | None = None
    on_autocast_changed: Callable[[], None] | None = None
    on_sample_changed: Callable[[], None] | None = None


class PageGroups:
    input_group: Adw.PreferencesGroup        # "Input", with the Verify Inputs header button
    output_group: Adw.PreferencesGroup       # "Output"
    processing_group: Adw.PreferencesGroup   # "Processing"
    input_row: InputFilesRow
    output_row: OutputFolderRow
    format_row: OutputFormatRow
    gpu_row: Adw.SwitchRow | None
    autocast_row: Adw.SwitchRow | None
    sample_row: Adw.SwitchRow | None

    def set_output_lead(self, rows: Sequence[Gtk.Widget]) -> None: ...
    def add_output_tail(self, row: Gtk.Widget) -> None: ...
    def add_input_row(self, row: Gtk.Widget) -> None: ...
    def add_processing(self, row: Gtk.Widget) -> None: ...
    def bindings(self, *, vocal_row: ReadableVocalSplitRow | None = None) -> SharedSettingsBindings: ...
    def apply(self, settings: Settings) -> SharedFileOptions: ...


def build_page_groups(
    callbacks: PageGroupCallbacks,
    *,
    processing: Collection[Literal["gpu", "autocast", "sample"]] = ("gpu", "autocast", "sample"),
) -> PageGroups: ...
```

- Each page calls `build_page_groups` once and gets its own widget instances
  (a fresh `Gtk.Builder` per call).
- The builder connects each switch's `notify::active` and calls the page's
  callback with no arguments; Audio Tools' existing `apollo_gpu_row` is
  replaced by the builder's `gpu_row`.
- `bindings()` passes the builder's rows (plus the page's vocal row, when it
  has one) to the existing `shared_settings_bindings`. `apply()` passes them
  to the existing `apply_shared_file_options`.
- Rows the builder did not create (`processing` omitted a switch) are `None`
  and are omitted from both, exactly as pages omit them today.
- `hint` lets each page keep its own help mechanism: `HelpHintManager.register`
  on Separation and Audio Tools, `set_tooltip` on Ensemble.

What stays per page, unchanged: each page's `SharedSettingsSession` and its
active-tab `can_commit` guard, its flush and preflight paths, and the
callbacks it supplies. The builder only creates widgets and hands them to the
existing binding and apply functions, so the flush/preflight contract in
`ui/AGENTS.md` does not change.

Behaviour unified as a side effect: Ensemble's and Audio Tools' input rows gain
Separation's `initial_folder_getter` (the file chooser opens in the first
input's folder).

### Row slots

New file: `ui/widgets/row_slot.py`.

`Adw.PreferencesGroup` has no insert-at-index, so a `RowSlot` places a
replaceable run of rows at a fixed position in a group and keeps any rows
after it in order (removing and re-adding the trailing rows when the slot's
contents change). It is used for:

- **Separation's Output group** (lead rows: the active method view's output
  toggle and Save stems summary).
- **Audio Tools' Tool group** (the active tool's settings rows after the tool
  picker).

`PageGroups.set_output_lead` is a thin wrapper over a `RowSlot`.

### Separation method switching

Today each method view owns an Output group (`view.stem_group`), and
`MainWindow._populate_columns` moves Format and Output folder into whichever
view is active.

New behaviour:

- Separation uses the builder's single Output group, fixed in the right column.
- `OutputStemsSection` gains an optional `host`; when `None` it does not add
  rows to a group and exposes them as `rows` (the quick-select row and the
  summary row — the only rows views add; no view overrides
  `build_stem_options`).
- On a method switch the window calls
  `groups.set_output_lead(view.output_stems.rows)`.
- The composed stem tooltip computed in
  `MethodView._update_stem_group_metadata` reaches the shared Output group
  through a hook (`MethodView.on_output_tooltip(text)`), applied when the view
  becomes active and whenever it recomputes. (The method always clears the
  group description, so only the tooltip needs forwarding.)
- The Vocal splitter row joins the per-view Model group and moves into the
  active view's group on a switch, using the same host-tracking pattern as
  `model_options_row` (`_model_options_host`).
- Processing becomes static (GPU, FP16 autocast, Sample mode never move).
- `view.stem_group` stays only as the holder for inactive views' rows. It is
  never placed in a column, and the window no longer retitles it "Output".

### Audio Tools Tool group

- A "Tool" group holds the tool picker (`tool_row`) as its first row and a
  `RowSlot` after it.
- The per-tool groups in `tool_stack` become holders. On a tool change the
  active tool's rows (including Align's Advanced align expander) move into
  the slot.
- Each tool's description (today the group description) becomes the picker's
  subtitle.
- Matchering, which has no settings, shows only the picker.
- Apollo's "open models folder" header button becomes a suffix button on the
  Apollo model row.
- The Gtk.Stack is removed if nothing else needs it after the change.

### Ensemble

- The Input group comes from the builder (title "Input").
- Member model options and Vocal splitter are added to the Ensemble group,
  after Member models.
- The Combination group's description is cleared and no longer updated.
- Advanced (Ensemble waveforms, Append ensemble name) stays in Processing.

## Error handling and invariants

- No setting keys, bindings, writers or flush paths change. Moving a row
  between groups never changes what it saves, because bindings are built from
  row widgets.
- Model-combo readiness gates (`LazyPopulator.ready`, per-combo
  `entry["ready"]`) are unaffected: no combo is rebuilt by a move.
- Moving a row with `RowSlot` removes it from its current parent before
  adding it, so a row is never in two groups.
- Hidden rows (for example the GPU row on non-Apollo tools) keep their
  visibility rules; the builder does not change visibility.

## Testing

- **Layout contract test** (new): for every page, every Separation method and
  every Audio Tools tool, the left column starts with the Input group, the
  right column is exactly Output then Processing, and key rows are where the
  rule puts them (Vocal splitter in the left column; Format and Output folder
  in Output).
- **Builder tests** (new): `bindings()` contains exactly the supplied rows,
  `apply()` pushes settings into them, and the `processing` subset omits rows
  cleanly.
- **RowSlot tests** (new): replacing contents, preserving trailing rows'
  order, emptying the slot, and moving a row that already has a parent.
- **Updated tests:** `tests/test_vocal_split_placement.py`,
  `tests/test_ensemble_page_design.py`, `tests/test_method_view_refresh.py`
  (stem-group metadata), and any test referencing the removed timestamp row or
  `select_group`.
- **Behaviour unchanged:** the existing shared-session, flush and preflight
  tests pass without modification.
- **Visual check:** re-render every page (light, dark, 720 px narrow) and
  re-measure column balance against the targets above.
