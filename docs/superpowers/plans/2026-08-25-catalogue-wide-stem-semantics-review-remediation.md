# Catalogue-Wide Stem Semantics Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the reviewed catalogue-wide stem semantics, make the bundled manifest fail closed under a strict schema, execute the one approved multi-source derived route, and republish one internally consistent current catalogue snapshot. The original reviewed snapshot contained 485 models; the Task 8 fresh-source amendment below advances the final target to 486.

**Architecture:** `bundled/model_stem_manifest.json` remains the exact canonical-ID/native-signature/context source of truth. Schema 2 adds a presentation-independent default-selection bit and distinguishes mix complements from reviewed sums. A shared exact-ID runtime-signature supplement covers catalogue entries whose published metadata omits their complete backend inventory; audit, rendering, live Download Center projection, and installed runtime assembly consume that same contract. The runtime continues to address audio only by native backend keys, projects reviewed roles one way into UI/CLI/catalogue surfaces, and materializes only recipes declared for the exact model. The unified catalogue generator validates and publishes all human and machine-readable artefacts from one collected snapshot.

**Tech Stack:** Python 3.12 compatibility, frozen dataclasses and validated value objects, JSON/TSV, NumPy audio arrays, stdlib `unittest`, scoped Ruff, basedpyright, GTK4/libadwaita consumer tests.

**Spec:** [Catalogue-Wide Stem Semantics and Canonical Naming Design](../specs/2026-08-24-catalogue-wide-stem-semantics-design.md). The reviewed schema-2 decisions and the corrected karaoke logical-primary contract are reflected in that spec and are binding throughout this plan.

## Global Constraints

- Preserve every canonical `family:basename` model ID, exact native stem key, backend primary/target value, artifact, hash, architecture, and execution option.
- Semantic matching remains exact canonical ID + complete case-folded native signature + explicit processing context. Never add fuzzy, substring, display-to-identity, author-derived, or filename-derived runtime matching.
- Treat a classic MDX model's computed primary and inverse as two addressable runtime outputs even though the engine obtains the inverse as `mix - primary`. A reviewed classic declaration must use both exact engine output keys; it must not masquerade as a one-output MDX-C target declaration.
- Keep role IDs as validated `StemRoleId` values backed by the manifest. Do not replace the extensible role vocabulary with one giant Python enum.
- Keep exactly these four ensemble pair definitions and no others:
  - `pair.vocals_instrumental`
  - `pair.karaoke`
  - `pair.backing_vocals`
  - `pair.center_side`
- `pair.karaoke` has exact ordered roles
  (`mix.instrumental_with_backing_vocals`, `vocal.lead`) and display
  `Instrumental with Backing Vocals/Lead Vocals`.
- Do not add `pair.reverb_echo`, guitar, instrument-target, effect, or other automatically generated specialty pairs. Specialty roles remain available in Multi-Stem and explicit stem selection without becoming two-model ensemble pair choices.
- A no-filter run of a normal Vocals, Instrumental, or target model exports both its native side and its reviewed inverse. `intent` must never suppress a valid inverse output.
- For every ordinary `karaoke`-intent model, `full_mix` logical primary is `mix.instrumental_with_backing_vocals` and `vocal_split` logical primary is `vocal.backing`; both contexts explicitly declare `logical_secondary: vocal.lead`. This semantic correction must not alter native backend keys, authored arrays, backend polarity, production method, or default-selection behavior. The exact VR BVE vocals-intent model remains distinct.
- GiantAILAB is the only currently approved multi-source sum. Its combined karaoke accompaniment is the full-mix logical primary and the sole current default-false logical primary; its three native outputs remain selected by default in a normal full-mix run. `pair.karaoke` schedules the combined accompaniment before Lead Vocals. Vocal Splitter may project all exact native meanings for auditability, but uses Backing Vocals as logical primary and schedules Backing Vocals before Lead Vocals.
- A scheduled derived route must either be produced or fail with an actionable error. It must never be silently omitted while the job reports success.
- Unknown custom models remain raw and ensemble-isolated. A signature mismatch on a reviewed model also falls back to raw semantics rather than partially applying the declaration.
- Treat `bundled/model_stem_manifest.json` as internal checked-in data: load schema 2 only, with no runtime migration or schema-1 compatibility path.
- Preserve the existing unrelated dirty worktree. At plan creation it includes audio/export/ensemble edits, `engines/stem_writer.py`, several tests, runtime `registered_models.json`, and an icon deletion. Do not revert, reformat, stage, or commit those hunks. Use path-specific staging, inspect `git diff --cached` before every commit, and do not commit at all while any unrelated path is already staged.
- Do not hand-edit generated catalogue Markdown or TSVs. Change their inputs/renderers, then regenerate all artefacts together.
- Use stdlib `unittest`, scoped Ruff, and basedpyright. Do not run repository-wide Ruff fixes or bulk formatting.
- Do not push or merge as part of this plan.

## Reviewed End-State Contract

The current baseline is schema 1 with 160 roles, 455 declarations, 30 waivers, 485 catalogue IDs, and 1,206 generated semantic-reference rows (1,176 context/output rows plus 30 waiver rows). That 485-model end state governed Tasks 1–7. Task 8's fresh-source amendment adds one exactly evidenced SCNet declaration and supersedes only the final counts: 486 catalogue IDs, 484 reviewed declarations, two Apollo waivers, 515 reviewed contexts, and zero raw IDs. The end state must have:

- schema 2;
- 486 post-deduplication catalogue IDs;
- 484 reviewed declarations and exactly two Apollo waivers;
- zero raw/unreviewed current-catalogue IDs;
- exactly four pair definitions;
- no unused role definitions;
- no normalized role-display, filename-tag, or accidental route collisions;
- zero structural audit findings;
- zero stale name/backend false positives; and
- a semantic TSV row count derived from the rendered schema-2 snapshot, not hard-coded to 1,206.
- exactly 30 final `karaoke` declarations: the frozen starting 28-ID set plus GiantAILAB and `mdx:UVR_MDXNET_KARA`; both MelBand BVE IDs are included and the exact VR BVE vocals-intent ID is excluded.

The only remaining waivers are:

```text
apollo:apollo_edm_big_by_essid
apollo:apollo_edm_by_essid
```

The closed intent vocabulary is:

```text
karaoke
drum_bass_sep
dual_voc_inst
multi_stem
special_fx
specialty_stem
instrumental
vocals
unknown
```

These values are explicit reviewed data. They are not inferred at runtime from a model label or basename.

---

## Task 1: Revise the approved design to match the reviewed decisions

**Files:**

- Modify: `docs/superpowers/specs/2026-08-24-catalogue-wide-stem-semantics-design.md`
- Reference: `docs/superpowers/plans/2026-08-24-catalogue-wide-stem-semantics.md`
- Reference: `docs/superpowers/plans/2026-08-25-unified-catalogue-stem-audit-generator.md`

- [ ] Add a dated revision section to the approved design instead of deleting its historical baseline measurements.

- [ ] Replace the schema-1 manifest example with schema 2 and document `selected_by_default` as an optional strict boolean that defaults to `true` when omitted. Explicit `false` must survive parsing, projection, JSON rendering, and route selection. Update the spec's `SemanticStemOutput`/`StemSemanticRoute` examples, public JSON projection example, and semantic-reference TSV header at the same time.

- [ ] Define the TSV contract precisely: append `complement_of`, `derived_from`, and `selected_by_default` as the final three columns. Render a complement dependency as one role ID, sum dependencies as ordered `|`-joined role IDs, and defaults as lowercase `true`/`false`. Leave dependency cells blank when inapplicable; leave all three blank only on waiver rows that have no output route.

- [ ] Document the two disjoint derived recipe forms:

  ```text
  complement_of: mix minus one exact native role
  derived_from:  sum of two or more exact native roles
  ```

  Dependencies are role IDs within the same model/context. Neither form permits display/native-name lookup or derived-to-derived chaining.

- [ ] Replace the spec's generated target/specialty pair language with the exact four-pair limit from Global Constraints. Preserve the existing saved-pair cutover; no support for old saved pair IDs is reintroduced.

- [ ] Add the closed intent vocabulary, canonical role-ID corrections, GiantAILAB recipe/default behavior, 483/2 review target, and dynamic semantic-row-count rule.

- [ ] Apply the ordinary-karaoke contract everywhere: accompaniment logical primary and explicit Lead Vocals logical secondary in `full_mix`, Backing Vocals logical primary and explicit Lead Vocals logical secondary in `vocal_split`, and accompaniment-first `pair.karaoke` display/role order. Preserve the exact VR BVE exception and make logical-primary membership/uniqueness independent of default selection so GiantAILAB's sole current default-false derived primary remains valid without a runtime model-ID special case. Add and project the optional general `logical_secondary` field without order, intent, or model-ID inference, and pin the final exact 30-ID karaoke set.

- [ ] State explicitly that exact target/complement routes remain both selected by default regardless of whether the model intent is `instrumental`, `vocals`, `special_fx`, or `specialty_stem`.

- [ ] Document the three MDX runtime inventory classes used in Task 5: classic ONNX has two addressable export keys, MDX-C multi has all configured instruments, and MDX-C target has one configured native target plus reviewed derived routes. Link the exact runtime-contract supplement and state that installed hash/config disagreement falls back raw.

- [ ] Verify documentation whitespace and links:

  ```bash
  git diff --check -- docs/superpowers/specs/2026-08-24-catalogue-wide-stem-semantics-design.md
  ```

- [ ] Commit only the spec revision if task commits are desired:

  ```bash
  git add docs/superpowers/specs/2026-08-24-catalogue-wide-stem-semantics-design.md
  git diff --cached --check
  git commit -m "docs(stems): correct karaoke primary semantics"
  ```

---

## Task 2: Introduce strict manifest schema 2 and propagate output defaults

**Files:**

- Modify: `bundled/model_stem_manifest.json`
- Modify: `core/stem_roles.py`
- Modify: `core/model_stem_manifest.py`
- Modify: `core/model_config/config.py`
- Modify: `core/stems.py`
- Modify: `core/stem_selection.py`
- Modify: `core/catalogue_types.py`
- Modify: `core/model_stem_semantics.py`
- Modify: `core/job_plan.py`
- Modify: `core/catalog_sources.py`
- Modify: `cli/discovery.py`
- Modify: `ui/views/base.py`
- Modify: `scripts/catalogue/stem_audit.py`
- Modify: `scripts/catalogue/render.py`
- Modify: `tests/test_model_stem_manifest.py`
- Modify: `tests/test_model_stem_semantics.py`
- Modify: `tests/test_stems_typed.py`
- Modify: `tests/test_stem_selection.py`
- Modify: `tests/test_job_plan_topology.py`
- Modify: `tests/test_method_view_refresh.py`
- Modify: `tests/test_stem_selection_state.py`
- Modify: `tests/test_catalog_stem_merge.py`
- Modify: `tests/test_cli_list_models.py`
- Modify: `tests/test_download_center_stem_refresh.py`
- Modify: `tests/test_catalogue_stem_audit.py`
- Modify: `tests/test_generate_models_catalogue.py`

### Schema 2 grammar

All objects are closed-world. Reject any unknown field at the root, role, pair, model, context, or output level.

```text
root:    schema_version, roles, pairs, models, waivers
role:    display, filename_tag, family, [removed_of]
pair:    display, roles
model:   native_signature, intent, contexts, evidence
context: logical_primary, [logical_secondary], outputs

native output:
  native, role, [production="native"], [selected_by_default]

mix-complement output:
  native=null, role, production="derived", complement_of,
  [selected_by_default]

sum output:
  native=null, role, production="derived", derived_from,
  [selected_by_default]
```

`selected_by_default` defaults to `true` when absent and must satisfy `type(value) is bool` when present. It controls unfiltered export independently of logical primary; a context has exactly one logical primary, but that route may be default-false. This is a generic membership/uniqueness invariant, not a model-ID exception. Optional `logical_secondary` must be distinct from primary and name one output role exactly once. Its absence projects no semantic secondary; no consumer may infer one by order, intent, display, or model ID. `derived_from` means a sum and therefore contains at least two distinct role IDs.

- [ ] Write failing loader tests before production edits. Cover:

  - exact integer schema version 2; reject booleans, floats, strings, 1, and 3;
  - duplicate JSON keys at root and nested levels by loading literal temporary JSON text;
  - unknown fields at every object level;
  - omitted `selected_by_default` becoming `true`, explicit `false` round trip, and non-boolean rejection;
  - native output dependency rejection;
  - derived output requiring exactly one recipe form;
  - `complement_of` resolving to one native output in the same context;
  - `derived_from` requiring two or more distinct native outputs in the same context;
  - missing, self, duplicate, and derived-to-derived dependencies;
  - duplicate case-folded native keys and duplicate role IDs within one context;
  - empty `native_signature` rejection;
  - exactly one logical primary, including a valid explicit-false logical primary and no coupling between primary validation and default selection;
  - omitted `logical_secondary`, a valid distinct member, and rejection of missing, duplicate, primary-equal, or non-string secondary roles;
  - role namespace prefix matching `StemRoleFamily.value`;
  - missing, self, cyclic, and cross-family `removed_of` edges;
  - reciprocal `.removed` naming for every `removed_of` declaration;
  - model/waiver overlap; and
  - application-facing raw fallback after a malformed bundled manifest.

- [ ] Parse JSON with a duplicate-aware `object_pairs_hook`. Convert duplicate failures into `StemManifestError`; include the duplicate key even when the decoder cannot retain a full nested path.

- [ ] Add helpers in `core/model_stem_manifest.py` rather than duplicating checks inline. Expected responsibilities include:

  ```python
  def _closed_mapping(..., *, required: frozenset[str], optional: frozenset[str]) -> Mapping[str, object]: ...
  def _strict_bool(value: object, path: tuple[str | int, ...]) -> bool: ...
  def _validate_removed_graph(roles: Mapping[StemRoleId, StemRoleDefinition]) -> None: ...
  def _validate_context_dependencies(...) -> None: ...
  ```

- [ ] Add `selected_by_default: bool = True` after the existing `derived_from` and `complement_of` fields in `SemanticStemOutput` so their positional construction cannot silently shift; append the new logical-secondary flag after it. Use keyword arguments in all new construction.

- [ ] Add `logical_secondary: bool = False` at the end of `SemanticStemOutput` and `StemSemanticRoute`, plus `logical_secondary_role: StemRoleId | StemLiteral | None = None` on `ModelStemSemantics`. Parse the optional context role, mark exactly one output/route when present, and emit top-level `logical_secondary_role` plus per-route `logical_secondary` in public JSON. Use keyword construction so existing positional fields cannot shift.

- [ ] Add `selected_by_default: bool = True` after the existing recipe fields in `StemSemanticRoute`, emit it in `as_dict()`, append the new logical-secondary flag after it, and change `stem_semantics_projection()` and every existing constructor (including Download Center fixtures) to keyword construction before relying on either field.

- [ ] Copy `SemanticStemOutput.selected_by_default` into `StemRoute` in `_semantic_routes()` instead of hard-coding `True`.

- [ ] Thread the explicit logical-secondary projection through `StemRoute`, catalogue projections, job-plan summaries, CLI/JSON, and primary/secondary selection helpers. `Secondary Stem Only` and positional `secondary` select the named route when present, including GiantAILAB's Lead Vocals across four-route full mix and three-route vocal split. When absent, expose no semantic secondary; do not choose the first non-primary route or branch on intent/model ID. Preserve existing backend-positional behavior only as backend behavior, not as a semantic role inference.

- [ ] Insert `logical_secondary` after `logical_primary` in `docs/model_stem_semantics_reference.tsv`, while keeping `complement_of`, `derived_from`, and `selected_by_default` as the final three columns. Render lowercase `true` on the named route, `false` on its peers, and blank for contexts without the optional field and waiver rows. Render exact dependency role IDs, ordered `|`-joined sums, and lowercase defaults; use blank dependency cells when inapplicable and leave all three final cells blank on waiver rows. Update renderer/test headers now; regenerate the checked-in file only in Task 8.

- [ ] Add renderer tests for a native row, one `complement_of` row, Giant-style ordered `derived_from` row whose logical primary has an explicit false default, logical-secondary true/false/blank cells, and a waiver row. These tests define the cells before Task 6 moves row construction behind the structured audit result.

- [ ] Change `schema_version` and add the already-confirmed `removed_of: "mix.music"` relationship to `mix.music.removed` in the bundled manifest during this task. The latter is required for the strict reciprocal removed-role validator. Leave all output defaults implicit so current behavior remains unchanged until the reviewed GiantAILAB `false` is added in Task 4.

- [ ] Run the focused red/green suite:

  ```bash
  .venv/bin/python -m unittest -v \
    tests.test_model_stem_manifest \
    tests.test_model_stem_semantics \
    tests.test_stems_typed \
    tests.test_stem_selection \
    tests.test_job_plan_topology \
    tests.test_method_view_refresh \
    tests.test_stem_selection_state \
    tests.test_catalog_stem_merge \
    tests.test_cli_list_models \
    tests.test_download_center_stem_refresh \
    tests.test_catalogue_stem_audit \
    tests.test_generate_models_catalogue
  ```

- [ ] Commit the schema/type boundary without generated artefacts:

  ```bash
  git add bundled/model_stem_manifest.json \
    core/stem_roles.py core/model_stem_manifest.py core/model_config/config.py \
    core/stems.py core/stem_selection.py core/catalog_sources.py \
    core/catalogue_types.py core/model_stem_semantics.py core/job_plan.py \
    cli/discovery.py ui/views/base.py \
    scripts/catalogue/stem_audit.py scripts/catalogue/render.py \
    tests/test_model_stem_manifest.py tests/test_model_stem_semantics.py \
    tests/test_stems_typed.py tests/test_stem_selection.py \
    tests/test_job_plan_topology.py tests/test_method_view_refresh.py \
    tests/test_stem_selection_state.py tests/test_catalog_stem_merge.py \
    tests/test_cli_list_models.py tests/test_download_center_stem_refresh.py \
    tests/test_catalogue_stem_audit.py tests/test_generate_models_catalogue.py
  git diff --cached --check
  git commit -m "feat(stems): add strict manifest schema 2"
  ```

---

## Task 3: Execute reviewed complement and multi-source-sum recipes

**Files:**

- Modify: `engines/mdx.py`
- Modify: `engines/mdx_c.py`
- Modify: `engines/mdx_c_engine.py`
- Modify: `tests/test_mdx_export_routing.py`
- Modify: `tests/test_stem_writer.py`
- Create: `tests/test_stem_semantics_remediation.py`

- [ ] Add failing audio-level tests with deliberately non-complementary arrays so the recipe cannot pass accidentally:

  1. A `complement_of` route still uses the existing mix-minus-source path and inversion/match-frequency options.
  2. A `derived_from=(vocal.backing, mix.instrumental)` route produces the sum of those two exact native sources, not `mix - lead`.
  3. Dependency lookup is by reviewed role to exact native key only; labels and filename tags are never accepted as source keys.
  4. A missing scheduled dependency raises an actionable exception before export completion.
  5. An unselected derived route is not synthesized.
  6. A derived-only explicit focus succeeds without forcing a bogus native-primary lookup.
  7. Existing one-target models still export native and inverse routes by default.

- [ ] Isolate recipe materialization in an engine helper. Its input is the exact available route inventory, exact scheduled export routes, native source mapping, and mix; its output is a source map keyed by native key or stable route concept.

- [ ] Build `sources_by_role` only from available routes whose native key resolves exactly/case-insensitively in the backend source map.

- [ ] Implement recipes as follows:

  ```text
  complement_of:
    call the existing MDX complement DSP path for mix - source

  derived_from:
    require every listed source role;
    normalize each source to channel-last write orientation;
    shape-check the arrays;
    combine them with spec_utils.combine_arrarys(..., is_swap=True)
  ```

- [ ] Keep sum recipes out of `_vocal_split_pair_sources()`'s complement fallback and out of single-target detection. A one-element `derived_from` is invalid schema, not an alias for `complement_of`.

- [ ] Refactor `mdx_export_routing_flags()`/`SeperateMDXC.seperate()` so a selected sum route is merged into `export_sources` after native routing and before `ExportPlan` is returned. The existing target-pair secondary-model processing remains attached only to `complement_of` routes.

- [ ] Cover classic MDX separately. `SeperateMDX.seperate()` computes its inverse as `mix - primary`, but both `primary_stem` and `secondary_stem` are addressable exported keys. Add table-driven tests for empty focus, primary-only focus, inverse-only focus, Karaoke, Reverb, Crowd, and every KUIELAB target. Assert that reviewed routes select the same exact keys the engine places in its source dictionary and that display/filename roles never replace those keys.

- [ ] Keep classic MDX DSP unchanged unless those tests expose a real routing defect. If a shared helper is needed, it may translate an exact reviewed role selection to `primary_stem`/`secondary_stem`; it must not recalculate, rename, or collapse the engine's two-output inventory.

- [ ] Do not edit `engines/stem_writer.py` for this task unless a failing test proves the generic exporter itself is wrong; that file already contains unrelated user changes. The planned recipe belongs in MDX-C source materialization.

- [ ] Run focused execution tests:

  ```bash
  .venv/bin/python -m unittest -v \
    tests.test_mdx_export_routing \
    tests.test_stem_writer \
    tests.test_stem_semantics_remediation
  ```

- [ ] Commit only the recipe implementation and its new tests:

  ```bash
  git add engines/mdx.py engines/mdx_c.py engines/mdx_c_engine.py \
    tests/test_mdx_export_routing.py tests/test_stem_writer.py \
    tests/test_stem_semantics_remediation.py
  git diff --cached --check
  git commit -m "feat(stems): execute reviewed derived recipes"
  ```

---

## Task 4: Correct the canonical role vocabulary and reviewed declarations

**Files:**

- Modify: `bundled/model_stem_manifest.json`
- Modify: `core/stem_roles.py`
- Modify: `core/model_stem_semantics.py`
- Modify: `core/model_stem_manifest.py`
- Create: `tests/fixtures/stem_manifest_decisions.json`
- Modify: `tests/test_model_stem_manifest.py`
- Modify: `tests/test_stem_semantics_remediation.py`
- Modify: `tests/test_ensemble_pair_buckets.py`

### Canonical role changes

Add or normalize these exact role definitions:

| Role ID | Display | Filename tag | Relationship |
|---|---|---|---|
| `vocal.bass` | `Bass Vocals` | `Bass_Vocals` | — |
| `instrument.hi_hat` | `Hi-Hat` | `Hi_Hat` | — |
| `instrument.hi_hat.removed` | `Hi-Hat Removed` | `Hi_Hat_Removed` | removed of `instrument.hi_hat` |
| `instrument.orchestra` | `Orchestra` | `Orchestra` | — |
| `instrument.orchestra.removed` | `Orchestra Removed` | `Orchestra_Removed` | removed of `instrument.orchestra` |
| `instrument.woodwinds` | `Woodwinds` | `Woodwinds` | — |
| `instrument.woodwinds.removed` | `Woodwinds Removed` | `Woodwinds_Removed` | removed of `instrument.woodwinds` |
| `instrument.guitar.lead` | `Lead Guitar` | `Lead_Guitar` | — |
| `instrument.guitar.rhythm` | `Rhythm Guitar` | `Rhythm_Guitar` | — |
| `instrument.drum_bass` | `Drum/Bass` | `Drum_Bass` | — |
| `instrument.drum_bass.removed` | `Drum/Bass Removed` | `Drum_Bass_Removed` | removed of `instrument.drum_bass` |
| `effect.reverb_echo` | `Reverb/Echo` | `Reverb_Echo` | — |
| `effect.reverb_echo.removed` | `Reverb/Echo Removed` | `Reverb_Echo_Removed` | removed of `effect.reverb_echo` |
| `cinematic.sfx` | `SFX` | `SFX` | — |
| `residual.other.removed` | `Residual Removed` | `Residual_Removed` | removed of `residual.other` |

Retain the `removed_of: "mix.music"` correction made during the schema-2 migration.

After remapping every use, remove these obsolete definitions:

```text
instrument.hh
instrument.hh.removed
instrument.orch
instrument.orch.removed
instrument.woodwind
instrument.woodwind.removed
instrument.rhythm
residual.back
residual.backing_vocal
residual.lead
residual.others
```

Keep `residual.other`; it is the reviewed residual stem for ordinary multi-stem music models.

- [ ] Write table-driven failing tests for the exact role definitions above, zero unused roles, and the exact four pair IDs. Assert `pair.karaoke` has accompaniment-first roles and display, and explicitly assert that no new effect/instrument pair was added.

- [ ] Keep one intent source of truth. Define/re-export the nine constants and `MODEL_STEM_INTENTS` from `core/model_stem_semantics.py`; import that vocabulary in `core/model_stem_manifest.py` rather than duplicating string literals in `core/stem_roles.py`. Keep `ModelStemSemantics.intent` serialized as the stable string value.

- [ ] Before editing declarations, create `tests/fixtures/stem_manifest_decisions.json` as an exact, sorted, independently reviewed ledger with one entry for every final reviewed model and every context:

  ```json
  {
    "schema_version": 1,
    "catalogue_model_count": 485,
    "declared_model_count": 483,
    "declared_context_count": 514,
    "waivers": ["apollo:apollo_edm_big_by_essid", "apollo:apollo_edm_by_essid"],
    "karaoke_model_ids": ["30 exact sorted canonical IDs"],
    "models": {
      "family:basename": {
        "intent": "one closed-vocabulary value",
        "contexts": {
          "full_mix": {
            "logical_primary": "role.id",
            "logical_secondary": "another.role.id",
            "outputs": [
              {
                "native": "exact backend key",
                "role": "role.id",
                "production": "native",
                "selected_by_default": true
              },
              {
                "native": null,
                "role": "derived.role.id",
                "production": "derived",
                "derived_from": ["role.id", "role.id"],
                "selected_by_default": false
              }
            ]
          }
        }
      }
    }
  }
  ```

  Omit `logical_secondary`, `complement_of`, or `derived_from` when inapplicable; never store empty placeholders. Build the first draft from the current exact declarations and the migration table below, then review the full 483-ID/route diff before changing the manifest. The 514 contexts are the existing 485 plus 28 promoted full-mix contexts plus `mdx:UVR_MDXNET_KARA`'s promoted vocal-split context. During Task 4, require exact equality for the 455 already-declared IDs and require the ledger-only 28 to equal the MDX waiver-promotion set; Task 5 removes that temporary gap and requires full 483-ID equality. In both phases, compare context sets, intents, logical primaries, optional logical secondaries, ordered outputs, exact native keys, roles, production, dependencies, selection defaults, waiver IDs, and the applicable counts. Each expected primary and present secondary must occur exactly once and be distinct. Task 4 authors `karaoke_model_ids` immediately as the independently reviewed final exact 30-ID set: the 28 starting karaoke declaration IDs, GiantAILAB, and the ledger-only promotion decision for `mdx:UVR_MDXNET_KARA`. Tests require it to equal the set of fixture models whose final intent is `karaoke`; both MelBand BVE IDs must be members and exact VR BVE must not. The production manifest remains at an interim 29 karaoke declarations after Task 4 because the pre-authored `mdx:UVR_MDXNET_KARA` decision is not applied there until Task 5. This fixture is a test oracle, never imported by runtime code or generated from the already-edited manifest.

- [ ] Replace every legacy intent (`vocal_pair`, `removal:*`, `instrument_target:*`, `spatial`, `backing_vocal_separation`) with one explicit allowed value. Use this reviewed classification policy only while editing the exact declarations; do not implement it as runtime inference:

  | Reviewed purpose | Intent |
  |---|---|
  | Karaoke/accompaniment pair, including GiantAILAB | `karaoke` |
  | ViperX Drum/Bass operation | `drum_bass_sep` |
  | Neutral first-class Vocals/Instrumental pair | `dual_voc_inst` |
  | Three-or-more ordinary output classes | `multi_stem` |
  | DeReverb, DeNoise, Reverb/Echo, restoration effect | `special_fx` |
  | Instrument target, SpeechSep, spatial, cinematic target | `specialty_stem` |
  | Model explicitly optimized for Instrumental | `instrumental` |
  | Model explicitly optimized for Vocals, including exact VR BVE | `vocals` |
  | Future reviewed declaration with no established purpose | `unknown` |

  The mechanical legacy migration is exact: `karaoke` stays `karaoke`; `multi_stem` stays `multi_stem`; `removal:*` becomes `special_fx`; `instrument_target:*` and `spatial` become `specialty_stem`. Apply the explicit exception tables in this task and Task 5 after that mechanical pass. Split the old `vocal_pair` bucket during the one-time review: exact models whose catalogue/configuration evidence says Instrumental become `instrumental`, exact models whose evidence says Vocals become `vocals`, and genuinely neutral first-class pairs become `dual_voc_inst`. Freeze every result by canonical ID; do not implement this wording as runtime inference. For every ordinary `karaoke` declaration, set `full_mix` logical primary to `mix.instrumental_with_backing_vocals` and `vocal_split` logical primary to `vocal.backing`, with explicit `logical_secondary: "vocal.lead"` in both contexts. `vr:UVR-BVE-4B_SN-44100-1` is the exact VR BVE exception and becomes `vocals` with `vocal.backing` primary in both contexts and its distinct BVE complement roles. The distinct `mdx:mbr_bve_gonzaluigi` and `mdx:model_MelBand-Roformer_BVE_by-Gonza` remain ordinary `karaoke` models and follow the same primary/secondary rule.

- [ ] Preserve and reassert Task 2's generic decoupling between logical-primary membership and `selected_by_default`; Task 4 does not relax or introduce that invariant. Continue requiring the declared logical-primary role to occur exactly once in the context. Retain the generic loader tests for both default-true and default-false primaries with no GiantAILAB model-ID branch. Separately assert the reviewed manifest has exactly one default-false logical primary and that it is GiantAILAB's full-mix accompaniment.

- [ ] Pin the independently reviewed final karaoke population in the Task 4 decision fixture now: the frozen starting 28 exact `karaoke` IDs, GiantAILAB, and the ledger-only `mdx:UVR_MDXNET_KARA` promotion decision, for exactly 30 fixture IDs. Assert the two MelBand BVE IDs are included and exact VR BVE is excluded. The Task 4 production manifest is separately interim 29 until Task 5 consumes the already-authored KARA decision. Do not derive this oracle from labels, names, or the edited manifest.

- [ ] Preserve `mdx:mbr_bgm_jasper`'s Vocals/Instrumental route mapping; only migrate its legacy intent to the closed vocabulary.

### Exact model corrections

- [ ] Correct GiantAILAB (`mdx:bs_karaoke_3stem_giantailab`) in both contexts:

  ```text
  vocals         -> vocal.lead
  backing_vocal  -> vocal.backing
  instrumental   -> mix.instrumental
  ```

  Add only in `full_mix`:

  ```json
  {
    "native": null,
    "role": "mix.instrumental_with_backing_vocals",
    "production": "derived",
    "derived_from": ["vocal.backing", "mix.instrumental"],
    "selected_by_default": false
  }
  ```

  Keep the exact native mappings, authored output order, production recipes, and selection defaults unchanged. In `full_mix`, make the derived `mix.instrumental_with_backing_vocals` route logical primary even though it remains `selected_by_default: false`; it is the sole current default-false logical primary, and a normal/default run therefore still schedules only the three native routes. Declare `logical_secondary: "vocal.lead"`, so Secondary Stem Only selects Lead Vocals despite four routes. `pair.karaoke` explicitly selects the combined derived accompaniment first and Lead Vocals second. The `vocal_split` projection exposes the three exact native meanings for identity/audit purposes and does not add the full-mix sum; make `vocal.backing` logical primary, declare `logical_secondary: "vocal.lead"`, and have `vocal_split_pair_routes()` schedule only `vocal.backing` + `vocal.lead`, so the splitter does not write a third Instrumental output.

- [ ] Correct SpeechSep:

  ```text
  mdx:bs_speech_alicen   vocals -> cinematic.speech; derived complement -> mix.music
  mdx:mbr_speech_alicen  vocals -> cinematic.speech; other -> mix.music
  ```

  Both use Speech as logical primary and `specialty_stem` intent. The background music may itself contain singing; do not relabel it Instrumental.

- [ ] Correct all five Bandit Speech/Music/Effects declarations so `effects`/`Effects` maps to `cinematic.sfx`, with Speech logical primary:

  ```text
  mdx:bandit_last
  mdx:bandit_30_zfturbo
  mdx:bandit_57_zfturbo
  mdx:bandit_63_zfturbo
  mdx:model_bandit_plus_dnr_sdr_11.47
  ```

- [ ] Correct the four combined Reverb/Echo models to `effect.reverb_echo` and `.removed`, with the clean/removed route logical primary:

  ```text
  mdx:dereverb-echo_mel_band_roformer_sdr_10.0169
  mdx:dereverb-echo_mel_band_roformer_sdr_13.4843_v2
  mdx:dereverb_echo_mbr_fused
  vr:UVR-DeEcho-DeReverb
  ```

- [ ] Invert the reviewed semantics—not the backend arrays—for all 12 DeReverb declarations so `dry`, `noreverb`, or `No Reverb` is `effect.reverb.removed` (or combined `.removed`), the reverb residual is the base effect role, and the clean route is logical primary:

  ```text
  mdx:MDX23C-De-Reverb-aufr33-jarredou
  mdx:bs_dereverb_2250_anvuew
  mdx:bs_deverb_256_8_anvuew
  mdx:bs_deverb_384_10_anvuew
  mdx:bs_deverb_room_anvuew
  mdx:dereverb-echo_mel_band_roformer_sdr_10.0169
  mdx:dereverb-echo_mel_band_roformer_sdr_13.4843_v2
  mdx:dereverb_mel_band_roformer_anvuew_sdr_19.1729
  mdx:dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050
  mdx:dereverb_mel_band_roformer_mono_anvuew_sdr_20.4029
  mdx:deverb_bs_roformer_8_384dim_10depth
  vr:UVR-De-Reverb-aufr33-jarredou
  ```

- [ ] Change the logical primary to `effect.noise.removed` for `vr:UVR-DeNoise` and `vr:UVR-DeNoise-Lite`; retain their exact native polarity and both default exports.

- [ ] Correct guitar roles:

  - `mdx:mbr_guitar_chencfd`: Guitar / Guitar Removed.
  - `mdx:mbr_lead_rhythm_guitar_listra92`: Lead Guitar / Rhythm Guitar, with Lead Guitar logical primary.

- [ ] Correct Orchestra / Orchestra Removed for:

  ```text
  mdx:bs_orch_xlancer
  mdx:bs_orch2_xlancer
  mdx:mdx23c_orch_verosment
  ```

  In particular, `mdx:mdx23c_orch_verosment` must not call the inverse `Instrumental`.

- [ ] Map ChoirSep native `bass` to `vocal.bass` in both ChoirSep models and use Soprano as logical primary:

  ```text
  mdx:scnet_choirsep_exp
  mdx:scnet_masked_choirsep_exp
  ```

- [ ] Replace source-order logical primaries with exact reviewed primaries. Pin the complete `{model_id: {context: role_id}}` mapping in `stem_manifest_decisions.json`; the following rules describe the approved table but must not become inference code:

  - ordinary Demucs/MDX four-, six-, and full music models containing Vocals -> `vocal.vocals`;
  - Mega Full -> `vocal.vocals`;
  - ordinary karaoke -> `mix.instrumental_with_backing_vocals` primary in `full_mix`, `vocal.backing` primary in `vocal_split`, and explicit `vocal.lead` logical secondary in both;
  - GiantAILAB follows that ordinary-karaoke rule even though its full-mix logical primary is a default-false derived sum;
  - Bandit and `checkpoint-multi_fixed` -> `cinematic.speech`;
  - all DrumSep models -> `instrument.kick`;
  - SCNet Surround -> `cinematic.front_lr` (display `Front L/R`);
  - both ChoirSep models -> `vocal.soprano`; and
  - both Jazz four-stem models -> `instrument.piano`.

- [ ] Run focused manifest/pair tests:

  ```bash
  .venv/bin/python -m unittest -v \
    tests.test_model_stem_manifest \
    tests.test_stem_semantics_remediation \
    tests.test_ensemble_pair_buckets
  ```

- [ ] Commit the reviewed vocabulary/data correction:

  ```bash
  git add bundled/model_stem_manifest.json core/stem_roles.py \
    core/model_stem_semantics.py core/model_stem_manifest.py \
    tests/fixtures/stem_manifest_decisions.json \
    tests/test_model_stem_manifest.py \
    tests/test_stem_semantics_remediation.py tests/test_ensemble_pair_buckets.py
  git diff --cached --check
  git commit -m "fix(stems): correct reviewed catalogue semantics"
  ```

---

## Task 5: Establish exact MDX runtime contracts and replace the 28 waivers

**Files:**

- Create: `bundled/model_runtime_stem_contracts.json`
- Create: `core/mdx_runtime_contract.py`
- Modify: `bundled/model_stem_manifest.json`
- Modify: `core/model_config/config.py`
- Modify: `core/model_stem_semantics.py`
- Modify: `core/catalog_sources.py`
- Modify: `core/stems.py`
- Modify: `scripts/catalogue/collect.py`
- Modify: `scripts/catalogue/render.py`
- Modify: `scripts/catalogue/stem_audit.py`
- Create: `tests/test_mdx_runtime_contract.py`
- Modify: `tests/test_core_model_data.py`
- Modify: `tests/test_model_stem_manifest.py`
- Modify: `tests/test_catalog_sources.py`
- Modify: `tests/test_catalogue_stem_audit.py`
- Modify: `tests/test_mdx_export_routing.py`
- Modify: `tests/test_stem_semantics_remediation.py`

These 28 rows are not one homogeneous “single target” batch. Eighteen are classic ONNX models whose engine exposes a primary and computed inverse under two addressable keys. Four MDX-C checkpoints are true two-output configurations. Six MDX-C/Roformer checkpoints are configured single targets whose semantic inverse is derived. The shared supplement also absorbs the existing one-off `mdx:UVR_MDXNET_KARA_2` classic correction, for 29 contract entries total. Preserve those three runtime classes exactly.

- [ ] Write failing tests for one strict, versioned `bundled/model_runtime_stem_contracts.json` loader. The closed-world root grammar is:

  ```text
  root: schema_version, contracts
  schema_version: exact integer 2 (reject bool, float, string, or another integer; schema 1 is not supported because this internal bundle was strengthened before approval)
  contracts: exact canonical model ID -> contract object
  ```

  Each closed-world contract contains:

  ```text
  backend: classic_onnx | mdx_c_target | mdx_c_multi
  native_signature: list[str] of non-empty ordered exact runtime keys
  primary_native: non-empty str that is one member of native_signature
  config_yamls: list[str] of exact accepted config basenames
  artifact_evidence: list of closed objects:
    uvr_md5: exact lowercase 32-character digest
    hash_record_source: exact durable checked-in source identifier
  config_evidence: exact config basename -> closed object:
    training_instruments: non-empty ordered list[str]
    target_instrument: exact str or null
    content_sha256: exact lowercase 64-character digest
    sources: non-empty list[str] of durable checked-in identifiers or authoritative URLs
  evidence:
    artifact_sources: non-empty list[str]
    runtime_metadata_sources: non-empty list[str]
    review_note: non-empty str
  ```

  All strings are stripped and must already equal their stripped value. Lists preserve authored order and reject exact duplicates; stem/config lists also reject case-fold duplicates. Every config value must be a basename ending in `.yaml` or `.yml` with no directory component, and `config_yamls` must exactly equal the `config_evidence` keys. Enforce runtime-class cardinality: `classic_onnx` has exactly two signature keys, no configs, non-empty artifact evidence, and empty config evidence; `mdx_c_target` has exactly one signature key and one-or-more configs; `mdx_c_multi` has at least two signature keys and one-or-more configs. The evidence objects are closed-world; source entries are exact authoritative URLs or durable checked-in/cache source identifiers, not prose aliases or ignored host paths. Reject duplicate JSON keys, unknown fields at root/contract/evidence levels, invalid backend values, invalid digests, missing durable sources, every cardinality/config-class mismatch, primary/signature disagreement, and any contract ID outside the `mdx:` family. Validate reviewed artifact digests against the checked-in MDX hash mapper. Validate every available checked-in config source against its authored SHA-256 and parsed ordered `training.instruments` plus `target_instrument`; catalogue/runtime reconciliation must require the same exact metadata. Require every contract signature to equal the corresponding semantic-manifest signature by cardinality plus case-insensitive set equality. Preserve stored signature order as the authoritative engine/config output order for reference rendering and deterministic evidence; order alone is not model identity and does not make an otherwise exact manifest match fail.

- [ ] Fail closed at both application boundaries. The strict loader raises a typed contract error; GUI/CLI runtime loading catches it once, logs an actionable warning, installs an empty supplement, and leaves affected models raw rather than crashing startup. Generator write/check treats missing, unreadable, or malformed bundled contract data as degraded/unusable evidence (exit `2`) and publishes nothing.

- [ ] Add immutable `MdxRuntimeContract` and exact lookup/reconciliation helpers in `core/mdx_runtime_contract.py`. Replace `_EXACT_CLASSIC_MDX_RUNTIME_SIGNATURES` and the duplicated `collect.py`/`catalog_sources.py` conditions with this one boundary. Its behavior is:

  - exact canonical ID lookup only;
  - catalogue use is allowed only after the collected primary artifact produced that same canonical ID;
  - installed use validates the computed artifact digest, positive checked-in hash-record provenance, observed hash/config-derived native keys, config basename, config SHA-256, ordered instruments, and target/null against the contract;
  - catalogue use may project reviewed semantics from an exact public artifact/config association but remains explicitly distinct from installed artifact-digest verification;
  - observed metadata wins for engine addressing; disagreement returns the observed signature as raw plus an actionable warning rather than overwriting it;
  - no label, substring, author, family-wide, or filename-similarity fallback; and
  - unknown IDs return no supplement.

- [ ] Have all four consumers use the reconciled result: `runtime_stem_signature()` for audit and TSV rendering, `core/catalog_sources.py` for live Download Center projection, and `ModelConfig`/`_model_native_stems()` for installed models. `core/stems.py` must continue addressing actual installed keys; the contract verifies them and never manufactures keys in an engine source dictionary.

- [ ] Capture the exact classic-ONNX contracts. These are two addressable outputs (`production: native` in the semantic manifest), even though `engines/mdx.py` computes the second array as a complement:

  | Canonical IDs | Exact ordered signature |
  |---|---|
  | `mdx:Kim_Inst` | `Instrumental`, `Vocals` |
  | `mdx:UVR_MDXNET_KARA_2` (already reviewed; preserve rather than promote) | `Instrumental`, `Vocals` |
  | `mdx:Kim_Vocal_1`, `mdx:Kim_Vocal_2` | `Vocals`, `Instrumental` |
  | `mdx:UVR_MDXNET_1_9703`, `mdx:UVR_MDXNET_2_9682`, `mdx:UVR_MDXNET_3_9662`, `mdx:UVR_MDXNET_9482`, `mdx:UVR_MDXNET_KARA` | `Vocals`, `Instrumental` |
  | `mdx:Reverb_HQ_By_FoxJoy` | `Reverb`, `No Reverb` |
  | `mdx:UVR-MDX-NET_Crowd_HQ_1` | `No Crowd`, `Crowd` |
  | `mdx:kuielab_a_bass`, `mdx:kuielab_b_bass` | `Bass`, `No Bass` |
  | `mdx:kuielab_a_drums`, `mdx:kuielab_b_drums` | `Drums`, `No Drums` |
  | `mdx:kuielab_a_other`, `mdx:kuielab_b_other` | `Other`, `No Other` |
  | `mdx:kuielab_a_vocals`, `mdx:kuielab_b_vocals` | `Vocals`, `Instrumental` |

  Record both the exact public artifact association and checked-in hash-metadata primary evidence. At install time, require the downloaded artifact's actual hash record to agree. In particular, do not use the stale Crowd probe that describes target `other`; the reviewed classic contract is exact `No Crowd` / `Crowd`.

- [ ] Capture the four MDX-C multi-output contracts. Both outputs are native and the first is logical primary:

  | Canonical IDs | Config evidence | Exact ordered signature |
  |---|---|---|
  | `mdx:MDX23C-8KFFT-InstVoc_HQ`, `mdx:MDX23C-8KFFT-InstVoc_HQ_2` | `model_2_stem_full_band_8k.yaml`, null target | `Vocals`, `Instrumental` |
  | `mdx:melband_roformer_instvoc_duality_v1`, `mdx:melband_roformer_instvox_duality_v2` | `config_melbandroformer_instvoc_duality.yaml`, null target | `Vocals`, `Instrumental` |

- [ ] Capture the six MDX-C target contracts. The signature contains only the configured target; the manifest declares its inverse with `complement_of`:

  | Canonical IDs | Config evidence | Exact signature |
  |---|---|---|
  | `mdx:melband_roformer_inst_v1`, `mdx:melband_roformer_inst_v2` | exact Inst v1/v2 config association; target `Instrumental` | `Instrumental` |
  | `mdx:model_bs_roformer_ep_317_sdr_12.9755`, `mdx:model_bs_roformer_ep_368_sdr_12.9628` | exact checkpoint YAML; target `Vocals` | `Vocals` |
  | `mdx:model_bs_roformer_ep_937_sdr_10.5309` | exact checkpoint YAML; target `No Drum-Bass` | `No Drum-Bass` |
  | `mdx:model_mel_band_roformer_ep_3005_sdr_11.4360` | exact checkpoint YAML; target `Vocals` | `Vocals` |

  Resolve and record the authoritative YAML evidence before removing each waiver. Known semantically identical config aliases are accepted only when both parsed `training.instruments` and `target_instrument` match the contract exactly. If fresh or matching cached evidence for any checkpoint is unavailable, leave that exact ID waived and stop this task rather than inferring from its display name or community primary.

- [ ] Promote the contracts to semantic declarations with these exact roles and intents:

  - Instrumental optimized (`mdx:Kim_Inst`, both MelBand Inst models): `mix.instrumental` primary / `vocal.vocals`, intent `instrumental`.
  - Vocals optimized (the two Kim Vocal models, four numbered UVR models, two KUIELAB Vocals components, both ViperX 12.9x models, and Mel-Roformer ViperX 11.43): `vocal.vocals` primary / `mix.instrumental`, intent `vocals` except the KUIELAB components, which use `specialty_stem`.
  - Neutral MDX23C HQ and MelBand Duality rows: `vocal.vocals` primary / `mix.instrumental`, intent `dual_voc_inst`.
  - `mdx:UVR_MDXNET_KARA`: preserve the exact ordered native signature and both outputs as native. In `full_mix`, map `Vocals -> vocal.lead` and `Instrumental -> mix.instrumental_with_backing_vocals`, with the latter logical primary and `vocal.lead` logical secondary. In `vocal_split`, map the same exact native keys to `vocal.lead` and `vocal.backing`, with `vocal.backing` logical primary and `vocal.lead` logical secondary. Keep both routes selected by default and use intent `karaoke`.
  - `mdx:Reverb_HQ_By_FoxJoy`: `Reverb -> effect.reverb`, `No Reverb -> effect.reverb.removed` primary; intent `special_fx`.
  - `mdx:UVR-MDX-NET_Crowd_HQ_1`: `No Crowd -> cinematic.crowd.removed` primary, `Crowd -> cinematic.crowd`; intent `specialty_stem`.
  - KUIELAB Bass/Drums/Other components: exact named target and exact `No …` inverse map to the corresponding base/removed roles; named target is primary; intent `specialty_stem`.
  - `mdx:model_bs_roformer_ep_937_sdr_10.5309`: `No Drum-Bass -> instrument.drum_bass.removed`, derived `instrument.drum_bass` primary; intent `drum_bass_sep`.

  For classic and multi-output contracts, both semantic outputs are native. Only the six target contracts use `production: derived` + `complement_of`. Verify and retain the 28 exact promotion decisions already authored in `tests/fixtures/stem_manifest_decisions.json`; do not regenerate them from the new production declarations.

- [ ] Assert 483 declarations, exactly the two Apollo waivers, and exact declaration/waiver disjointness. Define contract parity precisely: the 29 contract IDs equal the exact 28 promotion IDs plus existing `mdx:UVR_MDXNET_KARA_2`; every contract ID is a declaration ID; and each contract signature equals that declaration's signature case-insensitively. For each promoted ID, move the former waiver provenance into its declaration evidence with the runtime-contract source, then delete the waiver key entirely—there is no waiver text left to rewrite.

- [ ] Consume the pre-authored `mdx:UVR_MDXNET_KARA` promotion decision from the Task 4 fixture; do not add or rewrite the fixture ID in this task. Assert the resulting production manifest now equals the fixture's exact 30 `karaoke` canonical IDs. Require `logical_secondary: "vocal.lead"` in both contexts of every ordinary member; keep both MelBand BVE members in the set and exact VR BVE outside it.

- [ ] Test fail-closed runtime behavior for every backend class: expected observed metadata resolves reviewed; wrong casing alone still resolves exact; a missing, changed, expanded, or collapsed observed signature resolves raw with a warning. Exercise classic MDX empty focus, primary-only, inverse-only, Karaoke context, Reverb, Crowd, and every KUIELAB target through the engine export-key path.

- [ ] Test absence prevention explicitly: all 28 promoted IDs appear in `stem_semantics_reference_tsv()`, live `core/catalog_sources.py` projection, and installed-model projection using the same contract; no independent consumer may reimplement the supplement.

- [ ] Run focused contract/promotion/routing tests:

  ```bash
  .venv/bin/python -m unittest -v \
    tests.test_mdx_runtime_contract \
    tests.test_core_model_data \
    tests.test_model_stem_manifest \
    tests.test_catalog_sources \
    tests.test_catalogue_stem_audit \
    tests.test_mdx_export_routing \
    tests.test_stem_semantics_remediation
  ```

- [ ] Commit the evidence contract and exact declarations:

  ```bash
  git add bundled/model_runtime_stem_contracts.json bundled/model_stem_manifest.json \
    core/mdx_runtime_contract.py core/model_config/config.py \
    core/model_stem_semantics.py core/catalog_sources.py core/stems.py \
    scripts/catalogue/collect.py scripts/catalogue/render.py \
    scripts/catalogue/stem_audit.py tests/fixtures/stem_manifest_decisions.json \
    tests/test_mdx_runtime_contract.py tests/test_core_model_data.py \
    tests/test_model_stem_manifest.py tests/test_catalog_sources.py \
    tests/test_catalogue_stem_audit.py tests/test_mdx_export_routing.py \
    tests/test_stem_semantics_remediation.py
  git diff --cached --check
  git commit -m "fix(stems): review exact MDX runtime contracts"
  ```

---

## Task 6: Tighten semantic auditing and remove stale diagnostics

**Files:**

- Modify: `scripts/catalogue/collect.py`
- Modify: `scripts/catalogue/stem_audit.py`
- Modify: `scripts/catalogue/render.py`
- Modify: `scripts/generate_models_catalogue.py`
- Modify: `tests/test_catalogue_stem_audit.py`
- Modify: `tests/test_catalog_sources.py`
- Modify: `tests/test_generate_models_catalogue.py`

- [ ] Add failing collection/render/audit tests for:

  - an unused role (`role-unused`);
  - an intent outside the closed vocabulary;
  - model/waiver overlap;
  - an orphan declaration and orphan waiver relative to the collected snapshot;
  - missing context, duplicate role, invalid logical primary, missing required logical secondary on an ordinary karaoke context, invalid/ambiguous present logical secondary on any context, invalid recipe dependency, and incomplete pair;
  - normalized role-display, filename-tag, and rendered-route collisions;
  - stale logical-secondary data, missing required ordinary-karaoke secondary data, or stale/missing `selected_by_default` reference data; and
  - generated-reference drift without writes under `--check`.

  Define collision scope explicitly. A normalized role-definition collision is two distinct role IDs with the same Unicode-normalized, case-folded `display` or `filename_tag`. A rendered-route collision is two distinct route IDs within the same `(model_id, context)` whose rendered display or filename tag normalizes identically. Repeated `Vocals` labels across different models, or the same role repeated across contexts, are valid and are not collisions.

- [ ] Introduce one immutable `StemSemanticReferenceRow` in `scripts/catalogue/stem_audit.py` containing every identity, context, route, logical-primary/secondary flag, recipe, default, status, and evidence cell needed by the TSV. Extend `StemAuditResult` with its ordered `reference_rows`. Structural audit produces these rows directly from the reconciled snapshot/registry; `scripts/catalogue/render.py` serializes those rows and never resolves declarations a second time. Do not parse rendered TSV text back into diagnostics or infer secondary from row order.

- [ ] Make unused roles a structural publication failure. Derive usage from all context outputs plus the four pair definitions.

- [ ] Align target-model diagnostics with schema-2 recipe semantics:

  - `complement_of` is the only valid one-source mix complement;
  - `derived_from` is a two-or-more-source sum and is not accepted by the target-complement validator; and
  - all recipe dependencies must be present as native roles in the exact context.

- [ ] Reconcile exact reviewed semantics before Markdown or TSV rendering. In `scripts/catalogue/collect.py`, attach exact-ID registry/signature evidence to the collected `ModelEntry`; renderers and the structured audit consume that reconciled entry. For reviewed models, compare the declaration with exact runtime/catalogue signature evidence and do not emit label-keyword guesses as semantic truth. Preserve guessed evidence as an informational audit field for raw/unreviewed entries only; it must never overrule a reviewed declaration.

- [ ] Reorder generator coordination into two validation phases: collect/reconcile once, run all source- and manifest-structural diagnostics, then render every artifact in memory and run internal candidate-parity diagnostics. A structural failure or mismatch between structured rows and rendered candidate bytes blocks every mode and every replacement. On-disk drift is a separate comparison: it returns `1` in `--check`/`--summary`, but is expected and atomically replaceable in write mode after all candidates pass internal validation. Do not collect again between phases.

- [ ] Pin regressions for the three current false positives, which must disappear without a broad substring exception:

  ```text
  vr:3_HP-Vocal-UVR
  vr:4_HP-Vocal-UVR
  mdx:MDX23C_D1581
  ```

- [ ] Keep the exact ten native-to-role ambiguity groups and twenty role-to-native variant groups as informational evidence where they are legitimately model/context-specific. Project them only from successfully reconciled reviewed declarations in the exact collected catalogue; exclude waivers, raw entries, orphans, and `native: null` derived routes, while retaining classic computed inverses because they are addressable native engine keys. Include every explicit context, normalize native keys through `StemId.casefold`, and do not collapse related but distinct roles. The ten exact native groups are `bass`, `dry`, `instrumental`, `lead`, `no dry`, `no reverb`, `other`, `reverb`, `strings`, and `vocals`. The historical six-group count predated required Task 4/5 declarations: KUIELAB instrument Bass versus ChoirSep vocal bass and pure Reverb versus combined Reverb/Echo routes are genuine exact distinctions, not false positives. These groups are not collisions and must not cause the validator to manufacture global aliases.

- [ ] Require summary/check results for the canonical snapshot to report 483 reviewed, 2 waived, 0 raw, 0 structural findings, and 0 accidental collisions. Do not pin a semantic-row count. Instead assert all of these bidirectional parity rules:

  - the semantic TSV model-ID set equals all 485 post-deduplication catalogue IDs;
  - each reviewed declaration emits exactly every declared `(context, output)` row and no others;
  - each waiver emits exactly one waiver row;
  - every output row contains `selected_by_default=true|false`; ordinary karaoke contexts require `logical_secondary` true exactly once and false on peers; other contexts may omit it and render blank cells; waiver rows also render it blank; every complement/sum exactly matches the declaration dependency cells; and waiver rows alone leave all three final cells blank;
  - rendering `StemAuditResult.reference_rows` produces the in-memory candidate bytes exactly; and
  - `--check` compares those candidate bytes separately with the checked-in file to report drift.

- [ ] Preserve the unified generator exit-code contract. `--summary` remains read-only and returns `0` only for a clean snapshot, `1` for drift or semantic findings, `2` for degraded/unusable evidence, and `130` if an opt-in remote confidence audit is interrupted. Add regressions proving summary mode never writes repository files or caches.

- [ ] Update the generator's `--help`/epilog text to describe those summary exit codes; remove the current promise that every successful summary invocation returns `0`. Pin the help wording and all four exits in `tests/test_generate_models_catalogue.py`.

- [ ] Run generator/audit tests:

  ```bash
  .venv/bin/python -m unittest -v \
    tests.test_catalogue_stem_audit \
    tests.test_generate_models_catalogue
  ```

- [ ] Commit audit behavior before regenerating documents:

  ```bash
  git add scripts/catalogue/collect.py scripts/catalogue/stem_audit.py scripts/catalogue/render.py \
    scripts/generate_models_catalogue.py tests/test_catalogue_stem_audit.py \
    tests/test_catalog_sources.py tests/test_generate_models_catalogue.py
  git diff --cached --check
  git commit -m "fix(catalogue): enforce reviewed stem semantics"
  ```

---

## Task 7: Verify every runtime and presentation consumer

**Files:**

- Modify: `tests/test_model_stem_semantics.py`
- Modify: `tests/test_stem_selection.py`
- Modify: `tests/test_ensemble_model_eligibility.py`
- Modify: `tests/test_ensemble_stem_buckets.py`
- Modify: `tests/test_ensemble_collection.py`
- Modify: `tests/test_job_plan_topology.py`
- Modify: `tests/test_stem_only.py`
- Modify: `tests/test_model_picker_records.py`
- Modify: `tests/test_vocal_split_stems.py`
- Modify: `tests/test_ensemble_ui_helpers.py`
- Modify: `tests/test_download_center_stem_refresh.py`
- Modify: `tests/test_export_naming.py`
- Modify: `tests/test_export_stem_label.py`
- Modify: `tests/test_run_estimate.py`
- Modify: `tests/test_cli_list_models.py`
- Modify: `tests/test_catalog_stem_merge.py`
- Prefer adding cross-surface cases to: `tests/test_stem_semantics_remediation.py`

- [ ] Add end-to-end projection tests proving the same native/role/default metadata reaches:

  - catalogue `StemSemanticProjection`;
  - human CLI model details;
  - JSON top-level `logical_secondary_role` and `stem_routes`, including
    `logical_secondary` and `selected_by_default`;
  - primary/secondary stem pickers;
  - ensemble member eligibility and pair filtering;
  - Vocal Splitter route labels;
  - job-plan logical-primary/secondary summaries;
  - Model Test/export filenames;
  - ensemble collection tags; and
  - progress/log stem labels.

  `tests/test_vocal_split_stems.py` and `tests/test_export_naming.py` already contain unrelated worktree edits. Prefer putting cross-surface regressions in `tests/test_stem_semantics_remediation.py`; if a direct fixture must change, stage only the plan-owned hunks and inspect the cached diff.

- [ ] Assert normal two-route models export both sides with empty focus for each intent category (`instrumental`, `vocals`, `dual_voc_inst`, `special_fx`, and `specialty_stem`). This is the regression shield for the earlier inverse-export exclusion.

- [ ] Assert every ordinary karaoke declaration and consumer uses `mix.instrumental_with_backing_vocals` primary plus explicit `vocal.lead` secondary in `full_mix`, `vocal.backing` primary plus explicit `vocal.lead` secondary in `vocal_split`, and exact accompaniment-first `pair.karaoke` role/display order. Primary Stem Only and Secondary Stem Only must resolve those exact declared roles with no order/intent/model-ID inference. Assert the exact VR BVE vocals-intent declaration retains its distinct roles and polarity.

- [ ] Add no-filter/default-export regressions for both ordinary karaoke production layouts: native/native exports both selected routes, and native/derived exports both selected routes. Include each exact MelBand BVE model as its own case and assert the primary/secondary correction neither suppresses a normally selected output nor changes native keys, polarity, production, or output arrays.

- [ ] Assert GiantAILAB behavior across modes:

  | Scenario | Required result |
  |---|---|
  | Empty/default full-mix focus | Lead Vocals, Backing Vocals, Instrumental |
  | Explicit combined focus | Instrumental with Backing Vocals only |
  | Full-mix logical primary | Instrumental with Backing Vocals (`selected_by_default: false`) |
  | Full-mix logical secondary / Secondary Stem Only | Lead Vocals only |
  | `pair.karaoke` ensemble member | Instrumental with Backing Vocals + Lead Vocals |
  | Multi-Stem ensemble member | three native routes; no optional combined route |
  | Vocal Splitter logical-primary projection | Backing Vocals, Lead Vocals, Instrumental; no full-mix sum |
  | Vocal Splitter logical secondary / Secondary Stem Only | Lead Vocals only |
  | Vocal Splitter scheduled exports | Backing Vocals + Lead Vocals only |

  Assert both layers separately: the semantic projection retains the exact Instrumental native key; both contexts explicitly project `vocal.lead` as their sole logical secondary despite having four/three routes; logical-primary status does not enable the default-false full-mix sum during an unfiltered run; and `vocal_split_pair_routes()` excludes Instrumental from execution and never substitutes the full-mix derived accompaniment.

- [ ] Assert SpeechSep models are pair-compatible only where their exact roles satisfy an existing pair. Speech/Music labels must not make them eligible for Vocals/Instrumental or Karaoke.

- [ ] Assert Reverb/Echo, Guitar, Orchestra, Choir, Drum/Bass, and other specialty routes remain selectable in Multi-Stem/explicit focus while no new dual ensemble pair appears.

- [ ] Assert exact native keys still address engine source dictionaries after every role rename. Include mixed casing and prove labels such as `Hi-Hat`, `Orchestra`, and `Reverb/Echo` are never used for backend lookup.

- [ ] Assert existing exact `mbr_bgm_jasper` behavior and the four bundled pair definitions remain stable.

- [ ] Avoid per-widget naming fixes. If a consumer test fails, repair the shared semantic projection/selection boundary unless that surface is demonstrably bypassing it.

- [ ] Add a test-only `UVR_REQUIRE_PRIVATE_GTK=1` guard shared by the direct GTK suites. Under that guard, absence of `Gdk.Display`, a non-`GdkWaylandDisplay`, a display name other than private `codex-gtk`, or a display-related `SkipTest` is a failure. Without the guard, preserve the repository's normal skip behavior for environments intentionally lacking GTK.

- [ ] Run consumer suites. Use the repository's isolated GTK method for GTK-dependent cases if the host lacks a display:

  ```bash
  .venv/bin/python -m unittest -v \
    tests.test_model_stem_semantics \
    tests.test_stem_selection \
    tests.test_ensemble_pair_buckets \
    tests.test_ensemble_model_eligibility \
    tests.test_ensemble_stem_buckets \
    tests.test_ensemble_collection \
    tests.test_job_plan_topology \
    tests.test_stem_only \
    tests.test_model_picker_records \
    tests.test_vocal_split_stems \
    tests.test_ensemble_ui_helpers \
    tests.test_download_center_stem_refresh \
    tests.test_export_naming \
    tests.test_export_stem_label \
    tests.test_run_estimate \
    tests.test_cli_list_models \
    tests.test_catalog_stem_merge \
    tests.test_stem_semantics_remediation
  ```

- [ ] Run the display-backed subset on the private compositor; the bare command above is not sufficient evidence because it may skip these tests. On Claude Code or an already suitable host shell, run:

  ```bash
  /home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh -- \
    env UVR_REQUIRE_PRIVATE_GTK=1 UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest -v \
      tests.test_model_picker_records \
      tests.test_stem_only \
      tests.test_vocal_split_stems \
      tests.test_ensemble_ui_helpers \
      tests.test_download_center_stem_refresh
  ```

  On Codex when AF_UNIX creation is sandbox-blocked, wrap the same runner/command with:

  ```bash
  codex sandbox -C "$PWD" --disable network_proxy -P gtk-headless \
    /home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh -- \
    env UVR_REQUIRE_PRIVATE_GTK=1 UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest -v \
      tests.test_model_picker_records \
      tests.test_stem_only \
      tests.test_vocal_split_stems \
      tests.test_ensemble_ui_helpers \
      tests.test_download_center_stem_refresh
  ```

  Require the runner's own unpiped exit status, `Private Wayland socket: /tmp/codex-gtk.*`, an asserted `GdkWaylandDisplay` named `codex-gtk`, and zero display/GTK skips.

- [ ] Commit only new/changed consumer tests and any proven shared-boundary fix. Do not sweep unrelated UI/CLI files.

---

## Task 8: Regenerate the catalogue snapshot and run complete verification

**Files generated together:**

- Modify: `docs/models-catalogue.md`
- Regenerate: `docs/models-catalogue.ir.json` (gitignored sidecar; verify locally, do not force-add)
- Modify: `docs/model_intent_reference.tsv`
- Modify: `docs/model_display_reference.tsv`
- Modify: `docs/model_stem_semantics_reference.tsv`

### Fresh-source amendment discovered at the publication gate

The 2026-08-26 strict refresh used the newest mvsepless `models.json` and exposed two source-input changes before publication. This amendment is part of Task 8 and must be implemented and reviewed before retrying the generated write:

- [ ] Repair the TRvlvr compact-record evidence parser. Public MDX23C/Roformer lists encode ten exact records as `{checkpoint.ckpt: config.yaml}`. The collector currently scans keys only and drops the YAML scalar, while runtime catalogue code already recognizes this format. Parse a basename-only `.yaml`/`.yml` scalar as the exact config association without changing identity, source priority, or generic dedupe. Build an evidence-only exact index from `other_network_list` for the eight Roformer URL pairs, but never expose that list as selectable models. Join only when both checkpoint and config basenames agree; preserve every Task 5 rejected/unevidenced alias. The exact runtime contract remains the fail-closed authority.
- [ ] Add RED/GREEN coverage for all ten affected canonical IDs, requiring exact non-empty config basename, parsed SHA/instruments/target/primary, reviewed reconciliation, and zero structural findings. Include negative cases for a non-basename scalar, mismatched evidence-only checkpoint/config pairs, and later supplemental records that must not erase the upstream association.
- [ ] Add the repaired current mvsepless identity `mdx:scnet_mid_side_gilliaaan` as a reviewed declaration and independent fixture decision, not a waiver or runtime-contract entry. Pin exact `/scnet/scnet_mid_side_gilliaaan.ckpt`, `scnet_mid_side_gilliaaan_config.yaml`, config SHA-256 `c2b64c62b8485da36f0f2c7f3e6b43cf91f450a89536123cd7d5501be3189378`, ordered native signature `center|wide`, null target, primary `center`, intent `specialty_stem`, `center -> spatial.center`, `wide -> spatial.side`, and logical primary `spatial.center`. Preserve the regression that quarantines the obsolete cross-architecture `/mdx23c/mdx23c_mid_side_gilliaaan.ckpt` record.
- [ ] Advance the final snapshot contract to 486 catalogue IDs, 484 declarations, two Apollo waivers, zero raw IDs, and 515 reviewed contexts. The exact 30-ID karaoke set and every other role/pair/runtime invariant remain unchanged. Historical Task 1–7 checkpoints retain their contemporaneous 485/483/514 counts.
- [ ] Implement this amendment only in the shared catalogue evidence boundary, the one SCNet manifest/fixture decision, their focused tests, and the count assertions/spec text they directly supersede. Do not change runtime-contract data, display aliases, engines, widgets, source priority, or generic dedupe.

- [ ] Run a fresh synchronized write when network/cache evidence is healthy:

  ```bash
  .venv/bin/python scripts/generate_models_catalogue.py --refresh --write
  ```

  If refresh is unavailable or degraded, do not use `--allow-degraded`. Preserve the checked-in artefacts and report the evidence blocker instead of mixing snapshots.

- [ ] Immediately prove matching warm-offline parity and zero drift:

  ```bash
  .venv/bin/python scripts/generate_models_catalogue.py --offline --summary
  .venv/bin/python scripts/generate_models_catalogue.py --offline --check
  ```

- [ ] Inspect the summary for the exact 486 / 484 / 2 / 0 coverage contract, 515 reviewed contexts, exactly 30 fixture-pinned `karaoke` declarations, zero structural findings, zero accidental collisions, and no stale HP Vocals/D1581 mismatch lines.

- [ ] Run the focused semantic/execution/generator suite:

  ```bash
  .venv/bin/python -m unittest -v \
    tests.test_mdx_runtime_contract \
    tests.test_core_model_data \
    tests.test_model_stem_manifest \
    tests.test_model_stem_semantics \
    tests.test_stems_typed \
    tests.test_stem_selection \
    tests.test_mdx_export_routing \
    tests.test_stem_writer \
    tests.test_ensemble_pair_buckets \
    tests.test_ensemble_model_eligibility \
    tests.test_ensemble_stem_buckets \
    tests.test_ensemble_collection \
    tests.test_job_plan_topology \
    tests.test_stem_only \
    tests.test_model_picker_records \
    tests.test_vocal_split_stems \
    tests.test_ensemble_ui_helpers \
    tests.test_download_center_stem_refresh \
    tests.test_export_naming \
    tests.test_export_stem_label \
    tests.test_run_estimate \
    tests.test_cli_list_models \
    tests.test_catalog_sources \
    tests.test_catalog_stem_merge \
    tests.test_catalogue_stem_audit \
    tests.test_generate_models_catalogue \
    tests.test_stem_semantics_remediation
  ```

- [ ] Run scoped Ruff against only touched Python files:

  ```bash
  .venv/bin/ruff check \
    core/stem_roles.py core/model_stem_manifest.py core/mdx_runtime_contract.py \
    core/model_config/config.py core/catalog_sources.py core/stems.py \
    core/stem_selection.py core/catalogue_types.py core/model_stem_semantics.py \
    core/job_plan.py cli/discovery.py ui/views/base.py \
    engines/mdx.py engines/mdx_c.py engines/mdx_c_engine.py \
    scripts/catalogue/collect.py scripts/catalogue/stem_audit.py scripts/catalogue/render.py \
    scripts/generate_models_catalogue.py \
    tests/test_mdx_runtime_contract.py tests/test_core_model_data.py \
    tests/test_model_stem_manifest.py tests/test_model_stem_semantics.py \
    tests/test_stems_typed.py tests/test_stem_selection.py \
    tests/test_mdx_export_routing.py tests/test_stem_writer.py \
    tests/test_ensemble_pair_buckets.py tests/test_ensemble_model_eligibility.py \
    tests/test_ensemble_stem_buckets.py tests/test_ensemble_collection.py \
    tests/test_job_plan_topology.py tests/test_stem_only.py \
    tests/test_method_view_refresh.py tests/test_stem_selection_state.py \
    tests/test_model_picker_records.py tests/test_vocal_split_stems.py \
    tests/test_ensemble_ui_helpers.py tests/test_download_center_stem_refresh.py \
    tests/test_export_naming.py tests/test_export_stem_label.py tests/test_run_estimate.py \
    tests/test_cli_list_models.py \
    tests/test_catalog_sources.py tests/test_catalog_stem_merge.py \
    tests/test_catalogue_stem_audit.py tests/test_generate_models_catalogue.py \
    tests/test_stem_semantics_remediation.py

  .venv/bin/ruff format --check \
    core/stem_roles.py core/model_stem_manifest.py core/mdx_runtime_contract.py \
    core/model_config/config.py core/catalog_sources.py core/stems.py \
    core/stem_selection.py core/catalogue_types.py core/model_stem_semantics.py \
    core/job_plan.py cli/discovery.py ui/views/base.py \
    engines/mdx.py engines/mdx_c.py engines/mdx_c_engine.py \
    scripts/catalogue/collect.py scripts/catalogue/stem_audit.py scripts/catalogue/render.py \
    scripts/generate_models_catalogue.py \
    tests/test_mdx_runtime_contract.py tests/test_core_model_data.py \
    tests/test_model_stem_manifest.py tests/test_model_stem_semantics.py \
    tests/test_stems_typed.py tests/test_stem_selection.py \
    tests/test_mdx_export_routing.py tests/test_stem_writer.py \
    tests/test_ensemble_pair_buckets.py tests/test_ensemble_model_eligibility.py \
    tests/test_ensemble_stem_buckets.py tests/test_ensemble_collection.py \
    tests/test_job_plan_topology.py tests/test_stem_only.py \
    tests/test_method_view_refresh.py tests/test_stem_selection_state.py \
    tests/test_model_picker_records.py tests/test_vocal_split_stems.py \
    tests/test_ensemble_ui_helpers.py tests/test_download_center_stem_refresh.py \
    tests/test_export_naming.py tests/test_export_stem_label.py tests/test_run_estimate.py \
    tests/test_cli_list_models.py \
    tests/test_catalog_sources.py tests/test_catalog_stem_merge.py \
    tests/test_catalogue_stem_audit.py tests/test_generate_models_catalogue.py \
    tests/test_stem_semantics_remediation.py
  ```

- [ ] Run basedpyright on touched production modules:

  ```bash
  .venv/bin/python -m basedpyright \
    core/stem_roles.py core/model_stem_manifest.py core/mdx_runtime_contract.py \
    core/model_config/config.py core/catalog_sources.py core/stems.py \
    core/stem_selection.py core/catalogue_types.py core/model_stem_semantics.py \
    core/job_plan.py cli/discovery.py ui/views/base.py \
    engines/mdx.py engines/mdx_c.py engines/mdx_c_engine.py \
    scripts/catalogue/collect.py scripts/catalogue/stem_audit.py scripts/catalogue/render.py \
    scripts/generate_models_catalogue.py
  ```

- [ ] Run the repository-required project-wide type check, including tests:

  ```bash
  .venv/bin/python -m basedpyright
  ```

- [ ] Run the complete unit suite and final whitespace check:

  ```bash
  .venv/bin/python -m unittest discover -s tests -t . -v
  git diff --check
  ```

- [ ] Review final repository state. Confirm runtime caches/settings/weights, `registered_models.json`, temporary logs/symlinks, unrelated audio fixes, and the pre-existing icon deletion are not staged:

  ```bash
  git status --short
  git diff --cached --name-status
  ```

- [ ] Commit generated artefacts and any remaining verified plan-scoped changes only:

  ```bash
  git add docs/models-catalogue.md docs/model_intent_reference.tsv \
    docs/model_display_reference.tsv docs/model_stem_semantics_reference.tsv
  git diff --cached --check
  git commit -m "docs(models): regenerate reviewed stem catalogue"
  ```

## Completion Criteria

This remediation is complete only when all of the following are simultaneously true:

- the bundled manifest is strict schema 2 and loads without diagnostics;
- all current catalogue IDs are 484 reviewed + 2 Apollo waived;
- the 28 promoted MDX IDs are backed by one shared exact runtime-contract supplement, all 515 reviewed contexts render, and installed metadata disagreement fails raw;
- exact current declarations use only the closed intent vocabulary;
- all approved role IDs, names, removed relationships, logical primaries, optional logical secondaries, and recipes match this plan;
- normal two-sided models still export both sides by default;
- the independent fixture pins exactly 30 final karaoke IDs (starting 28 plus GiantAILAB plus `mdx:UVR_MDXNET_KARA`), including both MelBand BVE IDs and excluding exact VR BVE;
- ordinary karaoke primaries, explicit Lead-Vocals secondaries, and accompaniment-first `pair.karaoke` order are consistent across all consumers without inferred secondary behavior, while the exact VR BVE mapping remains distinct;
- native/native and native/derived ordinary karaoke layouts, including both MelBand BVE models, preserve all no-filter/default exports after the primary/secondary correction;
- GiantAILAB's default-false logical-primary sum behaves correctly in default, explicit-primary, Karaoke-pair, Multi-Stem, and Vocal Splitter flows;
- exactly four ensemble pairs remain;
- runtime/backend identity remains native and immutable;
- unified generated artefacts describe one matching 486-ID snapshot;
- focused tests, private-compositor GTK coverage with no relevant skips, warm-offline generator check, scoped Ruff, scoped formatting, scoped and project-wide basedpyright, full unit discovery, and `git diff --check` all pass; and
- no unrelated worktree state is included in plan commits.
