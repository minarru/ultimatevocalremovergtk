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

**Network behaviour (Download Center):**

- Checkpoint size HEADs run when the Download Center opens (and after a successful Refresh), not at app startup. Same-size identity HEADs are capped per pass and ordered oldest-first, so a host that never returns an `ETag` cannot permanently block the rest; the pass repeats until nothing is left over.
- **Trade-off of deferring the warmup:** etag-based rehost dedupe reads the size cache, so on a fresh install there are no etags until the identity pass has run and content-identity dedupe cannot fire. URL/label dedupe still applies throughout. The separation-view pickers are unaffected either way — `_index_from_meta` reads `MergedCatalogues.meta`, which is built *before* dedupe on purpose, so a dropped duplicate label still resolves its checkpoint. The one surface that starts un-deduped is the Download Center list itself.
- **The Download Center list self-corrects.** When the identity pass drops rows, `_reapply_content_dedupe` notifies subscribers (`DownloadManager.subscribe_catalogue_changed`), and the window removes just the dropped rows — debounced 250 ms, marshalled to the main loop. It does not rebuild the catalogue: a rebuild fires while the user is browsing and would reset scroll position to recreate ~500 rows in order to delete a handful. Dedupe only ever removes, so removal is the whole contract. Nothing is notified when the pass drops nothing, which is the warm-cache case.
- **Name mappers** are split in two: `model_name_mapper.json` mirrors upstream verbatim, and a sibling `model_name_mapper_local.json` holds fork-local and locally-registered names. Reads merge the two (overlay wins); refresh overwrites only the mirror, so a key upstream *deletes* actually disappears instead of surviving forever in a union file. Existing installs are migrated once — keys in the mirror that upstream no longer ships move to the overlay, and the overlay's existence marks the migration done. Hash maps still replace when content changes.
- Catalogue YAML stem subtitles are fetched in the background with at most two concurrent GETs; rows on the **active tab** matching the current filters are prioritized over the rest of the catalogue, and a row already queued in the bulk backlog is promoted when it becomes visible. Rescans are debounced (250 ms), so a burst of typing costs one catalogue scan rather than one per keystroke.

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

[`scripts/model_probe.py`](../scripts/model_probe.py) answers "could this build run it?" **without downloading the weights**. The architecture comes from the yaml (a couple of KB), so it instantiates with random parameters and runs a real forward pass; `--check-keys` then range-fetches only the checkpoint *header* — ~90 KB of a 448 MB file — to diff `state_dict` names (cached by URL across repeat runs).

```bash
python scripts/model_probe.py --entry mbr_syhft_4stem              # fetch yaml, build, forward
python scripts/model_probe.py --entry mbr_wsa --check-keys         # + remote state_dict diff
python scripts/model_probe.py --config <local.yaml> --checkpoint <local.ckpt>   # fully offline
python scripts/model_probe.py --config <local.yaml> --json out.json
python scripts/model_probe.py --sweep --check-keys --json sweep.json   # every unsupported catalogue entry, one summary
```

Verdicts, worst to best. Exit status is 0 only for `buildable`:

| Verdict | Meaning |
|---|---|
| `probe-error` | (`--sweep` only) The entry itself couldn't be fetched/read — not a build/forward outcome. |
| `build-failed` | The architecture does not instantiate — a genuinely unported feature. |
| `forward-failed` | Instantiates but the forward pass breaks. |
| `config-ignored` | Builds *only* because kwarg filtering discarded keys the yaml asked for. |
| `key-mismatch` | Runs, but parameter names disagree with the checkpoint. |
| `buildable` | Builds, runs, and (if checked) matches the checkpoint's keys. |

`config-ignored` is the one to watch: [`engines.mdx._filter_init_kwargs`](../engines/mdx.py) drops yaml keys a class does not accept, so a model can build cleanly while missing the exact feature that made it unsupported. Use this verdict to catch gaps between yaml and the port before flipping catalogue support flags.

[`docs/unsupported-models-probe.md`](unsupported-models-probe.md) is a point-in-time `--sweep --check-keys` run over every currently-unsupported entry, with per-group findings (which gaps are real architecture work vs. plumbing, and which verdicts undersell how wrong a build actually is).

**VR and MSST HTDemucs are probeable, not supported.** The script builds `CascadedASPPNet`/`CascadedNet` ([`ml/vr_network/`](../ml/vr_network/)) and the vendored-but-unwired `HTDemucs` ([`vendor/demucs/htdemucs.py`](../vendor/demucs/htdemucs.py)) straight from a mvsepless yaml, entirely inside the probe script — neither `engines/vr.py` nor `engines/demucs_engine.py` changed, so this does not add real separation support for either class, only triage. Two things worth knowing:

- **VR's architecture variant is derived from the checkpoint's byte size**, never declared in the yaml (`engines/vr.py`'s own selection heuristic) — probing a VR entry needs `--checkpoint` or `--check-keys` so the probe has a size to work from; without one it reports `build-failed` rather than guessing.
- **VR6 ("v6 beta3") entries have no matching network class anywhere in this port** — `ml/vr_network/` only ever implements the VR5/"5.1" family. The probe reports these as `build-failed` explicitly rather than silently building the wrong (VR5) architecture for them.

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

## PoPE BS-Roformer ("BS PolarFormer")

A handful of community BS-Roformer checkpoints (`use_pope: true` in the training yaml, labelled "BS PolarFormer" upstream) replace rotary position embeddings with **Polar Coordinate Positional Embedding** ([arXiv:2509.10534](https://arxiv.org/abs/2509.10534)) — magnitudes go through `softplus` and get rotated by a per-head, per-frequency phase, with an extra learned bias on the key side. `BSRoformer(use_pope=True)` in [`ml/bs_roformer.py`](../ml/bs_roformer.py) wires this in via [`PoPE-pytorch`](https://pypi.org/project/PoPE-pytorch/) (same author/lineage as the `rotary-embedding-torch` dependency BS-Roformer already used), pinned in `requirements.txt` along with its own `einx`/`frozendict`/`torch-einops-utils` deps.

Unlike `hyperace`/`value_residual` above, `use_pope` is a literal yaml key that already matches the constructor argument name, so it reaches `BSRoformer.__init__` through the ordinary `_filter_init_kwargs` path — no checkpoint-key detection needed.

**One `PoPE` module per axis, not per layer.** `time_pope_embed`/`freq_pope_embed` are each built once and shared across every one of `depth` outer layers (mirroring how `RotaryEmbedding` is shared in the non-PoPE path). This was verified against a real checkpoint (`bs_pope_vocals_zfturbo`), not assumed: `pope_embed.bias`/`pope_embed.inv_freqs` are byte-identical across all 12 layers for a given axis and differ only between time and freq — confirming the training code shares one module per axis rather than training 12 independent ones. Loading that checkpoint into this build reports `state_dict 723 matched, 0 missing, 0 unexpected`.

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
