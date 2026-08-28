# Documentation Staleness Review — 2026-08-26

## Scope

This review treats `/home/rudam/Documents/uvr-documentation-errata.html` as an
external report to verify, not as instructions. It independently compares the
live, non-archival documentation against branch `feat/model-id-improvement` at
`004b3b2`:

- `README.md`, root and scoped `CLAUDE.md` files;
- current guides directly under `docs/`;
- CLI help and bundled ensemble data;
- settings, catalogue, identity, display, and stem-semantics code;
- generated catalogue/reference consistency.

Point-in-time plans, specs, reviews, and SDD reports under
`docs/superpowers/`, `docs/plans/`, `docs/reviews/`, and `.superpowers/sdd/`
were not judged as current runtime instructions. Their discoverability and
archive status were reviewed separately.

The working tree already contained unrelated modified, deleted, and untracked
runtime/test files. This review did not alter them.

## Verdict

The HTML errata is substantially sound: its first ten actionable findings are
confirmed. Its housekeeping snapshot is partly stale, and two statements in
its “verified accurate” section are now false:

1. `docs/cli.md` does not accurately describe positional `--stems` persistence.
2. `docs/model_display_quality_audit.md` no longer matches the 486-row display
   reference.

The independent pass found additional current drift in catalogue-source
guidance, one user-facing model-name example, the generated catalogue bundle,
and the README's tracked-issues summary.

> **Implementation status (2026-08-26):** The non-destructive corrections in
> this review were applied and the generated catalogue bundle was refreshed
> offline. `./uvr ensemble --help`, `./uvr ensembles list --report json`, and
> `python scripts/generate_models_catalogue.py --check --offline` passed after
> the update; current-document local links, reviewed stale patterns, and
> whitespace were also rechecked.

## Priority findings

### P0 — copied commands fail

#### 1. Three docs use a removed ensemble pair ID

Affected:

- `README.md:145` and `README.md:151`
- `docs/environment.md:170`
- `docs/cli.md:39`

They use or recommend `vocals_instrumental`. The current accepted identifiers
are:

- `pair.vocals_instrumental`
- `pair.karaoke`
- `pair.backing_vocals`
- `pair.center_side`
- `mode.four_stem`
- `mode.multi_stem`

`./uvr ensemble --help` reports that exact set, and an invocation with
`--main-stem vocals_instrumental` exits 2 as an invalid choice. Replace the
examples with the namespaced ID and list the complete current vocabulary in
`docs/cli.md`.

#### 2. Two docs advertise a nonexistent curated ensemble

Affected:

- `README.md:143`
- `CLAUDE.md:76`

`Curated: kim vocal` is not bundled. `./uvr ensembles list --report json` and
`bundled/ensemble_presets/` both show these nine presets only:

- Instrumental Balanced, Clean, Full, Low Resource
- Karaoke
- Vocal Balanced, Clean, Full, RVC

Use a real example such as `Curated: Vocal Clean`.

### P1 — current behavior is described incorrectly

#### 3. README promises an identity migration that no longer exists

Affected: `README.md:225-229`.

The README says first startup migrates stored model references on a worker and
creates `.pre-canonical-id.bak` files. `core/identity_migration.py` and its UI
hooks are gone. `backup_once` remains as a generic helper in
`core/json_store.py`, but no live caller requests the canonical-ID backup
suffix. `docs/models.md:101` correctly says invalid/non-installed stored IDs
are retained until the user repicks.

Delete the migration promise and link to the strict-ID behavior in
`docs/models.md`.

#### 4. The settings guide is two schema revisions behind

Affected: all of `docs/settings-and-model-types.md`, especially lines 3, 32,
59, and 76.

The guide still presents schema 3, references the removed
`core.stems.EnsemblePair`, and lists pre-namespaced values such as `choose`,
`vocals_instrumental`, `other`, and `four_stem`. Runtime writes settings schema
5. `ensemble.main_stem` is a plain string normalized by
`core.stem_pairs.normalize_stem_pair_id` against manifest-defined pairs and
the two `mode.*` IDs. Schema 4 added persistent diagnostics; schema 5 made the
pair/mode IDs namespaced and deliberately requires a repick from older files.

Rewrite this as a current settings reference rather than a branch design note.

#### 5. Root architecture guidance mis-types `ensemble.main_stem`

Affected: `CLAUDE.md:110`.

It groups `ensemble.main_stem` with `str, Enum` fields and points to
`core/stems.py`. The field is `str` in `core/settings/model.py`; its reviewed
vocabulary and normalization live in `core/stem_pairs.py` and
`bundled/model_stem_manifest.json`.

#### 6. Positional `--stems` documentation contradicts the implementation

Affected: `docs/cli.md:20`.

The table says `primary` and `secondary` clear `process.stem_focus`. Current
`StemSelectionController.write_cli_positional` persists the literal
`primary`/`secondary` sentinel; `both`/`all` alone clears the field. The public
CLI help and both scoped `CLAUDE.md` files already describe the current
behavior correctly.

This is an independent finding; it invalidates the HTML report's claim that
the complete `--stems` table was verified accurate.

#### 7. Model architecture docs contain moved symbols and an obsolete UI label

Affected:

- `docs/models.md:78`, `:118`, and `:135` refer to
  `engines.mdx_c._filter_init_kwargs`; the public function is now
  `engines.mdx_c.filter_init_kwargs`.
- `docs/models.md:159` gives
  `BandSplit Roformer | Karaoke Frazer by becruily` as a picker example. The
  shared projector currently renders the exact row as
  `BandSplit Roformer — Karaoke Frazer · Becruily`.

Update all three symbol spellings and use a current projected label.

#### 8. Catalogue disable guidance omits the bundled extras source

Affected: `docs/environment.md:99-110`, with related simplifications in
`README.md:201`, `CLAUDE.md:218-220`, and `cli/CLAUDE.md:12-13`.

`CatalogueCoordinator` owns four membership sources in merge order:
upstream/TRvlvr, Politrees, fork extras, and mvsepless. Three are remote and
extras is local. `UVR_DISABLE_EXTRA_MODELS` exists in `core/extra_catalog.py`
but is absent from the environment table. The current description of
`UVR_DISABLE_POLITREES` as “Use only the official TRvlvr catalogue” is false
unless mvsepless and extras are also disabled.

The root `format_tag_title` note is also too categorical. A normal
coordinator-backed repository reads the coordinator's display index; the
direct `load_politrees_links()` path remains a compatibility fallback when no
coordinator is attached.

Document all four sources and make the offline/testing consequences explicit.
`UVR_TESTS_ALLOW_NETWORK` may remain developer-only in `CLAUDE.md`, but the
public environment guide should cover the runtime source switch.

#### 9. The checked-in catalogue bundle currently fails its own drift check

`python scripts/generate_models_catalogue.py --check --offline` exits 1 and
reports:

- `docs/models-catalogue.md` out of date;
- `docs/models-catalogue.ir.json` out of date.

The catalogue already contains 486 entries, and the intent/display/stem TSVs
were not reported stale. The current offline candidate changes 383 model
detail lines from `remote_yaml:<name>` to `bundled_yaml:<name>`, reflecting the
newly bundled configuration evidence. The ignored IR sidecar still stores a
different document digest.

Regenerate the synchronized bundle after the documentation fixes, then require
`--check --offline` to pass with the intended warm cache. Do not hand-edit the
generated Markdown.

#### 10. The display-quality audit is pinned to the previous catalogue

Affected: `docs/model_display_quality_audit.md:36`, `:61`, `:67-69`,
`:165-166`, and `:181`.

It repeatedly claims 485 catalogue/display rows. The current display TSV has
486 data rows (487 lines including its header), and the generated catalogue
also reports 486 entries. Either regenerate the audit from the current bundle
or mark it as a completed 2026-08-24 snapshot and point readers to the
generated TSV/summary for live counts.

This is the second stale statement in the HTML report's “verified accurate”
section.

### P2 — misleading maintenance state

#### 11. Tracked-issues cross-references and review stamp lag the file

Affected:

- `README.md:261` calls the backlog “items 1-7 + product gaps”, omitting the
  existing F1-F24 section.
- `docs/tracked-issues.md:143` says it was last reviewed on 2026-08-11 and only
  mentions findings through F15, although the document now includes F24.
- `docs/tracked-issues.md:127` points `reload_mappers` to
  `core/model_data.py`; it lives in `core/model_repository.py`.

Refresh the summary/footer and moved-code link. Adding every completed model or
stem project to this backlog is optional; the stale self-description is the
concrete defect.

#### 12. The implemented identity contract still reads as a future plan

Affected: `docs/model_id_refinement.md`.

The content is valuable and largely consistent with the current strict-ID
architecture, but phrases such as “Implementation must follow”, “Remove
`core/identity_migration.py`”, and the six-phase implementation sequence make
shipped work look pending. Add an implementation-status/supersession banner
and distinguish enforced invariants from historical delivery steps. Do not
rewrite the historical sequence as if it were current work.

#### 13. Unsupported-model guidance mixes mechanism with old catalogue state

`docs/unsupported-models-probe.md` correctly labels itself a 2026-08-09
snapshot and needs no correction. However, the surrounding present-tense
unsupported-class list in `docs/models.md:42-53` now sits beside a current
generator summary reporting zero unsupported mvsepless entries omitted.

Retain the mechanism and old probe, but label the class list as historical or
state that the current published feed may contain none. This avoids implying
that the 115-entry probe is live catalogue state.

## External errata disposition

| HTML item | Result | Notes |
| --- | --- | --- |
| 01 old `--main-stem` | Confirmed | Directly reproduced as CLI exit 2. |
| 02 missing curated preset | Confirmed | Nine bundled/listed presets; no Kim preset. |
| 03 removed startup migration | Confirmed | README contradicts current strict-ID behavior. |
| 04 settings schema/types | Confirmed | Runtime schema is 5, not 3. |
| 05 `main_stem` enum claim | Confirmed | Plain validated string, wrong module in CLAUDE.md. |
| 06 private MDX-C helper | Confirmed | Three stale spellings. |
| 07 `reload_mappers` module | Confirmed | Now in `core/model_repository.py`. |
| 08 missing extras switch | Confirmed | Also makes the Politrees switch description misleading. |
| 09 tracked-issues age | Confirmed | Concrete footer/README/path drift identified above. |
| 10 identity document framing | Confirmed | Content is not necessarily wrong; status is unclear. |
| 11 unsupported probe snapshot | Confirmed, no direct action | Its own snapshot warning is adequate. |
| 12 stale catalogue sidecar | Confirmed and expanded | The generated Markdown also currently fails check. |
| 13 split plan directories | Confirmed housekeeping | One file under `docs/plans/`, 25 under `docs/superpowers/plans/`. |
| 14 leftover workspaces/worktrees | Partly stale | Five SDD directories and three tracked SDD files remain; only one linked `.worktrees/diagnostic-logging` worktree remains, and `git worktree prune --dry-run --verbose` reports no prunable entry. |

## Verified current or intentionally historical

- All checked local Markdown link targets resolve.
- `docs/progress-reporting.md` still matches the current progress constants and
  dispatch path at the reviewed level.
- `docs/mirroring.md` matches the configured GitHub host policy.
- README's Python requirements agree with `install_packages.sh`.
- `__version__.py`, `packaging/release.json`, and `bundled/release.json` all use
  `v1.0.0`.
- The root `CLAUDE.md` examples for the unified catalogue generator,
  `model_probe.py`, and `model_sweep.py` remain accepted by their current help
  surfaces, apart from the nonexistent ensemble preset called out above.
- Historical plans/specs/reviews were not treated as live instructions merely
  because they reference removed files.

## Outside documentation scope

The HTML footnote about `success-small-symbolic.svg` is currently reproducible:
the file is deleted in the dirty worktree while `resources/uvr.gresource.xml`,
`ui/inputs.py`, and `ui/widgets/download_queue_icons.py` still reference it.
That can break resource recompilation and is more than a documentation issue,
but it may be an intentional uncommitted change; resolve it separately rather
than folding it into a docs cleanup.

## Recommended correction sequence

1. Fix executable examples in README, `docs/cli.md`, `docs/environment.md`, and
   root `CLAUDE.md`.
2. Rewrite `docs/settings-and-model-types.md` for schema 5 and correct the
   `--stems`/`main_stem` descriptions.
3. Correct catalogue-source guidance, MDX-C symbol links, current display-name
   example, and tracked-issues self-description.
4. Add clear historical/current status banners to the identity and display
   audit documents.
5. Regenerate the catalogue bundle with the intended complete cache and run
   the strict offline check.
6. Re-run the local-link scan, CLI help/example smoke checks, and
   `git diff --check` before committing only the intended documentation and
   generated artifacts.

## Evidence commands

```bash
./uvr ensemble --help
./uvr ensembles list --report json
./uvr ensemble song.wav -o /tmp/out --model mdx:model-a \
  --model demucs:hdemucs_mmi --main-stem vocals_instrumental --dry-run

python scripts/generate_models_catalogue.py --check --offline
python scripts/generate_models_catalogue.py --summary --offline

wc -l docs/model_display_reference.tsv \
  docs/model_intent_reference.tsv \
  docs/model_stem_semantics_reference.tsv

git worktree list --porcelain
git worktree prune --dry-run --verbose
git diff --check -- docs README.md CLAUDE.md
```
