# Ensemble Stem Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ensemble member eligibility and output combining share one semantic rule for "what stem does this model produce", fixing 8 wrongly-excluded models and stopping karaoke models from silently contaminating clean-instrumental ensembles.

**Architecture:** One pure resolver, `ensemble_stem_bucket(stem, *, stem_count, is_karaoke, is_bv)`, in `core/model_stem_semantics.py`. Selection (`core/model_data.py`), combining (`core/model_stem_semantics.export_stem_label`) and the catalogue side (the naming/scores plan) all route through it. Karaoke/BV models get their own `ENSEMBLE_MAIN_STEM` pair.

**Tech Stack:** Python 3, stdlib `unittest`, GTK4/libadwaita (UI layer only).

**Spec:** [docs/superpowers/specs/2026-07-31-ensemble-stem-semantics-design.md](../specs/2026-07-31-ensemble-stem-semantics-design.md)

## Global Constraints

- **Bucket values must be filename-safe: no parentheses.** `format_stem_basename` renders `{track_base} ({stem})`, `sanitize_filename_component` preserves parens, and `get_files_to_ensemble_for_stem`'s regex is `\(([^()]+)\)\.(?:wav|flac|mp3)$`. A bucket containing parens produces nested parens, the regex fails to match, members are silently not collected, and the ensemble emits single-member output. Task 1 Step 6 tests exactly this.
- **`core/export_naming.py` and ensemble collection change together.** Per the root CLAUDE.md, `Ensembler.get_files_to_ensemble` collects by filename prefix/suffix. A naming tweak that looks cosmetic will make ensembles silently produce single-member output.
- **No tkinter anywhere.** `core/` stays framework-agnostic.
- **Heavy imports stay lazy** — no `torch`, `onnxruntime` or `engines` imports from anything touched here.
- **Keep the `Seperate*` misspelling** and the verbatim strings in `bundled/error_handling.py`.
- **Adding to `ENSEMBLE_MAIN_STEM` must stay additive.** `settings.ensemble.main_stem` is a plain persisted string; existing stored values must keep resolving.
- Tests are **stdlib unittest** via `.venv/bin/python -m unittest`. No pytest.
- Type checking is pyright `basic`. Run `.venv/bin/python -m pyright` before the final commit.
- Search with `rg`, never `grep`.
- Never run unscoped `git checkout -- .`, `git restore .`, `git reset --hard`, `git stash` or `git clean` — this tree carries long-lived uncommitted edits under `models/*/model_data/`. Stage explicit paths only; never `git add -A`.

## Relationship to the naming/scores plan

`ensemble_stem_bucket` is shared. **Task 1 of this plan must land before Task 2 and Task 6 of [2026-07-31-model-catalog-naming-and-scores.md](2026-07-31-model-catalog-naming-and-scores.md).** Task 7 here applies the two required edits to that plan's call sites. If that plan is already merged, Task 7 is still correct — it edits the shipped code rather than the document.

## File Structure

| File | Responsibility |
| --- | --- |
| `bundled/constants/stems.py` (modify) | Filename-safe bucket tag constants. |
| `bundled/constants/process.py` (modify) | `KARAOKE_PAIR`, added to `ENSEMBLE_MAIN_STEM`. |
| `core/model_stem_semantics.py` (modify) | `ensemble_stem_bucket`, `ensemble_pair_buckets`; `export_stem_label` routes through them. |
| `core/model_data.py` (modify) | `matches_stem` compares buckets. |
| `core/ensemble_presets.py` (modify) | Skip an unresolvable member instead of raising. |

---

### Task 1: The stem bucket resolver

**Files:**
- Modify: `bundled/constants/stems.py` (append after line 53)
- Modify: `core/model_stem_semantics.py` (append after `canonical_ensemble_stem_tag`, line 741)
- Create: `tests/test_ensemble_stem_buckets.py`

**Interfaces:**
- Consumes: existing stem constants from `bundled/constants/stems.py`.
- Produces:
  - `ensemble_stem_bucket(stem: str, *, stem_count: int = 2, is_karaoke: bool = False, is_bv: bool = False) -> str`
  - Bucket constants `BUCKET_VOCALS`, `BUCKET_INSTRUMENTAL`, `BUCKET_OTHER`, `BUCKET_DRUMS`, `BUCKET_BASS`, `BUCKET_GUITAR`, `BUCKET_PIANO`, `BUCKET_LEAD_VOCALS`, `BUCKET_BV_VOCALS`, `BUCKET_INST_WITH_BV`, `BUCKET_INST_WITH_LEAD`, `BUCKET_UNKNOWN`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ensemble_stem_buckets.py`:

```python
"""One semantic rule for 'what stem does this model produce'."""

import re
import unittest

from core.export_naming import format_stem_basename
from core.model_stem_semantics import (
    BUCKET_BASS,
    BUCKET_BV_VOCALS,
    BUCKET_DRUMS,
    BUCKET_INST_WITH_BV,
    BUCKET_INST_WITH_LEAD,
    BUCKET_INSTRUMENTAL,
    BUCKET_LEAD_VOCALS,
    BUCKET_OTHER,
    BUCKET_UNKNOWN,
    BUCKET_VOCALS,
    ensemble_stem_bucket,
)

_ALL_BUCKETS = (
    BUCKET_VOCALS, BUCKET_INSTRUMENTAL, BUCKET_OTHER, BUCKET_DRUMS, BUCKET_BASS,
    BUCKET_LEAD_VOCALS, BUCKET_BV_VOCALS, BUCKET_INST_WITH_BV, BUCKET_INST_WITH_LEAD,
)


class OtherOverloadTests(unittest.TestCase):
    """'other' means three different things depending on context."""

    def test_two_stem_other_is_instrumental(self) -> None:
        self.assertEqual(ensemble_stem_bucket("other", stem_count=1), BUCKET_INSTRUMENTAL)
        self.assertEqual(ensemble_stem_bucket("other", stem_count=2), BUCKET_INSTRUMENTAL)

    def test_four_stem_other_is_its_own_stem(self) -> None:
        self.assertEqual(ensemble_stem_bucket("other", stem_count=4), BUCKET_OTHER)

    def test_karaoke_instrumental_is_its_own_bucket(self) -> None:
        self.assertEqual(
            ensemble_stem_bucket("Instrumental", stem_count=2, is_karaoke=True),
            BUCKET_INST_WITH_BV,
        )
        self.assertEqual(
            ensemble_stem_bucket("other", stem_count=2, is_karaoke=True),
            BUCKET_INST_WITH_BV,
        )


class KaraokeAndBvTests(unittest.TestCase):
    def test_karaoke_vocals_is_lead_vocals(self) -> None:
        self.assertEqual(
            ensemble_stem_bucket("Vocals", stem_count=1, is_karaoke=True), BUCKET_LEAD_VOCALS
        )

    def test_bv_model_mirrors_karaoke(self) -> None:
        self.assertEqual(
            ensemble_stem_bucket("Vocals", stem_count=1, is_bv=True), BUCKET_BV_VOCALS
        )
        self.assertEqual(
            ensemble_stem_bucket("Instrumental", stem_count=2, is_bv=True), BUCKET_INST_WITH_LEAD
        )


class CaseAndAliasTests(unittest.TestCase):
    def test_case_variants_fold(self) -> None:
        for raw in ("vocals", "Vocals", "VOCALS", "Vocal", "voc"):
            with self.subTest(raw=raw):
                self.assertEqual(ensemble_stem_bucket(raw, stem_count=1), BUCKET_VOCALS)

    def test_instrument_alias_is_admitted(self) -> None:
        # bs_inst_hyperace2_unwa declares its stem as 'instrument'.
        self.assertEqual(ensemble_stem_bucket("instrument", stem_count=1), BUCKET_INSTRUMENTAL)

    def test_four_stem_musdb_names(self) -> None:
        self.assertEqual(ensemble_stem_bucket("drums", stem_count=4), BUCKET_DRUMS)
        self.assertEqual(ensemble_stem_bucket("bass", stem_count=4), BUCKET_BASS)
        self.assertEqual(ensemble_stem_bucket("vocals", stem_count=4), BUCKET_VOCALS)

    def test_unknown_vocabulary_is_unknown(self) -> None:
        # Phantom Centre. Must never land in Vocals/Instrumental.
        self.assertEqual(ensemble_stem_bucket("Similarity", stem_count=1), BUCKET_UNKNOWN)
        self.assertEqual(ensemble_stem_bucket("Sfx", stem_count=1), BUCKET_UNKNOWN)

    def test_empty_is_unknown(self) -> None:
        self.assertEqual(ensemble_stem_bucket("", stem_count=1), BUCKET_UNKNOWN)


class IdentityCodeTests(unittest.TestCase):
    """Splitter identity codes name the product, so flags must not override."""

    def test_lead_only_resolves_without_the_karaoke_flag(self) -> None:
        # A vocal splitter writes 'lead_only' regardless of the parent model's
        # own flags — the flags describe the model, the code describes the stem.
        self.assertEqual(ensemble_stem_bucket("lead_only", stem_count=2), BUCKET_LEAD_VOCALS)
        self.assertEqual(ensemble_stem_bucket("Lead Vocals", stem_count=2), BUCKET_LEAD_VOCALS)

    def test_backing_only_resolves_without_the_bv_flag(self) -> None:
        self.assertEqual(ensemble_stem_bucket("backing_only", stem_count=2), BUCKET_BV_VOCALS)
        self.assertEqual(ensemble_stem_bucket("Backing Vocals", stem_count=2), BUCKET_BV_VOCALS)

    def test_identity_code_is_not_folded_into_plain_vocals(self) -> None:
        self.assertNotEqual(ensemble_stem_bucket("lead_only", stem_count=2), BUCKET_VOCALS)


class FilenameSafetyTests(unittest.TestCase):
    """A bucket with parentheses silently breaks ensemble collection."""

    #: Verbatim from core/job_runner.py:1315.
    COLLECT_RE = re.compile(r"\(([^()]+)\)\.(?:wav|flac|mp3)$", re.IGNORECASE)

    def test_no_bucket_contains_parentheses(self) -> None:
        for bucket in _ALL_BUCKETS:
            with self.subTest(bucket=bucket):
                self.assertNotIn("(", bucket)
                self.assertNotIn(")", bucket)

    def test_every_bucket_round_trips_through_the_collection_regex(self) -> None:
        for bucket in _ALL_BUCKETS:
            with self.subTest(bucket=bucket):
                name = format_stem_basename("Song Model", bucket) + ".wav"
                match = self.COLLECT_RE.search(name)
                self.assertIsNotNone(match, f"{name!r} would not be collected")
                assert match is not None
                self.assertEqual(match.group(1), bucket)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_ensemble_stem_buckets -v`
Expected: FAIL with `ImportError: cannot import name 'BUCKET_BASS' from 'core.model_stem_semantics'`

- [ ] **Step 3: Add the filename-safe tag constants**

In `bundled/constants/stems.py`, after `INST_WITH_BACKING_VOCALS_STEM` (line 53):

```python
# Filename-safe ensemble bucket tags. These are written into export filenames
# as ``({tag})``, so they must contain no parentheses: the ensemble collection
# regex in core/job_runner.py is ``\(([^()]+)\)\.(wav|flac|mp3)$`` and rejects
# nested parens. The human-readable labels above stay for UI display only.
INST_WITH_BACKING_VOCALS_TAG = 'Instrumental_WithBackingVocals'
INST_WITH_LEAD_VOCALS_TAG = 'Instrumental_WithLeadVocals'
LEAD_VOCALS_TAG = 'Lead_Vocals'
BACKING_VOCALS_TAG = 'Backing_Vocals'
```

- [ ] **Step 4: Write the resolver**

In `core/model_stem_semantics.py`, after `canonical_ensemble_stem_tag` (line 741). Add the four new tags to the existing import from `bundled.constants` first.

```python
BUCKET_VOCALS = VOCAL_STEM
BUCKET_INSTRUMENTAL = INST_STEM
BUCKET_OTHER = OTHER_STEM
BUCKET_DRUMS = DRUM_STEM
BUCKET_BASS = BASS_STEM
BUCKET_GUITAR = GUITAR_STEM
BUCKET_PIANO = PIANO_STEM
BUCKET_LEAD_VOCALS = LEAD_VOCALS_TAG
BUCKET_BV_VOCALS = BACKING_VOCALS_TAG
BUCKET_INST_WITH_BV = INST_WITH_BACKING_VOCALS_TAG
BUCKET_INST_WITH_LEAD = INST_WITH_LEAD_VOCALS_TAG
BUCKET_UNKNOWN = "Unknown"

#: Splitter identity codes and their human labels. These already name a
#: karaoke/BV product, so they resolve regardless of the model's own flags —
#: the flags describe the *model*, these describe the *stem*.
_IDENTITY_BUCKETS = {
    "lead_only": BUCKET_LEAD_VOCALS,
    "lead vocals": BUCKET_LEAD_VOCALS,
    "backing_only": BUCKET_BV_VOCALS,
    "backing vocals": BUCKET_BV_VOCALS,
}

#: Stem tokens that name the vocal target, in any casing authors have used.
_VOCAL_TOKENS = frozenset({"vocals", "vocal", "voc"})

#: Stem tokens that name the instrumental side. ``other`` is context-dependent
#: and is resolved by stem count, not by this set alone.
_INSTRUMENTAL_TOKENS = frozenset({"instrumental", "inst", "instrument"})

#: Non-vocal MUSDB stems, safe to fold on name alone.
_SIMPLE_STEM_TOKENS = {
    "drums": BUCKET_DRUMS,
    "bass": BUCKET_BASS,
    "guitar": BUCKET_GUITAR,
    "piano": BUCKET_PIANO,
}


def ensemble_stem_bucket(
    stem: str,
    *,
    stem_count: int = 2,
    is_karaoke: bool = False,
    is_bv: bool = False,
) -> str:
    """Return the ensemble bucket a model's stem belongs to.

    Three inputs, not one, because ``other`` is overloaded: it is the
    instrumental complement for a 2-stem model, a real MUSDB residual for a
    4-stem model, and instrumental-plus-backing-vocals for a karaoke model.

    Unrecognised stems return :data:`BUCKET_UNKNOWN`, which never matches a
    pair — that is what keeps specialty models (Phantom Centre's
    ``Similarity``) out of ``Vocals/Instrumental``.
    """
    token = str(stem or "").strip().casefold()
    if not token:
        return BUCKET_UNKNOWN

    # Identity codes name the product, not the model, so they win over flags.
    identity = _IDENTITY_BUCKETS.get(token)
    if identity is not None:
        return identity

    is_vocal = token in _VOCAL_TOKENS
    # ``other`` counts as instrumental only for 2-stem (or target-instrument)
    # models, where it is the complement of vocals rather than a MUSDB stem.
    is_instrumental = token in _INSTRUMENTAL_TOKENS or (
        token == "other" and stem_count <= 2
    )

    if is_karaoke:
        if is_vocal:
            return BUCKET_LEAD_VOCALS
        if is_instrumental:
            return BUCKET_INST_WITH_BV
    if is_bv:
        if is_vocal:
            return BUCKET_BV_VOCALS
        if is_instrumental:
            return BUCKET_INST_WITH_LEAD

    if is_vocal:
        return BUCKET_VOCALS
    if is_instrumental:
        return BUCKET_INSTRUMENTAL
    if token == "other":
        return BUCKET_OTHER
    simple = _SIMPLE_STEM_TOKENS.get(token)
    if simple is not None:
        return simple
    return BUCKET_UNKNOWN
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_ensemble_stem_buckets -v`
Expected: PASS across `OtherOverloadTests`, `KaraokeAndBvTests`, `CaseAndAliasTests`, `IdentityCodeTests` and `FilenameSafetyTests`

- [ ] **Step 6: Verify the filename-safety guard actually guards**

Temporarily set `INST_WITH_BACKING_VOCALS_TAG = 'Instrumental (With Backing Vocals)'` in `bundled/constants/stems.py`, then:

Run: `.venv/bin/python -m unittest tests.test_ensemble_stem_buckets.FilenameSafetyTests -v`
Expected: **FAIL** on both tests — this proves the guard catches the exact mistake that would silently break ensemble collection. Revert the constant and re-run to confirm PASS.

- [ ] **Step 7: Commit**

```bash
git add bundled/constants/stems.py core/model_stem_semantics.py tests/test_ensemble_stem_buckets.py
git commit -m "feat(core): add ensemble stem bucket resolver"
```

---

### Task 2: Karaoke stem pair

**Files:**
- Modify: `bundled/constants/process.py:66-78`
- Modify: `core/model_stem_semantics.py` (append after `ensemble_stem_bucket`)
- Create: `tests/test_ensemble_pair_buckets.py`

**Interfaces:**
- Consumes: bucket constants from Task 1.
- Produces:
  - `KARAOKE_PAIR: str` in `bundled.constants`
  - `ensemble_pair_buckets(main_stem: str) -> Tuple[str, str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ensemble_pair_buckets.py`:

```python
"""Mapping an ENSEMBLE_MAIN_STEM pair string to its two buckets."""

import unittest

from bundled.constants import (
    BASS_PAIR,
    CHOOSE_STEM_PAIR,
    ENSEMBLE_MAIN_STEM,
    FOUR_STEM_ENSEMBLE,
    KARAOKE_PAIR,
    MULTI_STEM_ENSEMBLE,
    OTHER_PAIR,
    VOCAL_PAIR,
)
from core.model_stem_semantics import (
    BUCKET_BASS,
    BUCKET_INST_WITH_BV,
    BUCKET_INSTRUMENTAL,
    BUCKET_LEAD_VOCALS,
    BUCKET_OTHER,
    BUCKET_UNKNOWN,
    BUCKET_VOCALS,
    ensemble_pair_buckets,
)


class PairBucketTests(unittest.TestCase):
    def test_vocal_pair(self) -> None:
        self.assertEqual(ensemble_pair_buckets(VOCAL_PAIR), (BUCKET_VOCALS, BUCKET_INSTRUMENTAL))

    def test_karaoke_pair(self) -> None:
        self.assertEqual(
            ensemble_pair_buckets(KARAOKE_PAIR), (BUCKET_LEAD_VOCALS, BUCKET_INST_WITH_BV)
        )

    def test_other_pair_keeps_other_as_a_real_stem(self) -> None:
        # Regression: resolving this through ensemble_stem_bucket would give
        # BUCKET_INSTRUMENTAL, because a 1-stem 'other' is the instrumental
        # complement. A pair is a request, not a model description.
        self.assertEqual(ensemble_pair_buckets(OTHER_PAIR), (BUCKET_OTHER, BUCKET_UNKNOWN))

    def test_bass_pair(self) -> None:
        primary, _secondary = ensemble_pair_buckets(BASS_PAIR)
        self.assertEqual(primary, BUCKET_BASS)

    def test_complement_half_is_unknown_not_a_bucket(self) -> None:
        # 'No Other' / 'No Bass' are derived by inversion, never trained, so
        # they are not a bucket any model can match. Callers discard UNKNOWN.
        for pair in (OTHER_PAIR, BASS_PAIR):
            with self.subTest(pair=pair):
                self.assertEqual(ensemble_pair_buckets(pair)[1], BUCKET_UNKNOWN)

    def test_non_pair_values_are_unknown(self) -> None:
        for value in (CHOOSE_STEM_PAIR, FOUR_STEM_ENSEMBLE, MULTI_STEM_ENSEMBLE, ""):
            with self.subTest(value=value):
                self.assertEqual(ensemble_pair_buckets(value), (BUCKET_UNKNOWN, BUCKET_UNKNOWN))


class MainStemListTests(unittest.TestCase):
    def test_karaoke_pair_is_offered(self) -> None:
        self.assertIn(KARAOKE_PAIR, ENSEMBLE_MAIN_STEM)

    def test_existing_pairs_are_preserved(self) -> None:
        # Additive only: stored settings.ensemble.main_stem must keep resolving.
        for value in (CHOOSE_STEM_PAIR, VOCAL_PAIR, OTHER_PAIR, BASS_PAIR,
                      FOUR_STEM_ENSEMBLE, MULTI_STEM_ENSEMBLE):
            with self.subTest(value=value):
                self.assertIn(value, ENSEMBLE_MAIN_STEM)

    def test_pair_splits_on_a_single_slash(self) -> None:
        # ui/ensemble/window.py:563 does main_stem.split("/", 1).
        primary, secondary = KARAOKE_PAIR.split("/", 1)
        self.assertTrue(primary)
        self.assertTrue(secondary)
        self.assertNotIn("/", secondary)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_ensemble_pair_buckets -v`
Expected: FAIL with `ImportError: cannot import name 'KARAOKE_PAIR' from 'bundled.constants'`

- [ ] **Step 3: Add the pair constant**

In `bundled/constants/process.py`, extend the import on line 2 with `INST_WITH_BACKING_VOCALS_STEM` and `LEAD_VOCAL_STEM_LABEL`, then after `BASS_PAIR` (line 72):

```python
#: Karaoke / BV models separate lead vocals from instrumental-plus-backing
#: vocals, which is not the same quantity as a clean instrumental. They get
#: their own pair so they ensemble with each other instead of contaminating
#: Vocals/Instrumental. Display labels here; buckets come from
#: ``ensemble_pair_buckets``.
KARAOKE_PAIR = f'{LEAD_VOCAL_STEM_LABEL}/{INST_WITH_BACKING_VOCALS_STEM}'
```

Then extend `ENSEMBLE_MAIN_STEM` (line 78), inserting after `VOCAL_PAIR`:

```python
ENSEMBLE_MAIN_STEM = (CHOOSE_STEM_PAIR, VOCAL_PAIR, KARAOKE_PAIR, OTHER_PAIR, DRUM_PAIR, BASS_PAIR, FOUR_STEM_ENSEMBLE, MULTI_STEM_ENSEMBLE)
```

- [ ] **Step 4: Write `ensemble_pair_buckets`**

In `core/model_stem_semantics.py`, after `ensemble_stem_bucket`:

```python
def ensemble_pair_buckets(main_stem: str) -> Tuple[str, str]:
    """Return the ``(primary, secondary)`` buckets for an ensemble pair string.

    An explicit table, **not** a call to :func:`ensemble_stem_bucket`. A pair is
    a user's *request*, not a description of a model's output, and the two
    disagree: ``Other/No Other`` asks for the MUSDB residual, but
    ``ensemble_stem_bucket("Other", stem_count=1)`` reads a 1-stem ``other`` as
    the instrumental complement. Resolving pairs through the model resolver
    would silently turn the Other pair into an Instrumental request.

    A table also keeps the parenthesized ``Instrumental (With Backing Vocals)``
    display label out of the stem alias table.

    Complement pairs (``No Other``, ``No Drums``, ``No Bass``) have one
    meaningful bucket: the complement is derived by inversion, never trained,
    so the secondary is :data:`BUCKET_UNKNOWN` and callers discard it.

    Non-pair values (Choose Stem Pair, 4 Stem, Multi-stem) return
    ``(BUCKET_UNKNOWN, BUCKET_UNKNOWN)``; those modes do not filter by a pair.
    """
    from bundled.constants import BASS_PAIR, DRUM_PAIR, KARAOKE_PAIR, OTHER_PAIR, VOCAL_PAIR

    table = {
        VOCAL_PAIR: (BUCKET_VOCALS, BUCKET_INSTRUMENTAL),
        KARAOKE_PAIR: (BUCKET_LEAD_VOCALS, BUCKET_INST_WITH_BV),
        OTHER_PAIR: (BUCKET_OTHER, BUCKET_UNKNOWN),
        DRUM_PAIR: (BUCKET_DRUMS, BUCKET_UNKNOWN),
        BASS_PAIR: (BUCKET_BASS, BUCKET_UNKNOWN),
    }
    return table.get(str(main_stem or "").strip(), (BUCKET_UNKNOWN, BUCKET_UNKNOWN))
```

Add `Tuple` to the module's `typing` import if absent.

**Why this is a table and not a resolver call:** `ensemble_stem_bucket` is
deliberately context-sensitive on `stem_count`, and a pair string carries no
stem count. Any value you pick is wrong for some pair. Verify the trap is
closed:

```bash
.venv/bin/python -c "
from core.model_stem_semantics import ensemble_stem_bucket, ensemble_pair_buckets, BUCKET_OTHER
from bundled.constants import OTHER_PAIR
print('resolver on the pair half:', ensemble_stem_bucket('Other', stem_count=1))
print('pair table:             ', ensemble_pair_buckets(OTHER_PAIR))
assert ensemble_pair_buckets(OTHER_PAIR)[0] == BUCKET_OTHER
print('OK')
"
```

Expected: the resolver prints `Instrumental` (correct for a 1-stem model), the
table prints `('Other', 'Unknown')` (correct for the pair), then `OK`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_ensemble_pair_buckets tests.test_ensemble_stem_buckets -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add bundled/constants/process.py core/model_stem_semantics.py tests/test_ensemble_pair_buckets.py
git commit -m "feat(core): give karaoke models their own ensemble stem pair"
```

---

### Task 3: Selection compares buckets

**Files:**
- Modify: `core/model_data.py:223-245` (`model_list`), `:256-271` (`ensemble_model_list`)
- Create: `tests/test_ensemble_model_eligibility.py`

**Interfaces:**
- Consumes: `ensemble_stem_bucket`, `ensemble_pair_buckets` (Tasks 1-2).
- Produces: `model_list(settings, primary_stem, secondary_stem, is_4_stem_check=False, is_no_demucs=False, *, wanted_buckets: Optional[AbstractSet[str]] = None) -> List[str]` — one added keyword-only parameter. `ensemble_model_list` keeps its signature.

**Why the extra parameter.** `ensemble_model_list` must resolve the pair through
`ensemble_pair_buckets`, not by bucketing each half: `ensemble_stem_bucket("Other",
stem_count=1)` returns `Instrumental`, so re-deriving buckets inside `model_list`
would turn the `Other/No Other` pair into an Instrumental request. Passing the
resolved buckets down is the only correct wiring. `rg` confirms the only other
production caller is `scripts/model_sweep.py:68`, which passes
`VOCAL_STEM, INST_STEM` — unambiguous, so it keeps the string path.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ensemble_model_eligibility.py`:

```python
"""Ensemble eligibility resolves by bucket, not by raw stem string."""

import unittest
import unittest.mock

from bundled.constants import BASS_PAIR, KARAOKE_PAIR, OTHER_PAIR, VOCAL_PAIR
from core.model_data import ModelRepository


class _FakeModel:
    """Stands in for a dry-check ModelConfig without hashing a checkpoint.

    Carries every attribute ``model_list`` reads, so these tests exercise the
    real method instead of re-asserting the resolver from Task 1.
    """

    def __init__(self, tag, primary, stems, *, is_karaoke=False, is_bv=False,
                 demucs_sources=(), demucs_stem_count=0):
        self.model_and_process_tag = tag
        self.primary_stem = primary
        self.mdx_model_stems = list(stems)
        self.mdx_stem_count = len(stems) or 1
        self.is_karaoke = is_karaoke
        self.is_bv_model = is_bv
        self.demucs_source_list = list(demucs_sources)
        self.demucs_stem_count = demucs_stem_count


def _eligible(models, main_stem):
    """Run the real ``ensemble_model_list`` over fake ``stem_check`` output."""
    with unittest.mock.patch.object(ModelRepository, "stem_check", return_value=models):
        return ModelRepository().ensemble_model_list(None, main_stem)


class PreviouslyExcludedModelTests(unittest.TestCase):
    """The models measured as wrongly excluded from Vocals/Instrumental."""

    def test_lowercase_vocals_becomes_eligible(self) -> None:
        # mel_band_roformer_kim_ft2_bleedless_unwa
        models = [_FakeModel("MDX-Net: kim_ft2", "vocals", ["vocals"])]
        self.assertEqual(_eligible(models, VOCAL_PAIR), ["MDX-Net: kim_ft2"])

    def test_two_stem_other_becomes_eligible(self) -> None:
        # mbr_inst2_unwa, melband_roformer_inst_v1e_plus, Resurrection
        models = [_FakeModel("MDX-Net: inst2_unwa", "other", ["other"])]
        self.assertEqual(_eligible(models, VOCAL_PAIR), ["MDX-Net: inst2_unwa"])

    def test_instrument_variant_becomes_eligible(self) -> None:
        # bs_inst_hyperace2_unwa
        models = [_FakeModel("MDX-Net: hyperace2", "instrument", ["instrument"])]
        self.assertEqual(_eligible(models, VOCAL_PAIR), ["MDX-Net: hyperace2"])

    def test_four_stem_lowercase_vocals_becomes_eligible(self) -> None:
        # huge_scnet_4stems_bleedless / _fullness
        models = [_FakeModel("MDX-Net: scnet4", "vocals",
                             ["drums", "bass", "other", "vocals"])]
        self.assertEqual(_eligible(models, VOCAL_PAIR), ["MDX-Net: scnet4"])

    def test_phantom_centre_stays_excluded(self) -> None:
        # Correct today, but by accident. Now it is by rule.
        models = [_FakeModel("MDX-Net: phantom", "Similarity", ["Similarity"])]
        self.assertEqual(_eligible(models, VOCAL_PAIR), [])


class OtherPairTests(unittest.TestCase):
    """'other' must stay a real stem for the Other pair."""

    def test_four_stem_other_matches_the_other_pair(self) -> None:
        models = [_FakeModel("MDX-Net: scnet4", "other",
                             ["drums", "bass", "other", "vocals"])]
        self.assertEqual(_eligible(models, OTHER_PAIR), ["MDX-Net: scnet4"])

    def test_two_stem_other_does_not_match_the_other_pair(self) -> None:
        # This model's 'other' is an instrumental, not a MUSDB residual.
        models = [_FakeModel("MDX-Net: inst2_unwa", "other", ["other"])]
        self.assertEqual(_eligible(models, OTHER_PAIR), [])


class KaraokeSeparationTests(unittest.TestCase):
    def test_karaoke_leaves_vocal_instrumental(self) -> None:
        models = [_FakeModel("MDX-Net: kara", "Vocals", ["Vocals"], is_karaoke=True)]
        self.assertEqual(_eligible(models, VOCAL_PAIR), [])

    def test_karaoke_appears_under_its_own_pair(self) -> None:
        models = [_FakeModel("MDX-Net: kara", "Vocals", ["Vocals"], is_karaoke=True)]
        self.assertEqual(_eligible(models, KARAOKE_PAIR), ["MDX-Net: kara"])

    def test_plain_model_does_not_appear_under_the_karaoke_pair(self) -> None:
        models = [_FakeModel("MDX-Net: inst_hq4", "Instrumental", ["Instrumental"])]
        self.assertEqual(_eligible(models, KARAOKE_PAIR), [])

    def test_bv_model_also_leaves_vocal_instrumental(self) -> None:
        models = [_FakeModel("MDX-Net: bv", "Vocals", ["Vocals"], is_bv=True)]
        self.assertEqual(_eligible(models, VOCAL_PAIR), [])


class UnchangedBehaviourTests(unittest.TestCase):
    def test_demucs_source_list_still_matches(self) -> None:
        models = [_FakeModel("Demucs: htdemucs", "Vocals", [],
                             demucs_sources=["drums", "bass", "other", "vocals"],
                             demucs_stem_count=4)]
        self.assertEqual(_eligible(models, BASS_PAIR), ["Demucs: htdemucs"])

    def test_four_stem_ensemble_keeps_only_four_source_models(self) -> None:
        from bundled.constants import FOUR_STEM_ENSEMBLE

        models = [
            _FakeModel("MDX-Net: scnet4", "vocals", ["drums", "bass", "other", "vocals"]),
            _FakeModel("MDX-Net: two_stem", "Vocals", ["Vocals", "Instrumental"]),
        ]
        self.assertEqual(_eligible(models, FOUR_STEM_ENSEMBLE), ["MDX-Net: scnet4"])

    def test_multi_stem_ensemble_keeps_everything(self) -> None:
        from bundled.constants import MULTI_STEM_ENSEMBLE

        models = [
            _FakeModel("MDX-Net: phantom", "Similarity", ["Similarity"]),
            _FakeModel("MDX-Net: kara", "Vocals", ["Vocals"], is_karaoke=True),
        ]
        self.assertEqual(len(_eligible(models, MULTI_STEM_ENSEMBLE)), 2)

    def test_choose_stem_pair_returns_nothing(self) -> None:
        from bundled.constants import CHOOSE_STEM_PAIR

        models = [_FakeModel("MDX-Net: any", "Vocals", ["Vocals"])]
        self.assertEqual(_eligible(models, CHOOSE_STEM_PAIR), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_ensemble_model_eligibility -v`
Expected: FAIL. `test_lowercase_vocals_becomes_eligible`, `test_two_stem_other_becomes_eligible`, `test_instrument_variant_becomes_eligible`, `test_four_stem_lowercase_vocals_becomes_eligible` and both karaoke-separation tests fail; `test_phantom_centre_stays_excluded` and the `UnchangedBehaviourTests` already pass and must keep passing.

- [ ] **Step 3: Route `model_list` through buckets**

In `core/model_data.py`, replace `model_list` (lines 223-245). This is a
minimal substitution — the branch structure of the original is preserved
exactly, with string equality swapped for bucket equality:

```python
    def model_list(
        self,
        settings: Settings,
        primary_stem: str,
        secondary_stem: str,
        is_4_stem_check: bool = False,
        is_no_demucs: bool = False,
        *,
        wanted_buckets: Optional[AbstractSet[str]] = None,
    ) -> List[str]:
        """Tk-free port of ``MainWindow.model_list`` (secondary-model filtering).

        Stem comparison goes through :func:`ensemble_stem_bucket` so yaml
        lowercase (``vocals``), the 2-stem ``other`` complement and the
        ``instrument`` variant resolve to the same bucket as the curated Title
        Case names, while karaoke models resolve to their own bucket instead of
        contaminating clean instrumentals.

        ``wanted_buckets`` lets :meth:`ensemble_model_list` supply buckets it
        resolved from the *pair* — necessary because a pair carries no stem
        count, so re-deriving buckets from the two halves here would read
        ``Other/No Other`` as an Instrumental request.
        """
        from .model_stem_semantics import BUCKET_UNKNOWN, ensemble_stem_bucket

        stem_check = self.stem_check(settings)
        if wanted_buckets is None:
            wanted = {
                ensemble_stem_bucket(primary_stem, stem_count=1),
                ensemble_stem_bucket(secondary_stem, stem_count=1),
            }
        else:
            wanted = set(wanted_buckets)
        wanted.discard(BUCKET_UNKNOWN)

        def bucket_of(model: "ModelConfig", stem: str) -> str:
            return ensemble_stem_bucket(
                stem,
                stem_count=model.mdx_stem_count or 1,
                is_karaoke=bool(getattr(model, "is_karaoke", False)),
                is_bv=bool(getattr(model, "is_bv_model", False)),
            )

        def matches_stem(model: "ModelConfig") -> bool:
            if not wanted:
                return False
            primary_match = bucket_of(model, model.primary_stem) in wanted
            mdx_match = any(bucket_of(model, stem) in wanted for stem in model.mdx_model_stems)
            if is_no_demucs:
                return primary_match or (mdx_match and model.mdx_stem_count <= 2)
            return primary_match or mdx_match

        def demucs_match(model: "ModelConfig") -> bool:
            return any(
                ensemble_stem_bucket(stem, stem_count=4) in wanted
                for stem in model.demucs_source_list
            )

        result: List[str] = []
        for model in stem_check:
            if is_4_stem_check and (model.demucs_stem_count == 4 or model.mdx_stem_count == 4):
                result.append(model.model_and_process_tag)
            elif matches_stem(model) or (not is_no_demucs and demucs_match(model)):
                result.append(model.model_and_process_tag)
        return result
```

Add `AbstractSet` to the module's `typing` import.

- [ ] **Step 4: Resolve the pair in `ensemble_model_list`**

In `core/model_data.py`, replace the final line of `ensemble_model_list`
(line 271):

```python
        from .model_stem_semantics import ensemble_pair_buckets

        stems = ensemble_main_stem.partition("/")
        return self.model_list(
            settings,
            stems[0],
            stems[2],
            wanted_buckets=set(ensemble_pair_buckets(ensemble_main_stem)),
        )
```

The `CHOOSE_STEM_PAIR`, `MULTI_STEM_ENSEMBLE` and `FOUR_STEM_ENSEMBLE` branches
above it are unchanged.

- [ ] **Step 5: Run the test**

Run: `.venv/bin/python -m unittest tests.test_ensemble_model_eligibility -v`
Expected: PASS, 15 tests

- [ ] **Step 6: Verify against the real installed model set**

```bash
UVR_DISABLE_POLITREES=1 .venv/bin/python -c "
from core import Settings
from core.model_data import ModelRepository
from bundled.constants import VOCAL_PAIR, KARAOKE_PAIR
s = Settings.load(); repo = ModelRepository()
voc = set(repo.ensemble_model_list(s, VOCAL_PAIR))
kar = set(repo.ensemble_model_list(s, KARAOKE_PAIR))
want_in = ['mel_band_roformer_kim_ft2_bleedless_unwa', 'mbr_inst2_unwa',
           'melband_roformer_inst_v1e_plus', 'bs_inst_hyperace2_unwa',
           'model_BandSplit-Roformer_Resurrection_Instrumental_by-Unwa']
def has(sel, frag): return any(frag in t for t in sel)
print('Vocals/Instrumental:', len(voc), ' Karaoke pair:', len(kar))
for f in want_in:  print(('  OK   ' if has(voc,f) else '  MISS '), f)
print(('  OK   ' if not has(voc,'Phantom-Mid') else '  LEAK '), 'Phantom-Mid (should be excluded)')
print('karaoke pair members:', sorted(t.split(chr(58)+chr(32),1)[1][:44] for t in kar))
assert not (voc & kar), 'a model is in both pairs'
"
```

Expected: all five `OK`, Phantom Centre `OK`, six karaoke models under the
karaoke pair, no overlap.

- [ ] **Step 7: Run the affected suites**

Run: `.venv/bin/python -m unittest tests.test_ensemble_model_eligibility tests.test_karaoke_metadata tests.test_mdx_c_registry tests.test_ensemble_ui_helpers -v`
Expected: PASS. If `test_karaoke_metadata` asserts karaoke models appear under
`Vocals/Instrumental`, that assertion encoded the bug — move it to the karaoke
pair and say so in the commit message.

- [ ] **Step 8: Check the sweep script still resolves**

```bash
rg -n "model_list" scripts/model_sweep.py
.venv/bin/python -c "import ast,sys; ast.parse(open('scripts/model_sweep.py').read()); print('parses OK')"
```

`scripts/model_sweep.py:68` passes `VOCAL_STEM, INST_STEM` positionally and does
not use `wanted_buckets`, so it takes the string path and is unaffected. No edit
expected.

- [ ] **Step 9: Commit**

```bash
git add core/model_data.py tests/test_ensemble_model_eligibility.py
git commit -m "fix(core): resolve ensemble eligibility by stem bucket"
```


### Task 4: Combining uses the same buckets

**Files:**
- Modify: `core/model_stem_semantics.py:444-465` (`export_stem_label`), `_ENSEMBLE_STEM_PRESERVE` (line 688)
- Modify: `tests/test_model_stem_semantics.py` if present, else create `tests/test_export_stem_label.py`

**Interfaces:**
- Consumes: Task 1 buckets.
- Produces: `export_stem_label(model, stem, *, for_ensemble=False)` unchanged in signature; ensemble-mode return value now a bucket.

- [ ] **Step 1: Write the failing test**

Create `tests/test_export_stem_label.py`:

```python
"""Ensemble-mode export labels are buckets, so members group correctly."""

import unittest

from core.model_stem_semantics import (
    BUCKET_INST_WITH_BV,
    BUCKET_INSTRUMENTAL,
    BUCKET_LEAD_VOCALS,
    BUCKET_VOCALS,
    canonical_ensemble_stem_tag,
    export_stem_label,
)


class _FakeModel:
    def __init__(self, *, is_karaoke=False, is_bv=False, stem_count=2):
        self.is_karaoke = is_karaoke
        self.is_bv_model = is_bv
        self.mdx_stem_count = stem_count


class EnsembleExportLabelTests(unittest.TestCase):
    def test_plain_model_folds_case(self) -> None:
        model = _FakeModel()
        self.assertEqual(export_stem_label(model, "vocals", for_ensemble=True), BUCKET_VOCALS)
        self.assertEqual(
            export_stem_label(model, "other", for_ensemble=True), BUCKET_INSTRUMENTAL
        )

    def test_karaoke_model_gets_its_own_tags(self) -> None:
        model = _FakeModel(is_karaoke=True)
        self.assertEqual(
            export_stem_label(model, "Vocals", for_ensemble=True), BUCKET_LEAD_VOCALS
        )
        self.assertEqual(
            export_stem_label(model, "Instrumental", for_ensemble=True), BUCKET_INST_WITH_BV
        )

    def test_karaoke_does_not_land_in_clean_instrumental(self) -> None:
        karaoke = export_stem_label(_FakeModel(is_karaoke=True), "Instrumental", for_ensemble=True)
        clean = export_stem_label(_FakeModel(), "Instrumental", for_ensemble=True)
        self.assertNotEqual(karaoke, clean)


class BucketRoundTripTests(unittest.TestCase):
    """The combine stage re-reads tags from filenames; they must survive."""

    def test_new_tags_pass_through_canonical_ensemble_stem_tag(self) -> None:
        for bucket in (BUCKET_INST_WITH_BV, BUCKET_LEAD_VOCALS):
            with self.subTest(bucket=bucket):
                self.assertEqual(canonical_ensemble_stem_tag(bucket), bucket)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_export_stem_label -v`
Expected: FAIL — `export_stem_label(model, "other", for_ensemble=True)` returns `'Other'` (via `canonical_ensemble_stem_tag`) instead of `'Instrumental'`, and the karaoke cases return `'Instrumental'`.

- [ ] **Step 3: Route ensemble-mode labels through the bucket**

In `core/model_stem_semantics.py`, replace the `for_ensemble` branch of `export_stem_label` (lines 454-455):

```python
    if for_ensemble:
        return ensemble_stem_bucket(
            stem,
            stem_count=int(getattr(model, "mdx_stem_count", 2) or 2),
            is_karaoke=bool(getattr(model, "is_karaoke", False)),
            is_bv=bool(getattr(model, "is_bv_model", False)),
        )
```

Update the docstring: ensemble members now resolve through `ensemble_stem_bucket`, so yaml lowercase, the 2-stem `other` complement and karaoke instrumentals each land in the correct bucket.

- [ ] **Step 4: Preserve the new tags from folding**

In `core/model_stem_semantics.py`, add the four new tags to `_ENSEMBLE_STEM_PRESERVE` (line 688):

```python
_ENSEMBLE_STEM_PRESERVE = frozenset(
    {
        LEAD_VOCAL_STEM,
        BV_VOCAL_STEM,
        LEAD_VOCAL_STEM_LABEL,
        BV_VOCAL_STEM_LABEL,
        INST_WITH_LEAD_VOCALS_STEM,
        INST_WITH_BACKING_VOCALS_STEM,
        # Bucket tags written into ensemble member filenames. The combine stage
        # re-reads them from the filename, so they must survive unchanged.
        INST_WITH_BACKING_VOCALS_TAG,
        INST_WITH_LEAD_VOCALS_TAG,
        LEAD_VOCALS_TAG,
        BACKING_VOCALS_TAG,
    }
)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_export_stem_label tests.test_ensemble_stem_buckets tests.test_export_naming -v`
Expected: PASS. `test_export_naming` may not exist; drop it from the command if `ls tests/test_export_naming.py` fails.

- [ ] **Step 6: Commit**

```bash
git add core/model_stem_semantics.py tests/test_export_stem_label.py
git commit -m "fix(core): group ensemble members by stem bucket when combining"
```

---

### Task 5: Presets degrade gracefully

**Files:**
- Modify: `core/ensemble_presets.py:150-170`
- Modify: `tests/test_ensemble_presets.py` (create if absent)

**Interfaces:**
- Consumes: nothing new.
- Produces: no signature change; member resolution returns `None`/skips rather than raising.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ensemble_presets.py` (create the file with the standard header if it does not exist):

```python
class IneligibleMemberTests(unittest.TestCase):
    """A karaoke model saved into a Vocals/Instrumental preset is now ineligible.

    Loading such a preset must skip the member, not raise — users have saved
    presets from before karaoke models moved to their own pair.
    """

    def test_unresolvable_member_is_skipped_not_raised(self) -> None:
        from core.ensemble_presets import resolve_preset_member

        result = resolve_preset_member(
            "MDX-Net: A Model That No Longer Exists",
            available={"MDX-Net: Something Else": object()},
        )
        self.assertIsNone(result)

    def test_resolvable_member_still_resolves(self) -> None:
        from core.ensemble_presets import resolve_preset_member

        marker = object()
        result = resolve_preset_member(
            "MDX-Net: Something Else",
            available={"MDX-Net: Something Else": marker},
        )
        self.assertIs(result, marker)
```

Before writing this, read `core/ensemble_presets.py:150-170` and adapt the
function name and signature to what actually exists there — the resolution
helper may be named differently or be a method. Keep the two behaviours under
test: a missing member yields `None` and does not raise; a present member
resolves.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_ensemble_presets -v`
Expected: FAIL — either `ImportError` for the helper name, or an exception from the missing-member path.

- [ ] **Step 3: Make the missing-member path non-fatal**

In `core/ensemble_presets.py`, wrap the member lookup so an unmatched label logs and is skipped:

```python
    from .debug_log import debug

    if resolved is None:
        debug(
            "settings",
            f"ensemble preset member not available, skipping label={model_name!r}",
        )
        return None
```

Match the surrounding style and the actual control flow at lines 150-170.

- [ ] **Step 4: Run the test**

Run: `.venv/bin/python -m unittest tests.test_ensemble_presets -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/ensemble_presets.py tests/test_ensemble_presets.py
git commit -m "fix(core): skip ensemble preset members that are no longer eligible"
```

---

### Task 6: UI copy for the karaoke pair

**Files:**
- Modify: `ui/help_text.py` (`ENSEMBLE_MAIN_STEM_HELP`)
- Modify: `ui/ensemble/window.py:824-825` (`_is_multi_or_four_stem` — verify only)

**Interfaces:**
- Consumes: `KARAOKE_PAIR` (Task 2).
- Produces: no API change.

- [ ] **Step 1: Verify the new pair flows through the existing UI paths**

```bash
rg -n "ENSEMBLE_MAIN_STEM|_is_multi_or_four_stem|_ensemble_stem_pair" ui/ensemble/window.py
```

`_ensemble_stem_pair` (line 560) splits on `/` and `_is_multi_or_four_stem` (line 824) checks membership in `(FOUR_STEM_ENSEMBLE, MULTI_STEM_ENSEMBLE)`. `KARAOKE_PAIR` contains exactly one `/` and is neither of those, so it takes the normal dual-stem path and the Save-stems toggles label themselves from the split halves. Confirm by reading both; no edit expected.

- [ ] **Step 2: Update the help text**

In `ui/help_text.py`, extend `ENSEMBLE_MAIN_STEM_HELP` with a sentence:

```
Karaoke and backing-vocal models separate lead vocals from instrumental-with-backing-vocals, which is not the same as a clean instrumental — they have their own pair so their output is not mixed with standard vocal/instrumental models.
```

- [ ] **Step 3: Launch and check the page**

Run: `./run_uvr.sh`, open Ensemble, and confirm: the Main stem pair combo lists `Lead Vocals/Instrumental (With Backing Vocals)`; selecting it lists the six karaoke models and nothing else; selecting `Vocals/Instrumental` lists the previously-missing models and no karaoke models; the Save stems toggles label correctly for both.

- [ ] **Step 4: Commit**

```bash
git add ui/help_text.py
git commit -m "docs(ui): explain the karaoke ensemble stem pair"
```

---

### Task 7: Integrate with the naming/scores plan

**Files:**
- Modify: `core/model_scores.py` (`primary_sdr`, from that plan's Task 2)
- Modify: `ui/download_center.py` (`_row_score`, from that plan's Task 6)
- Modify: `tests/test_model_scores.py`

**Interfaces:**
- Consumes: `ensemble_stem_bucket` (Task 1); `EntryMeta.stems` / `.target_instrument` from the naming/scores plan.
- Produces: `primary_sdr(stem_scores, target_stem=None, *, stem_count=2)` — one added keyword-only parameter.

**Skip this task entirely if the naming/scores plan has not been implemented yet.** Apply it as edits to that plan's Task 2 and Task 6 code blocks instead, then execute it there.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_model_scores.py`:

```python
class SdrStemResolutionTests(unittest.TestCase):
    """Score keys are lowercase; model targets are whatever the yaml said."""

    def test_two_stem_other_target_reads_instrumental_score(self) -> None:
        # mbr_inst2_unwa declares target 'other', meaning instrumental.
        scores = {"vocals": 9.0, "instrumental": 16.0}
        result = model_scores.primary_sdr(scores, "other", stem_count=2)
        self.assertEqual(result, ("instrumental", 16.0))

    def test_four_stem_other_target_reads_other_score(self) -> None:
        scores = {"vocals": 9.0, "drums": 10.0, "bass": 12.0, "other": 8.0}
        result = model_scores.primary_sdr(scores, "other", stem_count=4)
        self.assertEqual(result, ("other", 8.0))

    def test_case_mismatch_still_resolves(self) -> None:
        scores = {"vocals": 11.5, "instrumental": 16.25}
        self.assertEqual(model_scores.primary_sdr(scores, "Vocals", stem_count=2), ("vocals", 11.5))

    def test_unknown_target_falls_back_to_highest(self) -> None:
        scores = {"vocals": 11.5, "instrumental": 16.25}
        self.assertEqual(
            model_scores.primary_sdr(scores, "Similarity", stem_count=1), ("instrumental", 16.25)
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_scores.SdrStemResolutionTests -v`
Expected: FAIL — `primary_sdr() got an unexpected keyword argument 'stem_count'`

- [ ] **Step 3: Resolve both sides through the bucket**

In `core/model_scores.py`, replace `primary_sdr`:

```python
def primary_sdr(
    stem_scores: Mapping[str, float],
    target_stem: Optional[str] = None,
    *,
    stem_count: int = 2,
) -> Optional[Tuple[str, float]]:
    """Return ``(stem, sdr)`` for the model's headline score.

    Both the model's target stem and the score-data keys go through
    :func:`ensemble_stem_bucket` before comparison. The score data keys stems
    lowercase (``vocals``, ``instrumental``, ``other``) while a model's target
    is whatever its yaml said, so a raw comparison reproduces the same class of
    mismatch that broke ensemble eligibility: a 2-stem model targeting ``other``
    would miss its ``instrumental`` score entirely.

    The returned stem is the **score-data key**, not the bucket, so callers
    render the name the benchmark actually used.
    """
    from .model_stem_semantics import BUCKET_UNKNOWN, ensemble_stem_bucket

    if not stem_scores:
        return None
    if target_stem:
        wanted = ensemble_stem_bucket(target_stem, stem_count=stem_count)
        if wanted != BUCKET_UNKNOWN:
            for stem, value in stem_scores.items():
                if ensemble_stem_bucket(stem, stem_count=stem_count) == wanted:
                    return (stem, value)
    stem, value = max(stem_scores.items(), key=lambda item: item[1])
    return (stem, value)
```

- [ ] **Step 4: Pass the stem count from the catalogue side**

In `ui/download_center.py`, in `_row_score`, replace the `primary_sdr` call:

```python
        if meta is not None:
            scored = primary_sdr(
                sdr_for_files(meta.files),
                meta.target_instrument,
                stem_count=len(meta.stems) or 2,
            )
            if scored is not None:
                return (scored[0], scored[1], stems_text)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_model_scores tests.test_download_center_search -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/model_scores.py ui/download_center.py tests/test_model_scores.py
git commit -m "fix(core): resolve SDR stem selection through the shared bucket rule"
```

---

### Task 8: Full verification

**Files:** none modified unless a failure is found.

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS. Skips acceptable only for GTK-guarded and network-guarded classes.

- [ ] **Step 2: Type check**

Run: `.venv/bin/python -m pyright`
Expected: 0 errors.

- [ ] **Step 3: Confirm both defects are fixed against real models**

```bash
UVR_DISABLE_POLITREES=1 .venv/bin/python -c "
from core import Settings
from core.model_data import ModelRepository
from bundled.constants import VOCAL_PAIR, KARAOKE_PAIR
s = Settings.load(); repo = ModelRepository()
voc = repo.ensemble_model_list(s, VOCAL_PAIR)
kar = repo.ensemble_model_list(s, KARAOKE_PAIR)
print(f'Vocals/Instrumental: {len(voc)}  (was 28)')
print(f'Karaoke pair:        {len(kar)}  (was 0 - pair did not exist)')
assert len(voc) > 28, 'previously-excluded models did not become eligible'
assert len(kar) >= 6, 'karaoke models did not move to their own pair'
assert not (set(voc) & set(kar)), 'overlap between pairs'
print('OK')
"
```

Expected: Vocals/Instrumental above 28, karaoke pair at least 6, no overlap, `OK`.

- [ ] **Step 4: End-to-end ensemble run**

Run a two-member `Vocals/Instrumental` ensemble on a short file, using one previously-excluded model (`mbr_inst2_unwa`) and one that always worked (`UVR-MDX-NET Inst HQ 4`):

```bash
.venv/bin/python -m core.cli separate <short.wav> -o /tmp/ens-check --method ensemble 2>&1 | tail -20
ls /tmp/ens-check
```

Expected: two stems written, not a single-member passthrough. **This is the check that catches a broken bucket tag** — if collection silently failed, the output is one member's audio rather than a combination. Compare file size against a single-model run of the same input.

- [ ] **Step 5: Final commit**

```bash
git add -u
git commit -m "test: verify ensemble stem semantics end to end"
```

---

## Self-Review Notes

**Spec coverage:** `ensemble_stem_bucket` with the three-way `other` split → Task 1; filename safety → Task 1 Steps 3 and 6; `KARAOKE_PAIR` and `ensemble_pair_buckets` → Task 2; `matches_stem` by bucket → Task 3; `export_stem_label` and `_ENSEMBLE_STEM_PRESERVE` → Task 4; preset migration → Task 5; UI copy → Task 6; naming/scores integration → Task 7; verification → Task 8.

**Interface consistency:** `ensemble_stem_bucket(stem, *, stem_count, is_karaoke, is_bv)` is defined in Task 1 and called with those exact keywords in Tasks 2, 3, 4 and 7. Bucket constants are defined once in Task 1 and imported by name thereafter. `primary_sdr` gains exactly one keyword-only parameter in Task 7, and its only caller is updated in the same task.

**Cross-plan ordering:** Task 1 must land before the naming/scores plan's Tasks 2 and 6. Task 7 is the only place the two plans touch the same lines.

**Corrections made during the fine-tuning pass:**

1. **`ensemble_pair_buckets` resolved pairs through `ensemble_stem_bucket`.**
   That is wrong: `ensemble_stem_bucket("Other", stem_count=1)` returns
   `Instrumental`, so `Other/No Other` would have become an Instrumental
   request — a new bug of exactly the kind this plan exists to fix. Now an
   explicit table, with a regression test and a verification snippet in Task 2
   Step 4. This also forced the `wanted_buckets` parameter on `model_list`
   (Task 3), since a pair must be resolved as a unit.
2. **Task 3's test only re-asserted the Task 1 resolver**, so its "verify it
   fails" step honestly said the test would already pass. Rewritten to drive
   the real `ensemble_model_list` through a patched `stem_check`, which is the
   behaviour that actually changes.
3. **Task 3's `matches_stem` rewrite drifted from the original's
   `is_no_demucs` and `demucs_source_list` semantics.** Restructured as a
   minimal substitution that preserves the original branch structure, so the
   diff is reviewable against upstream.
4. **`lead_only` / `backing_only` were folded into plain vocals.** Identity
   codes now resolve before the karaoke/BV flags are consulted — they describe
   the stem, not the model. Covered by `IdentityCodeTests`.

**Deliberate non-goals:** the possible `KeyError` at `engines/mdx.py:661-662` is recorded in the spec's out-of-scope section rather than fixed — no installed model triggers it and confirming it needs a 2-instrument yaml that names its second stem something other than `Instrumental`.

**Verification design:** Task 8 Step 4 runs a real ensemble rather than trusting unit tests, because the failure mode of a bad bucket tag is silent single-member output that every unit test would still pass.
