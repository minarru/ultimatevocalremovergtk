# Final fix-wave report

**Date:** 2026-08-23
**Branch:** `feat/model-id-improvement`
**Reviewed starting point:** `e2d7946`
**Commit:** local fix-wave commit `fix(models): unify catalogue presentation surfaces`; the exact hash is reported in the final handoff because a commit cannot contain its own hash.

## Outcome

All four final-review findings were addressed in one fix wave:

1. Manual Downloads now gets both row titles and ordering from the shared exact family-scoped catalogue projector. `ManualDownloadRow` retains the original catalogue `selection` and raw `model`; `resolve_links()` passes both unchanged to `DownloadManager.manual_links()`.
2. Catalogue presentation identity is now distinct from executable inventory eligibility. Runtime projectors still decide inventory membership. When they reject a row, presentation may use only one validated, exact declared non-YAML primary. This gives the known BandSplit `.pth` row its audited `mdx:` display identity without adding a runtime record. Malformed, primaryless, and ambiguous rows retain the safe structure-only fallback.
3. A primary model whose repick gate survives refresh remains at `Choose Model`, but its banner now says the model is available and requires an explicit pick instead of claiming it is not installed.
4. The audit documents 484 syntactic catalogue presentation IDs versus 483 runtime inventory projections and identifies the intentionally runtime-ineligible BandSplit `.pth` row under the MDX `.ckpt`/`.onnx` execution contract.

## Files

- `core/model_catalogue.py` — exact `catalogue_presentation_id()` derivation and the shared `project_catalogue_display()` path.
- `core/downloads.py` — exact projected Manual Downloads ordering plus `ManualDownloadRow`.
- `ui/download.py` — consumes projected manual rows for titles and raw link resolution.
- `ui/views/base.py` — available-but-repick-required banner while preserving the gate.
- `scripts/catalogue/render.py` — display-reference generation now uses the same core catalogue presentation helper.
- `docs/model_display_quality_audit.md` — 484 presentation / 483 runtime explanation and BandSplit eligibility exception.
- `tests/test_manual_downloads.py` — exact `HP 1` title/order and original-selection link regression.
- `tests/test_model_identity_contracts.py` — BandSplit display/runtime exclusion plus malformed, primaryless, and ambiguous fallback regressions.
- `tests/test_cli_list_models.py` — CLI catalogue JSON parity with the audited BandSplit display and unchanged selection.
- `tests/test_method_view_refresh.py` — headless and real-widget assertions for the refreshed repick banner and non-executable state.

## TDD evidence

### RED

The first focused run produced four expected failures:

```text
.venv/bin/python -m unittest \
  tests.test_manual_downloads.ManualDownloadMergeTests.test_exact_projection_controls_row_title_sort_and_link_selection \
  tests.test_model_identity_contracts.CatalogueDisplayProjectionTests.test_ineligible_mdx_pth_row_uses_its_exact_presentation_id_only \
  tests.test_cli_list_models.DiscoveryTests.test_catalogue_cli_uses_audit_display_for_ineligible_mdx_pth_row \
  tests.test_method_view_refresh.InstalledRecordPickerTests.test_refresh_lists_a_newly_installed_gated_primary_without_selecting_it -v

FAILED (failures=4)
```

The failures were exactly: no manual projected-row adapter, compact BandSplit display in core and CLI, and the stale `is not installed` banner.

The private GTK regression also failed against the old banner on private socket `/tmp/codex-gtk.tOPZJY/codex-gtk`:

```text
test_post_download_refresh_reveals_a_gated_id_for_explicit_repick ... FAIL
AssertionError: 'now available' not found in '... is not installed ...'
```

Two additional safety cycles were observed before their fixes:

- malformed artifact evidence escaped with `UnboundLocalError` instead of falling back;
- an ambiguous two-primary VR row incorrectly received the curated `HP 1` presentation identity.

### GREEN

- Seven final focused headless regressions: **7 passed**.
- Related modules (`test_manual_downloads`, `test_model_identity_contracts`, `test_cli_list_models`, `test_method_view_refresh`, `test_generate_models_catalogue`, `test_no_runtime_display_inversion`): **282 passed, 4 skipped** without a display.
- Private GTK focused red/green regression: **1 passed** on `/tmp/codex-gtk.6NZY0e/codex-gtk`.
- Complete private GTK picker-refresh module: **25 passed** on `/tmp/codex-gtk.tI2i8X/codex-gtk`.
- Final-tree private GTK regression: **1 passed** on `/tmp/codex-gtk.8Jrmmu/codex-gtk`.

## Final verification

- Complete unittest discovery through the repository's private Wayland/D-Bus runner: **2,731 passed, 7 skipped** in 83.906 seconds; runner exit 0, private socket `/tmp/codex-gtk.GtCj8S/codex-gtk`.
- `.venv/bin/python -m basedpyright`: **0 errors, 0 warnings, 0 notes**.
- `git diff --check`: clean.
- Checked-in `docs/model_display_reference.tsv`: **484 rows, 484 unique IDs, 481 clean, 3 reviewed, 0 unreviewed, 0 case-insensitive display collisions**. The BandSplit row is `mdx:BandSplit_Roformer_4stems_FT_by_SYH99999` with display `BandSplit Roformer — (4 Stems) Fine-Tuned · SYH99999` and remains a `.pth` artifact.
- The strict live/offline generator check could not judge drift: both attempts saw only 112 of the prior 484 rows and correctly exited 2 under the degraded-publication guard. No checked-in catalogue/reference file was written. Generator behavior and reference rendering are covered by the passing focused module and the checked-in TSV audit above.
- Focused Ruff invocation still reports the repository's accepted pre-existing lint/format backlog in touched legacy files; no unrestricted fix or bulk formatting was applied.

## Invariants and risks

- Canonical `family:basename` runtime IDs, raw catalogue selections, artifact filenames, execution metadata, eligibility, and download resolution are unchanged.
- `_catalogue_records()` and all family runtime projectors are unchanged; the BandSplit `.pth` row is still excluded from executable inventory.
- The presentation fallback is exact and conservative: metadata must declare exactly the one validated non-YAML primary. There is no fuzzy matching, display inversion, or inferred ownership.
- No model inventory invalidation path was added or changed.
- Vocal Splitter behavior and metadata-based karaoke/BV eligibility were not touched.
- The only unresolved verification limitation is the degraded external catalogue snapshot described above; the publication guard failed closed as designed.
