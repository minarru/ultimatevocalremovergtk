# Mel-Band skip_connection + SCNet Masked/Tran Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Mel-Band `skip_connection` models and SCNet Masked/Tran downloadable and runnable through the existing MDX-C path, with typed ports and probe + CLI smoke verification.

**Architecture:** Port MSST skip residual into Mel/BS Roformer; add typed `SCNetMasked` and `SCNetTran` under `ml/scnet_src/`; dispatch Tran via `tran_*` yaml keys, Masked via checkpoint keys or catalogue `model_type` hint; unblock mvsepless catalogue entries.

**Tech Stack:** Python 3.14, PyTorch, stdlib `unittest`, basedpyright, existing `engines.mdx` / `core.cli` / `scripts.model_probe`.

**Spec:** [docs/superpowers/specs/2026-08-05-melband-skip-scnet-masked-tran-design.md](../specs/2026-08-05-melband-skip-scnet-masked-tran-design.md)

## Global Constraints

- **No tkinter anywhere.** Never import `ui` from `core`, `engines`, `ml`, or `scripts`.
- **Layering:** `ui` → `core` → `engines` → `ml`; `bundled` is read by all.
- **Typing:** Full annotations on every new/edited public function and MSST port — match `ml/scnet_src/scnet.py`. No untyped paste. basedpyright must stay clean on touched roots.
- **Tests are stdlib `unittest`.** Run with `.venv/bin/python -m unittest …`. No pytest.
- **Search with `rg`**, not `grep`.
- **Never** run unscoped `git checkout -- .`, `git restore .`, `git reset --hard`, `git stash`, or `git clean`. Stage explicit paths only; leave `models/MDX_Net_Models/model_data/model_name_mapper.json` unstaged if dirty.
- Upstream `Seperate*` spelling stays.
- Do **not** accept a kwarg without implementing its semantics (or, for `linear_transformer_depth=0` / `use_torch_checkpoint=False`, the MSST no-op path that still wires the True branch correctly).

**Before Task 1:** create a feature branch from current `main`:

```bash
git switch main
git pull --ff-only
git switch -c feat/melband-skip-scnet-masked-tran
```

## File map

| File | Role |
|---|---|
| `ml/mel_band_roformer.py` | Accept/implement `skip_connection`, `use_torch_checkpoint`, `mlp_expansion_factor`, `linear_transformer_depth` (+ linear attn when depth > 0) |
| `ml/bs_roformer.py` | Accept/implement `skip_connection`, `use_torch_checkpoint` |
| `ml/scnet_src/scnet_masked.py` | Typed SCNet Masked port (`SCNetMasked`) |
| `ml/scnet_src/scnet_tran.py` | Typed SCNet Tran port (`SCNetTran`) + dual-path Transformer separation |
| `ml/scnet.py` | Re-export `SCNet`, `SCNetMasked`, `SCNetTran` |
| `engines/mdx.py` | `_build_mdx_c_model` dispatch + optional `model_type_hint`; Masked key helper |
| `core/mdx_c_registry.py` | `infer_mdx_c_architecture` labels for Tran/Masked |
| `core/mvsepless_catalog.py` | Support `scnet_masked` / `scnet_tran`; remove Mel skip deny ids |
| `scripts/model_probe.py` | Pass catalogue `model_type` into build as hint |
| `docs/models.md` | Drop unsupported rows; note ports |
| `tests/test_mel_band_skip.py` | New Mel skip / kwarg acceptance tests |
| `tests/test_bs_roformer_skip.py` | New BS skip tests |
| `tests/test_scnet_module.py` | Extend for Masked + Tran smokes |
| `tests/test_mdx_arch_dispatch.py` | Tran / Masked factory cases |
| `tests/test_infer_mdx_c_architecture.py` | Arch label cases |
| `tests/test_mvsepless_catalog.py` | Supported / no longer denied |
| `tests/test_model_probe.py` | Update skip-entry expectations |

---

### Task 1: MelBandRoformer — accept MSST kwargs and implement skip + checkpoint

**Files:**
- Modify: `ml/mel_band_roformer.py`
- Create: `tests/test_mel_band_skip.py`
- Modify if needed: `ml/mel_band_roformer.py` Transformer for `linear_attn` (mirror `ml/bs_roformer.py` `LinearAttention` / `Transformer`)

**Why four kwargs:** probing `mbr_syhft_4stem` today drops `linear_transformer_depth`, `mlp_expansion_factor`, `skip_connection`, `use_torch_checkpoint`. Any remaining drop → verdict `config-ignored`, not `buildable`.

**Interfaces:**
- Produces: `MelBandRoformer(..., skip_connection: bool = False, use_torch_checkpoint: bool = False, mlp_expansion_factor: int = 4, linear_transformer_depth: int = 0, ...)`
- Forward residual (MSST): before each axial block `for j in range(i): x = x + store[j]`; after block `store[i] = x`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mel_band_skip.py
from __future__ import annotations

import inspect
import unittest

import torch

from engines.mdx import _filter_init_kwargs
from ml.mel_band_roformer import MelBandRoformer


class MelBandSkipTests(unittest.TestCase):
    def _tiny_kwargs(self) -> dict[str, object]:
        return {
            "dim": 8,
            "depth": 2,
            "stereo": True,
            "num_stems": 1,
            "time_transformer_depth": 1,
            "freq_transformer_depth": 1,
            "num_bands": 8,
            "dim_head": 4,
            "heads": 2,
            "flash_attn": False,
            "dim_freqs_in": 65,
            "stft_n_fft": 128,
            "stft_hop_length": 32,
            "stft_win_length": 128,
            "mask_estimator_depth": 1,
            "match_input_audio_length": True,
        }

    def test_msst_kwargs_are_accepted(self) -> None:
        params = inspect.signature(MelBandRoformer.__init__).parameters
        for name in (
            "skip_connection",
            "use_torch_checkpoint",
            "mlp_expansion_factor",
            "linear_transformer_depth",
        ):
            self.assertIn(name, params)
        cfg = {
            "dim": 8,
            "depth": 1,
            "skip_connection": True,
            "use_torch_checkpoint": False,
            "mlp_expansion_factor": 4,
            "linear_transformer_depth": 0,
            "num_bands": 8,
        }
        dropped = [
            k
            for k in cfg
            if k not in _filter_init_kwargs(MelBandRoformer, cfg)
            and k not in ("dim", "depth", "num_bands")  # always kept if accepted
        ]
        # Prefer: nothing from the MSST set is dropped
        filtered = _filter_init_kwargs(MelBandRoformer, {**cfg, "stereo": True})
        for name in (
            "skip_connection",
            "use_torch_checkpoint",
            "mlp_expansion_factor",
            "linear_transformer_depth",
        ):
            self.assertIn(name, filtered)

    def test_skip_connection_forward_shape(self) -> None:
        model = MelBandRoformer(**self._tiny_kwargs(), skip_connection=True)
        model.eval()
        with torch.no_grad():
            out = model(torch.randn(1, 2, 512))
        self.assertEqual(tuple(out.shape)[:2], (1, 2))
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
.venv/bin/python -m unittest tests.test_mel_band_skip -v
```

Expected: FAIL (`skip_connection` unexpected / missing from signature or filter).

- [ ] **Step 3: Implement**

In `MelBandRoformer.__init__` add (after existing kwargs, before `match_input_audio_length` is fine):

```python
mlp_expansion_factor: int = 4,
use_torch_checkpoint: bool = False,
skip_connection: bool = False,
linear_transformer_depth: int = 0,
```

Store `self.use_torch_checkpoint` and `self.skip_connection`.

Layer build — mirror MSST / BS: each depth entry is a `ModuleList` of optional linear + time + freq transformers. Port `LinearAttention` into this module (copy typed from `ml/bs_roformer.py`) and extend local `Transformer` with `linear_attn: bool = False`.

Pass `mlp_expansion_factor=mlp_expansion_factor` into each `MaskEstimator(...)`.

In `forward`, replace the plain layer loop with MSST logic:

```python
from torch.utils.checkpoint import checkpoint

store: list[Tensor | None] = [None] * len(self.layers)
for i, layer in enumerate(self.layers):
    layer_pair = cast(ModuleList, layer)
    # len 3 → linear, time, freq; len 2 → time, freq
    ...
    if self.skip_connection:
        for j in range(i):
            prev = store[j]
            if prev is not None:
                x = x + prev
    # rearrange / time / freq with optional checkpoint(...)
    if self.skip_connection:
        store[i] = x
```

Use `checkpoint(..., use_reentrant=False)` when `self.use_torch_checkpoint` for `band_split` and each transformer call (same order as MSST).

Do **not** add `use_pope` (not in target yamls; keep YAGNI).

- [ ] **Step 4: Run tests — expect PASS**

```bash
.venv/bin/python -m unittest tests.test_mel_band_skip -v
.venv/bin/python -m basedpyright ml/mel_band_roformer.py tests/test_mel_band_skip.py
```

- [ ] **Step 5: Commit**

```bash
git add ml/mel_band_roformer.py tests/test_mel_band_skip.py
git commit -m "$(cat <<'EOF'
feat(ml): MelBand skip_connection and related MSST kwargs

Accept skip_connection, use_torch_checkpoint, mlp_expansion_factor,
and linear_transformer_depth so skip-enabled Mel-Band configs build
without silent key drops.
EOF
)"
```

---

### Task 2: BSRoformer — skip_connection + use_torch_checkpoint

**Files:**
- Modify: `ml/bs_roformer.py` (`__init__` ~365–404, forward loop ~541–565)
- Create: `tests/test_bs_roformer_skip.py`

**Interfaces:**
- Produces: `BSRoformer(..., skip_connection: bool = False, use_torch_checkpoint: bool = False)`
- Same residual-store semantics as MelBand; BS already has linear / mlp kwargs.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_bs_roformer_skip.py
from __future__ import annotations

import unittest

import torch

from engines.mdx import _filter_init_kwargs
from ml.bs_roformer import BSRoformer


class BSRoformerSkipTests(unittest.TestCase):
    def test_skip_kwargs_accepted(self) -> None:
        filtered = _filter_init_kwargs(
            BSRoformer,
            {
                "dim": 8,
                "depth": 1,
                "skip_connection": True,
                "use_torch_checkpoint": False,
                "freqs_per_bands": (2, 2, 2, 2),
                "flash_attn": False,
            },
        )
        self.assertIn("skip_connection", filtered)
        self.assertIn("use_torch_checkpoint", filtered)

    def test_skip_forward_runs(self) -> None:
        model = BSRoformer(
            dim=8,
            depth=2,
            stereo=True,
            time_transformer_depth=1,
            freq_transformer_depth=1,
            freqs_per_bands=(4, 4, 4, 4),
            dim_head=4,
            heads=2,
            flash_attn=False,
            stft_n_fft=128,
            stft_hop_length=32,
            stft_win_length=128,
            skip_connection=True,
        )
        model.eval()
        with torch.no_grad():
            out = model(torch.randn(1, 2, 512))
        self.assertEqual(out.shape[0], 1)
```

- [ ] **Step 2: Run — expect FAIL**

```bash
.venv/bin/python -m unittest tests.test_bs_roformer_skip -v
```

- [ ] **Step 3: Implement**

Add the two kwargs; set `self.skip_connection` / `self.use_torch_checkpoint`. In the axial loop, insert the MSST store sum (before time/freq) and store assignment (after), plus checkpoint wraps when enabled. Preserve the existing `len(block) == 3` linear path.

- [ ] **Step 4: Run — expect PASS**

```bash
.venv/bin/python -m unittest tests.test_bs_roformer_skip -v
.venv/bin/python -m basedpyright ml/bs_roformer.py tests/test_bs_roformer_skip.py
```

- [ ] **Step 5: Commit**

```bash
git add ml/bs_roformer.py tests/test_bs_roformer_skip.py
git commit -m "$(cat <<'EOF'
feat(ml): BSRoformer skip_connection and checkpoint flag

Match MSST residual-store skip path so skip_connection is a real
accepted parameter rather than a silent drop.
EOF
)"
```

---

### Task 3: Unblock mvsepless catalogue entries

**Files:**
- Modify: `core/mvsepless_catalog.py` (`_SUPPORTED_MODEL_TYPES`, `_UNSUPPORTED_MODEL_TYPES`, `_UNSUPPORTED_ENTRY_IDS`)
- Modify: `tests/test_mvsepless_catalog.py`
- Modify: `tests/test_model_probe.py` (unsupported-reason expectations for `mbr_syhft_4stem`)
- Modify: `docs/models.md` (unsupported table rows for Mel skip / SCNet Masked / Tran)

**Interfaces:**
- Produces: `classify_entry("mbr_syhft_4stem", …) → (True, "")`; `classify_entry` for `model_type` `scnet_masked` / `scnet_tran` → supported.

- [ ] **Step 1: Update tests first**

Replace `test_skip_connection_ids_denied` with:

```python
def test_skip_connection_ids_supported(self) -> None:
    ok, reason = classify_entry(
        "mbr_4stemxl1_aname",
        {"model_type": "mel_band_roformer", "full_name": "XL"},
    )
    self.assertTrue(ok)
    self.assertEqual(reason, "")
```

Add:

```python
def test_scnet_masked_and_tran_supported(self) -> None:
    for model_type in ("scnet_masked", "scnet_tran"):
        ok, reason = classify_entry(
            f"id_{model_type}",
            {"model_type": model_type, "full_name": model_type},
        )
        self.assertTrue(ok, msg=reason)
```

Extend `ConvertTests.test_supported_types_land_in_mdx_list` tuples with `("scnet_masked", …)` and `("scnet_tran", …)`.

In `tests/test_model_probe.py`, change the case that expects `target.reason == "Mel-Band skip_connection not ported"` to expect empty reason / supported (read that test and invert the assertion).

In `docs/models.md`, remove the three table rows for SCNet Masked/Tran and Mel-Band skip; mention they are supported via MDX-C.

- [ ] **Step 2: Run — expect FAIL on new support assertions**

```bash
.venv/bin/python -m unittest tests.test_mvsepless_catalog.ClassifyTests -v
```

- [ ] **Step 3: Implement catalogue changes**

```python
_SUPPORTED_MODEL_TYPES = frozenset({
    "mel_band_roformer",
    "bs_roformer",
    "mdx23c",
    "scnet",
    "scnet_masked",
    "scnet_tran",
    "bandit",
    "bandit_v2",
})
```

Remove `scnet_masked` / `scnet_tran` from `_UNSUPPORTED_MODEL_TYPES`.  
Delete the five Mel skip ids from `_UNSUPPORTED_ENTRY_IDS` (keep `mbr_wsa` and `bs_cr_4stem_zf_turbo`).

Keep `_MODEL_TYPE_TO_LIST_KEY` / `_MODEL_TYPE_TO_ARCH` entries for masked/tran (already present).

- [ ] **Step 4: Run — expect PASS**

```bash
.venv/bin/python -m unittest tests.test_mvsepless_catalog tests.test_model_probe -v
```

- [ ] **Step 5: Commit**

```bash
git add core/mvsepless_catalog.py tests/test_mvsepless_catalog.py tests/test_model_probe.py docs/models.md
git commit -m "$(cat <<'EOF'
feat(catalog): enable Mel-Band skip and SCNet Masked/Tran entries

Mark scnet_masked and scnet_tran supported and stop denying
skip_connection Mel-Band 4-stem ids now that the ports exist.
EOF
)"
```

---

### Task 4: Typed SCNet Masked module

**Files:**
- Create: `ml/scnet_src/scnet_masked.py`
- Modify: `ml/scnet.py` (`__all__` + imports)
- Modify: `tests/test_scnet_module.py`

**Upstream reference:** `https://raw.githubusercontent.com/ZFTurbo/Music-Source-Separation-Training/main/models/scnet/scnet_masked.py`

**Interfaces:**
- Produces: `class SCNetMasked(nn.Module)` with the same constructor kwargs as `SCNet` (sources, dims, band_SR, …). Distinct class name (do not name it `SCNet`).
- Reuse typed `SDblock`, `FusionLayer`, `SUlayer`, `SeparationNet` from `ml/scnet_src/scnet.py` / `separation.py` — do not duplicate untyped copies.
- Adds `pos_embed_f`, `mask_layer`; forward applies `mixture * mask` then iSTFT.
- Prefer `torch_stft` / `torch_istft` from `ml.stft_device` if plain SCNet already does; otherwise match existing SCNet STFT style in this tree for load parity.

- [ ] **Step 1: Extend failing smoke test**

```python
from ml.scnet import SCNetMasked

class SCNetMaskedModuleTests(unittest.TestCase):
    def test_forward_shape(self) -> None:
        model = SCNetMasked(
            sources=["drums", "bass", "other", "vocals"],
            audio_channels=2,
            nfft=4096,
            hop_size=1024,
            win_size=4096,
            normalized=True,
            dims=[4, 32, 64, 128],
            band_SR=[0.175, 0.392, 0.433],
            band_stride=[1, 4, 16],
            band_kernel=[3, 4, 16],
            conv_depths=[3, 2, 1],
            compress=4,
            conv_kernel=3,
            num_dplayer=6,
            expand=1,
        )
        output = model(torch.randn(2, 2, 8192))
        self.assertEqual(output.shape, (2, 4, 2, 8192))
        self.assertTrue(hasattr(model, "mask_layer"))
        self.assertTrue(hasattr(model, "pos_embed_f"))
```

- [ ] **Step 2: Run — expect FAIL (import)**

```bash
.venv/bin/python -m unittest tests.test_scnet_module.SCNetMaskedModuleTests -v
```

- [ ] **Step 3: Implement typed port**

Create `SCNetMasked` with full annotations (`list[str]`, `list[int]`, `list[float]`, `Tensor` returns). Constructor defaults must match MSST/SCNet. Forward must include positional embed add and `mask_layer` path from upstream.

Export:

```python
# ml/scnet.py
from ml.scnet_src.scnet import SCNet
from ml.scnet_src.scnet_masked import SCNetMasked
from ml.scnet_src.separation import SeparationNet

__all__ = ["SCNet", "SCNetMasked", "SeparationNet"]
```

(Tran added in Task 5.)

- [ ] **Step 4: Run — expect PASS**

```bash
.venv/bin/python -m unittest tests.test_scnet_module -v
.venv/bin/python -m basedpyright ml/scnet.py ml/scnet_src/scnet_masked.py tests/test_scnet_module.py
```

- [ ] **Step 5: Commit**

```bash
git add ml/scnet_src/scnet_masked.py ml/scnet.py tests/test_scnet_module.py
git commit -m "$(cat <<'EOF'
feat(ml): typed SCNet Masked port

Add SCNetMasked with positional frequency embed and mask layer,
reusing the existing SCNet encoder/decoder blocks.
EOF
)"
```

---

### Task 5: Typed SCNet Tran module

**Files:**
- Create: `ml/scnet_src/scnet_tran.py`
- Modify: `ml/scnet.py`
- Modify: `tests/test_scnet_module.py`

**Upstream reference:** `…/models/scnet/scnet_tran.py` (class `SCNet_Tran`).

**Interfaces:**
- Produces: `class SCNetTran(nn.Module)` accepting SCNet kwargs **plus**  
  `tran_rotary_embedding_dim`, `tran_depth`, `tran_heads`, `tran_dim_head`, `tran_attn_dropout`, `tran_ff_dropout`, `tran_flash_attn`.
- Internal: typed `SeparationNetTran` / `DualPathTran` / `FeatureConversion`; use `ml.attend.Attend` and `RotaryEmbedding` like Mel-Band rather than an untyped local Attend paste when shapes match.
- Reuse `SDblock` / `FusionLayer` / `SUlayer` from `scnet.py`.

- [ ] **Step 1: Failing smoke**

```python
from ml.scnet import SCNetTran

class SCNetTranModuleTests(unittest.TestCase):
    def test_forward_shape(self) -> None:
        model = SCNetTran(
            sources=["drums", "bass", "other", "vocals"],
            audio_channels=2,
            nfft=4096,
            hop_size=1024,
            win_size=4096,
            normalized=True,
            dims=[4, 32, 64, 128],
            band_SR=[0.175, 0.392, 0.433],
            band_stride=[1, 4, 16],
            band_kernel=[3, 4, 16],
            conv_depths=[3, 2, 1],
            compress=4,
            conv_kernel=3,
            num_dplayer=2,  # keep smoke cheap
            expand=1,
            tran_rotary_embedding_dim=16,
            tran_depth=1,
            tran_heads=2,
            tran_dim_head=8,
            tran_attn_dropout=0.0,
            tran_ff_dropout=0.0,
            tran_flash_attn=False,
        )
        output = model(torch.randn(1, 2, 8192))
        self.assertEqual(output.shape, (1, 4, 2, 8192))
```

- [ ] **Step 2: Run — expect FAIL**

```bash
.venv/bin/python -m unittest tests.test_scnet_module.SCNetTranModuleTests -v
```

- [ ] **Step 3: Implement typed port** from MSST `SCNet_Tran` + helpers. Every `__init__` / `forward` annotated. Export `SCNetTran` from `ml/scnet.py`.

- [ ] **Step 4: Run — expect PASS**

```bash
.venv/bin/python -m unittest tests.test_scnet_module -v
.venv/bin/python -m basedpyright ml/scnet_src/scnet_tran.py ml/scnet.py
```

- [ ] **Step 5: Commit**

```bash
git add ml/scnet_src/scnet_tran.py ml/scnet.py tests/test_scnet_module.py
git commit -m "$(cat <<'EOF'
feat(ml): typed SCNet Tran port

Replace dual-path RNN separation with dual-path Transformers and
accept tran_* yaml kwargs used by MSST SCNet Tran checkpoints.
EOF
)"
```

---

### Task 6: Build dispatch + arch labels + probe hint

**Files:**
- Modify: `engines/mdx.py` (`_build_mdx_c_model`)
- Modify: `core/mdx_c_registry.py` (`infer_mdx_c_architecture`)
- Modify: `scripts/model_probe.py` (pass `model_type` hint into build)
- Modify: `tests/test_mdx_arch_dispatch.py`
- Modify: `tests/test_infer_mdx_c_architecture.py`

**Interfaces:**
- Produces:

```python
def scnet_variant_from_state_dict(keys: Sequence[str]) -> str | None:
    """Return 'masked' if keys look like SCNet Masked, else None."""

def _build_mdx_c_model(
    config: Any,
    state_dict_keys: Sequence[str] | None = None,
    model_type_hint: str | None = None,
) -> nn.Module: ...
```

Dispatch order for SCNet-shaped configs:
1. Any `tran_depth` / `tran_rotary_embedding_dim` (or other `tran_*`) in `model_cfg` → `SCNetTran`
2. Else if `scnet_variant_from_state_dict(keys) == "masked"` **or** `model_type_hint in {"scnet_masked", "SCNet Masked"}` → `SCNetMasked`
3. Else → `SCNet`

`infer_mdx_c_architecture`: before plain SCNet, if model has `tran_*` → `("SCNet Tran", True)`; elif `"masked" in yaml_name.lower()` → `("SCNet Masked", True)`; elif band_SR/sources → `("SCNet", True)`.

Probe: when building from `--entry`, pass `model_type_hint=target.model_type` into `build_from_config` / `_instantiate` / `_build_mdx_c_model` so Masked builds correctly before `--check-keys` loads headers.

- [ ] **Step 1: Failing dispatch tests**

```python
def test_scnet_tran_factory(self) -> None:
    config = ConfigDict({
        "model": {
            "sources": ["drums", "bass", "other", "vocals"],
            "hop_size": 1024,
            "nfft": 4096,
            "win_size": 4096,
            "normalized": True,
            "dims": [4, 32, 64, 128],
            "band_SR": [0.175, 0.392, 0.433],
            "band_stride": [1, 4, 16],
            "band_kernel": [3, 4, 16],
            "conv_depths": [3, 2, 1],
            "compress": 4,
            "conv_kernel": 3,
            "num_dplayer": 2,
            "expand": 1,
            "audio_channels": 2,
            "tran_rotary_embedding_dim": 16,
            "tran_depth": 1,
            "tran_heads": 2,
            "tran_dim_head": 8,
            "tran_attn_dropout": 0.0,
            "tran_ff_dropout": 0.0,
            "tran_flash_attn": False,
        },
        "audio": {"sample_rate": 44100},
        "training": {"instruments": ["Drums", "Bass", "Other", "Vocals"]},
        "inference": {"batch_size": 1, "dim_t": 256},
    })
    model = _build_mdx_c_model(config)
    self.assertEqual(model.__class__.__name__, "SCNetTran")

def test_scnet_masked_from_hint(self) -> None:
    # same model dict as test_scnet_factory (no tran_*)
    model = _build_mdx_c_model(config, model_type_hint="scnet_masked")
    self.assertEqual(model.__class__.__name__, "SCNetMasked")

def test_scnet_masked_from_keys(self) -> None:
    model = _build_mdx_c_model(
        config,
        state_dict_keys=["pos_embed_f", "mask_layer.0.weight", "encoder.0.SDlayer.convs.0.weight"],
    )
    self.assertEqual(model.__class__.__name__, "SCNetMasked")
```

Add infer tests with temp yaml fixtures containing `tran_depth` / filename `*_masked_*.yaml`.

- [ ] **Step 2: Run — expect FAIL**

```bash
.venv/bin/python -m unittest tests.test_mdx_arch_dispatch tests.test_infer_mdx_c_architecture -v
```

- [ ] **Step 3: Implement dispatch + probe wiring**

```python
def scnet_variant_from_state_dict(keys: Sequence[str]) -> str | None:
    joined = "\n".join(keys)
    if "mask_layer" in joined or "pos_embed_f" in joined:
        return "masked"
    return None
```

Wire `model_type_hint` through `scripts/model_probe.py` `_instantiate` / `build_from_config` and the `--entry` main path.

- [ ] **Step 4: Run — expect PASS**

```bash
.venv/bin/python -m unittest tests.test_mdx_arch_dispatch tests.test_infer_mdx_c_architecture tests.test_scnet_module -v
.venv/bin/python -m basedpyright engines/mdx.py core/mdx_c_registry.py scripts/model_probe.py
```

- [ ] **Step 5: Commit**

```bash
git add engines/mdx.py core/mdx_c_registry.py scripts/model_probe.py \
  tests/test_mdx_arch_dispatch.py tests/test_infer_mdx_c_architecture.py
git commit -m "$(cat <<'EOF'
feat(mdx): dispatch SCNet Masked and Tran builds

Select Tran from tran_* yaml keys and Masked from state-dict
markers or catalogue model_type hints.
EOF
)"
```

---

### Task 7: Full local verification — unit + basedpyright + probe

**Files:** none new (verification only); fix any fallout in the files above if probes fail.

- [ ] **Step 1: Unit + types**

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
```

Expected: OK / 0 errors. If something fails, fix on this branch before continuing (do not skip).

- [ ] **Step 2: Probe three entries with key check**

```bash
UVR_DISABLE_POLITREES=1 .venv/bin/python scripts/model_probe.py --entry mbr_syhft_4stem --check-keys
UVR_DISABLE_POLITREES=1 .venv/bin/python scripts/model_probe.py --entry scnet_masked_small_4stem_zftrubo --check-keys
UVR_DISABLE_POLITREES=1 .venv/bin/python scripts/model_probe.py --entry scnet_tran_4stem_zftrubo --check-keys
```

Expected each: verdict `buildable` (or `key-mismatch` only if remote header disagrees — treat unexpected Masked/Tran submodule keys as a port bug to fix). `dropped_config_keys` must not include `skip_connection` for Mel, nor `tran_*` for Tran.

- [ ] **Step 3: Commit any probe-driven fixes** (if needed) with an explicit message; if clean, no commit.

---

### Task 8: Download one checkpoint per family + CLI smoke separate

**Files:** none required (runtime under `models/`); optional short note in `docs/models.md` if smoke reveals a docs gap.

Prefer smallest Masked weight. Use a short stereo clip (e.g. existing test fixture or generate ~2–4 s wav).

- [ ] **Step 1: Download via app Download Center *or* curl the catalogue `checkpoint_url` / `config_url` into `models/MDX_Net_Models/` and `model_data/mdx_c_configs/`, then ensure hash registration (re-open app, or call `register_mdx_c_checkpoint` / download path). Confirm each appears in MDX model list.

- [ ] **Step 2: CLI smoke** (adjust `--model` to the registered display name or basename):

```bash
.venv/bin/python -c "import soundfile as sf, numpy as np; sr=44100; t=np.linspace(0,2,2*sr,endpoint=False); x=0.1*np.stack([np.sin(2*np.pi*440*t),np.sin(2*np.pi*554*t)],1).astype('float32'); sf.write('/tmp/uvr_smoke.wav', x, sr)"

.venv/bin/python -m core.cli separate /tmp/uvr_smoke.wav -o /tmp/uvr_smoke_mel --method mdx --model '<mel skip model>' --cpu
.venv/bin/python -m core.cli separate /tmp/uvr_smoke.wav -o /tmp/uvr_smoke_masked --method mdx --model '<masked small>' --cpu
.venv/bin/python -m core.cli separate /tmp/uvr_smoke.wav -o /tmp/uvr_smoke_tran --method mdx --model '<scnet tran>' --cpu
```

Expected: exit 0; stem wavs under each output dir; no state_dict / forward traceback.

CPU is fine for smoke; drop `--cpu` if GPU preferred and available. Large Mel 4-stem may need GPU + patience — still required once for the chosen Mel skip entry.

- [ ] **Step 3: Commit docs-only touch-ups if any**; do not commit downloaded weights.

- [ ] **Step 4: Open PR when smoke is green**

```bash
git push -u origin HEAD
gh pr create --title "feat: Mel-Band skip_connection + SCNet Masked/Tran" --body "$(cat <<'EOF'
## Summary
- Implement Mel/BS `skip_connection` (and related MSST kwargs) so Mel-Band 4-stem skip models build and run
- Typed SCNet Masked and SCNet Tran ports with MDX-C dispatch
- Unblock mvsepless catalogue entries; probe + CLI smoke verified locally

## Test plan
- [ ] `unittest discover` + basedpyright
- [ ] `model_probe --entry` ×3 with `--check-keys` → buildable
- [ ] CLI separate smoke for one Mel skip, Masked small, and Tran checkpoint
EOF
)"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|---|---|
| Mel/BS skip residual | 1, 2 |
| Mel kwargs so probe is not `config-ignored` | 1 |
| SCNet Masked typed port | 4 |
| SCNet Tran typed port | 5 |
| Dispatch Tran / Masked / SCNet | 6 |
| Catalogue unblock | 3 |
| docs/models.md | 3 (+8 if needed) |
| Unit tests + basedpyright | 1–7 |
| Probe `--check-keys` buildable | 7 |
| Download + CLI smoke | 8 |
| No typing shortcuts | Global + 4, 5 |

## Placeholder / consistency self-review

- No TBD steps; upstream URLs and class names fixed (`SCNetMasked`, `SCNetTran`).
- `model_type_hint` / `scnet_variant_from_state_dict` named consistently across Task 6 steps.
- Test runner is unittest throughout (not pytest).
- Weights stay gitignored; smoke does not commit checkpoints.
