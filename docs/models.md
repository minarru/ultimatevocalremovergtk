# Model architectures

## Download catalogues

The Download Center merges catalogues in this order (earlier labels win):

1. Official TRvlvr `download_checks.json`
2. Politrees `UVR_resources` community list
3. Fork-curated [`bundled/extra_models.json`](../bundled/extra_models.json)
4. [noblebarkrr/mvsepless_resources](https://huggingface.co/noblebarkrr/mvsepless_resources) `models.json` (live fetch, 24h disk cache)

The mvsepless feed has **no declared Hugging Face license tag**; this app only indexes remote URLs and downloads into the local models dirs (it does not rehost weights). Disable with `UVR_DISABLE_MVSEPLESS=1`.

After merging, a **dedupe pass** keeps the first selectable for each of:

- checkpoint basename
- normalized label (cosmetic renames like `Roformer Model: MelBand …` vs `Mel-Band Roformer …`, or `Inst V1` vs `Inst v1`)
- normalized checkpoint URL (strips `?download=true`)
- content identity (`x-linked-etag` / `ETag`) when the download size cache knows it

Earlier catalogues always win (upstream → Politrees → extras → mvsepless). Demucs bags only collide on identical file→URL maps or normalized labels — shared bag members are not treated as duplicates.

Entries this build cannot run yet still appear in the matching network tab as **Unsupported** (grayed, not downloadable), with a short reason. Use **Hide unsupported** in the Download Center filters to conceal them. First-pass unsupported classes:

| Class | Why |
|---|---|
| Medley-Vox | No engine port |
| MSST HTDemucs (single `.ckpt`) | Not the Facebook Demucs bag format |
| Classic VR from mvsepless | Needs `.ckpt`+yaml → VR hash bridge (use TRvlvr/Politrees VR instead) |
| Classic MDX-Net ONNX from mvsepless | Needs yaml→hash bridge (use TRvlvr ONNX instead) |
| Windowed Sink Attention Mel-Band (`mbr_wsa`) | Attention features not ported |
| BS Conformer (`bs_cr_4stem_zf_turbo`) | Conformer blocks not ported |

Supported Mel-Band / BS-Roformer / MDX23C / SCNet (including Masked and Tran) / Bandit(+v2) entries download through the existing MDX-C hash → `config_yaml` registration path. Mel-Band 4-stem models with `skip_connection: true` are supported via the same path.

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

`config-ignored` is the one to watch: [`engines.mdx._filter_init_kwargs`](../engines/mdx.py) drops yaml keys a class does not accept, so a model can build cleanly while missing the exact feature that made it unsupported. Use this verdict to catch gaps between yaml and the port before flipping catalogue support flags.

## HyperACE BS-Roformer

The `BS-Roformer-HyperACE` entries in [`bundled/extra_models.json`](../bundled/extra_models.json) attach a segmentation branch to every mask estimator — a depthwise-separable CSP backbone, hypergraph attention, a gated FPN decoder and a frequency pixel-shuffle head — summed onto the per-band mask MLPs. It lives in [`ml/hyperace.py`](../ml/hyperace.py).

Upstream ships **two** distinct sources; `v2_inst` and `v2_voc` are byte-identical to each other.

| Variant | segm keys | Total keys | Params | Differences |
|---|---|---|---|---|
| v1 | 398 | 1097 | 68.6M | Backbone strides time only; upsample head has no `out_conv`, narrows more slowly, 1×1 final conv; 16 hyperedges; HyperACE `k=3, l=2` |
| v2 (inst + voc) | 471 | 1170 | 72.0M | Backbone also halves the band axis in `p4`/`p5`; each upsample stage refined by a TFC-TDF `out_conv`; 32 hyperedges; HyperACE `k=2, l=1` |

**The variant is detected from the checkpoint, not the config.** Only the *packaged* v2-instrumental yaml carries a top-level `hyperace2: true`; upstream's own configs declare nothing at all, and that key is outside `model:` so it never reaches `_filter_init_kwargs` anyway. `hyperace_variant_from_state_dict` keys off the presence of `segm.*` and, within it, `upsample_head.*.out_conv` (v2 only). `SeperateMDXC` therefore loads the checkpoint *before* building the model. The `hyperace2` flag is still honoured as a fallback when no keys are available.

Verify a HyperACE checkpoint loads without running it — or without even downloading it:

```bash
python scripts/model_probe.py --config <hyperace.yaml> --checkpoint <hyperace.ckpt>
# state_dict   1170 matched, 0 missing, 0 unexpected
```

All three published checkpoints were verified this way against ~300 KB of range-fetched headers rather than 853 MB of weights.

HyperACE configs may still carry `use_torch_checkpoint` in yaml; it is accepted but optional on BS-Roformer builds that implement checkpointing.

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
