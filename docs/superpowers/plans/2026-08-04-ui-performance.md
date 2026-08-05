# UI Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove one main-loop CPU spin and ~940 ms of blocking main-thread work from the GTK4 UVR app, all verified by measurement rather than inspection.

**Architecture:** Six independent, individually revertable fixes. Three are pure caching/deferral in `core/` (memoize the catalogue merge, honour the politrees disk-cache TTL, defer icon-theme registration). Two remove pathological widget behaviour in `ui/widgets/console.py` (a self-re-arming idle source, a full-buffer copy per `DONE`). One replaces a full Download Center row rebuild with GTK's own `set_sort_func`. No layering changes: `ui` → `core` stays one-directional and nothing new is imported at `core` import time.

**Tech Stack:** Python 3.14, GTK4 + libadwaita via PyGObject, stdlib `unittest`, basedpyright (`standard` mode).

## Global Constraints

- **Tests are stdlib `unittest`, never pytest.** Run with `.venv/bin/python -m unittest ...`.
- **GTK tests must guard on a display.** Use `@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "GTK widget construction needs a display")` on the class, with `gi.require_version("Gtk", "4.0")` / `("Adw", "1")` inside `setUpClass`. The suite must still pass where GTK is unavailable.
- **Never call `widget.destroy()`** in a test or script — with no running main loop it segfaults.
- **No tkinter anywhere.** No new imports of `torch`, `onnxruntime`, or `engines` at `core` import time.
- **Widget state goes through `ui/widget_state.py`** (`stash`/`fetch`), never `row._uvr_foo = x`. Keys keep the `_uvr_` prefix.
- **Type checking must pass:** `.venv/bin/python -m basedpyright` clean over `ui/ core/ engines/ tests/`. Do not widen a GTK type to `Any` to silence an error.
- **Search with `rg`**, not `grep`.
- **Never run unscoped `git checkout -- .`, `git restore .`, `git reset --hard`, `git stash` or `git clean`.** This tree carries long-lived uncommitted edits under `models/*/model_data/`. Stage explicitly; never `git add -A`.
- **Baseline for every task:** `.venv/bin/python -m unittest discover -s tests` must pass before and after.

## Measured Baseline

Recorded 2026-08-04 on this machine, for regression comparison:

| Symptom | Measurement |
|---|---|
| `ConsoleView._do_scroll` while unmapped | 132,433 invocations in 0.50 s (~265k/s, pins a core) |
| `_ensure_model_combos_populated` (44 models installed) | 1,897 ms main-thread; ~800 ms steady-state |
| `format_tag_title` ×30 | 3,460,359 calls / 0.82 s; 57 full catalogue merges |
| `_merged_for_display` at startup | 625 ms main-thread across 8 calls |
| `politrees/_urlopen` at startup | 445 ms main-thread across 2 calls |
| `_register_application_icon` at startup | 312 ms main-thread (`has_icon` 101 ms → `add_search_path` → `has_icon` 164 ms) |
| Download Center catalogue build | 469 rows, 67 ms, repeated on every sort change |
| Time to window | ~1.9 s |

**Caution when re-profiling:** `cProfile` on Python 3.14 instruments *all* threads, not just the caller. A naive startup profile attributes the `uvr-separate-warm` thread's 1.6 s torch import to the main thread. Use per-call thread attribution (`threading.current_thread() is MAIN`) to confirm anything is really on the main loop.

---

### Task 1: Stop the console idle busy-loop

`ui/widgets/console.py:149-153` re-arms itself with `GLib.idle_add` whenever the view is unmapped. An idle source that is always ready means the main loop never blocks: it pins a CPU core and starves the `idle_add`-dispatched worker→UI callbacks, which sit at the same default priority. Trigger in the real app: expand the log panel mid-run (which clears `_defer_scroll` via `resume_scroll`), then collapse it again or minimise the window — every subsequent `append()` spins for the rest of the separation.

Fix: re-arm on the widget's next `map` signal instead of on idle.

**Files:**
- Modify: `ui/widgets/console.py:32-35` (add handler id), `ui/widgets/console.py:149-156` (`_do_scroll`)
- Test: `tests/test_console_scroll.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ConsoleView._map_handler_id: Optional[int]`, `ConsoleView._scroll_when_mapped() -> None`. No public API change.

- [ ] **Step 1: Write the failing test**

Create `tests/test_console_scroll.py`:

```python
"""An unmapped ConsoleView must not spin the GTK main loop.

ui/widgets/console.py:_do_scroll used to re-add itself with GLib.idle_add when
the view was not mapped. An idle source that is always ready means the main
loop never blocks, pinning a core and starving the worker->UI callbacks that
ui/dispatch.py schedules at the same priority.
"""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class ConsoleScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.console-scroll")
        cls._app.register()

    def _drain(self, iterations: int = 200) -> None:
        """Pump the default main context without blocking."""
        from gi.repository import GLib

        ctx = GLib.MainContext.default()
        for _ in range(iterations):
            if not ctx.iteration(False):
                break

    def test_unmapped_append_does_not_spin_idle(self) -> None:
        from ui.widgets.console import ConsoleView

        console = ConsoleView()
        self.assertFalse(console.get_mapped(), "fixture expects an unmapped view")

        calls = {"n": 0}
        original = console._do_scroll

        def counted() -> bool:
            calls["n"] += 1
            return original()

        console._do_scroll = counted  # type: ignore[method-assign]
        console.append("worker output line\n")
        self._drain()

        # With the bug this reaches the full drain count; the fix parks on
        # the "map" signal instead, so the idle runs at most once.
        self.assertLessEqual(
            calls["n"], 2, f"idle source re-armed {calls['n']} times while unmapped"
        )

    def test_unmapped_scroll_is_rearmed_on_map(self) -> None:
        from ui.widgets.console import ConsoleView

        console = ConsoleView()
        console.append("line\n")
        self._drain()
        self.assertIsNotNone(
            console._map_handler_id, "expected a pending map handler while unmapped"
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_console_scroll -v`
Expected: FAIL — `test_unmapped_append_does_not_spin_idle` reports ~200 re-arms; `test_unmapped_scroll_is_rearmed_on_map` fails with `AttributeError`/`None` on `_map_handler_id`.

- [ ] **Step 3: Add the handler-id slot**

In `ui/widgets/console.py`, in `__init__` alongside the other source ids (currently lines 32-35):

```python
        self._scroll_idle_id: Optional[int] = None
        self._reconcile_scroll_id: Optional[int] = None
        self._viewport_idle_id: Optional[int] = None
        self._map_handler_id: Optional[int] = None
        self._defer_scroll = False
```

- [ ] **Step 4: Replace the self-re-arming idle**

Replace `_do_scroll` (currently lines 149-156) with:

```python
    def _do_scroll(self) -> bool:
        self._scroll_idle_id = None
        if not self.get_mapped():
            # Re-arming another idle here spins the main loop: an idle source
            # that is always ready means the loop never blocks. Park on the
            # next map instead.
            self._scroll_when_mapped()
            return GLib.SOURCE_REMOVE

        self._scroll_view_to_end()
        return GLib.SOURCE_REMOVE

    def _scroll_when_mapped(self) -> None:
        """Defer the pending scroll until this view is mapped again."""
        if self._map_handler_id is not None:
            return

        def on_map(_widget: Gtk.Widget) -> None:
            if self._map_handler_id is not None:
                self.disconnect(self._map_handler_id)
                self._map_handler_id = None
            self._scroll_to_end()

        self._map_handler_id = self.connect("map", on_map)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_console_scroll -v`
Expected: PASS, both tests.

- [ ] **Step 6: Verify no regression in the suite and the type checker**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: PASS (same count as baseline, plus 2).

Run: `.venv/bin/python -m basedpyright`
Expected: 0 errors.

- [ ] **Step 7: Commit**

```bash
git add ui/widgets/console.py tests/test_console_scroll.py
git commit -m "fix(ui): stop console scroll spinning the main loop while unmapped"
```

---

### Task 2: Memoize the catalogue merge

`core/model_display.py:231 _merged_for_display()` rebuilds the whole merged catalogue on every call — `_display_base()` three times (each re-reading and re-parsing `bundled/model_manual_download.json`), then `_build_meta` plus `dedupe_download_catalogue`. Nothing caches it. `_ensure_model_combos_populated` calls `format_tag_title` per tag, so populating one expander triggers dozens of full rebuilds: 3.46 M Python calls and 0.82 s for just 30 tags.

The function takes no arguments, so a `maxsize=1` cache is exact. It must be invalidated wherever its inputs can change: the politrees cache and the on-disk hash mappers.

**Files:**
- Modify: `core/model_display.py:231-244` (`_merged_for_display`), plus a new `clear_display_cache`
- Modify: `core/politrees_catalog.py:47-51` (`clear_politrees_cache`)
- Modify: `core/model_data.py:127` (`reload_mappers`)
- Test: `tests/test_model_display_cache.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `core.model_display.clear_display_cache() -> None`. Called by `core.politrees_catalog.clear_politrees_cache()` and `ModelRepository.reload_mappers()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_model_display_cache.py`:

```python
"""_merged_for_display must be memoized and explicitly invalidatable.

Rebuilding it per call made format_tag_title ~9 ms, so populating one
secondary-model expander cost ~800 ms of main-thread time.
"""

from __future__ import annotations

import unittest
from unittest import mock

import core.model_display as md


class MergedForDisplayCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        md.clear_display_cache()

    def tearDown(self) -> None:
        md.clear_display_cache()

    def test_repeated_calls_reuse_one_merge(self) -> None:
        import core.catalog_sources as cs

        real = cs.merged_catalogues
        with mock.patch.object(cs, "merged_catalogues", side_effect=real) as spy:
            first = md._merged_for_display()
            second = md._merged_for_display()
        self.assertIs(first, second)
        self.assertEqual(spy.call_count, 1)

    def test_clear_display_cache_forces_rebuild(self) -> None:
        first = md._merged_for_display()
        md.clear_display_cache()
        second = md._merged_for_display()
        self.assertIsNot(first, second)

    def test_clear_politrees_cache_invalidates_display_cache(self) -> None:
        from core.politrees_catalog import clear_politrees_cache

        first = md._merged_for_display()
        clear_politrees_cache()
        second = md._merged_for_display()
        self.assertIsNot(
            first, second, "politrees feeds _display_base; its cache must invalidate"
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_display_cache -v`
Expected: FAIL — `AttributeError: module 'core.model_display' has no attribute 'clear_display_cache'`.

- [ ] **Step 3: Memoize and expose the invalidator**

In `core/model_display.py`, add `import functools` to the imports, then replace `_merged_for_display` (currently lines 231-244) with:

```python
@functools.lru_cache(maxsize=1)
def _merged_for_display():
    """Merged catalogues built from the upstream cache plus every supplement.

    Reads the same merge the Download Center does, which is the whole point:
    two separate merge paths are what left mvsepless and extras models showing
    as raw basenames here while the Download Center named them correctly.

    Memoized: this walks every catalogue source and re-reads
    ``model_manual_download.json``, and ``format_tag_title`` calls it once per
    dropdown entry. Invalidate through :func:`clear_display_cache` whenever a
    source changes (politrees refresh, hash-mapper reload).
    """
    from .catalog_sources import merged_catalogues

    return merged_catalogues(
        vr=_display_base(_VR_CATALOG_SOURCE_KEYS),
        mdx=_display_base(_MDX_CATALOG_SOURCE_KEYS),
        demucs=_display_base(_DEMUCS_CATALOG_SOURCE_KEYS),
    )


def clear_display_cache() -> None:
    """Drop the memoized catalogue merge (call when any source changes)."""
    _merged_for_display.cache_clear()
```

- [ ] **Step 4: Invalidate from the politrees cache**

In `core/politrees_catalog.py`, replace `clear_politrees_cache` (currently lines 47-51) with:

```python
def clear_politrees_cache() -> None:
    global _cached_links, _cached_weight_index, _cached_loaded_at
    _cached_links = None
    _cached_weight_index = None
    _cached_loaded_at = 0.0
    # Local import: core.model_display imports this module for _display_base.
    from .model_display import clear_display_cache

    clear_display_cache()
```

- [ ] **Step 5: Invalidate from the hash-mapper reload**

In `core/model_data.py`, in `reload_mappers` (starts line 127), add the invalidation immediately after the `debug("model", "reload_mappers")` line:

```python
    def reload_mappers(self) -> None:
        from .debug_log import debug
        from .model_display import clear_display_cache

        debug("model", "reload_mappers")
        clear_display_cache()
```

- [ ] **Step 6: Run the new tests**

Run: `.venv/bin/python -m unittest tests.test_model_display_cache -v`
Expected: PASS, all three.

- [ ] **Step 7: Run the full suite — this task is the one most likely to break others**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: PASS.

Several existing tests patch `core.catalog_sources.load_politrees_links` and then assert on merged output (`tests/test_extra_catalog.py`, `tests/test_mvsepless_catalog.py`, `tests/test_catalog_dedupe.py`, `tests/test_mdx_c_registry.py`, `tests/test_model_display.py`). If any now sees a stale merge, add `core.model_display.clear_display_cache()` to that test's `setUp` — do **not** weaken the cache. Record which tests needed it in the commit message.

- [ ] **Step 8: Measure the win**

```bash
PYTHONPATH=. UVR_DISABLE_POLITREES=1 .venv/bin/python -c "
import time
from bundled.constants import INST_STEM, VOCAL_STEM
from core import ModelRepository, Settings
from core.model_display import format_tag_title
s = Settings.load(); repo = ModelRepository()
v = repo.model_list(s, VOCAL_STEM, INST_STEM, is_no_demucs=True)
[format_tag_title(t, repo) for t in v]
t = time.perf_counter(); [format_tag_title(t2, repo) for t2 in v]
print(f'{len(v)} labels: {(time.perf_counter() - t) * 1000:.1f} ms')
"
```
Expected: well under 20 ms (baseline 273 ms).

- [ ] **Step 9: Type check and commit**

Run: `.venv/bin/python -m basedpyright`
Expected: 0 errors.

```bash
git add core/model_display.py core/politrees_catalog.py core/model_data.py tests/test_model_display_cache.py
git commit -m "perf(core): memoize the display catalogue merge"
```

---

### Task 3: Honour the politrees disk-cache TTL

`core/politrees_catalog.py:75 load_politrees_links` always attempts the network first and only reads the disk cache **when the fetch fails**. The 24 h TTL guards the in-process cache only, so a perfectly fresh `~/.cache/uvr/politrees_model_links.json` still costs a full round trip. This runs on the main thread during `MethodView.load()` (window construction): measured 445 ms locally, and up to the 30 s `urlopen` timeout behind a captive portal or dead DNS, with no window on screen.

Fix: if the on-disk entry is within TTL, use it and return immediately, kicking off one background refresh so the cache stays warm.

**Files:**
- Modify: `core/politrees_catalog.py:30-32` (globals), `:54-62` (`_read_disk_cache`), `:75-105` (`load_politrees_links`)
- Test: `tests/test_politrees_startup_cache.py` (create)

**Interfaces:**
- Consumes: `core.model_display.clear_display_cache` (Task 2) — already wired via `clear_politrees_cache`.
- Produces: `_read_disk_cache_entry() -> Optional[Tuple[Dict, float]]`, `_start_background_refresh() -> None`. `load_politrees_links(*, force: bool = False) -> Optional[Dict]` keeps its existing signature and return type.

- [ ] **Step 1: Write the failing test**

Create `tests/test_politrees_startup_cache.py`:

```python
"""A fresh on-disk politrees cache must not cost a startup network round trip.

load_politrees_links used to fetch first and only fall back to disk on failure,
so window construction blocked on HTTP (measured 445 ms; up to the 30 s urlopen
timeout on a bad network) even with a valid cache on disk.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest import mock

import core.politrees_catalog as pc


class PolitreesStartupCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self._tmp.name, "politrees_model_links.json")
        self._patch = mock.patch.object(
            pc, "_politrees_cache_path", return_value=self.cache_path
        )
        self._patch.start()
        pc.clear_politrees_cache()

    def tearDown(self) -> None:
        self._patch.stop()
        pc.clear_politrees_cache()
        self._tmp.cleanup()

    def _write_cache(self, fetched_at: float) -> None:
        payload = {"fetched_at": fetched_at, "data": {"mdx_download_list": {"M": "m.onnx"}}}
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_fresh_disk_cache_skips_the_network(self) -> None:
        self._write_cache(time.time())
        with mock.patch.object(
            pc, "_urlopen", side_effect=AssertionError("network hit despite fresh cache")
        ), mock.patch.object(pc, "_start_background_refresh") as refresh:
            data = pc.load_politrees_links()
        self.assertIsNotNone(data)
        assert data is not None
        self.assertIn("mdx_download_list", data)
        refresh.assert_called_once()

    def test_stale_disk_cache_still_fetches(self) -> None:
        self._write_cache(time.time() - (pc._POLITREES_CACHE_TTL_SECONDS + 60))
        with mock.patch.object(pc, "_urlopen", side_effect=OSError("offline")):
            data = pc.load_politrees_links()
        # Falls back to the stale disk copy rather than returning nothing.
        self.assertIsNotNone(data)

    def test_force_bypasses_the_disk_cache(self) -> None:
        self._write_cache(time.time())
        with mock.patch.object(pc, "_urlopen", side_effect=OSError("offline")) as opener:
            pc.load_politrees_links(force=True)
        opener.assert_called_once()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_politrees_startup_cache -v`
Expected: FAIL — `test_fresh_disk_cache_skips_the_network` raises the `AssertionError("network hit despite fresh cache")`, and `_start_background_refresh` does not exist.

- [ ] **Step 3: Add the refresh guard globals**

In `core/politrees_catalog.py`, add `import threading` to the imports and extend the globals block (currently lines 30-32):

```python
_cached_links: Optional[Dict] = None
_cached_weight_index: Optional[Dict[str, str]] = None
_cached_loaded_at: float = 0.0
_refresh_lock = threading.Lock()
_refresh_in_flight = False
```

- [ ] **Step 4: Read the disk cache with its timestamp**

Add alongside `_read_disk_cache` (keep the existing function — the network-failure fallback still uses it):

```python
def _read_disk_cache_entry() -> Optional[Tuple[Dict, float]]:
    """Return ``(data, fetched_at)`` from the on-disk cache, or ``None``."""
    try:
        with open(_politrees_cache_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            return None
        fetched_at = payload.get("fetched_at")
        if not isinstance(fetched_at, (int, float)):
            return None
        return payload["data"], float(fetched_at)
    except (OSError, ValueError, TypeError):
        return None
```

- [ ] **Step 5: Add the background refresh**

```python
def _start_background_refresh() -> None:
    """Refresh the catalogue off the main loop; at most one in flight."""
    global _refresh_in_flight
    with _refresh_lock:
        if _refresh_in_flight:
            return
        _refresh_in_flight = True

    def run() -> None:
        global _refresh_in_flight
        try:
            load_politrees_links(force=True)
        except Exception as exc:  # noqa: BLE001 - background best-effort
            debug("download", f"politrees background refresh failed err={exc}")
        finally:
            with _refresh_lock:
                _refresh_in_flight = False

    threading.Thread(target=run, name="uvr-politrees-refresh", daemon=True).start()
```

- [ ] **Step 6: Consult the disk cache before the network**

Replace the body of `load_politrees_links` between the `politrees_enabled()` guard and the `data: Optional[Dict] = None` line with:

```python
    now = time.time()
    if (
        not force
        and _cached_links is not None
        and (now - _cached_loaded_at) < _POLITREES_CACHE_TTL_SECONDS
    ):
        return _cached_links

    if not force:
        entry = _read_disk_cache_entry()
        if entry is not None and (now - entry[1]) < _POLITREES_CACHE_TTL_SECONDS:
            # A fresh cache on disk is authoritative: fetching here blocked
            # window construction on HTTP for no benefit.
            _cached_links = entry[0]
            _cached_weight_index = None
            _cached_loaded_at = now
            _start_background_refresh()
            return _cached_links

    data: Optional[Dict] = None
```

Leave the rest of the function (the `_urlopen` attempt, `_read_disk_cache` fallback, and `_write_disk_cache`) exactly as it is. Add `Tuple` to the `typing` import line if it is not already there.

- [ ] **Step 7: Run the new tests**

Run: `.venv/bin/python -m unittest tests.test_politrees_startup_cache -v`
Expected: PASS, all three.

- [ ] **Step 8: Verify the startup network cost is gone**

```bash
PYTHONPATH=. .venv/bin/python -c "
import time, core.politrees_catalog as pc
pc.load_politrees_links(force=True)   # ensure a fresh cache on disk
pc.clear_politrees_cache()            # drop the in-process copy
t = time.perf_counter(); pc.load_politrees_links()
print(f'warm-disk load: {(time.perf_counter() - t) * 1000:.1f} ms')
"
```
Expected: single-digit ms (baseline 229-445 ms).

- [ ] **Step 9: Full suite, type check, commit**

Run: `.venv/bin/python -m unittest discover -s tests`
Run: `.venv/bin/python -m basedpyright`
Expected: PASS / 0 errors.

```bash
git add core/politrees_catalog.py tests/test_politrees_startup_cache.py
git commit -m "perf(core): honour the politrees disk-cache TTL before fetching"
```

---

### Task 4: Defer application-icon registration off the startup path

`ui/resources.py:43 _register_application_icon` costs ~312 ms of main-thread time inside `do_startup`, before the window is presented: `theme.has_icon()` is a cold icon-theme scan (101 ms), `add_search_path` invalidates the theme, and the confirming `has_icon` on line 77 pays a second, more expensive scan (164 ms). The registered name is consumed by exactly one caller — `Adw.AboutDialog` via `application_icon=APP_ID` in `ui/about.py:111` — and `open_about` already calls `register_gresources()` before building the dialog.

Fix: drop the icon registration from `register_gresources()` and have About ask for it explicitly.

**Files:**
- Modify: `ui/resources.py:114-124` (`register_gresources`), add `ensure_application_icon`
- Modify: `ui/about.py:100-105` (`open_about`)
- Test: `tests/test_resources_icon_deferral.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ui.resources.ensure_application_icon() -> bool` — public wrapper around the existing private `_register_application_icon`, same return semantics (`True` once the icon name resolves).

- [ ] **Step 1: Write the failing test**

Create `tests/test_resources_icon_deferral.py`:

```python
"""Application-icon registration must not run during do_startup.

Two full Gtk.IconTheme scans (~312 ms measured) blocked the window for an icon
name only Adw.AboutDialog ever consumes.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK icon theme access needs a display",
)
class IconDeferralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.icon-deferral")
        cls._app.register()

    def test_register_gresources_skips_the_icon_scan(self) -> None:
        import ui.resources as resources

        with mock.patch.object(resources, "_register_application_icon") as icon:
            resources.register_gresources()
        icon.assert_not_called()

    def test_ensure_application_icon_performs_registration(self) -> None:
        import ui.resources as resources

        with mock.patch.object(
            resources, "_register_application_icon", return_value=True
        ) as icon:
            self.assertTrue(resources.ensure_application_icon())
        icon.assert_called_once()

    # SUPERSEDED during execution — do not implement as written.
    # Review found this asserts a token's presence, not behaviour: it passes
    # even if the call is commented out (the same string appears in the
    # adjacent comment), moved after dialog construction, or reduced to a dead
    # import. Human ruling: replace with a behavioural test that patches
    # ensure_application_icon, asserts open_about invokes it once, AND asserts
    # it runs BEFORE the dialog is constructed — an icon registered after
    # Adw.AboutDialog is built does not resolve for that dialog.
    def test_about_registers_icon_before_building_dialog(self) -> None:
        ...  # see tests/test_resources_icon_deferral.py for the shipped version


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_resources_icon_deferral -v`
Expected: FAIL — `register_gresources` still calls `_register_application_icon`, and `ensure_application_icon` does not exist.

- [ ] **Step 3: Split the icon registration out**

In `ui/resources.py`, replace `register_gresources` (currently lines 114-124) with:

```python
def register_gresources() -> bool:
    """Register the compiled GResource bundle and add its icon theme path.

    Safe to call more than once (e.g. from ``do_startup`` and again from
    ``do_activate`` if the display was not ready yet). Returns ``True`` when the
    bundle is loaded; the icon theme path is added whenever a display exists.

    Deliberately does **not** register the application icon: that costs two full
    ``Gtk.IconTheme`` scans (~312 ms) and only ``Adw.AboutDialog`` consumes the
    name. Call :func:`ensure_application_icon` at the point of use instead.
    """
    loaded = _register_bundle()
    _register_icon_theme()
    return loaded


def ensure_application_icon() -> bool:
    """Register ``packaging/<app-id>.png`` with the icon theme (idempotent).

    Deferred out of startup; call immediately before showing anything that
    names ``APP_ID`` as an icon.
    """
    return _register_application_icon()
```

- [ ] **Step 4: Have About request the icon**

In `ui/about.py`, in `open_about` (starts line 100), replace the import and call:

```python
def open_about(parent_window: typing.Any):
    """Open an About dialog summarising UVR. Wire this to a ``win.about`` action."""
    from .resources import ensure_application_icon, register_gresources

    register_gresources()
    # application_icon=APP_ID below only resolves once this has run.
    ensure_application_icon()
```

- [ ] **Step 5: Run the new tests**

Run: `.venv/bin/python -m unittest tests.test_resources_icon_deferral -v`
Expected: PASS, all three.

- [ ] **Step 6: Confirm the About dialog still shows its icon**

Run:
```bash
PYTHONPATH=. timeout 30 .venv/bin/python -c "
import gi
gi.require_version('Gtk','4.0'); gi.require_version('Gdk','4.0'); gi.require_version('Adw','1')
from gi.repository import Gdk, Gtk, Adw
Adw.init()
import ui.resources as R
R.register_gresources()
theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
print('before ensure:', theme.has_icon(R.APP_ID))
R.ensure_application_icon()
print('after ensure: ', theme.has_icon(R.APP_ID))
"
```
Expected: `before ensure: False`, `after ensure: True`.

- [ ] **Step 7: Full suite, type check, commit**

Run: `.venv/bin/python -m unittest discover -s tests`
Run: `.venv/bin/python -m basedpyright`
Expected: PASS / 0 errors.

```bash
git add ui/resources.py ui/about.py tests/test_resources_icon_deferral.py
git commit -m "perf(ui): defer application-icon registration to About"
```

---

### Task 5: Stop copying the whole console buffer on every `DONE`

`ui/widgets/console.py:82` guards the `DONE` marker with `self.get_text().endswith("\n")`. `get_text()` copies the entire buffer — up to the 5000-line cap — into a Python string just to inspect one character. Engines emit `DONE` once per stage per model, so this runs repeatedly through a long ensemble run.

**Files:**
- Modify: `ui/widgets/console.py:78-92` (`append`), add `_ends_with_newline`
- Test: `tests/test_console_scroll.py` (extend — same widget, same suite)

**Interfaces:**
- Consumes: `ConsoleView` from Task 1 (same file; apply Task 1 first to avoid a conflicting edit).
- Produces: `ConsoleView._ends_with_newline() -> bool`. `append()` behaviour is unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_console_scroll.py`, inside `ConsoleScrollTests`:

```python
    def test_done_marker_skipped_without_an_open_line(self) -> None:
        from bundled.constants import DONE
        from ui.widgets.console import ConsoleView

        console = ConsoleView()
        console.append("Running inference...\n")
        console.append(DONE)
        self.assertNotIn(DONE.strip(), console.get_text())

    def test_done_marker_appended_to_an_open_line(self) -> None:
        from bundled.constants import DONE
        from ui.widgets.console import ConsoleView

        console = ConsoleView()
        console.append("Running inference...")
        console.append(DONE)
        self.assertIn(DONE.strip(), console.get_text())

    # SUPERSEDED during execution — do not implement as written.
    # Review found this only proves `append` stopped calling the ConsoleView
    # wrapper `self.get_text()`; it does not prove the buffer isn't copied. A
    # later change copying via `self._buffer.get_text(start, end, False)`
    # would pass this test while reintroducing the O(n) regression. Human
    # ruling: spy on `Gtk.TextBuffer.get_text` and assert the copied span is
    # one character, so any full-buffer copy is caught regardless of API path.
    # Restore the spy in a finally/mock.patch.object — a leaked class-level
    # patch on a GTK type breaks unrelated tests.
    def test_done_check_does_not_copy_the_buffer(self) -> None:
        ...  # see tests/test_console_scroll.py for the shipped version
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_console_scroll -v`
Expected: FAIL on `test_done_check_does_not_copy_the_buffer` with "append() copied the whole buffer for the DONE check". The other two pass (they assert existing behaviour, which must be preserved).

- [ ] **Step 3: Add the cheap end-of-buffer check**

In `ui/widgets/console.py`, add below `append`:

```python
    def _ends_with_newline(self) -> bool:
        """Whether the buffer's last character is a newline.

        ``get_text()`` would copy the whole buffer (up to the line cap) to
        inspect one character; ``append`` runs this on every ``DONE`` marker.
        """
        end = self._buffer.get_end_iter()
        if end.get_offset() == 0:
            return False
        start = end.copy()
        start.backward_char()
        return self._buffer.get_text(start, end, False) == "\n"
```

- [ ] **Step 4: Use it in `append`**

Replace the guard at the top of `append` (currently lines 82-83):

```python
        if text == DONE and (self.is_empty() or self._ends_with_newline()):
            return
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_console_scroll -v`
Expected: PASS, all five.

- [ ] **Step 6: Full suite, type check, commit**

Run: `.venv/bin/python -m unittest discover -s tests`
Run: `.venv/bin/python -m basedpyright`
Expected: PASS / 0 errors.

```bash
git add ui/widgets/console.py tests/test_console_scroll.py
git commit -m "perf(ui): check the console's last character without copying the buffer"
```

---

### Task 6: Sort the Download Center in place instead of rebuilding

`ui/download_center.py:362 _on_sort_changed` calls `_rebuild_catalogue()`, which tears down and reconstructs all 469 `Adw.ActionRow`s (67 ms measured) and then has to re-apply every checked selection to work around its own destructiveness. Purpose filtering already does the right thing with `invalidate_filter`; sorting should mirror it with GTK's `set_sort_func` / `invalidate_sort`.

**Files:**
- Modify: `ui/download_center.py:313` (add `set_sort_func`), `:362-368` (`_on_sort_changed`), `:399-426` (`_add_model_row`), `:428-444` (`_add_unsupported_row`), `:784-812` (`_rebuild_catalogue`), plus a new `_invalidate_all_sorts`
- Test: `tests/test_download_center_sort.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `DownloadCenterWindow._compare_rows(row1, row2) -> int`, `_row_sort_key(row) -> tuple[int, int, float, str]`, `_invalidate_all_sorts() -> None`. Rows gain a `_uvr_sort_name` stash key.

- [ ] **Step 1: Write the failing test**

Create `tests/test_download_center_sort.py`:

```python
"""Changing Sort must reorder rows in place, not rebuild the catalogue.

_rebuild_catalogue reconstructs all ~469 Adw.ActionRows (67 ms measured) and
then has to re-apply every checked selection to undo its own destructiveness.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class DownloadCenterSortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.dc-sort")
        cls._app.register()

    def _window(self):
        from ui.download_center import DownloadCenterWindow

        return DownloadCenterWindow.__new__(DownloadCenterWindow)

    def test_sort_change_does_not_rebuild(self) -> None:
        from ui.download_center import SORT_OPTIONS

        window = self._window()
        window._sort_mode = SORT_OPTIONS[0][0]
        window.sort_row = mock.MagicMock()
        window._list_boxes = {}

        with mock.patch.object(
            type(window), "_rebuild_catalogue", autospec=True
        ) as rebuild, mock.patch.object(
            type(window), "_invalidate_all_sorts", autospec=True
        ) as invalidate, mock.patch(
            "ui.download_center.get_combo_value", return_value=SORT_OPTIONS[1][1]
        ):
            window._on_sort_changed()

        rebuild.assert_not_called()
        invalidate.assert_called_once()
        self.assertEqual(window._sort_mode, SORT_OPTIONS[1][0])

    def test_sdr_sort_key_orders_high_scores_first(self) -> None:
        from core.model_scores import SORT_SDR
        from gi.repository import Adw
        from ui.widget_state import stash

        window = self._window()
        window._sort_mode = SORT_SDR

        high = Adw.ActionRow()
        stash(high, "_uvr_sort_name", "high")
        stash(high, "_uvr_sdr", 12.0)
        stash(high, "_uvr_unsupported", False)

        low = Adw.ActionRow()
        stash(low, "_uvr_sort_name", "low")
        stash(low, "_uvr_sdr", 3.0)
        stash(low, "_uvr_unsupported", False)

        self.assertLess(window._compare_rows(high, low), 0)

    def test_unsupported_rows_sort_last(self) -> None:
        from core.model_scores import SORT_NAME
        from gi.repository import Adw
        from ui.widget_state import stash

        window = self._window()
        window._sort_mode = SORT_NAME

        supported = Adw.ActionRow()
        stash(supported, "_uvr_sort_name", "zzz")
        stash(supported, "_uvr_sdr", None)
        stash(supported, "_uvr_unsupported", False)

        unsupported = Adw.ActionRow()
        stash(unsupported, "_uvr_sort_name", "aaa")
        stash(unsupported, "_uvr_sdr", None)
        stash(unsupported, "_uvr_unsupported", True)

        self.assertLess(window._compare_rows(supported, unsupported), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_download_center_sort -v`
Expected: FAIL — `_invalidate_all_sorts` and `_compare_rows` do not exist.

- [ ] **Step 3: Stash a sort name on every row**

In `ui/download_center.py`, in `_add_model_row` (line 399), add after the existing `stash(action, "_uvr_stems_text", stems_text)`:

```python
        stash(action, "_uvr_sort_name", canonical_display_name(name).casefold())
```

In `_add_unsupported_row` (line 428), add after `stash(action, "_uvr_stems_text", "")`:

```python
        stash(action, "_uvr_sort_name", canonical_display_name(name).casefold())
```

- [ ] **Step 4: Add the comparison functions**

Add as methods on `DownloadCenterWindow`, next to `_row_matches_filter`:

```python
    def _row_sort_key(self, row: typing.Any) -> tuple[int, int, float, str]:
        """Order key: supported first, then the active sort mode, then name."""
        unsupported = 1 if fetch(row, "_uvr_unsupported", False) else 0
        name = fetch(row, "_uvr_sort_name", "")
        if self._sort_mode == SORT_SDR and not unsupported:
            sdr = fetch(row, "_uvr_sdr", None)
            if sdr is None:
                # Unscored models sink below scored ones, as in the old sort.
                return (unsupported, 1, 0.0, name)
            return (unsupported, 0, -float(sdr), name)
        return (unsupported, 0, 0.0, name)

    def _compare_rows(self, row1: typing.Any, row2: typing.Any) -> int:
        left = self._row_sort_key(row1)
        right = self._row_sort_key(row2)
        if left < right:
            return -1
        return 1 if left > right else 0

    def _invalidate_all_sorts(self) -> None:
        for arch, list_box in self._list_boxes.items():
            list_box.invalidate_sort()
            self._update_catalogue_page_state(arch)
```

No new imports needed: `ui/download_center.py:46` already has `from .widget_state import fetch, stash`, and `SORT_SDR` / `SORT_NAME` / `SORT_OPTIONS` already come in from `core.model_scores` at line 26.

- [ ] **Step 5: Attach the sort func to each list box**

In the catalogue-page builder, immediately after the existing `set_filter_func` call (line 313):

```python
        list_box.set_filter_func(lambda row, a=arch: self._row_matches_filter(row, a))
        list_box.set_sort_func(lambda r1, r2: self._compare_rows(r1, r2))
```

- [ ] **Step 6: Make the sort control invalidate instead of rebuild**

Replace the body of `_on_sort_changed` (line 362):

```python
    def _on_sort_changed(self, *_args: typing.Any) -> None:
        label = get_combo_value(self.sort_row) or SORT_OPTIONS[0][1]
        self._sort_mode = next(
            (value for value, text in SORT_OPTIONS if text == label),
            SORT_NAME,
        )
        # Re-sorting in place keeps every checked row, the way Purpose
        # filtering always has. Rebuilding dropped the selection.
        self._invalidate_all_sorts()
```

- [ ] **Step 7: Drop the now-redundant Python sort**

In `_rebuild_catalogue` (line 784) the list box sorts itself now, so the Python-side sort is dead. **Delete lines 793-804 outright** — the whole `if self._sort_mode == SORT_SDR: ... else: ...` block including the nested `_sort_key` function. Do **not** replace it with anything: lines 805-806 already are the add-row loop, so the region must read:

```python
            models = [
                name
                for name in (self._available.get(arch) or [])
                if name not in (NO_NEW_MODELS, NO_CONNECTION)
            ]
            for name in models:
                self._add_model_row(arch, name)
            unsupported = sorted(
```

Leave the `unsupported` loop, `invalidate_filter()`, `_update_catalogue_page_state(arch)` and the selection re-application below it untouched — genuine rebuilds (a refresh after downloads) still need them. `_row_score` stays in use from `_add_model_row`; do not delete it.

- [ ] **Step 8: Run the new tests**

Run: `.venv/bin/python -m unittest tests.test_download_center_sort -v`
Expected: PASS, all three.

- [ ] **Step 9: Verify the existing Download Center regression tests still hold**

Run: `.venv/bin/python -m unittest tests.test_download_center_state tests.test_download_center_search -v`
Expected: PASS. `tests/test_download_center_state.py` specifically covers "sort changes silently dropped every checked selection" — in-place sorting must satisfy it inherently.

- [ ] **Step 10: Full suite, type check, commit**

Run: `.venv/bin/python -m unittest discover -s tests`
Run: `.venv/bin/python -m basedpyright`
Expected: PASS / 0 errors.

```bash
git add ui/download_center.py tests/test_download_center_sort.py
git commit -m "perf(ui): re-sort the Download Center in place instead of rebuilding"
```

---

### Task 7: Verify the end-to-end win and record the profiling trap

**Files:**
- Modify: `ui/CLAUDE.md`
- Test: none (measurement task)

**Interfaces:**
- Consumes: all preceding tasks.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Re-measure startup with per-thread attribution**

Write `/tmp/uvr-prof/prof_mainthread.py` (create the directory first):

```python
"""Attribute startup cost to the main loop specifically.

cProfile on 3.14 captures every thread, so a plain startup profile mixes the
uvr-separate-warm thread's torch import into main-thread numbers.
"""

import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib  # noqa: E402

MAIN = threading.current_thread()
records: dict[str, list] = {}


def wrap(module, attr, label):
    orig = getattr(module, attr)

    def timed(*a, **k):
        t0 = time.perf_counter()
        try:
            return orig(*a, **k)
        finally:
            dt = time.perf_counter() - t0
            records.setdefault(label, []).append(
                (dt, threading.current_thread() is MAIN)
            )

    setattr(module, attr, timed)


import core.mdx_config_fetch as mcf  # noqa: E402
import core.model_display as md  # noqa: E402
import ui.resources as resources  # noqa: E402
import ui.widgets.rows as rows  # noqa: E402

wrap(resources, "_register_application_icon", "_register_application_icon")
wrap(resources, "register_gresources", "register_gresources")
wrap(rows, "set_combo_values", "set_combo_values")
wrap(rows, "make_combo_row", "make_combo_row")
wrap(mcf, "_urlopen", "politrees/_urlopen")
wrap(md, "_merged_for_display", "_merged_for_display")

from ui.application import UVRApplication  # noqa: E402

t0 = time.perf_counter()
app = UVRApplication()


def stop():
    print(f"\n=== window up after {time.perf_counter() - t0:.2f}s ===")
    print(f"{'call':30s} {'n':>4s} {'main-thread total':>18s} {'off-main':>10s}")
    for label, entries in sorted(
        records.items(), key=lambda kv: -sum(d for d, m in kv[1] if m)
    ):
        on = sum(d for d, m in entries if m)
        off = sum(d for d, m in entries if not m)
        n_on = sum(1 for _, m in entries if m)
        print(f"{label:30s} {n_on:4d} {on * 1000:15.1f} ms {off * 1000:8.1f} ms")
    app.quit()
    return False


GLib.timeout_add(1500, stop)
app.run([])
```

Run: `mkdir -p /tmp/uvr-prof && PYTHONPATH=. timeout 60 .venv/bin/python /tmp/uvr-prof/prof_mainthread.py`

Note that `_register_application_icon` will be absent from the output entirely after Task 4 — a wrapped callable that is never invoked records nothing.

Expected versus baseline:

| call | baseline | target |
|---|---|---|
| `_merged_for_display` | 625.1 ms | < 200 ms |
| `politrees/_urlopen` | 445.1 ms | 0 ms (warm disk cache) |
| `_register_application_icon` | 311.7 ms | not called |
| time to window | ~1.9 s | ~1.0 s |

- [ ] **Step 2: Confirm the console no longer spins**

```bash
PYTHONPATH=. timeout 30 .venv/bin/python -c "
import time, gi
gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')
from gi.repository import GLib
from ui.widgets.console import ConsoleView
c = ConsoleView(); calls = {'n': 0}; orig = c._do_scroll
def counted():
    calls['n'] += 1; return orig()
c._do_scroll = counted
c.append('line\n')
loop = GLib.MainLoop()
GLib.timeout_add(500, lambda: (loop.quit(), False)[1])
loop.run()
print('invocations in 0.5s:', calls['n'])
"
```
Expected: a single-digit count (baseline 132,433).

- [ ] **Step 3: Record the profiling trap in the UI notes**

Add to the bullet list in `ui/CLAUDE.md`:

```markdown
- `cProfile` on Python 3.14 instruments **every** thread, not just the caller. A naive startup profile blames the main loop for the `uvr-separate-warm` thread's ~1.6 s torch import — which is correctly lazy. Attribute per call (`threading.current_thread() is MAIN`) before believing that anything blocks the main loop.
```

- [ ] **Step 4: Commit**

```bash
git add ui/CLAUDE.md
git commit -m "docs(ui): note that cProfile on 3.14 is thread-global"
```

---

### Task 8: Fix the mvsepless sibling and the stale-TTL rewrite

Added during execution after Task 7's measurement missed the startup target (~1.5–1.6 s vs ~1.0 s). Two defects, both in code Tasks 1–7 left alone.

**8a — the missed sibling.** `core/mvsepless_catalog.py:216 load_mvsepless_models` has the *identical* pre-Task-3 shape as `load_politrees_links`: it always tries `_urlopen` first (line 233) and reads the disk cache only when that fails (line 237). Its TTL guard (lines 224-229) covers the in-process cache only. It runs on the GTK main thread at startup through `catalog_sources._supplemental_sources()`. Task 3 fixed one of the two siblings; this fixes the other.

**8b — the stale-TTL rewrite.** In *both* modules, the network-failure branch sets `data = _read_disk_cache()` and then falls through to `_write_disk_cache(data)`, which stamps `fetched_at = time.time()` onto the copy it just read back. The TTL clock resets on data that was never refreshed, so an offline session makes month-old data look freshly fetched — and after 8a lands, the next process start would treat it as fresh and skip the network indefinitely. Task 3's reviewer flagged this; it was out of scope then and is in scope now.

**Files:**
- Modify: `core/mvsepless_catalog.py:171-173` (globals), add `_read_disk_cache_entry` / `_start_background_refresh`, `:216-254` (`load_mvsepless_models`)
- Modify: `core/politrees_catalog.py` (`load_politrees_links` failure branch only)
- Test: `tests/test_mvsepless_startup_cache.py` (create), `tests/test_politrees_startup_cache.py` (extend)

**Interfaces:**
- Consumes: `core.model_display.clear_display_cache` (Task 2); the disk-TTL pattern established in Task 3.
- Produces: `core.mvsepless_catalog._read_disk_cache_entry() -> Optional[Tuple[Dict[str, Any], float]]`, `_start_background_refresh() -> None`. `load_mvsepless_models(*, force: bool = False)` keeps its signature.

- [ ] **Step 1: Write the failing tests for 8a**

Create `tests/test_mvsepless_startup_cache.py`, mirroring `tests/test_politrees_startup_cache.py` (read that file first and follow its structure, including its `UVR_DISABLE_MVSEPLESS`-equivalent env handling). It must cover:

1. A fresh on-disk cache skips the network — patch `_urlopen` with `side_effect=AssertionError("network hit despite fresh cache")`, patch `_start_background_refresh`, assert data returned and refresh called once.
2. A stale on-disk cache still fetches.
3. `force=True` bypasses the disk cache.
4. The disk-cache fast path invalidates the memoized display merge (`core.model_display._merged_for_display`), same property Task 3 asserts for politrees.

- [ ] **Step 2: Write the failing tests for 8b**

Add to `tests/test_politrees_startup_cache.py` and the new mvsepless file:

```python
    def test_failed_fetch_does_not_reset_the_disk_ttl(self) -> None:
        old = time.time() - 3600  # one hour old
        self._write_cache(old)
        with mock.patch.object(pc, "_urlopen", side_effect=OSError("offline")):
            pc.load_politrees_links(force=True)
        with open(self.cache_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertAlmostEqual(
            payload["fetched_at"],
            old,
            delta=1.0,
            msg="a failed fetch rewrote fetched_at, making stale data look fresh",
        )
```

- [ ] **Step 3: Run both to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_mvsepless_startup_cache tests.test_politrees_startup_cache -v`
Expected: the mvsepless module fails to import (`_read_disk_cache_entry` missing); `test_failed_fetch_does_not_reset_the_disk_ttl` fails in both files with `fetched_at` ≈ now instead of the old value.

- [ ] **Step 4: Implement 8a in `core/mvsepless_catalog.py`**

Add `import threading`, extend the globals block, and add the two helpers — mirroring `core/politrees_catalog.py` exactly, which is the reference implementation:

```python
_refresh_lock = threading.Lock()
_refresh_in_flight = False


def _read_disk_cache_entry() -> Optional[Tuple[Dict[str, Any], float]]:
    """Return ``(data, fetched_at)`` from the on-disk cache, or ``None``."""
    try:
        with open(_cache_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            return None
        fetched_at = payload.get("fetched_at")
        if not isinstance(fetched_at, (int, float)):
            return None
        return payload["data"], float(fetched_at)
    except (OSError, ValueError, TypeError):
        return None


def _start_background_refresh() -> None:
    """Refresh the catalogue off the main loop; at most one in flight."""
    global _refresh_in_flight
    with _refresh_lock:
        if _refresh_in_flight:
            return
        _refresh_in_flight = True

    def run() -> None:
        global _refresh_in_flight
        try:
            load_mvsepless_models(force=True)
        except Exception as exc:  # noqa: BLE001 - background best-effort
            debug("download", f"mvsepless background refresh failed err={exc}")
        finally:
            with _refresh_lock:
                _refresh_in_flight = False

    threading.Thread(target=run, name="uvr-mvsepless-refresh", daemon=True).start()
```

Then insert the fast path in `load_mvsepless_models`, immediately after the existing in-process TTL check and before `data: Optional[Dict[str, Any]] = None`:

```python
    if not force:
        entry = _read_disk_cache_entry()
        if entry is not None and (now - entry[1]) < _MVSEPLESS_CACHE_TTL_SECONDS:
            # A fresh cache on disk is authoritative: fetching here blocked
            # window construction on HTTP for no benefit.
            _cached_models = entry[0]
            _cached_loaded_at = now
            _cached_converted = None
            from .model_display import clear_display_cache

            clear_display_cache()
            _start_background_refresh()
            return _cached_models
```

- [ ] **Step 5: Implement 8b in both modules**

In `core/politrees_catalog.py:load_politrees_links`, track the data's origin and skip the rewrite when it came from disk:

```python
    data: Optional[Dict] = None
    from_disk = False
    try:
        with _urlopen(POLITREES_MODEL_LINKS_URL) as response:
            data = json.load(response)
    except Exception as exc:
        debug("download", f"politrees fetch failed err={type(exc).__name__}: {exc}")
        data = _read_disk_cache()
        from_disk = True
```

then guard the write:

```python
    if not from_disk:
        # Rewriting here would stamp fetched_at=now onto the copy we just read
        # back from disk, so an offline session makes month-old data look
        # freshly fetched and the TTL never expires.
        _write_disk_cache(data)
```

Apply the identical change to `load_mvsepless_models`. Leave `_cached_loaded_at = now` alone in both — that is the in-process cache, and resetting it correctly avoids re-hammering a dead network on every call within one session.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_mvsepless_startup_cache tests.test_politrees_startup_cache -v`
Expected: PASS.

- [ ] **Step 7: Re-measure startup**

Re-run the Task 7 harness (note the harness bug: wrapping an `lru_cache`-decorated function with a plain closure strips `.cache_clear`, which `core/model_data.py:reload_mappers` calls during `MainWindow.__init__` — the wrapper must forward `cache_clear` and `cache_info`).

Expected: time to window at or near ~1.1 s, versus the ~1.5–1.6 s Task 7 measured.

- [ ] **Step 8: Full suite, type check, commit**

Run: `UVR_DISABLE_POLITREES=1 .venv/bin/python -m unittest discover -s tests`
Run: `.venv/bin/python -m basedpyright`
Expected: PASS / 0 errors.

```bash
git add core/mvsepless_catalog.py core/politrees_catalog.py tests/test_mvsepless_startup_cache.py tests/test_politrees_startup_cache.py
git commit -m "perf(core): honour the mvsepless disk-cache TTL and stop resetting it on failure"
```

---

## Out of Scope

Measured and deliberately not changed:

- **Progress throttling** (`ui/run_control.py:580-594`) — already gated on both a minimum interval and phase/pass change.
- **Shutdown and cleanup polls** (`ui/run_control.py:378`, `:432`) — bounded at 80 × 50 ms.
- **`map_basenames_to_display`** — already does a single merge per dropdown; Task 2 makes it cheaper for free.
- **`resolve_model_dry` / `estimate_workload`** — ~12 ms per model change, dominated by the merge that Task 2 caches.
- **Heavy-import laziness** — verified intact; `engines`, `torch` and `onnxruntime` all import on `uvr-separate-warm`.
