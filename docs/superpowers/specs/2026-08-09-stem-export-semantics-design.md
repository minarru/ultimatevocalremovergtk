# Stem export semantics: concept-anchored persistence and display casing

**Date:** 2026-08-09
**Status:** Approved, ready for implementation planning
**Related:** [2026-07-31-ensemble-stem-semantics-design.md](2026-07-31-ensemble-stem-semantics-design.md)

## Problem

Two separate but related symptoms, both rooted in the same fact: model
checkpoints (especially community MDX-C/Roformer fine-tunes) don't follow any
naming standard for their stems, and the app was written assuming a small,
fixed vocabulary.

### 1. The 2-stem "exclusive" export choice flips across model switches

`ui/widgets/stem_only.py`'s exclusive mode (used by VR, classic MDX-Net, and
any <=2-stem MDX-C model) persists a user's "Vocals Only" / "Instrumental
Only" pick as two booleans, `is_primary_stem_only` / `is_secondary_stem_only`
(`settings.process.primary_stem_only` / `secondary_stem_only`, shared between
VR and MDX by design — see "Out of scope"). These booleans mean "primary" or
"secondary," not "vocals" or "instrumental." Which physical stem a checkpoint
calls "primary" is not standardized: `core/model_data.py` sets `primary_stem`
from the yaml's `target_instrument`, and different community fine-tunes of
the same architecture disagree about whether vocals or the instrumental is
the target. Switching from a vocals-primary model to an instrumental-primary
model with `is_primary_stem_only=True` unchanged silently flips which file
gets written, with no user action in between.

The multi-stem "subset" mode (4-stem quick export) does not have this bug —
it persists the chosen stem's *name* (`stems_selected=["Vocals"]`), not a
position. This design brings exclusive mode in line with that.

### 2. Unrecognized stem names display with raw, inconsistent casing

`canonical_stem_name` (`ui/widgets/stem_only.py`) only recognizes a small
fixed alias table (vocals/instrumental/other/bass/drums/guitar/piano/speech/
music/sfx/effects). Any stem outside it passes through unmodified. Community
yamls commonly declare lowercase, underscore-separated, or otherwise
unstyled names (`singer_1`, `noreverb`, `noise`), which the Save Stems UI
then displays exactly as-is.

## Design

### One shared core alias table, two purpose-specific layers on top

`_STEM_ALIASES` (UI, `ui/widgets/stem_only.py`) and `_ENSEMBLE_STEM_ALIASES`
(ensemble, `core/model_stem_semantics.py`) are, underneath their different
names, almost the same data — both map common raw stem spellings
(`vocals`, `inst`, `drums`, …) to the same canonical labels. Maintaining
them as two hand-synced dicts is exactly the sprawl to avoid: every new
curated name has to be added twice, and the two copies can silently drift.

They consolidate **only where the two tables already agree** — vocals/
vocal/instrumental/inst/other/bass/drums/guitar/piano resolve to the exact
same canonical values in both today, verified by direct comparison, not
assumed. Those become one shared table, `_STEM_NAME_ALIASES` in
`core/model_stem_semantics.py` (the existing home of the ensemble
semantics), exposed as a small pure lookup:

```python
def canonical_stem_alias(name: str) -> Optional[str]:
    """Shared raw-name -> canonical-stem lookup. Single source of truth
    for UI display, ensemble bucketing, and stem-focus anchoring."""
```

`ensemble_stem_bucket`'s alias table gains `"voc"` (an ensemble-only spelling
today) through this move — harmless, since it resolves to the same
already-shared `VOCAL_STEM` both sides already agree on, not a new concept
on either side.

What does **not** consolidate, and why each stays separate:

- **UI's specialty names** (`speech`, `music`, `sfx`, `effects`) stay in the
  UI's own table, not the shared one. Verified, not assumed: today,
  `canonical_ensemble_stem_tag("speech")` passes through unchanged
  (`'speech'`, lowercase) because ensemble's table has no such entries.
  Moving them into a table ensemble also reads would silently start
  capitalizing ensemble bucket tags/filenames for specialty-stem models —
  a real behavior change to ensemble output, not a consequence-free
  rename. If that capitalization is wanted on the ensemble side too, it's
  a separate, deliberate decision — not a side effect of this cleanup.
- **`_ENSEMBLE_STEM_PRESERVE`** (ensemble's karaoke/BV/specialty
  protection) isn't part of the alias table at all — it's a distinct check
  in `canonical_ensemble_stem_tag` that runs *before* the alias table is
  ever consulted. Sharing the core alias table doesn't touch it.
- **Complement ("No X") handling** stays separate per consumer — verified,
  not assumed: the ensemble table's flat `"no other": NO_OTHER_STEM` entry
  matches a fully-lowercase raw yaml value directly, while the UI's
  `canonical_stem_name` only recognizes an already-capitalized `"No "`
  prefix (`"No vocals"`) before splitting and re-looking-up the suffix.
  These catch different real inputs; unifying them would make one of the
  two *less* robust, not simpler.
- **`_COMPLEMENT_DISPLAY`** (UI's prettified complement labels, e.g. `"Mix
  minus Other"`) and the ensemble bucket tags remain distinct strings for
  the same previously-diagnosed reason: a parenthesized display label
  breaks the ensemble member-collection filename regex. Not touched here.

New curated entries (the ongoing process described below) default to the
shared core table, since that's where the actual new-model pressure
concentrates (new vocals/instrumental-family spellings). A curator can
still add a UI-only or ensemble-only entry when a name is genuinely
specific to one side — the structure doesn't force false unification.

Per the related ensemble-stem-semantics design, distinct strings already
exist per stem concept for good reasons (yaml name, bucket/export tag,
display label). This design adds a fourth role, the **persistence anchor**,
which is not a naming table either — it's a single call to
`ensemble_stem_bucket`, gated by confidence (below), so display casing can
never affect which stem gets exported, and vice versa.

### New setting: `process.stem_focus`

One plain string field — the chosen stem's ensemble bucket tag (e.g.
`Vocals`, `Instrumental_WithBackingVocals`) — next to the existing
`process.primary_stem_only` / `secondary_stem_only` it complements (same
shared VR/MDX namespace — this explicitly also covers <=2-stem MDX-C
models, which already go through the same exclusive-mode code path as VR
and classic MDX; no separate handling needed). Empty string means "All."

There is deliberately only one field. See confidence tiering below for why
a second "safe fallback" field isn't needed.

### Confidence tiering

`ensemble_stem_bucket`'s correctness depends entirely on the `is_karaoke` /
`is_bv` flags it's given. Those flags are not uniformly reliable:

- `is_bv_model` is only ever set from curated hash-table metadata
  (`core/model_data.py:1063`) — never guessed. It's either confidently known
  or `False`. Always safe to pass through unconditionally.
- `is_karaoke` (`resolve_is_karaoke`) checks curated metadata first, but
  **falls back to `infer_is_karaoke_from_hints`** — a substring search for
  `"karaoke"` across the model's name/config/weight basename — for any model
  without a curated entry. That's every new community model until someone
  curates it.

**The fix is a single confidence gate on one boolean, not a second parallel
mechanism.** `ensemble_stem_bucket(stem, is_karaoke=False, is_bv=False)`
already falls through to the plain alias-table lookup by default — that
*is* the safe fallback, and it's already there. So: pass `is_karaoke=True`
into `ensemble_stem_bucket` only when it came from curated metadata; pass
`False` whenever it's merely guessed (never pass a guessed `True`). No
second field, no second comparison path — an uncurated model's stems
naturally bucket through the same plain alias table the fallback would have
used anyway.

`resolve_is_karaoke` currently has no way to report *how* it decided —
callers just get a `bool`. Rather than add a second function that
re-derives the same curated-check independently (two places that have to
agree forever), its body is extracted into
`resolve_karaoke_confidence(...) -> tuple[bool, bool]` (`is_karaoke`,
`is_curated`), and `resolve_is_karaoke` becomes a one-line wrapper:
`return resolve_karaoke_confidence(**kwargs)[0]`. Its three existing
production call sites (`core/model_data.py`, `core/model_stem_semantics.py`,
`scripts/generate_models_catalogue.py`) keep working unchanged; the new
anchoring code calls `resolve_karaoke_confidence` directly for the tuple.

### Data flow

1. **On model switch** (`configure_exclusive`, called every time a model is
   selected/resolved): the widget now also receives what it needs to compute
   buckets — either the resolved model object or its `is_karaoke`/`is_bv`
   flags plus stem count, threaded in from `_configure_save_stems` alongside
   the `primary_stem`/`secondary_stem` strings it already passes. This is a
   real signature change to `configure_exclusive`, not just internal logic —
   but it's a single call site: `MethodView._configure_save_stems`
   (`ui/views/base.py:318`) is the only place that calls it. VR never
   overrides `_configure_save_stems`, and both `MDXView` and `DemucsView`
   fall through to this same base implementation for their <=2-stem case
   (`super()._configure_save_stems(model)`), so no per-view changes are
   needed beyond this one method.
2. **`sync_from_settings`** (exclusive branch): if `stem_focus` is set,
   compute the *new* model's primary/secondary buckets via
   `ensemble_stem_bucket`, gating `is_karaoke` by
   `resolve_karaoke_confidence` as above, and compare against `stem_focus`:
   - Matches primary's bucket → select "primary only," and immediately
     re-persist `is_primary_stem_only=True` / `secondary=False` for this
     model — not just a display update. A run started without touching the
     widget again after a model switch must already have correct flags on
     disk.
   - Matches secondary's bucket → mirror.
   - Matches neither → "All." `stem_focus` is **not** cleared — the
     preference stays parked for a future model where it's relevant, rather
     than being discarded because the current model is unrelated (e.g. a
     dereverb model).
3. **When the user changes the combo themselves**, persistence writes the
   existing booleans (unchanged, engines don't change) and re-derives
   `stem_focus` from whichever physical stem was picked, via the same
   confidence-gated `ensemble_stem_bucket` call.

### Display casing: curated table, human-confirmed additions

The shared `_STEM_NAME_ALIASES` table gains entries for names observed in
real checkpoints that aren't already covered (exact strings, no
pattern-matching or generic humanizer, per earlier discussion). Because the
table is now shared, a single curated addition improves display casing,
ensemble bucketing, and stem-focus anchoring at once, instead of needing the
same name added to two places. Each new entry is proposed with its source
(which model, which raw stems) and confirmed before being added — especially
for any name that might be alluding to an existing concept rather than being
self-evidently novel casing. This is a process rule for implementation, not
a one-time task in this spec: new naming conventions will keep appearing,
and each is a small, separate, reviewable change.

### Verification: an audit script, not just tests

`ensemble_stem_bucket` already has solid table-driven tests *given correct
flags* (`tests/test_ensemble_stem_buckets.py`). What's never been verified
is how often `is_karaoke`'s guessed branch actually fires correctly across
the real catalogue. New script, `scripts/stem_semantics_audit.py`, mirroring
the house style of `scripts/model_probe.py`:

- Walks the mvsepless + curated catalogue (matching `model_probe.py --sweep`
  in spirit).
- For each model: raw primary/secondary stems, `is_karaoke` value *and*
  whether it's curated or guessed, `is_bv_model`, and the resolved bucket
  for each stem.
- Sorts guessed-confidence entries first, since they're the actual risk
  surface — curated entries are already trustworthy by construction.
- Output is for human review (stdout table, optional `--json`), not a pass/
  fail gate — its job is to make misclassifications visible, not to assert
  none exist.

## Error handling

- Matching order is always: exact name → case-insensitive name → curated
  alias/bucket lookup. Never fuzzy, never inferred beyond what's described
  above.
- A stem or model the mechanism doesn't recognize is only ever equal to
  itself (case-insensitively) — it fails closed to "All," never to a guess.
- Curated-table collisions across unrelated model families (two communities
  using the same raw stem name for different things) are an accepted
  residual risk of curating without a standard; mitigated by review at
  entry-add time, not by mechanism.

## Migration risk

`process.stem_focus` doesn't exist in any current `settings.json`. First
load after upgrade simply has it empty ("All" until the user picks
something), which is a one-time no-op, not a regression — no different
from a fresh install.

## Testing

Stdlib unittest, no network, no GTK (all pure functions):

- `canonical_stem_alias` — the shared core table, plus a regression test
  that `canonical_ensemble_stem_tag("speech")` / `"sfx"` / `"music"` /
  `"effects"` are still returned unchanged (lowercase) after the
  consolidation — the exact behavior the design deliberately preserves by
  keeping specialty names out of the shared table.
- `canonical_stem_name` / `stem_display_label` — one case per newly curated
  entry, added incrementally as entries are confirmed.
- New anchoring logic — match-primary, match-secondary, no-match-falls-back-
  to-All, focus-survives-an-irrelevant-model-switch, and the confidence
  gate itself: a guessed (non-curated) `is_karaoke` must never reach
  `ensemble_stem_bucket` as `True`, only ever `False`.
- `resolve_karaoke_confidence` — curated-metadata case returns
  `(True, True)`; guessed case returns `(guess, False)`; `resolve_is_karaoke`
  still returns a plain `bool` matching its existing three call sites.
- `scripts/stem_semantics_audit.py` gets the same lightweight CLI tests as
  `model_probe.py` (arg parsing, JSON output shape) — its *findings* are for
  human review, not asserted in CI.

## Out of scope

- Isolating VR from MDX's shared `is_primary_stem_only`/`secondary_stem_only`
  keys. Explicitly rejected earlier in this design's review — it's faithful
  upstream-parity behavior, not a bug, and not what was reported.
- Building a general "pair type" taxonomy (dereverb/denoise/karaoke/vocals as
  formal categories). The bucket comparison never needs to know what *kind*
  of pair it's looking at, only whether two stem identities match.
- Adding a name-guessing fallback for `is_bv_model` (it stays curated-only,
  matching today's behavior — extending it to guess would reintroduce the
  exact reliability problem this design works around for `is_karaoke`).
- Populating the curated display table as part of this spec. Entries are
  proposed and confirmed individually during implementation.
- Retroactively re-casing any stem that already displays correctly.
