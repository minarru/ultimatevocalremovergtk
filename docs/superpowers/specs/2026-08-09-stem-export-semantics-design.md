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

### Two tables, kept deliberately separate

Per the related ensemble-stem-semantics design, three strings already exist
per stem concept: the yaml's raw name, an ensemble bucket/export tag, and a
UI display label. This design adds a fourth role — a **persistence anchor**
— and is explicit about which existing mechanism answers which question, so
no single table has to be the answer to everything:

| Table | Lives in | Answers | Scope |
|---|---|---|---|
| `_ENSEMBLE_STEM_ALIASES` / `ensemble_stem_bucket` | `core/model_stem_semantics.py` | "what bucket does this stem belong to, for combining/matching" | Reused as-is; not modified by this design |
| `_STEM_ALIASES` / `canonical_stem_name` | `ui/widgets/stem_only.py` | "what should this stem be *called* on screen" | Extended: new curated entries for cosmetic casing only |
| *(new)* persistence anchor | `ui/widgets/stem_only.py` | "which physical stem did the user actually ask for, independent of this model's primary/secondary labeling" | New: described below |

The persistence anchor is **not** a third naming table. It's a comparison
that reuses the other two, choosing between them by confidence (below).

### New setting: `process.stem_focus` + `process.stem_focus_bucket`

Two plain string fields, next to the existing `process.primary_stem_only` /
`secondary_stem_only` they complement (same shared VR/MDX namespace — this
explicitly also covers <=2-stem MDX-C models, which already go through the
same exclusive-mode code path as VR and classic MDX; no separate handling
needed).

- `stem_focus`: the chosen stem's plain canonical name (via
  `canonical_stem_name`, cheap, always computable, no model flags needed).
  Empty string means "All."
- `stem_focus_bucket`: the chosen stem's ensemble bucket tag (via
  `ensemble_stem_bucket`), set **only** when it was computed under curated
  confidence (see below). Empty when not available.

Both are written together whenever the user picks a stem, and both are read
together whenever a newly-selected model needs its exclusive-mode combo
re-synced.

### Confidence tiering

`ensemble_stem_bucket`'s correctness depends entirely on the `is_karaoke` /
`is_bv` flags it's given. Those flags are not uniformly reliable:

- `is_bv_model` is only ever set from curated hash-table metadata
  (`core/model_data.py:1063`) — never guessed. It's either confidently known
  or `False`.
- `is_karaoke` (`resolve_is_karaoke`) checks curated metadata first, but
  **falls back to `infer_is_karaoke_from_hints`** — a substring search for
  `"karaoke"` across the model's name/config/weight basename — for any model
  without a curated entry. That's every new community model until someone
  curates it.

A new, additive helper, `is_karaoke_curated(model_data) -> bool`, reports
*only* the first (reliable) branch — whether curated metadata settled it —
without changing `resolve_is_karaoke`'s existing `bool` contract (it has
three production call sites today; none of them need to change).

**Rule:** bucket-tag comparison is only used when curated confidence holds
for the model providing the anchor *and* the model being switched to.
`stem_focus_bucket` is only ever written when the source model's karaoke
classification came from curated metadata (`is_bv_model` needs no such
check — it's never guessed). If either side falls back to guessed
confidence, comparison uses the plain `stem_focus` canonical name instead —
still a real improvement over today's position-based booleans, just not
karaoke/BV-aware. A guessed classification is never used to compute or
compare a bucket tag, so a wrong guess degrades to the simpler (safe)
matching mode rather than producing a confident wrong answer.

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
   compute the *new* model's bucket only if its own karaoke/BV
   classification is curated-confidence; if either that or `stem_focus_bucket`
   itself is unavailable, compare `stem_focus` against the new model's plain
   canonical primary/secondary names instead. Then:
   - Matches primary → select "primary only," and immediately re-persist
     `is_primary_stem_only=True` / `secondary=False` for this model — not
     just a display update. A run started without touching the widget again
     after a model switch must already have correct flags on disk.
   - Matches secondary → mirror.
   - Matches neither → "All." `stem_focus`/`stem_focus_bucket` are **not**
     cleared — the preference stays parked for a future model where it's
     relevant, rather than being discarded because the current model is
     unrelated (e.g. a dereverb model).
3. **When the user changes the combo themselves**, persistence writes the
   existing booleans (unchanged, engines don't change) and re-derives
   `stem_focus` / `stem_focus_bucket` from whichever physical stem was
   picked, using the same confidence rule.

### Display casing: curated table, human-confirmed additions

`_STEM_ALIASES` gains entries for names observed in real checkpoints that
aren't already covered (exact strings, no pattern-matching or generic
humanizer, per earlier discussion). Each new entry is proposed with its
source (which model, which raw stems) and confirmed before being added —
especially for any name that might be alluding to an existing concept rather
than being self-evidently novel casing. This is a process rule for
implementation, not a one-time task in this spec: new naming conventions
will keep appearing, and each is a small, separate, reviewable change.

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

`process.stem_focus` / `stem_focus_bucket` don't exist in any current
`settings.json`. First load after upgrade simply has them empty ("All"
until the user picks something), which is a one-time no-op, not a
regression — no different from a fresh install.

## Testing

Stdlib unittest, no network, no GTK (all pure functions):

- `canonical_stem_name` / `stem_display_label` — one case per newly curated
  entry, added incrementally as entries are confirmed.
- New anchoring logic — match-primary, match-secondary, no-match-falls-back-
  to-All, focus-survives-an-irrelevant-model-switch, and the confidence
  downgrade (guessed karaoke on either side → plain-name comparison, never a
  bucket comparison).
- `is_karaoke_curated` — curated-metadata true/false, and absence of
  metadata (falls to `False`, distinct from `resolve_is_karaoke`'s guess).
- `scripts/stem_semantics_audit.py` gets the same lightweight CLI tests as
  `model_probe.py` (arg parsing, JSON output shape) — its *findings* are for
  human review, not asserted in CI.

## Out of scope

- Isolating VR from MDX's shared `is_primary_stem_only`/`secondary_stem_only`
  keys. Explicitly rejected earlier in this design's review — it's faithful
  upstream-parity behavior, not a bug, and not what was reported.
- Building a general "pair type" taxonomy (dereverb/denoise/karaoke/vocals as
  formal categories). The bucket/canonical-name comparison never needs to
  know what *kind* of pair it's looking at, only whether two stem identities
  match.
- Adding a name-guessing fallback for `is_bv_model` (it stays curated-only,
  matching today's behavior — extending it to guess would reintroduce the
  exact reliability problem this design works around for `is_karaoke`).
- Populating the curated display table as part of this spec. Entries are
  proposed and confirmed individually during implementation.
- Retroactively re-casing any stem that already displays correctly.
