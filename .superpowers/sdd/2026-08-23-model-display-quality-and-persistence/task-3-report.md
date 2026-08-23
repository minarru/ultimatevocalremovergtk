# Task 3 Report: inventory, refresh backfill, and download finalization

## Status

Complete. Installed inventory presentation now uses the shared projector with
exact evidence precedence, successful online refresh paths durably backfill
presentation evidence, and verified downloads persist their exact catalogue
selection/source before the single publication invalidation.

Implementation commit: `00f71dc` (`feat(models): persist display evidence across refreshes`).

## Implementation summary

- Installed `ModelRecord` display enrichment now feeds explicit registry
  override and the best exact source label into `project_model_display()`.
  Current catalogue association wins over persisted exact evidence; exact
  mirror mapper evidence is the final friendly source before the raw canonical
  basename. Curated aliases remain projector-owned and therefore take their
  required precedence after an explicit override.
- Exact catalogue association uses canonical family plus current catalogue
  record or unambiguous primary-artifact membership. It never derives identity
  from display text. Inventory enrichment replaces only `ModelRecord.display`
  and performs no registry writes, hashing, or network access.
- Catalogue snapshots now retain an immutable family/selection source map for
  the winning upstream, Politrees, extras, or MVSEP-less entry, including exact
  metadata evidence retained before download-list deduplication.
- A separate mutation helper backfills installed presentation evidence after a
  successful live catalogue refresh or successful online model-metadata
  update. It prefers current exact catalogue evidence, otherwise accepts an
  exact mirror mapper label, and registry merge semantics preserve any trusted
  explicit override.
- Backfill occurs after the live snapshot is applied and does not trigger
  another catalogue publication or invalidation. A registry write failure
  emits an actionable `RuntimeWarning`, leaves the live snapshot active, and is
  retried on the next successful online refresh. Cached/offline catalogue
  listing never invokes the helper.
- Download finalization retains transfer/artifact validation, family/hash
  registration, and fresh candidate identity verification before persisting
  the exact catalogue selection and source. Persistence precedes exactly one
  `invalidate_models()` call. A failed persistence returns not-ready and
  not-published detail; a later `exists` finalization persists and publishes.
- App context supplies the repository to its shared download manager so live
  refreshes can perform the explicit backfill.

## Files

- `core/catalogue_coordinator.py`
- `core/downloads.py`
- `core/model_install.py`
- `core/model_inventory.py`
- `ui/context.py`
- `tests/test_catalogue_coordinator.py`
- `tests/test_core_downloads.py`
- `tests/test_model_identity_contracts.py`
- `tests/test_model_install.py`
- `.superpowers/sdd/2026-08-23-model-display-quality-and-persistence/task-3-report.md`

The pre-existing Task 5 generator/audit changes in
`scripts/catalogue/collect.py`, `scripts/catalogue/render.py`,
`scripts/generate_models_catalogue.py`, `tests/test_generate_models_catalogue.py`,
`docs/model_display_quality_audit.md`, and
`docs/model_display_reference.tsv` were preserved and excluded from the Task 3
implementation commit.

## RED/GREEN TDD evidence

### Initial integration RED

Tests were written before production integration:

```bash
.venv/bin/python -m unittest \
  tests.test_model_identity_contracts.DisplayEnrichmentTests.test_registry_override_and_exact_source_precedence_use_shared_projector \
  tests.test_model_identity_contracts.DisplayEnrichmentTests.test_live_then_persisted_then_mirror_source_precedence \
  tests.test_model_identity_contracts.DisplayEnrichmentTests.test_inventory_projection_never_persists_presentation \
  tests.test_model_identity_contracts.PresentationBackfillTests.test_backfill_persists_installed_exact_catalogue_evidence \
  tests.test_model_install.SingleFilePublicationTests.test_presentation_is_persisted_before_the_only_publication \
  tests.test_model_install.SingleFilePublicationTests.test_failed_presentation_write_is_retryable_from_exists \
  tests.test_core_downloads.UpdateModelSettingsTests.test_successful_online_mapper_update_attempts_presentation_backfill -v
```

Result before production changes: expected RED, 4 failures and 2 errors.
Inventory ignored override/persisted precedence, the backfill API did not
exist, and finalization neither persisted evidence nor supported the required
failure/retry ordering.

### Initial integration GREEN

The same command after the minimal integration passed all 7 tests.

### Exact provenance RED/GREEN

```bash
.venv/bin/python -m unittest \
  tests.test_catalogue_coordinator.CatalogueCoordinatorTests.test_snapshot_records_exact_winning_source_for_each_entry \
  tests.test_core_downloads.PresentationBackfillRefreshTests -v
```

Before the provenance implementation, the snapshot test errored because
`entry_sources` was absent. After adding immutable winning-source projection,
all 3 tests passed. The already-present refresh behavior tests also remained
green while provenance was added.

### Pre-dedupe and mirror-only RED

```bash
.venv/bin/python -m unittest \
  tests.test_model_identity_contracts.PresentationBackfillTests.test_mapper_refresh_can_backfill_without_a_catalogue_snapshot \
  tests.test_model_identity_contracts.PresentationBackfillTests.test_prededupe_exact_catalogue_evidence_is_backfilled -v
```

Result before the edge fix: expected RED, 2 failures because neither path
persisted evidence. After allowing exact mirror evidence without a snapshot
and retaining exact pre-dedupe source ownership, both tests passed.

## Verification

Focused integration and regression suite:

```bash
.venv/bin/python -m unittest \
  tests.test_catalogue_coordinator tests.test_core_downloads \
  tests.test_model_identity_contracts tests.test_model_install \
  tests.test_cli_list_models tests.test_model_repository_subscribers \
  tests.test_model_registry tests.test_name_mapper_overlay \
  tests.test_no_runtime_display_inversion -v
```

Result: 231 tests passed in 2.804 seconds.

Static type verification:

```bash
.venv/bin/python -m basedpyright \
  core/catalogue_coordinator.py core/downloads.py core/model_install.py \
  core/model_inventory.py ui/context.py tests/test_catalogue_coordinator.py \
  tests/test_core_downloads.py tests/test_model_identity_contracts.py \
  tests/test_model_install.py
```

Result: 0 errors, 0 warnings, 0 notes.

Private-compositor GTK verification, used because the ordinary discovery run
reached GTK tests with no display and exited 139:

```bash
/home/rudam/.claude/skills/testing-gtk-headless/scripts/run-private-wayland.sh -- \
  env UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
  .venv/bin/python -m unittest discover -s tests -t . -v
```

Result: the runner created private Wayland and D-Bus endpoints under `/tmp`;
2,684 tests passed in 85.064 seconds, 6 skipped, exit 0. No host compositor or
host session bus was used.

Formatting/whitespace verification:

```bash
git diff --cached --check
```

Result before the implementation commit: passed with no output.

`ruff check` over all touched legacy modules reports 15 existing repository
baseline findings (unused legacy imports, historical import ordering, one
legacy `zip` strictness finding, and existing test warnings). No new Task 3
diagnostic appeared, and broad mechanical cleanup was intentionally kept out
of this scoped commit.

## Self-review

- Presentation precedence is explicit override, projector-curated alias,
  current exact catalogue label, persisted exact label, exact mirror source,
  then raw canonical basename. Identity and runtime fields are untouched.
- Exact source matching is family-scoped and filename-exact; ambiguous artifact
  membership is rejected rather than guessed. Runtime modules still pass the
  no-display-inversion guard.
- Inventory reads call only read-only registry and mapper paths. Persistence is
  isolated behind the explicit successful-online-refresh helper.
- Refresh publication happens before backfill, and the helper performs no
  invalidation. Failure therefore cannot discard a live snapshot or create a
  publication/invalidation loop, and every later successful online path can
  retry.
- Finalization persists only after a freshly rebuilt candidate is installed
  and identity-complete. Persistence failure cannot publish; successful retry
  makes the presentation change observable and emits exactly one invalidation.
- Eligibility, catalogue selection, canonical IDs, artifact selection, and
  runtime resolution were not changed.
- Task 5-owned files were neither edited by this task nor included in its
  commit.

## Concerns / handoff

None. The repository-wide Ruff baseline remains outside Task 3 scope.
