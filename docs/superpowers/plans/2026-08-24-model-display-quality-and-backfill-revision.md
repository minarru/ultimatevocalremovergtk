# Model Display Quality and Backfill Revision Implementation Plan

> **For Codex:** Implement this plan test-first. Do not commit or push unless the user asks.

**Goal:** Make every model surface use the revised, reviewed display names and make installed-model backfill select exact evidence from the published deduplicated catalogue.

**Architecture:** Keep canonical identity and display projection separate. Extend the checked-in exact presentation manifest and the conservative projector for reviewed source-label grammar, then change inventory backfill to resolve exact primary artifacts through the published family maps rather than the pre-deduplication metadata pool. Catalogue generation continues to consume the runtime projector and becomes the exhaustive collision/quality gate.

**Tech Stack:** Python 3.12-compatible stdlib, JSON manifest, `unittest`, Ruff, basedpyright, GTK4/libadwaita tests through the repository's private headless runner.

---

## Global constraints

- Preserve canonical `family:basename` IDs, artifact names, model hashes, execution metadata, stem routing, karaoke/BV eligibility, and saved selections.
- Never invert a display label into identity and never add fuzzy, substring, or author-derived matching.
- Keep `project_model_display()` deterministic and idempotent.
- Do not stage, commit, push, or merge without a separate user request.

### Task 1: Lock the revised naming contract in tests

**Files:**

- Modify: `tests/test_model_naming.py`
- Modify: `tests/test_model_identity_contracts.py` only for unchanged stem-label invariants if the closest existing fixture lives there

**Steps:**

1. Add table-driven projector tests for the twelve confirmed corrections, four ViperX names, six VR aliases, MDX/MDX23C corrections, author-component normalization, version/state casing, `HQ`, standalone `FT`, and opaque-token preservation.
2. Add representative and exhaustive manifest-driven tests for the 25 count-leading entries and 54 Mega entries, including normalized stem terms.
3. Assert the three reviewed collision suffixes, Gonza/Gonzaluigi distinction, and exact `No Drum-Bass`/`Drum-Bass` output labels.
4. Update old expectations that encode superseded naming rules.
5. Run `.venv/bin/python -m unittest tests.test_model_naming -v` and confirm the new assertions fail for the expected presentation mismatches before production changes.

### Task 2: Implement the revised projector and exact aliases

**Files:**

- Modify: `core/model_naming.py`
- Modify: `bundled/model_display_manifest.json`
- Test: `tests/test_model_naming.py`

**Steps:**

1. Add exact canonical-ID aliases for all reviewed correction batches, ViperX entries, VR utility names, MDX/MDX23C entries, count-leading entries, and Mega entries.
2. Expand the case-insensitive exact author alias table and normalize each reviewed `A & B` component independently while preserving source order and unknown-handle spelling.
3. Make conservative formatting preserve/restore `HQ`, expand standalone `FT`, normalize reviewed technical/version/state tokens, place stem counts after variants, and avoid an empty em dash.
4. Keep raw unknown basenames unchanged and prove projector idempotence.
5. Run `.venv/bin/python -m unittest tests.test_model_naming -v` until green.
6. Run scoped Ruff checks for the touched Python files.

### Task 3: Resolve backfill evidence through the published catalogue

**Files:**

- Modify: `tests/test_model_identity_contracts.py`
- Modify: `core/model_inventory.py`
- Possibly modify: `core/debug_log.py` only if the existing structured warning API cannot express the required event

**Steps:**

1. Add a failing regression fixture where upstream `V1` and Politrees `v1` metadata point to one artifact while the published family map contains one deduplicated entry; require the published label/source to replace mapper evidence and preserve an explicit override.
2. Add a failing genuine post-deduplication ambiguity test requiring no registry mutation and an actionable structured warning with canonical ID and candidate selections.
3. Add a regression proving presentation relabeling preserves canonical picker identity and does not increment `inventory_generation`.
4. Implement an exact published-family resolver keyed by the record's primary artifact and family. Treat pre-deduplication labels as evidence only, never as the ambiguity boundary.
5. Use the resolver in both live installed-record display projection and durable backfill. On genuine ambiguity, retain existing evidence and warn; on one match, persist current label/source without touching explicit override.
6. Run `.venv/bin/python -m unittest tests.test_model_identity_contracts.PresentationBackfillTests -v` and the broader identity-contract module until green.
7. Run scoped Ruff checks for the touched Python files.

### Task 4: Strengthen catalogue quality gates and regenerate reviewed outputs

**Files:**

- Modify: `tests/test_generate_models_catalogue.py`
- Modify: `scripts/catalogue/render.py`
- Regenerate: `docs/model_display_reference.tsv`
- Regenerate: `docs/model_display_quality_audit.md`
- Regenerate: `docs/models-catalogue.md`

**Steps:**

1. Add failing audit tests for expanded `High Quality`, leading stem-count placement, operational notes, and other mechanically detectable violations from the revision.
2. Implement the focused audit flags without treating unknown raw basenames as inferred catalogue models.
3. Run `.venv/bin/python -m unittest tests.test_generate_models_catalogue -v` until green.
4. Run the offline warm-cache generator to regenerate the catalogue, full 484-row display reference, and quality audit through the runtime projector.
5. Run the generator's read-only strict check and require exactly 484 reference rows, zero unreviewed flags, and zero accidental display collisions.
6. Review the generated diff for identity/artifact drift; only presentation text and expected review metadata may change.

### Task 5: Verify every shared consumer and repository quality gate

**Files:**

- Test existing GUI, CLI, JSON, progress, Model Test, Download Center, ensemble, and Vocal Splitter suites that consume the shared projection
- Modify tests only if a superseded display expectation must be updated or a missing surface regression is exposed

**Steps:**

1. Run focused naming, registry, inventory, download, CLI, catalogue-generator, repository-refresh, and display-consumer unit modules.
2. Run the isolated GTK picker/refresh tests through the private headless GTK workflow; verify primary, secondary, ensemble-member, Vocal Splitter, Model Test, and post-refresh selection preservation.
3. Run `.venv/bin/ruff check` and `.venv/bin/ruff format --check` only on touched Python files.
4. Run `.venv/bin/python -m unittest discover -s tests -t . -v`.
5. Run `.venv/bin/python -m basedpyright`.
6. Inspect `git diff --check`, `git status --short`, and the complete diff. Report verification evidence and any remaining limitations without committing.
