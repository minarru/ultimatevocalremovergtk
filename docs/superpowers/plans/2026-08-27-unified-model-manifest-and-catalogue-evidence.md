# Unified Model Manifest and Catalogue Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace three bundled model authorities with one strict manifest, fix catalogue evidence parsing and identity drift, expose accurate evidence states, and republish all 485 current catalogue entries without unexplained raw-output rows.

**Architecture:** `bundled/model_manifest.json` is loaded atomically by a modular `core/model_manifest/` package and projected through compatibility facades. A shared family-aware catalogue identity function reconciles bundled exact evidence with a schema-2 last-known-good online validation cache. Semantic review status and evidence availability remain separate through core, UI, CLI, and generator surfaces.

**Tech Stack:** Python 3.12 compatibility, frozen dataclasses and mapping proxies, strict JSON, restricted PyYAML loading, urllib conditional requests, atomic JSON/text stores, threaded catalogue workers, GTK4/libadwaita, stdlib `unittest`, scoped Ruff, basedpyright.

**Spec:** [docs/superpowers/specs/2026-08-27-unified-model-manifest-and-catalogue-evidence-design.md](../specs/2026-08-27-unified-model-manifest-and-catalogue-evidence-design.md)

## Global Constraints

- Preserve exact canonical `family:basename` identity, native backend stem
  keys, artifact/config names, execution metadata, eligibility, settings, and
  saved selections.
- Treat display aliases, reviewed roles, intent, lifecycle, and runtime
  contracts as checked-in reviewed decisions. Never infer them from an unknown
  label or mutate them from online data.
- Use exact family-aware identity and exact config association only. No fuzzy,
  substring, author-derived, or display-to-identity matching.
- Preserve usable bundled or cached evidence across network/revalidation
  failures. A missing response is not a signature mismatch.
- Keep `StemReviewStatus` independent from `CatalogueEvidenceState`.
- Invalid unified bundled data fails atomically; do not publish partial views.
- Use `core.model_data.load_mdx_c_config_data` for MDX-C config bytes. Do not
  introduce a second YAML loader.
- Do not hand-edit generated catalogue Markdown or TSVs. Change reviewed input
  and rendering code, then regenerate them together.
- Use stdlib `unittest`, scoped Ruff/format checks, basedpyright, and the
  repository Xvfb flow. Do not run unrestricted Ruff fixes or bulk formatting.
- Stage by explicit paths and inspect `git diff --cached` before each commit.
  Do not stage settings, caches, logs, weights, runtime registries, or temporary
  files. Do not push or merge unless separately requested.

## Reviewed End-State Contract

- one bundled `model_manifest.json`, schema version 1;
- no bundled display, stem, or MDX-runtime manifest files remaining;
- 487 unified records: 485 current and two retired;
- 485 semantic declarations total, with 483 current declarations and two
  current Apollo waivers;
- 514 current reviewed contexts and 1,237 current semantic-reference rows;
- zero unexplained raw current IDs and zero accidental normalized collisions;
- all 24 Demucs catalogue identities and the VR BVE declaration resolved from
  the same runtime manifest;
- `mdx:mbr_invert_clean_becruily` current and reviewed;
- `mdx:mbr_guitar_becruily` and `mdx:mbr_inst_becruily` retained as retired;
- cache schema 2 writes with last-known-good preservation and conditional
  revalidation; and
- fresh-online, matching warm-offline, and bundled cold-offline presentation
  and reviewed semantics parity.

---

## Task 1: Freeze legacy view parity and define the unified schema

**Files:**

- Create: `core/model_manifest/__init__.py`
- Create: `core/model_manifest/schema.py`
- Create: `core/model_manifest/loader.py`
- Create: `tests/fixtures/model_manifest/legacy_display.json`
- Create: `tests/fixtures/model_manifest/legacy_stems.json`
- Create: `tests/fixtures/model_manifest/legacy_runtime.json`
- Create: `tests/test_model_manifest.py`
- Reference: `core/model_naming.py`
- Reference: `core/model_stem_manifest.py`
- Reference: `core/mdx_runtime_contract.py`

- [ ] Copy the current three bundled documents into deliberately small frozen
  test fixtures that jointly exercise: an author alias, a display-only waiver,
  a reviewed stem declaration, an Apollo waiver, a derived route, a retired
  candidate, config evidence, and an MDX runtime contract. Fixtures are test
  inputs, not runtime fallbacks.

- [ ] Write failing tests for `load_model_manifest_document(document)` and
  `load_model_manifest(path=...)` covering:

  - exact schema version 1 and closed root/record/nested objects;
  - duplicate-key rejection at every JSON depth;
  - exact canonical model IDs and `current|retired` lifecycle;
  - exactly one of `stem_semantics|stem_waiver`;
  - optional independent `display_alias|display_waivers`;
  - author alias normalization and duplicate case-folded token rejection;
  - existing role, pair, context, output, dependency, default-selection, and
    logical-primary/secondary constraints;
  - exact catalogue evidence and 64-character lowercase config digest fields;
  - config source, config-name, role, pair, and output cross-references;
  - MDX-only runtime contracts and existing backend cardinality rules;
  - one all-or-nothing failure diagnostic with no partial public views; and
  - recursively immutable returned mappings and tuples.

- [ ] Run the new tests and confirm import/API failures:

  ```bash
  .venv/bin/python -m unittest tests.test_model_manifest -v
  ```

- [ ] Implement frozen schema value objects and path-aware
  `ModelManifestError` diagnostics in `schema.py`. Move reusable validation
  primitives instead of importing private validators cyclically from the old
  loaders.

- [ ] Implement one cached loader in `loader.py`. Publish a
  `ModelManifestRegistry` only after every section validates. Add an explicit
  cache-reset helper for tests and one critical log event on bundled-load
  failure.

- [ ] Expose only stable read-only types and loader functions from
  `core/model_manifest/__init__.py`; do not expose the raw mutable JSON object.

- [ ] Add a test-only adapter that converts the three frozen legacy fixtures
  into the new document and assert presentation, stem, and runtime view parity.
  The adapter must not be imported by production code.

- [ ] Re-run the focused tests:

  ```bash
  .venv/bin/python -m unittest tests.test_model_manifest -v
  ```

- [ ] Commit the schema and loader if task commits are desired:

  ```bash
  git add core/model_manifest tests/fixtures/model_manifest tests/test_model_manifest.py
  git diff --cached --check
  git commit -m "refactor(models): define unified manifest schema"
  ```

---

## Task 2: Build the unified bundled manifest and preserve public adapters

**Files:**

- Create: `bundled/model_manifest.json`
- Create: `core/model_manifest/presentation.py`
- Create: `core/model_manifest/stems.py`
- Create: `core/model_manifest/runtime.py`
- Modify: `core/model_naming.py`
- Modify: `core/model_stem_manifest.py`
- Modify: `core/mdx_runtime_contract.py`
- Modify: `tests/test_model_manifest.py`
- Modify: `tests/test_model_naming.py`
- Modify: `tests/test_model_stem_manifest.py`
- Modify: `tests/test_mdx_runtime_contract.py`

- [ ] Write failing adapter-parity tests that load the current production
  manifests and a generated unified candidate, then compare:

  - all 202 exact display aliases, 11 author aliases, and eight display waiver
    records;
  - all current roles, four pairs, 484 legacy stem declarations, and two stem
    waivers; and
  - all 29 MDX runtime contracts, config evidence records, and artifact
    evidence fields.

- [ ] Add negative tests proving that a broken presentation section prevents
  stem/runtime publication and vice versa.

- [ ] Implement the three domain views over `ModelManifestRegistry`:

  ```python
  def presentation_registry() -> PresentationRegistry: ...
  def stem_semantics_registry() -> StemSemanticsRegistry: ...
  def mdx_runtime_registry() -> MdxRuntimeContractRegistry: ...
  ```

  Runtime contracts must reference model-level semantic and config evidence;
  do not retain duplicated signature/config objects in memory.

- [ ] Change `load_model_display_manifest`, `load_bundled_stem_semantics`,
  `load_stem_manifest`, `load_mdx_runtime_contracts`, their documented path
  constants, and exact resolve/reconcile helpers into thin compatibility
  facades. Preserve their current return shapes and public call signatures for
  existing consumers during this task.

- [ ] Construct `bundled/model_manifest.json` from the current three documents
  with deterministically sorted canonical model IDs and stable field ordering.
  Validate it through the production loader, then run the parity tests before
  making current-catalogue amendments.

- [ ] Run the focused legacy and unified suites:

  ```bash
  .venv/bin/python -m unittest \
    tests.test_model_manifest \
    tests.test_model_naming \
    tests.test_model_stem_manifest \
    tests.test_mdx_runtime_contract -v
  ```

- [ ] Commit the unified data and compatibility projections if desired. Keep
  the old files temporarily for parity until Task 9:

  ```bash
  git add bundled/model_manifest.json core/model_manifest \
    core/model_naming.py core/model_stem_manifest.py core/mdx_runtime_contract.py \
    tests/test_model_manifest.py tests/test_model_naming.py \
    tests/test_model_stem_manifest.py tests/test_mdx_runtime_contract.py
  git diff --cached --check
  git commit -m "refactor(models): unify bundled model metadata"
  ```

---

## Task 3: Share exact catalogue identity across runtime and tooling

**Files:**

- Create: `core/catalogue_identity.py`
- Modify: `core/model_catalogue.py`
- Modify: `core/catalog_sources.py`
- Modify: `scripts/catalogue/collect.py`
- Modify: `scripts/catalogue/stem_audit.py`
- Modify: `tests/test_model_identity_contracts.py`
- Modify: `tests/test_catalog_sources.py`
- Modify: `tests/test_generate_models_catalogue.py`
- Modify: `tests/test_catalogue_stem_audit.py`

- [ ] Write failing table-driven tests feeding the same exact row through the
  runtime merge, `ModelCatalogueService`, generator collection, and stem audit.
  Assert one canonical ID for VR, MDX classic, MDX-C, Apollo, and all 24 Demucs
  catalogue identities, including hash-named Demucs artifacts.

- [ ] Add regression tests that reject multiple YAMLs, multiple primary
  artifacts, a declared primary outside the validated file mapping, invalid ID
  components, and cross-family label collisions.

- [ ] Move the current `catalogue_presentation_id` implementation into
  `core/catalogue_identity.py` with a frontend-neutral name and signature:

  ```python
  def catalogue_model_id(
      family: str,
      selection: str,
      raw: object,
      meta: object,
  ) -> str | None: ...
  ```

- [ ] Re-export it as `catalogue_presentation_id` from
  `core/model_catalogue.py` for compatibility. Replace
  `core/catalog_sources.py::_catalogue_model_id` and the generator/audit copies
  with the shared call.

- [ ] Make association paths consume family-scoped `meta_by_family` or
  `catalogue_entry_meta`. Keep the flat `catalogue_meta` only where a legacy
  caller needs a presentation map; do not use it for exact identity.

- [ ] Run focused tests:

  ```bash
  .venv/bin/python -m unittest \
    tests.test_model_identity_contracts \
    tests.test_catalog_sources \
    tests.test_generate_models_catalogue \
    tests.test_catalogue_stem_audit -v
  ```

- [ ] Commit if desired:

  ```bash
  git add core/catalogue_identity.py core/model_catalogue.py core/catalog_sources.py \
    scripts/catalogue/collect.py scripts/catalogue/stem_audit.py \
    tests/test_model_identity_contracts.py tests/test_catalog_sources.py \
    tests/test_generate_models_catalogue.py tests/test_catalogue_stem_audit.py
  git diff --cached --check
  git commit -m "fix(models): share exact catalogue identity"
  ```

---

## Task 4: Upgrade the validation cache and use the restricted YAML parser

**Files:**

- Modify: `core/catalogue_stem_cache.py`
- Modify: `core/mdx_config_fetch.py`
- Modify: `core/model_data.py`
- Modify: `tests/test_catalogue_stem_cache.py`
- Modify: `tests/test_core_model_data.py`

- [ ] Write failing parser tests with a representative `!!python/tuple`
  config and an unsafe `!!python/object/apply` payload. Require the first to
  produce exact `training.instruments`/`target_instrument` and the second to
  raise without constructing an object.

- [ ] Write failing cache tests for:

  - read-only loading of the current implicit schema;
  - schema-2 normalization on the next successful mutation;
  - exact URL normalization;
  - fresh success and fresh cold-failure TTLs;
  - conditional request headers from ETag and Last-Modified;
  - HTTP 304 preserving body evidence while advancing `checked_at`;
  - HTTP 200 replacing evidence only after size, parse, and digest checks;
  - changed bytes with unchanged fields versus changed semantic fields;
  - failed revalidation preserving usable evidence and validators while
    recording structured `last_error`;
  - a cold failure returning no usable evidence;
  - manual-force retry bypassing success and failure TTLs;
  - concurrent updates preserving every entry;
  - atomic-write failure preserving the prior file; and
  - no writes under a read-only access policy.

- [ ] Replace `parse_stems_from_yaml_bytes` internals with
  `load_mdx_c_config_data`; retain the small extraction function and reject
  non-mapping/training-less/empty-instrument documents explicitly.

- [ ] Introduce immutable cache result/error objects carrying stems, target,
  digest, validators, timestamps, usable/stale state, and warning. Read legacy
  `ok` records but write only root `schema_version: 2` plus normalized entries.

- [ ] Extend the fetch path to build `urllib.request.Request` with conditional
  headers. Treat 304 as a successful validation result, not an exception path.
  Keep the two-megabyte limit.

- [ ] Replace swallowed worker exceptions with structured failure storage and
  warning/debug events. Never log response bodies.

- [ ] Preserve incremental subscriber notification, priority promotion, and
  shutdown behavior. Add batch aggregate logs and trace-only per-entry success
  logs.

- [ ] Run focused tests:

  ```bash
  .venv/bin/python -m unittest \
    tests.test_core_model_data \
    tests.test_catalogue_stem_cache -v
  ```

- [ ] Commit if desired:

  ```bash
  git add core/catalogue_stem_cache.py core/mdx_config_fetch.py core/model_data.py \
    tests/test_catalogue_stem_cache.py tests/test_core_model_data.py
  git diff --cached --check
  git commit -m "fix(catalogue): preserve validated config evidence"
  ```

---

## Task 5: Reconcile exact evidence without lower-authority overrides

**Files:**

- Modify: `core/catalogue_types.py`
- Modify: `core/catalog_sources.py`
- Modify: `core/downloads.py`
- Modify: `core/model_stem_semantics.py`
- Modify: `core/model_manifest/stems.py`
- Modify: `core/model_manifest/runtime.py`
- Modify: `tests/test_catalog_sources.py`
- Modify: `tests/test_catalog_stem_merge.py`
- Modify: `tests/test_download_center_stem_refresh.py`
- Modify: `tests/test_mdx_runtime_contract.py`

- [ ] Add failing tests for an independent `CatalogueEvidenceState` enum with
  `ready`, `pending`, `unavailable`, `stale`, and `not_applicable`. Assert that
  it does not alter `StemReviewStatus` or identity.

- [ ] Extend `EntryMeta` with:

  ```python
  catalogue_evidence_status: CatalogueEvidenceState
  catalogue_evidence_warning: str = ""
  ```

  Provide safe defaults so unrelated hand-constructed test metadata remains
  source-compatible.

- [ ] Write exact regression fixtures for:

  - `mdx:mbr_guitar_becruily`: exact YAML `Guitar|Other`, target `Guitar`,
    despite a lower summary label of Instrumental;
  - `mdx:mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956`: exact associated
    config `Vocals|Instrumental`, target `Vocals`, despite alias metadata using
    karaoke/other; and
  - `mdx:dereverb-echo_mel_band_roformer_sdr_10.0169`: exact config
    `dry|No dry`, despite lower metadata using dry/other.

  Assert all three stay reviewed and retain current route semantics.

- [ ] Implement one reconciliation function that applies the spec precedence:
  live exact config, bundled exact config, exact non-config family evidence,
  then audit-only hints. Make `with_catalogue_config_evidence`, `_build_meta`,
  and `DownloadManager.apply_catalogue_stem_cache` call it.

- [ ] Treat missing or failed online evidence as pending/unavailable/stale,
  never as a semantic mismatch. Treat a successfully observed signature or
  target disagreement as raw with a model-specific warning.

- [ ] Move the generator-only Demucs signature overlay and exact VR BVE
  supplement into unified model records. Assert runtime, Download Center, and
  generator projections agree for those IDs.

- [ ] Preserve strict MDX runtime digest checks. A runtime-contract digest or
  parsed-field mismatch remains raw even if ordinary catalogue evidence would
  accept a same-semantics digest drift.

- [ ] Run focused tests:

  ```bash
  .venv/bin/python -m unittest \
    tests.test_catalog_sources \
    tests.test_catalog_stem_merge \
    tests.test_download_center_stem_refresh \
    tests.test_mdx_runtime_contract -v
  ```

- [ ] Commit if desired:

  ```bash
  git add core/catalogue_types.py core/catalog_sources.py core/downloads.py \
    core/model_stem_semantics.py core/model_manifest/stems.py \
    core/model_manifest/runtime.py tests/test_catalog_sources.py \
    tests/test_catalog_stem_merge.py tests/test_download_center_stem_refresh.py \
    tests/test_mdx_runtime_contract.py
  git diff --cached --check
  git commit -m "fix(catalogue): reconcile exact model evidence"
  ```

---

## Task 6: Render honest Download Center states and refresh incrementally

**Files:**

- Modify: `ui/download_center.py`
- Modify: `ui/preferences.py`
- Modify: `core/downloads.py`
- Modify: `tests/test_download_center_stem_refresh.py`
- Modify: `tests/test_download_center_dedupe_refresh.py`
- Modify: `tests/test_preferences_catalogue_refresh.py`
- Modify: `tests/test_catalogue_coordinator.py`

- [ ] Write failing subtitle tests for:

  ```text
  reviewed + ready       -> reviewed purpose and curated routes
  reviewed + stale       -> reviewed routes, with warning retained
  no evidence + pending  -> Loading output details…
  no evidence + failure  -> Output details unavailable
  Apollo waiver          -> restoration/output details not applicable
  observed mismatch      -> Raw outputs · followed by observed native names
  genuine unknown        -> Raw outputs, optionally followed by observed names
  ```

- [ ] Add GTK-level tests that transition one existing row through pending to
  ready and pending to unavailable without rebuilding the list. Assert scroll
  position, checked state, and canonical selection remain unchanged.

- [ ] Make visible-row priority scheduling operate on family-scoped entries and
  exact config URLs. Track queued/in-flight state so pending is observable
  before a response arrives.

- [ ] Extend Preferences refresh into two phases: source refresh publishes
  immediately, then a force/conditional evidence batch starts. Update feedback
  to distinguish “catalogue refreshed; output details updating” from final
  aggregate failures. Do not block the Preferences worker on the full batch.

- [ ] Add an explicit force-revalidation API instead of deleting the cache.
  Manual refresh must retry failures and preserve last-known-good entries.

- [ ] Log batch start/completion and reviewed/raw/waived/pending/unavailable/
  stale counts. Log subscriber exceptions. Keep per-entry successes trace-only.

- [ ] Run non-rendering unit tests:

  ```bash
  .venv/bin/python -m unittest \
    tests.test_download_center_stem_refresh \
    tests.test_download_center_dedupe_refresh \
    tests.test_preferences_catalogue_refresh \
    tests.test_catalogue_coordinator -v
  ```

- [ ] Run GTK tests with the repository's isolated Xvfb flow:

  ```bash
  GSK_RENDERER=cairo xvfb-run -a .venv/bin/python -m unittest \
    tests.test_download_center_stem_refresh \
    tests.test_preferences_catalogue_refresh -v
  ```

- [ ] Commit if desired:

  ```bash
  git add ui/download_center.py ui/preferences.py core/downloads.py \
    tests/test_download_center_stem_refresh.py \
    tests/test_download_center_dedupe_refresh.py \
    tests/test_preferences_catalogue_refresh.py tests/test_catalogue_coordinator.py
  git diff --cached --check
  git commit -m "fix(ui): distinguish catalogue evidence states"
  ```

---

## Task 7: Expose evidence state consistently in CLI and JSON

**Files:**

- Modify: `core/model_catalogue.py`
- Modify: `cli/discovery.py`
- Modify: `tests/test_cli_list_models.py`
- Modify: `tests/test_model_identity_contracts.py`

- [ ] Write failing tests for `uvr models list --all-known` human and JSON
  projections. Require exact `catalogue_evidence_status` and optional
  `catalogue_evidence_warning`, alongside unchanged canonical ID, backend
  fields, and `stem_semantics_status`.

- [ ] Assert JSON mode emits exactly one JSON document on stdout even when
  evidence warnings occur; diagnostics go to stderr/logging.

- [ ] Extend `ModelCatalogueRecord` or its detail projection with the evidence
  fields from family-scoped `EntryMeta`. Avoid fetching or parsing configs from
  the CLI rendering path.

- [ ] Render short human evidence text only where it disambiguates pending,
  unavailable, stale, or mismatch state. Do not replace curated stem labels
  with backend names in human output.

- [ ] Run focused tests:

  ```bash
  .venv/bin/python -m unittest \
    tests.test_cli_list_models \
    tests.test_model_identity_contracts -v
  ```

- [ ] Commit if desired:

  ```bash
  git add core/model_catalogue.py cli/discovery.py \
    tests/test_cli_list_models.py tests/test_model_identity_contracts.py
  git diff --cached --check
  git commit -m "feat(cli): report catalogue evidence state"
  ```

---

## Task 8: Review the current upstream delta in the unified manifest

**Files:**

- Modify: `bundled/model_manifest.json`
- Modify: `tests/test_model_manifest.py`
- Modify: `tests/test_model_stem_semantics.py`
- Modify: `tests/test_mdx_runtime_contract.py`
- Create: `tests/fixtures/catalogue/current_model_ids.txt`

- [ ] Add a failing current-snapshot fixture test requiring exactly 485 sorted
  post-deduplication canonical IDs. Make fixture review explicit; do not derive
  expected IDs from the manifest under test.

- [ ] Add `mdx:mbr_invert_clean_becruily` as `current` with:

  - display `MelBand Roformer — Invert Clean · Becruily`;
  - intent `vocals`;
  - runtime native signature `Vocals`;
  - full-mix logical primary `vocal.vocals`;
  - derived `mix.instrumental` complement;
  - exact source label/artifact/config provenance; and
  - config evidence parsed as training `Vocals|Other`, target `Vocals`.

- [ ] Add tests proving the training list does not incorrectly make `Other` a
  native target-model output.

- [ ] Mark `mdx:mbr_guitar_becruily` and `mdx:mbr_inst_becruily` as `retired`.
  Assert installed resolution retains their display and routes while current
  coverage and Download Center exclude them.

- [ ] Pin all 24 Demucs exact identities/signatures and the exact VR BVE record
  in unified-manifest tests. Remove any expectation that a generator-only
  overlay supplies them.

- [ ] Assert current/retired counts, 483 current semantics, two current Apollo
  waivers, 514 current contexts, 485 total semantic declarations including
  retired records, four pairs, and zero unused roles/collisions.

- [ ] Run focused tests:

  ```bash
  .venv/bin/python -m unittest \
    tests.test_model_manifest \
    tests.test_model_stem_semantics \
    tests.test_mdx_runtime_contract -v
  ```

- [ ] Commit reviewed data if desired:

  ```bash
  git add bundled/model_manifest.json tests/fixtures/catalogue/current_model_ids.txt \
    tests/test_model_manifest.py tests/test_model_stem_semantics.py \
    tests/test_mdx_runtime_contract.py
  git diff --cached --check
  git commit -m "data(models): review current catalogue semantics"
  ```

---

## Task 9: Make the unified generator validate and publish one snapshot

**Files:**

- Modify: `scripts/generate_models_catalogue.py`
- Modify: `scripts/catalogue/collect.py`
- Modify: `scripts/catalogue/stem_audit.py`
- Modify: `scripts/catalogue/render.py`
- Modify: `scripts/catalogue/__init__.py`
- Modify: `tests/test_generate_models_catalogue.py`
- Modify: `tests/test_catalogue_stem_audit.py`
- Modify: `tests/test_catalog_sources.py`

- [ ] Write failing generator tests for:

  - one collection pass feeding manifest validation and every rendered output;
  - a new unreviewed current ID;
  - a missing current ID that must be explicitly retired;
  - a retired ID reappearing current;
  - config digest drift with unchanged parsed semantics;
  - config signature/target drift;
  - display and route collisions;
  - missing required evidence;
  - degraded acquisition refusing manifest publication;
  - `--check` and `--summary` performing zero repository/cache writes; and
  - a failure during candidate rendering/replacement leaving all prior files
    intact.

- [ ] Add a normalized manifest candidate to the publication bundle. Construct
  it by combining existing human-reviewed presentation/stem/runtime fields with
  exact collected catalogue/config evidence. Refuse to create semantic fields
  for a new ID or delete a reviewed record automatically.

- [ ] Validate the full in-memory candidate and every rendered document before
  the first atomic replacement. Preserve exit codes `0`, `1`, `2`, and `130`.

- [ ] Remove generator-only Demucs and VR signature supplements after unified
  records cover them. Retain source summaries only as diagnostics.

- [ ] Extend `--summary` with current/retired counts, evidence states, same-
  semantics digest drift, semantic mismatches, lifecycle drift, and reference
  drift. Keep the existing confidence-audit argument surface unchanged.

- [ ] Make `--check` compare `bundled/model_manifest.json` as well as catalogue,
  IR, intent, display, and stem-reference outputs. Write mode publishes the
  manifest through `write_json_atomic` only after validation.

- [ ] Run generator tests:

  ```bash
  .venv/bin/python -m unittest \
    tests.test_generate_models_catalogue \
    tests.test_catalogue_stem_audit -v
  ```

- [ ] Run a warm-offline read-only check and verify no changed files:

  ```bash
  git status --short
  .venv/bin/python scripts/generate_models_catalogue.py --check --offline
  git status --short
  ```

- [ ] Commit if desired:

  ```bash
  git add scripts/generate_models_catalogue.py scripts/catalogue/__init__.py \
    scripts/catalogue/collect.py scripts/catalogue/stem_audit.py \
    scripts/catalogue/render.py \
    tests/test_generate_models_catalogue.py tests/test_catalogue_stem_audit.py
  git diff --cached --check
  git commit -m "refactor(catalogue): publish unified model evidence"
  ```

---

## Task 10: Remove obsolete bundled authorities and update documentation

**Files:**

- Delete: `bundled/model_display_manifest.json`
- Delete: `bundled/model_stem_manifest.json`
- Delete: `bundled/model_runtime_stem_contracts.json`
- Modify: `CLAUDE.md`
- Modify: `docs/models-catalogue.md` through the generator
- Modify: `docs/model_intent_reference.tsv` through the generator
- Modify: `docs/model_display_reference.tsv` through the generator
- Modify: `docs/model_stem_semantics_reference.tsv` through the generator
- Modify: `docs/superpowers/specs/2026-08-22-model-display-projection-refresh-design.md`
- Modify: `docs/superpowers/specs/2026-08-24-catalogue-wide-stem-semantics-design.md`
- Modify: `tests/test_model_manifest.py`
- Modify: `tests/test_generate_models_catalogue.py`

- [ ] Add failing repository-structure tests proving production code and docs
  no longer reference the three obsolete bundled filenames, except historical
  supersession notes and frozen test fixtures.

- [ ] Remove the old files and any redundant JSON loading/validation code from
  the three compatibility facades. Keep their public Python APIs until a
  separately reviewed cleanup removes them.

- [ ] Replace Task 2's temporary direct-production-file parity assertion with
  the frozen legacy-fixture parity assertion before deleting the old files.
  The final test suite must not require an obsolete runtime file to exist.

- [ ] Add supersession notes to the older display and stem designs pointing to
  the 2026-08-27 design. Preserve those documents as historical records.

- [ ] Update `CLAUDE.md` bundled-data, display, stem, runtime-contract,
  generator, and cache guidance to name the unified manifest and evidence-state
  split.

- [ ] Regenerate from a reviewed live snapshot:

  ```bash
  .venv/bin/python scripts/generate_models_catalogue.py --refresh
  ```

- [ ] Require generated results of 485 current models, 483 reviewed semantic
  declarations, two Apollo waivers, 514 current contexts, 1,237 stem-reference
  rows, zero unexplained raw IDs, zero unreviewed display flags, and zero
  normalized collisions.

- [ ] Run read-only consistency immediately after generation:

  ```bash
  .venv/bin/python scripts/generate_models_catalogue.py --check --offline
  ```

- [ ] Commit removed authorities, docs, and generated outputs if desired:

  ```bash
  git add -A -- bundled/model_display_manifest.json bundled/model_stem_manifest.json \
    bundled/model_runtime_stem_contracts.json bundled/model_manifest.json \
    CLAUDE.md docs/models-catalogue.md docs/model_intent_reference.tsv \
    docs/model_display_reference.tsv docs/model_stem_semantics_reference.tsv \
    docs/superpowers/specs/2026-08-22-model-display-projection-refresh-design.md \
    docs/superpowers/specs/2026-08-24-catalogue-wide-stem-semantics-design.md \
    tests/test_model_manifest.py tests/test_generate_models_catalogue.py
  git diff --cached --name-status
  git diff --cached --check
  git commit -m "docs(models): publish unified catalogue review"
  ```

---

## Task 11: Run end-to-end regression and host-realistic UI verification

**Files:**

- Modify only plan-scoped code/tests if verification exposes a defect.
- Do not modify runtime cache/settings/model files during repository staging.

- [ ] Run the focused core, UI, CLI, and generator suite:

  ```bash
  .venv/bin/python -m unittest \
    tests.test_model_manifest \
    tests.test_model_naming \
    tests.test_model_stem_manifest \
    tests.test_model_stem_semantics \
    tests.test_mdx_runtime_contract \
    tests.test_model_identity_contracts \
    tests.test_catalog_sources \
    tests.test_catalog_stem_merge \
    tests.test_catalogue_stem_cache \
    tests.test_download_center_stem_refresh \
    tests.test_download_center_dedupe_refresh \
    tests.test_preferences_catalogue_refresh \
    tests.test_cli_list_models \
    tests.test_catalogue_stem_audit \
    tests.test_generate_models_catalogue -v
  ```

- [ ] Run GTK-sensitive suites under Xvfb and require no relevant skips:

  ```bash
  GSK_RENDERER=cairo xvfb-run -a .venv/bin/python -m unittest \
    tests.test_download_center_stem_refresh \
    tests.test_download_center_dedupe_refresh \
    tests.test_preferences_catalogue_refresh -v
  ```

- [ ] Run scoped Ruff and formatting over every touched Python file. Build the
  explicit list from Git rather than checking the whole backlog:

  ```bash
  git diff --name-only --diff-filter=ACMR | \
    awk '/\.py$/ {print}' | \
    xargs -r .venv/bin/ruff check
  git diff --name-only --diff-filter=ACMR | \
    awk '/\.py$/ {print}' | \
    xargs -r .venv/bin/ruff format --check
  ```

- [ ] Run scoped and project-wide basedpyright:

  ```bash
  .venv/bin/python -m basedpyright \
    core/model_manifest core/catalogue_identity.py core/catalogue_stem_cache.py \
    core/catalog_sources.py core/catalogue_types.py core/downloads.py \
    core/model_catalogue.py core/model_naming.py core/model_stem_manifest.py \
    core/mdx_runtime_contract.py cli/discovery.py ui/download_center.py \
    ui/preferences.py scripts/generate_models_catalogue.py scripts/catalogue
  .venv/bin/python -m basedpyright
  ```

- [ ] Run the complete suite under the CI-equivalent display flow:

  ```bash
  GSK_RENDERER=cairo xvfb-run -a \
    .venv/bin/python -m unittest discover -s tests -t . -v
  ```

- [ ] Run final generator and whitespace checks:

  ```bash
  .venv/bin/python scripts/generate_models_catalogue.py --check --offline
  git diff --check
  ```

- [ ] With explicit host-GUI approval, launch the real-cache app using the
  existing verbose trace command and inspect Download Center after manual
  refresh. Require:

  - no tuple-constructor YAML warnings;
  - no unexplained `Raw outputs` among the 485 current rows;
  - pending/unavailable/stale rows use their specific subtitle;
  - Apollo rows are not described as raw;
  - all 24 Demucs rows use reviewed semantics;
  - conditional 304/200/failure events are visible at the intended log level;
  - no uncaught worker/subscriber exception; and
  - settings, installed models, and canonical selections remain intact.

- [ ] Inspect repository state and stage nothing unexpected:

  ```bash
  git status --short
  git diff --cached --name-status
  git diff --stat
  ```

- [ ] If verification required code fixes, return to the task that owns those
  exact files, repeat that task's focused verification, and use its explicit
  path-scoped commit command. Do not create a catch-all verification commit.

## Completion Criteria

Implementation is complete only when:

- one strict bundled file supplies presentation, stems, and MDX runtime views
  atomically, with no runtime references to the three obsolete JSON files;
- exact identity is shared across runtime and tooling, including all Demucs;
- tuple-bearing upstream configs parse safely and unsafe Python tags fail;
- exact config evidence outranks summary/alias hints in all three pinned
  regressions;
- conditional refresh preserves last-known-good evidence and exposes failures;
- Download Center, CLI, and JSON distinguish semantic state from evidence
  availability;
- current/retired/new model decisions and all reviewed counts match the
  end-state contract;
- generated artifacts are synchronized from one non-degraded snapshot;
- focused tests, Xvfb GTK tests, scoped Ruff/format, scoped and full
  basedpyright, the complete Xvfb unit suite, generator checks, and whitespace
  checks pass; and
- no cache, settings, registry, weights, logs, or unrelated files are staged,
  committed, pushed, or merged.
