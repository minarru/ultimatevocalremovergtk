# UI metadata cache — design

**Date:** 2026-08-05  
**Status:** approved for planning (scope from caching suggestions after Mel-Band / SCNet merge)  
**Related:** 2026-08-04 UI performance work (catalogue merge, SWR, deferred combo populate — already shipped)

## Problem

Selection IDs in settings stay as name/tag strings (correct). The remaining lag on vocal-split / secondary expanders is **re-deriving dry-check metadata** (open checkpoint → MD5 → hash-map lookup → `is_karaoke` / stems) and **re-labelling tags**, not which string we store.

Today:

| Mechanism | What it does | Gap |
|---|---|---|
| `ModelRepository.stem_check` | Caches dry `ModelConfig`s keyed by `tuple(all_model_tags())` | Session-only; invalidated only via `invalidate_stem_check` |
| `model_list` / ensemble MULTI_STEM | Filters `stem_check` | Benefits once stem_check is warm |
| `karaoke_model_list` | Builds a **fresh** dry `ModelConfig` per VR+MDX tag every call | Does **not** use `stem_check` or any other cache — primary expand lag after F1 |
| `settings.process.model_hash_table` | Typed field + flat map + JSON persist | **Never wired** to `repo.model_hash_table` (`AppContext.repo` constructs `ModelRepository()` with `{}`) |
| `format_tag_title` | Uses memoized `_merged_for_display` | No per-tag memo; still pays parse + lookup per call in hot loops |
| Checkpoint MD5 | `compute_checkpoint_hash` on miss | No mtime/size guard; no durable path→hash across restarts |

## Goals

1. Make vocal-split karaoke/BV list construction O(filter) after the first warm for a given tag set.
2. Persist path→hash across sessions with stale-file invalidation so dry checks and first runs skip re-reading multi-GB checkpoints when unchanged.
3. Memoize `format_tag_title` keyed by tag + display-cache generation.
4. Keep settings selection identity as tags/names (no hash-based settings migration).

## Non-goals

- Changing ensemble/member storage to MD5.
- Sidecar JSON next to every checkpoint (optional later if hash maps stay incomplete).
- Moving hashing off the main thread beyond the existing F1 idle deferral (can follow once caches land).
- Caching full `ModelConfig` objects in `settings.json` (too large / too coupled).

## Design

### A. Karaoke eligibility cache (in-process)

Add `ModelRepository._karaoke_cache: Optional[Tuple[Tuple[str, ...], List[str]]]` parallel to `_stem_check_cache`, keyed by `tuple(default_change_model_tags())`.

`karaoke_model_list`:

1. If cache key matches, return the cached tag list.
2. Else build dry configs (same as today), filter `model_status and (is_karaoke or is_bv_model)`, store tags, return.

`invalidate_stem_check` also clears `_karaoke_cache` (same invalidation sites: downloads, mapper reload, model-params dialog).

**Why not only filter `stem_check`?** Cold karaoke path would force hashing every Demucs weight too. A VR+MDX-scoped cache matches the pool UVR already uses for change-model defaults.

**Optional micro-opt:** if `stem_check` is already warm and its tag tuple is a superset, filter in memory without rebuilding — nice-to-have, not required for correctness.

### B. Durable hash table (settings-backed)

Keep the public shape consumers already use (`repo.model_hash_table: Dict[str, str]` path→md5) for reads in `ModelConfig.get_model_hash`.

Under the hood store richer entries in settings so we can invalidate:

```text
process.model_hash_table[path] = {
  "hash": "<md5 or chunk hash string>",
  "mtime_ns": <int>,
  "size": <int>,
}
```

Migration on load: if a value is a bare string, treat as hash with unknown mtime/size → re-stat and re-hash on next use (or trust once then rewrite).

Wire-up:

1. `AppContext.repo` (or `ModelRepository.__init__(hash_table=...)`) seeds `repo.model_hash_table` from settings via a small adapter that flattens trusted entries to path→hash **only when** `os.stat` mtime/size match; otherwise omit (force recompute).
2. `get_model_hash` (or a repo helper `remember_hash(path, hash)`) updates both the in-memory flat map and `settings.process.model_hash_table` with fresh stats.
3. Persist on the next normal `save_settings` (no extra save storm): mark dirty when the table grows/changes; existing UI save paths already flush settings often enough. For headless CLI, update settings dict in memory and save if `Settings` was loaded from disk.

Do **not** put multi-megabyte tables in git; this is user `settings.json` only.

### C. `format_tag_title` memo

Module-level cache keyed by `(tag, display_generation)` where `display_generation` increments inside `clear_display_cache()` (same generation already used for merge invalidation — reuse or add a counter next to it).

`format_tag_title(tag, repo)` ignores `repo` for the key except insofar as generation already covers mapper/catalogue changes (`reload_mappers` → `clear_display_cache`).

Clear the memo from `clear_display_cache` so tests that swap catalogue patches stay correct.

### D. Ensemble / secondary lists

No new cache type. Document that after A+B, `model_list` / `ensemble_model_list` stay correct via `stem_check` + durable hashes. Optionally add a thin `eligibility_tags(settings, predicate)` helper later if more menus duplicate karaoke's pattern — YAGNI until a third caller appears.

## Invalidation matrix

| Event | stem_check | karaoke | display title memo | durable hash entry |
|---|---|---|---|---|
| `invalidate_stem_check` | clear | clear | — | — |
| `reload_mappers` / `clear_display_cache` | (callers already invalidate stem where needed) | clear via stem invalidate sites | bump generation | — |
| Download / delete model | invalidate stem | clear | — | drop path or leave until mtime miss |
| Checkpoint replaced same path | — | — | — | mtime/size miss → rehash |
| Settings load | — | — | — | seed trusted only |

## Testing strategy

- Unit: karaoke second call does not construct `ModelConfig` (patch constructor or count calls).
- Unit: hash remember + load round-trip; mtime change forces recompute.
- Unit: `format_tag_title` same tag hits memo; `clear_display_cache` forces recompute.
- Existing ensemble / vocal-split / display-cache suites must stay green; patch both catalogue disable flags where tests hit `_merged_for_display`.

## Success metrics

On a machine with ~40–80 installed models (same class as the 2026-08-04 baseline):

- Second `karaoke_model_list` in-process: &lt; 5 ms (no file I/O).
- After restart with warm `settings.json` hash table and unchanged files: first dry `stem_check` / karaoke build skips `compute_checkpoint_hash` for every previously seen path (assert via mock).
- `format_tag_title` × N tags after warm merge: no per-call catalogue work beyond memo hit.
