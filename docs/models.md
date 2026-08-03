# Model architectures

## Download catalogues

The Download Center merges catalogues in this order (earlier labels win):

1. Official TRvlvr `download_checks.json`
2. Politrees `UVR_resources` community list
3. Fork-curated [`bundled/extra_models.json`](../bundled/extra_models.json)
4. [noblebarkrr/mvsepless_resources](https://huggingface.co/noblebarkrr/mvsepless_resources) `models.json` (live fetch, 24h disk cache)

The mvsepless feed has **no declared Hugging Face license tag**; this app only indexes remote URLs and downloads into the local models dirs (it does not rehost weights). Disable with `UVR_DISABLE_MVSEPLESS=1`.

After merging, a **dedupe pass** keeps the first selectable for each checkpoint basename and for each normalized label (cosmetic renames like `Roformer Model: MelBand …` vs `Mel-Band Roformer …`, or `Inst V1` vs `Inst v1`). Earlier catalogues always win.

Entries this build cannot run yet still appear in the matching network tab as **Unsupported** (grayed, not downloadable), with a short reason. Use **Hide unsupported** in the Download Center filters to conceal them. First-pass unsupported classes:

| Class | Why |
|---|---|
| Medley-Vox | No engine port |
| SCNet Masked / SCNet Tran | Architecture not ported |
| MSST HTDemucs (single `.ckpt`) | Not the Facebook Demucs bag format |
| Classic VR from mvsepless | Needs `.ckpt`+yaml → VR hash bridge (use TRvlvr/Politrees VR instead) |
| Classic MDX-Net ONNX from mvsepless | Needs yaml→hash bridge (use TRvlvr ONNX instead) |
| Windowed Sink Attention Mel-Band (`mbr_wsa`) | Attention features not ported |
| BS Conformer (`bs_cr_4stem_zf_turbo`) | Conformer blocks not ported |
| Mel-Band 4-stem with `skip_connection` | Skip path not ported |

Supported Mel-Band / BS-Roformer / MDX23C / SCNet / Bandit(+v2) entries download through the existing MDX-C hash → `config_yaml` registration path.

### Triaging an unsupported entry

[`scripts/model_probe.py`](../scripts/model_probe.py) answers "could this build run it?" **without downloading the weights**. The architecture comes from the yaml (a couple of KB), so it instantiates with random parameters and runs a real forward pass; `--check-keys` then range-fetches only the checkpoint *header* — ~90 KB of a 448 MB file — to diff `state_dict` names.

```bash
python scripts/model_probe.py --entry mbr_syhft_4stem              # fetch yaml, build, forward
python scripts/model_probe.py --entry mbr_wsa --check-keys         # + remote state_dict diff
python scripts/model_probe.py --config <local.yaml> --checkpoint <local.ckpt>   # fully offline
python scripts/model_probe.py --config <local.yaml> --json out.json
```

Verdicts, worst to best. Exit status is 0 only for `buildable`:

| Verdict | Meaning |
|---|---|
| `build-failed` | The architecture does not instantiate — a genuinely unported feature. |
| `forward-failed` | Instantiates but the forward pass breaks. |
| `config-ignored` | Builds *only* because `_filter_init_kwargs` discarded keys the yaml asked for. |
| `key-mismatch` | Runs, but parameter names disagree with the checkpoint. |
| `buildable` | Builds, runs, and (if checked) matches the checkpoint's keys. |

`config-ignored` is the one to watch: [`engines.mdx._filter_init_kwargs`](../engines/mdx.py) drops yaml keys a class does not accept, so a model can build cleanly while missing the exact feature that made it unsupported. Probing `mbr_syhft_4stem` reports `skip_connection` among the dropped keys, which is precisely why that entry is listed.

## HyperACE BS-Roformer

The four `BS-Roformer-HyperACE` entries in [`bundled/extra_models.json`](../bundled/extra_models.json) attach a segmentation branch to every mask estimator — a depthwise-separable CSP backbone, hypergraph attention, a gated FPN decoder and a frequency pixel-shuffle head — summed onto the per-band mask MLPs. It lives in [`ml/hyperace.py`](../ml/hyperace.py) and adds ~21M parameters (51M → 72M for the v2 instrumental model).

It is switched on by a **top-level** `hyperace2: true` in the yaml, *not* a key inside `model:`. `_filter_init_kwargs` only ever sees the `model:` section, so `_build_mdx_c_model` reads the flag off the config root and injects `hyperace=True`. Without that, a plain BSRoformer is built and `load_state_dict` rejects ~471 `mask_estimators.N.segm.*` keys.

Verify a HyperACE checkpoint loads without running it:

```bash
python scripts/model_probe.py --config <hyperace.yaml> --checkpoint <hyperace.ckpt>
# state_dict   1170 matched, 0 missing, 0 unexpected
```

The probe still reports `config-ignored` for these configs because `skip_connection` and `use_torch_checkpoint` are dropped. Both are inert here — upstream's `v2_inst/bs_roformer.py` stores them and never reads them in `forward`, and this config sets `skip_connection: false`. They are deliberately **not** accepted as parameters: taking a kwarg we do not implement would silence the probe for a future config where the flag does matter.

## SCNet (4-stem music separation)

SCNet models separate music into **Drums**, **Bass**, **Other**, and **Vocals**. They use `.ckpt` checkpoints with a matching yaml config under `models/MDX_Net_Models/model_data/mdx_c_configs/`.

- Download via **Download Center → MDX-Net** (Politrees entries prefixed `SCnet:`)
- Select the model in the MDX-Net method dropdown
- Per-stem export toggles appear automatically for 4-stem models

## Bandit (3-stem cinematic separation)

Bandit models separate cinematic audio into **Speech**, **Music**, and **Sfx** (or **Effects** on some checkpoints).

- Download via **Download Center → MDX-Net** (Politrees entries prefixed `Bandit:`)
- **Bandit v2** checkpoints run at **48 kHz** internally; output is resampled back to 44.1 kHz for export
- **Bandit Plus** checkpoints run at 44.1 kHz

Ensemble mode vocal/instrumental filtering does not apply to Bandit stems.

## Unrecognized models

MDX-C models downloaded from **Download Center** (checkpoint + paired yaml) are **auto-registered** on download. If the model was downloaded earlier, the app also tries the download catalogue on first use before prompting. Download catalogue labels are shown in the model dropdown (for example `BandSplit Roformer | Karaoke Frazer by becruily` instead of the raw checkpoint filename).

When placing a community `.ckpt` manually with no catalogue entry, the unrecognized-model dialog lets you pick the yaml config. The **Architecture** row auto-detects SCNet, Bandit, or Roformer from the yaml shape. Enable **Roformer Model** for SCNet, Bandit, and Roformer checkpoints (routes through the shared MDX-C chunked inference path).
