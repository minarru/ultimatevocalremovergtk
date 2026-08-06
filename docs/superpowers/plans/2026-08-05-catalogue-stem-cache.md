# Catalogue YAML Stem Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Background-fetch catalogue YAML configs to fill `EntryMeta.stems` for non-mvsepless rows, cache on disk, show stems beside SDR in Download Center, and refresh open rows via a coalesced main-thread flush.

**Architecture:** New `core/catalogue_stem_cache.py` (disk JSON + one daemon worker + subscribe/notify). `catalog_sources._build_meta` looks up / enqueues yaml URLs when mvsepless left stems empty. `format_sdr_subtitle` always appends `extra` when present. Download Center patches `catalogue_meta` and debounces subtitle updates (~200 ms, one timeout).

**Tech Stack:** Python 3.x, PyYAML (`safe_load` for remote bodies), stdlib `unittest`, basedpyright, GTK4 debounce via `GLib.timeout_add` / existing `idle_on_main`.

**Spec:** [docs/superpowers/specs/2026-08-05-catalogue-stem-cache-design.md](../specs/2026-08-05-catalogue-stem-cache-design.md)

## Global Constraints

- **Tests are stdlib `unittest`, never pytest.** `.venv/bin/python -m unittest ...`
- **No tkinter.** No `torch` / `onnxruntime` / `engines` at `core` import time. Stem parse must not import ML stacks.
- **Never unscoped `git checkout` / `restore` / `reset --hard` / `stash` / `clean`; never `git add -A`.** Stage explicitly; local `models/*/model_data/` dirt is common.
- **Catalogue tests** that touch merges must set `UVR_DISABLE_POLITREES` and `UVR_DISABLE_MVSEPLESS` (or patch both loaders) and call `clear_display_cache()` after replacing source data. Also set `UVR_DISABLE_CATALOGUE_STEMS=1` unless the test is specifically about the stem cache worker.
- **Patch `_urlopen` on the importing module** (`core.catalogue_stem_cache._urlopen`), not only `mdx_config_fetch`.
- **GTK tests** use `@unittest.skipUnless(DISPLAY or WAYLAND_DISPLAY, ...)` and `gi.require_version` in `setUpClass`. Never `widget.destroy()`.
- **basedpyright** clean on touched modules; annotate parameters.
- **Search with `rg`**, not `grep`.

## File map

| File | Role |
|---|---|
| `core/catalogue_stem_cache.py` | **Create** — cache, worker, subscribe |
| `core/paths.py` | `CATALOGUE_STEM_CACHE_FILE` |
| `core/catalog_sources.py` | Lookup / enqueue in `_build_meta` |
| `core/model_scores.py` | SDR + extra both in subtitle |
| `core/downloads.py` | Optional helper to patch meta stems from cache |
| `ui/download_center.py` | Subscribe + debounced flush |
| `docs/environment.md` | `UVR_DISABLE_CATALOGUE_STEMS` |
| `tests/test_catalogue_stem_cache.py` | **Create** |
| `tests/test_model_scores.py` | Extend subtitle cases |
| `tests/test_catalog_stem_merge.py` | **Create** — `_build_meta` / enqueue |
| `tests/test_download_center_stem_refresh.py` | **Create** — debounce (GTK-guarded) |

---

### Task 1: `format_sdr_subtitle` shows SDR and stems together

**Files:**
- Modify: `core/model_scores.py` (`format_sdr_subtitle`)
- Modify: `tests/test_model_scores.py`, `tests/test_download_center_search.py` (assertions that assumed SDR suppressed `extra`)

**Interfaces:**
- Consumes: existing `format_sdr_subtitle(sdr, size_text="", *, stem=None, extra="") -> str`
- Produces: same signature; when both `sdr` and `extra` are set, subtitle contains both segments joined by ` · `

- [ ] **Step 1: Write the failing test**

In `tests/test_model_scores.py` add:

```python
def test_format_sdr_subtitle_includes_extra_alongside_sdr(self) -> None:
    from core.model_scores import format_sdr_subtitle

    self.assertEqual(
        format_sdr_subtitle(11.43, "1.2 GB", stem="vocals", extra="Vocals, Instrumental"),
        "vocals 11.4 SDR · Vocals, Instrumental · 1.2 GB",
    )
```

Update any test that expected SDR-only when `extra` was also passed (search with `rg "format_sdr_subtitle" tests`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_scores.ModelScoresTests.test_format_sdr_subtitle_includes_extra_alongside_sdr -v`

Expected: FAIL — `extra` omitted when SDR present.

- [ ] **Step 3: Implement**

Replace the `elif extra` branch in `format_sdr_subtitle` with an independent `if extra.strip(): parts.append(...)`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m unittest tests.test_model_scores tests.test_download_center_search -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/model_scores.py tests/test_model_scores.py tests/test_download_center_search.py
git commit -m "$(cat <<'EOF'
fix(ui): show catalogue stems beside SDR in Download Center subtitles

format_sdr_subtitle treated the stem list as a no-score fallback; append
extra whenever present so scored rows still expose export stems.
EOF
)"
```

---

### Task 2: Stem cache module (disk + lookup + remember)

**Files:**
- Create: `core/catalogue_stem_cache.py`
- Modify: `core/paths.py` (add `CATALOGUE_STEM_CACHE_FILE`)
- Test: `tests/test_catalogue_stem_cache.py` (create)

**Interfaces:**
- Consumes: `paths.CACHE_DIR` / `migrate_cache_file`, `yaml.safe_load`, urllib via module-local `_urlopen`
- Produces:
  - `@dataclass(frozen=True) class StemCacheHit: stems: tuple[str, ...]; target_instrument: Optional[str]; ok: bool`
  - `catalogue_stems_enabled() -> bool`
  - `normalize_config_url(url: str) -> str`
  - `lookup_stems(url: str) -> Optional[StemCacheHit]`
  - `remember_stems(url: str, stems: Sequence[str], target_instrument: Optional[str], *, ok: bool) -> None`
  - `clear_catalogue_stem_cache() -> None`
  - `parse_stems_from_yaml_bytes(data: bytes) -> tuple[list[str], Optional[str]]`
  - Constants: `_SUCCESS_TTL_SECONDS = 7 * 24 * 3600`, `_FAILURE_TTL_SECONDS = 6 * 3600`, `_MAX_BODY_BYTES = 2 * 1024 * 1024`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalogue_stem_cache.py` covering:

1. `parse_stems_from_yaml_bytes` with a minimal yaml containing `training.instruments` and `target_instrument`.
2. `remember_stems` → `lookup_stems` round-trip (use temp `UVR_CACHE_DIR`).
3. Failed entry (`ok=False`) is returned by lookup within failure TTL but stems empty.
4. `catalogue_stems_enabled` is False when `UVR_DISABLE_CATALOGUE_STEMS=1`.
5. Expired success entry (patch `time.time`) returns `None`.

- [ ] **Step 2: Run tests — expect FAIL** (module missing).

- [ ] **Step 3: Implement module + path constant**

Add to `core/paths.py` next to other cache files:

```python
CATALOGUE_STEM_CACHE_FILE = os.path.join(CACHE_DIR, "catalogue_stem_cache.json")
```

Implement `core/catalogue_stem_cache.py` per spec: in-memory dict synced to disk on remember; `clear_catalogue_stem_cache` clears memory, removes file, calls `clear_display_cache()`.

`parse_stems_from_yaml_bytes`: `yaml.safe_load` only (remote untrusted). Read `training` mapping; instruments list → `str` list; optional `target_instrument`. Empty instruments → `([], None)`.

Do **not** start the worker in this task.

- [ ] **Step 4: Run tests — expect PASS.** basedpyright on new file.

- [ ] **Step 5: Commit**

```bash
git add core/catalogue_stem_cache.py core/paths.py tests/test_catalogue_stem_cache.py
git commit -m "$(cat <<'EOF'
feat(core): add on-disk catalogue YAML stem cache

Persist config-URL → instruments for Download Center enrichment without
mvsepless metadata.
EOF
)"
```

---

### Task 3: Background worker + subscribe/notify

**Files:**
- Modify: `core/catalogue_stem_cache.py`
- Extend: `tests/test_catalogue_stem_cache.py`

**Interfaces:**
- Consumes: Task 2 API, `_urlopen(url) -> context manager with .read()`
- Produces:
  - `enqueue_missing(urls: Iterable[str]) -> None`
  - `ensure_worker_started() -> None`
  - `subscribe(callback: Callable[[], None]) -> None` / `unsubscribe` optional
  - Worker fetches, `remember_stems`, then `_notify_subscribers()` once per drained batch (not per URL)

- [ ] **Step 1: Failing tests**

```python
def test_enqueue_dedupes_and_worker_remembers(self) -> None:
    # patch _urlopen to return yaml bytes for one URL
    # enqueue twice, ensure_worker_started, join with timeout
    # lookup_stems returns instruments

def test_notify_fires_once_per_batch(self) -> None:
    calls = []
    subscribe(lambda: calls.append(1))
    # enqueue two URLs, both succeed via patched _urlopen
    # after worker idle: assert len(calls) == 1  # or small, not 2
```

Use a threading.Event or short poll loop; do not sleep blindly for >2s.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement worker**

- `queue.Queue` of normalized URLs; set of in-flight/queued for dedupe.
- Daemon thread name `uvr-catalogue-stems`.
- Read at most `_MAX_BODY_BYTES + 1`; if larger, treat as failure.
- On batch: process until queue empty; then notify all subscribers once.
- Guard `subscribe` list with a lock.

- [ ] **Step 4: Tests PASS.**

- [ ] **Step 5: Commit**

```bash
git add core/catalogue_stem_cache.py tests/test_catalogue_stem_cache.py
git commit -m "$(cat <<'EOF'
feat(core): background-fetch catalogue YAML stems

One daemon worker drains a deduped URL queue and notifies subscribers
once per batch so the UI can coalesce refreshes.
EOF
)"
```

---

### Task 4: Wire `_build_meta` lookup + enqueue

**Files:**
- Modify: `core/catalog_sources.py`
- Test: `tests/test_catalog_stem_merge.py` (create)

**Interfaces:**
- Consumes: `lookup_stems`, `enqueue_missing`, `ensure_worker_started`, `catalogue_stems_enabled`
- Produces: `_build_meta` fills `EntryMeta.stems` / `target_instrument` from cache when mvsepless left them empty; enqueues yaml URLs on miss

- [ ] **Step 1: Helper + failing test**

Add a small pure helper in `catalog_sources.py` (easier to test):

```python
def _yaml_config_url(files: Mapping[str, str]) -> Optional[str]:
    for name, ref in files.items():
        if str(name).endswith((".yaml", ".yml")) and str(ref).startswith(("http://", "https://")):
            return str(ref).split("?", 1)[0]
    return None
```

Test file (with both catalogue disables + `UVR_DISABLE_CATALOGUE_STEMS` unset for the positive case):

1. When cache has a hit for the yaml URL and `extra_meta` has no stems → `EntryMeta.stems` equals cached list.
2. When miss and enabled → `enqueue_missing` called (patch) with that URL; `ensure_worker_started` called.
3. When `extra_meta` already has stems → cache ignored; no enqueue.
4. When `UVR_DISABLE_CATALOGUE_STEMS=1` → no enqueue.

- [ ] **Step 2: FAIL then implement in `_build_meta`.**

After reading `source_meta` stems:

```python
stems = list(stems) if isinstance(stems, list) else []
target = source_meta.get("target_instrument") or None
if not stems:
    from .catalogue_stem_cache import (
        catalogue_stems_enabled,
        enqueue_missing,
        ensure_worker_started,
        lookup_stems,
    )
    yaml_url = _yaml_config_url(files)
    if yaml_url:
        hit = lookup_stems(yaml_url)
        if hit is not None and hit.ok and hit.stems:
            stems = list(hit.stems)
            if not target:
                target = hit.target_instrument
        elif catalogue_stems_enabled():
            enqueue_missing([yaml_url])
            # defer ensure_worker_started to end of merged_catalogues
```

At end of `merged_catalogues`, if any enqueue happened during the build, call `ensure_worker_started()`. Track with a module-local flag or return count from `_build_meta`. Cleanest: `_build_meta` returns `(dict, enqueued: bool)` or use a list `pending: list[str]` passed in.

Prefer:

```python
pending_yaml: list[str] = []
# _build_meta(..., pending_yaml)
# ...
if pending_yaml:
    enqueue_missing(pending_yaml)
    ensure_worker_started()
```

- [ ] **Step 3: Tests PASS.** Clear display cache in tearDown.

- [ ] **Step 4: Commit**

```bash
git add core/catalog_sources.py tests/test_catalog_stem_merge.py
git commit -m "$(cat <<'EOF'
feat(core): enrich EntryMeta stems from catalogue YAML cache

When mvsepless left stems empty, look up or enqueue the entry's config
URL so Download Center can show export stems after a background fetch.
EOF
)"
```

---

### Task 5: DownloadManager patch + Download Center debounced refresh

**Files:**
- Modify: `core/downloads.py` (add `apply_catalogue_stem_cache() -> set[str]` returning labels updated)
- Modify: `ui/download_center.py`
- Test: `tests/test_download_center_stem_refresh.py` (create; GTK-guarded for debounce if needed — pure debounce helper can live on the window as methods tested with a fake clock)

**Interfaces:**
- Consumes: `lookup_stems`, `_yaml_config_url` / files on `EntryMeta`, subscribe API
- Produces: coalesced subtitle refresh; ≤1 timeout armed at a time; debounce ~200 ms

- [ ] **Step 1: `DownloadManager.apply_catalogue_stem_cache`**

```python
def apply_catalogue_stem_cache(self) -> set[str]:
    """Patch catalogue_meta stems from the YAML stem cache. Return updated labels."""
    from .catalogue_stem_cache import lookup_stems
    from .catalog_sources import EntryMeta  # or dataclasses.replace

    updated: set[str] = set()
    for label, meta in list(self.catalogue_meta.items()):
        if meta.stems:
            continue
        url = _yaml_config_url(meta.files)
        if not url:
            continue
        hit = lookup_stems(url)
        if hit is None or not hit.ok or not hit.stems:
            continue
        self.catalogue_meta[label] = dataclasses.replace(
            meta,
            stems=list(hit.stems),
            target_instrument=meta.target_instrument or hit.target_instrument,
        )
        updated.add(label)
    return updated
```

(`EntryMeta` is frozen — confirm and use `dataclasses.replace`.)

Unit-test with a fake `catalogue_meta` dict (no GTK).

- [ ] **Step 2: Download Center subscribe + debounce**

On successful catalogue populate (where rows are built), call:

```python
from core.catalogue_stem_cache import subscribe, ensure_worker_started
subscribe(self._schedule_stem_subtitle_refresh)
ensure_worker_started()  # in case meta build already enqueued
```

Implement:

```python
def _schedule_stem_subtitle_refresh(self) -> None:
    if self._stem_refresh_armed:
        return
    self._stem_refresh_armed = True
    from gi.repository import GLib
    GLib.timeout_add(200, self._flush_stem_subtitles)

def _flush_stem_subtitles(self) -> bool:
    self._stem_refresh_armed = False
    updated = self.manager.apply_catalogue_stem_cache()
    if not updated:
        return False  # remove timeout source
    for key, action in self._row_actions.items():
        _arch, name = key
        if name not in updated:
            continue
        # rebuild stems_text from meta; keep stashed sdr/size
        ...
        set_row_subtitle(...)
    return False
```

Worker notify may run off the main thread — `_schedule_stem_subtitle_refresh` must hop with `idle_on_main(self._schedule_stem_subtitle_refresh_on_main)` if subscribe is invoked from the worker. Spec: subscribe callback is invoked from the worker thread → **always** wrap schedule in `idle_on_main`.

- [ ] **Step 3: Test debounce arming**

Without full GTK if possible: extract arm logic to a helper that records timeout scheduling via a injectable `schedule_timeout(ms, cb)`. Assert 5 notifies → one arm until flush clears the flag.

Or GTK test: mock `timeout_add` to capture calls.

- [ ] **Step 4: Manual/automated verification**

Run unit suites for new tests + basedpyright.

- [ ] **Step 5: Commit**

```bash
git add core/downloads.py ui/download_center.py tests/test_download_center_stem_refresh.py
git commit -m "$(cat <<'EOF'
feat(ui): coalesced Download Center refresh when YAML stems arrive

Subscribe to the catalogue stem worker and debounce subtitle updates so
the main loop is not flooded per URL.
EOF
)"
```

---

### Task 6: Docs + full verification

**Files:**
- Modify: `docs/environment.md`
- Optionally: `docs/tracked-issues.md` one-line note

- [ ] **Step 1: Document `UVR_DISABLE_CATALOGUE_STEMS`** next to other catalogue disable flags.

- [ ] **Step 2: Full suite**

```bash
UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
  .venv/bin/python -m unittest tests.test_catalogue_stem_cache tests.test_catalog_stem_merge \
  tests.test_model_scores tests.test_download_center_stem_refresh -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
```

- [ ] **Step 3: Commit docs**

```bash
git add docs/environment.md docs/tracked-issues.md
git commit -m "$(cat <<'EOF'
docs: document UVR_DISABLE_CATALOGUE_STEMS

Background YAML stem enrichment for Download Center can be disabled
for offline/CI runs.
EOF
)"
```

---

## Spec coverage

| Spec item | Task |
|---|---|
| SDR + stems subtitle | Task 1 |
| Disk cache + parse | Task 2 |
| Worker + batch notify | Task 3 |
| `_build_meta` merge/enqueue | Task 4 |
| Coalesced UI refresh | Task 5 |
| Env docs | Task 6 |
| No Demucs heuristics / hash JSON | out of scope |

## Placeholder scan

No TBD / “add tests later” without concrete cases.
