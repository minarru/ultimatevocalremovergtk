# Ensemble stem semantics

**Date:** 2026-07-31
**Status:** Approved, ready for implementation planning
**Related:** [2026-07-31-model-catalog-naming-and-scores-design.md](2026-07-31-model-catalog-naming-and-scores-design.md)

## Problem

The ensemble member list decides compatibility by comparing raw stem strings.
`ModelRepository.model_list`'s `matches_stem` closure
(`core/model_data.py:234-237`):

```python
primary_match = model.primary_stem in {primary_stem, secondary_stem}
mdx_stem_match = primary_stem in model.mdx_model_stems and model.mdx_stem_count <= 2
```

Those stem names come from the checkpoint yaml for community models
(`core/model_data.py:591-613`) and from the curated hash-map JSON for upstream
models. The JSONs are consistently Title Case; the yamls are whatever the model
author typed. Measured against the installed model set, 8 of 30 MDX models are
wrongly excluded from `Vocals/Instrumental`:

```
mel_band_roformer_kim_ft2_bleedless_unwa   primary='vocals'      stems=['vocals']
huge_scnet_4stems_bleedless                primary='vocals'      stems=['drums','bass','other','vocals']
huge_scnet_4stems_fullness                 primary='vocals'      stems=['drums','bass','other','vocals']
mbr_inst2_unwa                             primary='other'       stems=['other']
melband_roformer_inst_v1e_plus             primary='other'       stems=['other']
model_BandSplit-Roformer_Resurrection_...  primary='other'       stems=['other']
bs_inst_hyperace2_unwa                     primary='instrument'  stems=['instrument']
Phantom-Mid-Wesleyr36                      primary='Similarity'  stems=['Similarity']
```

The normalization already exists — `canonical_ensemble_stem_tag`
(`core/model_stem_semantics.py:717`) folds `vocals`→`Vocals` — but `rg` shows it
is called **only from `core/job_runner.py`**, the stage that *combines*
outputs. It is never called from `core/model_data.py`, the stage that *selects*
members. `get_files_to_ensemble_for_stem` (`core/job_runner.py:1306`) even
casefolds explicitly. The runner tolerates what the selector rejects.

The same asymmetry sits inside `matches_stem` itself: line 243 does
`primary_stem.lower() in model.demucs_source_list` for the Demucs branch.
Case-insensitive for Demucs, case-sensitive for MDX, one function apart.

### `other` is overloaded three ways

A blanket `other` → instrumental alias would be wrong:

| Context | Meaning | Correct bucket |
| --- | --- | --- |
| 2-stem non-karaoke (`mbr_inst2_unwa`, `v1e_plus`, `Resurrection`) | instrumental complement of vocals | Instrumental |
| 4-stem (`huge_scnet_4stems_*`) | MUSDB residual after drums/bass/vocals | Other, genuinely its own stem |
| karaoke / BV model | instrumental **+ backing vocals** | neither |

Eligibility needs three inputs — stem name, stem count, and the karaoke/BV flag
— not one string.

### Karaoke models are wrongly *included*

This is more serious than the exclusions, because it corrupts audio rather than
hiding a list entry.

Karaoke models resolve as `primary='Vocals'`, `secondary='Instrumental'`, so
they pass the `Vocals/Instrumental` filter today. `karaoke_bv_export_labels`
(`core/model_stem_semantics.py:436-441`) records what that secondary actually
is:

```
'Instrumental' -> 'Instrumental (With Backing Vocals)'
```

But `export_stem_label` bypasses the relabel in ensemble mode
(`core/model_stem_semantics.py:454-455`):

```python
if for_ensemble:
    return canonical_ensemble_stem_tag(stem)
```

So six installed models — four Karaoke Fusion variants, Frazer, MB-Ro-Kara —
write `(Instrumental)` and get combined with clean instrumentals from Inst HQ
4/5. `_ENSEMBLE_STEM_PRESERVE` explicitly lists `INST_WITH_BACKING_VOCALS_STEM`
so it will not be folded, but that guard only ever sees the relabelled string,
which ensemble mode never produces.

### Instrumental is often derived, not a model output

The three `other` models are `primary='other'`, `secondary='No other'` —
nothing named "Instrumental" exists in their outputs. The instrumental is always
synthesized, by one of three paths in `engines/mdx.py:660-680`:

- combine on, exactly 2 stems → use the model's real second stem
- combine on, >2 stems → **sum** the remaining stems
- otherwise → **spectral inversion** of primary against the mixture

`is_mdx23_combine_stems` selects between summing and inverting for >2-stem
models. This is why stem count must be an input to bucket resolution.

## Design

### `ensemble_stem_bucket` (new, in `core/model_stem_semantics.py`)

One pure function, taking plain values rather than a `ModelConfig`, so both the
catalogue side and the installed side can call it:

```python
def ensemble_stem_bucket(
    stem: str,
    *,
    stem_count: int = 2,
    is_karaoke: bool = False,
    is_bv: bool = False,
) -> str
```

Resolution order:

1. karaoke model, vocal-ish stem → `BUCKET_LEAD_VOCALS`
2. karaoke model, instrumental-ish stem → `BUCKET_INST_WITH_BV`
3. BV model, vocal-ish stem → `BUCKET_BV_VOCALS`
4. BV model, instrumental-ish stem → `BUCKET_INST_WITH_LEAD`
5. `stem_count <= 2` and stem in `{other, instrumental, inst, instrument}` → `BUCKET_INSTRUMENTAL`
6. `stem_count >= 3` and stem is `other` → `BUCKET_OTHER`
7. casefolded alias lookup for vocals / drums / bass / guitar / piano
8. anything else → `BUCKET_UNKNOWN`

`BUCKET_UNKNOWN` never matches a pair, which keeps `Similarity`
(Phantom Centre) out of `Vocals/Instrumental` — the existing correct behaviour,
now for a stated reason rather than by accident. `instrument` gains an alias,
which admits `bs_inst_hyperace2_unwa`.

**Bucket values must be filename-safe.** `format_stem_basename` renders
`{track_base} ({stem})` and `sanitize_filename_component` preserves
parentheses, so a bucket of `Instrumental (With Backing Vocals)` would produce
`Song Model (Instrumental (With Backing Vocals)).wav`. The collection regex in
`get_files_to_ensemble_for_stem` is `\(([^()]+)\)\.(?:wav|flac|mp3)$`, which
rejects nested parentheses — members would silently fail to collect and the
ensemble would emit single-member output. Verified:

```
True   Song Model (Instrumental).wav                        -> Instrumental
False  Song Model (Instrumental (With Backing Vocals)).wav  -> None
True   Song Model (Instrumental_WithBackingVocals).wav      -> Instrumental_WithBackingVocals
```

So three strings exist per concept, deliberately:

| Role | Example |
| --- | --- |
| yaml stem (input) | `other`, `Instrumental`, `vocals` |
| bucket / export tag (comparison + filename) | `Instrumental_WithBackingVocals` |
| UI display label | `Instrumental (With Backing Vocals)` |

### Karaoke gets its own stem pair

`KARAOKE_PAIR = f"{LEAD_VOCAL_STEM_LABEL}/{INST_WITH_BACKING_VOCALS_STEM}"`
joins `ENSEMBLE_MAIN_STEM` in `bundled/constants/process.py`. Karaoke and BV
models leave `Vocals/Instrumental` and ensemble with each other instead.

`ensemble_pair_buckets(main_stem) -> Tuple[str, str]` maps a pair string to its
two buckets. A separate function rather than aliasing the display strings, so
the parenthesized label never enters the alias table.

Adding to `ENSEMBLE_MAIN_STEM` is additive: `settings.ensemble.main_stem` is a
plain string and stored values keep resolving.

### Selection and combine share one rule

- `matches_stem` compares buckets instead of raw strings.
- `export_stem_label(..., for_ensemble=True)` returns the bucket, reading
  `is_karaoke` / `is_bv` off the model, instead of calling
  `canonical_ensemble_stem_tag` directly.
- `canonical_ensemble_stem_tag` must round-trip the new bucket tags unchanged,
  so they join `_ENSEMBLE_STEM_PRESERVE`.

## Interaction with the naming/scores plan

The two efforts answer the same underlying question — *what stem does this
model actually produce* — on opposite sides:

| | Naming/scores plan | This plan |
| --- | --- | --- |
| Subject | downloadable catalogue entries | installed models |
| Source of stems | catalogue JSON (`EntryMeta.stems`, `target_instrument`) | `ModelConfig` from yaml / hash map |
| Consumer | SDR badge, purpose filter | ensemble eligibility, combine bucket |

**`ensemble_stem_bucket` lands first and both consume it.** It is pure and has
no dependencies, so it can be built before either plan's other work.

Two concrete edits to the naming/scores plan follow from this:

1. **Task 2, `primary_sdr`.** The score data keys stems as lowercase
   (`vocals`, `instrumental`, `drums`, `bass`, `other`). Comparing a model's raw
   `target_instrument` against those keys reproduces the same class of bug.
   Both sides route through `ensemble_stem_bucket` before comparing, so a
   2-stem model whose target is `other` reads its `instrumental` score instead
   of missing.
2. **Task 6, `_row_score`.** Passes `stem_count=len(meta.stems)` so the
   catalogue side applies the same 2-stem-vs-4-stem rule.

Without this, an `other`-named 2-stem instrumental model would show no SDR
badge despite having one, and the naming plan would ship a second, subtly
different answer to the same question.

## Migration risk

Users who built `Vocals/Instrumental` ensembles containing karaoke models will
find those members gone from the list. Saved ensemble presets may reference
them. Preset loading must degrade gracefully — an unresolvable member is
skipped with a log line, never an exception. `core/ensemble_presets.py` resolves
members by sanitized label and needs a test covering the now-ineligible case.

## Testing

Stdlib unittest, no network.

- `ensemble_stem_bucket` — table test over the three `other` contexts, the
  karaoke/BV flags, case variants, `instrument`, and `Similarity` → unknown.
- Filename safety — assert every bucket constant survives
  `format_stem_basename` and re-matches the collection regex.
- `matches_stem` — the 8 excluded models above become eligible (except
  `Similarity`, which stays out by design), and karaoke models leave
  `Vocals/Instrumental`.
- Preset loading with a member that is no longer eligible.

## Out of scope

- The possible `KeyError` at `engines/mdx.py:661-662`, where combine-on with a
  2-instrument yaml indexes `working_sources[self.secondary_stem]` using the
  pair-mapper name rather than a yaml key. No installed model triggers it and
  it needs its own investigation.
- Changing how the instrumental is derived (sum vs inversion).
- Any change to `is_mdx23_combine_stems` semantics.
