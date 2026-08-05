# Mel-Band skip_connection + SCNet Masked/Tran

**Date:** 2026-08-05  
**Status:** Approved for planning  
**Scope:** Unblock mvsepless Mel-Band 4-stem `skip_connection` models, port SCNet Masked and SCNet Tran, verify with probe + short CLI smoke downloads.

## Goals

1. Catalogue entries that need Mel-Band `skip_connection: true` become downloadable and runnable.
2. `scnet_masked` and `scnet_tran` model types become downloadable and runnable through the existing MDX-C / Roformer inference path.
3. Ports are fully typed to the same standard as `ml/scnet_src/scnet.py` and the rest of `ml/` (no untyped MSST paste).
4. Verification: unit tests + `model_probe --entry … --check-keys` → `buildable`, then download one checkpoint per family and CLI-smoke separate a short clip.

## Non-goals

- SCNet unofficial, Windowed Sink Attention Mel-Band, BS Conformer, Medley-Vox, or other unsupported catalogue classes.
- SDR / quality claims.
- UI redesign beyond Download Center support flags and arch labels.
- Making CI download multi-hundred-MB weights.

## Background

- Mel-Band yaml (e.g. `mbr_syhft_4stem`) sets `skip_connection: true`. Our `MelBandRoformer` does not accept the kwarg, so `_filter_init_kwargs` drops it (`config-ignored`). Those entry ids are denied in `core/mvsepless_catalog.py`.
- MSST implements skip as: before each axial block, sum all stored outputs from earlier layers; after the block, store the new `x`. Same pattern exists on MSST `BSRoformer`.
- SCNet Masked is a separate MSST class (`models/scnet/scnet_masked.py`): same SD/SU shell as SCNet, plus frequency `pos_embed_f` and a final `mask_layer` applied as `mixture * mask`. Yaml **model** kwargs match plain SCNet — no shape discriminator.
- SCNet Tran (`scnet_tran.py`) replaces the dual-path RNN separation net with dual-path Transformers. Yaml adds `tran_*` keys (`tran_depth`, `tran_rotary_embedding_dim`, …) — discriminable from config alone.
- MSST selects the class via CLI/`training.model_type` string. This fork selects MDX-C nets via yaml heuristics in `engines/mdx._build_mdx_c_model` (and arch labels in `core/mdx_c_registry.infer_mdx_c_architecture`).

## Architecture

Three ports, all consumed by the existing MDX-C path:

| Piece | Location | Behavior |
|---|---|---|
| Mel/BS skip | `ml/mel_band_roformer.py`, `ml/bs_roformer.py` | Accept `skip_connection: bool = False`; when true, residual-sum prior block stores (MSST semantics). |
| SCNet Masked | `ml/scnet_src/scnet_masked.py`, re-export `ml/scnet.py` | Typed port; `pos_embed_f` + `mask_layer`. |
| SCNet Tran | `ml/scnet_src/scnet_tran.py`, re-export `ml/scnet.py` | Typed port; `tran_*` ctor args; dual-path Transformer separation. |

### Build dispatch (order matters)

In `_build_mdx_c_model` (and mirrored for dialog arch inference):

1. If `model:` has Tran markers (`tran_depth`, `tran_rotary_embedding_dim`, or equivalent `tran_*` set) → **SCNetTran**.
2. Else if SCNet-shaped (`band_SR` / `sources`):
   - If `state_dict_keys` contain `mask_layer` / `pos_embed_f` (HyperACE-style pre-load), **or** an explicit Masked hint from catalogue `model_type=scnet_masked` when keys are unavailable → **SCNetMasked**.
   - Else → plain **SCNet**.
3. Existing Mel-Band (`num_bands`), BS-Roformer (`freqs_per_bands`), Bandit branches unchanged.

Unrecognized-model dialog labels: `SCNet`, `SCNet Masked`, `SCNet Tran` as appropriate.

### Catalogue

- Add `scnet_masked` and `scnet_tran` to `_SUPPORTED_MODEL_TYPES` (and keep list/arch maps).
- Remove from `_UNSUPPORTED_MODEL_TYPES`: `scnet_masked`, `scnet_tran`.
- Remove Mel-Band skip ids from `_UNSUPPORTED_ENTRY_IDS`:  
  `mbr_syhft_4stem`, `mbr_syhft_4stem2`, `mbr_4stemlarge1_aname`, `mbr_4stemlarge2_aname`, `mbr_4stemxl1_aname`.
- Update `docs/models.md` unsupported table and any probe notes that treat `skip_connection` as deliberately dropped once Mel/BS accept and implement it.

## Data flow

Unchanged outer pipeline: mvsepless → Download Center → checkpoint + yaml → `register_mdx_c_checkpoint` → hash map → `assemble_model` → `_build_mdx_c_model` → `SeperateMDXC`.

**Masked without weights at register time:** registration does not load checkpoints. Prefer:

1. Catalogue conversion / registration may persist a Masked hint when `model_type=scnet_masked` (only if a natural home already exists in params/hash map; do not invent a parallel registry).
2. At engine build, HyperACE already loads checkpoint keys before constructing the net — use the same hook for Masked key detection.
3. `model_probe --entry` must pass catalogue `model_type` into the build so Masked is not mis-instantiated as plain SCNet when probing without a local ckpt; `--check-keys` then confirms the Masked parameter names.

Wrong family still surfaces as load `key-mismatch` / forward failure via existing paths — do not silently drop `skip_connection` or `tran_*` once the target class accepts them.

Plain SCNet-shaped yaml with no Masked hint and no keys continues to build plain SCNet (current behavior).

## Typing requirements

No implementation shortcuts:

- Ports match `ml/scnet_src/scnet.py`: `from __future__ import annotations`, full parameter and return annotations, typed config aliases where SCNet already uses them.
- Do not leave MSST’s untyped `def forward(self, x):` / unannotated `__init__` bodies in tree.
- Reuse shared pieces (`SeparationNet`, Attend/rotary where Tran needs them, STFT device helpers) at typed call sites.
- Mel/BS: `skip_connection: bool = False`; forward remains `Tensor`-annotated.
- New tests and probe spies stay `reportMissingParameterType`-clean.
- basedpyright must pass on touched `ml/`, `engines/`, `core/`, `scripts/`, `tests/`.

## Testing

### Unit (CI)

- Mel/BS: tiny forward with `skip_connection=True` vs `False`; assert the kwarg is accepted (not in `_filter_init_kwargs` drop list for those classes).
- Masked / Tran: module smokes analogous to `tests/test_scnet_module.py` (small dims, short stereo input, shape `(B, stems, C, T)`).
- Catalogue: supported types and Mel-Band skip ids no longer denied; update `tests/test_mvsepless_catalog.py` and `tests/test_model_probe.py`.
- Dispatch: `tran_*` yaml → Tran; SCNet-shaped + Masked keys/hint → Masked; plain SCNet unchanged. Update `tests/test_mdx_c_registry.py` / arch-dispatch tests as needed.

### Probe (developer / this work)

```bash
python scripts/model_probe.py --entry mbr_syhft_4stem --check-keys
python scripts/model_probe.py --entry scnet_masked_small_4stem_zftrubo --check-keys
python scripts/model_probe.py --entry scnet_tran_4stem_zftrubo --check-keys
```

Expect verdict `buildable` (and no `skip_connection` / Masked-only keys among ignored init kwargs for those builds).

### Manual smoke (this work, not CI)

Download one checkpoint per family (prefer smallest Masked: `scnet_masked_small_4stem_zftrubo`). Run:

```bash
python -m core.cli separate <short.wav> -o /tmp/out --method mdx --stems both
```

(or the multi-stem equivalent for 4-stem models) for each registered model. Success = stems written without load/forward errors.

## Success criteria

- [ ] Mel-Band skip and SCNet Masked/Tran ports land typed and typecheck-clean.
- [ ] Catalogue no longer marks the target entries Unsupported for these reasons.
- [ ] Unit tests + basedpyright green.
- [ ] Three probe `--check-keys` runs report `buildable`.
- [ ] Three CLI smoke separations succeed on a short clip after download.

## Open decisions (resolved)

| Decision | Choice |
|---|---|
| Include SCNet Tran? | Yes, same change as Masked. |
| Approaches | Family-complete port (Mel+BS skip, typed Masked/Tran, hybrid dispatch). |
| Verification bar | Probe + download + CLI smoke (not CI weight download). |
| Typing | Full annotations; no shortcut ports. |
