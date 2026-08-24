# Catalogue-Wide Stem Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace spelling-based stem guesses with an exact, reviewed semantic projection for every current catalogue model, then use stable role IDs and canonical stem names consistently in selection, export, ensemble, catalogue, CLI, JSON, and GTK surfaces.

**Architecture:** Keep native backend output keys immutable and introduce a separate `StemRoleId` layer resolved from exact canonical model ID, complete native signature, and processing context. A bundled versioned manifest owns role names, per-model mappings, logical primaries, and ensemble pairs; unknown or signature-mismatched models stay raw and ensemble-isolated. Runtime routes carry semantic roles while retaining a read-only `concept` compatibility projection, and settings/saved ensembles make an intentional schema cutover to new namespaced pair IDs.

**Tech Stack:** Python 3.12-compatible stdlib, immutable dataclasses, versioned JSON manifest, TSV audit reference, stdlib `unittest`, GTK4/libadwaita through the private headless runner, scoped Ruff, and basedpyright.

**Spec:** [Catalogue-Wide Stem Semantics and Canonical Naming Design](../specs/2026-08-24-catalogue-wide-stem-semantics-design.md)

---

## Global Constraints

- Preserve exact native yaml/hash stem keys, canonical `family:basename` model IDs, artifacts, hashes, source order, backend `primary_stem`, backend `target_instrument`, inversion polarity, and execution metadata.
- Never derive identity from a display label. Runtime semantic resolution may use only exact canonical model ID, complete native signature, and explicit processing context.
- Do not add fuzzy, substring, filename, author, or guessed-intent matching to runtime semantics.
- Unknown custom models and signature-mismatched known models must remain raw and isolated; a declaration mismatch rejects the entire model context rather than partially mapping it.
- Keep semantic resolution per assembled model. It must not write model-specific state back into the shared `Settings` object.
- No-filter runs continue exporting all normally selected outputs. Logical primary changes ordering and positional selection only.
- Existing saved ensemble pair IDs are deliberately unsupported. Reset them with actionable warnings; do not silently translate them.
- Tests use stdlib `unittest`, never pytest. Run Ruff only on touched Python files; the full-tree Ruff backlog is not part of this change.
- Preserve the unrelated user/runtime edit to `registered_models.json` without staging, rewriting, or restoring it.
- Commit each completed task locally at its stated boundary. Do not push or merge without a separate user request.

---

### Task 1: Introduce semantic role types and a fail-closed manifest loader

**Files:**

- Create: `core/stem_roles.py`
- Create: `core/model_stem_manifest.py`
- Create: `bundled/model_stem_manifest.json`
- Modify: `core/stems.py`
- Create: `tests/test_model_stem_manifest.py`
- Modify: `tests/test_stems_typed.py`

**Interfaces:**

```python
ROLE_ID_RE = re.compile(
    r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
    r"(?:\.[a-z][a-z0-9]*(?:_[a-z0-9]+)*)+$"
)

@dataclass(frozen=True, slots=True, order=True)
class StemRoleId:
    value: str

@dataclass(frozen=True, slots=True)
class StemRoleDefinition:
    id: StemRoleId
    display: str
    filename_tag: str
    family: StemRoleFamily
    removed_of: StemRoleId | None = None

@dataclass(frozen=True, slots=True)
class SemanticStemOutput:
    native: StemId | None
    role: StemRoleId | StemLiteral
    production: StemProduction
    backend_primary: bool
    logical_primary: bool
    derived_from: tuple[StemRoleId, ...] = ()
    complement_of: StemRoleId | None = None

def resolve_model_stem_semantics(
    model_id: str,
    *,
    native_stems: Sequence[str],
    backend_primary: str = "",
    backend_target: str = "",
    context: StemProcessingContext = StemProcessingContext.FULL_MIX,
) -> ModelStemSemantics: ...
```

- [ ] **Step 1: Write failing value-object and loader tests**

Add table-driven tests covering:

- valid and invalid namespaced `StemRoleId` values;
- exact case-preserving `StemId` lookup and `StemLiteral` round trips;
- all four closed enums from the design;
- valid roles, pairs, model contexts, native outputs, derived outputs, and waivers;
- native outputs with no dependency fields and derived outputs with exactly one
  of `derived_from` or `complement_of`;
- duplicate case-folded native keys;
- duplicate normalized role displays and filename tags;
- missing role/pair references, missing logical primary, and multiple logical primaries;
- an exact-ID/signature match, an order-only signature change, a cardinality mismatch, a missing context, and an unknown model;
- explicit `vocal_split` context selection; and
- a corrupt bundled manifest producing one logged startup error plus a raw projection, while the direct validation API raises a typed `StemManifestError`.

Move `StemId` and `StemLiteral` into `core/stem_roles.py`, then re-export them from `core.stems` so existing imports remain valid. The tests must prove there is one class identity, not duplicate compatibility wrappers.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_model_stem_manifest \
  tests.test_stems_typed -v
```

Expected: failure because `core.stem_roles`, the manifest loader, and the bundled manifest do not yet exist.

- [ ] **Step 3: Implement immutable types and strict manifest parsing**

Implement `StemProcessingContext`, `StemProduction`, `StemReviewStatus`, and `StemRoleFamily` only as closed behavior enums. Keep the growing role vocabulary in JSON and validated `StemRoleId` values.

Add a `StemSemanticsRegistry` holding immutable role, pair, model, and waiver mappings. Direct loading must validate the complete document and raise `StemManifestError` with a field path. The application-facing cached loader must catch that exception once, log an error, and return an empty registry so model execution can continue with raw routes.

Seed `bundled/model_stem_manifest.json` with `schema_version: 1`, the approved canonical role definitions and pair definitions, and an empty `models` object. Catalogue completeness becomes a strict gate in Task 2 rather than a loader invariant, allowing the loader to be tested independently.

- [ ] **Step 4: Implement exact resolution and raw fallback**

Resolution must:

1. Find only `models[model_id]`.
2. Compare the complete case-folded native signature as an order-insensitive set with equal cardinality.
3. Select only the requested context.
4. Preserve actual runtime spelling in every native `StemId`.
5. Set backend-primary flags by case-insensitive native-key comparison without changing the backend value.
6. Return `StemReviewStatus.RAW` with one `StemLiteral` per actual native output on any miss or mismatch.

Use a raw diagnostic string that identifies `unknown-model`, `signature-mismatch`, or `missing-context`; include expected and actual signatures for verbose logging.

- [ ] **Step 5: Verify and commit Task 1**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_model_stem_manifest \
  tests.test_stems_typed -v
.venv/bin/ruff check core/stem_roles.py core/model_stem_manifest.py core/stems.py tests/test_model_stem_manifest.py tests/test_stems_typed.py
.venv/bin/ruff format --check core/stem_roles.py core/model_stem_manifest.py core/stems.py tests/test_model_stem_manifest.py tests/test_stems_typed.py
.venv/bin/python -m basedpyright core/stem_roles.py core/model_stem_manifest.py core/stems.py tests/test_model_stem_manifest.py tests/test_stems_typed.py
git diff --check
```

Expected: all commands pass. Then commit only Task 1 files:

```bash
git add core/stem_roles.py core/model_stem_manifest.py core/stems.py bundled/model_stem_manifest.json tests/test_model_stem_manifest.py tests/test_stems_typed.py
git commit -m "feat(stems): add semantic role manifest"
```

---

### Task 2: Build the exhaustive catalogue manifest and reference gate

**Files:**

- Modify: `bundled/model_stem_manifest.json`
- Modify: `scripts/stem_semantics_audit.py`
- Modify: `scripts/generate_models_catalogue.py`
- Modify: `scripts/catalogue/collect.py`
- Modify: `scripts/catalogue/render.py`
- Create: `docs/model_stem_semantics_reference.tsv`
- Modify: `tests/test_stem_semantics_audit.py`
- Modify: `tests/test_generate_models_catalogue.py`
- Modify: `tests/test_model_stem_manifest.py`

**New generator option:**

```text
--write-stem-semantics-reference
    Write or compare docs/model_stem_semantics_reference.tsv.
    Under --check, remain read-only and fail on drift.
```

- [ ] **Step 1: Add failing catalogue coverage and collision tests**

Pin these observed counts from the approved audit: 485 post-deduplication model IDs, 148 literal spellings, 123 case-folded backend names, 92 backend-primary names, and four complement-only names. The exact semantic reference has 1,203 data rows (454 reviewed declarations plus 31 waivers).

Add tests that require:

- every current canonical ID to have a reviewed declaration or an explicit model-level waiver;
- every declared complete native signature to match current evidence;
- one reference row per native or derived output and processing context;
- both contexts for every Vocal Splitter-eligible model;
- no unreviewed rows, duplicate context roles, missing logical primaries, dangling pair references, or normalized display/tag collisions;
- exact coverage for all contextual uses of `other`, `inst`, `instrument`, `lead`, `back`, `dry`, and `noreverb`;
- all 28 karaoke identities, both MelBand BVE identities, the VR BVE reversal, and the GiantAILAB third route;
- all eight spatial entries projecting to `Center/Side`;
- the complete canonical instrument, effects, cinematic/SFX, surround, vocal, mixture, and removal vocabulary from the spec; and
- `--check --write-stem-semantics-reference` performing zero writes.

- [ ] **Step 2: Run the strict tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_model_stem_manifest \
  tests.test_stem_semantics_audit \
  tests.test_generate_models_catalogue -v
```

Expected: failure because the manifest has no model declarations and the new reference option/file do not exist.

- [ ] **Step 3: Extend read-only collection and review tooling**

Make the catalogue collector expose exact canonical ID, complete native signature, backend primary/target, current guessed intent, structured karaoke/BV metadata, and provenance without changing catalogue membership.

Extend `scripts/stem_semantics_audit.py` to emit deterministic candidate rows for review, but never mark a candidate trusted automatically. Its strict mode must resolve every final row through the runtime loader and report:

```text
models=485 literal_names=148 normalized_names=123 primary_names=92
complement_only=4 unreviewed=0 signature_mismatches=0 collisions=0
```

Add the reference option to `scripts/generate_models_catalogue.py`. Follow the existing display-reference contract: normal write mode writes it atomically; `--check` renders in memory and compares without touching the filesystem.

- [ ] **Step 4: Populate and review all exact model declarations**

Populate `bundled/model_stem_manifest.json` by canonical ID. For every record:

- copy the complete reviewed signature;
- map every native and derived output to a role;
- declare exactly one logical primary per context;
- provide exact evidence text or a waiver reason;
- add `vocal_split` only where explicitly supported; and
- assign pair IDs only when the full declared pair is semantically valid.

Apply the approved naming decisions exactly: ordinary karaoke versus Vocal Splitter semantics, VR BVE reversal, ordinary semantics for the two MelBand BVE models, `<Target> Removed`, `Instrumental/Bleed`, `Center/Side`, `Foreground SFX/Background SFX`, expanded SCNet surround channels, concise percussion names, and full canonical instrument terminology.

Do not copy a guessed intent into trusted runtime metadata. Guessed intent remains a separate reference column for audit comparison.

- [ ] **Step 5: Generate and inspect the reference**

Run an authoritative refresh, then confirm matching warm-offline parity:

```bash
.venv/bin/python scripts/generate_models_catalogue.py \
  --refresh --write --write-display-reference \
  --write-stem-semantics-reference
.venv/bin/python scripts/generate_models_catalogue.py \
  --offline --check --write-display-reference \
  --write-stem-semantics-reference
.venv/bin/python scripts/stem_semantics_audit.py --check
```

Expected: 485 identities covered, the pinned vocabulary counts match, no strict findings remain, and warm-offline output matches the refreshed snapshot.

- [ ] **Step 6: Verify and commit Task 2**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_model_stem_manifest \
  tests.test_stem_semantics_audit \
  tests.test_generate_models_catalogue -v
.venv/bin/ruff check scripts/stem_semantics_audit.py scripts/generate_models_catalogue.py scripts/catalogue/collect.py scripts/catalogue/render.py tests/test_stem_semantics_audit.py tests/test_generate_models_catalogue.py tests/test_model_stem_manifest.py
.venv/bin/ruff format --check scripts/stem_semantics_audit.py scripts/generate_models_catalogue.py scripts/catalogue/collect.py scripts/catalogue/render.py tests/test_stem_semantics_audit.py tests/test_generate_models_catalogue.py tests/test_model_stem_manifest.py
.venv/bin/python -m basedpyright scripts/stem_semantics_audit.py scripts/generate_models_catalogue.py scripts/catalogue tests/test_stem_semantics_audit.py tests/test_generate_models_catalogue.py tests/test_model_stem_manifest.py
git diff --check
```

Expected: all commands pass. Review generated diffs to ensure model IDs, artifacts, eligibility, hashes, and backend metadata did not change. Then commit:

```bash
git add bundled/model_stem_manifest.json scripts/stem_semantics_audit.py scripts/generate_models_catalogue.py scripts/catalogue/collect.py scripts/catalogue/render.py docs/model_stem_semantics_reference.tsv tests/test_stem_semantics_audit.py tests/test_generate_models_catalogue.py tests/test_model_stem_manifest.py
git commit -m "data(stems): review catalogue stem semantics"
```

---

### Task 3: Project semantic roles into runtime routes and logical primary selection

**Files:**

- Modify: `core/stems.py`
- Modify: `core/stem_selection.py`
- Modify: `core/model_config/config.py`
- Modify: `core/model_config/base.py`
- Modify: `core/job_plan.py`
- Modify: `tests/test_stems_typed.py`
- Modify: `tests/test_model_stem_semantics.py`
- Modify: `tests/test_stem_selection.py`
- Modify: `tests/test_job_plan_native_values.py`
- Modify: `tests/test_job_plan_topology.py`

**Route cutover:**

```python
@dataclass(frozen=True, slots=True)
class StemRoute:
    native: StemId | None
    role: StemRoleId | StemLiteral
    label: str
    filename_tag: str
    kind: StemRouteKind = StemRouteKind.NATIVE
    conditional: bool = False
    selected_by_default: bool = True
    logical_primary: bool = False

    @property
    def concept(self) -> str:
        return stem_role_key(self.role)
```

- [ ] **Step 1: Write failing route and logical-primary regressions**

Add tests proving:

- `model_stem_routes()` resolves by `model.canonical_id`, full native inventory, and `StemProcessingContext`;
- route lookup retains exact native spelling while selection and ensemble identity use `StemRoleId`;
- `route.concept` is a read-only stable projection, not a second stored identity;
- an unknown ID and a known signature mismatch retain distinct raw literals and cannot match reviewed roles;
- positional `primary` selects the reviewed logical primary even when backend primary is the other native side;
- positional `secondary` selects the declared logical secondary for two-route models;
- no focus exports every default route;
- an explicit semantic focus overrides logical-primary ordering;
- a multi-route model retains existing positional fallback unless a logical secondary is declared; and
- assembling two models from one `Settings` object does not mutate `process.stem_focus`, ensemble pair, or any model setting.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_stems_typed \
  tests.test_model_stem_semantics \
  tests.test_stem_selection \
  tests.test_job_plan_native_values \
  tests.test_job_plan_topology -v
```

Expected: semantic-role and logical-primary assertions fail against `StemBucket`/backend-primary routing.

- [ ] **Step 3: Change `StemRoute` and route construction**

Make every route constructor accept a `StemRoleId | StemLiteral`. `model_stem_routes()` must call the manifest resolver once per assembled model and construct native/derived routes from the returned outputs. Keep raw route labels and tags unchanged for unknowns.

Retain `StemBucket` only as a temporary compatibility adapter for untouched callers during this task. New or edited code must not derive a reviewed semantic role through `bucket_for_model_stem()`.

Add the resolved `ModelStemSemantics` projection to assembled model config state and copy it into `ModelDescriptor`/planned routes. Do not alter `primary_stem` or `secondary_stem` fields.

- [ ] **Step 4: Apply logical primary to selection and planning**

Update `_apply_stem_focus()`, `planned_output_routes()`, and stem-selection state so positional `primary` finds `route.logical_primary`. For a declared two-route model, positional `secondary` selects the single non-primary route. Keep native-key matching for engine-side exclusivity flags and source lookup.

Selection persistence stores role IDs for semantic choices and retains the positional sentinels `primary` and `secondary`. A raw choice stores its `raw:<casefolded-native>` identity and only rematches that same model/signature.

- [ ] **Step 5: Verify and commit Task 3**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_stems_typed \
  tests.test_model_stem_semantics \
  tests.test_stem_selection \
  tests.test_job_plan_native_values \
  tests.test_job_plan_topology -v
.venv/bin/ruff check core/stems.py core/stem_selection.py core/model_config/config.py core/model_config/base.py core/job_plan.py tests/test_stems_typed.py tests/test_model_stem_semantics.py tests/test_stem_selection.py tests/test_job_plan_native_values.py tests/test_job_plan_topology.py
.venv/bin/ruff format --check core/stems.py core/stem_selection.py core/model_config/config.py core/model_config/base.py core/job_plan.py tests/test_stems_typed.py tests/test_model_stem_semantics.py tests/test_stem_selection.py tests/test_job_plan_native_values.py tests/test_job_plan_topology.py
.venv/bin/python -m basedpyright core/stem_roles.py core/model_stem_manifest.py core/stems.py core/stem_selection.py core/model_config core/job_plan.py tests/test_stems_typed.py tests/test_model_stem_semantics.py tests/test_stem_selection.py tests/test_job_plan_native_values.py tests/test_job_plan_topology.py
git diff --check
```

Expected: all commands pass. Then commit:

```bash
git add core/stems.py core/stem_selection.py core/model_config/config.py core/model_config/base.py core/job_plan.py tests/test_stems_typed.py tests/test_model_stem_semantics.py tests/test_stem_selection.py tests/test_job_plan_native_values.py tests/test_job_plan_topology.py
git commit -m "refactor(stems): route by reviewed semantic roles"
```

---

### Task 4: Preserve native engine lookup while canonicalizing export and splitter output

**Files:**

- Modify: `engines/base.py`
- Modify: `engines/stem_writer.py`
- Modify: `engines/mdx_c.py`
- Modify: `engines/mdx_c_engine.py`
- Modify: `engines/demucs_engine.py`
- Modify: `core/export_naming.py`
- Modify: `tests/test_stem_writer.py`
- Modify: `tests/test_export_stem_label.py`
- Modify: `tests/test_mdx_export_routing.py`
- Modify: `tests/test_demucs_secondary_slots.py`
- Modify: `tests/test_vocal_split_stems.py`
- Modify: `tests/test_target_other_stems.py`

- [ ] **Step 1: Add failing engine-boundary tests**

Cover these invariants with real mixed-case source dictionaries and derived outputs:

- engine source lookup always uses `route.native.raw`, never role ID, display, or filename tag;
- canonical display names appear in user progress/log text and new filenames;
- portable filename presentation changes `/` to `-` (`Drum/Bass` ->
  `Drum-Bass`, `Reverb/Echo` -> `Reverb-Echo`, `Front L/R` -> `Front L-R`)
  without changing the role display or internal tag;
- internal ensemble buffers and capture filenames use stable `filename_tag` values;
- backend primary still controls inversion and source-array polarity when logical primary differs;
- exact target/complement models write `<Target>` and `<Target> Removed`;
- multi-stem models write components plus `Residual`, without synthesized per-component complements;
- unrestricted runs still call `write_audio()` for every default route;
- zero scheduled writes for a non-empty export still raises the existing explicit error;
- ordinary karaoke full-mix and Vocal Splitter contexts produce their different approved accompaniment meanings;
- VR BVE reverses lead/backing semantics by context;
- the two MelBand BVE models use ordinary karaoke semantics; and
- GiantAILAB preserves its third route outside the karaoke-pair selection.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_stem_writer \
  tests.test_export_stem_label \
  tests.test_mdx_export_routing \
  tests.test_demucs_secondary_slots \
  tests.test_vocal_split_stems \
  tests.test_target_other_stems -v
```

Expected: failures where engines still derive export identity through `StemBucket`, raw labels, or global karaoke/BV aliases.

- [ ] **Step 3: Separate source keys, semantic routes, and output names**

Change export loops to carry the selected `StemRoute` through source lookup and writing:

```python
source_key = resolve_in_sources(sources, route.native) if route.native else None
output_label = route.label
internal_tag = route.filename_tag
```

Derived routes must declare their source/complement dependency in the manifest projection; engine code may calculate audio from those references but must not guess a semantic name from `secondary_stem`.

Update `stem_export_wav_path()` and Model Test suffix composition to take the route label/tag explicitly. Add one centralized one-way filename presentation helper in `core/export_naming.py` that changes `/` to `-` before the existing path-component sanitizer. Do not use that helper for identity and do not rename existing files on disk.

- [ ] **Step 4: Make Vocal Splitter context explicit**

When assembling the splitter model, resolve it with `StemProcessingContext.VOCAL_SPLIT`; ordinary primary and ensemble members use `FULL_MIX`. Remove global spelling-based lead/backing reinterpretation from the write path after all callers consume route semantics.

Keep Vocal Splitter eligibility exact: only models with karaoke/BV metadata and a valid reviewed `vocal_split` context may be selected.

- [ ] **Step 5: Verify and commit Task 4**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_stem_writer \
  tests.test_export_stem_label \
  tests.test_mdx_export_routing \
  tests.test_demucs_secondary_slots \
  tests.test_vocal_split_stems \
  tests.test_target_other_stems -v
.venv/bin/ruff check engines/base.py engines/stem_writer.py engines/mdx_c.py engines/mdx_c_engine.py engines/demucs_engine.py core/export_naming.py tests/test_stem_writer.py tests/test_export_stem_label.py tests/test_mdx_export_routing.py tests/test_demucs_secondary_slots.py tests/test_vocal_split_stems.py tests/test_target_other_stems.py
.venv/bin/ruff format --check engines/base.py engines/stem_writer.py engines/mdx_c.py engines/mdx_c_engine.py engines/demucs_engine.py core/export_naming.py tests/test_stem_writer.py tests/test_export_stem_label.py tests/test_mdx_export_routing.py tests/test_demucs_secondary_slots.py tests/test_vocal_split_stems.py tests/test_target_other_stems.py
.venv/bin/python -m basedpyright engines/base.py engines/stem_writer.py engines/mdx_c.py engines/mdx_c_engine.py engines/demucs_engine.py core/export_naming.py tests/test_stem_writer.py tests/test_export_stem_label.py tests/test_mdx_export_routing.py tests/test_demucs_secondary_slots.py tests/test_vocal_split_stems.py tests/test_target_other_stems.py
git diff --check
```

Expected: all commands pass. Then commit:

```bash
git add engines/base.py engines/stem_writer.py engines/mdx_c.py engines/mdx_c_engine.py engines/demucs_engine.py core/export_naming.py tests/test_stem_writer.py tests/test_export_stem_label.py tests/test_mdx_export_routing.py tests/test_demucs_secondary_slots.py tests/test_vocal_split_stems.py tests/test_target_other_stems.py
git commit -m "fix(stems): export canonical semantic names"
```

---

### Task 5: Replace the closed pair enum and cut persistence to new pair IDs

**Files:**

- Create: `core/stem_pairs.py`
- Modify: `core/stems.py`
- Modify: `core/settings/defaults.py`
- Modify: `core/settings/model.py`
- Modify: `core/settings/coerce.py`
- Modify: `core/ensemble_service.py`
- Modify: `core/ensemble_presets.py`
- Modify: `bundled/ensemble_presets/Instrumental_Balanced.json`
- Modify: `bundled/ensemble_presets/Instrumental_Clean.json`
- Modify: `bundled/ensemble_presets/Instrumental_Full.json`
- Modify: `bundled/ensemble_presets/Instrumental_Low_Resource.json`
- Modify: `bundled/ensemble_presets/Karaoke.json`
- Modify: `bundled/ensemble_presets/Vocal_Balanced.json`
- Modify: `bundled/ensemble_presets/Vocal_Clean.json`
- Modify: `bundled/ensemble_presets/Vocal_Full.json`
- Modify: `bundled/ensemble_presets/Vocal_RVC.json`
- Modify: `tests/test_core_settings.py`
- Modify: `tests/test_settings_coerce_v3.py`
- Modify: `tests/test_saved_ensembles.py`
- Modify: `tests/test_ensemble_presets.py`

**Persistence shape:**

```python
@dataclass
class EnsembleSettings:
    main_stem: str = ""

@dataclass(frozen=True, slots=True)
class StemPairDefinition:
    id: str
    display: str
    roles: tuple[StemRoleId, StemRoleId]
```

- [ ] **Step 1: Write failing settings-v5 and saved-ensemble-v2 tests**

Require:

- `SETTINGS_SCHEMA_VERSION == 5`;
- new defaults store `ensemble.main_stem == ""`;
- every pre-v5 settings payload resets the pair to empty and adds exactly one repick warning;
- no old enum value or display string is translated;
- a valid v5 namespaced pair/mode ID round-trips unchanged;
- an unknown v5 pair resets to empty with a warning;
- saved ensemble schema 2 writes a namespaced pair/mode ID atomically;
- legacy/no-version saved ensembles preserve member IDs, algorithm, and flags but clear the pair and warn;
- a legacy document cannot run until a pair is repicked and resaved; and
- all bundled curated presets declare schema 2 and valid new IDs.

- [ ] **Step 2: Run persistence tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_core_settings \
  tests.test_settings_coerce_v3 \
  tests.test_saved_ensembles \
  tests.test_ensemble_presets -v
```

Expected: failures because schema 4 and `EnsemblePair` remain in production persistence.

- [ ] **Step 3: Implement the pair registry and settings migration**

Load pair definitions from the validated semantic registry. Expose exact helpers:

```python
def stem_pair_definition(pair_id: str) -> StemPairDefinition | None: ...
def is_stem_mode(pair_id: str) -> bool: ...
def normalize_stem_pair_id(value: object) -> str: ...
```

Recognize only current manifest pair IDs plus `mode.four_stem` and `mode.multi_stem`. Empty string is the only Choose value.

Capture the source settings schema before generic coercion. If it is below 5, hard-reset `ensemble.main_stem` and append one field-specific validation warning. Preserve that migration warning when `validate_model_references()` adds its own warnings; do not let the later validation assignment overwrite it, and deduplicate repeated validation calls. Remove `EnsemblePair` from `EnsembleSettings`, defaults, coercion, and serialization.

- [ ] **Step 4: Implement saved schema 2 and rewrite curated presets**

`save_ensemble()` must write:

```json
{
  "schema_version": 2,
  "ensemble_main_stem": "pair.karaoke",
  "ensemble_type": "Max Spec",
  "selected_models": ["mdx:first", "mdx:second"]
}
```

`ResolvedEnsemblePreset.main_stem` becomes `str`. Keep legacy member resolution and missing-model warnings intact while adding the pair-reset warning. Rewrite each curated preset to schema 2 using the reviewed pair or mode ID; do not change member identities or algorithms.

- [ ] **Step 5: Verify and commit Task 5**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_core_settings \
  tests.test_settings_coerce_v3 \
  tests.test_saved_ensembles \
  tests.test_ensemble_presets -v
.venv/bin/ruff check core/stem_pairs.py core/stems.py core/settings/defaults.py core/settings/model.py core/settings/coerce.py core/ensemble_service.py core/ensemble_presets.py tests/test_core_settings.py tests/test_settings_coerce_v3.py tests/test_saved_ensembles.py tests/test_ensemble_presets.py
.venv/bin/ruff format --check core/stem_pairs.py core/stems.py core/settings/defaults.py core/settings/model.py core/settings/coerce.py core/ensemble_service.py core/ensemble_presets.py tests/test_core_settings.py tests/test_settings_coerce_v3.py tests/test_saved_ensembles.py tests/test_ensemble_presets.py
.venv/bin/python -m basedpyright core/stem_pairs.py core/stems.py core/settings core/ensemble_service.py core/ensemble_presets.py tests/test_core_settings.py tests/test_settings_coerce_v3.py tests/test_saved_ensembles.py tests/test_ensemble_presets.py
git diff --check
```

Expected: all commands pass. Then commit:

```bash
git add core/stem_pairs.py core/stems.py core/settings/defaults.py core/settings/model.py core/settings/coerce.py core/ensemble_service.py core/ensemble_presets.py bundled/ensemble_presets tests/test_core_settings.py tests/test_settings_coerce_v3.py tests/test_saved_ensembles.py tests/test_ensemble_presets.py
git commit -m "feat(ensembles): adopt semantic stem pair ids"
```

---

### Task 6: Reconcile ensemble eligibility, planning, and collection by role ID

**Files:**

- Modify: `core/model_repository.py`
- Modify: `core/job_plan.py`
- Modify: `core/ensembler.py`
- Modify: `core/run_hooks.py`
- Modify: `core/run_estimate.py`
- Modify: `core/job_runner.py`
- Modify: `core/model_config/config.py`
- Modify: `tests/test_ensemble_model_eligibility.py`
- Modify: `tests/test_ensemble_pair_buckets.py`
- Modify: `tests/test_ensemble_stem_buckets.py`
- Modify: `tests/test_ensemble_collection.py`
- Modify: `tests/test_job_plan_topology.py`
- Modify: `tests/test_vocal_split_stems.py`

- [ ] **Step 1: Add failing cross-model compatibility tests**

Build fixtures using different native layouts that map to the same reviewed pair. Require:

- `Vocals/Instrumental` models ensemble despite `vocals/other` and `other/vocals` order/spelling differences;
- ordinary karaoke layouts ensemble under `pair.karaoke`;
- VR BVE uses its distinct backing-vocal pair and does not enter ordinary karaoke by spelling;
- Center/Wide, Mid/Side, and Similarity/Difference models ensemble under one `pair.center_side`;
- reviewed target/removal models ensemble through role IDs rather than `No X` spelling;
- GiantAILAB contributes only the two pair roles in karaoke mode and all three routes in multi-stem mode;
- raw unknowns and signature mismatches never contribute to reviewed pairs or merge with each other by spelling;
- a pair choice is available only when at least two distinct installed models each provide both requested roles;
- multi-stem grouping combines equal `StemRoleId` values and isolates raw literals; and
- invalid or no-longer-eligible pair selection blocks readiness and requests an explicit repick instead of selecting a nearby pair.

- [ ] **Step 2: Run ensemble suites and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_ensemble_model_eligibility \
  tests.test_ensemble_pair_buckets \
  tests.test_ensemble_stem_buckets \
  tests.test_ensemble_collection \
  tests.test_job_plan_topology \
  tests.test_vocal_split_stems -v
```

Expected: failures where eligibility and combine paths still use `StemBucket`, old enum halves, or raw filename spelling.

- [ ] **Step 3: Replace bucket-based eligibility and pair routing**

Change `ModelRepository.ensemble_model_list()` to resolve installed models and test exact role coverage against a `StemPairDefinition`. Do not grant eligibility from guessed catalogue intent.

Change `routes_for_ensemble_pair()`, job-plan output construction, workload estimation, and run hooks to use pair role IDs. Dual-pair final routes come directly from the role registry. Four- and multi-stem modes use reserved mode IDs.

- [ ] **Step 4: Replace combine identity and filename parsing assumptions**

Make collection carry the planned route's `StemRoleId` and `filename_tag` as metadata. `Ensembler` must group by role ID and use the registry tag for temporary filenames; it must not reconstruct semantics from display text or storage names.

Keep a compatibility reader only for temporary files produced within the same run if required by the engine boundary. It must be keyed by the already-planned tag and must never convert an arbitrary filename into a trusted role.

- [ ] **Step 5: Verify and commit Task 6**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_ensemble_model_eligibility \
  tests.test_ensemble_pair_buckets \
  tests.test_ensemble_stem_buckets \
  tests.test_ensemble_collection \
  tests.test_job_plan_topology \
  tests.test_vocal_split_stems -v
.venv/bin/ruff check core/model_repository.py core/job_plan.py core/ensembler.py core/run_hooks.py core/run_estimate.py core/job_runner.py core/model_config/config.py tests/test_ensemble_model_eligibility.py tests/test_ensemble_pair_buckets.py tests/test_ensemble_stem_buckets.py tests/test_ensemble_collection.py tests/test_job_plan_topology.py tests/test_vocal_split_stems.py
.venv/bin/ruff format --check core/model_repository.py core/job_plan.py core/ensembler.py core/run_hooks.py core/run_estimate.py core/job_runner.py core/model_config/config.py tests/test_ensemble_model_eligibility.py tests/test_ensemble_pair_buckets.py tests/test_ensemble_stem_buckets.py tests/test_ensemble_collection.py tests/test_job_plan_topology.py tests/test_vocal_split_stems.py
.venv/bin/python -m basedpyright core/model_repository.py core/job_plan.py core/ensembler.py core/run_hooks.py core/run_estimate.py core/job_runner.py core/model_config/config.py tests/test_ensemble_model_eligibility.py tests/test_ensemble_pair_buckets.py tests/test_ensemble_stem_buckets.py tests/test_ensemble_collection.py tests/test_job_plan_topology.py tests/test_vocal_split_stems.py
git diff --check
```

Expected: all commands pass. Then commit:

```bash
git add core/model_repository.py core/job_plan.py core/ensembler.py core/run_hooks.py core/run_estimate.py core/job_runner.py core/model_config/config.py tests/test_ensemble_model_eligibility.py tests/test_ensemble_pair_buckets.py tests/test_ensemble_stem_buckets.py tests/test_ensemble_collection.py tests/test_job_plan_topology.py tests/test_vocal_split_stems.py
git commit -m "refactor(ensembles): reconcile models by stem role"
```

---

### Task 7: Make catalogue, CLI, JSON, and diagnostics consume the projection

**Files:**

- Modify: `core/model_stem_semantics.py`
- Modify: `core/catalog_sources.py`
- Modify: `core/catalogue_types.py`
- Modify: `core/job_plan.py`
- Modify: `core/run_loop.py`
- Modify: `cli/discovery.py`
- Modify: `cli/ensemble.py`
- Modify: `cli/job.py`
- Modify: `tests/test_catalog_sources.py`
- Modify: `tests/test_catalog_stem_merge.py`
- Modify: `tests/test_cli_ensemble.py`
- Modify: `tests/test_cli_list_models.py`
- Modify: `tests/test_job_plan_topology.py`
- Modify: `tests/test_progress_ticks.py`

- [ ] **Step 1: Add failing shared-consumer tests**

Require human CLI and plan summaries to show canonical role names, while JSON retains raw backend fields and adds exactly:

```json
{
  "backend_primary_stem": "other",
  "backend_target_stem": "other",
  "logical_primary_role": "mix.instrumental",
  "stem_semantics_status": "reviewed",
  "stem_context": "full_mix",
  "stem_routes": []
}
```

Add tests for reviewed, waived, raw unknown, signature mismatch, normal karaoke, Vocal Splitter, BVE, spatial, effect-removal, and multi-stem records. Assert progress and diagnostic events include canonical label, role ID, native key, context, and status at appropriate verbosity.

Catalogue tests must prove exact manifest intent overrides guessed intent for presentation/eligibility, while guessed intent remains visible as audit evidence and never mutates the manifest.

- [ ] **Step 2: Run consumer tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_catalog_sources \
  tests.test_catalog_stem_merge \
  tests.test_cli_ensemble \
  tests.test_cli_list_models \
  tests.test_job_plan_topology \
  tests.test_progress_ticks -v
```

Expected: failures because CLI/JSON/catalogue consumers still expose guessed or backend names and old pair values.

- [ ] **Step 3: Consolidate presentation helpers on the manifest projection**

Replace `stem_display_overrides()`, global special-effect naming, and guessed-role output helpers with thin adapters over `ModelStemSemantics`. Keep backend-shape extraction helpers only where engines or catalogue collection require raw evidence. Mark guessed intent as audit-only in naming and docstrings.

Catalogue entries must carry semantic status, logical primary, canonical role list, and evidence without changing their canonical model IDs or download metadata.

- [ ] **Step 4: Update CLI, JSON, and diagnostics**

Make human CLI output read canonical role displays. Make machine output emit one complete JSON document with raw and semantic fields side by side. Update ensemble argument validation to accept current namespaced pair/mode IDs and list them with their canonical labels.

Log normal reviewed routing at verbose/debug level. Log raw fallback, signature mismatch, missing context, invalid pair, and persistence reset as warnings without exposing user paths or secrets.

- [ ] **Step 5: Verify and commit Task 7**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_catalog_sources \
  tests.test_catalog_stem_merge \
  tests.test_cli_ensemble \
  tests.test_cli_list_models \
  tests.test_job_plan_topology \
  tests.test_progress_ticks -v
.venv/bin/ruff check core/model_stem_semantics.py core/catalog_sources.py core/catalogue_types.py core/job_plan.py core/run_loop.py cli/discovery.py cli/ensemble.py cli/job.py tests/test_catalog_sources.py tests/test_catalog_stem_merge.py tests/test_cli_ensemble.py tests/test_cli_list_models.py tests/test_job_plan_topology.py tests/test_progress_ticks.py
.venv/bin/ruff format --check core/model_stem_semantics.py core/catalog_sources.py core/catalogue_types.py core/job_plan.py core/run_loop.py cli/discovery.py cli/ensemble.py cli/job.py tests/test_catalog_sources.py tests/test_catalog_stem_merge.py tests/test_cli_ensemble.py tests/test_cli_list_models.py tests/test_job_plan_topology.py tests/test_progress_ticks.py
.venv/bin/python -m basedpyright core/model_stem_semantics.py core/catalog_sources.py core/catalogue_types.py core/job_plan.py core/run_loop.py cli/discovery.py cli/ensemble.py cli/job.py tests/test_catalog_sources.py tests/test_catalog_stem_merge.py tests/test_cli_ensemble.py tests/test_cli_list_models.py tests/test_job_plan_topology.py tests/test_progress_ticks.py
git diff --check
```

Expected: all commands pass. Then commit:

```bash
git add core/model_stem_semantics.py core/catalog_sources.py core/catalogue_types.py core/job_plan.py core/run_loop.py cli/discovery.py cli/ensemble.py cli/job.py tests/test_catalog_sources.py tests/test_catalog_stem_merge.py tests/test_cli_ensemble.py tests/test_cli_list_models.py tests/test_job_plan_topology.py tests/test_progress_ticks.py
git commit -m "feat(cli): expose canonical stem semantics"
```

---

### Task 8: Update GTK selectors, Download Center, Model Test, and safe repicks

**Files:**

- Modify: `ui/views/base.py`
- Modify: `ui/views/mdx.py`
- Modify: `ui/views/demucs.py`
- Modify: `ui/widgets/stem_only.py`
- Modify: `ui/widgets/vocal_split_row.py`
- Modify: `ui/ensemble/window.py`
- Modify: `ui/download_center.py`
- Modify: `ui/option_summaries.py`
- Modify: `ui/window.py`
- Modify: `tests/test_stem_only.py`
- Modify: `tests/test_stem_selection_state.py`
- Modify: `tests/test_ensemble_ui_helpers.py`
- Modify: `tests/test_ensemble_save_dialog.py`
- Modify: `tests/test_download_center_stem_refresh.py`
- Modify: `tests/test_model_picker_records.py`
- Modify: `tests/test_vocal_split_stems.py`
- Modify: `tests/test_export_naming.py`
- Modify: `tests/test_inactive_view_stem_focus.py`

- [ ] **Step 1: Add failing headless GTK and pure-widget tests**

Cover primary, secondary, ensemble-member, Vocal Splitter, Model Test, and Download Center surfaces. Require:

- canonical role labels rather than backend basenames/spellings;
- widget state keyed by role ID or canonical model ID, never display text;
- logical-primary ordering and correct `Primary Stem Only` behavior;
- Vocal Splitter showing only karaoke/BV models with valid reviewed splitter contexts;
- pair choices generated from the installed inventory and the two-contributor rule;
- Center/Side and cross-layout karaoke members appearing together;
- raw unknown models displaying raw stem names but remaining unavailable to reviewed ensemble pairs;
- a new download/inventory refresh preserving a still-valid role/pair selection;
- a removed or invalid role/pair resetting to Choose with a visible repick requirement;
- no automatic nearest-choice selection; and
- Model Test filenames using the same canonical route label as normal export.

- [ ] **Step 2: Run pure tests and private GTK tests; verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_stem_selection_state \
  tests.test_ensemble_ui_helpers \
  tests.test_download_center_stem_refresh \
  tests.test_export_naming \
  tests.test_inactive_view_stem_focus -v
/home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh \
  .venv/bin/python -m unittest \
  tests.test_stem_only \
  tests.test_ensemble_save_dialog \
  tests.test_model_picker_records \
  tests.test_vocal_split_stems -v
```

Expected: semantic-label, pair-registry, and safe-repick assertions fail against existing bucket/display-string widgets.

- [ ] **Step 3: Bind every GTK surface to semantic routes**

Build Save Stems rows from `StemRoute.role`, `label`, and `logical_primary`. Build ensemble pair rows from installed-inventory `StemPairDefinition` choices. Store IDs through combo tag values and use labels only for rendering/search.

Download Center purpose/stem subtitles must use the exact manifest projection when declared and a clearly raw fallback otherwise. Primary/secondary/member pickers continue storing canonical model IDs.

Replace UI calls to global `canonical_stem_name()` and old pair halves where the selected model's semantic routes are available. Keep a raw-only formatter for unknown custom outputs.

- [ ] **Step 4: Implement inventory-refresh repick behavior**

On the existing single model-inventory invalidation:

1. Rebuild model and semantic route records.
2. Restore exact canonical model IDs.
3. Restore exact role/pair IDs only if still present and eligible.
4. Otherwise select Choose, add the validation/review message, and leave Start disabled until the user repicks.

Do not invalidate once per widget and do not persist a display label as a replacement ID.

- [ ] **Step 5: Verify and commit Task 8**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_stem_selection_state \
  tests.test_ensemble_ui_helpers \
  tests.test_download_center_stem_refresh \
  tests.test_export_naming \
  tests.test_inactive_view_stem_focus -v
/home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh \
  .venv/bin/python -m unittest \
  tests.test_stem_only \
  tests.test_ensemble_save_dialog \
  tests.test_model_picker_records \
  tests.test_vocal_split_stems -v
.venv/bin/ruff check ui/views/base.py ui/views/mdx.py ui/views/demucs.py ui/widgets/stem_only.py ui/widgets/vocal_split_row.py ui/ensemble/window.py ui/download_center.py ui/option_summaries.py ui/window.py tests/test_stem_only.py tests/test_stem_selection_state.py tests/test_ensemble_ui_helpers.py tests/test_ensemble_save_dialog.py tests/test_download_center_stem_refresh.py tests/test_model_picker_records.py tests/test_vocal_split_stems.py tests/test_export_naming.py tests/test_inactive_view_stem_focus.py
.venv/bin/ruff format --check ui/views/base.py ui/views/mdx.py ui/views/demucs.py ui/widgets/stem_only.py ui/widgets/vocal_split_row.py ui/ensemble/window.py ui/download_center.py ui/option_summaries.py ui/window.py tests/test_stem_only.py tests/test_stem_selection_state.py tests/test_ensemble_ui_helpers.py tests/test_ensemble_save_dialog.py tests/test_download_center_stem_refresh.py tests/test_model_picker_records.py tests/test_vocal_split_stems.py tests/test_export_naming.py tests/test_inactive_view_stem_focus.py
.venv/bin/python -m basedpyright ui/views/base.py ui/views/mdx.py ui/views/demucs.py ui/widgets/stem_only.py ui/widgets/vocal_split_row.py ui/ensemble/window.py ui/download_center.py ui/option_summaries.py ui/window.py tests/test_stem_only.py tests/test_stem_selection_state.py tests/test_ensemble_ui_helpers.py tests/test_ensemble_save_dialog.py tests/test_download_center_stem_refresh.py tests/test_model_picker_records.py tests/test_vocal_split_stems.py tests/test_export_naming.py tests/test_inactive_view_stem_focus.py
git diff --check
```

Expected: all commands pass. Then commit:

```bash
git add ui/views/base.py ui/views/mdx.py ui/views/demucs.py ui/widgets/stem_only.py ui/widgets/vocal_split_row.py ui/ensemble/window.py ui/download_center.py ui/option_summaries.py ui/window.py tests/test_stem_only.py tests/test_stem_selection_state.py tests/test_ensemble_ui_helpers.py tests/test_ensemble_save_dialog.py tests/test_download_center_stem_refresh.py tests/test_model_picker_records.py tests/test_vocal_split_stems.py tests/test_export_naming.py tests/test_inactive_view_stem_focus.py
git commit -m "feat(ui): present canonical stem roles"
```

---

### Task 9: Regenerate artefacts and run the complete verification gate

**Files:**

- Regenerate: `docs/models-catalogue.md`
- Regenerate: `docs/model_display_reference.tsv`
- Regenerate: `docs/model_display_quality_audit.md`
- Regenerate: `docs/model_stem_semantics_reference.tsv`
- Modify tests only if a stale expectation contradicts the approved spec; do not weaken a gate to make it pass

- [ ] **Step 1: Re-run authoritative and offline catalogue checks**

Run:

```bash
.venv/bin/python scripts/generate_models_catalogue.py \
  --refresh --write --write-display-reference \
  --write-stem-semantics-reference
.venv/bin/python scripts/generate_models_catalogue.py \
  --offline --check --write-display-reference \
  --write-stem-semantics-reference
.venv/bin/python scripts/stem_semantics_audit.py --check
```

Expected: 485 identities, pinned vocabulary counts, zero unreviewed declarations, zero signature mismatches, zero dangling roles/pairs, zero accidental normalized display/tag collisions, and fresh-online/warm-offline semantic parity.

- [ ] **Step 2: Run all focused non-GTK suites together**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_model_stem_manifest \
  tests.test_stems_typed \
  tests.test_model_stem_semantics \
  tests.test_stem_selection \
  tests.test_stem_writer \
  tests.test_export_stem_label \
  tests.test_mdx_export_routing \
  tests.test_demucs_secondary_slots \
  tests.test_target_other_stems \
  tests.test_core_settings \
  tests.test_settings_coerce_v3 \
  tests.test_saved_ensembles \
  tests.test_ensemble_presets \
  tests.test_ensemble_model_eligibility \
  tests.test_ensemble_pair_buckets \
  tests.test_ensemble_stem_buckets \
  tests.test_ensemble_collection \
  tests.test_job_plan_native_values \
  tests.test_job_plan_topology \
  tests.test_catalog_sources \
  tests.test_catalog_stem_merge \
  tests.test_cli_ensemble \
  tests.test_cli_list_models \
  tests.test_generate_models_catalogue \
  tests.test_stem_semantics_audit -v
```

Expected: zero failures and zero errors.

- [ ] **Step 3: Run the complete unit suite in private GTK isolation**

Invoke the `testing-gtk-headless` skill if the runner needs troubleshooting, then run:

```bash
/home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh \
  .venv/bin/python -m unittest discover -s tests -t . -v
```

Expected: exit 0 with zero failures and zero errors. The private compositor must not touch the host Wayland session.

- [ ] **Step 4: Run static and repository checks**

Re-run the exact scoped Ruff commands from Tasks 1-8, then run:

```bash
.venv/bin/python -m basedpyright
git diff --check
git status --short
```

Expected: scoped Ruff clean, basedpyright reports zero errors, whitespace is clean, and status contains only intended implementation/generated files plus the pre-existing unstaged `registered_models.json` user/runtime change.

- [ ] **Step 5: Perform a final semantic diff review**

Inspect the complete branch diff and confirm:

- canonical IDs, model artifacts, hashes, backend stem keys, backend primary/target values, and execution metadata did not change;
- all semantic membership comes from exact manifest declarations;
- raw/unknown behavior is isolated and network-free;
- settings schema 5 and saved ensemble schema 2 reset old pairs as approved;
- no display string is parsed into identity;
- generated references contain no unexplained or unreviewed row; and
- `registered_models.json` was not included in any task commit.

- [ ] **Step 6: Commit only final generated/test adjustments**

If Step 1 regenerated tracked artefacts after Task 8, commit only those verified files and any necessary expectation updates:

```bash
git add docs/models-catalogue.md docs/model_display_reference.tsv docs/model_display_quality_audit.md docs/model_stem_semantics_reference.tsv
git commit -m "docs(models): regenerate stem semantics catalogue"
```

If there is no diff in those files, do not create an empty commit. Do not push.

---

## Completion Evidence

The implementation is complete only when the final report records:

- the exact commit IDs created by Tasks 1-9;
- the authoritative catalogue and warm-offline check results;
- 485 reviewed/waived current identities and the pinned 148/123/92/4 vocabulary counts;
- zero unreviewed entries, signature mismatches, dangling role/pair references, and accidental collisions;
- focused suite totals and complete suite totals;
- scoped Ruff and project-wide basedpyright results;
- private headless GTK command and result;
- final `git diff --check` and `git status --short`; and
- explicit confirmation that no push occurred and `registered_models.json` remained outside all commits.
