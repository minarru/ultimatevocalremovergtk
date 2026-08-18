# Stem identity: native keys never mutate

**Date:** 2026-08-17
**Status:** Approved, implementing
**Related:**
- [2026-07-31-ensemble-stem-semantics-design.md](2026-07-31-ensemble-stem-semantics-design.md)
- [2026-08-09-stem-export-semantics-design.md](2026-08-09-stem-export-semantics-design.md)
- Prerequisite: vocal-splitter community-config fix — landed as `2171862`

## Problem

One string is still asked to be four jobs: yaml/hash dict key, UVR Title Case
label, positional primary, and run concept (`lead_only` after vocal-split
remap). Community MDX-C yamls use `vocals` / `other`; engines compare
`== "Vocals"`. Vocal split overwrites `primary_stem` with `lead_only`, then
`write_audio` compares the yaml name to that token.

GTK Save stems persist `process.stem_focus` (bucket tags) but ModelConfig
assemble ignores it. CLI `--stems vocals` never writes `stem_focus` and
treats vocals as “primary only,” so an inst-primary model exports
instrumental. `--profile gui` inherits mixed spellings (`mdx.stems='vocals'`
vs `'Vocals'`).

## Design

Native yaml/hash keys never change. A Concept (`StemBucket` or `StemLiteral`)
is computed from native + context (`stem_count`, `is_karaoke`, `is_bv`,
`is_vocal_split`). Filenames, save flags, GTK matching, and CLI `--stems`
read the concept. Demix dict lookup keeps the native key.

```
NativeStem  →  bucket_for_model_stem(..., is_vocal_split=)
            →  StemBucket | StemLiteral
            →  filename / UI / chain / stem_focus
```

- No per-model hash catalog. Vocabulary stays `_STEM_NAME_ALIASES`.
- `lead_only` remains an *input* alias for old ensemble members. New runs
  must not assign `primary_stem = lead_only`.
- Do not wrap `ModelConfig.primary_stem` as `StemId` (engines need the raw
  dict key). `StemId` stays the lookup helper.

### Resolver

`bucket_for_model_stem` gains `is_vocal_split: bool = False` (splitter *role*,
not karaoke-as-primary). Full table, with `stem_count` 2:

| native | plain | `is_karaoke` | `is_bv` | `is_vocal_split` | `is_vocal_split` + `is_bv` |
|---|---|---|---|---|---|
| `Vocals` / `vocals` | `VOCALS` | `LEAD_VOCALS` | `BACKING_VOCALS` | `LEAD_VOCALS` | `BACKING_VOCALS` |
| `Instrumental` / 2-stem `other` | `INSTRUMENTAL` | `INST_WITH_BV` | `INST_WITH_LEAD` | `BACKING_VOCALS` | `LEAD_VOCALS` |
| 4-stem `other` | `OTHER` | `OTHER` | `OTHER` | `OTHER` | `OTHER` |
| unrecognized | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` |

A splitter's instrumental complement is Backing Vocals, never Inst-with-BGV —
that is the whole reason `is_vocal_split` is not spelled `is_karaoke`.
Karaoke/BV as primary keeps `is_karaoke` / `is_bv` without `is_vocal_split`;
the splitter chain stays off.

This table has exactly one implementation. `vocal_split_primary_stem` and
`vocal_split_write_logic_stem` encoded it a second time and are **deleted**;
their assertions moved onto the resolver. One consequence: a missing or
unrecognized splitter stem used to default to backing vocals, and now resolves
`UNKNOWN`, which `write_audio` skips rather than mislabelling.

`concept_is(stem, StemBucket.VOCALS, **ctx)` replaces `== VOCAL_STEM` at
engine and frontend call sites. `stem_count` is a **required** keyword on
`bucket_for_model_stem` / `concept_is` / `focus_matches_stem`: native `other`
means the instrumental side at 2 stems and the MUSDB residual at 4, so a
defaulted count is a silent mis-resolution. With a model in hand use
`stem_concept(model, stem)` or `stem_context(model)` — the single derivation
point for all four context fields — rather than assembling context by hand.

### ModelConfig

Delete the vocal-split remap of `primary_stem` / `secondary_stem`. Native
spelling stays. Assemble-time exclusive export honors `process.stem_focus`
(concept match onto native instruments). Empty focus keeps boolean /
`mdx.stems` behavior.

Resolution is **per-config, never a write-back into `Settings`**. One
`Settings` assembles many configs (ensemble members, secondaries, pre-process
models), and in the GUI it is the live persisted object that read-only callers
such as `estimate_workload` also assemble from — so writing resolved flags
back leaked one model's pick onto the next and silently rewrote the user's
saved Save-stems toggles. Consumers downstream of assemble read the config's
`is_primary_stem_only` / `is_secondary_stem_only`; the two that only ever see
`Settings` (`planned_output_stems`, the ensemble combine-step list) resolve
focus themselves against the stems they have. Ensemble has no model — only an
`EnsemblePair` — so those two call sites use `exclusive_flags_for_pair`
against `pair.buckets()`. Matching the already-remapped `stem_halves()` labels
through `exclusive_flags_for_focus` with `stem_count=2` would turn Other into
Instrumental and leave `--stems vocals` unmatched on karaoke.

Deleting the remap also un-breaks `check_only_selection_stem`, which built
`f"{primary_stem} Only"` labels and so matched nothing at all while the
primary read `lead_only`. It now compares concepts, and reads the resolved
per-config flags rather than re-deriving the demucs/ensemble choice from
`Settings`.

### Engines

`write_audio` resolves concept once for deverb, inst-only splitter flags,
BV rebalance, vocal-split labels, and `master_vocal_path`. Demucs in-loop
chain uses `concept_is(..., VOCALS)`. MDX-C demix dicts stay yaml-native;
write names are concept labels (`Lead Vocals` / `Backing Vocals`).

### GTK and CLI

`process.stem_focus` is the shared exclusive-pick (bucket tag, or `raw:…`
for `StemLiteral`). Core resolves it. GTK persists it; CLI `--stems
vocals|instrumental|bass|drums|other` writes it. `--stems
primary|secondary|both` stay positional and clear focus. `--set
process.stem_focus=` accepts aliases.

`uvr models list/show` JSON keeps native keys. Human table may pretty-print.
`--vocal-split` and `--main-stem` are unchanged.

**Focus vocabulary.** `normalize_stem_focus` canonicalizes to a bucket tag,
`raw:<stem>`, or empty. As a *pick*, `other` means the Other stem — unlike a
model's native `other`, which the resolver reads as the instrumental side at 2
stems; cross-spelling still matches, but in `focus_matches_stem`, not in the
stored value. A specialty stem must be named explicitly as `raw:<stem>`: a
bare unrecognized token is a typo, so `--set` rejects it (via
`validate_setting_value`) and settings load drops it, rather than storing a
`raw:` pick that matches nothing.

**Unmatched focus.** A focus naming neither stem — or both — resolves to
"export everything" rather than a guess. Because that silently produces more
files than asked for, `JobResolver` emits a `stems.focus_unmatched` diagnostic
naming the focus, the model and its actual stems.

## Filenames

Export labels read the concept, so a community yaml's `vocals` / `other` pair
now lands on `Vocals` / `Instrumental` instead of the raw checkpoint spelling.
4-stem `other` stays `Other`; specialty stems with no bucket keep their native
name. This is a deliberate, user-visible rename of *inconsistent* output
names, not of the canonical labels — pinned by tests, because
`Ensembler.get_files_to_ensemble` collects members by filename.

## Out of scope

Hash-keyed per-model maps; renaming the canonical stem labels themselves;
running the splitter on karaoke/BV primaries; rewriting `secondary_stem()`;
wrapping assembler fields as `StemId`; redoing ensemble eligibility or the
catalogue generator.
