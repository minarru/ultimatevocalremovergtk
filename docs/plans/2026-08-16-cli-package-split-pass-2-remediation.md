# CLI Package-Split Pass-2 Remediation

## Summary

The rereview is substantially correct. Confirm findings covering output naming, canonical GUI identities, ensemble planning, GUI settings mutation, migration races, collision handling, incomplete settings presentation, and stale offline documentation.

Qualify two findings:

- The offline wrapper is ineffective, but many identity paths already pass `allow_network=False`. The real remaining violation is MDX-C configuration resolution, which can still download or write metadata during planning.
- Download interruption generally produces the right result today, but signal handling should still be normalized with processing.

Reject or omit these findings:

- GUI plan confirmation remains enabled by default by prior product decision.
- Invalid enum `--set` values are already rejected.
- The AST guard already covers `ui`, and the model-assembly membership expression has already been corrected.

The independent pass also found release-blocking defects in benchmark topology validation, benchmark interruption reporting, catalogue-cache invalidation, collision preflight, and repeated model assembly across batch inputs.

## Core Planning and Execution

- Add a resolved batch-execution API to `JobRunner` that accepts an immutable `ResolvedJob`, per-input staging destinations, failure policy, and callbacks. Assemble runtime models once per job, then process every input using its planned naming position.
- Keep mutable runtime `ModelConfig` objects confined to one execution. GUI jobs use fail-fast behavior; CLI batches use continue-on-error unless requested otherwise.
- Make `OutputNamingContext` authoritative during execution. Remove `_apply_planned_basename` and never infer batch numbering from a one-item runner invocation.
- Add structured per-input results containing planned input identity, generated files, failure/interruption state, and timings. Preserve existing callbacks additively for GUI compatibility.
- Resolve ensemble topology through one core helper shared by planning and execution:
  - Explicit stem pairs produce their exact paired outputs.
  - Four-stem ensembles produce the standard four stems.
  - Multi-stem outputs derive from member descriptors and are marked conditional when metadata cannot guarantee them.
- Extend model descriptors with the supported stem topology needed by that helper. Assert that every guaranteed planned output matches the runner's generated-file records.
- Make separation and ensemble resolvers accept a `ValidationLevel` and return the single `ResolvedJob` produced at that level. Validation must not repeat model assembly, hashing, or resolution.

## Identity, Catalogue, Persistence, and GUI

- Preserve already-canonical identities when importing `--profile gui`; prefix only legacy unqualified model values.
- Define explicit family constraints for every model-reference setting:
  - Primary models resolve only within their selected VR, MDX, or Demucs family.
  - Apollo resolves only as Apollo.
  - Splitters and Demucs preprocessors resolve only to eligible VR/MDX models.
  - Generic secondary models allow VR/MDX/Demucs subject to stem applicability.
  - Ensemble members allow VR/MDX/Demucs.
- During migration, leave ambiguous or family-mismatched references unchanged, count them as conflicts, and retain the old identity version for retry. Clear only genuinely unknown references according to the existing sentinel rules.
- Replace the no-op offline context with explicit access policies:
  - Planning, processing, migration, completion, inspection, configuration, and identity lookup use installed plus cached/bundled metadata, with network and metadata writes forbidden.
  - Only explicit catalogue and download administration may request online data or materialize downloaded configuration.
- Thread that policy through MDX-C configuration lookup so missing YAML produces a diagnostic during planning instead of downloading or registering metadata.
- Make catalogue caches key on access mode and captured inventory generation. Publish a collected value only if the generation is unchanged; otherwise discard and retry.
- Put GUI profiles, CLI profiles, and saved ensembles behind shared per-path read/compare/write/delete locks. Migration writes use a captured content digest and report conflicts instead of overwriting concurrent edits.
- Remove mutation of `AppContext.settings` from GUI execution. Save the live user snapshot before starting, then pass a deep-copied resolved plan directly to the runner. Model-native and canonical runtime values remain run-local.
- Keep final inventory/hash checks on a worker and require settings fingerprint, inventory generation, and hashes to remain current before execution. A stale plan returns to preflight and confirmation.
- Preserve "Confirm processing plan before starting" as enabled by default; Audio Tools continue to preflight without a confirmation dialog.

## CLI Safety, Reporting, and Presentation

- Replace prefix-based collision checks with exact guaranteed destinations from the resolved plan. Conditional outputs are checked when materialized.
- Plan promotion for the entire output unit before moving files:
  - `rename` selects one common numeric suffix and applies it to every output in the unit.
  - `fail` and `skip` make no moves after a collision.
  - `overwrite` backs up only exact targets until the whole unit succeeds.
  - Any promotion failure rolls moved files back into staging and restores overwritten targets.
- Serialize in-process promotion per output directory and recheck destinations immediately before promotion. Retry rename selection after a race.
- Repair benchmark topology validation to compare actual resolved output-stem topology instead of the removed legacy `identity` payload. Empty or indeterminate topology is a validation failure, not a compatible match.
- Normalize interruption across processing, Audio Tools, downloads, benchmarks, and top-level handling: exit `130`, `ok: false`, `status: "failed"`, `stopped: true`, an interrupted failed unit, and matching JSONL terminal fields.
- Send engine console exclusively to stderr unless quiet. Machine-report stdout remains exactly one JSON document or valid JSONL events.
- Make `SettingsResolver` the only provenance source. Remove CLI source reconstruction and preserve list-valued settings when flattening GUI/profile layers.
- Expand `settings show` and `settings explain` to cover processing, Audio Tools, and UI sections. Human output uses deterministic scalar rows and labelled structured values.
- Document the current separation/ensemble and Audio Tool manifest schema versions, launcher/flag removals, offline guarantees, interruption fields, and intentional pre-release compatibility break. Update active `CLAUDE.md` guidance; historical reviews remain untouched.
- Remove the obsolete offline wrapper and any resulting dead imports after all callers use explicit policies.

## Tests and Delivery Gates

1. Add regressions first for double-suffixed single/batch outputs, canonical GUI profiles, ensemble topology, GUI settings mutation, benchmark schema drift, repeated model assembly, and exact collision preflight. Build CLI fixtures from real `ResolvedJob.to_dict()` output instead of legacy synthetic dictionaries.
2. Implement single-assembly batch execution and naming parity. Test separation, ensemble member retention, same-basename inputs, batch indexes, conditional outputs, continue-on-error, and GUI fail-fast behavior.
3. Implement transactional collision promotion. Test common-suffix rename, false prefix collisions, preflighted multi-input conflicts, promotion-time races, rollback, overwrite restoration, and interruption cleanup.
4. Implement constrained identity migration, storage locking, explicit catalogue policy, and generation-safe caches. Use concurrency barriers to prove no stale cache publication, cross-family migration, network access, or planning-time metadata writes.
5. Complete GUI run-local settings, benchmark/interruption fixes, settings presentation, documentation, and cleanup. Test GTK main-thread boundaries, stale-plan reconfirmation, confirmation-disabled behavior, JSON ownership, JSONL terminal events, and signal restoration.

After every gate, run focused unit tests and basedpyright. The final gate also runs the complete unittest suite under the known-good GTK/Wayland environment, shell syntax and launcher tests, AST import guards, network-denial tests, and `git diff --check`.

## Assumptions

- The CLI remains pre-release; no removed launcher, flag, report shape, or headless compatibility shim returns.
- GUI plan confirmation remains enabled by default.
- Processing and all read-only discovery paths are strictly offline and non-mutating.
- CLI staging, promotion, reporting, and manifests remain frontend-owned; reusable naming, identity, topology, resolution, and runner behavior remain in core.
