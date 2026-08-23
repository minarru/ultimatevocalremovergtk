# Model Display Quality Audit

**Date:** 2026-08-23
**Status:** Implemented and enforced
**Scope:** Complete current public catalogue, runtime display projection, and
online/offline verification

## Contract

Every model display is projected from one exact canonical runtime ID and exact
presentation evidence:

```text
explicit trusted registry override
  -> exact bundled alias
  -> exact live or persisted source label through conservative formatting
  -> raw canonical basename
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

[`model_display_reference.tsv`](model_display_reference.tsv) contains exactly
484 current public catalogue rows. Each row records:

- catalogue family, effective execution architecture, source, and declared
  catalogue generation;
- the unmodified catalogue label;
- the exact canonical runtime ID derived from the runtime primary artifact;
- the runtime-projected display and exact weight filename;
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
an `mdx:` ID. All 484 checked-in IDs are unique.

Current strict result:

| Measure | Count |
| --- | ---: |
| Reference rows | 484 |
| Unique canonical IDs | 484 |
| Clean rows | 481 |
| Reviewed rows | 3 |
| Unreviewed rows | 0 |
| Accidental case-insensitive display collisions | 0 |

The three reviewed rows retain bracketed backend IDs because removing them
would collapse same-title catalogue entries. Each has two visible mechanical
flags, `embedded-id` and `underscore`; both flags have an exact ID-scoped,
reasoned waiver. No flag is globally suppressed.

## Implemented naming policy

The projector applies these approved rules only to presentation:

- VR has no artificial family prefix. Exact aliases cover the 22 formerly raw
  legacy names while retaining meaningful HP/SP/HP2, band, sample-rate, SN,
  and sequence tokens.
- Mel-Band variants render as `MelBand Roformer`; BS variants render as
  `BandSplit Roformer`; the five PolarFormer entries use exact
  `BandSplit PolarFormer` aliases.
- Counts render as `(N Stems)`. `Inst`, `Voc`, and `InstVoc` render as
  `Instrumental`, `Vocals`, and `Instrumental/Vocals` where they are known
  presentation terms.
- `FT`, `HQ`, `SDR`, `FFT`, and `8K` use the approved readable forms. Opaque
  `SN`, `Fv9`, and numeric identifiers are preserved.
- Repeated family copy such as `SCNet ... SCNet` is removed without changing
  the family heading.
- The eight KUIELAB ONNX storage-style names and the exact Bowed Strings row
  use reviewed exact aliases; this does not create a general filename parser.
- Demucs retains its meaningful `v1`-`v4` generation and uses curated backend
  spellings such as `HTDemucs Fine-Tuned`.
- The classic ONNX batch retains the `MDX-Net` engine heading and renders its
  descriptive `UVR` body without storage punctuation.
- BVE-to-Karaoke wording is presentation-only. Karaoke/BV eligibility still
  comes from model metadata, never from title text.
- Exact author aliases normalize known spellings without guessing ownership.
  Gonza and Gonzaluigi remain distinct reviewed attributions.
- A genuinely unknown custom model with no exact evidence stays at its raw
  canonical basename.

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

`--check --write-display-reference` never writes the catalogue, sidecar,
reference, downloaded metadata, or cache content. An online check may still
read the network: missing or stale coordinator, supplement, community, and
YAML data is consumed in memory without creating or replacing cache paths.

## Snapshot and offline behavior

The checked-in reference was reproduced from the complete warm cache captured
on 2026-08-23:

| Collection mode | Entries | Presentation result |
| --- | ---: | --- |
| Fresh online snapshot | 484 | Complete source evidence |
| Matching warm offline cache | 484 | Byte-identical reference projection |
| Isolated cold offline cache | 97 | Bundled/local membership only |

Online and warm-offline runs use the same projector, so equivalent exact
source evidence produces identical names. The registry persists exact
presentation evidence for installed models, and successful downloads publish
only after that evidence is stored. Cold-offline unknowns do not receive a
guessed remote association; they retain their raw basename.

The existing degraded-publication guard applies before either checked-in
document is written or judged. A cold-cache subset therefore exits 2 instead
of replacing or comparing against the 484-row publication unless a maintainer
explicitly passes `--allow-degraded`. `--summary` remains read-only and can be
used to diagnose that subset.

## Reproducible commands

Use a complete cache with all coordinator and supplemental sources. The
snapshot used for this audit can be selected explicitly with `UVR_CACHE_DIR`:

```bash
UVR_CACHE_DIR=/path/to/warm-cache \
  .venv/bin/python scripts/generate_models_catalogue.py \
  --offline --write-display-reference
```

Strict read-only verification:

```bash
UVR_CACHE_DIR=/path/to/warm-cache \
  .venv/bin/python scripts/generate_models_catalogue.py \
  --offline --check --write-display-reference
```

Refresh from the live sources, then write the audited reference:

```bash
.venv/bin/python scripts/generate_models_catalogue.py \
  --refresh --write-display-reference
```

Diagnose an isolated cold cache without writing:

```bash
UVR_CACHE_DIR=/path/to/empty-cache \
  .venv/bin/python scripts/generate_models_catalogue.py --summary --offline
```

`--write-display-reference` is opt-in. Without it, normal catalogue generation
is unchanged. `--summary` and `--check` retain their existing read-only
semantics, and exit 2 continues to mean the available data is too degraded to
publish or judge.
