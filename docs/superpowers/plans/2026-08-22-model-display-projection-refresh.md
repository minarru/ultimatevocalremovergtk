# Model Display Projection and Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Use `test-driven-development` for every behavior change and `verification-before-completion` before reporting success. Track progress with the checkbox steps below.

**Goal:** Make `ModelRecord.display` the authoritative friendly label everywhere, refresh mounted model consumers when presentation data changes, and publish each downloaded logical model exactly once when it becomes usable.

**Architecture:** Enrich display labels once at the end of offline inventory construction, keeping exact canonical `family:basename` identity and execution artifacts untouched. Add a presentation-only repository revision/event beside the existing full inventory event, route both through the same coalesced GTK repaint spine, and centralize post-download registration/usability/publication in one frontend-neutral finalizer used by both GTK and CLI.

**Tech Stack:** Python 3.14, immutable `ModelRecord` values, `CatalogueCoordinator`, GTK4/libadwaita, `unittest`, basedpyright.

**Spec:** `docs/superpowers/specs/2026-08-22-model-display-projection-refresh-design.md`

## Global Constraints

- Runtime and persisted identity remains the exact canonical `family:basename`. Display text must never resolve a runtime model.
- `ModelRecord.display` is presentation-only. Enrichment must not alter `id`, `family`, `basename`, `backend_name`, artifacts, MDX/Demucs specs, installation state, or identity completeness.
- The model identity digest continues to exclude `display`; a presentation-only change must not stale an effective plan or increment `inventory_generation`.
- Inventory projection accepts only exact catalogue or mapper evidence. Keep fuzzy/substring behavior confined to catalogue search and legacy display compatibility paths.
- Inventory construction and presentation refresh stay offline and side-effect free: no network, checkpoint hashing, probing, or settings writes.
- Full invalidation emits only `models_changed`. Presentation invalidation emits only `model_presentation_changed`.
- GTK callbacks may originate on worker threads. They must cross to the main loop through the existing coalesced refresh callback before touching widgets.
- Selection restoration is by canonical ID. A value that was warning-gated before refresh remains unselected until the user explicitly repicks it, even if that exact ID has become available.
- Vocal-splitter membership remains karaoke-only; display work may relabel eligible rows but must not broaden the pool.
- One queue item is one logical model. It publishes only after all declared artifacts and registration metadata are usable, and it owns at most one full invalidation.
- Preserve the user's dirty worktree. Do not stage or commit during execution unless the user explicitly authorizes it. Suggested commit messages are checkpoints only.

## Task 1: Add a Strict Mapper Lookup Primitive

**Files:**

- Modify: `core/model_display.py`
- Modify: `tests/test_model_display.py`

- [x] **Step 1: Write failing exact-match tests.**

  Add focused cases for a new public helper named `lookup_mapper_display_exact`:

  ```python
  def test_exact_mapper_lookup_accepts_basename_and_known_extension(self) -> None:
      mapper = {
          "model.ckpt": "Friendly CKPT",
          "other": "Other",
      }
      self.assertEqual(
          lookup_mapper_display_exact("model", mapper),
          "Friendly CKPT",
      )

  def test_exact_mapper_lookup_rejects_substring_candidate(self) -> None:
      self.assertIsNone(
          lookup_mapper_display_exact(
              "model",
              {"model_v2.ckpt": "Wrong model"},
          )
      )
  ```

  Cover the bare basename, every recognized mapper extension, an unrecognized extension, an empty/malformed mapper, and the substring-only regression.

- [x] **Step 2: Run the focused tests and confirm RED.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest tests.test_model_display -v
  ```

  Expected: new tests fail because `lookup_mapper_display_exact` does not exist.

- [x] **Step 3: Implement the exact helper without changing legacy lookup behavior.**

  In `core/model_display.py`, accept `Mapping[str, str] | None` and check only:

  ```python
  for extension in _MAPPER_EXTENSIONS:
      key = basename if not extension else f"{basename}{extension}"
      if key in name_mapper:
          return str(name_mapper[key])
  return None
  ```

  Do not call `lookup_mapper_display`, `resolve_mapper_basename`, `os.path.splitext` fallback loops, casefold matching, or substring matching from this helper. Leave the legacy helper intact for compatibility consumers that intentionally retain its old behavior.

- [x] **Step 4: Run the focused tests and confirm GREEN.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest tests.test_model_display -v
  ```

- [x] **Step 5: Review the diff for an accidental runtime inversion path.**

  ```bash
  rg -n "lookup_mapper_display_exact|resolve_mapper_basename" core tests
  ```

  Confirm the new helper maps basename to display only.

**Suggested commit checkpoint:** `feat: add exact model display mapper lookup`

## Task 2: Enrich Displays Once in the Inventory Projection

**Files:**

- Modify: `core/model_inventory.py`
- Modify: `tests/test_model_identity_contracts.py`
- Modify: `tests/test_model_display.py`

- [x] **Step 1: Add failing inventory projection tests.**

  Using the existing repository and catalogue snapshot fixtures, cover:

  1. friendly catalogue display wins over a conflicting mapper;
  2. catalogue basename echo falls through to an exact mapper;
  3. installed-only MDX and Demucs records receive an exact mapper display;
  4. VR uses its exact catalogue display index but has no mapper fallback;
  5. Apollo preserves exact catalogue/registered display and otherwise stays raw;
  6. unknown custom models retain the raw basename;
  7. substring-only mapper candidates are ignored;
  8. local mapper overlay precedence remains visible after enrichment;
  9. a registered Demucs display remains authoritative.

  Add a table-driven fixture representing several currently installed-style basenames and assert that every exact mapping agrees with the existing `main` presentation result, while unknown fixtures stay raw.

- [x] **Step 2: Add an invariant test around `dataclasses.replace`.**

  Snapshot the record before enrichment and assert that only `.display` changes:

  ```python
  self.assertEqual(enriched.id, original.id)
  self.assertEqual(enriched.family, original.family)
  self.assertEqual(enriched.basename, original.basename)
  self.assertEqual(enriched.backend_name, original.backend_name)
  self.assertEqual(enriched.artifacts, original.artifacts)
  self.assertEqual(enriched.demucs, original.demucs)
  self.assertEqual(enriched.mdx, original.mdx)
  self.assertEqual(enriched.installed, original.installed)
  self.assertEqual(enriched.identity_complete, original.identity_complete)
  ```

- [x] **Step 3: Run the inventory/display contract tests and confirm RED.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_model_display \
      tests.test_model_identity_contracts -v
  ```

- [x] **Step 4: Implement one final enrichment pass.**

  Add a private `_enrich_record_displays(repo, records, snapshot)` after all catalogue, installed, bundled-Demucs, and registered-Demucs merges and before collision detection:

  ```python
  records = _catalogue_records(snapshot) if snapshot is not None else []
  records = _merge_installed(repo, records)
  records = _apply_bundled_demucs(records, bundled_demucs_specs)
  records = _apply_registered_demucs(records, registered_demucs)
  records = _enrich_record_displays(repo, records, snapshot)
  return IdentityIndex(_detect_collisions(records))
  ```

  For each record:

  - preserve `record.display` when it is already non-empty and differs from `record.basename`;
  - otherwise consult the exact snapshot display index for its family;
  - treat an index value equal to the basename as a raw echo and continue;
  - for MDX and Demucs only, consult `lookup_mapper_display_exact` on the repository's current name mapper;
  - fall back to `record.basename`;
  - return the original object when the display is unchanged and `replace(record, display=...)` otherwise.

  Use only `snapshot.display_index_vr`, `snapshot.display_index_mdx`, and `snapshot.display_index_demucs`. Apollo has no mapper/display index beyond the display already carried by its catalogue or registration record.

- [x] **Step 5: Run the focused tests and confirm GREEN.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_model_display \
      tests.test_model_identity_contracts -v
  ```

- [x] **Step 6: Re-run the runtime inversion guard.**

  ```bash
  .venv/bin/python -m unittest tests.test_no_runtime_display_inversion -v
  ```

**Suggested commit checkpoint:** `feat: enrich inventory records with exact display names`

## Task 3: Separate Presentation Invalidation from Full Inventory Invalidation

**Files:**

- Modify: `core/model_repository.py`
- Modify: `core/downloads.py`
- Modify: `tests/test_model_repository_subscribers.py`
- Modify: `tests/test_model_repository_invalidation.py`
- Modify: `tests/test_model_display_cache.py`
- Modify: `tests/test_core_downloads.py`

- [x] **Step 1: Write failing presentation-event tests.**

  Mirror the existing `models_changed` contract for:

  - `subscribe_model_presentation_changed(callback)`;
  - `unsubscribe_model_presentation_changed(callback)`;
  - duplicate subscription idempotence;
  - unknown unsubscription as a no-op;
  - one event per invalidation;
  - listener exception isolation;
  - re-entrant notification suppression.

  Also assert that `invalidate_models()` emits `models_changed` once and does **not** emit `model_presentation_changed`.

- [x] **Step 2: Write failing cache/revision boundary tests.**

  Seed the identity cache, hash table, stem-check cache, and karaoke cache, then call:

  ```python
  repo.invalidate_model_presentation(reload_mappers=False)
  ```

  Assert:

  - identity/display projection cache is cleared;
  - `inventory_generation` is unchanged;
  - `naming_revision` is unchanged when mapper reload is false;
  - `model_hash_table`, `_stem_check_cache`, and `_karaoke_cache` remain the same objects/values;
  - no hash loader or hash-table provider is called;
  - the presentation event fires exactly once.

  Add the mapper-source variant and assert `naming_revision` increments once while hash maps and eligibility caches remain untouched.

- [x] **Step 3: Run the repository tests and confirm RED.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_model_repository_subscribers \
      tests.test_model_repository_invalidation \
      tests.test_model_display_cache -v
  ```

- [x] **Step 4: Split mapper loading by semantic layer.**

  Refactor `ModelRepository.reload_mappers()` into narrow private helpers:

  ```python
  def _reload_hash_mappers(self) -> None: ...

  def _reload_name_mappers(self) -> None:
      ...
      self._naming_revision += 1

  def reload_mappers(self) -> None:
      self._reload_hash_mappers()
      self._reload_name_mappers()
  ```

  Preserve initialization and full invalidation behavior. A presentation mapper refresh must call only `_reload_name_mappers()`.

- [x] **Step 5: Implement the presentation subscriber and invalidation APIs.**

  Add a separate subscriber list, lock, and re-entrancy guard beside the inventory event. Implement:

  ```python
  def invalidate_model_presentation(
      self, *, reload_mappers: bool = False
  ) -> None:
      with self._inventory_lock:
          if reload_mappers:
              self._reload_name_mappers()
          self._identity_cache_key = None
          self._identity_cache = None
      self._notify_model_presentation_changed()
  ```

  Do not increment inventory generation, rehydrate hashes, clear stem/karaoke caches, or emit the full inventory event. Keep callback invocation thread-agnostic and isolate failures through `core.debug_log.debug`.

- [x] **Step 6: Route mapper downloads to the narrowest event.**

  In `DownloadManager.update_model_settings`, track hash-map changes separately from name-mapper changes:

  - any hash-map change: `repo.invalidate_models()`;
  - name-mapper-only change: `repo.invalidate_model_presentation(reload_mappers=True)`;
  - no semantic change: no event.

  Full invalidation subsumes name changes; never emit both events for one mapper transaction.

- [x] **Step 7: Run focused tests and confirm GREEN.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_model_repository_subscribers \
      tests.test_model_repository_invalidation \
      tests.test_model_display_cache \
      tests.test_core_downloads -v
  ```

**Suggested commit checkpoint:** `feat: add presentation-only model invalidation`

## Task 4: Bridge Catalogue Display Deltas into the Repository Event

**Files:**

- Modify: `core/model_repository.py`
- Modify: `tests/test_model_repository_subscribers.py`
- Modify: `tests/test_catalogue_coordinator.py` only if its public delta contract needs an additional assertion

- [x] **Step 1: Write failing coordinator-bridge tests.**

  Use a small fake coordinator with `subscribe_delta`, `unsubscribe_delta`, and a current snapshot/revision. Assert that repository construction subscribes exactly once and that:

  - `DeltaKind.SOURCES_CHANGED` emits one presentation event;
  - `DeltaKind.IDENTITY_REFINED` emits one presentation event because an installed record may lose/gain its exact catalogue association;
  - `DeltaKind.METADATA_CHANGED` emits none because stem subtitles do not change model labels;
  - the bridge does not reload name mappers or increment inventory generation;
  - full repository invalidation remains a separate event.

- [x] **Step 2: Run the bridge tests and confirm RED.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_model_repository_subscribers \
      tests.test_catalogue_coordinator -v
  ```

- [x] **Step 3: Subscribe the repository to relevant typed deltas.**

  Bind a private `_on_catalogue_delta(delta)` in `ModelRepository.__init__` when the injected coordinator exposes `subscribe_delta`. Import `DeltaKind` lazily and call `invalidate_model_presentation(reload_mappers=False)` for source or identity deltas only.

  Do not call `coordinator.snapshot()` from the callback and do not remesh sources. The next identity read consumes the coordinator's already-published snapshot and revised display indexes.

- [x] **Step 4: Define lifecycle cleanup without creating a second owner.**

  The coordinator's existing `close()` clears its subscribers. If repository disposal already has an application-owned hook, unsubscribe there; otherwise document/test that coordinator shutdown owns callback release rather than adding an unused repository `close()` API.

- [x] **Step 5: Run the focused tests and confirm GREEN.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_model_repository_subscribers \
      tests.test_catalogue_coordinator -v
  ```

**Suggested commit checkpoint:** `feat: publish catalogue display changes through repository`

## Task 5: Route Both Repository Events through One GTK Refresh Spine

**Files:**

- Modify: `ui/window.py`
- Modify: `tests/test_model_refresh_spine.py`

- [x] **Step 1: Add failing dual-subscription/coalescing tests.**

  Extend the bare-window tests to prove:

  - initialization subscribes the same callback to `models_changed` and `model_presentation_changed`;
  - closing unsubscribes that callback from both;
  - either event schedules one `idle_on_main` flush;
  - one inventory event plus one presentation event before the idle callback still causes one repaint;
  - repaint never calls either invalidation method;
  - an active run defers/coalesces the repaint until completion.

- [x] **Step 2: Run the refresh-spine tests and confirm RED.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest tests.test_model_refresh_spine -v
  ```

- [x] **Step 3: Subscribe both signals to the existing coalescer.**

  Keep one `_model_refresh_armed` flag and one worker-to-main-loop callback. Rename `_on_models_changed` to `_on_model_projection_changed` only if it makes all call sites clearer; do not create parallel idle paths.

  The callback sequence stays:

  ```text
  repository event (any thread)
      -> arm once
      -> idle_on_main(...)
      -> run-state deferral check
      -> _apply_model_refresh()
  ```

- [x] **Step 4: Make `_refresh_models` repaint-only.**

  Remove the legacy `source != "repository"` branch that calls `repo.invalidate_models()`. All invalidation must happen before notification in repository/core code. Retain the run deferral and `_model_list_consumers()` traversal.

- [x] **Step 5: Run the focused tests and confirm GREEN.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest tests.test_model_refresh_spine -v
  ```

**Suggested commit checkpoint:** `feat: coalesce inventory and presentation refreshes in gtk`

## Task 6: Lock Picker Refresh, Selection, and Eligibility Behavior

**Files:**

- Modify: `ui/ensemble/window.py`
- Modify: `tests/test_model_picker_records.py`
- Modify: `tests/test_method_view_refresh.py`
- Modify: `tests/test_vocal_split_row.py`
- Modify: `tests/test_apollo_picker_write_gate.py`

- [x] **Step 1: Add failing ensemble dialog lifecycle tests.**

  Prove that `EnsemblePage.refresh_models()`:

  - rebuilds immediately from `_model_members_for_rebuild()` when `models_dialog.get_mapped()` is true;
  - clears `_models_dirty` after that rebuild;
  - marks `_models_dirty` without rebuilding when the dialog/page is inactive;
  - rebuilds the dirty list on `on_activated()`;
  - preserves hidden/warning-gated members throughout each path.

- [x] **Step 2: Add cross-picker relabel and repick regressions.**

  Reuse the existing fake rows/GTK fixtures to assert:

  - primary and Apollo pickers repaint immediately with a changed `record.display`;
  - expanded secondary/pre-process and vocal-splitter controls repaint on their existing idle/lazy path;
  - collapsed controls remain dirty and repaint on expansion;
  - a valid canonical selection survives label change/reorder without a settings write;
  - a previously gated exact canonical ID remains stored but unselected when that model appears, until the simulated user selects it;
  - duplicate labels keep distinct canonical combo/check values.

- [x] **Step 3: Add the vocal-splitter membership guard.**

  Supply one karaoke and one non-karaoke installed record with friendly displays. Assert that refresh presents the friendly karaoke label and canonical ID, and never adds the non-karaoke ID. Do not mock the result after filtering; exercise the row's real karaoke-pool boundary.

- [x] **Step 4: Run the focused GTK consumer tests and confirm RED.**

  Use the repository's supported GTK environment. If the host compositor is unavailable, invoke the `testing-gtk-headless` skill before retrying.

  ```bash
  WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 \
    GDK_BACKEND=wayland \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
    UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_model_picker_records \
      tests.test_method_view_refresh \
      tests.test_vocal_split_row \
      tests.test_apollo_picker_write_gate -v
  ```

- [x] **Step 5: Implement only the missing ensemble refresh branch.**

  Existing method, Apollo, and vocal-splitter refresh/lazy gates should remain intact. In `EnsemblePage.refresh_models`, keep the splitter refresh, then use the dialog's mapped state:

  ```python
  if self.models_dialog.get_mapped():
      self._models_dirty = False
      self._rebuild_model_list(self._model_members_for_rebuild())
  else:
      self._models_dirty = True
  ```

  Guard partially initialized test/window states with `getattr` as needed. Do not persist the rebuilt selection and do not clear `_models_write_gated`.

- [x] **Step 6: Run the focused tests and confirm GREEN.**

  Repeat the command from Step 4.

**Suggested commit checkpoint:** `fix: refresh model pickers without clearing selection gates`

## Task 7: Build One Transactional Download Publication Finalizer

**Files:**

- Create: `core/model_install.py`
- Modify: `core/model_registry.py`
- Modify: `core/mdx_c_registry.py` only if a readiness query is needed
- Modify: `core/apollo_registry.py` only if a readiness query is needed
- Create: `tests/test_model_install.py`
- Modify: `tests/test_mdx_c_registry.py`
- Modify: `tests/test_extra_catalog.py`

- [x] **Step 1: Define the result contract in tests.**

  Plan a small immutable result:

  ```python
  @dataclass(frozen=True)
  class ModelInstallResult:
      ready: bool
      published: bool
      metadata_changed: bool = False
      detail: str = ""
  ```

  And one shared entry point:

  ```python
  def finalize_downloaded_model(
      *,
      repo: ModelRepository,
      family: str,
      selection: str,
      jobs: Sequence[tuple[str, str]],
      transfer_result: str,
  ) -> ModelInstallResult: ...
  ```

  Both frontends will call this function; no family registry, transfer method, or batch callback may invalidate independently.

- [x] **Step 2: Write failing transaction tests.**

  Cover:

  - stopped/failed transfer: not ready, no registration, no invalidation;
  - one missing target from a multi-file item: not ready and no invalidation;
  - completed single-file VR/MDX-ONNX item: ready and one invalidation;
  - completed paired MDX-C item: registration occurs, fresh inventory candidate is installed and identity-complete, then one invalidation;
  - completed paired Apollo item: registration occurs, fresh inventory candidate is installed and identity-complete, then one invalidation;
  - supported catalogue Demucs entry: all declared artifacts and known execution spec are required before publish;
  - unchanged `exists` with complete metadata: ready but not published and no invalidation;
  - `exists` with repaired registration/ownership metadata: ready, published once;
  - registration that still cannot produce an installed identity-complete candidate: actionable `detail`, no invalidation;
  - repeated finalization is idempotent.

  Use a real temporary catalogue snapshot and artifact roots for the representative family integration cases. Patch only hashing/network boundaries, not the final inventory result.

- [x] **Step 3: Run the new tests and confirm RED.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest tests.test_model_install -v
  ```

- [x] **Step 4: Make ownership indexing report whether it changed metadata.**

  Change `ModelRegistryService.index_downloaded(...) -> bool` and make `remember_registered(...) -> bool` idempotent:

  - return false and avoid rewriting when the exact hash-to-canonical-ID entry already exists;
  - return true only when an entry is added or repaired;
  - callers that ignore the return remain source-compatible.

  Keep canonical IDs derived from family plus the exact downloaded checkpoint basename. Do not derive them from `selection` or display text.

- [x] **Step 5: Implement family registration and pre-publication verification.**

  In `core/model_install.py`:

  1. accept only `complete`/`exists` transfer results;
  2. verify every declared job target is a regular file;
  3. run MDX-C/Apollo registration and ownership indexing, accumulating `metadata_changed`;
  4. obtain the coordinator's current snapshot in offline mode;
  5. build a **fresh, uncached** candidate index with `build_identity_index(repo, snapshot=...)` after registration;
  6. locate the record for the exact `(family, selection)` catalogue reference;
  7. require `record.installed` and `record.identity_complete`;
  8. set `changed = transfer_result == "complete" or metadata_changed`;
  9. call `repo.invalidate_models()` exactly once only when `ready and changed`.

  The fresh candidate is a precondition check, not a publication: it must not write caches, increment generation, notify, fetch, or hash checkpoints. If no current catalogue snapshot exists, return a clear incomplete result rather than guessing from a filename.

  MDX-C/Apollo registration helpers continue to return “metadata changed”; do not add invalidation inside them. Catalogue Demucs downloads use their exact published spec and artifact transaction; do not invent a local registration row when none is required.

- [x] **Step 6: Run the focused registration/finalizer tests and confirm GREEN.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_model_install \
      tests.test_mdx_c_registry \
      tests.test_extra_catalog -v
  ```

**Suggested commit checkpoint:** `feat: centralize usable model download publication`

## Task 8: Move GTK and CLI Downloads onto the Shared Finalizer

**Files:**

- Modify: `core/downloads.py`
- Modify: `core/download_queue.py`
- Modify: `ui/download.py`
- Modify: `ui/download_center.py`
- Modify: `ui/window.py`
- Modify: `cli/discovery.py`
- Modify: `tests/test_core_downloads.py`
- Modify: `tests/test_download_queue.py`
- Modify: `tests/test_cli_list_models.py`
- Modify: download UI tests only where callback signatures change

- [x] **Step 1: Write failing transfer-ownership tests.**

  Assert that `DownloadManager.download(...)`:

  - only transfers/finalizes files and returns `complete`, `exists`, or `stopped`;
  - accepts no repository publication responsibility;
  - does not call MDX-C/Apollo registration;
  - never calls `invalidate_models()`.

  Update the old `test_download_registers_paired_mdx_c_jobs` expectation to live in `tests/test_model_install.py` rather than deleting coverage.

- [x] **Step 2: Write failing queue publication tests.**

  Inject a repository and mock the shared finalizer. Prove:

  - finalizer runs once immediately after each successful logical item;
  - the first item publishes before the second blocked item completes;
  - an intermediate file does not publish;
  - finalizer failure maps the item to `failed` with its actionable detail;
  - stopped/cancelled/transfer-failed items never finalize;
  - two completed items cause one finalizer/publication opportunity each, not one batch event.

- [x] **Step 3: Write failing GTK batch-callback tests.**

  Assert `init_download_queue_ui` batch completion still updates the indicator, Download Center, toast, and desktop notification, but does not call any model invalidation/refresh callback. Remove the unused `on_models_changed` parameter from `init_download_queue_ui`, `open_download_center`, and `DownloadCenterWindow` once tests capture the intended interface.

- [x] **Step 4: Write failing CLI publication tests.**

  For two resolved catalogue records, assert:

  - each successful transfer calls `finalize_downloaded_model` immediately with its exact family/selection/jobs;
  - a finalizer incomplete result makes only that input fail;
  - no post-batch `repo.invalidate_models()` occurs;
  - mapper/hash metadata refresh cannot become a second invalidation after model publication;
  - JSON/JSONL stdout remains one valid machine-readable document/event stream.

- [x] **Step 5: Run focused tests and confirm RED.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_core_downloads \
      tests.test_download_queue \
      tests.test_cli_list_models -v
  ```

- [x] **Step 6: Make `DownloadManager.download` transfer-only.**

  Remove its `repo` parameter and the MDX-C/Apollo registration block. Update callers and tests. Keep `.part` finalization, cancellation cleanup, progress, and result semantics unchanged.

- [x] **Step 7: Finalize each queue item before marking it ready.**

  In `DownloadQueue._process_item`, after a `complete`/`exists` transfer result, convert `item.arch_type` through `FAMILY_BY_ARCH` and call the shared finalizer with `item.selection` and all jobs. Only map the item to `complete`/`exists` when `ready` is true; otherwise set `STATUS_FAILED` and the returned detail.

  Do not wait for `_worker_main` batch completion to publish. Keep batch completion for aggregate UI only.

- [x] **Step 8: Remove the GTK invalidation callback chain.**

  Delete `on_models_changed` plumbing from `ui/download.py`, `ui/download_center.py`, and the two `ui/window.py` call sites. The repository event raised by the per-item finalizer is now the only model-refresh source.

- [x] **Step 9: Use the same finalizer in the CLI.**

  Construct the CLI repository with the same coordinator snapshot owned by its `DownloadManager`. Run mapper/hash refresh, if retained, before processing model items so it cannot become a second post-publication full invalidation. Then call `finalize_downloaded_model` after each successful transfer and remove the manual `ModelRegistryService.index_downloaded` and post-batch `repo.invalidate_models()` calls.

  Preserve per-input status, SIGINT behavior, partial exit code, quiet stderr handling, and machine-readable stdout discipline.

- [x] **Step 10: Run the focused tests and confirm GREEN.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_core_downloads \
      tests.test_download_queue \
      tests.test_cli_list_models \
      tests.test_model_install -v
  ```

**Suggested commit checkpoint:** `fix: publish each usable download exactly once`

## Task 9: Prove Model Test, Progress, and CLI Consume the Enriched Display

**Files:**

- Modify: `tests/test_identity_planning.py`
- Modify: `tests/test_job_runner_planned.py`
- Modify: `tests/test_export_naming.py`
- Modify: `tests/test_run_control.py` only if progress-label coverage is missing
- Modify: `tests/test_cli_list_models.py`
- Modify implementation files only if a test exposes a consumer bypassing `ModelRecord.display`

- [x] **Step 1: Add a resolved-plan display propagation test.**

  Create a record whose identity/artifact basename is raw but display is friendly. Resolve a plan and assert:

  ```python
  self.assertEqual(plan.models[0].id, "mdx:melband_roformer_karaoke_becruily")
  self.assertEqual(plan.models[0].backend_name, "melband_roformer_karaoke_becruily")
  self.assertEqual(
      plan.models[0].display,
      "MelBand Roformer — Karaoke · becruily",
  )
  self.assertEqual(
      plan.inputs[0].naming.model_label,
      "MelBand Roformer — Karaoke · becruily",
  )
  ```

- [x] **Step 2: Add Model Test filename/folder tests.**

  With `process.add_model_name=True`, assert the output includes:

  ```text
  song MelBand Roformer — Karaoke · becruily (Vocals).wav
  ```

  With `process.create_model_folder=True`, assert the folder uses the same sanitized display. Add unsafe path characters to a second label and prove sanitization affects only filesystem components, never the descriptor ID/backend/artifacts. Add an unknown custom model and assert its raw basename is appended.

- [x] **Step 3: Add human/machine CLI parity tests.**

  Assert human model lists and plan summaries use the enriched display. Assert JSON output still carries the exact canonical ID, backend name, and artifacts. Reuse the existing digest test to prove a display-only rename leaves `model_identity_digest` unchanged.

- [x] **Step 4: Add progress-label parity only at the owning boundary.**

  If `tests/test_run_control.py` does not already prove the active resolved descriptor label reaches the floating log/progress surface, add one focused test there. Do not add a second display mapper in UI code; the expected fix is propagation from `ModelRecord.display` through `ModelDescriptor.display`.

- [x] **Step 5: Run focused naming/CLI tests.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_identity_planning \
      tests.test_job_runner_planned \
      tests.test_export_naming \
      tests.test_run_control \
      tests.test_cli_list_models -v
  ```

  If any consumer test fails, change only that consumer to use the already-carried record/descriptor display. Do not resolve a display back into an ID.

**Suggested commit checkpoint:** `test: lock model display propagation across outputs`

## Task 10: Cross-Layer Regression and Final Verification

**Files:**

- Modify tests named above only for uncovered regressions
- Update: `docs/superpowers/specs/2026-08-22-model-display-projection-refresh-design.md` status only after implementation verification
- Create the SDD execution/review artifacts only when an execution workflow requests them

- [x] **Step 1: Run the complete focused non-GTK regression set.**

  ```bash
  UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_model_display \
      tests.test_model_identity_contracts \
      tests.test_model_repository_subscribers \
      tests.test_model_repository_invalidation \
      tests.test_model_display_cache \
      tests.test_catalogue_coordinator \
      tests.test_model_install \
      tests.test_download_queue \
      tests.test_core_downloads \
      tests.test_cli_list_models \
      tests.test_identity_planning \
      tests.test_job_runner_planned \
      tests.test_export_naming \
      tests.test_no_runtime_display_inversion -v
  ```

- [x] **Step 2: Run the focused GTK regression set.**

  ```bash
  WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 \
    GDK_BACKEND=wayland \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
    UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest \
      tests.test_method_view_refresh \
      tests.test_vocal_split_row \
      tests.test_apollo_picker_write_gate \
      tests.test_model_picker_records \
      tests.test_model_refresh_spine \
      tests.test_run_control -v
  ```

  If the environment cannot safely access the host compositor, use the `testing-gtk-headless` skill and record the proven isolated command in the SDD verification report.

- [x] **Step 3: Run the complete suite in the supported GTK environment.**

  ```bash
  WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 \
    GDK_BACKEND=wayland \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
    MPLCONFIGDIR=/tmp/uvr-mpl-model-display \
    PYTHONWARNINGS=ignore \
    UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    .venv/bin/python -m unittest discover -s tests -t . -q
  ```

- [x] **Step 4: Run static analysis and whitespace validation.**

  ```bash
  .venv/bin/python -m basedpyright
  git diff --check
  ```

- [x] **Step 5: Audit the final diff against the locked contracts.**

  ```bash
  git diff --stat
  git diff -- core/model_display.py core/model_inventory.py \
    core/model_repository.py core/model_install.py core/downloads.py \
    core/download_queue.py core/model_registry.py ui/window.py \
    ui/download.py ui/download_center.py ui/ensemble/window.py \
    cli/discovery.py tests docs/superpowers/specs
  ```

  Confirm:

  - all picker labels originate from `ModelRecord.display`;
  - canonical IDs/backend/artifacts are unchanged;
  - no inventory code uses fuzzy mapper matching;
  - presentation-only refresh leaves plans and eligibility caches valid;
  - each logical model has one post-usability full invalidation owner;
  - batch callbacks do not invalidate;
  - warning gates still require an explicit repick;
  - vocal splitter remains karaoke-only.

- [x] **Step 6: Update documentation status and write the verification report.**

  Only after all commands pass, change the spec status from approved/awaiting implementation to implemented/verified and record exact commands, exit codes, test counts, and any environment limitations in the active `.superpowers/sdd/...` execution folder.

- [ ] **Step 7: Stop for the user's integration choice.**

  Do not stage or commit. Report the changed files and verification evidence, then ask whether the user wants the suggested checkpoints combined, committed separately, or left uncommitted.
