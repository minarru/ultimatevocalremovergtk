# Model ID Improvement Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the seven Important and one Minor branch-review findings without weakening the locked canonical-ID, offline-index, active-dependency, or keep-text contracts.

**Architecture:** Keep canonical IDs in settings and persistence, carry resolved `ModelRecord` data across planning/runtime boundaries, and reserve fuzzy catalogue matching for catalogue operations. Build inventory only from offline trusted evidence, make command owners inject catalogue snapshots explicitly, derive nested model topology once from the resolved primary, and expose preserved invalid GUI values through field-specific warnings.

**Tech Stack:** Python 3.14, `unittest`, GTK4/libadwaita, immutable model identity records, `CatalogueCoordinator`, basedpyright.

**Spec:** `docs/model_id_refinement.md`

**Review:** `docs/reviews/2026-08-22-model-id-improvement-branch-review.md`

## Global Constraints

- Runtime and persisted model identities are exact `family:basename` values; runtime never parses display text or silently qualifies a basename.
- `models download` and catalogue search retain catalogue-facing fuzzy matching; runtime lookup does not.
- Settings retain canonical IDs. Engine filenames and checkpoint paths travel separately through records/descriptors.
- Index construction is offline, does not hash checkpoints, and does not write metadata.
- Only active model paths enter dependency maps and identity digests; runtime consumes the same topology.
- Illegal stored values remain verbatim, show no picker selection, and surface a warning until explicitly repicked.
- Read-only CLI commands do not access the network and close command-owned catalogue coordinators.
- No staging or commits unless the user explicitly requests them.

---

### Task 1: Enforce strict runtime IDs and preserve saved-ensemble warnings

**Files:**
- Modify: `core/model_identity.py`
- Modify: `cli/profiles.py`
- Modify: `cli/audio.py`
- Modify: `core/ensemble_service.py`
- Modify: `core/ensemble_presets.py`
- Modify: `cli/discovery.py`
- Test: `tests/test_cli_list_models.py`
- Test: `tests/test_identity_cutover.py`
- Test: `tests/test_cli_redesign.py`

**Interfaces:**
- Consumes: `parse_stored_model_id(value: str) -> ModelId`, `IdentityIndex.lookup(model_id: str) -> ModelRecord`, and `CliModelLookup.lookup(...)`.
- Produces: strict `ModelIdentityService.resolve(...)` semantics and `ResolvedEnsemblePreset.validation_warnings: tuple[str, ...]`.

- [x] **Step 1: Write strict-boundary regression tests**

Add literal behavior tests which assert that `ModelIdentityService.resolve` rejects a bare basename and legacy `Arch: basename`, Apollo CLI resolution rejects `--model restorer` with the discovery hint, GUI-profile extraction preserves an illegal value instead of prefixing it, and saved ensemble resolution retains reader warnings:

```python
with self.assertRaisesRegex(ValueError, "not a canonical model ID"):
    service.resolve("model", family="mdx")

with self.assertRaisesRegex(ValueError, "not a canonical model ID"):
    service.resolve("MDX-Net: model")

self.assertEqual(preset.validation_warnings, tuple(document.validation_warnings))
```

Replace existing tests that require legacy ensemble/basename conversion with strict rejection or keep-text assertions. Keep catalogue download fuzzy-resolution tests unchanged.

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_cli_list_models tests.test_identity_cutover tests.test_cli_redesign -v
```

Expected: new strict-service, Apollo, GUI-profile, and ensemble-warning tests fail because permissive qualification/conversion still occurs or warnings are dropped.

- [x] **Step 3: Implement strict resolution and warning propagation**

Make `ModelIdentityService.resolve` parse the supplied canonical ID before applying family/eligibility checks and route its lookup through `IdentityIndex.lookup`. Remove runtime use of basename matching and `_qualify_stored_model`. Use `CliModelLookup` at Apollo and model-administration CLI boundaries. Resolve curated preset IDs exactly; preserve illegal saved user ensemble members and carry `EnsembleDocument.validation_warnings` in `ResolvedEnsemblePreset` rather than converting them.

The intended service shape is:

```python
model_id = parse_stored_model_id(str(query or "").strip())
record = self.lookup(model_id.value)
if family is not None and record.family != family.casefold():
    raise ValueError(...)
return record
```

- [x] **Step 4: Run the focused tests and verify GREEN**

Run the Step 2 command. Expected: PASS with no network access or persisted rewrites.

- [x] **Step 5: Run direct consumer regressions**

Run:

```bash
.venv/bin/python -m unittest tests.test_ensemble_presets tests.test_core_consolidation tests.test_audio_cli -v
```

Expected: PASS.

---

### Task 2: Complete offline inventory projection and all-known catalogue ownership

**Files:**
- Modify: `core/model_inventory.py`
- Modify: `core/model_identity.py`
- Modify: `cli/discovery.py`
- Test: `tests/test_model_identity_contracts.py`
- Test: `tests/test_model_pools_real_repository.py`
- Test: `tests/test_cli_list_models.py`

**Interfaces:**
- Consumes: repository `model_hash_table`, trusted local hash metadata, `CatalogueCoordinator.ensure(vip=True, allow_network=False)`, and existing MDX-C config loading/type inference.
- Produces: targetable `ModelRecord`s for configured installed MDX-C checkpoints and a command-owned catalogue-backed repository for `models list --all-known`.

- [x] **Step 1: Write inventory and command integration regressions**

Add real-data-shape tests proving:

```python
record = build_identity_index(repo).lookup("mdx:configured")
self.assertTrue(record.identity_complete)
self.assertEqual(record.artifacts.supporting_filenames, ("configured.yaml",))
self.assertEqual(record.mdx.kind, "bs_roformer")
```

The fixture must place the checkpoint in the MDX model root, place YAML in the patched `MDX_C_CONFIG_PATH`, and seed the trusted checkpoint hash plus hash JSON `config_yaml` association without hashing the checkpoint during index construction.

Add installed filename cases `.pth`, `bad:name.pth`, and an unexpected nested family path; assert the malformed row is omitted while a valid sibling remains.

Add a command-level `--all-known` test with a fake offline `CatalogueCoordinator` snapshot and the real repository/index construction. Assert an uninstalled catalogue record appears and `close()` is called. Do not patch `_published_index`.

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_model_identity_contracts tests.test_model_pools_real_repository tests.test_cli_list_models -v
```

Expected: configured MDX-C remains incomplete, malformed IDs publish, and command-level catalogue-only rows are absent.

- [x] **Step 3: Implement offline MDX association and record validation**

Add a contained helper which reads only trusted cached metadata to associate an installed checkpoint with its config filename/path and infer `MdxSpec`. Reuse the existing MDX-C loader/inference path for tagged YAML. Do not calculate a checkpoint hash or fetch YAML during index construction.

Validate the derived ID before constructing a record:

```python
model_id = ModelId(family, basename)
return ModelRecord(id=model_id.value, family=family, basename=basename, ...)
```

Reject family-relative artifact layouts not explicitly supported by that family and let existing per-row containment omit the bad row.

- [x] **Step 4: Implement command-owned offline catalogue injection**

For `--all-known`, construct `CatalogueCoordinator`, attach it to `ModelRepository`, build rows, and close the coordinator in `finally`. The coordinator call must use `allow_network=False`. Default installed-only listing may remain on a bare repository.

- [x] **Step 5: Run the focused tests and verify GREEN**

Run the Step 2 command. Expected: PASS.

- [x] **Step 6: Run the real repository invariant probe**

Run a read-only probe over installed MDX records and assert every legacy-configured checkpoint is `identity_complete=True`; report any intentional unconfigured checkpoint separately. Also run:

```bash
.venv/bin/python -m unittest tests.test_model_identity_duplicates tests.test_mdx_c_registry -v
```

Expected: PASS.

---

### Task 3: Make planned topology and runtime backend handoffs identical

**Files:**
- Modify: `core/job_plan.py`
- Modify: `cli/job.py`
- Modify: `core/model_config/determine.py`
- Modify: `core/model_config/config.py`
- Modify: `core/audio_plan.py`
- Modify: `cli/audio.py`
- Modify: `core/audio_tools.py`
- Test: `tests/test_identity_planning.py`
- Test: `tests/test_identity_cutover.py`
- Test: `tests/test_cli_audio.py`
- Test: `tests/test_audio_tools_naming.py`

**Interfaces:**
- Consumes: resolved primary `ModelRecord`, its normalized native primary stem, active dependency records, and `ResolvedAudioJob.model.backend_name`/checkpoint.
- Produces: one active-secondary topology shared by canonicalization, planning, replay/staleness, and nested assembly; explicit Apollo backend data for execution.

- [x] **Step 1: Write MDX topology regression tests**

Add table-driven literal expectations for Vocals, Instrumental, Other, Bass, and Drums, including lowercase native stems. Prove inactive secondary slots are ignored by CLI canonicalization, the runtime-created secondary has the same canonical ID as `model_dependencies`, and the digest contains exactly that path.

```python
cases = (
    ("Vocals", "mdx.voc_inst_secondary_model"),
    ("Instrumental", "mdx.voc_inst_secondary_model"),
    ("Other", "mdx.other_secondary_model"),
    ("Bass", "mdx.bass_secondary_model"),
    ("Drums", "mdx.drums_secondary_model"),
)
```

- [x] **Step 2: Write Apollo execution handoff regressions**

Construct a resolved Apollo plan whose settings contain `apollo:restorer` and whose descriptor backend is `restorer.ckpt`. Exercise the real runner boundary with inference patched below it; assert the observed checkpoint ends in `/restorer.ckpt` and never contains `apollo:`. Also assert `_run_audio` builds `ApolloModelData("restorer.ckpt")`.

- [x] **Step 3: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_identity_planning tests.test_identity_cutover tests.test_cli_audio tests.test_audio_tools_naming -v
```

Expected: MDX plan/runtime paths disagree and Apollo execution observes the canonical ID as a filename.

- [x] **Step 4: Implement a shared active-secondary decision**

Resolve primary identity/topology first. Derive the applicable slot from the normalized native primary stem, with Demucs multi-source widening preserved. Reuse the resulting active paths in CLI canonicalization and dependency construction. Pass resolved dependency records into nested `ModelConfig` construction rather than creating a new identity decision from raw settings.

One helper owns the mapping:

```python
def secondary_slot_for_primary_stem(primary_stem: str) -> str | None:
    return {
        "vocals": "voc_inst", "instrumental": "voc_inst",
        "other": "other", "bass": "bass", "drums": "drums",
    }.get(primary_stem.strip().casefold())
```

- [x] **Step 5: Implement explicit Apollo backend handoff**

Keep `settings.audio_tools.apollo_model` canonical. Add a runtime-only backend/checkpoint input sourced from `ResolvedAudioJob.model` and pass it into `AudioToolRunner`/`AudioTools`. Both `ApolloModelData` and inference must consume that explicit backend value.

- [x] **Step 6: Run focused tests and verify GREEN**

Run the Step 3 command. Expected: PASS.

- [x] **Step 7: Run planning/replay regression suites**

Run:

```bash
.venv/bin/python -m unittest tests.test_engine_identity_consumers tests.test_no_runtime_display_inversion tests.test_cli_replay tests.test_cli_redesign -v
```

Expected: PASS.

---

### Task 4: Repair model-defaults identity consumption and surface every GUI warning

**Files:**
- Modify: `ui/dialogs/model_params.py`
- Modify: `ui/views/base.py`
- Modify: `ui/widgets/vocal_split_row.py`
- Modify: `ui/audio_tools/window.py`
- Modify: `ui/ensemble/window.py`
- Modify: `core/ensemble_service.py`
- Test: `tests/test_method_view_refresh.py`
- Test: `tests/test_vocal_split_row.py`
- Test: `tests/test_apollo_picker_write_gate.py`
- Test: `tests/test_model_picker_records.py`
- Test: `tests/test_identity_cutover.py`
- Create: `tests/test_model_params_identity.py`
- Test: `tests/test_ensemble_model_eligibility.py`
- Test: `tests/test_saved_ensembles.py`

**Interfaces:**
- Consumes: exact `ModelIdentityService.lookup`, stage-one and stage-two validation warnings, and `ResolvedEnsemblePreset.validation_warnings` from Task 1.
- Produces: valid dry `ModelConfig` objects for Change Model Defaults and visible field-specific warning state for every identity picker.

- [x] **Step 1: Write Change Model Defaults consumer tests**

Exercise the dialog helper or an extracted core-sized helper with a canonical VR/MDX tag and real identity index. Assert both normal dry inspection and `is_get_hash_dir_only=True` receive a valid `ModelConfig` with the correct canonical ID/process method.

- [x] **Step 2: Write warning-surfacing tests for every picker**

For secondary, vocal splitter, Apollo, and saved ensemble controls, restore a noncanonical or missing stored value. Assert all three behaviors together:

```python
self.assertEqual(settings_value, original_illegal_text)
self.assertEqual(get_combo_value(row), CHOOSE_MODEL)
self.assertIn(original_illegal_text, visible_warning_text)
```

Then simulate an explicit valid repick and assert the warning clears and the canonical ID is written. Tests must inspect live banner/row state, not source text.

- [x] **Step 3: Run GUI-focused tests and verify RED**

Run with active Wayland/DBus:

```bash
WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 GDK_BACKEND=wayland DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 .venv/bin/python -m unittest tests.test_method_view_refresh tests.test_vocal_split_row tests.test_apollo_picker_write_gate tests.test_model_picker_records tests.test_identity_cutover tests.test_model_params_identity tests.test_ensemble_model_eligibility tests.test_saved_ensembles -v
```

Expected: Change Model Defaults is invalid without identity and the non-primary warning assertions fail.

- [x] **Step 4: Pass exact identity into Change Model Defaults**

Resolve the selected canonical ID once and call `ModelConfig` with `identity=record`, `record.display`, and `record.arch`, preserving both dry-inspection modes.

- [x] **Step 5: Add shared warning state to non-primary pickers**

Use the existing stage-one/stage-two warning wording and primary method banner pattern. Preserve write gates. Each picker stores its field-specific warning until an explicit valid repick; refresh alone must not clear or rewrite it. Propagate saved-ensemble document warnings through service resolution into the ensemble page banner.

- [x] **Step 6: Run GUI-focused tests and verify GREEN**

Run the Step 3 command. Expected: PASS without GTK warnings or crashes.

- [x] **Step 7: Run complete verification**

Run:

```bash
WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 GDK_BACKEND=wayland DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus MPLCONFIGDIR=/tmp/uvr-mpl-model-id-remediation PYTHONWARNINGS=ignore UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 .venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m basedpyright
git diff --check
```

Expected: full suite PASS, basedpyright reports zero errors/warnings/notes, and whitespace check is clean.
