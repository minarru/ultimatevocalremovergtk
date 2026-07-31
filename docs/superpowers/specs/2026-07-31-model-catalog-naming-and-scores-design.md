# Unified model catalogue naming and scores

**Date:** 2026-07-31
**Status:** Approved, ready for implementation planning

## Problem

Two defects, one root cause.

### Models display as raw basenames

After the mvsepless merge (`62c9b4a`, `298fc10`), models installed from the
fork-curated `extra_models.json` and from `mvsepless_resources` show their
on-disk basename in the runtime method pickers, while the Download Center shows
a readable label for the same model. Reproduced against the working tree:

```
RAW   bs_inst_hyperace2_unwa          (extras)
RAW   huge_scnet_4stems_bleedless     (extras)
RAW   huge_scnet_4stems_fullness      (extras)
RAW   mbr_inst2_unwa                  (mvsepless)
RAW   mbr_instfvx_gabox               (mvsepless)
OK    model_bs_roformer_ep_317_sdr_12.9755 -> BandSplit Roformer | SDR 1297 by Viperx
```

The cause is two independent merge paths that have drifted:

| Path | Sources consumed |
| --- | --- |
| `DownloadManager._merge_politrees_supplement` (`core/downloads.py:321`) | upstream → politrees → extras → mvsepless → dedupe |
| `model_display.load_*_catalog_display_index` (`core/model_display.py:204`) | upstream cache → politrees |

The second path never learned about the two newest sources. Adding them to its
source-key tuples would work today and rot again at the next source, because
`convert_mvsepless_catalog` flattens its MDX-family lists *before* merging, so
the index builder would have to duplicate that flattening too.

### Label dialects

Four sources contribute labels in four house styles, all visible in one list:

| Source | Example |
| --- | --- |
| upstream TRvlvr | `MDX23C InstVoc HQ` |
| politrees | `MelBand Roformer \| Karaoke by Aufr33 & Viperx` |
| extras | `Roformer Model: BandSplit Roformer \| HyperACE v2 Instrumental by Unwa` |
| mvsepless | `Mel-Band Roformer Vocals by Kimberley Jensen` |

The extras entries keep a `Roformer Model: ` category prefix that
`sanitize_catalogue_label` strips at runtime but the Download Center renders
verbatim, so one model is named two different things in two views.

### SDR is near-empty

No upstream catalogue publishes SDR. `parse_sdr_score`
(`core/model_scores.py:22-26`) scrapes digits out of names. Measured against the
461-entry merged catalogue: 9 entries scored from the label (2.0%), 25 if
checkpoint filenames are scraped too (5.4%). "Sort by SDR" ranks 25 models and
leaves 436 in an arbitrary tail, and unscored rows render a blank subtitle that
reads as a bug.

## Source audit

Four candidate SDR sources were checked before designing around any of them.

| Source | Usable | Coverage |
| --- | --- | --- |
| audio-separator `models-scores.json` | **Yes** | 98/461 (21.3%), benchmarked, per-stem, keyed by checkpoint filename |
| MVSEP quality-checker API | No | Hard-capped at 20 rows per `dataset_type` (~80 total) |
| ZFTurbo `docs/pretrained_models.md` | Parseable | **0 new** — 15 entries, already covered or not models we ship |
| MSST-WebUI | No scores file found | — |

MVSEP is rejected on identity, not size: its rows are keyed by `algo_name` —
`"BS Roformer (2025.07.20, MVSep.com)"`, `"MVSep Ensemble (vocals, instrum)
(2024.10.08)"` — which name MVSEP's hosted service algorithms. Many are
ensembles or proprietary and are not downloadable checkpoints at all. Joining
them to our filenames means fuzzy-matching two schemes that were never meant to
align, whose failure mode is a wrong number attached to a real model. That is
worse than showing nothing.

Coverage from audio-separator, by architecture:

```
VR       28/ 28   100.0%
MDX      66/407    16.2%
Demucs    4/ 24    16.7%   (v4 only; matches on the .yaml key)
Apollo    0/  2     0.0%
overall  98/461    21.3%
```

**21% is the ceiling from published data.** Community fine-tunes are released
without a benchmark run; the measurements were never made. Computing them
ourselves needs ground-truth multitrack stems and reference SDR, which
`core/bench_metrics.py` does not implement (it does A/B diffing). Out of scope.

The design must therefore make an unscored model look intentional rather than
broken.

## Design

### Data flow

```
politrees cache ─┐
upstream cache ──┤
bundled/extra ───┼─→ core/catalog_sources.py ─┬─→ DownloadManager  (rows)
mvsepless cache ─┘   merge + dedupe + meta    └─→ model_display     (dropdowns)
                              │
                     canonical_display_name()  ← core/model_naming.py
                     sdr_for_files()           ← core/model_scores.py
```

### `core/catalog_sources.py` (new)

Owns the single merge. Returns the merged, deduped `{label: files}` catalogues
per architecture, plus a parallel `{label: EntryMeta}` map carrying
`checkpoint`, `source`, `stems`, `target_instrument`, `category`.

Reads only the disk caches that `politrees_catalog` and `mvsepless_catalog`
already maintain — no network, so dropdown population stays offline-safe and
fast. `DownloadManager._merge_politrees_supplement` becomes a thin caller, and
`model_display`'s index builders read the same merged result. The raw-basename
class of bug is then closed structurally: a fifth source cannot reintroduce it.

### `core/model_naming.py` (new)

One pure function, `canonical_display_name(label)`:

1. Strip category prefixes, via a new `strip_catalogue_prefix`.
2. Canonicalize the architecture family: `Mel-Band` / `MelBand` / `mel_band` →
   `MelBand Roformer`; `BS-Roformer` / `BandSplit` → `BandSplit Roformer`.
3. Normalize the author separator to `·`.

The existing `sanitize_catalogue_label`, `sanitize_vr_catalogue_label` and
`sanitize_demucs_catalogue_label` **stay in `model_display.py`**. They look
redundant but are not: `core/ensemble_presets.py:155-163` uses
`sanitize_catalogue_label` for casefolded *matching* when resolving a preset
member to a model, and `core/mdx_c_registry.py` re-exports it to
`scripts/generate_models_catalogue.py`. `canonical_display_name` reformats —
substituting it there would silently break preset resolution. Stripping for
matching and rendering for display are different jobs. `strip_catalogue_prefix`
is a superset (it also strips `VR Arch ` and `Apollo Model: `); unifying the two
means changing preset matching and is out of scope.

Descriptive middles pass through verbatim — no model is renamed into something
wrong. Both views call it, so the two-names-for-one-model split closes.

```
MDX23C InstVoc HQ                                          -> MDX23C — InstVoc HQ
MelBand Roformer | Karaoke by Aufr33 & Viperx              -> MelBand Roformer — Karaoke · Aufr33 & Viperx
Roformer Model: BandSplit Roformer | HyperACE v2 by Unwa   -> BandSplit Roformer — HyperACE v2 · Unwa
Mel-Band Roformer Vocals by Kimberley Jensen               -> MelBand Roformer — Vocals · Kimberley Jensen
```

### `core/model_scores.py` (extended)

Real backend, following the `extra_models.json` precedent: live fetch →
seven-day disk cache under `CACHE_DIR` → bundled snapshot fallback, with
`UVR_DISABLE_MODEL_SCORES=1` as the kill switch (matching
`UVR_DISABLE_POLITREES` / `UVR_DISABLE_MVSEPLESS`).

Aggregation is mean SDR per stem across tracks. Two correctness details:

- Exclude the `seconds_per_minute_m3` key, which is a speed metric and would
  otherwise be aggregated as if it were a stem.
- Look up by **any** filename in the entry, not just the primary checkpoint.
  `primary_checkpoint_name` skips `.yaml` keys, which is exactly how Demucs v4
  is keyed in the score data — the current helper misses all 24 Demucs entries.
- 19 models in the source carry no track scores (De-Echo, DeNoise and other
  utility models). Treat as unscored, not as an error.

The existing filename regex stays as a fallback for the ~14 models whose SDR
appears only in their name.

The badge names its stem — `vocals 11.4 SDR`, never a bare `11.4 SDR`. The same
`model_bs_roformer_ep_317` checkpoint is 11.43 on vocals and 16.01 on
instrumental; an unlabelled number invites a comparison between different
quantities. Sorting keys on the target stem's score so a purpose-filtered list
compares like with like; unscored models keep their current tail position.

### Subtitle fallback chain

`SDR (if known) → stems → size`, so a row always says something:

```
mel_band_roformer_kim_ft2   vocals 10.9 SDR · 1.2 GB
mbr_instfvx_gabox           vocals, other · 890 MB
```

This is what the retained mvsepless metadata buys: all 415 of its entries know
their stems and target instrument, so an unscored row is still informative.
`convert_mvsepless_catalog` currently discards `category`, `stems` and
`target_instrument`; keeping them in the metadata sidecar also gives the purpose
filter real data instead of regex-guessing from labels. The `category` values
are Russian and need a translation table (40 distinct values).

## Testing

Stdlib unittest, no network, checked-in JSON fixtures.

- `model_naming` — pure function over a table of the four dialects.
- Score aggregation — fixture covering per-stem means, the
  `seconds_per_minute_m3` exclusion, the `.yaml` Demucs key, and a
  zero-track entry.
- `catalog_sources` — merge order and dedupe parity with current behaviour.
- **Regression test for the reported bug:** the five basenames listed above
  resolve to non-raw display names.

Existing suites that must keep passing: `test_model_display`,
`test_model_scores`, `test_catalog_dedupe`, `test_mvsepless_catalog`,
`test_extra_catalog`, `test_core_downloads`, `test_download_center_search`.

## Out of scope

- Computing SDR locally (needs ground-truth stems and a reference-SDR
  implementation).
- Scraping the MVSEP leaderboard.
- Any change to download, resolve or install plumbing: catalogue labels remain
  the identity key throughout.
