# Unified Model Manifest and Catalogue Evidence Design

**Status:** Approved for implementation on 2026-08-27.

## Summary

Replace the three independent bundled model manifests with one strict,
immutable model manifest, and upgrade the mutable catalogue YAML cache into a
last-known-good validation cache. The unified manifest is the sole bundled
authority for exact presentation aliases, reviewed stem semantics, roles,
pairs, lifecycle, catalogue/config evidence, and strict MDX runtime contracts.
Online catalogue data may validate or challenge those decisions, but may not
invent or silently rewrite them.

This revision addresses the Download Center's misleading `Raw outputs` rows.
Those rows currently combine several unrelated states: a genuine unknown
model, an evidence fetch still in progress, an unavailable config, a reviewed
restoration model for which stems do not apply, and a successful signature
mismatch. They must become distinct states.

Canonical model identity remains exact `family:basename`. Native backend stem
keys, artifact names, model execution, eligibility, settings, and saved
selections remain unchanged.

## Goals

- Make one atomic bundled file the authority for all reviewed per-model facts.
- Give runtime, Download Center, CLI, generator, and audit code one exact
  catalogue-ID derivation function and one evidence-precedence policy.
- Preserve reviewed display and stem behavior in cold-offline operation.
- Revalidate current upstream configs efficiently without discarding usable
  evidence on transient failures.
- Distinguish semantic review state from evidence availability in UI and JSON.
- Make an upstream addition, removal, or semantic drift an actionable review
  event rather than an inferred runtime behavior change.
- Republish the current 485-model catalogue with no unexplained raw entries.

## Non-Goals

- Do not change canonical IDs, backend-native stem keys, export routes, model
  eligibility, or execution metadata.
- Do not infer intent, authors, roles, pairs, or runtime contracts from fuzzy
  labels or unknown basenames.
- Do not turn the online validation cache into a fourth presentation manifest.
- Do not migrate or reinterpret the mutable installed-model registry.
- Do not preserve the old bundled manifest files as runtime fallbacks after the
  new file is published.

## Architecture

```text
bundled/model_manifest.json
  |-- strict loader (one parse, one atomic success/failure boundary)
  |-- presentation view --> model_naming compatibility facade
  |-- stem view ---------> model_stem_manifest compatibility facade
  `-- runtime view ------> mdx_runtime_contract compatibility facade

post-deduplicated catalogue snapshot
  + exact family-aware catalogue ID
  + bundled exact evidence
  + catalogue_stem_cache.json schema 2 (optional live validation)
  --> EntryMeta semantics + CatalogueEvidenceState
  --> Download Center, CLI/JSON, generator and audit
```

`core/model_manifest/` owns the new implementation and is split by
responsibility:

```text
core/model_manifest/__init__.py
core/model_manifest/schema.py
core/model_manifest/loader.py
core/model_manifest/presentation.py
core/model_manifest/stems.py
core/model_manifest/runtime.py
```

The public functions currently imported from `core/model_naming.py`,
`core/model_stem_manifest.py`, and `core/mdx_runtime_contract.py` remain stable
through thin compatibility facades during this change. Consumers must not
parse the bundled JSON themselves.

## Unified Bundled Manifest

The new file is `bundled/model_manifest.json`. It starts at
`schema_version: 1` because it is a new atomic contract rather than a runtime
migration of any old schema.

```json
{
  "schema_version": 1,
  "author_aliases": {
    "viperx": "ViperX"
  },
  "roles": {
    "vocal.vocals": {
      "display": "Vocals",
      "filename_tag": "Vocals",
      "family": "vocal"
    }
  },
  "pairs": {
    "pair.vocals_instrumental": {
      "display": "Vocals/Instrumental",
      "roles": ["vocal.vocals", "mix.instrumental"]
    }
  },
  "models": {
    "mdx:example": {
      "lifecycle": "current",
      "display_alias": "MelBand Roformer — Example · Author",
      "display_waivers": {
        "embedded-id": "Exact backend ID is retained to avoid a collision."
      },
      "stem_semantics": {
        "native_signature": ["Vocals"],
        "intent": "vocals",
        "contexts": {
          "full_mix": {
            "logical_primary": "vocal.vocals",
            "outputs": []
          }
        },
        "review_note": "Exact reviewed route declaration."
      },
      "catalogue_evidence": {
        "source": "mvsepless",
        "catalogue_label": "exact source label",
        "primary_artifact": "example.ckpt",
        "config_yaml": "example.yaml",
        "metadata_source": "exact_config"
      },
      "config_evidence": {
        "example.yaml": {
          "content_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
          "training_instruments": ["Vocals"],
          "target_instrument": "Vocals",
          "sources": ["models/MDX_Net_Models/model_data/mdx_c_configs/example.yaml"]
        }
      },
      "runtime_contract": {
        "backend": "mdx_c_target",
        "primary_native": "Vocals",
        "config_yamls": ["example.yaml"],
        "evidence": {
          "artifact_sources": ["https://example.invalid/example.ckpt"],
          "runtime_metadata_sources": ["models/MDX_Net_Models/model_data/model_data.json"],
          "review_note": "Exact config and hash evidence establish the runtime contract."
        },
        "artifact_evidence": [
          {
            "uvr_md5": "00000000000000000000000000000000",
            "hash_record_source": "models/MDX_Net_Models/model_data/model_data.json"
          }
        ]
      }
    }
  }
}
```

The existing schema-2 stem context and output grammar is embedded unchanged
inside `stem_semantics`. The example abbreviates its route objects only; their
closed fields and validation remain governed by the 2026-08-24 stem-semantics
design.

### Root and Record Rules

- Every object is closed-world. Unknown fields fail validation.
- `author_aliases` keys are case-folded exact author tokens. They do not match
  substrings or infer authors.
- `roles` and `pairs` retain the current strict schema and four reviewed pair
  definitions.
- Every model key parses as an exact canonical ID.
- `lifecycle` is exactly `current` or `retired`.
- Every record requires `lifecycle`, `catalogue_evidence`, and exactly one of
  `stem_semantics` or `stem_waiver`. A `stem_waiver` is a non-empty reviewed
  reason string.
- `display_alias` and `display_waivers` are optional and independent. A model
  may have a waiver without an alias.
- `catalogue_evidence` requires non-empty `source`, `catalogue_label`,
  `primary_artifact`, and `metadata_source`; `config_yaml` is optional. It is
  exact provenance, not identity input. A retired model retains its last
  reviewed catalogue evidence.
- `config_evidence` is optional and keyed by exact config basename. Its digest
  and parsed training fields must agree with every bundled/local source it
  cites. Source strings are non-empty `http://`, `https://`, `bundled/`,
  `models/`, `cache:`, or `checked-in:` references; local references are
  revalidated against their bytes.
- `runtime_contract` is allowed only for `mdx:` records. It retains the current
  exact `backend`, `primary_native`, `config_yamls`, `evidence`, and ordered
  `artifact_evidence` fields. `evidence` contains artifact sources, runtime
  metadata sources, and a review note; each artifact-evidence row contains an
  exact `uvr_md5` and reviewed hash-record source. The contract references the
  record's `stem_semantics` and `config_evidence`; it does not duplicate a
  second native signature or a second config-evidence object.
- Runtime backend classes preserve the current classic ONNX, MDX-C multi, and
  MDX-C target cardinality rules.
- A runtime contract's config names must resolve within that same record, and
  its primary native value must be valid for the reviewed signature.
- `current` records participate in current-catalogue coverage. `retired`
  records remain resolvable for installed models but are excluded from that
  coverage and from Download Center membership.
- If a retired ID reappears upstream, generation fails with a lifecycle-drift
  diagnostic until a reviewer marks it current.

### Atomic Load and Failure

The file is parsed and validated once into immutable views. Presentation,
stems, and runtime consumers all receive views from that same validated object.
If any section is invalid, no section is published: callers receive their
existing safe raw/fallback behavior and one critical diagnostic identifies the
manifest error. Runtime must never mix presentation from one file version with
stems or contracts from another.

The old bundled files are removed in the same implementation commit:

- `bundled/model_display_manifest.json`
- `bundled/model_stem_manifest.json`
- `bundled/model_runtime_stem_contracts.json`

There is no runtime compatibility reader for those files. A test-only migration
fixture proves that the new views reproduce all old reviewed decisions before
the current-catalogue amendments are applied.

## Exact Catalogue Identity

Move `catalogue_presentation_id` into neutral
`core/catalogue_identity.py`. Preserve the existing import from
`core/model_catalogue.py` as a re-export.

Runtime merging, Download Center, CLI, generator, and semantic audit all call
this one function with the family, catalogue label, complete file mapping, and
family-scoped metadata. The first-checkpoint shortcut in
`core/catalog_sources.py::_catalogue_model_id` is removed. In particular,
Demucs identities derive from their declared YAML/model identity, not from a
hash-named checkpoint artifact.

Metadata lookup is family-scoped through `meta_by_family` and
`catalogue_entry_meta`. The flat `catalogue_meta` mapping remains a transitional
compatibility view only and must not be used to associate an entry when two
families can share a label.

## Evidence Precedence

For an exact canonical catalogue ID, use evidence in this order:

1. Successfully parsed bytes from the exact associated live config URL.
2. Exact bundled `config_evidence` for that model and config basename.
3. Exact non-config family evidence for catalogue types that do not have an
   associated config, including Demucs declarations and the reviewed VR BVE
   supplement.
4. Source summaries and categories as audit-only hints.

When an exact config association exists, a source summary, category, alias, or
model name must never override the parsed or bundled config's instruments or
target. This preserves the reviewed mappings for the current Guitar,
Karaoke-Aufr33/ViperX, and DeReverb-Echo entries, whose lower-authority summary
metadata currently disagrees with their exact YAML.

All remote YAML bytes use `core.model_data.load_mdx_c_config_data`. This accepts
the reviewed `!!python/tuple` construct used by MDX-C configs while rejecting
arbitrary Python object tags. `yaml.safe_load` is not used for these configs.

An exact signature or target mismatch after a successful parse changes that
row's semantic review status to `raw` and exposes an actionable warning. A
missing network response does not manufacture a mismatch.

## Mutable Online Validation Cache

Keep the runtime file name `catalogue_stem_cache.json`, but write explicit
schema 2:

```json
{
  "schema_version": 2,
  "entries": {
    "https://example.invalid/config.yaml": {
      "stems": ["Vocals", "Instrumental"],
      "target_instrument": "Vocals",
      "content_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "etag": "optional validator",
      "last_modified": "optional validator",
      "fetched_at": 0.0,
      "checked_at": 0.0,
      "last_error": null
    }
  }
}
```

`last_error`, when present, is a closed object containing `kind`, `message`,
and `at`. Cache keys are normalized exact URLs. A cache entry never contains
display aliases, roles, pairs, intent, lifecycle, or runtime-contract
decisions.

- Read the existing implicit/legacy cache schema without writing it.
- The next successful mutation writes the complete normalized schema-2 cache
  atomically.
- Normal startup treats successful evidence as fresh for seven days and a
  cold failure as fresh for six hours.
- Manual refresh bypasses both TTLs and conditionally revalidates every current
  config URL with `If-None-Match` and/or `If-Modified-Since` when validators
  exist.
- HTTP 304 updates `checked_at` and preserves evidence and `fetched_at`.
- HTTP 200 is size-limited, parsed, digested, compared, and only then replaces
  usable evidence and validators.
- A failed revalidation preserves all last-known-good evidence and validators,
  records `last_error`, and marks the evidence stale. It must not replace a
  good entry with an empty failure record.
- A first fetch failure has no usable evidence and is unavailable until retry.
- Concurrent worker completions serialize through the existing lock and each
  write is atomic.
- Manual refresh retries prior failures; ordinary background scheduling obeys
  the failure TTL.
- A content digest change with unchanged parsed instruments and target remains
  reviewed but is reported as evidence drift for the next checked-in
  republish. Strict runtime-contract records continue to require their exact
  approved digest and fields and become raw on contract mismatch.

## Review State and Evidence State

Do not add loading/network values to `StemReviewStatus`. Semantic review stays
`reviewed`, `waived`, or `raw`.

Add a separate `CatalogueEvidenceState` with exact values:

| State | Meaning |
|---|---|
| `ready` | Usable exact bundled or live evidence is available. |
| `pending` | No usable evidence exists and an exact fetch is queued/in flight. |
| `unavailable` | No usable evidence exists and the latest fetch failed or cannot run. |
| `stale` | Last-known-good evidence is in use after failed revalidation. |
| `not_applicable` | The model class has no stem-output contract, such as waived Apollo restoration entries. |

Add `catalogue_evidence_status` and optional
`catalogue_evidence_warning` to `EntryMeta` and catalogue CLI JSON. Evidence
state never changes identity or selection.

The Download Center subtitle contract is:

- reviewed + ready/stale: render reviewed purpose and curated route labels;
- pending: `Loading output details…`;
- unavailable: `Output details unavailable`;
- waived/not applicable: a restoration/not-applicable subtitle, never raw;
- raw after usable evidence or for a genuine unknown: `Raw outputs` plus any
  observed native names.

Stale reviewed evidence may keep its curated subtitle and expose the warning
through row detail/tooltip and diagnostics.

## Refresh and Notifications

The Preferences `Refresh catalogue cache` action performs two phases:

1. Refresh and publish the source catalogue snapshot.
2. Queue conditional evidence revalidation for every current config URL.

The source refresh must not block until more than one hundred configs finish.
Its immediate feedback may say that the catalogue was refreshed and output
details are updating. Cache workers notify incrementally, and Download Center
rows update in place without changing scroll position, checks, or canonical
selection. Completion logs aggregate ready, raw, pending, unavailable, and
stale counts. Fetch and parse failures are logged with exact model ID, URL,
error type, and message, but never response bodies.

Aggregate batch events are debug-level. Per-entry success/revalidation events
are trace-level; failures and semantic drift are warnings. Subscriber failures
must be logged rather than silently swallowed.

## Current Catalogue Revision

The reviewed implementation target is the post-deduplication catalogue
observed on 2026-08-27:

- 485 current catalogue identities;
- 483 current reviewed stem declarations;
- two current Apollo stem waivers;
- 514 current reviewed contexts;
- zero unexplained raw current identities;
- 1,237 current stem-semantics reference rows;
- two retained retired identities;
- 487 total unified model records and 485 total semantic declarations when
  the retired records are included.

Add this current record:

```text
ID: mdx:mbr_invert_clean_becruily
Display: MelBand Roformer — Invert Clean · Becruily
Intent: vocals
Native signature: Vocals
Logical primary: vocal.vocals
Derived complement: mix.instrumental
Exact config training.instruments: Vocals, Other
Exact config target_instrument: Vocals
```

The runtime native signature is the single configured target (`Vocals`), not
the training-source list. Preserve the existing MDX-C target-model route rules.

Retain these exact installed-model records as `retired`:

```text
mdx:mbr_guitar_becruily
mdx:mbr_inst_becruily
```

They retain display, stems, config evidence, and runtime resolution but do not
count toward current catalogue coverage or Download Center membership.

Do not change the reviewed semantics for these apparent drifts; correct the
evidence precedence instead:

```text
mdx:mbr_guitar_becruily
mdx:mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956
mdx:dereverb-echo_mel_band_roformer_sdr_10.0169
```

All 24 current Demucs catalogue identities and their native signatures, plus
the exact VR BVE declaration, move into the unified current records so runtime
and generator no longer rely on generator-only overlays.

## Generator and Publication Contract

`scripts/generate_models_catalogue.py` remains the only public maintenance
command. It reads one collected post-deduplication snapshot and the unified
manifest, then validates all outputs before any replacement.

The generator does not invent reviewed decisions. It may normalize and update
machine-derived `catalogue_evidence` and `config_evidence` only after every
current ID already has an explicit reviewed declaration or waiver. New IDs,
removed current IDs, reappearing retired IDs, semantic config drift, exact
display collisions, route collisions, or missing evidence fail with
model-specific diagnostics and require a human edit.

Write mode atomically publishes the normalized whole manifest and generated
Markdown/TSV artifacts only after strict validation succeeds. Check and summary
modes write neither repository files nor caches. A degraded snapshot cannot be
mixed with an older manifest or published using `--allow-degraded` when it
would produce incomplete reviewed coverage.

The generated review artifacts continue to cover basename, canonical ID,
display, catalogue provenance, native signature, curated roles, logical
primary/secondary, pair, status, and evidence. Retired records are validated
but excluded from current-catalogue TSV rows; a separate summary reports them.

## Verification Requirements

- Strictly test every root, role, pair, model, evidence, config, stem, and
  runtime-contract field, including duplicate JSON keys and cross-references.
- Prove old-three-manifest to new-one-manifest view parity using frozen test
  fixtures before deleting the old files.
- Test atomic all-or-nothing loader failure and raw/fallback behavior.
- Test exact identity parity across runtime, generator, UI, CLI, all 24 Demucs
  IDs, and the reviewed VR BVE record.
- Test tuple-bearing YAML and unsafe Python-tag rejection.
- Test cache legacy reads; schema-2 writes; conditional 200 and 304; same-
  semantics digest drift; semantic drift; stale last-known-good preservation;
  cold failures; retries; concurrent writes; and atomic-write failures.
- Test the three exact evidence-precedence regressions, the new Invert Clean
  record, installed retired records, and retired/current coverage rules.
- Test every Download Center subtitle state, incremental row refresh, preserved
  selection/check state, and Preferences refresh feedback.
- Test human CLI and JSON evidence parity without polluting machine-readable
  stdout.
- Require the reviewed current counts above, zero accidental normalized
  display/route collisions, and zero unexplained raw current identities.
- Run focused unit tests, private Xvfb GTK coverage, generator online refresh
  and warm/cold offline checks, scoped Ruff and formatting, project-wide
  basedpyright, the complete unit suite, and `git diff --check`.
