# UVR Model Catalogue (TRvlvr + Politrees)

Generated: 2026-07-12 15:47 UTC by `scripts/generate_models_catalogue.py`.

Regenerate after catalogue updates:

```bash
python scripts/generate_models_catalogue.py
```

Intent sources: catalogue label, yaml/hash metadata, Politrees model_data,
and [upseem/uvr5-cli-no-ui models.txt](https://github.com/upseem/uvr5-cli-no-ui/blob/main/models.txt)
(cached as `docs/model_intent_reference.tsv`).

## How to read this

- **Name intent** — from label, metadata, or community reference.
- **Backend focus** — what `ModelData` uses as `primary_stem` at runtime.
- **Best result** — the stem users typically want from that model name.
- **Flags** — vocal/instrumental labelling mismatches (only when metadata resolved).

### Roformer `other` yaml quirk (not a bug)

Instrumental Mel-Band / BS models often use `target_instrument: other` with
`instruments: [other, vocals]`. That is a **2-stem vocal/instrumental** split.
The GUI should show **Vocals** / **Instrumental** for 2-stem yaml pairs, not Demucs Other.

## Summary

- Total catalogue entries: **198**
- Entries with resolved metadata: **198**
- Unknown intent remaining: **0**
- Flagged mismatches: **0**

## Quick reference (all models)

| Family | Model | Intent | Best result | Backend | Target | Flags |
| --- | --- | --- | --- | --- | --- | --- |
| VR Architecture | VR Arch Single Model v4: MGM_HIGHEND_v4 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v4: MGM_LOWEND_A_v4 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v4: MGM_LOWEND_B_v4 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v4: MGM_MAIN_v4 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 10_SP-UVR-2B-32000-1 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 11_SP-UVR-2B-32000-2 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 12_SP-UVR-3B-44100 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 13_SP-UVR-4B-44100-1 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 14_SP-UVR-4B-44100-2 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 15_SP-UVR-MID-44100-1 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 16_SP-UVR-MID-44100-2 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 17_HP-Wind_Inst-UVR | instrumental | instrumental | unknown | no woodwinds | — |
| VR Architecture | VR Arch Single Model v5: 1_HP-UVR | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 2_HP-UVR | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 3_HP-Vocal-UVR | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| VR Architecture | VR Arch Single Model v5: 4_HP-Vocal-UVR | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| VR Architecture | VR Arch Single Model v5: 5_HP-Karaoke-UVR | karaoke | Karaoke backing (Instrumental primary; complement … | karaoke_instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 6_HP-Karaoke-UVR | karaoke | Karaoke backing (Instrumental primary; complement … | karaoke_instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 7_HP2-UVR | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 8_HP2-UVR | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: 9_HP2-UVR | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| VR Architecture | VR Arch Single Model v5: UVR-BVE-4B_SN-44100-1 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| VR Architecture | VR Arch Single Model v5: UVR-De-Echo-Aggressive by FoxJoy | special_fx | special_fx | unknown | no echo | — |
| VR Architecture | VR Arch Single Model v5: UVR-De-Echo-Normal by FoxJoy | special_fx | special_fx | unknown | no echo | — |
| VR Architecture | VR Arch Single Model v5: UVR-DeEcho-Aggressive by FoxJoy | special_fx | special_fx | unknown | no echo | — |
| VR Architecture | VR Arch Single Model v5: UVR-DeEcho-DeReverb by FoxJoy | special_fx | special_fx | unknown | no reverb | — |
| VR Architecture | VR Arch Single Model v5: UVR-DeEcho-Normal by FoxJoy | special_fx | special_fx | unknown | no echo | — |
| VR Architecture | VR Arch Single Model v5: UVR-DeNoise by FoxJoy | special_fx | special_fx | unknown | noise | — |
| VR Architecture | VR Arch Single Model v5: UVR-DeNoise-Lite by FoxJoy | special_fx | special_fx | unknown | noise | — |
| VR Architecture | VR Arch Single Model v5: UVR-DeReverb by aufr33 & jarredou | special_fx | special_fx | unknown | dry | — |
| Bandit | Bandit Plus: Cinematic Bandit Plus by kwatcharasupat | multi_stem | Multi-stem: Speech, Music, Effects | multi_stem | Speech | — |
| Bandit | Bandit v2: Cinematic Bandit v2 Multilang by kwatcharasupat | multi_stem | Multi-stem: Speech, Music, Sfx | multi_stem | Speech | — |
| MDX-Net ONNX | MDX-Net Model: Kim Inst | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net Model: Kim Vocal 1 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net Model: Kim Vocal 2 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net Model: Reverb HQ By FoxJoy | special_fx | special_fx | unknown | reverb | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET 1 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET 2 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET 3 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Crowd HQ 1 By Aufr33 | instrumental | instrumental | unknown | no crowd | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Inst 1 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Inst 2 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Inst 3 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Inst HQ 1 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Inst HQ 2 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Inst HQ 3 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Inst HQ 4 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Inst HQ 5 | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Inst Main | instrumental | Instrumental (+ Vocals complement) | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Karaoke | karaoke | Karaoke vocals (Vocals primary; complement = instr… | karaoke_vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Karaoke 2 | karaoke | Karaoke backing (Instrumental primary; complement … | instrumental_primary | Instrumental | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Main | dual_voc_inst | Vocals or Instrumental — both are first-class 2-st… | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net Model: UVR-MDX-NET Voc FT | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net Model: UVR_MDXNET_9482 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net Model: kuielab_a_bass | multi_stem | multi_stem | unknown | bass | — |
| MDX-Net ONNX | MDX-Net Model: kuielab_a_drums | multi_stem | multi_stem | unknown | drums | — |
| MDX-Net ONNX | MDX-Net Model: kuielab_a_other | multi_stem | multi_stem | unknown | other | — |
| MDX-Net ONNX | MDX-Net Model: kuielab_a_vocals | multi_stem | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX-Net ONNX | MDX-Net Model: kuielab_b_bass | multi_stem | multi_stem | unknown | bass | — |
| MDX-Net ONNX | MDX-Net Model: kuielab_b_drums | multi_stem | multi_stem | unknown | drums | — |
| MDX-Net ONNX | MDX-Net Model: kuielab_b_other | multi_stem | multi_stem | unknown | other | — |
| MDX-Net ONNX | MDX-Net Model: kuielab_b_vocals | multi_stem | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX23C | MDX23 Model: MDX23C_D1581 | vocals | Vocals (+ Instrumental complement) | vocal_primary | Vocals | — |
| MDX23C | MDX23C Model: MDX23C DeReverb by aufr33 & jarredou | special_fx | dry, No dry | two_stem | dry | — |
| MDX23C | MDX23C Model: MDX23C DrumSep by aufr33 & jarredou | multi_stem | Multi-stem: kick, snare, toms, hh, ride, crash | multi_stem | kick | — |
| MDX23C | MDX23C Model: MDX23C InstVoc HQ | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | two_stem | Vocals | — |
| MDX23C | MDX23C Model: MDX23C Phantom Centre extraction by wesleyr36 | vocals | Similarity (single native output) | single_target:Similarity | Similarity | — |
| Roformer | BandSplit Roformer \| 4-stems FT by SYH99999 | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| Roformer | BandSplit Roformer \| Chorus Male-Female by Sucial | vocals | male, female | two_stem | male | — |
| Roformer | BandSplit Roformer \| Dereverb by anvuew | special_fx | noreverb (single native output) | single_target:noreverb | noreverb | — |
| Roformer | BandSplit Roformer \| FNO by Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| Roformer | BandSplit Roformer \| Inst-EXP-Value-Residual by Unwa | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | BandSplit Roformer \| Karaoke Frazer by becruily | karaoke | Karaoke backing (Instrumental primary; complement … | vocal_target | Vocals | — |
| Roformer | BandSplit Roformer \| Male-Female by aufr33 | vocals | male, female | two_stem | male | — |
| Roformer | BandSplit Roformer \| Resurrection Instrumental by Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| Roformer | BandSplit Roformer \| Resurrection Vocals by Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | BandSplit Roformer \| Revive by Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | BandSplit Roformer \| Revive v2 by Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | BandSplit Roformer \| Revive v3 by Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | BandSplit Roformer \| SDR 1053 by Viperx | drum_bass_sep | No Drum-Bass (drum/bass separation; complement = D… | drum_bass_target | No Drum-Bass | — |
| Roformer | BandSplit Roformer \| SDR 1296 by Viperx | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | BandSplit Roformer \| SDR 1297 by Viperx | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | BandSplit Roformer \| SW by jarredou | multi_stem | Multi-stem: bass, drums, other, vocals, guitar, pi… | multi_stem | bass | — |
| Roformer | BandSplit Roformer \| Vocals by Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer Kim \| Big Beta v4 FT by Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| Big Beta v5e FT by Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| Big Beta v6 FT by Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| Big Beta v6x FT by Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| Big SYHFT v1 by SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| FT by Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| FT v2 Bleedless by Unwa | special_fx | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| FT v2 by Unwa | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| Inst v1 by Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| Roformer | MelBand Roformer Kim \| Inst v1e Plus by Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| Roformer | MelBand Roformer Kim \| Inst v1e by Unwa | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| Roformer | MelBand Roformer Kim \| Inst v2 by Unwa | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer Kim \| InstVoc Duality v1 by Unwa | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | two_stem | Vocals | — |
| Roformer | MelBand Roformer Kim \| InstVoc Duality v2 by Unwa | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | two_stem | Vocals | — |
| Roformer | MelBand Roformer Kim \| SYHFT by SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| SYHFT v2 by SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| SYHFT v2.5 by SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| SYHFT v3 by SYH99999 | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| Vocals Fullness v1 by Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| Vocals Fullness v2 by Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| Vocals v1 by Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| Vocals v2 by Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer Kim \| Vocals v3 by Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer \| 4-stems FT Large v1 by SYH99999 | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| Roformer | MelBand Roformer \| 4-stems FT Large v2 by SYH99999 | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| Roformer | MelBand Roformer \| 4-stems Large v1 by Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| Roformer | MelBand Roformer \| 4-stems XL v1 by Aname | multi_stem | Multi-stem: drums, bass, other, vocals | multi_stem | drums | — |
| Roformer | MelBand Roformer \| Aspiration Less Aggressive by Sucial | vocals | aspiration, other | two_stem | aspiration | — |
| Roformer | MelBand Roformer \| Aspiration by Sucial | vocals | aspiration, other | two_stem | aspiration | — |
| Roformer | MelBand Roformer \| BVE by Gonza | vocals | Lead (single native output) | single_target:Lead | Lead | — |
| Roformer | MelBand Roformer \| Bleed Suppressor v1 by Unwa & 97chris | special_fx | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Crowd by Aufr33 & Viperx | instrumental | crowd (single native output) | single_target:crowd | crowd | — |
| Roformer | MelBand Roformer \| DeReverb Big by Sucial | special_fx | dry (single native output) | single_target:dry | dry | — |
| Roformer | MelBand Roformer \| DeReverb Less Aggressive by anvuew | special_fx | noreverb (single native output) | single_target:noreverb | noreverb | — |
| Roformer | MelBand Roformer \| DeReverb Mono by anvuew | special_fx | noreverb (single native output) | single_target:noreverb | noreverb | — |
| Roformer | MelBand Roformer \| DeReverb Super Big by Sucial | special_fx | dry (single native output) | single_target:dry | dry | — |
| Roformer | MelBand Roformer \| DeReverb by anvuew | special_fx | noreverb (single native output) | single_target:noreverb | noreverb | — |
| Roformer | MelBand Roformer \| DeReverb-Echo Fused by Sucial | special_fx | dry (single native output) | single_target:dry | dry | — |
| Roformer | MelBand Roformer \| DeReverb-Echo by Sucial | special_fx | dry, No dry | two_stem | dry | — |
| Roformer | MelBand Roformer \| DeReverb-Echo v2 by Sucial | special_fx | dry (single native output) | single_target:dry | dry | — |
| Roformer | MelBand Roformer \| Denoise Aggr by Aufr33 | special_fx | dry (single native output) | single_target:dry | dry | — |
| Roformer | MelBand Roformer \| Denoise by Aufr33 | special_fx | dry (single native output) | single_target:dry | dry | — |
| Roformer | MelBand Roformer \| Duality v1 by Aname | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | vocal_target | vocals | — |
| Roformer | MelBand Roformer \| Guitar by becruily | instrumental | Guitar (single native output) | single_target:Guitar | Guitar | — |
| Roformer | MelBand Roformer \| Instrumental Bleedless v1 by Gabox | special_fx | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Bleedless v2 by Gabox | special_fx | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental DeNoise-DeBleed by Gabox | special_fx | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness v1 by Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness v2 by Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness v3 by Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness v4 Noise by Gabox | special_fx | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness v5 Noise by Gabox | special_fx | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness v5 by Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness v6 Noise by Gabox | special_fx | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness v6 by Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness v7 Noise by Gabox | special_fx | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness v7 by Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness v8 by Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental Fullness vX by Gabox | dual_voc_inst | User picks Vocals or Instrumental (dual 2-stem) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental by Gabox | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental by becruily | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental v1 by Gabox | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental v2 by Gabox | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Instrumental v3 by Gabox | instrumental | Instrumental (complement = Vocals) | instrumental_target | Instrumental | — |
| Roformer | MelBand Roformer \| Karaoke Fusion Aggressive by Gonza | karaoke | Karaoke backing (Instrumental primary; complement … | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Karaoke Fusion Aggressive v2 by Gonza | karaoke | Karaoke backing (Instrumental primary; complement … | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Karaoke Fusion Standard by Gonza | karaoke | Karaoke backing (Instrumental primary; complement … | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Karaoke Fusion Total by Gonza | karaoke | Karaoke backing (Instrumental primary; complement … | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Karaoke by Aufr33 & Viperx | karaoke | Karaoke backing (Instrumental primary; complement … | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Karaoke by Gabox | karaoke | Karaoke backing (Instrumental primary; complement … | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Karaoke by Gabox (beta) | karaoke | Karaoke backing (Instrumental primary; complement … | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Karaoke by becruily | karaoke | Karaoke backing (Instrumental primary; complement … | two_stem | Vocals | — |
| Roformer | MelBand Roformer \| SDR 1143 by Viperx | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Small by Aname | instrumental | Instrumental (+ Vocals complement) | two_stem | Instrumental | — |
| Roformer | MelBand Roformer \| Vocals Bleedless by Aname | special_fx | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer \| Vocals Fullness by Aname | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer \| Vocals Fullness v1 by Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Vocals Fullness v2 by Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Vocals Fullness v3 by Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Vocals Fullness v4 by Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Vocals Fullness v5 by Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Vocals Fullness v6 by Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Vocals by Gabox | vocals | Vocals (complement = Instrumental) | vocal_target | Vocals | — |
| Roformer | MelBand Roformer \| Vocals by Kimberley Jensen | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer \| Vocals by becruily | vocals | Vocals (complement = Instrumental) | vocal_target | vocals | — |
| Roformer | MelBand Roformer \| instrumental Metal preview by Mesk | instrumental | Instrumental (yaml `other`; complement = vocals) | instrumental_target_other_yaml | other | — |
| SCNet | 4-stems SCNet Large | multi_stem | Multi-stem: Drums, Bass, Other, Vocals | multi_stem | Drums | — |
| SCNet | 4-stems SCNet Large by starrytong | multi_stem | Multi-stem: Drums, Bass, Other, Vocals | multi_stem | Drums | — |
| SCNet | 4-stems SCNet MUSDB18 by starrytong | multi_stem | Multi-stem: Drums, Bass, Other, Vocals | multi_stem | Drums | — |
| SCNet | 4-stems SCNet XL | multi_stem | Multi-stem: Drums, Bass, Other, Vocals | multi_stem | Drums | — |
| Demucs | Demucs v1: demucs | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v1: demucs_extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v1: light | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v1: light_extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v1: tasnet | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v1: tasnet_extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2: demucs | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2: demucs48_hq | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2: demucs_extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2: demucs_unittest | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2: tasnet | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v2: tasnet_extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3: UVR Model | dual_voc_inst | 2-stem: instrumental + vocals (user picks focus) | multi_stem |  | — |
| Demucs | Demucs v3: mdx | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3: mdx_extra | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3: mdx_extra_q | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3: mdx_q | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3: repro_mdx_a | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3: repro_mdx_a_hybrid_only | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v3: repro_mdx_a_time_only | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v4: hdemucs_mmi | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v4: htdemucs | multi_stem | 4-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v4: htdemucs_6s | multi_stem | 6-stem Demucs | multi_stem |  | — |
| Demucs | Demucs v4: htdemucs_ft | multi_stem | 4-stem Demucs | multi_stem |  | — |

## Karaoke models

Karaoke models differ by architecture: VR HP-Karaoke uses **Instrumental** as
`primary_stem`; MDX-Net Karaoke uses **Vocals** with `is_karaoke: true`.
Roformer karaoke yamls typically target **vocals** (lead) with instrumental complement.

| Model | Primary | Karaoke flag | Best result |
| --- | --- | --- | --- |
| VR Arch Single Model v5: 5_HP-Karaoke-UVR | Instrumental | yes | Karaoke backing (Instrumental primary; complement = lead vocals) |
| VR Arch Single Model v5: 6_HP-Karaoke-UVR | Instrumental | yes | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MDX-Net Model: UVR-MDX-NET Karaoke | Vocals | yes | Karaoke vocals (Vocals primary; complement = instrumental backing) |
| MDX-Net Model: UVR-MDX-NET Karaoke 2 | Instrumental | — | Karaoke backing (Instrumental primary; complement = lead vocals) |
| BandSplit Roformer \| Karaoke Frazer by becruily | Vocals | — | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MelBand Roformer \| Karaoke Fusion Aggressive by Gonza | Vocals | — | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MelBand Roformer \| Karaoke Fusion Aggressive v2 by Gonza | Vocals | — | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MelBand Roformer \| Karaoke Fusion Standard by Gonza | Vocals | — | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MelBand Roformer \| Karaoke Fusion Total by Gonza | Vocals | — | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MelBand Roformer \| Karaoke by Aufr33 & Viperx | Vocals | — | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MelBand Roformer \| Karaoke by Gabox | Vocals | — | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MelBand Roformer \| Karaoke by Gabox (beta) | Vocals | — | Karaoke backing (Instrumental primary; complement = lead vocals) |
| MelBand Roformer \| Karaoke by becruily | Vocals | — | Karaoke backing (Instrumental primary; complement = lead vocals) |

## Instrumental models with yaml stem `other`

These models are **instrumental-first** in practice. The training yaml names the
native output `other` (not `Instrumental`). Backend `primary_stem` is therefore
`other`, which previously showed as Demucs-style “Other” in the GUI. Relabel to
**Vocals** / **Instrumental** (yaml `other` is the backing track).

| Model | Config | Instruments | Best result |
| --- | --- | --- | --- |
| BandSplit Roformer \| FNO by Unwa | config_BandSplit-Roformer_FNO_by-Unwa.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| BandSplit Roformer \| Resurrection Instrumental by Unwa | config_BandSplit-Roformer_Resurrection_Instrumental_by-Unwa.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer Kim \| Inst v1 by Unwa | config_melband_roformer_inst.yaml | other, vocals | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer Kim \| Inst v1e Plus by Unwa | config_melband_roformer_inst.yaml | other, vocals | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer Kim \| Inst v1e by Unwa | config_melband_roformer_inst.yaml | other, vocals | Instrumental (yaml `other`; complement = vocals) |
| MelBand Roformer \| instrumental Metal preview by Mesk | config_melband_roformer_inst_metal_prev_by_mesk.yaml | vocals, other | Instrumental (yaml `other`; complement = vocals) |

## VR Architecture (detail)

### VR Arch Single Model v4: MGM_HIGHEND_v4

- **Source:** TRvlvr+Politrees
- **Weight:** `MGM_HIGHEND_v4.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (12.3), vocals (6.9)

### VR Arch Single Model v4: MGM_LOWEND_A_v4

- **Source:** TRvlvr+Politrees
- **Weight:** `MGM_LOWEND_A_v4.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.0), vocals (7.0)

### VR Arch Single Model v4: MGM_LOWEND_B_v4

- **Source:** TRvlvr+Politrees
- **Weight:** `MGM_LOWEND_B_v4.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.1), vocals (7.5)

### VR Arch Single Model v4: MGM_MAIN_v4

- **Source:** TRvlvr+Politrees
- **Weight:** `MGM_MAIN_v4.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (12.4), vocals (6.2)

### VR Arch Single Model v5: 10_SP-UVR-2B-32000-1

- **Source:** TRvlvr+Politrees
- **Weight:** `10_SP-UVR-2B-32000-1.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.3), vocals (7.5)

### VR Arch Single Model v5: 11_SP-UVR-2B-32000-2

- **Source:** TRvlvr+Politrees
- **Weight:** `11_SP-UVR-2B-32000-2.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.8), vocals (7.3)

### VR Arch Single Model v5: 12_SP-UVR-3B-44100

- **Source:** TRvlvr+Politrees
- **Weight:** `12_SP-UVR-3B-44100.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.1), vocals (7.5)

### VR Arch Single Model v5: 13_SP-UVR-4B-44100-1

- **Source:** TRvlvr+Politrees
- **Weight:** `13_SP-UVR-4B-44100-1.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.3), vocals (7.8)

### VR Arch Single Model v5: 14_SP-UVR-4B-44100-2

- **Source:** TRvlvr+Politrees
- **Weight:** `14_SP-UVR-4B-44100-2.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** politrees_vr_hash
- **Note:** Community ref: instrumental* (13.5), vocals (8.0)

### VR Arch Single Model v5: 15_SP-UVR-MID-44100-1

- **Source:** TRvlvr+Politrees
- **Weight:** `15_SP-UVR-MID-44100-1.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.1), vocals (7.5)

### VR Arch Single Model v5: 16_SP-UVR-MID-44100-2

- **Source:** TRvlvr+Politrees
- **Weight:** `16_SP-UVR-MID-44100-2.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** politrees_vr_hash
- **Note:** Community ref: instrumental* (13.3), vocals (7.4)

### VR Arch Single Model v5: 17_HP-Wind_Inst-UVR

- **Source:** TRvlvr+Politrees
- **Weight:** `17_HP-Wind_Inst-UVR.pth`
- **Name intent:** instrumental
- **Backend focus:** unknown
- **Primary stem (backend):** `no woodwinds`
- **Best result:** instrumental
- **Metadata:** community_models.txt
- **Note:** Community ref: no woodwinds*, woodwinds

### VR Arch Single Model v5: 1_HP-UVR

- **Source:** TRvlvr+Politrees
- **Weight:** `1_HP-UVR.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.7), vocals (7.9)

### VR Arch Single Model v5: 2_HP-UVR

- **Source:** TRvlvr+Politrees
- **Weight:** `2_HP-UVR.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.5), vocals (8.2)

### VR Arch Single Model v5: 3_HP-Vocal-UVR

- **Source:** TRvlvr+Politrees
- **Weight:** `3_HP-Vocal-UVR.pth`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (8.2), instrumental (14.0)

### VR Arch Single Model v5: 4_HP-Vocal-UVR

- **Source:** TRvlvr+Politrees
- **Weight:** `4_HP-Vocal-UVR.pth`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (8.3), instrumental (13.6)

### VR Arch Single Model v5: 5_HP-Karaoke-UVR

- **Source:** TRvlvr+Politrees
- **Weight:** `5_HP-Karaoke-UVR.pth`
- **Name intent:** karaoke
- **Backend focus:** karaoke_instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Karaoke model:** yes
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** politrees_vr_hash
- **Note:** Community ref: instrumental* (12.2), vocals (5.2)

### VR Arch Single Model v5: 6_HP-Karaoke-UVR

- **Source:** TRvlvr+Politrees
- **Weight:** `6_HP-Karaoke-UVR.pth`
- **Name intent:** karaoke
- **Backend focus:** karaoke_instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Karaoke model:** yes
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** politrees_vr_hash
- **Note:** Community ref: instrumental* (13.0), vocals (4.6)

### VR Arch Single Model v5: 7_HP2-UVR

- **Source:** TRvlvr+Politrees
- **Weight:** `7_HP2-UVR.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.5), vocals (8.3)

### VR Arch Single Model v5: 8_HP2-UVR

- **Source:** TRvlvr+Politrees
- **Weight:** `8_HP2-UVR.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (13.5), vocals (8.2)

### VR Arch Single Model v5: 9_HP2-UVR

- **Source:** TRvlvr+Politrees
- **Weight:** `9_HP2-UVR.pth`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** politrees_vr_hash
- **Note:** Community ref: instrumental* (13.7), vocals (8.0)

### VR Arch Single Model v5: UVR-BVE-4B_SN-44100-1

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-BVE-4B_SN-44100-1.pth`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (0.0), instrumental (7.7)

### VR Arch Single Model v5: UVR-De-Echo-Aggressive by FoxJoy

- **Source:** TRvlvr
- **Weight:** `UVR-De-Echo-Aggressive.pth`
- **Name intent:** special_fx
- **Backend focus:** unknown
- **Primary stem (backend):** `no echo`
- **Best result:** special_fx
- **Metadata:** community_models.txt
- **Note:** Community ref: no echo*, echo

### VR Arch Single Model v5: UVR-De-Echo-Normal by FoxJoy

- **Source:** TRvlvr
- **Weight:** `UVR-De-Echo-Normal.pth`
- **Name intent:** special_fx
- **Backend focus:** unknown
- **Primary stem (backend):** `no echo`
- **Best result:** special_fx
- **Metadata:** community_models.txt
- **Note:** Community ref: no echo*, echo

### VR Arch Single Model v5: UVR-DeEcho-Aggressive by FoxJoy

- **Source:** Politrees
- **Weight:** `UVR-De-Echo-Aggressive.pth`
- **Name intent:** special_fx
- **Backend focus:** unknown
- **Primary stem (backend):** `no echo`
- **Best result:** special_fx
- **Metadata:** community_models.txt
- **Note:** Community ref: no echo*, echo

### VR Arch Single Model v5: UVR-DeEcho-DeReverb by FoxJoy

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-DeEcho-DeReverb.pth`
- **Name intent:** special_fx
- **Backend focus:** unknown
- **Primary stem (backend):** `no reverb`
- **Best result:** special_fx
- **Metadata:** politrees_vr_hash
- **Note:** Community ref: no reverb*, reverb

### VR Arch Single Model v5: UVR-DeEcho-Normal by FoxJoy

- **Source:** Politrees
- **Weight:** `UVR-De-Echo-Normal.pth`
- **Name intent:** special_fx
- **Backend focus:** unknown
- **Primary stem (backend):** `no echo`
- **Best result:** special_fx
- **Metadata:** community_models.txt
- **Note:** Community ref: no echo*, echo

### VR Arch Single Model v5: UVR-DeNoise by FoxJoy

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-DeNoise.pth`
- **Name intent:** special_fx
- **Backend focus:** unknown
- **Primary stem (backend):** `noise`
- **Best result:** special_fx
- **Metadata:** politrees_vr_hash
- **Note:** Community ref: noise*, no noise

### VR Arch Single Model v5: UVR-DeNoise-Lite by FoxJoy

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-DeNoise-Lite.pth`
- **Name intent:** special_fx
- **Backend focus:** unknown
- **Primary stem (backend):** `noise`
- **Best result:** special_fx
- **Metadata:** politrees_vr_hash
- **Note:** Community ref: noise*, no noise

### VR Arch Single Model v5: UVR-DeReverb by aufr33 & jarredou

- **Source:** Politrees
- **Weight:** `UVR-De-Reverb-aufr33-jarredou.pth`
- **Name intent:** special_fx
- **Backend focus:** unknown
- **Primary stem (backend):** `dry`
- **Best result:** special_fx
- **Metadata:** community_models.txt
- **Note:** Community ref: dry*, no dry

## Bandit (detail)

### Bandit Plus: Cinematic Bandit Plus by kwatcharasupat

- **Source:** Politrees
- **Weight:** `model_bandit_plus_dnr_sdr_11.47.ckpt`
- **Config:** `config_dnr_bandit_bsrnn_multi_mus64.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `Speech`
- **Instruments:** Speech, Music, Effects
- **Best result:** Multi-stem: Speech, Music, Effects
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:config_dnr_bandit_bsrnn_multi_mus64.yaml

### Bandit v2: Cinematic Bandit v2 Multilang by kwatcharasupat

- **Source:** Politrees
- **Weight:** `checkpoint-multi_fixed.ckpt`
- **Config:** `config_dnr_bandit_v2_mus64.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `Speech`
- **Instruments:** Speech, Music, Sfx
- **Best result:** Multi-stem: Speech, Music, Sfx
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:config_dnr_bandit_v2_mus64.yaml

## MDX-Net ONNX (detail)

### MDX-Net Model: Kim Inst

- **Source:** TRvlvr+Politrees
- **Weight:** `Kim_Inst.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.5), vocals (9.1)

### MDX-Net Model: Kim Vocal 1

- **Source:** TRvlvr+Politrees
- **Weight:** `Kim_Vocal_1.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (10.1), instrumental (15.5)

### MDX-Net Model: Kim Vocal 2

- **Source:** TRvlvr+Politrees
- **Weight:** `Kim_Vocal_2.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (10.2), instrumental (15.4)

### MDX-Net Model: Reverb HQ By FoxJoy

- **Source:** TRvlvr+Politrees
- **Weight:** `Reverb_HQ_By_FoxJoy.onnx`
- **Name intent:** special_fx
- **Backend focus:** unknown
- **Primary stem (backend):** `reverb`
- **Best result:** special_fx
- **Metadata:** community_models.txt
- **Note:** Community ref: reverb*, no reverb

### MDX-Net Model: UVR-MDX-NET 1

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_1_9703.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.6), instrumental (15.0)

### MDX-Net Model: UVR-MDX-NET 2

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_2_9682.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.4), instrumental (15.0)

### MDX-Net Model: UVR-MDX-NET 3

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_3_9662.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.7), instrumental (15.0)

### MDX-Net Model: UVR-MDX-NET Crowd HQ 1 By Aufr33

- **Source:** Politrees
- **Weight:** `UVR-MDX-NET_Crowd_HQ_1.onnx`
- **Name intent:** instrumental
- **Backend focus:** unknown
- **Primary stem (backend):** `no crowd`
- **Best result:** instrumental
- **Metadata:** community_models.txt
- **Note:** Community ref: no crowd*, crowd

### MDX-Net Model: UVR-MDX-NET Inst 1

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_1.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.2), vocals (9.2)

### MDX-Net Model: UVR-MDX-NET Inst 2

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_2.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.3), vocals (9.2)

### MDX-Net Model: UVR-MDX-NET Inst 3

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_3.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.3), vocals (9.2)

### MDX-Net Model: UVR-MDX-NET Inst HQ 1

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_HQ_1.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.4), vocals (8.8)

### MDX-Net Model: UVR-MDX-NET Inst HQ 2

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_HQ_2.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.3), vocals (8.8)

### MDX-Net Model: UVR-MDX-NET Inst HQ 3

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_HQ_3.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.4), vocals (8.8)

### MDX-Net Model: UVR-MDX-NET Inst HQ 4

- **Source:** Politrees
- **Weight:** `UVR-MDX-NET-Inst_HQ_4.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** politrees_mdx_hash
- **Note:** Community ref: instrumental* (15.5), vocals (8.8)

### MDX-Net Model: UVR-MDX-NET Inst HQ 5

- **Source:** Politrees
- **Weight:** `UVR-MDX-NET-Inst_HQ_5.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** politrees_mdx_hash
- **Note:** Community ref: instrumental* (15.3), vocals (8.7)

### MDX-Net Model: UVR-MDX-NET Inst Main

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Inst_Main.onnx`
- **Name intent:** instrumental
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (15.1), vocals (8.5)

### MDX-Net Model: UVR-MDX-NET Karaoke

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_KARA.onnx`
- **Name intent:** karaoke
- **Backend focus:** karaoke_vocal_primary
- **Primary stem (backend):** `Vocals`
- **Karaoke model:** yes
- **Best result:** Karaoke vocals (Vocals primary; complement = instrumental backing)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** politrees_mdx_hash
- **Note:** Community ref: vocals* (5.6), instrumental (14.1)

### MDX-Net Model: UVR-MDX-NET Karaoke 2

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_KARA_2.onnx`
- **Name intent:** karaoke
- **Backend focus:** instrumental_primary
- **Primary stem (backend):** `Instrumental`
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: instrumental* (14.8), vocals (5.4)

### MDX-Net Model: UVR-MDX-NET Main

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_Main.onnx`
- **Name intent:** dual_voc_inst
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals or Instrumental — both are first-class 2-stem exports
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** community_models.txt
- **Note:** Both Vocals and Instrumental are first-class exports
- **Note:** Community ref: vocals* (10.2), instrumental (15.4)

### MDX-Net Model: UVR-MDX-NET Voc FT

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR-MDX-NET-Voc_FT.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (10.2), instrumental (15.4)

### MDX-Net Model: UVR_MDXNET_9482

- **Source:** TRvlvr+Politrees
- **Weight:** `UVR_MDXNET_9482.onnx`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.3), instrumental (14.9)

### MDX-Net Model: kuielab_a_bass

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_a_bass.onnx`
- **Name intent:** multi_stem
- **Backend focus:** unknown
- **Primary stem (backend):** `bass`
- **Best result:** multi_stem
- **Metadata:** community_models.txt
- **Note:** Community ref: bass* (10.4), no bass

### MDX-Net Model: kuielab_a_drums

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_a_drums.onnx`
- **Name intent:** multi_stem
- **Backend focus:** unknown
- **Primary stem (backend):** `drums`
- **Best result:** multi_stem
- **Metadata:** community_models.txt
- **Note:** Community ref: drums* (7.0), no drums

### MDX-Net Model: kuielab_a_other

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_a_other.onnx`
- **Name intent:** multi_stem
- **Backend focus:** unknown
- **Primary stem (backend):** `other`
- **Best result:** multi_stem
- **Metadata:** community_models.txt
- **Note:** Community ref: other*, no other

### MDX-Net Model: kuielab_a_vocals

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_a_vocals.onnx`
- **Name intent:** multi_stem
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.6), instrumental (15.3)

### MDX-Net Model: kuielab_b_bass

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_b_bass.onnx`
- **Name intent:** multi_stem
- **Backend focus:** unknown
- **Primary stem (backend):** `bass`
- **Best result:** multi_stem
- **Metadata:** community_models.txt
- **Note:** Community ref: bass* (9.9), no bass

### MDX-Net Model: kuielab_b_drums

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_b_drums.onnx`
- **Name intent:** multi_stem
- **Backend focus:** unknown
- **Primary stem (backend):** `drums`
- **Best result:** multi_stem
- **Metadata:** community_models.txt
- **Note:** Community ref: drums* (7.1), no drums

### MDX-Net Model: kuielab_b_other

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_b_other.onnx`
- **Name intent:** multi_stem
- **Backend focus:** unknown
- **Primary stem (backend):** `other`
- **Best result:** multi_stem
- **Metadata:** community_models.txt
- **Note:** Community ref: other*, no other

### MDX-Net Model: kuielab_b_vocals

- **Source:** TRvlvr+Politrees
- **Weight:** `kuielab_b_vocals.onnx`
- **Name intent:** multi_stem
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals* (9.0), instrumental (15.1)

## MDX23C (detail)

### MDX23 Model: MDX23C_D1581

- **Source:** TRvlvr
- **Weight:** `MDX23C_D1581.ckpt`
- **Name intent:** vocals
- **Backend focus:** vocal_primary
- **Primary stem (backend):** `Vocals`
- **Best result:** Vocals (+ Instrumental complement)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** community_models.txt
- **Note:** Community ref: vocals (10.0), instrumental (15.5)

### MDX23C Model: MDX23C DeReverb by aufr33 & jarredou

- **Source:** Politrees
- **Weight:** `MDX23C-De-Reverb-aufr33-jarredou.ckpt`
- **Config:** `config_dereverb_mdx23c.yaml`
- **Name intent:** special_fx
- **Backend focus:** two_stem
- **Primary stem (backend):** `dry`
- **Instruments:** dry, No dry
- **Best result:** dry, No dry
- **Metadata:** remote_yaml:config_dereverb_mdx23c.yaml
- **Note:** Community ref: dry, no dry

### MDX23C Model: MDX23C DrumSep by aufr33 & jarredou

- **Source:** Politrees
- **Weight:** `MDX23C-DrumSep-aufr33-jarredou.ckpt`
- **Config:** `config_drumsep_mdx23c.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `kick`
- **Instruments:** kick, snare, toms, hh, ride, crash
- **Best result:** Multi-stem: kick, snare, toms, hh, ride, crash
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** remote_yaml:config_drumsep_mdx23c.yaml
- **Note:** Community ref: kick, snare, toms, hh, ride, crash

### MDX23C Model: MDX23C InstVoc HQ

- **Source:** Politrees
- **Weight:** `MDX23C-8KFFT-InstVoc_HQ.ckpt`
- **Config:** `model_2_stem_full_band_8k.yaml`
- **Name intent:** dual_voc_inst
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** bundled_yaml:model_2_stem_full_band_8k.yaml
- **Note:** Community ref: vocals (10.6), instrumental (15.8)

### MDX23C Model: MDX23C Phantom Centre extraction by wesleyr36

- **Source:** Politrees
- **Weight:** `model_mdx23c_ep_271_l1_freq_72.2383.ckpt`
- **Config:** `config_mdx23c_similarity.yaml`
- **Name intent:** vocals
- **Backend focus:** single_target:Similarity
- **Primary stem (backend):** `Similarity`
- **Instruments:** Similarity, Difference
- **Target instrument:** `Similarity`
- **Best result:** Similarity (single native output)
- **Metadata:** remote_yaml:config_mdx23c_similarity.yaml

## Roformer (detail)

### BandSplit Roformer | 4-stems FT by SYH99999

- **Source:** Politrees
- **Weight:** `BandSplit_Roformer_4stems_FT_by_SYH99999.pth`
- **Config:** `config_BandSplit_Roformer_4stems_FT_by_SYH99999.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** remote_yaml:config_BandSplit_Roformer_4stems_FT_by_SYH99999.yaml

### BandSplit Roformer | Chorus Male-Female by Sucial

- **Source:** Politrees
- **Weight:** `model_chorus_bs_roformer_ep_267_sdr_24.1275.ckpt`
- **Config:** `config_bs_roformer_chorus_male_female.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** two_stem
- **Primary stem (backend):** `male`
- **Instruments:** male, female
- **Best result:** male, female
- **Metadata:** remote_yaml:config_bs_roformer_chorus_male_female.yaml
- **Note:** Community ref: male, female

### BandSplit Roformer | Dereverb by anvuew

- **Source:** Politrees
- **Weight:** `deverb_bs_roformer_8_384dim_10depth.ckpt`
- **Config:** `config_bs_roformer_deverb_8_384dim_10depth.yaml`
- **Architecture:** BS Roformer
- **Name intent:** special_fx
- **Backend focus:** single_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** noreverb (single native output)
- **Metadata:** remote_yaml:config_bs_roformer_deverb_8_384dim_10depth.yaml
- **Note:** Community ref: noreverb*, reverb

### BandSplit Roformer | FNO by Unwa

- **Source:** Politrees
- **Weight:** `model_BandSplit-Roformer_FNO_by-Unwa.ckpt`
- **Config:** `config_BandSplit-Roformer_FNO_by-Unwa.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_BandSplit-Roformer_FNO_by-Unwa.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### BandSplit Roformer | Inst-EXP-Value-Residual by Unwa

- **Source:** Politrees
- **Weight:** `BS_Inst_EXP_VRL.ckpt`
- **Config:** `config_bs_roformer_inst_exp_vrl.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_bs_roformer_inst_exp_vrl.yaml

### BandSplit Roformer | Karaoke Frazer by becruily

- **Source:** Politrees
- **Weight:** `model_BandSplit-Roformer_Karaoke_Frazer_by-becruily.ckpt`
- **Config:** `config_BandSplit-Roformer_Karaoke_Frazer_by-becruily.yaml`
- **Architecture:** BS Roformer
- **Name intent:** karaoke
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_BandSplit-Roformer_Karaoke_Frazer_by-becruily.yaml

### BandSplit Roformer | Male-Female by aufr33

- **Source:** Politrees
- **Weight:** `bs_roformer_male_female_by_aufr33_sdr_7.2889.ckpt`
- **Config:** `config_bs_roformer_chorus_male_female.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** two_stem
- **Primary stem (backend):** `male`
- **Instruments:** male, female
- **Best result:** male, female
- **Metadata:** remote_yaml:config_bs_roformer_chorus_male_female.yaml

### BandSplit Roformer | Resurrection Instrumental by Unwa

- **Source:** Politrees
- **Weight:** `model_BandSplit-Roformer_Resurrection_Instrumental_by-Unwa.ckpt`
- **Config:** `config_BandSplit-Roformer_Resurrection_Instrumental_by-Unwa.yaml`
- **Architecture:** BS Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_BandSplit-Roformer_Resurrection_Instrumental_by-Unwa.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### BandSplit Roformer | Resurrection Vocals by Unwa

- **Source:** Politrees
- **Weight:** `model_BandSplit-Roformer_Resurrection_Vocals_by-Unwa.ckpt`
- **Config:** `config_BandSplit-Roformer_Resurrection_Vocals_by-Unwa.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_BandSplit-Roformer_Resurrection_Vocals_by-Unwa.yaml

### BandSplit Roformer | Revive by Unwa

- **Source:** Politrees
- **Weight:** `bs_roformer_revive_by_unwa.ckpt`
- **Config:** `config_bs_roformer_revive_by_unwa.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_bs_roformer_revive_by_unwa.yaml

### BandSplit Roformer | Revive v2 by Unwa

- **Source:** Politrees
- **Weight:** `bs_roformer_revive_v2_by_unwa.ckpt`
- **Config:** `config_bs_roformer_revive_by_unwa.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_bs_roformer_revive_by_unwa.yaml

### BandSplit Roformer | Revive v3 by Unwa

- **Source:** Politrees
- **Weight:** `bs_roformer_revive_v3_by_unwa.ckpt`
- **Config:** `config_bs_roformer_revive_by_unwa.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_bs_roformer_revive_by_unwa.yaml

### BandSplit Roformer | SDR 1053 by Viperx

- **Source:** Politrees
- **Weight:** `model_bs_roformer_ep_937_sdr_10.5309.ckpt`
- **Config:** `config_bs_roformer_ep_937_sdr_10.5309.yaml`
- **Architecture:** BS Roformer
- **Name intent:** drum_bass_sep
- **Backend focus:** drum_bass_target
- **Primary stem (backend):** `no drum-bass`
- **Instruments:** No Drum-Bass, Drum-Bass
- **Target instrument:** `No Drum-Bass`
- **Best result:** No Drum-Bass (drum/bass separation; complement = Drum-Bass)
- **Save stems UI:** UI: No Drum-Bass / Drum-Bass subset
- **Metadata:** remote_yaml:config_bs_roformer_ep_937_sdr_10.5309.yaml
- **Note:** Community ref: no drum-bass*, drum-bass

### BandSplit Roformer | SDR 1296 by Viperx

- **Source:** Politrees
- **Weight:** `model_bs_roformer_ep_368_sdr_12.9628.ckpt`
- **Config:** `config_bs_roformer_ep_368_sdr_12.9628.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_bs_roformer_ep_368_sdr_12.9628.yaml
- **Note:** Community ref: vocals* (12.1), instrumental (16.3)

### BandSplit Roformer | SDR 1297 by Viperx

- **Source:** Politrees
- **Weight:** `model_bs_roformer_ep_317_sdr_12.9755.ckpt`
- **Config:** `config_bs_roformer_ep_317_sdr_12.9755.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_bs_roformer_ep_317_sdr_12.9755.yaml
- **Note:** Community ref: vocals* (11.8), instrumental (16.5)

### BandSplit Roformer | SW by jarredou

- **Source:** Politrees
- **Weight:** `model_BandSplit-Roformer_SW_by-jarredou.ckpt`
- **Config:** `config_BandSplit-Roformer_SW_by-jarredou.yaml`
- **Architecture:** BS Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `bass`
- **Instruments:** bass, drums, other, vocals, guitar, piano
- **Best result:** Multi-stem: bass, drums, other, vocals, guitar, piano
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** remote_yaml:config_BandSplit-Roformer_SW_by-jarredou.yaml
- **Note:** Intent inferred from metadata (multi_stem)

### BandSplit Roformer | Vocals by Gabox

- **Source:** Politrees
- **Weight:** `bs_roformer_voc_gabox.ckpt`
- **Config:** `config_bs_roformer_voc_gabox.yaml`
- **Architecture:** BS Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_bs_roformer_voc_gabox.yaml

### MelBand Roformer Kim | Big Beta v4 FT by Unwa

- **Source:** Politrees
- **Weight:** `melband_roformer_big_beta4.ckpt`
- **Config:** `config_melband_roformer_big_beta4.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_big_beta4.yaml
- **Note:** Community ref: vocals* (12.5), other

### MelBand Roformer Kim | Big Beta v5e FT by Unwa

- **Source:** Politrees
- **Weight:** `melband_roformer_big_beta5e.ckpt`
- **Config:** `config_melband_roformer_big_beta5e.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_big_beta5e.yaml
- **Note:** Community ref: vocals* (12.4), other

### MelBand Roformer Kim | Big Beta v6 FT by Unwa

- **Source:** Politrees
- **Weight:** `melband_roformer_big_beta6.ckpt`
- **Config:** `config_melband_roformer_big_beta6.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_big_beta6.yaml

### MelBand Roformer Kim | Big Beta v6x FT by Unwa

- **Source:** Politrees
- **Weight:** `melband_roformer_big_beta6x.ckpt`
- **Config:** `config_melband_roformer_big_beta6x.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_big_beta6x.yaml

### MelBand Roformer Kim | Big SYHFT v1 by SYH99999

- **Source:** Politrees
- **Weight:** `MelBandRoformerBigSYHFTV1.ckpt`
- **Config:** `config_melband_roformer_vocals_big_v1_ft.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_big_v1_ft.yaml
- **Note:** Community ref: vocals* (12.3), other

### MelBand Roformer Kim | FT by Unwa

- **Source:** Politrees
- **Weight:** `mel_band_roformer_kim_ft_unwa.ckpt`
- **Config:** `config_melband_roformer_kim_ft_unwa.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:config_melband_roformer_kim_ft_unwa.yaml
- **Note:** Community ref: vocals* (12.4), other

### MelBand Roformer Kim | FT v2 Bleedless by Unwa

- **Source:** Politrees
- **Weight:** `mel_band_roformer_kim_ft2_bleedless_unwa.ckpt`
- **Config:** `config_melband_roformer_kim_ft_unwa.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:config_melband_roformer_kim_ft_unwa.yaml

### MelBand Roformer Kim | FT v2 by Unwa

- **Source:** Politrees
- **Weight:** `mel_band_roformer_kim_ft2_unwa.ckpt`
- **Config:** `config_melband_roformer_kim_ft_unwa.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:config_melband_roformer_kim_ft_unwa.yaml

### MelBand Roformer Kim | Inst v1 by Unwa

- **Source:** Politrees
- **Weight:** `melband_roformer_inst_v1.ckpt`
- **Config:** `config_melband_roformer_inst.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `Instrumental`
- **Instruments:** other, vocals
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** politrees_mdx_hash
- **Note:** Community ref: instrumental* (15.9), vocals (9.8)
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### MelBand Roformer Kim | Inst v1e Plus by Unwa

- **Source:** Politrees
- **Weight:** `melband_roformer_inst_v1e_plus.ckpt`
- **Config:** `config_melband_roformer_inst.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** other, vocals
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:config_melband_roformer_inst.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### MelBand Roformer Kim | Inst v1e by Unwa

- **Source:** Politrees
- **Weight:** `melband_roformer_inst_v1e.ckpt`
- **Config:** `config_melband_roformer_inst.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `Instrumental`
- **Instruments:** other, vocals
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** bundled_yaml:config_melband_roformer_inst.yaml
- **Note:** Community ref: instrumental* (15.8), vocals (9.6)
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

### MelBand Roformer Kim | Inst v2 by Unwa

- **Source:** Politrees
- **Weight:** `melband_roformer_inst_v2.ckpt`
- **Config:** `config_melband_roformer_inst_v2.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_v2.yaml
- **Note:** Community ref: instrumental* (16.1), vocals (10.3)

### MelBand Roformer Kim | InstVoc Duality v1 by Unwa

- **Source:** Politrees
- **Weight:** `melband_roformer_instvoc_duality_v1.ckpt`
- **Config:** `config_melband_roformer_instvoc_duality.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** remote_yaml:config_melband_roformer_instvoc_duality.yaml
- **Note:** Community ref: vocals (11.0), instrumental (16.1)

### MelBand Roformer Kim | InstVoc Duality v2 by Unwa

- **Source:** Politrees
- **Weight:** `melband_roformer_instvoc_duality_v2.ckpt`
- **Config:** `config_melband_roformer_instvoc_duality.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** remote_yaml:config_melband_roformer_instvoc_duality.yaml

### MelBand Roformer Kim | SYHFT by SYH99999

- **Source:** Politrees
- **Weight:** `MelBandRoformerSYHFT.ckpt`
- **Config:** `config_melband_roformer_vocals_ft.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_ft.yaml
- **Note:** Community ref: vocals* (8.0), other

### MelBand Roformer Kim | SYHFT v2 by SYH99999

- **Source:** Politrees
- **Weight:** `MelBandRoformerSYHFTV2.ckpt`
- **Config:** `config_melband_roformer_vocals_ft.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_ft.yaml
- **Note:** Community ref: vocals* (8.6), other

### MelBand Roformer Kim | SYHFT v2.5 by SYH99999

- **Source:** Politrees
- **Weight:** `MelBandRoformerSYHFTV2.5.ckpt`
- **Config:** `config_melband_roformer_vocals_ft.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_ft.yaml
- **Note:** Community ref: vocals* (8.5), other

### MelBand Roformer Kim | SYHFT v3 by SYH99999

- **Source:** Politrees
- **Weight:** `MelBandRoformerSYHFTV3Epsilon.ckpt`
- **Config:** `config_melband_roformer_vocals_ft.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_ft.yaml
- **Note:** Community ref: vocals* (9.5), other

### MelBand Roformer Kim | Vocals Fullness v1 by Aname

- **Source:** Politrees
- **Weight:** `melband_roformer_kim_vocals_fullness_v1_by_aname.ckpt`
- **Config:** `config_melband_roformer_vocals_fullness_aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer Kim | Vocals Fullness v2 by Aname

- **Source:** Politrees
- **Weight:** `melband_roformer_kim_vocals_fullness_v2_by_aname.ckpt`
- **Config:** `config_melband_roformer_vocals_fullness_aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer Kim | Vocals v1 by Aname

- **Source:** Politrees
- **Weight:** `melband_roformer_kim_vocals_v1_by_aname.ckpt`
- **Config:** `config_melband_roformer_vocals_fullness_aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer Kim | Vocals v2 by Aname

- **Source:** Politrees
- **Weight:** `melband_roformer_kim_vocals_v2_by_aname.ckpt`
- **Config:** `config_melband_roformer_vocals_fullness_aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer Kim | Vocals v3 by Aname

- **Source:** Politrees
- **Weight:** `melband_roformer_kim_vocals_v3_by_aname.ckpt`
- **Config:** `config_melband_roformer_vocals_fullness_aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer | 4-stems FT Large v1 by SYH99999

- **Source:** Politrees
- **Weight:** `MelBand_Roformer_4stems_FT_Large_v1_by_SYH99999.ckpt`
- **Config:** `config_MelBand_Roformer_4stems_FT_Large_by_SYH99999.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** remote_yaml:config_MelBand_Roformer_4stems_FT_Large_by_SYH99999.yaml

### MelBand Roformer | 4-stems FT Large v2 by SYH99999

- **Source:** Politrees
- **Weight:** `MelBand_Roformer_4stems_FT_Large_v2_by_SYH99999.ckpt`
- **Config:** `config_MelBand_Roformer_4stems_FT_Large_by_SYH99999.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** remote_yaml:config_MelBand_Roformer_4stems_FT_Large_by_SYH99999.yaml

### MelBand Roformer | 4-stems Large v1 by Aname

- **Source:** Politrees
- **Weight:** `MelBand_Roformer_4stems_Large_v1_by_Aname.ckpt`
- **Config:** `config_MelBand_Roformer_4stems_Large_v1_by_Aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** remote_yaml:config_MelBand_Roformer_4stems_Large_v1_by_Aname.yaml

### MelBand Roformer | 4-stems XL v1 by Aname

- **Source:** Politrees
- **Weight:** `MelBand_Roformer_4stems_XL_v1_by_Aname.ckpt`
- **Config:** `config_MelBand_Roformer_4stems_XL_v1_by_Aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `drums`
- **Instruments:** drums, bass, other, vocals
- **Best result:** Multi-stem: drums, bass, other, vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** remote_yaml:config_MelBand_Roformer_4stems_XL_v1_by_Aname.yaml

### MelBand Roformer | Aspiration Less Aggressive by Sucial

- **Source:** Politrees
- **Weight:** `aspiration_mel_band_roformer_less_aggr_sdr_18.1201.ckpt`
- **Config:** `config_melband_roformer_aspiration.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** two_stem
- **Primary stem (backend):** `aspiration`
- **Instruments:** aspiration, other
- **Best result:** aspiration, other
- **Metadata:** remote_yaml:config_melband_roformer_aspiration.yaml
- **Note:** Community ref: aspiration, other

### MelBand Roformer | Aspiration by Sucial

- **Source:** Politrees
- **Weight:** `aspiration_mel_band_roformer_sdr_18.9845.ckpt`
- **Config:** `config_melband_roformer_aspiration.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** two_stem
- **Primary stem (backend):** `aspiration`
- **Instruments:** aspiration, other
- **Best result:** aspiration, other
- **Metadata:** remote_yaml:config_melband_roformer_aspiration.yaml
- **Note:** Community ref: aspiration, other

### MelBand Roformer | BVE by Gonza

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_BVE_by-Gonza.ckpt`
- **Config:** `config_MelBand-Roformer_BVE_by-Gonza.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** single_target:Lead
- **Primary stem (backend):** `Lead`
- **Instruments:** Lead, Back
- **Target instrument:** `Lead`
- **Best result:** Lead (single native output)
- **Metadata:** remote_yaml:config_MelBand-Roformer_BVE_by-Gonza.yaml

### MelBand Roformer | Bleed Suppressor v1 by Unwa & 97chris

- **Source:** Politrees
- **Weight:** `mel_band_roformer_bleed_suppressor_v1.ckpt`
- **Config:** `config_melband_roformer_bleed_suppressor_v1.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Bleed
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_bleed_suppressor_v1.yaml
- **Note:** Community ref: instrumental*, bleed

### MelBand Roformer | Crowd by Aufr33 & Viperx

- **Source:** Politrees
- **Weight:** `mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144.ckpt`
- **Config:** `config_melband_roformer_crowd_aufr33_viperx_sdr_8.7144.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** single_target:crowd
- **Primary stem (backend):** `crowd`
- **Instruments:** crowd, other
- **Target instrument:** `crowd`
- **Best result:** crowd (single native output)
- **Metadata:** remote_yaml:config_melband_roformer_crowd_aufr33_viperx_sdr_8.7144.yaml
- **Note:** Community ref: crowd*, other

### MelBand Roformer | DeReverb Big by Sucial

- **Source:** Politrees
- **Weight:** `dereverb_big_mbr_ep_362.ckpt`
- **Config:** `config_melband_roformer_dereverb_echo_v2.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** single_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** dry (single native output)
- **Metadata:** remote_yaml:config_melband_roformer_dereverb_echo_v2.yaml

### MelBand Roformer | DeReverb Less Aggressive by anvuew

- **Source:** Politrees
- **Weight:** `dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050.ckpt`
- **Config:** `config_melband_roformer_dereverb_anvuew.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** single_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** noreverb (single native output)
- **Metadata:** remote_yaml:config_melband_roformer_dereverb_anvuew.yaml
- **Note:** Community ref: noreverb*, reverb

### MelBand Roformer | DeReverb Mono by anvuew

- **Source:** Politrees
- **Weight:** `dereverb_mel_band_roformer_mono_anvuew_sdr_20.4029.ckpt`
- **Config:** `config_melband_roformer_dereverb_anvuew.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** single_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** noreverb (single native output)
- **Metadata:** remote_yaml:config_melband_roformer_dereverb_anvuew.yaml

### MelBand Roformer | DeReverb Super Big by Sucial

- **Source:** Politrees
- **Weight:** `dereverb_super_big_mbr_ep_346.ckpt`
- **Config:** `config_melband_roformer_dereverb_echo_v2.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** single_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** dry (single native output)
- **Metadata:** remote_yaml:config_melband_roformer_dereverb_echo_v2.yaml

### MelBand Roformer | DeReverb by anvuew

- **Source:** Politrees
- **Weight:** `dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt`
- **Config:** `config_melband_roformer_dereverb_anvuew.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** single_target:noreverb
- **Primary stem (backend):** `noreverb`
- **Instruments:** noreverb, reverb
- **Target instrument:** `noreverb`
- **Best result:** noreverb (single native output)
- **Metadata:** remote_yaml:config_melband_roformer_dereverb_anvuew.yaml
- **Note:** Community ref: noreverb*, reverb

### MelBand Roformer | DeReverb-Echo Fused by Sucial

- **Source:** Politrees
- **Weight:** `dereverb_echo_mbr_fused.ckpt`
- **Config:** `config_melband_roformer_dereverb_echo_v2.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** single_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** dry (single native output)
- **Metadata:** remote_yaml:config_melband_roformer_dereverb_echo_v2.yaml

### MelBand Roformer | DeReverb-Echo by Sucial

- **Source:** Politrees
- **Weight:** `dereverb-echo_mel_band_roformer_sdr_10.0169.ckpt`
- **Config:** `config_melband_roformer_dereverb-echo.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** two_stem
- **Primary stem (backend):** `dry`
- **Instruments:** dry, No dry
- **Best result:** dry, No dry
- **Metadata:** remote_yaml:config_melband_roformer_dereverb-echo.yaml
- **Note:** Community ref: dry, no dry

### MelBand Roformer | DeReverb-Echo v2 by Sucial

- **Source:** Politrees
- **Weight:** `dereverb-echo_mel_band_roformer_sdr_13.4843_v2.ckpt`
- **Config:** `config_melband_roformer_dereverb-echo_sdr_13.4843_v2.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** single_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, No dry
- **Target instrument:** `dry`
- **Best result:** dry (single native output)
- **Metadata:** remote_yaml:config_melband_roformer_dereverb-echo_sdr_13.4843_v2.yaml
- **Note:** Community ref: dry*, no dry

### MelBand Roformer | Denoise Aggr by Aufr33

- **Source:** Politrees
- **Weight:** `denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768.ckpt`
- **Config:** `config_melband_roformer_denoise_aufr33_aggr_sdr_27.9768.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** single_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** dry (single native output)
- **Metadata:** remote_yaml:config_melband_roformer_denoise_aufr33_aggr_sdr_27.9768.yaml
- **Note:** Community ref: dry*, other

### MelBand Roformer | Denoise by Aufr33

- **Source:** Politrees
- **Weight:** `denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt`
- **Config:** `config_melband_roformer_denoise_aufr33_sdr_27.9959.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** single_target:dry
- **Primary stem (backend):** `dry`
- **Instruments:** dry, other
- **Target instrument:** `dry`
- **Best result:** dry (single native output)
- **Metadata:** remote_yaml:config_melband_roformer_denoise_aufr33_sdr_27.9959.yaml
- **Note:** Community ref: dry*, other

### MelBand Roformer | Duality v1 by Aname

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_Duality_v1_by-Aname.ckpt`
- **Config:** `config_MelBand-Roformer_Duality_v1_by-Aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_MelBand-Roformer_Duality_v1_by-Aname.yaml

### MelBand Roformer | Guitar by becruily

- **Source:** Politrees
- **Weight:** `melband_roformer_guitar_becruily.ckpt`
- **Config:** `config_melband_roformer_guitar_becruily.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** single_target:Guitar
- **Primary stem (backend):** `Guitar`
- **Instruments:** Guitar, Other
- **Target instrument:** `Guitar`
- **Best result:** Guitar (single native output)
- **Metadata:** remote_yaml:config_melband_roformer_guitar_becruily.yaml

### MelBand Roformer | Instrumental Bleedless v1 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_bleedless_v1_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Bleedless v2 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_bleedless_v2_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental DeNoise-DeBleed by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_denoise_debleed_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness v1 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v1_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness v2 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v2_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness v3 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v3_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness v4 Noise by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v4_noise_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness v5 Noise by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v5_noise_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness v5 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v5_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness v6 Noise by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v6_noise_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness v6 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v6_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness v7 Noise by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v7_noise_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness v7 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v7_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness v8 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_v8_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental Fullness vX by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_fullness_vX_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** dual_voc_inst
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** User picks Vocals or Instrumental (dual 2-stem)
- **Save stems UI:** UI: Vocals / Instrumental (either stem is a valid primary export)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_instrumental_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental by becruily

- **Source:** Politrees
- **Weight:** `mel_band_roformer_instrumental_becruily.ckpt`
- **Config:** `config_melband_roformer_instrumental_becruily.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_instrumental_becruily.yaml

### MelBand Roformer | Instrumental v1 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_v1_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental v2 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_v2_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Instrumental v3 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_inst_v3_gabox.ckpt`
- **Config:** `config_melband_roformer_inst_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Target instrument:** `Instrumental`
- **Best result:** Instrumental (complement = Vocals)
- **Save stems UI:** UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)
- **Metadata:** remote_yaml:config_melband_roformer_inst_gabox.yaml

### MelBand Roformer | Karaoke Fusion Aggressive by Gonza

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_Karaoke_Fusion_Aggressive_by-Gonza.ckpt`
- **Config:** `config_MelBand-Roformer_Karaoke_Fusion_by-Gonza.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_MelBand-Roformer_Karaoke_Fusion_by-Gonza.yaml

### MelBand Roformer | Karaoke Fusion Aggressive v2 by Gonza

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_Karaoke_Fusion_Aggressive_v2_by-Gonza.ckpt`
- **Config:** `config_MelBand-Roformer_Karaoke_Fusion_v2_by-Gonza.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_MelBand-Roformer_Karaoke_Fusion_v2_by-Gonza.yaml

### MelBand Roformer | Karaoke Fusion Standard by Gonza

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_Karaoke_Fusion_Standard_by-Gonza.ckpt`
- **Config:** `config_MelBand-Roformer_Karaoke_Fusion_by-Gonza.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** bundled_yaml:config_MelBand-Roformer_Karaoke_Fusion_by-Gonza.yaml

### MelBand Roformer | Karaoke Fusion Total by Gonza

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_Karaoke_Fusion_Total_by-Gonza.ckpt`
- **Config:** `config_MelBand-Roformer_Karaoke_Fusion_Total_by-Gonza.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_MelBand-Roformer_Karaoke_Fusion_Total_by-Gonza.yaml

### MelBand Roformer | Karaoke by Aufr33 & Viperx

- **Source:** Politrees
- **Weight:** `mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt`
- **Config:** `config_melband_roformer_karaoke_aufr33_viperx_sdr_10.1956.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_melband_roformer_karaoke_aufr33_viperx_sdr_10.1956.yaml
- **Note:** Community ref: vocals* (8.4), instrumental (14.7)

### MelBand Roformer | Karaoke by Gabox

- **Source:** Politrees
- **Weight:** `model_MelBand-Roformer_Karaoke_by-Gabox.ckpt`
- **Config:** `config_MelBand-Roformer_Karaoke_by-Gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_MelBand-Roformer_Karaoke_by-Gabox.yaml

### MelBand Roformer | Karaoke by Gabox (beta)

- **Source:** Politrees
- **Weight:** `mel_band_roformer_karaoke_gabox.ckpt`
- **Config:** `config_melband_roformer_voc_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer | Karaoke by becruily

- **Source:** Politrees
- **Weight:** `melband_roformer_karaoke_becruily.ckpt`
- **Config:** `config_melband_roformer_karaoke_becruily.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** karaoke
- **Backend focus:** two_stem
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Best result:** Karaoke backing (Instrumental primary; complement = lead vocals)
- **Save stems UI:** UI: Vocals / complement
- **Metadata:** remote_yaml:config_melband_roformer_karaoke_becruily.yaml

### MelBand Roformer | SDR 1143 by Viperx

- **Source:** Politrees
- **Weight:** `model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt`
- **Config:** `config_melband_roformer_ep_3005_sdr_11.4360.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** politrees_mdx_hash
- **Note:** Community ref: vocals* (10.5), instrumental (15.1)

### MelBand Roformer | Small by Aname

- **Source:** Politrees
- **Weight:** `melband_roformer_small_by_aname.ckpt`
- **Config:** `config_melband_roformer_small_by_aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** two_stem
- **Primary stem (backend):** `Instrumental`
- **Instruments:** Instrumental, Vocals
- **Best result:** Instrumental (+ Vocals complement)
- **Save stems UI:** UI: Instrumental / complement
- **Metadata:** remote_yaml:config_melband_roformer_small_by_aname.yaml
- **Note:** Intent inferred from metadata (instrumental)

### MelBand Roformer | Vocals Bleedless by Aname

- **Source:** Politrees
- **Weight:** `melband_roformer_vocals_bleedness_by_aname.ckpt`
- **Config:** `config_melband_roformer_vocals_test_by_aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** special_fx
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, instruments
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_melband_roformer_vocals_test_by_aname.yaml

### MelBand Roformer | Vocals Fullness by Aname

- **Source:** Politrees
- **Weight:** `mel_band_roformer_vocals_fullness_aname.ckpt`
- **Config:** `config_melband_roformer_vocals_fullness_aname.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_fullness_aname.yaml

### MelBand Roformer | Vocals Fullness v1 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_voc_fullness_v1_gabox.ckpt`
- **Config:** `config_melband_roformer_voc_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer | Vocals Fullness v2 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_voc_fullness_v2_gabox.ckpt`
- **Config:** `config_melband_roformer_voc_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer | Vocals Fullness v3 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_voc_fullness_v3_gabox.ckpt`
- **Config:** `config_melband_roformer_voc_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer | Vocals Fullness v4 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_voc_fullness_v4_gabox.ckpt`
- **Config:** `config_melband_roformer_voc_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer | Vocals Fullness v5 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_voc_fullness_v5_gabox.ckpt`
- **Config:** `config_melband_roformer_voc_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer | Vocals Fullness v6 by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_voc_fullness_v6_gabox.ckpt`
- **Config:** `config_melband_roformer_voc_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer | Vocals by Gabox

- **Source:** Politrees
- **Weight:** `mel_band_roformer_voc_gabox.ckpt`
- **Config:** `config_melband_roformer_voc_gabox.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** Vocals, Instrumental
- **Target instrument:** `Vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental
- **Metadata:** remote_yaml:config_melband_roformer_voc_gabox.yaml

### MelBand Roformer | Vocals by Kimberley Jensen

- **Source:** Politrees
- **Weight:** `vocals_mel_band_roformer.ckpt`
- **Config:** `config_melband_roformer_vocals_kim.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `Vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_kim.yaml
- **Note:** Community ref: vocals* (12.6), other

### MelBand Roformer | Vocals by becruily

- **Source:** Politrees
- **Weight:** `mel_band_roformer_vocals_becruily.ckpt`
- **Config:** `config_melband_roformer_vocals_becruily.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** vocals
- **Backend focus:** vocal_target
- **Primary stem (backend):** `vocals`
- **Instruments:** vocals, other
- **Target instrument:** `vocals`
- **Best result:** Vocals (complement = Instrumental)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_vocals_becruily.yaml

### MelBand Roformer | instrumental Metal preview by Mesk

- **Source:** Politrees
- **Weight:** `melband_roformer_inst_metal_prev_by_mesk.ckpt`
- **Config:** `config_melband_roformer_inst_metal_prev_by_mesk.yaml`
- **Architecture:** Mel-Band Roformer
- **Name intent:** instrumental
- **Backend focus:** instrumental_target_other_yaml
- **Primary stem (backend):** `other`
- **Instruments:** vocals, other
- **Target instrument:** `other`
- **Best result:** Instrumental (yaml `other`; complement = vocals)
- **Save stems UI:** UI: Vocals / Instrumental (yaml `other` is the backing track)
- **Metadata:** remote_yaml:config_melband_roformer_inst_metal_prev_by_mesk.yaml
- **Note:** Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)

## SCNet (detail)

### 4-stems SCNet Large

- **Source:** Politrees
- **Weight:** `model_scnet_sdr_9.3244.ckpt`
- **Config:** `config_musdb18_scnet_large.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `Drums`
- **Instruments:** Drums, Bass, Other, Vocals
- **Best result:** Multi-stem: Drums, Bass, Other, Vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:config_musdb18_scnet_large.yaml

### 4-stems SCNet Large by starrytong

- **Source:** Politrees
- **Weight:** `SCNet-large_starrytong_fixed.ckpt`
- **Config:** `config_musdb18_scnet_large_starrytong.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `Drums`
- **Instruments:** Drums, Bass, Other, Vocals
- **Best result:** Multi-stem: Drums, Bass, Other, Vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:config_musdb18_scnet_large_starrytong.yaml

### 4-stems SCNet MUSDB18 by starrytong

- **Source:** Politrees
- **Weight:** `scnet_checkpoint_musdb18.ckpt`
- **Config:** `config_musdb18_scnet.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `Drums`
- **Instruments:** Drums, Bass, Other, Vocals
- **Best result:** Multi-stem: Drums, Bass, Other, Vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** politrees_mdx_hash

### 4-stems SCNet XL

- **Source:** Politrees
- **Weight:** `model_scnet_ep_54_sdr_9.8051.ckpt`
- **Config:** `config_musdb18_scnet_xl.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Primary stem (backend):** `Drums`
- **Instruments:** Drums, Bass, Other, Vocals
- **Best result:** Multi-stem: Drums, Bass, Other, Vocals
- **Save stems UI:** UI: per-stem subset or focus row
- **Metadata:** bundled_yaml:config_musdb18_scnet_xl.yaml

## Demucs (detail)

### Demucs v1: demucs

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v1: demucs_extra

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs_extra.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v1: light

- **Source:** TRvlvr+Politrees
- **Weight:** `light.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v1: light_extra

- **Source:** TRvlvr+Politrees
- **Weight:** `light_extra.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v1: tasnet

- **Source:** TRvlvr+Politrees
- **Weight:** `tasnet.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v1: tasnet_extra

- **Source:** TRvlvr+Politrees
- **Weight:** `tasnet_extra.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v2: demucs

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs-e07c671f.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v2: demucs48_hq

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs48_hq-28a1282c.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v2: demucs_extra

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs_extra-3646af93.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v2: demucs_unittest

- **Source:** TRvlvr+Politrees
- **Weight:** `demucs_unittest-09ebc15f.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v2: tasnet

- **Source:** TRvlvr+Politrees
- **Weight:** `tasnet-beb46fac.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v2: tasnet_extra

- **Source:** TRvlvr+Politrees
- **Weight:** `tasnet_extra-df3777b2.th`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v3: UVR Model

- **Source:** TRvlvr+Politrees
- **Weight:** `ebf34a2db.th`
- **Config:** `UVR_Demucs_Model_1.yaml`
- **Name intent:** dual_voc_inst
- **Backend focus:** multi_stem
- **Instruments:** instrumental, vocals
- **Best result:** 2-stem: instrumental + vocals (user picks focus)
- **Metadata:** demucs_heuristic

### Demucs v3: mdx

- **Source:** TRvlvr+Politrees
- **Weight:** `7d865c68-3d5dd56b.th`
- **Config:** `mdx.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v3: mdx_extra

- **Source:** TRvlvr+Politrees
- **Weight:** `cfa93e08-61801ae1.th`
- **Config:** `mdx_extra.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v3: mdx_extra_q

- **Source:** TRvlvr+Politrees
- **Weight:** `7fd6ef75-a905dd85.th`
- **Config:** `mdx_extra_q.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v3: mdx_q

- **Source:** TRvlvr+Politrees
- **Weight:** `305bc58f-18378783.th`
- **Config:** `mdx_q.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v3: repro_mdx_a

- **Source:** TRvlvr+Politrees
- **Weight:** `902315c2-b39ce9c9.th`
- **Config:** `repro_mdx_a.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v3: repro_mdx_a_hybrid_only

- **Source:** TRvlvr+Politrees
- **Weight:** `902315c2-b39ce9c9.th`
- **Config:** `repro_mdx_a_hybrid_only.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v3: repro_mdx_a_time_only

- **Source:** TRvlvr+Politrees
- **Weight:** `1ef250f1-592467ce.th`
- **Config:** `repro_mdx_a_time_only.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v4: hdemucs_mmi

- **Source:** TRvlvr+Politrees
- **Weight:** `75fc33f5-1941ce65.th`
- **Config:** `hdemucs_mmi.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v4: htdemucs

- **Source:** TRvlvr+Politrees
- **Weight:** `955717e8-8726e21a.th`
- **Config:** `htdemucs.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v4: htdemucs_6s

- **Source:** TRvlvr+Politrees
- **Weight:** `5c90dfd2-34c22ccb.th`
- **Config:** `htdemucs_6s.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals, guitar, piano
- **Best result:** 6-stem Demucs
- **Metadata:** demucs_heuristic

### Demucs v4: htdemucs_ft

- **Source:** TRvlvr+Politrees
- **Weight:** `04573f0d-f3cf25b2.th`
- **Config:** `htdemucs_ft.yaml`
- **Name intent:** multi_stem
- **Backend focus:** multi_stem
- **Instruments:** drums, bass, other, vocals
- **Best result:** 4-stem Demucs
- **Metadata:** demucs_heuristic
