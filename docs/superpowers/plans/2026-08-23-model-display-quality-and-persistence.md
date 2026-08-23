# Model Display Quality and Persistence Implementation Plan

> **For agentic workers:** Use subagent-driven development and TDD. Preserve
> unrelated or pre-existing worktree changes and commit only task-owned files.

**Goal:** Give every model surface one ID-aware, offline-stable display
projection while preserving exact runtime identity, artifact names, eligibility,
and execution metadata.

**Design inputs:** `docs/model_display_quality_audit.md`,
`docs/model_display_reference.tsv`, and
`docs/superpowers/specs/2026-08-22-model-display-projection-refresh-design.md`.

## Global Constraints

- Canonical runtime IDs remain exact `family:basename`; never resolve identity
  from display text.
- Backend names, artifact filenames, catalogue selection keys, execution
  metadata, stem semantics, and picker eligibility remain unchanged.
- `ModelRecord.display` is the installed-model presentation authority. Every
  displayed catalogue row must use the same projector.
- Display precedence is: explicit trusted registry override, exact curated
  alias, exact live or persisted source label through conservative formatting,
  then raw basename.
- Unknown custom models keep their raw basename. No fuzzy matching, guessed
  attribution, or substring identity is allowed.
- Download finalization persists presentation only after transfer, artifact,
  installed-record, and identity-completeness checks; it invalidates exactly
  once and only after that write succeeds.
- Read-only CLI and generator check paths remain offline/read-only. Catalogue
  refresh backfill failure publishes the live snapshot with an actionable
  warning and retries on a later successful refresh.
- Existing uncommitted audit/generator work is part of this plan and must be
  preserved.

## Task 1: Add the ID-aware projector and curated manifest

**Production:** `core/model_naming.py`, a checked-in bundled JSON manifest.
**Tests:** `tests/test_model_naming.py` and focused display tests.

- Write failing tests for the public projector API:

  ```python
  project_model_display(
      model_id: str,
      *,
      source_label: str = "",
      explicit_display: str = "",
  ) -> str
  ```

- Implement precedence, exact canonical-ID lookup, manifest schema validation,
  author aliases, idempotent conservative formatting, and raw fallback.
- Manifest schema contains `schema_version`, exact `model_aliases`,
  case-insensitive `author_aliases`, and exact per-ID/per-flag `waivers` with
  reasons.
- Encode the approved naming contract:
  - no VR prefix and exact readable aliases for all 22 raw VR names;
  - `MelBand Roformer`, `BandSplit Roformer`, and `BandSplit PolarFormer`;
  - full `Instrumental`, `Vocals`, and `Instrumental/Vocals` terms;
  - explicit counts as `(N Stems)`;
  - `FT`/`HQ` as `Fine-Tuned`/`High Quality`, normalized `SDR`, `FFT`, and
    `8K`, with opaque `SN`, `Fv9`, and numeric identifiers preserved;
  - version-only Demucs headings with curated backend aliases;
  - `MDX-Net — UVR …` for the ONNX batch;
  - presentation-only BVE-to-Karaoke wording;
  - three collision-preserving embedded IDs and the reviewed
    Gonza/Gonzaluigi near-duplicate annotations;
  - exact PolarFormer names:
    `BandSplit PolarFormer — 09-07-2026 (4 Stems) · Aname`,
    `BandSplit PolarFormer — Lazy Bat (4 Stems) · Aname`,
    `BandSplit PolarFormer — Instrumental/Vocals Duality Lazy Bat · Aname`,
    `BandSplit PolarFormer — Karaoke · Lambda001`, and
    `BandSplit PolarFormer — Vocals · ZFTurbo`.
- Preserve `canonical_display_name()` as the structure-only compatibility
  formatter, but route new human presentation through the ID-aware API.

## Task 2: Upgrade the local registry and migrate presentation evidence

**Production:** `core/model_registry.py`, path/name-mapper integration.
**Tests:** registry, mapper-overlay, and concurrency/atomic-store tests.

- Read the existing flat `registered_models.json` without writing and normalize
  it in memory to:

  ```json
  {
    "schema_version": 2,
    "hashes": {"<hash>": "family:basename"},
    "models": {
      "family:basename": {
        "catalogue_label": "exact source label",
        "catalogue_source": "source name",
        "display_override": "optional trusted override"
      }
    }
  }
  ```

- On the next registry mutation, write schema 2 atomically under the existing
  lock. Preserve hash ownership and presentation entries across concurrent
  updates; fail safely on malformed data without truncation.
- Add exact read/write methods for model presentation. An empty optional field
  is omitted, and explicit overrides survive catalogue-label backfill.
- Stop consuming legacy local name-mapper overlays for presentation. On the
  first presentation-aware mutation, rename each legacy local mapper to
  `model_name_mapper_local.legacy.json` only when that archive does not already
  exist. If it exists, leave the old source file untouched but ignored and emit
  a warning; never overwrite either file.

## Task 3: Integrate inventory, refresh backfill, and download finalization

**Production:** model inventory/repository/catalogue refresh and
`core/model_install.py`.
**Tests:** inventory contracts, repository refresh, model installation, CLI
listing, and offline behavior.

- Resolve each installed record using explicit registry override, curated
  alias, current exact catalogue label, persisted exact label, and raw fallback
  in that order. Only `.display` may change.
- Prefer current live source evidence and backfill installed known models after
  a successful online refresh. Backfill must not replace an explicit override.
  A write failure logs an actionable warning, keeps the live snapshot, and
  retries on a later successful refresh.
- In `finalize_downloaded_model`, persist the candidate catalogue label/source
  after usability and identity verification but before publication. A failed
  write returns not-ready/not-published detail; a later `exists` retry can write
  and publish. Preserve exactly one invalidation per completed usable model.
- Keep catalogue selection and all runtime resolution canonical-ID based.

## Task 4: Unify GUI and CLI surfaces and validate refresh behavior

**Production:** only surface adapters that still bypass `ModelRecord.display`
or the catalogue projector.
**Tests:** picker/refresh tests plus private headless GTK coverage.

- Audit and route the primary, secondary, ensemble-member, Vocal Splitter,
  Model Test, Download Center, progress/log, human CLI, and JSON `display`
  surfaces through the shared projection.
- Keep widget values and selection restoration keyed by canonical ID. Newly
  downloaded options appear after the one repository refresh but are not
  silently selected; the user repicks them.
- Keep Vocal Splitter eligibility based only on karaoke/BV metadata, not title
  wording.
- Add isolated headless GTK tests for representative picker labels, selection
  preservation, post-download refresh, and karaoke-only filtering.

## Task 5: Finish full-catalogue auditing and strict verification

**Production/tooling:** existing changes under `scripts/catalogue/` and
`scripts/generate_models_catalogue.py`; checked-in audit/reference documents.
**Tests:** `tests/test_generate_models_catalogue.py` and full verification.

- Make display-reference generation call the runtime ID-aware projector and
  emit reviewed/unreviewed status using manifest waivers.
- Keep `--check --write-display-reference` read-only and make it fail for every
  unreviewed presentation flag or accidental case-insensitive collision.
- Preserve degraded-publication protection, fresh-online/warm-offline parity,
  and cold-offline raw fallback.
- Regenerate and review the full 484-row reference. It must contain zero
  unreviewed flags and zero accidental collisions; only explicit reasoned
  waivers are accepted.
- Run focused naming, registry, inventory, installation, CLI, generator,
  repository-refresh, and headless GTK tests, then the complete unittest suite
  and basedpyright.
