# Model Identity Refinement

**Date:** 2026-08-21

> **Implementation status — historical delivery record.** The strict-ID
> contract described here is implemented. Read its invariants as current
> behavior; the phase sequence and delivery wording below record the completed
> 2026-08-21 implementation rather than pending work.

This document is the locked product contract for a shared model-identity
pipeline. It supersedes architecture-specific display-to-filename inversion as
the runtime lookup mechanism. The shipped implementation follows these locks;
do not re-open them to preserve old settings, replays, or ensembles.

## Status and decisions

Governing rule: breaking changes to settings files, replays, and ensembles are
acceptable when they simplify the design. Do not keep alias tables, dual JSON
fields, mixed-schema documents, or a migrator for a small existing user base.

Locked:

- One shared identity pipeline. Families remain `vr`, `mdx`, `demucs`,
  `apollo`. Do not split `mdx:` into `roformer:`, `scnet:`, `bandit:`, or
  `mdxc:`.
- Canonical `family:basename` at storage and execution. Runtime never parses
  display text.
- Keep identity and presentation roles distinct: canonical ID, display title,
  catalogue selectable, backend selector, and artifacts. The existing
  `catalog:{family}:{urlencoded(selection)}` form is a Download Center row ID,
  not a runtime model identity.
- No identity migrator and no `identity_schema_version`. Non-canonical stored
  values stay in the file; the GUI shows no selection plus a warning and does
  not write Choose/No Model over them. Readers ignore an obsolete
  `identity_schema_version`; normal writers omit it on their next save.
- No `engine_name` JSON alias. CLI and JSON expose `backend_name` only.
- GUI method/ensemble/karaoke pickers list installed records only, including
  configurable incomplete Demucs `.th`/YAML records. `models list --all-known`
  lists every published `ModelRecord`. Unsupported catalogue rows stay in
  `models catalog`; unsupported Demucs-root `.ckpt` files are validation
  diagnostics, not records or picker entries.
- Visible picker and Download Center titles stay the current canonical/mapper
  strings. Family/basename disambiguators only on multi-family pickers.
- `CatalogueCoordinator` is not re-keyed. Identity reads the existing
  family-split snapshot plus `meta_by_family[family][selection]`; primary family
  maps and the transitional legacy `meta` projection retain their current keys.
- Index construction is offline. YAML fetch may run later on plan, validate, or
  start for that one active model when policy permits. GUI and CLI are online by
  default; relevant CLI commands expose `--offline`.
- Replayable separation, ensemble, and audio manifests use schema 3. Replay
  requires a flat active-path dependency map of canonical IDs plus the active
  model-identity digest. Schema 1/2 and schema-3 manifests missing either field
  are compatibility errors.
- `models download` preserves catalogue-only fuzzy resolution: exact
  `CatalogEntryId`, selectable, or display first, then a unique substring.
  Unknown or ambiguous queries fail; runtime identity resolution stays exact.

Example (Inst HQ 4):

| Name | Value |
|---|---|
| Canonical ID | `mdx:UVR-MDX-NET-Inst_HQ_4` |
| Display | `MDX-Net — UVR-MDX-NET Inst HQ 4` |
| Catalogue selectable | `MDX-Net Model: UVR-MDX-NET Inst HQ 4` |

## Why this refinement is needed

The application already stores canonical IDs in most settings and UI combo
values, but the canonical identity is not carried through execution. Assembly
currently converts a record back to its display value, `ModelConfig` reverses
that value to a filename, and Demucs then parses the display value again to
infer backend behavior. A change in presentation can therefore change, or
break, model selection.

The catalogue projection compounds this problem by indexing every file in a
catalogue entry as though it were independently selectable. That produces
logical duplicates:

- MDX YAML configuration files can appear as model records alongside their
  checkpoint.
- Demucs YAML bags and each of their member weights can appear as separate
  records with the same display label.
- Resolving a Demucs display can select one bag member instead of the parent
  bag.

The architecture-specific behavior is uneven:

| Family | Current strengths | Current gaps |
|---|---|---|
| MDX | Mature mapper and catalogue semantics; checkpoint/config pairing is already understood by runtime configuration. | Catalogue identity still treats configuration filenames as aliases or records, and runtime still reverses display text. |
| VR | Simple one-checkpoint shape and generally stable basename/display mapping. | UI process-method and engine-architecture labels are not normalized at a single boundary; display parsing remains in the path resolver. |
| Demucs | Installed discovery already hides weights owned by local YAML bags. | Version and source layout are inferred from display substrings; canonical em-dash labels do not match the legacy pipe mapper; six-source metadata is not carried into `ModelConfig`; catalogue bag members remain logical duplicates. |
| Apollo | Checkpoint/config registration already uses an explicit engine filename. | It uses the same `engine_name` field with different semantics and should consume the shared record contract. |

Concrete Demucs failure modes include canonical `v1 — Tasnet` and `v2 —
Demucs` displays falling through to the v4 default, legacy models consequently
being searched in `v3_v4_repo`, and `htdemucs_6s` starting with four-source
configuration until inference output happens to correct part of the engine
state. Focused name-resolution tests pass because they cover the helper and the
installed v4 happy path, not the complete identity-to-runtime contract.

## Target contract

Every runtime-selectable model has exactly one immutable logical record:

```text
disk inventory + catalogue + bundled mapper + local registry
                           |
                           v
                    family adapter
                           |
                           v
                     ModelRecord
             /             |             \
        UI / CLI      planning/config      engine loader
       id + label      id + metadata       backend + files
```

The following concepts must remain distinct:

| Concept | Meaning | Persistence |
|---|---|---|
| Canonical ID | Stable application identity, for example `demucs:htdemucs_6s`. | Settings, profiles, ensembles, CLI manifests, and registered-model indexes. |
| Basename | Extension-free logical key used inside the canonical ID. | Embedded in the ID; not separately selected by users. |
| Display | User-facing picker / Download Center title, for example `v4 — htdemucs_6s`. | Catalogue/mapper/registration metadata only; never parsed during execution. |
| Catalogue selectable | Winning family download-list label (long source string). | Catalogue-only join/search value on `CatalogueRef`; accepted by `models download`, never by runtime identity lookup. |
| Backend name | Exact selector passed toward the family loader after resolution. | Derived in the record; reported for diagnostics. Equals basename except Demucs LocalRepo signatures and Apollo filenames. |
| Artifacts | Primary checkpoint/YAML and any supporting files. | Catalogue or registration metadata; installed paths are resolved by the family adapter. |

The existing catalogue-owned `CatalogEntryId(family, selection)` serializes as
`catalog:{family}:{urlencoded(selection)}`. It is the Download Center row ID,
not a `ModelId`, display string, or coordinator map key. Keep that type in
`core/model_catalogue.py`; do not redeclare it in the identity layer.

Required invariants:

1. A canonical ID resolves to at most one record.
2. A logical model produces exactly one record even if it has multiple files.
3. Duplicate display labels are allowed and never make canonical IDs ambiguous.
4. Runtime code does not resolve, normalize, or inspect display labels.
5. An installed record either resolves to a valid primary artifact and complete
   metadata or is explicitly incomplete/unavailable with a diagnostic.
6. Auxiliary files (MDX YAML, Demucs bag members) are never independent runtime
   models. YAML-shaped stored IDs are illegal values, not aliases.
7. Catalogue refreshes or display-label changes cannot alter an existing
   canonical ID.
8. Resolution never replaces an ID-valued settings field with a display,
   backend selector, or filename; those values live only in descriptors and
   per-run configuration.
9. Catalogue refresh must not bump `ModelRepository.inventory_generation`.
10. Unsupported catalogue entries are catalogue rows, not `ModelRecord`s.
    Unsupported Demucs-root `.ckpt` files are artifact diagnostics, not logical
    models.

## Core data model

### Model ID

Retain `ModelId(family, basename)` and its `family:basename` serialization.
Normal parsing must require:

- A recognized, lowercase family: `vr`, `mdx`, `demucs`, or `apollo`.
- A non-empty basename without another colon.
- An exact record ID after parsing. Do not case-fold the basename or apply
  fuzzy matching at this boundary.

Architecture names such as `VR Architecture:...`, raw basenames, displays, and
substrings are not accepted at storage or execution. They remain on disk until
the user re-picks; they are not converted.

### Model record

Expand `ModelRecord` so it owns the values consumers currently reconstruct:

```python
@dataclass(frozen=True)
class ModelArtifacts:
    primary_filename: str
    supporting_filenames: tuple[str, ...] = ()


@dataclass(frozen=True)
class DemucsSpec:
    version: Literal["v1", "v2", "v3", "v4"]
    source_layout: Literal["2_stem", "4_stem", "6_stem"]


@dataclass(frozen=True)
class MdxSpec:
    kind: Literal[
        "classic_onnx",
        "mdx23c",
        "mel_band_roformer",
        "bs_roformer",
        "scnet",
        "scnet_masked",
        "scnet_tran",
        "bandit",
        "bandit_v2",
    ]


@dataclass(frozen=True)
class CatalogueRef:
    family: str
    selection: str  # winning family download-list selectable


@dataclass(frozen=True)
class ModelRecord:
    id: str
    family: str
    basename: str
    display: str
    backend_name: str
    artifacts: ModelArtifacts
    installed: bool
    catalogue_entry: CatalogueRef | None = None
    identity_complete: bool = True
    identity_error: str | None = None
    demucs: DemucsSpec | None = None
    mdx: MdxSpec | None = None
```

`backend_name` means the family adapter's engine-facing selector, not a second
display field. For VR and MDX it is normally the checkpoint stem. For a Demucs
bag it is the bag name; for a standalone repository weight it is the selector
accepted by the local Demucs repository. Apollo retains its filename-based
selector behind the same explicit field. JSON and CLI report `backend_name`
only; do not emit `engine_name`.

`catalogue_entry.selection` is the winning family download-list selectable.
After cutover, download and missing-preset offers start from `family:basename` →
`record.catalogue_entry` → that selectable. List/JSON may omit the selectable
or nest it under `catalogue_entry`. Identity wrappers must not become the
Download Center lookup; that lookup remains the existing `CatalogEntryId` and
`ModelCatalogueService`.

`identity_complete` covers only the fields required to identify and locate a
logical model, including `DemucsSpec` / `MdxSpec.kind`. It does not replace
VR/MDX/Apollo inference-parameter metadata, checkpoint hashing, or the existing
GUI flow for configuring an unrecognized MDX checkpoint. `installed`,
`identity_complete`, and family inference metadata are validated as separate
concerns.

`MdxSpec.kind` is the runnable engine path only. YAML flags (PoPE, HyperACE,
`unwa_inst_large_2`, value residual) are not identity. Unported types
(Medley-Vox, windowed MelBand `mbr_wsa`, BS Conformer) stay unsupported
catalogue rows: not kinds, not picker records. Unknown installed YAML →
`identity_complete: false`.

`ModelRecord.to_dict()` adds `backend_name`, primary/supporting artifact names,
structured Demucs metadata, and `MdxSpec.kind` when present.

### Identity index

Build one immutable index per repository inventory generation and catalogue
revision:

```python
records_by_id: Mapping[str, ModelRecord]
```

There is no `legacy_aliases` map and no `IdentityMigrator`.

Lookup contexts:

| Context | Accepted input | Matching policy |
|---|---|---|
| Runtime, settings, profile creation, replay | Canonical ID or sentinel | Exact `records_by_id` lookup. Anything else is an illegal stored value. |
| Catalogue/UI search | Free text | Search-only label/description matching; the chosen result returns a canonical ID or `CatalogEntryId`. |

Do not reuse search matching for runtime selection.

### Module ownership

Keep responsibilities separated during implementation:

- `core/model_identity.py` owns `ModelId`, record/specification value types,
  strict lookup, and the immutable published index interface.
- A focused `core/model_inventory.py` owns family adapters and merges catalogue,
  installed, bundled, and registered sources. It must not construct
  `ModelConfig`.
- `core/catalogue_coordinator.py` is not re-keyed. It keeps fetch, merge,
  dedupe, SWR, selectable keys, and visible names. Identity reads
  `snapshot.vr` / `snapshot.mdx` / `snapshot.demucs` / `snapshot.apollo`.
  Coordinator work for this refinement is projection-only: add
  `snapshot.meta_by_family[family][selection]` to stop cross-family
  `dict.update` collisions, retain legacy `meta` temporarily for unmigrated
  consumers, and stop treating every YAML or bag-member filename as its own
  identity record (`display_index_*` wrappers or drop those consumers).
  `CatalogEntryId` is a `ModelCatalogueService` / UI row ID, not a coordinator
  map key.
- `core/model_display.py` retains forward display canonicalization for
  catalogue/mapper ingestion. It is not a runtime resolver.
- A focused `core/demucs_registry.py` owns bundled/custom Demucs specification
  loading, validation, locking, and persistence.
- `core/model_config/` consumes already-resolved records and owns mutable
  per-run configuration, paths, hashes, and inference parameters.

This keeps catalogue source merging out of runtime configuration and prevents
the identity module from becoming another general model repository.

## Inventory and catalogue projection

### Projection order

Construct records in this order:

1. Project catalogue entries into logical, not file-level, candidates. Identity
   consumes the existing family-split coordinator snapshot; it does not
   re-key coordinator maps.
2. Scan installed artifacts and join them to candidates by exact family
   artifact rules, creating records for installed models that have no
   catalogue entry.
3. Enrich known models from the bundled mapper/specification table.
4. Apply registered custom-model metadata.
5. Validate uniqueness and identity completeness, then publish the immutable
   index.

Dedupe and precedence operate within a family. A VR and MDX entry with the
same selectable or display must coexist in `meta_by_family` and must not
overwrite one another through the transitional cross-family `meta` projection.
Identity consumers use only `meta_by_family`; preserve the winning selectable
on `catalogue_entry` for forward download lookup.

Installed state wins only for the `installed` flag and resolved local paths.
It must not silently replace catalogue display or structured metadata. Local
registration metadata wins for a registered custom model. A conflict between
two different primary artifacts claiming the same canonical ID makes that
record unavailable and produces a diagnostic.

Join exact filenames first. A case-fold-only match may coalesce catalogue and
installed candidates only when the filesystem is case-insensitive or trusted
catalogue content identity proves that they are the same artifact. On a
case-sensitive filesystem, two installed filenames that differ only by case
remain distinct exact IDs. Never choose one by dictionary insertion order.

The extension-free ID format also means `foo.onnx` and `foo.ckpt`, or legacy
and newer Demucs artifacts with the same basename, can claim the same ID. If
catalogue metadata does not explicitly pair those files into one logical
model, publish an identity-collision diagnostic and make both unavailable
rather than applying the current implicit extension/directory preference. The
user can resolve a custom collision by renaming and re-registering one model.

Preserve cache invalidation through catalogue revision, model-inventory
generation, and naming revision. Parse installed Demucs bags once per inventory
generation rather than rescanning YAML for each lookup.

Identity construction is read-only and offline. It consumes the coordinator's
published snapshot plus bundled/cached metadata and must not refresh the
network, download MDX configuration, hash checkpoints, prompt for model
parameters, register a checkpoint, or write caches. Infer `MdxSpec.kind` from
local evidence only (extension, on-disk YAML, catalogue `model_type`).

`ensure_mdx_c_config` may run later on validate, plan, or start for **that one
active model** when the caller's explicit access policy allows network and
metadata writes. Those paths are online by default. Separation, ensemble,
audio, replay, and model-validation CLI entrypoints expose `--offline` and
thread `allow_network = not args.offline` into planning; GUI starts pass the
online default. A successful fetch invalidates/rebuilds identity state and
re-resolves the active ID before planning continues. An offline miss or failed
download is an actionable configuration diagnostic. Do not fetch YAML while
publishing the identity index.

Identity index publish shares the `ModelRepository.invalidate_models()` lock.
Capture inventory generation, catalogue revision, and naming revision before
building. Publish only if all three still match; otherwise discard and retry.
This prevents a concurrent download or mapper reload from publishing a stale
identity index after invalidation.

### Family rules

#### VR

- The primary artifact is one `.pth` file.
- The canonical basename and normal backend name are the filename without
  `.pth`.
- Catalogue files that are not the primary `.pth` are supporting artifacts or
  ignored metadata, never records.
- Normalize `VR_ARCH_PM` versus `VR_ARCH_TYPE` inside the adapter. Callers must
  not choose between the UI process label and engine architecture.

#### MDX

- Choose `.ckpt` when the entry explicitly pairs it with an MDX-C YAML; choose
  `.onnx` for classic MDX. A catalogue entry containing both without metadata
  that establishes the pairing is invalid instead of first-file-wins.
- Associate YAML files with the checkpoint as supporting configuration.
- Never produce a canonical ID from a YAML configuration basename.
- A stored ID whose basename is a YAML/config name is illegal. Leave it in the
  file; show no selection plus a warning; do not invent a parent checkpoint.
- Preserve native mapper keys for backend lookup; canonical display labels are
  presentation only.

#### Demucs

- If a catalogue or installed unit contains one YAML bag, the YAML stem is the
  canonical basename and its referenced weights are supporting artifacts.
- Otherwise a standalone `.th` or `.th.gz` checkpoint is the logical model.
- A Demucs-root `.ckpt` is not a Facebook Demucs logical model. Exclude it from
  the identity index, GUI pickers, and `models list --all-known`; publish an
  unsupported-format repository diagnostic that `models validate` reports.
  `models configure` cannot make an MSST `.ckpt` load as Facebook Demucs.
- Strip recognized compound suffixes as a unit, so `tasnet.th.gz` does not
  become the canonical basename `tasnet.th`.
- A member weight referenced by a bag is never a record. A stored ID that names
  a bag member is illegal (keep-text + warning), not an alias to the parent
  bag.
- More than one candidate YAML entrypoint in one logical catalogue entry is an
  invalid entry rather than a first-file-wins choice.
- A Demucs record is runtime-eligible only when version and source layout are
  known structurally (`identity_complete`).

Populate `DemucsSpec` using this precedence:

1. Registered custom-model metadata.
2. A versioned bundled `Demucs_Models/model_data/model_specs.json` keyed by
   canonical ID for known official models. Each entry stores its exact
   entrypoint filename, display, version, and source layout.
3. Explicit catalogue metadata.
4. Stem count from trusted catalogue metadata when it is exactly 2, 4, or 6.
   Stem count never overrides registration, bundled specifications, or explicit
   catalogue metadata.
5. Strict catalogue-label import at index construction, limited to the exact
   `Demucs vN: name` or `vN | name` forms (N in 1–4). No hyphen-as-separator,
   no substring.

Label import is an ingestion step at index construction, not runtime parsing
and not settings migration. If a version or source layout remains unknown, keep
the installed model selectable in GUI pickers with `identity_complete: false`
and a persistent warning banner, but reject planning or execution with the
missing field named in the error. Do not default to v4/four-stem.

Keep `model_name_mapper.json` as a display source for ingestion. It is not the
authoritative version/layout database. Seed the bundled specification file into
the writable data tree through the existing model-data initialization path, and
validate that mapper keys and official specification entrypoints do not drift.

#### Apollo

- Preserve the current checkpoint/config pairing and hash-backed local
  metadata.
- Express its loader filename through `backend_name` and its checkpoint/config
  through `ModelArtifacts` so callers no longer special-case `engine_name`.

### Artifact-path safety

Validate primary and supporting artifact names before putting them in a
record. Reject absolute paths, `..`, empty components, unexpected family
subdirectories, and resolved paths outside the configured model root. For
installed paths, resolve symlinks and verify containment before hashing or
loading. Catalogue display labels and registration metadata must never become
filesystem paths.

## Runtime data flow

`ModelIdentityService.resolve()` parses a canonical ID and returns its record.
It does not accept a `fuzzy` option. Family constraints validate the resolved
record after ID parsing rather than prefixing an unqualified input.

Planning and assembly then carry that record forward:

1. `JobResolver` fills `model_dependencies: Mapping[str, str]` with exact
   canonical IDs **only when those paths are active**. Active + missing or
   ineligible is a planning diagnostic, never a silent `None`.
2. `ModelDescriptor` is built directly from the record, including display,
   backend name, artifact identity, and Demucs/MDX topology.
3. `assemble_model` passes the resolved record or equivalent immutable identity
   fields into `ModelConfig`.
4. The family adapter resolves the installed primary path from the artifact
   name and version-specific directory.
5. Engines receive backend selectors, paths, and structured metadata. They do
   not invoke display-name helpers.

Active settings paths:

- `vr.model`, `mdx.model`, `demucs.model`
- indexed ensemble members such as `ensemble.selected_models[0]`
- twelve secondary slots: `{vr,mdx,demucs}.{voc_inst,other,bass,drums}_secondary_model`
- `process.vocal_splitter`
- `demucs.pre_proc_model`
- `audio_tools.apollo_model`

When secondary is enabled and the run is 4-stem or multi-stem Demucs, the map
includes all four non-sentinel family secondary slots. A 2-stem run includes
only the slot for the primary stem.

`AudioJobResolver` owns `audio_tools.apollo_model`. Do not mutate that field to
`backend_name` or `engine_name`.

Dependency keys are stable dotted settings paths, with zero-based brackets for
list members. Values are canonical IDs. Do not substitute display labels,
backend names, filenames, or catalogue row IDs. Serialize keys in lexical order
for deterministic plans and manifests.

`process_determine_secondary_model`, `process_determine_vocal_split_model`, and
`process_determine_demucs_pre_proc_model` consume the dependency map rather than
creating a new identity service and converting the ID back to display text.
Keep the existing family/applicability constraints on every path. Swallowing
`ValueError` and returning `None` is forbidden for an active path.

Vocal splitter identity is an exact `vr:` or `mdx:` ID. Karaoke/BV eligibility
is a **planning** check. Remove substring fallback in
`resolve_splitter_identity`.

Extend `ModelDescriptor` with `backend_name`, artifacts, optional `DemucsSpec`,
and optional `MdxSpec`, and serialize the complete dependency map as canonical
IDs in job plans and manifests. Runtime may build mutable `ModelConfig`
instances per run, but all identity decisions are complete before that
construction begins.

Every prepared plan also carries `model_identity_digest`. Compute it as SHA-256
over canonical JSON containing the lexically sorted active dependency paths and,
for each referenced record, its canonical ID, family, backend name, primary and
supporting artifacts, `DemucsSpec`, and `MdxSpec`. Exclude display,
catalogue-facing text, installed paths/state, and unrelated records. Before
start, re-resolve the dependency map and recompute the digest; a mismatch makes
the plan stale. A display-only change or a semantic change to an unused model
must not invalidate it. This supplements rather than replaces the existing
inventory-generation and checkpoint-hash guards.

Do not mutate the resolved settings snapshot from an ID to an engine value
during assembly.

Add explicit identity fields to the model-configuration base:

- `canonical_id`
- `model_display_label`
- `backend_name`
- `model_artifacts`
- canonical engine architecture

Do not keep `model_name` as a dual-meaning field that engines parse for display
prefixes, mapper values, `UVR_Model`, or `htdemucs_6s`. Diagnostics use the
carried display label; backend caches use the carried backend name or basename.

Audit every current reverse-display consumer, including engine base setup,
run hooks/loop, separator salvage reporting, error context, model-parameter
dialogs, dry inspection, Apollo setup, and nested model factories.

After cutover, an AST/import guard forbids runtime modules from calling
display-to-basename resolvers. Allowlist: `core.model_display`, tests, and
catalogue scripts. Forbidden: engines, `model_config`, `job_plan`, assemble,
determine, run_hooks, CLI job paths. There is no `identity_migration` module
in this story.

For Demucs, `get_demucs_model_data()` becomes assignment from `DemucsSpec`:

- `version` selects the legacy directory or `v3_v4_repo`.
- `source_layout` selects the existing two-, four-, or six-source list and
  mapper constants before planning.
- The primary artifact selects the exact entrypoint.
- The engine may validate actual inference output against the declared layout,
  but must not silently rewrite the declared identity metadata.

## Display and UI behavior

Display formatting is one-way:

```text
ModelRecord.display -> combo label / plan / log / report
```

Delete runtime uses of `display -> mapper key -> basename`. Keep small
forward-formatting helpers for catalogue/mapper ingestion. Visible method
picker and Download Center titles stay the current canonical/mapper strings,
including MDX prefix stripping (`MDX-Net Model:` / `Roformer Model:` and
similar). `family:basename` and `catalog:family:…` are stored ids only.

Populate model controls from records as stable triples and sort without an
inverse display dictionary:

```python
(record.id, record.display, record.family)
```

Preserve SDR-aware ordering by sorting records alongside their score inputs;
use `(display.casefold(), id)` as the deterministic tie-breaker. Never rebuild
the record list through `{display: basename}`, which drops duplicate labels.

The stored combo value remains the ID. Duplicate labels stay as separate rows.
Where a picker can contain more than one family (ensemble), append the family
or basename only as a visual disambiguator without changing `record.display` or
persisted state. Do not add that disambiguator on the MDX tab.

GUI method, ensemble, and karaoke combos list **installed `ModelRecord`s only**
(`inventory_generation`), including configurable incomplete Demucs `.th`/YAML
records. Uninstalled catalogue rows and unsupported Demucs-root `.ckpt` files
stay out of those pickers. `uvr models list --all-known` lists every published
`ModelRecord`; unsupported catalogue rows stay in `models catalog`, and
unsupported installed files stay in validation diagnostics.

Incomplete Demucs rows are selectable. The method page shows a persistent
warning banner until configured. Planning fails with a named missing field if
the user starts anyway. There is no GTK configure form in this spec. Recovery
is `uvr models configure` / `register`. Parked for later: reuse the
unrecognized-checkpoint model-parameter dialog with version/layout fields.

Incomplete MDX keeps the existing unrecognized-checkpoint parameter dialog.
Demucs stays banner plus CLI.

A stored non-canonical string is left in the file. The combo shows no
selection plus a warning. `populate_models` must not `resolve` then `set_flat`
a canonical ID or Choose/No Model default over that value on window load or
picker refresh.

Saved user ensembles and curated bundled presets must contain canonical IDs.
Validate curated presets with a repository test/build check. Do not retain
runtime `canonical_id_from_member_tag()` display parsing. Missing curated
members use the record's `catalogue_entry` link for the download offer. If a
bundled preset still contains a display tag, fix the bundled data.

Download Center rows use the existing `CatalogEntryId(family, selection)`.
`models catalog --query` stays free text. `models download` preserves current
catalogue resolution: exact row ID, exact selectable/display, then a unique
substring match. Unknown or multiple matches fail and list candidate row IDs.

## Custom Demucs registration

### Registration input

`uvr models register CHECKPOINT --family demucs --config CONFIG.json` requires
the config. The minimal schema is:

```json
{
  "demucs_version": "v4",
  "source_layout": "6_stem",
  "display_name": "My six-source Demucs model"
}
```

Validation rules:

- `demucs_version` is required and must be `v1`, `v2`, `v3`, or `v4`.
- `source_layout` is required and must be `2_stem`, `4_stem`, or `6_stem`.
- `display_name` is optional, must be a non-empty string when present, and
  defaults to the canonical basename.
- The user cannot provide a separate ID or backend name. Both derive from the
  validated entrypoint so they cannot drift apart.
- v1/v2 accept direct `.th` and `.th.gz` checkpoints and install into the
  legacy Demucs directory.
- v3/v4 accept direct `.th` checkpoints or `.yaml` bags and install into
  `v3_v4_repo`.
- A YAML bag must contain a non-empty `models` list. Every signature must match
  exactly one adjacent `signature-*.th` weight; missing or ambiguous members
  reject the registration.
- v3/v4 weight filenames must follow the local Demucs repository contract:
  either `signature.th` or exactly one `signature-checksum.th` suffix pair.
  Validate a declared checksum against the file before registration, and set
  `backend_name` to the signature consumed by `LocalRepo`. Reject filenames
  with multiple hyphen splits instead of deferring a loader crash.

### Stored registration metadata

Add an atomically written registry at:

```text
Demucs_Models/model_data/registered_models.json
```

Use a versioned document keyed by canonical ID:

```json
{
  "schema_version": 1,
  "models": {
    "demucs:my_model": {
      "display_name": "My model",
      "backend_name": "my_model",
      "entrypoint": "v3_v4_repo/my_model.yaml",
      "supporting_artifacts": [
        "v3_v4_repo/abc12345-checksum.th"
      ],
      "primary_hash": "...",
      "demucs_version": "v4",
      "source_layout": "4_stem"
    }
  },
  "by_primary_hash": {
    "...": "demucs:my_model"
  }
}
```

Paths are normalized relative to the Demucs model root and must remain inside
it. `models` is authoritative and `by_primary_hash` is a validated reverse
index in the same locked document. Demucs registration does not also update the
existing global registered-hash file; that file remains the authority for
VR/MDX/Apollo. Keeping Demucs metadata and duplicate detection in one atomic
JSON replacement avoids an unrecoverable half-commit between two indexes.

Use the existing UVR checkpoint fingerprint for `primary_hash` so duplicate
reporting remains compatible with current CLI behavior. Validation also
re-parses a YAML entrypoint and checks that every recorded/referenced member is
present; member content hashing is not required for model identity.

Registration is a failure-safe operation with the registry committed last:

1. Validate configuration, entrypoint, bag membership, destination paths, and
   all collisions before copying.
2. Copy every artifact to temporary files in the destination directory.
3. Promote the complete artifact unit.
4. Under the registry lock, recheck collisions and atomically replace the
   single Demucs registry with both forward and reverse entries.
5. Invalidate the model inventory only after the registry is durable.
6. On an ordinary failure, remove only artifacts and metadata created by this
   command. If the process crashes after artifact promotion but before the
   registry commit, discovery exposes an unconfigured/unavailable custom model;
   rerunning registration or configure is the supported recovery path.

For recovery, register may adopt an existing destination only when every
source/destination artifact fingerprint matches and no registry entry claims a
different ID. A different file remains a hard collision. Configure may attach
metadata directly to the incomplete installed ID after validating the same
artifact rules.

Extend `models configure demucs:ID --config ...` to update the registered
specification. A version change is allowed only when the existing entrypoint is
already in the directory for that version; configuration must not implicitly
move a model. Reset removes local metadata, after which an otherwise unknown
custom model remains installed but unavailable until configured again.

Existing releases may have Demucs hashes in the global registered-model index
without version/layout metadata. Treat the new Demucs registry as
authoritative. If the old canonical ID and installed artifact match a bundled
or catalogue specification, copy a complete entry into the Demucs registry.
Otherwise keep the artifact visible with `identity_complete: false` and tell
the user to run `models configure demucs:ID --config ...`; do not infer the
missing source layout from its name or directory.

## Strict-ID cutover

There is no identity migrator and no `identity_schema_version` field in this
story. Format readers ignore an obsolete field, and normal writers omit it on
the next save without converting model values. The completed delivery removed
`core/identity_migration.py`, the settings dataclass/default field, ensemble
emission, and the UI migration hooks.

Validation is deliberately two-stage because settings load before the lazy
repository is available:

1. The format reader checks each model-valued string for canonical
   `family:basename` syntax and a recognized family, or a permitted sentinel.
   It preserves an illegal value verbatim and records a validation warning.
2. After repository binding, validate exact record existence, installed state,
   `identity_complete`, and eligibility for that particular settings path.

A non-canonical string, including a display, unqualified basename,
architecture-prefixed tag, YAML/config name, or Demucs bag member, stays in the
document. GUI: no selection plus a warning; do not write Choose/No Model. CLI:
fail with `expected canonical model ID family:basename` and point to
`uvr models list` or `uvr models catalog`.

Use a format-specific reader for each persisted shape so sparse documents are
not inflated:

- Main settings and settings-shaped GUI profiles validate nested primary,
  secondary, splitter, pre-process, Apollo, and ensemble fields through
  `Settings`.
- Sparse CLI profiles under `profiles/cli` are traversed explicitly. Validate
  top-level `model`, every `members` entry, and model-reference values inside
  the sparse `settings` mapping without converting the document to a full
  settings payload. Never run `Settings.from_json_dict` on a sparse CLI
  profile.
- Saved ensemble documents validate `selected_models` while preserving their
  ensemble fields and schema.

Do not recursively treat arbitrary JSON under the profile root as a settings
document.

After the cutover:

- `models show`, ID-targeted `validate`, and `configure` accept canonical IDs
  only. An untargeted `models validate` also reports unsupported installed
  artifacts, including Demucs-root `.ckpt` files.
- `models catalog --query` remains free-text because it is search, not identity
  resolution.
- `models download` remains catalogue-facing and accepts an exact
  `CatalogEntryId`, exact selectable/display, or one unambiguous fuzzy match.
- New profiles, ensemble definitions, and replay-generated temporary profiles
  contain IDs.
- A bare model name supplied to a runtime identity argument is rejected.

## CLI and reporting changes

`uvr models list --all-known` reports one row per published `ModelRecord`.
Unsupported catalogue entries, Demucs bag members, MDX configuration files, and
unsupported Demucs-root `.ckpt` artifacts are not rows. The unsupported
catalogue entries remain available through `models catalog`; unsupported local
artifacts are available through `models validate`. Add these stable fields to
human/JSON detail output:

- `id`
- `family`
- `display`
- `backend_name`
- `primary_artifact`
- `supporting_artifacts`
- `installed`
- `identity_complete`
- `identity_error`, when applicable
- `demucs_version` and `source_layout` for Demucs
- `mdx_kind` for MDX when known

Fix dry model inspection to use the canonical engine architecture from the
record. A VR display/process-method label must never reach `ModelConfig` as the
architecture selector.

Internal missing-model offers follow `ModelRecord.catalogue_entry` instead of
reverse-searching by display. User-supplied `models download` references retain
the catalogue-only resolution policy above. Downloading a Demucs bag installs
one artifact unit and invalidates the inventory once.

All replayable separation, ensemble, and audio manifests use
`"schema_version": 3`. Bench output is not replayable and is outside this
cutover. Schema 3 requires these top-level fields even when a command has no
active model dependency:

```json
{
  "schema_version": 3,
  "model_dependencies": {
    "ensemble.selected_models[0]": "mdx:UVR-MDX-NET-Inst_HQ_4",
    "process.vocal_splitter": "vr:UVR-De-Echo-Normal"
  },
  "model_identity_digest": "sha256:..."
}
```

`model_dependencies` is `{}` only when the command genuinely has no model
dependency. Replay accepts schema 3 only, requires the map and digest, validates
every ID against the family/field constraint, recomputes the active dependency
digest, and then produces its temporary sparse profile. Schema 1/2 and malformed
schema-3 manifests fail as compatibility errors without fuzzy lookup. Preserve
the existing explicit `--allow-model-change` escape hatch: when supplied, it
may accept both checkpoint-hash and active semantic-digest changes, and the JSON
result reports the recorded and current values. It never enables fuzzy ID
resolution or bypasses schema/field validation.

Update `docs/cli.md`, `docs/environment.md`, `docs/models.md`, and catalogue
documentation to distinguish IDs, displays, selectables, backend names, and
artifacts. Document that legacy settings/ensembles/replays are not converted
and that the user must re-pick models.

## Historical implementation sequence

### Phase 1: Lock regressions and contracts

- Add failing inventory-cardinality fixtures for MDX checkpoint/YAML entries
  and Demucs YAML/member entries.
- Add end-to-end failures for canonical v1/v2 Demucs labels, version-specific
  directories, UVR two-source models, and `htdemucs_6s`.
- Add strict-ID tests before changing resolver behavior. Do not add a
  migration-alias suite.
- Add sparse CLI-profile, saved-ensemble, curated-preset, nested dependency,
  and replay fixtures so every persisted/reference shape is represented.
- Lock current catalogue download matching: exact row ID/selectable/display,
  unique substring fallback, and explicit ambiguity failure.
- Lock schema-3 `model_dependencies` path keys and active semantic-digest
  fixtures before changing manifest writers.
- Snapshot current CLI JSON fields so dropping `engine_name` is deliberate.

### Phase 2: Build the logical identity index

- Introduce artifact, `DemucsSpec`, and `MdxSpec` types.
- Seed bundled official `DemucsSpec` data (`model_specs.json`) with the index.
- Add `snapshot.meta_by_family[family][selection]`, consume it from identity,
  and retain legacy `meta` temporarily for unmigrated consumers; stop file-level
  `display_index_*` identity.
- Coalesce installed bag members and MDX configuration files into their parent
  records.
- Keep unsupported catalogue entries in `ModelCatalogueService` only. Publish
  unsupported Demucs-root `.ckpt` files as validation diagnostics, not records.
- Add explicit case/extension collision diagnostics and safe artifact-path
  validation.
- Publish the immutable ID index under existing repository invalidation rules,
  with generation-checked publication and no network or metadata writes.

Keep compatibility wrappers for the current `*_catalogue_display_index()`
methods only while consumers move. Wrappers may expose primary basenames but
must not recreate support-file records.

### Phase 3: Carry identity through planning and execution

- Make `JobResolver`, `ModelDescriptor`, and `assemble_model` carry resolved
  identity fields.
- Resolve and carry every primary, indexed ensemble, secondary, splitter,
  pre-process, and Apollo dependency in the flat stable-path map.
- Compute `model_identity_digest` from only the active dependency records and
  reject a stale plan before start. Display-only and unrelated record changes
  do not change the digest.
- Thread explicit network policy through validation/planning. If allowed, fetch
  one active model's missing MDX YAML, rebuild identity, and re-resolve it.
- Change family path resolution to consume record artifacts/backend names.
- Replace Demucs display parsing with `DemucsSpec` assignment when the spec is
  present (official v1/v2/6-stem work). Incomplete records stay selectable and
  fail at planning.
- Normalize VR method/architecture aliases at the adapter boundary.
- Change engine logging and output naming to consume `model_display_label`
  without recomputing it.

### Phase 4: Add Demucs registration metadata

- Extend `ModelRegistryService` with the versioned Demucs registry.
- Implement direct-checkpoint and complete-bag validation/copy transactions.
- Extend register/configure/reset and inventory invalidation.
- Surface incomplete or changed artifacts through validation and CLI detail
  output. Custom Demucs registration stays in this phase.

### Phase 5: Strict persistence and UI

- Validate settings, GUI profiles, sparse CLI profiles, and saved ensembles
  in two stages: syntax/family at read time, then repository existence,
  installation, completeness, and field eligibility. Leave illegal strings in
  place.
- Remove the identity migrator, settings/default version field, ensemble
  emission, and UI migration hooks. Ignore old `identity_schema_version` input
  and drop it on the next normal save.
- Gate picker writes so `populate_models` cannot overwrite an unresolved stored
  value.
- Populate/sort pickers directly from installed records and preserve duplicate
  displays.
- Keep configurable incomplete Demucs `.th`/YAML records selectable with a
  warning. Exclude Demucs-root `.ckpt` files and surface them through
  `models validate`.
- Incomplete MDX: keep the unrecognized-checkpoint dialog.
- Switch runtime CLI identity arguments and profile validation to strict IDs;
  preserve catalogue-only fuzzy matching for `models download`.
- Convert/validate curated presets as canonical build-time data.
- Add default-online/`--offline` policy to separation, ensemble, audio, replay,
  and model validation.
- Emit schema 3 for replayable manifests, with the required flat dependency map
  and active identity digest; replay rejects schema 1/2.
- Extend replay's explicit `--allow-model-change` override to hash and semantic
  digest changes without weakening exact-ID or schema validation.

### Phase 6: Remove reverse resolution and document the cutover

- Remove fuzzy runtime resolution and display-to-basename helpers after all
  callers have moved. Keep fuzzy matching confined to catalogue search/download.
- Retain only forward display formatting for catalogue/mapper ingestion.
- Add an architecture guard that forbids runtime display-to-basename imports
  (allowlist as specified above).
- Update CLI/environment/model documentation and active architectural guidance.

## Test matrix and acceptance criteria

### Identity and catalogue

- A synthetic VR entry yields one checkpoint record.
- A synthetic MDX checkpoint plus YAML yields one checkpoint record and one
  supporting artifact.
- A synthetic Demucs YAML plus multiple member weights yields one bag record.
- A standalone Demucs weight remains independently selectable.
- An unsupported Demucs-root `.ckpt` produces a stable `models validate`
  diagnostic, is absent from the identity index, pickers, and `--all-known`, and
  never reaches the Facebook Demucs loader.
- Unsupported catalogue entries remain visible through `models catalog` with
  support diagnostics but never become `ModelRecord`s.
- Identical raw catalogue labels in two families remain separate
  family-qualified catalogue entries and model records, with distinct
  `meta_by_family` values.
- Duplicate displays retain distinct IDs and resolve correctly by ID.
- Exact-case catalogue and installed forms of the same model coalesce.
- A case-only join coalesces only on a case-insensitive filesystem or with
  trusted content identity; two real case-distinct files remain distinct.
- Same-basename MDX extensions and cross-directory Demucs collisions become
  explicit unavailable records instead of silently choosing one.
- A concurrent catalogue refresh or model invalidation cannot publish an index
  built from the old generation.
- Identity enumeration performs no network requests, downloads, hashes,
  prompts, registration, or metadata writes.
- Bundled Demucs specifications cover every official mapper entry and agree on
  entrypoint, version, and layout.
- Catalogue refresh does not bump `inventory_generation`.
- Catalogue ID construction uses the existing `CatalogEntryId.selection` field
  and wire encoding.

### Runtime

- Every complete installed record round-trips from ID to record to an existing
  primary path.
- Changing a record's display fixture does not change path, version, topology,
  or loader selector.
- VR dry inspection uses the engine architecture and does not fail with an
  unset model path.
- MDX-C loads its checkpoint and associated YAML without a configuration record
  appearing in inventory.
- With network allowed, a missing active MDX YAML is fetched once, identity is
  rebuilt, and the same canonical ID is re-resolved. `--offline` performs no
  request and returns an actionable configuration diagnostic.
- Demucs v1/v2 resolve into the legacy directory; v3/v4 resolve into
  `v3_v4_repo`.
- Demucs two-, four-, and six-source specs reach planning, stem selection,
  engine routing, and export descriptors unchanged.
- Enabled secondary, vocal-splitter, and Demucs pre-process IDs resolve into
  the same dependency map and remain independent of display changes.
- An enabled missing or family-ineligible nested dependency fails planning
  instead of being silently omitted.
- Planning leaves primary, nested, ensemble, and Apollo settings fields as
  canonical IDs; backend names appear only in descriptors/configurations.
- The flat dependency map contains every active path, uses indexed ensemble
  keys, sorts deterministically, and never contains a display or backend name.
- Changing an active record's backend/artifact/Demucs/MDX semantics changes
  `model_identity_digest` and stales the plan. Display-only and unrelated model
  changes leave the digest valid.
- Actual Demucs inference output with a source count different from metadata
  fails with an actionable compatibility error.
- Vocal-splitter resolution is exact `vr:` / `mdx:` ID; substring matching is
  gone.
- 4-stem/multi-stem Demucs with secondaries maps all four non-sentinel slots;
  2-stem maps only the primary-stem slot.

### Registration

- Demucs registration without config fails before copying.
- Invalid versions, layouts, extensions, paths, and display values fail before
  copying.
- Invalid v3/v4 repository filenames and checksum suffixes fail before
  copying.
- A direct checkpoint registers, survives repository reconstruction, and
  resolves by its returned ID.
- A complete YAML bag copies and registers all members as one unit.
- Missing/ambiguous members and destination collisions leave no partial files
  or registry entries.
- `models validate` detects missing or inconsistent YAML bag members.
- A simulated crash boundary cannot leave Demucs metadata split across two
  authoritative indexes; promoted-but-unregistered artifacts are recoverable
  through register/configure.
- Registration adopts content-identical orphan destinations but rejects a
  different file at the same destination.
- Configure/reset obey replacement flags and never move artifacts implicitly.
- Unknown globally indexed Demucs registrations remain visible and explicitly
  require configuration.

### Persistence and UI

- Non-canonical stored values remain in the file; the combo shows no selection
  plus a warning; Choose/No Model is not written over them.
- Read-time validation catches malformed/family-invalid IDs without requiring a
  repository; repository binding catches missing, uninstalled, incomplete, and
  field-ineligible records without rewriting stored text.
- An obsolete `identity_schema_version` is ignored on read and absent after the
  next normal save; no model value is migrated as a side effect.
- Sparse CLI-profile validation preserves top-level model/member identity,
  sparse settings, profile schema, and nonidentity fields, and never inflates
  the document through `Settings.from_json_dict`.
- Curated presets pass a static canonical-ID check and missing-member downloads
  use catalogue links rather than display inversion.
- Duplicate labels remain separate rows, and selecting either persists its
  exact ID.
- Refreshing display/catalogue metadata does not change the selected ID.
- GUI pickers contain installed records only; `--all-known` contains every
  published `ModelRecord` and no unsupported catalogue, MDX config, Demucs
  member, or unsupported Demucs-root `.ckpt` rows.
- Incomplete Demucs is selectable with a warning banner; planning names the
  missing field.
- Visible picker and Download Center titles match current canonical/mapper
  strings.

### CLI and compatibility

- Bare basenames and displays are rejected by runtime model arguments with the
  documented discovery hint.
- `models catalog --query` continues to accept free text.
- `models download` accepts exact row ID/selectable/display or one unique fuzzy
  match and rejects ambiguous queries with candidate row IDs.
- Human and JSON output agree on backend names, artifacts, metadata status, and
  Demucs topology. There is no `engine_name` field.
- Separation, ensemble, and audio manifests use schema 3 and always contain the
  flat `model_dependencies` map plus `model_identity_digest`; replay rejects
  schema 1/2 and malformed schema 3 without fuzzy lookup. Bench output is
  unchanged.
- `--allow-model-change` permits recorded hash/digest drift and reports it, but
  cannot admit a missing dependency, wrong family, illegal ID, or old schema.

## Delivery gates

After each phase, run the focused identity, model-display, catalogue,
model-config, Demucs, CLI discovery, and job-planning unit tests plus
basedpyright. Before completion, also run:

- The complete unittest suite in the repository's known-good GTK/Wayland
  environment.
- Targeted GTK model-picker tests, including the keep-text write-gate.
- Offline/network-denial tests for identity construction and `--offline`
  validate/plan/start paths, plus an allowed one-model YAML-fetch test.
- CLI human/JSON contract tests.
- `git diff --check` and repository import/architecture guards.

The refinement is complete only when all complete installed models resolve from
their canonical ID without inspecting display text, every catalogue entry has
the expected logical cardinality, and the Demucs version/source-layout matrix
is correct before engine inference begins.

## Explicit non-goals

- Splitting `mdx:` into architecture-specific family prefixes.
- Adding an identity migrator, `identity_schema_version`, alias tables, or an
  `engine_name` JSON compatibility alias.
- Re-keying `CatalogueCoordinator` maps.
- Removing the transitional legacy `CatalogueSnapshot.meta` projection before
  its unrelated consumers migrate; identity itself uses `meta_by_family` only.
- Changing the visible naming style of VR or MDX picker / Download Center
  titles beyond using the canonical display already supplied by
  catalogue/mapper metadata.
- A GTK Demucs configure form (parked: reuse unrecognized-checkpoint dialog).
- Stem display names, stem-focus vocabulary, or export-filename labels. That is
  a separate refinement.
- Designing arbitrary Demucs source layouts or dynamic engine stem maps.
- Changing separation algorithms, model weights, catalogue source/refresh
  policy, or the canonical `family:basename` syntax. This refinement preserves
  current `models download` fuzzy matching while making its ambiguity behavior
  explicit.
