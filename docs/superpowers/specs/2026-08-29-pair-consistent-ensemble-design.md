# Pair-consistent ensemble

**Date:** 2026-08-29  
**Status:** Approved for implementation planning  
**Related:** [Ensemble quality recommendations](2026-08-29-ensemble-quality-recommendations.md)

## Summary

For **dual-stem** ensembles, combine the pair half that members **predict as native**, then derive the other half from the job mix (`mix − combined_native`, or `spec_utils.invert_stem` when `mdx.is_invert_spec` is on). Do not Max Spec one pair role and Min Spec the other independently, and do not stack member leftovers (`complement_of`, Combine Stems, per-member invert).

Identity is reviewed **`StemRoleId`**, not yaml primary, not pair-display order, not filename tags. 4-stem / multi-stem runs are unchanged.

## Goals

1. When a dual-stem pair has a clear native vs leftover split, the ensembled leftover is a mix residual of the combined native, not Min Spec of member leftovers.
2. Member leftover files may still be kept when save-all is on; they are not inputs to the **ensembled** leftover.
3. The combine algorithm is the first token of `ensemble.type` (`primary_algorithm`). The second token is unused while this mode is on.
4. **Recommended (Max / Min)** stays independent Max/Min. This mode is opt-in.

## Non-goals

- 4-stem mix projection / Wiener across drums+bass+other+vocals.
- GCC-PHAT member alignment.
- Changing Max Spec / Soft Spec math.
- Roformer native `(1 − mask) × mix` after the ensembler.
- Changing how members themselves derive stems.
- Inventing roles for raw `StemLiteral` members.

## Identity

Do not read `ModelConfig.primary_stem`, `pair_stems[0]`, or `logical_primary` as “the stem to stack.”

| Name | Meaning | This feature |
| --- | --- | --- |
| Native yaml key (`StemId`) | Engine dict lookup | Unused at combine |
| Reviewed role (`StemRoleId`) | Combine key (`CollectedStem.group_key`) | Stack / residual identity |
| Filename tag | Export spelling | Write path only |
| Pair order (`pair.roles`) | UI labels and today’s Max vs Min **slots** | Not the native/leftover split |
| `logical_primary` | User-facing default stem | Karaoke accompaniment-first; not the stack target |
| `complement_of` / `StemRouteKind.DERIVED` | Leftover recipe on that member | Do not stack; derive once after combine |

Bundled pair order (for UI only):

- `pair.vocals_instrumental`: `vocal.vocals`, `mix.instrumental`
- `pair.karaoke`: `mix.instrumental_with_backing_vocals`, `vocal.lead` (accompaniment **first**)
- `pair.backing_vocals`: `vocal.backing`, `mix.instrumental_with_lead_vocals`
- `pair.center_side`: `spatial.center`, `spatial.side`

### Which role to stack

Inspect each member’s exported `StemRoute`s for the two pair roles.

A route is a **native prediction** when `kind is StemRouteKind.NATIVE` and `complement_of is None`.

Let `native_A` / `native_B` be the members that native-predict pair roles A and B.

| Situation | Action |
| --- | --- |
| `native_A >= 2` and `native_B == 0` | Combine A with `primary_algorithm`; derive B from mix |
| `native_B >= 2` and `native_A == 0` | Combine B; derive A (wide-primary Center/Side) |
| Both roles have `>= 1` native predictor | **No-op**: combine both roles as today (dual-native Center/Side, mixed voc-primary + inst-primary) |
| Flag on but neither side has two native predictors | **No-op**; keep today’s combiner (including insufficient-member errors) |
| 4-stem / `mode.multi_stem` | **No-op** |
| Raw `StemLiteral` on a pair role | That member does not count as a native predictor for a reviewed role |

Karaoke members that native-predict `vocal.lead` and derive accompaniment are the first row: stack Lead, residual is Instrumental with Backing Vocals — even though pair order and `logical_primary` put accompaniment first.

Inst-primary voc/inst ensembles that only native-predict `mix.instrumental` stack Instrumental and derive Vocals. Mixed voc-primary + inst-primary ensembles hit the dual-native row and stay independent.

`pair.center_side` uses the same table. Single-target Center models (`complement_of: spatial.center` on Side) derive Side. Dual-native `mid|side` / `center|wide` members keep both combines.

### Stem focus

Apply `_filter_final_collected_stems` as today, then:

- Focus is only the stacked role: combine and write that file; skip the residual.
- Focus is only the leftover role: combine the native **in memory** (do not write the native export), write the residual under the leftover filename tag.
- Empty focus / both roles: write combined native and residual.

### Save-all members

Members still write their own native **and** leftover files. Only the **ensembled** leftover uses the mix residual.

## Settings

- `ensemble.derive_complement_from_mix: bool = False`
- Flat key `is_derive_complement_from_mix` → `("ensemble", "derive_complement_from_mix")`
- CLI: `--set ensemble.derive_complement_from_mix=true` through `SettingsResolver`
- Do not encode this mode as a fake Min Spec atom. `ensemble.type` stays `Atom/Atom`; the boolean is the switch.
- No settings schema version bump: omitted key coerces to false.

While the flag is on and a plan exists, **combine always uses `primary_algorithm`** (first token). That way Recommended Max/Min plus the switch still Max Spec the native instead of Min Spec karaoke lead (pair slot 1).

### Preset

New preset label **Pair-consistent (native / mix residual)** (`PAIR_CONSISTENT_PRESET`).

- Selecting it sets `derive_complement_from_mix=True` and `ensemble.type` to `Max Spec/Max Spec` (second atom unused).
- Selecting Recommended / Full Max / … sets the flag **false** and today’s atom pair.
- `preset_for_state(primary, secondary, *, derive_complement_from_mix)` returns the new preset only when the flag is on **and** the atoms are Max Spec/Max Spec; flag on with other atoms is Custom.
- `pair_for_preset` for the new preset returns `(MAX_SPEC, MAX_SPEC)` and the UI also sets the flag.

Saved ensemble JSON grows `derive_complement_from_mix` (default false on legacy documents). Curated recipes stay unchanged.

## Dual-stem recipe (when a plan exists)

1. Collect member waveforms for the **stacked role** (`CollectedStem.group_key`).
2. Combine with `primary_algorithm` (`ensemble_inputs`, including wav-ensemble when that atom allows it).
3. Residual mix is `FileState.decoded_mix` (same PCM members used). Do not re-decode the path.
4. Shape-match mix and combined native (`spec_utils.to_shape` / the same layout as `derive_mdx_complement`).
5. Leftover =
   - `mdx.is_invert_spec` off: waveform `mix − combined_native` (same as `derive_mdx_complement` time path).
   - `mdx.is_invert_spec` on: `spec_utils.invert_stem(mix, combined_native)` (generic 2048/1024).
6. Write leftover with the leftover role’s **filename tag**. Do not run `ensemble_inputs` on member leftover arrays.

Members may still invert their own leftovers during the file pass; those files are unused for the ensembled leftover.

If fewer than two native contributors exist, do not take this path.

## UI

Placement is in **Ensemble options** (`_build_ensemble_group` in `ui/ensemble/window.py`), not in **Advanced ensemble options**. That expander stays save-all / append name / Ensemble waveforms.

Order in Ensemble options, after **Algorithm preset**:

1. Switch **Derive complement from mix** (`Adw.SwitchRow`), bound to `ensemble.derive_complement_from_mix`.
2. Existing **Primary algorithm** combo.
3. Existing **Secondary algorithm** combo.

Hide the switch when `_ensemble_is_multi_or_four()` (4-stem / multi-stem already hide the preset and secondary rows). Do not put a second copy of the control on Processing or in Member model options.

- When the flag is on and a plan can be computed from the selected pair + members, retitle the first algorithm row to `{stacked role display} algorithm` and the second to `{leftover display} (from mix)`; disable the second row.
- When the flag is on but the plan is a no-op (dual-native members), keep both algorithm rows enabled as today and subtitle that independent combine is in effect.
- Spectral inversion help (`mdx.is_invert_spec` on the MDX/shared row): after ensemble combine, invert is the same WAV-level `invert_stem` as MDX leftovers.

## Tests

- Voc/inst, two voc-primary members, flag on, invert off: ensembled instrumental equals mix − combined vocals, not Min Spec of member instrumentals.
- Karaoke: stack `vocal.lead`, leftover filename tag is Instrumental with Backing Vocals.
- Dual-native Center/Side: flag on does not skip the Side combine.
- Wide-primary (native Side only): stack Side, derive Center.
- Inst-primary-only voc/inst: stack Instrumental, derive Vocals.
- Mixed voc-primary + inst-primary: no residual; both roles still combine.
- `is_invert_spec` on: `invert_stem(mix, combined_native)`.
- Flag off: Max/Min still ensembles both roles (characterization).
- 4-stem: flag ignored.
- Save-all: member leftover files remain; ensembled leftover is mix-derived.
- Stem focus leftover-only: native export omitted; residual written.
- Saved ensemble round-trip persists the boolean; legacy JSON loads false.

## Follow-ups (not this branch)

See [ensemble quality recommendations](2026-08-29-ensemble-quality-recommendations.md): alignment, Wiener weights, 4-stem projection, combiner hop size.
