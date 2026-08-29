# Pair-Consistent Ensemble Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dual-stem ensembles can combine native-predicted roles and derive the leftover from the job mix, without stacking member complements or redefining Recommended Max/Min.

**Architecture:** A pure planner (`core/ensemble_pair_consistent.py`) looks at member `StemRoute`s and the reviewed pair roles. When the setting is on and exactly one pair role has two-or-more native predictors, `Ensembler` combines that role with `primary_algorithm` and writes the other role via `spec_utils.mix_complement` on `FileState.decoded_mix`. Dual-native pairs, 4-stem, and raw literals stay on today’s per-role combine.

**Tech Stack:** Python 3.12, nested `Settings`, `StemRoleId` / `StemRoute`, `ml.spec_utils`, GTK4 ensemble page, stdlib unittest, scoped Ruff, basedpyright.

**Spec:** [docs/superpowers/specs/2026-08-29-pair-consistent-ensemble-design.md](../specs/2026-08-29-pair-consistent-ensemble-design.md)

## Global Constraints

- Combine by reviewed `StemRoleId` (`CollectedStem.group_key`). Never stack on yaml `primary_stem`, pair-display order, `logical_primary`, or filename tags.
- `ensemble.derive_complement_from_mix` defaults false. Do not change Recommended Max/Min.
- While the flag is on and a plan exists, combine uses `primary_algorithm` (first token of `ensemble.type`). The second atom is unused.
- Dual-native pairs (both roles have ≥1 native predictor) are a no-op even when the flag is on.
- 4-stem / `mode.multi_stem` ignore the flag.
- Residual mix is `FileState.decoded_mix`. Do not re-decode the input path.
- Core must not import `engines` (torch). Residual math lives in `ml/spec_utils.py`; `derive_mdx_complement` may call it.
- Do not invent roles for `StemLiteral` members.
- stdlib unittest, scoped Ruff/format, basedpyright on touched files. No unrestricted `ruff check --fix`.
- Stage explicit paths only. Do not commit settings, caches, weights, or `.uvr-runtime/`.

## File map

- Create: `core/ensemble_pair_consistent.py` — `PairConsistentPlan`, `resolve_pair_consistent_plan`, `is_native_pair_output`
- Create: `tests/test_ensemble_pair_consistent.py` — planner, residual, ensembler, hook wiring
- Modify: `core/ensemble_algorithms.py` — `PAIR_CONSISTENT_PRESET`, `preset_for_state`, row titles
- Modify: `core/settings/model.py`, `defaults.py`, `flat_map.py`, `coerce.py` — new bool
- Modify: `ml/spec_utils.py` — `mix_complement`; factor combine-without-write if needed
- Modify: `engines/mdx_c.py` — `derive_mdx_complement` delegates to `mix_complement`
- Modify: `core/ensembler.py` — combine-to-array + write residual
- Modify: `core/run_hooks.py` — collect member routes, apply plan, pass mix
- Modify: `core/ensemble_service.py` — persist/load/apply the bool
- Modify: `cli/job.py` — preset provenance includes the new path
- Modify: `ui/ensemble/window.py`, `ui/help_text.py` — switch in Ensemble options (not Advanced), disable leftover algorithm row
- Modify: `tests/test_ensemble_algorithms.py`, `tests/test_ensemble_ui_helpers.py`, `tests/test_saved_ensembles.py`, `tests/test_run_hooks.py`

---

### Task 1: Native vs leftover planner

**Files:**

- Create: `core/ensemble_pair_consistent.py`
- Test: `tests/test_ensemble_pair_consistent.py`

**Interfaces:**

- Consumes: `StemRoleId`, `StemLiteral`, `StemRoute`, `StemRouteKind` from `core.stems` / `core.stem_roles`
- Produces:

```python
@dataclass(frozen=True, slots=True)
class PairConsistentPlan:
    stacked_role: StemRoleId
    leftover_role: StemRoleId

def is_native_pair_output(route: StemRoute) -> bool: ...

def resolve_pair_consistent_plan(
    pair_roles: tuple[StemRoleId, StemRoleId],
    member_routes: Sequence[Sequence[StemRoute]],
) -> PairConsistentPlan | None: ...
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ensemble_pair_consistent.py
from __future__ import annotations

import unittest

from core.ensemble_pair_consistent import (
    PairConsistentPlan,
    resolve_pair_consistent_plan,
)
from core.stem_roles import StemLiteral, StemRoleId
from core.stems import StemId, StemRoute, StemRouteKind


VOCALS = StemRoleId("vocal.vocals")
INST = StemRoleId("mix.instrumental")
LEAD = StemRoleId("vocal.lead")
KARAOKE_INST = StemRoleId("mix.instrumental_with_backing_vocals")
CENTER = StemRoleId("spatial.center")
SIDE = StemRoleId("spatial.side")


def _native(role: StemRoleId, key: str) -> StemRoute:
    return StemRoute(StemId(key), role, key, key, StemRouteKind.NATIVE)


def _complement(role: StemRoleId, of_role: StemRoleId) -> StemRoute:
    return StemRoute(
        None,
        role,
        str(role),
        str(role),
        StemRouteKind.DERIVED,
        complement_of=of_role,
    )


class ResolvePairConsistentPlanTests(unittest.TestCase):
    def test_voc_primary_members_stack_vocals(self) -> None:
        members = (
            (_native(VOCALS, "vocals"), _complement(INST, VOCALS)),
            (_native(VOCALS, "vocals"), _complement(INST, VOCALS)),
        )
        self.assertEqual(
            resolve_pair_consistent_plan((VOCALS, INST), members),
            PairConsistentPlan(VOCALS, INST),
        )

    def test_karaoke_stacks_lead_not_pair_slot_zero(self) -> None:
        members = (
            (_complement(KARAOKE_INST, LEAD), _native(LEAD, "vocals")),
            (_complement(KARAOKE_INST, LEAD), _native(LEAD, "vocals")),
        )
        plan = resolve_pair_consistent_plan((KARAOKE_INST, LEAD), members)
        self.assertEqual(plan, PairConsistentPlan(LEAD, KARAOKE_INST))

    def test_dual_native_center_side_is_noop(self) -> None:
        members = (
            (_native(CENTER, "mid"), _native(SIDE, "side")),
            (_native(CENTER, "mid"), _native(SIDE, "side")),
        )
        self.assertIsNone(resolve_pair_consistent_plan((CENTER, SIDE), members))

    def test_center_only_models_derive_side(self) -> None:
        members = (
            (_native(CENTER, "center"), _complement(SIDE, CENTER)),
            (_native(CENTER, "center"), _complement(SIDE, CENTER)),
        )
        self.assertEqual(
            resolve_pair_consistent_plan((CENTER, SIDE), members),
            PairConsistentPlan(CENTER, SIDE),
        )

    def test_wide_primary_stacks_side(self) -> None:
        members = (
            (_complement(CENTER, SIDE), _native(SIDE, "wide")),
            (_complement(CENTER, SIDE), _native(SIDE, "wide")),
        )
        self.assertEqual(
            resolve_pair_consistent_plan((CENTER, SIDE), members),
            PairConsistentPlan(SIDE, CENTER),
        )

    def test_mixed_voc_and_inst_primary_is_noop(self) -> None:
        members = (
            (_native(VOCALS, "vocals"), _complement(INST, VOCALS)),
            (_complement(VOCALS, INST), _native(INST, "instrumental")),
        )
        self.assertIsNone(resolve_pair_consistent_plan((VOCALS, INST), members))

    def test_raw_literal_does_not_count_as_native_role(self) -> None:
        raw = StemRoute(
            StemId("Vocals"),
            StemLiteral("Vocals"),
            "Vocals",
            "Vocals",
            StemRouteKind.NATIVE,
        )
        members = ((raw, _complement(INST, VOCALS)), (_native(VOCALS, "vocals"),))
        self.assertIsNone(resolve_pair_consistent_plan((VOCALS, INST), members))

    def test_one_native_predictor_is_noop(self) -> None:
        members = ((_native(VOCALS, "vocals"), _complement(INST, VOCALS)),)
        self.assertIsNone(resolve_pair_consistent_plan((VOCALS, INST), members))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_ensemble_pair_consistent -v`

Expected: FAIL with `ModuleNotFoundError: core.ensemble_pair_consistent`

- [ ] **Step 3: Implement the planner**

```python
# core/ensemble_pair_consistent.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from core.stem_roles import StemRoleId
from core.stems import StemRoute, StemRouteKind


@dataclass(frozen=True, slots=True)
class PairConsistentPlan:
    stacked_role: StemRoleId
    leftover_role: StemRoleId


def is_native_pair_output(route: StemRoute) -> bool:
    return (
        isinstance(route.role, StemRoleId)
        and route.kind is StemRouteKind.NATIVE
        and route.complement_of is None
    )


def resolve_pair_consistent_plan(
    pair_roles: tuple[StemRoleId, StemRoleId],
    member_routes: Sequence[Sequence[StemRoute]],
) -> PairConsistentPlan | None:
    role_a, role_b = pair_roles
    native_a = 0
    native_b = 0
    for routes in member_routes:
        saw_a = False
        saw_b = False
        for route in routes:
            if not is_native_pair_output(route):
                continue
            if route.role == role_a:
                saw_a = True
            elif route.role == role_b:
                saw_b = True
        native_a += int(saw_a)
        native_b += int(saw_b)
    if native_a >= 2 and native_b == 0:
        return PairConsistentPlan(role_a, role_b)
    if native_b >= 2 and native_a == 0:
        return PairConsistentPlan(role_b, role_a)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_ensemble_pair_consistent -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/ensemble_pair_consistent.py tests/test_ensemble_pair_consistent.py
git commit -m "$(cat <<'EOF'
feat: plan pair-consistent ensemble from native stem roles

EOF
)"
```

---

### Task 2: Settings boolean

**Files:**

- Modify: `core/settings/model.py` (`EnsembleSettings`)
- Modify: `core/settings/defaults.py` (`default_ensemble`)
- Modify: `core/settings/flat_map.py`
- Modify: `core/settings/coerce.py` (`_BOOL_FIELDS`)
- Test: `tests/test_ensemble_pair_consistent.py` (add a class)

**Interfaces:**

- Consumes: existing `Settings` / `coerce_field` / `set_path`
- Produces: `ensemble.derive_complement_from_mix: bool = False`; flat `is_derive_complement_from_mix`

- [ ] **Step 1: Write the failing tests**

```python
class DeriveComplementSettingTests(unittest.TestCase):
    def test_default_is_false(self) -> None:
        from core.settings import Settings

        self.assertFalse(Settings.defaults().ensemble.derive_complement_from_mix)

    def test_set_path_coerces_and_flat_key_round_trips(self) -> None:
        from core.settings import Settings
        from core.settings.access import get_flat, set_flat, set_path

        settings = Settings.defaults()
        set_path(settings, "ensemble.derive_complement_from_mix", "true")
        self.assertTrue(settings.ensemble.derive_complement_from_mix)
        self.assertTrue(get_flat(settings, "is_derive_complement_from_mix"))
        set_flat(settings, "is_derive_complement_from_mix", False)
        self.assertFalse(settings.ensemble.derive_complement_from_mix)
```

- [ ] **Step 2: Run the new tests**

Run: `.venv/bin/python -m unittest tests.test_ensemble_pair_consistent.DeriveComplementSettingTests -v`

Expected: FAIL (`EnsembleSettings` has no `derive_complement_from_mix`)

- [ ] **Step 3: Add the field**

On `EnsembleSettings` in `core/settings/model.py`:

```python
derive_complement_from_mix: bool = False
```

In `default_ensemble()`:

```python
"derive_complement_from_mix": False,
```

In `FLAT_TO_PATH`:

```python
"is_derive_complement_from_mix": ("ensemble", "derive_complement_from_mix"),
```

Add `("ensemble", "derive_complement_from_mix")` to `_BOOL_FIELDS` in `core/settings/coerce.py`.

Do not bump `SETTINGS_SCHEMA_VERSION`.

- [ ] **Step 4: Re-run tests**

Run: `.venv/bin/python -m unittest tests.test_ensemble_pair_consistent.DeriveComplementSettingTests -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/settings/model.py core/settings/defaults.py core/settings/flat_map.py core/settings/coerce.py tests/test_ensemble_pair_consistent.py
git commit -m "$(cat <<'EOF'
feat: add ensemble.derive_complement_from_mix setting

EOF
)"
```

---

### Task 3: Preset mapping

**Files:**

- Modify: `core/ensemble_algorithms.py`
- Test: `tests/test_ensemble_algorithms.py` and/or `tests/test_ensemble_ui_helpers.py` (`PresetMappingTests`)

**Interfaces:**

- Consumes: existing `ENSEMBLE_PRESET_PAIRS` / `preset_for_pair` / `pair_for_preset`
- Produces:

```python
PAIR_CONSISTENT_PRESET = "Pair-consistent (native / mix residual)"

def preset_for_state(
    primary: str,
    secondary: str,
    *,
    derive_complement_from_mix: bool = False,
) -> str: ...
```

`pair_for_preset(PAIR_CONSISTENT_PRESET)` returns `(MAX_SPEC, MAX_SPEC)`. Add the label to `ENSEMBLE_PRESET_OPTIONS` after Recommended. Do **not** put it in `ENSEMBLE_PRESET_PAIRS` (that map is atoms-only).

- [ ] **Step 1: Write the failing tests**

```python
def test_pair_consistent_preset_is_flag_plus_max_spec(self) -> None:
    from bundled.constants import MAX_SPEC
    from core.ensemble_algorithms import (
        CUSTOM_PRESET,
        PAIR_CONSISTENT_PRESET,
        RECOMMENDED_PRESET,
        pair_for_preset,
        preset_for_state,
    )

    self.assertEqual(pair_for_preset(PAIR_CONSISTENT_PRESET), (MAX_SPEC, MAX_SPEC))
    self.assertEqual(
        preset_for_state(MAX_SPEC, MAX_SPEC, derive_complement_from_mix=True),
        PAIR_CONSISTENT_PRESET,
    )
    self.assertEqual(
        preset_for_state(MAX_SPEC, MAX_SPEC, derive_complement_from_mix=False),
        "Full Max",
    )
    self.assertEqual(
        preset_for_state(MAX_SPEC, MIN_SPEC, derive_complement_from_mix=True),
        CUSTOM_PRESET,
    )
    self.assertEqual(
        preset_for_state(MAX_SPEC, MIN_SPEC, derive_complement_from_mix=False),
        RECOMMENDED_PRESET,
    )
```

Keep `preset_for_pair(MAX_SPEC, MAX_SPEC)` as Full Max.

- [ ] **Step 2: Run tests**

Run: `.venv/bin/python -m unittest tests.test_ensemble_ui_helpers.PresetMappingTests -v`

Expected: FAIL (`PAIR_CONSISTENT_PRESET` missing). If this module’s `setUpModule` requires GTK, put the tests in `tests/test_ensemble_algorithms.py` instead (GTK-free).

- [ ] **Step 3: Implement**

```python
PAIR_CONSISTENT_PRESET = "Pair-consistent (native / mix residual)"

ENSEMBLE_PRESET_OPTIONS: Tuple[str, ...] = (
    CUSTOM_PRESET,
    RECOMMENDED_PRESET,
    PAIR_CONSISTENT_PRESET,
    FULL_MAX_PRESET,
    SOFT_BLEND_PRESET,
    HYBRID_CLEAN_PRESET,
    MEDIAN_ROBUST_PRESET,
)

def pair_for_preset(preset: Optional[str]) -> Optional[Tuple[str, str]]:
    if not preset or preset == CUSTOM_PRESET:
        return None
    if preset == PAIR_CONSISTENT_PRESET:
        return (_DEFAULT_PRIMARY, _DEFAULT_PRIMARY)
    return ENSEMBLE_PRESET_PAIRS.get(preset)


def preset_for_state(
    primary: str,
    secondary: str,
    *,
    derive_complement_from_mix: bool = False,
) -> str:
    if derive_complement_from_mix:
        if (primary, secondary) == (_DEFAULT_PRIMARY, _DEFAULT_PRIMARY):
            return PAIR_CONSISTENT_PRESET
        return CUSTOM_PRESET
    return preset_for_pair(primary, secondary)
```

- [ ] **Step 4: Run tests**

Expected: PASS, including existing `test_recommended_round_trip`

- [ ] **Step 5: Commit**

```bash
git add core/ensemble_algorithms.py tests/test_ensemble_algorithms.py tests/test_ensemble_ui_helpers.py
git commit -m "$(cat <<'EOF'
feat: add pair-consistent ensemble algorithm preset

EOF
)"
```

---

### Task 4: Shared mix residual

**Files:**

- Modify: `ml/spec_utils.py`
- Modify: `engines/mdx_c.py` (`derive_mdx_complement`)
- Test: `tests/test_ensemble_pair_consistent.py`

**Interfaces:**

- Consumes: `to_shape`, `invert_stem`
- Produces:

```python
def mix_complement(
    mix: np.ndarray,
    stem: np.ndarray,
    *,
    invert_spec: bool = False,
) -> np.ndarray: ...
```

Layout must match today’s `derive_mdx_complement`: `to_shape(stem, mix.shape)` then `invert_stem(mix, shaped)` or `-shaped.T + mix.T`.

- [ ] **Step 1: Write the failing tests**

```python
class MixComplementTests(unittest.TestCase):
    def test_waveform_residual_matches_mdx_time_path(self) -> None:
        import numpy as np
        from ml.spec_utils import mix_complement, to_shape

        rng = np.random.default_rng(1)
        mix = rng.standard_normal((2, 32)).astype(np.float64)
        stem = rng.standard_normal((2, 30)).astype(np.float64)
        shaped = to_shape(stem, mix.shape)
        np.testing.assert_array_equal(
            mix_complement(mix, stem, invert_spec=False),
            -shaped.T + mix.T,
        )

    def test_invert_spec_calls_invert_stem(self) -> None:
        import numpy as np
        from unittest.mock import patch
        from ml.spec_utils import mix_complement

        mix = np.ones((2, 8), dtype=np.float64)
        stem = np.zeros((2, 8), dtype=np.float64)
        sentinel = np.full((8, 2), 7.0)
        with patch("ml.spec_utils.invert_stem", return_value=sentinel) as invert:
            out = mix_complement(mix, stem, invert_spec=True)
        invert.assert_called_once()
        np.testing.assert_array_equal(out, sentinel)
```

- [ ] **Step 2: Run tests**

Run: `.venv/bin/python -m unittest tests.test_ensemble_pair_consistent.MixComplementTests -v`

Expected: FAIL (`mix_complement` missing)

- [ ] **Step 3: Implement and delegate**

Add `mix_complement` next to `invert_stem` in `ml/spec_utils.py`. Change `derive_mdx_complement` to:

```python
from ml import spec_utils

def derive_mdx_complement(...):
    raw_mix = match_frequency_pitch(mix) if match_frequency_pitch is not None else mix
    return spec_utils.mix_complement(
        raw_mix, native_source, invert_spec=bool(invert_spec)
    )
```

Keep `match_frequency_pitch` on the MDX wrapper only; ensembler will pass already-matched `decoded_mix`.

- [ ] **Step 4: Run residual tests plus a focused MDX complement test**

Run:

```bash
.venv/bin/python -m unittest tests.test_ensemble_pair_consistent.MixComplementTests tests.test_mdx_export_routing -v
```

If `test_mdx_export_routing` is too broad, run the invert/complement cases already in that module. Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ml/spec_utils.py engines/mdx_c.py tests/test_ensemble_pair_consistent.py
git commit -m "$(cat <<'EOF'
feat: share mix-minus residual between MDX and ensemble

EOF
)"
```

---

### Task 5: Ensembler combine-to-array and residual write

**Files:**

- Modify: `core/ensembler.py`
- Modify: `ml/spec_utils.py` only if `ensemble_inputs` must return the wave (prefer a `combine_ensemble_waveforms` helper used by both `ensemble_inputs` and the ensembler)
- Test: `tests/test_ensemble_pair_consistent.py`

**Interfaces:**

- Consumes: `PairConsistentPlan`, `mix_complement`, existing member-array gathering in `ensemble_outputs`
- Produces:

```python
def combine_stem_waveforms(
    self,
    stem: CollectedStem,
    *,
    is_multi_stem: bool,
    stem_arrays: ...,
    stem_paths: ...,
) -> np.ndarray: ...

def write_stem_waveform(
    self,
    audio_file_base: str,
    stem: CollectedStem,
    wave: np.ndarray,
) -> str: ...
```

`ensemble_outputs` keeps today’s behaviour when not residual. Do not import `engines`.

When combining under a plan, **always** pass `self.primary_algorithm` (ignore pair slot).

- [ ] **Step 1: Write the failing tests**

Use `object.__new__(Ensembler)` like `tests/test_ensemble_finalization.py`. Two member vocals `(2, 8)` arrays `[1,1,...]` and `[3,3,...]`, Average atom, mix all `4`s:

```python
class EnsemblerResidualTests(unittest.TestCase):
    def test_average_then_mix_minus_not_min_spec_of_leftovers(self) -> None:
        import numpy as np
        from bundled.constants import AUDIO_AVERAGE
        from core.ensembler import CollectedStem, Ensembler
        from core.settings import Settings
        from core.stem_roles import StemRoleId

        vocals = CollectedStem(StemRoleId("vocal.vocals"), "Vocals")
        inst = CollectedStem(StemRoleId("mix.instrumental"), "Instrumental")
        mix = np.full((2, 8), 4.0, dtype=np.float64)
        member_vocals = [
            np.full((2, 8), 1.0, dtype=np.float64),
            np.full((2, 8), 3.0, dtype=np.float64),
        ]
        member_inst = [
            np.full((2, 8), 9.0, dtype=np.float64),
            np.full((2, 8), 0.0, dtype=np.float64),
        ]
        ensembler = object.__new__(Ensembler)
        ensembler.settings = Settings.defaults()
        ensembler.primary_algorithm = AUDIO_AVERAGE
        ensembler.secondary_algorithm = "Min Spec"
        ensembler.pair_stems = (vocals, inst)
        ensembler.is_normalization = False
        ensembler.amplification_threshold = 0.0
        ensembler.is_wav_ensemble = True
        # ... wav_type_set / save_format / paths as in test_ensemble_finalization
        combined = ensembler.combine_stem_waveforms(
            vocals,
            is_multi_stem=False,
            stem_arrays={vocals.group_key: member_vocals},
            stem_paths={},
        )
        leftover = ensembler.mix_residual(mix, combined, invert_spec=False)
        np.testing.assert_allclose(combined, np.full((2, 8), 2.0))
        np.testing.assert_allclose(leftover.T if leftover.shape != mix.shape else leftover, mix - combined)
        # leftover must not equal Min Spec of member_inst
        self.assertFalse(np.allclose(leftover, np.zeros((2, 8))))
```

Adjust shapes to whatever `combine_ensemble_waveforms` actually returns (channel-first vs `.T`). Lock it in the test after the first implementation, matching `mix_complement`.

- [ ] **Step 2: Run tests**

Expected: FAIL (`combine_stem_waveforms` missing)

- [ ] **Step 3: Implement**

Factor the STFT/wave combine out of `ensemble_inputs` so both the writer and `combine_stem_waveforms` share one function. `ensemble_outputs` should call `combine_stem_waveforms` then `write_stem_waveform` so the off-path stays one write.

Add `Ensembler.mix_residual(self, mix, stem, *, invert_spec: bool)` that calls `spec_utils.mix_complement`.

- [ ] **Step 4: Run ensembler tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_ensemble_pair_consistent.EnsemblerResidualTests tests.test_ensemble_finalization tests.test_ensemble_collection -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/ensembler.py ml/spec_utils.py tests/test_ensemble_pair_consistent.py
git commit -m "$(cat <<'EOF'
feat: combine ensemble natives then write a mix residual

EOF
)"
```

---

### Task 6: Hook wiring (mix, member routes, focus)

**Files:**

- Modify: `core/run_hooks.py`
- Test: `tests/test_run_hooks.py`, `tests/test_ensemble_pair_consistent.py`

**Interfaces:**

- Consumes: `resolve_pair_consistent_plan`, `run_export_routes(model)`, `FileState.decoded_mix`, `settings.ensemble.derive_complement_from_mix`, `settings.mdx.is_invert_spec`
- Produces: scratch `ensemble_member_routes: dict[str, tuple[StemRoute, ...]]`; `after_file` takes the residual path when a plan exists

**`after_chunk`:** for each member, store `run_export_routes(model)` under `ensemble_member_routes[member_id]`.

**`after_file` (dual-stem only):**

```python
pair_roles = tuple(stem.role for stem in self.ensemble.pair_stems)
plan = None
if (
    not self.is_multi_stem
    and runner.settings.ensemble.derive_complement_from_mix
    and len(pair_roles) == 2
    and all(isinstance(role, StemRoleId) for role in pair_roles)
):
    plan = resolve_pair_consistent_plan(
        pair_roles,
        tuple(state.scratch.get("ensemble_member_routes", {}).values()),
    )
```

If `plan is None`, keep today’s loop over `combine_steps`.

If `plan` is set:

1. `output_stems = _filter_final_collected_stems(list(self.ensemble.pair_stems), focus)`
2. Find `stacked` / `leftover` CollectedStems by role.
3. `combined = self.ensemble.combine_stem_waveforms(stacked, ...)`
4. If stacked is in `output_stems`: `write_stem_waveform(...)`
5. If leftover is in `output_stems`: `write_stem_waveform(..., mix_residual(state.decoded_mix, combined, invert_spec=runner.settings.mdx.is_invert_spec))`
6. Do not call `ensemble_outputs` on the leftover role.

If focus is leftover-only, skip writing the stacked file.

Save-all member files are already written in the member pass; do not delete them.

- [ ] **Step 1: Write failing hook tests**

Extend `tests/test_run_hooks.py` with a fake ensembler that records `combine_stem_waveforms` / `write_stem_waveform` / `ensemble_outputs` calls. Cases:

- Flag off: `ensemble_outputs` called for both pair stems (characterization).
- Flag on, two voc-primary route lists: `combine_stem_waveforms` once for vocals; `write_stem_waveform` for vocals and instrumental; leftover write uses `decoded_mix`.
- Flag on, 4-stem: `ensemble_outputs` per native (flag ignored).
- Focus `mix.instrumental`: combine vocals, write only instrumental.
- Dual-native routes: `ensemble_outputs` for both Center and Side.

- [ ] **Step 2: Run tests**

Expected: FAIL (no `ensemble_member_routes` / residual path)

- [ ] **Step 3: Implement hook changes**

- [ ] **Step 4: Run**

```bash
.venv/bin/python -m unittest tests.test_run_hooks tests.test_ensemble_pair_consistent tests.test_ensemble_finalization -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/run_hooks.py tests/test_run_hooks.py tests/test_ensemble_pair_consistent.py
git commit -m "$(cat <<'EOF'
feat: derive ensemble leftovers from the decoded mix

EOF
)"
```

---

### Task 7: Saved ensembles and CLI preset apply

**Files:**

- Modify: `core/ensemble_service.py` (`save_ensemble`, `ResolvedEnsemblePreset`, `apply`, `create`)
- Modify: `cli/job.py` (`preset_paths` includes `ensemble.derive_complement_from_mix`)
- Modify: `ui/ensemble/window.py` (`_do_save_ensemble` / `create(...)`)
- Test: `tests/test_saved_ensembles.py`

**Interfaces:**

- Consumes: `settings.ensemble.derive_complement_from_mix`
- Produces: JSON key `derive_complement_from_mix` (bool). Legacy documents without the key load as false.

- [ ] **Step 1: Write failing tests**

```python
def test_derive_complement_round_trips_and_legacy_defaults_false(self) -> None:
    # save_ensemble(..., derive_complement_from_mix=True) → load True
    # legacy JSON without the key → False after resolve/apply
```

- [ ] **Step 2: Run** `tests.test_saved_ensembles -v` — FAIL on missing kwarg

- [ ] **Step 3: Thread the bool through save/load/apply/create and the GUI save helper**

`EnsembleService.apply` must set `settings.ensemble.derive_complement_from_mix`.

- [ ] **Step 4: Re-run** `tests.test_saved_ensembles` plus any CLI ensemble apply test that lists preset paths

- [ ] **Step 5: Commit**

```bash
git add core/ensemble_service.py cli/job.py ui/ensemble/window.py tests/test_saved_ensembles.py
git commit -m "$(cat <<'EOF'
feat: persist pair-consistent ensemble in saved recipes

EOF
)"
```

---

### Task 8: Ensemble page UI and help

**Files:**

- Modify: `ui/ensemble/window.py`
- Modify: `ui/help_text.py`
- Modify: `core/ensemble_algorithms.py` (`algorithm_row_titles`, `ensemble_options_summary`)
- Test: `tests/test_ensemble_ui_helpers.py` (helpers only; no `widget.destroy()`)

**Interfaces:**

- Placement: `Adw.SwitchRow` **Derive complement from mix** in `_build_ensemble_group` (title **Ensemble options**), **after** `preset_row` and **before** `primary_algo_row`. Bind with the same `_set_bool` / `get_flat` pattern as other ensemble switches (`is_derive_complement_from_mix`).
- Do **not** add it to the **Advanced ensemble options** `Adw.ExpanderRow` in `_build_output_group` (that expander stays save-all, append name, Ensemble waveforms).
- Hide the switch when `_ensemble_is_multi_or_four()`.
- `_on_preset_changed`: if Pair-consistent, set flag true and atoms Max/Max; other named presets set flag false
- `_refresh_ensemble_type_values`: `set_combo_value(preset_row, preset_for_state(...))`; when flag on and selected members yield a plan, retitle/disable the secondary algorithm row
- Computing the plan in the UI: map selected model tags through the repo to `run_export_routes` when cheap; if models are not resolved yet, keep generic titles `Primary algorithm` / `Complement (from mix)`

```python
def ensemble_options_summary(..., derive_complement_from_mix: bool = False, leftover_label: str | None = None) -> str:
    if derive_complement_from_mix and not multi_stem:
        right = leftover_label or "mix residual"
        return f"{left} ← {primary_algo} · {right} · {models_bit}"
```

Help strings:

```python
DERIVE_COMPLEMENT_FROM_MIX_HELP = (
    "Combine native stems with the first algorithm, then derive the other "
    "pair file from the mix (mix minus the combined native, or Spectral inversion)."
)
```

Append one sentence to `IS_INVERT_SPEC_HELP`: ensemble leftovers use the same WAV-level invert.

- [ ] **Step 1: Failing helper tests** for `preset_for_state` (already done) plus `ensemble_options_summary` with the flag on showing `mix residual` instead of `← Min Spec`

- [ ] **Step 2: Run helper tests**

- [ ] **Step 3: Wire the switch in `_build_ensemble_group`**

Insert `self.derive_complement_row = make_switch_row("Derive complement from mix", ...)` immediately after `group.add(self.preset_row)` and before `self.primary_algo_row`. Connect `notify::active` with `_set_bool("is_derive_complement_from_mix", ...)`. Dual-stem only: hide the switch when `_ensemble_is_multi_or_four()`. Sync active state in the same load path as the algorithm combos.

- [ ] **Step 4: Run**

```bash
.venv/bin/python -m unittest tests.test_ensemble_ui_helpers tests.test_ensemble_algorithms tests.test_ensemble_pair_consistent -v
```

GTK tests in that module use `require_private_gtk` / the [GTK display-backend convention](../../environment.md#gtk-display-backend-testing). Do not add tests that call `widget.destroy()`.

- [ ] **Step 5: Commit**

```bash
git add ui/ensemble/window.py ui/help_text.py core/ensemble_algorithms.py tests/test_ensemble_ui_helpers.py
git commit -m "$(cat <<'EOF'
feat: expose pair-consistent ensemble in the Ensemble page

EOF
)"
```

---

### Task 9: Types, lint, and spec/docs

**Files:**

- Already-written spec: `docs/superpowers/specs/2026-08-29-pair-consistent-ensemble-design.md`
- Related recs: `docs/superpowers/specs/2026-08-29-ensemble-quality-recommendations.md`
- Touched Python as above

- [ ] **Step 1: basedpyright and ruff on the touched set**

```bash
.venv/bin/python -m basedpyright core/ensemble_pair_consistent.py core/ensemble_algorithms.py core/ensembler.py core/run_hooks.py core/ensemble_service.py core/settings/model.py core/settings/defaults.py core/settings/flat_map.py core/settings/coerce.py ml/spec_utils.py engines/mdx_c.py ui/ensemble/window.py ui/help_text.py cli/job.py tests/test_ensemble_pair_consistent.py
.venv/bin/ruff check core/ensemble_pair_consistent.py core/ensemble_algorithms.py core/ensembler.py core/run_hooks.py core/ensemble_service.py core/settings/model.py core/settings/defaults.py core/settings/flat_map.py core/settings/coerce.py ml/spec_utils.py engines/mdx_c.py ui/ensemble/window.py ui/help_text.py cli/job.py tests/test_ensemble_pair_consistent.py
.venv/bin/ruff format --check core/ensemble_pair_consistent.py core/ensemble_algorithms.py core/ensembler.py core/run_hooks.py core/ensemble_service.py tests/test_ensemble_pair_consistent.py
```

- [ ] **Step 2: Full ensemble-related unittest slice**

```bash
.venv/bin/python -m unittest tests.test_ensemble_pair_consistent tests.test_ensemble_algorithms tests.test_ensemble_collection tests.test_ensemble_finalization tests.test_run_hooks tests.test_saved_ensembles tests.test_ensemble_ui_helpers -v
```

- [ ] **Step 3: Commit remaining docs if they changed**

```bash
git add docs/superpowers/specs/2026-08-29-pair-consistent-ensemble-design.md docs/superpowers/specs/2026-08-29-ensemble-quality-recommendations.md docs/superpowers/plans/2026-08-29-pair-consistent-ensemble.md
git commit -m "$(cat <<'EOF'
docs: specify pair-consistent ensemble against reviewed stem roles

EOF
)"
```

If specs were already committed earlier in the branch, skip unchanged files.

---

## Spec coverage

| Spec requirement | Task |
| --- | --- |
| Stack native `StemRoleId`, not pair slot / yaml primary | 1, 6 |
| Karaoke stacks lead | 1 |
| Dual-native Center/Side no-op | 1, 6 |
| Wide-primary stacks side | 1 |
| Mixed voc/inst-primary no-op | 1 |
| Raw literals ignored | 1 |
| Setting default off | 2 |
| Preset not a fake Min Spec atom | 3 |
| Combine uses `primary_algorithm` | 5, 6 |
| `mix_complement` / invert | 4, 5 |
| `decoded_mix` | 6 |
| Stem focus leftover-only | 6 |
| Save-all members kept | 6 |
| Saved JSON + CLI apply | 7 |
| UI switch + disable leftover row | 8 |
| 4-stem ignored | 6 |
| Recommended unchanged | 2, 3, 6 characterization |

## Placeholder scan

None of TBD / “handle edge cases” / “tests for the above” without code remain in the tasks above.
