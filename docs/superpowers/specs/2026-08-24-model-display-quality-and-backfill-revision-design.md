# Model Display Quality and Backfill Revision Design

**Date:** 2026-08-24

**Status:** Implemented

**Scope:** Model presentation quality, exact catalogue evidence, and installed-model presentation backfill

## Summary

This revision supersedes the affected naming and catalogue-presentation matching
rules in the implemented
[`2026-08-22 model display projection and refresh design`](2026-08-22-model-display-projection-refresh-design.md).
It does not change the underlying identity model: canonical `family:basename`
IDs, artifacts, backend configuration, stem semantics, eligibility, and saved
selections remain authoritative and unchanged.

Every human-facing model surface uses the same ID-aware presentation pipeline.
The revision improves the reviewed public catalogue names, restores established
abbreviations such as `HQ`, and makes online refresh backfill use the published,
deduplicated catalogue entry rather than treating harmless source-label aliases
as identity ambiguity.

The generated catalogue, display reference, and quality audit are regenerated
from the runtime projector after the implementation and its focused tests pass.

## Invariants and Non-goals

Presentation changes must never alter:

- canonical `family:basename` IDs or family assignment;
- backend names or primary/supporting artifact filenames;
- model hashes, configuration lookup, execution metadata, or identity digests;
- stem names, routing semantics, karaoke/BV eligibility, or picker membership;
- saved canonical selections or warning/repick gates; or
- download resolution and catalogue selection keys.

Display text is never inverted into identity. The revision does not introduce
fuzzy matching, substring identity, guessed authorship, basename parsing for
unknown models, or semantic inference from arbitrary custom filenames.

## Presentation Evidence Precedence

Every model surface uses this precedence:

1. trusted explicit registry override;
2. exact canonical-ID alias from the bundled presentation manifest;
3. exact current label from the published, deduplicated catalogue snapshot;
4. exact persisted catalogue label;
5. exact family name-mapper label; and
6. a family-labelled raw canonical basename for a genuinely unknown VR or
   Demucs model, and the raw basename for another genuinely unknown family.

An empty value falls through to the next layer. A catalogue refresh may replace
persisted mapper evidence with exact current catalogue evidence, but it must not
replace or erase an explicit display override.

Projection remains offline, deterministic, and idempotent once its exact
evidence has been selected. Online and matching warm-offline snapshots must
produce identical display text. A cold-offline unknown model remains raw after
its non-semantic family heading (`VR —` or `Demucs —`) rather than receiving a
guessed catalogue association.

## Canonical Display Grammar

The canonical structure is:

```text
Family or product [— Variant] [(N Stems)] [· Author(s)] [collision suffix]
```

Rules:

- Do not emit an em dash when there is no variant. Use
  `BandSplit Roformer (4 Stems)`, not
  `BandSplit Roformer — (4 Stems)`.
- Put the count after the complete variant, including its size, tuning, and
  version: `SCNet — Huge Bleedless (4 Stems) · Aname` and
  `MelBand Roformer — Large v2 (4 Stems) · Aname`.
- Use `·` only for author attribution. Preserve the source order of multiple
  authors.
- Use `/` for paired concepts such as `Instrumental/Vocals`, `Male/Female`,
  `Drum/Bass`, and `De-Echo/DeReverb`.
- Remove storage underscores and ordinary word-joining hyphens. Preserve
  meaningful forms such as `Fine-Tuned`, `Mid-Side`, `De-Echo`, `Hi-Hat`, and
  the exact output-stem term `Drum-Bass`.
- Remove filenames, extensions, download state, backend configuration details,
  and operational notes such as `(only weights)`.
- Prefix reviewed VR models with the generation established by their exact
  catalogue evidence (`VR v4 —` or `VR v5 —`). Prefix an unknown custom VR
  basename with `VR —` without guessing a generation.
- Prefix reviewed Demucs models with `Demucs vN —`. Prefix an unknown custom
  Demucs basename with `Demucs —` without guessing a generation.
- Preserve a bracketed collision suffix only for an exact reviewed model whose
  friendly title would otherwise collide.

## Family Headings and Technical Tokens

Canonical family/product headings are:

- `MelBand Roformer`;
- `BandSplit Roformer`;
- `BandSplit PolarFormer`;
- `MDX-Net`;
- `MDX23C`;
- `SCNet`;
- `Bandit`; and
- `Apollo`;
- `VR v4` and `VR v5` for reviewed VR generations; and
- `Demucs v1` through `Demucs v4` for reviewed Demucs generations.

VR and Demucs family headings intentionally remain visible in mixed selectors.
Do not double-prefix an already projected label. `UVR` remains only when it is
part of a reviewed product or model variant, not as a substitute family
heading.

Technical-token rules:

- `HQ` is the canonical presentation token. Preserve source `HQ` and convert
  reviewed `High Quality` wording back to `HQ`.
- Expand standalone `FT` to `Fine-Tuned`. Do not expand `FT` inside an opaque
  identifier such as `SYHFT`.
- Expand known standalone `Inst`, `Voc`, `InstVoc`, and `Vox` presentation terms
  to `Instrumental`, `Vocals`, and `Instrumental/Vocals`.
- Use plural `Vocals` for an output class, including HP Vocal, Kim Vocal, and
  Mega Vocal entries.
- Normalize `SDR`, `FFT`, `8K`, and units such as `16 kHz` and `44.1 kHz`.
- Use lowercase version markers such as `v1` and `v2.5`, and title-case reviewed
  descriptive states such as `Beta`, `Preview`, `Full`, and `Final`.
- Normalize reviewed compound names to `DeReverb`, `DeNoise`, `DeBleed`,
  `SpeechSep`, `ChoirSep`, and `DrumSep`.
- Preserve opaque tokens including `SN`, `Fv1` through `FvX`, `SYHFT`, `BGM`,
  `FNF`, `VFX`, `IHF`, `EXP`, `FNO`, `MUSDB18`, and reviewed numeric IDs.

These transformations apply only when exact source evidence or an exact
canonical-ID alias establishes that the token has the reviewed meaning. The
projector must not infer a target, author, version, or metric from an unknown
basename.

## Exact Naming Batches

### Confirmed corrections

The bundled presentation manifest provides exact aliases for:

- `BandSplit Roformer — DeReverb Room · Anvuew`;
- `BandSplit Roformer — SpeechSep · AliceN`;
- `BandSplit Roformer — Mag (3179) · Anvuew`;
- `BandSplit Roformer — Karaoke · Becruily & Frazer`;
- `BandSplit Roformer — Guitar · Kimberley Xlance`;
- `BandSplit Roformer — Siamese Vocals · Unwa`;
- `BandSplit Roformer — Instrumental EXP Value Residual · Unwa`;
- `MelBand Roformer — Instrumental Metal Preview · Mesk`;
- `MelBand Roformer — Xeno · DrYound3r`;
- `MelBand Roformer — DeNoiser Children 16 kHz · Phaedrus33`;
- `MDX-Net — UVR 9482`; and
- `MDX23C — Phantom Centre Extraction · WesleyR36`.

The Instrumental EXP Value Residual alias applies independently to the exact
MVSep and Politrees IDs. Because those distinct artifacts otherwise collide,
the Politrees `mdx:BS_Inst_EXP_VRL` display retains its reviewed bracketed
backend ID. Exact aliases also place Essid's metrics before the author
(`Instrumental (SDR 16.52/16.81) · Essid`) and render
`mdx:mel_band_roformer_karaoke_gabox` as
`MelBand Roformer — Karaoke Beta · Gabox`.

All BandSplit `Deverb`/`Dereverb` entries render as `DeReverb`. Reviewed
`Choirsep` entries render as `ChoirSep`; lowercase state words use their
approved title case; and uppercase `V1`/`V2` version markers render as
lowercase `v1`/`v2`.

The `Mag` alias deliberately uses `3179`, matching its exact canonical basename
and artifact. The upstream `3719` label is treated as questionable presentation
data, not as authority to rename the artifact or runtime ID.

### ViperX models

Use these exact displays:

- `BandSplit Roformer — Drum/Bass Separation (SDR 10.53) · ViperX`;
- `BandSplit Roformer — ViperX 12.96`;
- `BandSplit Roformer — ViperX 12.97`; and
- `MelBand Roformer — Vocals (SDR 11.44) · ViperX`.

The ViperX-series form intentionally keeps the TRvlvr 12.96 and 12.97 entries
distinct from the MVSep entries displayed as
`Vocals (SDR 12.96/12.97) · ViperX`.

The 10.53 model-level title describes the operation rather than copying its
primary output label. Its exact output stems remain `No Drum-Bass` (the mix
without the combined subset) and `Drum-Bass` (the isolated combined subset).
Presentation work must not change those stem names or their routing.

### Stem-count entries

Apply these forms to all 25 entries whose current display leads with the count:

- no variant: `Family (N Stems) · Author`;
- with a variant: `Family — Variant (N Stems) · Author`;
- size and version stay together before the count, for example
  `Large v2 (4 Stems)`; and
- tuning stays with the variant, for example
  `Fine-Tuned Large v1 (4 Stems)`.

Representative results:

- `BandSplit Roformer (4 Stems) · Aname`;
- `MDX23C — Small (4 Stems) · KUIELAB`;
- `MelBand Roformer — Large v2 (4 Stems) · Aname`; and
- `SCNet — Huge Strong Fullness (4 Stems) · Aname`.

### Mega models

All 54 Mega entries use one of these templates:

```text
BandSplit Roformer — Mega Full (53 Stems) · MVSep
BandSplit Roformer — Mega <Stem> Only (53 Stems) · MVSep
```

Normalize exact stem terms including `Acoustic Guitar`, `Backing Vocals`,
`Digital Piano`, `Double Bass`, `Electric Guitar`, `French Horn`, `Hi-Hat`,
`Lead Vocals`, `Wind Chimes`, and `Vocals`. Do not retain `(FULL)`, lowercase
`(only …)`, storage hyphens, or the abbreviation `Hh`.

### MDX-Net and MDX23C

- Preserve the engine distinction between `MDX-Net` and `MDX23C`.
- Use `MDX-Net — UVR …` without repeating `MDXNET` in the variant body.
- Preserve `HQ`, for example `MDX-Net — UVR Instrumental HQ 4`.
- Restore `8K FFT` when the exact model evidence contains it:
  `MDX23C — 8K FFT Instrumental/Vocals HQ` and
  `MDX23C — 8K FFT Instrumental/Vocals HQ 2`.
- Use `MDX-Net — Kim Vocals 1` and `MDX-Net — Kim Vocals 2`, not singular
  `Vocal`.
- Retain meaningful opaque model identifiers such as `D1581`.

### VR

All 28 reviewed VR identities carry an authoritative generation prefix. The 24
v5 entries cover HP, HP2, SP, BVE, and utility models; the four MGM entries use
v4. Representative forms are:

- `VR v5 — HP Vocals 3`;
- `VR v5 — SP 4-Band 44.1 kHz 1`;
- `VR v5 — Karaoke BVE (4 Bands, SN, 44.1 kHz) 1`;
- `VR v5 — De-Echo Aggressive · FoxJoy`;
- `VR v5 — De-Echo/DeReverb · FoxJoy`;
- `VR v5 — DeNoise Lite · FoxJoy`;
- `VR v5 — DeReverb · Aufr33 & Jarredou`; and
- `VR v4 — MGM High-End`.

Preserve reviewed HP, HP2, SP, MGM, BVE, band-count, sample-rate, SN, and
sequence identifiers. Karaoke/BVE wording is presentation-only and must not
change Vocal Splitter eligibility. For an exact v4/v5 source label without a
curated alias, retain its generation and conservatively format the label. A
custom VR basename with no generation evidence uses `VR — <raw basename>`.

### Demucs

All 24 reviewed Demucs identities use expanded generation-aware names:

- v1: `Time-Domain`, `Time-Domain Extra`, `Light`, `Light Extra`,
  `Conv-TasNet`, and `Conv-TasNet Extra`;
- v2: `Time-Domain`, `Time-Domain 48 kHz HQ`, `Time-Domain Extra`,
  `Unit Test`, `Conv-TasNet`, and `Conv-TasNet Extra`;
- v3: `MDX`, `MDX Extra`, `MDX Quantized`, `MDX Extra Quantized`, the three
  `Repro MDX A` variants, and `UVR Model (2 Stems)`; and
- v4: `Hybrid Demucs MMI`, `Hybrid Transformer`,
  `Hybrid Transformer (6 Stems)`, and
  `Hybrid Transformer Fine-Tuned`.

The complete display begins with `Demucs vN —`, for example
`Demucs v4 — Hybrid Transformer (6 Stems)`. An exact source label may supply a
known generation and backend spelling, but the projector never derives a
generation from an arbitrary basename. A custom basename without generation
evidence uses `Demucs — <raw basename>`.

### Author attribution

Author aliases are case-insensitive but apply only to exact author tokens. For
a reviewed `A & B` attribution, normalize each component independently and
preserve source order.

Required authoritative spellings include `Essid`, `Aufr33`, `Jarredou`,
`StarryTong`, `WesleyR36`, `ViperX`, `Becruily`, `Anvuew`, `Gilliaaan`, and
`ZFTurbo`. Do not title-case unknown or deliberately styled handles such as
`jazzpear`, `chenCFD`, or `neoculture`. Gonza and Gonzaluigi remain distinct
reviewed authors.

## Collision and Unknown-model Rules

- Preserve the four reviewed bracketed backend IDs whose removal
  would create display collisions.
- Do not introduce duplicate displays for the ViperX series.
- Compare generated displays case-insensitively after Unicode normalization.
- Resolve a new collision through an exact descriptive alias or a reviewed
  backend-ID suffix with a reasoned waiver. Never resolve it by changing
  canonical identity.
- Unknown custom models without exact presentation evidence retain their raw
  basenames after the non-semantic `VR —` or `Demucs —` family heading where
  applicable. Conservative formatting must not manufacture catalogue
  membership, a generation, or a backend expansion.

## Published-catalogue Backfill Contract

Installed-model presentation backfill resolves current evidence against the
post-deduplication public snapshot: the same catalogue entries shown by the
Download Center and used to construct catalogue `ModelRecord` values.

Matching is by the exact canonical `family:basename` derived from the primary
artifact. It is not by display text. Multiple pre-deduplication source labels
for the same artifact, such as upstream `V1` and Politrees `v1`, are
presentation aliases rather than identity ambiguity.

For each installed model:

1. Derive the exact canonical ID from its family and primary artifact.
2. Find published entries in that family that resolve to that exact ID.
3. If exactly one published entry remains after catalogue deduplication, use
   its current label and source as the current presentation evidence.
4. Replace persisted `model_name_mapper` evidence with that published label and
   source, preserving any explicit display override.
5. If multiple genuinely distinct published matches remain, retain the
   existing evidence, emit an actionable ambiguity warning containing the
   canonical ID and candidate selections, and do not mutate the registry.

This matching rule does not case-fold or normalize a display label into an ID.
It collapses aliases only because the published catalogue has already resolved
them to the same exact family-scoped artifact identity.

Backfill is presentation-only. It does not increment `inventory_generation`,
rehash checkpoints, invalidate execution plans, change eligibility, or modify
saved canonical selections. A successful relabel emits the existing
presentation-change notification so mounted and lazy widgets repaint while
preserving selection by canonical ID.

## Surface Contract

The primary, secondary, pre-process, ensemble-member, Vocal Splitter, Model
Test, Download Center, progress/log, human CLI, and JSON `display` surfaces all
consume the shared projection. Widget values remain canonical IDs. Vocal
Splitter membership remains karaoke/BV-metadata-only. Newly available models
still require the approved safe repick behavior.

## Verification Requirements

### Naming projection

- Test precedence, idempotence, exact alias lookup, source formatting, and raw
  fallback.
- Prove that `HQ` remains abbreviated, standalone `FT` becomes `Fine-Tuned`,
  and opaque compounds remain unchanged.
- Cover every confirmed exact correction and all four ViperX displays.
- Assert the exact `No Drum-Bass` and `Drum-Bass` output labels remain
  unchanged.
- Cover all stem-count placements, all Mega stem-term transformations, all 28
  reviewed VR identities, all 24 reviewed Demucs identities,
  author-component normalization, technical-token casing, and version/state
  casing.
- Prove that exact v4/v5 and Demucs v1-v4 source labels remain idempotent,
  trusted overrides stay verbatim, and unknown custom models receive only the
  family-aware raw fallback.
- Prove that the four collision suffixes and Gonza/Gonzaluigi distinction are
  preserved.

### Catalogue and registry behavior

- Reproduce the upstream `V1` plus Politrees `v1` duplicate-label cases for
  `mdx:melband_roformer_inst_v1` and
  `mdx:melband_roformer_instvoc_duality_v1`.
- Verify that refresh selects the single published entry, replaces mapper
  evidence with its friendly catalogue label/source, and preserves an explicit
  override.
- Verify that genuine post-deduplication ambiguity is non-mutating and emits
  the required warning.
- Verify presentation relabeling preserves canonical picker selections and
  triggers no full inventory invalidation.
- Verify fresh-online and matching warm-offline parity plus cold-offline raw
  fallback without network access.

### Full surfaces and publication

- Validate primary, secondary, ensemble-member, Vocal Splitter, Model Test,
  Download Center, progress/log, CLI, and JSON display output.
- Regenerate the full 484-row display reference only after implementation.
  Require zero unreviewed presentation flags and zero accidental display
  collisions.
- Run the focused naming, registry, inventory, repository-refresh, generator,
  CLI, and private headless GTK suites, followed by the complete unit suite and
  basedpyright.
- Launch the host-Wayland application through `uvr --trace gui` with real local
  settings, models, and cache. Diagnostic CLI flags must not reach GTK; the
  trace must contain no unknown-option failure, CSS parser warning, uncaught
  exception, or unexpected basename fallback.
- Parse the source stylesheet with GTK and rebuild the bundled GResource after
  removing unsupported CSS declarations. The Python-measured error-summary
  height cap remains authoritative.

## Implementation Boundary

This specification introduces no public projector signature or registry schema
change. The audit and generated reference describe the verified implementation
state after regeneration.
