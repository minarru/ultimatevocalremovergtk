# Catalogue YAML stem cache — design

**Date:** 2026-08-05  
**Status:** approved for planning  
**Related:** Download Center stem subtitles; [2026-07-31 model catalog naming](2026-07-31-model-catalog-naming-and-scores-design.md); UI metadata cache (hashes) is orthogonal

## Problem

Download Center row subtitles show stem export lists only when:

1. `EntryMeta.stems` is non-empty (today filled almost only from **mvsepless** metadata), and  
2. There is **no** SDR score — `format_sdr_subtitle` treats the stem list as an `elif` fallback.

~179 catalogue labels lack stems; ~136 of those already advertise a `.yaml` URL. Those configs already declare `training.instruments` / `target_instrument` (same data runtime uses). Users want stems visible **alongside** SDR without blocking startup or spamming the GTK main loop.

## Goals

1. Background-fetch catalogue YAML URLs for entries missing stems; parse instruments; persist under `CACHE_DIR`.
2. Merge cached stems into `EntryMeta` under mvsepless (mvsepless / existing meta wins).
3. Show both SDR and stem list in Download Center subtitles when both exist.
4. Refresh open Download Center rows via a **coalesced** main-thread flush (debounce), not per-URL `idle_add`.

## Non-goals (v1)

- Demucs / Apollo heuristics without YAML.
- Hashing weights or using `model_data.json` / `<hash>.json` for ONNX-only rows.
- Shipping a static stem table in git.
- Changing separation / `ModelConfig` stem resolution (runtime already reads YAML).

## Design

### Module: `core/catalogue_stem_cache.py`

Disk file: `CACHE_DIR/catalogue_stem_cache.json` (via `paths.migrate_cache_file` + new `CATALOGUE_STEM_CACHE_FILE`).

Shape:

```json
{
  "fetched_at": 0.0,
  "entries": {
    "https://…/config.yaml": {
      "stems": ["vocals", "other"],
      "target_instrument": null,
      "fetched_at": 1234567890.0,
      "ok": true
    },
    "https://…/missing.yaml": {
      "stems": [],
      "target_instrument": null,
      "fetched_at": 1234567890.0,
      "ok": false
    }
  }
}
```

Key = config URL with query stripped (`split("?", 1)[0]`).

Public API:

| Function | Role |
|---|---|
| `catalogue_stems_enabled() -> bool` | False when `UVR_DISABLE_CATALOGUE_STEMS` is `1`/`true`/`yes` |
| `lookup_stems(url: str) -> Optional[StemCacheHit]` | Trusted hit within TTL; `None` if miss/expired |
| `remember_stems(url, stems, target_instrument, *, ok: bool) -> None` | Persist + bump in-memory |
| `enqueue_missing(urls: Iterable[str]) -> None` | Deduped queue for background worker |
| `ensure_worker_started() -> None` | Idempotent daemon thread |
| `clear_catalogue_stem_cache() -> None` | Drop memory + delete file; call `clear_display_cache()` |
| `subscribe(callback: Callable[[], None]) -> None` | UI registers coalesced refresh trigger (invoked from worker after batch writes, **not** per URL from GTK) |

TTL: **7 days** for successful entries; **6 hours** for `ok: false` (avoid hammering dead URLs).

Worker: one daemon thread, pull URLs from a `queue.Queue`, fetch with existing `_urlopen` (or a thin local copy bound by value for tests — patch this module’s `_urlopen`), parse YAML without importing torch:

- Prefer `yaml.safe_load` → `training.instruments` / `training.target_instrument` (same fields as `ModelConfig` / probe).
- Cap body size (e.g. 2 MiB) so a bad URL cannot blow memory.
- On success/failure: `remember_stems`; after each batch of N writes **or** when the queue drains, call subscribed notify once.

Do **not** call `GLib` from this module — UI owns the debounce.

### Merge: `core/catalog_sources.py`

In `_build_meta`, after reading `extra_meta` (mvsepless):

```text
if not stems:
    yaml_url = first .yaml http(s) ref in files
    hit = lookup_stems(yaml_url)
    if hit and hit.ok and hit.stems:
        stems = hit.stems
        target_instrument = hit.target_instrument or target
    elif yaml_url and catalogue_stems_enabled():
        enqueue_missing([yaml_url])
```

After building meta for a merge, `ensure_worker_started()` once if anything was enqueued.

Priority: **mvsepless `extra_meta.stems` always wins** over the YAML cache.

### Subtitle: `core/model_scores.py`

Change `format_sdr_subtitle` so `extra` is not exclusive with SDR:

```text
parts = []
if sdr is not None:
    parts.append(stem-labelled SDR)
if extra.strip():
    parts.append(extra.strip())   # always, when present
if size:
    parts.append(size)
```

Update existing tests that assumed SDR suppressed `extra`.

### UI: `ui/download_center.py`

On Download Center construct / after catalogue load:

1. `subscribe(_schedule_stem_subtitle_refresh)`.
2. `_schedule_stem_subtitle_refresh` sets a flag and arms **one** `GLib.timeout_add(200, _flush_stem_subtitles)` (or `idle_on_main` with debounce) if not already armed.
3. `_flush_stem_subtitles`: clear arm flag; for each row action, re-read `manager.catalogue_meta` (must see updated stems — see cache invalidation below), update `_uvr_stems_text` stash, rebuild subtitle with current SDR/size stashes. Do **not** recreate rows.

**Main-thread budget:** one timeout callback per debounce window; O(visible rows) subtitle string updates only — no catalogue rebuild, no network.

### Cache vs display merge

`EntryMeta` is built inside `merged_catalogues` / `_merged_for_display`. After the worker fills the stem cache, subsequent `_build_meta` must see new hits. Options:

1. **Preferred:** `lookup_stems` is read live during `_build_meta`; `clear_display_cache()` after a batch of successful remembers so the next `_merged_for_display()` rebuilds meta. Download Center’s flush then either:
   - calls a small `manager.refresh_catalogue_meta_stems()` that patches `catalogue_meta` labels from `lookup_stems` without full remount, **or**
   - re-assigns `catalogue_meta` from a fresh merge.

Prefer **patch-in-place** on `DownloadManager.catalogue_meta` for labels whose yaml URL now hits the cache (avoids tearing down the list). Full `clear_display_cache` still runs so other consumers (method pickers) eventually see stems if they read meta.

2. Worker must not call `clear_display_cache` on every URL — only once per drained batch / notify.

### Env / docs

| Variable | Effect |
|---|---|
| `UVR_DISABLE_CATALOGUE_STEMS` | Skip enqueue, lookup returns None (mvsepless stems unchanged) |

Document in `docs/environment.md`. Add a short note under tracked-issues or Download Center docs if one exists.

### Testing

- Unit: parse fixtures → stems; TTL / failed entry; enqueue dedupe; `format_sdr_subtitle` with SDR+extra.
- Unit: `_build_meta` fills from cache; enqueues on miss (patch worker).
- GTK (display-guarded): debounce schedule arms once for many notifies; flush updates subtitle text.
- Neutralise politrees/mvsepless HTTP in tests that touch merge (`UVR_DISABLE_*` or patch loaders).

### Success metrics

- After one Download Center open + warm cache, ≥ most yaml-bearing previously stem-less MDX rows show a stem list in the subtitle (with or without SDR).
- Opening Download Center does not block on YAML network I/O on the main thread.
- Stress: 100 rapid notify calls → ≤ ~2–3 main-thread flush invocations in 1 s (debounce).

## Open follow-ups (out of v1)

- ONNX-only / Demucs heuristics.
- Persist yaml bodies under `MDX_C_CONFIG_PATH` while stem-caching (optional dedupe with `mdx_config_fetch`).
