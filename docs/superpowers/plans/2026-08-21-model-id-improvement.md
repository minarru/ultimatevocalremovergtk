# Model Identity Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry a single canonical `family:basename` identity from storage through planning and engines, so runtime never parses display text and each logical model is one `ModelRecord`.

**Architecture:** `core/model_identity.py` owns value types and exact lookup. `core/model_inventory.py` builds one immutable index per inventory generation + catalogue revision + naming revision from family adapters (catalogue snapshot, installed files, bundled specs, Demucs registry). Planning (`JobResolver`, `AudioJobResolver`) fills a flat active-path dependency map of canonical IDs, computes `model_identity_digest`, and passes records into `assemble_model` / `ModelConfig`. Engines consume `backend_name`, artifacts, `DemucsSpec`, and `MdxSpec`. Display stays one-way.

**Tech Stack:** Python 3, stdlib `unittest`, basedpyright, GTK4/libadwaita for picker tests, existing `CatalogueCoordinator` (not re-keyed).

**Spec:** [docs/model_id_refinement.md](../../model_id_refinement.md)

## Global Constraints

- Families stay `vr`, `mdx`, `demucs`, `apollo`. Do not invent `roformer:`, `scnet:`, `bandit:`, or `mdxc:`.
- Canonical storage/execution form is `family:basename`. Runtime never parses display text.
- No identity migrator, no `identity_schema_version`, no alias tables, no `engine_name` JSON field.
- Do not re-key `CatalogueCoordinator` maps. Identity reads `snapshot.vr/mdx/demucs/apollo` plus `snapshot.meta_by_family[family][selection]`.
- Catalogue refresh must not bump `ModelRepository.inventory_generation`.
- Identity index construction is offline: no network, no `ensure_mdx_c_config`, no hashing, no registration writes.
- Breaking changes to settings, replays, and ensembles are acceptable. Leave illegal stored strings in place; do not write Choose/No Model over them.
- Tests: `.venv/bin/python -m unittest …` (no pytest). Network guard is armed via `tests/__init__.py`.
- Type-check touched files with `.venv/bin/python -m basedpyright <files>` before each commit.
- Do not touch stem display names, stem-focus, or export-filename labels.
- Do not add a GTK Demucs configure form.
- Every existing test must stay green after each task commit. Target-behavior tests land in the same task as the code that makes them pass — do not commit a red suite.

---

## File structure

| Path | Responsibility |
|---|---|
| `core/model_identity.py` | `ModelId`, `ModelRecord`, `ModelArtifacts`, `DemucsSpec`, `MdxSpec`, `CatalogueRef`, exact `lookup`, published index interface. No `ModelConfig`. No fuzzy `resolve` after Task 19. |
| `core/model_inventory.py` | Family adapters; merge catalogue + installed + bundled + registry; collisions; path safety; build the immutable index. Must not construct `ModelConfig`. |
| `core/demucs_registry.py` | Load/validate/lock `model_specs.json` and `registered_models.json`. |
| `models/Demucs_Models/model_data/model_specs.json` | Official Demucs version + source layout keyed by canonical ID. Seeded like `model_name_mapper.json` (`BUNDLED_MODELS_DIR` is `models/`). |
| `core/catalogue_coordinator.py` | Add `meta_by_family`; keep transitional `meta`; stop file-level identity in display-index wrappers. |
| `core/model_repository.py` | Share inventory lock with identity publish; compound-suffix listing; exclude Demucs-root `.ckpt` from identity/pickers. |
| `core/job_plan.py` | Active-path `model_dependencies`, `model_identity_digest`, carry records. |
| `core/model_config/assemble.py` | Pass records; never `engine_value` display inversion. |
| `core/model_config/config.py` | Identity fields on `ModelConfig`; `get_demucs_model_data` assigns `DemucsSpec`. |
| `core/model_config/determine.py` | Consume the dependency map; never swallow `ValueError` on an active path. |
| `core/audio_plan.py` | Keep `audio_tools.apollo_model` as a canonical ID. |
| `core/identity_migration.py` | Deleted in Task 16. |
| `cli/execution.py`, `cli/audio.py`, `cli/replay.py` | Replayable manifests schema 3. Bench unchanged. |
| `ui/views/base.py` | Populate from installed records; write-gate. |
| `tests/test_model_identity_contracts.py` | Cardinality, strict lookup, digest, collisions. |
| `tests/test_demucs_registry.py` | Official specs + register/configure. |
| `tests/test_identity_planning.py` | Nested map, Apollo, YAML fetch policy. |
| `tests/test_identity_cutover.py` | Persistence, pickers, schema 3, CLI JSON. |
| `tests/test_no_runtime_display_inversion.py` | AST/import guard. |

```text
snapshot.vr/mdx/demucs/apollo + meta_by_family
        |     installed files     bundled specs     Demucs registry
        v              v                 v                  v
                 core/model_inventory.py
                        |
                        v
              records_by_id  (immutable)
                        |
          JobResolver / AudioJobResolver
                        |
          assemble_model -> ModelConfig -> engines
```

---

### Task 1: Characterization locks (download matching, CLI JSON, manifests)

**Files:**
- Create: `tests/test_model_identity_contracts.py`
- Test only. No production changes.

**Interfaces:**
- Consumes: existing `core.model_catalogue.ModelCatalogueService.resolve`, `core.model_identity.ModelRecord.to_dict`, `cli.execution.MANIFEST_SCHEMA_VERSION`, `cli.audio` manifest writer, `cli.bench` manifest writer.
- Produces: regression locks so later tasks cannot silently change download matching or drop `engine_name` without updating these tests.

- [ ] **Step 1: Write the characterization tests**

Create `tests/test_model_identity_contracts.py`:

```python
"""Locks for the model-identity cutover. Characterization tests in this
module describe *current* contracts and must pass on the first commit.
Target-behavior tests are added in later tasks in this same file."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from bundled.constants import CHOOSE_MODEL, NO_MODEL
from core.model_catalogue import CatalogEntryId, ModelCatalogueRecord, ModelCatalogueService
from core.model_identity import ModelRecord


class DownloadMatchingLockTests(unittest.TestCase):
    """models download stays catalogue-facing: exact row id, exact
    selectable/display, then one unique substring. Ambiguity fails."""

    def setUp(self) -> None:
        self.service = ModelCatalogueService.__new__(ModelCatalogueService)
        self.hq4_id = CatalogEntryId("mdx", "MDX-Net Model: UVR-MDX-NET Inst HQ 4")
        self.row = ModelCatalogueRecord(
            id=self.hq4_id.value,
            family="mdx",
            selection=self.hq4_id.selection,
            display="MDX-Net — UVR-MDX-NET Inst HQ 4",
            purpose="all",
            supported=True,
            installed=False,
        )
        self.service.records = lambda: (self.row,)  # type: ignore[method-assign]

    def test_exact_catalog_entry_id_resolves(self) -> None:
        got = self.service.resolve(self.hq4_id.value)
        self.assertEqual(got.id, self.hq4_id.value)

    def test_exact_selectable_resolves(self) -> None:
        got = self.service.resolve("MDX-Net Model: UVR-MDX-NET Inst HQ 4")
        self.assertEqual(got.selection, self.hq4_id.selection)

    def test_exact_display_resolves(self) -> None:
        got = self.service.resolve("MDX-Net — UVR-MDX-NET Inst HQ 4")
        self.assertEqual(got.selection, self.hq4_id.selection)

    def test_unique_substring_resolves(self) -> None:
        got = self.service.resolve("Inst HQ 4")
        self.assertEqual(got.selection, self.hq4_id.selection)

    def test_ambiguous_substring_lists_candidate_ids(self) -> None:
        other_id = CatalogEntryId("mdx", "MDX-Net Model: UVR-MDX-NET Inst HQ 5")
        other = ModelCatalogueRecord(
            id=other_id.value,
            family="mdx",
            selection=other_id.selection,
            display="MDX-Net — UVR-MDX-NET Inst HQ 5",
            purpose="all",
            supported=True,
            installed=False,
        )
        self.service.records = lambda: (self.row, other)  # type: ignore[method-assign]
        with self.assertRaises(ValueError) as ctx:
            self.service.resolve("Inst HQ")
        message = str(ctx.exception)
        self.assertIn(self.hq4_id.value, message)
        self.assertIn(other_id.value, message)


class CliJsonEngineNameSnapshotTests(unittest.TestCase):
    """Current ModelRecord JSON emits engine_name. Task 5 drops it."""

    def test_to_dict_currently_includes_engine_name(self) -> None:
        record = ModelRecord(
            id="mdx:UVR-MDX-NET-Inst_HQ_4",
            family="mdx",
            basename="UVR-MDX-NET-Inst_HQ_4",
            display="MDX-Net — UVR-MDX-NET Inst HQ 4",
        )
        payload = record.to_dict()
        self.assertIn("engine_name", payload)
        self.assertEqual(payload["engine_name"], "UVR-MDX-NET-Inst_HQ_4")
        self.assertNotIn("backend_name", payload)


class ManifestSchemaSnapshotTests(unittest.TestCase):
    """Replayable manifests are schema 1 (separate/ensemble) and 2 (audio).
    Bench is schema 1 and is not replayable. Task 18 bumps replayable
    manifests to schema 3."""

    def test_separate_manifest_schema_is_1(self) -> None:
        from cli.execution import MANIFEST_SCHEMA_VERSION

        self.assertEqual(MANIFEST_SCHEMA_VERSION, 1)

    def test_replay_currently_accepts_schema_1_and_2(self) -> None:
        import inspect
        from cli import replay

        source = inspect.getsource(replay.cmd_run)
        self.assertIn("{1, 2}", source)

    def test_bench_manifest_schema_stays_1(self) -> None:
        import inspect
        from cli import bench

        source = inspect.getsource(bench.cmd_bench)
        self.assertIn('"schema_version": 1', source)


class SentinelLockTests(unittest.TestCase):
    def test_choose_and_no_model_strings_are_stable(self) -> None:
        self.assertEqual(CHOOSE_MODEL, "Choose Model")
        self.assertEqual(NO_MODEL, "No Model Selected")
```

`ModelCatalogueService.resolve` is the real download matcher (`core/model_catalogue.py`). Exact selectable/display is a casefold set membership; substring uses `catalogue_label_matches`. Ambiguity lists `row.id` strings (already `catalog:family:…`).

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_model_identity_contracts -v`

Expected: PASS. If download resolution lives elsewhere, fix the test to call that function — these are characterization tests, not target tests.

- [ ] **Step 3: No production code**

- [ ] **Step 4: Type-check the new test file**

Run: `.venv/bin/python -m basedpyright tests/test_model_identity_contracts.py`

- [ ] **Step 5: Commit**

```bash
git add tests/test_model_identity_contracts.py
git commit -m "$(cat <<'EOF'
test: lock catalogue download matching and identity JSON snapshots

EOF
)"
```

---

### Task 2: Identity value types (`backend_name`, artifacts, specs)

**Files:**
- Modify: `core/model_identity.py`
- Modify: every `ModelRecord(...)` construction site that breaks (tests + `_ModelInventory.records` + `identity_migration.py` Apollo extras)
- Modify: `tests/test_model_identity_contracts.py` (replace the engine_name snapshot with `backend_name`)
- Modify: `tests/test_cli_list_models.py`, `tests/test_core_consolidation.py`, `tests/test_model_identity_duplicates.py` if they assert `engine_name`

**Interfaces:**
- Consumes: existing `ModelId`, `FAMILIES`
- Produces:

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

`ModelRecord.to_dict()` emits `backend_name`, `primary_artifact`, `supporting_artifacts`, `identity_complete`, and when set `demucs_version` / `source_layout` / `mdx_kind`. It does **not** emit `engine_name`.

Keep a module-level compatibility property only if a same-task caller cannot be updated: prefer updating callers. `engine_value()` may keep its name but must read `backend_name`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_model_identity_contracts.py`:

```python
from core.model_identity import (
    CatalogueRef,
    DemucsSpec,
    MdxSpec,
    ModelArtifacts,
    ModelRecord,
)


class ModelRecordContractTests(unittest.TestCase):
    def test_to_dict_reports_backend_name_not_engine_name(self) -> None:
        record = ModelRecord(
            id="demucs:htdemucs_6s",
            family="demucs",
            basename="htdemucs_6s",
            display="v4 — htdemucs_6s",
            backend_name="htdemucs_6s",
            artifacts=ModelArtifacts(
                primary_filename="htdemucs_6s.yaml",
                supporting_filenames=("abc12345-deadbeef.th",),
            ),
            installed=True,
            catalogue_entry=CatalogueRef("demucs", "Demucs v4: htdemucs_6s"),
            demucs=DemucsSpec("v4", "6_stem"),
        )
        payload = record.to_dict()
        self.assertEqual(payload["backend_name"], "htdemucs_6s")
        self.assertEqual(payload["primary_artifact"], "htdemucs_6s.yaml")
        self.assertEqual(payload["supporting_artifacts"], ["abc12345-deadbeef.th"])
        self.assertEqual(payload["demucs_version"], "v4")
        self.assertEqual(payload["source_layout"], "6_stem")
        self.assertNotIn("engine_name", payload)

    def test_mdx_kind_is_serialized(self) -> None:
        record = ModelRecord(
            id="mdx:UVR-MDX-NET-Inst_HQ_4",
            family="mdx",
            basename="UVR-MDX-NET-Inst_HQ_4",
            display="MDX-Net — UVR-MDX-NET Inst HQ 4",
            backend_name="UVR-MDX-NET-Inst_HQ_4",
            artifacts=ModelArtifacts("UVR-MDX-NET-Inst_HQ_4.onnx"),
            installed=True,
            mdx=MdxSpec("classic_onnx"),
        )
        self.assertEqual(record.to_dict()["mdx_kind"], "classic_onnx")
```

Update `CliJsonEngineNameSnapshotTests` in the same file: delete it. The new test replaces that lock.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_model_identity_contracts.ModelRecordContractTests -v`

Expected: FAIL with `TypeError: ModelRecord.__init__() got an unexpected keyword argument 'backend_name'` (or `engine_name` still present).

- [ ] **Step 3: Expand the types**

In `core/model_identity.py`:

1. Add the dataclasses above (import `Literal` from `typing`).
2. Replace `ModelRecord` fields: drop `engine_name`; add `backend_name: str`, `artifacts: ModelArtifacts`, and the optional fields with defaults.
3. Rewrite `to_dict()`:

```python
def to_dict(self) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": self.id,
        "family": self.family,
        "basename": self.basename,
        "display": self.display,
        "backend_name": self.backend_name,
        "primary_artifact": self.artifacts.primary_filename,
        "supporting_artifacts": list(self.artifacts.supporting_filenames),
        "installed": self.installed,
        "identity_complete": self.identity_complete,
    }
    if self.identity_error:
        payload["identity_error"] = self.identity_error
    if self.demucs is not None:
        payload["demucs_version"] = self.demucs.version
        payload["source_layout"] = self.demucs.source_layout
    if self.mdx is not None:
        payload["mdx_kind"] = self.mdx.kind
    return payload
```

4. Update `_ModelInventory.records()` to pass `backend_name=basename` (Apollo: the filename) and `artifacts=ModelArtifacts(primary_filename=...)`. Apollo's primary filename is the on-disk file with extension.
5. `engine_value()`: `return self.legacy_member_tag(record) if member else record.backend_name`.
6. Export the new types from `__all__` and from `core/__init__.py` (`ModelArtifacts`, `DemucsSpec`, `MdxSpec`, `CatalogueRef`).
7. Fix every `ModelRecord(` construction in tests. `rg -n "ModelRecord\(" tests core`. For `_rec` helpers:

```python
def _rec(model_id: str, basename: str, *, installed: bool = True, display: str = "") -> ModelRecord:
    family = model_id.split(":", 1)[0]
    return ModelRecord(
        id=model_id,
        family=family,
        basename=basename,
        display=display or basename,
        backend_name=basename,
        artifacts=ModelArtifacts(f"{basename}.ckpt" if family == "mdx" else f"{basename}.pth"),
        installed=installed,
    )
```

8. `rg -n "engine_name" tests cli core ui` and update assertions to `backend_name`. Leave `engine_value` method name.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
.venv/bin/python -m unittest tests.test_model_identity_contracts tests.test_model_identity_duplicates tests.test_cli_list_models tests.test_core_consolidation -v
.venv/bin/python -m basedpyright core/model_identity.py core/__init__.py tests/test_model_identity_contracts.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/model_identity.py core/__init__.py tests
git commit -m "$(cat <<'EOF'
feat: add ModelRecord artifacts, specs, and backend_name

EOF
)"
```

---

### Task 3: Strict lookup helper (no fuzzy, no display)

**Files:**
- Modify: `core/model_identity.py`
- Modify: `tests/test_model_identity_contracts.py`
- Do **not** delete `resolve(..., fuzzy=True)` yet. Old callers keep using it until Task 19.

**Interfaces:**
- Produces:

```python
class IdentityIndex:
    def __init__(self, records: Mapping[str, ModelRecord]):
        self._records = dict(records)

    def lookup(self, model_id: str) -> ModelRecord:
        ...

def parse_stored_model_id(value: str) -> ModelId:
    """Exact family:basename. No casefold of basename, no Arch: Display."""
```

`ModelId.parse` today casefolds the family and accepts any basename. Change it so:

- Family must be exactly one of `vr|mdx|demucs|apollo` after stripping; store it lowercase.
- Basename is **not** case-folded. Empty or containing `:` raises.
- `VR Architecture:…`, raw basenames, and displays raise `ValueError: not a canonical model ID`.

`IdentityIndex.lookup` does `records_by_id[value]` after `ModelId.parse`. No display/basename/engine fallback. Missing → `ValueError: unknown model {value!r}`.

- [ ] **Step 1: Write the failing tests**

```python
from core.model_identity import IdentityIndex, ModelId, parse_stored_model_id


class StrictIdParseTests(unittest.TestCase):
    def test_parses_canonical_id(self) -> None:
        parsed = parse_stored_model_id("mdx:UVR-MDX-NET-Inst_HQ_4")
        self.assertEqual(parsed.family, "mdx")
        self.assertEqual(parsed.basename, "UVR-MDX-NET-Inst_HQ_4")

    def test_rejects_display_and_arch_prefix(self) -> None:
        for value in (
            "MDX-Net — UVR-MDX-NET Inst HQ 4",
            "MDX-Net: UVR-MDX-NET Inst HQ 4",
            "UVR-MDX-NET-Inst_HQ_4",
            "mdx:",
            "roformer:foo",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_stored_model_id(value)

    def test_does_not_casefold_basename(self) -> None:
        parsed = parse_stored_model_id("mdx:Some_Model")
        self.assertEqual(parsed.basename, "Some_Model")


class IdentityIndexLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        from core.model_identity import ModelArtifacts, ModelRecord

        record = ModelRecord(
            id="mdx:Some_Model",
            family="mdx",
            basename="Some_Model",
            display="MDX-Net — Some Model",
            backend_name="Some_Model",
            artifacts=ModelArtifacts("Some_Model.onnx"),
            installed=True,
        )
        self.index = IdentityIndex({record.id: record})

    def test_exact_id_hits(self) -> None:
        self.assertEqual(self.index.lookup("mdx:Some_Model").basename, "Some_Model")

    def test_casefold_id_does_not_hit(self) -> None:
        with self.assertRaises(ValueError):
            self.index.lookup("mdx:some_model")

    def test_display_does_not_hit(self) -> None:
        with self.assertRaises(ValueError):
            self.index.lookup("MDX-Net — Some Model")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_model_identity_contracts.StrictIdParseTests tests.test_model_identity_contracts.IdentityIndexLookupTests -v`

Expected: FAIL (`cannot import name 'IdentityIndex'` / `'parse_stored_model_id'`).

- [ ] **Step 3: Implement lookup**

Add to `core/model_identity.py`:

```python
def parse_stored_model_id(value: str) -> ModelId:
    text = str(value or "").strip()
    family, separator, basename = text.partition(":")
    if not separator or family not in FAMILIES or not basename or ":" in basename:
        raise ValueError(f"not a canonical model ID: {value!r}")
    return ModelId(family, basename)


class IdentityIndex:
    def __init__(self, records: Mapping[str, ModelRecord]):
        self._records = dict(records)

    def lookup(self, model_id: str) -> ModelRecord:
        key = parse_stored_model_id(model_id).value
        try:
            return self._records[key]
        except KeyError:
            raise ValueError(f"unknown model {model_id!r}") from None

    def records(self) -> tuple[ModelRecord, ...]:
        return tuple(self._records.values())
```

Keep `ModelId.parse` behaving as today for existing callers, **or** make `ModelId.parse` call `parse_stored_model_id` and fix tests that expected casefold (`tests/test_model_identity_duplicates.py` `test_a_single_casefold_match_still_resolves` currently expects `mdx:some_model` → `mdx:Some_Model`). If you change `ModelId.parse`, update that test to expect `ValueError` — that is the spec. Prefer changing `ModelId.parse` to the strict rules so there is one parser.

If `ModelId.parse` becomes strict, `resolve_model_record`'s exact-id branch still works for exact strings; casefold basename matching inside `resolve()` stays until Task 19.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_model_identity_contracts tests.test_model_identity_duplicates tests.test_cli_list_models -v
.venv/bin/python -m basedpyright core/model_identity.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/model_identity.py tests/test_model_identity_contracts.py tests/test_model_identity_duplicates.py tests/test_cli_list_models.py
git commit -m "$(cat <<'EOF'
feat: add strict canonical model ID lookup

EOF
)"
```

---

### Task 4: `meta_by_family` on the catalogue snapshot

**Files:**
- Modify: `core/catalogue_coordinator.py` (`CatalogueSnapshot`, `_publish`)
- Modify: `tests/test_catalogue_coordinator.py` (and any snapshot field unpacking)
- Modify: `tests/test_model_identity_contracts.py`

**Interfaces:**
- Produces: `CatalogueSnapshot.meta_by_family: Mapping[str, Mapping[str, EntryMeta]]` keyed `family → selectable → EntryMeta`.
- Transitional `snapshot.meta` remains a cross-family label-keyed dict for unmigrated consumers. Identity must not read it.

Build `meta_by_family` **before** the cross-family `meta.update` so a VR and MDX entry with the same selectable both survive.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_model_identity_contracts.py` (or extend `tests/test_catalogue_coordinator.py` if that file already constructs snapshots via the coordinator):

```python
class MetaByFamilyTests(unittest.TestCase):
    def test_snapshot_has_family_split_meta(self) -> None:
        from core.catalogue_coordinator import CatalogueSnapshot
        import typing

        hints = typing.get_type_hints(CatalogueSnapshot)
        self.assertIn("meta_by_family", CatalogueSnapshot.__dataclass_fields__)

    def test_same_selectable_in_two_families_does_not_overwrite(self) -> None:
        from core.catalog_sources import EntryMeta, _build_meta
        from bundled.constants import VR_ARCH_TYPE, MDX_ARCH_TYPE

        vr = {"Shared Label": {"a.pth": "http://example.invalid/a.pth"}}
        mdx = {"Shared Label": {"b.onnx": "http://example.invalid/b.onnx"}}
        vr_meta = _build_meta(vr, VR_ARCH_TYPE, {}, {})
        mdx_meta = _build_meta(mdx, MDX_ARCH_TYPE, {}, {})
        # The production snapshot must keep both. This test will be rewritten
        # in Step 3 to call the coordinator helper that builds meta_by_family.
        self.assertEqual(vr_meta["Shared Label"].arch, VR_ARCH_TYPE)
        self.assertEqual(mdx_meta["Shared Label"].arch, MDX_ARCH_TYPE)
```

After implementing, replace the second test with a call to the real builder:

```python
def _meta_by_family_from_lists(vr, mdx, demucs=None, apollo=None):
    from core.catalogue_coordinator import build_meta_by_family
    return build_meta_by_family(vr, mdx, demucs or {}, apollo or {}, extra_meta={})
```

and assert `result["vr"]["Shared Label"]` and `result["mdx"]["Shared Label"]` both exist.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_model_identity_contracts.MetaByFamilyTests -v`

Expected: FAIL (`meta_by_family` not a field).

- [ ] **Step 3: Implement family-split meta**

In `core/catalogue_coordinator.py`:

1. Add field to `CatalogueSnapshot`:

```python
meta_by_family: Mapping[str, Mapping[str, Any]]
```

Place it next to `meta`. Because the dataclass is frozen and only constructed in `_publish` (confirmed: one `CatalogueSnapshot(` site), update that one call.

2. Add:

```python
def build_meta_by_family(
    vr, mdx, demucs, apollo, extra_meta, alias_meta=None,
) -> dict[str, dict[str, Any]]:
    from .catalog_sources import _build_meta, _metadata_alias_index
    from bundled.constants import (
        APOLLO_ARCH_TYPE, DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE,
    )
    aliases = alias_meta if alias_meta is not None else _metadata_alias_index(extra_meta)
    return {
        "vr": _build_meta(vr, VR_ARCH_TYPE, extra_meta, aliases),
        "mdx": _build_meta(mdx, MDX_ARCH_TYPE, extra_meta, aliases),
        "demucs": _build_meta(demucs, DEMUCS_ARCH_TYPE, extra_meta, aliases),
        "apollo": _build_meta(apollo, APOLLO_ARCH_TYPE, extra_meta, aliases),
    }
```

3. In `_publish`, replace the `meta.update` loop with:

```python
meta_by_family = build_meta_by_family(vr, mdx, demucs, apollo, extra_meta, alias_meta)
meta: dict[str, Any] = {}
for family_meta in meta_by_family.values():
    meta.update(family_meta)  # transitional; identity must not use this
```

4. Pass `meta_by_family={family: MappingProxyType(entries) for family, entries in meta_by_family.items()}` into the snapshot (or a nested MappingProxyType).
5. Change `_basename_index` consumers: identity will stop using display indexes in Task 6. For this task, keep building `display_index_*` from **primary checkpoints only** so wrappers stop promoting YAML/bag-member stems:

```python
def _basename_index(meta: Mapping[str, Any], arch: str) -> dict[str, str]:
    import os
    from .model_display import _is_checkpoint_name

    index: dict[str, str] = {}
    for entry in meta.values():
        if getattr(entry, "arch", None) != arch:
            continue
        display = str(getattr(entry, "display", "") or "")
        checkpoint = getattr(entry, "checkpoint", None)
        files = getattr(entry, "files", {}) or {}
        names = [checkpoint] if checkpoint else [
            name for name in files if _is_checkpoint_name(str(name))
        ]
        for filename in names:
            if not filename:
                continue
            stem = os.path.splitext(os.path.basename(str(filename)))[0]
            index.setdefault(stem, display)
    return index
```

Use `meta_by_family[family].values()` instead of the merged `meta` when building per-arch indexes so a stolen label cannot attach the wrong arch.

Add a cardinality test:

```python
class DisplayIndexPrimaryOnlyTests(unittest.TestCase):
    def test_yaml_stem_is_not_an_index_key(self) -> None:
        from core.catalog_sources import EntryMeta
        from core.catalogue_coordinator import _basename_index
        from bundled.constants import MDX_ARCH_TYPE

        meta = {
            "MDX-Net Model: Pair": EntryMeta(
                label="MDX-Net Model: Pair",
                display="MDX-Net — Pair",
                arch=MDX_ARCH_TYPE,
                files={"pair.ckpt": "http://x/pair.ckpt", "pair.yaml": "http://x/pair.yaml"},
                checkpoint="pair.ckpt",
            )
        }
        index = _basename_index(meta, MDX_ARCH_TYPE)
        self.assertEqual(set(index), {"pair"})
        self.assertNotIn("pair.yaml", index)
        self.assertNotIn("pair", {"pair.yaml"})  # sanity
```

The yaml stem `pair` from `pair.yaml` via `splitext` would be `"pair"` too — use distinct names in a second test:

```python
        meta = {
            "MDX-Net Model: Pair": EntryMeta(
                label="MDX-Net Model: Pair",
                display="MDX-Net — Pair",
                arch=MDX_ARCH_TYPE,
                files={
                    "model.ckpt": "http://x/model.ckpt",
                    "config.yaml": "http://x/config.yaml",
                },
                checkpoint="model.ckpt",
            )
        }
        index = _basename_index(meta, MDX_ARCH_TYPE)
        self.assertEqual(set(index), {"model"})
        self.assertNotIn("config", index)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_model_identity_contracts tests.test_catalogue_coordinator tests.test_model_display -v
.venv/bin/python -m basedpyright core/catalogue_coordinator.py
```

Expected: PASS. If `test_model_display` expected YAML stems in the index, update those tests: wrappers must not recreate support-file records.

- [ ] **Step 5: Commit**

```bash
git add core/catalogue_coordinator.py tests
git commit -m "$(cat <<'EOF'
feat: split catalogue meta by family and index primary artifacts only

EOF
)"
```

---

### Task 5: Family adapters and logical inventory index

**Files:**
- Create: `core/model_inventory.py`
- Modify: `core/model_identity.py` (`ModelIdentityService` publishes/caches the index)
- Modify: `core/model_repository.py` (`_list_models` compound suffixes; inventory lock; Demucs-root `.ckpt` not listed as a logical model)
- Modify: `tests/test_model_identity_contracts.py`

**Interfaces:**
- Produces:

```python
# core/model_inventory.py
def artifact_stem(filename: str) -> str: ...
def validate_artifact_name(name: str, *, family: str) -> str: ...
def build_identity_index(
    repo: Any,
    *,
    snapshot: Any | None,
    bundled_demucs_specs: Mapping[str, DemucsSpec] | None = None,
    registered_demucs: Mapping[str, Any] | None = None,
) -> IdentityIndex: ...
```

`artifact_stem` strips suffixes as a unit in this order: `.th.gz`, `.ckpt`, `.onnx`, `.pth`, `.yaml`, `.yml`, `.th`, `.bin`, `.gz`.

`validate_artifact_name` rejects absolute paths, `..`, empty components, and family subdirectories that escape the model root. Returns the normalized relative name.

Projection order (spec):

1. Catalogue entries → logical candidates from `snapshot.<family>` + `meta_by_family[family][selection]`. One record per selectable. YAML/bag members are supporting artifacts, never IDs.
2. Installed artifacts join by exact filename. Installed-only models get records with `catalogue_entry=None`.
3. Bundled mapper / `model_specs.json` enrich official Demucs (Task 7 seeds the file; this task may pass `{}`).
4. Registered custom Demucs (Task 14; pass `{}` until then).
5. Uniqueness + `identity_complete`, then `IdentityIndex`.

Family rules — implement all of these in this task:

**VR:** primary = `.pth`; basename = stem; backend_name = stem.

**MDX:** `.ckpt` when paired with YAML; `.onnx` for classic. YAML is supporting. Never emit `mdx:<yaml-stem>` as an ID. Infer `MdxSpec.kind` from local evidence only: `.onnx` → `classic_onnx`; on-disk/catalogue YAML `model_type` / filename heuristics for `mdx23c`, `mel_band_roformer`, `bs_roformer`, `scnet`, `scnet_masked`, `scnet_tran`, `bandit`, `bandit_v2`. Unknown installed YAML → `identity_complete=False`. Unported catalogue types stay out of the index (unsupported catalogue rows).

**Demucs:** YAML bag stem is the ID; referenced weights are supporting. Standalone `.th` / `.th.gz` is a model. Demucs-root `.ckpt` is **not** a record (validation diagnostic later). Member weights are not records. Missing version/layout → selectable installed record with `identity_complete=False`. Do not default to v4/four-stem.

**Apollo:** `backend_name` = filename with extension; artifacts = checkpoint (+ config if present).

Collisions: two different primaries claiming the same ID → both `identity_complete=False` with `identity_error` naming the collision. Case-fold join of catalogue vs installed only when the filesystem is case-insensitive (`os.path.normcase("A") == os.path.normcase("a")`) or trusted content identity matches.

Index construction must not call `ensure_mdx_c_config`, `urlopen`, or hash a checkpoint. Assert in tests by patching those names to raise.

`ModelIdentityService.records()` / `lookup()` should use the new index when `repo` is a real `ModelRepository`. Cache on `(inventory_generation, catalogue_revision, naming_revision)`. Publish under `repo` inventory lock:

```python
# ModelRepository.__init__
self._inventory_lock = threading.RLock()

def invalidate_models(self) -> None:
    with self._inventory_lock:
        self._inventory_generation += 1
        self._stem_check_cache = None
        self._karaoke_cache = None
        self.model_hash_table.clear()
        self.reload_mappers()
        self._notify_models_changed()
```

```python
def _published_index(self) -> IdentityIndex:
    repo = self.repo
    lock = getattr(repo, "_inventory_lock", None)
    if lock is None:
        return build_identity_index(repo, snapshot=_snapshot(repo))
    with lock:
        gen = repo.inventory_generation
        cat = repo.catalogue_revision
        naming = repo.naming_revision
        index = build_identity_index(repo, snapshot=_snapshot(repo))
        if (
            repo.inventory_generation != gen
            or repo.catalogue_revision != cat
            or repo.naming_revision != naming
        ):
            return self._published_index()
        return index
```

Keep old `records()` catalogue-index fallback only if `build_identity_index` cannot run (no snapshot). Prefer always running the builder.

- [ ] **Step 1: Write the failing tests**

```python
class ArtifactStemTests(unittest.TestCase):
    def test_strips_compound_th_gz(self) -> None:
        from core.model_inventory import artifact_stem
        self.assertEqual(artifact_stem("tasnet.th.gz"), "tasnet")
        self.assertEqual(artifact_stem("tasnet.th"), "tasnet")
        self.assertEqual(artifact_stem("model.ckpt"), "model")


class InventoryCardinalityTests(unittest.TestCase):
    def test_mdx_checkpoint_plus_yaml_is_one_record(self) -> None:
        from core.model_inventory import build_identity_index
        repo, snapshot = _fake_mdx_pair()
        index = build_identity_index(repo, snapshot=snapshot)
        ids = [r.id for r in index.records() if r.family == "mdx"]
        self.assertEqual(ids, ["mdx:model"])
        record = index.lookup("mdx:model")
        self.assertEqual(record.artifacts.primary_filename, "model.ckpt")
        self.assertEqual(record.artifacts.supporting_filenames, ("config.yaml",))

    def test_demucs_bag_plus_members_is_one_record(self) -> None:
        from core.model_inventory import build_identity_index
        repo, snapshot = _fake_demucs_bag()
        index = build_identity_index(repo, snapshot=snapshot)
        demucs = [r for r in index.records() if r.family == "demucs"]
        self.assertEqual([r.id for r in demucs], ["demucs:htdemucs_ft"])
        self.assertTrue(demucs[0].artifacts.supporting_filenames)

    def test_yaml_shaped_id_is_not_a_record(self) -> None:
        from core.model_inventory import build_identity_index
        repo, snapshot = _fake_mdx_pair()
        index = build_identity_index(repo, snapshot=snapshot)
        with self.assertRaises(ValueError):
            index.lookup("mdx:config")

    def test_demucs_root_ckpt_is_not_a_record(self) -> None:
        from core.model_inventory import build_identity_index
        repo, snapshot = _fake_demucs_root_ckpt()
        index = build_identity_index(repo, snapshot=snapshot)
        ids = [r.id for r in index.records()]
        self.assertNotIn("demucs:mystery", ids)

    def test_builder_does_not_touch_the_network(self) -> None:
        from core.model_inventory import build_identity_index
        repo, snapshot = _fake_mdx_pair()
        with patch("core.mdx_config_fetch.ensure_mdx_c_config", side_effect=AssertionError("fetch")):
            build_identity_index(repo, snapshot=snapshot)
```

Implement `_fake_mdx_pair` / `_fake_demucs_bag` / `_fake_demucs_root_ckpt` in the same test file. They must not hit the real coordinator. Minimal shape:

```python
def _fake_mdx_pair():
    from types import SimpleNamespace
    from core.catalog_sources import EntryMeta
    from bundled.constants import MDX_ARCH_TYPE

    selectable = "MDX-Net Model: Pair"
    entry = EntryMeta(
        label=selectable,
        display="MDX-Net — Pair",
        arch=MDX_ARCH_TYPE,
        files={"model.ckpt": "http://example.invalid/model.ckpt", "config.yaml": "http://example.invalid/config.yaml"},
        checkpoint="model.ckpt",
    )
    snapshot = SimpleNamespace(
        vr={}, mdx={selectable: entry.files}, demucs={}, apollo={},
        meta_by_family={"vr": {}, "mdx": {selectable: entry}, "demucs": {}, "apollo": {}},
        unsupported={},
    )
    repo = SimpleNamespace(
        list_vr_models=lambda: [],
        list_mdx_models=lambda: [],
        list_demucs_models=lambda: [],
        inventory_generation=0,
        catalogue_revision="x",
        naming_revision=0,
        mdx_name_select_MAPPER={},
        demucs_name_select_MAPPER={},
    )
    return repo, snapshot
```

For the bag fixture, `files` should include `htdemucs_ft.yaml` plus two `sig-checksum.th` names; `checkpoint` should be the yaml basename or None — the Demucs adapter treats a unit with one yaml as a bag regardless.

For root `.ckpt`, `list_demucs_models` may still return `mystery` until `list_demucs_models` is fixed; the identity builder must exclude it even if the lister still yields it. Also change `list_demucs_models` to skip `DEMUCS_MODELS_DIR/*.ckpt` (not in `v3_v4_repo`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_model_identity_contracts.ArtifactStemTests tests.test_model_identity_contracts.InventoryCardinalityTests -v`

Expected: FAIL (`No module named 'core.model_inventory'`).

- [ ] **Step 3: Implement adapters**

Create `core/model_inventory.py` with `artifact_stem`, `validate_artifact_name`, and `build_identity_index`. Keep family logic in private functions `_project_vr`, `_project_mdx`, `_project_demucs`, `_project_apollo`, then `_merge_installed`, `_apply_bundled_demucs`, `_detect_collisions`.

MDX pairing: if files contain exactly one checkpoint and one yaml, pair them. If both `.onnx` and `.ckpt` without pairing metadata, mark invalid (`identity_complete=False`) rather than first-file-wins.

Demucs bag: if files contain one `.yaml`, basename is the yaml stem; every `models:` member listed in a local yaml (when installed) or every `.th` in the catalogue unit is supporting. More than one yaml in one unit → invalid entry, no record.

`list_demucs_models`: use `artifact_stem` instead of `os.path.splitext`; skip `.ckpt` in `DEMUCS_MODELS_DIR` (the Facebook Demucs root). Newer-repo `.ckpt` that is not a bag member stays out of identity as well (same diagnostic class). After this change, `test_demucs_models.py` / listing tests may need to expect `.th.gz` stems without a leftover `.th`.

Wire `ModelIdentityService.records()` to `self._published_index().records()`. Exact `lookup` uses the index. Keep `resolve(fuzzy=True)` on top of the new records for one more phase so CLI still works.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_model_identity_contracts tests.test_model_identity_duplicates tests.test_demucs_models tests.test_cli_list_models tests.test_catalogue_coordinator -v
.venv/bin/python -m basedpyright core/model_inventory.py core/model_identity.py core/model_repository.py
```

Expected: PASS. Fix listing tests that assumed `tasnet.th.gz` → basename `tasnet.th`.

- [ ] **Step 5: Commit**

```bash
git add core/model_inventory.py core/model_identity.py core/model_repository.py tests
git commit -m "$(cat <<'EOF'
feat: build a logical model-identity index from family adapters

EOF
)"
```

---

### Task 6: Collision diagnostics, path safety, generation-checked publish

**Files:**
- Modify: `core/model_inventory.py`, `core/model_identity.py`, `core/model_repository.py`
- Modify: `tests/test_model_identity_contracts.py`

**Interfaces:**
- Produces: identity-collision records (unavailable, named error); `validate_artifact_name` raising `ValueError`; publish retry covered by a test that mutates generation during build.

- [ ] **Step 1: Write the failing tests**

```python
class CollisionAndSafetyTests(unittest.TestCase):
    def test_onnx_and_ckpt_same_basename_are_unavailable(self) -> None:
        from core.model_inventory import build_identity_index
        repo, snapshot = _fake_mdx_extension_collision()
        index = build_identity_index(repo, snapshot=snapshot)
        with self.assertRaises(ValueError):
            index.lookup("mdx:foo")
        # Both candidates must be absent or marked incomplete; neither is runnable.
        runnable = [r for r in index.records() if r.id == "mdx:foo" and r.identity_complete]
        self.assertEqual(runnable, [])

    def test_rejects_parent_directory_artifact_name(self) -> None:
        from core.model_inventory import validate_artifact_name
        with self.assertRaises(ValueError):
            validate_artifact_name("../escape.pth", family="vr")

    def test_stale_generation_discards_the_index(self) -> None:
        from core.model_identity import ModelIdentityService
        builds = []

        class Repo:
            inventory_generation = 1
            catalogue_revision = "a"
            naming_revision = 0
            _inventory_lock = __import__("threading").RLock()
            def list_vr_models(self):
                return []
            def list_mdx_models(self):
                return []
            def list_demucs_models(self):
                return []

        repo = Repo()
        service = ModelIdentityService(repo)
        real_build = __import__("core.model_inventory", fromlist=["build_identity_index"]).build_identity_index

        def racing_build(*args, **kwargs):
            builds.append(repo.inventory_generation)
            if len(builds) == 1:
                repo.inventory_generation = 2
            return real_build(*args, **kwargs)

        with patch("core.model_inventory.build_identity_index", side_effect=racing_build):
            service.records()
        self.assertGreaterEqual(len(builds), 2)
```

The last test depends on `_published_index` calling `build_identity_index`. If the patch target must be the name bound in `model_identity.py`, patch `core.model_identity.build_identity_index` instead.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_model_identity_contracts.CollisionAndSafetyTests -v`

Expected: FAIL (collision still first-file-wins, or publish does not retry).

- [ ] **Step 3: Implement collisions, `validate_artifact_name`, retry**

```python
def validate_artifact_name(name: str, *, family: str) -> str:
    text = str(name or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or text.startswith("~"):
        raise ValueError(f"illegal artifact path {name!r}")
    parts = [p for p in text.split("/") if p]
    if not parts or any(p == ".." or p == "." for p in parts):
        raise ValueError(f"illegal artifact path {name!r}")
    return "/".join(parts)
```

Call it on every primary and supporting filename before inserting a record.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_model_identity_contracts -v
.venv/bin/python -m basedpyright core/model_inventory.py core/model_identity.py
```

- [ ] **Step 5: Commit**

```bash
git add core/model_inventory.py core/model_identity.py core/model_repository.py tests/test_model_identity_contracts.py
git commit -m "$(cat <<'EOF'
feat: reject identity collisions and stale index publication

EOF
)"
```

---

### Task 7: Bundled official `DemucsSpec` (`model_specs.json`)

**Files:**
- Create: `models/Demucs_Models/model_data/model_specs.json`
- Create: `core/demucs_registry.py` (read-only load + drift check in this task; writes in Task 14)
- Modify: `core/paths.py` if a bundled-seed path is needed (follow existing `model_name_mapper.json` seeding)
- Modify: `core/model_inventory.py` to apply bundled specs with the spec's precedence
- Create: `tests/test_demucs_registry.py`

**Interfaces:**
- Produces: `load_bundled_demucs_specs() -> dict[str, dict]` keyed by `demucs:<stem>`.
- Each entry: `entrypoint`, `display`, `version`, `source_layout`.
- Precedence at index time: registered (empty until Task 14) → bundled specs → explicit catalogue metadata → stem count 2/4/6 from trusted catalogue stems → exact label import `Demucs vN: name` / `vN | name` only. Stem count never overrides bundled/registry. No hyphen-as-separator.

Official mapping from the current mapper (gzipped and uncompressed v1 files with the same stem are **one** logical model; list both filenames in `supporting`/`entrypoint` alternatives):

```json
{
  "schema_version": 1,
  "models": {
    "demucs:tasnet": {
      "entrypoint": "tasnet.th",
      "alternate_entrypoints": ["tasnet.th.gz"],
      "display": "v1 — Tasnet",
      "version": "v1",
      "source_layout": "4_stem"
    },
    "demucs:htdemucs_6s": {
      "entrypoint": "v3_v4_repo/htdemucs_6s.yaml",
      "display": "v4 — htdemucs_6s",
      "version": "v4",
      "source_layout": "6_stem"
    },
    "demucs:UVR_Demucs_Model_1": {
      "entrypoint": "v3_v4_repo/UVR_Demucs_Model_1.yaml",
      "display": "v3 — UVR_Model_1",
      "version": "v3",
      "source_layout": "2_stem"
    }
  }
}
```

Fill **every** official mapper key. UVR_* models are `2_stem`. `htdemucs_6s` is `6_stem`. Other v3/v4 bags are `4_stem`. v1/v2 checkpoints are `4_stem`. Seed into the writable tree the same way `model_name_mapper.json` is copied.

Label import (index construction only): if version is still unknown and display or selectable matches `^(?:Demucs )?v([1-4])(?:\s*[|:]\s*|\s+[—-]\s+)(.+)$` — **reject** the hyphen-as-separator form. Accept only `Demucs vN: name` and `vN | name`. Canonical em-dash displays are **not** parsed here; they rely on bundled specs.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_demucs_registry.py
import json
import unittest
from pathlib import Path

from core.model_identity import DemucsSpec


class BundledDemucsSpecTests(unittest.TestCase):
    def test_specs_cover_every_official_mapper_stem(self) -> None:
        from core.demucs_registry import load_bundled_demucs_specs, mapper_stems

        specs = load_bundled_demucs_specs()
        self.assertEqual(set(specs), mapper_stems())

    def test_htdemucs_6s_is_six_source_v4(self) -> None:
        from core.demucs_registry import load_bundled_demucs_specs

        spec = load_bundled_demucs_specs()["demucs:htdemucs_6s"]
        self.assertEqual(spec, DemucsSpec("v4", "6_stem"))

    def test_uvr_bag_is_two_source(self) -> None:
        from core.demucs_registry import load_bundled_demucs_specs

        spec = load_bundled_demucs_specs()["demucs:UVR_Demucs_Model_1"]
        self.assertEqual(spec.source_layout, "2_stem")
```

Also add an inventory test that a fake installed `htdemucs_6s` record gets `DemucsSpec("v4", "6_stem")` from bundled data even when catalogue metadata is empty.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_demucs_registry -v`

Expected: FAIL (`No module named 'core.demucs_registry'`).

- [ ] **Step 3: Write JSON + loader + apply in inventory**

`mapper_stems()` should use `artifact_stem` on each mapper key so `tasnet.th` and `tasnet.th.gz` collapse to `demucs:tasnet`.

`.gitignore` already has `models/Demucs_Models/model_data/*` with `!model_name_mapper.json`. Add:

```
!models/Demucs_Models/model_data/model_specs.json
```

Seed the file through `core/paths.py` `ensure_data_dir` next to the mapper copy (around the `Demucs_Models/model_data/model_name_mapper.json` pair). In the portable layout `BUNDLED_MODELS_DIR == MODELS_DIR`, so the committed file is the live file.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_demucs_registry tests.test_model_identity_contracts -v
.venv/bin/python -m basedpyright core/demucs_registry.py
```

- [ ] **Step 5: Commit**

```bash
git add models/Demucs_Models/model_data/model_specs.json core/demucs_registry.py core/model_inventory.py core/paths.py tests/test_demucs_registry.py .gitignore
git commit -m "$(cat <<'EOF'
feat: seed official Demucs version and source-layout specs

EOF
)"
```

---

### Task 8: Active dependency map and identity digest

**Files:**
- Modify: `core/job_plan.py` (`JobResolver`, `ModelDescriptor`, `ResolvedJob`)
- Create: `tests/test_identity_planning.py`

**Interfaces:**
- Produces:

```python
MODEL_SENTINELS = frozenset({CHOOSE_MODEL, NO_MODEL, ""})

def active_model_paths(settings, *, command: str) -> tuple[str, ...]: ...
def compute_model_identity_digest(dependencies: Mapping[str, ModelRecord]) -> str: ...
```

`JobResolver._identity_records` is replaced by `_dependency_map(settings, command) -> dict[str, ModelRecord]`.

Active paths (skip sentinels):

| Path | Active when |
|---|---|
| `vr.model` / `mdx.model` / `demucs.model` | command/method selects that family |
| `ensemble.selected_models[i]` | ensemble command; `i` zero-based |
| `{family}.{voc_inst,other,bass,drums}_secondary_model` | that family's `is_secondary_model_activate` and the stem slot applies |
| `process.vocal_splitter` | `process.vocal_splitter_enabled` |
| `demucs.pre_proc_model` | `demucs.is_pre_proc_model_activate` |

4-stem / multi-stem Demucs with secondaries: all four non-sentinel slots. 2-stem: only the primary-stem slot (`voc_inst` or `other` via existing `_secondary_slot_for_stem`).

Apollo is **not** in this map.

Missing or family-ineligible **active** path: planning diagnostic / `ValueError`, never omit. `lookup` only (no fuzzy).

`ModelDescriptor` gains `backend_name: str`, `artifacts: ModelArtifacts`, `demucs: DemucsSpec | None = None`, `mdx: MdxSpec | None = None`.

Digest: SHA-256 of canonical JSON, prefix `sha256:`. Payload keys sorted. For each path in sorted order: `id`, `family`, `backend_name`, `primary`, `supporting`, `demucs`, `mdx`. Exclude display, catalogue text, installed flag, paths.

`ResolvedJob.to_dict()` includes `model_dependencies: {path: id}` (lexical key order) and `model_identity_digest`. Before start, re-resolve and recompute; mismatch → stale plan error.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_identity_planning.py
import unittest
from bundled.constants import CHOOSE_MODEL, NO_MODEL, DEMUCS_ARCH_TYPE
from core.settings import Settings
from core.job_plan import active_model_paths, compute_model_identity_digest


class ActivePathTests(unittest.TestCase):
    def test_mdx_primary_only_when_secondaries_off(self) -> None:
        settings = Settings.defaults()
        settings.process.method = "MDX-Net"
        settings.mdx.model = "mdx:UVR-MDX-NET-Inst_HQ_4"
        self.assertEqual(active_model_paths(settings, command="separate"), ("mdx.model",))

    def test_enabled_splitter_is_included(self) -> None:
        settings = Settings.defaults()
        settings.process.method = "MDX-Net"
        settings.mdx.model = "mdx:UVR-MDX-NET-Inst_HQ_4"
        settings.process.vocal_splitter_enabled = True
        settings.process.vocal_splitter = "vr:UVR-De-Echo-Normal"
        self.assertEqual(
            active_model_paths(settings, command="separate"),
            ("mdx.model", "process.vocal_splitter"),
        )

    def test_four_stem_secondaries_include_all_slots(self) -> None:
        settings = Settings.defaults()
        settings.process.method = DEMUCS_ARCH_TYPE
        settings.demucs.model = "demucs:htdemucs"
        settings.demucs.is_secondary_model_activate = True
        settings.demucs.voc_inst_secondary_model = "mdx:a"
        settings.demucs.other_secondary_model = "mdx:b"
        settings.demucs.bass_secondary_model = "mdx:c"
        settings.demucs.drums_secondary_model = "mdx:d"
        paths = active_model_paths(settings, command="separate", source_layout="4_stem")
        self.assertIn("demucs.voc_inst_secondary_model", paths)
        self.assertIn("demucs.drums_secondary_model", paths)

    def test_two_stem_secondaries_include_only_primary_slot(self) -> None:
        settings = Settings.defaults()
        settings.process.method = DEMUCS_ARCH_TYPE
        settings.demucs.model = "demucs:UVR_Demucs_Model_1"
        settings.demucs.is_secondary_model_activate = True
        settings.demucs.voc_inst_secondary_model = "mdx:a"
        settings.demucs.other_secondary_model = "mdx:b"
        paths = active_model_paths(settings, command="separate", source_layout="2_stem")
        self.assertEqual(
            [p for p in paths if p.endswith("_secondary_model")],
            ["demucs.voc_inst_secondary_model"],
        )


class DigestTests(unittest.TestCase):
    def test_display_change_does_not_change_digest(self) -> None:
        from core.model_identity import ModelArtifacts, ModelRecord
        a = ModelRecord(
            id="mdx:foo", family="mdx", basename="foo", display="Old",
            backend_name="foo", artifacts=ModelArtifacts("foo.onnx"), installed=True,
        )
        b = ModelRecord(
            id="mdx:foo", family="mdx", basename="foo", display="New",
            backend_name="foo", artifacts=ModelArtifacts("foo.onnx"), installed=True,
        )
        self.assertEqual(
            compute_model_identity_digest({"mdx.model": a}),
            compute_model_identity_digest({"mdx.model": b}),
        )

    def test_backend_change_changes_digest(self) -> None:
        from core.model_identity import ModelArtifacts, ModelRecord
        a = ModelRecord(
            id="mdx:foo", family="mdx", basename="foo", display="X",
            backend_name="foo", artifacts=ModelArtifacts("foo.onnx"), installed=True,
        )
        b = ModelRecord(
            id="mdx:foo", family="mdx", basename="foo", display="X",
            backend_name="foo.onnx", artifacts=ModelArtifacts("foo.onnx"), installed=True,
        )
        self.assertNotEqual(
            compute_model_identity_digest({"mdx.model": a}),
            compute_model_identity_digest({"mdx.model": b}),
        )
```

`active_model_paths` needs `source_layout` either as an argument (from the already-looked-up primary record) or it looks up the primary first. Prefer: `active_model_paths(settings, command, *, primary=None)` and use `primary.demucs.source_layout` when present.

Also add: enabled missing secondary raises in `JobResolver._dependency_map` (patch `lookup` to raise).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_identity_planning -v`

Expected: FAIL (`cannot import name 'active_model_paths'`).

- [ ] **Step 3: Implement map + digest; switch JobResolver**

Serialize keys with `ensemble.selected_models[{i}]`. Sort the dict for `to_dict()` with `dict(sorted(map.items()))`.

Do not call `resolve(..., fuzzy=True)` on these paths — `IdentityIndex.lookup` / `parse_stored_model_id` then family constraint.

Update `tests/test_job_plan_topology.py` if `_identity_records` is gone: it should still pass through `_dependency_map`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_identity_planning tests.test_job_plan_topology tests.test_core_consolidation.JobPlanTests -v
.venv/bin/python -m basedpyright core/job_plan.py
```

- [ ] **Step 5: Commit**

```bash
git add core/job_plan.py tests/test_identity_planning.py tests/test_job_plan_topology.py
git commit -m "$(cat <<'EOF'
feat: plan model dependencies as a flat canonical-ID map

EOF
)"
```

---

### Task 9: Carry identity through assemble and `ModelConfig`

**Files:**
- Modify: `core/model_config/assemble.py`
- Modify: `core/model_config/config.py`, `core/model_config/base.py`
- Modify: `core/model_config/determine.py`
- Modify: `tests/test_core_model_data.py`, `tests/test_identity_planning.py`

**Interfaces:**
- `assemble_model` looks up each ID with the identity index and passes the `ModelRecord` (or copies `canonical_id`, `model_display_label`, `backend_name`, `model_artifacts`, engine architecture) into `ModelConfig`.
- Nested `engine_value()` that converts ID → display is deleted.
- Settings fields stay canonical IDs. Do not write `backend_name` into `vr.model` etc.
- `get_vr_model_path` / `get_mdx_model_path` / `get_demucs_model_path` join the family directory with `record.artifacts.primary_filename` (Demucs: version directory from `DemucsSpec`). They must not call `resolve_*_model_basename`.
- `determine.py`: `_model_config_for_reference` takes a record from the dependency map. Swallowing `ValueError` → `None` on an active path is forbidden.

`ModelIdentity` in `base.py` gains:

```python
canonical_id: str = ""
model_display_label: str = ""
backend_name: str = ""
model_artifacts: Optional[ModelArtifacts] = None
```

Keep `model_name` as a deprecated alias of `model_display_label` only if an engine still reads it in this task; Task 12 removes display parsing from engines. For this task, set **both** `model_name = record.display` (diagnostics) and the new fields, but path lookup must use artifacts.

- [ ] **Step 1: Write the failing tests**

```python
class AssembleDoesNotInvertDisplayTests(unittest.TestCase):
    def test_assemble_leaves_settings_as_canonical_id(self) -> None:
        from core.model_config.assemble import assemble_model
        from core.settings import Settings
        from bundled.constants import MDX_ARCH_TYPE

        settings = Settings.defaults()
        settings.process.method = MDX_ARCH_TYPE
        settings.mdx.model = "mdx:foo"
        repo = _repo_with_mdx_record("foo")
        configs = assemble_model(settings, repo, "mdx:foo", MDX_ARCH_TYPE)
        self.assertEqual(settings.mdx.model, "mdx:foo")
        self.assertEqual(configs[0].canonical_id, "mdx:foo")
        self.assertEqual(configs[0].backend_name, "foo")

    def test_path_uses_artifact_not_display(self) -> None:
        from core.model_config.assemble import assemble_model
        from core.settings import Settings
        from bundled.constants import MDX_ARCH_TYPE
        import os

        settings = Settings.defaults()
        settings.process.method = MDX_ARCH_TYPE
        settings.mdx.model = "mdx:foo"
        repo = _repo_with_mdx_record("foo", display="WRONG LABEL")
        configs = assemble_model(settings, repo, "mdx:foo", MDX_ARCH_TYPE)
        self.assertEqual(os.path.basename(configs[0].model_path or ""), "foo.onnx")
        self.assertEqual(configs[0].model_display_label, "WRONG LABEL")
```

Copy `_repo_with_mdx_record` from `tests/test_core_model_data.py` `AssembleMdxIdentityTests` / `_repo_with_mdx`, then put an `IdentityIndex` with one complete `mdx:foo` record on the repo (or patch `ModelIdentityService._published_index`). The checkpoint file can be a temp empty `foo.onnx` under a patched `paths.MDX_MODELS_DIR`.

Also: `process_determine_secondary_model` with an enabled missing ID must raise, not return `None`. Put this in `tests/test_identity_planning.py`.

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL (`ModelConfig` has no `canonical_id`, or path still uses display inversion).

- [ ] **Step 3: Implement**

In `assemble.py` delete the nested `engine_value`. Resolve via `ModelIdentityService(repo)` index `lookup`. For ensemble members, look up each `selected_models` entry.

Pass `record` into `ModelConfig.__init__` as a new optional `identity: ModelRecord | None = None`. When omitted (dry tests), keep today's constructor but do not invert.

`get_demucs_model_path`: if `self.demucs_spec` (set in Task 10) or `identity.demucs` is present, choose `DEMUCS_MODELS_DIR` vs `DEMUCS_NEWER_REPO_DIR` from version; join with primary filename. Compound suffix already handled by the artifact name.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_identity_planning tests.test_core_model_data tests.test_mdx_model_path tests.test_job_plan_topology -v
.venv/bin/python -m basedpyright core/model_config
```

- [ ] **Step 5: Commit**

```bash
git add core/model_config tests
git commit -m "$(cat <<'EOF'
feat: assemble ModelConfig from identity records instead of display text

EOF
)"
```

---

### Task 10: `DemucsSpec` assignment and VR architecture normalize

**Files:**
- Modify: `core/model_config/config.py` `get_demucs_model_data`
- Modify: VR path / dry-check architecture selection (`method_key_for_resolution` vs `VR_ARCH_TYPE`)
- Modify: `tests/test_demucs_name_resolution.py`, `tests/test_identity_planning.py`, `tests/test_job_plan_native_values.py`

**Interfaces:**
- `get_demucs_model_data()` copies `identity.demucs.version` / `source_layout` onto `demucs_version`, `demucs_source_list`, `demucs_source_map`, `demucs_stem_count`. No substring search of `model_name`. Incomplete spec → do not default to v4/four-stem; the planner has already rejected incomplete records.
- Map `2_stem` → `DEMUCS_2_SOURCE` / `DEMUCS_2_SOURCE_MAPPER` / 2; `4_stem` → `DEMUCS_4_SOURCE` / `DEMUCS_4_SOURCE_MAPPER` / 4; `6_stem` → a new `DEMUCS_6_SOURCE` list plus existing `DEMUCS_6_SOURCE_MAPPER` / 6. Add next to `DEMUCS_4_SOURCE` in `bundled/constants/stems.py`:

```python
DEMUCS_6_SOURCE = ["drums", "bass", "other", "vocals", "guitar", "piano"]
```

Do not invent a new layout vocabulary.
- VR: engine architecture is `VR_ARCH_TYPE`; UI process label is `VR_ARCH_PM`. Normalize inside the adapter / `ModelConfig` so dry inspection never receives `VR_ARCH_PM` as the architecture selector.

- [ ] **Step 1: Write the failing tests**

```python
class DemucsSpecAssignmentTests(unittest.TestCase):
    def test_v1_display_does_not_select_version(self) -> None:
        cfg = _config_with_record(
            id="demucs:tasnet",
            display="v1 — Tasnet",
            demucs=DemucsSpec("v1", "4_stem"),
            primary="tasnet.th",
        )
        cfg.get_demucs_model_data()
        from bundled.constants import DEMUCS_V1
        self.assertEqual(cfg.demucs_version, DEMUCS_V1)

    def test_htdemucs_6s_is_six_source_before_inference(self) -> None:
        cfg = _config_with_record(
            id="demucs:htdemucs_6s",
            display="v4 — htdemucs_6s",
            demucs=DemucsSpec("v4", "6_stem"),
            primary="htdemucs_6s.yaml",
        )
        cfg.get_demucs_model_data()
        self.assertEqual(cfg.demucs_stem_count, 6)
```

`_config_with_record` should `ModelConfig.__new__` and set the identity fields without scanning disk, unless existing tests already construct a full config.

Add: changing `cfg.model_name` to a misleading string after assignment must not change version (proves display is unused). Optionally: `cfg.model_name = "v4 | nope"; cfg.get_demucs_model_data(); still v1`.

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL (`demucs_stem_count == 4` for 6s; v1 display currently misses `v1 | ` and stays v4).

- [ ] **Step 3: Replace `get_demucs_model_data` body**

```python
def get_demucs_model_data(self):
    spec = self.demucs if getattr(self, "demucs", None) is not None else None
    if spec is None:
        raise ValueError(f"{self.canonical_id} is missing Demucs version/layout metadata")
    self.demucs_version = {"v1": DEMUCS_V1, "v2": DEMUCS_V2, "v3": DEMUCS_V3, "v4": DEMUCS_V4}[spec.version]
    if spec.source_layout == "2_stem":
        self.demucs_source_list, self.demucs_source_map, self.demucs_stem_count = (
            DEMUCS_2_SOURCE, DEMUCS_2_SOURCE_MAPPER, 2
        )
    elif spec.source_layout == "6_stem":
        self.demucs_source_list, self.demucs_source_map, self.demucs_stem_count = (
            DEMUCS_6_SOURCE, DEMUCS_6_SOURCE_MAPPER, 6
        )
    else:
        self.demucs_source_list, self.demucs_source_map, self.demucs_stem_count = (
            DEMUCS_4_SOURCE, DEMUCS_4_SOURCE_MAPPER, 4
        )
```

Use the real constant names from `bundled.constants`. If 6-source constants do not exist, add them in `bundled/constants/process.py` beside the 4-source ones (guitar, piano). Do not parse `self.model_name`.

Still must not invent `segment` (`tests/test_job_plan_native_values.py`).

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_identity_planning tests.test_demucs_name_resolution tests.test_job_plan_native_values -v
```

`MapperSeparatorToleranceTests` still tests `resolve_mapper_basename` for **ingestion**. Leave them until Task 19. Runtime path tests that required em-dash inversion for execution should now go through `DemucsSpec` instead.

- [ ] **Step 5: Commit**

```bash
git add core/model_config/config.py bundled/constants/process.py tests
git commit -m "$(cat <<'EOF'
feat: assign Demucs version and layout from DemucsSpec

EOF
)"
```

---

### Task 11: Apollo ID, vocal-splitter exact match, MDX YAML fetch policy

**Files:**
- Modify: `core/audio_plan.py`
- Modify: `core/settings/job_resolution.py` `resolve_splitter_identity`
- Modify: `core/job_plan.py` (online default vs `--offline`)
- Modify: `cli/separate.py`, `cli/ensemble.py` if present, `cli/audio.py`, `cli/replay.py`, `cli/discovery.py` (validate)
- Modify: `tests/test_identity_planning.py`

**Interfaces:**
- `AudioJobResolver._resolve_apollo` must **not** assign `settings.audio_tools.apollo_model = record.backend_name`. Keep the canonical ID. Use `backend_name` only when joining `APOLLO_MODELS_DIR`.
- `resolve_splitter_identity`: `parse_stored_model_id` + `lookup` + karaoke-pool membership. Delete the `reference.casefold() in tag.casefold()` fallback. `allowed_families` conceptually `vr`/`mdx` (wrong family → error).
- Identity index stays offline. `ensure_mdx_c_config` may run on validate/plan/start for **that one active model** when `allow_network` is true. Default for GUI and CLI is online. `--offline` sets `allow_network=False`. After a successful fetch, invalidate inventory, rebuild identity, re-lookup the same ID. Offline miss → configuration diagnostic. Planning currently wraps `mdx_c_network(False)` always — change that to honor the caller's policy.

- [ ] **Step 1: Write the failing tests**

```python
class ApolloSettingsStayCanonicalTests(unittest.TestCase):
    def test_resolver_does_not_write_filename_into_settings(self) -> None:
        from core.audio_plan import AudioJobResolver
        from core.settings import Settings
        from core.job_plan import ValidationLevel

        settings = Settings.defaults()
        settings.audio_tools.apollo_model = "apollo:restorer"
        resolver = AudioJobResolver(_repo_with_apollo_record("restorer.ckpt"))
        resolver._resolve_apollo(settings, [], ValidationLevel.CONFIG)
        self.assertEqual(settings.audio_tools.apollo_model, "apollo:restorer")


class SplitterExactIdTests(unittest.TestCase):
    def test_substring_no_longer_matches(self) -> None:
        from core.settings.job_resolution import resolve_splitter_identity
        from core.settings import Settings

        settings = Settings.defaults()
        repo = _repo_with_karaoke("vr:UVR-De-Echo-Normal")
        with self.assertRaises(ValueError):
            resolve_splitter_identity("Echo", settings, repo)

    def test_canonical_splitter_id_still_resolves(self) -> None:
        from core.settings.job_resolution import resolve_splitter_identity
        from core.settings import Settings

        settings = Settings.defaults()
        repo = _repo_with_karaoke("vr:UVR-De-Echo-Normal")
        self.assertEqual(
            resolve_splitter_identity("vr:UVR-De-Echo-Normal", settings, repo),
            "vr:UVR-De-Echo-Normal",
        )


class MdxYamlFetchPolicyTests(unittest.TestCase):
    def test_plan_offline_does_not_fetch(self) -> None:
        from unittest.mock import patch
        from core.job_plan import JobResolver

        resolver = JobResolver(_repo_with_mdx_c_missing_yaml())
        with patch("core.mdx_config_fetch.ensure_mdx_c_config", side_effect=AssertionError("fetch")):
            with self.assertRaises(ValueError):
                resolver.resolve(_separate_spec(), allow_network=False)

    def test_plan_online_fetches_once_then_relooks_up(self) -> None:
        from unittest.mock import patch
        from core.job_plan import JobResolver

        fetches = []

        def fake_ensure(name, **kwargs):
            fetches.append(name)
            return True

        resolver = JobResolver(_repo_with_mdx_c_missing_yaml())
        with patch("core.mdx_config_fetch.ensure_mdx_c_config", side_effect=fake_ensure):
            resolver.resolve(_separate_spec(), allow_network=True)
        self.assertEqual(len(fetches), 1)
```

`_repo_with_apollo_record` / `_repo_with_karaoke` / `_repo_with_mdx_c_missing_yaml` / `_separate_spec` are local fakes in this test module. Reuse `tests/test_job_plan_topology.py` `MdxCOfflinePlanningTests` for the JobSpec shape. `JobResolver.resolve` must grow an `allow_network: bool = True` argument (online default).

Reuse `tests/test_job_plan_topology.py` `MdxCOfflinePlanningTests` and invert the default: offline is now opt-in.

- [ ] **Step 2: Run tests to verify they fail**

Expected: Apollo still overwrites the filename; splitter substring still works; plan still forces `mdx_c_network(False)`.

- [ ] **Step 3: Implement**

Add `--offline` in `cli/separate.py` `add_separate_args`, ensemble parser, audio parser, replay parser, and `models validate`. Thread `allow_network=not args.offline` into `JobResolver.resolve` / `AudioJobResolver`.

```python
# resolve_splitter_identity
def resolve_splitter_identity(reference: str, settings: Settings, repo: Any) -> str:
    from core.model_identity import ModelIdentityService, parse_stored_model_id
    parse_stored_model_id(reference)  # raises on display/substring
    service = ModelIdentityService(repo)
    record = service.index.lookup(reference)
    if record.family not in {"vr", "mdx"}:
        raise ValueError(f"model {record.id} is not eligible for this setting")
    pool = {service.canonical_id_from_member_tag(tag) for tag in repo.karaoke_model_list(settings)}
    # During this task karaoke_model_list may still return Arch: Display tags.
    # Compare against canonical ids. If canonical_id_from_member_tag still
    # parses displays, that is OK until Task 19; membership is the planning check.
    if record.id not in pool:
        raise ValueError(f"model {record.id} is not an installed vocal splitter")
    return record.id
```

Expose `service.index` as the published `IdentityIndex`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_identity_planning tests.test_job_plan_topology tests.test_cli_redesign -v
```

- [ ] **Step 5: Commit**

```bash
git add core/audio_plan.py core/settings/job_resolution.py core/job_plan.py cli tests
git commit -m "$(cat <<'EOF'
feat: keep Apollo IDs canonical and fetch MDX YAML only for the active model

EOF
)"
```

---

### Task 12: Engine consumers use carried display and backend name

**Files:**
- Modify: engines that read `model_name` for logging, output naming, or version detection — `rg -n "model_name" engines core/run_hooks.py core/export_naming.py`
- Modify: `engines/base.py`, `engines/demucs_engine.py` if they parse display prefixes
- Do not change stem export naming.

**Interfaces:**
- Diagnostics / logs / output titles: `model_display_label` (or `model_name` if still aliased).
- Backend caches / LocalRepo: `backend_name`.
- Inference must not call `resolve_*_model_basename`.
- If actual Demucs source count ≠ declared layout, raise an actionable error. Unit-test with a stubbed output count, not a real forward pass.

- [ ] **Step 1: Write the failing tests**

Add a test that patches the Demucs engine's post-inference stem count to 4 while spec says 6 and expects `ValueError` mentioning source layout. Keep it in `tests/test_identity_planning.py` with the engine function extracted if needed so GTK/torch is not required. If the check lives on `ModelConfig` / orchestration, test that function directly.

- [ ] **Step 2–4:** Implement the mismatch check; switch log/name call sites; run `tests.test_identity_planning tests.test_run_estimate` plus any engine unit tests that do not import torch at module level.

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat: stop engines parsing display text for model identity

EOF
)"
```

---

### Task 13: Custom Demucs registry document

**Files:**
- Modify: `core/demucs_registry.py` (writes)
- Modify: `core/model_registry.py` only if you must reject dual-index writes — Demucs must **not** update the global hash index
- Create path: `{DEMUCS_MODELS_DIR}/model_data/registered_models.json`

**Interfaces:** Schema as in the spec (`schema_version`, `models` keyed by canonical ID, `by_primary_hash`). Atomic replace via `core.json_store.write_json_atomic` / existing locked JSON helpers. `models` is authoritative; `by_primary_hash` is rebuilt from it on load if mismatched.

- [ ] **Step 1: Write tests in `tests/test_demucs_registry.py`** for load empty, round-trip write, hash index rebuilt, path containment rejection (`../`).

- [ ] **Step 2:** FAIL on missing writer.

- [ ] **Step 3:** Implement `DemucsRegistry.load/save` with the lock file next to the JSON.

- [ ] **Step 4–5:** Tests + commit `feat: add versioned Demucs registered_models.json`.

---

### Task 14: `models register` / `configure` / `reset` for Demucs

**Files:**
- Modify: `cli/discovery.py` `cmd_models_register`, `cmd_models_configure`
- Modify: `core/demucs_registry.py`, `core/model_inventory.py` (apply registration at step 4 of projection)
- Modify: `tests/test_demucs_registry.py`

**Interfaces:** `--config` required for Demucs. Schema:

```json
{"demucs_version": "v4", "source_layout": "6_stem", "display_name": "My model"}
```

Copy artifacts to temp, promote, then commit registry, then `invalidate_models()`. No partial registry. Adopt orphan destinations only when fingerprints match. Configure must not move between v1/v2 dir and `v3_v4_repo`. Reset drops metadata; artifact remains with `identity_complete=False`.

v3/v4 weights: `signature.th` or one `signature-checksum.th`. `backend_name` = LocalRepo signature.

- [ ] **Step 1: Tests** — no config fails before copy; invalid version/layout/extension fails before copy; complete bag copies all members; collision leaves no files; configure refuses a version change that would move dirs.

Use `tempfile.TemporaryDirectory` and `UVR_DATA_DIR`.

- [ ] **Step 2–5:** Implement, run `tests.test_demucs_registry tests.test_cli_list_models`, commit `feat: register and configure custom Demucs with version and layout`.

---

### Task 15: Two-stage persistence validation; delete the migrator

**Files:**
- Delete: `core/identity_migration.py`
- Modify: `core/settings/model.py`, `core/settings/defaults.py` (drop `identity_schema_version` from writers; ignore it on read)
- Modify: `ui/application.py`, `ui/window.py`, `ui/context.py` (remove `start_identity_migration`)
- Modify: `core/ensemble_service.py` (stop emitting `identity_schema_version`)
- Modify: `cli/profiles.py` (validate `model` / `members` / sparse settings model paths; never `Settings.from_json_dict` on sparse CLI JSON)
- Modify: `tests/test_core_consolidation.py` (`IdentityServiceTests` — replace migration cases with keep-text cases)
- Modify: `tests/test_identity_cutover.py` (new)

**Interfaces:**
- Stage 1 (no repo): each model-valued string is a sentinel or `parse_stored_model_id` succeeds. Illegal values stay in the field; collect warnings (non-persisted list on `Settings` or returned from `from_json_dict`).
- Stage 2 (repo bound): lookup, installed, `identity_complete`, field eligibility.
- GUI: no selection + warning; `populate_models` must not `lookup` then `set_flat` Choose/No Model.
- CLI runtime identity args: fail with `expected canonical model ID family:basename` and hint `uvr models list`.
- Readers ignore obsolete `identity_schema_version`; writers omit it.

- [ ] **Step 1: Tests**

```python
class KeepTextCutoverTests(unittest.TestCase):
    def test_display_in_settings_is_preserved(self) -> None:
        payload = default_settings_dict()
        payload["mdx"]["model"] = "MDX-Net — UVR-MDX-NET Inst HQ 4"
        settings = Settings.from_json_dict(payload)
        self.assertEqual(settings.mdx.model, "MDX-Net — UVR-MDX-NET Inst HQ 4")
        self.assertNotIn("identity_schema_version", settings.to_json_dict())

    def test_sparse_cli_profile_is_not_inflated(self) -> None:
        import json
        import tempfile
        from unittest.mock import patch
        from cli.profiles import load_profile, PROFILE_SCHEMA_VERSION
        from core.settings import Settings

        payload = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "name": "sparse",
            "model": "mdx:UVR-MDX-NET-Inst_HQ_4",
            "members": [],
            "settings": {"process.vocal_splitter": "vr:UVR-De-Echo-Normal"},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = handle.name
        real = Settings.from_json_dict

        def wrapped(data):
            if isinstance(data, dict) and data.get("model") == payload["model"]:
                raise AssertionError("sparse profile fed to Settings.from_json_dict")
            return real(data)

        with patch.object(Settings, "from_json_dict", side_effect=wrapped):
            _settings, loaded = load_profile(path)
        self.assertEqual(loaded.model, "mdx:UVR-MDX-NET-Inst_HQ_4")
        self.assertEqual(
            loaded.settings["process.vocal_splitter"], "vr:UVR-De-Echo-Normal"
        )
```

Patch `Settings.from_json_dict` to raise if it is called from the sparse loader.

- [ ] **Step 2:** FAIL (migrator still stamps 2 / clears to Choose Model).

- [ ] **Step 3:** Delete migrator; update all imports (`rg identity_migration`). Implement syntax warnings. Update `IdentityServiceTests` that expected clears.

- [ ] **Step 4:**

```bash
.venv/bin/python -m unittest tests.test_identity_cutover tests.test_core_consolidation tests.test_cli_redesign tests.test_ensemble_presets -v
```

- [ ] **Step 5: Commit** `feat: drop identity migration and keep illegal stored model strings`.

---

### Task 16: GUI pickers from installed records

**Files:**
- Modify: `ui/views/base.py` `populate_models`
- Modify: ensemble picker, `ui/widgets/vocal_split_row.py`
- Modify: Demucs method view — warning banner for `identity_complete=False`
- Modify: `tests/test_method_view_refresh.py`, add picker tests (GTK `skipUnless` DISPLAY/WAYLAND)

**Interfaces:**
- Items are `(record.id, record.display)` triples plus family for ensemble disambiguation only.
- Sort: existing SDR order; tie-break `(display.casefold(), id)`. Never `{display: basename}`.
- Membership: installed records only (`inventory_generation`). Include incomplete Demucs `.th`/YAML. Exclude Demucs-root `.ckpt` and uninstalled catalogue rows.
- Write-gate:

```python
stored = get_flat(self.settings, self.model_key, CHOOSE_MODEL)
ids = {item[0] for item in items}
if stored not in (CHOOSE_MODEL, NO_MODEL, None, "") and stored not in ids:
    try:
        parse_stored_model_id(str(stored))
        present = any(r.id == stored for r in installed)
        if not present:
            set_combo_value(self.model_row, CHOOSE_MODEL)  # visual only
            # do not set_flat
            return
    except ValueError:
        set_combo_value(self.model_row, CHOOSE_MODEL)
        # do not set_flat
        return
```

Never `set_flat` a resolved ID or sentinel over a non-canonical stored string.

Incomplete Demucs: selectable; persistent `Adw.Banner` on the method page until `identity_complete`. Planning still names the missing field.

Incomplete MDX: existing unrecognized-checkpoint dialog unchanged.

- [ ] **Step 1: Tests** — duplicate displays keep two IDs; write-gate does not call `set_flat` for `"v4 — htdemucs"`; SDR sort still works. Use `MethodView.__new__` where possible; GTK tests for the banner.

- [ ] **Step 2–5:** Implement, run picker tests + `tests.test_vocal_split_row tests.test_method_view_refresh`, commit `feat: populate model pickers from installed identity records`.

---

### Task 17: CLI list/show JSON, strict identity args, curated presets

**Files:**
- Modify: `cli/discovery.py`, `cli/job.py` `_canonicalize_model_references`
- Modify: `bundled/ensemble_presets/*.json` if any member is not `family:basename` (currently already IDs — add a unit test that asserts that)
- Modify: `core/ensemble_presets.py` — missing member download uses `record.catalogue_entry`, not display inversion. Delete runtime `canonical_id_from_member_tag` display parsing once pickers are migrated (or leave a shim until Task 19).
- Modify: `tests/test_cli_list_models.py`, `tests/test_ensemble_presets.py`

**Interfaces:**
- `models list --all-known`: every published `ModelRecord`. No YAML rows, no bag members, no unsupported catalogue, no Demucs-root `.ckpt`.
- `models show|validate|configure`: canonical IDs only.
- Untargeted `models validate` reports unsupported installed artifacts (Demucs-root `.ckpt`).
- JSON fields: `id`, `family`, `display`, `backend_name`, artifacts, `installed`, `identity_complete`, `identity_error`, Demucs/MDX specs. No `engine_name`.
- `models catalog --query` stays free text. `models download` stays Task 1 matching.

- [ ] **Step 1: Tests** for JSON keys, `--all-known` cardinality on the fake index, bare basename rejected by `uvr separate` canonicalization, curated preset static check:

```python
class CuratedPresetIdTests(unittest.TestCase):
    def test_every_bundled_member_is_a_canonical_id(self) -> None:
        from core.model_identity import parse_stored_model_id
        from pathlib import Path
        import json
        root = Path("bundled/ensemble_presets")
        for path in root.glob("*.json"):
            payload = json.loads(path.read_text())
            for member in payload["selected_models"]:
                parse_stored_model_id(member)
```

- [ ] **Step 2–5:** Implement, commit `feat: report backend_name and require canonical IDs on the CLI`.

---

### Task 18: Schema-3 replayable manifests

**Files:**
- Modify: `cli/execution.py` `MANIFEST_SCHEMA_VERSION = 3`, `write_manifest`
- Modify: `cli/audio.py` `_write_audio_manifest` → schema 3
- Modify: `cli/replay.py` accept **only** schema 3; require `model_dependencies` and `model_identity_digest`
- Modify: `tests/test_identity_cutover.py`, `tests/test_model_identity_contracts.py` (update snapshot tests)
- Do **not** change `cli/bench.py`

**Interfaces:** Even when there is no model (should be rare), emit `"model_dependencies": {}` and the digest of that empty map. Replay recomputes digest, validates each ID against family/field constraints, then builds the sparse profile from IDs. Schema 1/2 → compatibility error, no fuzzy lookup.

`--allow-model-change` may accept checkpoint-hash **and** digest drift and must report recorded vs current values. It must not accept wrong family, illegal ID, or old schema.

- [ ] **Step 1: Tests** — writer emits schema 3 + both fields; replay rejects schema 1; `--allow-model-change` reports digest drift; bench source still `"schema_version": 1`.

- [ ] **Step 2–5:** Implement, update `docs/environment.md` table in Task 20 or here if tests read it. Commit `feat: require schema-3 manifests with an identity digest`.

---

### Task 19: Remove reverse resolution and add the AST guard

**Files:**
- Modify: `core/model_display.py` — keep forward `map_basenames_to_display` / `format_tag_title` / mapper ingestion. Runtime resolvers `resolve_mdx_model_basename`, `resolve_vr_model_basename`, `resolve_demucs_model_basename`, `resolve_model_basename` must not be imported from engines/`model_config`/`job_plan`/`assemble`/`determine`/`run_hooks`/CLI job paths. Either delete them or keep them private to `model_display` for catalogue scripts.
- Delete `ModelIdentityService.resolve(..., fuzzy=True)` and `resolve_model_record` fuzzy branch. Replace remaining callers with `lookup`.
- Delete `canonical_id_from_member_tag` display parsing if still present.
- Create: `tests/test_no_runtime_display_inversion.py`
- Modify: `tests/test_demucs_name_resolution.py` — keep mapper ingestion tests; drop tests that exist only to lock runtime inversion.

**Allowlist for the guard:** `core/model_display.py`, `tests/`, `scripts/`.

**Forbidden modules:** `engines/`, `core/model_config/`, `core/job_plan.py`, `core/model_config/assemble.py`, `core/model_config/determine.py`, `core/run_hooks.py`, `cli/job.py`, `cli/execution.py`, `cli/audio.py`, `cli/replay.py`.

Forbidden imported names: `resolve_mdx_model_basename`, `resolve_vr_model_basename`, `resolve_demucs_model_basename`, `resolve_model_basename`, `resolve_mapper_basename` (unless a listed allowlist file).

- [ ] **Step 1: Write the guard test** (mirror `tests/test_no_core_flat_settings.py`):

```python
import ast
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[1]
_FORBIDDEN = {
    "resolve_mdx_model_basename",
    "resolve_vr_model_basename",
    "resolve_demucs_model_basename",
    "resolve_model_basename",
    "resolve_mapper_basename",
}
_ALLOWLIST = {
    Path("core/model_display.py"),
}
_SCAN_DIRS = ("engines", "core", "cli")
_SKIP_PREFIXES = (
    Path("core/model_display.py"),
    Path("tests"),
    Path("scripts"),
)


class NoRuntimeDisplayInversionTests(unittest.TestCase):
    def test_runtime_modules_do_not_import_display_to_basename_helpers(self) -> None:
        violations: list[str] = []
        for folder in _SCAN_DIRS:
            for path in sorted((_ROOT / folder).rglob("*.py")):
                relative = path.relative_to(_ROOT)
                if relative in _ALLOWLIST or relative.parts[0] in {"tests", "scripts"}:
                    continue
                if relative.as_posix().startswith("core/model_display"):
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            if alias.name in _FORBIDDEN:
                                violations.append(f"{relative}:{node.lineno}:{alias.name}")
        self.assertEqual(violations, [], "\n".join(violations))
```

- [ ] **Step 2:** FAIL listing current `config.py` / `assemble.py` / `model_identity.py` imports.

- [ ] **Step 3:** Remove those imports and the fuzzy resolver. `ModelIdentityService.display_label` uses `lookup`. CLI `resolve_model_id` becomes lookup-only.

- [ ] **Step 4:**

```bash
.venv/bin/python -m unittest tests.test_no_runtime_display_inversion tests.test_model_identity_contracts tests.test_identity_planning tests.test_identity_cutover tests.test_demucs_name_resolution tests.test_model_display -v
```

- [ ] **Step 5: Commit** `feat: forbid runtime display-to-basename model resolution`.

---

### Task 20: Documentation and architectural guidance

**Files:**
- Modify: `docs/cli.md`, `docs/environment.md`, `docs/models.md`, `CLAUDE.md`
- Modify: `docs/model_id_refinement.md` status line if it still says “locked, not implemented”

Document: IDs vs display vs selectable vs `backend_name` vs artifacts; no migrator (user re-picks); `--offline`; schema 3; `models download` fuzzy is catalogue-only; Demucs-root `.ckpt` is a validate diagnostic.

- [ ] **Step 1:** No new tests unless a docs `--check` script exists. Run `python scripts/generate_models_catalogue.py --check` only if this task did not touch catalogue generation (it should not).

- [ ] **Step 2:** Edit the docs. Add a CLAUDE.md invariant: identity index publish shares `invalidate_models`; picker membership is installed records; runtime must not import display-to-basename helpers.

- [ ] **Step 3:** Full verification:

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python -m basedpyright
git diff --check
```

GTK picker tests run under xvfb in CI. Locally they need `DISPLAY` or `WAYLAND_DISPLAY`.

- [ ] **Step 4: Commit** `docs: describe canonical model identity and the schema-3 cutover`.

---

## Self-review

**Spec coverage**

| Spec section | Task |
|---|---|
| Value types, `backend_name`, no `engine_name` JSON | 2 |
| Strict `family:basename`, no fuzzy lookup | 3, 19 |
| `meta_by_family`, no coordinator re-key, primary-only indexes | 4 |
| Logical cardinality, adapters, `.th.gz`, Demucs-root `.ckpt` | 5 |
| Collisions, path safety, generation-checked publish | 6 |
| Bundled `DemucsSpec`, label-import rules | 7 |
| Active nested map, digest, 4-stem slots | 8 |
| assemble / paths / determine no display inversion | 9 |
| DemucsSpec assignment, VR arch normalize | 10 |
| Apollo ID, splitter exact, YAML fetch policy, `--offline` | 11 |
| Engine display audit, layout mismatch | 12 |
| Demucs registry + register/configure | 13–14 |
| No migrator, keep-text, sparse CLI, write-gate | 15–16 |
| CLI JSON, `--all-known`, curated IDs | 17 |
| Schema 3 manifests, `--allow-model-change` | 18 |
| AST guard, delete reverse resolvers | 19 |
| Docs | 20 |
| Catalogue download matching preserved | 1, 17 |
| `mdx:` stays one family; `MdxSpec.kind` closed set | 2, 5 |
| Index offline | 5, 11 |

**Placeholder scan:** none of TBD / “handle edge cases” / “similar to Task N” remain as the only instruction — family-adapter internals are specified in Task 5; Demucs JSON is specified in Task 7; digest JSON is specified in Task 8.

**Type consistency:** `CatalogueRef.selection` (not `.key`); `backend_name`; `IdentityIndex.lookup`; `model_dependencies` dotted paths with `ensemble.selected_models[i]`; digest prefix `sha256:`; manifest `schema_version` 3.

---

## Delivery gates (from the spec)

After each task: focused unittest modules listed in that task + basedpyright on touched files.

Before calling the work complete:

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python -m basedpyright
git diff --check
```

Plus GTK picker write-gate tests, offline/network-denial tests for index build and `--offline` plan, and CLI human/JSON contract tests.
