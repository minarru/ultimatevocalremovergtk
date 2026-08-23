# UI layer (GTK4 / libadwaita)

Loaded when working under `ui/`. Layer rules, invariants and repo workflow live in the root [CLAUDE.md](../CLAUDE.md).

## Widget behaviour and diagnosis

- `Adw.Dialog.get_content_width()` is the *requested* width and never tracks allocation; `notify::content-width` only fires when code sets it. Drive responsive dialog layout from an `Adw.Breakpoint`.
- Diagnose GTK layout/rendering by inspecting live widget state, not by reasoning from source. Walk the tree printing `type(w).__name__`, `w.get_css_classes()` and geometry via `get_first_child()`/`get_next_sibling()`; for animations, sample across frames with `GLib.timeout_add(16, ...)`. Three wrong theories this way cost more than the probe that settled it.
- libadwaita composites hide behaviour in internal children: `Adw.Banner` wraps its content in a `Gtk.Revealer` (250ms slide-down), and `Adw.ToolbarView` stacks top bars in a `Gtk.Box` carrying libadwaita's `collapse-spacing` class. Reach them by walking for the type/class and degrade gracefully — they are implementation details.
- Animating an `Adw.ToolbarView` top bar re-allocates all content beneath it every frame (measured: 13 relayouts per 250ms `Adw.Banner` slide). Reveal top bars instantly unless you have measured the reflow.
- `Adw.Dialog` needs `set_size_request(...)`. `set_content_width`/`set_content_height` are only *preferred* sizes; without a minimum libadwaita warns ("does not have a minimum size") and can allocate below the content's minimum, clipping children.
- Drive the real app non-interactively for measurement: build `UVRApplication()`, arm `GLib.timeout_add(ms, lambda: (app.quit(), False)[1])`, then `app.run([])`. Scratch scripts need `PYTHONPATH=.` — `bundled` is not installed into the venv.
- `cProfile` on Python 3.14 instruments **every** thread, not just the caller. A naive startup profile blames the main loop for the `uvr-separate-warm` thread's ~1.6 s torch import — which is correctly lazy. Attribute per call (`threading.current_thread() is MAIN`) before believing that anything blocks the main loop.

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
- **Format, GPU, autocast, sample mode, vocal splitter, separation I/O** — separation-page widgets; flushed in `MainWindow._flush_settings` only when the Separation tab is visible (stale-widget guard). Ensemble and Audio Tools keep their own live copies on their tabs.

Rules for new UI:

- If a widget writes a key used across tabs or methods, persist live on change **and** flush before `build_job_spec`, or gate writes on the active tab/method — never persist from a stale inactive surface.
- **Anti-pattern:** calling `save_stems.persist_to_settings()` from `save_options()` or any path that runs when `include_stem_only=False` (Demucs/MDX regression: inactive Demucs `quick_all` cleared MDX Instrumental focus before plan review).
