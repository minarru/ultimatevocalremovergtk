# Model Display Projection and Refresh Design

**Date:** 2026-08-22  
**Status:** Implemented and verified (2026-08-23). Full suite 2639 tests OK (6 skipped); basedpyright 0 errors; GTK tests run on a private headless Wayland session, not the host compositor.  
**Scope:** Exact model display projection, presentation refresh, picker refresh policy, and completed-download publication

> **Revision notice (2026-08-24):** The naming-quality and published-catalogue
> backfill rules in this implemented design are superseded by the approved
> [`Model Display Quality and Backfill Revision Design`](2026-08-24-model-display-quality-and-backfill-revision-design.md).
> Canonical identity and the remaining refresh/publication contracts here stay
> in force.

## Summary

Every model surface must obtain its human-readable name from
`ModelRecord.display`, while runtime identity remains the exact canonical
`family:basename`. Installed models that are absent from the current catalogue
must receive an exact catalogue or name-mapper display when one exists and keep
their raw basename when no exact presentation mapping exists.

Inventory changes and presentation-only changes are different events. A model
installation invalidates the full inventory exactly once, after that logical
model has all required artifacts and registration metadata needed to be usable.
A catalogue-label or name-mapper change refreshes presentation without
incrementing `inventory_generation`, rehashing checkpoints, invalidating an
execution plan, or changing picker eligibility.

All GTK model consumers refresh through the existing coalesced main-window
spine. Valid selections survive a relabel by canonical ID. A previously missing
or warning-gated value remains gated when an exact matching model becomes
available and requires an explicit user repick.

## Problem

Before the canonical-identity cutover, method pickers mapped on-disk basenames
to friendly names independently. The cutover correctly made pickers consume
`ModelRecord` values, but installed-only records are currently created with
`display=basename`. The result is inconsistent presentation:

- the main, secondary, pre-process, ensemble-member, vocal-splitter, and Apollo
  pickers may show raw filenames;
- progress and log labels can show a friendly exact mapping for the same model;
- catalogue source refinements can change available presentation data without
  repainting already-mounted widgets; and
- download completion currently has more than one possible invalidation owner,
  causing batch-delayed refreshes and possible duplicate invalidations.

The fix must restore the friendly-name behavior of `main` without restoring
display-to-basename runtime resolution or weakening the canonical-ID contract.

## Goals

1. Give every installed `ModelRecord` the same friendly display that `main`
   produces when an exact presentation mapping exists.
2. Make `ModelRecord.display` the single presentation source for GUI pickers,
   progress/log labels, Model Test output naming, and human-readable CLI output.
3. Preserve canonical IDs, backend names, artifacts, execution metadata, and
   model-identity digests when only a display changes.
4. Refresh mounted model widgets when catalogue or mapper presentation changes.
5. Publish each completed logical model download exactly once, as soon as that
   model is usable, without waiting for the rest of the queue.
6. Preserve warning gates and require an explicit repick when a formerly
   unavailable canonical ID becomes available.
7. Keep the vocal-splitter picker restricted to karaoke-eligible models.

## Non-goals

- Renaming checkpoint, YAML, configuration, or registry files.
- Changing canonical IDs, backend lookup values, saved settings, or manifests.
- Resolving runtime input from display labels.
- Adding aliases, migrations, fuzzy matching, or unique-substring matching to
  inventory presentation.
- Correcting questionable source mapping data in code. Incorrect exact mappings
  must be fixed in the catalogue or mapper data.
- Reordering or broadening stem, karaoke, secondary, or ensemble eligibility.
- Proving that a downloaded neural network will complete inference. "Usable"
  here means that the repository has every declared artifact and registration
  datum required to construct an installed, identity-complete record.

## Identity and Presentation Contract

`ModelRecord.display` is presentation-only. Enrichment must never alter:

- `id`, `family`, or `basename`;
- `backend_name`;
- primary or supporting artifact filenames;
- `demucs` or `mdx` execution specifications;
- installation and completeness semantics; or
- canonical values persisted by GTK or accepted by the CLI.

The model identity digest continues to exclude `display`. A presentation-only
change therefore cannot invalidate a resolved separation, ensemble, or audio
plan.

Duplicate display strings are allowed. Picker rows retain their canonical ID
as their value, and no runtime path may invert display text into identity.

## Exact Display Projection

The inventory builder applies one presentation-enrichment pass after catalogue,
installed, bundled, and locally registered records have been merged. This keeps
all consumers consistent and avoids presentation logic in individual widgets.

For each record:

1. Preserve an already-friendly display supplied by an exact catalogue record
   or trusted local registration.
2. If the catalogue display merely echoes the basename, try an exact family
   name-mapper match.
3. If no catalogue record exists, try an exact family name-mapper match.
4. Otherwise retain the raw basename.

Family details:

- **MDX:** exact catalogue display index, then exact MDX name mapper, then raw.
- **VR:** exact catalogue display index, then raw.
- **Demucs:** exact catalogue display index, then exact Demucs name mapper, then
  raw. Trusted registered-Demucs display metadata remains authoritative for its
  record.
- **Apollo:** exact catalogue or registered display, then raw; Apollo currently
  has no name mapper.

"Exact mapper match" permits only the canonical basename itself or the same
basename with a recognized artifact extension. It does not permit containment,
substring, case-guessing, or matching against a display value. The inventory
path must use a dedicated exact helper rather than the legacy mapper helper's
substring fallback.

The local mapper overlay continues to win over the upstream mapper mirror
within the mapper layer. A genuinely friendly catalogue display still wins over
the mapper, matching `main` behavior.

The projection is offline and side-effect free. It reads only the repository's
current mapper snapshot and the coordinator's already-published catalogue
snapshot. It performs no network access, checkpoint hashing, model probing, or
settings writes.

## Repository Revisions and Events

The repository exposes two semantic notifications.

### Full inventory change

The existing `models_changed` event remains the event for installed artifacts
or execution metadata changing. `invalidate_models()`:

- increments `inventory_generation`;
- clears identity, stem-check, karaoke, and other inventory-derived caches;
- rehydrates trusted hashes and reloads mappers;
- invalidates resolved plans through the existing generation check; and
- emits `models_changed` once.

A full invalidation subsumes presentation. It must not also emit a separate
presentation event, because both events would schedule duplicate widget work.

### Presentation-only change

Add a repository-owned `model_presentation_changed` subscription alongside the
existing `models_changed` subscription. A presentation invalidation:

- clears the identity/display projection cache and any cached picker projection
  containing display strings;
- reloads name mappers and bumps the naming revision when the mapper files are
  the source of the change;
- leaves `inventory_generation`, trusted hashes, stem checks, karaoke
  eligibility, and execution metadata intact; and
- emits `model_presentation_changed` once.

Because the repository already owns the catalogue coordinator reference and
keys its identity index by catalogue revision, it subscribes to coordinator
deltas capable of changing a published display index. Source changes trigger a
presentation invalidation. Stem-subtitle-only metadata changes do not repaint
model pickers. Coordinator callbacks may arrive on worker threads; repository
notifications remain thread-agnostic, and GTK consumers marshal them to the
main loop.

Listener exceptions are isolated and logged so one subscriber cannot strand
the remaining refresh wave. Re-entrant notification is guarded as it is for
the current inventory event.

## GTK Refresh Lifecycle

`MainWindow` subscribes the same coalescing callback to both repository events.
Both events arrive after their respective repository caches are invalidated, so
the UI callback only repaints; it never calls an invalidation method. If both
events arrive before the idle callback runs, one repaint is sufficient.

Refresh policy:

- **Primary method pickers:** rebuild immediately.
- **Apollo picker:** rebuild immediately.
- **Expanded secondary and pre-process sections:** rebuild on the next idle
  callback.
- **Collapsed secondary and pre-process sections:** mark dirty and rebuild when
  expanded.
- **Expanded vocal-splitter row:** rebuild on the next idle callback.
- **Collapsed vocal-splitter row:** mark dirty and rebuild when expanded.
- **Open or active ensemble member sheet:** rebuild immediately.
- **Inactive ensemble page:** mark the member list dirty and rebuild on
  activation.
- **Active separation run:** defer and coalesce all model-list repaints until
  the run finishes.

Every rebuild uses `ModelRecord.display` as the label and `ModelRecord.id` as the
value. A display change may reorder rows, but selection restoration is by
canonical ID and cannot write settings merely because the label or position
changed.

The vocal-splitter list continues to originate from the karaoke-eligible model
pool. Display enrichment and presentation refresh may rename its rows but may
not add a non-karaoke model.

## Selection and Warning Gates

The refresh code distinguishes a currently valid selection from a stored value
that was already warning-gated.

- A valid selected canonical ID remains selected after relabeling, reordering,
  or presentation refresh.
- A gated value remains stored verbatim and the widget continues to show no
  selection.
- If a newly downloaded model has exactly the gated canonical ID, it appears in
  the available list but does not clear the gate or select itself.
- Only a direct user choice from that picker clears its gate and replaces the
  stored value.

This rule applies to primary, secondary, pre-process, vocal-splitter, Apollo,
and ensemble-member selections. Lazy refresh must preserve the gate while a
section is collapsed or an ensemble page is inactive.

## Download Publication

A queue item represents one logical model and may contain multiple files. The
application publishes the item to the repository only after it is usable.

The per-model sequence is:

1. Finish every required download job for the catalogue entry.
2. Finalize each file from its temporary path.
3. Commit required MDX-C, Apollo, Demucs, hash ownership, and local display
   registration metadata.
4. Confirm that the completed transaction has all declared artifacts and
   metadata needed to produce the expected installed, identity-complete
   canonical record.
5. Call `invalidate_models()` exactly once.
6. Let the repository notification refresh mounted or lazy consumers.

This definition is transaction-completeness, not an inference smoke test. A
failed or cancelled item that has not reached the usable postcondition emits no
model-list invalidation. An unchanged `exists` result emits no invalidation
unless finalization repaired or added registration metadata and made the model
usable.

Each usable model in a multi-item queue invalidates independently when it
finishes. Users can select the first completed model while later items continue
downloading. The GTK coalescer may collapse notifications that arrive in the
same main-loop window, but the download system does not hold successful models
until the entire queue drains.

There is one shared invalidation owner for GUI and CLI downloads. Per-family
registration must not invalidate internally, the GTK batch-complete callback
must not invalidate, and the CLI post-batch path must not add a second
invalidation. Batch completion remains responsible for toasts, notifications,
Download Center status, and aggregate command results.

If finalization cannot establish usability, the item reports an actionable
failure or incomplete status and does not announce the model to mounted
pickers.

## Model Test Mode and Output Naming

Model Test mode (`process.add_model_name`) already receives its naming label
from the resolved plan's `ModelDescriptor.display`. The descriptor copies
`ModelRecord.display`, so inventory enrichment automatically makes output names
use the friendly label.

For example, an enriched record may produce:

```text
song MelBand Roformer — Karaoke · becruily (Vocals).wav
```

The same label is used for generated model folders. Filename sanitization
continues to remove unsafe path characters without changing canonical IDs or
backend artifact lookup. Unknown custom models use their raw basename.

Ensemble member filenames continue to include member display labels because
collection depends on those planned member names. This design does not change
the ensemble naming or collection contract; it only supplies the corrected
display label.

## CLI and Other Consumers

Human-readable CLI model listings and plan summaries consume the enriched
`ModelRecord.display`. Machine-readable output continues to expose canonical
IDs and unchanged backend/artifact fields. A display rename cannot make a CLI
model argument resolve, move a saved selection, or change a replay dependency.

Progress, error context, parameter dialogs, and option summaries should prefer
the record/descriptor display already carried by the resolved model. They may
retain a best-effort display fallback for objects without identity, but must not
perform display-to-ID inversion.

## Failure Behavior

- A missing or malformed mapper behaves as an empty mapper and falls back to
  the catalogue display or raw basename.
- One malformed catalogue or mapper row cannot empty an inventory or picker.
- A suspicious but exact source mapping is displayed as supplied; correcting
  it is a data-maintenance task.
- A presentation callback failure is logged and does not stop other listeners.
- A presentation change during a run is deferred and cannot mutate the active
  plan.
- A download that cannot meet its usable postcondition is not presented as a
  completed install.
- Duplicate display labels remain independently selectable by canonical ID.

## Testing Strategy

### Exact projection

- Friendly catalogue display wins over a mapper entry.
- A catalogue basename echo falls through to an exact mapper entry.
- An installed-only model receives an exact extension-normalized mapper entry.
- An unknown custom model retains its raw basename.
- A substring-only mapper candidate is rejected.
- Local mapper overlay precedence remains intact within the mapper layer.
- Enrichment leaves ID, basename, backend name, artifacts, architecture specs,
  installation state, and completeness unchanged.
- A representative installed-model fixture matches `main` for every exact
  mapping used by the fixture.

### Repository events

- Presentation invalidation rebuilds the display projection and emits once.
- Presentation invalidation does not increment `inventory_generation`, reload
  hashes, clear eligibility caches, change the model identity digest, or stale
  a resolved plan.
- Full invalidation emits the inventory event only and includes the new display
  on the next identity read.
- Catalogue display-index changes reach repository presentation subscribers.
- Re-entrant and throwing subscribers remain isolated.

### Downloads

- A multi-file model emits no invalidation after an intermediate file.
- Successful finalization emits exactly one full invalidation for that logical
  model.
- Multiple queue items publish individually rather than waiting for the batch.
- `exists` without a metadata change emits none.
- Metadata repair that makes an existing model usable emits exactly one.
- Failed, cancelled, or identity-incomplete finalization emits none and reports
  the reason.
- MDX-C and Apollo registration do not emit an additional invalidation.
- GTK batch completion and CLI batch completion do not duplicate the event.

### GTK consumers

- Primary and Apollo pickers repaint immediately.
- Expanded lazy pickers repaint on idle; collapsed pickers repaint on expand.
- Active ensemble members repaint; inactive ensemble members rebuild on
  activation.
- The vocal-splitter picker shows friendly names but only karaoke-eligible IDs.
- A selected canonical ID survives a label change and reorder without a
  settings write.
- A previously gated exact ID stays gated after installation until the user
  explicitly repicks it.
- Duplicate display labels retain distinct canonical values.
- Refreshes are deferred and coalesced during an active run.

### Naming and CLI

- Model Test output filenames and generated model folders use the enriched
  display.
- Unsafe display characters are sanitized only in filesystem components.
- Unknown custom models append their raw basename.
- Human-readable CLI output and progress labels agree with picker labels.
- Machine-readable IDs, backend names, artifacts, digests, and replay behavior
  remain unchanged across a display-only update.

## Acceptance Criteria

The change is complete when:

1. Every installed model with an exact presentation mapping displays the same
   friendly name in all pickers, progress/log surfaces, Model Test filenames,
   and human-readable CLI output.
2. Genuinely unknown custom models display their raw basename.
3. Canonical IDs and execution artifacts remain unchanged and no runtime path
   resolves a model from display text.
4. Catalogue-label changes repaint mounted widgets without staling plans.
5. Each logical download publishes once, only after it is usable, and does not
   receive a second batch invalidation.
6. Newly available gated IDs require an explicit repick.
7. Vocal splitter remains karaoke-only.
8. Focused regression tests, the complete unittest suite, basedpyright, and
   `git diff --check` pass in the repository's supported GTK test environment.
