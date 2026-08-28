# Models and stems

Models turn a mix into one or more audio outputs, called *stems*. Begin in the
**Download Center**: it shows what a model is intended to produce, whether this
build supports it, and whether it is already installed. A model must be
installed before it appears in a method, ensemble, or Vocal Splitter picker.

The Download Center is a catalogue, not the list of models on your machine. In
the CLI, keep those two views separate:

```bash
uvr models list                                  # installed IDs
uvr models catalog --family mdx --query karaoke  # downloadable catalogue rows
uvr models download "MelBand Roformer — Karaoke · Gabox"
uvr models list --all-known                      # installed plus catalogue-only records
```

`uvr models list` is the source of truth for IDs accepted by a separation
command. `uvr models catalog` searches Download Center entries, including
uninstalled ones. `uvr models download` resolves an exact `catalog:` ID, exact
selectable/display text, or a unique substring.

## Choose a supported model

Open **Download Center**, select the method you need, and choose a supported
row. Unsupported rows are grayed, cannot be downloaded, and can be hidden with
**Hide unsupported**. Catalogue labels and scores are useful evidence, not a
quality guarantee, so test a short representative clip before a large job.

| Goal | Where to look | Expected outputs |
|---|---|---|
| Vocals or instrumental | VR Architecture, MDX-Net, or Demucs | A vocals/instrumental pair or its model-specific equivalent. |
| Karaoke or backing-vocal work | A reviewed Karaoke/backing-vocal model | Lead vocals and an instrumental mix retaining backing vocals, or the Vocal Splitter pair. |
| Drums, bass, vocals, and residual music | MDX-Net 4-stem or multi-stem, including SCNet | One exportable output per available stem. |
| Speech, music, and effects | MDX-Net BandIt | Three cinematic stems, not a vocals/instrumental ensemble pair. |
| Music restoration | Audio Tools with Apollo | Restoration rather than source separation. |

This build supports VR Architecture, MDX-Net (including MDX23C,
Mel-Band/BS-Roformer, SCNet, and BandIt), and Demucs v2/v3/v4. Supported
Mel-Band, BS-Roformer, MDX23C, SCNet (including Masked and Tran), and BandIt
(including v2) rows use the MDX-C checkpoint-and-YAML registration path;
Mel-Band 4-stem models with `skip_connection: true` are supported too.

For an MDX-C Roformer, SCNet, or BandIt checkpoint, enable **Roformer Model**
in the MDX-C model parameters. That selects the shared MDX-C chunked-inference
route. Download Center installs supply the paired YAML automatically.

## Understand the stems you will get

Reviewed models translate native YAML/backend labels into stable user-facing
concepts before files are named or ensemble compatibility is decided. A native
name such as `other`, `instrument`, or `No dry` can therefore differ from the
exported label. The engine retains the native key; the UI, filenames, and
ensemble matching use the user-facing concept.

### Two-stem models

Most vocal models produce a selected stem and its complement. The CLI can ask
for positional outputs with `--stems primary` or `--stems secondary`. Reviewed
semantics also identify vocals/instrumental, center/side, and other relationships
without matching display text.

### Karaoke and backing vocals

In a full-mix run, a reviewed karaoke model produces **Instrumental with
Backing Vocals** and **Lead Vocals**. In Vocal Splitter use, the corresponding
outputs are **Lead Vocals** and **Backing Vocals**. Only reviewed
karaoke/backing-vocal models appear in the Vocal Splitter picker.

### Four-stem and multi-stem models

Four-stem music models commonly export **Drums**, **Bass**, **Other**, and
**Vocals**. Other multi-stem models can expose Guitar, Piano, Speech, Music,
Effects, choir parts, channel stems, or other model-specific outputs. They stay
distinct: the application never collapses them into a generic `Other` stem.
Per-stem export controls follow the installed model's actual output inventory.

For 4-stem and multi-stem ensembles, a requested stem filters only the final
combined outputs. Every member still emits its complete inventory for
aggregation. BandIt stems do not use vocals/instrumental ensemble filtering.

## Display names and exact IDs

The picker name is for people; the exact ID is for settings, CLI commands, and
execution:

```text
Display name:  MDX-Net — UVR Instrumental HQ 4
Canonical ID:  mdx:UVR-MDX-NET-Inst_HQ_4
```

Canonical IDs always use `family:basename`, with `family` one of `vr`, `mdx`,
`demucs`, or `apollo`. Get the exact installed ID from `uvr models list`:

```bash
uvr separate song.wav -o /tmp/stems --model mdx:UVR-MDX-NET-Inst_HQ_4
```

Do not replace an ID with a friendly label in saved configuration or CLI input.
Labels can change or be ambiguous, so the application never reverses a display
name into a filename. A malformed or unavailable stored ID remains in settings;
the picker shows **Choose Model** until you choose an installed model again.

## Custom and unknown models

Download Center installs are registered automatically, including MDX-C
checkpoints paired with YAML and Apollo checkpoints paired with configuration.
For an MDX-C file downloaded before registration was added, the application
tries its catalogue entry on first use.

For a manually placed, unknown checkpoint, use the GTK unrecognized-model
dialog. For a community MDX-C `.ckpt`, select its matching YAML; the dialog
recognises Roformer, SCNet, and BandIt shapes and persists the result. It also
collects architecture-specific VR or classic MDX-Net parameters. Audio Tools
can similarly associate an unknown Apollo checkpoint with its configuration.

The CLI registration flow copies a checkpoint into its model family and requires
a JSON configuration:

```bash
uvr models register /path/to/model.ckpt --family mdx --config /path/to/model.json
```

Use `uvr models validate` to check installed models and configuration. A
historic Demucs-root single `.ckpt` is not a runnable Demucs record in this
port; `uvr models validate` with no model argument reports it as unsupported.

## Supported special families

### SCNet

[SCNet](https://github.com/starrytong/SCNet) music models commonly separate
**Drums**, **Bass**, **Other**, and **Vocals**. They use a `.ckpt` checkpoint
and matching YAML under `models/MDX_Net_Models/model_data/mdx_c_configs/`.
Download them via **Download Center → MDX-Net**, select them in the MDX-Net
method, then choose the stems to export. Masked and Tran use the same route.

### BandIt

[BandIt](https://github.com/kwatcharasupat/bandit) separates cinematic audio
into **Speech**, **Music**, and **Sfx** (called **Effects** by some models).
Download it via **Download Center → MDX-Net**. The
[BandIt v2 implementation](https://github.com/kwatcharasupat/bandit-v2) runs
internally at 48 kHz then exports at 44.1 kHz; BandIt Plus runs at 44.1 kHz.

### Apollo

[Apollo](https://github.com/JusperLee/Apollo) is an Audio Tools restoration
family, not a stem separator. Use its Audio Tools picker or a supported
Download Center row. Manually placed `.ckpt` or `.bin` files belong in
`models/Apollo_Models/` and need matching configuration metadata.

## Advanced: catalogue mechanics

`CatalogueCoordinator` owns source snapshots, merging, projections, and typed
deltas. Filesystem inventory remains the only installed-membership source for
GUI pickers and the default `uvr models list`.

Download Center merges catalogues in this order; earlier labels win:

1. Official TRvlvr `download_checks.json` (live refresh under the cache
   directory; bundled `model_manual_download.json` is read-only fallback).
2. [Politrees `UVR_resources`](https://github.com/Politrees/UVR_resources).
3. Fork-curated [`bundled/extra_models.json`](../bundled/extra_models.json).
4. [noblebarkrr/mvsepless_resources](https://huggingface.co/noblebarkrr/mvsepless_resources)
   `models.json` (live fetch, 24-hour disk cache).

Upstream MDX flattening includes `scnet_download_list` and
`bandit_download_list` before supplements, so a live TRvlvr selection wins over
an extras duplicate. The labels affected before those lists were flattened are
recorded in `PRIOR_EXTRAS_SCNET_BANDIT_WINNERS`. The mvsepless feed has no
declared Hugging Face license tag; this app indexes URLs and downloads into
local model directories, but does not rehost weights.

Deduplication retains the first selectable for each checkpoint basename,
normalized label, normalized checkpoint URL (removing `?download=true`), and
trusted Hugging Face `X-Linked-Etag` content identity. Weak/ordinary HTTP ETags
and `Last-Modified` are URL-scoped and do not deduplicate across URLs. Demucs
bags collide only when their file-to-URL maps or normalized labels match;
sharing individual bag members is not a collision. Source-disable switches are
documented in [environment.md](environment.md#catalogue-and-download-configuration).

Explicit Download Center **Refresh** and online `uvr models catalog` or
`uvr models download` revalidate every remote source and publish one mixed-age
snapshot. Failed sources retain their last good payload; online CLI warns about
stale/partial state and fails only with no usable snapshot. `allow_network=False`
performs no HTTP and starts no workers. `allow_metadata_writes=False` also
prevents cache migration and envelope writes. Stale-while-revalidate starts when
a list is opened, not at GTK startup. Identity removals apply incrementally;
source additions or changes mark the open window pending and rebuild on its next
explicit refresh or `present()`.

Checkpoint-size HEADs run when Download Center opens and after a successful
refresh, not at startup. Same-size identity requests are capped per pass and
oldest-first; passes repeat until none remain. On a cold cache, URL/label
dedupe still works while content-identity dedupe waits for HEAD results. Later
identity removals delete only affected rows (250 ms debounce) rather than
rebuilding and resetting scroll position. YAML stem subtitles fetch in the
background with two concurrent requests; active filtered rows take priority.
The separation pickers remain unaffected by Download Center deduplication:
their metadata index is built before that presentation-only dedupe pass.

The upstream `model_name_mapper.json` refreshes verbatim. Local and registered
names live in `model_name_mapper_local.json`; reads overlay local values, while
refresh replaces only the upstream mirror. Existing installations migrate keys
removed upstream to the local overlay once. Hash maps still replace on content
change.

### Unsupported rows and probing

Unsupported rows stay visible in the matching network tab with a short reason.
These are portability limits, not a guarantee that the current feed has a row
of every class:

| Class | Why |
|---|---|
| Medley-Vox | No engine port. |
| MSST HTDemucs (single `.ckpt`) | Not the Facebook Demucs bag format. |
| Classic VR from mvsepless | Needs a `.ckpt` + YAML-to-VR-hash bridge; use TRvlvr/Politrees VR. |
| Classic MDX-Net ONNX from mvsepless | Needs a YAML-to-hash bridge; use TRvlvr ONNX. |
| Windowed Sink Attention Mel-Band (`mbr_wsa`) | Attention features are not ported. |
| BS Conformer (`bs_cr_4stem_zf_turbo`) | Conformer blocks are not ported. |

[`scripts/model_probe.py`](../scripts/model_probe.py) tests whether this build
could run an entry without downloading full weights: it fetches the small YAML,
builds with random parameters, and runs a real forward pass. `--check-keys`
range-fetches only the checkpoint header (about 90 KB of a 448 MB example) and
compares `state_dict` names, caching responses by URL.

```bash
python scripts/model_probe.py --entry mbr_syhft_4stem              # fetch YAML, build, forward
python scripts/model_probe.py --entry mbr_wsa --check-keys         # plus key comparison
python scripts/model_probe.py --config /path/to/local.yaml \
  --checkpoint /path/to/local.ckpt  # offline
python scripts/model_probe.py --sweep --check-keys
```

Exit status is 0 only for `buildable`:

| Verdict | Meaning |
|---|---|
| `probe-error` | (`--sweep` only) The entry could not be fetched/read, not a build/forward result. |
| `build-failed` | The architecture does not instantiate. |
| `forward-failed` | It instantiates but the forward pass fails. |
| `config-ignored` | It built only because kwarg filtering discarded YAML keys. |
| `key-mismatch` | It runs but checkpoint parameter names disagree. |
| `buildable` | It builds, runs, and, when checked, matches checkpoint keys. |

Treat `config-ignored` as a warning: MDX-C kwarg filtering can build a model
while omitting the feature that matters. See
[`docs/unsupported-models-probe.md`](unsupported-models-probe.md) for the
point-in-time sweep and grouped findings.

VR and MSST HTDemucs are *probeable*, not supported. The probe can construct
VR `CascadedASPPNet`/`CascadedNet` and vendored-but-unwired HTDemucs, but the
separation engines do not use those paths. A VR probe needs `--checkpoint` or
`--check-keys` because its variant comes from checkpoint size, not YAML; without
one it reports `build-failed` rather than guessing. VR6 ("v6 beta3") has no
matching network class and is explicitly `build-failed`.

## Advanced: identity contract

`ModelRecord` separates execution identity from presentation:

| Field | Meaning |
|---|---|
| `id` (`family:basename`) | Exact storage/execution key across `vr`, `mdx`, `demucs`, and `apollo`. |
| `display` | Human-facing GUI and CLI label. |
| Catalogue selectable (`CatalogueRef`) | Download Center identity in the separate `catalog:{family}:{urlencoded(selection)}` namespace. |
| `backend_name` | The legacy engine's selection/loading value. |
| `artifacts` | The primary and supporting model files. |

`build_identity_index` constructs an offline `IdentityIndex` for each
`(inventory_generation, catalogue_revision, naming_revision)` tuple from the
catalogue, installed files, bundled Demucs specifications, and Demucs registry.
It does not fetch YAML, hash checkpoints, or access the network. Lookup is an
exact `family:basename` dictionary lookup; only the display layer projects
friendly labels, and runtime code never resolves a display label to a basename.

GUI method, ensemble, and karaoke pickers list installed records, including
configurable-but-incomplete Demucs `.th`/YAML records. `uvr models list
--all-known` adds uninstalled catalogue records. The runtime does not migrate
old model strings or silently substitute a similarly named model; there is no
identity migrator or identity-schema version.

## Advanced: specialised Roformer support

### HyperACE BS-Roformer

[`BS-Roformer-HyperACE`](https://huggingface.co/pcunwa/BS-Roformer-HyperACE)
entries add a segmentation branch to each mask estimator: depthwise-separable
CSP backbone, hypergraph attention, gated FPN decoder, and frequency
pixel-shuffle head. [`ml/hyperace.py`](../ml/hyperace.py) sums it with the
per-band mask MLP output. v1 has 398 segmentation/1097 total keys and 68.6M
parameters; v2 has 471/1170 and 72.0M. v1 strides time only, has no upsample
`out_conv`, uses 16 hyperedges and `k=3, l=2`; v2 also halves bands in `p4`/`p5`,
adds TFC-TDF `out_conv` refinements, and uses 32 hyperedges and `k=2, l=1`.

The checkpoint determines the variant: upstream configs declare no marker, and
only packaged v2-instrumental YAML has top-level `hyperace2: true`. The loader
detects `segm.*` and v2's `upsample_head.*.out_conv`; `hyperace2` is fallback
when keys are unavailable. Verify without running separation:

```bash
python scripts/model_probe.py --config /path/to/hyperace.yaml \
  --checkpoint /path/to/hyperace.ckpt
# state_dict   1170 matched, 0 missing, 0 unexpected
```

All three published checkpoints were verified from about 300 KB range-fetched
headers instead of 853 MB weights. `use_torch_checkpoint` remains accepted but
optional when the BS-Roformer implementation supports checkpointing.

### PoPE BS-Roformer ("BS PolarFormer")

Community "BS PolarFormer" checkpoints set `use_pope: true` and replace rotary
embeddings with [Polar Coordinate Positional Embedding](https://arxiv.org/abs/2509.10534),
implemented through [PoPE-pytorch](https://pypi.org/project/PoPE-pytorch/).
Magnitudes pass through `softplus`, rotate by a per-head/per-frequency phase,
and receive a learned key-side bias. Unlike HyperACE, `use_pope` is an ordinary
YAML constructor key and needs no checkpoint-key detection.

There is one PoPE module for time and one for frequency, shared across outer
layers rather than recreated per layer. The verified `bs_pope_vocals_zfturbo`
checkpoint has identical same-axis `pope_embed.bias`/`pope_embed.inv_freqs`
across its 12 layers and different values between axes; loading reports 723
matched keys with none missing or unexpected.

### Primary implementation sources

These are primary architecture sources, not a duplicate of the full project
acknowledgements:

- [starrytong/SCNet](https://github.com/starrytong/SCNet) is the official
  original SCNet implementation.
- [Music-Source-Separation-Training](https://github.com/ZFTurbo/Music-Source-Separation-Training)
  supplies the MSST implementations used for SCNet Masked and SCNet Tran, plus
  related MDX-C support.
- [lucidrains/BS-RoFormer](https://github.com/lucidrains/BS-RoFormer) supplies
  the Band-Split and Mel-Band Roformer lineage.
- [BandIt](https://github.com/kwatcharasupat/bandit),
  [BandIt v2](https://github.com/kwatcharasupat/bandit-v2), and
  [Apollo](https://github.com/JusperLee/Apollo) are the source projects for
  those families.
- [BS-Roformer-HyperACE](https://huggingface.co/pcunwa/BS-Roformer-HyperACE)
  and [PoPE-pytorch](https://pypi.org/project/PoPE-pytorch/) are the sources for
  the specialised Roformer paths above.
