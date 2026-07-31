# Model architectures

## Download catalogues

The Download Center merges catalogues in this order (earlier labels win):

1. Official TRvlvr `download_checks.json`
2. Politrees `UVR_resources` community list
3. Fork-curated [`bundled/extra_models.json`](../bundled/extra_models.json)
4. [noblebarkrr/mvsepless_resources](https://huggingface.co/noblebarkrr/mvsepless_resources) `models.json` (live fetch, 24h disk cache)

The mvsepless feed has **no declared Hugging Face license tag**; this app only indexes remote URLs and downloads into the local models dirs (it does not rehost weights). Disable with `UVR_DISABLE_MVSEPLESS=1`.

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
