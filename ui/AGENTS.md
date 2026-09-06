# UI layer (GTK4 / libadwaita)

Loaded when working under `ui/`. Layer rules, invariants and repo workflow live in the root [AGENTS.md](../AGENTS.md).

## Widget behaviour and diagnosis

- `Adw.Dialog.get_content_width()` is the *requested* width and never tracks allocation; `notify::content-width` only fires when code sets it. Drive responsive dialog layout from an `Adw.Breakpoint`.
- Diagnose GTK layout/rendering by inspecting live widget state, not by reasoning from source. Walk the tree printing `type(w).__name__`, `w.get_css_classes()` and geometry via `get_first_child()`/`get_next_sibling()`; for animations, sample across frames with `GLib.timeout_add(16, ...)`. Three wrong theories this way cost more than the probe that settled it.
- libadwaita composites hide behaviour in internal children: `Adw.Banner` wraps its content in a `Gtk.Revealer` (an animated slide-down), and `Adw.ToolbarView` stacks top bars in a `Gtk.Box` carrying libadwaita's `collapse-spacing` class. Reach them by walking for the type/class and degrade gracefully — they are implementation details.
- Animating an `Adw.ToolbarView` top bar re-allocates all content beneath it every frame (observed during past `Adw.Banner` layout measurements; timing depends on the installed version). Reveal top bars instantly unless you have measured the reflow.
- `Adw.Dialog` using breakpoints needs an explicit minimum via `set_size_request(...)`. `set_content_width`/`set_content_height` are only *preferred* sizes; without a minimum libadwaita warns ("does not have a minimum size") and can allocate below the content's minimum, clipping children.
- Drive the real app non-interactively for measurement: build `UVRApplication()`, arm `GLib.timeout_add(ms, lambda: (app.quit(), False)[1])`, then `app.run([])`. Scratch scripts need `PYTHONPATH=.` — `bundled` is not installed into the venv.
- `cProfile` on Python 3.14 instruments **every** thread, not just the caller. A naive startup profile blames the main loop for the `uvr-separate-warm` thread's torch import — which is correctly lazy. Attribute per call (`threading.current_thread() is MAIN`) before believing that anything blocks the main loop.

## Model-list refresh

- Widget selection state is the canonical `ModelRecord.id`; `display` is a replaceable label and must never be resolved back to identity.
- Inventory and presentation notifications both coalesce through `MainWindow._refresh_models()`. Snapshot the selected ID before invalidating a lazy picker and repick safely after rebuilding it.
- New model-list surfaces must expose `refresh_models()` and join `MainWindow._model_list_consumers()`.
- Vocal Splitter remains filtered exclusively by karaoke/BV metadata; display wording must not affect eligibility.

## Settings coupling

- The Save-stems widget ([ui/widgets/stem_only.py](widgets/stem_only.py)) is a GTK adapter over [`core/stem_selection.py`](../core/stem_selection.py), which writes `process.stem_focus` (a concept, `raw:…` tag, or positional `primary`/`secondary` sentinel) in every branch — including the ones that clear it back to `""`. Miss a branch and the widget looks right while `--profile gui` and the plan-time diagnostics inherit a stale concept.

### Flush / preflight contract

Shared keys and where they may be written:

- **`process.stem_focus`** — Save Stems on the active separation method only (`MethodView.save(include_stem_only=True)` → `_persist_stem_only`). Ensemble: `EnsemblePage._flush_run_settings()` before `build_job_spec` / `start`. Never from inactive VR/MDX/Demucs views.
- **Format/quality, GPU, autocast, sample mode, vocal splitter, I/O** — per-page typed bindings in [`SharedSettingsSession`](shared_settings.py). Each page commits only fields it edited; immediate commits advance the displayed baseline so later flushes cannot replay old edits. All three sessions gate writes on their visible tab. `MainWindow._flush_settings` retains the Separation guard; Ensemble and Audio Tools flush shared edits before spec/start. The global Verify Inputs callback remains a separate input authority and adopts the Separation input baseline even while another tab is visible.

Rules for new UI:

- Add shared controls to the typed binding factory and each page's refresh. Route interactive callbacks through the exact field handle and programmatic loads through `session.refresh`; keep method-specific and Save Stems owners separate. Format events adopt the restored active quality before committing format; quality events edit only that quality. Vocal model writes require the populated canonical picker and its repick gate. Run pages must not call the format/vocal rows' legacy whole-widget persistence methods.
- **Anti-pattern:** calling `save_stems.persist_to_settings()` from `save_options()` or any path that runs when `include_stem_only=False` (Demucs/MDX regression: inactive Demucs `quick_all` cleared MDX Instrumental focus before plan review).

## Presentation and lifecycle ownership

- Download Center renders `CatalogueBrowserState` rows and keeps its ordered
  `(arch, name)` selection and public pinned snapshot there. Display search and
  raw-label totals intentionally have different predicates. Hide retains the
  cached window; terminal `DownloadCenterWindow.dispose()` releases its
  subscriptions, timers and late UI deliveries. `DownloadQueueUiBinding.dispose()`
  delegates to the center only while it retains ownership; rebind transfers ownership. `AppContext.download_manager`
  and `download_queue` are the shared lazy service owners.
- Ensemble acquires records/eligibility, projects members purely, renders them
  without Settings writes, then explicitly reconciles at the existing successful
  nonempty-list triggers. Early returns and saved-preset outer persistence keep
  their separate semantics.
- RunController consumes `RunTarget`/`RunHost` behaviors, `RunProgressPresenter`
  and `RunShutdownCoordinator`. Error context snapshots use the visible target
  at begin_run; polling and cleanup ordering are tested with an injected scheduler.
- Save Stems keeps core `StemSelectionState` as its reducer; `StemPresentation`
  supplies immutable summaries, dimming and visibility. Tests own compatibility
  proxy vocabulary in `tests/stem_ui_helpers.py`.

- `core.error_log` owns thread-safe storage; `ui.errorlog` owns weak GTK delivery
  through the main loop and lifetime disposal. Keep `RunErrorContext` snapshots
  independent of current widget state when delayed reports arrive.
- Download completion integration uses a real queue worker,
  `latest_main_thread`/GLib coalescing, the visible indicator and the cached
  center's `refresh_after_downloads`. Test transfers/finalizers are external
  boundaries; do not replace dispatch with synchronous calls to prove delivery.
  Run `tests.test_download_queue_completion_ui` through the private runner and
  explicit private-display guard described in the environment guide.
