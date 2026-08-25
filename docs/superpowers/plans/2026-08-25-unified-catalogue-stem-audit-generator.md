# Unified Catalogue and Stem Audit Generator

**Date:** 2026-08-25

**Status:** Approved for implementation

## Goal

Make `scripts/generate_models_catalogue.py` the single public catalogue
maintenance command. Preserve focused internal modules for collection,
rendering, strict semantic validation, and the optional remote checkpoint
confidence audit.

## Global Constraints

- Collect the authoritative catalogue snapshot once per invocation and reuse it
  for every rendered output and strict semantic diagnostic.
- Normal successful writes synchronize the Markdown catalogue, IR sidecar,
  intent TSV, display TSV, and stem-semantics TSV.
- Existing `--write-tsv`, `--write-display-reference`, and
  `--write-stem-semantics-reference` options remain accepted as deprecated
  compatibility no-ops.
- Every normal write and `--check` runs strict manifest validation. Structural
  failures block publication; write mode may repair stale generated references,
  while check mode reports drift without any repository or cache writes.
- `--summary` is read-only and reports model-specific semantic findings.
- The opt-in `--audit-stem-confidence` mode preserves the old mvsepless remote
  hash audit. It shares `--offline` and `--refresh`; offline forbids every
  catalogue, config, and checkpoint request.
- Preserve exit codes 0 success, 1 drift/findings, 2 degraded snapshot, and 130
  interrupted confidence audit.
- Do not change runtime IDs, stem roles, manifest semantics, model execution,
  or UI behavior.
- Use TDD for every behavior change and preserve atomic per-file publication.

## Task 1: Extract structured strict stem auditing

Create `scripts/catalogue/stem_audit.py` and move the full-catalogue strict
semantic checks out of `scripts/stem_semantics_audit.py`. Expose structured
diagnostics rather than parsing rendered output. Cover catalogue coverage,
native signatures, target complements, contexts, logical primaries,
Vocal Splitter declarations, role/tag collisions, pair completeness, pinned
evidence counts, and reference parity. Diagnostics must identify affected
canonical model IDs. Add focused tests first and retain the current manifest
and reference schema during this task.

## Task 2: Expand the review renderer and semantic summary

Extend the stem-semantics TSV with runtime family, basename, catalogue source,
catalogue label, and execution architecture while preserving every existing
column. Populate waiver rows with available identity and provenance rather
than blank review fields. Make `render_summary_report` consume Task 1's
structured audit and report reviewed/waived/raw counts, signature/context
findings, native-to-role ambiguities, role-to-native variants, invalid pairs,
collisions, and reference drift. Keep the complete review as TSV plus summary;
do not add another Markdown document. Add renderer tests first.

## Task 3: Unify generator publication and check behavior

Refactor `generate_models_catalogue.py` so one collected snapshot feeds all
renderers and strict validation. Normal writes produce all references;
`--check` compares all of them and performs zero repository/cache writes;
`--summary` includes semantic findings and remains read-only. Render and
validate everything before atomic replacements. Treat unavailable required
supplemental evidence as degraded instead of mixing snapshots. Keep the old
write flags accepted and marked deprecated. Fix the baseline Apollo
supplemental-fetch failures by enforcing the existing read-only access policy
through every supplemental path. Add CLI/publication tests first.

## Task 4: Merge the optional remote confidence audit

Move the old mvsepless checkpoint-confidence implementation into
`scripts/catalogue/stem_audit.py` behind generator mode
`--audit-stem-confidence`. Preserve `--guessed-only`, `--only`, `--limit`,
`--json`, `--quiet`, and hash-cache control. Default uses warm caches,
`--refresh` forces refresh, and `--offline` suppresses every network boundary;
reject offline with hash-cache bypass. Preserve atomic JSON output and Ctrl-C
exit 130. Remove `scripts/stem_semantics_audit.py`, update script documentation
and examples, and migrate its tests to the unified CLI/module. Add failing
behavioral tests before moving production code.

## Task 5: Integrated verification and generated artefacts

Regenerate the five catalogue artefacts from one authoritative snapshot and
verify matching warm-offline output. Require the current checked-in universe
to retain 485 canonical IDs and 1,206 semantic output/context rows unless the
authoritative refreshed snapshot proves an intentional catalogue change. Run
the focused generator, manifest, source, and tool suites; scoped Ruff and
format checks; basedpyright; the complete unit suite; and `git diff --check`.
Do not push.
