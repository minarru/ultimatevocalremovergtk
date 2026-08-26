# Model Display Quality Audit

**Date:** 2026-08-24
**Status:** Historical 2026-08-24 snapshot; implemented delivery record
**Scope:** The 2026-08-24 public-catalogue, runtime display-projection, and
online/offline verification snapshot

> **Historical snapshot.** This audit records the completed 2026-08-24
> 485-row delivery snapshot. It is not the live catalogue count: at the
> 2026-08-26 review, the generated reference/catalogue contains 486 rows. Use
> [`model_display_reference.tsv`](model_display_reference.tsv) and the
> generated [`models-catalogue.md`](models-catalogue.md) as the current source.

## Contract

Every model display is projected from one exact canonical runtime ID and exact
presentation evidence:

```text
explicit trusted registry override
  -> exact bundled alias
  -> exact current published catalogue label
  -> exact persisted catalogue label
  -> exact family name-mapper label
  -> family-labelled raw basename for VR/Demucs, otherwise raw basename
```

The runtime ID remains `family:basename`. Display text is never inverted into
identity, and this work does not change catalogue selection keys, artifact
filenames, execution metadata, stem semantics, eligibility, or download
resolution.

`core.model_naming.project_model_display()` is the presentation authority.
Runtime inventories, catalogue surfaces, and this audit generator call that
same ID-aware projector. The older `canonical_display_name()` remains a
structure-only compatibility formatter; the audit no longer treats its output
alone as the final runtime display.

## Checked-in reference

At the time of this snapshot, [`model_display_reference.tsv`](model_display_reference.tsv)
contained exactly 485 public catalogue rows and their syntactic presentation
IDs. Runtime inventory projected 484 of those rows. The remaining row,
`BandSplit_Roformer_4stems_FT_by_SYH99999.pth`, is intentionally ineligible
under the MDX `.ckpt`/`.onnx` execution contract; its exact `mdx:` presentation
ID lets catalogue surfaces use the audited title without creating an executable
inventory record. Presentation coverage does not alter runtime eligibility.
Each row records:

- catalogue family, effective execution architecture, source, and declared
  catalogue generation;
- the unmodified catalogue label;
- the exact family-scoped presentation ID derived from the primary artifact;
- the shared projected display and exact weight filename;
- mechanical presentation flags;
- `clean`, `reviewed`, or `unreviewed` status; and
- exact per-flag waiver reasons from
  `bundled/model_display_manifest.json`.

Demucs identity follows the runtime artifact contract: a bag with a YAML uses
the YAML basename, while older single-weight entries use the weight basename.
VR uses `vr:<pth basename>`, MDX/MDX-C-derived entries use
`mdx:<checkpoint basename>`, and Apollo uses `apollo:<checkpoint basename>`.
The accepted catalogue-family mapping is explicit: `VR Architecture`,
`Demucs`, `Apollo`, `MDX-Net`, `MDX-Net ONNX`, `MDX23C`, `Roformer`, `SCNet`,
and `Bandit`. Any other spelling fails generation instead of silently minting
an `mdx:` ID. All 485 checked-in IDs are unique.

Current strict result:

| Measure | Count |
| --- | ---: |
| Syntactic catalogue presentation IDs | 485 |
| Runtime inventory projections | 484 |
| Unique presentation IDs | 485 |
| Clean rows | 478 |
| Reviewed rows | 7 |
| Unreviewed rows | 0 |
| Accidental case-insensitive display collisions | 0 |

The seven reviewed rows retain bracketed backend IDs because removing them
would collapse same-title catalogue entries. Six belong to three exact
same-title pairs; the seventh remains distinct from its matching MVSep title.
Each has two visible mechanical flags, `embedded-id` and `underscore`; both
flags have an exact ID-scoped, reasoned waiver. No flag is globally suppressed.

## Implemented naming policy

The projector applies these approved rules only to presentation:

- All 28 reviewed VR identities carry their authoritative `VR v4` or `VR v5`
  heading while retaining meaningful HP/SP/HP2, band, sample-rate, SN, and
  sequence tokens.
- Mel-Band variants render as `MelBand Roformer`; BS variants render as
  `BandSplit Roformer`; the five PolarFormer entries use exact
  `BandSplit PolarFormer` aliases.
- Counts render after the complete variant as `(N Stems)`, with no empty em
  dash for a family-only entry. `Inst`, `Voc`, `InstVoc`, and reviewed `Vocal`
  output classes render as `Instrumental`, `Vocals`, and
  `Instrumental/Vocals`.
- Standalone `FT` expands to `Fine-Tuned`; `HQ` remains abbreviated. `SDR`,
  `FFT`, `8K`, and reviewed sample-rate units use their canonical forms.
  Opaque `SN`, `Fv9`, `SYHFT`, and numeric identifiers are preserved.
- Repeated family copy such as `SCNet ... SCNet` is removed without changing
  the family heading.
- All 54 Mega rows use `Mega Full` or `Mega <Stem> Only`, followed by
  `(53 Stems)`. The 25 formerly count-leading rows place their count after the
  complete variant.
- The eight KUIELAB ONNX storage-style names, the reviewed classic ONNX batch,
  all remaining VR utility names, and the exact correction batches use
  canonical-ID aliases; this does not create a general filename parser.
- All 24 reviewed Demucs identities retain their meaningful `Demucs v1`-
  `Demucs v4` generation and use expanded backend names such as
  `Hybrid Transformer Fine-Tuned`.
- The classic ONNX batch retains the `MDX-Net` engine heading and renders its
  descriptive `UVR` body without storage punctuation.
- BVE-to-Karaoke wording is presentation-only. Karaoke/BV eligibility still
  comes from model metadata, never from title text.
- Exact author aliases normalize each component of a reviewed `A & B`
  attribution without title-casing unknown handles. Gonza and Gonzaluigi
  remain distinct reviewed attributions.
- A genuinely unknown custom model with no exact evidence keeps its raw
  canonical basename after a non-semantic `VR —` or `Demucs —` heading where
  applicable.

## Mechanical audit and waivers

Mechanical flags are review indicators, not transformation rules. The audit
currently checks:

| Flag | Meaning |
| --- | --- |
| `raw-basename` | Display is still the storage basename |
| `underscore` | Display contains a storage/backend separator |
| `hyphenated-stem-count` | Display uses compact `N-stems` wording |
| `repeated-family` | Family is repeated in heading and title |
| `instvoc` | Compact `InstVoc` remains |
| `lowercase-sdr` | Metric abbreviation is inconsistently cased |
| `expanded-hq` | The canonical `HQ` token was expanded to `High Quality` |
| `leading-stem-count` | A count appears before rather than after the variant |
| `operational-note` | A download/backend note leaked into presentation text |
| `embedded-id` | A bracketed backend identifier remains visible |
| `duplicate-display` | Two rows collide after Unicode case folding |

An exact manifest waiver changes a flagged row from `unreviewed` to
`reviewed` only when that exact canonical ID provides a non-empty reason for
every retained flag. A missing waiver, a waiver for another ID, or a waiver
for only one of several flags leaves the row unreviewed. Display collisions
are checked independently and always fail strict verification.

Normal write mode may emit an unreviewed reference so a maintainer can inspect
and review it. Strict check mode exits 1 for any of:

- reference or catalogue drift;
- one or more unreviewed presentation flags; or
- any case-insensitive display collision.

`--check` validates the catalogue, IR sidecar, intent reference, display
reference, and stem-semantics reference together. It never writes those
artifacts, downloaded metadata, or cache content. An online check may still
read the network: missing or stale coordinator, community, and YAML data is
consumed in memory without creating or replacing cache paths.

## Snapshot and offline behavior

The checked-in reference was reproduced from the complete warm cache captured
on 2026-08-24:

| Collection mode | Entries | Presentation result |
| --- | ---: | --- |
| Fresh online snapshot | 485 | Complete source evidence |
| Matching warm offline cache | 485 | Byte-identical reference projection |
| Isolated cold offline cache | 97 | Bundled/local membership only |

Online and warm-offline runs use the same projector, so equivalent exact
source evidence produces identical names. The registry persists exact
presentation evidence for installed models, and successful downloads publish
only after that evidence is stored. Refresh backfill matches exact primary
artifacts against the post-deduplication public snapshot, so harmless source
label aliases do not create false ambiguity. A genuine published ambiguity is
non-mutating and emits an actionable warning. Cold-offline unknowns do not
receive a guessed remote association; VR and Demucs entries retain only their
family-labelled raw basename fallback.

The existing degraded-publication guard applies before the generated artifact
bundle is written or judged. A cold-cache subset therefore exits 2 instead of
replacing or comparing against the 485-row publication unless a maintainer
explicitly passes `--allow-degraded`. `--summary` remains read-only and can be
used to diagnose that subset.

## Reproducible commands

Use a complete cache with all coordinator and supplemental sources. The
snapshot used for this audit can be selected explicitly with `UVR_CACHE_DIR`:

```bash
UVR_CACHE_DIR=/path/to/warm-cache \
  .venv/bin/python scripts/generate_models_catalogue.py \
  --offline
```

Strict read-only verification:

```bash
UVR_CACHE_DIR=/path/to/warm-cache \
  .venv/bin/python scripts/generate_models_catalogue.py \
  --offline --check
```

Refresh from the live sources, then write the audited reference:

```bash
.venv/bin/python scripts/generate_models_catalogue.py \
  --refresh
```

Diagnose an isolated cold cache without writing:

```bash
UVR_CACHE_DIR=/path/to/empty-cache \
  .venv/bin/python scripts/generate_models_catalogue.py --summary --offline
```

Normal generation synchronizes the Markdown catalogue, IR sidecar, intent TSV,
display TSV, and stem-semantics TSV in one validated bundle. `--check` is the
read-only validation of that same complete bundle. The legacy `--write-tsv`,
`--write-display-reference`, and `--write-stem-semantics-reference` flags remain
accepted as deprecated compatibility no-ops; they no longer select individual
outputs. `--summary` remains read-only, and exit 2 continues to mean the
available data is too degraded to publish or judge.
