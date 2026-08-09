# Stem Export Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 2-stem "exclusive" export choice (VR, classic MDX-Net, <=2-stem MDX-C) survive switching between models that disagree about which physical stem is "primary," and consolidate three near-duplicate stem-name vocabularies into one, fixing inconsistent display casing along the way.

**Architecture:** One shared raw-name→canonical-stem lookup (`core/model_stem_semantics.py::canonical_stem_alias`) replaces three independently-maintained copies (UI display table, ensemble tag table, `core/stems.py`'s bucket token sets). A new `settings.process.stem_focus` field stores the user's exclusive-mode pick as a stable ensemble bucket tag instead of a position (primary/secondary); on every model switch it's re-resolved against the new model's own stems via `ensemble_stem_bucket`, gated by a new curated-vs-guessed confidence signal on `ModelConfig.is_karaoke`/`is_karaoke_curated` so an unreliable guess never drives a confident wrong stem export.

**Tech Stack:** Python 3.14, stdlib `unittest`, GTK4/libadwaita (via PyGObject, headless-safe for widget construction in this test suite), no new dependencies.

**Spec:** [docs/superpowers/specs/2026-08-09-stem-export-semantics-design.md](../specs/2026-08-09-stem-export-semantics-design.md)

## Global Constraints

- Every existing test must keep passing after each task — this plan is a refactor-plus-feature over code with real production callers, not a from-scratch build. Run the full suite (`.venv/bin/python -m unittest discover -s tests`) at the end of every task, not just the new tests.
- No new pip dependencies.
- Follow the repo's existing patterns: `rg` for search, stdlib `unittest`, one commit per task (see each task's final step).
- Type-check touched files with `.venv/bin/python -m basedpyright <files>` before each commit; the plan's final task runs it project-wide.
- Do not touch `_ENSEMBLE_STEM_PRESERVE`, `_COMPLEMENT_DISPLAY`, or either side's "No X" complement handling — the spec verified these must stay separate (behavior differences, not accidental duplication).
- Do not add UI-only specialty names (`speech`, `music`, `sfx`, `effects`) to the shared table — verified in the spec that this would silently change `canonical_ensemble_stem_tag`'s output for those stems.

---

### Task 1: Shared stem-name alias table + `canonical_stem_alias`

**Files:**
- Modify: `core/model_stem_semantics.py:660-737` (the `_ENSEMBLE_STEM_ALIASES` block and `canonical_ensemble_stem_tag`)
- Test: `tests/test_model_stem_semantics.py`

**Interfaces:**
- Produces: `core.model_stem_semantics.canonical_stem_alias(name: str) -> Optional[str]` — casefolded raw-name lookup against the shared core vocabulary (vocals/vocal/voc/instrumental/inst/instrument/other/bass/drums/guitar/piano). Returns `None` for anything outside that set. This is the function every later task in this plan calls.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_model_stem_semantics.py`. Its top-level `from bundled.constants import (...)` block (currently `BV_VOCAL_STEM`, `BV_VOCAL_STEM_LABEL`, `INST_STEM`, `INST_WITH_BACKING_VOCALS_STEM`, `INST_WITH_LEAD_VOCALS_STEM`, `LEAD_VOCAL_STEM`, `LEAD_VOCAL_STEM_LABEL`, `VOCAL_STEM`) needs `NO_BASS_STEM` and `NO_OTHER_STEM` added (alphabetically, after `LEAD_VOCAL_STEM_LABEL`); its `from core.model_stem_semantics import (...)` block needs `canonical_stem_alias` added (alphabetically, after `apply_karaoke_quick_export_default`):

```python
class CanonicalStemAliasTests(unittest.TestCase):
    def test_resolves_the_shared_core_vocabulary(self) -> None:
        self.assertEqual(canonical_stem_alias("vocals"), VOCAL_STEM)
        self.assertEqual(canonical_stem_alias("VOCALS"), VOCAL_STEM)
        self.assertEqual(canonical_stem_alias("voc"), VOCAL_STEM)
        self.assertEqual(canonical_stem_alias("instrumental"), INST_STEM)
        self.assertEqual(canonical_stem_alias("instrument"), INST_STEM)
        self.assertEqual(canonical_stem_alias("drums"), "Drums")
        self.assertEqual(canonical_stem_alias("bass"), "Bass")
        self.assertEqual(canonical_stem_alias("guitar"), "Guitar")
        self.assertEqual(canonical_stem_alias("piano"), "Piano")
        self.assertEqual(canonical_stem_alias("other"), "Other")

    def test_returns_none_outside_the_shared_vocabulary(self) -> None:
        self.assertIsNone(canonical_stem_alias("speech"))
        self.assertIsNone(canonical_stem_alias("singer_1"))
        self.assertIsNone(canonical_stem_alias(""))
        self.assertIsNone(canonical_stem_alias(None))


class EnsembleStemCanonicalizationRegressionTests(unittest.TestCase):
    """Locks in canonical_ensemble_stem_tag's existing contract through the
    refactor -- specialty names must stay unchanged, karaoke/BV labels must
    stay preserved, complement tags must stay ensemble-specific."""

    def test_specialty_names_pass_through_unchanged(self) -> None:
        from core.model_stem_semantics import canonical_ensemble_stem_tag

        self.assertEqual(canonical_ensemble_stem_tag("speech"), "speech")
        self.assertEqual(canonical_ensemble_stem_tag("sfx"), "sfx")
        self.assertEqual(canonical_ensemble_stem_tag("music"), "music")
        self.assertEqual(canonical_ensemble_stem_tag("effects"), "effects")

    def test_complement_tags_still_resolve(self) -> None:
        from core.model_stem_semantics import canonical_ensemble_stem_tag

        self.assertEqual(canonical_ensemble_stem_tag("no other"), NO_OTHER_STEM)
        self.assertEqual(canonical_ensemble_stem_tag("no bass"), NO_BASS_STEM)

    def test_instrument_alias_now_recognized(self) -> None:
        """New: core/stems.py already recognized "instrument" for bucketing;
        ensemble tag canonicalization gains it too via the shared table."""
        from core.model_stem_semantics import canonical_ensemble_stem_tag

        self.assertEqual(canonical_ensemble_stem_tag("instrument"), INST_STEM)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_model_stem_semantics.CanonicalStemAliasTests -v`
Expected: FAIL with `ImportError: cannot import name 'canonical_stem_alias'`

Run: `.venv/bin/python -m unittest tests.test_model_stem_semantics.EnsembleStemCanonicalizationRegressionTests.test_instrument_alias_now_recognized -v`
Expected: FAIL — `canonical_ensemble_stem_tag("instrument")` currently returns `"instrument"` unchanged, not `INST_STEM`.

- [ ] **Step 3: Replace `_ENSEMBLE_STEM_ALIASES` with the shared table + `canonical_stem_alias`**

In `core/model_stem_semantics.py`, replace the block currently at lines 660-676 (`_ENSEMBLE_STEM_ALIASES = {...}`) with:

```python
# Raw-name -> canonical-stem lookup shared by UI display, ensemble
# bucketing, and stem-focus persistence anchoring. Only entries every
# consumer already agrees on (or a strict, verified addition) belong here.
# UI-only specialty names (speech/music/sfx/effects) and each consumer's
# own complement ("No X") handling stay separate -- see
# docs/superpowers/specs/2026-08-09-stem-export-semantics-design.md.
_STEM_NAME_ALIASES: Dict[str, str] = {
    "vocals": VOCAL_STEM,
    "vocal": VOCAL_STEM,
    "voc": VOCAL_STEM,
    "instrumental": INST_STEM,
    "inst": INST_STEM,
    "instrument": INST_STEM,
    "other": OTHER_STEM,
    "bass": BASS_STEM,
    "drums": DRUM_STEM,
    "guitar": GUITAR_STEM,
    "piano": PIANO_STEM,
}


def canonical_stem_alias(name: str) -> Optional[str]:
    """Shared raw-name -> canonical-stem lookup, casefolded.

    Single source of truth for UI display, ensemble bucketing, and
    stem-focus anchoring. Returns ``None`` for anything not in the shared
    core vocabulary -- callers layer their own purpose-specific handling
    (specialty names, complement stems, karaoke/BV identity codes) on top.
    """
    if not name:
        return None
    return _STEM_NAME_ALIASES.get(str(name).strip().casefold())


# Ensemble-only: complement ("No X") tags, matched as a whole lowercase
# string. Kept separate from _STEM_NAME_ALIASES -- unlike the UI's
# NO_STEM-prefix-then-suffix-lookup approach (ui/widgets/stem_only.py), this
# must match a raw, fully-lowercase yaml value directly. Verified: the UI's
# canonical_stem_name only recognizes an already-capitalized "No " prefix.
_ENSEMBLE_STEM_COMPLEMENTS: Dict[str, str] = {
    "no other": NO_OTHER_STEM,
    "no bass": NO_BASS_STEM,
    "no drums": NO_DRUM_STEM,
    "no guitar": NO_GUITAR_STEM,
    "no piano": NO_PIANO_STEM,
}
```

Then replace the `_ENSEMBLE_STEM_CANONICAL` block (originally lines 695-710, which built its frozenset from `_ENSEMBLE_STEM_ALIASES.values()`) with:

```python
_ENSEMBLE_STEM_CANONICAL = frozenset(
    {
        VOCAL_STEM,
        INST_STEM,
        OTHER_STEM,
        BASS_STEM,
        DRUM_STEM,
        GUITAR_STEM,
        PIANO_STEM,
        NO_OTHER_STEM,
        NO_BASS_STEM,
        NO_DRUM_STEM,
        NO_GUITAR_STEM,
        NO_PIANO_STEM,
    }
)
```

(This was already a complete superset of `_ENSEMBLE_STEM_ALIASES.values()` — the union was redundant.)

Finally, update `canonical_ensemble_stem_tag` (originally lines 713-737) to consult the complements dict and the shared function instead of the deleted `_ENSEMBLE_STEM_ALIASES`:

```python
def canonical_ensemble_stem_tag(stem: str) -> str:
    """Normalize a stem tag for multi-stem ensemble bucketing and filenames.

    Only folds well-known aliases (``vocals`` → ``Vocals``, ``drums`` →
    ``Drums``, …). Leaves karaoke/BV identity codes and specialty stems
    (Speech, Lead Vocals, Sfx, …) unchanged so they never merge with MUSDB
    stems by accident.
    """
    if not stem:
        return stem
    stripped = str(stem).strip()
    if not stripped:
        return stripped
    if stripped in _ENSEMBLE_STEM_PRESERVE:
        return stripped
    if stripped in _ENSEMBLE_STEM_CANONICAL:
        return stripped
    complement = _ENSEMBLE_STEM_COMPLEMENTS.get(stripped.casefold())
    if complement is not None:
        return complement
    aliased = canonical_stem_alias(stripped)
    if aliased is not None:
        return aliased
    # Title Case / odd casing of a known label (e.g. ``VOCALS`` → ``Vocals``).
    for label in _ENSEMBLE_STEM_CANONICAL:
        if label.casefold() == stripped.casefold():
            return label
    return stripped
```

`Dict` and `Optional` are already imported at the top of this file (used by `stem_display_overrides`'s return type) — no new imports needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_model_stem_semantics -v`
Expected: all PASS, including the new `CanonicalStemAliasTests` and `EnsembleStemCanonicalizationRegressionTests`.

- [ ] **Step 5: Run the full existing suite to check for regressions**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: OK, same pass count as before this task plus the new tests. Pay particular attention to `tests.test_ensemble_stem_buckets` and `tests.test_ensemble_stem_casing` (these exercise `ensemble_stem_bucket`/`canonical_ensemble_stem_tag`'s consumers).

- [ ] **Step 6: Type-check and commit**

Run: `.venv/bin/python -m basedpyright core/model_stem_semantics.py tests/test_model_stem_semantics.py`
Expected: 0 errors.

```bash
git add core/model_stem_semantics.py tests/test_model_stem_semantics.py
git commit -m "Consolidate the ensemble stem-alias table into a shared canonical_stem_alias.

_ENSEMBLE_STEM_ALIASES duplicated the UI display table's data. Replaces it
with a shared _STEM_NAME_ALIASES table + canonical_stem_alias() lookup that
later tasks reuse for UI display, core/stems.py's bucket resolution, and
stem-focus anchoring. Ensemble-only complement handling and specialty-name
passthrough are unaffected (regression tests added)."
```

---

### Task 2: Fold `core/stems.py`'s private token sets into the shared table

**Files:**
- Modify: `core/stems.py:158-172` (`_VOCAL_TOKENS`, `_INSTRUMENTAL_TOKENS`, `_SIMPLE_STEM_TOKENS`) and `core/stems.py:220-262` (`bucket_for_model_stem`)
- Test: `tests/test_ensemble_stem_buckets.py`

**Interfaces:**
- Consumes: `core.model_stem_semantics.canonical_stem_alias` (Task 1).
- Produces: `bucket_for_model_stem`'s public signature and return type are unchanged (`StemBucket`) — this task changes its internals only, not its contract. `ensemble_stem_bucket` (which delegates to it) is likewise unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ensemble_stem_buckets.py`:

```python
class ThirdVocabularyConsolidationTests(unittest.TestCase):
    """core/stems.py's bucket_for_model_stem had its own private token sets,
    already drifted from the other two tables (it alone recognized
    "instrument"). This locks in that the drift is now gone in both
    directions: the new alias reaches bucketing (already true) *and* stays
    behavior-identical for every token the old private sets recognized."""

    def test_instrument_alias_resolves_to_instrumental_bucket(self) -> None:
        self.assertEqual(
            ensemble_stem_bucket("instrument", stem_count=1), BUCKET_INSTRUMENTAL
        )

    def test_voc_alias_resolves_to_vocals_bucket(self) -> None:
        self.assertEqual(ensemble_stem_bucket("voc", stem_count=2), BUCKET_VOCALS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_ensemble_stem_buckets.ThirdVocabularyConsolidationTests -v`
Expected: `test_instrument_alias_resolves_to_instrumental_bucket` FAILS (current `_INSTRUMENTAL_TOKENS` already contains `"instrument"`, so this specific one may actually pass already — that's fine, it's here as a locked-in regression guard, not a new behavior). `test_voc_alias_resolves_to_vocals_bucket` should also already pass today. Both existing separately from the refactor — the point of this step is confirming they pass *before and after* Step 3, proving the refactor doesn't change behavior.

- [ ] **Step 3: Refactor `bucket_for_model_stem` to use the shared table**

In `core/stems.py`, replace the token-set block (lines 158-172):

```python
_IDENTITY_BUCKETS = {
    "lead_only": StemBucket.LEAD_VOCALS,
    "lead vocals": StemBucket.LEAD_VOCALS,
    "backing_only": StemBucket.BACKING_VOCALS,
    "backing vocals": StemBucket.BACKING_VOCALS,
}

_VOCAL_TOKENS = frozenset({"vocals", "vocal", "voc"})
_INSTRUMENTAL_TOKENS = frozenset({"instrumental", "inst", "instrument"})
_SIMPLE_STEM_TOKENS = {
    "drums": StemBucket.DRUMS,
    "bass": StemBucket.BASS,
    "guitar": StemBucket.GUITAR,
    "piano": StemBucket.PIANO,
}
```

with:

```python
_IDENTITY_BUCKETS = {
    "lead_only": StemBucket.LEAD_VOCALS,
    "lead vocals": StemBucket.LEAD_VOCALS,
    "backing_only": StemBucket.BACKING_VOCALS,
    "backing vocals": StemBucket.BACKING_VOCALS,
}

# Canonical label -> bucket enum for the plain single-instrument stems.
# Alias spellings (vocals/voc/drums/...) live in the shared
# core.model_stem_semantics table bucket_for_model_stem now queries via
# canonical_stem_alias; this dict only maps already-canonical labels to
# their bucket, it is not alias data.
_SIMPLE_STEM_BUCKETS = {
    DRUM_STEM: StemBucket.DRUMS,
    BASS_STEM: StemBucket.BASS,
    GUITAR_STEM: StemBucket.GUITAR,
    PIANO_STEM: StemBucket.PIANO,
}
```

Then replace `bucket_for_model_stem` (lines 220-262):

```python
def bucket_for_model_stem(
    stem: str | StemId,
    *,
    stem_count: int = 2,
    is_karaoke: bool = False,
    is_bv: bool = False,
) -> StemBucket:
    """Map a model stem id to an ensemble bucket (may be ``UNKNOWN``)."""
    from core.model_stem_semantics import canonical_stem_alias

    raw = stem.raw if isinstance(stem, StemId) else stem
    token = str(raw or "").strip().casefold()
    if not token:
        return StemBucket.UNKNOWN

    identity = _IDENTITY_BUCKETS.get(token)
    if identity is not None:
        return identity

    canonical = canonical_stem_alias(token)
    is_vocal = canonical == VOCAL_STEM
    is_instrumental = canonical == INST_STEM or (
        token == "other" and 1 <= stem_count <= 2
    )

    if is_karaoke:
        if is_vocal:
            return StemBucket.LEAD_VOCALS
        if is_instrumental:
            return StemBucket.INST_WITH_BV
    if is_bv:
        if is_vocal:
            return StemBucket.BACKING_VOCALS
        if is_instrumental:
            return StemBucket.INST_WITH_LEAD

    if is_vocal:
        return StemBucket.VOCALS
    if is_instrumental:
        return StemBucket.INSTRUMENTAL
    if token == "other":
        return StemBucket.OTHER
    simple = _SIMPLE_STEM_BUCKETS.get(canonical) if canonical else None
    if simple is not None:
        return simple
    return StemBucket.UNKNOWN
```

`DRUM_STEM`, `BASS_STEM`, `GUITAR_STEM`, `PIANO_STEM`, `VOCAL_STEM`, `INST_STEM` are already imported at the top of `core/stems.py` (used by the `StemBucket` enum definition) — no new imports needed. The `canonical_stem_alias` import is deferred (function-local), matching this file's existing pattern of deferred imports from `core.model_stem_semantics` elsewhere in the same file (`export_stem_key`, `resolve_in_sources`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_ensemble_stem_buckets -v`
Expected: all PASS, including every pre-existing test in this file (this is the regression guard the spec calls for — `OtherOverloadTests`, karaoke/BV bucket tests, splitter identity tests, and the new `ThirdVocabularyConsolidationTests`).

- [ ] **Step 5: Run the full existing suite**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: OK. Also spot-check `tests.test_ensemble_stem_casing` (uses `_ensemble_stem_bucket` from `core/job_runner.py`, which itself calls `canonical_ensemble_stem_tag` — Task 1's function, unaffected by this task, but worth re-confirming green).

- [ ] **Step 6: Type-check and commit**

Run: `.venv/bin/python -m basedpyright core/stems.py tests/test_ensemble_stem_buckets.py`
Expected: 0 errors.

```bash
git add core/stems.py tests/test_ensemble_stem_buckets.py
git commit -m "Remove core/stems.py's private vocals/instrumental token sets.

bucket_for_model_stem had its own copy of the same alias vocabulary,
already drifted from the other two (it alone recognized "instrument").
Now queries the shared canonical_stem_alias from Task 1 instead."
```

---

### Task 3: Fold the UI display table into the shared table

**Files:**
- Modify: `ui/widgets/stem_only.py:80-137` (`_STEM_ALIASES`, `canonical_stem_name`)
- Test: `tests/test_stem_only.py`

**Interfaces:**
- Consumes: `core.model_stem_semantics.canonical_stem_alias` (Task 1).
- Produces: `canonical_stem_name`'s signature and behavior for every currently-passing input are unchanged; it additionally now recognizes `"voc"` and `"instrument"`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_stem_only.py`'s `StemDisplayLabelTests` class:

```python
    def test_gains_shared_table_aliases_not_previously_recognized(self) -> None:
        self.assertEqual(canonical_stem_name("voc"), VOCAL_STEM)
        self.assertEqual(canonical_stem_name("instrument"), INST_STEM)

    def test_specialty_names_still_resolve_locally(self) -> None:
        self.assertEqual(canonical_stem_name("speech"), "Speech")
        self.assertEqual(canonical_stem_name("sfx"), "Sfx")
        self.assertEqual(canonical_stem_name("music"), "Music")
        self.assertEqual(canonical_stem_name("effects"), "Effects")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_stem_only.StemDisplayLabelTests.test_gains_shared_table_aliases_not_previously_recognized -v`
Expected: FAIL — `canonical_stem_name("voc")` currently returns `"voc"` unchanged (not in `_STEM_ALIASES`), same for `"instrument"`.

- [ ] **Step 3: Refactor `_STEM_ALIASES` and `canonical_stem_name`**

In `ui/widgets/stem_only.py`, replace lines 80-95 (`_STEM_ALIASES = {...}`) with:

```python
# UI-only: names with no ensemble/bucket significance today. Kept separate
# from the shared core table on purpose -- folding them in would change
# core/model_stem_semantics.canonical_ensemble_stem_tag's output for these
# stems (verified: it passes them through unchanged today). See
# docs/superpowers/specs/2026-08-09-stem-export-semantics-design.md.
_STEM_ALIASES: Dict[str, str] = {
    "speech": "Speech",
    "music": "Music",
    "sfx": "Sfx",
    "effects": "Effects",
}
```

Change the existing top-level import block at lines 31-34 from:

```python
from core.model_stem_semantics import (
    VOCALS_OTHER_DISPLAY_OVERRIDES,
    stem_display_overrides,
)
```

to:

```python
from core.model_stem_semantics import (
    VOCALS_OTHER_DISPLAY_OVERRIDES,
    canonical_stem_alias,
    stem_display_overrides,
)
```

Then replace `canonical_stem_name` (lines 122-137):

```python
def canonical_stem_name(stem: Optional[str]) -> Optional[str]:
    """Normalize model/yaml stem strings to canonical UVR labels."""
    if not stem:
        return stem
    shared = canonical_stem_alias(stem)
    if shared is not None:
        return shared
    if stem in _STEM_ALIASES:
        return _STEM_ALIASES[stem]
    lowered = stem.lower()
    if lowered in _STEM_ALIASES:
        return _STEM_ALIASES[lowered]
    if stem.startswith(NO_STEM) and len(stem) > len(NO_STEM):
        suffix = stem[len(NO_STEM) :]
        canonical_suffix = canonical_stem_alias(suffix) or _STEM_ALIASES.get(suffix.lower(), suffix)
        if canonical_suffix == suffix and suffix[:1].islower():
            canonical_suffix = suffix.title()
        return f"{NO_STEM}{canonical_suffix}"
    return stem
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_stem_only -v`
Expected: all PASS (20 existing + 2 new).

- [ ] **Step 5: Run the full existing suite**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 6: Type-check and commit**

Run: `.venv/bin/python -m basedpyright ui/widgets/stem_only.py tests/test_stem_only.py`
Expected: 0 errors.

```bash
git add ui/widgets/stem_only.py tests/test_stem_only.py
git commit -m "Fold the UI stem-display alias table into the shared canonical_stem_alias.

canonical_stem_name now consults Task 1's shared table first, gaining
"voc" and "instrument" (previously only core/stems.py's bucket resolver
knew them). Specialty names (speech/music/sfx/effects) stay UI-only."
```

---

### Task 4: Extract `resolve_karaoke_confidence` from `resolve_is_karaoke`

**Files:**
- Modify: `core/model_stem_semantics.py` (the `resolve_is_karaoke` function, currently around line 230)
- Test: `tests/test_model_stem_semantics.py`

**Interfaces:**
- Produces: `core.model_stem_semantics.resolve_karaoke_confidence(*, model_data=None, model_name="", config_yaml="", weight_basename="") -> tuple[bool, bool]` — `(is_karaoke, is_curated)`. `resolve_is_karaoke`'s existing signature and `bool` return are unchanged; it becomes a one-line wrapper.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_model_stem_semantics.py`'s `KaraokeDetectionTests` class:

```python
    def test_confidence_true_when_curated(self) -> None:
        self.assertEqual(
            resolve_karaoke_confidence(model_data={"is_karaoke": True}),
            (True, True),
        )

    def test_confidence_false_when_guessed_from_name(self) -> None:
        self.assertEqual(
            resolve_karaoke_confidence(
                model_name="BandSplit Roformer | Karaoke Frazer by becruily",
            ),
            (True, False),
        )

    def test_confidence_false_and_not_karaoke_with_no_signal(self) -> None:
        self.assertEqual(resolve_karaoke_confidence(), (False, False))

    def test_resolve_is_karaoke_still_returns_a_plain_bool(self) -> None:
        self.assertIs(resolve_is_karaoke(model_data={"is_karaoke": True}), True)
        self.assertIs(resolve_is_karaoke(), False)
```

Add `resolve_karaoke_confidence` to the `from core.model_stem_semantics import (...)` block at the top of the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_model_stem_semantics.KaraokeDetectionTests -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_karaoke_confidence'`.

- [ ] **Step 3: Extract the function**

In `core/model_stem_semantics.py`, replace `resolve_is_karaoke` (currently ~line 230-245):

```python
def resolve_karaoke_confidence(
    *,
    model_data: Optional[Mapping] = None,
    model_name: str = "",
    config_yaml: str = "",
    weight_basename: str = "",
) -> Tuple[bool, bool]:
    """Resolve ``(is_karaoke, is_curated)``.

    ``is_curated`` is ``True`` only when curated hash metadata settled it.
    ``False`` means ``is_karaoke`` came from
    :func:`infer_is_karaoke_from_hints`'s name/config/weight-basename
    substring guess, which is unreliable for any model without a curated
    hash-table entry -- i.e. every new community model until someone
    curates it.
    """
    if model_data:
        if model_data.get("is_karaoke") or model_data.get("is_karaokee"):
            return True, True
    guess = infer_is_karaoke_from_hints(
        model_name=model_name,
        config_yaml=config_yaml,
        weight_basename=weight_basename,
    )
    return guess, False


def resolve_is_karaoke(
    *,
    model_data: Optional[Mapping] = None,
    model_name: str = "",
    config_yaml: str = "",
    weight_basename: str = "",
) -> bool:
    """Resolve karaoke flag from hash metadata or catalogue/config hints."""
    is_karaoke, _is_curated = resolve_karaoke_confidence(
        model_data=model_data,
        model_name=model_name,
        config_yaml=config_yaml,
        weight_basename=weight_basename,
    )
    return is_karaoke
```

`Tuple` is already imported at the top of this file (used by `ensemble_pair_buckets`'s return type) — no new imports needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_model_stem_semantics -v`
Expected: all PASS.

- [ ] **Step 5: Run the full existing suite**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: OK. `resolve_is_karaoke`'s three production callers (`core/model_data.py`, `scripts/generate_models_catalogue.py`, and its own use inside `core/model_stem_semantics.py`'s `export_intent_from_model`) are untouched by this task — Task 5 updates the `core/model_data.py` one specifically.

- [ ] **Step 6: Type-check and commit**

Run: `.venv/bin/python -m basedpyright core/model_stem_semantics.py tests/test_model_stem_semantics.py`
Expected: 0 errors.

```bash
git add core/model_stem_semantics.py tests/test_model_stem_semantics.py
git commit -m "Extract resolve_karaoke_confidence from resolve_is_karaoke.

Gives callers a way to tell curated hash-metadata detection apart from a
name-substring guess, without a second function re-deriving the same
curated-check independently. resolve_is_karaoke becomes a wrapper; its
three existing call sites are unaffected."
```

---

### Task 5: Track curated-vs-guessed confidence on `ModelConfig`

**Files:**
- Modify: `core/model_data.py:661` (init), `core/model_data.py:1057-1083` (`check_if_karaokee_model`, `apply_karaoke_metadata`), `core/model_data.py:33` (import)
- Test: `tests/test_core_model_data.py` (the existing dedicated test file for `core/model_data.py`-level `ModelConfig` behavior; it already imports `ModelConfig` from `core.model_config` and tests other `ModelConfig` construction paths there)

**Interfaces:**
- Consumes: `resolve_karaoke_confidence` (Task 4).
- Produces: `ModelConfig.is_karaoke_curated: bool` (default `False`), set alongside `is_karaoke` by both `check_if_karaokee_model` (curated hash path) and `apply_karaoke_metadata` (guessed fallback path). Task 6/7 read this attribute directly.

- [ ] **Step 1: Write the failing test**

Add a new test class to `tests/test_core_model_data.py`, which already has `import typing` at the top (line 1):

```python
class ModelConfigKaraokeConfidenceTests(unittest.TestCase):
    """ModelConfig.is_karaoke_curated must agree with which branch of
    resolve_karaoke_confidence actually set is_karaoke."""

    def _model(self) -> typing.Any:
        from types import SimpleNamespace

        # Minimal stand-in with just the attributes check_if_karaokee_model
        # and apply_karaoke_metadata read/write.
        model = SimpleNamespace(
            model_data=None,
            is_karaoke=False,
            is_karaoke_curated=False,
            is_bv_model=False,
            bv_model_rebalance=0,
            model_name="",
            model_basename=None,
            model_path=None,
        )
        return model

    def test_curated_hash_metadata_sets_curated_true(self) -> None:
        from core.model_data import _ModelConfigImplementation

        model = self._model()
        model.model_data = {"is_karaoke": True}
        _ModelConfigImplementation.check_if_karaokee_model(model)
        self.assertTrue(model.is_karaoke)
        self.assertTrue(model.is_karaoke_curated)

    def test_guessed_from_name_sets_curated_false(self) -> None:
        from core.model_data import _ModelConfigImplementation

        model = self._model()
        model.model_name = "BandSplit Roformer | Karaoke Frazer by becruily"
        _ModelConfigImplementation.apply_karaoke_metadata(model)
        self.assertTrue(model.is_karaoke)
        self.assertFalse(model.is_karaoke_curated)

    def test_no_signal_leaves_both_false(self) -> None:
        from core.model_data import _ModelConfigImplementation

        model = self._model()
        _ModelConfigImplementation.apply_karaoke_metadata(model)
        self.assertFalse(model.is_karaoke)
        self.assertFalse(model.is_karaoke_curated)
```

Note: `_ModelConfigImplementation.check_if_karaokee_model(model)` / `_ModelConfigImplementation.apply_karaoke_metadata(model)` call the unbound methods directly against a plain `SimpleNamespace` stand-in — this works because neither method touches anything on `self` beyond the attributes set up in `_model()`. `_ModelConfigImplementation` (`core/model_data.py:516`) is the base class `check_if_karaokee_model`/`apply_karaoke_metadata` are actually defined on; the public `ModelConfig` (`core/model_config/config.py`, imported back into `core/model_data.py` at its very end to resolve the circular reference) subclasses it and inherits both unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_core_model_data.ModelConfigKaraokeConfidenceTests -v`
Expected: FAIL — `SimpleNamespace` has no `is_karaoke_curated` attribute access issue is fine (it's set in `_model()`), but the assertions on it being `True`/matching will fail since the production code doesn't set it yet (`AttributeError` won't occur since `_model()` initializes it to `False`; the assertions themselves fail).

- [ ] **Step 3: Add the attribute and wire it into both resolution paths**

In `core/model_data.py`, change the import at line 33:

```python
from .model_stem_semantics import is_vocal_target, resolve_karaoke_confidence
```

(`resolve_is_karaoke` is removed from this import — after this task it has no remaining callers in this file.)

At line 661, add the new attribute right after `is_karaoke`:

```python
        self.is_karaoke = False
        self.is_karaoke_curated = False
        self.is_bv_model = False
```

Replace `check_if_karaokee_model` (lines 1057-1065):

```python
    def check_if_karaokee_model(self):
        if not self.model_data:
            return
        if IS_KARAOKEE in self.model_data.keys():
            self.is_karaoke = self.model_data[IS_KARAOKEE]
            self.is_karaoke_curated = True
        if IS_BV_MODEL in self.model_data.keys():
            self.is_bv_model = self.model_data[IS_BV_MODEL]
        if IS_BV_MODEL_REBAL in self.model_data.keys() and self.is_bv_model:
            self.bv_model_rebalance = self.model_data[IS_BV_MODEL_REBAL]
```

Replace `apply_karaoke_metadata` (lines 1067-1083):

```python
    def apply_karaoke_metadata(self, config_yaml: str = "") -> None:
        """Set ``is_karaoke``/``is_karaoke_curated`` from hash JSON and
        catalogue/config name hints."""
        self.check_if_karaokee_model()
        if self.is_karaoke:
            return
        weight_basename = getattr(self, "model_basename", None)
        if not weight_basename:
            model_path = getattr(self, "model_path", None) or ""
            if model_path:
                weight_basename = os.path.splitext(os.path.basename(model_path))[0]
        is_karaoke, is_curated = resolve_karaoke_confidence(
            model_data=self.model_data,
            model_name=str(self.model_name or ""),
            config_yaml=config_yaml,
            weight_basename=str(weight_basename or ""),
        )
        if is_karaoke:
            self.is_karaoke = True
            self.is_karaoke_curated = is_curated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_core_model_data.ModelConfigKaraokeConfidenceTests -v`
Expected: PASS.

- [ ] **Step 5: Run the full existing suite**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: OK — this is the step that catches whether removing `resolve_is_karaoke` from `core/model_data.py`'s imports broke anything else in that file (it shouldn't; it had exactly one call site, now replaced).

- [ ] **Step 6: Type-check and commit**

Run: `.venv/bin/python -m basedpyright core/model_data.py tests/test_core_model_data.py`
Expected: 0 errors.

```bash
git add core/model_data.py tests/test_core_model_data.py
git commit -m "Track whether ModelConfig.is_karaoke came from curated metadata or a guess.

New is_karaoke_curated attribute, set alongside is_karaoke by both the
curated hash-table path (check_if_karaokee_model) and the name-guess
fallback path (apply_karaoke_metadata, via resolve_karaoke_confidence).
Consumed by the stem-focus anchoring mechanism in the next tasks."
```

---

### Task 6: `process.stem_focus` setting, `confident_stem_bucket`, and `configure_exclusive` plumbing

**Files:**
- Modify: `core/settings/model.py:74-75` (`ProcessSettings`)
- Modify: `core/settings/defaults.py:28-29` (`default_process`)
- Modify: `core/model_stem_semantics.py` (new `confident_stem_bucket` function)
- Modify: `ui/widgets/stem_only.py` — `SaveStemsSection.__init__` and `configure_exclusive` (line numbers given below are from before Task 3's edits to this same file; Task 3 shrinks it by roughly 10 lines, so search for `def __init__` inside `class SaveStemsSection` and `def configure_exclusive` by name rather than trusting the exact line numbers)
- Test: `tests/test_model_stem_semantics.py`, `tests/test_stem_only.py`

**Interfaces:**
- Produces: `settings.process.stem_focus: str` (default `""`). `core.model_stem_semantics.confident_stem_bucket(stem, *, stem_count, is_karaoke, is_karaoke_curated, is_bv) -> str`. `SaveStemsSection.configure_exclusive(..., is_karaoke=False, is_karaoke_curated=False, is_bv=False, stem_count=2)` — new keyword-only params, stored as `self._exclusive_is_karaoke`, `self._exclusive_is_karaoke_curated`, `self._exclusive_is_bv`, `self._exclusive_stem_count`. No behavior change yet — Task 7 is what makes these do something.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_model_stem_semantics.py`:

```python
class ConfidentStemBucketTests(unittest.TestCase):
    """A guessed (non-curated) is_karaoke must never reach
    ensemble_stem_bucket as True -- only ever False, which is the same
    fallback ensemble_stem_bucket already uses by default."""

    def test_curated_karaoke_uses_the_karaoke_bucket(self) -> None:
        self.assertEqual(
            confident_stem_bucket(
                "Vocals", stem_count=2, is_karaoke=True, is_karaoke_curated=True, is_bv=False
            ),
            BUCKET_LEAD_VOCALS,
        )

    def test_guessed_karaoke_falls_back_to_the_plain_bucket(self) -> None:
        self.assertEqual(
            confident_stem_bucket(
                "Vocals", stem_count=2, is_karaoke=True, is_karaoke_curated=False, is_bv=False
            ),
            BUCKET_VOCALS,
        )

    def test_is_bv_is_never_gated(self) -> None:
        self.assertEqual(
            confident_stem_bucket(
                "Vocals", stem_count=2, is_karaoke=False, is_karaoke_curated=False, is_bv=True
            ),
            BUCKET_BV_VOCALS,
        )
```

Add `BUCKET_BV_VOCALS`, `BUCKET_LEAD_VOCALS`, `BUCKET_VOCALS`, `confident_stem_bucket` to the test file's top-level `from core.model_stem_semantics import (...)` block (alphabetically: `BUCKET_BV_VOCALS` and `BUCKET_LEAD_VOCALS` before `DUAL_STEM_WEIGHTS`; `BUCKET_VOCALS` and `confident_stem_bucket` — the latter after `apply_karaoke_quick_export_default`/`canonical_stem_alias`, before `export_intent_from_fields` — exact position doesn't matter, the block is already alphabetized elsewhere in this file, keep that convention). None of these four names are in that block yet — the existing `test_karaoke_vocal_primary_note`-area test that uses `BUCKET_LEAD_VOCALS`/`BUCKET_INST_WITH_BV` imports them locally inside its own test method instead; leave that one as-is, it's unrelated to this task.

Add to `tests/test_stem_only.py`'s `SaveStemsSectionTests` class:

```python
    def test_configure_exclusive_accepts_and_stores_confidence_kwargs(self) -> None:
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
            is_karaoke=True,
            is_karaoke_curated=True,
            is_bv=False,
            stem_count=2,
        )
        self.assertTrue(self.section._exclusive_is_karaoke)
        self.assertTrue(self.section._exclusive_is_karaoke_curated)
        self.assertFalse(self.section._exclusive_is_bv)
        self.assertEqual(self.section._exclusive_stem_count, 2)

    def test_configure_exclusive_confidence_kwargs_default_safely(self) -> None:
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.assertFalse(self.section._exclusive_is_karaoke)
        self.assertFalse(self.section._exclusive_is_karaoke_curated)
        self.assertFalse(self.section._exclusive_is_bv)
        self.assertEqual(self.section._exclusive_stem_count, 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_model_stem_semantics.ConfidentStemBucketTests tests.test_stem_only.SaveStemsSectionTests.test_configure_exclusive_accepts_and_stores_confidence_kwargs -v`
Expected: FAIL — `confident_stem_bucket` doesn't exist yet; `configure_exclusive` raises `TypeError: unexpected keyword argument 'is_karaoke'`.

- [ ] **Step 3: Add `stem_focus` to the settings schema**

In `core/settings/model.py`, in the `ProcessSettings` dataclass (currently lines 74-75):

```python
    primary_stem_only: bool = False
    secondary_stem_only: bool = False
    stem_focus: str = ""
```

In `core/settings/defaults.py`, in `default_process()` (currently lines 28-29):

```python
        "primary_stem_only": False,
        "secondary_stem_only": False,
        "stem_focus": "",
```

No entry needed in `core/settings/coerce.py`'s `_BOOL_FIELDS` (it's a `str` field) or in `core/settings/flat_map.py` (accessed directly as `settings.process.stem_focus`, matching the existing pattern for `settings.mdx.stems_selected`, not through the generic flat-combo bridge).

- [ ] **Step 4: Add `confident_stem_bucket`**

In `core/model_stem_semantics.py`, add near `ensemble_stem_bucket`:

```python
def confident_stem_bucket(
    stem: str,
    *,
    stem_count: int,
    is_karaoke: bool,
    is_karaoke_curated: bool,
    is_bv: bool,
) -> str:
    """``ensemble_stem_bucket``, but a guessed (non-curated) ``is_karaoke``
    is never passed through as ``True``.

    ``ensemble_stem_bucket(stem, is_karaoke=False, is_bv=False)`` already
    falls through to the plain alias-table lookup by default -- that *is*
    the safe fallback for an uncurated model's stems, so nothing else is
    needed here beyond gating the one boolean that isn't always reliable.
    ``is_bv`` needs no such gate: it is only ever set from curated
    metadata, never guessed.
    """
    return ensemble_stem_bucket(
        stem,
        stem_count=stem_count,
        is_karaoke=is_karaoke and is_karaoke_curated,
        is_bv=is_bv,
    )
```

- [ ] **Step 5: Extend `configure_exclusive`'s signature**

In `ui/widgets/stem_only.py`, in `__init__` (currently around line 303-304), add the new instance attributes next to the existing exclusive-mode ones:

```python
        self._exclusive_primary: Optional[str] = None
        self._exclusive_secondary: Optional[str] = None
        self._exclusive_is_karaoke: bool = False
        self._exclusive_is_karaoke_curated: bool = False
        self._exclusive_is_bv: bool = False
        self._exclusive_stem_count: int = 2
```

In `configure_exclusive` (currently lines 423-461), add the four new keyword-only parameters and store them:

```python
    def configure_exclusive(
        self,
        *,
        primary_stem: Optional[str],
        secondary_stem: Optional[str],
        primary_key: str,
        secondary_key: str,
        has_model: bool = True,
        stem_label_overrides: Optional[Dict[str, str]] = None,
        export_semantics_note: str = "",
        is_karaoke: bool = False,
        is_karaoke_curated: bool = False,
        is_bv: bool = False,
        stem_count: int = 2,
    ) -> None:
        self.mode = "exclusive"
        self._has_model = has_model
        self._primary_key = primary_key
        self._secondary_key = secondary_key
        self._exclusive_primary = primary_stem
        self._exclusive_secondary = secondary_stem
        self._exclusive_is_karaoke = is_karaoke
        self._exclusive_is_karaoke_curated = is_karaoke_curated
        self._exclusive_is_bv = is_bv
        self._exclusive_stem_count = stem_count
        self._stem_label_overrides = stem_label_overrides
        self._export_semantics_note = export_semantics_note or ""
        self._hide_all_rows()
        if not has_model:
            self._section_visible = False
            return
        self._section_visible = True
        options = build_stem_only_options(
            primary_stem=primary_stem,
            secondary_stem=secondary_stem,
            primary_key=primary_key,
            secondary_key=secondary_key,
            stem_label_overrides=stem_label_overrides,
        )
        was_loading = self._loading
        self._loading = True
        try:
            self._exclusive_options = _fill_export_combo(self._exclusive_row, options)
        finally:
            self._loading = was_loading
        self._exclusive_row.set_visible(True)
        self._apply_semantics_tooltip(self._exclusive_row)
```

(Only the signature and the four new assignment lines changed; the body below `self._export_semantics_note = ...` is unchanged from the current implementation.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_model_stem_semantics.ConfidentStemBucketTests tests.test_stem_only.SaveStemsSectionTests -v`
Expected: all PASS.

- [ ] **Step 7: Run the full existing suite**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: OK — `configure_exclusive`'s new parameters all default safely, so every existing call site (including the one in `ui/views/base.py` this plan hasn't updated yet) keeps working unchanged.

- [ ] **Step 8: Type-check and commit**

Run: `.venv/bin/python -m basedpyright core/settings/model.py core/settings/defaults.py core/model_stem_semantics.py ui/widgets/stem_only.py tests/test_model_stem_semantics.py tests/test_stem_only.py`
Expected: 0 errors.

```bash
git add core/settings/model.py core/settings/defaults.py core/model_stem_semantics.py ui/widgets/stem_only.py tests/test_model_stem_semantics.py tests/test_stem_only.py
git commit -m "Add process.stem_focus setting and confidence-gated bucket plumbing.

New settings.process.stem_focus field, confident_stem_bucket (gates a
guessed is_karaoke to False before it reaches ensemble_stem_bucket), and
configure_exclusive's new is_karaoke/is_karaoke_curated/is_bv/stem_count
parameters -- all wired to safe defaults, no behavior change yet."
```

---

### Task 7: Wire the stem-focus anchoring behavior into sync/persist

**Files:**
- Modify: `ui/widgets/stem_only.py` — add new functions next to `_exclusive_name_from_settings`/`_persist_exclusive_choice`, and update `sync_from_settings`/`persist_to_settings` (line numbers shift with each of Tasks 1, 3, and 6's edits to this file — locate by function name, not line number)
- Modify: `ui/views/base.py` — `_configure_save_stems` (unaffected by earlier tasks; still at line 318-328 unless something else changed this file first)
- Test: `tests/test_stem_only.py`

**Interfaces:**
- Consumes: `confident_stem_bucket` (Task 6), `settings.process.stem_focus` (Task 6), `ModelConfig.is_karaoke`/`is_karaoke_curated`/`is_bv_model` (Task 5).
- Produces: the actual anchoring behavior described in the spec — this is the task that fixes the reported bug.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_stem_only.py`'s `SaveStemsSectionTests` class:

```python
    def test_stem_focus_survives_switching_to_a_model_where_it_is_secondary(self) -> None:
        """The bug this whole feature exists to fix: picking "Instrumental
        Only" on a vocals-primary model, then switching to a model where
        the instrumental happens to be the *secondary* stem, must still
        export the instrumental -- not silently flip to vocals."""
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        set_combo_value(self.section._exclusive_row, "is_secondary_stem_only")
        self.section.persist_to_settings()
        self.assertEqual(self.settings.process.stem_focus, INST_STEM)

        # Switch to a model where Instrumental is now primary, Vocals secondary.
        self.section.configure_exclusive(
            primary_stem=INST_STEM,
            secondary_stem=VOCAL_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertTrue(self.settings["is_primary_stem_only"])
        self.assertFalse(self.settings["is_secondary_stem_only"])
        self.assertIn("Instrumental", self.section.export_summary())

    def test_stem_focus_falls_back_to_all_for_an_unrelated_model(self) -> None:
        self.settings.process.stem_focus = INST_STEM
        self.section.configure_exclusive(
            primary_stem="noreverb",
            secondary_stem="reverb",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertFalse(self.settings["is_primary_stem_only"])
        self.assertFalse(self.settings["is_secondary_stem_only"])
        # The preference stays parked, not discarded, for a future relevant model.
        self.assertEqual(self.settings.process.stem_focus, INST_STEM)

    def test_empty_stem_focus_uses_legacy_boolean_behavior(self) -> None:
        """Before any pick under the new mechanism, behavior is unchanged."""
        self.settings["is_primary_stem_only"] = True
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertIn("Vocals", self.section.export_summary())

    def test_persist_writes_stem_focus_from_the_chosen_stem(self) -> None:
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        set_combo_value(self.section._exclusive_row, "is_primary_stem_only")
        self.section.persist_to_settings()
        self.assertEqual(self.settings.process.stem_focus, VOCAL_STEM)

    def test_persist_all_clears_stem_focus(self) -> None:
        self.settings.process.stem_focus = VOCAL_STEM
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        set_combo_value(self.section._exclusive_row, _TOGGLE_ALL)
        self.section.persist_to_settings()
        self.assertEqual(self.settings.process.stem_focus, "")
```

`set_combo_value` is not currently imported in this test file. Add it to the existing `from ui.widgets.stem_only import (...)` block (currently: `SaveStemsSection`, `_QUICK_ALL`, `_QUICK_INSTRUMENTAL`, `_QUICK_VOCALS`, `_TOGGLE_ALL`, `_LEAD_VOCAL_PAIR_LABELS`, `build_stem_only_options`, `canonical_stem_name`, `roformer_lead_vocal_label_overrides`, `stem_display_label`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_stem_only.SaveStemsSectionTests -v -k stem_focus`
Expected: FAIL — `sync_from_settings`/`persist_to_settings` don't touch `stem_focus` yet, so it stays at its default `""` throughout, and the model-switch flip in `test_stem_focus_survives_switching_to_a_model_where_it_is_secondary` still happens (asserts fail).

- [ ] **Step 3: Add the anchoring functions**

In `ui/widgets/stem_only.py`, add near `_exclusive_name_from_settings`/`_persist_exclusive_choice` (currently lines 266-278):

```python
def _exclusive_name_from_focus(
    settings: typing.Any,
    *,
    primary_stem: Optional[str],
    secondary_stem: Optional[str],
    primary_key: str,
    secondary_key: str,
    is_karaoke: bool,
    is_karaoke_curated: bool,
    is_bv: bool,
    stem_count: int,
) -> Optional[str]:
    """Resolve the exclusive-mode combo choice from ``process.stem_focus``.

    Returns ``None`` when no focus is recorded yet (caller falls back to
    ``_exclusive_name_from_settings``'s legacy boolean-based read). Once a
    focus is recorded, always returns a definite choice -- ``primary_key``/
    ``secondary_key`` on a match, or ``_TOGGLE_ALL`` when neither of this
    model's stems match (a different, unrelated pair type).
    """
    from core.model_stem_semantics import confident_stem_bucket

    focus = getattr(settings.process, "stem_focus", "") or ""
    if not focus:
        return None
    kwargs = dict(
        stem_count=stem_count,
        is_karaoke=is_karaoke,
        is_karaoke_curated=is_karaoke_curated,
        is_bv=is_bv,
    )
    if primary_stem and confident_stem_bucket(primary_stem, **kwargs) == focus:
        return primary_key
    if secondary_stem and confident_stem_bucket(secondary_stem, **kwargs) == focus:
        return secondary_key
    return _TOGGLE_ALL


def _stem_focus_for_choice(
    name: str,
    *,
    primary_stem: Optional[str],
    secondary_stem: Optional[str],
    primary_key: str,
    secondary_key: str,
    is_karaoke: bool,
    is_karaoke_curated: bool,
    is_bv: bool,
    stem_count: int,
) -> str:
    """Bucket tag to persist as ``process.stem_focus`` for an exclusive pick."""
    from core.model_stem_semantics import confident_stem_bucket

    if name == primary_key and primary_stem:
        stem = primary_stem
    elif name == secondary_key and secondary_stem:
        stem = secondary_stem
    else:
        return ""
    return confident_stem_bucket(
        stem,
        stem_count=stem_count,
        is_karaoke=is_karaoke,
        is_karaoke_curated=is_karaoke_curated,
        is_bv=is_bv,
    )
```

- [ ] **Step 4: Wire them into `sync_from_settings` and `persist_to_settings`**

In `sync_from_settings` (currently lines 557-572), replace the `"exclusive"` branch:

```python
            if self.mode == "exclusive":
                name = _exclusive_name_from_focus(
                    self.settings,
                    primary_stem=self._exclusive_primary,
                    secondary_stem=self._exclusive_secondary,
                    primary_key=self._primary_key,
                    secondary_key=self._secondary_key,
                    is_karaoke=self._exclusive_is_karaoke,
                    is_karaoke_curated=self._exclusive_is_karaoke_curated,
                    is_bv=self._exclusive_is_bv,
                    stem_count=self._exclusive_stem_count,
                )
                if name is None:
                    name = _exclusive_name_from_settings(
                        self.settings, self._primary_key, self._secondary_key
                    )
                else:
                    _persist_exclusive_choice(
                        self.settings, self._primary_key, self._secondary_key, name
                    )
                set_combo_value(self._exclusive_row, name)
```

In `persist_to_settings` (currently lines 574-583), replace the `"exclusive"` branch:

```python
        if self.mode == "exclusive":
            name = get_combo_value(self._exclusive_row) or _TOGGLE_ALL
            _persist_exclusive_choice(
                self.settings, self._primary_key, self._secondary_key, name
            )
            self.settings.process.stem_focus = _stem_focus_for_choice(
                name,
                primary_stem=self._exclusive_primary,
                secondary_stem=self._exclusive_secondary,
                primary_key=self._primary_key,
                secondary_key=self._secondary_key,
                is_karaoke=self._exclusive_is_karaoke,
                is_karaoke_curated=self._exclusive_is_karaoke_curated,
                is_bv=self._exclusive_is_bv,
                stem_count=self._exclusive_stem_count,
            )
```

- [ ] **Step 5: Update the `_configure_save_stems` call site**

In `ui/views/base.py`, in `_configure_save_stems` (currently lines 318-328):

```python
    def _configure_save_stems(self, model: typing.Any) -> None:
        """Default: exclusive export filter for <=2-stem / VR-style models."""
        self.save_stems.configure_exclusive(
            primary_stem=self._resolved_primary_stem,
            secondary_stem=self._resolved_secondary_stem,
            primary_key=self.primary_only_key,
            secondary_key=self.secondary_only_key,
            has_model=True,
            stem_label_overrides=stem_display_overrides(model),
            export_semantics_note=recommended_export_note(model),
            is_karaoke=bool(getattr(model, "is_karaoke", False)),
            is_karaoke_curated=bool(getattr(model, "is_karaoke_curated", False)),
            is_bv=bool(getattr(model, "is_bv_model", False)),
            stem_count=2,
        )
```

`stem_count=2` is hardcoded because `_configure_save_stems`'s base implementation (per its own docstring) is only ever reached for <=2-stem models — `MDXView` and `DemucsView` both route anything with more stems to `configure_subset`/`configure_demucs` instead (see the spec's data-flow section for the exact call-site trace).

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_stem_only -v`
Expected: all PASS, including every new `stem_focus` test from Step 1.

- [ ] **Step 7: Run the full existing suite**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 8: Type-check and commit**

Run: `.venv/bin/python -m basedpyright ui/widgets/stem_only.py ui/views/base.py tests/test_stem_only.py`
Expected: 0 errors.

```bash
git add ui/widgets/stem_only.py ui/views/base.py tests/test_stem_only.py
git commit -m "Anchor the 2-stem exclusive export choice to a stable stem identity.

sync_from_settings/persist_to_settings now read/write process.stem_focus
(an ensemble bucket tag) instead of trusting is_primary_stem_only across a
model switch. Fixes the reported bug: switching between two 2-stem models
that disagree about which stem is "primary" no longer silently flips which
file gets exported. Falls back to today's boolean-only behavior until the
user makes their first pick under the new mechanism."
```

---

### Task 8: Stem-semantics audit script

**Files:**
- Create: `scripts/stem_semantics_audit.py`
- Test: `tests/test_stem_semantics_audit.py`

**Interfaces:**
- Consumes: `resolve_karaoke_confidence` (Task 4), `confident_stem_bucket` (Task 6), `scripts.model_probe.iter_catalogue_targets`/`_fetch_config`/`_cache_dir` (existing).
- Produces: `scripts.stem_semantics_audit.main(argv=None) -> int`, runnable as `python scripts/stem_semantics_audit.py [--json PATH] [--guessed-only]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stem_semantics_audit.py`:

```python
"""CLI tests for the stem-semantics audit script. No network -- catalogue
walking and config fetching are patched; only the script's own logic
(sorting, table rendering, JSON output shape) is under test."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location(
    "stem_semantics_audit",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "stem_semantics_audit.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
stem_semantics_audit = importlib.util.module_from_spec(_SPEC)
sys.modules["stem_semantics_audit"] = stem_semantics_audit
_SPEC.loader.exec_module(stem_semantics_audit)


def _entry(entry_id: str, *, curated: bool, karaoke: bool = True) -> "stem_semantics_audit.StemSemanticsEntry":
    return stem_semantics_audit.StemSemanticsEntry(
        entry_id=entry_id,
        label=entry_id,
        stems=["vocals", "other"],
        is_karaoke=karaoke,
        is_karaoke_curated=curated,
        is_bv=False,
        buckets=["Vocals", "Instrumental"],
    )


class RenderTableTests(unittest.TestCase):
    def test_includes_confidence_and_buckets(self) -> None:
        table = stem_semantics_audit.render_table([_entry("a", curated=True)])
        self.assertIn("a", table)
        self.assertIn("curated", table)
        self.assertIn("Vocals", table)

    def test_marks_errors(self) -> None:
        entry = stem_semantics_audit.StemSemanticsEntry(
            entry_id="bad", label="bad", error="config unreadable"
        )
        table = stem_semantics_audit.render_table([entry])
        self.assertIn("ERROR", table)
        self.assertIn("config unreadable", table)


class MainCliTests(unittest.TestCase):
    def test_json_output_is_written_to_the_given_path(self) -> None:
        entries = [_entry("guessed", curated=False), _entry("curated", curated=True)]
        with patch.object(stem_semantics_audit, "_iter_entries", return_value=iter(entries)):
            with tempfile.TemporaryDirectory() as tmp:
                json_path = os.path.join(tmp, "out.json")
                exit_code = stem_semantics_audit.main(["--json", json_path])
                self.assertEqual(exit_code, 0)
                with open(json_path) as f:
                    data = json.load(f)
                self.assertEqual(len(data), 2)
                self.assertIn("is_karaoke_curated", data[0])

    def test_guessed_confidence_sorted_first(self) -> None:
        entries = [_entry("curated", curated=True), _entry("guessed", curated=False)]
        with patch.object(stem_semantics_audit, "_iter_entries", return_value=iter(entries)):
            with tempfile.TemporaryDirectory() as tmp:
                json_path = os.path.join(tmp, "out.json")
                stem_semantics_audit.main(["--json", json_path])
                with open(json_path) as f:
                    data = json.load(f)
                self.assertEqual(data[0]["entry_id"], "guessed")
                self.assertEqual(data[1]["entry_id"], "curated")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_stem_semantics_audit -v`
Expected: FAIL — `scripts/stem_semantics_audit.py` doesn't exist yet (`FileNotFoundError` or `ImportError` from the `importlib` loader).

- [ ] **Step 3: Write the script**

Create `scripts/stem_semantics_audit.py`:

```python
#!/usr/bin/env python3
"""Audit is_karaoke/is_bv confidence and resolved stem buckets across the
mvsepless catalogue. For human review, not a pass/fail gate -- see
docs/superpowers/specs/2026-08-09-stem-export-semantics-design.md.

Usage:
    python scripts/stem_semantics_audit.py                    # print a table
    python scripts/stem_semantics_audit.py --guessed-only      # only the risk surface
    python scripts/stem_semantics_audit.py --json /tmp/out.json
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class StemSemanticsEntry:
    entry_id: str
    label: str
    stems: List[str] = field(default_factory=list)
    is_karaoke: bool = False
    is_karaoke_curated: bool = False
    is_bv: bool = False
    buckets: List[str] = field(default_factory=list)
    error: str = ""


def _entry_for_target(target: Any, catalogue_entry: dict) -> StemSemanticsEntry:
    from core.model_data import load_mdx_c_config
    from core.model_stem_semantics import confident_stem_bucket, resolve_karaoke_confidence
    from scripts.model_probe import _cache_dir, _fetch_config

    try:
        config_path = _fetch_config(target.config_url, _cache_dir())
        config = load_mdx_c_config(config_path)
    except Exception as exc:  # noqa: BLE001 - one bad entry must not abort the audit
        return StemSemanticsEntry(entry_id=target.entry_id, label=target.label, error=str(exc))

    training = config.get("training") or {}
    stems = [str(s) for s in (training.get("instruments") or [])]
    is_bv = bool(catalogue_entry.get("is_bv_model"))
    is_karaoke, is_curated = resolve_karaoke_confidence(
        model_data=catalogue_entry,
        model_name=target.label,
        config_yaml=target.config_url,
        weight_basename=target.checkpoint_url,
    )
    buckets = [
        confident_stem_bucket(
            stem,
            stem_count=len(stems) or 2,
            is_karaoke=is_karaoke,
            is_karaoke_curated=is_curated,
            is_bv=is_bv,
        )
        for stem in stems
    ]
    return StemSemanticsEntry(
        entry_id=target.entry_id,
        label=target.label,
        stems=stems,
        is_karaoke=is_karaoke,
        is_karaoke_curated=is_curated,
        is_bv=is_bv,
        buckets=buckets,
    )


def _iter_entries(*, guessed_only: bool = False) -> Iterator[StemSemanticsEntry]:
    from core.mvsepless_catalog import load_mvsepless_models
    from scripts.model_probe import iter_catalogue_targets

    catalogue = load_mvsepless_models() or {}
    for target in iter_catalogue_targets(catalogue, unsupported_only=False):
        entry = catalogue.get(target.entry_id) or {}
        result = _entry_for_target(target, entry)
        if guessed_only and result.is_karaoke_curated:
            continue
        yield result


def render_table(entries: List[StemSemanticsEntry]) -> str:
    lines = []
    for e in entries:
        if e.error:
            lines.append(f"{e.entry_id:40s} ERROR={e.error}")
            continue
        confidence = "curated" if e.is_karaoke_curated else "guessed"
        lines.append(
            f"{e.entry_id:40s} karaoke={e.is_karaoke!s:5s} ({confidence:7s}) "
            f"bv={e.is_bv!s:5s} stems={e.stems} buckets={e.buckets}"
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument(
        "--guessed-only",
        action="store_true",
        help="Only show entries whose is_karaoke came from a name guess, not curated metadata.",
    )
    args = parser.parse_args(argv)

    entries = list(_iter_entries(guessed_only=args.guessed_only))
    entries.sort(key=lambda e: e.is_karaoke_curated)  # guessed (False) sorts first

    print(render_table(entries))
    if args.json_path:
        with open(args.json_path, "w") as f:
            json.dump([asdict(e) for e in entries], f, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_stem_semantics_audit -v`
Expected: all PASS.

- [ ] **Step 5: Smoke-test the real script against one live entry (manual, not part of the automated suite)**

Run: `.venv/bin/python scripts/stem_semantics_audit.py --json /tmp/stem_semantics_audit.json` and let it run against the real catalogue (this does hit the network, unlike the unit tests above — that's expected and matches `model_probe.py`'s own local-only sweep pattern). Confirm it prints a table without crashing and that `/tmp/stem_semantics_audit.json` contains valid JSON. This step has no pass/fail assertion beyond "doesn't crash" — its purpose is confirming the real catalogue-walking wiring works, which the mocked unit tests above don't exercise.

- [ ] **Step 6: Run the full existing suite**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 7: Type-check and commit**

Run: `.venv/bin/python -m basedpyright scripts/stem_semantics_audit.py tests/test_stem_semantics_audit.py`
Expected: 0 errors.

```bash
git add scripts/stem_semantics_audit.py tests/test_stem_semantics_audit.py
git commit -m "Add scripts/stem_semantics_audit.py for reviewing karaoke-confidence data.

Walks the mvsepless catalogue and reports, per model: raw stems, whether
is_karaoke came from curated metadata or a name guess, is_bv, and the
resolved bucket for each stem. Human review tool, not a CI gate -- guessed-
confidence entries sort first since they're the actual risk surface."
```

---

### Task 9: Final verification

**Files:** None modified — this task is a checkpoint, not a code change.

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -30`
Expected: `OK`, with the skip count matching what it was before this plan started (GTK-display-dependent tests skip identically in both environments).

- [ ] **Step 2: Run basedpyright project-wide**

Run: `.venv/bin/python -m basedpyright`
Expected: `0 errors, 0 warnings, 0 notes`.

- [ ] **Step 3: Manually verify the fix in the running app**

Per the `run` skill: launch the app, select a 2-stem model where vocals is primary, pick "Instrumental Only," then switch to a different 2-stem model where the instrumental happens to be the *secondary* stem (e.g. two MDX-C models with opposite `target_instrument` values). Confirm the Save Stems summary still reads "Instrumental" after the switch, and that `settings.json`'s `process.stem_focus` reflects the chosen bucket tag (not a raw stem name).

- [ ] **Step 4: Confirm no stray debug output or TODOs were left behind**

Run: `git diff main --stat` (or the equivalent against whatever base this plan branched from) and skim each changed file's diff once more for stray `print()` calls, commented-out code, or anything that doesn't match what this plan specified.
