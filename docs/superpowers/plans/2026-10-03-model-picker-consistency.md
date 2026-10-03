# Model Picker Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separation and Ensemble choose catalogue models through one entry-row pattern and one `ModelPicker` dialog.

**Architecture:** `ModelPicker` gains a `PickerConfig` (title, purpose tabs, search placeholder) and an optional multi-select mode (`MemberCallbacks`). Ensemble's checklist dialog becomes a multi-select picker. The picker creates the `Gtk.CheckButton`s Ensemble already keeps in `_model_checks`, so Ensemble's projection, write gate and persist boundary are untouched. Separation's call site does not change. Apollo's dropdown, the vocal splitter and the other auxiliary selectors are not changed.

**Tech Stack:** Python 3.12+, GTK 4 / libadwaita via PyGObject, Blueprint layouts compiled into `ui/data/uvr.gresource`, stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-03-model-picker-consistency-design.md`

## Global Constraints

- Work on branch `claude/model-picker-consistency`, created from `dev`.
- **Do not touch** these; each stays a dropdown by design:
  - `ui/widgets/vocal_split_row.py` and `resources/ui/vocal_split_row.blp`
  - Audio Tools' `apollo_model_row` and its refresh/write-gate code
  - The secondary-model and Demucs pre-process combos (`MethodView._model_combos`)
  - `show_change_defaults_dialog`
- No setting key, writer, flush or preflight path changes. Ensemble's write-gate fields keep their names and semantics: `_models_write_gated`, `_models_gated_values`, `_models_gated_ids`.
- Ensemble keeps these names, because tests set and read them directly:
  - `_model_checks: dict[str, Gtk.CheckButton]` and `_model_row_text`
  - `_on_model_toggled(check)`, `_set_visible_models_active(active)` and `_visible_model_tags()`
  - `_update_models_dialog_status()`, `_open_models_dialog()`, `_on_models_dialog_closed()` and `models_dialog`
- `ModelPicker`'s positional signature `(repo, current, choose, get_more)` and default behaviour stay, so `MainWindow._open_model_picker` is unchanged.
- Opening, searching, filtering, viewing details or closing a picker never commits a selection. In multi mode, only toggling a check commits (live, as today).
- Picker titles exactly: `"Choose Model"` (Separation, unchanged) and `"Member Models"` (Ensemble).
- Fixed layout values go in Blueprint; never call `widget.destroy()` in tests.
- GTK tests use the repo's display guard (`@unittest.skipUnless(DISPLAY or WAYLAND_DISPLAY)` + `gi.require_version` in `setUpClass`).
- Test command used below: `T="$HOME/.claude/skills/testing-gtk-headless/scripts/run-private-wayland.sh -- env UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 .venv/bin/python -m unittest"`. Do not pipe it; redirect to a file and read the file.
- After any `.blp` change: `./resources/compile_resources.sh`, then `./resources/compile_resources.sh --check`, then `blueprint-compiler lint` on the changed file. Format and lint every touched Python file with `.venv/bin/ruff format` / `.venv/bin/ruff check`. Project-wide `.venv/bin/python -m basedpyright` must report `0 errors` before each commit.

## Review Focus

1. **Ensemble write gate survives the new widget:** the gated-member and reopen tests in `tests/test_model_picker_records.py` pass unchanged. Setting check state inside `set_members` must not fire `_on_model_toggled`, which would reset `chosen_ensemble`. Pinned in Tasks 1 and 2.
2. **Check-widget reuse:** reopening the member dialog without a stem/pair change reuses the same `Gtk.CheckButton` objects (`test_opening_dialog_reuses_existing_check_widgets`). Pinned in Tasks 1 and 2.
3. **Separation unchanged:** the existing tests in `tests/test_model_picker_ui.py` pass without edits.
4. **Out-of-scope dropdowns untouched:** `git diff --stat dev` lists no splitter, Apollo, Model options or Change Model Defaults files.

---

### Task 1: `PickerConfig` and the multi-select mode in `ModelPicker`

**Files:**
- Modify: `ui/model_picker.py`, `resources/ui/model-picker.blp`
- Test: `tests/test_model_picker_ui.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class PickerConfig:
      title: str = "Choose Model"
      purposes: tuple[tuple[str, str], ...] = PURPOSES   # () hides tabs and compact dropdown
      search_placeholder: str = "Search installed models"

  @dataclass(frozen=True)
  class MemberCallbacks:
      toggled: Callable[[Gtk.CheckButton | None], None]
      set_visible_active: Callable[[bool], None]

  class ModelPicker:
      def __init__(self, repo, current, choose, get_more, *,
                   config: PickerConfig = PickerConfig(),
                   members: MemberCallbacks | None = None): ...
      def set_members(self, records: Sequence[ModelRecord], selected_ids: Collection[str], *,
                      placeholder: str = "",
                      placeholder_description: str = "") -> dict[str, Gtk.CheckButton]: ...
      def visible_ids(self) -> list[str]: ...
      def set_status(self, text: str) -> None: ...
  ```
- Blueprint additions: `Gtk.Button select_all` (`"Select All"`, flat) and `Gtk.Button clear` (`"Clear"`, flat) beside `reset`, both `visible: false` by default. The picker shows them in multi mode.

- [ ] **Step 1: Write the failing tests** (GTK-guarded, alongside the existing picker tests, reusing their fake repo/records):
  - `test_config_title_and_hidden_tabs`: `PickerConfig(title="Member Models", purposes=())` → the dialog title matches; `purpose_tabs` and `purpose_compact` are not visible, including after the dialog crosses the 700 sp breakpoint.
  - `test_default_config_is_separation`: the default config keeps today's title and purpose tabs (Review Focus 3).
  - `test_members_reuse_checks_and_block_handlers`: `toggled=Mock()`. `set_members([a, b], {"mdx:a"})` returns checks with `a` active and `b` inactive; `toggled` is not called. A second `set_members([a, b], {"mdx:b"})` returns the **same** check objects with the states flipped; `toggled` is still not called. User `set_active` on a check calls `toggled` once.
  - `test_members_rows_come_only_from_set_members`: an installed record not passed to `set_members` is not listed, and `refresh_models()` keeps the member list.
  - `test_members_visible_ids_follow_search_and_sort`: three records; the search narrows `visible_ids()`, which stays in display order.
  - `test_members_select_all_and_clear_delegate`: clicking `select_all` / `clear` calls `set_visible_active(True)` / `(False)`.
  - `test_members_placeholder_shows_status_page`: `set_members((), (), placeholder="Could not list models", placeholder_description="See Error Log for details")` → list hidden, the `empty` status page visible with that title and description, and its Reset Filters button hidden.
  - `test_members_details_toggle`: details for a selected record shows "Remove from Ensemble", and clicking it deactivates the check. For an unselected record it shows "Add to Ensemble".
  - `test_members_row_activation_toggles_check`.
- [ ] **Step 2: Run** `$T tests.test_model_picker_ui > /tmp/mp1.log 2>&1`. Expected: failures.
- [ ] **Step 3: Implement.**
  - Apply `config.title` to the dialog and `config.search_placeholder` to the search entry. Build purpose buttons from `config.purposes`; when it is empty, hide `purpose_tabs` and `purpose_compact`, skip the breakpoint setters that reveal `purpose_compact`, and use `'all'` as the purpose in `_refresh`.
  - `refresh_models()`: single mode is unchanged. Multi mode re-projects the records from the last `set_members` call through `project_installed`, never the full installed inventory.
  - Multi mode rows: `_create_row` adds a `Gtk.CheckButton` prefix in place of the check image. It sets the check as the row's activatable widget and connects `toggled` to `members.toggled`, keeping the handler ID.
  - Multi mode state: `set_members` blocks each handler around `set_active`. The details button's label and action follow the check state.
  - Multi mode controls: show `select_all` / `clear` and wire them to `members.set_visible_active`. `set_status` writes the `count` label, which `_refresh` does not overwrite in multi mode. The context label reads `"Compatible models"`.
- [ ] **Step 4: Run** the tests. Expected: `OK`, with the existing picker tests unchanged.
- [ ] **Step 5: Commit** `feat(ui): ModelPicker takes a per-page config and a multi-select mode`.

### Task 2: Ensemble's member dialog is the multi-select picker

**Files:**
- Modify: `ui/ensemble/window.py`:
  - `_build_models_dialog` (355-379)
  - `_render_member_projection` (~1335-1369)
  - `_models_row_visible`, `_visible_model_tags`, `_update_models_dialog_status`, `_on_models_search_changed`
  - `_open_models_dialog` (1549-1556), the `models_dialog` use near 1608, and the `edit_models_button` wiring (306-308)
- Modify: `resources/ui/ensemble-page.blp` (remove `edit_models_button`)
- Delete: `resources/ui/ensemble-member-picker.blp` (`./resources/compile_resources.sh` regenerates the bundle and its file list from the `.blp` sources)
- Modify: `tests/test_ui_boundaries.py`, `tests/test_saved_ensembles.py`, `tests/test_ensemble_performance.py`, but only where they set `models_listbox`, `models_search` or `models_dialog` directly

**Interfaces:**
- Consumes: Task 1 (`ModelPicker`, `PickerConfig`, `MemberCallbacks`).
- Produces:
  - `MEMBER_PICKER = PickerConfig(title="Member Models", purposes=(), search_placeholder="Search compatible models")`
  - `EnsemblePage._member_picker: ModelPicker`
  - `EnsemblePage.models_dialog`, kept as an alias of `_member_picker.dialog`

- [ ] **Step 1: Write the failing tests** in `tests/test_model_picker_records.py` (GTK-guarded class beside the existing Ensemble cases):
  - `test_member_dialog_is_the_shared_picker`: `page.models_dialog is page._member_picker.dialog`, and the title is `"Member Models"`.
  - `test_render_uses_picker_checks`: after `_render_member_projection`, `page._model_checks` is the dict `set_members` returned, and the active states equal `projection.selected_ids`.
  - `test_rendering_does_not_reset_saved_ensemble` (Review Focus 1): with `settings.ensemble.chosen_ensemble = "Saved preset"`, render a projection with two selected IDs; `chosen_ensemble` is unchanged.
  - `test_trigger_row_has_no_edit_button`: no `Gtk.Button` descendant of `models_trigger_row`.
- [ ] **Step 2: Run** `$T tests.test_model_picker_records > /tmp/mp2.log 2>&1`. Expected: failures.
- [ ] **Step 3: Implement.**
  - `_build_models_dialog`:
    - Build `self._member_picker = ModelPicker(self.context.repo, lambda: "", lambda _id: False, lambda: self.window._on_download(None, None), config=MEMBER_PICKER, members=MemberCallbacks(self._on_model_toggled, self._set_visible_models_active))`.
    - Set `self.models_dialog = self._member_picker.dialog` and connect `closed` to `_on_models_dialog_closed`.
    - Keep `set_tooltip(..., ENSEMBLE_LISTBOX_HELP)` on the picker's list.
  - `_render_member_projection`:
    - Keep the gate bookkeeping at the top unchanged.
    - Replace the list-box clear/append loop with `self._model_checks = self._member_picker.set_members(projection.records, projection.selected_ids, placeholder=projection.placeholder, placeholder_description=...)`.
    - Pass `"See Error Log for details"` as the description when the placeholder is "Could not list models", as the old placeholder row's subtitle did.
    - Fill `_model_row_text[tag] = (record.display, picker subtitle)`.
  - Helpers:
    - `_visible_model_tags` → `self._member_picker.visible_ids()`.
    - Delete `_models_row_visible` and `_on_models_search_changed`.
    - `_update_models_dialog_status` calls `self._member_picker.set_status(models_selection_status(...))` with today's arguments.
  - `_open_models_dialog`: keep the stem-pair guard and `_ensure_member_list()`. Replace clearing `models_search` with `self._member_picker.reset()`, then call `present_modal_dialog(self.models_dialog, self.window)`. Keep `present_modal_dialog`, which the tests patch.
  - Remove `edit_models_button` from the Blueprint and its `connect` call.
- [ ] **Step 4: Run** `$T tests.test_model_picker_records tests.test_ensemble_performance tests.test_gui_gated_plans tests.test_ui_boundaries tests.test_saved_ensembles tests.test_page_layout_contract tests.test_ensemble_page_design > /tmp/mp2.log 2>&1`. Expected: `OK`. Edit tests only where they built the removed widgets; do not change gate or persist assertions.
- [ ] **Step 5: Full suite:** `$T discover -s tests -t . > /tmp/mp-full.log 2>&1` → `OK`; basedpyright → `0 errors`; `./resources/compile_resources.sh --check` matches.
- [ ] **Step 6: Commit** `feat(ui): Ensemble members use the shared model picker`.

### Task 3: Visual verification and final checks

**Files:** none (scratch renders under `/tmp`, isolated `UVR_DATA_DIR` with a copied `settings.json` and `models/` symlinked)

- [ ] **Step 1: Render** on the private display, in light, dark and a 480 px-wide dialog:
  - Both entry rows.
  - Both pickers' browser pages.
  - Ensemble's picker with a placeholder.
  - One details page per mode.
- [ ] **Step 2: Compare.** The two dialogs share the header layout, controls row, row height and empty state. Only the configured differences may vary: purpose tabs, check prefix vs check mark, Select All/Clear, and the details button label. Report any other difference with its screenshot.
- [ ] **Step 3: Final checks:** full suite `OK`; basedpyright `0 errors`; resource bundle `--check` matches; ruff clean on touched files; `git diff --stat dev` passes Review Focus 4.
- [ ] **Step 4: Commit** any test-only follow-ups as `test(ui): pin the shared model picker across pages`.
