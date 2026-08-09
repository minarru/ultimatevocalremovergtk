# Unsupported-catalogue probe results (2026-08-09)

A full [`scripts/model_probe.py`](../scripts/model_probe.py) sweep of every mvsepless catalogue
entry `classify_entry` currently marks **unsupported** — 115 entries at the time of this run, out
of 415 total. This is a point-in-time snapshot for triage, not a live status page; the mvsepless
catalogue and this port both move. Regenerate with:

```bash
python scripts/model_probe.py --sweep --check-keys --json /tmp/unsupported_sweep.json
```

`--check-keys` range-fetches each checkpoint's header (no full downloads) to diff `state_dict`
names against what the probe builds. See [models.md](models.md#triaging-an-unsupported-entry) for
what each verdict means and the general triage workflow this sweep is part of.

## Verdict tally

| Verdict | Count | Meaning |
|---|---|---|
| `build-failed` | 63 | Architecture does not instantiate at all. |
| `buildable` | 33 | Builds, runs, and (checked) matches the checkpoint's keys. |
| `config-ignored` | 15 | Builds only because kwarg filtering silently dropped yaml keys. |
| `key-mismatch` | 4 | Runs, but parameter names disagree with the checkpoint. |

**None of this reclassifies any entry as supported.** `classify_entry`'s unsupported reasons are
about missing *plumbing* (hash bridges, an engine, a whole bag-of-models format) that this probe
never touches — it only ever builds a standalone module from a yaml, never runs it through
`engines/`. A `buildable` verdict here answers "is the port viable", not "is this in the app".

## By catalogue reason

| Reason | Count | Verdicts |
|---|---|---|
| needs MDX-Net ONNX yaml→hash bridge | 45 | 45 build-failed |
| needs VR .ckpt+yaml hash bridge | 41 | 33 buildable, 4 build-failed, 4 key-mismatch |
| MSST Demucs single-ckpt format not supported | 16 | 13 config-ignored, 3 build-failed |
| Medley-Vox engine not ported | 11 | 11 build-failed |
| Windowed Sink Attention Mel-Band not ported | 1 | 1 config-ignored |
| BS Conformer not ported | 1 | 1 config-ignored |

---

## needs MDX-Net ONNX yaml→hash bridge (45, all build-failed)

Every entry fails identically: `AttributeError: "'norm'"`. These are classic MDX-Net **ONNX**
checkpoints; their yaml has no `model:` section this probe's architecture builders recognize
(not MDX-C, not a Roformer, not SCNet/Bandit), so it falls through to the `TFC_TDF_net` (MDX23C)
fallback as a last resort — which then crashes reading `model.norm`, a field only genuine MDX23C
configs declare. This is expected and uninformative per-entry: none of these are meant to build
via this path at all. They need an ONNX Runtime loader plus the yaml→hash bridge noted in
[models.md](models.md), not an architecture port.

<details>
<summary>All 45 entries</summary>

mdx_kim_inst, mdx_kim_vocal1, mdx_kim_vocal2, mdx_kuielab_a_bass, mdx_kuielab_a_drums,
mdx_kuielab_a_other, mdx_kuielab_a_vocals, mdx_kuielab_b_bass, mdx_kuielab_b_drums,
mdx_kuielab_b_other, mdx_kuielab_b_vocals, mdx_reverb_hq_foxjoy, mdx_inst1, mdx_inst2, mdx_inst3,
mdx_inst_full_292, mdx_inst_hq1, mdx_inst_hq2, mdx_inst_hq3, mdx_inst_hq4, mdx_inst_hq5,
mdx_inst_main, mdx_vocft, mdx_crowd_hq1, mdx_inst_187_beta, mdx_inst_82_beta, mdx_inst_90_beta,
mdx_main_340, mdx_main_390, mdx_main_406, mdx_main_427, mdx_main_438, mdx_1_9703, mdx_2_9682,
mdx_3_9662, mdx_9482, mdx_karaoke1, mdx_karaoke2, mdx_main, mdx_6s_piano_anvuew,
mdx_6s_vocals_anvuew, mdx_6s_drum_anvuew, mdx_6s_bass_anvuew, mdx_6s_acoustic_guitar_anvuew,
mdx_6s_electric_guitar_anvuew

</details>

## needs VR .ckpt+yaml hash bridge (41)

**33 `buildable`.** All standard VR5/"5.1" family models (`CascadedASPPNet`/`CascadedNet`), same
architecture already ported in [`ml/vr_network/`](../ml/vr_network/). Per
[models.md](models.md#triaging-an-unsupported-entry), **VR is probeable, not supported** — the
probe builds the network standalone; `engines/vr.py` never runs it. "Buildable" here means the
port is architecturally sound for these, gated only on the yaml→hash bridge, not on any porting
work.

<details>
<summary>All 33 buildable entries</summary>

1_hp-uvr, 2_hp-uvr, 3_hp-vocal-uvr, 4_hp-vocal-uvr, 5_hp-karaoke-uvr, 6_hp-karaoke-uvr,
7_hp2-uvr, 8_hp2-uvr, 9_hp2-uvr, 10_sp-uvr-2b-32000-1, 11_sp-uvr-2b-32000-2, 12_sp-uvr-3b-44100,
13_sp-uvr-4b-44100-1, 14_sp-uvr-4b-44100-2, 15_sp-uvr-mid-44100-1, 16_sp-uvr-mid-44100-2,
17_hp-wind_inst-uvr, uvr-deecho-dereverb, uvr-bve-4b_sn-44100-1, uvr-bve-v2-4b-sn-44100,
mgm-v5-karokee-32000-beta1, mgm-v5-karokee-32000-beta2-agr, mgm_highend_v4, mgm_lowend_a_v4,
mgm_lowend_b_v4, mgm_main_v4, uvr-de-reverb-aufr33-jarredou, uvr-de-breath-sucial-v1,
uvr-de-breath-sucial-v2, vr_harmonic_noise_sep, bass-4band-3090_4band, drums-4band-3090_4band,
wip-piano-4band-129605kb

</details>

**4 `key-mismatch` — a real architecture gap, not a bridge problem.** FoxJoy's De-Echo/DeNoise
family (`uvr-de-echo-aggressive`, `uvr-de-echo-normal`, `uvr-denoise-lite`, `uvr-denoise`) all
report the same diff: 109 matched / 350 missing / 580 unexpected. The checkpoint has **two**
auxiliary heads (`aux1_out`, `aux2_out`) where the ported `CascadedASPPNet` has one (`aux_out`),
and its ASPP bottleneck nests one level deeper (`aspp.bottleneck.0.conv.*` vs. the ported
`aspp.bottleneck.conv.*`). This is a distinct VR variant this port's `ml/vr_network/` does not
implement — separate from the yaml→hash bridge gap the other 37 VR entries have. Worth its own
tracked item if these models matter; see [`docs/tracked-issues.md`](tracked-issues.md) item 6.

**4 `build-failed`, two different reasons:**

- `vr6_last_baseline_tsurumeso`, `vr6_bass_drypaint`, `vr6_soprano_drypaint` — VR6 ("v6 beta3").
  Confirms the existing note in [models.md](models.md#triaging-an-unsupported-entry): no class
  anywhere in `ml/vr_network/` implements VR6, reported honestly rather than silently built as
  the wrong (VR5) architecture.
- `vr_multi_drums_beta` — `ValueError: VR architecture selection needs a checkpoint size`. This
  one has a `checkpoint_url` and should have had its size range-fetched like the other 40; the
  fetch likely failed transiently for this specific host response. Re-run
  `--entry vr_multi_drums_beta --check-keys` to confirm before treating it as architecturally
  distinct from the 33 buildable entries above.

## MSST Demucs single-ckpt format not supported (16)

**13 `config-ignored`**, all missing `num_subbands` — an HTDemucs yaml field this vendored,
never-wired-up `HTDemucs` ([`vendor/demucs/htdemucs.py`](../vendor/demucs/htdemucs.py)) doesn't
implement. Consistent across `demucs4_mvsep_vocals`, `demucs4_4stem`, `demucs4_6stem`,
`demucs4_ft_bass`, `demucs4_ft_drums`, `demucs4_ft_vocals`, `demucs4_ft_other`,
`demucs_mid_side_wesleyr36`, `demucs4_choirsep`, `demucs4_drumsep_4stem_inagoy`,
`demucs4_cdx_zfturbo_1/2/3`, `demucs4_lead_rhythm_guitar_drypaint`.

**A probe-tooling gap surfaced here, not a port gap:** 4 of those 13
(`demucs4_6stem`, `demucs4_cdx_zfturbo_1/2/3`) show `0 matched / ~380-525 missing / 6 unexpected`,
with the "unexpected" keys being `args`, `klass`, `kwargs`, `metrics`, `state` — the top level of
Demucs's own training-experiment ("XP"/solver) checkpoint wrapper, distinct from the
Lightning-style wrapper `torch_checkpoint_state_dict_keys` already unwraps
(see `TorchCheckpointKeyTests.test_descends_into_a_lightning_style_wrapper` in
[`tests/test_model_probe.py`](../tests/test_model_probe.py)). The real weights are nested one
level deeper (under `state`, typically) and never got extracted, so these four key-diffs are
noise, not a real 0%-match finding — worth teaching the checkpoint-key reader this second wrapper
shape if MSST Demucs support is ever prioritized.

**3 `build-failed`** (`demucs3_mmi`, `demucs4_drumsep_4stem_inagoy`, `demucs3_saxophone`):
`ValueError: htdemucs config has no 'htdemucs' kwargs section`. Their yaml declares `model:
hdemucs` — the older **Hybrid Demucs v3** bag-of-models architecture, genuinely distinct from the
v4 `HTDemucs` this repo vendors. Not a config variant of the same network; a different,
unvendored one. The catalogue reason ("single-ckpt format not supported") undersells this a
little — it's not just packaging, HDemucs v3 has no ported class here at all.

## Medley-Vox engine not ported (11, all build-failed)

Every entry: `AttributeError: "'norm'"` — same generic TFC_TDF_net-fallback crash as the MDX-Net
ONNX group, for the same reason (no `engines/` support exists to give this probe anything better
to try). Uninformative per-entry, expected: `multi_singing_librispeech`,
`multi_singing_librispeech_138`, `singing_librispeech_ft_isrnet`, `singing_librispeech_isrnet`,
`medley_vox_vocal_231`, `medley_vox_vocals_135`, `medley_vox_vocals_163`, `medley_vox_vocals_188`,
`medley_vox_vocals_200`, `medley_vox_vocals_238`, `medley_vox_choirsep_drypaint`.

## Windowed Sink Attention Mel-Band not ported (1, config-ignored)

`mbr_wsa` — Windowed Sink Attention Mel-Band Roformer Vocals by Smule Labs. Dropped config keys:
`num_sink_tokens`, `use_flex_attention`, `window_size`. State dict: **684 matched, 0 missing, 1
unexpected** (`sink_tokens`) — by far the smallest gap in this whole sweep. Everything else about
this checkpoint is a plain `MelBandRoformer`; only the windowed-sink-token attention variant is
missing. If any single unsupported entry in this sweep is worth porting next, this is the
cheapest one.

## BS Conformer not ported (1, config-ignored)

`bs_cr_4stem_zf_turbo` — BS Conformer 4 Stems by ZFTurbo. Dropped config keys:
`conv_expansion_factor`, `conv_kernel_size`, `ff_mult`, `freq_conformer_depth`, `sage_attention`,
`time_conformer_depth`. Unlike `mbr_wsa` above, **`config-ignored` undersells how wrong this
build is**: state dict shows 1179 matched / **264 missing / 348 unexpected** out of roughly 1500
keys. The checkpoint's attention blocks nest as `layers.N.M.layers.0.attn.*` (a Conformer block
wrapping its own attention submodule); the plain `BSRoformer` this probe falls back to has
`layers.N.M.layers.0.0.*` (attention directly, no Conformer wrapper) — genuinely different block
structure, not a missing-flag situation. This one would need real Conformer blocks ported into
`ml/bs_roformer.py` (or a sibling module), not a kwarg fix.

---

## Summary: what's worth doing next, if anything

Ranked by (estimated port effort) vs. (how wrong the current build is):

1. **`mbr_wsa`** — smallest real gap (1 unexpected key), single entry. Cheapest genuine port.
2. **Demucs XP-wrapper checkpoint-key unwrapping** — a probe/tooling fix (teach
   `torch_checkpoint_state_dict_keys` to descend into `state`), not an architecture port; clears
   the noise on 4 of the 16 MSST Demucs entries so real diffs are visible there.
3. **FoxJoy De-Echo/DeNoise VR variant** — 4 checkpoints, needs a second aux head and a bottleneck
   nesting change in `ml/vr_network/`.
4. Everything else (ONNX bridge, VR5 hash bridge, Medley-Vox engine, HDemucs v3, BS Conformer) is
   either pure plumbing (bridges) or a substantially larger port (a whole engine, a whole
   architecture family) — correctly out of scope for a kwarg-level fix.
