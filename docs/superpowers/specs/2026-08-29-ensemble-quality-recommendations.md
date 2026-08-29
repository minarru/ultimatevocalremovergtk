# Ensemble quality recommendations

**Date:** 2026-08-29  
**Status:** Recommendations (not an implementation plan)  
**Related:** [Pair-consistent ensemble](2026-08-29-pair-consistent-ensemble-design.md)

Roformer native invert (`(1 − mask) × mix` in the model STFT) is a separate member-level spec and is not on this branch. It improves member primaries; it does not replace pair-consistent combine for the **final** dual-stem pair.

How this combiner actually works: members are STFT’d at **2048/1024**, then Max/Min/Median/Soft (or waveform Average / Chunk Min). Dual-stem **Recommended** is **Max Spec on the primary and Min Spec on the secondary**. Members are not time-aligned, not weighted, and not forced to sum back to the mix.

## Highest leverage

### 1. Derive the complement after combine (pair-consistent)

Recommended Max/Min means vocals = loudest bin across models and instrumental = quietest. Those two files are not a pair. `mix − combined_vocals` is usually a better instrumental than Min Spec of member instrumentals.

Same idea for 4-stem: combine **natives**, then optional mix-consistency (`mix − vocals`, or project drums+bass+other+vocals onto the mix).

This is the quality win the Roformer-native invert spec left out (that spec is **per member** only). **This is the first feature to implement** — see the pair-consistent design.

### 2. Stop independent Max and Min on a pair

If two algorithms remain, they should be **coupled**: e.g. Max Spec vocals, then instrumental = mix − that, or Min Spec vocals and instrumental = mix − that. Soft Spec / Hybrid Spec on **both** sides is less schizophrenic than Max/Min.

### 3. Wiener / posterior blend instead of hard Max

Max Spec keeps artifacts from the most aggressive member. Soft Spec already weights by magnitude agreement. A Wiener

`Ŝ = mix × Σ|Sᵢ|² / (Σ|Sᵢ|² + |residual|²)`

(or weights from catalogue SDR / a short validation clip) usually beats hard argmax. Per-member **user weights** are the cheap version.

### 4. Align, then combine

VR, Roformer (often hop 441), and Demucs do not share latency. A few ms of skew makes Max Spec pick the leading smear. GCC-PHAT (or the existing `ensemble_for_align` Min Spec align helper) before the combiner is high value.

### 5. Finer combiner STFT

Same issue as `invert_stem`: ~23 ms hops. Hop 256–512, COLA, no `center` length bugs. Does not need to match any one model. Waveform Average / wav-ensemble is already the right path when members are Demucs-like.

## Composition (often bigger than the atom)

### 6. Diverse members, not five Mel-Bands

Max Spec of clones ≈ the clone plus noise. One VR + one Roformer + one Demucs beats three of the same Roformer family.

### 7. Don’t ensemble derived leftovers

Member instrumentals were built with Combine Stems, `mix − stem`, or `invert_stem`. Stacking those files mixes recipes. Combine **vocals** (and other natives); build Instrumental once at the end.

### 8. 4-stem mix projection

After combining drums/bass/other/vocals, scale or Wiener so they sum toward the mix. Independent Max Spec on four stems inflates energy and leaves a hole vs the mix.

### 9. Match operating points

Different Compensate, denoise, pitch, and invert settings on members make the stack a loudness/phase contest. Ensemble-level “same invert / no denoise on members, invert once at the end” is policy, not a new atom.

## Smaller / already half-there

- **Median of magnitude + average phase** (today’s median of real/imag independently is phase-hostile).
- **Max mag / avg phase** is already in the app — often better than Max Spec on vocals.
- **In-memory member buffers** (already used) avoid 16-bit WAV round-trips; keep that as the only path.
- **Don’t Max Spec a 2-member ensemble** — with two models, Average or Soft Spec is less brittle.

## What not to chase

- A second neural ensembler.
- Combining in each model’s native STFT (no shared grid).
- More overlap on the combiner without alignment (smoother artifacts).

## Suggested order

1. Pair-consistent ensemble (this branch): combine primary, then mix-derived secondary.
2. Docs/defaults for diverse members (6) and “don’t stack leftovers” (7) — partly implied by (1).
3. Alignment (4) and Soft/Wiener weights (3).
4. Roformer native invert (separate spec) improves **members**; it does not replace (1) for the **final** pair.
