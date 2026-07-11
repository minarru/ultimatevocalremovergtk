# Model architectures

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

When placing a community `.ckpt` manually, the unrecognized-model dialog lets you pick the yaml config. The **Architecture** row auto-detects SCNet, Bandit, or Roformer from the yaml shape. Enable **Roformer Model** for SCNet, Bandit, and Roformer checkpoints (routes through the shared MDX-C chunked inference path).
