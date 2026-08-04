# UI layer (GTK4 / libadwaita)

Loaded when working under `ui/`. Layer rules, invariants and repo workflow live in the root [CLAUDE.md](../CLAUDE.md).

## Widget behaviour and diagnosis

- `Adw.Dialog.get_content_width()` is the *requested* width and never tracks allocation; `notify::content-width` only fires when code sets it. Drive responsive dialog layout from an `Adw.Breakpoint`.
- Diagnose GTK layout/rendering by inspecting live widget state, not by reasoning from source. Walk the tree printing `type(w).__name__`, `w.get_css_classes()` and geometry via `get_first_child()`/`get_next_sibling()`; for animations, sample across frames with `GLib.timeout_add(16, ...)`. Three wrong theories this way cost more than the probe that settled it.
- libadwaita composites hide behaviour in internal children: `Adw.Banner` wraps its content in a `Gtk.Revealer` (250ms slide-down), and `Adw.ToolbarView` stacks top bars in a `Gtk.Box` carrying libadwaita's `collapse-spacing` class. Reach them by walking for the type/class and degrade gracefully — they are implementation details.
- Animating an `Adw.ToolbarView` top bar re-allocates all content beneath it every frame (measured: 13 relayouts per 250ms `Adw.Banner` slide). Reveal top bars instantly unless you have measured the reflow.
- `Adw.Dialog` needs `set_size_request(...)`. `set_content_width`/`set_content_height` are only *preferred* sizes; without a minimum libadwaita warns ("does not have a minimum size") and can allocate below the content's minimum, clipping children.
- `cProfile` on Python 3.14 instruments **every** thread, not just the caller. A naive startup profile blames the main loop for the `uvr-separate-warm` thread's ~1.6 s torch import — which is correctly lazy. Attribute per call (`threading.current_thread() is MAIN`) before believing that anything blocks the main loop.
