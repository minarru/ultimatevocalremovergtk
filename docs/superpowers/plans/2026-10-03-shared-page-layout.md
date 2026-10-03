# Shared Page Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Separation, Ensemble and Audio Tools one column layout (left: Input → page section; right: Output → Processing) built from shared group builders.

**Architecture:** A `build_page_groups()` builder creates each page's Input, Output and Processing groups and their shared rows, and hands those rows to the existing `shared_settings_bindings` / `apply_shared_file_options`. A `RowSlot` helper swaps a run of rows inside a group, used for Separation's per-method output rows and Audio Tools' per-tool settings. Pages keep their sessions, tab guards, flush paths and existing attribute names (as aliases to the builder's rows).

**Tech Stack:** Python 3.12+, GTK 4 / libadwaita via PyGObject, Blueprint layouts compiled into `ui/data/uvr.gresource`, stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-03-shared-page-layout-design.md`

## Global Constraints

- Work on branch `claude/shared-page-layout`, created from `dev`.
- Group titles exactly: `Input`, `Output`, `Processing`, `Tool` (Audio Tools), `Model` (Separation, unchanged), `Ensemble` and `Combination` (Ensemble, unchanged).
- No setting key, binding, writer, flush or preflight path changes. Each page's `SharedSettingsSession` and its `can_commit` tab guard stay as they are.
- Pages keep their current public/test-facing attribute names, assigned from the builder: `input_row` (Audio Tools also keeps `inputs_row` and the `me_/ts_/ps_/ap_inputs_row` aliases), `output_row`, `format_row`, `gpu_row`, `autocast_row`, `sample_row`; Audio Tools keeps `apollo_gpu_row` as an alias of its `gpu_row`; Ensemble keeps `stems_group` as an alias of its Output group.
- Tooltips the builder attaches (through the page's `hint` callback): input row `INPUT_FOLDER_ENTRY_HELP`, output row `OUTPUT_FOLDER_ENTRY_HELP`, GPU `IS_GPU_CONVERSION_HELP`, FP16 `IS_AUTOCAST_HELP`, sample mode `MODEL_SAMPLE_MODE_HELP`. Pages stop registering these themselves.
- Fixed layout values go in Blueprint; never call `widget.destroy()` in tests.
- GTK tests use the repo's display guard (`@unittest.skipUnless(DISPLAY or WAYLAND_DISPLAY)` + `gi.require_version` in `setUpClass`); tests that build `MainWindow` follow `tests/test_vocal_split_placement.py` (register an `Adw.Application`, `addCleanup(window.set_application, None)`).
- Test command used below: `T="$HOME/.claude/skills/testing-gtk-headless/scripts/run-private-wayland.sh -- env UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 .venv/bin/python -m unittest"`. Do not pipe it; redirect to a file and read the file.
- After any `.blp` change: `./resources/compile_resources.sh`, then `./resources/compile_resources.sh --check`, then `blueprint-compiler lint` on the changed file (only new, non-translation warnings matter). Format and lint every touched Python file with `.venv/bin/ruff format` / `.venv/bin/ruff check`.

## Review Focus

1. **Repeated method switching** (VR → MDX → Demucs → VR): Separation's Output group must show exactly the active view's lead rows, then Format, then Output folder — no duplicates, no missing rows, tooltip from the active view. Pinned in Task 3.
2. **Editing a row after it moved** must still persist through the page's shared session (format change after a method switch, inputs after a tool switch). Pinned in Tasks 3 and 5.
3. **Vocal splitter selection survives moves:** switching Separation methods must not reset the splitter model or write `NO_MODEL` (lazy-combo gate). Pinned in Task 3.
4. **Tool switching keeps per-tool state:** Align → Apollo → Align keeps Align's rows and the Advanced align expander's expanded state; dual tools still show the pairs row instead of the files row. Pinned in Task 5.
5. **Narrow layout order:** in the single-column layout the order is Input, page section, Output, Processing on every page. Pinned in Task 6.

---

### Task 1: RowSlot helper

**Files:**
- Create: `ui/widgets/row_slot.py`
- Test: `tests/test_row_slot.py`

**Interfaces:**
- Produces: `class RowSlot` with `__init__(self, group: Adw.PreferencesGroup, *, trailing: Sequence[Gtk.Widget] = ())`, property `rows -> tuple[Gtk.Widget, ...]`, `replace(self, rows: Sequence[Gtk.Widget]) -> None`, `append_trailing(self, row: Gtk.Widget) -> None`. Rows added to the group before the slot is created stay above it.

- [ ] **Step 1: Write the failing tests** (GTK-guarded class `RowSlotTests`). Helper `_order(group)` returns the rows in display order (walk the group's internal `Gtk.ListBox` children; libadwaita wraps them in its listbox).
  - `test_replace_places_rows_before_trailing`: group with leading row `L`, slot with trailing `(T1, T2)`, `replace([A, B])` → order `[L, A, B, T1, T2]`.
  - `test_replace_swaps_contents`: then `replace([C])` → `[L, C, T1, T2]`; `A.get_parent()` is `None`.
  - `test_empty_slot`: `replace([])` → `[L, T1, T2]`; `slot.rows == ()`.
  - `test_moves_row_from_another_group`: `A` first added to `other_group`; `replace([A])` → `A` in this group's order and not in `other_group`'s.
  - `test_append_trailing_goes_last`: `append_trailing(T3)` after `replace([A])` → `[L, A, T1, T2, T3]`.
- [ ] **Step 2: Run** `$T tests.test_row_slot > /tmp/rs.log 2>&1` — expected: errors, module missing.
- [ ] **Step 3: Implement `RowSlot`.** To move a row, find its current owning group with `row.get_ancestor(Adw.PreferencesGroup)` and call that group's `remove(row)`. `replace` removes current slot rows and trailing rows, adds the new rows, then re-adds the trailing rows. No GTK import at module scope beyond `gi.repository` (same as other widgets).
- [ ] **Step 4: Run** the same command — expected: `OK`.
- [ ] **Step 5: Commit** `feat(ui): RowSlot swaps a run of rows inside a preferences group`.

### Task 2: Shared page group builder

**Files:**
- Create: `resources/ui/page-groups.blp`, `ui/widgets/page_groups.py`
- Test: `tests/test_page_groups.py`

**Interfaces:**
- Consumes: `RowSlot` (Task 1); `InputFilesRow`, `OutputFolderRow` (`ui/widgets/file_chooser.py`); `OutputFormatRow`, `FormatEdit` (`ui/widgets/format_row.py`); `shared_settings_bindings`, `apply_shared_file_options`, `SharedSettingsBindings`, `SharedFileOptions`, `sample_mode_subtitle`, `SAMPLE_MODE_TITLE` (as used today in `ui/window.py`).
- Produces (exact):
  ```python
  @dataclass(frozen=True)
  class PageGroupCallbacks:
      on_inputs_changed: Callable[[], None]
      on_output_changed: Callable[[], None]
      on_format_changed: Callable[[FormatEdit], None]
      toast: Callable[[str], None]
      hint: Callable[[Gtk.Widget, str], object]
      accept_any_getter: Callable[[], bool]
      initial_folder_getter: Callable[[], str | None]
      sample_duration: int = 30
      view_inputs_action: str | None = "win.view_inputs"
      on_view_inputs: Callable[[], None] | None = None
      on_gpu_changed: Callable[[], None] | None = None
      on_autocast_changed: Callable[[], None] | None = None
      on_sample_changed: Callable[[], None] | None = None

  ProcessingRow = Literal["gpu", "autocast", "sample"]

  class PageGroups:
      input_group: Adw.PreferencesGroup; output_group: Adw.PreferencesGroup
      processing_group: Adw.PreferencesGroup
      input_row: InputFilesRow; output_row: OutputFolderRow; format_row: OutputFormatRow
      gpu_row: Adw.SwitchRow | None; autocast_row: Adw.SwitchRow | None
      sample_row: Adw.SwitchRow | None
      view_inputs_button: Gtk.Button
      def add_input_row(self, row: Gtk.Widget) -> None
      def set_output_lead(self, rows: Sequence[Gtk.Widget]) -> None
      def add_output_tail(self, row: Gtk.Widget) -> None
      def add_processing(self, row: Gtk.Widget) -> None
      def bindings(self, *, vocal_row: ReadableVocalSplitRow | None = None) -> SharedSettingsBindings
      def apply(self, settings: Settings) -> SharedFileOptions

  def build_page_groups(callbacks: PageGroupCallbacks, *,
                        processing: Collection[ProcessingRow] = ("gpu", "autocast", "sample")) -> PageGroups
  ```
- Group/row order produced: Input = `[input_row, *add_input_row rows]`; Output = `[*lead, format_row, output_row, *tail]`; Processing = `[gpu, autocast, sample (those requested, in that order), *add_processing rows]`.

- [ ] **Step 1: Write the failing tests** (`PageGroupsTests`, GTK-guarded; reuse Task 1's `_order` helper by importing it from `tests.test_row_slot`).
  - `test_titles`: the three groups' `get_title()` are `"Input"`, `"Output"`, `"Processing"`.
  - `test_output_order_with_lead_and_tail`: `set_output_lead([A, B])`, `add_output_tail(C)` → Output order `[A, B, format_row, output_row, C]`.
  - `test_processing_subset`: `processing=("gpu",)` → `autocast_row is None`, `sample_row is None`, Processing order `[gpu_row]`.
  - `test_bindings_cover_supplied_rows`: full build → `bindings().use_gpu`, `.autocast`, `.sample_mode`, `.export_path`, `.input_paths`, `.save_format` are not `None`; `vocal_splitter_enabled is None` without `vocal_row`. With `processing=("gpu",)` → `.autocast is None` and `.sample_mode is None`.
  - `test_apply_pushes_settings`: a `Settings()` with `process.export_path="/tmp/out"`, `process.use_gpu=True`, `process.sample_mode=True` → after `apply(settings)`, `output_row.path == "/tmp/out"`, `gpu_row.get_active()`, `sample_row.get_active()`.
  - `test_switch_callbacks_take_no_arguments`: `on_gpu_changed=mock.Mock()`; `gpu_row.set_active(True)` → mock called once with no arguments.
  - `test_hints_attached`: `hint=mock.Mock()` → called with `(input_row, INPUT_FOLDER_ENTRY_HELP)`, `(output_row, OUTPUT_FOLDER_ENTRY_HELP)`, `(gpu_row, IS_GPU_CONVERSION_HELP)`, `(autocast_row, IS_AUTOCAST_HELP)`, `(sample_row, MODEL_SAMPLE_MODE_HELP)`.
  - `test_view_inputs_button`: default → `view_inputs_button.get_action_name() == "win.view_inputs"`; with `view_inputs_action=None, on_view_inputs=cb` → no action name, `clicked` calls `cb`.
- [ ] **Step 2: Run** `$T tests.test_page_groups > /tmp/pg.log 2>&1` — expected: errors, module missing.
- [ ] **Step 3: Write `resources/ui/page-groups.blp`.** Objects: `input_group` (title `"Input"`, `[header-suffix]` flat `Gtk.Button view_inputs_button`, icon `view-list-symbolic`, `valign: center`), `output_group` (title `"Output"`), `processing_group` (title `"Processing"`), and `gpu_row` / `autocast_row` / `sample_row` copied from `resources/ui/separation-groups.blp` (same titles, prefixes and FP16 subtitle). Compile resources.
- [ ] **Step 4: Implement `build_page_groups`** in `ui/widgets/page_groups.py`: load the builder once per call (`load_builder("page-groups")`), create the three rows with the callbacks (`InputFilesRow(on_inputs_changed, on_toast=toast, accept_any_getter=…, initial_folder_getter=…)`, `OutputFolderRow(on_output_changed, on_toast=toast)`, `OutputFormatRow(on_format_changed)`), connect each requested switch's `notify::active` to a lambda calling its callback with no arguments, set the sample row title/subtitle from `SAMPLE_MODE_TITLE` / `sample_mode_subtitle(callbacks.sample_duration)`, attach the five hints, and use a `RowSlot(output_group, trailing=(format_row, output_row))` behind `set_output_lead` / `add_output_tail`. Unrequested switches are never added to a group and are exposed as `None`.
- [ ] **Step 5: Run** the tests — expected: `OK`. Ruff format/check both files; basedpyright on the project.
- [ ] **Step 6: Commit** `feat(ui): shared builder for the run pages' Input, Output and Processing groups`.

### Task 3: Separation adopts the builder

**Files:**
- Modify: `ui/window.py` (`_build_files_group` 612-631, `_build_method_group` 633-655, `_build_model_options_group` 728-738, `_build_shared_group` 740-765, `_populate_columns` 460-498, `_register_hints` ~790, `_install_shared_session` / `_apply_shared_widgets` ~876-900)
- Modify: `ui/views/base.py` (`_update_stem_group_metadata` 461-516), `ui/widgets/output_stems.py` (`OutputStemsSection.__init__`), `ui/hints.py` (`HelpHintManager.register`)
- Modify: `resources/ui/separation-groups.blp` (remove `files_group`, `processing_group`, `gpu_row`, `autocast_row`, `sample_row`)
- Create: `tests/test_page_layout_contract.py`
- Modify: `tests/test_vocal_split_placement.py`, `tests/test_method_view_refresh.py` (only if the hook changes break its stubs)

**Interfaces:**
- Consumes: `build_page_groups`, `PageGroups`, `PageGroupCallbacks` (Task 2).
- Produces:
  - `OutputStemsSection(section, host: Adw.PreferencesGroup | None, *, use_direct_controls=True)`; property `rows -> tuple[Adw.PreferencesRow, Adw.ActionRow]` = `(quick row, summary row)`. With `host=None` nothing is added to a group.
  - `MethodView.on_output_tooltip: Callable[[str], None] | None` (default `None`); `_update_stem_group_metadata` calls it with the composed tooltip when set.
  - `HelpHintManager.register(widget, text)` replaces an existing entry for the same widget instead of appending.
  - `MainWindow._page_groups: PageGroups`; `MainWindow._col_start` / `_col_end` unchanged.
  - Test helpers in `tests/test_page_layout_contract.py`: `column_titles(column: Gtk.Box) -> list[str]` (titles of the column's direct children) and `contains(group: Gtk.Widget, row: Gtk.Widget) -> bool` (`row.is_ancestor(group)`), reused by Tasks 4–6.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_page_layout_contract.py`, class `SeparationLayoutTests` (builds `MainWindow`; for each method index of `window.method_row`): `column_titles(window._col_start) == ["Input", "Model"]`, `column_titles(window._col_end) == ["Output", "Processing"]`, `contains(left Model group, window.vocal_split_row)`, `contains(window._page_groups.output_group, window.format_row)` and `window.output_row` likewise.
  - `test_output_rows_after_repeated_switching` (Review Focus 1): switch VR → MDX → Demucs → VR; Output group order is `[*active_view.output_stems.rows, format_row, output_row]` and each inactive view's rows have no `Adw.PreferencesGroup` ancestor inside the window.
  - `test_output_tooltip_follows_active_view`: after switching to a view, the Output group's tooltip equals that view's latest composed tooltip (spy `on_output_tooltip`).
  - `test_format_edit_after_switch_persists` (Review Focus 2): with the Separation tab visible, switch method, change `format_row` to FLAC through the same path a user edit takes (its format combo), call `window._flush_settings()`, then `settings.process.save_format == "FLAC"`.
  - `test_vocal_splitter_survives_switching` (Review Focus 3): set `settings.process.vocal_splitter` to a value present in the row's list (or stub the list as `tests/test_vocal_split_placement.py` does), switch methods twice, row's `model_value` and the setting are unchanged.
  - `tests/test_hints.py` (or the existing hints test module if one covers `HelpHintManager`): `test_register_replaces_existing_entry` — register a widget twice with different text; `len(manager._registry) == 1`; tooltip is the second text after `refresh()`.
- [ ] **Step 2: Run** `$T tests.test_page_layout_contract > /tmp/lc.log 2>&1` — expected: failures (Vocal splitter in Processing; Output group is the view's `stem_group`).
- [ ] **Step 3: Implement.**
  - Build `self._page_groups = build_page_groups(PageGroupCallbacks(…), processing=("gpu","autocast","sample"))` in place of `_build_files_group` / `_build_shared_group`'s row creation, with `hint=self._hint_manager.register`, Separation's existing `initial_folder_getter`, and its existing switch handlers. Assign `self.files_group`, `self.shared_group`, `self.input_row`, `self.output_row`, `self.format_row`, `self.gpu_row`, `self.autocast_row`, `self.sample_row` from it. Remove the five hint registrations now done by the builder from `_register_hints`.
  - `self.vocal_split_row` is created as today but not added to Processing; track `self._vocal_row_host` like `_model_options_host`, and in `_populate_columns` move it into `view.group` right after `model_options_row`.
  - `_populate_columns`: left = `[files_group, view.group]`; right = `[self._page_groups.output_group, self.shared_group]`; call `self._page_groups.set_output_lead(view.output_stems.rows)`; delete the `_output_rows_host` reparenting and the `view.stem_group.set_title("Output")` retitle.
  - On a switch, clear the previous view's `on_output_tooltip`, set the new view's to a function that does `self._hint_manager.register(self._page_groups.output_group, text)`, then call `view._update_stem_group_metadata(refresh_workload=False)` so the tooltip is current.
  - `_install_shared_session` / `_apply_shared_widgets`: use `self._page_groups.bindings(vocal_row=self.vocal_split_row)` and `self._page_groups.apply(self.settings)` (keep the vocal row's own apply call if `_apply_shared_widgets` has one today).
  - `OutputStemsSection`: make `host` optional and add `rows`. `MethodView` keeps passing `self.stem_group` (it becomes the off-screen holder).
- [ ] **Step 4: Run** `$T tests.test_page_layout_contract tests.test_vocal_split_placement tests.test_method_view_refresh tests.test_flush_settings_tab_guard tests.test_inactive_view_stem_focus > /tmp/t3.log 2>&1` — expected: `OK`. Rename the two `*_processing_group_hosts_the_row` tests in `tests/test_vocal_split_placement.py` to `*_model_side_hosts_the_row` and assert the row's left-column ancestor.
- [ ] **Step 5: Full suite** `$T discover -s tests -t . > /tmp/full.log 2>&1` — expected: `OK`. Then `.venv/bin/python -m basedpyright` — `0 errors`.
- [ ] **Step 6: Commit** `feat(ui): Separation builds its shared groups and keeps one Output group`.

### Task 4: Ensemble adopts the builder

**Files:**
- Modify: `ui/ensemble/window.py` (`__init__` layout 228-252, `_build_files_group` 261-275, `_build_stems_group` 394-405, `_build_output_group` 407-~470, `_install_shared_session` / `_apply_shared_widgets` 512-535, `_update_ensemble_options_summary` 1338-~1370 and its calls at 390, 1202, 1219, 1236, 1259, 1299, 1570)
- Modify: `resources/ui/ensemble-page.blp` (remove `files_group`, `stems_group`, `processing_group`, `gpu_row`, `autocast_row`, `sample_row`; move `member_options_row` out of `advanced_row` to a top-level object)
- Modify: `tests/test_page_layout_contract.py`, `tests/test_ensemble_page_design.py`, `tests/test_ensemble_ui_helpers.py`

**Interfaces:**
- Consumes: Task 2 builder; `OutputStemsSection(…, host=None).rows` (Task 3); contract-test helpers (Task 3).

- [ ] **Step 1: Write the failing tests** in `tests/test_page_layout_contract.py`, class `EnsembleLayoutTests`: `column_titles(page._col_start) == ["Input", "Ensemble", "Combination"]`; `column_titles(page._col_end) == ["Output", "Processing"]`; Ensemble group contains `page.member_options_row` and `page.vocal_split_row`; Output group order `[*page.output_stems.rows, format_row, output_row, save_all_row]`; Processing contains the `advanced_row` expander whose rows are exactly `append_name_row` and `wav_ensemble_row`; `page._layout_object("combination_group", Adw.PreferencesGroup).get_description()` is empty or `None`.
- [ ] **Step 2: Run** `$T tests.test_page_layout_contract > /tmp/lc.log 2>&1` — expected: Ensemble cases fail.
- [ ] **Step 3: Implement.** Build page groups with `hint=set_tooltip` (Ensemble's mechanism), Ensemble's handlers, `sample_duration=self.settings.process.sample_mode_duration`, and an `initial_folder_getter` with the same expression Separation uses (folder of the first entry in `settings.process.input_paths`, else `None`); `processing=("gpu","autocast","sample")`; keep the attribute aliases from Global Constraints (`stems_group = groups.output_group`). Construct `OutputStemsSection(self.save_stems, None)` and `set_output_lead(self.output_stems.rows)`; `add_output_tail(self.save_all_row)`; `add_processing(advanced_row)`. Add `member_options_row` then `vocal_split_row` to `ensemble_group` after `models_trigger_row`. Columns: left `(input_group, ensemble_group, combination_group)`, right `(output_group, processing_group)`. Delete `_update_ensemble_options_summary` and its seven calls; delete `ensemble_options_summary` from its helper module only if `rg` finds no other caller; delete the two summary tests in `tests/test_ensemble_ui_helpers.py` (`test_karaoke_plan_summary_uses_stacked_role_on_the_left`, `test_noop_dual_native_keeps_independent_algorithm_summary`). Remove Ensemble's own hint registrations for the five builder-owned rows.
- [ ] **Step 4: Run** `$T tests.test_page_layout_contract tests.test_ensemble_page_design tests.test_ensemble_ui_helpers tests.test_ensemble_flush_settings tests.test_vocal_split_placement tests.test_run_control > /tmp/t4.log 2>&1` — expected: `OK` (update `test_ensemble_page_design.py` only where it asserts the old group of the output folder).
- [ ] **Step 5: Full suite** and basedpyright as in Task 3 — `OK`, `0 errors`.
- [ ] **Step 6: Commit** `feat(ui): Ensemble follows the shared layout`.

### Task 5: Audio Tools adopts the builder and a Tool group

**Files:**
- Modify: `ui/audio_tools/window.py` (`__init__` layout 177-195, `_build_files_group` 215-246, `_build_select_group` 248-257, `_build_tool_stack` and the per-tool `_build_*_page` methods 259-~400, `_build_shared_group` 481-~525, `_sync_tool_visibility` / `_sync_files_visibility` 640-667, `sync_processing_from_settings` and the load path that sets `testing_row` ~586, `_install_shared_session` / `_apply_shared_widgets` 594-613)
- Modify: `resources/ui/audio-tools-page.blp` (remove `files_group`, `select_group`'s untitled wrapper → `tool_group` titled `"Tool"` holding `tool_row`, remove `processing_group`, `apollo_gpu_row`, `testing_row`, `tool_stack`; keep each tool's settings group as an unparented holder; add `description: "Line up two recordings of the same song";` to the Align group and drop its `title`; move `apollo_folder_button` to a `[suffix]` of `apollo_model_row`)
- Modify: `tests/test_page_layout_contract.py`, `tests/test_flush_settings_tab_guard.py` (only alias-related breakage), tests that reference `testing_row` or `tool_stack`

**Interfaces:**
- Consumes: Task 1 `RowSlot`; Task 2 builder; contract-test helpers (Task 3).
- Produces: `AudioToolsPage.tool_group: Adw.PreferencesGroup`; `AudioToolsPage._tool_rows: dict[str, tuple[Gtk.Widget, ...]]` (tool name → its settings rows, empty tuple for Matchering); `AudioToolsPage._col_start` / `_col_end`.

- [ ] **Step 1: Write the failing tests** in `tests/test_page_layout_contract.py`, class `AudioToolsLayoutTests`, for every entry of `AUDIO_TOOL_ORDER`: `column_titles(page._col_start) == ["Input", "Tool"]`; `column_titles(page._col_end) == ["Output", "Processing"]`; Tool group order `[tool_row, *page._tool_rows[tool]]`; `tool_row.get_subtitle()` equals the tool holder group's description (`None`/empty for Matchering); Output group order `[format_row, output_row]`; Processing order `[gpu_row, normalize_row, amplification_row]`; `gpu_row.get_visible()` only for Apollo Restore; `page` has no `testing_row` attribute.
  - `test_tool_switch_keeps_rows_and_expander` (Review Focus 4): select Align, expand its Advanced align expander, switch to Apollo then back → Align's rows are the slot contents again and the expander is still expanded.
  - `test_dual_tools_show_pairs_row` (Review Focus 4): for each tool in `DUAL_INPUT_TOOLS`, `dual_inputs_row` visible and `input_row` hidden; for Manual Ensemble the reverse.
  - `test_inputs_edit_after_tool_switch_persists` (Review Focus 2): show the tab (`window.content_stack.set_visible_child_name("audio_tools")`), switch tools, call `page.input_row.set_paths([path])` with notification on (its change callback commits immediately while the tab is visible), then `settings.process.input_paths == [path]`.
- [ ] **Step 2: Run** `$T tests.test_page_layout_contract > /tmp/lc.log 2>&1` — expected: Audio Tools cases fail.
- [ ] **Step 3: Implement.** Build page groups with `hint=self.hints.register`, `processing=("gpu",)`, the same `initial_folder_getter` expression as Separation, `view_inputs_action=None, on_view_inputs=lambda: self._on_view_inputs_clicked(None)` (Audio Tools' button is not an action today), and Audio Tools' handlers; keep the aliases from Global Constraints. `add_input_row(self.dual_inputs_row)`; `add_processing(normalize_row)`, `add_processing(amplification_row)`; delete `testing_row` and its load/sync code. Build `tool_group` with `tool_row` and `self._tool_slot = RowSlot(tool_group)`; collect each tool's rows into `_tool_rows` while building its holder group; in `_sync_tool_visibility` call `self._tool_slot.replace(self._tool_rows[tool])` and set `tool_row` subtitle from the holder's description. Keep `_sync_files_visibility` setting the Input group's description (now `self._page_groups.input_group`). Columns: left `(input_group, tool_group)`, right `(output_group, processing_group)`; keep `_col_start` / `_col_end`.
- [ ] **Step 4: Run** `$T tests.test_page_layout_contract tests.test_flush_settings_tab_guard tests.test_audio_tools_preferences_resync tests.test_view_inputs > /tmp/t5.log 2>&1` — expected: `OK`.
- [ ] **Step 5: Full suite** and basedpyright as in Task 3 — `OK`, `0 errors`.
- [ ] **Step 6: Commit** `feat(ui): Audio Tools follows the shared layout with one Tool group`.

### Task 6: Narrow order and visual verification

**Files:**
- Modify: `tests/test_page_layout_contract.py`

- [ ] **Step 1: Write the test** `test_narrow_layout_keeps_rule_order` (Review Focus 5): for each page's `columns_box`, call `set_columns_narrow(box, True)`; the box is vertical and the concatenation `column_titles(col_start) + column_titles(col_end)` starts with `"Input"` and ends with `["Output", "Processing"]`.
- [ ] **Step 2: Run** `$T tests.test_page_layout_contract > /tmp/lc.log 2>&1` — expected: `OK` (this pins existing behaviour; if it fails, fix the column order, not the test).
- [ ] **Step 3: Render and measure.** Render every page state (3 Separation methods, Ensemble, 6 tools) at 1280×900, 720×900 and 1280×900 dark on the private display with an isolated `UVR_DATA_DIR` (copy `settings.json`, symlink `models/`). Measure left − right content height per page. Expected within ±30 px of the spec's targets: Separation VR/MDX ≈ −40, Demucs ≈ −95, Ensemble ≈ +110, Manual Ensemble ≈ +5, Align ≈ +250. Report any page outside the band with its screenshot instead of tuning silently.
- [ ] **Step 4: Final checks:** full suite `OK`; basedpyright `0 errors`; `./resources/compile_resources.sh --check` matches; ruff clean on all touched files.
- [ ] **Step 5: Commit** `test(ui): pin the shared layout order in the narrow layout`.
