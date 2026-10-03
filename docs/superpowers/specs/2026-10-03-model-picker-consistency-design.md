# Model picker consistency — design

**Status:** proposed, awaiting review
**Date:** 2026-10-03
**Branch:** `dev` (implementation on a feature branch off `dev`)

## Goal

Choosing models from the catalogue works the same way on Separation (its
model) and Ensemble (its member models): one entry-row pattern on the page,
and one model dialog.

Success means:

- Both entry rows are a single activatable row with a chevron that opens the
  shared dialog. Neither page has a second button for the same action.
- The two dialogs are one component (`ModelPicker`). They share search,
  Reset, the architecture filter, sorting, row subtitles, the details page,
  the empty state and the Get More Models button.
- No selection, persistence or write-gate behaviour changes.

## Background

The 2026-10-03 UI review listed "unifying the model pickers" as out of scope
for the shared page layout. Today:

| | Separation | Ensemble members | Apollo (Audio Tools, unchanged) |
|---|---|---|---|
| Entry row | `ActionRow`: model name / outputs, chevron | "Member models" / chosen names, **Edit models** button *and* chevron | `ComboRow` "Apollo model" with an inline dropdown, plus an open-folder button |
| Chooser | "Choose Model" dialog, 800×640: search, Reset, purpose tabs, architecture filter, sort, details page, Get More Models | "Member models" dialog, 440×560: description, status line, search, Select all, Clear, checklist | The combo's popover list |
| Row subtitle | Outputs · SDR (for Vocals/Instrumental) | Architecture name only | Display name only |
| Details | Yes | No | No |
| Get more | Header button → Download Center | None | Open the models folder |
| Saved model missing | "Saved model unavailable · Choose another installed model" | Dropped at persist with a debug log | Shows "Choose Model" with no explanation |

## Decisions

| Question | Decision |
|---|---|
| Vocal splitter and deverb | **Unchanged.** Its combo stays simple by design (user decision). |
| Apollo model (Audio Tools) | **Unchanged dropdown** (user decision). The dialog earns its weight only when browsing many catalogue models; Apollo has a handful. |
| Other auxiliary selectors (secondary models and the Demucs pre-process model in Model options, Change Model Defaults) | Unchanged: they are secondary choices inside an options surface, like the splitter. |
| One dialog or two styled alike | One `ModelPicker`, configured per page, with a single-select and a multi-select mode. |
| Ensemble's selection state | Stays `EnsemblePage._model_checks: dict[str, Gtk.CheckButton]`. The picker creates the check buttons; the projection, write gate and persist boundary are untouched. |
| Ensemble "Edit models" button | Removed; the row's chevron is the only affordance, as on Separation. |
| Purpose tabs | Separation: unchanged. Ensemble: hidden (the stem pair already decides eligibility). |
| Multi-select commit | Live, as today: each toggle persists through the page. Single-select closes the dialog on a successful choice, as today. |
| Ensemble SDR sorting | Not added. Ensemble sorts by name; SDR sorting stays Separation-only (Vocals/Instrumental purposes). |

### Out of scope

The vocal splitter row, the Apollo model dropdown, the auxiliary selectors
above, the Download Center, and the review's other leftovers (dialog conventions, dot-formatted numbers,
control-type inconsistencies).

## Design

### Entry rows

Separation's row is unchanged. Ensemble's row keeps its title "Member models"
and its existing name-list subtitle (`_update_models_summary`), and loses the
Edit models button, so the chevron is its only affordance, as on Separation.

### `ModelPicker` configuration

```python
@dataclass(frozen=True)
class PickerConfig:
    title: str = "Choose Model"
    purposes: tuple[tuple[str, str], ...] = PURPOSES  # () hides the purpose tabs
    search_placeholder: str = "Search installed models"

@dataclass(frozen=True)
class MemberCallbacks:
    toggled: Callable[[Gtk.CheckButton | None], None]
    set_visible_active: Callable[[bool], None]
```

`ModelPicker(repo, current, choose, get_more, *, config=PickerConfig(),
members: MemberCallbacks | None = None)`. Positional arguments are
unchanged, so Separation's call site needs no edit. When `members` is given:

- **Rows** carry a `Gtk.CheckButton` prefix in place of the check-mark image;
  activating a row toggles its check. The info button and details page stay.
- **Row source** is `set_members(records, selected_ids, *, placeholder="",
  placeholder_description="") -> dict[str, Gtk.CheckButton]`. The page passes `MemberProjection.records`,
  and the picker projects them with `project_installed` for subtitles and
  filters. Check buttons are reused per ID across calls, with their `toggled`
  handler blocked while the picker sets their state.
- **Select all and Clear** sit beside Reset and call
  `members.set_visible_active(True/False)`. The page keeps today's batching.
  `visible_ids()` returns the filtered, sorted IDs in display order.
- **Status:** the count label shows the page's status text through
  `set_status(text)`, which the page drives from today's
  `models_selection_status`.
- **Placeholders** ("Choose a stem pair to list models", "Could not list
  models") show in the empty status page instead of a fake row.
- **The details button** reads "Add to Ensemble" or "Remove from Ensemble"
  and toggles the check.

### Ensemble

`_build_models_dialog` builds `ModelPicker(…, config=MEMBER_PICKER,
members=MemberCallbacks(self._on_model_toggled,
self._set_visible_models_active))`. `_render_member_projection` replaces its
list-box loop with `self._model_checks =
picker.set_members(projection.records, projection.selected_ids,
placeholder=projection.placeholder)` and fills `_model_row_text` from the
records, as today. `_visible_model_tags` delegates to `picker.visible_ids()`,
and `_open_models_dialog` presents `picker.dialog`. `models_listbox`,
`models_search` and `models_status_label` go away, along with
`resources/ui/ensemble-member-picker.blp`.

## Invariants

- Canonical IDs only; display labels never recover identity.
- Separation's `_choose_model` and Ensemble's `MemberProjection` write gate
  and persist boundary are unchanged. Their existing tests keep their assertions; only widget
  plumbing in the tests changes.
- Opening a picker never commits. Search, filters, details and close are
  session-only, as `tests/test_model_picker_ui.py` pins today.
- Ensemble stays lazy: building the page does not resolve member models.
- Every picker refreshes through its page's `refresh_models()`, which
  `MainWindow._model_list_consumers()` already reaches.

## Testing

- **Picker GTK tests:** config sets the title and hides purpose tabs; the
  default config is Separation's; multi mode reuses check buttons, blocks handlers while setting state, lists
  `visible_ids()` in display order, shows placeholders in the status page,
  and the details button toggles membership.
- **Ensemble:** `tests/test_model_picker_records.py`,
  `tests/test_ensemble_performance.py`, `tests/test_gui_gated_plans.py` and
  `tests/test_ui_boundaries.py` keep their assertions. Only references to
  removed widgets change.
- **Visual check:** both pickers in light, dark and the narrow (≤512 sp)
  layout, plus both entry rows.
